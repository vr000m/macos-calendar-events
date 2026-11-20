"""Timestamps for events in Europe/Helsinki, Asia/Kolkata and Asia/Tokyo.

Expected UTC strings and epoch seconds are hand-written (cross-checked with
``TZ=<zone> /bin/date``), never computed by project code. All-day rows carry the
local components the adapter would capture on a Mac whose system zone is that zone.
"""

import dataclasses
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

import pytest

from macos_calendar_events import _api
from macos_calendar_events._raw import RawEvent
from macos_calendar_events.models import Event
from tests.fakes import FakeSource, raw_event, utc


def query(events: Sequence[RawEvent], start: str, end: str) -> list[Event]:
    source = FakeSource(events=events)
    return _api.query_events(
        lambda: source, utc(start), utc(end), calendars=None, include_notes=False, prompt=False
    ).events


def all_day(start_z: str, end_z: str, day: tuple[int, int, int], **kw: Any) -> RawEvent:
    return raw_event(
        start_z,
        end_z,
        all_day=True,
        time_zone=None,
        start_local=(*day, 0, 0, 0),
        end_local=(*day, 23, 59, 59),
        **kw,
    )


def times(event: Event) -> tuple[str, int, str, int]:
    out = event.to_dict()
    return (out["start"], out["start_ts"], out["end"], out["end_ts"])  # type: ignore[return-value]


# --- timed events: local date vs UTC date, half-hour offset, EU DST ------------------


@pytest.mark.parametrize(
    ("label", "start", "end", "tz", "expected"),
    [
        # Tokyo 2025-11-20 07:30-08:30 JST is still 2025-11-19 in UTC.
        (
            "tokyo-early-morning",
            "2025-11-19T22:30:00Z",
            "2025-11-19T23:30:00Z",
            "Asia/Tokyo",
            ("2025-11-19T22:30:00Z", 1763591400, "2025-11-19T23:30:00Z", 1763595000),
        ),
        # Kolkata +05:30: 09:15-10:00 IST.
        (
            "kolkata-half-hour",
            "2025-11-20T03:45:00Z",
            "2025-11-20T04:30:00Z",
            "Asia/Kolkata",
            ("2025-11-20T03:45:00Z", 1763610300, "2025-11-20T04:30:00Z", 1763613000),
        ),
        # Helsinki spring forward 2026-03-29: 02:30 EET -> 04:30 EEST is one real hour.
        (
            "helsinki-spring-forward",
            "2026-03-29T00:30:00Z",
            "2026-03-29T01:30:00Z",
            "Europe/Helsinki",
            ("2026-03-29T00:30:00Z", 1774744200, "2026-03-29T01:30:00Z", 1774747800),
        ),
        # Helsinki fall back 2026-10-25: 03:30 EEST -> 03:30 EET (same wall time), one hour.
        (
            "helsinki-fall-back",
            "2026-10-25T00:30:00Z",
            "2026-10-25T01:30:00Z",
            "Europe/Helsinki",
            ("2026-10-25T00:30:00Z", 1792888200, "2026-10-25T01:30:00Z", 1792891800),
        ),
    ],
)
def test_timed_event_instants(
    label: str, start: str, end: str, tz: str, expected: tuple[str, int, str, int]
) -> None:
    [event] = query([raw_event(start, end, time_zone=tz)], start, end)
    assert times(event) == expected
    assert event.time_zone == tz
    assert event.start_date is None and event.end_date is None
    assert event.to_dict()["occurrence_start_ts"] == expected[1]


def test_tokyo_morning_matches_a_utc_window_on_the_previous_day() -> None:
    row = raw_event("2025-11-19T22:30:00Z", "2025-11-19T23:30:00Z", time_zone="Asia/Tokyo")
    # A UTC window on 2025-11-19 finds it; one on 2025-11-20 does not.
    assert len(query([row], "2025-11-19T22:00:00Z", "2025-11-20T00:00:00Z")) == 1
    assert query([row], "2025-11-20T00:00:00Z", "2025-11-20T02:00:00Z") == []


# --- all-day events: local midnight instants, exclusive end_date --------------------


@pytest.mark.parametrize(
    ("label", "start_z", "end_inclusive_z", "day", "expected", "dates", "length"),
    [
        (
            "tokyo",
            "2025-11-19T15:00:00Z",
            "2025-11-20T14:59:59Z",
            (2025, 11, 20),
            ("2025-11-19T15:00:00Z", 1763564400, "2025-11-20T15:00:00Z", 1763650800),
            (date(2025, 11, 20), date(2025, 11, 21)),
            timedelta(hours=24),
        ),
        (
            "kolkata",
            "2025-11-19T18:30:00Z",
            "2025-11-20T18:29:59Z",
            (2025, 11, 20),
            ("2025-11-19T18:30:00Z", 1763577000, "2025-11-20T18:30:00Z", 1763663400),
            (date(2025, 11, 20), date(2025, 11, 21)),
            timedelta(hours=24),
        ),
        (
            "helsinki",
            "2025-11-19T22:00:00Z",
            "2025-11-20T21:59:59Z",
            (2025, 11, 20),
            ("2025-11-19T22:00:00Z", 1763589600, "2025-11-20T22:00:00Z", 1763676000),
            (date(2025, 11, 20), date(2025, 11, 21)),
            timedelta(hours=24),
        ),
        (
            "helsinki-spring-forward-23h",
            "2026-03-28T22:00:00Z",
            "2026-03-29T20:59:59Z",
            (2026, 3, 29),
            ("2026-03-28T22:00:00Z", 1774735200, "2026-03-29T21:00:00Z", 1774818000),
            (date(2026, 3, 29), date(2026, 3, 30)),
            timedelta(hours=23),
        ),
        (
            "helsinki-fall-back-25h",
            "2026-10-24T21:00:00Z",
            "2026-10-25T21:59:59Z",
            (2026, 10, 25),
            ("2026-10-24T21:00:00Z", 1792875600, "2026-10-25T22:00:00Z", 1792965600),
            (date(2026, 10, 25), date(2026, 10, 26)),
            timedelta(hours=25),
        ),
    ],
)
def test_all_day_in_zone(
    label: str,
    start_z: str,
    end_inclusive_z: str,
    day: tuple[int, int, int],
    expected: tuple[str, int, str, int],
    dates: tuple[date, date],
    length: timedelta,
) -> None:
    [event] = query([all_day(start_z, end_inclusive_z, day)], start_z, expected[2])
    assert times(event) == expected  # start = local midnight, end = next local midnight
    assert (event.start_date, event.end_date) == dates  # end_date exclusive
    assert event.end - event.start == length
    assert event.to_dict()["start_date"] == dates[0].isoformat()


# --- window edges and widen-then-filter ---------------------------------------------

HELSINKI_DAY = ("2026-03-28T22:00:00Z", "2026-03-29T21:00:00Z")  # local 2026-03-29 (23 h)


def test_helsinki_dst_day_window_edges() -> None:
    previous_day = all_day(
        "2026-03-27T22:00:00Z", "2026-03-28T21:59:59Z", (2026, 3, 28), external_id="prev"
    )
    the_day = all_day(
        "2026-03-28T22:00:00Z", "2026-03-29T20:59:59Z", (2026, 3, 29), external_id="day"
    )
    next_day = all_day(
        "2026-03-29T21:00:00Z", "2026-03-30T20:59:59Z", (2026, 3, 30), external_id="next"
    )
    ends_at_start = raw_event(
        "2026-03-28T21:00:00Z", "2026-03-28T22:00:00Z", external_id="ends-at-start"
    )
    starts_at_end = raw_event(
        "2026-03-29T21:00:00Z", "2026-03-29T22:00:00Z", external_id="starts-at-end"
    )
    last_minute = raw_event(
        "2026-03-29T20:59:00Z", "2026-03-29T21:00:00Z", external_id="last-minute"
    )
    rows = [previous_day, the_day, next_day, ends_at_start, starts_at_end, last_minute]
    events = query(rows, *HELSINKI_DAY)
    assert [e.external_id for e in events] == ["day", "last-minute"]


@pytest.mark.parametrize(
    ("window", "inside", "outside"),
    [
        # Tokyo all-day 2025-11-20 vs 2025-11-21 around a UTC window on 2025-11-20.
        (
            ("2025-11-20T00:00:00Z", "2025-11-20T01:00:00Z"),
            all_day("2025-11-19T15:00:00Z", "2025-11-20T14:59:59Z", (2025, 11, 20)),
            all_day("2025-11-20T15:00:00Z", "2025-11-21T14:59:59Z", (2025, 11, 21)),
        ),
        # Kolkata all-day 2025-11-20 vs 2025-11-21 around a UTC window on 2025-11-20.
        (
            ("2025-11-20T16:00:00Z", "2025-11-20T17:00:00Z"),
            all_day("2025-11-19T18:30:00Z", "2025-11-20T18:29:59Z", (2025, 11, 20)),
            all_day("2025-11-20T18:30:00Z", "2025-11-21T18:29:59Z", (2025, 11, 21)),
        ),
        # Helsinki all-day 2026-03-29 (DST day) vs 2026-03-28 around a UTC window.
        (
            ("2026-03-28T22:00:00Z", "2026-03-28T23:00:00Z"),
            all_day("2026-03-28T22:00:00Z", "2026-03-29T20:59:59Z", (2026, 3, 29)),
            all_day("2026-03-27T22:00:00Z", "2026-03-28T21:59:59Z", (2026, 3, 28)),
        ),
    ],
)
def test_widen_then_filter(window: tuple[str, str], inside: RawEvent, outside: RawEvent) -> None:
    inside = dataclasses.replace(inside, external_id="in")
    outside = dataclasses.replace(outside, external_id="out")
    source = FakeSource(events=[inside, outside])
    events = _api.query_events(
        lambda: source,
        utc(window[0]),
        utc(window[1]),
        calendars=None,
        include_notes=False,
        prompt=False,
    ).events
    q_start, q_end, _ = source.ranges[0]
    assert (q_start, q_end) == (
        utc(window[0]) - timedelta(days=1),
        utc(window[1]) + timedelta(days=1),
    )
    fetched = {r.external_id for r in source.events(q_start, q_end, None)}
    assert fetched == {"in", "out"}  # both fetched by the widened query
    assert [e.external_id for e in events] == ["in"]  # strict overlap keeps one
