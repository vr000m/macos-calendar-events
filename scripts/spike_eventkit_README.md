# Phase 0 EventKit/TCC spike: how to run it

This is a throwaway. It's committed with its findings, then deleted in a second Phase 0 commit (see the dev plan, Phase 0).

- **Privacy:** it records counts, booleans, enum ints, timings and shape categories only. It never records titles, names, emails, notes, URLs, locations, calendar titles or identifier values.
- **Read-only:** it only calls EventKit getters, predicate queries and the access request.
- **Output:** results go to `.spike/` (gitignored) as one JSON file per run.

Run everything from the repo root:

```sh
cd ~/Code/vr000m/macos-calendar-events
SPIKE=(uv run --python 3.12 --with 'pyobjc-framework-EventKit>=13' python scripts/spike_eventkit.py)
```

launchd runs need a **persistent** interpreter. `uv run --with` envs live under `~/.cache/uv/builds-v0/.tmp…` and are deleted when `uv run` exits, so make `.spike/venv` (gitignored) once:

```sh
"${SPIKE[@]}" --make-venv     # = uv venv --python 3.12 .spike/venv && uv pip install --python .spike/venv/bin/python 'pyobjc-framework-EventKit>=13'
```

Define this helper once in the same shell. It's used by steps 5 and 6:

```sh
# bounded wait: up to 180 s, then show the err log and launchd state (never hangs)
spike_wait() {
  local l=$1 i=0
  while (( i < 180 )); do
    if grep -q 'results written' ".spike/launchd/$l.out.log" 2>/dev/null; then cat ".spike/launchd/$l.out.log"; return 0; fi
    sleep 5; (( i += 5 ))
  done
  echo "timed out after 180s waiting for $l"
  cat ".spike/launchd/$l.err.log" 2>/dev/null
  launchctl print "gui/$UID/local.mce-spike.$l" 2>/dev/null | grep -E 'state|last exit'
  return 1
}
```

## 1. Timing (Terminal.app; no store, no prompt)

```sh
time "${SPIKE[@]}" --import-only
time .spike/venv/bin/python scripts/spike_eventkit.py --import-only
```

The first command includes `uv run` overhead. The second is the bare persistent-venv interpreter plus `import EventKit`.

## 2. Terminal.app, direct, with prompt

```sh
"${SPIKE[@]}" --label terminal --prompt --summary
```

A prompt should appear. Note **which app it names**, then click **Allow / Full Access**. The summary shows `status_initial` → `status_final`, `access_request.callback_delivered` (`threading_event_without_runloop`, `only_after_runloop_pump` or `never`), and `store_lifetime` (counts from the store created before the grant vs a fresh one).

This run also does the shape pass (±30 days; `--days-back/--days-forward` to change it), the predicate-edge probes, and the four-year probe.

If `status_initial` is already `full_access`, there's no first-time grant to measure. **Optionally** run `tccutil reset Calendar com.apple.Terminal`, which removes only Terminal's Calendar grant, then rerun step 2. To compare explicit run-loop pumping on a second fresh grant, add `--wait runloop` to that rerun.

## 3. Your usual terminal / VS Code (optional, one per app)

```sh
"${SPIKE[@]}" --label iterm --prompt --summary --skip-four-year      # or --label vscode, ghostty, ...
```

Note whether a prompt appears and which app it names.

**Denied-path stderr (optional):** in one of these apps, click **Don't Allow**, then rerun the same command without `--prompt`. That records the denied path and its stderr. You can re-enable the app later in System Settings.

## 4. Child of a Terminal-started Python parent

```sh
"${SPIKE[@]}" --as-parent --label terminal-parent --prompt --summary --skip-four-year
```

The parent never touches EventKit. It records the child's exit code (and the signal, if TCC kills it), the child's stderr shape, and the child's status and responsible-process attribution.

## 5. Child of a launchd-started parent

`--write-plist` uses `.spike/venv/bin/python`, and refuses an ephemeral `builds-v0` interpreter. The job runs **once** at load (no `KeepAlive`), so a failure never respawns. Old logs are cleared each time the plist is written.

```sh
# 5a: no prompt. Does Terminal's grant carry over? What does stderr show on the not_determined path?
"${SPIKE[@]}" --write-plist --label launchd-noprompt --skip-four-year
launchctl bootstrap gui/$UID .spike/launchd/local.mce-spike.launchd-noprompt.plist
spike_wait launchd-noprompt
launchctl bootout gui/$UID/local.mce-spike.launchd-noprompt

# 5b: with prompt. Can a prompt appear at all? If one does, note the app name and click Allow.
"${SPIKE[@]}" --write-plist --label launchd-prompt --prompt --skip-four-year
launchctl bootstrap gui/$UID .spike/launchd/local.mce-spike.launchd-prompt.plist
spike_wait launchd-prompt
launchctl bootout gui/$UID/local.mce-spike.launchd-prompt
```

## 6. launchd parent → `uv tool`-installed entry point (koda's real shape)

This step writes to `~/.local/bin`; you uninstall it in step 8.

```sh
"${SPIKE[@]}" --write-tool-pkg
uv tool install --python 3.12 .spike/toolpkg
"${SPIKE[@]}" --write-plist --label launchd-tool --prompt --skip-four-year --child-cmd "$HOME/.local/bin/mce-spike-probe"
launchctl bootstrap gui/$UID .spike/launchd/local.mce-spike.launchd-tool.plist
spike_wait launchd-tool
launchctl bootout gui/$UID/local.mce-spike.launchd-tool
```

If the launchd children didn't reach `full_access`, go to step 7. Check whether you can add the binary there (the tool's Python, which the results name). If you can, add it, then repeat 5a and 6 without `--prompt`.

## 7. System Settings (manual observation)

```sh
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars"
```

Note:
- which entries are listed (Terminal? python? the tool?);
- whether there's a **+** button to add an app or binary manually;
- whether a launcher that never prompted (a launchd child) shows up.

## 8. Cleanup

```sh
uv tool uninstall mce-spike-probe
launchctl print gui/$UID | grep mce-spike || echo "no spike agents loaded"
```

## What to send back

The JSON files stay in `.spike/` on this Mac, and the agent reads them from there. Just reply with:

1. which app each prompt named, or "no prompt", per step;
2. what you clicked;
3. the step 7 System Settings observations;
4. any crash dialog or killed process;
5. which steps you skipped.
