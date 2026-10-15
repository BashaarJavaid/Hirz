"""Authenticated companion HTTP ceremonies, confined to disposable scenario databases."""

from typing import Any

import httpx
from webauthn.helpers import base64url_to_bytes

from hirz.api.app import create_app
from hirz.companion import auth
from hirz.companion.api import Companion
from hirz.constitution.schema import dump
from hirz.graph.models import now
from hirz.pipeline.service import Pipeline
from hirz.twin.authenticator import CONFIG, Authenticator
from hirz.twin.scenario import LoadedScenario


class Phone:
    def __init__(self, p: Pipeline, loaded: LoadedScenario):
        if not str(p.connection.engine.url.database).startswith("hirz_ha_smoke_"):
            raise ValueError("Software phone requires a disposable scenario database")
        self.p, self.loaded = p, loaded
        self.service = Companion(
            p.connection.engine, p.audit, CONFIG, demo_world=loaded.world
        )
        self.app = create_app(companion=self.service)
        self.clients: dict[str, tuple[httpx.AsyncClient, Authenticator]] = {}

    async def post(
        self, member: str, path: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        client, _ = self.clients[member]
        result = await client.post("/api/" + path, json=body)
        if result.status_code != 200:
            raise ValueError(
                f"Companion {path} refused ({result.status_code}): {result.text}"
            )
        return dict(result.json())

    async def approvals(self, member: str) -> dict[str, Any]:
        await self.enroll(member)
        response = await self.clients[member][0].get("/api/approvals")
        response.raise_for_status()
        return dict(response.json())

    async def enroll(self, member: str) -> None:
        if member in self.clients:
            return
        invitation = await auth.initial_invitation(
            self.p, self.loaded.ref("members", member), at=now()
        )
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url=CONFIG.origin,
            headers={"origin": CONFIG.origin},
        )
        self.clients[member] = client, Authenticator()
        result = await client.get("/api/auth/session")
        result.raise_for_status()
        answer = await self.ceremony(
            member, {"operation": "enroll", "token": invitation}
        )
        client.headers["x-hirz-csrf"] = answer["csrf"]

    async def ceremony(self, member: str, binding: dict[str, Any]) -> dict[str, Any]:
        options = await self.post(member, "auth/begin", binding)
        _, key = self.clients[member]
        credential = key.response(
            base64url_to_bytes(options["publicKey"]["challenge"]),
            register=binding["operation"] == "enroll",
        )
        return await self.post(
            member, "auth/finish", {"id": options["id"], "credential": credential}
        )

    async def activate(
        self, member: str, candidate: str, proposal: str | None = None
    ) -> dict[str, Any]:
        await self.enroll(member)
        body = {"yaml": candidate}
        if proposal:
            body["proposal_id"] = proposal
        draft = await self.post(member, "constitution/draft", body)
        await self.post(member, "constitution/review", {"id": draft["id"]})
        result = await self.ceremony(
            member,
            {
                "operation": "activate",
                "draft_id": draft["id"],
                "candidate_hash": draft["candidate_hash"],
            },
        )
        return {
            "version": int(result["version"]),
            "authenticated": True,
            "engine": "dogwood-local",
            "review": draft["review"],
        }

    async def initialize(self) -> dict[str, Any]:
        owner = next(
            name
            for name, ident in self.loaded.references["members"].items()
            if self.loaded.world.members[ident].role == "owner"
        )
        return await self.activate(owner, dump(self.p.bundle.policy()))

    async def close(self) -> None:
        for client, _ in self.clients.values():
            await client.aclose()
