# Integration guide

## Call the CLI from another program

Resolve the executable's absolute path with `uv tool dir --bin` and append `macos-calendar-events`. Use a 10-second timeout for routine queries: a cold query takes about 0.3 s, and the first launch of a fresh install about 1.6 s. Set up [Calendar access](calendar-access.md) separately so the caller can run without `--prompt`.

Read stdout only after exit `0` and use the exit code to handle failures. Stderr is for diagnostics. For optional calendar hints, continue without hints if the process fails to launch, is killed, times out, returns a non-zero exit code, or produces JSON that fails schema or version validation.

Use the schema from `macos-calendar-events schema window-v1` or `macos-calendar-events schema calendars-v1`. Both commands return the schema for the installed version. If you fetch a schema from GitHub, use the tag that matches the installed package ([window-v1 at 0.1.0], [calendars-v1 at 0.1.0]).

[window-v1 at 0.1.0]: https://raw.githubusercontent.com/vr000m/macos-calendar-events/v0.1.0/docs/schema/window-v1.schema.json
[calendars-v1 at 0.1.0]: https://raw.githubusercontent.com/vr000m/macos-calendar-events/v0.1.0/docs/schema/calendars-v1.schema.json

### JSON compatibility

- Within `schema_version: 1`, new fields can be added. Fields keep their names, types, and meanings. Ignore fields your consumer does not use. When validating all required fields, use the schema that matches the CLI output.
- Enums are open. Map unfamiliar enum values to `unknown`. A breaking change gets a new schema version and schema files.
- An event `id` is opaque and unique within one response. To merge copies of the same invite across calendars, the provisional key is `(external_id, occurrence_start)`. Keep each row with a null `external_id`.

See the [CLI reference](cli.md#read-the-output) for document envelopes and date handling.

### Python subprocess example

Install `jsonschema[format-nongpl]` in the consumer's environment. The extra supplies the validator for RFC 3339 timestamps. Replace `CLI` with the path on your Mac. The function returns an empty list for a successful query with no matching events and `None` if the query or validation fails.

```python
import json
import subprocess
from typing import Any

import jsonschema  # third-party: pip install "jsonschema[format-nongpl]" (date-time checks)

CLI = "/Users/<you>/.local/bin/macos-calendar-events"


def _not_json(name: str) -> Any:
    raise ValueError(name)  # Python's json accepts NaN and Infinity; JSON does not


def _cli_json(*args: str) -> Any:
    proc = subprocess.run([CLI, *args], capture_output=True, timeout=10, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"exit {proc.returncode}")
    return json.loads(proc.stdout, parse_constant=_not_json)


def calendar_hints(start: int, end: int) -> list[dict] | None:
    try:
        schema = _cli_json("schema", "window-v1")  # cache this if you call often
        doc = _cli_json("window", "--start", str(start), "--end", str(end), "--pad-minutes", "15")
        # format_checker: dates are checked too (by default `format` is not enforced)
        jsonschema.validate(doc, schema, format_checker=jsonschema.FormatChecker())
        version = doc["schema_version"]  # checked here, not left to the fetched schema
        if isinstance(version, bool) or version != 1:  # True == 1 in Python
            return None
        return doc["events"]
    except Exception:  # any failure means no hints, never a crash
        return None
```

## Call the Python API directly

Install `macos-calendar-events==0.1.0` in the application environment, for example with `python -m pip install macos-calendar-events==0.1.0`.

```python
from datetime import UTC, datetime

import macos_calendar_events as mce

print(mce.authorization_status())
events = mce.events_in_window(
    datetime(2025, 11, 19, 16, tzinfo=UTC), 1763571600, prompt=False
)
for event in events:
    print(event.start, event.title, [attendee.email for attendee in event.attendees])
print([calendar.title for calendar in mce.list_calendars(prompt=False)])
```

| Call | Behaviour |
| --- | --- |
| `events_in_window(start, end, *, calendars=None, include_notes=False, prompt=True)` | Returns `list[Event]`. Bounds are integer epoch seconds or aware UTC datetimes. Pass a list of selectors such as `["Work"]`; a bare string raises `InvalidQueryError`. |
| `list_calendars(*, prompt=True)` | Returns `list[CalendarInfo]`. |
| `authorization_status()` | Returns the current `AccessStatus` without prompting. |
| `request_access(timeout=60.0)` | Requests full Calendar access when macOS can prompt and returns `AccessStatus`. |

`events_in_window` and `list_calendars` default to `prompt=True`. Call them with `prompt=False` when no one can respond to a prompt. They can raise `CalendarAccessError`, `CalendarNotFoundError`, `EventKitUnavailableError`, or `InvalidQueryError` (also a `ValueError`). The [CLI window bounds](cli.md#query-bounds-and-limitations) also apply to `events_in_window`. To query a padded window in Python, adjust the bounds before calling.

## Install the CLI from source

To install the tagged source instead of the PyPI package:

```sh
uv tool install --python 3.12.7 git+https://github.com/vr000m/macos-calendar-events@v0.1.0
```

From the root of a local checkout, use `uv tool install --python 3.12.7 --force .`.
