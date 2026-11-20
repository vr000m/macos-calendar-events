# macos-calendar-events

Read-only macOS Calendar (EventKit) window queries, with a versioned JSON CLI.

It answers one question accurately and completely: **which events overlap the UTC window
`[start, end)`, across every calendar this Mac can see?** It was built for a meeting
recorder that fetches events in a fuzzy window around a recording and uses the invitee
list as a hint for spelling speaker names. Ranking, matching or choosing "the" meeting is
out of scope; that belongs to the consumer.

The CLI and its JSON output are the stable contract. A Python API is also public, but
secondary.

## Requirements

- **macOS 14 (Sonoma) or newer.** Older macOS exits with code 4.
- Python 3.11+ (installed for you by `uv tool install`).
- [uv](https://docs.astral.sh/uv/).

## Install

```sh
uv tool install --python 3.12.7 git+https://github.com/vr000m/macos-calendar-events@v0.1.0
macos-calendar-events --version
```

Pin `--python` to an exact version (any 3.11+ works; 3.12.7 is the tested one). Without it, uv
picks the newest Python it can find (for example 3.13), and the Calendar grant is keyed to
that interpreter (see [Interpreter caveats](#interpreter-caveats)).

The CLI lands in `~/.local/bin`. A launchd job's PATH does not include `~/.local/bin`, so
programs should call the CLI by its absolute path, e.g.
`/Users/<you>/.local/bin/macos-calendar-events`.

To install from a checkout instead: `uv tool install --python 3.12.7 --force .`

## Granting Calendar access

macOS (TCC) asks once per *responsible process* and remembers the answer. The CLI never
prompts unless you pass `--prompt`; without it, a missing grant exits 3 immediately.

- **Grant from the context that will run the CLI.** TCC keys the grant to the responsible
  process: the terminal app when you run from a terminal, or the launchd job's executable
  when the CLI runs under launchd. Granting from Terminal grants only that terminal app.
- **Interactive use:** run this once from that terminal and click Allow:

  ```sh
  macos-calendar-events calendars --prompt
  ```

- **launchd consumers:** grant once from the consumer's own launchd job, e.g. a one-shot
  setup command that runs `macos-calendar-events calendars --prompt` as a child of the
  job. The grant belongs to the job's executable (for example the consumer's Python
  interpreter), which may not be the CLI's. Don't make `uv run`, a shell or another wrapper
  the job's executable, because the grant would then belong to an ephemeral or shared
  binary. The grant run needs a logged-in GUI session (the `gui/$(id -u)` domain) and a timeout
  of at least 70 s, because the CLI waits up to 60 s for the answer. Exit 0 means granted;
  exit 3 means denied, or that no prompt could be shown. Normal runs keep a short timeout
  (10 s is plenty).
- **Standalone launchd or cron use:** a one-shot launchd job grants the CLI's own
  interpreter, and that grant also covers cron jobs that run the CLI (see
  [cron](#cron)). The job runs once at load and is not kept alive. Save this as
  `~/Library/LaunchAgents/local.macos-calendar-events.grant.plist` (replace `<you>`):

  ```xml
  <?xml version="1.0" encoding="UTF-8"?>
  <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
  <plist version="1.0">
  <dict>
    <key>Label</key><string>local.macos-calendar-events.grant</string>
    <key>ProgramArguments</key>
    <array>
      <string>/Users/<you>/.local/bin/macos-calendar-events</string>
      <string>calendars</string>
      <string>--prompt</string>
    </array>
    <key>RunAtLoad</key><true/>
  </dict>
  </plist>
  ```

  Then:

  ```sh
  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.macos-calendar-events.grant.plist
  # click Allow in the prompt
  launchctl bootout gui/$(id -u)/local.macos-calendar-events.grant
  ```

  Afterwards System Settings shows an entry named after the interpreter (e.g. `python3.12`).

- **System Settings → Privacy & Security → Calendars** can't add apps. It only toggles
  entries that have already prompted.
- **Reset during development:** `tccutil reset Calendar <bundle-id>` (you run this; the tool
  never does). Without a bundle id, `tccutil reset Calendar` resets the Calendar grant of
  **every** app, so you will have to grant your terminal and any jobs again.

### Interpreter caveats

- Outside a terminal, the grant is keyed to the interpreter binary's real path, and System
  Settings lists it by binary name (`python3.12`, `python3.13`, …). An unpinned
  `uv tool install` may pick a different Python than you granted (for example 3.13 instead
  of 3.12), and a uv Python upgrade or reinstall changes that path too. Either way, expect
  exit 3 until you grant again.
- Pin the exact version with `--python` when installing, and grant again after changing it:

  ```sh
  uv tool install --python 3.12.7 --force git+https://github.com/vr000m/macos-calendar-events@v0.1.0
  ```

  To see which interpreter a tool install uses:
  `readlink -f ~/.local/share/uv/tools/macos-calendar-events/bin/python`.

- Any script run under launchd or cron by a granted interpreter inherits its Calendar access.

### cron

cron jobs are attributed to the CLI's interpreter, just like launchd jobs, so a cron job
exits 3 until that interpreter is granted. Grant it once with the
[one-shot launchd recipe](#granting-calendar-access) above; the same cron job then works.
A grant from your terminal does not cover cron.

cron runs commands with a minimal environment, and `$HOME` or `~` in a crontab is easy to
get wrong, so use absolute paths everywhere (replace `<you>`):

```crontab
*/15 * * * * /Users/<you>/.local/bin/macos-calendar-events calendars > /Users/<you>/calendars.json 2>> /Users/<you>/calendars.err
```

## Integrating from another program

Run the CLI as a subprocess, by absolute path, with a timeout (10 s is generous: a cold
query takes about 0.3 s, and the first launch of a fresh install about 1.6 s).

- Read JSON from stdout only on exit 0; never parse stderr.
- Treat **any** failure as "no calendar hints", never as fatal for your own pipeline: a
  non-zero exit, a signal, a timeout, a missing executable, invalid JSON, a schema mismatch,
  or a `schema_version` other than 1.
- Send `--start`/`--end` as integer Unix epoch seconds (RFC 3339 UTC with `Z` or `+00:00` is
  also accepted), at or after 1970, with nothing around the value (no whitespace or trailing
  newline); anything else exits 2. Every output instant has an integer `_ts` sibling
  (`start_ts`, `end_ts`, `occurrence_start_ts`; the window echo has `start_ts`/`end_ts`), so
  you never parse dates.
- The output schemas are `docs/schema/window-v1.schema.json` and
  `docs/schema/calendars-v1.schema.json`. Use the copy **at the tag matching the installed
  CLI**, e.g.
  `https://raw.githubusercontent.com/vr000m/macos-calendar-events/v0.1.0/docs/schema/window-v1.schema.json`,
  or ask the installed CLI: `macos-calendar-events schema window-v1`.
- Stability within `schema_version` 1: fields may be added (ignore unknown keys), but none
  are removed, renamed, retyped or changed in meaning. Enums are open: map unknown values to
  `unknown`. Any breaking change bumps `schema_version` to 2 with new schema files.
- `id` is opaque and unique within one response. To merge one invite that appears in several
  calendars, dedupe on `(external_id, occurrence_start)` when `external_id` is non-null
  (provisional guidance); rows with a null `external_id` are never deduped.
- Declined and canceled events are returned with their status; you decide what to drop.

The example below validates each document against the schema of the installed CLI with
[`jsonschema`](https://pypi.org/project/jsonschema/), so the events it returns have every
field the schema promises; anything else, including any exception, is "no calendar hints".

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
        # format_checker: dates are checked too (by default `format` is not enforced);
        # the schema also pins schema_version == 1 (const)
        jsonschema.validate(doc, schema, format_checker=jsonschema.FormatChecker())
        return doc["events"]
    except Exception:  # any failure means no hints, never a crash
        return None
```

## CLI

```sh
# events overlapping a window, padded by 15 minutes on each side
macos-calendar-events window --start 1763568000 --end 1763571600 --pad-minutes 15

# RFC 3339 UTC input, restricted to two calendars (by id or case-insensitive title)
macos-calendar-events window --start 2025-11-19T16:00:00Z --end 2025-11-19T17:00:00Z \
  --calendar Work --calendar Home

# include notes (off by default)
macos-calendar-events window --start 1763568000 --end 1763571600 --include-notes

# every calendar
macos-calendar-events calendars

# the packaged schemas
macos-calendar-events schema window-v1
macos-calendar-events schema calendars-v1
```

The window document is `{schema_version, window: {start, end, start_ts, end_ts}, events}`,
where `window` echoes the padded window. Events are sorted by `(start, end, calendar.id,
id)`; all instants are UTC with whole seconds. All-day events carry `start_date` and
`end_date` (Gregorian `YYYY-MM-DD` whatever the Mac's calendar setting, end exclusive); use
those rather than the UTC instants, which
reflect the Mac's time zone at query time. A full example lives in
`tests/golden/window-v1.json`.

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | OK; JSON on stdout |
| 1 | Internal error (one stderr line naming the exception class) |
| 2 | Usage or argument error: bad time, epoch seconds out of range, `end <= start`, end after 9999-12-30T23:59:59Z, window over the cap, `--pad-minutes < 0` or too large |
| 3 | Calendar access not granted (see [Granting Calendar access](#granting-calendar-access)) |
| 4 | EventKit unavailable: not macOS, macOS older than 14, or PyObjC missing |
| 5 | A `--calendar` selector matched nothing |

Use stdout only on exit 0. Every non-zero exit leaves stdout empty, except an exit 1 from a
stdout write that fails partway (for example a full non-blocking pipe or a full disk), which
can leave a truncated prefix.

## Python API

```python
from datetime import UTC, datetime

import macos_calendar_events as mce

print(mce.authorization_status())  # never prompts
events = mce.events_in_window(
    datetime(2025, 11, 19, 16, tzinfo=UTC), 1763571600, prompt=False
)
for event in events:
    print(event.start, event.title, [a.email for a in event.attendees])
print([c.title for c in mce.list_calendars(prompt=False)])
```

`start`/`end` are integer epoch seconds or aware UTC datetimes. The functions raise
`CalendarAccessError`, `CalendarNotFoundError`, `EventKitUnavailableError` or
`InvalidQueryError` (a `ValueError`). `calendars` must be a list of selectors; a bare string
raises `InvalidQueryError`. `events_in_window` and `list_calendars` default to `prompt=True`.

## Known limitations

- Calendars hidden (unchecked) in Calendar.app are still returned; EventKit doesn't expose
  that state. Use `--calendar` to restrict.
- Exchange delegate calendars are unverified.
- A window may be at most 3×365−2 days long (after padding); longer windows exit 2 instead
  of being silently truncated by EventKit. The cap keeps a year of margin below the span
  where a row went missing once, but it is not verified at its full length; if the opt-in
  live consistency check finds missing rows, a later release lowers it. Windows may be
  arbitrarily far in the past, but the end must not be after 9999-12-30T23:59:59Z; a later
  end exits 2.
- Event times are truncated to whole seconds before the overlap check, so an event whose
  bound has a fractional second can be missed by a window that it overlaps by under one
  second. Calendar apps normally store whole seconds.
- If a Calendar access request times out and the grant arrives later (for example from
  System Settings), the process keeps the event store it created before the grant. Run
  the command again; each CLI run is a new process.
- `external_id` may be null, and one invite can appear once per calendar.
- Floating (no time zone) and all-day events are placed using the Mac's current time zone.
- `time_zone` is informational: an IANA name when available, otherwise EventKit's raw name.

## Privacy

The tool only reads. It sends nothing anywhere, writes no files, and prints calendar data
only to stdout. Every event's `notes` is `null` (the key is always present) unless you pass
`--include-notes`. Error messages carry no event or calendar content.

## License

BSD-2-Clause. See [LICENSE](LICENSE).
