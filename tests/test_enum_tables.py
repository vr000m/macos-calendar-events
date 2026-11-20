"""EventKit enum ints map to the public enums; unknown ints become UNKNOWN."""

import sys
from collections.abc import Callable
from enum import StrEnum
from typing import Any

import pytest

from macos_calendar_events import _mapping
from macos_calendar_events.models import (
    AccessStatus,
    EventStatus,
    ParticipantRole,
    ParticipantType,
    ParticipationStatus,
    SourceType,
)

# Hand-written from Apple's EventKit headers.
CASES: list[tuple[Callable[[int], StrEnum], dict[int, StrEnum], StrEnum]] = [
    (
        _mapping.access_status_from_int,
        {
            0: AccessStatus.NOT_DETERMINED,
            1: AccessStatus.RESTRICTED,
            2: AccessStatus.DENIED,
            3: AccessStatus.FULL_ACCESS,
            4: AccessStatus.WRITE_ONLY,
        },
        AccessStatus.UNKNOWN,
    ),
    (
        _mapping.source_type_from_int,
        {
            0: SourceType.LOCAL,
            1: SourceType.EXCHANGE,
            2: SourceType.CALDAV,
            3: SourceType.MOBILEME,
            4: SourceType.SUBSCRIBED,
            5: SourceType.BIRTHDAYS,
        },
        SourceType.UNKNOWN,
    ),
    (
        _mapping.event_status_from_int,
        {
            0: EventStatus.NONE,
            1: EventStatus.CONFIRMED,
            2: EventStatus.TENTATIVE,
            3: EventStatus.CANCELED,
        },
        EventStatus.UNKNOWN,
    ),
    (
        _mapping.participant_role_from_int,
        {
            0: ParticipantRole.UNKNOWN,
            1: ParticipantRole.REQUIRED,
            2: ParticipantRole.OPTIONAL,
            3: ParticipantRole.CHAIR,
            4: ParticipantRole.NON_PARTICIPANT,
        },
        ParticipantRole.UNKNOWN,
    ),
    (
        _mapping.participation_status_from_int,
        {
            0: ParticipationStatus.UNKNOWN,
            1: ParticipationStatus.PENDING,
            2: ParticipationStatus.ACCEPTED,
            3: ParticipationStatus.DECLINED,
            4: ParticipationStatus.TENTATIVE,
            5: ParticipationStatus.DELEGATED,
            6: ParticipationStatus.COMPLETED,
            7: ParticipationStatus.IN_PROCESS,
        },
        ParticipationStatus.UNKNOWN,
    ),
    (
        _mapping.participant_type_from_int,
        {
            0: ParticipantType.UNKNOWN,
            1: ParticipantType.PERSON,
            2: ParticipantType.ROOM,
            3: ParticipantType.RESOURCE,
            4: ParticipantType.GROUP,
        },
        ParticipantType.UNKNOWN,
    ),
]


@pytest.mark.parametrize(("convert", "table", "unknown"), CASES)
def test_known_and_unknown_ints(
    convert: Callable[[int], StrEnum], table: dict[int, StrEnum], unknown: StrEnum
) -> None:
    for value, expected in table.items():
        assert convert(value) == expected
    assert convert(99) == unknown
    assert convert(-1) == unknown


@pytest.mark.skipif(sys.platform != "darwin", reason="EventKit constants exist only on macOS")
def test_tables_match_eventkit_constants() -> None:
    """Constants need no TCC grant; this reads names only, never the calendar."""
    ek: Any = pytest.importorskip("EventKit")
    assert dict(_mapping.ACCESS_STATUS) == {
        ek.EKAuthorizationStatusNotDetermined: AccessStatus.NOT_DETERMINED,
        ek.EKAuthorizationStatusRestricted: AccessStatus.RESTRICTED,
        ek.EKAuthorizationStatusDenied: AccessStatus.DENIED,
        ek.EKAuthorizationStatusFullAccess: AccessStatus.FULL_ACCESS,
        ek.EKAuthorizationStatusWriteOnly: AccessStatus.WRITE_ONLY,
    }
    assert dict(_mapping.SOURCE_TYPE) == {
        ek.EKSourceTypeLocal: SourceType.LOCAL,
        ek.EKSourceTypeExchange: SourceType.EXCHANGE,
        ek.EKSourceTypeCalDAV: SourceType.CALDAV,
        ek.EKSourceTypeMobileMe: SourceType.MOBILEME,
        ek.EKSourceTypeSubscribed: SourceType.SUBSCRIBED,
        ek.EKSourceTypeBirthdays: SourceType.BIRTHDAYS,
    }
    assert dict(_mapping.EVENT_STATUS) == {
        ek.EKEventStatusNone: EventStatus.NONE,
        ek.EKEventStatusConfirmed: EventStatus.CONFIRMED,
        ek.EKEventStatusTentative: EventStatus.TENTATIVE,
        ek.EKEventStatusCanceled: EventStatus.CANCELED,
    }
    assert dict(_mapping.PARTICIPANT_ROLE) == {
        ek.EKParticipantRoleUnknown: ParticipantRole.UNKNOWN,
        ek.EKParticipantRoleRequired: ParticipantRole.REQUIRED,
        ek.EKParticipantRoleOptional: ParticipantRole.OPTIONAL,
        ek.EKParticipantRoleChair: ParticipantRole.CHAIR,
        ek.EKParticipantRoleNonParticipant: ParticipantRole.NON_PARTICIPANT,
    }
    assert dict(_mapping.PARTICIPATION_STATUS) == {
        ek.EKParticipantStatusUnknown: ParticipationStatus.UNKNOWN,
        ek.EKParticipantStatusPending: ParticipationStatus.PENDING,
        ek.EKParticipantStatusAccepted: ParticipationStatus.ACCEPTED,
        ek.EKParticipantStatusDeclined: ParticipationStatus.DECLINED,
        ek.EKParticipantStatusTentative: ParticipationStatus.TENTATIVE,
        ek.EKParticipantStatusDelegated: ParticipationStatus.DELEGATED,
        ek.EKParticipantStatusCompleted: ParticipationStatus.COMPLETED,
        ek.EKParticipantStatusInProcess: ParticipationStatus.IN_PROCESS,
    }
    assert dict(_mapping.PARTICIPANT_TYPE) == {
        ek.EKParticipantTypeUnknown: ParticipantType.UNKNOWN,
        ek.EKParticipantTypePerson: ParticipantType.PERSON,
        ek.EKParticipantTypeRoom: ParticipantType.ROOM,
        ek.EKParticipantTypeResource: ParticipantType.RESOURCE,
        ek.EKParticipantTypeGroup: ParticipantType.GROUP,
    }
