"""Waiting for the Calendar access completion handler (stdlib only)."""

from __future__ import annotations

import threading
from collections.abc import Callable


def wait_for_access(
    request: Callable[[Callable[[bool, object | None], None]], None],
    read_status: Callable[[], int],
    timeout: float,
    wait: Callable[[threading.Event, float], bool] = threading.Event.wait,
) -> int:
    """Call ``request`` with a completion handler, wait up to ``timeout``, return the status.

    The completion may fire on any thread; Phase 0 showed no run loop is needed. ``wait``
    is the seam for tests. If the completion never fires, the current status is returned.
    """
    done = threading.Event()

    def completion(granted: bool, error: object | None) -> None:
        done.set()

    request(completion)
    wait(done, timeout)
    return read_status()
