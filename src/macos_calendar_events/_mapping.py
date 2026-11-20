"""Pure mapping from raw adapter records to the public data types (no I/O, no PyObjC)."""

from __future__ import annotations

import dataclasses
import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import NamedTuple
from urllib.parse import unquote

from ._raw import RawCalendar, RawEvent, RawParticipant
from .errors import CalendarNotFoundError, InvalidQueryError
from .models import (
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
)

# EventKit enum ints -> public enums. Unknown ints map to UNKNOWN.
ACCESS_STATUS: Mapping[int, AccessStatus] = {
    0: AccessStatus.NOT_DETERMINED,  # EKAuthorizationStatusNotDetermined
    1: AccessStatus.RESTRICTED,  # EKAuthorizationStatusRestricted
    2: AccessStatus.DENIED,  # EKAuthorizationStatusDenied
    3: AccessStatus.FULL_ACCESS,  # EKAuthorizationStatusFullAccess
    4: AccessStatus.WRITE_ONLY,  # EKAuthorizationStatusWriteOnly
}
SOURCE_TYPE: Mapping[int, SourceType] = {
    0: SourceType.LOCAL,
    1: SourceType.EXCHANGE,
    2: SourceType.CALDAV,
    3: SourceType.MOBILEME,
    4: SourceType.SUBSCRIBED,
    5: SourceType.BIRTHDAYS,
}
EVENT_STATUS: Mapping[int, EventStatus] = {
    0: EventStatus.NONE,
    1: EventStatus.CONFIRMED,
    2: EventStatus.TENTATIVE,
    3: EventStatus.CANCELED,
}
PARTICIPANT_ROLE: Mapping[int, ParticipantRole] = {
    0: ParticipantRole.UNKNOWN,
    1: ParticipantRole.REQUIRED,
    2: ParticipantRole.OPTIONAL,
    3: ParticipantRole.CHAIR,
    4: ParticipantRole.NON_PARTICIPANT,
}
PARTICIPATION_STATUS: Mapping[int, ParticipationStatus] = {
    0: ParticipationStatus.UNKNOWN,
    1: ParticipationStatus.PENDING,
    2: ParticipationStatus.ACCEPTED,
    3: ParticipationStatus.DECLINED,
    4: ParticipationStatus.TENTATIVE,
    5: ParticipationStatus.DELEGATED,
    6: ParticipationStatus.COMPLETED,
    7: ParticipationStatus.IN_PROCESS,
}
PARTICIPANT_TYPE: Mapping[int, ParticipantType] = {
    0: ParticipantType.UNKNOWN,
    1: ParticipantType.PERSON,
    2: ParticipantType.ROOM,
    3: ParticipantType.RESOURCE,
    4: ParticipantType.GROUP,
}

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
MAX_WINDOW = timedelta(days=3 * 365 - 2)  # R13
QUERY_MARGIN = timedelta(days=1)  # R13 widening
LATEST_END = (
    datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC) - QUERY_MARGIN
)  # keeps widening in range
_EPOCH_TEXT = re.compile(r"^[0-9]+$")
_RFC3339_UTC = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$"
)  # hour 00-23 here: Python 3.14's fromisoformat accepts T24:00:00 as next-day midnight


def access_status_from_int(value: int) -> AccessStatus:
    return ACCESS_STATUS.get(value, AccessStatus.UNKNOWN)


def source_type_from_int(value: int) -> SourceType:
    return SOURCE_TYPE.get(value, SourceType.UNKNOWN)


def event_status_from_int(value: int) -> EventStatus:
    return EVENT_STATUS.get(value, EventStatus.UNKNOWN)


def participant_role_from_int(value: int) -> ParticipantRole:
    return PARTICIPANT_ROLE.get(value, ParticipantRole.UNKNOWN)


def participation_status_from_int(value: int) -> ParticipationStatus:
    return PARTICIPATION_STATUS.get(value, ParticipationStatus.UNKNOWN)


def participant_type_from_int(value: int) -> ParticipantType:
    return PARTICIPANT_TYPE.get(value, ParticipantType.UNKNOWN)


# --- text ----------------------------------------------------------------------------


def unicode_text(text: str) -> str:
    """``text`` with every unpaired UTF-16 surrogate replaced by U+FFFD.

    An ``NSString`` may hold a lone surrogate, which PyObjC passes through as ``\\udXXX``;
    such a ``str`` can't be UTF-8 encoded (JSON output, id hashing). A split but valid
    pair is joined into its code point.
    """
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
    return text


# --- mailto and color ----------------------------------------------------------------


def _is_mailto(url: str) -> bool:
    return url[:7].lower() == "mailto:"


def parse_mailto(url: str) -> str | None:
    """First address of an RFC 6068 ``mailto:`` URL, or ``None`` (R4).

    The path's address list is split on ``,`` before percent-decoding; with an empty
    path the first address of a ``to=`` hfield is used. ``+`` is not a space.
    """
    if not _is_mailto(url):
        return None
    path, _, query = url[7:].partition("?")
    if path:
        return _clean_address(path.split(",")[0])
    for hfield in query.split("&"):
        name, sep, value = hfield.partition("=")
        if sep and unquote(name).lower() == "to" and value:
            return _clean_address(value.split(",")[0])
    return None


def _clean_address(raw: str) -> str | None:
    address = unquote(raw).strip()
    return address or None


def rgb_to_hex(rgb: tuple[float, float, float] | None) -> str | None:
    """sRGB components in [0, 1] -> ``#RRGGBB`` (uppercase); ``None`` passes through."""
    if rgb is None:
        return None
    channels = []
    for component in rgb:
        if not math.isfinite(component):
            return None
        channels.append(math.floor(min(max(component, 0.0), 1.0) * 255 + 0.5))
    return "#{:02X}{:02X}{:02X}".format(*channels)


# --- instants and windows ------------------------------------------------------------


def epoch_to_utc(seconds: float) -> datetime:
    """Epoch seconds -> aware UTC datetime truncated to whole seconds (floor, so pre-1970
    values truncate the same way a datetime's sub-seconds do in serialization)."""
    return EPOCH + timedelta(seconds=math.floor(seconds))


def parse_instant(value: datetime | int) -> datetime:
    """Python API input: a non-negative int epoch or an aware UTC datetime (R12)."""
    if isinstance(value, bool):
        raise InvalidQueryError("instant must be an int epoch or an aware UTC datetime")
    if isinstance(value, int):
        if value < 0:
            raise InvalidQueryError("epoch seconds must be non-negative")
        try:
            return EPOCH + timedelta(seconds=value)
        except OverflowError:
            raise InvalidQueryError("epoch seconds out of range") from None
    if isinstance(value, datetime):
        offset = value.utcoffset()
        if offset is None:
            raise InvalidQueryError("naive datetime; pass an aware UTC datetime")
        if offset != timedelta(0):
            raise InvalidQueryError("datetime must be UTC (utcoffset() == 0)")
        instant = value.astimezone(UTC).replace(microsecond=0)
        if instant < EPOCH:
            raise InvalidQueryError("instant before 1970-01-01T00:00:00Z")
        return instant
    raise InvalidQueryError("instant must be an int epoch or an aware UTC datetime")


def parse_instant_text(text: str) -> datetime:
    """CLI input: ``^[0-9]+$`` epoch seconds or an RFC 3339 UTC string (R12)."""
    # fullmatch, not match: ``$`` would also accept a trailing newline.
    if _EPOCH_TEXT.fullmatch(text):
        try:
            seconds = int(text)
        except ValueError:  # CPython refuses to convert very long digit strings
            raise InvalidQueryError("epoch seconds out of range") from None
        return parse_instant(seconds)
    if not _RFC3339_UTC.fullmatch(text):
        raise InvalidQueryError("expected epoch seconds or an RFC 3339 UTC time (Z or +00:00)")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise InvalidQueryError("invalid RFC 3339 date-time") from None
    return parse_instant(parsed)


def validate_window(start: datetime, end: datetime) -> None:
    """Aware UTC, at or after 1970, ``end > start``, length at most 3*365-2 days (R12, R13)."""
    for value in (start, end):
        offset = value.utcoffset()
        if offset is None:
            raise InvalidQueryError("window bounds must be aware UTC datetimes")
        if offset != timedelta(0):
            raise InvalidQueryError("window bounds must be UTC")
    if start < EPOCH:
        raise InvalidQueryError("window starts before 1970-01-01T00:00:00Z")
    if end <= start:
        raise InvalidQueryError("window end must be after start")
    if end > LATEST_END:
        raise InvalidQueryError("window ends too close to year 9999")
    if end - start > MAX_WINDOW:
        raise InvalidQueryError(f"window longer than {MAX_WINDOW.days} days")


def parse_window(start: datetime | int, end: datetime | int) -> tuple[datetime, datetime]:
    """Python API window: both bounds through :func:`parse_instant`, then
    :func:`validate_window`. The one check for every caller-supplied window."""
    window = parse_instant(start), parse_instant(end)
    validate_window(*window)
    return window


def query_range(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    return start - QUERY_MARGIN, end + QUERY_MARGIN


def overlaps(ev_start: datetime, ev_end: datetime, w_start: datetime, w_end: datetime) -> bool:
    """Half-open overlap; a zero-length event counts when ``w_start <= ev_start < w_end``."""
    if ev_start == ev_end:
        return w_start <= ev_start < w_end
    return ev_start < w_end and ev_end > w_start


def normalize_all_day(
    start_epoch: float,
    end_epoch: float,
    start_local: tuple[int, ...],
    end_local: tuple[int, ...],
) -> tuple[datetime, datetime, date, date]:
    """All-day instants and exclusive dates; an inclusive local 23:59:59 end becomes +1 s."""
    start = epoch_to_utc(start_epoch)
    end = epoch_to_utc(end_epoch)
    start_date = date(*start_local[:3])
    end_date = date(*end_local[:3])
    if tuple(end_local[3:6]) == (23, 59, 59):
        end += timedelta(seconds=1)
        end_date += timedelta(days=1)
    return start, end, start_date, end_date


# --- calendars -----------------------------------------------------------------------


def select_calendars(
    cals: Sequence[RawCalendar], selectors: Sequence[str] | None
) -> list[RawCalendar]:
    """R6: id match first, else casefolded title match; every selector must match.

    A selector equal to a raw ``calendarIdentifier`` selects that calendar only. Otherwise it
    matches by id every calendar whose output id (:func:`unicode_text` of the raw id; the two
    differ only for a lone surrogate) equals it. The returned records keep their raw ids for
    the adapter's lookup.
    """
    if selectors is None:
        return list(cals)
    if len(selectors) == 0:
        raise InvalidQueryError("calendars=[] selects nothing; pass None for all calendars")
    chosen: set[str] = set()
    unmatched: list[str] = []
    for selector in selectors:
        by_id = [c.id for c in cals if c.id == selector] or [
            c.id for c in cals if unicode_text(c.id) == selector
        ]
        if by_id:
            chosen.update(by_id)
            continue
        folded = selector.casefold()
        by_title = [c.id for c in cals if c.title is not None and c.title.casefold() == folded]
        if by_title:
            chosen.update(by_title)
        else:
            unmatched.append(selector)
    if unmatched:
        titles = sorted({c.title for c in cals if c.title is not None})
        raise CalendarNotFoundError(unmatched, titles)
    return [c for c in cals if c.id in chosen]


def map_calendar(raw: RawCalendar) -> CalendarInfo:
    return CalendarInfo(
        id=unicode_text(raw.id),
        title=raw.title,
        source_title=raw.source_title,
        source_type=source_type_from_int(raw.source_type),
        color_hex=rgb_to_hex(raw.color_rgb),
        read_only=not raw.allows_modifications,
    )


def to_calendars(raw: Sequence[RawCalendar]) -> list[CalendarInfo]:
    """Map, then sort by ``(source_title is not None, source_title or "", title or "", id)``."""
    mapped = [map_calendar(c) for c in raw]
    mapped.sort(
        key=lambda c: (c.source_title is not None, c.source_title or "", c.title or "", c.id)
    )
    return mapped


# --- events --------------------------------------------------------------------------


def map_participant(raw: RawParticipant) -> Participant:
    email: str | None = None
    url = raw.url
    if url is not None and _is_mailto(url):
        email = parse_mailto(url)
        url = None
    return Participant(
        name=raw.name,
        email=email,
        url=url,
        role=participant_role_from_int(raw.role),
        status=participation_status_from_int(raw.status),
        type=participant_type_from_int(raw.type),
        is_self=raw.is_current_user,
    )


def map_event(raw: RawEvent, calendar: CalendarRef, *, include_notes: bool) -> Event | None:
    """Map one raw row; ``None`` when R3 says skip (nil start or end). ``id`` is left empty
    for :func:`assign_ids`."""
    if raw.start_epoch is None or raw.end_epoch is None:
        return None
    start_date: date | None = None
    end_date: date | None = None
    if raw.all_day and raw.start_local is not None and raw.end_local is not None:
        start, end, start_date, end_date = normalize_all_day(
            raw.start_epoch, raw.end_epoch, raw.start_local, raw.end_local
        )
    else:
        start, end = epoch_to_utc(raw.start_epoch), epoch_to_utc(raw.end_epoch)
    occurrence = start if raw.occurrence_epoch is None else epoch_to_utc(raw.occurrence_epoch)
    attendees = tuple(map_participant(p) for p in raw.attendees)
    self_status = next((a.status for a in attendees if a.is_self), None)
    return Event(
        id="",
        external_id=raw.external_id,
        event_identifier=raw.event_identifier,
        title=raw.title,
        start=start,
        end=end,
        all_day=raw.all_day,
        start_date=start_date,
        end_date=end_date,
        time_zone=raw.time_zone,
        location=raw.location,
        url=raw.url,
        notes=raw.notes if include_notes else None,
        status=event_status_from_int(raw.status),
        is_recurring=raw.has_recurrence_rules or raw.is_detached,
        is_detached=raw.is_detached,
        occurrence_start=occurrence,
        organizer=None if raw.organizer is None else map_participant(raw.organizer),
        attendees=attendees,
        self_status=self_status,
        calendar=calendar,
    )


def _base_id(event: Event) -> str:
    key = "\x1f".join(
        (
            event.calendar.id,
            event.external_id or event.event_identifier or "",
            event.occurrence_start.isoformat(),
            event.start.isoformat(),
            event.end.isoformat(),
        )
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def assign_ids(events: Sequence[Event]) -> list[Event]:
    """R3 id derivation: hashed base key; collisions get ``-2``, ``-3``… in order of
    ``(title or "", location or "")``, then input (EventKit) order."""
    groups: dict[str, list[int]] = {}
    for index, event in enumerate(events):
        groups.setdefault(_base_id(event), []).append(index)
    ids: dict[int, str] = {}
    for base, members in groups.items():
        members.sort(key=lambda i: (events[i].title or "", events[i].location or "", i))
        for ordinal, index in enumerate(members, start=1):
            ids[index] = base if ordinal == 1 else f"{base}-{ordinal}"
    return [dataclasses.replace(e, id=ids[i]) for i, e in enumerate(events)]


class MappedEvents(NamedTuple):
    events: list[Event]
    skipped: int


def to_events(
    raw: Sequence[RawEvent],
    window: tuple[datetime, datetime],
    *,
    include_notes: bool,
    calendars: Mapping[str, RawCalendar] | None = None,
) -> MappedEvents:
    """Map -> skip (R3) -> overlap filter -> ids -> sort by ``(start, end, calendar.id, id)``.

    ``calendars`` (keyed by raw id) supplies the title and source title for each row's
    ``CalendarRef``; the ref's id is the cleaned output id.
    """
    w_start, w_end = window
    known = calendars or {}
    kept: list[Event] = []
    skipped = 0
    for row in raw:
        if row.calendar_id is None:
            skipped += 1
            continue
        cal = known.get(row.calendar_id)
        ref = CalendarRef(
            id=unicode_text(row.calendar_id),
            title=None if cal is None else cal.title,
            source_title=None if cal is None else cal.source_title,
        )
        event = map_event(row, ref, include_notes=include_notes)
        if event is None:
            skipped += 1
            continue
        if overlaps(event.start, event.end, w_start, w_end):
            kept.append(event)
    with_ids = assign_ids(kept)
    with_ids.sort(key=lambda e: (e.start, e.end, e.calendar.id, e.id))
    return MappedEvents(with_ids, skipped)
