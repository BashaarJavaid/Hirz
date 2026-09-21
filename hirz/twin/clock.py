"""Aware simulated time driven only by an injected monotonic timer."""

import math
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from hirz.adapters.base import AdapterError
from hirz.graph.models import utc


class SimClock:
    def __init__(
        self,
        start: datetime,
        speed: float,
        *,
        timer: Callable[[], float] = time.monotonic,
    ):
        self._at = utc(start)
        self._timer = timer
        self._base = timer()
        self._speed = self._validate_speed(speed)

    @staticmethod
    def _validate_speed(value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise AdapterError("Clock speed must be finite and nonnegative.")
        return value

    def _instant(self, sample: float) -> datetime:
        elapsed = sample - self._base
        if not math.isfinite(elapsed) or elapsed < 0:
            raise AdapterError("Monotonic timer moved backwards or is invalid.")
        return self._at + timedelta(seconds=elapsed * self._speed)

    def now(self) -> datetime:
        return self._instant(self._timer())

    __call__ = now

    def set_speed(self, speed: float) -> None:
        speed = self._validate_speed(speed)
        sample = self._timer()
        self._at, self._base, self._speed = self._instant(sample), sample, speed

    def jump(self, at: datetime) -> None:
        at = utc(at)
        sample = self._timer()
        if at < self._instant(sample):
            raise AdapterError("Simulation cannot move backwards.")
        self._at, self._base = at, sample
