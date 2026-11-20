"""Synthetic CLI fixtures for the golden files (R16: RFC 2606 addresses, made-up content).

Used by ``scripts/regen_goldens.py`` and the Phase 5b contract test. Each builder returns
the CLI argv plus the FakeSource to run it against.
"""

from __future__ import annotations

from typing import NamedTuple

from macos_calendar_events._raw import RawEvent
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


def _all_day(start_z: str, end_z: str, day: tuple[int, int, int], key: str, title: str) -> RawEvent:
    """An all-day row as captured on a Mac whose system zone gives these local components."""
    return raw_event(
        start_z,
        end_z,
        calendar_id="cal-holidays",
        external_id=f"ext-{key}",
        event_identifier=f"evt-{key}",
        title=title,
        all_day=True,
        time_zone=None,
        start_local=(*day, 0, 0, 0),
        end_local=(*day, 23, 59, 59),
        status=0,
    )


def _timed(start_z: str, end_z: str, zone: str, key: str, title: str) -> RawEvent:
    return raw_event(
        start_z,
        end_z,
        calendar_id="cal-work",
        external_id=f"ext-{key}",
        event_identifier=f"evt-{key}",
        title=title,
        time_zone=zone,
    )


# Events in Asia/Tokyo (+09:00), Asia/Kolkata (+05:30) and Europe/Helsinki (+02:00 in
# November). Each all-day row simulates a Mac in that zone (local components are per row).
ZONE_EVENTS = [
    # Tokyo 2025-11-20 01:00-01:30 JST: local date is a day after the UTC date.
    _timed("2025-11-19T16:00:00Z", "2025-11-19T16:30:00Z", "Asia/Tokyo", "tokyo", "Tokyo sync"),
    # Kolkata 21:45-22:15 IST: half-hour offset.
    _timed(
        "2025-11-19T16:15:00Z", "2025-11-19T16:45:00Z", "Asia/Kolkata", "kolkata", "Kolkata review"
    ),
    # Helsinki 19:00-19:15 EET: starts at --end (17:00Z); only the padding includes it.
    _timed(
        "2025-11-19T17:00:00Z",
        "2025-11-19T17:15:00Z",
        "Europe/Helsinki",
        "helsinki-edge",
        "Helsinki wrap-up",
    ),
    # Helsinki 19:15-19:30 EET: starts at the padded end (17:15Z): excluded.
    _timed(
        "2025-11-19T17:15:00Z",
        "2025-11-19T17:30:00Z",
        "Europe/Helsinki",
        "helsinki-after",
        "Helsinki after",
    ),
    # All-day 2025-11-20 in Tokyo: local midnight is 2025-11-19T15:00Z, so it overlaps.
    _all_day("2025-11-19T15:00:00Z", "2025-11-20T14:59:59Z", (2025, 11, 20), "jp-day", "JP Day"),
    # All-day 2025-11-21 in Tokyo: fetched by the widened query, filtered out.
    _all_day(
        "2025-11-20T15:00:00Z", "2025-11-21T14:59:59Z", (2025, 11, 21), "jp-next", "JP Next Day"
    ),
    # All-day 2025-11-19 in Kolkata: 2025-11-18T18:30Z to 2025-11-19T18:30Z.
    _all_day("2025-11-18T18:30:00Z", "2025-11-19T18:29:59Z", (2025, 11, 19), "in-day", "IN Day"),
    # All-day 2025-11-20 in Kolkata starts 18:30Z, after the padded end: filtered out.
    _all_day(
        "2025-11-19T18:30:00Z", "2025-11-20T18:29:59Z", (2025, 11, 20), "in-next", "IN Next Day"
    ),
    # All-day 2025-11-19 in Helsinki: 2025-11-18T22:00Z to 2025-11-19T22:00Z.
    _all_day("2025-11-18T22:00:00Z", "2025-11-19T21:59:59Z", (2025, 11, 19), "fi-day", "FI Day"),
    # All-day 2025-11-18 in Helsinki ends 2025-11-18T22:00Z: filtered out.
    _all_day(
        "2025-11-17T22:00:00Z", "2025-11-18T21:59:59Z", (2025, 11, 18), "fi-prev", "FI Prev Day"
    ),
]


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
        # canceled, starts 17:30Z, after the padded end (17:15Z): filtered by overlap
        raw_event(
            "2025-11-19T17:30:00Z",
            "2025-11-19T18:00:00Z",
            calendar_id="cal-work",
            external_id="ext-late",
            title="Late",
            status=3,
        ),
        *ZONE_EVENTS,
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
