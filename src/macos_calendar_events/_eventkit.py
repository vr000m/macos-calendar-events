"""EventKit adapter: the only module that imports PyObjC (filled in Phase 4)."""

from typing import Any


def _load_eventkit() -> Any:
    import EventKit

    return EventKit
