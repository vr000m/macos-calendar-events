"""R18 contract: CLI stdout validates against the v1 schemas and equals the hand-reviewed
goldens byte for byte; error exits leave stdout empty; the real entry points work.

Goldens are change detectors: regenerate with scripts/regen_goldens.py, hand-review,
and add a CHANGELOG line for any golden change.
"""

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
from macos_calendar_events.cli import main
from macos_calendar_events.errors import EventKitUnavailableError
from tests.fakes import NOT_DETERMINED, FakeSource, raw_calendar
from tests.golden_fixtures import CliFixture, build_calendars_fixture, build_window_fixture

GOLDEN = Path(__file__).resolve().parent / "golden"


def _validator(name: str) -> Draft202012Validator:
    text = (files("macos_calendar_events") / "schema" / f"{name}.schema.json").read_text("utf-8")
    return Draft202012Validator(
        json.loads(text), format_checker=Draft202012Validator.FORMAT_CHECKER
    )


@pytest.mark.parametrize(
    ("schema", "builder"),
    [("window-v1", build_window_fixture), ("calendars-v1", build_calendars_fixture)],
)
def test_stdout_validates_and_matches_golden(
    capsysbinary: pytest.CaptureFixture[bytes], schema: str, builder: Callable[[], CliFixture]
) -> None:
    fixture = builder()
    assert main(fixture.argv, source=fixture.source) == 0
    captured = capsysbinary.readouterr()
    assert captured.err == b""
    errors = [e.validator for e in _validator(schema).iter_errors(json.loads(captured.out))]
    assert errors == []
    assert captured.out == (GOLDEN / f"{schema}.json").read_bytes()


def _raising_calendars(exc: Exception) -> FakeSource:
    class Raising(FakeSource):
        def calendars(self) -> Any:
            raise exc

    return Raising()


WINDOW = ["window", "--start", "1763568000", "--end", "1763571600"]


@pytest.mark.parametrize(
    ("argv", "source", "code"),
    [
        (["window", "--start", "1763571600", "--end", "1763568000"], FakeSource(), 2),
        ([*WINDOW[:2], "nope", *WINDOW[3:]], FakeSource(), 2),
        (WINDOW, FakeSource(status=NOT_DETERMINED), 3),
        (["calendars"], FakeSource(status=NOT_DETERMINED), 3),
        ([*WINDOW, "--calendar", "missing"], FakeSource(calendars=[raw_calendar()]), 5),
        (WINDOW, _raising_calendars(RuntimeError("boom")), 1),
        (["calendars"], _raising_calendars(KeyError("boom")), 1),
    ],
)
def test_error_exits_leave_stdout_empty(
    capsysbinary: pytest.CaptureFixture[bytes], argv: list[str], source: FakeSource, code: int
) -> None:
    assert main(argv, source=source) == code
    captured = capsysbinary.readouterr()
    assert captured.out == b""
    assert len(captured.err.decode().splitlines()) == 1


def test_unavailable_exit_leaves_stdout_empty(
    capsysbinary: pytest.CaptureFixture[bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> Any:
        raise EventKitUnavailableError("unavailable (test)")

    monkeypatch.setattr(_eventkit, "default_source", boom)
    assert main(["calendars"]) == 4
    assert capsysbinary.readouterr().out == b""


@pytest.mark.parametrize(
    "argv",
    [["window"], ["schema", "nope"], ["frobnicate"], [*WINDOW, "--pad-minutes", "-1"]],
)
def test_argparse_errors_leave_stdout_empty(
    capsysbinary: pytest.CaptureFixture[bytes], argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as info:
        main(argv, source=FakeSource())
    assert info.value.code == 2
    assert capsysbinary.readouterr().out == b""


# --- real entry points (never reach EventKit: no TCC) ----------------------------------

SCRIPT = Path(sys.executable).parent / "macos-calendar-events"
ENTRY_POINTS = {
    "module": [sys.executable, "-m", "macos_calendar_events.cli"],
    "script": [str(SCRIPT)],
}


def _run(entry: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*ENTRY_POINTS[entry], *args], capture_output=True, text=True, check=False, timeout=30
    )


def test_installed_script_exists() -> None:
    assert SCRIPT.is_file(), "the venv should contain the console script"


@pytest.mark.parametrize("entry", sorted(ENTRY_POINTS))
def test_help_exits_0(entry: str) -> None:
    proc = _run(entry, "--help")
    assert proc.returncode == 0
    assert "window" in proc.stdout and "calendars" in proc.stdout


@pytest.mark.parametrize("entry", sorted(ENTRY_POINTS))
def test_unparseable_start_exits_2_with_empty_stdout(entry: str) -> None:
    proc = _run(entry, "window", "--start", "yesterday", "--end", "1763571600")
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert len(proc.stderr.splitlines()) == 1


@pytest.mark.parametrize("entry", sorted(ENTRY_POINTS))
def test_version(entry: str) -> None:
    proc = _run(entry, "--version")
    assert proc.returncode == 0
    assert proc.stdout == "macos-calendar-events 0.1.0 (schema_version 1)\n"
