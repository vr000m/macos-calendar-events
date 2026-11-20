"""Public wrappers forward to _api with default_source() and the documented defaults."""

from collections.abc import Iterator

import pytest

import macos_calendar_events as m
from macos_calendar_events import _eventkit
from tests.fakes import FULL_ACCESS, NOT_DETERMINED, FakeSource, raw_calendar, raw_event


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeSource]:
    source = FakeSource(
        status=NOT_DETERMINED,
        status_after_request=FULL_ACCESS,
        calendars=[raw_calendar("cal-1", title="Work"), raw_calendar("cal-2", title="Home")],
        events=[
            raw_event(calendar_id="cal-1", notes="n", external_id="w"),
            raw_event(calendar_id="cal-2", external_id="h"),
        ],
    )
    monkeypatch.setattr(_eventkit, "default_source", lambda: source)
    yield source


def test_events_in_window_forwards_and_defaults(fake: FakeSource) -> None:
    events = m.events_in_window(1763568000, 1763571600, calendars=["Home"])
    assert [e.external_id for e in events] == ["h"]
    assert fake.ranges[0][2] == ["cal-2"]
    assert fake.requests == [60.0]  # prompt=True by default


def test_events_in_window_notes_default_off(fake: FakeSource) -> None:
    fake.status = FULL_ACCESS
    [work, _] = sorted(m.events_in_window(1763568000, 1763571600), key=lambda e: e.calendar.id)
    assert work.notes is None
    [work, _] = sorted(
        m.events_in_window(1763568000, 1763571600, include_notes=True),
        key=lambda e: e.calendar.id,
    )
    assert work.notes == "n"


def test_events_in_window_returns_a_list_of_events(fake: FakeSource) -> None:
    events = m.events_in_window(1763568000, 1763571600)
    assert isinstance(events, list)
    assert all(isinstance(e, m.Event) for e in events)


def test_prompt_false_raises_access_error(fake: FakeSource) -> None:
    with pytest.raises(m.CalendarAccessError):
        m.events_in_window(1763568000, 1763571600, prompt=False)
    with pytest.raises(m.CalendarAccessError):
        m.list_calendars(prompt=False)
    assert fake.requests == []


def test_list_calendars_defaults_to_prompt(fake: FakeSource) -> None:
    cals = m.list_calendars()
    assert [c.title for c in cals] == ["Home", "Work"]
    assert fake.requests == [60.0]


def test_status_and_request_return_access_status(fake: FakeSource) -> None:
    status = m.authorization_status()
    assert isinstance(status, m.AccessStatus) and status is m.AccessStatus.NOT_DETERMINED
    assert fake.requests == []
    granted = m.request_access(timeout=5.0)
    assert granted is m.AccessStatus.FULL_ACCESS
    assert fake.requests == [5.0]
    m.request_access()
    assert fake.requests == [5.0, 60.0]


def test_request_access_default_is_the_read_gate_timeout(fake: FakeSource) -> None:
    import importlib

    from macos_calendar_events import _api

    # One constant for both waits: the public default follows ACCESS_TIMEOUT_S.
    original = _api.ACCESS_TIMEOUT_S
    _api.ACCESS_TIMEOUT_S = 42.0  # type: ignore[misc]
    try:
        importlib.reload(m).request_access()
        assert fake.requests == [42.0]
    finally:
        _api.ACCESS_TIMEOUT_S = original  # type: ignore[misc]
        importlib.reload(m)


def test_reexported_names() -> None:
    expected = {
        "SCHEMA_VERSION",
        "AccessStatus",
        "CalendarAccessError",
        "CalendarInfo",
        "CalendarNotFoundError",
        "CalendarRef",
        "Event",
        "EventKitUnavailableError",
        "EventStatus",
        "InvalidQueryError",
        "MacosCalendarEventsError",
        "Participant",
        "ParticipantRole",
        "ParticipantType",
        "ParticipationStatus",
        "SourceType",
        "__version__",
        "authorization_status",
        "calendars_to_json",
        "events_in_window",
        "list_calendars",
        "request_access",
        "window_to_json",
    }
    assert set(m.__all__) == expected
    for name in expected:
        assert hasattr(m, name)
    assert m.__version__ == "0.1.0"
    assert m.SCHEMA_VERSION == 1
