"""R9: the access gate and the completion wait, with injected fakes (no TCC)."""

import threading
import time
from collections.abc import Callable

import pytest

from macos_calendar_events import _api
from macos_calendar_events._access import wait_for_access
from macos_calendar_events.errors import CalendarAccessError
from macos_calendar_events.models import AccessStatus
from tests.fakes import DENIED, FULL_ACCESS, NOT_DETERMINED, RESTRICTED, WRITE_ONLY, FakeSource

Completion = Callable[[bool, object | None], None]


def _calendars(source: FakeSource, *, prompt: bool) -> object:
    return _api.query_calendars(lambda: source, prompt=prompt)


def _events(source: FakeSource, *, prompt: bool) -> object:
    return _api.query_events(
        lambda: source,
        1763568000,
        1763571600,
        calendars=None,
        include_notes=False,
        prompt=prompt,
    )


READS = [_calendars, _events]


@pytest.mark.parametrize("read", READS)
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (RESTRICTED, AccessStatus.RESTRICTED),
        (DENIED, AccessStatus.DENIED),
        (WRITE_ONLY, AccessStatus.WRITE_ONLY),
        (42, AccessStatus.UNKNOWN),
    ],
)
def test_non_full_status_raises_without_request(
    read: Callable[..., object], raw: int, expected: AccessStatus
) -> None:
    source = FakeSource(status=raw)
    for prompt in (False, True):
        with pytest.raises(CalendarAccessError) as info:
            read(source, prompt=prompt)
        assert info.value.status is expected
    assert source.requests == []
    assert source.ranges == []


@pytest.mark.parametrize("read", READS)
def test_full_access_proceeds(read: Callable[..., object]) -> None:
    source = FakeSource(status=FULL_ACCESS)
    read(source, prompt=False)
    assert source.requests == []


@pytest.mark.parametrize("read", READS)
def test_not_determined_without_prompt_raises_and_never_requests(
    read: Callable[..., object],
) -> None:
    source = FakeSource(status=NOT_DETERMINED, status_after_request=FULL_ACCESS)
    with pytest.raises(CalendarAccessError) as info:
        read(source, prompt=False)
    assert info.value.status is AccessStatus.NOT_DETERMINED
    assert source.requests == []


@pytest.mark.parametrize("read", READS)
@pytest.mark.parametrize(
    ("after", "expected"),
    [
        (FULL_ACCESS, None),
        (DENIED, AccessStatus.DENIED),
        (NOT_DETERMINED, AccessStatus.NOT_DETERMINED),
    ],
)
def test_not_determined_with_prompt_requests_once(
    read: Callable[..., object], after: int, expected: AccessStatus | None
) -> None:
    source = FakeSource(status=NOT_DETERMINED, status_after_request=after)
    if expected is None:
        read(source, prompt=True)
    else:
        with pytest.raises(CalendarAccessError) as info:
            read(source, prompt=True)
        assert info.value.status is expected
    assert source.requests == [_api.ACCESS_TIMEOUT_S]


def test_access_timeout_constant() -> None:
    assert _api.ACCESS_TIMEOUT_S == 60.0


def test_access_error_message_has_remediation() -> None:
    message = str(CalendarAccessError(AccessStatus.DENIED))
    assert "calendars --prompt" in message
    assert "granted per launching context" in message
    assert "System Settings → Privacy & Security → Calendars" in message
    assert "\n" not in message


def test_status_and_request_wrappers() -> None:
    source = FakeSource(status=NOT_DETERMINED, status_after_request=FULL_ACCESS)
    assert _api.authorization_status(lambda: source) is AccessStatus.NOT_DETERMINED
    assert _api.request_access(lambda: source, 5.0) is AccessStatus.FULL_ACCESS
    assert source.requests == [5.0]


# --- wait_for_access -----------------------------------------------------------------


class _Status:
    def __init__(self, value: int) -> None:
        self.value = value

    def read(self) -> int:
        return self.value


def _threaded_requester(status: _Status, granted: bool) -> Callable[[Completion], None]:
    def request(completion: Completion) -> None:
        def fire() -> None:
            time.sleep(0.05)
            status.value = FULL_ACCESS if granted else DENIED
            completion(granted, None)

        threading.Thread(target=fire, daemon=True).start()

    return request


def test_wait_grant_from_another_thread() -> None:
    status = _Status(NOT_DETERMINED)
    started = time.monotonic()
    result = wait_for_access(_threaded_requester(status, True), status.read, timeout=5.0)
    assert result == FULL_ACCESS
    assert time.monotonic() - started < 2.0


def test_wait_deny_from_another_thread() -> None:
    status = _Status(NOT_DETERMINED)
    result = wait_for_access(_threaded_requester(status, False), status.read, timeout=5.0)
    assert result == DENIED


def test_wait_never_called_back_returns_current_status_after_timeout() -> None:
    status = _Status(NOT_DETERMINED)
    started = time.monotonic()
    result = wait_for_access(lambda completion: None, status.read, timeout=0.2)
    elapsed = time.monotonic() - started
    assert result == NOT_DETERMINED
    assert 0.2 <= elapsed < 0.2 + 0.5


@pytest.mark.parametrize("completed", [True, False])
def test_injected_wait_is_the_only_wait(completed: bool) -> None:
    """The run-loop seam: the fake waiter gets the event and timeout and decides
    when waiting ends; nothing else blocks."""
    status = _Status(NOT_DETERMINED)
    calls: list[tuple[threading.Event, float]] = []

    def fake_wait(event: threading.Event, timeout: float) -> bool:
        calls.append((event, timeout))
        if completed:
            status.value = FULL_ACCESS
        return completed

    started = time.monotonic()
    result = wait_for_access(lambda completion: None, status.read, 30.0, wait=fake_wait)
    assert time.monotonic() - started < 1.0
    assert len(calls) == 1
    assert isinstance(calls[0][0], threading.Event)
    assert calls[0][1] == 30.0
    assert result == (FULL_ACCESS if completed else NOT_DETERMINED)


def test_completion_sets_the_waited_event() -> None:
    seen: list[bool] = []

    def request(completion: Completion) -> None:
        completion(True, None)

    def fake_wait(event: threading.Event, timeout: float) -> bool:
        seen.append(event.is_set())
        return event.is_set()

    wait_for_access(request, lambda: FULL_ACCESS, 1.0, wait=fake_wait)
    assert seen == [True]
