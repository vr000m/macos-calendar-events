"""Copy the packaged JSON Schemas (the single source of truth) to docs/schema/ (R18).

Usage: uv run python scripts/sync_schemas.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "macos_calendar_events" / "schema"
TARGET = ROOT / "docs" / "schema"


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    for path in sorted(SOURCE.glob("*.schema.json")):
        shutil.copyfile(path, TARGET / path.name)
        print(f"synced {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
