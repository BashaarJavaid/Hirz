"""Read supplied canonical events; no scheduling writes."""

from datetime import datetime

from hirz.graph.models import AdapterDomain, ScheduleEvent, utc
from hirz.twin.adapters import TwinAdapter


class TwinCalendar(TwinAdapter):
    domain: AdapterDomain = "calendar"
    capabilities = frozenset({"list_events", "expected_arrivals"})

    async def list_events(
        self, start: datetime, end: datetime
    ) -> tuple[ScheduleEvent, ...]:
        self.read()
        self.world.check_range(start, end)
        return tuple(
            e
            for e in self.world.calendar
            if utc(e.starts_at) < utc(end) and utc(e.ends_at) > utc(start)
        )

    async def expected_arrivals(
        self, start: datetime, end: datetime
    ) -> tuple[ScheduleEvent, ...]:
        return tuple(
            e for e in await self.list_events(start, end) if e.kind == "arrival"
        )
