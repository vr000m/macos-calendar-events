"""scripts/validate_json.py prints only JSON paths and keywords, never values (R16)."""

import json
import subprocess
import sys
from pathlib import Path

from macos_calendar_events.models import window_to_json
from tests.model_fixtures import ALL_DAY, TIMED, WINDOW

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_json.py"
SENTINEL = "SENTINEL-" + "do-not-echo"


def _run(stdin: bytes, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True, check=False
    )


def _valid_doc() -> dict[str, object]:
    doc: dict[str, object] = json.loads(window_to_json([TIMED, ALL_DAY], window=WINDOW))
    return doc


def test_valid_document_passes_silently() -> None:
    proc = _run(json.dumps(_valid_doc()).encode(), "window-v1")
    assert proc.returncode == 0
    assert proc.stdout == b""


def test_invalid_document_reports_path_and_keyword_only() -> None:
    doc = _valid_doc()
    events = doc["events"]
    assert isinstance(events, list)
    events[0]["all_day"] = SENTINEL  # wrong type, carries the sentinel
    proc = _run(json.dumps(doc).encode(), "window-v1")
    assert proc.returncode == 1
    out = proc.stdout.decode() + proc.stderr.decode()
    assert SENTINEL not in out
    assert "$.events[0].all_day: type" in out


def test_format_invalid_instant_reports_format() -> None:
    doc = _valid_doc()
    events = doc["events"]
    assert isinstance(events, list)
    events[0]["start"] = "2025-13-45T99:99:99Z"
    proc = _run(json.dumps(doc).encode(), "window-v1")
    assert proc.returncode == 1
    assert proc.stdout.decode().strip() == "$.events[0].start: format"


def test_empty_stdin() -> None:
    proc = _run(b"", "window-v1")
    assert proc.returncode != 0
    assert proc.stdout == b""


def test_non_json_stdin_is_not_echoed() -> None:
    proc = _run(f"{{not json {SENTINEL}".encode(), "calendars-v1")
    assert proc.returncode != 0
    assert SENTINEL.encode() not in proc.stdout + proc.stderr


def test_unknown_schema_name() -> None:
    proc = _run(b"{}", "nope-v1")
    assert proc.returncode == 2
    assert proc.stdout == b""
