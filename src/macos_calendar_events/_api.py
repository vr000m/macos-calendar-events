"""Query orchestration over an injected ``EventSource`` (R9, R11 order, R13)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Final, NamedTuple

from . import _mapping
from ._raw import EventSource
from .errors import CalendarAccessError, InvalidQueryError
from .models import AccessStatus, CalendarInfo, Event

ACCESS_TIMEOUT_S: Final = 60.0


class QueryResult(NamedTuple):
    events: list[Event]
    skipped: int  # rows dropped by R3


def _require_access(source: EventSource, *, prompt: bool) -> None:
    status = _mapping.access_status_from_int(source.authorization_status())
    if status is AccessStatus.NOT_DETERMINED and prompt:
        status = _mapping.access_status_from_int(source.request_access(ACCESS_TIMEOUT_S))
    if status is not AccessStatus.FULL_ACCESS:
        raise CalendarAccessError(status)


def query_events(
    get_source: Callable[[], EventSource],
    start: datetime | int,
    end: datetime | int,
    *,
    calendars: Sequence[str] | None,
    include_notes: bool,
    prompt: bool,
) -> QueryResult:
    """validate -> source -> access gate -> select -> widen -> fetch -> map."""
    w_start = _mapping.parse_instant(start)
    w_end = _mapping.parse_instant(end)
    _mapping.validate_window(w_start, w_end)
    if isinstance(calendars, str):  # a bare string would be read as one selector per character
        raise InvalidQueryError("calendars must be a list of selectors, not a single string")
    if calendars is not None and len(calendars) == 0:
        raise InvalidQueryError("calendars=[] selects nothing; pass None for all calendars")
    source = get_source()
    _require_access(source, prompt=prompt)
    all_calendars = source.calendars()
    selected = _mapping.select_calendars(all_calendars, calendars)
    q_start, q_end = _mapping.query_range(w_start, w_end)
    ids = None if calendars is None else [c.id for c in selected]
    raw = source.events(q_start, q_end, ids)
    mapped = _mapping.to_events(
        raw,
        (w_start, w_end),
        include_notes=include_notes,
        calendars={c.id: c for c in all_calendars},
    )
    return QueryResult(mapped.events, mapped.skipped)


def query_calendars(get_source: Callable[[], EventSource], *, prompt: bool) -> list[CalendarInfo]:
    source = get_source()
    _require_access(source, prompt=prompt)
    return _mapping.to_calendars(source.calendars())


def authorization_status(get_source: Callable[[], EventSource]) -> AccessStatus:
    return _mapping.access_status_from_int(get_source().authorization_status())


def request_access(get_source: Callable[[], EventSource], timeout: float) -> AccessStatus:
    return _mapping.access_status_from_int(get_source().request_access(timeout))
