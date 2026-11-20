"""Public data types and the single owner of JSON serialization (R3, R4, R12, R18)."""

from __future__ import annotations

import calendar as _calendar
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Final, Literal, TypedDict

SCHEMA_VERSION: Final = 1
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


class AccessStatus(StrEnum):
    NOT_DETERMINED = "not_determined"
    RESTRICTED = "restricted"
    DENIED = "denied"
    FULL_ACCESS = "full_access"
    WRITE_ONLY = "write_only"
    UNKNOWN = "unknown"


class EventStatus(StrEnum):
    NONE = "none"
    CONFIRMED = "confirmed"
    TENTATIVE = "tentative"
    CANCELED = "canceled"
    UNKNOWN = "unknown"


class ParticipationStatus(StrEnum):
    UNKNOWN = "unknown"
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    TENTATIVE = "tentative"
    DELEGATED = "delegated"
    COMPLETED = "completed"
    IN_PROCESS = "in_process"


class ParticipantRole(StrEnum):
    UNKNOWN = "unknown"
    REQUIRED = "required"
    OPTIONAL = "optional"
    CHAIR = "chair"
    NON_PARTICIPANT = "non_participant"


class ParticipantType(StrEnum):
    UNKNOWN = "unknown"
    PERSON = "person"
    ROOM = "room"
    RESOURCE = "resource"
    GROUP = "group"


class SourceType(StrEnum):
    LOCAL = "local"
    EXCHANGE = "exchange"
    CALDAV = "caldav"
    MOBILEME = "mobileme"
    SUBSCRIBED = "subscribed"
    BIRTHDAYS = "birthdays"
    UNKNOWN = "unknown"


def _utc_text(value: datetime) -> str:
    """RFC 3339 UTC with whole seconds and a ``Z`` suffix (sub-seconds are truncated)."""
    return _as_utc(value).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def _utc_ts(value: datetime) -> int:
    """Whole epoch seconds, consistent with :func:`_utc_text` (also before 1970)."""
    return _calendar.timegm(_as_utc(value).utctimetuple())


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetime cannot be serialized")
    return value.astimezone(UTC)


def _date_text(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


@dataclass(frozen=True, slots=True)
class Participant:
    name: str | None
    email: str | None
    url: str | None  # None when the participant URL is mailto:
    role: ParticipantRole
    status: ParticipationStatus
    type: ParticipantType
    is_self: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "email": self.email,
            "url": self.url,
            "role": str(self.role),
            "status": str(self.status),
            "type": str(self.type),
            "is_self": self.is_self,
        }


@dataclass(frozen=True, slots=True)
class CalendarRef:
    id: str
    title: str | None
    source_title: str | None

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "title": self.title, "source_title": self.source_title}


@dataclass(frozen=True, slots=True)
class CalendarInfo:
    id: str
    title: str | None
    source_title: str | None
    source_type: SourceType
    color_hex: str | None  # "#RRGGBB" (sRGB) or None
    read_only: bool  # not allowsContentModifications

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "source_title": self.source_title,
            "source_type": str(self.source_type),
            "color_hex": self.color_hex,
            "read_only": self.read_only,
        }


@dataclass(frozen=True, slots=True)
class Event:
    id: str  # opaque; unique within one response
    external_id: str | None
    event_identifier: str | None
    title: str | None
    start: datetime  # UTC, whole seconds
    end: datetime  # UTC, exclusive
    all_day: bool
    start_date: date | None  # all-day only
    end_date: date | None  # all-day only, exclusive
    time_zone: str | None
    location: str | None
    url: str | None
    notes: str | None
    status: EventStatus
    is_recurring: bool
    is_detached: bool
    occurrence_start: datetime
    organizer: Participant | None
    attendees: tuple[Participant, ...]
    self_status: ParticipationStatus | None
    calendar: CalendarRef

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "external_id": self.external_id,
            "event_identifier": self.event_identifier,
            "title": self.title,
            "start": _utc_text(self.start),
            "start_ts": _utc_ts(self.start),
            "end": _utc_text(self.end),
            "end_ts": _utc_ts(self.end),
            "all_day": self.all_day,
            "start_date": _date_text(self.start_date),
            "end_date": _date_text(self.end_date),
            "time_zone": self.time_zone,
            "location": self.location,
            "url": self.url,
            "notes": self.notes,
            "status": str(self.status),
            "is_recurring": self.is_recurring,
            "is_detached": self.is_detached,
            "occurrence_start": _utc_text(self.occurrence_start),
            "occurrence_start_ts": _utc_ts(self.occurrence_start),
            "organizer": None if self.organizer is None else self.organizer.to_dict(),
            "attendees": [a.to_dict() for a in self.attendees],
            "self_status": None if self.self_status is None else str(self.self_status),
            "calendar": self.calendar.to_dict(),
        }


class WindowEcho(TypedDict):
    start: str
    end: str
    start_ts: int
    end_ts: int


class WindowDocument(TypedDict):
    schema_version: Literal[1]
    window: WindowEcho
    events: list[dict[str, object]]


class CalendarsDocument(TypedDict):
    schema_version: Literal[1]
    calendars: list[dict[str, object]]


def _dumps(document: object) -> str:
    return json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _window_bound(value: datetime | int) -> datetime:
    """A window bound in either form ``events_in_window`` accepts: aware datetime or int epoch."""
    if isinstance(value, bool) or not isinstance(value, datetime | int):
        raise TypeError("window bounds must be aware datetimes or int epoch seconds")
    return value if isinstance(value, datetime) else _EPOCH + timedelta(seconds=value)


def window_to_json(
    events: Sequence[Event], *, window: tuple[datetime | int, datetime | int]
) -> str:
    """Serialize a window document; ``window`` is the padded caller window (not the query range),
    as aware datetimes or int epoch seconds (the same forms ``events_in_window`` accepts)."""
    start, end = (_window_bound(bound) for bound in window)
    document: WindowDocument = {
        "schema_version": SCHEMA_VERSION,
        "window": {
            "start": _utc_text(start),
            "end": _utc_text(end),
            "start_ts": _utc_ts(start),
            "end_ts": _utc_ts(end),
        },
        "events": [e.to_dict() for e in events],
    }
    return _dumps(document)


def calendars_to_json(calendars: Sequence[CalendarInfo]) -> str:
    document: CalendarsDocument = {
        "schema_version": SCHEMA_VERSION,
        "calendars": [c.to_dict() for c in calendars],
    }
    return _dumps(document)
