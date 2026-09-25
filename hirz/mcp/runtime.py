"""Local household services; native policy compilation happens only at startup."""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from hashlib import sha256
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from mcp import types
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirz import db
from hirz.constitution.boundary import Dogwood
from hirz.constitution.schema import loads
from hirz.graph.models import now
from hirz.mcp.auth import identity_context
from hirz.mcp.contracts import (
    OUTPUTS,
    TOOLS,
    Result,
    input_schema,
    output_schema,
    response,
)
from hirz.mcp.household import HouseholdTools
from hirz.mcp.presentation import Annualized
from hirz.mcp.profiles import Profiles
from hirz.mcp.server import HirzMCP
from hirz.pipeline.audit import AuditWriter
from hirz.pipeline.service import Pipeline, PolicyBundle

log = logging.getLogger(__name__)


class HouseholdRuntime:
    def __init__(
        self,
        engine: AsyncEngine,
        audit: AuditWriter,
        *,
        clock: Callable[..., Any] = now,
        profiles: Profiles | None = None,
        card_evidence: dict[UUID, Annualized] | None = None,
    ):
        self.engine, self.audit, self.clock = engine, audit, clock
        self.profiles = profiles or Profiles()
        self.card_evidence = card_evidence or {}
        self.boundary = Dogwood()
        self.bundles: dict[UUID, tuple[PolicyBundle, str]] = {}

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        async with self.boundary.persistent():
            async with self._policies():
                yield

    @asynccontextmanager
    async def _policies(self) -> AsyncIterator[None]:
        async with self.engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        sa.select(db.constitution_versions).join(
                            db.households,
                            sa.and_(
                                db.households.c.id
                                == db.constitution_versions.c.household_id,
                                db.households.c.constitution_version
                                == db.constitution_versions.c.version,
                            ),
                        )
                    )
                )
                .mappings()
                .all()
            )
        for row in rows:
            if sha256(row["yaml"].encode()).hexdigest() != row["hash"]:
                raise ValueError("Stored policy integrity check failed")
            bundle = await PolicyBundle.validate(
                row["household_id"], loads(row["yaml"]), self.boundary
            )
            self.bundles[row["household_id"]] = bundle, row["hash"]
        try:
            yield
        finally:
            self.bundles.clear()

    async def call(self, name: str, arguments: dict[str, Any]) -> Result:
        identity = identity_context.get()
        if name == "what_can_you_do":
            TOOLS[name][0].model_validate(arguments)
            return response(
                "Hirz helps with household rules, energy plans, device requests and suspicious-request checks.",
                details=(
                    "This preview uses simulated contact checks. Rule proposals do not activate rules.",
                ),
                available_tools=tuple(TOOLS) if identity else ("what_can_you_do",),
            )
        if identity is None:
            raise ValueError("Link your account to use household tools.")
        cached = self.bundles.get(identity.household_id)
        if cached is None:
            raise ValueError(
                "Household policy is unavailable. Restart after configuring its local policy."
            )
        bundle, fingerprint = cached
        async with self.engine.connect() as connection:
            return await HouseholdTools(
                Pipeline(connection, bundle, self.boundary, self.audit, self.clock),
                identity.principal,
                policy_hash=fingerprint,
                profiles=self.profiles.households.get(identity.household_id, {}),
                card_evidence=self.card_evidence.get(identity.household_id),
            ).call(name, arguments)


def register(server: HirzMCP, runtime: HouseholdRuntime) -> None:
    from hirz.mcp.cards import TOOLS as CARD_TOOLS
    from hirz.mcp.cards import register as register_cards

    if not server.authentication:
        raise ValueError("Household tools require OAuth")
    register_cards(server)
    for name, (_, scope, _) in TOOLS.items():
        if scope:
            server.tool_scopes[name] = "hirz:" + scope

    @server._mcp_server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=name,
                description=description,
                inputSchema=input_schema(schema),
                outputSchema=output_schema(OUTPUTS[name]),
                _meta={"ui": {"resourceUri": f"ui://hirz/{CARD_TOOLS[name]}"}}
                if name in CARD_TOOLS
                else None,
                annotations=types.ToolAnnotations(
                    readOnlyHint=name
                    in {
                        "what_can_you_do",
                        "get_household_context",
                        "explain_plan",
                        "get_action_audit",
                    },
                    destructiveHint=False,
                    openWorldHint=False,
                ),
            )
            for name, (schema, _, description) in TOOLS.items()
        ]

    @server._mcp_server.call_tool(validate_input=False)  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        error = False
        try:
            if name not in TOOLS:
                raise ValueError("Choose an available household tool.")
            result = await runtime.call(name, arguments)
        except ValidationError:
            result = response(
                "Please check the request's fields and supply the required values.",
                status="failed",
                code="INVALID_INPUT",
            )
            error = True
        except ValueError as exc:
            # Never echo arbitrary values or SQL from validation/backend exceptions.
            code = (
                "REQUEST_CONFLICT"
                if str(exc).startswith("REQUEST_CONFLICT:")
                else "REQUEST_REFUSED"
            )
            result = response(
                "That request could not be accepted. Check its references and try again.",
                status="failed",
                code=code,
            )
            error = True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error(
                "household_tool_failed tool=%s error=%s", name, type(exc).__name__
            )
            result = response(
                "Household tools are temporarily unavailable. Please try again later.",
                status="failed",
                code="UNAVAILABLE",
            )
            error = True
        output_model = OUTPUTS.get(name, Result)
        try:
            output = output_model.model_validate(
                result.model_dump(exclude_unset=True, exclude_defaults=True)
            )
        except ValidationError as exc:
            log.error(
                "household_tool_failed tool=%s error=%s", name, type(exc).__name__
            )
            result = response(
                "Household tools are temporarily unavailable. Please try again later.",
                status="failed",
                code="UNAVAILABLE",
            )
            error = True
            output = output_model.model_validate(
                result.model_dump(exclude_unset=True, exclude_defaults=True)
            )
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text", text=output.model_dump_json(by_alias=True)
                )
            ],
            structuredContent=output.model_dump(mode="json", by_alias=True),
            isError=error,
        )
