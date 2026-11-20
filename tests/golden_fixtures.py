"""Synthetic CLI fixtures for the golden files (R16: RFC 2606 addresses, made-up content).

Used by ``scripts/regen_goldens.py`` and the Phase 5b contract test. Each builder returns
the CLI argv plus the FakeSource to run it against.
"""

from __future__ import annotations

from typing import NamedTuple

from tests.fakes import FULL_ACCESS, FakeSource, raw_calendar, raw_event, raw_participant, ts


class CliFixture(NamedTuple):
    argv: list[str]
    source: FakeSource


CALENDARS = [
    raw_calendar(
        "cal-work",
        title="Work",
        source_title="Example Org",
        source_type=1,
        color_rgb=(1.0, 0.4, 0.0),  # #FF6600, distinct from the builder default
    ),
    raw_calendar(
        "cal-home",
        title="Home",
        source_title="iCloud",
        source_type=2,
        color_rgb=(0.0, 0.5, 1.0),
    ),
    raw_calendar(
        "cal-holidays",
        title="Holidays",
        source_title=None,
        source_type=4,
        color_rgb=None,
        allows_modifications=False,
    ),
]

ORGANIZER = raw_participant(
    name="Alex Example", url="mailto:alex@example.com", role=3, status=2, type=1
)
SELF = raw_participant(
    name="Sam Example", url="mailto:sam@example.org", role=1, status=4, type=1, is_current_user=True
)
ROOM = raw_participant(name="Room 1", url="urn:x-room:example-1", role=4, status=0, type=2)


def build_window_fixture() -> CliFixture:
    """A 16:00-17:00Z window (epoch input) padded by 15 minutes."""
    events = [
        # 15:50-15:55Z: ends before --start (16:00Z), so only the 15-minute padding includes it
        raw_event(
            "2025-11-19T15:50:00Z",
            "2025-11-19T15:55:00Z",
            calendar_id="cal-work",
            external_id="ext-early",
            event_identifier="evt-early",
            title="Early sync",
        ),
        # non-ASCII title; organizer also listed in attendees; self attendee tentative
        raw_event(
            "2025-11-19T16:00:00Z",
            "2025-11-19T16:30:00Z",
            calendar_id="cal-work",
            external_id="ext-planning",
            event_identifier="evt-planning",
            title="Réunion — 会議 ☕",
            location="Room 1",
            url="https://example.com/meetings/1",
            notes="Agenda: example notes",
            organizer=ORGANIZER,
            attendees=(ORGANIZER, SELF, ROOM),
            has_recurrence_rules=True,
        ),
        # nil attendees, nil organizer, floating, nil identifiers
        raw_event(
            "2025-11-19T16:30:00Z",
            "2025-11-19T17:00:00Z",
            calendar_id="cal-home",
            external_id=None,
            event_identifier=None,
            title="Focus time",
            time_zone=None,
            status=2,
        ),
        # all-day (system zone America/Los_Angeles), inclusive 23:59:59 end
        raw_event(
            "2025-11-19T08:00:00Z",
            "2025-11-20T07:59:59Z",
            calendar_id="cal-holidays",
            external_id="ext-holiday",
            event_identifier="evt-holiday",
            title="Example Day",
            all_day=True,
            time_zone=None,
            start_local=(2025, 11, 19, 0, 0, 0),
            end_local=(2025, 11, 19, 23, 59, 59),
            status=0,
        ),
        # canceled inside the unpadded window: returned with status canceled (R5)
        raw_event(
            "2025-11-19T16:40:00Z",
            "2025-11-19T16:50:00Z",
            calendar_id="cal-home",
            external_id="ext-canceled",
            event_identifier="evt-canceled",
            title="Canceled check-in",
            status=3,
        ),
        # canceled, outside the padded window (ends after 17:15Z start): filtered by overlap
        raw_event(
            "2025-11-19T17:30:00Z",
            "2025-11-19T18:00:00Z",
            calendar_id="cal-work",
            external_id="ext-late",
            title="Late",
            status=3,
        ),
    ]
    assert ts("2025-11-19T16:00:00Z") == 1763568000
    argv = [
        "window",
        "--start",
        "1763568000",
        "--end",
        "1763571600",
        "--pad-minutes",
        "15",
    ]
    return CliFixture(argv, FakeSource(status=FULL_ACCESS, calendars=CALENDARS, events=events))


def build_calendars_fixture() -> CliFixture:
    return CliFixture(["calendars"], FakeSource(status=FULL_ACCESS, calendars=CALENDARS))
