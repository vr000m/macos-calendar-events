# Task: macos-calendar-events v0.1: read-only EventKit window query library and CLI

**Status**: Not Started
**Component**: core
**Assigned to**: Varun Singh (vr000m)
**Priority**: High
**Branch**: `feature/core-events-api`
**Created**: 2026-11-19
**Completed**:
**Review Gates**: none

## Objective

Ship an open-source Python package, `macos-calendar-events` (import name `macos_calendar_events`), that reads macOS Calendar through EventKit, read-only. It returns every event that overlaps a time window, across every calendar the Mac can see, through a JSON CLI with a versioned output schema. That CLI is the stable contract between repos. A Python API with plain JSON-serializable dataclasses is also public, but secondary.

## Context

- **Motivation (consumer, not scope):** koda-pipecat records meetings, diarizes speakers (S1, S2, …), and post-processes each session. It wants to fetch calendar events in a fuzzy window around a recording (for example ±15 min), work out which of several overlapping meetings was actually attended, and use the invitee list as a *non-normative* hint, mostly for spelling speaker names. koda-pipecat integrates by **running the CLI as a subprocess** with a timeout and parsing its versioned JSON. It doesn't import this library, so the two repos share only the CLI and JSON contract (R18). All of that ranking, matching, and LLM reconciliation stays in koda-pipecat. This package only answers "what events overlap [start, end)?" accurately and completely.
- **Why a separate repo:** it's reusable outside koda, it's open source, and it keeps PyObjC/EventKit and macOS privacy (TCC) concerns out of the consumer.
- **Data reality (assumption, checked in Phase 0):** the user's Calendar.app aggregates several accounts (work Exchange/Google, personal iCloud, shared and subscribed calendars). The default `EKEventStore` is assumed to expose them all, so "all calendars" is the default. *Phase 0:* the default store exposed 16 calendars (CalDAV, subscribed, birthdays), and all 15 `delegateSources` were already among the default store's sources, so delegate calendars need no special handling. Phase 0 measures this, and any gap becomes a documented limitation.
- **Repo state (snapshot 2026-11-19 15:30 PST):** branch `feature/core-events-api` (from `main` at `4568144 Initial commit`), containing plan commits plus a `.gitignore` update that ignores `/.review-plan`. Files: `LICENSE` (**BSD 2-Clause**, © 2026 Varun Singh), stock Python `.gitignore` (ignores `.venv`, `.mypy_cache`; does not ignore `uv.lock`, which doesn't exist yet and is committed in Phase 1), this plan. No `pyproject.toml` yet.
- **Dev machine:** macOS 26.6.2. Two uv binaries are installed: `/opt/homebrew/bin/uv` 0.13.9 and `~/.local/bin/uv` 0.9.18. Which one `uv` resolves to depends on the shell's PATH: interactive login shells resolve Homebrew's first, while non-login shells (including agent shells that run phase gates) resolve `~/.local/bin` first. Phase 1 pins `[tool.uv] required-version = ">=0.9"` and runs `uv lock --check` with both binaries by absolute path, so either works. Latest `pyobjc-framework-EventKit` on PyPI is 13.0 (`requires_python >=3.11`).

## Requirements

The **Type and Signature Sketch** (Technical Specifications) is the single source for public signatures. R1–R9 must match it.

### Functional
- R1. `events_in_window(start, end, *, calendars=None, include_notes=False, prompt=True) -> list[Event]` returns every event overlapping the half-open window `[start, end)` from all calendars by default. `calendars` optionally restricts the query (R6).
- R2. `list_calendars(*, prompt=True) -> list[CalendarInfo]` returns every event calendar EventKit exposes:
  - `id`, `title`, `source_title`.
  - `source_type`: `SourceType`, mapped from the `EKSourceType` int; unknown ints become `unknown`.
  - `color_hex`: `#RRGGBB` in sRGB, or `None` if conversion fails.
  - `read_only`: `not EKCalendar.allowsContentModifications`.

  Calendars are sorted by `(source_title is not None, source_title or "", title or "", id)`, so calendars with a null `source_title` sort first.
- R3. `Event` fields:
  - Identity: `id` (opaque string, unique within one response; its format is not part of the contract), `external_id`, `event_identifier`. Documented consumer dedupe key: `(external_id, occurrence_start)`, only when `external_id` is non-null; rows with a null `external_id` are never deduped. This guidance stays provisional: Phase 0 did not observe an external id shared across calendars (0 of 111), but it also saw no detached, floating or Exchange rows, so the live smoke keeps counting these shapes (Phase 4). **`id` derivation (internal, owned by `_mapping.assign_ids`, not contract):** base key `(calendar.id, external_id or event_identifier or "", occurrence_start, start, end)`, SHA-256-hashed and truncated to 16 hex chars. Rows whose base keys collide within one response get an ordinal suffix (`-2`, `-3`, …) in order of `(title or "", location or "")`, then EventKit order. Uniqueness therefore holds by construction, and ids are stable across identical calls.
  - Content: `title`, `location`, `url`, `notes` (only when `include_notes=True`, else `None`).
  - Time: `start`, `end` (UTC instants, end exclusive, serialized `…Z` with whole seconds), `all_day`, `start_date` / `end_date` (calendar dates `YYYY-MM-DD`, end exclusive, set only for all-day events, otherwise `None`; derived by the pure `_mapping.normalize_all_day` from local date components the adapter captures), `time_zone` (informational only). For all-day and floating events, the UTC `start`/`end` instants reflect the Mac's system time zone at query time; consumers should use `start_date`/`end_date` for all-day events. For all-day events, an EventKit end of local `23:59:59` is normalized to the next local midnight (+1 s), so both `end` and `end_date` are exclusive (Phase 0 confirms the raw representation).
  - State: `status`, `is_recurring` (`hasRecurrenceRules or isDetached`), `is_detached`, `occurrence_start`.
  - People and calendar: `organizer: Participant | None`, `attendees: tuple[Participant, ...]`, `self_status: ParticipationStatus | None`, `calendar: CalendarRef`. The organizer may also appear in `attendees` (Phase 0 observed this); the library passes both through without deduping.

  Nullability is decided up front, because R18 forbids retyping later. The type sketch is authoritative. Nullable: `title`, `event_identifier`, `time_zone`, `external_id`, `location`, `url`, `notes`, `start_date`, `end_date`, `organizer`, `self_status`, `calendar.source_title`, `calendar.title`, and participant `name`/`email`/`url`. Non-null: `calendar.id`, `start`, `end`, `occurrence_start`. An event whose EventKit `startDate`, `endDate` or calendar identifier is nil is **skipped**, never emitted with a placeholder. `occurrence_start` falls back to `start`, so it can only be missing when `start` is. The pure `_mapping.to_events` does the skipping and returns a `MappedEvents(events, skipped)` pair. `_api.query_events` passes the count up in a `QueryResult(events, skipped)`, so the live smoke can record it; the public wrappers return only `.events` (Phase 0 measured 0 skips). `time_zone` is "IANA name when available, otherwise EventKit's raw zone name, `None` for floating". A nil `attendees` collection becomes `()` (the field is a non-optional tuple); nil scalar fields become `None`. Phase 0 saw nil `organizer` on 173 of 212 events, nil `attendees` on 156 CalDAV events and nil `timeZone` on every all-day event, so these are the common shapes, not edge cases. `occurrence_start` falls back to `start` when `occurrenceDate` is nil.
- R4. `Participant`:
  - `name | None`, `email | None`, `url | None`, `role`, `status`, `type` (person/room/resource/group/unknown), `is_self` (`EKParticipant.isCurrentUser`).
  - `email` follows RFC 6068 parsing. The scheme is compared case-insensitively. The path's address list is split on `,` **before** percent-decoding, and the first path address wins. If the path is empty, the first address of a `to=` hfield is used; other hfields are ignored. Surrounding whitespace is trimmed, and the result is `None` when no address remains. `url` is the raw URL **only when it is not `mailto:`**, otherwise `None`.
  - `self_status` is the status of the first `is_self` attendee in EventKit order, or `None` when there isn't one.
- R5. Declined and canceled events **are returned** with their status. Consumers decide what to drop.
- R6. Calendar filter:
  - Each selector matches by exact `calendarIdentifier` first; if any calendar's id matches, title matching is skipped for that selector. Otherwise it matches by title compared with `casefold()`. A title can match several calendars, and all are included.
  - Any selector that matches nothing raises `CalendarNotFoundError` listing available titles, even when other selectors match.
  - `calendars=[]` raises `InvalidQueryError` (a `ValueError` subclass). The CLI's exit-5 stderr line names only the unmatched selectors via `repr()`, never calendar titles, so it stays one line. `None` means all calendars. The filter is **never** silently ignored.
- R7. CLI commands:
  - `macos-calendar-events window --start T --end T [--calendar X ...] [--pad-minutes N] [--include-notes] [--prompt]`
  - `macos-calendar-events calendars [--prompt]`
  - `macos-calendar-events schema {window-v1|calendars-v1}` writes the packaged schema bytes to stdout (exit 0; an unknown name exits 2).
  - `T` is either a non-negative integer of Unix epoch seconds or an RFC 3339 UTC string (R12).
  - The CLI **never prompts for Calendar access unless `--prompt` is passed**. There is no `--no-prompt` flag. Without `--prompt`, a `not_determined` status exits 3 immediately. The README tells users to grant access once by running `macos-calendar-events calendars --prompt` from the context that will run the CLI (R9; Decision (Phase 0): grant context).
  - `macos-calendar-events --version`, which prints `macos-calendar-events <version> (schema_version 1)`.

  Output is JSON on stdout, diagnostics go to stderr, and exit codes are documented (R11). **The CLI is the primary, documented integration surface** (R18). The Python API (R1, R2, R9) stays public but secondary, for tests and in-process users.
- R8. Output is deterministic: events sorted by `(start, end, calendar.id, id)`, all UTC.

### Permissions (TCC)
- R9. Access API:
  - `authorization_status() -> AccessStatus` returns `not_determined | restricted | denied | full_access | write_only | unknown`. The EventKit int is mapped in `_mapping`, and unknown ints become `unknown`.
  - `request_access(timeout=60.0) -> AccessStatus` uses `requestFullAccessToEventsWithCompletion_` only. `requestAccessToEntityType_completion_` is never called (R19). The wait is the pure helper `_access.wait_for_access(request, read_status, timeout, wait=…)`. It takes an injected requester and an injected waiter. The waiter defaults to `threading.Event.wait`, and the adapter uses that default. Phase 0 showed the completion fires on a background thread with no run loop pumped, both from a terminal and under launchd. The waiter seam stays for tests. If the completion never fires within `timeout`, it returns the current status.
  - Reads gate on access (timeout `_api.ACCESS_TIMEOUT_S = 60.0`): `full_access` passes; `not_determined` with `prompt=True` requests once, then re-checks; anything else, including still `not_determined` after the request, raises `CalendarAccessError(status)`.
  - Remediation text is generic, and was revised after Phase 0's System Settings check showed apps can't be added manually: "Calendar access is granted per launching context. Run `macos-calendar-events calendars --prompt` once from the same context (the same terminal app, or the same launchd job/interpreter), or enable an existing entry in System Settings → Privacy & Security → Calendars". **Emit point:** this text is the CLI's single exit-3 stderr line and the message of `CalendarAccessError`; tests assert it in both places (Phases 3 and 5). **Not measured in Phase 0 (assumptions, verified in Phase 5b manual validation):** the denied path, whether framework or PyObjC output appears there, and that toggling an existing System Settings entry restores access.
  - **TCC attribution (Phase 0):** TCC attributes access to the *responsible process*. For a process started from a terminal, that's the terminal app. For a launchd job and all of its children, it's the job's executable (for a uv-managed Python, the interpreter binary's realpath). A terminal grant does not carry over to launchd jobs. The package doesn't try to detect the responsible app. `write_only` counts as denied for reads. **Measured scope:** Phase 0 measured one terminal app (Rex) and one launchd shape in which the job's executable and the CLI's interpreter were the same binary, so it can't say whether a grant belongs to the job's executable or to the CLI's interpreter when they differ (koda's job executable is its own). Terminal.app, VS Code and **cron** were not measured. Phase 6 adds a launchd parent with a different executable and a cron-parent check (Decision (Phase 0): cron). Until those are recorded, treat those contexts as unverified. Phase 0 ran on macOS 26.6.2 only; the macOS 14 floor (R19) rests on feature detection, not on a test run on 14 or 15.
- R10. No writes, ever. Enforced by `scripts/check_readonly.sh` in CI:
  - `grep -rnE` over `src/` for a denylist: `saveEvent|removeEvent|saveCalendar|removeCalendar|saveReminder|removeReminder|commit_?\(|requestWriteOnlyAccess|requestAccessToEntityType`, plus `\.reset\(`. `reset` is never called (store lifetime rule, Phase 4).
  - Grep's exit code is interpreted strictly: `1` (no match) is a pass, `0` (match) is a fail, and anything else (for example `2` for an unreadable path) is a fail.
  - An **allowlist**: the set of PyObjC selector calls with arguments in `_eventkit.py` (identifiers ending in `_(`) must equal `scripts/eventkit_selectors.allow`.
  - Each check reports a distinct stderr tag (`[denylist]`, `[allowlist]`, `[imports]`, `[grep-error]`), so tests can tell which one fired. The script is itself tested (Phase 1).

### Boundaries and errors
- R11. CLI exit codes:
  - `0` ok.
  - `1` internal error: a catch-all handler prints one line, `internal error: <ExceptionClass>`, with no traceback and no message text (privacy).
  - `2` usage or argument error, including an over-cap window (R13) and `--pad-minutes < 0`. argparse's usage block is allowed here.
  - `3` calendar access not granted.
  - `4` EventKit unavailable (not macOS, macOS < 14, or PyObjC missing).
  - `5` calendar selector not found.

  Check order, which pins which code wins: argument and window validation (2) → EventKit availability (4) → access (3) → calendar selection (5). Exit 2 comes only from argparse and `InvalidQueryError`; any other `ValueError` is an internal error (exit 1).

  On exits 1, 3, 4 and 5, the CLI itself writes exactly one stderr line. Apple frameworks or PyObjC may add their own output (Phase 0 records whether they do), so consumers must not parse stderr. Every non-zero exit leaves stdout empty, because stdout is written once, after serialization succeeds. A process killed by a signal (for example a TCC refusal, if Phase 0 observes one) is outside the CLI's control. Consumers treat it like any other failure.
- R12. **UTC at the contract boundary, input and output.**
  - **CLI:** `--start`/`--end` accept exactly two forms. (a) **Non-negative integer Unix epoch seconds**, matching `^[0-9]+$` (e.g. `1763568000`); this is the form koda sends. (b) An **RFC 3339 UTC string** matching `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|\+00:00)$`, parsed with `datetime.fromisoformat` (Python 3.11+), with fractional seconds truncated to whole seconds. Both forms must denote an instant **at or after `1970-01-01T00:00:00Z`**; an earlier RFC 3339 string exits `2` just like a negative epoch. Everything else exits `2` with a one-line message: negative or float epochs, pre-1970 strings, naive strings, `-00:00`, and any other offset. This supersedes the earlier "naive = local" rule.
  - **Python API:** `start`/`end` accept a non-negative `int` of epoch seconds (not `bool`, not `float`) or a timezone-aware `datetime` with `utcoffset() == timedelta(0)`. Naive or non-zero-offset datetimes, datetimes before `1970-01-01T00:00:00Z`, floats, negative ints, and epochs outside `datetime`'s range raise `InvalidQueryError` (a `ValueError` subclass), for symmetry with the CLI. Both entry points normalize through the pure `_mapping.parse_instant` / `_mapping.parse_instant_text`.
  - **Output:** every instant (`start`, `end`, `occurrence_start`, and the echoed padded window's `start`/`end`) is emitted twice: as a UTC `…Z` string with whole seconds, and as a required integer epoch-seconds sibling (`start_ts`, `end_ts`, `occurrence_start_ts`; the window echo has `start_ts`/`end_ts`). The pre-1970 rule applies to **input only**: output `_ts` values may be negative for old events (an event overlapping the window can start before 1970), so output `_ts` schema fields have no `minimum`. Both forms derive from one `datetime` at serialization time in `models.py`, so they can't disagree.
  - **Consumer's job:** koda sends integer epoch seconds. The library never needs the consumer's time zone, and local-time presentation is the consumer's concern.
  - `end <= start` → `InvalidQueryError` / exit 2.
  - **Order with padding:** the CLI parses and validates the raw `--start`/`--end` first (grammar, 1970 floor, `end > start`), then applies `--pad-minutes`, then `_api` validates the padded window (aware UTC, `end > start`, length cap, 1970 floor). Padding that would push the padded start before `1970-01-01T00:00:00Z` therefore exits 2; this is a documented edge, not a separate rule.
- R13. Window span cap: EventKit's `predicateForEventsWithStartDate:endDate:calendars:` only matches events within a four-year span, so over-cap windows raise `InvalidQueryError` (CLI exit 2) instead of being silently truncated. The details:
  - **Limit:** the caller's window, measured **after** `--pad-minutes` padding, may be at most **3×365 − 2 days** long. (Decision, run 4: lowered from 4×365 − 2. Phase 0 saw one row in the union of four 365-day queries that the single 1460-day query did not return. It was unexplained, and the range was relative to now and counts-only, so it can't be re-found. The cap keeps a year of margin below the span where that happened, and is **unverified at larger spans**.)
  - **Widening (single owner):** `_api` widens the padded window by **±1 day** via the pure `_mapping.query_range()`, and `EventKitSource.events()` queries exactly the range it receives. The total queried range is therefore at most 3×365 days. Phase 0 measured that EventKit silently truncates spans above 1460 days, so this stays under that limit with margin. The Python overlap filter trims the result back to the window. An opt-in live consistency check (Phase 4) compares one query against three chunked queries. This is needed because all-day and floating events are date-anchored, so DST and time-zone shifts can move them by up to a day relative to a UTC window.
  - **Length, not age:** the cap limits window **length** only. Windows may be arbitrarily far in the past, for example a crashed cron job reprocessing a week- or month-old session with its absolute UTC times.

  No chunking in v0.1.
- R14. `import macos_calendar_events` succeeds on non-macOS and without PyObjC. EventKit is imported lazily, and only `_eventkit.py` imports `EventKit`/`Foundation`/`AppKit`/`objc` (enforced by `scripts/check_readonly.sh`).

### Packaging and quality
- R15. Packaging and tooling:
  - `pyproject.toml` with a hatchling backend, `uv`-managed, `requires-python = ">=3.11"`, `readme = "README.md"`.
  - Runtime dependency `pyobjc-framework-EventKit>=13; sys_platform == 'darwin'` (the floor is the tested version).
  - ruff (lint and format), mypy `--strict` (one type checker), pytest. `py.typed` shipped.
  - License metadata `BSD-2-Clause`.
  - Classifiers stay generic (`Operating System :: MacOS`, `Environment :: MacOS X`), because no PyPI classifier expresses a macOS version. The macOS 14 Sonoma minimum is stated in the project `description` and README, and enforced at runtime (R19).
- R16. Privacy: no real calendar data in the repo, in test output, or in CI logs.
  - Fixtures are hand-written with RFC 2606 domains (`example.com`, `example.org`).
  - The live smoke test asserts on integer counts only.
  - `scripts/validate_json.py` prints only JSON paths and validator keywords, never values.
  - `scripts/check_privacy.sh` (run in CI) scans `git ls-files --cached --others --exclude-standard` (tracked plus untracked-not-ignored files) case-insensitively for email addresses outside RFC 2606 domains (including their subdomains) and GitHub noreply addresses. Paths missing from the worktree are skipped. There is **no exclusion list**, so local scratch files must be gitignored.
  - **No tracked file may contain a disallowed address-shaped literal.** Test seeds are built at runtime by string concatenation, and the plan describes seeds without address-shaped text.
  - Exit codes: 0 clean, 1 violation, 2 error (e.g. not a git repository).
- R17. CI on GitHub Actions:
  - `macos-latest` (Python 3.11 and 3.13) runs ruff, mypy, unit tests (`-m "not live"`), `check_readonly.sh` and `check_privacy.sh`.
  - `ubuntu-latest` (Python 3.12) runs unit tests only, to prove R14 without PyObjC; darwin-only tests skip.
  - No live calendar access in CI.

### Cross-repo contract (CLI + JSON)
- R18. **CLI JSON contract.**
  - **Schemas:** the stdout of `window` and `calendars` is specified by JSON Schemas shipped as **package data**: `src/macos_calendar_events/schema/window-v1.schema.json` and `calendars-v1.schema.json`, loaded via `importlib.resources`, so the CLI and tests read the same files. The packaged copy under `src/` is the **single source of truth**.
  - **How consumers get the schemas:**
    - The CLI prints them: `macos-calendar-events schema {window-v1|calendars-v1}` returns the schema of the *installed* version.
    - Published copies in `docs/schema/window-v1.schema.json` and `docs/schema/calendars-v1.schema.json` let other coding agents and consumers build against the contract.
    - `scripts/sync_schemas.py` copies the packaged files to `docs/schema/`, and `tests/test_schema_copies.py` asserts the docs copies are byte-identical to the packaged ones.
    - Consumers and coding agents use the `docs/schema/` copy **at the tag matching their installed CLI** (or the installed CLI's `schema` output); after release koda may rely on the pinned tag URL. The README says this.
  - **All v1 fields are required.** A field added in a later v1.x is required in that version's schema, and a consumer validating against the installed CLI's schema always sees a matching pair. Each schema declares `$schema: https://json-schema.org/draft/2020-12/schema`, a stable `$id` that is the tag-pinned raw URL of the published docs copy, matching the real file name: `https://raw.githubusercontent.com/vr000m/macos-calendar-events/v0.1.0/docs/schema/window-v1.schema.json` and `…/v0.1.0/docs/schema/calendars-v1.schema.json`. These URLs won't resolve until the implementation PRs merge and `v0.1.0` is tagged; that is expected, and nothing in CI fetches them. Once tagged, koda may rely on the pinned tag URL and `schema_version: {const: 1}`.
  - **Envelopes** (all keys required): the window document is `{schema_version, window: {start, end}, events: [...]}`, where `window` echoes the padded caller window (not the ±1-day query range). The calendars document is `{schema_version, calendars: [...]}`. See `WindowDocument`/`CalendarsDocument` in the type sketch.
  - **Serialization:** UTF-8 with `ensure_ascii=False`, `sort_keys=True`, `indent=2` and a trailing newline. Datetimes are RFC 3339 with whole seconds (`timespec="seconds"`); raw timestamps are truncated to whole seconds at the `Raw*` boundary.
  - **Stability rules within v1:** fields may be **added** (consumers must ignore unknown keys), but none are removed, renamed, retyped, or changed in meaning. **Enums are open within v1:** a new enum value is an additive change. Schema enum fields are `type: string` with their known values listed in an `x-known-values` annotation and the field `description`, and consumers map unknown values to `unknown`. Any breaking change bumps `schema_version` to 2 with new schema files.
  - **Enforcement:** contract tests (Phase 5b) validate CLI output against the schemas, with format checking on, and compare it byte for byte with golden files `tests/golden/window-v1.json` and `tests/golden/calendars-v1.json`. Goldens are the **single stated exception** to "expected values never come from running the code". They are change detectors generated by `scripts/regen_goldens.py`, hand-reviewed before commit, and any golden change needs a `CHANGELOG.md` line. Phase 2's hand-written expected values remain the independent correctness check.
  - **Documented consumer rule (README):** call the CLI by absolute path with a timeout (suggested 10 s; Phase 0 measured cold queries at ~0.3 s, first launch of a fresh install ~1.6 s), don't parse stderr, and treat any non-zero exit, signal, timeout, missing executable, or JSON/schema/`schema_version` mismatch as "no calendar hints". Never treat it as fatal for the consumer's own pipeline. **Install and locate:** the supported install is `uv tool install git+https://github.com/vr000m/macos-calendar-events@v0.1.0` (a pinned tag), which puts the CLI in `~/.local/bin`. A launchd agent's PATH doesn't include `~/.local/bin`, so consumers invoke the CLI by absolute path. koda reads it from config/env (e.g. `KODA_CALENDAR_CLI`, default `~/.local/bin/macos-calendar-events`) and treats `FileNotFoundError` as "no hints".
  - **Performance:** a cold-process startup of ~100–200 ms (Python + PyObjC import) per call is acceptable. Startup optimization is out of scope. Phase 0 times store creation plus ±15-minute and ±7-day queries, cold.
- R19. **macOS 14 (Sonoma) or newer only.** `default_source()` gates on feature detection, `EKEventStore.instancesRespondToSelector_("requestFullAccessToEventsWithCompletion:")`, rather than parsing `platform.mac_ver()`. If the selector is missing, it raises `EventKitUnavailableError` (CLI exit `4`), quoting `platform.mac_ver()[0]` in the message for information only. There are no code paths for older macOS.

## Non-Goals

- Ranking, scoring, fuzzy matching, or choosing "the" meeting. No LLM calls. (These belong to koda-pipecat.)
- Writing, editing, or deleting events, reminders (`EKEntityTypeReminder`), alarms, or attachments.
- Non-EventKit sources (ICS URLs, CalDAV, Google/Microsoft APIs). A future `calendar-window`-style multi-backend is out of scope.
- Change notifications (`EKEventStoreChangedNotification`), result caching, daemons.
- Detecting calendars that are *hidden* (unchecked) in Calendar.app. EventKit doesn't expose that view state, so hidden-but-subscribed calendars are returned. This is documented, and the `calendars` filter is the workaround.
- Delegate calendars. Phase 0 found all 15 delegate sources already among the default store's sources, so nothing is excluded on that Mac. Exchange-specific delegate handling is unverified; if a consumer finds delegates missing, `initWithSources:` is a follow-up.
- Detecting which app TCC attributes a request to (remediation text is generic, R9).
- Converting to or presenting local time (the consumer's concern; R12).
- Windows over the R13 cap, Python < 3.11, macOS < 14 (R19), publishing to PyPI (release is a follow-up plan).
- Optimizing CLI startup latency or running a resident server/daemon for consumers (R18 accepts ~100–200 ms per call).
- Merging duplicate rows when one invite appears in several calendars. Rows stay separate; consumers dedupe on `(external_id, occurrence_start)` when `external_id` is non-null (R3).

## Review Focus

- **EventKit contracts** (Apple Developer docs):
  - `EKEventStore.requestFullAccessToEventsWithCompletion:` (macOS 14+; the only request API used).
  - `EKAuthorizationStatus` values (`FullAccess`=3 replaced `Authorized` on 14+, `WriteOnly`=4).
  - `predicateForEventsWithStartDate:endDate:calendars:` four-year limit and its edge behavior (measured in Phase 0). `eventsMatchingPredicate:` expands recurring occurrences.
  - `EKEvent.occurrenceDate`, `isDetached`, `hasRecurrenceRules`, `calendarItemExternalIdentifier` (may be nil, shared across occurrences, or differ across accounts), `eventIdentifier`.
  - `EKParticipant.URL`, `participantRole/Status/Type`, `isCurrentUser`.
  - `EKSourceType`, `EKCalendar.allowsContentModifications`, `EKCalendar.color`.
  - Whether a store created before the grant returns data after it.
- **TCC attribution:** TCC attributes access to the *responsible process* (Phase 0): the terminal app for terminal-launched processes, and the job's executable for a launchd job and its children. Because koda runs the CLI as a **subprocess**, attribution follows koda's own responsible process. Phase 0 measured Rex (terminal) and launchd; a prompt appeared for a bare interpreter, so no app Info.plist was needed there. Terminal.app, VS Code, cron, and a launchd job whose executable differs from the CLI's interpreter are **unmeasured** (Phase 6 checks them). **This was the highest risk; Phase 0 de-risked the measured contexts only.**
- **Completion-handler threading:** the completion block fires on an arbitrary queue. `_access.wait_for_access` blocks on `threading.Event` with a timeout. Phase 0 confirmed that no `NSRunLoop` pumping is needed.
- **Time:** UTC-only input (integer epoch seconds or RFC 3339 `Z`/`+00:00`) and output (strings plus `_ts` epochs) (R12); RFC 3339 `…Z` with whole seconds; DST transitions; floating (no-tz) events; all-day `start_date`/`end_date` exclusivity; ±1-day query widening (R13); `time_zone` passed through as informational, including non-IANA names such as `GMT+0530`.
- **Cross-repo contract:** JSON Schema draft 2020-12 with format checking, additive-only evolution within `schema_version` 1.
- **Formats:** RFC 6068 (`mailto:`), RFC 3986 scheme case-insensitivity, RFC 2606 fixture domains.
- **Overlap semantics** at boundaries, including zero-duration events.

## Architecture & Call Flow

> **Confirmed by the user 2026-11-19**, with one override: koda-pipecat integrates through a **CLI subprocess**, not a library import (see Decisions). Independently executing components:
> - the launcher (Terminal or launchd), which determines TCC attribution;
> - the koda-pipecat process;
> - the CLI subprocess, which hosts this library and Apple's EventKit framework in-process;
> - the out-of-process calendar agent plus TCC daemon.
>
> `cli.py` calls `_api.query_events(get_source, …)` with `get_source = (lambda: source) if source is not None else default_source`. Its injected test source works, and window validation runs before the EventKit availability check (R11 order). The public `events_in_window` / `list_calendars` in `__init__` are thin wrappers over the same `_api` functions, with `default_source()`.

```mermaid
graph LR
    L[launcher: Terminal app or launchd agent] -->|starts; TCC responsible process| K[koda-pipecat]
    K -->|subprocess by absolute path + timeout; JSON schema v1 on stdout| BIN[~/.local/bin/macos-calendar-events: uv-tool venv python. Under launchd, TCC sees the job's executable, which may be koda's interpreter, not this one]
    BIN --> CLI[cli.py]
    P[in-process Python users / tests] -.->|secondary| INIT[__init__: events_in_window / list_calendars]
    INIT -->|default_source| API[_api.query_events / query_calendars]
    CLI -->|get_source| API
    API -->|pure| MAP[_mapping.py]
    MAP -->|builds| MOD[models.py]
    CLI -->|window_to_json / calendars_to_json| MOD
    API -->|EventSource protocol| EK[_eventkit.py EventKitSource]
    EK -->|wait| ACC[_access.wait_for_access]
    EK -->|PyObjC| EVK[EventKit.framework]
    EVK -->|XPC| CAL[calendaragent + tccd]
    U((user)) -.->|answers prompt, attributed to launcher app| CAL
```

```mermaid
sequenceDiagram
    participant K as koda-pipecat
    participant C as CLI subprocess
    participant D as default_source()
    participant A as _api
    participant S as EventKitSource
    participant T as tccd / calendaragent
    participant M as _mapping
    K->>C: spawn `window --start <epoch> --end <epoch> --pad-minutes 15` (no --prompt; timeout)
    C->>A: query_events(get_source, start, end, calendars, include_notes, prompt)
    A->>M: validate_window(start, end)  (InvalidQueryError on naive / non-UTC / inverted / over cap → exit 2)
    A->>D: get_source() = default_source()
    D-->>A: EventKitUnavailableError → exit 4 (if no EventKit / macOS < 14)
    A->>S: authorization_status() (raw int)
    A->>M: access_status_from_int(int)
    alt not_determined and prompt
        A->>S: request_access(ACCESS_TIMEOUT_S)
        S->>T: requestFullAccessToEvents (wait_for_access ≤ timeout)
        T-->>S: granted / denied / no callback
        A->>S: authorization_status() (re-check)
    end
    A-->>C: CalendarAccessError if not full_access → exit 3
    A->>S: calendars()
    A->>M: select_calendars(raw_calendars, selectors)  (CalendarNotFoundError → exit 5)
    A->>M: query_range(padded_start, padded_end)  (±1 day)
    A->>S: events(query_start, query_end, calendar_ids)  (queried exactly as given)
    S-->>A: list[RawEvent]  (plain Python, no ObjC objects)
    A->>M: to_events(raw, window, include_notes)  (map, overlap filter, sort)
    M-->>A: MappedEvents(events, skipped)
    A-->>C: QueryResult(events, skipped)
    C->>C: window_to_json(events, window=padded)  (models.py)
    C-->>K: stdout JSON (schema_version 1), exit 0
    Note over K,C: non-zero exit / signal / timeout / parse error → koda proceeds with no calendar hints
```

**Grant run (one-shot setup, not part of the normal flow above).** The only way to grant access under launchd is to run `macos-calendar-events calendars --prompt` once from the consumer's own launchd job, or from the README's standalone one-shot job. It uses the same flow as above with `--prompt`, and differs in four ways:
- It needs a logged-in GUI session (`gui/$UID` domain) for the prompt to show.
- Its timeout is at least 70 s, because `request_access` waits up to `ACCESS_TIMEOUT_S` = 60 s. The 10 s consumer timeout applies to normal runs only.
- Exit 0 means granted. Exit 3 means denied, or that no prompt could be shown (for example under cron).
- The grant belongs to the launchd job's executable (R9), so the job must run an executable that is stable across runs, not `uv run` or a shell wrapper.

## Implementation Checklist

Each phase ends in a green, checkable state, and the next phase doesn't start until it is. Every `/conduct`-run phase gate (Phases 1–4, 5a, 5b and 6) ends with the **full CI command** (spelled out literally in each Test command so `/conduct` can run it), so a phase-boundary commit can't be CI-red:

Full gate: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -m "not live" && bash scripts/check_readonly.sh && bash scripts/check_privacy.sh`

Phase-specific pytest paths run first as a fast check. **Live-command preflight** (applies to the Phase 4 live smoke and the Phase 5b `Validation cmd`; the Phase 5b reset step and the Phase 6 launchd steps deliberately skip it): those commands run from the terminal app that holds the Calendar grant (recorded in Phase 0 Findings). It is preceded by `uv run python -c "import sys, macos_calendar_events as m; s = m.authorization_status(); print(s); sys.exit(s != 'full_access')"`, which fails fast without prompting (available from Phase 4).

### Spike 0: EventKit and TCC spike (human-run; throwaway; decided the design)

**Status:** done 2026-11-19; results are in `## Findings`. This section is historical. The spike script was committed at `3f27a1f` and deleted in `7f12955`, so it is no longer in the tree. The heading avoids the `### Phase N:` form on purpose, because `/conduct` parses that form as a phase to run. "Phase 0" elsewhere in this plan means this spike.

Former slots (historical, not for `/conduct`): impl file `scripts/spike_eventkit.py`; no test files; run with `uv run --python 3.12 --with pyobjc-framework-EventKit python scripts/spike_eventkit.py --summary`.

**Goal:** Turn the riskiest assumptions into observed facts before freezing types. The spike prints **counts and shapes only**, never titles, names, emails, notes, or ids.

- Record the interpreter path, Python version and PyObjC version. Time the bare interpreter + `import EventKit` separately from `uv run` overhead (R18 budget).
- **Permissions:** from Terminal.app and from the user's usual terminal or VS Code, check `authorizationStatusForEntityType_`, call `requestFullAccessToEventsWithCompletion_`, and record whether a prompt appears, which app it names, and the resulting status. Record if the process is killed instead of returning a status.
- **Subprocess attribution (koda's path):** run the spike as a *child process* (a) of a Python parent started from Terminal and (b) of a parent started by a user `launchd` agent (`launchctl bootstrap gui/$UID` with a temporary plist the user loads and unloads). For each, record attribution, whether a prompt can appear, the resulting status, and whether a grant made from Terminal carries over.
- **Run loop:** confirm whether `threading.Event.wait(timeout)` receives the completion without an `NSRunLoop`; if not, record that `NSRunLoop.currentRunLoop().runUntilDate_` slices are required.
- **Store lifetime:** after a first-time grant (on a reset grant, done by the user), compare calendar and event counts from the store created before the grant with those from a fresh store (input to the store-lifetime rule; Phase 0 may relax it to a single store).
- **Four-year limit:** counts only. Compare one 1460-day query with the sum of four 365-day queries over the same range, and record what a 1462-day query returns (input to the R13 cap).
- **Timing:** cold store creation plus a ±15-minute query and a ±7-day query; confirm or adjust the suggested 10 s consumer timeout (R18).
- **Executable attribution:** also run the launchd-child case through the same kind of executable koda will run, a `uv tool`-installed entry point (a throwaway package) invoked by absolute path, and record which executable path TCC attributes.
- **System Settings:** record whether the Calendars pane allows manually adding an app or binary, and whether a launcher that never prompted shows up there (this shapes the R9 remediation text and the D1 reopen criteria).
- **Framework stderr:** record whether Apple frameworks or PyObjC write to stderr on the `not_determined` and denied paths (R11).
- **Predicate edges:** over a real window, compare counts for events ending exactly at, starting exactly at, and zero-length on the window edges between a narrow query and a widened-then-filtered query (informational: the adapter widens by ±1 day regardless, R13).
- **Shapes over a real ±7-day window** (counts only):
  - nil counts for `calendarItemExternalIdentifier`, `title`, `eventIdentifier`, `occurrenceDate`, `timeZone`, source title, `event.calendar`, `calendar.title`, `calendar.calendarIdentifier`, `startDate`, `endDate`, `organizer`, participant `URL` and `name`;
  - counts of events that would be skipped under the R3 rule (nil `startDate`, `endDate` or calendar identifier);
  - duplicate counts of the R3 `id` base key, and whether occurrences and detached occurrences share `eventIdentifier`;
  - floating (no `timeZone`) timed events, counted;
  - `timeZone` names that `zoneinfo.ZoneInfo` rejects;
  - whether recurring occurrences share the external id;
  - whether the same invite in two calendars shares an external id, reported explicitly as "observed / not observed";
  - participant URL scheme distribution;
  - all-day `startDate`/`endDate` representation (raw instants and the local date components the adapter captures for `_mapping.normalize_all_day`);
  - `participantType` values;
  - a `hasRecurrenceRules` × `isDetached` cross-tab, and `occurrenceDate` vs `startDate` on detached events;
  - per source type, how many events have 0, 1 or more `isCurrentUser` attendees, and whether the organizer repeats in `attendees`;
  - calendar color spaces and whether sRGB hex conversion succeeds with the declared dependencies;
  - `delegateSources` count vs default-store sources;
  - `EKSourceType` values seen.
- **Exit checklist (Phase 0 is done only when all hold):**
  - every bullet above has a recorded result in `## Findings` (Phase 0);
  - measurements are recorded in `## Findings` below the marker. `## Decisions` and the contract above the marker are edited (via `/dev-plan update`) **only when a result forces a contract change**. Phase 0 runs **before** the final `/review-plan`: after Phase 0, one `/review-plan` runs, then `/conduct`;
  - the architecture-reopen criteria are checked explicitly. **Stop and re-plan the CLI-subprocess architecture only if** (a) the CLI launched under a launchd-started parent can't reach `full_access` by any documented user step (granting from Terminal, or adding the executable in Privacy settings, if Phase 0's System Settings check shows that's possible), or (b) the permission completion callback never fires even with the run loop pumped. Every other Phase 0 result updates Phases 2–4 via `/dev-plan update`, followed by a fresh `/review-plan`.
  - Spike 0 is recorded as done in `## Progress` (as a plain line, not a checkbox, so `/conduct` doesn't parse it as a phase);
  - the spike is deleted in a second human-run Phase 0 commit, after the findings commit, so Phase 1 starts from a tree that passes `ruff check .` and the privacy gate.
- Commit the spike with its findings (so history keeps it), then delete it in a second Phase 0 commit.

### Phase 1: Scaffold, tooling, CI

**Impl files:** `pyproject.toml, uv.lock, .gitignore, README.md, CHANGELOG.md, src/macos_calendar_events/__init__.py, src/macos_calendar_events/py.typed, src/macos_calendar_events/_eventkit.py, .github/workflows/ci.yml, scripts/check_readonly.sh, scripts/eventkit_selectors.allow, scripts/check_privacy.sh`
**Test files:** `tests/test_import.py, tests/test_check_scripts.py`
**Test command:** `uv run pytest tests/test_import.py tests/test_check_scripts.py -v && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -m "not live" && bash scripts/check_readonly.sh && bash scripts/check_privacy.sh`

**Goal:** Every later phase lands on a working lint/type/test/guard harness. The package imports without PyObjC.

- The spike was already deleted in Phase 0's second commit, so Phase 1 starts from a clean tree.
- `.gitignore`: add `/.conduct/` and `/.gauntlet/` (skein run state). `check_privacy.sh` scans untracked, not-ignored files, so unignored state files would be scanned.
- **Manual post-commit step (user-run; must pass before Phase 2):** `git push -u origin feature/core-events-api && gh run watch --exit-status`. Phases 2–5b end at a green local gate and are not pushed one by one; CI first sees them at the next push. Phase 6 ends with a mandatory push and `gh run watch --exit-status`, and R17's criterion applies to that head.
- Run `uv lock --check` with both `/opt/homebrew/bin/uv` and `~/.local/bin/uv` by absolute path, and record the result in Findings.
- `pyproject.toml`:
  - hatchling, src layout, package data `schema/*.json` included.
  - `readme = "README.md"`; this phase adds a stub README that Phase 6 fills.
  - `description` states macOS 14+; generic classifiers (R15); `[tool.uv] required-version = ">=0.9"`.
  - `[project.scripts] macos-calendar-events = "macos_calendar_events.cli:main"`. The entry point targets `cli.py`, which first exists in Phase 5a. That is accepted, because nothing invokes the script before then.
  - `[dependency-groups] dev = [pytest, ruff, mypy, "jsonschema[format-nongpl]", types-jsonschema]`.
  - ruff config: target py311, `select = ["E","F","I","B","UP","SIM","RUF"]`.
  - mypy: `strict = true`, `files = ["src", "tests"]`, override `ignore_missing_imports` for `EventKit`, `Foundation`, `AppKit`, `objc`.
  - pytest: `markers = ["live: touches the real macOS calendar; opt-in"]`. `uv.lock` committed.
- `CHANGELOG.md` stub (an `Unreleased` section), so golden changes in Phase 5a/5b have somewhere to be logged.
- `_eventkit.py` starts as a three-line stub (lazy `import EventKit` inside a function) so the strict-mypy + PyObjC-as-`Any` assumption is proven now, not in Phase 4.
- `tests/test_import.py` (fresh subprocess via `sys.executable -c`, so the result doesn't depend on test order):
  - with `sys.modules['EventKit'] = sys.modules['Foundation'] = sys.modules['objc'] = None`, `import macos_calendar_events` succeeds and exposes `__version__`;
  - in a normal subprocess, `"EventKit" not in sys.modules` after import.
- `scripts/check_readonly.sh`: the R10 denylist via `grep -rnE` with strict exit-code handling, the selector allowlist comparison, and an R14 check with the anchored pattern `^[[:space:]]*(import|from)[[:space:]]+(EventKit|Foundation|AppKit|objc)([[:space:].]|$)`, which may match only in `_eventkit.py`. Each check emits its R10 stderr tag.
- `scripts/check_privacy.sh`: per R16.
- `tests/test_check_scripts.py` copies each script into a temp tree (initialized with `git init` and `git add`, so `git ls-files` is real) and runs it. Every case asserts the exit code **and** the expected stderr tag:
  - clean tree → exit 0;
  - `check_readonly.sh`, parametrized over **all 10** denylist alternatives, each seeded in a non-`_eventkit.py` module → `[denylist]`;
  - a selector missing from the allowlist → `[allowlist]`; a stale allowlist entry that the code no longer uses → `[allowlist]`;
  - `import EventKit`, `from EventKit import X` and `import objc` in a non-`_eventkit.py` module → `[imports]`; a comment mentioning pyobjc passes;
  - an unreadable file (`chmod 000`) isolates grep exit 2 → `[grep-error]`; `src/` missing → non-zero;
  - `check_privacy.sh` (every seed address is assembled at runtime from parts, so no disallowed literal exists in any tracked file): a non-RFC-2606 address with an uppercase domain → 1; near-miss domains (a look-alike of `example.com`, and `example.com` used as a prefix of another domain) → 1; an RFC 2606 subdomain address and a GitHub noreply address → 0; a non-git directory → 2; an untracked, not-ignored file holding a disallowed address → 1; the same file gitignored → 0; a tracked file deleted from the worktree is skipped (exit 0);
  - **self-test over the real repository:** `check_privacy.sh` run on the actual checkout exits 0.
- CI per R17 (macOS 3.11 and 3.13 run the full gate; ubuntu 3.12 runs `uv run pytest -m "not live"`).

### Phase 2: Domain types, JSON serialization and schemas

**Impl files:** `src/macos_calendar_events/models.py, src/macos_calendar_events/errors.py, src/macos_calendar_events/schema/window-v1.schema.json, src/macos_calendar_events/schema/calendars-v1.schema.json, docs/schema/window-v1.schema.json, docs/schema/calendars-v1.schema.json, scripts/sync_schemas.py`
**Test files:** `tests/test_models.py, tests/test_schemas.py, tests/test_schema_copies.py`
**Test command:** `uv run pytest tests/test_models.py tests/test_schemas.py tests/test_schema_copies.py -v && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -m "not live" && bash scripts/check_readonly.sh && bash scripts/check_privacy.sh`
**Goal:** The public data shape is fixed and serializes to one stable JSON form. One module owns serialization and `SCHEMA_VERSION`.

- Frozen, slotted dataclasses and `StrEnum`s per the type sketch. Collections are tuples.
- `models.py` owns `SCHEMA_VERSION = 1`, `window_to_json(events, *, window) -> str` and `calendars_to_json(calendars) -> str`, both using the R18 serialization rules (sort_keys, indent 2, `ensure_ascii=False`, trailing newline, `timespec="seconds"`). Keys are always present, with `None` as `null`.
- Errors: base `MacosCalendarEventsError`; `CalendarAccessError(status: AccessStatus)`, `CalendarNotFoundError(selectors, available_titles)`, `EventKitUnavailableError`, and `InvalidQueryError(MacosCalendarEventsError, ValueError)` for window and `calendars=[]` errors. `InvalidQueryError` is the only `ValueError` the CLI maps to exit 2.
- Write both JSON Schemas by hand from the type sketch: `$schema`, `$id`, `schema_version: {const: 1}`, required keys, types, nullability per R3, `color_hex` pattern `^#[0-9A-F]{6}$`, `date-time` formats, `additionalProperties: true`. Enum fields are open: `type: string` plus `x-known-values: [...]` and a `description` listing the values (R18). `start_date`/`end_date` use `format: date`, and every instant uses `format: date-time` with `pattern` `^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$`. Both envelopes are specified per `WindowDocument`/`CalendarsDocument`. Every instant string has a required `type: integer` `<name>_ts` sibling, with no minimum, because output may be pre-1970. Run `uv run python scripts/sync_schemas.py` after any schema edit to refresh `docs/schema/`.
- `tests/test_models.py`:
  - hand-written expected dicts derived from the spec (not from calling the code);
  - a non-ASCII title serializes unescaped;
  - a sub-second datetime serializes with whole seconds;
  - the exact `window_to_json` text for a two-event fixture matches a hand-written string (pins key order and indent);
  - a frozen-mutation attempt raises `FrozenInstanceError`.
- `tests/test_schemas.py`:
  - `Draft202012Validator.check_schema` passes on both files;
  - serializer output validates with `format_checker=Draft202012Validator.FORMAT_CHECKER`;
  - negatives: missing required key, wrong type, naive datetime string, `not-a-date`, `schema_version: 2`, a fractional-second instant; `2025-13-45T99:99:99Z` satisfies the pattern but must fail with keyword `format`, which proves format checking is active;
  - positive: an extra unknown key validates;
  - each schema's `required` equals the dataclass field names for `Event`, `Participant`, `CalendarRef` and `CalendarInfo`, **plus** the `_ts` siblings that `to_dict` adds (`start_ts`, `end_ts`, `occurrence_start_ts` on `Event`; none on the other three types);
  - each of the five output enums (`EventStatus`, `ParticipationStatus`, `ParticipantRole`, `ParticipantType`, `SourceType`) has values equal to its field's `x-known-values`; `AccessStatus` is excluded because no schema field carries it. A document with an unknown enum string still validates;
  - an instant with `+02:00` instead of `Z` fails validation;
  - envelope `required` keys equal `WindowDocument`/`CalendarsDocument` in the type sketch;
  - a document with `organizer: null` and `self_status: null` validates;
  - every `<name>_ts` equals the epoch of its `<name>` string (hand-written fixture), and a document missing a `_ts` field fails;
  - `tests/test_schema_copies.py`: each `docs/schema/*.json` is byte-identical to its packaged copy under `src/macos_calendar_events/schema/`.

### Phase 3: Pure core (mapping, access gate, window, selection) against a fake source

**Impl files:** `src/macos_calendar_events/_raw.py, src/macos_calendar_events/_mapping.py, src/macos_calendar_events/_access.py, src/macos_calendar_events/_api.py`
**Test files:** `tests/fakes.py, tests/test_window_query.py, tests/test_calendar_selection.py, tests/test_access.py, tests/test_enum_tables.py, tests/test_mailto.py`
**Test command:** `uv run pytest tests/test_window_query.py tests/test_calendar_selection.py tests/test_access.py tests/test_enum_tables.py tests/test_mailto.py -v && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -m "not live" && bash scripts/check_readonly.sh && bash scripts/check_privacy.sh`
**Goal:** All behavior that isn't "talk to EventKit" is pure and is exercised through `_api.query_events(lambda: fake, …)` / `_api.query_calendars(lambda: fake, …)` with a `FakeSource`, plus `_access.wait_for_access` with injected callables. No `src/` module in this phase imports PyObjC; one darwin-only test reads EventKit constants. This phase does **not** touch `__init__.py` (wired in Phase 4).

- `_raw.py`: the `EventSource` Protocol and the `RawCalendar` / `RawEvent` / `RawParticipant` records:
  - plain Python: raw `timeIntervalSince1970` floats (normalized to whole-second UTC in `_mapping.epoch_to_utc`), local date-time components for all-day events, raw EventKit enum **ints** (including authorization status), strings, `None`. Fields are enumerated in the type sketch;
  - `color_rgb: tuple[float, float, float] | None` already converted to sRGB by the adapter.
- `_mapping.py`: `access_status_from_int`, `source_type_from_int`, `event_status_from_int`, role/status/type tables (unknown int → `UNKNOWN`), `parse_mailto`, `rgb_to_hex`, `parse_instant`, `parse_instant_text`, `validate_window`, `query_range`, `epoch_to_utc`, `normalize_all_day`, `assign_ids`, `select_calendars`, `overlaps`, `map_participant`, `map_calendar`, `map_event`, `to_events` (map → overlap filter → sort), `to_calendars` (map → sort).
- `_access.py`: `wait_for_access(request: Callable[[Callable[[bool, object | None], None]], None], read_status: Callable[[], int], timeout: float, wait: Callable[[threading.Event, float], bool] = threading.Event.wait) -> int`, built on a stdlib `threading.Event`. The injected `wait` is the run-loop seam.
- `_api.py`: `ACCESS_TIMEOUT_S = 60.0`; `query_events(get_source, start, end, *, calendars, include_notes, prompt)` (returns `QueryResult(events, skipped)`; the public wrapper returns `.events`) and `query_calendars(get_source, *, prompt)` run validate (R11 order) → `get_source()` → access gate (R9) → select → `query_range` → fetch → map. It also provides `authorization_status(get_source)` and `request_access(get_source, timeout)` for the public wrappers.
- Named fixture-driven tests, each asserting observable output:
  - **overlap:** event ends exactly at window start → excluded; starts exactly at window end → excluded; spans the whole window → included; zero-duration at window start → included, at window end → excluded.
  - **recurring:** two occurrences of one series → distinct `id`, same `event_identifier`, same `external_id`, `is_recurring=True`; a detached occurrence's `id` differs from its siblings' and is identical across two calls; nil `occurrenceDate` → `occurrence_start == start`.
  - **all-day (`normalize_all_day`, hand-written cases):**
    - single-day (local 00:00 → next-day 00:00);
    - three-day;
    - an inclusive local `23:59:59` end → end instant +1 s and `end_date` the next day;
    - a DST-transition day (America/Los_Angeles 2026-03-08, a 23-hour day) → correct dates, instants 23 h apart;
    - a non-UTC zone (Asia/Kolkata) whose local date differs from the UTC date → `start_date` comes from local components;
    - events at both window edges; `time_zone=None`; timed events have `start_date is None`.
  - **floating:** a timed event with `time_zone=None`.
  - **DST:** an event across the US spring-forward and fall-back boundaries keeps correct UTC instants, serialized with `Z`; `time_zone` passed through unchanged, including a non-IANA name such as `GMT+0530`.
  - **declined:** self attendee `declined` → returned with `self_status == DECLINED`; canceled → `status == CANCELED`.
  - **self rows:** zero `is_self` attendees → `self_status is None`; two → the first in order wins.
  - **attendees:** non-mailto URL → `email=None`, `url` kept; mailto → `url is None`; no name → `name=None`; organizer-only → `attendees == ()`; room → `type == ROOM`; a participant URL with no scheme → `email=None`, `url` kept; the organizer also present in `attendees` → both returned, no dedupe (R3); a nil attendees collection → `()` and a nil organizer → `None`.
  - **nulls:** nil `title`, `event_identifier`, `external_id` → `null` in output, and `id` still unique.
  - **skips (R3):** raw events with a nil start, end or calendar id are not emitted, and `to_events` reports a skip count equal to their number, which `query_events` returns in `QueryResult.skipped`; an event with nil `occurrenceDate` is kept (`occurrence_start == start`).
  - **instants (`parse_instant`, `parse_instant_text`):** `1763568000` and `"1763568000"` → the same UTC datetime as `2025-11-19T16:00:00Z`; `+00:00` accepted; fractional RFC 3339 seconds truncated; rejected with `InvalidQueryError`: `-1`, `"-1"`, `1969-12-31T23:59:59Z`, `datetime(1969, 12, 31, 23, 59, 59, tzinfo=UTC)`, `1.5`, `"1.5"`, `True`, naive, `-00:00`, `+05:30`, date-only, and an out-of-range epoch.
  - **id collisions:** two events in one calendar with the same start and both identifiers nil → distinct ids (one gets the `-2` suffix), identical across two calls.
  - **same invite in two calendars** → two rows, distinct `id`.
  - **mailto (`tests/test_mailto.py`):** `mailto:a@example.com`, `MAILTO:a@example.com`, `mailto:a%40example.com`, `mailto:a@example.com?subject=x`, bare `mailto:` → `None`, `mailto:a@example.com,b@example.com` → first; `mailto:?to=a@example.com` → `a@example.com`; `mailto:a%2Cb@example.com` → `a,b@example.com` (split before decoding); `mailto:%20a@example.com%20` → trimmed; `mailto:?TO=a@example.com` → `a@example.com` (hfield names are case-insensitive); `mailto:a+b@example.com` → `a+b@example.com` (a literal `+` is not decoded to a space).
  - **enum tables (`tests/test_enum_tables.py`):** every known int per table plus one unknown int → `UNKNOWN`; authorization ints 0–4 plus unknown. A darwin-only, non-live test (`skipif(sys.platform != "darwin")`; constants need no TCC grant) asserts table keys equal `EventKit.EKParticipantStatusAccepted` and its peers, `EKAuthorizationStatusFullAccess`, `EKSourceTypeExchange`, and so on.
  - **calendars (R2):** each `CalendarInfo` field from a raw calendar; `read_only=True` calendar; `color_rgb=None` → `color_hex=None`; `(0.0, 0.5, 1.0)` → `#0080FF`; unknown source-type int → `unknown`; calendar ordering, including a mix of null and non-null `source_title` with a hand-written expected order (nulls first).
  - **selection (R6):** id match; case-insensitive title match; duplicate titles across sources both selected; a selector equal to one calendar's id and another's title selects by id only; one valid + one unknown selector → `CalendarNotFoundError`; `calendars=[]` → `InvalidQueryError`; `None` → all.
  - **window validation:** naive → `InvalidQueryError`; `end <= start` → `InvalidQueryError`; non-UTC aware datetime (`+05:30`) → `InvalidQueryError`; a window of exactly 3×365 − 2 days passes and one second more raises; a padded start before 1970 → `InvalidQueryError`; a multi-week window (6 weeks) passes; an old absolute window (`2025-01-06T17:00:00Z`–`2025-01-06T18:00:00Z`) passes and returns its fixture events.
  - **query widening:** `FakeSource` records the range it was asked for, which equals the padded window ±1 day (an effect on the outside system); an all-day event whose UTC instants fall just outside the window but within the widened range is fetched, then included or excluded strictly by `overlaps`.
  - **access gate (`tests/test_access.py`):**
    - each `AccessStatus` from the fake: only `full_access` proceeds; `not_determined` + `prompt=False` raises with zero recorded requests;
    - `not_determined` + `prompt=True` records exactly one request, then: granted → proceeds; denied → raises `CalendarAccessError(DENIED)`; still `not_determined` → raises `CalendarAccessError(NOT_DETERMINED)`;
    - `str(CalendarAccessError(status))` contains the R9 remediation text (`calendars --prompt`);
    - `wait_for_access` with a requester that calls back `True` from another thread → returns the post-grant status; calls back `False` → returns denied status; never calls back → returns the current status after `timeout` (elapsed < timeout + 0.5 s); a fake `wait` is called with the event and `timeout`, and its return value drives the result (run-loop seam).
  - **epoch normalization:** `epoch_to_utc(1700000000.987)` → whole-second UTC; a negative (pre-1970) epoch maps correctly.
  - **empty:** zero events → `[]`; `include_notes=False` → `notes is None` even when raw notes exist.
  - **ordering (R8):** fixtures that tie at each sort-key level assert a hand-written expected order.

### Phase 4: EventKit adapter, platform gate and public API wiring

**Impl files:** `src/macos_calendar_events/_eventkit.py, src/macos_calendar_events/__init__.py, scripts/eventkit_selectors.allow`
**Test files:** `tests/test_eventkit_adapter.py, tests/test_platform_guard.py, tests/test_public_api.py, tests/test_live_smoke.py`
**Test command:** `uv run pytest tests/test_eventkit_adapter.py tests/test_platform_guard.py tests/test_public_api.py -v && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -m "not live" && bash scripts/check_readonly.sh && bash scripts/check_privacy.sh`
**Validation cmd:** `uv run python -c "import sys, macos_calendar_events as m; s = m.authorization_status(); print(s); sys.exit(s != 'full_access')" && MACOS_CALENDAR_EVENTS_LIVE=1 uv run pytest -m live -v`
**Goal:** A thin translation from EventKit objects to `Raw*` records. Decisions live in `_mapping` and waiting lives in `_access`; the adapter's remaining branches run in CI against a stub `EventKitNamespace`. Only this module imports PyObjC.

- `EventKitSource(ek: EventKitNamespace | None = None)` implements `EventSource`:
  - `EventKitNamespace` bundles everything class-level the adapter needs: the store class, `EKEntityTypeEvent`, `NSCalendar`, `NSTimeZone`, and the sRGB color converter. The default is built from the real modules, and tests inject a stub namespace;
  - **store lifetime:** the store is created lazily on first use; after a `request_access` that returns `full_access`, the source discards it and builds a fresh store; `reset` is never called (Phase 0: before/after counts matched, so a single store would also work; the rule stays as insurance, D7);
  - `authorization_status()` returns the raw int;
  - `request_access(timeout)` calls `_access.wait_for_access` with `store.requestFullAccessToEventsWithCompletion_`, with the default `threading.Event.wait` waiter (Phase 0: no run-loop pumping needed);
  - `calendars()` uses `calendarsForEntityType_(EKEntityTypeEvent)`, with NSColor → sRGB via `colorUsingColorSpace_(NSColorSpace.sRGBColorSpace())`, `None` on failure;
  - `events(start, end, calendar_ids)` queries **exactly** the range it receives (`_api` already widened it). It resolves ids via `calendarWithIdentifier_`; `calendar_ids=None` means all, and a non-None list that resolves to zero calendars returns `[]` without querying.
- Getters only, no decisions:
  - `NSDate` → raw `timeIntervalSince1970` float (normalized in `_mapping.epoch_to_utc`);
  - `NSTimeZone.name()` passed through raw;
  - for all-day events, local date-time components of start and end via `NSCalendar.currentCalendar()` components (normalized in `_mapping.normalize_all_day`);
  - NSColor → sRGB floats via the namespace converter, `None` on failure;
  - nil → `None`, except a nil attendees collection → `()`; participant URL → `absoluteString()`.
- `default_source()` and `_clear_default_source()` live in `_eventkit.py`, with one cached `EventKitSource` per process. Raises `EventKitUnavailableError` on non-darwin, `ImportError`, or the missing 14+ selector (R19).
- `__init__.py`: wire `events_in_window`, `list_calendars`, `authorization_status`, `request_access` as thin wrappers over `_api` / `default_source()`, plus re-exports of models, errors and `__version__`.
- `scripts/eventkit_selectors.allow`: the exact selector set used.
- `tests/test_eventkit_adapter.py` (stub store; runs where `objc` is absent by stubbing the factory, and NSDate conversion tests are darwin-only):
  - `request_access` with a stub that never calls back returns the current status within the timeout;
  - calendar-id resolution passes only the selected stub calendars to the predicate;
  - an unknown id is skipped (selection already validated);
  - after a stub `request_access` returns full access, the next read uses a newly built stub store (factory called twice); after denial, no new store is built;
  - the predicate receives `start`/`end` exactly as passed (no widening in the adapter);
  - `calendar_ids=["missing"]` → `[]`, with no predicate call;
  - stub events with nil `attendees`, nil `organizer` and nil `timeZone` → `attendees == ()`, `organizer is None`, `time_zone is None` (the common Phase 0 shapes);
  - darwin-only conversions against real Foundation objects (no TCC grant needed): an `NSDate` with fractional seconds and a pre-1970 `NSDate` → the expected raw floats; a non-RGB `NSColor` → sRGB floats or `None`; local components for a stub all-day event.
- `tests/test_platform_guard.py`: a stub store class without the 14+ selector → `EventKitUnavailableError` whose message includes the version string; with the selector → a source; non-darwin (monkeypatched `sys.platform`) → `EventKitUnavailableError`; blocked `EventKit` import → `EventKitUnavailableError`.
- Live smoke (`@pytest.mark.live`, skipped unless `MACOS_CALENDAR_EVENTS_LIVE=1` **and** darwin), over now ± 7 days: compute violation **counts** (non-aware datetimes, `start > end`, non-overlapping rows, empty ids, duplicate ids, JSON or schema failures) and assert each equals 0; `len(list_calendars()) > 0`. Print only counts. The live calls are wrapped in `try/except Exception as exc`, which fails with `type(exc).__name__` only (`raise … from None`), so no message or traceback carrying calendar data reaches the output. Schema errors are counted via `iter_errors` and never formatted. Extra counts: rows skipped by `to_events` (R3; read from `_api.query_events(default_source, …).skipped`, which the public wrapper doesn't return), all-day rows with null dates, `end_date <= start_date`, and timed rows with non-null dates. Shape counts that Phase 0 didn't observe, so a later run can confirm them: detached rows, floating timed rows, Exchange-source rows, and rows sharing an `external_id` across calendars. A non-live test feeds the smoke helper a fake that raises with a sentinel string, and asserts the sentinel is absent from captured output. **Cap consistency check (opt-in live, counts only):** over a fixed absolute window of 3×365 − 2 days, compare one query with the union of three chunked queries. The count of distinct `(calendar.id, event_identifier or external_id, occurrence_start)` keys must match, and only the difference count is printed. A non-zero difference means the R13 cap is unsafe at that span, so lower it.
- `tests/test_public_api.py`: monkeypatch `default_source` to return a recording `FakeSource`; assert argument forwarding, the defaults `include_notes=False` and `prompt=True`, that `authorization_status()` and `request_access()` return `AccessStatus`, and the re-exported names.

### Phase 5a: CLI and golden generator

> Phase 5 was split into 5a and 5b in review run 4. Older "Phase 5" references in Decisions mean both. `/conduct` hands back after every phase boundary in its default mode (one phase per `--resume`; do not pass `--autonomous` for this plan), so the hand-back after 5a is the review slot for the goldens.

**Impl files:** `src/macos_calendar_events/cli.py, tests/golden_fixtures.py, scripts/validate_json.py, scripts/regen_goldens.py, CHANGELOG.md`
**Test files:** `tests/test_cli.py, tests/test_validate_json.py`
**Test command:** `uv run pytest tests/test_cli.py tests/test_validate_json.py -v && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -m "not live" && bash scripts/check_readonly.sh && bash scripts/check_privacy.sh`
**Goal:** The CLI is a thin shell: parse → `_api` → serialize → map exceptions to exit codes (R11). It has no logic of its own beyond padding and UTC input validation. The golden generator and fixtures exist, but the goldens are neither generated nor committed in this phase, so they get a hand review before anything depends on them (R18).

- `cli.py` and `tests/golden_fixtures.py`, which has one builder each, `build_window_fixture()` and `build_calendars_fixture()`, used by both the generator script and the Phase 5b contract test. The script loads the module by path via `importlib.util.spec_from_file_location`.
- `main(argv: Sequence[str] | None = None, *, source: EventSource | None = None) -> int` calls `_api.query_events(get_source, …)` with `get_source = (lambda: source) if source is not None else default_source`. `source` is the test seam and isn't a CLI flag. The module ends with `if __name__ == "__main__": sys.exit(main())`.
- A catch-all handler maps unexpected exceptions to exit 1 with a one-line class-only message. Exit 2 is mapped only from argparse and `InvalidQueryError`. Exit 5's line names only the unmatched selectors, via `repr()`. stdout is written once, as UTF-8 bytes to `sys.stdout.buffer`, after serialization succeeds.
- `window`: `--start`, `--end` (non-negative integer epoch seconds, or RFC 3339 UTC ending `Z`/`+00:00`; R12), `--calendar` (repeatable), `--pad-minutes N` (int ≥ 0). Order per R12: validate the raw `--start`/`--end`, then pad both ends, then `_api` validates the padded window (cap and 1970 floor). `--include-notes`, `--prompt`. Output: `window_to_json` with the padded window echoed. `calendars`: `calendars_to_json`. `schema <name>`: writes the packaged schema bytes. `--version`.
- `scripts/validate_json.py <schema-name>`: loads the packaged schema, validates stdin with the format checker, prints only the JSON path and keyword on failure, and exits non-zero. `tests/test_validate_json.py` feeds an invalid document containing a sentinel string and asserts the sentinel is absent from output. It also covers empty stdin and non-JSON stdin (non-zero exit, nothing echoed, sentinel absent from stdout and stderr) and a pattern-valid but format-invalid instant (keyword `format`).
- `scripts/regen_goldens.py` writes `tests/golden/*.json` from the `tests/golden_fixtures.py` builders (which include a non-ASCII title, an organizer who also appears in `attendees`, a nil-attendees event, and a `--pad-minutes 15` window). Goldens therefore carry every `_ts` field, and the window golden is produced from epoch-seconds input. **This phase writes the script but does not run it.**
- `tests/test_cli.py`, via `main([...], source=FakeSource(...))` + `capsys`:
  - stdout parses as JSON with the expected events;
  - `--pad-minutes 15` includes an event 10 min before `--start`, and the echoed `window` equals start − 15 min / end + 15 min; `--pad-minutes -1` → exit 2; padding that pushes the window over the cap → exit 2; `--start 0 --pad-minutes 15` → exit 2 (padded start before 1970, R12), while `--start 0 --pad-minutes 0` → 0;
  - `--include-notes` emits notes, and its absence emits `null`;
  - two `--calendar` flags restrict output; an unknown `--calendar` → exit 5;
  - prompt wiring, with `FakeSource` at `not_determined`: without `--prompt`, both `window` and `calendars` exit 3 with **zero** recorded requests; with `--prompt`, exactly one request is recorded; `--no-prompt` is rejected by argparse (exit 2);
  - each error class → its exit code, with one CLI-written stderr line for 1/3/4/5 (argparse exits use `pytest.raises(SystemExit)`); the exit-3 line contains the R9 remediation text (`calendars --prompt`) and no calendar titles;
  - **R11 check order (each case asserts the winning code):** an inverted window with a source whose `default_source` raises `EventKitUnavailableError` → 2 (2 before 4); `EventKitUnavailableError` with a bad selector → 4 (4 before 5); `FakeSource` at `not_determined`, no `--prompt`, and an unknown `--calendar` → 3, not 5 (3 before 5, since an ungranted read returns zero calendars);
  - `default_source` monkeypatched to raise `EventKitUnavailableError` → exit 4, one stderr line, empty stdout; a non-darwin subprocess running `python -m macos_calendar_events.cli calendars` → exit 4 (ubuntu CI); an inverted window on non-darwin → exit 2 (R11 order);
  - `FakeSource` raising `RuntimeError` with a sentinel message → exit 1, stderr exactly `internal error: RuntimeError`, sentinel absent;
  - exit 5 with a newline inside a selector → exactly one stderr line, and it omits calendar titles;
  - one test per input form, each with its expected exit code: epoch `1763568000` → 0; `…Z` → 0; `…+00:00` → 0; fractional `…T12:00:00.5Z` → 0 (truncated); naive → 2; `+05:30` → 2; date-only → 2; `-00:00` → 2; float epoch `1763568000.5` → 2; negative epoch `-1` → 2; pre-1970 `1969-12-31T23:59:59Z` → 2; boundary `0` and `1970-01-01T00:00:00Z` → 0 with byte-identical output. A string that matches the R12 regex but fails `fromisoformat` (for example month 13) → 2, never 1. Also: `window --start 1763568000 --end 1763571600` and `window --start 2025-11-19T16:00:00Z --end 2025-11-19T17:00:00Z` produce **byte-identical** stdout;
  - `schema window-v1` / `schema calendars-v1` stdout is byte-identical to the packaged files; `schema nope` → 2 with empty stdout;
  - `end <= start` → 2;
  - UTC input (R12): `Z` and `+00:00` are accepted; a naive value and `+05:30` each exit 2 with the one-line UTC message and empty stdout; output instants all end in `Z`;
  - an old absolute window (`--start 2025-01-06T17:00:00Z --end 2025-01-06T18:00:00Z`) and a 6-week window both exit 0 with the fixture events.
- **Review slot (user-run, between 5a and 5b; `/conduct` hands back after 5a):**
  1. `uv run python scripts/regen_goldens.py`.
  2. Hand-review the diff of `tests/golden/*.json` against Phase 2's hand-written expected values and the spec.
  3. Add a `CHANGELOG.md` line, then commit the goldens as a user commit.
  4. Run `/conduct --resume`.

### Phase 5b: Contract tests and live validation

**Impl files:** none
**Test files:** `tests/test_cli_contract.py`
**Test command:** `uv run pytest tests/test_cli_contract.py -v && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -m "not live" && bash scripts/check_readonly.sh && bash scripts/check_privacy.sh`
**Validation cmd:** `set -o pipefail; uv run python -c "import sys, macos_calendar_events as m; s = m.authorization_status(); print(s); sys.exit(s != 'full_access')" && uv run macos-calendar-events calendars | uv run python scripts/validate_json.py calendars-v1 && uv run macos-calendar-events window --start "$(date -u -v-1d +%Y-%m-%dT%H:%M:%SZ)" --end "$(date -u -v+1d +%Y-%m-%dT%H:%M:%SZ)" | uv run python scripts/validate_json.py window-v1`
**Goal:** The stable cross-repo contract holds: stdout of every command validates against the v1 schemas and matches the hand-reviewed goldens byte for byte (R18). Any fix a failing contract test needs lands in `cli.py` or the schemas through the fix loop.

- `tests/test_cli_contract.py` (R18):
  - `main([...], source=FakeSource(fixed fixtures))` stdout validates against the schema and equals the committed golden file byte for byte;
  - every error exit leaves stdout empty;
  - real subprocesses `[sys.executable, "-m", "macos_calendar_events.cli", …]` and the installed `macos-calendar-events` script (found via the venv `bin/`): `--help` exits 0; an unparseable `--start` exits 2 with empty stdout; `--version` prints the version and schema_version.
- **Manual validation (user-run, last in this phase):**
  - the live preflight is skipped here, because this step resets the grant;
  - `tccutil reset Calendar <terminal-bundle-id>`, followed by `uv run python -c "import macos_calendar_events as m; print(m.request_access())"`; record prompt, grant and deny behavior;
  - **denied path (not measured in Phase 0):** answer Don't Allow once, then record the CLI exit code (expect 3), whether Apple frameworks or PyObjC write to stderr (bytes only), and whether enabling the entry in System Settings restores access (R9, R11);
  - re-grant before marking the phase done.

### Phase 6: Docs and release readiness (no publish)

**Impl files:** `README.md, CHANGELOG.md`
**Test files:** none
**Test command:** `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -m "not live" && bash scripts/check_readonly.sh && bash scripts/check_privacy.sh`
**Validation cmd:** `uv build && uvx --from dist/*.whl macos-calendar-events --version && uv run --no-project --with dist/*.whl python -c "import importlib.resources as r; p = r.files('macos_calendar_events'); assert (p / 'py.typed').is_file(); [(p / 'schema' / n).read_text() for n in ('window-v1.schema.json', 'calendars-v1.schema.json')]" && test "$(unzip -p dist/*.whl '*.dist-info/METADATA' | grep -cE '^(License-Expression: BSD-2-Clause|Requires-Python: >=3\.11|Requires-Dist: pyobjc-framework-eventkit.*sys_platform == .darwin.)$')" = 3 && uvx --from dist/*.whl macos-calendar-events schema window-v1 | cmp - docs/schema/window-v1.schema.json && uvx --from dist/*.whl macos-calendar-events schema calendars-v1 | cmp - docs/schema/calendars-v1.schema.json`
**Goal:** A stranger can install it, grant permission, and run it from the README alone. Every README command is executed verbatim on the Mac before this phase is marked done, except `tccutil reset` (it revokes the grant) and the pinned-tag `uv tool install …@v0.1.0` (the tag doesn't exist until after merge).

- README sections:
  - what/why (consumer use case in one paragraph, ranking explicitly out of scope);
  - **requirements: macOS 14 Sonoma+**;
  - install: `uv tool install git+https://github.com/vr000m/macos-calendar-events@v0.1.0`, with the CLI landing in `~/.local/bin`, and a note that launchd's PATH lacks `~/.local/bin`, so callers should use the absolute path;
  - permission walkthrough, covering:
    - **Grant from the context that will run the CLI.** TCC keys the grant to the responsible process: the terminal app when run from a terminal, or the launchd job's executable when run under launchd. Granting from Terminal grants only that terminal app.
    - **Interactive use:** run `macos-calendar-events calendars --prompt` once from that terminal.
    - **launchd consumers (koda):** grant once from the consumer's own launchd job. koda runs `macos-calendar-events calendars --prompt` once as a child of its own job, e.g. a one-shot setup command. The grant belongs to the job's executable (koda's interpreter), which may not be the CLI's. Don't use `uv run`, a shell or another wrapper as the job's executable, because the grant would then key an ephemeral or shared binary. The grant run needs a logged-in GUI session (`gui/$UID` domain) and a timeout of at least 70 s, since `request_access` waits up to `ACCESS_TIMEOUT_S` = 60 s. The 10 s consumer timeout applies only to normal runs. Exit 0 means granted; exit 3 means denied, or that no prompt could be shown.
    - **Standalone launchd use:** a documented one-shot recipe. A plist with `ProgramArguments` = the installed CLI's absolute path plus `calendars --prompt`, `RunAtLoad` and no `KeepAlive`; then `launchctl bootstrap gui/$UID <plist>`, click Allow, `launchctl bootout gui/$UID/<label>`. It grants the CLI's interpreter binary.
    - **System Settings:** it can't add apps manually; it only toggles entries that already prompted.
    - **Reset during development:** `tccutil reset Calendar <bundle-id>`, run by the user, never by the tool.
  - interpreter caveats:
    - A uv Python upgrade or reinstall changes the interpreter realpath: the CLI's interpreter under the standalone recipe, koda's interpreter under koda's job. Access is lost (exit 3) until you re-grant. Phase 0 didn't test an upgrade, so the README states this as expected behavior, not as measured.
    - **cron:** unverified (Phase 6 cron check). Until it is recorded, prefer launchd.
    - Any script run under launchd by the granted interpreter inherits Calendar access.
    - Recommend pinning the exact patch version at install (`uv tool install --python 3.12.<patch> …`) and re-running the grant after any interpreter change.
  - **"Integrating from another program" (primary):** absolute-path subprocess call with a timeout, the R18 stability rules and the "any failure = no hints" rule, the `schema` subcommand and a link to `docs/schema/`, with the instruction that consumers and coding agents use the `docs/schema/` copy at the tag matching their installed CLI (e.g. `https://raw.githubusercontent.com/vr000m/macos-calendar-events/v0.1.0/docs/schema/window-v1.schema.json`) or `macos-calendar-events schema`, epoch-seconds input (koda sends integer epoch seconds; RFC 3339 `Z`/`+00:00` is also accepted), the `_ts` output fields, the dedupe key `(external_id, occurrence_start)` when `external_id` is non-null (provisional per Phase 0), and the fact that `id` is opaque;
  - CLI examples; Python API example (secondary); exit codes (R11, including 1);
  - known limitations: hidden calendars, Exchange delegate calendars (unverified), the R13 cap, external-id caveats, floating times, non-IANA zone names;
  - privacy note; BSD-2-Clause.
- The `v0.1.0` tag that the install command pins is created by the user on `main` after merge (user-run; pushing a tag is the user's call). Until then, README examples are validated with `uv tool install --force .` from the checkout.
- **Manual (user-run, post-tag; after the PRs merge and `v0.1.0` is pushed):** for each name in `window-v1 calendars-v1`, `curl -fsSL https://raw.githubusercontent.com/vr000m/macos-calendar-events/v0.1.0/docs/schema/$name.schema.json | cmp - src/macos_calendar_events/schema/$name.schema.json`, which proves the `$id` URLs resolve and match the packaged schemas.
- **Manual (user-run; never automated, because it writes to `~/.local/bin`):** `uv tool install --force . && ~/.local/bin/macos-calendar-events --version`.
- **Manual (user-run): launchd grant recipe.** Pin a Python patch version whose interpreter has no grant yet (`uv tool install --force --python 3.12.<a patch other than Phase 0's> .`), then run the README's one-shot recipe (`calendars --prompt`) unconditionally. Pass: exit 0 and stdout that validates against `calendars-v1`. Record whether a prompt appeared. The recipe must not be skipped because an interpreter was already granted.
- **Manual (user-run): launchd run.** Run the installed `~/.local/bin/macos-calendar-events window` (±1 day, no `--prompt`, no preflight) from a user launchd agent by absolute path. Pass: exit 0 and stdout that validates against `window-v1`.
- **Manual (user-run): different-executable parent.** Run the CLI as a child of a launchd job whose own executable is a different interpreter (for example the system `python3`), which is koda's shape. Record the exit code and which entry (the job's executable or the CLI's interpreter) appears in System Settings → Calendars. If the CLI exits 3, the grant follows the CLI's interpreter; update R9 and the README.
- **Manual (user-run): cron.** Add a temporary crontab entry that runs the CLI by absolute path (`calendars`, then `calendars --prompt`), record exit codes and whether a prompt appears, then remove the entry. If cron can't reach `full_access` by any documented step, the README says cron is unsupported and koda must launch the CLI from launchd.
- Record all four results in Findings (exit codes, counts, entry names; no calendar content).
- **Post-tag check (user-run):** once `v0.1.0` exists, run the README's pinned install command once and record the result.
- A short consumer snippet: `CLI_PATH = os.environ.get("KODA_CALENDAR_CLI", os.path.expanduser("~/.local/bin/macos-calendar-events"))`; `subprocess.run([CLI_PATH, "window", "--start", str(int(t0.timestamp())), "--end", str(int(t1.timestamp())), "--pad-minutes", "15"], capture_output=True, timeout=10)`, with `FileNotFoundError`/`TimeoutExpired`/non-zero/`json.JSONDecodeError` all mapped to "no hints", then a `schema_version` check, dedupe on `(external_id, occurrence_start)` for non-null `external_id`, and reconcile in your own code.

## Technical Specifications

### Files to Modify
- `.gitignore`: add `/.conduct/` and `/.gauntlet/` in Phase 1 (it already covers `.venv`, `.mypy_cache`, `dist/`, `/.review-plan`, `/.spike/`; `uv.lock` stays tracked).

### New Files to Create
- `pyproject.toml`, `uv.lock`, `README.md` (stub in Phase 1, full in Phase 6): packaging and tooling.
- `src/macos_calendar_events/__init__.py`: public API wrappers (Phase 4) and re-exports.
- `src/macos_calendar_events/models.py`: domain dataclasses, enums, `SCHEMA_VERSION`, `window_to_json`, `calendars_to_json`.
- `src/macos_calendar_events/errors.py`: exception hierarchy.
- `src/macos_calendar_events/_raw.py`: `EventSource` Protocol and `Raw*` records (adapter contract).
- `src/macos_calendar_events/_mapping.py`: pure functions, including all EventKit int → enum tables.
- `src/macos_calendar_events/_access.py`: `wait_for_access` (stdlib only).
- `src/macos_calendar_events/_api.py`: orchestration over an `EventSource`.
- `src/macos_calendar_events/_eventkit.py`: the only PyObjC importer.
- `src/macos_calendar_events/cli.py`: argparse CLI.
- `src/macos_calendar_events/schema/window-v1.schema.json`, `src/macos_calendar_events/schema/calendars-v1.schema.json`: the cross-repo JSON contract (R18), shipped as package data.
- `src/macos_calendar_events/py.typed`
- `docs/schema/window-v1.schema.json`, `docs/schema/calendars-v1.schema.json`: published byte-identical copies of the packaged schemas (packaged copy is the source of truth); `scripts/sync_schemas.py` refreshes them.
- `tests/fakes.py`, `tests/test_*.py`, `tests/golden/*.json`: fakes, tests, goldens (fictional data only).
- `scripts/check_readonly.sh`, `scripts/eventkit_selectors.allow`, `scripts/check_privacy.sh`, `scripts/validate_json.py`, `scripts/regen_goldens.py`; (the Phase 0 spike script `scripts/spike_eventkit.py` was deleted in `7f12955`; nothing to create).
- `.github/workflows/ci.yml`, `CHANGELOG.md`.

### Type and Signature Sketch

This sketch is the single source for public signatures.

```python
# models.py
SCHEMA_VERSION: Final = 1
class AccessStatus(StrEnum): NOT_DETERMINED="not_determined"; RESTRICTED="restricted"; DENIED="denied"; FULL_ACCESS="full_access"; WRITE_ONLY="write_only"; UNKNOWN="unknown"
class EventStatus(StrEnum): NONE="none"; CONFIRMED="confirmed"; TENTATIVE="tentative"; CANCELED="canceled"; UNKNOWN="unknown"
class ParticipationStatus(StrEnum): UNKNOWN="unknown"; PENDING="pending"; ACCEPTED="accepted"; DECLINED="declined"; TENTATIVE="tentative"; DELEGATED="delegated"; COMPLETED="completed"; IN_PROCESS="in_process"
class ParticipantRole(StrEnum): UNKNOWN="unknown"; REQUIRED="required"; OPTIONAL="optional"; CHAIR="chair"; NON_PARTICIPANT="non_participant"
class ParticipantType(StrEnum): UNKNOWN="unknown"; PERSON="person"; ROOM="room"; RESOURCE="resource"; GROUP="group"
class SourceType(StrEnum): LOCAL="local"; EXCHANGE="exchange"; CALDAV="caldav"; MOBILEME="mobileme"; SUBSCRIBED="subscribed"; BIRTHDAYS="birthdays"; UNKNOWN="unknown"

@dataclass(frozen=True, slots=True)
class Participant:
    name: str | None; email: str | None; url: str | None     # url is None when the participant URL is mailto:
    role: ParticipantRole; status: ParticipationStatus; type: ParticipantType; is_self: bool

@dataclass(frozen=True, slots=True)
class CalendarRef:
    id: str; title: str | None; source_title: str | None

@dataclass(frozen=True, slots=True)
class CalendarInfo:
    id: str; title: str | None; source_title: str | None; source_type: SourceType
    color_hex: str | None   # "#RRGGBB" (sRGB) or None
    read_only: bool         # not allowsContentModifications
    def to_dict(self) -> dict[str, object]: ...

@dataclass(frozen=True, slots=True)
class Event:
    id: str                         # opaque; unique within one response (format not part of the contract)
    external_id: str | None         # calendarItemExternalIdentifier
    event_identifier: str | None    # EKEvent.eventIdentifier; shared by occurrences of a series
    title: str | None
    start: datetime; end: datetime  # UTC; end exclusive; whole seconds; serialized as …Z string + start_ts/end_ts int
    all_day: bool
    start_date: date | None; end_date: date | None   # all-day only; end exclusive; computed by `_mapping.normalize_all_day` from adapter-captured local components
    time_zone: str | None           # informational: IANA when available, else raw EventKit name; None = floating
    location: str | None; url: str | None; notes: str | None
    status: EventStatus
    is_recurring: bool; is_detached: bool
    occurrence_start: datetime      # occurrenceDate, falling back to start; serialized + occurrence_start_ts
    organizer: Participant | None
    attendees: tuple[Participant, ...]
    self_status: ParticipationStatus | None
    calendar: CalendarRef
    def to_dict(self) -> dict[str, object]: ...   # adds start_ts, end_ts, occurrence_start_ts (R12); schema required = fields + these three

class WindowEcho(TypedDict): start: str; end: str; start_ts: int; end_ts: int   # padded caller window
class WindowDocument(TypedDict): schema_version: Literal[1]; window: WindowEcho; events: list[dict[str, object]]
class CalendarsDocument(TypedDict): schema_version: Literal[1]; calendars: list[dict[str, object]]

def window_to_json(events: Sequence[Event], *, window: tuple[datetime, datetime]) -> str: ...
def calendars_to_json(calendars: Sequence[CalendarInfo]) -> str: ...

# _raw.py  (adapter boundary; no ObjC types cross it; private; stable after Phase 0)
@dataclass(frozen=True, slots=True)
class RawParticipant:
    name: str | None; url: str | None; role: int; status: int; type: int; is_current_user: bool
@dataclass(frozen=True, slots=True)
class RawCalendar:
    id: str; title: str | None; source_title: str | None; source_type: int
    color_rgb: tuple[float, float, float] | None; allows_modifications: bool
@dataclass(frozen=True, slots=True)
class RawEvent:
    calendar_id: str | None                                   # nil → row skipped in _mapping (R3)
    external_id: str | None; event_identifier: str | None; title: str | None
    start_epoch: float | None; end_epoch: float | None; occurrence_epoch: float | None   # nil start/end → skipped
    all_day: bool
    start_local: tuple[int, int, int, int, int, int] | None   # all-day only: (Y, M, D, h, m, s) in the system zone
    end_local: tuple[int, int, int, int, int, int] | None
    time_zone: str | None; location: str | None; url: str | None; notes: str | None
    status: int; has_recurrence_rules: bool; is_detached: bool
    organizer: RawParticipant | None; attendees: tuple[RawParticipant, ...]

class EventSource(Protocol):
    def authorization_status(self) -> int: ...               # raw EKAuthorizationStatus
    def request_access(self, timeout: float) -> int: ...     # raw status after the wait
    def calendars(self) -> Sequence[RawCalendar]: ...
    def events(self, start: datetime, end: datetime, calendar_ids: Sequence[str] | None) -> Sequence[RawEvent]: ...

# _access.py  (stdlib only)
def wait_for_access(request: Callable[[Callable[[bool, object | None], None]], None],
                    read_status: Callable[[], int], timeout: float,
                    wait: Callable[[threading.Event, float], bool] = threading.Event.wait) -> int: ...

# _mapping.py  (pure)
def access_status_from_int(value: int) -> AccessStatus: ...
def epoch_to_utc(seconds: float) -> datetime: ...                        # truncate to whole seconds, UTC
def normalize_all_day(start_epoch: float, end_epoch: float, start_local: tuple[int, ...],
                      end_local: tuple[int, ...]) -> tuple[datetime, datetime, date, date]: ...  # inclusive 23:59:59 end → +1 s; dates from local components
def assign_ids(events: Sequence[Event]) -> list[Event]: ...            # R3 derivation; ordinal suffix on collision
def parse_mailto(url: str) -> str | None: ...
def validate_window(start: datetime, end: datetime) -> None: ...          # aware, utcoffset()==0, >= 1970, end > start, length <= 3*365-2 days
def query_range(start: datetime, end: datetime) -> tuple[datetime, datetime]: ...  # (start - 1 day, end + 1 day)
def select_calendars(cals: Sequence[RawCalendar], selectors: Sequence[str] | None) -> list[RawCalendar]: ...
def overlaps(ev_start: datetime, ev_end: datetime, w_start: datetime, w_end: datetime) -> bool: ...
class MappedEvents(NamedTuple): events: list[Event]; skipped: int
def to_events(raw: Sequence[RawEvent], window: tuple[datetime, datetime], *, include_notes: bool) -> MappedEvents: ...
def parse_instant(value: datetime | int) -> datetime: ...              # int epoch ≥ 0 or aware UTC datetime; else InvalidQueryError
def parse_instant_text(text: str) -> datetime: ...                    # CLI: ^[0-9]+$ epoch or RFC 3339 Z/+00:00
def to_calendars(raw: Sequence[RawCalendar]) -> list[CalendarInfo]: ...

# _api.py
ACCESS_TIMEOUT_S: Final = 60.0
class QueryResult(NamedTuple): events: list[Event]; skipped: int       # skipped = rows dropped by R3
def query_events(get_source: Callable[[], EventSource], start: datetime | int, end: datetime | int, *,
                 calendars: Sequence[str] | None, include_notes: bool, prompt: bool) -> QueryResult: ...
def query_calendars(get_source: Callable[[], EventSource], *, prompt: bool) -> list[CalendarInfo]: ...
def authorization_status(get_source: Callable[[], EventSource]) -> AccessStatus: ...
def request_access(get_source: Callable[[], EventSource], timeout: float) -> AccessStatus: ...

# __init__.py  (public; thin wrappers over _api with default_source())
def events_in_window(start: datetime | int, end: datetime | int, *, calendars: Sequence[str] | None = None,
                     include_notes: bool = False, prompt: bool = True) -> list[Event]: ...
def list_calendars(*, prompt: bool = True) -> list[CalendarInfo]: ...
def authorization_status() -> AccessStatus: ...
def request_access(timeout: float = 60.0) -> AccessStatus: ...
```

**Overlap rule:** `ev_start < w_end and ev_end > w_start`, plus the zero-duration case `ev_start == ev_end and w_start <= ev_start < w_end`. A Python filter can only remove rows, so completeness depends on the queried range being a superset of the window, which `query_range` guarantees by widening ±1 day (R13): date-anchored all-day and floating events can shift by up to a day relative to a UTC window.

### Architecture Decisions
- **Adapter returns plain `Raw*` records (chosen) vs mapping over PyObjC objects (rejected).** B gives each piece of state one owner (EventKit facts in `_eventkit`, decisions in `_mapping`, waiting in `_access`), makes fakes trivial, and keeps ObjC out of the public surface. The adapter is not branch-free: its remaining branches (store lifetime, calendar-id resolution, timeout path) are unit-tested against an injected stub `EventKitNamespace`, and only the PyObjC getter calls are left to the live smoke test.
- **Return declined/canceled, never filter:** the consumer has context we lack (it may have attended a declined meeting).
- **CLI subprocess is the cross-repo contract (user override, 2026-11-19).** Consumers depend on a versioned JSON document plus exit codes, not on Python types. That means koda never needs PyObjC in its environment, a crash or hang in EventKit can't take koda down, and internals can change freely within `schema_version` 1. The cost is ~100–200 ms startup per call, which is fine for once-per-session use.
- **Separate rows per calendar:** the library never merges duplicates. `external_id` is exposed, and consumers dedupe on `(external_id, occurrence_start)` when `external_id` is non-null.
- **macOS 14+ only, by feature detection:** one permission API, no deprecated code path, nothing untested.
- **Reject rather than chunk over-cap windows** (subtract before you add; no observed need).
- **Prompting:** the library defaults to `prompt=True` for interactive Python users. The CLI prompts only with `--prompt`, because its main caller is a non-interactive subprocess with a 10 s timeout, and a prompt that can wait 60 s would guarantee a timeout under launchd.
- **UTC-only boundary (user override, extended in round 2):** input (epoch seconds or RFC 3339 UTC) and output (`…Z` plus `_ts` epochs) are UTC, so goldens are byte-stable on any machine, the library never needs the consumer's time zone, and no zone-name lookup can fail.
- **Open enums:** Apple adds EventKit enum values (e.g. `FullAccess`/`WriteOnly` in macOS 14); open enums keep such additions within v1.
- **Fresh store after grant, never `reset`:** safe whichever way Phase 0's store comparison comes out, and it keeps `reset` on the banned list.
- **`notes` opt-in:** notes often carry dial-in codes and passcodes. koda passes `--include-notes` when it wants them for meeting matching.
- **Schemas as package data:** one copy, readable by installed consumers and by tests.
- **Single owner for widening:** `_api` widens via `_mapping.query_range`, and the adapter queries exactly what it's given, so the range can't be widened twice past EventKit's span.
- **Getter-only adapter:** epoch floats, local components and raw ints cross the boundary; every conversion is a pure `_mapping` function tested in CI.
- **One type checker (mypy strict):** pyright would duplicate the gate.

### Dependencies
- Runtime: `pyobjc-framework-EventKit>=13; sys_platform == 'darwin'` (brings `pyobjc-core`, `pyobjc-framework-Cocoa`, which includes AppKit for `NSColor`).
- Dev: `pytest`, `ruff`, `mypy`, `jsonschema[format-nongpl]`, `types-jsonschema`.
- No other runtime deps (stdlib `argparse`, `json`, `zoneinfo`, `dataclasses`, `threading`, `importlib.resources`).

### Integration Seams

| Seam | Writer (task) | Caller (task) | Contract |
|------|---------------|---------------|----------|
| `EventSource` protocol / `Raw*` records | `_eventkit.py` (P4), `tests/fakes.py` (P3) | `_api.py` (P3) | No ObjC objects; timestamps as raw epoch floats, plus local components for all-day events (normalized in `_mapping`); nil → `None`; enum and authorization fields are raw EventKit ints; `color_rgb` sRGB floats or `None`; `events()` queries exactly the given range; `calendar_ids=None` means all calendars, and a non-None list resolving to no calendars returns `[]` without querying |
| Access wait | `_access.py` (P3) | `_eventkit.py` (P4) | Returns a raw status int within `timeout`, whether or not the completion fires; the waiter is injectable (run-loop seam) |
| Access gate | `_api.py` (P3) | `__init__` (P4), `cli.py` (P5a) | Raises `CalendarAccessError(status)` unless `full_access`; requests at most once per call, and only when `prompt=True`; timeout `ACCESS_TIMEOUT_S = 60.0` |
| JSON schema v1 | `models.py` + `src/macos_calendar_events/schema/*.json` (P2) | CLI (P5a), koda-pipecat (external) | Keys always present; RFC 3339 whole-second datetimes; UTF-8, `ensure_ascii=False`, sorted keys; additive-only within v1, open enums; `schema_version` bumps on any breaking change (R18) |
| Launchd grant run | consumer's launchd job (koda, external) or the README's one-shot job (P6) | `cli.py` (P5a): `calendars --prompt` | Runs `calendars --prompt` once from the context that will run the CLI. Needs a GUI session and a timeout of at least 70 s. Exit 0 = granted, 3 = denied or no prompt. The grant belongs to the job's executable, which must be stable (no `uv run` or shell wrapper). The normal run never prompts |
| CLI subprocess | `cli.py` (P5a) | koda-pipecat (external) | `--start`/`--end` as epoch seconds or RFC 3339 UTC; `schema` subcommand; invoked by absolute path (`uv tool install …@v0.1.0`; `KODA_CALENDAR_CLI`); args per R7; stdout validates against v1 schema; exit codes per R11; stdout empty on error; consumer applies timeout and treats any failure as "no hints" |

## Testing Notes

### Test Approach
- **Unit (CI + local):** Phases 1–5, through public or seam functions with `FakeSource`, injected requesters, or a stub store. Expected values come from the requirements, not from running the code. The single exception is the generated, hand-reviewed goldens (R18).
- **Live (local, opt-in):** `MACOS_CALENDAR_EVENTS_LIVE=1 uv run pytest -m live`, after the live preflight. Integer-count assertions only.
- **Manual:** the Phase 0 spike (done); the Phase 5b reset, prompt and denied-path checks; the Phase 6 launchd, different-executable and cron checks and README walk-through.

### Edge Cases to Cover (each is mapped to a named test in its phase)

| Edge case | Covered in |
|-----------|------------|
| Recurring and detached occurrences | Phase 3 recurring |
| All-day, single and multi-day | Phase 3 all-day |
| DST boundaries | Phase 3 DST |
| Floating-time events | Phase 3 floating |
| Zero-duration events | Phase 3 overlap |
| Declined and canceled events | Phase 3 declined |
| Zero or several self rows | Phase 3 self rows |
| Attendee without email or name; organizer-only; room/resource participants | Phase 3 attendees |
| mailto variants | Phase 3 mailto |
| Nil title, identifier or external id | Phase 3 nulls |
| Same invite in two calendars | Phase 3 |
| Duplicate titles; id-vs-title collision; empty selector list | Phase 3 selection |
| Read-only calendars and color conversion | Phase 3 calendars |
| Unknown enum ints, including authorization | Phase 3 enum tables |
| TCC states and prompt outcomes, including timeout | Phase 3 access, Phase 4 adapter |
| Non-macOS and no-PyObjC import | Phase 1 import, ubuntu CI |
| macOS < 14 guard | Phase 4 platform guard |
| Over-cap window and padding past the cap | Phases 3 and 5a |
| Old absolute window and multi-week window | Phases 3 and 5a |
| ±1-day query widening and all-day events near edges | Phase 3 |
| Non-UTC or naive input; input grammar forms | Phases 3 and 5a |
| id collisions with nil identifiers | Phase 3 |
| Null `source_title` ordering | Phase 3 |
| mailto hfields and encoded commas | Phase 3 |
| Exit-code precedence (2 before 4, 4 before 5, 3 before 5) | Phase 5a |
| Epoch vs RFC 3339 input equivalence; negative/float epoch; `-00:00` | Phases 3 and 5a |
| Skipped nil-start/end/calendar rows | Phases 3 and 4 |
| `schema` subcommand and docs copies | Phases 2, 5a, 5b and 6 |
| Raising library during live smoke | Phase 4 |
| Organizer repeated in attendees; nil attendees, organizer or timeZone | Phases 3, 4 and 5a |
| Non-IANA zone names (`GMT+0530`); scheme-less participant URLs | Phase 3 |
| Non-ASCII output | Phases 2, 5a and 5b |
| Sub-second timestamps | Phase 2 |
| Zero events | Phase 3 empty |
| CLI as a child of a launchd-started parent | Phase 0 spike (same-executable shape); Phase 6 manual (CLI as the job, and as a child of a job with a different executable) |

## Risks & Open Questions

- **Risk: no TCC prompt from some terminals or from launchd.** *Phase 0: did not occur.* Prompts appeared from the terminal (Rex) and from a launchd job (attributed to `python3.12`). *Remaining mitigation:* worst case, a follow-up plan ships a minimal helper `.app`.
- **Risk: interpreter-keyed grants.** Under launchd, the grant belongs to the job's executable. In Phase 0 that executable and the CLI's interpreter were the same uv-managed `python3.12` realpath, so the run can't show which of the two holds the grant when they differ (koda's job executable is its own); Phase 6 checks this. A uv Python upgrade or reinstall changes that path, so access is lost (exit 3) until a re-grant. Conversely, every script that interpreter runs under launchd inherits Calendar access. *Mitigation:* the README documents both; it recommends pinning the exact Python patch at `uv tool install` time, re-granting after an interpreter change, and (optionally) a dedicated interpreter for the tool. koda treats exit 3 as "no hints" and surfaces a re-grant hint.
- **Risk: cron attribution is unmeasured.** Phase 0 covered a terminal and launchd. koda's scheduled jobs may run from cron, which has no GUI session and may get no prompt. *Mitigation:* the Phase 6 cron check; if cron can't be granted, the README says so and koda launches the CLI from launchd.
- **Risk: R13 cap above 3×365 days.** Phase 0 saw one unexplained row in a chunked union that a single 1460-day query lacked, and the range can't be re-found. *Mitigation:* the cap is 3×365 − 2 days and labelled unverified at larger spans; the opt-in live consistency check (Phase 4) re-tests it.
- **Risk: only macOS 26.6.2 was measured.** The macOS 14 floor rests on feature detection, not on a run on 14 or 15. CI covers the runner's version only.
- **Risk: shapes Phase 0 didn't observe.** A shared external id across calendars, detached occurrences, floating timed events and Exchange rows were all absent. The dedupe guidance stays provisional, and the live smoke counts these shapes on each run.
- **Open dependency (koda-pipecat repo, no tracking item here):** koda's one-shot `calendars --prompt` setup and its exit-3 handling are commitments in that repo. Track them there.
- **Risk: the completion handler never fires without a run loop.** *Phase 0: did not occur* (background-thread callback, no pump). `wait_for_access` still guarantees a bounded wait.
- **Risk: a store created before the grant returns empty results after it** (exit 0 with `[]` on first run). *Phase 0: did not occur* (the pre-grant store matched a fresh one). The D7 fresh store after a grant is kept as cheap insurance. Related: with `not_determined` and no prompt, EventKit silently returns 0 calendars and 0 events with no error, which is why the access gate (R9) must run before any read.
- **Risk: `calendarItemExternalIdentifier` instability** (it can change for some sources after sync, and differ across accounts). *Mitigation:* `id` is opaque and per-document; the dedupe guidance `(external_id, occurrence_start)` is provisional until Phase 0.
- **Risk: PyObjC/macOS version drift.** *Mitigation:* macOS 14 floor via feature detection, a tested PyObjC floor, CI on `macos-latest`, and a darwin-only test pinning EventKit constants.
- **Risk: contract drift between repos.** *Mitigation:* R18 schemas with format checking, schema-model sync tests, goldens, `schema_version` checked by koda.
- **Risk: privacy leaks through test or validation failures.** *Mitigation:* count-only live assertions, a value-free `validate_json.py`, `check_privacy.sh` in CI.
- **Open questions:** the R13 cap above 3×365 days (the unexplained Phase 0 row); cron and different-executable attribution (Phase 6 checks); the denied path and its System Settings recovery (Phase 5b). Round-2 decisions were resolved via `/grill` on 2026-11-19 (see Decisions). Phase 0 is done; run 4 of `/review-plan` produced the decisions at the end of Decisions.

## Decisions

- Decision (grilled): Notes are off by default (`include_notes=False`, CLI `--include-notes`). koda opts in when it needs notes for meeting matching. → R1, R3, Architecture Decisions.
- Decision (grilled): One invite in two calendars returns separate rows with distinct `id`s and a shared `external_id`. koda dedupes; the library never merges. → R3, Non-Goals, Architecture Decisions. *(Refined by D5 below.)*
- Decision (grilled): macOS 14 (Sonoma)+ only. The pre-14 `requestAccessToEntityType_completion_` path is dropped; minimum OS is stated in README and pyproject; Phases 0 and 4 test only the 14+ API. → R9, R11, R15, R19, Phases 0/1/4/6. *(Review note: no PyPI classifier expresses a macOS version, so R15 states the minimum in `description`/README and keeps generic classifiers; R19 enforces it at runtime by feature detection.)*
- Decision (grilled): Plans live in `docs/dev_plans/` (skein convention), so `/plan-view` and `/conduct` find them.
- Decision (grilled): Architecture override. koda-pipecat integrates via a **CLI subprocess**, not a library import. CLI + versioned JSON (`schema_version`) is the documented stable contract between repos; consumers call it with a timeout and treat any non-zero exit, timeout, or parse error as "no calendar hints". The Python API stays public but secondary (tests, in-process users). ~100–200 ms startup is acceptable. Phase 0 checks TCC attribution for a subprocess of a Terminal- or launchd-launched parent. Architecture gate confirmed by the user 2026-11-19 with this change. → Objective, Context, R7, R18, Architecture & Call Flow, Phases 0/2/5/6, Integration Seams.
- Decision (grilled): D1. Phase 0 reopens the CLI-subprocess architecture only if the launchd-parented CLI can't get full access via any documented user step, or the permission callback never fires even with the run loop pumped. Other Phase 0 results update Phases 2–4, followed by a fresh `/review-plan`. → Phase 0 exit checklist, Risks.
- Decision (grilled): D2 (user override). UTC everywhere at the contract boundary, input and output. CLI `--start`/`--end` accept only `Z`/`+00:00`; naive or non-UTC → exit 2 with a clear message (this supersedes "CLI naive = local"). The Python API rejects naive or non-zero-offset datetimes. All output instants are UTC `…Z`, whole seconds. koda converts to UTC before calling, and local presentation is the consumer's concern. `time_zone` stays informational; all-day events also carry `start_date`/`end_date` (exclusive end) computed in the adapter. → R3, R7, R12, R18, Review Focus, diagrams, Phases 0/2/3/4/5/6, type sketch, Acceptance. *(Round 2: the adapter only captures local components; the date arithmetic is the pure `_mapping.normalize_all_day`.)*
- Decision (grilled): D3. Enums are open within v1: strings with known values documented (`x-known-values`), consumers map unknown → `unknown`, `EventStatus` gains `UNKNOWN`; closed-enum tests are replaced by "every StrEnum value documented in schema". → R18, Phase 2, type sketch, seams.
- Decision (grilled): D4. The CLI prompts only with `--prompt`; `--no-prompt` is removed; the Python API keeps `prompt=True`; the README says to grant once via `macos-calendar-events calendars --prompt` in Terminal. → R7, diagrams, Phases 5/6, Architecture Decisions.
- Decision (grilled): D5. `id` is opaque and unique within a response. The documented dedupe key is `(external_id, occurrence_start)`, only when `external_id` is non-null, and it's provisional pending the Phase 0 cross-calendar check. → R3, Non-Goals, Phase 6, type sketch, Risks.
- Decision (grilled): D6. The adapter always queries ±1 day beyond the already-padded caller window, and the Python overlap filter trims, because all-day and floating events are date-anchored and DST or zone shifts can move them up to a day relative to a UTC window. The cap (3×365 − 2 days on the padded window, lowered from 4×365 − 2 in run 4) limits window **length**, not age: windows may be arbitrarily far in the past (e.g. a crashed cron reprocessing an old session with absolute UTC times). Tests cover an old absolute window and a multi-week window. → R13, diagrams, Phases 3/4/5, overlap rule. *(Round 2: the single widening owner is `_api` via `_mapping.query_range`; the adapter queries exactly the range it receives.)*
- Decision (grilled): D7. One cached source per process; lazy store; a fresh store after a request that returns full access; `reset` is never called. Phase 0 found a single store would also work; the rule stays as insurance (see Decision (Phase 0), D7). → R10, Phases 1/4, Architecture Decisions.
- Decision (grilled): D8. Goldens are generated by `scripts/regen_goldens.py`, hand-reviewed, with a CHANGELOG line on change. This is stated as the single exception; Phase 2's hand-written expected values remain the independent check. → R18, Phases 1/5a/5b, Testing Notes.
- Decision (grilled): D9. Install via `uv tool install git+https://github.com/vr000m/macos-calendar-events@v0.1.0`. koda reads the absolute path from config/env (e.g. `KODA_CALENDAR_CLI`, default `~/.local/bin/macos-calendar-events`), and `FileNotFoundError` → no hints. launchd's PATH lacks `~/.local/bin`. → R18, Phase 6, seams.
- Decision (grilled): R2-4. Phase 0 (human-run spike) runs now, before the final review. Measurements go to `## Findings` below the marker; the contract and `## Decisions` are edited only when a result forces it; then one `/review-plan` runs before `/conduct`. → Phase 0 exit checklist.
- Decision (grilled): R2-3. Events missing `start`, `end`, `calendar.id` (or `occurrence_start`, which falls back to `start`) are skipped, and skips are counted in Phase 0 and the live smoke. `calendar.title` is nullable now. → R2, R3, type sketch, Phases 0/3/4.
- Decision (grilled): R2-2. `macos-calendar-events schema {window-v1|calendars-v1}` prints the packaged schema, and all v1 fields are required. Copies are also published at `docs/schema/window-v1.schema.json` and `docs/schema/calendars-v1.schema.json` for other coding agents and consumers. The packaged copy under `src/` is the single source of truth; `scripts/sync_schemas.py` refreshes the docs copies, and a test asserts they're byte-identical. The README links `docs/schema/`. → R7, R18, Phases 2/5/6, Files.
- Decision (grilled): R2-1. The privacy scan covers `git ls-files --cached --others --exclude-standard`, skips paths missing from the worktree, and has no exclusion list; local scratch must be gitignored. → R16, Phase 1.
- Decision (grilled): Q-a (user override/extension). CLI `--start`/`--end` accept either a non-negative integer of Unix epoch seconds or RFC 3339 ending `Z`/`+00:00`. Everything else (`-00:00`, naive, other offsets, floats, negative epochs) → exit 2. koda sends epoch seconds. The Python API accepts an `int` epoch or a tz-aware UTC `datetime`, rejecting naive or non-zero offsets. Output: every instant also gets a required integer epoch field (`start_ts`, `end_ts`, `occurrence_start_ts`, and the echoed padded window's `start_ts`/`end_ts`). → R7, R12, R18, schemas, type sketch, goldens, Phases 2/3/5/6, README.
- Decision (grilled): Q-b. `uv tool install --force .` is a user-run manual step; the automated Phase 6 check keeps the build plus the wheel content/metadata checks. → Phase 6.
- Decision (grilled): pre-1970 input. Instants before `1970-01-01T00:00:00Z` are rejected in both input forms (negative epoch, earlier RFC 3339 string, or earlier `datetime`) with exit 2 or `InvalidQueryError`. Output `_ts` may still be negative, with no schema minimum. → R12, Phases 3/5.
- Decision (grilled): schema `$id`. It is the tag-pinned raw URL of the published docs copy (`https://raw.githubusercontent.com/vr000m/macos-calendar-events/v0.1.0/docs/schema/{window,calendars}-v1.schema.json`). It won't resolve until the PRs merge and `v0.1.0` is tagged, which is expected. Phase 6 adds a post-tag user-run check that the URLs resolve and match the packaged schemas. → R18, Phase 6.
- Decision (grilled): versioned copies. The README tells consumers and coding agents to use the `docs/schema/` copy at the tag matching their installed CLI (or `macos-calendar-events schema`). After release, koda may rely on the pinned tag URL. → R18, Phase 6 README.
- Decision (Phase 0): grant context. TCC attributes access to the responsible process: the terminal app for terminal-launched processes, and the job's executable (the interpreter realpath) for launchd jobs and their children. A terminal grant doesn't carry over to launchd, and System Settings can't add apps manually. So the README's grant instructions say to grant once from the same context that will run the CLI; for launchd, that's a one-shot launchd recipe, or koda running `macos-calendar-events calendars --prompt` once from its own launchd job. This supersedes D4's "grant once … in Terminal" wording (D4's prompt-only-with-`--prompt` rule stands). → R9 remediation text, Phase 6 README and manual check.
- Decision (Phase 0): interpreter-keyed grants. A uv Python upgrade loses access, and any script run by the granted interpreter under launchd inherits it. This is documented as a risk; the README recommends pinning the exact Python patch at install and re-granting after interpreter changes. → Risks, Phase 6 README.
- Decision (Phase 0): run loop. The completion fired on a background thread without pumping, so the adapter uses the default `threading.Event.wait` waiter; the injectable seam stays for tests. → R9, Phase 4.
- Decision (Phase 0): D7 kept as is. The pre-grant store matched a fresh store (16 calendars / 62 events), so a single store would also work, but the fresh-store-after-grant rule stays as cheap insurance (no contract change).
- Decision (Phase 0): D1 reopen criteria checked, not triggered. A launchd-started CLI reached `full_access` via a prompt, and the callback fired. The CLI-subprocess architecture stands.
- Decision (run 4): cron. koda's scheduled jobs may run from cron, which Phase 0 did not measure. Cron stays in scope but is labelled unverified; Phase 6 adds a manual cron check, and if cron can't reach `full_access` the README says it is unsupported. → R9, Review Focus, Risks, Phase 6.
- Decision (run 4): R13 cap. The caller's padded window is capped at 3×365 − 2 days (was 4×365 − 2), because Phase 0's unexplained missing row at 1460 days can't be re-found. No new spike. An opt-in live consistency check (Phase 4) re-tests the cap. → R13, type sketch, Phases 3/4, Risks.
- Decision (run 4): Phase 5 split. Phase 5 becomes 5a (CLI, goldens generator) and 5b (contract tests, live validation). `/conduct` hands back after 5a, so the user hand-reviews and commits the goldens before 5b (R18). The Phase 0 heading became `### Spike 0`, so `/conduct --resume` no longer sees a ticked human-run phase. → Phases 5a/5b, Progress.
- Decision (run 4): padding order. The CLI validates raw `--start`/`--end`, then pads, then `_api` validates the padded window including the 1970 floor, so `--start 0 --pad-minutes 15` exits 2. → R12, Phase 5a.
- Decision (run 4): skip count. `_api.query_events` returns `QueryResult(events, skipped)`; public wrappers return `.events`; the live smoke reads `.skipped`. → R3, type sketch, Phase 4.
- Decision (run 4): schema `required` equals the dataclass fields plus the `_ts` siblings that `to_dict` adds. → Phase 2.

## Acceptance Criteria

- **R1, R3–R6, R8:** the Phase 3 named tests in `tests/test_window_query.py`, `tests/test_calendar_selection.py` and `tests/test_mailto.py` pass, and so does `tests/test_public_api.py` (Phase 4).
- **R2:** the Phase 3 calendars tests and `tests/test_public_api.py` pass, and the live smoke shows `list_calendars()` is non-empty.
- **R7, R11 (exit codes 0–5, empty stdout on error, one stderr line for 1/3/4/5) and R12 (UTC-only input as epoch seconds or RFC 3339 `Z`/`+00:00` in the CLI and API; `Z` strings plus `_ts` epochs in output):** pass in `tests/test_cli.py` and `tests/test_cli_contract.py`, including real-subprocess cases.
- **R9:** `tests/test_access.py` (gate outcomes and the grant/deny/timeout wait) `tests/test_eventkit_adapter.py` and `tests/test_public_api.py` pass. On the Mac, the Phase 5b manual reset → `request_access()` run, including the denied path, is recorded in Findings.
- **R10 and R14:** `bash scripts/check_readonly.sh` passes, and `tests/test_check_scripts.py` proves it fails on seeded violations and on an unreadable path.
- **R13:** the cap boundary, old-absolute-window, multi-week and ±1-day widening tests (Phase 3) and the CLI over-cap, padding, old-window and multi-week tests (Phase 5a) pass.
- **R14:** `tests/test_import.py` passes, and the ubuntu CI job is green.
- **R16:** `bash scripts/check_privacy.sh` passes in CI, the sentinel test in `tests/test_validate_json.py` passes, and the live smoke prints counts only.
- **R17:** CI is green on macOS (3.11, 3.13) and ubuntu (3.12) for the pushed branch.
- **R18:** `tests/test_schemas.py`, `tests/test_schema_copies.py` and `tests/test_cli_contract.py` pass (including `schema` subcommand byte-equality and epoch/RFC 3339 input equivalence) (format checking, schema-model sync, goldens), and the Phase 5b validation command validates live CLI output against both packaged schemas on the Mac.
- **R19:** `tests/test_platform_guard.py` passes.
- **R9 and R18 under launchd:** the Phase 6 launchd grant recipe and launchd run each exit 0 with schema-valid stdout, and the different-executable and cron checks are recorded in Findings. A failure in those two checks updates R9 and the README rather than blocking the release; a failure in the first two blocks it.
- README commands are executed verbatim on the Mac, except `tccutil reset` and the pinned-tag install (which gets its own post-tag check).
- **R15:** the Phase 6 validation command proves the built wheel runs `--version`, contains `py.typed` and both schemas, and its `METADATA` carries `License-Expression: BSD-2-Clause`, `Requires-Python: >=3.11` and the darwin-only PyObjC requirement.

<!-- reviewed: 2026-11-20 @ 2ce6b3ccc4691a4678bfb9a7068dc13e5676be42 -->

<!-- /review-plan writes the marker line above. Everything below is the workspace: edits here do NOT invalidate the marker. -->

## Progress

- Spike 0 (EventKit and TCC): done 2026-11-19; findings below. This line is deliberately not a checkbox, so `/conduct` doesn't parse it as a phase.
- Do not tick Phases 1–6 by hand during a `/conduct` run. The conductor tracks them, and manual ticks shift its phase index. Leave them unticked until the run completes.
- [ ] Phase 1: Scaffold, tooling, CI
- [ ] Phase 2: Domain types, JSON serialization and schemas
- [ ] Phase 3: Pure core against a fake source
- [ ] Phase 4: EventKit adapter, platform gate and public API wiring
- [ ] Phase 5a: CLI and golden generator
- [ ] Phase 5b: Contract tests and live validation
- [ ] Phase 6: Docs and release readiness

## Findings

### Spike 0: EventKit and TCC spike (run 2026-11-19 by the user; counts and shapes only)

Source: the spike script is recoverable at commit `3f27a1f` (`git show 3f27a1f:scripts/spike_eventkit.py`); it was deleted in `7f12955`. Only the summarized counts below were kept; raw output was not saved.

**Environment**
- macOS 26.6.2, arm64; PyObjC 13.0; Python 3.12.7 (uv-managed; realpath `~/.local/share/uv/python/cpython-3.12.7-macos-aarch64-none/bin/python3.12`).
- The user's terminal is Rex (`TERM_PROGRAM=rex`, bundle `Rex Server.app`). The run labelled `iterm` was also Rex, already granted, so it isn't a separate-app data point. VS Code wasn't run.
- **Timing (R18 budget):**
  - `import EventKit` ≈ 0.05 s; interpreter start to import done ≈ 0.09 s; `uv run --with … --import-only` total ≈ 0.44 s.
  - Cold store creation ≈ 0 ms; cold store + ±15-min query ≈ 4–20 ms; ±7-day query ≈ 2–5 ms (warm the same).
  - First launch of a freshly installed `uv tool` entry point: import ≈ 0.73 s, child total ≈ 1.6 s (bytecode compile on first run).
  - The suggested 10 s consumer timeout is confirmed, with a wide margin.

**Permissions and attribution**
- **Terminal (Rex):** `not_determined` → prompt shown → granted → `full_access`. The callback arrived on a background thread via `threading.Event.wait` **without a run loop** in ≈ 3.0 s (including the click).
- **Child of a terminal-started Python parent:** the responsible process is `Rex Server.app`; it inherited the Rex grant; exit 0; empty stderr.
- **launchd-started parent → child Python (no terminal ancestor):** the responsible process is the launchd job's executable (`python3.12`; `responsible_is_self` true for the job's process). Rex's grant **did not carry over** (`not_determined`).
  - Without `--prompt`, reads returned **0 calendars / 0 events silently**, with no exception and no stderr.
  - With `--prompt`, a prompt appeared and was granted in ≈ 2.4 s, with the callback again without a run loop.
- **launchd → `uv tool`-installed entry point (koda's shape):** already `full_access`. The tool venv's Python resolves to the same uv-managed interpreter realpath as the launchd job's executable, so the grant is keyed to the interpreter binary, not to the script or tool name. The child's responsible process was the launchd job's `python3.12`.
- **System Settings → Privacy & Security → Calendars:** two entries, `python3.12` (Full Access) and `Rex Server` (Full Access). There's **no "+" button**, so manual add isn't possible; the only way to grant is the prompt.
- **Framework stderr (R11):** 0 bytes on every path measured: import, status, `not_determined` reads, access request, all queries. The denied path wasn't exercised.
- **Store lifetime:** the store created before the first-time grant returned the same counts as a fresh store (16 calendars, 62 events in ±7 days) in both the terminal and launchd grants.
- **D1 reopen criteria: not triggered.** The launchd-started CLI reached `full_access` via a documented user step (a prompt from the launchd context), and the callback fires without pumping.
- **Harness note:** the first launchd attempt exited 78 (EX_CONFIG) because the plist pointed at an ephemeral `uv run --with` interpreter (`~/.cache/uv/builds-v0/.tmp…`, deleted on exit). That was a test-harness bug, not a result; the spike was fixed to use a persistent venv before the recorded launchd runs.

**Calendars and sources**
- 16 calendars:
  - calendar types: 14 CalDAV (1), 1 subscription (3), 1 birthday (4);
  - source types: 14 CalDAV (2), 1 subscribed (4), 1 birthdays (5).
- 20 store sources (18 CalDAV, 1 subscribed, 1 birthdays). No nil calendar title, id or source.
- `delegateSources`: 15 (all CalDAV), all 15 already among the default store's sources.
- Colors: 16/16 in Device RGB (model 1), and 16/16 converted to sRGB hex with the declared dependencies.

**Shapes (212 events, now ±30 days; system zone IANA-like)**
- **Nil counts:** `organizer` 173, `timeZone` 34 (exactly the all-day events). Zero nils for external id, title, `eventIdentifier`, `occurrenceDate`, `event.calendar`, `calendar.title`, `calendar.calendarIdentifier`, source title, `startDate`, `endDate`, participant `URL` and participant `name`.
- **R3 skip candidates:** 0.
- **`id` base key:** 212 distinct, 0 collisions.
- **`eventIdentifier`:** 11 identifiers shared by 112 rows (recurring occurrences share it), which confirms that `eventIdentifier` alone isn't unique per row. No detached occurrences in the window.
- **Recurrence:** recurring 127 and non-recurring 85, with `isDetached` false for all. 26 recurring series, each with one external id.
- **Cross-calendar external id:** **not observed** (111 external ids, 0 in 2+ calendars). `(external_id, occurrence_start)` collisions: 0. The provisional dedupe guidance holds and stays a consumer rule.
- **Time zones:**
  - 174 IANA-like, 4 GMT-offset style (all 4 rejected by `zoneinfo`), 34 nil (all-day);
  - 0 floating timed events.
  - This confirms `time_zone` must stay a raw informational string.
- **All-day (34):**
  - every one has nil `timeZone`, local start `00:00:00` and local end `23:59:59` (inclusive);
  - UTC start offsets 7 h (11) and 8 h (23), i.e. anchored to the system zone;
  - durations 1 d (27), 2 d (1), 3 d (4), plus 1.0417 d (1) and 4.0417 d (1), each one hour longer from crossing the DST fall-back;
  - local end − start dates: 0 (28), 1 (1), 2 (4), 3 (1).
  - This matches `normalize_all_day`'s inclusive-end +1 s rule.
- **Participants:**
  - 55 attendees, all type 1 (person); roles 1/2/3 = 50/1/4; status 1/2/3/4 = 2/51/1/1;
  - URL schemes: `mailto` 82, no scheme 12 (non-mailto → `email=None`, `url` kept); no odd mailto shapes (query, percent-encoding, `//`, uppercase scheme).
- **Self attendee:** CalDAV events had exactly one `isCurrentUser` attendee in 39 cases and nil `attendees` in 156; subscribed (7) and birthdays (10) had nil `attendees`; never more than one. `organizer.isCurrentUser` was true 2 times.
- **Organizer in attendees:** the organizer also appeared in `attendees` in 11 events (now noted in R3; no dedupe).
- **Status and availability:** event status 0/1/3 = 42/169/1; availability −1/0/1 = 18/167/27 (availability isn't in the contract).

**Predicate edges (`predicateForEventsWithStartDate:endDate:calendars:`)**
- An event ending exactly at the window start was **included** by the narrow EventKit query (20/20), but excluded by the half-open overlap filter.
- Starting exactly at the window end: excluded (0/20).
- Zero-length at the window start: included (1/1); at the window end: excluded (1/1).
- So EventKit's predicate is inclusive at the start edge. The widen-then-filter design (R13) is required, not just defensive; the widened query contained every case.

**Four-year limit**
- Range = now − 730 d.
- The 1460-day query returned 4287 rows. The 1461-, 1462- and 1500-day queries returned the **same 4287 rows** (latest start at +1459.2 d), with no error. EventKit **silently truncates** longer spans, which confirms R13's raise-instead-of-truncate cap.
- Four 365-day queries summed to 4292 rows (union 4288 distinct, so 4 boundary-spanning events were counted twice). **1 row appeared in the union but not in the 1460-day query.**
  - Unexplained. It may be a row-identity artifact, or a sub-1460-day effective limit.
  - It matters only for windows near the cap (koda uses minutes), so there's no contract change. It's flagged for the final `/review-plan`.
- Query cost: about 0.22–0.28 s for 1460 days, 0.02–0.07 s per 365 days.

### Implementation run (emulated `/conduct`, 2026-11-20, agent-run while the user was away)

Phases are recorded in `.conduct/state-*.json` (`completed_phases`), not by ticking Progress. Commits are small, one logical unit each.

**Phase 1**
- `uv lock --check`: `/opt/homebrew/bin/uv` 0.13.9 → exit 0; `~/.local/bin/uv` 0.9.18 → exit 0 (both "Resolved 37 packages").
- Local env: `python3` and uv's default interpreter on this Mac are Homebrew 3.15, so `.venv` was created with `uv venv --python 3.12.7` (the granted interpreter). Not a repo change; CI pins its own versions.
- Deviation: ruff ≥ 0.17 formats Python code blocks inside Markdown, and `ruff format --check .` failed on this plan's type sketch (deliberately compact, one-line classes). `[tool.ruff] extend-exclude = ["*.md"]` keeps the plan untouched; ruff still lints and formats every `.py` file.
- `check_readonly.sh` excludes dunder calls (`__init__(` etc.) from the selector-allowlist set, since they are not PyObjC selectors.
- `check_privacy.sh` allows RFC 2606 names: `example.com/.org/.net` and the reserved TLDs `.test`, `.example`, `.invalid`, `.localhost`, each including subdomains, plus `*.noreply.github.com`.
- Not done (user-run manual step): `git push -u origin feature/core-events-api && gh run watch --exit-status`. CI has therefore not run yet.

**Phase 2**
- `Participant` and `CalendarRef` also have `to_dict()` (the sketch lists it only on `CalendarInfo` and `Event`); they are used by `Event.to_dict`.
- Serializing a naive `datetime` raises `ValueError` (it can't happen via `_mapping`, which only produces aware UTC values).
- `_ts` values use `calendar.timegm`, so they agree with the truncated `…Z` string for pre-1970 instants too (`int(dt.timestamp())` would round toward zero and disagree for negative sub-second values).
- `CalendarAccessError`'s message is exactly the R9 remediation text; the status is on `.status`. `CalendarNotFoundError`'s message names only the unmatched selectors via `repr()`; available titles are on `.available_titles`.
- Schemas use `$defs` with `$ref` for each open enum, so the enum-parity test checks `$defs/<enum>` and that each field references it. RFC 2606 example addresses appear as literals in test fixtures (allowed by R16).

### Authoring self-review (2026-11-19, inline; not a `/review-plan` run)

This was an author-side pass over skein `review-plan`'s five lenses plus its contradiction pass, run inline by the author instead of in fresh-context agents. **It doesn't replace `/review-plan`. Run that before `/conduct`.** It doesn't write the review marker.

Fixed during the pass:
- *codebase-claims:* the license is **BSD-2-Clause**, not MIT, so it's now in R15 and the README. `requires-python` was raised to 3.11 to match PyObjC 13 (`>=3.11`).
- *assumptions:* "hidden calendars can be excluded" was false (EventKit has no visibility flag), so it moved to Non-Goals with a workaround. "External id is stable and unique" was false, so `id` now includes the calendar id plus an occurrence start, with an `event_identifier` fallback and a documented risk.
- *assumptions:* the 4-year predicate limit would silently truncate wide windows, so R13 now rejects them explicitly.
- *sequencing:* the TCC/run-loop unknowns could invalidate the adapter and CLI design, so they moved to a Phase 0 spike before the scaffold rather than being discovered in Phase 4.
- *spec-and-testing:* tests originally named internal helpers. They now drive `query_events` / `main(argv, source=)` and assert observable output and fake-recorded effects. Zero-duration and boundary overlap cases were added. The privacy rule for live tests is stated.
- *architecture:* two adapter shapes were compared and the plain-`Raw*` boundary was chosen. Only `_eventkit.py` imports PyObjC (R14), and the CLI has no logic of its own.
- *spec-and-testing (2nd pass):* the privacy acceptance check used `grep '@'`, which would match pytest decorators, so it's now an email-shaped regex excluding RFC 2606 domains.
- *contradiction pass:* the CLI's naive-datetime rule (local time) vs the library's (reject) is intentional and now stated in R12. Notes are listed in R3 but default-off, which is reconciled via `include_notes` and Q1.

Accepted / deferred: no window chunking; no helper `.app` (only if Phase 0 shows it's needed).

### Update 2026-11-19: grilled decisions applied

Q1–Q5 were resolved via skein `/grill` and woven into the contract above the marker (see `## Decisions`). Q5 changed the architecture: the CLI is now the cross-repo contract. The contract changed, so `/review-plan` must run before `/conduct`. The review marker is still the unfilled placeholder.

### Review Findings Addressed (`/review-plan` run 20261119T143424, plan hash 98ca668; applied 2026-11-19)

The review produced 82 findings: 2 Critical, 39 Important and 41 Minor, 14 of them contradictions. Numbers below are the `.findings` index + 1 in `.review-plan/latest-claude.json`.

- **63 findings were fixed**, wholly or in their mechanical part, above the marker.
- **19 findings were routed to 9 pending decisions** (D1–D9, under "Pending grill" below). Some findings were split between the two: the mechanical part was fixed and the policy part is pending.
- **0 were waived.**

Codebase claims were re-verified:
- `HEAD` is `feature/core-events-api`, past `main` @ `4568144`.
- `/opt/homebrew/bin/uv` is 0.13.9 and is first on the login-shell PATH; `~/.local/bin/uv` is 0.9.18. Both of #24 and #49 are correct.

| Finding(s) | Fix |
|---|---|
| #1 (Critical) | R10 + Phase 1: `grep -rnE`, strict exit codes (1 pass / 0 fail / other fail), selector allowlist `scripts/eventkit_selectors.allow`, self-tests in `tests/test_check_scripts.py` (seeded violation, unreadable path) |
| #2 (Critical) | R9 + `_access.wait_for_access` with an injected requester; grant/deny/no-callback tests (Phase 3); prompt → granted/denied/still-undetermined gate tests; adapter timeout test against a stub store (Phase 4); manual reset → `request_access()` step (Phase 5, user-run, last) |
| #5 | Live-command preflight (`authorization_status()` must be `full_access`, no prompt); the granting terminal is recorded in Phase 0 Findings |
| #6 (measurement part) | Phase 0 compares a pre-grant store with a fresh store. Policy → D7 |
| #7 | Phase 0 counts zone names `zoneinfo` rejects; `time_zone` documented as "IANA when available". Fallback → D2 |
| #8 | R3 nullability decided up front: `title`, `event_identifier`, `source_title` nullable; `occurrence_start` falls back to `start`; Phase 0 nil counts |
| #11 | R4 RFC 6068 rules; `tests/test_mailto.py` parametrized cases |
| #14 | Diagrams redrawn: `cli.py → _api.query_events(source or default_source())`, `__init__` and `default_source()` nodes, `_mapping` returns to `_api`, exit paths shown |
| #15, #77 | Manual reset/prompt step moved to Phase 5 (after `cli.py` exists), done via `request_access()`, run last with a re-grant; `tccutil reset` exempt from the Phase 6 verbatim rule |
| #19, #44, #51 | R11: exit 1 catch-all (class-only line), one-line rule scoped to 1/3/4/5, argparse usage allowed for 2, single stdout write, signal death outside CLI control |
| #20 | Schemas shipped as package data under `src/macos_calendar_events/schema/`; `--version` added to R7 |
| #21 (mechanical part) | Phase 0 marked human-run, with an exit checklist (Findings → Decisions → `/dev-plan update` + `/review-plan` if the contract changes). Reopen criteria → D1 |
| #22 | `types-jsonschema` in the Phase 1 dev group |
| #24, #49 | Context repo state rewritten as a dated snapshot; both uv binaries recorded; `[tool.uv] required-version = ">=0.9"` |
| #27 | Live smoke asserts integer counts; `validate_json.py` prints path + keyword only; sentinel test |
| #28, #37 | Authorization int mapped in `_mapping`; `EventKitSource(store_factory=…)` stub tests in CI; full int-table tests + darwin-only EventKit-constant test |
| #29, #61, #73 | Spike committed in Phase 0, deleted in Phase 1 (never linted; no exclude needed) |
| #30 | Every phase gate ends with the full CI command, spelled out literally, with phase-specific paths as a fast pre-check |
| #31 | `__init__.py` wiring moved to Phase 4; Phase 3 ships only `_api` functions |
| #32 | Stub `README.md` in Phase 1 with `readme = "README.md"` |
| #33, #42 | R2: `SourceType` enum, `color_hex` `#RRGGBB` sRGB (conversion failure → `None`), `read_only = not allowsContentModifications`, calendar ordering; Phase 3 calendar tests; Phase 0 color-space check |
| #34, #75 | Import test in a fresh subprocess with PyObjC modules blocked; ubuntu CI job; R14 import grep in `check_readonly.sh` |
| #35, #56, #62 | One extra: `jsonschema[format-nongpl]`; `FORMAT_CHECKER` in tests and `validate_json.py`; negative date tests |
| #36 (structural part) | `check_schema`, `required` == dataclass fields, wrong-type/missing-key negatives, extra-key positive. Enum-equality part → D3 |
| #38 (non-prompt parts) | `--include-notes`, repeated `--calendar`, unknown `--calendar` → 5, `--pad-minutes -1` → 2; zero-request test for the non-prompting form (exact flag per D4) |
| #39 (measurement part) | Phase 0 predicate-edge measurement. Widening policy → D6 |
| #40 | Edge-case table maps each case to a named test; floating, multi-day all-day, unknown ints, read-only calendar, empty result, launchd manual check added |
| #41 | `scripts/check_privacy.sh` (case-insensitive, all `git ls-files`, explicit exit codes) in CI and self-tested; AC reworded |
| #43 | Remediation text generic; non-goal: no responsible-app detection |
| #45 | `is_recurring = hasRecurrenceRules or isDetached`; Phase 0 cross-tab |
| #47 | R18: UTF-8, `ensure_ascii=False`; non-ASCII golden fixture |
| #48 | Data-reality line marked as an assumption; Phase 0 `delegateSources` check; conditional non-goal |
| #50 | Phase 0 `isCurrentUser` counts; rule: first `is_self` attendee, else `None`; tests |
| #52 | PyObjC floor raised to the tested `>=13` |
| #53 | R19 uses feature detection (`instancesRespondToSelector_`); `mac_ver` is informational only; guard tests via stub classes |
| #54 | Spike pinned to `--python 3.12`; versions and timing recorded |
| #55 | Phase 1 `_eventkit.py` stub proves the strict-mypy config early |
| #57 (shape part) | Whole seconds at the `Raw*` boundary, `timespec="seconds"`, sub-second test. Offset → D2 |
| #58 | `$schema`, `$id`, `schema_version: {const: 1}`; v2-document negative test |
| #59 | R15 and the decision note reconciled: generic classifiers; minimum OS in description/README; runtime enforcement |
| #65 | Type sketch declared the single source; R1/R2 now include `prompt` |
| #66 | Launcher and user actors added to the component graph |
| #67 | `uv.lock` in Phase 1 Impl files |
| #68 | Phase 1 validation: user-run push + `gh run watch --exit-status` |
| #70, #76 | `models.py` owns `SCHEMA_VERSION`, `window_to_json`, `calendars_to_json` and formatting; exact-text test in Phase 2 |
| #74 | Phase 1 notes the console-script entry precedes `cli.py`, accepted |
| #78 | R6: `calendars=[]` → `ValueError`; mixed valid/unknown raises; id beats title |
| #79 (CLI part) | Cap measured after padding; CLI over-cap and padding → exit 2. Exact boundary → D6 |
| #80 | R8 sort by instant; tie-at-each-level fixtures with mixed offsets |
| #81 | `if __name__ == "__main__": sys.exit(main())`; real-subprocess and console-script exit-code tests |
| #82 | Acceptance criteria per requirement, naming test files (R11–R13 added; R2/R7 re-pointed) |

### Pending grill: resolved 2026-11-19

D1–D9 from `/review-plan` run 20261119T143424 were grilled with the user on 2026-11-19 and applied above the marker as `Decision (grilled): D1…D9`. D2 was an override (UTC-only input and output); D6 was accepted with clarifications (rationale for the ±1-day widening; the cap limits length, not age). The others were accepted as recommended.

### Re-review required

**`/review-plan` must re-run before `/conduct`.** D2 changed the CLI and Python **input contract** (UTC-only `--start`/`--end`; non-UTC rejected with exit 2), which supersedes the earlier "naive = local" rule. D2, D3 and D6 also changed the output schema (`start_date`/`end_date`, open enums, `EventStatus.UNKNOWN`) and the query range. The review marker is intentionally left unfilled.

### Review Findings Addressed, round 2 (`/review-plan` run 20261119T155444, plan hash 3ced2e6; applied 2026-11-19)

The review produced 62 findings: 3 Critical, 30 Important and 29 Minor, 9 of them contradictions.
- **57 findings were fixed** above the marker, some only in their mechanical part.
- **5 findings were routed to decisions** (#8 nil policy, #11 privacy scan set, #14 schema delivery, #20 Phase 0 re-review, #58 required vs additive), plus the mechanical-remainder parts of #12, #27 and #59.
- Two decisions were carried over from the D-round report: Q-a (`-00:00`) and Q-b (`uv tool install` in the Phase 6 slot).
- **0 were waived.**

| Finding(s) | Fix |
|---|---|
| #1, #2 (Critical), #12 (literal part) | The address-shaped seed was removed from the plan. R16 now says no tracked file may hold a disallowed address literal, and seeds are built at runtime. A self-test runs `check_privacy.sh` over the real checkout. Scan set → R2-1 |
| #3 (Critical), #17, #34 | All-day arithmetic moved to the pure `_mapping.normalize_all_day`, fed by adapter-captured local components. The inclusive `23:59:59` end becomes +1 s (both `end` and `end_date` exclusive). Hand-written cases: single-day, three-day, inclusive end, LA DST day, Kolkata. Live-smoke counts for all-day and timed date nullness |
| #4, #7, #44 | `id` derivation stated above the marker (`_mapping.assign_ids`: hashed base key plus a deterministic ordinal suffix). Colliding nil-identifier fixture added. The detached-row test now asserts observable properties. Phase 0 counts base-key duplicates and `eventIdentifier` sharing |
| #5, #6 | `WindowEcho`/`WindowDocument`/`CalendarsDocument` added to the type sketch and R18. Envelope required-keys test; padded-window echo test; one golden uses padding |
| #9 | Phase 0 runs the launchd case through a `uv tool`-installed entry point by absolute path. The executable node was added to the component graph |
| #10, #13 | Single widening owner: `_api` via `_mapping.query_range`; the adapter queries exactly what it receives (R13, Phase 4, seams, D6 note). Stub test checks the predicate gets unmodified dates |
| #15, #46 | Phase 0 four-year-limit measurement (1460 vs 4×365, and 1462) |
| #16 | `EventKitNamespace` injection replaces `store_factory`. `default_source()`/`_clear_default_source()` are owned by `_eventkit.py` |
| #18 | Live smoke wraps calls, fails with the class name only (`from None`), counts schema errors via `iter_errors`; sentinel test |
| #19 | `wait_for_access(..., wait=threading.Event.wait)` injected waiter plus a fake-waiter test |
| #21 | Phase 1 push moved to a manual post-commit step. Phase 4/5 Validation cmd slots are now one backticked command with the preflight inlined (`set -o pipefail` in Phase 5) |
| #22, #54 | Phase 5 build order and `/conduct --pause-phase`. `tests/golden_fixtures.py` builders are named and loaded by path. `CHANGELOG.md` is in the Phase 5 Impl files |
| #23 | The launchd check moved to Phase 6, after `uv tool install --force .` |
| #24 | Null `source_title` sorts first; mixed-order fixture |
| #25 | Anchored R14 import pattern; seeded `import`/`from` negatives |
| #26, #61 | Distinct stderr tags per check. Denylist parametrized over all 10 alternatives in a non-`_eventkit.py` file. Stale-allowlist and unreadable-file (grep exit 2) cases |
| #27 (mechanical part) | Temp tree is a real git repo; near-miss and subdomain cases built at runtime; noreply → 0; non-repo → 2. Untracked case → R2-1 |
| #28 | Exact instant pattern stated; `2025-13-45T99:99:99Z` must fail with keyword `format`; fractional-second negative |
| #29 | R4: `to=` hfield rule, split before decoding, trimming; new mailto cases |
| #30 | `tests/test_public_api.py` (forwarding, defaults, return types, re-exports), cited in the R1/R2/R9 ACs |
| #31 | Darwin-only adapter conversion cases against real Foundation objects |
| #32 | Exit-4 tests (monkeypatched `default_source`, non-darwin subprocess); exit-1 sentinel test |
| #33 | Phase 6 Validation cmd checks wheel contents (`py.typed`, both schemas) and `METADATA` (license, Requires-Python, darwin marker); R15 AC added |
| #35 | Exit-5 line names unmatched selectors via `repr()` only; newline test |
| #36 | Input grammar regex plus `datetime.fromisoformat`; fractional seconds accepted and truncated; one test per form (`-00:00` → Q-a) |
| #37 | Diagrams: `request_access(ACCESS_TIMEOUT_S)` arrow, `models.py` node, serialization step. `_api.authorization_status`/`request_access` in the sketch |
| #38 | Schema-sync test names the five output enums and excludes `AccessStatus` |
| #39 | `RawParticipant`/`RawCalendar`/`RawEvent` enumerated in the sketch (private; Phase 0 may amend) |
| #40 | Empty-resolving `calendar_ids` → `[]` without querying (seam row plus adapter test) |
| #41 | R11 check order (2 → 4 → 3 → 5) via `get_source` laziness; non-darwin inverted-window test |
| #42 | `_api.ACCESS_TIMEOUT_S = 60.0` (R9, seam row, sketch) |
| #43, #56 | Dev-machine line rewritten: PATH order depends on the shell; `uv lock --check` with both binaries in Phase 1 |
| #45 | R11's one-line guarantee scoped to CLI-written lines; consumers don't parse stderr; Phase 0 records framework stderr |
| #47 | Phase 0 times store creation plus ±15-minute and ±7-day queries; the timeout is confirmed against it |
| #48 | Phase 0 System Settings manual-add check; R9 text and D1 reopen wording tied to it |
| #49 | R3 nullable list points to the type sketch and includes `organizer`/`self_status`; null-organizer schema case |
| #50 | Preflight scope stated (Phase 4 live smoke and Phase 5 Validation cmd only) |
| #51 | Phase 3 goal reworded (no `src/` PyObjC import; one darwin-only constants test) |
| #52, #60 | README verbatim rule exempts the pinned-tag install; post-tag user-run check added; AC updated |
| #53 | Phase 0 exit checklist: tick Progress, delete the spike in a second Phase 0 commit |
| #55 | `uv.lock` wording corrected (not yet present; committed in Phase 1) |
| #57 | `InvalidQueryError(ValueError)` is the only exit-2 `ValueError`; others → exit 1 |
| #59 (sequencing part) | Spike deletion is a second human-run Phase 0 commit. Scan-set part → R2-1 |
| #62 | `validate_json.py` empty and non-JSON stdin tests; `set -o pipefail` |

### Pending grill (round 2): resolved 2026-11-19

R2-1 to R2-4, Q-a and Q-b were grilled with the user on 2026-11-19 and applied above the marker as `Decision (grilled): …`. Q-a was an override/extension: the CLI and API accept epoch seconds or RFC 3339 UTC, and the output carries `_ts` epoch fields. R2-2 added published copies under `docs/schema/`. The others were accepted as recommended.

### Next step

**The user runs Phase 0 (the human-run EventKit/TCC spike) now**, recording measurements in `## Findings` (Phase 0) above, then runs one final `/review-plan`. `/conduct` starts only after that review, once its marker is written. The contract changed again in this update (input forms, `_ts` output fields, `schema` subcommand, `docs/schema/`, skip rule, privacy scan set), so the earlier markers wouldn't hold anyway.

## Issues & Solutions

## Final Results
