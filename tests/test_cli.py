"""CLI behavior via ``main([...], source=FakeSource(...))`` (R7, R11, R12, R18)."""

import json
import subprocess
import sys
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from macos_calendar_events import _eventkit
from macos_calendar_events._raw import EventSource
from macos_calendar_events.cli import main
from macos_calendar_events.errors import EventKitUnavailableError
from tests.fakes import NOT_DETERMINED, FakeSource, raw_calendar, raw_event
from tests.golden_fixtures import build_calendars_fixture, build_window_fixture

ROOT = Path(__file__).resolve().parents[1]
START, END = "1763568000", "1763571600"  # 2025-11-19T16:00:00Z .. 17:00:00Z
SENTINEL = "SENTINEL-" + "calendar-secret"


class Out:
    def __init__(self, code: int, out: str, err: str) -> None:
        self.code, self.out, self.err = code, out, err

    @property
    def doc(self) -> Any:
        return json.loads(self.out)

    @property
    def err_lines(self) -> list[str]:
        return self.err.splitlines()


@pytest.fixture
def run(capsys: pytest.CaptureFixture[str]) -> Callable[..., Out]:
    def call(argv: list[str], source: EventSource | None = None) -> Out:
        code = main(argv, source=source)
        captured = capsys.readouterr()
        return Out(code, captured.out, captured.err)

    return call


def window(*extra: str, start: str = START, end: str = END) -> list[str]:
    return ["window", "--start", start, "--end", end, *extra]


def cals() -> list[Any]:
    return [
        raw_calendar("cal-1", title="Work"),
        raw_calendar("cal-2", title="Home"),
        raw_calendar("cal-3", title="Trips"),
    ]


def source(**kw: Any) -> FakeSource:
    kw.setdefault("calendars", cals())
    kw.setdefault(
        "events",
        [
            raw_event(calendar_id="cal-1", external_id="w", notes="n"),
            raw_event(calendar_id="cal-2", external_id="h"),
            raw_event(calendar_id="cal-3", external_id="t"),
        ],
    )
    return FakeSource(**kw)


# --- output --------------------------------------------------------------------------


def test_window_outputs_json(run: Callable[..., Out]) -> None:
    result = run(window(), source())
    assert result.code == 0 and result.err == ""
    doc = result.doc
    assert doc["schema_version"] == 1
    assert sorted(e["external_id"] for e in doc["events"]) == ["h", "t", "w"]
    assert doc["window"] == {
        "start": "2025-11-19T16:00:00Z",
        "end": "2025-11-19T17:00:00Z",
        "start_ts": 1763568000,
        "end_ts": 1763571600,
    }
    assert result.out.endswith("}\n")


def test_output_instants_end_in_z(run: Callable[..., Out]) -> None:
    doc = run(window(), source()).doc
    for event in doc["events"]:
        for key in ("start", "end", "occurrence_start"):
            assert event[key].endswith("Z")


def test_calendars_outputs_json(run: Callable[..., Out]) -> None:
    result = run(["calendars"], source())
    assert result.code == 0
    assert [c["title"] for c in result.doc["calendars"]] == ["Home", "Trips", "Work"]


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0
    assert capsys.readouterr().out == "macos-calendar-events 0.1.0 (schema_version 1)\n"


# --- padding ------------------------------------------------------------------------


def test_pad_minutes_includes_early_event_and_echoes_padded_window(run: Callable[..., Out]) -> None:
    early = raw_event("2025-11-19T15:50:00Z", "2025-11-19T15:55:00Z", external_id="early")
    without = run(window(), FakeSource(events=[early]))
    assert without.doc["events"] == []
    result = run(window("--pad-minutes", "15"), FakeSource(events=[early]))
    assert [e["external_id"] for e in result.doc["events"]] == ["early"]
    assert result.doc["window"] == {
        "start": "2025-11-19T15:45:00Z",
        "end": "2025-11-19T17:15:00Z",
        "start_ts": 1763567100,
        "end_ts": 1763572500,
    }


def test_negative_pad_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(window("--pad-minutes", "-1"), source=source())
    assert info.value.code == 2
    assert capsys.readouterr().out == ""


def test_padding_over_cap_is_usage_error(run: Callable[..., Out]) -> None:
    # 3*365-2 days exactly is allowed; padding pushes it over the cap.
    end = str(1763568000 + (3 * 365 - 2) * 86400)
    assert run(window(end=end), source()).code == 0
    result = run(window("--pad-minutes", "1", end=end), source())
    assert result.code == 2 and result.out == ""


@pytest.mark.parametrize("minutes", ["2000000000", "99999999999999999999"])
def test_absurd_padding_is_usage_error_not_internal(run: Callable[..., Out], minutes: str) -> None:
    result = run(window("--pad-minutes", minutes), source())
    assert result.code == 2 and result.out == ""
    assert len(result.err_lines) == 1


def test_padding_before_1970(run: Callable[..., Out]) -> None:
    assert run(window("--pad-minutes", "15", start="0", end="3600"), source()).code == 2
    assert run(window("--pad-minutes", "0", start="0", end="3600"), source()).code == 0


# --- notes, calendars, prompt -----------------------------------------------------------


def test_include_notes(run: Callable[..., Out]) -> None:
    by_id = {e["external_id"]: e for e in run(window(), source()).doc["events"]}
    assert by_id["w"]["notes"] is None
    by_id = {e["external_id"]: e for e in run(window("--include-notes"), source()).doc["events"]}
    assert by_id["w"]["notes"] == "n"


def test_two_calendar_flags_restrict(run: Callable[..., Out]) -> None:
    result = run(window("--calendar", "Work", "--calendar", "cal-2"), source())
    assert sorted(e["external_id"] for e in result.doc["events"]) == ["h", "w"]


def test_unknown_calendar_exits_5(run: Callable[..., Out]) -> None:
    result = run(window("--calendar", "Work", "--calendar", "Nope"), source())
    assert result.code == 5
    assert result.out == ""
    assert len(result.err_lines) == 1
    assert "'Nope'" in result.err
    assert "Trips" not in result.err and "Home" not in result.err


def test_selector_with_newline_gives_one_line(run: Callable[..., Out]) -> None:
    result = run(window("--calendar", "bad\nname"), source())
    assert result.code == 5
    assert len(result.err_lines) == 1
    assert "Work" not in result.err


@pytest.mark.parametrize("argv", [window(), ["calendars"]])
def test_no_prompt_flag_never_requests(run: Callable[..., Out], argv: list[str]) -> None:
    fake = source(status=NOT_DETERMINED, status_after_request=3)
    result = run(argv, fake)
    assert result.code == 3
    assert fake.requests == []
    assert result.out == ""
    assert len(result.err_lines) == 1
    assert "calendars --prompt" in result.err
    assert "Work" not in result.err


@pytest.mark.parametrize("argv", [window("--prompt"), ["calendars", "--prompt"]])
def test_prompt_flag_requests_once(run: Callable[..., Out], argv: list[str]) -> None:
    fake = source(status=NOT_DETERMINED, status_after_request=3)
    assert run(argv, fake).code == 0
    assert len(fake.requests) == 1


def test_no_prompt_option_does_not_exist() -> None:
    with pytest.raises(SystemExit) as info:
        main(window("--no-prompt"), source=source())
    assert info.value.code == 2


# Every unambiguous prefix of every long option, per subcommand: argparse's default prefix
# matching would read ``--pro`` as ``--prompt`` and ``--i`` as ``--include-notes``.
_FLAGS = ("--include-notes", "--prompt")  # options that take no value
_OPTIONS = {
    "window": ("--start", "--end", "--calendar", "--pad-minutes", *_FLAGS),
    "calendars": ("--prompt",),
}
_ABBREVIATED = [
    (command, option, option[:length])
    for command, options in _OPTIONS.items()
    for option in options
    for length in range(3, len(option))
    if sum(o.startswith(option[:length]) for o in options) == 1
]


@pytest.mark.parametrize(("command", "option", "prefix"), _ABBREVIATED)
def test_abbreviated_options_are_rejected(command: str, option: str, prefix: str) -> None:
    fake = source(status=NOT_DETERMINED, status_after_request=3)
    base = window() if command == "window" else ["calendars"]
    value = [] if option in _FLAGS else ["5" if option == "--pad-minutes" else START]
    with pytest.raises(SystemExit) as info:
        main([*base, prefix, *value], source=fake)
    assert info.value.code == 2
    assert fake.requests == []  # an abbreviation never prompts


def test_abbreviation_table_includes_the_reported_cases() -> None:
    assert {("calendars", "--pro"), ("window", "--i")} <= {(c, p) for c, _, p in _ABBREVIATED}


# --- error mapping and R11 order ------------------------------------------------------


@pytest.fixture
def unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> EventSource:
        raise EventKitUnavailableError("EventKit requires macOS 14 or newer (platform: test)")

    monkeypatch.setattr(_eventkit, "default_source", boom)


@pytest.mark.usefixtures("unavailable")
def test_unavailable_exits_4(run: Callable[..., Out]) -> None:
    for argv in (window(), ["calendars"]):
        result = run(argv)
        assert result.code == 4
        assert result.out == ""
        assert len(result.err_lines) == 1


@pytest.mark.usefixtures("unavailable")
def test_order_usage_before_unavailable(run: Callable[..., Out]) -> None:
    assert run(window(start=END, end=START)).code == 2


@pytest.mark.usefixtures("unavailable")
def test_order_unavailable_before_selector(run: Callable[..., Out]) -> None:
    assert run(window("--calendar", "Nope")).code == 4


def test_order_access_before_selector(run: Callable[..., Out]) -> None:
    fake = source(status=NOT_DETERMINED)
    assert run(window("--calendar", "Nope"), fake).code == 3


def test_internal_error_hides_message(run: Callable[..., Out]) -> None:
    class Exploding(FakeSource):
        def calendars(self) -> Any:
            raise RuntimeError(SENTINEL)

    result = run(window(), Exploding())
    assert result.code == 1
    assert result.err == "internal error: RuntimeError\n"
    assert result.out == ""
    assert SENTINEL not in result.err


def test_non_invalid_query_value_error_is_internal(run: Callable[..., Out]) -> None:
    class BadValue(FakeSource):
        def calendars(self) -> Any:
            raise ValueError(SENTINEL)

    result = run(["calendars"], BadValue())
    assert (result.code, result.err) == (1, "internal error: ValueError\n")


def _simulated_non_darwin(argv: list[str]) -> subprocess.CompletedProcess[str]:
    code = (
        "import sys; sys.platform = 'linux'\n"
        "from macos_calendar_events.cli import main\n"
        f"sys.exit(main({argv!r}))\n"
    )
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)


def test_simulated_non_darwin_subprocess() -> None:
    proc = _simulated_non_darwin(["calendars"])
    assert proc.returncode == 4
    assert proc.stdout == ""
    assert len(proc.stderr.splitlines()) == 1
    assert _simulated_non_darwin(window(start=END, end=START)).returncode == 2


@pytest.mark.skipif(sys.platform == "darwin", reason="real non-darwin run (ubuntu CI)")
def test_non_darwin_module_run() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "macos_calendar_events.cli", "calendars"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 4
    inverted = subprocess.run(
        [sys.executable, "-m", "macos_calendar_events.cli", *window(start=END, end=START)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert inverted.returncode == 2


# --- input forms (R12) ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end", "code"),
    [
        ("1763568000", "1763571600", 0),
        ("2025-11-19T16:00:00Z", "2025-11-19T17:00:00Z", 0),
        ("2025-11-19T16:00:00+00:00", "2025-11-19T17:00:00+00:00", 0),
        ("2025-11-19T12:00:00.5Z", "2025-11-19T17:00:00Z", 0),
        ("2025-11-19T16:00:00", "2025-11-19T17:00:00Z", 2),
        ("2025-11-19T16:00:00+05:30", "2025-11-19T17:00:00Z", 2),
        ("2025-11-19", "2025-11-20", 2),
        ("2025-11-19T16:00:00-00:00", "2025-11-19T17:00:00Z", 2),
        ("1763568000.5", "1763571600", 2),
        ("-1", "1763571600", 2),
        ("1969-12-31T23:59:59Z", "1763571600", 2),
        ("2025-13-19T16:00:00Z", "2025-11-19T17:00:00Z", 2),  # regex ok, fromisoformat fails
        ("1763571600", "1763568000", 2),  # end <= start
        ("1763568000", "1763568000", 2),
        ("1763568000\n", "1763571600", 2),  # ``$`` must not accept a trailing newline
        ("2025-11-19T16:00:00Z\n", "2025-11-19T17:00:00Z", 2),  # same for RFC 3339
        ("9" * 5000, "1763571600", 2),  # beyond CPython's int-from-string digit limit
        ("253402214400", "253402300799", 2),  # widening by a day would pass year 9999
    ],
)
def test_input_forms(run: Callable[..., Out], start: str, end: str, code: int) -> None:
    result = run(window(start=start, end=end), source())
    assert result.code == code
    if code == 2:
        assert result.out == ""
        assert len(result.err_lines) == 1


def test_naive_and_offset_messages_are_one_utc_line(run: Callable[..., Out]) -> None:
    for bad in ("2025-11-19T16:00:00", "2025-11-19T16:00:00+05:30"):
        result = run(window(start=bad), source())
        assert result.code == 2 and result.out == ""
        assert len(result.err_lines) == 1
        assert "UTC" in result.err


def test_epoch_zero_and_1970_string_are_byte_identical(run: Callable[..., Out]) -> None:
    a = run(window(start="0", end="3600"), source())
    b = run(window(start="1970-01-01T00:00:00Z", end="3600"), source())
    assert a.code == b.code == 0
    assert a.out == b.out


def test_epoch_and_rfc3339_inputs_are_byte_identical(run: Callable[..., Out]) -> None:
    a = run(window(), source())
    b = run(window(start="2025-11-19T16:00:00Z", end="2025-11-19T17:00:00Z"), source())
    assert a.out == b.out and a.out != ""


def test_fractional_input_is_truncated(run: Callable[..., Out]) -> None:
    doc = run(window(start="2025-11-19T15:59:59.9Z"), source()).doc
    assert doc["window"]["start"] == "2025-11-19T15:59:59Z"


def test_old_and_multi_week_windows(run: Callable[..., Out]) -> None:
    old = raw_event("2025-01-06T17:15:00Z", "2025-01-06T17:45:00Z", external_id="old")
    result = run(
        window(start="2025-01-06T17:00:00Z", end="2025-01-06T18:00:00Z"),
        FakeSource(events=[old]),
    )
    assert result.code == 0
    assert [e["external_id"] for e in result.doc["events"]] == ["old"]
    later = raw_event("2025-12-20T10:00:00Z", "2025-12-20T11:00:00Z", external_id="later")
    result = run(
        window(start="2025-11-19T00:00:00Z", end="2025-12-31T00:00:00Z"),
        FakeSource(events=[later]),
    )
    assert result.code == 0
    assert [e["external_id"] for e in result.doc["events"]] == ["later"]


# --- schema command ---------------------------------------------------------------------


@pytest.mark.parametrize("name", ["window-v1", "calendars-v1"])
def test_schema_command_prints_packaged_bytes(
    capsysbinary: pytest.CaptureFixture[bytes], name: str
) -> None:
    assert main(["schema", name]) == 0
    packaged = (files("macos_calendar_events") / "schema" / f"{name}.schema.json").read_bytes()
    assert capsysbinary.readouterr().out == packaged


def test_unknown_schema_name(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(["schema", "nope"])
    assert info.value.code == 2
    assert capsys.readouterr().out == ""


# --- golden fixtures (rendered in memory; goldens are not written here) ----------------


def _schema(name: str) -> Draft202012Validator:
    text = (files("macos_calendar_events") / "schema" / f"{name}.schema.json").read_text()
    return Draft202012Validator(
        json.loads(text), format_checker=Draft202012Validator.FORMAT_CHECKER
    )


def test_golden_fixtures_render_schema_valid_output(run: Callable[..., Out]) -> None:
    window_fixture = build_window_fixture()
    result = run(window_fixture.argv, window_fixture.source)
    assert result.code == 0
    assert list(_schema("window-v1").iter_errors(result.doc)) == []
    events = {e["title"]: e for e in result.doc["events"]}
    assert "Réunion — 会議 ☕" in events  # non-ASCII, unescaped
    assert "Late" not in events
    window = result.doc["window"]
    assert (window["start_ts"], window["end_ts"]) == (1763568000 - 900, 1763571600 + 900)

    # Early sync is selected only because of --pad-minutes 15.
    early = events["Early sync"]
    unpadded = (1763568000, 1763571600)
    padded = (window["start_ts"], window["end_ts"])
    assert not (early["start_ts"] < unpadded[1] and early["end_ts"] > unpadded[0])
    assert early["start_ts"] < padded[1] and early["end_ts"] > padded[0]

    # Canceled events are returned with their status (R5).
    canceled = [e for e in result.doc["events"] if e["status"] == "canceled"]
    assert [e["title"] for e in canceled] == ["Canceled check-in"]

    # Zone rows (expected values hand-checked with TZ=<zone> /bin/date).
    zone_rows = {
        t: (events[t]["start"], events[t]["end"], events[t]["start_date"], events[t]["end_date"])
        for t in ("Tokyo sync", "Kolkata review", "Helsinki wrap-up", "JP Day", "IN Day", "FI Day")
    }
    assert zone_rows == {
        "Tokyo sync": ("2025-11-19T16:00:00Z", "2025-11-19T16:30:00Z", None, None),
        "Kolkata review": ("2025-11-19T16:15:00Z", "2025-11-19T16:45:00Z", None, None),
        "Helsinki wrap-up": ("2025-11-19T17:00:00Z", "2025-11-19T17:15:00Z", None, None),
        "JP Day": ("2025-11-19T15:00:00Z", "2025-11-20T15:00:00Z", "2025-11-20", "2025-11-21"),
        "IN Day": ("2025-11-18T18:30:00Z", "2025-11-19T18:30:00Z", "2025-11-19", "2025-11-20"),
        "FI Day": ("2025-11-18T22:00:00Z", "2025-11-19T22:00:00Z", "2025-11-19", "2025-11-20"),
    }
    assert events["Tokyo sync"]["time_zone"] == "Asia/Tokyo"
    assert events["Kolkata review"]["time_zone"] == "Asia/Kolkata"
    wrap_up = events["Helsinki wrap-up"]  # selected only because of the padding
    assert wrap_up["start_ts"] == unpadded[1] and wrap_up["end_ts"] == padded[1]
    # Widened query fetched these; strict overlap filtered them out.
    fetched = {
        r.title for r in window_fixture.source.events(*window_fixture.source.ranges[0][:2], None)
    }
    for title in ("Helsinki after", "JP Next Day", "IN Next Day", "FI Prev Day"):
        assert title in fetched and title not in events
    calendars_fixture = build_calendars_fixture()
    result = run(calendars_fixture.argv, calendars_fixture.source)
    assert result.code == 0
    assert list(_schema("calendars-v1").iter_errors(result.doc)) == []
    colors = [c["color_hex"] for c in result.doc["calendars"] if c["color_hex"] is not None]
    assert len(colors) == len(set(colors))  # non-null colors are distinct


def test_regen_script_renders_without_writing() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("regen", ROOT / "scripts" / "regen_goldens.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rendered = module.render_all()
    assert sorted(rendered) == ["calendars-v1.json", "window-v1.json"]
    assert all(data.endswith(b"}\n") for data in rendered.values())


# --- stdout write failures (R11: exit 1, one stderr line) ------------------------------


class _FailingBuffer:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    def write(self, data: bytes) -> int:
        raise self.exc


class _FailingStdout:
    def __init__(self, exc: BaseException) -> None:
        self.buffer = _FailingBuffer(exc)

    def flush(self) -> None:
        pass

    def fileno(self) -> int:
        raise OSError("no fd")


@pytest.mark.parametrize("exc", [BrokenPipeError(32, "Broken pipe"), OSError(28, "No space")])
@pytest.mark.parametrize("argv", [["schema", "window-v1"], ["calendars"], window()])
def test_stdout_write_failure_is_one_line_internal_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    exc: BaseException,
) -> None:
    monkeypatch.setattr(sys, "stdout", _FailingStdout(exc))
    code = main(argv, source=source())
    err = capsys.readouterr().err
    assert code == 1
    assert err.splitlines() == [f"internal error: {type(exc).__name__}"]


def test_closed_stdout_pipe_exits_1_with_one_line_subprocess() -> None:
    import os

    read_end, write_end = os.pipe()
    os.close(read_end)  # the reader went away before the CLI writes
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "macos_calendar_events.cli", "schema", "window-v1"],
            stdout=write_end,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    finally:
        os.close(write_end)
    assert proc.returncode == 1
    assert proc.stderr.splitlines() == ["internal error: BrokenPipeError"]
