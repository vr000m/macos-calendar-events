"""Read-only macOS Calendar (EventKit) window queries. macOS 14+.

The CLI (``macos-calendar-events``) is the primary integration surface; this Python API
is public but secondary. EventKit is imported lazily, so this package imports anywhere.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from . import _api, _eventkit
from .errors import (
    CalendarAccessError,
    CalendarNotFoundError,
    EventKitUnavailableError,
    InvalidQueryError,
    MacosCalendarEventsError,
)
from .models import (
    SCHEMA_VERSION,
    AccessStatus,
    CalendarInfo,
    CalendarRef,
    Event,
    EventStatus,
    Participant,
    ParticipantRole,
    ParticipantType,
    ParticipationStatus,
    SourceType,
    calendars_to_json,
    window_to_json,
)

__version__ = "0.1.0"

__all__ = [
    "SCHEMA_VERSION",
    "AccessStatus",
    "CalendarAccessError",
    "CalendarInfo",
    "CalendarNotFoundError",
    "CalendarRef",
    "Event",
    "EventKitUnavailableError",
    "EventStatus",
    "InvalidQueryError",
    "MacosCalendarEventsError",
    "Participant",
    "ParticipantRole",
    "ParticipantType",
    "ParticipationStatus",
    "SourceType",
    "__version__",
    "authorization_status",
    "calendars_to_json",
    "events_in_window",
    "list_calendars",
    "request_access",
    "window_to_json",
]


def events_in_window(
    start: datetime | int,
    end: datetime | int,
    *,
    calendars: Sequence[str] | None = None,
    include_notes: bool = False,
    prompt: bool = True,
) -> list[Event]:
    """Every event overlapping the half-open UTC window ``[start, end)`` (R1)."""
    return _api.query_events(
        _eventkit.default_source,
        start,
        end,
        calendars=calendars,
        include_notes=include_notes,
        prompt=prompt,
    ).events


def list_calendars(*, prompt: bool = True) -> list[CalendarInfo]:
    """Every event calendar EventKit exposes (R2)."""
    return _api.query_calendars(_eventkit.default_source, prompt=prompt)


def authorization_status() -> AccessStatus:
    """Current Calendar authorization status; never prompts (R9)."""
    return _api.authorization_status(_eventkit.default_source)


def request_access(timeout: float = 60.0) -> AccessStatus:
    """Request full Calendar access (may show the system prompt) and wait up to ``timeout``."""
    return _api.request_access(_eventkit.default_source, timeout)
