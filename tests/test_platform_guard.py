"""R19/R14: default_source() raises EventKitUnavailableError when EventKit can't be used."""

import platform
import sys
from collections.abc import Iterator

import pytest

from macos_calendar_events import _eventkit
from macos_calendar_events.errors import EventKitUnavailableError
from tests.ek_stubs import Factory, StubStore, StubStoreClass, namespace


@pytest.fixture(autouse=True)
def _fresh_default() -> Iterator[None]:
    _eventkit._clear_default_source()
    yield
    _eventkit._clear_default_source()


def _stub_namespace(has_selector: bool) -> _eventkit.EventKitNamespace:
    return namespace(Factory(lambda: StubStore([], [])), StubStoreClass(has_selector=has_selector))


def test_missing_macos_14_selector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(_eventkit, "_load_namespace", lambda: _stub_namespace(False))
    monkeypatch.setattr(platform, "mac_ver", lambda: ("13.6.1", ("", "", ""), "arm64"))
    with pytest.raises(EventKitUnavailableError) as info:
        _eventkit.default_source()
    assert "13.6.1" in str(info.value)


def test_selector_present_gives_a_cached_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(_eventkit, "_load_namespace", lambda: _stub_namespace(True))
    source = _eventkit.default_source()
    assert isinstance(source, _eventkit.EventKitSource)
    assert _eventkit.default_source() is source
    _eventkit._clear_default_source()
    assert _eventkit.default_source() is not source


def test_non_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(EventKitUnavailableError):
        _eventkit.default_source()


def test_blocked_eventkit_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "EventKit", None)
    with pytest.raises(EventKitUnavailableError) as info:
        _eventkit.default_source()
    assert info.value.__cause__ is None


def test_unavailable_is_a_package_error() -> None:
    from macos_calendar_events.errors import MacosCalendarEventsError

    assert issubclass(EventKitUnavailableError, MacosCalendarEventsError)
