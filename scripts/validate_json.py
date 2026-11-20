"""Validate a JSON document on stdin against a packaged schema (R16-safe output).

Usage: <command> | uv run python scripts/validate_json.py {window-v1|calendars-v1}

Prints only JSON paths and validator keywords, never values. Exit codes: 0 valid,
1 schema violations, 2 usage error, empty stdin or not JSON.
"""

from __future__ import annotations

import json
import sys
from importlib.resources import files

from jsonschema import Draft202012Validator

NAMES = ("window-v1", "calendars-v1")


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in NAMES:
        print(f"usage: validate_json.py {{{'|'.join(NAMES)}}}", file=sys.stderr)
        return 2
    schema_text = (files("macos_calendar_events") / "schema" / f"{argv[0]}.schema.json").read_text(
        "utf-8"
    )
    validator = Draft202012Validator(
        json.loads(schema_text), format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    raw = sys.stdin.buffer.read()
    if not raw.strip():
        print("invalid: empty input", file=sys.stderr)
        return 2
    try:
        document = json.loads(raw)
    except ValueError:  # the decoder message can quote input; never print it
        print("invalid: not JSON", file=sys.stderr)
        return 2
    errors = sorted(validator.iter_errors(document), key=lambda e: e.json_path)
    for error in errors:
        print(f"{error.json_path}: {error.validator}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
