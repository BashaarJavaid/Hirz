"""Explicit synthetic bootstrap exception; no policy activation or audit fabrication."""

from collections.abc import Callable
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
import yaml
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncConnection
from yaml.nodes import MappingNode

from hirz import db
from hirz.graph.models import MODELS, GraphError, Model, now, utc
from hirz.graph.repository import GraphRepository, row_model, row_values


class UniqueLoader(yaml.SafeLoader):
    def construct_mapping(
        self, node: MappingNode, deep: bool = False
    ) -> dict[Any, Any]:
        self.flatten_mapping(node)
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise GraphError("Duplicate YAML key.")
            seen.add(key)
        return super().construct_mapping(node, deep)


def demo_id(household: str, kind: str, slug: str) -> UUID:
    if not isinstance(slug, str) or not slug.strip():
        raise GraphError("Demo entity references must be nonempty strings.")
    return uuid5(NAMESPACE_URL, f"hirz:demo:{household}:{kind}:{slug}")


REFERENCE_KINDS = {
    "member_id": "members",
    "owner_member_id": "members",
    "contact_id": "trusted_contacts",
    "asset_id": "assets",
    "zone_id": "assets",
    "schedule_id": "schedules",
}


class Seed:
    def __init__(self, graph: dict[str, Any], constitution: dict[str, Any]):
        self.graph = graph
        self.constitution = constitution
        if set(graph) - ({"household"} | (set(MODELS) - {"households"})):
            raise GraphError("Unknown graph seed field.")
        home = graph["household"]
        if not isinstance(home, dict):
            raise GraphError("Seed household must be a mapping.")
        if {"id", "constitution_version"} & home.keys():
            raise GraphError(
                "Seed household identity/version come from its slug and constitution."
            )
        self.slug = home["slug"]
        if self.slug not in {"quinn-home", "quinn-parents"}:
            raise GraphError(
                "Only the two synthetic demo households may be bootstrapped."
            )
        if constitution.get("household") != self.slug:
            raise GraphError("Graph and constitution households differ.")
        version = constitution.get("version")
        if type(version) is not int or version <= 0:
            raise GraphError("A positive constitution version is required.")
        self.version = version
        self.household_id = demo_id(self.slug, "households", self.slug)
        self.yaml = yaml.safe_dump(constitution, sort_keys=True)
        self.hash = sha256(self.yaml.encode()).hexdigest()

    def models(self, at: datetime) -> dict[str, list[Model]]:
        at = utc(at)
        home = {k: v for k, v in self.graph["household"].items() if k != "slug"}
        result: dict[str, list[Model]] = {
            "households": [
                MODELS["households"].model_validate(
                    home
                    | {"id": self.household_id, "constitution_version": self.version}
                )
            ]
        }
        for name in MODELS:
            if name == "households":
                continue
            result[name] = []
            rows = self.graph.get(name, [])
            if not isinstance(rows, list):
                raise GraphError("Seed entities must be lists.")
            for row in rows:
                values = dict(row)
                if "household_id" in values:
                    raise GraphError(
                        "Seed rows inherit their household; do not supply household_id."
                    )
                if name == "member_accounts":
                    if values.get("provider") != "demo":
                        raise GraphError("Seed accounts must use the demo provider.")
                else:
                    values["id"] = demo_id(self.slug, name, values["id"])
                for key, kind in REFERENCE_KINDS.items():
                    if values.get(key) is not None:
                        values[key] = demo_id(self.slug, kind, values[key])
                if name == "asset_bindings" and values.get("adapter") != "twin":
                    raise GraphError("Bootstrap asset bindings must be twin.")
                if name == "contact_channels":
                    if values.get("source") != "twin":
                        raise GraphError(
                            "Bootstrap channel verification must be simulated."
                        )
                    values["verified_at"] = at
                if name in {"observations", "constraints"}:
                    raise GraphError(
                        "Initial observations belong to scenarios; constraints require audited intake."
                    )
                values["household_id"] = self.household_id
                result[name].append(MODELS[name].model_validate(values))
        # Validate references before any database write, including the full seed batch.
        ids = {
            name: {getattr(m, "id", None) for m in models}
            for name, models in result.items()
        }
        for name, models in result.items():
            keys = [
                tuple(
                    row_values(name, m)[c.name]
                    for c in db.GRAPH_TABLES[name].primary_key
                )
                for m in models
            ]
            if len(keys) != len(set(keys)):
                raise GraphError("Duplicate seed entity.")
            for model in models:
                for key, kind in REFERENCE_KINDS.items():
                    value = getattr(model, key, None)
                    if value is not None and value not in ids[kind]:
                        raise GraphError(
                            "Seed reference does not exist in this household."
                        )
        return result


def read_seed(path: Path) -> Seed:
    try:
        documents = list(yaml.load_all(path.read_text(), Loader=UniqueLoader))
        if len(documents) != 2 or any(not isinstance(doc, dict) for doc in documents):
            raise GraphError(
                "A seed requires exactly two YAML mappings: graph and constitution."
            )
        seed = Seed(documents[0], documents[1])
        seed.models(now())
        return seed
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        yaml.YAMLError,
        ValidationError,
    ) as exc:
        if isinstance(exc, GraphError):
            raise
        raise GraphError(
            "Invalid demo seed; check its graph fields and YAML structure."
        ) from None


async def untouched(connection: AsyncConnection, seed: Seed, at: datetime) -> bool:
    expected = seed.models(at)
    for name, table in db.GRAPH_TABLES.items():
        scope = "id" if name == "households" else "household_id"
        rows = (
            (
                await connection.execute(
                    sa.select(table).where(table.c[scope] == seed.household_id)
                )
            )
            .mappings()
            .all()
        )
        actual = [row_model(name, dict(row)).model_dump(mode="json") for row in rows]
        wanted = [m.model_dump(mode="json") for m in expected[name]]
        if any(row["valid_from"] != at for row in rows) or sorted(
            actual, key=str
        ) != sorted(wanted, key=str):
            return False
        history = db.HISTORY_TABLES[name]
        if await connection.scalar(
            sa.select(sa.exists().where(history.c[scope] == seed.household_id))
        ):
            return False
    if await connection.scalar(
        sa.select(sa.exists().where(db.audit_log.c.household_id == seed.household_id))
    ):
        return False
    versions = (
        (
            await connection.execute(
                sa.select(db.constitution_versions).where(
                    db.constitution_versions.c.household_id == seed.household_id
                )
            )
        )
        .mappings()
        .all()
    )
    return len(versions) == 1 and (
        versions[0]["version"] == seed.version
        and versions[0]["hash"] == seed.hash
        and versions[0]["yaml"] == seed.yaml
        and versions[0]["status"] == "unvalidated"
        and versions[0]["activated_at"] is None
        and versions[0]["compiled_cedar"] is None
        and versions[0]["analysis_report"] is None
    )


async def load_seeds(
    connection: AsyncConnection, seeds: list[Seed], clock: Callable[[], datetime] = now
) -> list[dict[str, Any]]:
    if not seeds or len({s.household_id for s in seeds}) != len(seeds):
        raise GraphError("Supply each demo household once.")
    results = []
    # One transaction and refresh for the entire input batch, including both homes.
    repository = GraphRepository(connection, seeds[0].household_id)
    async with repository.write(clock):
        await connection.run_sync(db.require_current)
        assert repository._at is not None
        at = repository._at
        for seed in seeds:
            models = seed.models(at)
            repository.household_id = seed.household_id
            existing = await repository.get("households", {})
            status = "loaded"
            if existing is not None:
                if not await untouched(connection, seed, existing["valid_from"]):
                    raise GraphError(
                        "Existing household differs or has evolved; bootstrap refuses to reset it."
                    )
                status = "unchanged"
            else:
                for name, entities in models.items():
                    for entity in entities:
                        await repository.put(name, entity)
                await connection.execute(
                    db.constitution_versions.insert().values(
                        household_id=seed.household_id,
                        version=seed.version,
                        yaml=seed.yaml,
                        hash=seed.hash,
                    )
                )
            results.append(
                {
                    "household": seed.slug,
                    "household_id": str(seed.household_id),
                    "status": status,
                    "constitution_version": seed.version,
                    "policy_status": "unvalidated",
                    "members": len(models["members"]),
                    "assets": len(models["assets"]),
                }
            )
    return results
