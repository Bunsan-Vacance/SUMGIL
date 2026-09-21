"""Daily operating window for producers that only run during service hours."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta

MINUTES_PER_DAY = 24 * 60
DEFAULT_SUBWAY_WINDOW_START = "05:30"
DEFAULT_SUBWAY_WINDOW_END = "01:00"
SUBWAY_WINDOW_START_ENV = "SUBWAY_OPERATING_START"
SUBWAY_WINDOW_END_ENV = "SUBWAY_OPERATING_END"


def parse_hhmm(value: str) -> int:
    """Parse ``HH:MM`` into minutes of day. ``24:00`` means end of day."""
    try:
        hour_text, minute_text = value.strip().split(":")
        hour, minute = int(hour_text), int(minute_text)
    except ValueError as exc:
        raise ValueError(f"time must be HH:MM: {value!r}") from exc
    total = hour * 60 + minute
    if not (0 <= minute < 60) or not (0 <= total <= MINUTES_PER_DAY):
        raise ValueError(f"time out of range: {value!r}")
    return total


@dataclass(frozen=True)
class OperatingWindow:
    """Half-open daily window ``[start, end)`` in minutes of day.

    ``end < start`` means the window wraps past midnight (e.g. 05:30-01:00).
    """

    start_min: int
    end_min: int

    def __post_init__(self) -> None:
        if self.start_min == self.end_min:
            raise ValueError("operating window start and end must differ")

    @classmethod
    def from_text(cls, start: str, end: str) -> OperatingWindow:
        return cls(parse_hhmm(start), parse_hhmm(end))

    def contains(self, moment: datetime) -> bool:
        minute = moment.hour * 60 + moment.minute
        if self.start_min < self.end_min:
            return self.start_min <= minute < self.end_min
        return minute >= self.start_min or minute < self.end_min

    def covers_hour(self, hour_start: datetime) -> bool:
        """True when the whole hour beginning at ``hour_start`` is inside the window."""
        return self.contains(hour_start) and self.contains(hour_start + timedelta(minutes=59))

    def last_open(self, now: datetime) -> datetime:
        """Most recent window start at or before ``now``."""
        start = now.replace(
            hour=(self.start_min % MINUTES_PER_DAY) // 60,
            minute=self.start_min % 60,
            second=0,
            microsecond=0,
        )
        return start - timedelta(days=1) if start > now else start


def subway_window_from_env() -> OperatingWindow:
    return OperatingWindow.from_text(
        os.environ.get(SUBWAY_WINDOW_START_ENV, DEFAULT_SUBWAY_WINDOW_START),
        os.environ.get(SUBWAY_WINDOW_END_ENV, DEFAULT_SUBWAY_WINDOW_END),
    )
