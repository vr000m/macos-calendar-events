"""R18: the published docs/schema copies are byte-identical to the packaged schemas."""

from importlib.resources import files
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs" / "schema"
NAMES = ["window-v1.schema.json", "calendars-v1.schema.json"]


@pytest.mark.parametrize("name", NAMES)
def test_docs_copy_is_byte_identical(name: str) -> None:
    packaged = (files("macos_calendar_events") / "schema" / name).read_bytes()
    assert (DOCS / name).read_bytes() == packaged


def test_no_extra_docs_schemas() -> None:
    assert sorted(p.name for p in DOCS.glob("*.json")) == sorted(NAMES)
