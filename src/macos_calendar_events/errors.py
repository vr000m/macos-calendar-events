"""Exception hierarchy. Messages never include calendar content (R16)."""

from __future__ import annotations

from collections.abc import Sequence

from .models import AccessStatus

ACCESS_REMEDIATION = (
    "Calendar access is granted per launching context. "
    "Run `macos-calendar-events calendars --prompt` once from the same context "
    "(the same terminal app, or the same launchd job/interpreter), "
    "or enable an existing entry in System Settings → Privacy & Security → Calendars"
)


class MacosCalendarEventsError(Exception):
    """Base class for every error this package raises on purpose."""


class CalendarAccessError(MacosCalendarEventsError):
    """Calendar access is not ``full_access`` (R9). The message is the remediation text."""

    def __init__(self, status: AccessStatus) -> None:
        super().__init__(ACCESS_REMEDIATION)
        self.status = status


class CalendarNotFoundError(MacosCalendarEventsError):
    """One or more calendar selectors matched nothing (R6).

    The message names only the unmatched selectors (via ``repr``); available calendar
    titles are kept on the instance, never in the message.
    """

    def __init__(self, selectors: Sequence[str], available_titles: Sequence[str]) -> None:
        self.selectors = tuple(selectors)
        self.available_titles = tuple(available_titles)
        names = ", ".join(repr(s) for s in self.selectors)
        super().__init__(f"calendar selector not found: {names}")


class EventKitUnavailableError(MacosCalendarEventsError):
    """EventKit can't be used: not macOS, macOS older than 14, or PyObjC missing (R19)."""


class InvalidQueryError(MacosCalendarEventsError, ValueError):
    """An invalid window or ``calendars=[]``; the only ``ValueError`` the CLI maps to exit 2."""
