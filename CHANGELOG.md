# Changelog

All notable changes to this project are documented here. Golden-file (`tests/golden/*.json`) changes always get a line.

## Unreleased
### Added
- `macos-calendar-events` CLI: `window` (`--start`/`--end` as epoch seconds or RFC 3339 UTC, `--calendar`, `--pad-minutes`, `--include-notes`, `--prompt`), `calendars [--prompt]`, `schema {window-v1|calendars-v1}`, and `--version`. Exit codes 0–5 per the README contract.
- Python API: `events_in_window`, `list_calendars`, `authorization_status`, `request_access` (macOS 14+, read-only EventKit).
- JSON Schemas `window-v1` and `calendars-v1` (`schema_version` 1), packaged and published under `docs/schema/`.
- `scripts/validate_json.py` (paths and keywords only) and `scripts/regen_goldens.py`. Goldens are not generated yet; they need a hand review first.
