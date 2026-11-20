"""Phase 2: the hand-written schemas match the types, and format checking is active (R18)."""

import copy
import dataclasses
import json
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from importlib.resources import files
from typing import Any, get_type_hints

import pytest
from jsonschema import Draft202012Validator

from macos_calendar_events.models import (
    CalendarInfo,
    CalendarRef,
    CalendarsDocument,
    Event,
    EventStatus,
    Participant,
    ParticipantRole,
    ParticipantType,
    ParticipationStatus,
    SourceType,
    WindowDocument,
    calendars_to_json,
    window_to_json,
)
from tests.model_fixtures import ALL_DAY, CALENDAR, TIMED, WINDOW

Json = dict[str, Any]


def _schema(name: str) -> Json:
    text = (files("macos_calendar_events") / "schema" / f"{name}.schema.json").read_text("utf-8")
    loaded: Json = json.loads(text)
    return loaded


WINDOW_SCHEMA = _schema("window-v1")
CALENDARS_SCHEMA = _schema("calendars-v1")


def _validator(schema: Json) -> Draft202012Validator:
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def _errors(schema: Json, doc: object) -> list[str]:
    """Validator keywords of every error (never values)."""
    return [str(e.validator) for e in _validator(schema).iter_errors(doc)]


def _window_doc() -> Json:
    doc: Json = json.loads(window_to_json([TIMED, ALL_DAY], window=WINDOW))
    return doc


def _calendars_doc() -> Json:
    doc: Json = json.loads(calendars_to_json([CALENDAR]))
    return doc


@pytest.mark.parametrize("schema", [WINDOW_SCHEMA, CALENDARS_SCHEMA])
def test_schema_is_valid_draft_2020_12(schema: Json) -> None:
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema_version"] == {"const": 1}


def test_schema_ids_are_tag_pinned_raw_urls() -> None:
    base = "https://raw.githubusercontent.com/vr000m/macos-calendar-events/v0.1.0/docs/schema/"
    assert WINDOW_SCHEMA["$id"] == base + "window-v1.schema.json"
    assert CALENDARS_SCHEMA["$id"] == base + "calendars-v1.schema.json"


def test_serializer_output_validates() -> None:
    assert _errors(WINDOW_SCHEMA, _window_doc()) == []
    assert _errors(CALENDARS_SCHEMA, _calendars_doc()) == []


def _set(doc: Json, path: tuple[str | int, ...], value: object) -> Json:
    out = copy.deepcopy(doc)
    node: Any = out
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return out


def _drop(doc: Json, path: tuple[str | int, ...]) -> Json:
    out = copy.deepcopy(doc)
    node: Any = out
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return out


@pytest.mark.parametrize(
    ("mutate", "keyword"),
    [
        (lambda d: _drop(d, ("events", 0, "title")), "required"),
        (lambda d: _drop(d, ("window",)), "required"),
        (lambda d: _set(d, ("events", 0, "all_day"), "yes"), "type"),
        (lambda d: _set(d, ("events", 0, "start"), "2025-11-19T16:00:00"), "pattern"),  # naive
        (lambda d: _set(d, ("events", 1, "start_date"), "not-a-date"), "format"),
        (lambda d: _set(d, ("schema_version",), 2), "const"),
        (lambda d: _set(d, ("events", 0, "end"), "2025-11-19T16:30:00.5Z"), "pattern"),
        (lambda d: _set(d, ("events", 0, "start"), "2025-11-19T16:00:00+02:00"), "pattern"),
        (lambda d: _set(d, ("window", "start_ts"), 1.5), "type"),
    ],
)
def test_window_negatives(mutate: Any, keyword: str) -> None:
    assert keyword in _errors(WINDOW_SCHEMA, mutate(_window_doc()))


def test_impossible_date_time_fails_on_format_only() -> None:
    """Matches the pattern, so only an active format checker can reject it."""
    doc = _set(_window_doc(), ("events", 0, "start"), "2025-13-45T99:99:99Z")
    assert _errors(WINDOW_SCHEMA, doc) == ["format"]


def test_missing_ts_field_fails() -> None:
    for key in ("start_ts", "end_ts", "occurrence_start_ts"):
        assert "required" in _errors(WINDOW_SCHEMA, _drop(_window_doc(), ("events", 0, key)))
    assert "required" in _errors(WINDOW_SCHEMA, _drop(_window_doc(), ("window", "end_ts")))


def test_calendars_negatives() -> None:
    doc = _calendars_doc()
    assert "pattern" in _errors(
        CALENDARS_SCHEMA, _set(doc, ("calendars", 0, "color_hex"), "#0080ff")
    )
    assert "required" in _errors(CALENDARS_SCHEMA, _drop(doc, ("calendars", 0, "read_only")))
    assert "type" in _errors(CALENDARS_SCHEMA, _set(doc, ("calendars", 0, "id"), None))
    assert _errors(CALENDARS_SCHEMA, _set(doc, ("calendars", 0, "color_hex"), None)) == []


def test_extra_unknown_keys_validate() -> None:
    doc = _set(_window_doc(), ("events", 0, "future_field"), {"any": "thing"})
    doc["also_new"] = 1
    assert _errors(WINDOW_SCHEMA, doc) == []
    assert _errors(CALENDARS_SCHEMA, _set(_calendars_doc(), ("calendars", 0, "x"), 1)) == []


def test_null_organizer_and_self_status_validate() -> None:
    doc = _set(_window_doc(), ("events", 0, "organizer"), None)
    doc = _set(doc, ("events", 0, "self_status"), None)
    assert _errors(WINDOW_SCHEMA, doc) == []


def test_unknown_enum_strings_validate() -> None:
    doc = _set(_window_doc(), ("events", 0, "status"), "brand_new_status")
    doc = _set(doc, ("events", 0, "attendees", 0, "role"), "brand_new_role")
    doc = _set(doc, ("events", 0, "self_status"), "brand_new")
    assert _errors(WINDOW_SCHEMA, doc) == []
    cal = _set(_calendars_doc(), ("calendars", 0, "source_type"), "brand_new_source")
    assert _errors(CALENDARS_SCHEMA, cal) == []


def _field_names(cls: type) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


def test_required_keys_match_dataclass_fields_plus_ts_siblings() -> None:
    defs = WINDOW_SCHEMA["$defs"]
    ts = {"start_ts", "end_ts", "occurrence_start_ts"}
    assert set(defs["event"]["required"]) == _field_names(Event) | ts
    assert set(defs["participant"]["required"]) == _field_names(Participant)
    assert set(defs["calendar_ref"]["required"]) == _field_names(CalendarRef)
    info = CALENDARS_SCHEMA["$defs"]["calendar_info"]
    assert set(info["required"]) == _field_names(CalendarInfo)
    # every required key is also described under properties
    for node in (defs["event"], defs["participant"], defs["calendar_ref"], info):
        assert set(node["required"]) == set(node["properties"])


def test_envelope_required_keys_match_typed_dicts() -> None:
    assert set(WINDOW_SCHEMA["required"]) == set(get_type_hints(WindowDocument))
    assert set(CALENDARS_SCHEMA["required"]) == set(get_type_hints(CalendarsDocument))
    window = WINDOW_SCHEMA["$defs"]["window"]
    assert set(window["required"]) == {"start", "end", "start_ts", "end_ts"}


@pytest.mark.parametrize(
    ("enum", "schema", "def_name"),
    [
        (EventStatus, WINDOW_SCHEMA, "event_status"),
        (ParticipationStatus, WINDOW_SCHEMA, "participation_status"),
        (ParticipantRole, WINDOW_SCHEMA, "participant_role"),
        (ParticipantType, WINDOW_SCHEMA, "participant_type"),
        (SourceType, CALENDARS_SCHEMA, "source_type"),
    ],
)
def test_enum_known_values_match(enum: type[StrEnum], schema: Json, def_name: str) -> None:
    node = schema["$defs"][def_name]
    assert node["type"] == "string"
    assert node["x-known-values"] == [m.value for m in enum]
    for member in enum:
        assert member.value in node["description"]


def test_enum_fields_reference_their_definitions() -> None:
    defs = WINDOW_SCHEMA["$defs"]
    assert defs["event"]["properties"]["status"] == {"$ref": "#/$defs/event_status"}
    assert defs["participant"]["properties"]["role"] == {"$ref": "#/$defs/participant_role"}
    assert defs["participant"]["properties"]["status"] == {"$ref": "#/$defs/participation_status"}
    assert defs["participant"]["properties"]["type"] == {"$ref": "#/$defs/participant_type"}
    info = CALENDARS_SCHEMA["$defs"]["calendar_info"]
    assert info["properties"]["source_type"] == {"$ref": "#/$defs/source_type"}


def test_ts_siblings_equal_epoch_of_strings() -> None:
    hand_written = {
        "2025-11-19T16:00:00Z": 1763568000,
        "2025-11-19T16:30:00Z": 1763569800,
        "2025-11-20T08:00:00Z": 1763625600,
        "2025-11-21T08:00:00Z": 1763712000,
        "2025-11-21T16:00:00Z": 1763740800,
    }
    doc = _window_doc()
    pairs = [(doc["window"]["start"], doc["window"]["start_ts"])]
    pairs.append((doc["window"]["end"], doc["window"]["end_ts"]))
    for ev in doc["events"]:
        for name in ("start", "end", "occurrence_start"):
            pairs.append((ev[name], ev[f"{name}_ts"]))
    for text, ts in pairs:
        assert hand_written[text] == ts
        assert int(datetime.fromisoformat(text).timestamp()) == ts


def test_pre_1970_negative_ts_validates() -> None:
    old = datetime(1969, 7, 20, 20, 17, tzinfo=UTC)
    event = dataclasses.replace(TIMED, start=old, occurrence_start=old)
    doc = json.loads(window_to_json([event], window=WINDOW))
    assert doc["events"][0]["start_ts"] < 0
    assert _errors(WINDOW_SCHEMA, doc) == []


# --- anchored patterns: Python's `$` also matches before a final newline -------------


def _with(doc: Json, path: tuple[str | int, ...], change: Callable[[str], str]) -> Json:
    """A deep copy of ``doc`` with the string at ``path`` replaced by ``change(old)``."""
    probe = copy.deepcopy(doc)
    target: Any = probe
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = change(target[path[-1]])
    return probe


def _pattern_paths(schema: Json, doc: Json) -> list[tuple[str | int, ...]]:
    """Paths of every string the validator checks against a ``pattern`` in ``doc``."""
    validator = _validator(schema)
    paths: list[tuple[str | int, ...]] = []

    def walk(instance: object, path: tuple[str | int, ...]) -> None:
        if isinstance(instance, dict):
            for key, value in instance.items():
                walk(value, (*path, key))
        elif isinstance(instance, list):
            for index, value in enumerate(instance):
                walk(value, (*path, index))
        elif isinstance(instance, str):
            probe = _with(doc, path, lambda value: value + "\u0000")  # breaks any anchored pattern
            if any(e.validator == "pattern" for e in validator.iter_errors(probe)):
                paths.append(path)

    walk(doc, ())
    return paths


@pytest.mark.parametrize(
    ("name", "schema"), [("window-v1", WINDOW_SCHEMA), ("calendars-v1", CALENDARS_SCHEMA)]
)
@pytest.mark.parametrize("affix", ["\n", "\r\n", "\n\n", " ", "x", "0"])
@pytest.mark.parametrize("where", ["suffix", "prefix"])
def test_patterned_strings_reject_any_extra_character(
    name: str, schema: Json, affix: str, where: str
) -> None:
    from pathlib import Path

    doc: Json = json.loads((Path(__file__).parent / "golden" / f"{name}.json").read_text("utf-8"))
    assert _errors(schema, doc) == []
    paths = _pattern_paths(schema, doc)
    assert paths, "the golden document exercises the patterned fields"
    for path in paths:
        probe = _with(doc, path, lambda v: v + affix if where == "suffix" else affix + v)
        assert _errors(schema, probe), (path, repr(affix), where)
