"""Hand-written model fixtures shared by the model and schema tests (synthetic data only)."""

from datetime import UTC, date, datetime

from macos_calendar_events.models import (
    CalendarInfo,
    CalendarRef,
    Event,
    EventStatus,
    Participant,
    ParticipantRole,
    ParticipantType,
    ParticipationStatus,
    SourceType,
)

ORGANIZER = Participant(
    name="Alex Example",
    email="alex@example.com",
    url=None,
    role=ParticipantRole.CHAIR,
    status=ParticipationStatus.ACCEPTED,
    type=ParticipantType.PERSON,
    is_self=False,
)
SELF_ATTENDEE = Participant(
    name=None,
    email=None,
    url="urn:uuid:00000000-0000-0000-0000-000000000001",
    role=ParticipantRole.REQUIRED,
    status=ParticipationStatus.ACCEPTED,
    type=ParticipantType.PERSON,
    is_self=True,
)

TIMED = Event(
    id="a1b2c3d4e5f60718",
    external_id="ext-1",
    event_identifier="evt-1",
    title="Planning",
    start=datetime(2025, 11, 19, 16, 0, tzinfo=UTC),
    end=datetime(2025, 11, 19, 16, 30, tzinfo=UTC),
    all_day=False,
    start_date=None,
    end_date=None,
    time_zone="America/Los_Angeles",
    location="Room 1",
    url=None,
    notes=None,
    status=EventStatus.CONFIRMED,
    is_recurring=False,
    is_detached=False,
    occurrence_start=datetime(2025, 11, 19, 16, 0, tzinfo=UTC),
    organizer=ORGANIZER,
    attendees=(ORGANIZER, SELF_ATTENDEE),
    self_status=ParticipationStatus.ACCEPTED,
    calendar=CalendarRef(id="cal-1", title="Work", source_title="iCloud"),
)

ALL_DAY = Event(
    id="0123456789abcdef",
    external_id=None,
    event_identifier=None,
    title="Holiday",
    start=datetime(2025, 11, 20, 8, 0, tzinfo=UTC),
    end=datetime(2025, 11, 21, 8, 0, tzinfo=UTC),
    all_day=True,
    start_date=date(2025, 11, 20),
    end_date=date(2025, 11, 21),
    time_zone=None,
    location=None,
    url=None,
    notes=None,
    status=EventStatus.NONE,
    is_recurring=False,
    is_detached=False,
    occurrence_start=datetime(2025, 11, 20, 8, 0, tzinfo=UTC),
    organizer=None,
    attendees=(),
    self_status=None,
    calendar=CalendarRef(id="cal-2", title=None, source_title=None),
)

WINDOW = (datetime(2025, 11, 19, 16, 0, tzinfo=UTC), datetime(2025, 11, 21, 16, 0, tzinfo=UTC))

CALENDAR = CalendarInfo(
    id="cal-1",
    title="Work",
    source_title="iCloud",
    source_type=SourceType.CALDAV,
    color_hex="#0080FF",
    read_only=False,
)
