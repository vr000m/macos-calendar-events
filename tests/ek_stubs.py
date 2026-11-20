"""Stub EventKit objects for adapter tests (no PyObjC, no TCC)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

from macos_calendar_events._eventkit import EventKitNamespace


class Obj:
    """An object whose attributes are zero-argument getters, like PyObjC properties."""

    def __init__(self, **values: Any) -> None:
        for name, value in values.items():
            setattr(self, name, lambda value=value: value)


class Date:
    def __init__(self, epoch: float) -> None:
        self.epoch = epoch

    def timeIntervalSince1970(self) -> float:
        return self.epoch


def calendar(identifier: str, title: str = "Work", source: Any = "default") -> Obj:
    if source == "default":
        source = Obj(title="iCloud", sourceType=2)
    return Obj(
        calendarIdentifier=identifier,
        title=title,
        source=source,
        color="red",
        allowsContentModifications=True,
    )


def event(
    cal: Any, start: float = 1763568000.0, end: float = 1763569800.0, **overrides: Any
) -> Obj:
    values: dict[str, Any] = {
        "calendar": cal,
        "calendarItemExternalIdentifier": "ext-1",
        "eventIdentifier": "evt-1",
        "title": "Planning",
        "startDate": Date(start),
        "endDate": Date(end),
        "occurrenceDate": Date(start),
        "isAllDay": False,
        "timeZone": Obj(name="America/Los_Angeles"),
        "location": None,
        "URL": None,
        "notes": None,
        "status": 1,
        "hasRecurrenceRules": False,
        "isDetached": False,
        "organizer": None,
        "attendees": None,
    }
    values.update(overrides)
    return Obj(**values)


class StubStore:
    def __init__(
        self,
        calendars: list[Any],
        events: list[Any],
        on_request: Callable[[Callable[[bool, object | None], None]], None] | None = None,
    ) -> None:
        self._calendars = calendars
        self._events = events
        self._on_request = on_request
        self.predicates: list[tuple[Any, Any, list[Any] | None]] = []
        self.requests = 0

    def calendarsForEntityType_(self, entity: int) -> list[Any]:
        return list(self._calendars)

    def calendarWithIdentifier_(self, identifier: str) -> Any:
        return next((c for c in self._calendars if c.calendarIdentifier() == identifier), None)

    def predicateForEventsWithStartDate_endDate_calendars_(
        self, start: Any, end: Any, calendars: list[Any] | None
    ) -> str:
        self.predicates.append((start, end, calendars))
        return "predicate"

    def eventsMatchingPredicate_(self, predicate: str) -> list[Any]:
        return list(self._events)

    def requestFullAccessToEventsWithCompletion_(
        self, completion: Callable[[bool, object | None], None]
    ) -> None:
        self.requests += 1
        if self._on_request is not None:
            self._on_request(completion)


class StubStoreClass:
    def __init__(self, status: int = 3, has_selector: bool = True) -> None:
        self.status = status
        self.has_selector = has_selector

    def authorizationStatusForEntityType_(self, entity: int) -> int:
        return self.status

    def instancesRespondToSelector_(self, selector: str) -> bool:
        return self.has_selector and selector == "requestFullAccessToEventsWithCompletion:"


@dataclasses.dataclass
class Factory:
    """Builds a fresh StubStore per call and remembers each one."""

    make: Callable[[], StubStore]
    built: list[StubStore] = dataclasses.field(default_factory=list)

    def __call__(self) -> StubStore:
        store = self.make()
        self.built.append(store)
        return store


def namespace(
    factory: Factory, store_class: StubStoreClass | None = None, **overrides: Any
) -> EventKitNamespace:
    ns = EventKitNamespace(
        store_class=store_class or StubStoreClass(),
        entity_type_event=0,
        new_store=factory,
        make_date=lambda seconds: seconds,
        local_components=lambda d: (2025, 11, 20, 0, 0, 0),
        to_srgb=lambda color: None if color is None else (1.0, 0.0, 0.0),
    )
    return dataclasses.replace(ns, **overrides)
