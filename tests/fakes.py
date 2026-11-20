"""A fake EventSource and raw-record builders (synthetic data only)."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from macos_calendar_events._raw import RawCalendar, RawEvent, RawParticipant

NOT_DETERMINED, RESTRICTED, DENIED, FULL_ACCESS, WRITE_ONLY = 0, 1, 2, 3, 4


def ts(text: str) -> float:
    """``2025-11-19T16:00:00Z`` -> epoch float."""
    return datetime.fromisoformat(text).timestamp()


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


def raw_calendar(id: str = "cal-1", **overrides: Any) -> RawCalendar:
    base = RawCalendar(
        id=id,
        title="Work",
        source_title="iCloud",
        source_type=2,
        color_rgb=(0.0, 0.5, 1.0),
        allows_modifications=True,
    )
    return dataclasses.replace(base, **overrides)


def raw_participant(**overrides: Any) -> RawParticipant:
    base = RawParticipant(
        name="Sam Example",
        url="mailto:sam@example.com",
        role=1,
        status=2,
        type=1,
        is_current_user=False,
    )
    return dataclasses.replace(base, **overrides)


def raw_event(
    start: str = "2025-11-19T16:00:00Z", end: str = "2025-11-19T16:30:00Z", **overrides: Any
) -> RawEvent:
    base = RawEvent(
        calendar_id="cal-1",
        external_id="ext-1",
        event_identifier="evt-1",
        title="Planning",
        start_epoch=ts(start),
        end_epoch=ts(end),
        occurrence_epoch=ts(start),
        all_day=False,
        start_local=None,
        end_local=None,
        time_zone="America/Los_Angeles",
        location=None,
        url=None,
        notes=None,
        status=1,
        has_recurrence_rules=False,
        is_detached=False,
        organizer=None,
        attendees=(),
    )
    return dataclasses.replace(base, **overrides)


class FakeSource:
    """In-memory EventSource that records what it was asked for.

    ``events()`` matches like EventKit's predicate: inclusive at the range start
    (an event ending exactly at ``start`` is returned), exclusive at the range end.
    """

    def __init__(
        self,
        *,
        status: int = FULL_ACCESS,
        status_after_request: int | None = None,
        calendars: Sequence[RawCalendar] = (),
        events: Sequence[RawEvent] = (),
    ) -> None:
        self.status = status
        self.status_after_request = status_after_request
        self._calendars = list(calendars) if calendars else [raw_calendar()]
        self._events = list(events)
        self.requests: list[float] = []
        self.ranges: list[tuple[datetime, datetime, list[str] | None]] = []

    def authorization_status(self) -> int:
        return self.status

    def request_access(self, timeout: float) -> int:
        self.requests.append(timeout)
        if self.status_after_request is not None:
            self.status = self.status_after_request
        return self.status

    def calendars(self) -> Sequence[RawCalendar]:
        return list(self._calendars)

    def events(
        self, start: datetime, end: datetime, calendar_ids: Sequence[str] | None
    ) -> Sequence[RawEvent]:
        self.ranges.append((start, end, None if calendar_ids is None else list(calendar_ids)))
        lo, hi = start.timestamp(), end.timestamp()
        out = []
        for ev in self._events:
            if calendar_ids is not None and ev.calendar_id not in calendar_ids:
                continue
            undated = ev.start_epoch is None or ev.end_epoch is None  # R3 skip candidates
            if undated or (ev.start_epoch < hi and ev.end_epoch >= lo):  # type: ignore[operator]
                out.append(ev)
        return out
