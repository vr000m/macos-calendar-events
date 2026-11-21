# Calendar access on macOS

Grant access from the context that will run `macos-calendar-events`. macOS privacy controls (TCC) record the grant for the responsible process. In a terminal, that's the terminal app. Under launchd, it's the job's executable. The CLI can request access only when you pass `--prompt`. A query without access exits `3`.

## Terminal

Run this from the terminal app you intend to use. Click Allow when macOS asks for full Calendar access.

```sh
macos-calendar-events calendars --prompt
```

## A program running under launchd

Run `macos-calendar-events calendars --prompt` once as a child of the same launchd job that will query Calendar. Use the job's intended executable directly in its configuration. A shell or `uv run` wrapper can make macOS attribute the grant to a shared or temporary executable.

Do the setup in a logged-in GUI session (`gui/$(id -u)`) and allow at least 70 seconds for the call. The CLI can wait up to 60 seconds for the prompt. Exit `0` confirms access. Exit `3` means full access is unavailable, including when the prompt is denied or cannot be shown. Use a shorter timeout for routine [subprocess calls](integration.md#call-the-cli-from-another-program).

## Standalone launchd or cron

A one-shot LaunchAgent can grant access to the CLI's Python interpreter. The grant also covers cron jobs that run the CLI with that interpreter. Use the CLI's absolute path in job definitions. Find its directory with `uv tool dir --bin`. A typical location is `~/.local/bin`.

Save the following as `~/Library/LaunchAgents/local.macos-calendar-events.grant.plist`. Replace `/Users/yourname/.local/bin/macos-calendar-events` with the absolute path on your Mac.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.macos-calendar-events.grant</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/yourname/.local/bin/macos-calendar-events</string>
    <string>calendars</string>
    <string>--prompt</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
```

Load the job in your GUI session and click Allow. Once the prompt is complete, unload the job. The grant persists.

```sh
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/local.macos-calendar-events.grant.plist
# Click Allow before running the next command.
launchctl bootout "gui/$(id -u)/local.macos-calendar-events.grant"
```

### cron

Use absolute paths in crontab entries because cron runs with a minimal environment. This example lists calendars every 15 minutes and saves output and diagnostics separately.

```crontab
*/15 * * * * /Users/yourname/.local/bin/macos-calendar-events calendars > /Users/yourname/calendars.json 2>> /Users/yourname/calendars.err
```

## Interpreter changes

For a Python executable running under launchd or cron, macOS keys the grant to the interpreter's real path. A different Python version, upgrade, or reinstall can change that path. Pin an exact Python version when installing the CLI with uv and repeat the grant for the appropriate executable if the path changes.

To resolve the Python interpreter used by a uv tool install:

```sh
readlink -f "$(uv tool dir)/macos-calendar-events/bin/python"
```

System Settings lists the interpreter by binary name, such as `python3.12`. Any script that runs under launchd or cron with that granted interpreter can use its Calendar access.

## Troubleshooting exit 3

- Check **System Settings → Privacy & Security → Calendars** for the terminal app or interpreter that ran the grant. Settings can toggle an existing entry. Run a query with `--prompt` to request a new grant.
- If a terminal command succeeds and a job exits `3`, run the permission setup from the job's context.
- If a grant arrives after a request times out, rerun the command to create a fresh EventKit store.
- To clear a terminal app's Calendar decision during development, run `tccutil reset Calendar <bundle-id>` with the app's bundle ID. Omitting the bundle ID clears Calendar grants for every app.
