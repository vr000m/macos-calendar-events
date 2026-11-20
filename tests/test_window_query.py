"""Window queries through ``_api.query_events`` against a FakeSource (R1, R3-R5, R8, R12, R13).

Expected values are hand-written from the spec.
"""

import dataclasses
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest

from macos_calendar_events import _api
from macos_calendar_events._mapping import (
    epoch_to_utc,
    normalize_all_day,
    parse_instant,
    parse_instant_text,
    validate_window,
)
from macos_calendar_events._raw import RawCalendar, RawEvent
from macos_calendar_events.errors import InvalidQueryError
from macos_calendar_events.models import (
    Event,
    EventStatus,
    ParticipantType,
    ParticipationStatus,
)
from tests.fakes import FakeSource, raw_calendar, raw_event, raw_participant, ts, utc

W_START = "2025-11-19T16:00:00Z"
W_END = "2025-11-19T17:00:00Z"


def query(
    events: Sequence[RawEvent],
    start: str = W_START,
    end: str = W_END,
    *,
    calendars: Sequence[RawCalendar] = (),
    include_notes: bool = False,
) -> _api.QueryResult:
    source = FakeSource(events=events, calendars=calendars)
    return _api.query_events(
        lambda: source,
        utc(start),
        utc(end),
        calendars=None,
        include_notes=include_notes,
        prompt=False,
    )


def only(events: Sequence[RawEvent], **kw: Any) -> Event:
    result = query(events, **kw)
    assert len(result.events) == 1
    return result.events[0]


# --- overlap -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end", "included"),
    [
        ("2025-11-19T15:00:00Z", "2025-11-19T16:00:00Z", False),  # ends at window start
        ("2025-11-19T17:00:00Z", "2025-11-19T18:00:00Z", False),  # starts at window end
        ("2025-11-19T15:00:00Z", "2025-11-19T18:00:00Z", True),  # spans the window
        ("2025-11-19T16:00:00Z", "2025-11-19T16:00:00Z", True),  # zero-length at start
        ("2025-11-19T17:00:00Z", "2025-11-19T17:00:00Z", False),  # zero-length at end
        ("2025-11-19T16:59:59Z", "2025-11-19T17:30:00Z", True),
    ],
)
def test_overlap_edges(start: str, end: str, included: bool) -> None:
    assert len(query([raw_event(start, end)]).events) == int(included)


# --- recurring -----------------------------------------------------------------------


def _series(start: str, end: str, **kw: Any) -> RawEvent:
    return raw_event(start, end, external_id="series-1", event_identifier="evt-s", **kw)


def test_recurring_occurrences() -> None:
    a = _series("2025-11-19T16:00:00Z", "2025-11-19T16:10:00Z", has_recurrence_rules=True)
    b = _series("2025-11-19T16:30:00Z", "2025-11-19T16:40:00Z", has_recurrence_rules=True)
    b = _replace(b, occurrence_epoch=ts("2025-11-19T16:30:00Z"))
    first, second = query([a, b]).events
    assert first.id != second.id
    assert first.event_identifier == second.event_identifier == "evt-s"
    assert first.external_id == second.external_id == "series-1"
    assert first.is_recurring and second.is_recurring


def test_detached_occurrence_id_is_distinct_and_stable() -> None:
    sibling = _series("2025-11-19T16:00:00Z", "2025-11-19T16:10:00Z", has_recurrence_rules=True)
    detached = _series(
        "2025-11-19T16:20:00Z",
        "2025-11-19T16:30:00Z",
        occurrence_epoch=ts("2025-11-19T16:00:00Z"),
        is_detached=True,
    )
    run1 = query([sibling, detached]).events
    run2 = query([sibling, detached]).events
    assert run1[0].id != run1[1].id
    assert [e.id for e in run1] == [e.id for e in run2]
    assert run1[1].is_detached and run1[1].is_recurring  # hasRecurrenceRules or isDetached
    assert run1[1].occurrence_start == utc("2025-11-19T16:00:00Z")


def test_nil_occurrence_date_falls_back_to_start() -> None:
    event = only([raw_event(occurrence_epoch=None)])
    assert event.occurrence_start == event.start == utc(W_START)


# --- all-day ------------------------------------------------------------------------


def _replace(raw: RawEvent, **kw: Any) -> RawEvent:
    return dataclasses.replace(raw, **kw)


def test_all_day_single_day_midnight_to_midnight() -> None:
    got = normalize_all_day(
        ts("2025-11-20T08:00:00Z"),
        ts("2025-11-21T08:00:00Z"),
        (2025, 11, 20, 0, 0, 0),
        (2025, 11, 21, 0, 0, 0),
    )
    assert got == (
        utc("2025-11-20T08:00:00Z"),
        utc("2025-11-21T08:00:00Z"),
        date(2025, 11, 20),
        date(2025, 11, 21),
    )


def test_all_day_three_days_inclusive_end() -> None:
    got = normalize_all_day(
        ts("2025-11-20T08:00:00Z"),
        ts("2025-11-23T07:59:59Z"),
        (2025, 11, 20, 0, 0, 0),
        (2025, 11, 22, 23, 59, 59),
    )
    assert got == (
        utc("2025-11-20T08:00:00Z"),
        utc("2025-11-23T08:00:00Z"),
        date(2025, 11, 20),
        date(2025, 11, 23),
    )


def test_all_day_inclusive_end_becomes_next_midnight() -> None:
    _, end, _, end_date = normalize_all_day(
        ts("2025-11-20T08:00:00Z"),
        ts("2025-11-21T07:59:59Z"),
        (2025, 11, 20, 0, 0, 0),
        (2025, 11, 20, 23, 59, 59),
    )
    assert end == utc("2025-11-21T08:00:00Z")
    assert end_date == date(2025, 11, 21)


def test_all_day_dst_spring_forward_day_is_23_hours() -> None:
    # America/Los_Angeles 2026-03-08: 00:00 PST = 08:00Z; 23:59:59 PDT = 06:59:59Z next day.
    start, end, start_date, end_date = normalize_all_day(
        ts("2026-03-08T08:00:00Z"),
        ts("2026-03-09T06:59:59Z"),
        (2026, 3, 8, 0, 0, 0),
        (2026, 3, 8, 23, 59, 59),
    )
    assert (start_date, end_date) == (date(2026, 3, 8), date(2026, 3, 9))
    assert end - start == timedelta(hours=23)


def test_all_day_dates_come_from_local_components() -> None:
    # Asia/Kolkata 2025-11-20 00:00 IST = 2025-11-19T18:30Z (UTC date differs).
    start, end, start_date, end_date = normalize_all_day(
        ts("2025-11-19T18:30:00Z"),
        ts("2025-11-20T18:29:59Z"),
        (2025, 11, 20, 0, 0, 0),
        (2025, 11, 20, 23, 59, 59),
    )
    assert start.date() == date(2025, 11, 19)
    assert start_date == date(2025, 11, 20)
    assert end_date == date(2025, 11, 21)
    assert end == utc("2025-11-20T18:30:00Z")


def _all_day(day: int, *, start_z: str, end_z: str) -> RawEvent:
    return raw_event(
        start_z,
        end_z,
        all_day=True,
        time_zone=None,
        start_local=(2025, 11, day, 0, 0, 0),
        end_local=(2025, 11, day, 23, 59, 59),
        external_id=f"day-{day}",
    )


def test_all_day_rows_at_window_edges() -> None:
    # Window = local day 2025-11-20 in Los Angeles: [08:00Z, next 08:00Z).
    before = _all_day(19, start_z="2025-11-19T08:00:00Z", end_z="2025-11-20T07:59:59Z")
    inside = _all_day(20, start_z="2025-11-20T08:00:00Z", end_z="2025-11-21T07:59:59Z")
    after = _all_day(21, start_z="2025-11-21T08:00:00Z", end_z="2025-11-22T07:59:59Z")
    result = query([before, inside, after], "2025-11-20T08:00:00Z", "2025-11-21T08:00:00Z")
    assert [e.external_id for e in result.events] == ["day-20"]
    event = result.events[0]
    assert event.all_day
    assert event.time_zone is None
    assert (event.start_date, event.end_date) == (date(2025, 11, 20), date(2025, 11, 21))
    assert event.to_dict()["end"] == "2025-11-21T08:00:00Z"


def test_timed_events_have_no_dates() -> None:
    event = only([raw_event()])
    assert event.start_date is None and event.end_date is None
    assert not event.all_day


# --- floating and DST ----------------------------------------------------------------


def test_floating_timed_event() -> None:
    event = only([raw_event(time_zone=None)])
    assert event.time_zone is None
    assert event.start_date is None
    assert event.to_dict()["start"] == "2025-11-19T16:00:00Z"


# LA spring-forward 01:30 PST -> 03:30 PDT; fall-back 01:30 PDT -> 01:30 PST; a non-IANA zone.
@pytest.mark.parametrize(
    ("start", "end", "tz"),
    [
        (
            "2026-03-08T09:30:00Z",
            "2026-03-08T10:30:00Z",
            "America/Los_Angeles",
        ),
        (
            "2026-11-01T08:30:00Z",
            "2026-11-01T09:30:00Z",
            "America/Los_Angeles",
        ),
        ("2026-03-08T09:30:00Z", "2026-03-08T10:30:00Z", "GMT+0530"),
    ],
)
def test_dst_boundaries_keep_utc_instants(start: str, end: str, tz: str) -> None:
    event = only([raw_event(start, end, time_zone=tz)], start=start, end=end)
    out = event.to_dict()
    assert (out["start"], out["end"]) == (start, end)
    assert event.end - event.start == timedelta(hours=1)
    assert event.time_zone == tz


# --- declined, self rows, attendees ---------------------------------------------------


def test_declined_and_canceled_are_returned() -> None:
    me = raw_participant(is_current_user=True, status=3)
    declined = raw_event(attendees=(me,), external_id="d")
    canceled = raw_event(status=3, external_id="c", start_epoch=ts("2025-11-19T16:05:00Z"))
    first, second = query([declined, canceled]).events
    assert first.self_status is ParticipationStatus.DECLINED
    assert second.status is EventStatus.CANCELED


def test_self_status_none_without_self_attendee() -> None:
    assert only([raw_event(attendees=(raw_participant(),))]).self_status is None


def test_first_self_attendee_wins() -> None:
    a = raw_participant(is_current_user=True, status=4)
    b = raw_participant(is_current_user=True, status=2)
    assert only([raw_event(attendees=(raw_participant(), a, b))]).self_status is (
        ParticipationStatus.TENTATIVE
    )


def test_attendee_shapes() -> None:
    web = raw_participant(url="https://example.com/people/1")
    mail = raw_participant(url="mailto:pat@example.org")
    nameless = raw_participant(name=None)
    room = raw_participant(type=2, name="Room 1", url="urn:x-room:1")
    schemeless = raw_participant(url="example.com/people/2")
    event = only([raw_event(attendees=(web, mail, nameless, room, schemeless))])
    w, m, n, r, s = event.attendees
    assert (w.email, w.url) == (None, "https://example.com/people/1")
    assert (m.email, m.url) == ("pat@example.org", None)
    assert n.name is None
    assert r.type is ParticipantType.ROOM
    assert (s.email, s.url) == (None, "example.com/people/2")


def test_organizer_only_and_organizer_in_attendees() -> None:
    organizer = raw_participant(name="Org", role=3)
    alone = only([raw_event(organizer=organizer, attendees=())])
    assert alone.attendees == ()
    assert alone.organizer is not None and alone.organizer.name == "Org"
    both = only([raw_event(organizer=organizer, attendees=(organizer, raw_participant()))])
    assert both.organizer == both.attendees[0]
    assert len(both.attendees) == 2  # no dedupe


def test_nil_attendees_and_organizer() -> None:
    event = only([raw_event(organizer=None, attendees=())])
    assert event.attendees == ()
    assert event.organizer is None
    assert event.to_dict()["attendees"] == []


# --- nulls, skips --------------------------------------------------------------------


def test_nil_identity_fields_are_null_and_ids_unique() -> None:
    a = raw_event(title=None, event_identifier=None, external_id=None)
    b = raw_event(
        title=None,
        event_identifier=None,
        external_id=None,
        start_epoch=ts("2025-11-19T16:10:00Z"),
    )
    first, second = query([a, b]).events
    out = first.to_dict()
    assert (out["title"], out["event_identifier"], out["external_id"]) == (None, None, None)
    assert first.id != second.id


def test_rows_with_nil_start_end_or_calendar_are_skipped() -> None:
    keep = raw_event(occurrence_epoch=None, external_id="keep")
    rows = [
        raw_event(start_epoch=None),
        raw_event(end_epoch=None),
        raw_event(calendar_id=None),
        keep,
    ]
    result = query(rows)
    assert result.skipped == 3
    assert [e.external_id for e in result.events] == ["keep"]
    assert result.events[0].occurrence_start == result.events[0].start


# --- instants ------------------------------------------------------------------------


def test_epoch_and_rfc3339_agree() -> None:
    expected = datetime(2025, 11, 19, 16, 0, tzinfo=UTC)
    assert parse_instant(1763568000) == expected
    assert parse_instant_text("1763568000") == expected
    assert parse_instant_text("2025-11-19T16:00:00Z") == expected
    assert parse_instant_text("2025-11-19T16:00:00+00:00") == expected
    assert parse_instant_text("2025-11-19T16:00:00.999999Z") == expected
    assert parse_instant(datetime(2025, 11, 19, 16, 0, 0, 500_000, tzinfo=UTC)) == expected
    assert parse_instant(0) == datetime(1970, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "value",
    [
        -1,
        datetime(1969, 12, 31, 23, 59, 59, tzinfo=UTC),
        1.5,
        True,
        datetime(2025, 11, 19, 16, 0),  # naive
        datetime(2025, 11, 19, 16, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
        10**20,
        "1763568000",  # strings are CLI-only
    ],
)
def test_parse_instant_rejects(value: Any) -> None:
    with pytest.raises(InvalidQueryError):
        parse_instant(value)


@pytest.mark.parametrize(
    "text",
    [
        "-1",
        "1969-12-31T23:59:59Z",
        "1.5",
        "2025-11-19T16:00:00",
        "2025-11-19T16:00:00-00:00",
        "2025-11-19T16:00:00+05:30",
        "2025-11-19",
        "99999999999999999999",
        "2025-13-45T99:99:99Z",
        "",
        " 1763568000",
    ],
)
def test_parse_instant_text_rejects(text: str) -> None:
    with pytest.raises(InvalidQueryError):
        parse_instant_text(text)


@pytest.mark.parametrize(
    "text", ["2025-11-19T16:00:00Z\n", "2025-11-19T16:00:00+00:00\n", "2025-11-19T16:00:00Z\r\n"]
)
def test_rfc3339_with_trailing_newline_fails_the_grammar_check(text: str) -> None:
    # Rejected by the anchored grammar itself (fullmatch), not only later by fromisoformat.
    with pytest.raises(InvalidQueryError, match="expected epoch seconds or an RFC 3339"):
        parse_instant_text(text)


# --- ids -----------------------------------------------------------------------------


def test_id_collision_gets_suffix_and_is_stable() -> None:
    a = raw_event(external_id=None, event_identifier=None, title="b")
    b = raw_event(external_id=None, event_identifier=None, title="a")
    run1 = query([a, b]).events
    run2 = query([a, b]).events
    ids = sorted(e.id for e in run1)
    assert ids[1] == ids[0] + "-2"
    assert [(e.title, e.id) for e in run1] == [(e.title, e.id) for e in run2]
    by_title = {e.title: e.id for e in run1}
    assert by_title["b"] == by_title["a"] + "-2"  # suffix order: title, then EventKit order


def test_same_invite_in_two_calendars_gives_two_rows() -> None:
    cals = [raw_calendar("cal-1"), raw_calendar("cal-2", title="Home")]
    rows = [raw_event(calendar_id="cal-1"), raw_event(calendar_id="cal-2")]
    first, second = query(rows, calendars=cals).events
    assert first.id != second.id
    assert (first.calendar.id, second.calendar.id) == ("cal-1", "cal-2")


# --- window validation ---------------------------------------------------------------


def test_window_validation_errors() -> None:
    start = utc("2025-11-19T16:00:00Z")
    with pytest.raises(InvalidQueryError):
        validate_window(datetime(2025, 11, 19, 16), datetime(2025, 11, 19, 17))
    with pytest.raises(InvalidQueryError):
        validate_window(start, start)
    with pytest.raises(InvalidQueryError):
        validate_window(start, start - timedelta(seconds=1))
    ist = timezone(timedelta(hours=5, minutes=30))
    with pytest.raises(InvalidQueryError):
        validate_window(start.astimezone(ist), (start + timedelta(hours=1)).astimezone(ist))


def test_window_length_cap() -> None:
    start = utc("2025-01-01T00:00:00Z")
    validate_window(start, start + timedelta(days=3 * 365 - 2))
    with pytest.raises(InvalidQueryError):
        validate_window(start, start + timedelta(days=3 * 365 - 2, seconds=1))


def test_padded_start_before_1970_is_invalid() -> None:
    with pytest.raises(InvalidQueryError):
        validate_window(
            datetime(1969, 12, 31, 23, 45, tzinfo=UTC), datetime(1970, 1, 1, 1, tzinfo=UTC)
        )


def test_api_rejects_over_cap_window() -> None:
    start = utc("2025-01-01T00:00:00Z")
    with pytest.raises(InvalidQueryError):
        query([], "2025-01-01T00:00:00Z", (start + timedelta(days=1094)).isoformat())


def test_multi_week_window_passes() -> None:
    row = raw_event("2025-12-20T10:00:00Z", "2025-12-20T11:00:00Z")
    result = query([row], "2025-11-19T00:00:00Z", "2025-12-31T00:00:00Z")  # 6 weeks
    assert len(result.events) == 1


def test_old_absolute_window_returns_fixture_events() -> None:
    row = raw_event("2025-01-06T17:15:00Z", "2025-01-06T17:45:00Z", external_id="old")
    result = query([row], "2025-01-06T17:00:00Z", "2025-01-06T18:00:00Z")
    assert [e.external_id for e in result.events] == ["old"]


# --- query widening ------------------------------------------------------------------


def test_query_range_is_window_plus_minus_one_day() -> None:
    source = FakeSource()
    _api.query_events(
        lambda: source,
        utc(W_START),
        utc(W_END),
        calendars=None,
        include_notes=False,
        prompt=False,
    )
    assert source.ranges == [
        (utc("2025-11-18T16:00:00Z"), utc("2025-11-20T17:00:00Z"), None),
    ]


def test_widened_fetch_then_strict_overlap() -> None:
    # Asia/Kolkata all-day rows around a window of 2025-11-20T16:00Z-17:00Z.
    inside = raw_event(
        "2025-11-19T18:30:00Z",
        "2025-11-20T18:29:59Z",
        all_day=True,
        start_local=(2025, 11, 20, 0, 0, 0),
        end_local=(2025, 11, 20, 23, 59, 59),
        external_id="in",
    )
    outside = raw_event(
        "2025-11-20T18:30:00Z",
        "2025-11-21T18:29:59Z",
        all_day=True,
        start_local=(2025, 11, 21, 0, 0, 0),
        end_local=(2025, 11, 21, 23, 59, 59),
        external_id="out",
    )
    source = FakeSource(events=[inside, outside])
    result = _api.query_events(
        lambda: source,
        utc("2025-11-20T16:00:00Z"),
        utc("2025-11-20T17:00:00Z"),
        calendars=None,
        include_notes=False,
        prompt=False,
    )
    q_start, q_end, _ = source.ranges[0]
    fetched = source.events(q_start, q_end, None)
    assert {r.external_id for r in fetched} == {"in", "out"}
    assert [e.external_id for e in result.events] == ["in"]


# --- epoch, empty, notes -------------------------------------------------------------


def test_epoch_to_utc_truncates_and_handles_pre_1970() -> None:
    assert epoch_to_utc(1700000000.987) == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    assert epoch_to_utc(-86400.0) == datetime(1969, 12, 31, tzinfo=UTC)
    assert epoch_to_utc(-0.5) == datetime(1969, 12, 31, 23, 59, 59, tzinfo=UTC)


def test_empty_result() -> None:
    assert query([]).events == []
    assert query([]).skipped == 0


def test_notes_only_when_requested() -> None:
    row = raw_event(notes="secret agenda")
    assert only([row]).notes is None
    assert only([row], include_notes=True).notes == "secret agenda"


# --- ordering (R8) -------------------------------------------------------------------


def test_ordering_ties_at_each_level() -> None:
    cals = [raw_calendar(c) for c in ("cal-0", "cal-1", "cal-2", "cal-3")]
    rows = [
        raw_event(W_START, "2025-11-19T16:30:00Z", calendar_id="cal-3", title="A"),
        raw_event(W_START, "2025-11-19T16:15:00Z", calendar_id="cal-2", title="B"),
        raw_event(W_START, "2025-11-19T16:30:00Z", calendar_id="cal-0", title="C"),
        # same base key (identifiers nil): ids base and base-2, by title
        raw_event(
            W_START,
            "2025-11-19T16:30:00Z",
            calendar_id="cal-1",
            title="E",
            external_id=None,
            event_identifier=None,
        ),
        raw_event(
            W_START,
            "2025-11-19T16:30:00Z",
            calendar_id="cal-1",
            title="D",
            external_id=None,
            event_identifier=None,
        ),
        raw_event("2025-11-19T15:00:00Z", "2025-11-19T16:30:00Z", title="F"),
    ]
    result = query(rows, calendars=cals)
    assert [e.title for e in result.events] == ["F", "B", "C", "D", "E", "A"]


@pytest.mark.parametrize("zone", ["Asia/Tokyo", "Asia/Kolkata", "Europe/Helsinki"])
def test_non_utc_aware_inputs_are_rejected(zone: str) -> None:
    from zoneinfo import ZoneInfo

    from macos_calendar_events._mapping import parse_instant

    with pytest.raises(InvalidQueryError, match="must be UTC"):
        parse_instant(datetime(2025, 11, 20, 9, 0, tzinfo=ZoneInfo(zone)))


@pytest.mark.parametrize("text", ["2025-11-20T09:00:00+09:00", "2025-11-20T09:00:00+05:30"])
def test_non_utc_offset_text_is_rejected(text: str) -> None:
    from macos_calendar_events._mapping import parse_instant_text

    with pytest.raises(InvalidQueryError):
        parse_instant_text(text)
