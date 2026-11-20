"""Phase 2: data types serialize to one stable JSON form. Expected values are hand-written."""

import dataclasses
import json
from datetime import UTC, datetime

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
