"""Bounded scalar forms over SDK elicitation; no transaction survives a prompt."""

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hirz.mcp.runtime import HouseholdRuntime

from pydantic import ValidationError

from hirz.mcp.auth import identity_context
from hirz.mcp.contracts import REVISION_VALUES, TOOLS, Result, input_schema, response
from hirz.pipeline.confirmation import RequesterReview, Review, review_context


def fields(
    name: str, arguments: dict[str, Any], *, clarification: bool = False
) -> dict[str, Any]:
    schema = input_schema(TOOLS[name][0])
    required = set(schema.get("required", ())) - arguments.keys()
    action = arguments.get("action")
    if (
        name == "revise_household_plan"
        and arguments.get("change")
        and arguments.get("operation") != "remove"
    ):
        required.update(
            REVISION_VALUES.get(arguments["change"], {"at"}) - arguments.keys()
        )
    if (
        name == "verify_trusted_identity"
        and arguments.get("operation") == "start"
        and not arguments.get("case_id")
    ):
        required.update({"contact", "text"} - arguments.keys())
    if name == "approve_action":
        for reference, dependent in (
            ("plan_id", "version"),
            ("action_id", "approval_id"),
        ):
            if arguments.get(reference) and not arguments.get(dependent):
                required.add(dependent)
    required.update(
        {
            "charge_car": {"percent", "minutes"},
            "set_temperature": {"temperature_f"},
            "request_door_unlock": {"minutes"},
            "apply_profile": {"profile"},
        }.get(str(action), set())
        - arguments.keys()
    )
    properties = {}
    for key, raw in schema["properties"].items():
        if key in {
            "request_id",
            "claimed_requester",
            "claimed_author",
            "presented_number",
        }:
            continue
        if not clarification and key not in required:
            continue
        value = dict(raw)
        if "anyOf" in value:
            value = next(v for v in value["anyOf"] if v.get("type") != "null") | {
                "description": raw["description"]
            }
        if "$ref" in value:
            value = schema["$defs"][value["$ref"].rsplit("/", 1)[1]] | {
                "description": raw["description"]
            }
        if value.get("type") not in {"string", "number", "integer", "boolean"}:
            continue
        value = {
            k: v
            for k, v in value.items()
            if k
            in {
                "type",
                "description",
                "enum",
                "minimum",
                "maximum",
                "minLength",
                "maxLength",
            }
        }
        value["title"] = key.replace("_", " ").capitalize()
        if arguments.get(key) is not None:
            value["default"] = arguments[key]
        properties[key] = value
    return {
        "type": "object",
        "properties": properties,
        "required": sorted(required & properties.keys()),
    }


async def call(
    server: Any, runtime: "HouseholdRuntime", name: str, arguments: dict[str, Any]
) -> Result:
    ctx = server._mcp_server.request_context
    request = ctx.request
    # Stateful SDK tasks inherit initialization contextvars. Never use those as identity.
    identity = request.scope.get("hirz_identity") if request is not None else None
    token = identity_context.set(identity)
    try:
        capabilities = (
            ctx.session.client_params.capabilities
            if ctx.session.client_params
            else None
        )
        supported = bool(
            capabilities
            and capabilities.elicitation
            and capabilities.elicitation.form is not None
        )
        review = Review()
        review_token = review_context.set(review if supported else None)
        pending = fields(name, arguments)
        for _ in range(16):
            if not pending["properties"]:
                try:
                    result = await runtime.call(name, arguments)
                except RequesterReview as required:
                    # The call has returned through all connection/transaction contexts.
                    async with asyncio.timeout(300):
                        answer = await ctx.session.elicit_form(
                            "The household rules require your confirmation of this exact request: "
                            + name.replace("_", " ")
                            + ". "
                            + "; ".join(
                                f"{k.replace('_', ' ')}: {v}"
                                for k, v in arguments.items()
                                if not k.endswith("_id")
                                and not k.startswith("claimed_")
                                and v is not None
                            ),
                            {
                                "type": "object",
                                "properties": {
                                    "confirmed": {
                                        "type": "boolean",
                                        "title": "I confirm this request",
                                    }
                                },
                                "required": ["confirmed"],
                            },
                            related_request_id=ctx.request_id,
                        )
                    if answer.action != "accept" or answer.content != {
                        "confirmed": True
                    }:
                        return response(
                            "Requester confirmation was not given. No further action was submitted.",
                            status="clarification",
                            code="PROMPT_DECLINED",
                        )
                    identity_context.set(await request.scope["hirz_reauthorize"]())
                    review.accepted.add(required.binding)
                    continue
                except ValidationError as invalid:
                    if not supported:
                        raise
                    # A backend/output validation failure is not a missing
                    # caller value and must never prompt for unrelated fields.
                    try:
                        TOOLS[name][0].model_validate(arguments)
                    except ValidationError:
                        pass
                    else:
                        raise invalid
                    pending = fields(name, arguments, clarification=True)
                    bad = {
                        str(error["loc"][0])
                        for error in invalid.errors()
                        if error["loc"]
                    }
                    pending["properties"] = {
                        k: v for k, v in pending["properties"].items() if k in bad
                    }
                    pending["required"] = list(pending["properties"])
                    message = "Please supply valid values for this request."
                else:
                    if result.data.status != "clarification" or not supported:
                        return result
                    pending = fields(name, arguments, clarification=True)
                    field = (result.data.code or "").removeprefix("CLARIFY_").lower()
                    if field in pending["properties"]:
                        pending["required"] = [field]
                    message = " ".join(
                        (
                            result.speakable.headline,
                            *result.speakable.details,
                            *result.speakable.options,
                        )
                    )
            else:
                message = "Please supply the missing details for this request."
            if not supported or not pending["properties"]:
                return response(message, status="clarification", code="CLARIFY")
            # One scalar per question keeps Dot usable without a form/card.
            choices = pending.get("required") or [
                {
                    "execute_household_action": "profile"
                    if arguments.get("action") == "apply_profile"
                    else "room",
                    "evaluate_permission": "room",
                    "revise_household_plan": "applies_to",
                    "verify_trusted_identity": "contact",
                    "get_household_context": "member",
                    "approve_action": "plan_id",
                }.get(name, next(iter(pending["properties"])))
            ]
            key = next(
                (k for k in choices if k in pending["properties"]),
                next(iter(pending["properties"])),
            )
            pending = {
                "type": "object",
                "properties": {key: pending["properties"][key]},
                "required": [key],
            }
            message += " " + pending["properties"][key]["title"] + "?"
            try:
                async with asyncio.timeout(300):
                    reply = await ctx.session.elicit_form(
                        message, pending, related_request_id=ctx.request_id
                    )
            except TimeoutError:
                return response(
                    "That question expired. Please make the request again.",
                    status="clarification",
                    code="PROMPT_EXPIRED",
                )
            if reply.action != "accept":
                return response(
                    "The question was declined or cancelled. No further request was submitted.",
                    status="clarification",
                    code="PROMPT_DECLINED",
                )
            values = reply.content
            if (
                not isinstance(values, dict)
                or values.keys() - pending["properties"].keys()
            ):
                raise ValueError("Invalid elicitation reply")
            from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

            Draft202012Validator(pending).validate(values)
            identity_context.set(await request.scope["hirz_reauthorize"]())
            arguments = arguments | values
            pending = fields(name, arguments)
            if not pending["properties"]:
                TOOLS[name][0].model_validate(arguments)
        return response(
            "Please try again with the complete request.",
            status="clarification",
            code="CLARIFY",
        )
    except TimeoutError:
        return response(
            "That question expired. Please make the request again.",
            status="clarification",
            code="PROMPT_EXPIRED",
        )
    finally:
        if "review_token" in locals():
            review_context.reset(review_token)
        identity_context.reset(token)
