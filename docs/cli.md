# CLI reference

Run `macos-calendar-events --help` for commands or `macos-calendar-events window --help` for query flags. `--version` prints both the installed package version and its JSON schema version.

## Query a window

```sh
macos-calendar-events window --start 1763568000 --end 1763571600 --pad-minutes 15
```

| Flag | Default | Behaviour |
| --- | --- | --- |
| `--start`, `--end` | Required | Use whole Unix epoch seconds or RFC 3339 UTC with `Z` or `+00:00`, without surrounding whitespace. UTC strings accept up to six fractional digits and are truncated to whole seconds. |
| `--calendar ID_OR_TITLE` | All event calendars | Repeat to select multiple calendars. Each selector first looks for an ID match, then for case-insensitive title matches if the ID lookup finds nothing. |
| `--pad-minutes N` | `0` | Extend both ends of the window by a non-negative number of whole minutes. |
| `--include-notes` | Off | Include available event notes. By default, the `notes` field is `null`. |
| `--prompt` | Off | Allow macOS to request Calendar access. See [Calendar access](calendar-access.md). |

```sh
macos-calendar-events window \
  --start 2025-11-19T16:00:00Z --end 2025-11-19T17:00:00Z \
  --calendar Work --calendar Home
```

The CLI returns events overlapping the half-open window `[start, end)` after padding. An event that ends exactly at the window start or starts exactly at the window end is excluded. A zero-duration event is included when its timestamp falls inside the window.

## List calendars and schemas

```sh
macos-calendar-events calendars
macos-calendar-events schema window-v1
macos-calendar-events schema calendars-v1
```

`calendars` lists the event calendars EventKit exposes, including IDs you can use with `--calendar`. Use `calendars --prompt` for initial permission setup. The `schema` command reads the packaged JSON Schema and works without Calendar access.

## Read the output

- `window` returns `schema_version`, `window`, and `events`. The `window` object echoes the padded bounds as `start`, `end`, `start_ts`, and `end_ts`. Events are sorted by `(start, end, calendar.id, id)`.
- `calendars` returns `schema_version` and `calendars`.
- Instants are UTC at whole-second precision. The `_ts` fields hold Unix epoch seconds for the corresponding text timestamps, including `occurrence_start_ts` for `occurrence_start`.
- For all-day events, use `start_date` and the exclusive `end_date`. These are Gregorian `YYYY-MM-DD` dates. The UTC instants for all-day and floating events use the Mac's time zone at query time. `time_zone` is informational. Its value can be an IANA name, EventKit's raw name, or `null`.
- Declined and cancelled events are included with their status. One invite can appear in more than one calendar. See the [integration guide](integration.md#json-compatibility) for deduplication and compatibility rules.

See sample documents for [events](../tests/golden/window-v1.json) and [calendars](../tests/golden/calendars-v1.json).

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success. Query and schema commands write JSON to stdout. |
| `1` | Internal error. Stderr gets a line naming the exception class. |
| `2` | Usage or argument error, including an invalid time, window or padding. |
| `3` | Full Calendar access is unavailable. See [Calendar access](calendar-access.md#troubleshooting-exit-3). |
| `4` | EventKit is unavailable. Calendar queries require macOS 14 or newer and PyObjC. |
| `5` | At least one `--calendar` selector matched nothing. |

Use stdout only on exit `0`. A failed write can leave partial output on exit `1`. For a regular file opened at its end without append mode, the CLI attempts to remove the bytes it added if the file is still exactly the length it left it. A pipe, an append-mode file, a write starting before or past EOF, or a concurrent same-length rewrite can leave partial output.

## Query bounds and limitations

- After padding, the start must be at or after `1970-01-01T00:00:00Z`. The end must be after the start and no later than `9999-12-30T23:59:59Z`.
- A padded window can span at most 1,093 days. This cap leaves about a year of margin below a span where EventKit missed an event. The full 1,093-day span still needs live verification.
- Event times are truncated to whole seconds before the overlap check. This can exclude an event that overlaps the window by less than a second.
- EventKit also returns calendars unchecked in Calendar.app. Use `--calendar` to limit the query. Exchange delegate calendars are unverified.
