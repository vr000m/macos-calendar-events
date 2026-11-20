"""Adapter boundary: plain-Python records the EventKit adapter produces (no ObjC types).

Values are raw EventKit facts: epoch floats, local date-time components for all-day
events, enum ints, strings and ``None``. All decisions happen in ``_mapping``.

Text fields are valid Unicode (the adapter replaces unpaired UTF-16 surrogates with
U+FFFD). Calendar identifiers (``RawCalendar.id``, ``RawEvent.calendar_id``) are the
exact EventKit strings instead: they are keys for joins and for the adapter's
``calendarWithIdentifier_`` lookup, so ``_mapping`` cleans them only where they become
output (``CalendarInfo.id``, ``CalendarRef.id``) or are compared with a caller selector.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RawParticipant:
    name: str | None
    url: str | None
    role: int
    status: int
    type: int
    is_current_user: bool


@dataclass(frozen=True, slots=True)
class RawCalendar:
    id: str
    title: str | None
    source_title: str | None
    source_type: int
    color_rgb: tuple[float, float, float] | None  # already sRGB
    allows_modifications: bool


@dataclass(frozen=True, slots=True)
class RawEvent:
    calendar_id: str | None  # nil -> row skipped (R3)
    external_id: str | None
    event_identifier: str | None
    title: str | None
    start_epoch: float | None  # nil -> skipped
    end_epoch: float | None  # nil -> skipped
    occurrence_epoch: float | None
    all_day: bool
    start_local: tuple[int, int, int, int, int, int] | None  # all-day only, system zone
    end_local: tuple[int, int, int, int, int, int] | None
    time_zone: str | None
    location: str | None
    url: str | None
    notes: str | None
    status: int
    has_recurrence_rules: bool
    is_detached: bool
    organizer: RawParticipant | None
    attendees: tuple[RawParticipant, ...]


class EventSource(Protocol):
    def authorization_status(self) -> int:
        """Raw EKAuthorizationStatus."""
        ...

    def request_access(self, timeout: float) -> int:
        """Request full access; return the raw status after the wait."""
        ...

    def calendars(self) -> Sequence[RawCalendar]: ...

    def events(
        self, start: datetime, end: datetime, calendar_ids: Sequence[str] | None
    ) -> Sequence[RawEvent]:
        """Events EventKit matches for exactly ``[start, end]``; ``None`` = all calendars."""
        ...
