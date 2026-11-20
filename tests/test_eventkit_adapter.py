"""Adapter branches against stub EventKit objects; conversions against real Foundation
objects on macOS (no store, no TCC)."""

import subprocess
import sys
import time
from datetime import UTC, datetime
from typing import Any

import pytest

from macos_calendar_events._eventkit import EventKitSource
from tests.ek_stubs import Factory, Obj, StubStore, StubStoreClass, calendar, event, namespace

START = datetime(2025, 11, 18, 16, 0, tzinfo=UTC)
END = datetime(2025, 11, 20, 17, 0, tzinfo=UTC)


def _source(
    calendars: list[Any] | None = None,
    events: list[Any] | None = None,
    store_class: StubStoreClass | None = None,
    on_request: Any = None,
) -> tuple[EventKitSource, Factory]:
    cals = calendars if calendars is not None else [calendar("cal-1")]
    factory = Factory(lambda: StubStore(cals, events or [], on_request))
    return EventKitSource(namespace(factory, store_class)), factory


def test_store_is_created_lazily() -> None:
    source, factory = _source()
    assert factory.built == []
    source.calendars()
    source.calendars()
    assert len(factory.built) == 1


def test_authorization_status_returns_raw_int() -> None:
    source, factory = _source(store_class=StubStoreClass(status=2))
    assert source.authorization_status() == 2
    assert factory.built == []  # a class-level call, no store needed


def test_request_access_without_callback_returns_current_status_within_timeout() -> None:
    source, _ = _source(store_class=StubStoreClass(status=0))
    started = time.monotonic()
    assert source.request_access(0.2) == 0
    assert time.monotonic() - started < 0.2 + 0.5


def test_fresh_store_after_grant() -> None:
    store_class = StubStoreClass(status=0)

    def grant(completion: Any) -> None:
        store_class.status = 3
        completion(True, None)

    source, factory = _source(store_class=store_class, on_request=grant)
    assert source.request_access(1.0) == 3
    source.calendars()
    assert len(factory.built) == 2  # the pre-grant store is discarded, never reset
    assert factory.built[0].requests == 1


def test_no_new_store_after_denial() -> None:
    store_class = StubStoreClass(status=0)

    def deny(completion: Any) -> None:
        store_class.status = 2
        completion(False, None)

    source, factory = _source(store_class=store_class, on_request=deny)
    assert source.request_access(1.0) == 2
    source.calendars()
    assert len(factory.built) == 1


def test_calendar_ids_resolve_to_selected_calendars_only() -> None:
    work, home, other = calendar("cal-1"), calendar("cal-2", "Home"), calendar("cal-3")
    source, factory = _source(calendars=[work, home, other])
    source.events(START, END, ["cal-2", "unknown-id", "cal-1"])
    [(_, _, passed)] = factory.built[0].predicates
    assert passed == [home, work]  # unknown id skipped


def test_all_calendars_passes_none() -> None:
    source, factory = _source()
    source.events(START, END, None)
    assert factory.built[0].predicates[0][2] is None


def test_predicate_gets_the_exact_range() -> None:
    source, factory = _source()
    source.events(START, END, None)
    start, end, _ = factory.built[0].predicates[0]
    assert (start, end) == (START.timestamp(), END.timestamp())


def test_unresolvable_ids_return_empty_without_querying() -> None:
    source, factory = _source()
    assert source.events(START, END, ["missing"]) == []
    assert factory.built[0].predicates == []


def test_common_nil_shapes() -> None:
    cal = calendar("cal-1")
    source, _ = _source(events=[event(cal, attendees=None, organizer=None, timeZone=None)])
    [raw] = source.events(START, END, None)
    assert raw.attendees == ()
    assert raw.organizer is None
    assert raw.time_zone is None
    assert raw.calendar_id == "cal-1"
    assert raw.start_local is None  # timed event


def test_event_getters() -> None:
    cal = calendar("cal-1")
    person = Obj(
        name="Sam Example",
        URL=Obj(absoluteString="mailto:sam@example.com"),
        participantRole=1,
        participantStatus=2,
        participantType=1,
        isCurrentUser=True,
    )
    row = event(
        cal,
        organizer=person,
        attendees=[person],
        URL=Obj(absoluteString="https://example.com/e/1"),
        isAllDay=True,
        timeZone=None,
        calendar=None,
    )
    source, _ = _source(events=[row])
    [raw] = source.events(START, END, None)
    assert raw.calendar_id is None
    assert raw.url == "https://example.com/e/1"
    assert raw.organizer is not None and raw.organizer.url == "mailto:sam@example.com"
    assert raw.attendees[0].is_current_user is True
    assert (raw.start_local, raw.end_local) == ((2025, 11, 20, 0, 0, 0), (2025, 11, 20, 0, 0, 0))
    assert (raw.start_epoch, raw.end_epoch) == (1763568000.0, 1763569800.0)


def test_calendar_getters() -> None:
    no_source = calendar("cal-2", "Orphan", source=None)
    source, _ = _source(calendars=[calendar("cal-1"), no_source])
    first, second = source.calendars()
    assert (first.id, first.title, first.source_title, first.source_type) == (
        "cal-1",
        "Work",
        "iCloud",
        2,
    )
    assert first.color_rgb == (1.0, 0.0, 0.0)
    assert first.allows_modifications is True
    assert (second.source_title, second.source_type) == (None, -1)


# --- real Foundation conversions (macOS only; no store is created) ---------------------

darwin = pytest.mark.skipif(sys.platform != "darwin", reason="needs PyObjC Foundation")


@darwin
def test_nsdate_to_epoch_floats() -> None:
    foundation: Any = pytest.importorskip("Foundation")
    from macos_calendar_events._eventkit import _epoch

    frac = foundation.NSDate.dateWithTimeIntervalSince1970_(1700000000.25)
    old = foundation.NSDate.dateWithTimeIntervalSince1970_(-12345.5)
    assert _epoch(frac) == 1700000000.25
    assert _epoch(old) == -12345.5
    assert _epoch(None) is None


@darwin
def test_non_rgb_color_converts_to_srgb_or_none() -> None:
    appkit: Any = pytest.importorskip("AppKit")
    from macos_calendar_events._eventkit import _load_namespace

    ns = _load_namespace()
    gray = appkit.NSColor.colorWithCalibratedWhite_alpha_(0.5, 1.0)
    rgb = ns.to_srgb(gray)
    assert rgb is None or (len(rgb) == 3 and all(0.0 <= c <= 1.0 for c in rgb))
    assert ns.to_srgb(None) is None
    blue = appkit.NSColor.colorWithSRGBRed_green_blue_alpha_(0.0, 0.5, 1.0, 1.0)
    got = ns.to_srgb(blue)
    assert got is not None
    assert [round(c, 3) for c in got] == [0.0, 0.5, 1.0]


@darwin
def test_local_components_are_gregorian_whatever_the_user_calendar() -> None:
    # A Mac set to a Buddhist calendar: ``currentCalendar`` would report year 2568.
    code = (
        "from macos_calendar_events._eventkit import _load_namespace\n"
        "ns = _load_namespace()\n"
        "print(ns.local_components(ns.make_date(1763568000.0))[:2])\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code, "-AppleLocale", "th_TH@calendar=buddhist"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "(2025, 11)"


@darwin
def test_local_components_for_all_day_event() -> None:
    from macos_calendar_events._eventkit import _load_namespace

    real = _load_namespace()
    start, end = 1763625600.0, 1763711999.0
    expected = [datetime.fromtimestamp(t).timetuple()[:6] for t in (start, end)]
    cal = calendar("cal-1")
    row = event(
        cal,
        isAllDay=True,
        startDate=real.make_date(start),
        endDate=real.make_date(end),
        occurrenceDate=real.make_date(start),
    )
    factory = Factory(lambda: StubStore([cal], [row]))
    ns = namespace(factory, local_components=real.local_components, make_date=real.make_date)
    [raw] = EventKitSource(ns).events(START, END, None)
    assert [raw.start_local, raw.end_local] == [tuple(e) for e in expected]
