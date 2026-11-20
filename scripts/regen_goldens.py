"""Regenerate tests/golden/*.json from tests/golden_fixtures.py (R18 change detectors).

Usage: uv run python scripts/regen_goldens.py

Goldens are hand-reviewed before commit, and any golden change needs a CHANGELOG line.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "tests" / "golden"


def _load_fixtures() -> ModuleType:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))  # golden_fixtures imports tests.fakes
    spec = importlib.util.spec_from_file_location(
        "golden_fixtures", ROOT / "tests" / "golden_fixtures.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load tests/golden_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_all() -> dict[str, bytes]:
    """Run each fixture through the CLI and return ``{file name: stdout bytes}``."""
    from macos_calendar_events.cli import main

    fixtures = _load_fixtures()
    rendered: dict[str, bytes] = {}
    for name, builder in (
        ("window-v1.json", fixtures.build_window_fixture),
        ("calendars-v1.json", fixtures.build_calendars_fixture),
    ):
        fixture = builder()
        buffer = io.BytesIO()
        stdout = io.TextIOWrapper(buffer, encoding="utf-8")
        with contextlib.redirect_stdout(stdout):
            code = main(fixture.argv, source=fixture.source)
        stdout.flush()
        if code != 0:
            raise RuntimeError(f"{name}: CLI exited {code}")
        rendered[name] = buffer.getvalue()
    return rendered


def main() -> int:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for name, data in render_all().items():
        (GOLDEN_DIR / name).write_bytes(data)
        print(f"wrote tests/golden/{name} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
