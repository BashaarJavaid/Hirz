"""calendar contract. Methods do not implement or authorize operations."""

from datetime import datetime
from typing import Protocol

from hirz.adapters.base import Adapter
from hirz.graph.models import ScheduleEvent


class CalendarAdapter(Adapter, Protocol):
    async def list_events(
        self, start: datetime, end: datetime
    ) -> tuple[ScheduleEvent, ...]: ...

    async def expected_arrivals(
        self, start: datetime, end: datetime
    ) -> tuple[ScheduleEvent, ...]: ...
