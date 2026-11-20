"""Phase 2: data types serialize to one stable JSON form. Expected values are hand-written."""

import dataclasses
import json
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from macos_calendar_events.models import (
    SCHEMA_VERSION,
    CalendarRef,
    calendars_to_json,
    window_to_json,
)
from tests.model_fixtures import ALL_DAY, CALENDAR, ORGANIZER, TIMED, WINDOW

ORGANIZER_EMAIL = "alex@example.com"

TWO_EVENT_JSON = """{
  "events": [
    {
      "all_day": false,
      "attendees": [
        {
          "email": "alex@example.com",
          "is_self": false,
          "name": "Alex Example",
          "role": "chair",
          "status": "accepted",
          "type": "person",
          "url": null
        },
        {
          "email": null,
          "is_self": true,
          "name": null,
          "role": "required",
          "status": "accepted",
          "type": "person",
          "url": "urn:uuid:00000000-0000-0000-0000-000000000001"
        }
      ],
      "calendar": {
        "id": "cal-1",
        "source_title": "iCloud",
        "title": "Work"
      },
      "end": "2025-11-19T16:30:00Z",
      "end_date": null,
      "end_ts": 1763569800,
      "event_identifier": "evt-1",
      "external_id": "ext-1",
      "id": "a1b2c3d4e5f60718",
      "is_detached": false,
      "is_recurring": false,
      "location": "Room 1",
      "notes": null,
      "occurrence_start": "2025-11-19T16:00:00Z",
      "occurrence_start_ts": 1763568000,
      "organizer": {
        "email": "alex@example.com",
        "is_self": false,
        "name": "Alex Example",
        "role": "chair",
        "status": "accepted",
        "type": "person",
        "url": null
      },
      "self_status": "accepted",
      "start": "2025-11-19T16:00:00Z",
      "start_date": null,
      "start_ts": 1763568000,
      "status": "confirmed",
      "time_zone": "America/Los_Angeles",
      "title": "Planning",
      "url": null
    },
    {
      "all_day": true,
      "attendees": [],
      "calendar": {
        "id": "cal-2",
        "source_title": null,
        "title": null
      },
      "end": "2025-11-21T08:00:00Z",
      "end_date": "2025-11-21",
      "end_ts": 1763712000,
      "event_identifier": null,
      "external_id": null,
      "id": "0123456789abcdef",
      "is_detached": false,
      "is_recurring": false,
      "location": null,
      "notes": null,
      "occurrence_start": "2025-11-20T08:00:00Z",
      "occurrence_start_ts": 1763625600,
      "organizer": null,
      "self_status": null,
      "start": "2025-11-20T08:00:00Z",
      "start_date": "2025-11-20",
      "start_ts": 1763625600,
      "status": "none",
      "time_zone": null,
      "title": "Holiday",
      "url": null
    }
  ],
  "schema_version": 1,
  "window": {
    "end": "2025-11-21T16:00:00Z",
    "end_ts": 1763740800,
    "start": "2025-11-19T16:00:00Z",
    "start_ts": 1763568000
  }
}
"""


def test_schema_version_is_one() -> None:
    assert SCHEMA_VERSION == 1


def test_window_to_json_exact_text() -> None:
    assert window_to_json([TIMED, ALL_DAY], window=WINDOW) == TWO_EVENT_JSON


# 2025-11-19T16:00:00Z and 2025-11-21T16:00:00Z: the bounds of WINDOW as int epochs.
_INT_WINDOW = (1763568000, 1763740800)


@pytest.mark.parametrize("start_is_int", [False, True])
@pytest.mark.parametrize("end_is_int", [False, True])
def test_window_to_json_accepts_the_bound_forms_events_in_window_accepts(
    start_is_int: bool, end_is_int: bool
) -> None:
    start = _INT_WINDOW[0] if start_is_int else WINDOW[0]
    end = _INT_WINDOW[1] if end_is_int else WINDOW[1]
    assert window_to_json([TIMED, ALL_DAY], window=(start, end)) == TWO_EVENT_JSON


_PLUS5 = timezone(timedelta(hours=5))
_S, _E = WINDOW
_CAP = timedelta(days=3 * 365 - 2)
_LAST_END = datetime(9999, 12, 30, 23, 59, 59, tzinfo=UTC)  # latest end the query margin allows

_BOUNDS = [  # (bound, parses): each is tried as the start and as the end of a window
    (1763600000, True),  # an int epoch inside WINDOW
    (datetime(2025, 11, 20, 16, tzinfo=ZoneInfo("UTC")), True),
    (datetime(2025, 11, 20, 16, 0, 0, 999999, tzinfo=UTC), True),  # truncated, as R18
    (-5, False),  # negative epoch
    (10**12, False),  # out of datetime range (was OverflowError)
    (True, False),
    (1.5, False),
    ("1763568000", False),
    (None, False),
    (datetime(2025, 11, 19, 16), False),  # naive
    (datetime(2025, 11, 19, 21, tzinfo=_PLUS5), False),  # aware but not UTC
    (datetime(1969, 12, 31, 23, 59, 59, tzinfo=UTC), False),  # before 1970
]

_WINDOWS = [  # (window, valid)
    (WINDOW, True),
    (_INT_WINDOW, True),
    ((_S, _INT_WINDOW[1]), True),
    ((0, 1), True),  # the 1970 floor
    ((_S, _S + _CAP), True),  # exactly the span cap
    ((_S, _S + _CAP + timedelta(seconds=1)), False),  # over the cap
    ((0, _E), False),  # 1970 to 2025: over the cap
    ((_S, _S), False),  # empty
    ((10, 5), False),  # inverted int epochs
    ((5, 5), False),
    ((_E, _S), False),  # inverted datetimes
    ((_LAST_END - timedelta(seconds=1), _LAST_END), True),
    ((_LAST_END, _LAST_END + timedelta(seconds=1)), False),  # past the year-9999 bound
    *[((b, _E), ok) for b, ok in _BOUNDS],
    *[((_S, b), ok) for b, ok in _BOUNDS],
]


def _query_accepts(window: tuple[object, object]) -> bool:
    from macos_calendar_events import _api
    from macos_calendar_events.errors import InvalidQueryError
    from tests.fakes import FakeSource

    try:
        _api.query_events(
            FakeSource,
            window[0],  # type: ignore[arg-type]
            window[1],  # type: ignore[arg-type]
            calendars=None,
            include_notes=False,
            prompt=False,
        )
    except InvalidQueryError:
        return False
    return True


@pytest.mark.parametrize(("window", "valid"), _WINDOWS)
def test_window_to_json_accepts_exactly_the_windows_events_in_window_accepts(
    window: tuple[object, object], valid: bool
) -> None:
    """Whole windows, not just bounds: the serializer and the query share one check."""
    from macos_calendar_events._mapping import parse_window
    from macos_calendar_events.errors import InvalidQueryError

    assert _query_accepts(window) is valid
    if valid:
        doc = json.loads(window_to_json([], window=window))  # type: ignore[arg-type]
        start, end = parse_window(*window)  # type: ignore[arg-type]
        assert (doc["window"]["start_ts"], doc["window"]["end_ts"]) == (
            int(start.timestamp()),
            int(end.timestamp()),
        )
    else:
        with pytest.raises(InvalidQueryError):
            window_to_json([], window=window)  # type: ignore[arg-type]


def test_participant_to_dict_hand_written() -> None:
    assert ORGANIZER.to_dict() == {
        "name": "Alex Example",
        "email": ORGANIZER_EMAIL,
        "url": None,
        "role": "chair",
        "status": "accepted",
        "type": "person",
        "is_self": False,
    }


def test_calendars_to_json_hand_written() -> None:
    expected = {
        "schema_version": 1,
        "calendars": [
            {
                "id": "cal-1",
                "title": "Work",
                "source_title": "iCloud",
                "source_type": "caldav",
                "color_hex": "#0080FF",
                "read_only": False,
            }
        ],
    }
    text = calendars_to_json([CALENDAR])
    assert json.loads(text) == expected
    assert text.endswith("}\n")


def test_empty_window_document() -> None:
    doc = json.loads(window_to_json([], window=WINDOW))
    assert doc == {
        "schema_version": 1,
        "window": {
            "start": "2025-11-19T16:00:00Z",
            "end": "2025-11-21T16:00:00Z",
            "start_ts": 1763568000,
            "end_ts": 1763740800,
        },
        "events": [],
    }


def test_non_ascii_title_is_unescaped() -> None:
    event = dataclasses.replace(TIMED, title="Réunion — 会議 ☕")
    text = window_to_json([event], window=WINDOW)
    assert '"title": "Réunion — 会議 ☕"' in text
    assert "\\u" not in text


def test_sub_second_datetime_serializes_whole_seconds() -> None:
    start = datetime(2025, 11, 19, 16, 0, 5, 999_999, tzinfo=UTC)
    event = dataclasses.replace(TIMED, start=start, occurrence_start=start)
    out = event.to_dict()
    assert out["start"] == "2025-11-19T16:00:05Z"
    assert out["start_ts"] == 1763568005
    assert out["occurrence_start"] == "2025-11-19T16:00:05Z"


def test_pre_1970_instant_has_negative_ts() -> None:
    start = datetime(1969, 12, 31, 23, 59, 59, tzinfo=UTC)
    event = dataclasses.replace(TIMED, start=start)
    out = event.to_dict()
    assert out["start"] == "1969-12-31T23:59:59Z"
    assert out["start_ts"] == -1


def test_frozen_mutation_raises() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        TIMED.title = "changed"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        CalendarRef(id="x", title=None, source_title=None).id = "y"  # type: ignore[misc]


def test_collections_are_tuples() -> None:
    assert isinstance(TIMED.attendees, tuple)


@pytest.mark.parametrize(
    ("zone", "local", "text", "epoch"),
    [
        # Expected values cross-checked with TZ=<zone> /bin/date, not project code.
        ("Asia/Tokyo", (2025, 11, 20, 7, 30), "2025-11-19T22:30:00Z", 1763591400),
        ("Asia/Kolkata", (2025, 11, 20, 9, 15), "2025-11-20T03:45:00Z", 1763610300),
        ("Europe/Helsinki", (2026, 3, 29, 2, 30), "2026-03-29T00:30:00Z", 1774744200),
        ("Europe/Helsinki", (2026, 3, 29, 4, 30), "2026-03-29T01:30:00Z", 1774747800),
        ("Europe/Helsinki", (2026, 10, 25, 0, 0), "2026-10-24T21:00:00Z", 1792875600),
    ],
)
def test_zone_aware_datetime_serializes_as_utc(
    zone: str, local: tuple[int, int, int, int, int], text: str, epoch: int
) -> None:
    start = datetime(*local, tzinfo=ZoneInfo(zone))
    out = dataclasses.replace(TIMED, start=start, occurrence_start=start).to_dict()
    assert (out["start"], out["start_ts"]) == (text, epoch)
    assert (out["occurrence_start"], out["occurrence_start_ts"]) == (text, epoch)


def test_helsinki_ambiguous_fall_back_hour_uses_fold() -> None:
    first = datetime(2026, 10, 25, 3, 30, tzinfo=ZoneInfo("Europe/Helsinki"))  # EEST
    second = first.replace(fold=1)  # EET, one hour later
    a = dataclasses.replace(TIMED, start=first).to_dict()
    b = dataclasses.replace(TIMED, start=second).to_dict()
    assert (a["start"], a["start_ts"]) == ("2026-10-25T00:30:00Z", 1792888200)
    assert (b["start"], b["start_ts"]) == ("2026-10-25T01:30:00Z", 1792891800)
