# macos-calendar-events

Query macOS Calendar through EventKit and get versioned JSON from a read-only CLI. It returns events that overlap a UTC time window, including attendee details. A meeting recorder can use those details as hints when identifying speakers. Ranking, matching or choosing "the" meeting is out of scope and belongs to the consumer.

## Quick start

Requires macOS 14 (Sonoma) or newer and Python 3.11 or newer. Install from PyPI with [uv](https://docs.astral.sh/uv/), which can fetch Python for you.

```sh
uv tool install --python 3.12.7 macos-calendar-events==0.1.0
macos-calendar-events --version
macos-calendar-events calendars --prompt
```

Click Allow when macOS asks for full Calendar access. Pin the Python patch version so scheduled jobs can keep using the same interpreter. Python 3.12.7 was tested for 0.1.0. See the [Calendar access guide] for launchd, cron, and exit `3`.

Query a one-hour UTC window across all calendars EventKit exposes. Replace the dates with the range you want to inspect.

```sh
macos-calendar-events window --start 2025-11-19T16:00:00Z --end 2025-11-19T17:00:00Z
```

Use `--calendar Work` to pick a calendar or `--pad-minutes 15` to extend both ends. The CLI only reads Calendar. It writes results to stdout, writes no files, sends no data over the network, and returns notes as `null` unless you pass `--include-notes`. Error messages carry no event or calendar content.

## Documentation

- [Calendar access guide] covers terminal, launchd and cron permissions, plus interpreter changes.
- [CLI reference] covers commands, query semantics, exit codes and limitations.
- [Integration guide] covers a schema-validated subprocess example and the public Python API.

For tools that consume JSON, the CLI and its JSON output are the stable contract. The Python API is also public but secondary. Print the schemas shipped with your installation using `macos-calendar-events schema window-v1` or `macos-calendar-events schema calendars-v1`. The 0.1.0 release includes [window-v1] and [calendars-v1] schemas.

## Release and license

[0.1.0 on PyPI] · [GitHub release] · [Changelog] · [BSD-2-Clause license]

[Calendar access guide]: https://github.com/vr000m/macos-calendar-events/blob/main/docs/calendar-access.md
[CLI reference]: https://github.com/vr000m/macos-calendar-events/blob/main/docs/cli.md
[Integration guide]: https://github.com/vr000m/macos-calendar-events/blob/main/docs/integration.md
[window-v1]: https://raw.githubusercontent.com/vr000m/macos-calendar-events/v0.1.0/docs/schema/window-v1.schema.json
[calendars-v1]: https://raw.githubusercontent.com/vr000m/macos-calendar-events/v0.1.0/docs/schema/calendars-v1.schema.json
[0.1.0 on PyPI]: https://pypi.org/project/macos-calendar-events/0.1.0/
[GitHub release]: https://github.com/vr000m/macos-calendar-events/releases/tag/v0.1.0
[Changelog]: https://github.com/vr000m/macos-calendar-events/blob/main/CHANGELOG.md
[BSD-2-Clause license]: https://github.com/vr000m/macos-calendar-events/blob/main/LICENSE
