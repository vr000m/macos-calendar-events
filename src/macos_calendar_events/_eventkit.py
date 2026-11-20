"""EventKit adapter: EventKit objects -> plain ``Raw*`` records. Read-only (R10).

The only module that imports PyObjC (R14), always lazily. Getters only: decisions live
in ``_mapping`` and waiting lives in ``_access``. Every PyObjC selector call with
arguments here is listed in ``scripts/eventkit_selectors.allow``.
"""

from __future__ import annotations

import platform
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import _access, _mapping
from ._raw import RawCalendar, RawEvent, RawParticipant
from .errors import EventKitUnavailableError
from .models import AccessStatus

FULL_ACCESS_SELECTOR = "requestFullAccessToEventsWithCompletion:"
LocalComponents = tuple[int, int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class EventKitNamespace:
    """Everything class-level the adapter needs; tests inject a stub."""

    store_class: Any  # EKEventStore
    entity_type_event: int  # EKEntityTypeEvent
    new_store: Callable[[], Any]  # EKEventStore.alloc().init()
    make_date: Callable[[float], Any]  # epoch seconds -> NSDate
    local_components: Callable[[Any], LocalComponents]  # NSDate -> system-zone (Y, M, D, h, m, s)
    to_srgb: Callable[[Any], tuple[float, float, float] | None]  # NSColor -> sRGB floats


def _load_namespace() -> EventKitNamespace:
    """Build the namespace from the real modules; raises ImportError without PyObjC."""
    import AppKit
    import EventKit
    import Foundation

    units = (
        Foundation.NSCalendarUnitYear
        | Foundation.NSCalendarUnitMonth
        | Foundation.NSCalendarUnitDay
        | Foundation.NSCalendarUnitHour
        | Foundation.NSCalendarUnitMinute
        | Foundation.NSCalendarUnitSecond
    )

    def make_date(seconds: float) -> Any:
        return Foundation.NSDate.dateWithTimeIntervalSince1970_(seconds)

    def local_components(ns_date: Any) -> LocalComponents:
        # Always Gregorian: ``currentCalendar`` follows the user's calendar preference, so a
        # Buddhist, Japanese, Hebrew or Islamic setting would yield non-Gregorian Y/M/D.
        # Built per call, as ``currentCalendar`` was: a calendar fixes its time zone (the
        # default zone) when it is created, and R3 places all-day dates in the zone at
        # query time, so a cached calendar would go stale after a time zone change.
        gregorian = Foundation.NSCalendar.calendarWithIdentifier_(
            Foundation.NSCalendarIdentifierGregorian
        )
        c = gregorian.components_fromDate_(units, ns_date)
        return (
            int(c.year()),
            int(c.month()),
            int(c.day()),
            int(c.hour()),
            int(c.minute()),
            int(c.second()),
        )

    def to_srgb(color: Any) -> tuple[float, float, float] | None:
        if color is None:
            return None
        try:
            converted = color.colorUsingColorSpace_(AppKit.NSColorSpace.sRGBColorSpace())
            if converted is None:
                return None
            return (
                float(converted.redComponent()),
                float(converted.greenComponent()),
                float(converted.blueComponent()),
            )
        except Exception:
            return None

    return EventKitNamespace(
        store_class=EventKit.EKEventStore,
        entity_type_event=int(EventKit.EKEntityTypeEvent),
        new_store=lambda: EventKit.EKEventStore.alloc().init(),
        make_date=make_date,
        local_components=local_components,
        to_srgb=to_srgb,
    )


def _text(value: Any) -> str | None:
    # Every text NSString crosses the Raw* boundary as valid Unicode (no lone surrogates).
    return None if value is None else _mapping.unicode_text(str(value))


def _identifier(value: Any) -> str | None:
    # Calendar identifiers are lookup keys (calendarWithIdentifier_), so they cross unchanged;
    # _mapping cleans them where they become output.
    return None if value is None else str(value)


def _epoch(ns_date: Any) -> float | None:
    return None if ns_date is None else float(ns_date.timeIntervalSince1970())


def _url_text(url: Any) -> str | None:
    return None if url is None else _text(url.absoluteString())


def _participant(p: Any) -> RawParticipant:
    return RawParticipant(
        name=_text(p.name()),
        url=_url_text(p.URL()),
        role=int(p.participantRole()),
        status=int(p.participantStatus()),
        type=int(p.participantType()),
        is_current_user=bool(p.isCurrentUser()),
    )


class EventKitSource:
    """``EventSource`` over a lazily created ``EKEventStore``."""

    def __init__(self, ek: EventKitNamespace | None = None) -> None:
        self._ek = ek if ek is not None else _load_namespace()
        self._store: Any = None

    def _get_store(self) -> Any:
        if self._store is None:
            self._store = self._ek.new_store()
        return self._store

    def authorization_status(self) -> int:
        ek = self._ek
        return int(ek.store_class.authorizationStatusForEntityType_(ek.entity_type_event))

    def request_access(self, timeout: float) -> int:
        store = self._get_store()

        def request(completion: Callable[[bool, object | None], None]) -> None:
            store.requestFullAccessToEventsWithCompletion_(completion)

        status = _access.wait_for_access(request, self.authorization_status, timeout)
        if _mapping.access_status_from_int(status) is AccessStatus.FULL_ACCESS:
            # A store created before the grant is discarded, never reset (D7).
            self._store = None
        return status

    def calendars(self) -> Sequence[RawCalendar]:
        store = self._get_store()
        found = store.calendarsForEntityType_(self._ek.entity_type_event) or ()
        return [self._calendar(c) for c in found]

    def _calendar(self, cal: Any) -> RawCalendar:
        source = cal.source()
        return RawCalendar(
            id=str(cal.calendarIdentifier()),  # lossless: events() looks it up again
            title=_text(cal.title()),
            source_title=None if source is None else _text(source.title()),
            source_type=-1 if source is None else int(source.sourceType()),
            color_rgb=self._ek.to_srgb(cal.color()),
            allows_modifications=bool(cal.allowsContentModifications()),
        )

    def events(
        self, start: datetime, end: datetime, calendar_ids: Sequence[str] | None
    ) -> Sequence[RawEvent]:
        """Events for exactly ``[start, end]`` (``_api`` already widened the range)."""
        store = self._get_store()
        calendars: list[Any] | None = None
        if calendar_ids is not None:
            calendars = []
            for identifier in calendar_ids:
                cal = store.calendarWithIdentifier_(identifier)
                if cal is not None:
                    calendars.append(cal)
            if not calendars:
                return []
        ek = self._ek
        predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
            ek.make_date(start.timestamp()), ek.make_date(end.timestamp()), calendars
        )
        found = store.eventsMatchingPredicate_(predicate) or ()
        return [self._event(e) for e in found]

    def _event(self, ev: Any) -> RawEvent:
        cal = ev.calendar()
        all_day = bool(ev.isAllDay())
        start_date, end_date = ev.startDate(), ev.endDate()
        start_local = end_local = None
        if all_day and start_date is not None and end_date is not None:
            start_local = self._ek.local_components(start_date)
            end_local = self._ek.local_components(end_date)
        zone = ev.timeZone()
        organizer = ev.organizer()
        return RawEvent(
            calendar_id=None if cal is None else _identifier(cal.calendarIdentifier()),
            external_id=_text(ev.calendarItemExternalIdentifier()),
            event_identifier=_text(ev.eventIdentifier()),
            title=_text(ev.title()),
            start_epoch=_epoch(start_date),
            end_epoch=_epoch(end_date),
            occurrence_epoch=_epoch(ev.occurrenceDate()),
            all_day=all_day,
            start_local=start_local,
            end_local=end_local,
            time_zone=None if zone is None else _text(zone.name()),
            location=_text(ev.location()),
            url=_url_text(ev.URL()),
            notes=_text(ev.notes()),
            status=int(ev.status()),
            has_recurrence_rules=bool(ev.hasRecurrenceRules()),
            is_detached=bool(ev.isDetached()),
            organizer=None if organizer is None else _participant(organizer),
            attendees=tuple(_participant(p) for p in (ev.attendees() or ())),
        )


_default: EventKitSource | None = None


def default_source() -> EventKitSource:
    """The process-wide source; raises ``EventKitUnavailableError`` when EventKit can't be
    used (not macOS, PyObjC missing, or macOS older than 14 by feature detection, R19)."""
    global _default
    if _default is not None:
        return _default
    if sys.platform != "darwin":
        raise EventKitUnavailableError(
            f"EventKit requires macOS 14 or newer (platform: {sys.platform})"
        )
    try:
        ek = _load_namespace()
    except ImportError:
        raise EventKitUnavailableError("PyObjC EventKit bindings are not installed") from None
    if not ek.store_class.instancesRespondToSelector_(FULL_ACCESS_SELECTOR):
        version = platform.mac_ver()[0] or "unknown"
        raise EventKitUnavailableError(f"macOS 14 or newer is required (found macOS {version})")
    _default = EventKitSource(ek)
    return _default


def _clear_default_source() -> None:
    global _default
    _default = None
