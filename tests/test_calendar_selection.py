"""R2 calendar mapping and ordering; R6 selection."""

import copy
import pickle

import pytest

from macos_calendar_events import _api
from macos_calendar_events._mapping import rgb_to_hex, select_calendars, to_calendars
from macos_calendar_events._raw import RawCalendar
from macos_calendar_events.errors import CalendarNotFoundError, InvalidQueryError
from macos_calendar_events.models import CalendarInfo, SourceType
from tests.fakes import FakeSource, raw_calendar, raw_event


def test_calendar_fields_from_raw() -> None:
    raw = raw_calendar(
        "cal-9",
        title="Team",
        source_title="Example Org",
        source_type=1,
        color_rgb=(1.0, 0.0, 0.0),
        allows_modifications=True,
    )
    assert to_calendars([raw]) == [
        CalendarInfo(
            id="cal-9",
            title="Team",
            source_title="Example Org",
            source_type=SourceType.EXCHANGE,
            color_hex="#FF0000",
            read_only=False,
        )
    ]


def test_read_only_calendar() -> None:
    [info] = to_calendars([raw_calendar(allows_modifications=False)])
    assert info.read_only is True


def test_no_color() -> None:
    [info] = to_calendars([raw_calendar(color_rgb=None)])
    assert info.color_hex is None


def test_rgb_to_hex() -> None:
    assert rgb_to_hex((0.0, 0.5, 1.0)) == "#0080FF"
    assert rgb_to_hex((1.0, 1.0, 1.0)) == "#FFFFFF"
    assert rgb_to_hex(None) is None


def test_unknown_source_type() -> None:
    [info] = to_calendars([raw_calendar(source_type=77)])
    assert info.source_type is SourceType.UNKNOWN


def test_calendar_ordering_nulls_first() -> None:
    raw = [
        raw_calendar("c5", title="b", source_title="Beta"),
        raw_calendar("c4", title="a", source_title="Beta"),
        raw_calendar("c3", title="z", source_title=None),
        raw_calendar("c2", title=None, source_title="Alpha"),
        raw_calendar("c7", title="a", source_title="Beta"),
        raw_calendar("c1", title="m", source_title=None),
        raw_calendar("c6", title=None, source_title=None),
    ]
    # key: (source_title is not None, source_title or "", title or "", id)
    expected = ["c6", "c1", "c3", "c2", "c4", "c7", "c5"]
    assert [c.id for c in to_calendars(raw)] == expected


def test_query_calendars_through_api() -> None:
    source = FakeSource(calendars=[raw_calendar("b", title="B"), raw_calendar("a", title="A")])
    assert [c.id for c in _api.query_calendars(lambda: source, prompt=False)] == ["a", "b"]


# --- selection (R6) ------------------------------------------------------------------

CALS = [
    raw_calendar("id-work", title="Work", source_title="iCloud"),
    raw_calendar("id-home", title="Home", source_title="iCloud"),
    raw_calendar("id-work2", title="work", source_title="Example Org"),
    raw_calendar("Home", title="Trips", source_title="Local"),
]


def _ids(selected: list[RawCalendar]) -> list[str]:
    return [c.id for c in selected]


def test_select_by_id() -> None:
    assert _ids(select_calendars(CALS, ["id-home"])) == ["id-home"]


def test_select_by_title_case_insensitive_includes_duplicates() -> None:
    assert _ids(select_calendars(CALS, ["WORK"])) == ["id-work", "id-work2"]


def test_id_match_wins_over_title_match() -> None:
    # "Home" is one calendar's id and another's title: id only.
    assert _ids(select_calendars(CALS, ["Home"])) == ["Home"]


_LONE = "\ud83d"


@pytest.mark.parametrize("raw_id", ["cal-1", "cal-\U0001f600", "cal-" + _LONE, _LONE + "cal"])
@pytest.mark.parametrize("form", ["raw", "listed"])
def test_exact_id_wins_over_a_title_equal_to_it(raw_id: str, form: str) -> None:
    """R6: a selector equal to a calendar's raw identifier or its listed (output) id selects
    that calendar by id, even when another calendar's title is the same string."""
    [listed] = to_calendars([raw_calendar(raw_id)])
    selector = raw_id if form == "raw" else listed.id
    target = raw_calendar(raw_id, title="Target")
    decoy = raw_calendar("decoy", title=selector)
    assert _ids(select_calendars([target, decoy], [selector])) == [raw_id]


def test_unknown_selector_raises_even_with_a_valid_one() -> None:
    with pytest.raises(CalendarNotFoundError) as info:
        select_calendars(CALS, ["id-home", "Nope"])
    assert info.value.selectors == ("Nope",)
    assert "'Nope'" in str(info.value)
    assert "Work" not in str(info.value)  # titles never in the message
    assert "Work" in info.value.available_titles


def test_empty_selector_list_is_invalid() -> None:
    with pytest.raises(InvalidQueryError):
        select_calendars(CALS, [])
    assert issubclass(InvalidQueryError, ValueError)


def test_none_selects_all() -> None:
    assert _ids(select_calendars(CALS, None)) == [c.id for c in CALS]


def test_selection_restricts_query_and_rows() -> None:
    events = [
        raw_event(calendar_id="id-work", external_id="w"),
        raw_event(calendar_id="id-home", external_id="h"),
    ]
    source = FakeSource(calendars=CALS, events=events)
    result = _api.query_events(
        lambda: source,
        1763568000,
        1763571600,
        calendars=["id-home"],
        include_notes=False,
        prompt=False,
    )
    assert [e.external_id for e in result.events] == ["h"]
    assert source.ranges[0][2] == ["id-home"]
    assert result.events[0].calendar.title == "Home"
    assert result.events[0].calendar.source_title == "iCloud"


def test_api_empty_calendar_list_fails_before_source() -> None:
    def no_source() -> FakeSource:
        raise AssertionError("source must not be created")

    with pytest.raises(InvalidQueryError):
        _api.query_events(
            no_source, 1763568000, 1763571600, calendars=[], include_notes=False, prompt=False
        )


def test_api_unknown_selector_raises_not_found() -> None:
    source = FakeSource(calendars=CALS)
    with pytest.raises(CalendarNotFoundError):
        _api.query_events(
            lambda: source,
            1763568000,
            1763571600,
            calendars=["missing"],
            include_notes=False,
            prompt=False,
        )
    assert source.ranges == []


def test_bare_string_calendars_is_invalid_not_one_selector_per_character() -> None:
    source = FakeSource(calendars=CALS)
    with pytest.raises(InvalidQueryError):
        _api.query_events(
            lambda: source,
            1763568000,
            1763571600,
            calendars="Work",
            include_notes=False,
            prompt=False,
        )
    assert source.ranges == []


def test_not_found_error_survives_pickle_and_copy() -> None:
    error = CalendarNotFoundError(["Nope"], ["Home", "Work"])
    for clone in (pickle.loads(pickle.dumps(error)), copy.copy(error), copy.deepcopy(error)):
        assert clone.selectors == ("Nope",)
        assert clone.available_titles == ("Home", "Work")
        assert str(clone) == str(error)
