"""The README's integration example returns events only for a schema-valid document (R18).

Any other outcome (a non-zero exit, a launch failure, bytes that are not JSON, a document
the installed CLI's schema rejects, a schema that can't be used) is "no calendar hints".
"""

import json
import re
import subprocess
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
GOLDEN = json.loads((ROOT / "tests" / "golden" / "window-v1.json").read_text("utf-8"))
SCHEMA = (files("macos_calendar_events") / "schema" / "window-v1.schema.json").read_bytes()


def _calendar_hints() -> Callable[[int, int], Any]:
    blocks = re.findall(r"```python\n(.*?)```", README.read_text("utf-8"), flags=re.DOTALL)
    [code] = [b for b in blocks if "def calendar_hints" in b]
    namespace: dict[str, Any] = {}
    exec(compile(code, str(README), "exec"), namespace)
    hints: Callable[[int, int], Any] = namespace["calendar_hints"]
    return hints


Reply = tuple[int, bytes] | BaseException


def _install(monkeypatch: pytest.MonkeyPatch, schema: Reply, window: Reply) -> None:
    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        reply = schema if cmd[1] == "schema" else window
        if isinstance(reply, BaseException):
            raise reply
        return subprocess.CompletedProcess(cmd, reply[0], reply[1], b"")

    monkeypatch.setattr(subprocess, "run", fake_run)


def _doc(**changes: Any) -> bytes:
    doc = dict(GOLDEN)
    for key, value in changes.items():
        if value is _MISSING:
            doc.pop(key)
        else:
            doc[key] = value
    return json.dumps(doc).encode()


_MISSING = object()
_EVENT = GOLDEN["events"][0]


def test_schema_valid_document_returns_its_events(monkeypatch: pytest.MonkeyPatch) -> None:
    assert GOLDEN["events"], "the golden document has events"
    _install(monkeypatch, (0, SCHEMA), (0, json.dumps(GOLDEN).encode()))
    assert _calendar_hints()(1763568000, 1763571600) == GOLDEN["events"]


def test_no_events_is_an_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, (0, SCHEMA), (0, _doc(events=[])))
    assert _calendar_hints()(1763568000, 1763571600) == []


@pytest.mark.parametrize(
    "stdout",
    [
        _doc(schema_version=True),  # True == 1 in Python, not in JSON Schema
        _doc(schema_version=2),
        _doc(schema_version="1"),
        _doc(schema_version=_MISSING),
        _doc(events=[None]),
        _doc(events=[{"id": "x"}]),  # an event without its required keys
        _doc(events=[{**_EVENT, "start_ts": "1763568000"}]),  # a retyped field
        _doc(events=[{**_EVENT, "attendees": None}]),
        # pattern-valid but not real dates: only a format checker rejects them
        _doc(events=[{**_EVENT, "start": "2025-02-30T12:00:00Z"}]),
        _doc(events=[{**_EVENT, "start": "2025-13-45T99:99:99Z"}]),
        _doc(events=[{**_EVENT, "start_date": "yesterday"}]),
        _doc(window={**GOLDEN["window"], "end": "2025-11-31T00:00:00Z"}),
        _doc(extra=float("nan")),  # not JSON, even in a field the schema doesn't name
        _doc(extra=float("inf")),
        _doc(events={}),
        _doc(events=_MISSING),
        _doc(window=_MISSING),
        b"[]",
        b"null",
        b'"text"',
        b"not json",
        b"\xff\xfe",  # not UTF-8
        b"",
        b'{"schema_version": NaN, "events": []}',
        b"[" * 20_000,  # too deep for the decoder (RecursionError)
    ],
)
def test_schema_invalid_document_is_no_hints(
    monkeypatch: pytest.MonkeyPatch, stdout: bytes
) -> None:
    _install(monkeypatch, (0, SCHEMA), (0, stdout))
    assert _calendar_hints()(1763568000, 1763571600) is None


@pytest.mark.parametrize(
    ("schema", "window"),
    [
        ((0, SCHEMA), (3, b"")),  # any non-zero exit
        ((0, SCHEMA), (1, json.dumps(GOLDEN).encode())),  # stdout ignored on failure
        ((2, b""), (0, json.dumps(GOLDEN).encode())),  # the schema command failed
        ((0, b"not json"), (0, json.dumps(GOLDEN).encode())),
        ((0, b'{"type": 5}'), (0, json.dumps(GOLDEN).encode())),  # an unusable schema
        (FileNotFoundError(2, "missing"), (0, json.dumps(GOLDEN).encode())),
        ((0, SCHEMA), FileNotFoundError(2, "missing")),
        ((0, SCHEMA), PermissionError(13, "denied")),
        ((0, SCHEMA), subprocess.TimeoutExpired("cli", 10)),
        (subprocess.TimeoutExpired("cli", 10), (0, json.dumps(GOLDEN).encode())),
    ],
)
def test_command_failures_are_no_hints(
    monkeypatch: pytest.MonkeyPatch, schema: Reply, window: Reply
) -> None:
    _install(monkeypatch, schema, window)
    assert _calendar_hints()(1763568000, 1763571600) is None
