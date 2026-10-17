import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from hirz.aws.schedules import name, reconcile


class Connection:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None

    @asynccontextmanager
    async def begin(self):
        yield

    async def execute(self, statement):
        self.statement = statement
        return Mock(all=lambda: self.rows)


def test_projection_repairs_missing_removes_obsolete_and_updates(monkeypatch):
    async def run():
        at = datetime.now(UTC)
        home = uuid4()
        key = name(home, "a")
        stored = {"action-obsolete": {}}
        calls = []

        async def call(sdk, method, **values):
            calls.append(method)
            selected = values.get("Name")
            if method == "list_schedules":
                return {"Schedules": [{"Name": k} for k in stored]}
            if method == "get_schedule":
                return stored[selected]
            if method == "delete_schedule":
                del stored[selected]
            else:
                stored[selected] = values

        monkeypatch.setattr("hirz.aws.schedules.call", call)
        c = Connection([(home, "a", at + timedelta(minutes=2))])

        async def sync():
            await reconcile(
                c, None, group="hirz-item36", target="lambda", role="role", at=at
            )

        await sync()
        assert set(stored) == {key}
        assert stored[key]["Target"]["Input"] == "{}"
        assert stored[key]["ActionAfterCompletion"] == "DELETE"
        assert stored[key]["FlexibleTimeWindow"] == {"Mode": "OFF"}
        calls.clear()
        await sync()
        assert calls == ["list_schedules", "get_schedule"]
        del stored[key]
        await sync()
        assert key in stored
        c.rows = [(home, "a", at + timedelta(minutes=3))]
        await sync()
        assert calls[-1] == "update_schedule"
        c.rows = []
        await sync()
        assert not stored
        compiled = c.statement.compile().params
        assert ["scheduled", "executing", "dispatched"] in compiled.values()
        assert at in compiled.values()
        assert name(home, "a") != name(uuid4(), "a")

    asyncio.run(run())


@pytest.mark.parametrize(
    "code,raises", [("ConflictException", False), ("AccessDeniedException", True)]
)
def test_schedule_errors_fail_closed(monkeypatch, code, raises):
    async def run():
        at = datetime.now(UTC)
        c = Connection([(uuid4(), "a", at + timedelta(minutes=1))])
        call = AsyncMock(
            side_effect=[
                {"Schedules": []},
                ClientError({"Error": {"Code": code}}, "CreateSchedule"),
            ]
        )
        monkeypatch.setattr("hirz.aws.schedules.call", call)
        if raises:
            with pytest.raises(ClientError):
                await reconcile(c, None, group="g", target="t", role="r", at=at)
        else:
            await reconcile(c, None, group="g", target="t", role="r", at=at)

    asyncio.run(run())
