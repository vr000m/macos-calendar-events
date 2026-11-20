"""Opt-in live smoke against the real calendar (R16: integer counts only).

Runs only with ``MACOS_CALENDAR_EVENTS_LIVE=1`` on macOS. Never prompts (``prompt=False``).
Every live call is wrapped so a failure reports only the exception class name.
"""

import itertools
import json
import os
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import Any, TypeVar

import pytest
from jsonschema import Draft202012Validator

from macos_calendar_events import _api, _eventkit
from macos_calendar_events._mapping import MAX_WINDOW, overlaps
from macos_calendar_events._raw import EventSource
from macos_calendar_events.models import Event, SourceType, calendars_to_json, window_to_json
from tests.fakes import FakeSource

LIVE = pytest.mark.skipif(
    not (os.environ.get("MACOS_CALENDAR_EVENTS_LIVE") == "1" and sys.platform == "darwin"),
    reason="set MACOS_CALENDAR_EVENTS_LIVE=1 on macOS to run",
)
T = TypeVar("T")


class SmokeFailure(AssertionError):
    pass


def guarded(call: Callable[[], T]) -> T:
    try:
        return call()
    except Exception as exc:
        raise SmokeFailure(f"live call failed: {type(exc).__name__}") from None


def _schema_error_count(name: str, text: str) -> int:
    schema = json.loads(
        (files("macos_calendar_events") / "schema" / f"{name}.schema.json").read_text()
    )
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    try:
        document = json.loads(text)
    except ValueError:
        return 1
    return sum(1 for _ in validator.iter_errors(document))


def smoke_counts(get_source: Callable[[], EventSource], now: datetime) -> dict[str, int]:
    window = (now - timedelta(days=7), now + timedelta(days=7))
    result = guarded(
        lambda: _api.query_events(
            get_source, *window, calendars=None, include_notes=False, prompt=False
        )
    )
    calendars = guarded(lambda: _api.query_calendars(get_source, prompt=False))
    events: list[Event] = result.events
    source_type = {c.id: c.source_type for c in calendars}
    calendars_by_external: dict[str, set[str]] = defaultdict(set)
    for e in events:
        if e.external_id is not None:
            calendars_by_external[e.external_id].add(e.calendar.id)
    instants = [d for e in events for d in (e.start, e.end, e.occurrence_start)]
    return {
        # violations (must be 0)
        "non_aware_datetimes": sum(1 for d in instants if d.utcoffset() is None),
        "start_after_end": sum(1 for e in events if e.start > e.end),
        "non_overlapping": sum(1 for e in events if not overlaps(e.start, e.end, *window)),
        "empty_ids": sum(1 for e in events if not e.id),
        "duplicate_ids": len(events) - len({e.id for e in events}),
        "window_schema_errors": _schema_error_count(
            "window-v1", guarded(lambda: window_to_json(events, window=window))
        ),
        "calendars_schema_errors": _schema_error_count(
            "calendars-v1", guarded(lambda: calendars_to_json(calendars))
        ),
        # informational
        "calendars": len(calendars),
        "events": len(events),
        "skipped_r3": result.skipped,
        "all_day_null_dates": sum(
            1 for e in events if e.all_day and (e.start_date is None or e.end_date is None)
        ),
        "end_date_not_after_start_date": sum(
            1
            for e in events
            if e.start_date is not None and e.end_date is not None and e.end_date <= e.start_date
        ),
        "timed_with_dates": sum(
            1 for e in events if not e.all_day and (e.start_date or e.end_date)
        ),
        "detached": sum(1 for e in events if e.is_detached),
        "floating_timed": sum(1 for e in events if not e.all_day and e.time_zone is None),
        "exchange_rows": sum(
            1 for e in events if source_type.get(e.calendar.id) is SourceType.EXCHANGE
        ),
        "external_id_cross_calendar": sum(1 for c in calendars_by_external.values() if len(c) > 1),
    }


VIOLATIONS = (
    "non_aware_datetimes",
    "start_after_end",
    "non_overlapping",
    "empty_ids",
    "duplicate_ids",
    "window_schema_errors",
    "calendars_schema_errors",
)


def _print_counts(counts: dict[str, int]) -> None:
    for name in sorted(counts):
        print(f"{name}={counts[name]}")


RowKey = tuple[str, str | None, str | None, datetime, datetime, datetime]


def _keys(events: list[Event]) -> Counter[RowKey]:
    """Each row's identity and instants, counted (a multiset: identical rows all count)."""
    return Counter(
        (e.calendar.id, e.event_identifier, e.external_id, e.occurrence_start, e.start, e.end)
        for e in events
    )


def cap_difference(get_source: Callable[[], EventSource], start: datetime) -> int:
    """Rows in one result but not the other: one query vs the three chunks (0 = same rows).

    Rows are compared as a multiset of full keys (both identifiers, occurrence start, start
    and end), so a missing row is never masked by a different extra row, by a row that shares
    its identifiers, or by a duplicate. A row in several chunks (it spans a chunk boundary)
    counts once: the chunks merge by taking each key's largest count.
    """

    def run(a: datetime, b: datetime) -> list[Event]:
        return guarded(
            lambda: (
                _api.query_events(
                    get_source, a, b, calendars=None, include_notes=False, prompt=False
                ).events
            )
        )

    end = start + MAX_WINDOW
    step = MAX_WINDOW / 3
    bounds = [start, start + step, start + 2 * step, end]
    single = _keys(run(start, end))
    union: Counter[RowKey] = Counter()
    for a, b in itertools.pairwise(bounds):
        union |= _keys(run(a, b))  # elementwise max
    difference = sum(((single - union) + (union - single)).values())
    print(f"cap_single={single.total()} cap_union={union.total()} cap_difference={difference}")
    return difference


# --- live ---------------------------------------------------------------------------


@pytest.mark.live
@LIVE
def test_live_smoke_counts() -> None:
    status = guarded(lambda: _api.authorization_status(_eventkit.default_source))
    assert status == "full_access", "live smoke needs full_access in this launching context"
    counts = smoke_counts(_eventkit.default_source, datetime.now(UTC).replace(microsecond=0))
    _print_counts(counts)
    assert counts["calendars"] > 0
    assert {name: counts[name] for name in VIOLATIONS} == dict.fromkeys(VIOLATIONS, 0)


@pytest.mark.live
@LIVE
def test_live_cap_consistency() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    assert cap_difference(_eventkit.default_source, start) == 0


# --- non-live guard on the helper ---------------------------------------------------

SENTINEL = "SENTINEL-" + "private-calendar-text"


class _Exploding(FakeSource):
    def calendars(self) -> Any:
        raise RuntimeError(SENTINEL)


def test_smoke_failure_hides_exception_text(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SmokeFailure) as info:
        smoke_counts(lambda: _Exploding(), datetime(2025, 11, 19, tzinfo=UTC))
    out = capsys.readouterr()
    assert SENTINEL not in str(info.value)
    assert SENTINEL not in out.out + out.err
    assert "RuntimeError" in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_smoke_counts_on_fake_are_clean() -> None:
    from tests.fakes import raw_event

    now = datetime(2025, 11, 19, 16, 0, tzinfo=UTC)
    counts = smoke_counts(lambda: FakeSource(events=[raw_event()]), now)
    assert {name: counts[name] for name in VIOLATIONS} == dict.fromkeys(VIOLATIONS, 0)
    assert counts["events"] == 1 and counts["calendars"] == 1


class _Scripted(FakeSource):
    """Returns ``first`` for the single full-window query, ``chunks`` for each chunk query."""

    def __init__(self, first: list[Any], chunks: list[Any]) -> None:
        super().__init__()
        self._first, self._chunks, self._calls = first, chunks, 0

    def events(self, start: datetime, end: datetime, calendar_ids: Any) -> Any:
        self._calls += 1
        return self._first if self._calls == 1 else self._chunks


def _cap_row(spec: str) -> Any:
    """``"a"``: event ``a`` 10:00-11:00; ``"a@12"``: the same identifiers and occurrence start
    but ending 12:00."""
    from tests.fakes import raw_event

    event_id, _, end_hour = spec.partition("@")
    # Inside every chunk of the cap window that starts at 2024-01-01.
    return raw_event(
        "2024-06-01T10:00:00Z",
        f"2024-06-01T{end_hour or '11'}:00:00Z",
        event_identifier=event_id,
    )  # occurrence start defaults to the start: identical for "a" and "a@12"


@pytest.mark.parametrize(
    ("single", "chunks", "expected"),
    [
        (["a"], ["a"], 0),  # same rows
        ([], [], 0),
        (["a", "b"], ["a", "b"], 0),
        (["a"], ["b"], 2),  # same size, different rows: must not pass
        ([], ["a"], 1),  # a row missing from the single query (the targeted failure)
        (["a"], [], 1),  # an extra row in the single query
        (["a", "b"], ["a", "c"], 2),
        (["a"], ["a", "a@12"], 1),  # same identifiers and occurrence start, other end
        (["a@12"], ["a"], 2),
        (["a"], ["a", "a"], 1),  # one of two identical rows missing
        (["a", "a"], ["a"], 1),
        (["a", "a"], ["a", "a"], 0),
    ],
)
def test_cap_difference_compares_sets_not_sizes(
    single: list[str], chunks: list[str], expected: int
) -> None:
    source = _Scripted([_cap_row(i) for i in single], [_cap_row(i) for i in chunks])
    start = datetime(2024, 1, 1, tzinfo=UTC)
    assert cap_difference(lambda: source, start) == expected
