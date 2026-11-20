"""The README's integration example treats any mismatch as "no calendar hints" (R18)."""

import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

README = Path(__file__).resolve().parents[1] / "README.md"


def _calendar_hints() -> Callable[[int, int], Any]:
    blocks = re.findall(r"```python\n(.*?)```", README.read_text("utf-8"), flags=re.DOTALL)
    [code] = [b for b in blocks if "def calendar_hints" in b]
    namespace: dict[str, Any] = {}
    exec(compile(code, str(README), "exec"), namespace)
    hints: Callable[[int, int], Any] = namespace["calendar_hints"]
    return hints


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [
        (0, b'{"schema_version": 1, "events": [{"id": "x"}]}', [{"id": "x"}]),
        (0, b'{"schema_version": 1, "events": []}', []),
        (0, b"[]", None),  # valid JSON, wrong top-level type
        (0, b"null", None),
        (0, b'"text"', None),
        (0, b'{"schema_version": 1, "events": {}}', None),  # events not a list
        (0, b'{"schema_version": 1}', None),  # events missing
        (0, b'{"schema_version": 2, "events": []}', None),
        (0, b'{"events": []}', None),
        (0, b"not json", None),
        (0, b"\xff\xfe", None),  # not UTF-8
        (0, b"", None),
        (3, b"", None),  # any non-zero exit
    ],
)
def test_calendar_hints_mismatch_is_no_hints(
    monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: bytes, expected: Any
) -> None:
    hints = _calendar_hints()

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args, returncode, stdout, b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert hints(1763568000, 1763571600) == expected


@pytest.mark.parametrize(
    "exc", [FileNotFoundError(2, "missing"), subprocess.TimeoutExpired("cli", 10)]
)
def test_calendar_hints_launch_failures_are_no_hints(
    monkeypatch: pytest.MonkeyPatch, exc: BaseException
) -> None:
    hints = _calendar_hints()

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise exc

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert hints(1763568000, 1763571600) is None
