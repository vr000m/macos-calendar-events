#!/usr/bin/env bash
# R10 / R14 guard: no EventKit write APIs, an exact PyObjC selector allowlist, and
# PyObjC imports confined to _eventkit.py. Run from anywhere; paths resolve from
# this script's location. Exit 0 = clean, non-zero = a check failed.
# Each failing check prints a distinct tag: [denylist] [allowlist] [imports] [grep-error].
set -u

root="$(cd "$(dirname "$0")/.." && pwd)"
src="$root/src"
adapter="$src/macos_calendar_events/_eventkit.py"
allow="$root/scripts/eventkit_selectors.allow"
fail=0

if [ ! -d "$src" ]; then
    echo "[grep-error] src/ directory not found" >&2
    exit 2
fi

# grep exit codes: 0 = match (violation), 1 = no match (pass), anything else = error.
run_grep() { # tag description pattern [extra grep args...]
    local tag="$1" what="$2" pattern="$3"
    shift 3
    local out rc
    out="$(grep -rnE --include='*.py' "$@" -e "$pattern" "$src" 2>&1)"
    rc=$?
    case "$rc" in
        0) echo "[$tag] $what:" >&2; echo "$out" >&2; fail=1 ;;
        1) ;;
        *) echo "[grep-error] grep exited $rc during the $tag check:" >&2; echo "$out" >&2; fail=1 ;;
    esac
}

deny='saveEvent|removeEvent|saveCalendar|removeCalendar|saveReminder|removeReminder|commit_?\(|requestWriteOnlyAccess|requestAccessToEntityType|\.reset\('
run_grep denylist "EventKit write/reset API referenced" "$deny"

imports='^[[:space:]]*(import|from)[[:space:]]+(EventKit|Foundation|AppKit|objc)([[:space:].]|$)'
run_grep imports "PyObjC imported outside _eventkit.py" "$imports" --exclude='_eventkit.py'

# Allowlist: PyObjC selector calls with arguments (identifiers ending in "_(") in the
# adapter must equal scripts/eventkit_selectors.allow exactly. Dunder calls are not selectors.
used=""
if [ -f "$adapter" ]; then
    used="$(grep -oE '[A-Za-z_][A-Za-z0-9_]*_\(' "$adapter" | sed 's/($//' | grep -vE '^__.*__$' | LC_ALL=C sort -u)"
fi
allowed=""
if [ -f "$allow" ]; then
    allowed="$(grep -vE '^[[:space:]]*(#|$)' "$allow" | sed 's/[[:space:]]*$//' | LC_ALL=C sort -u)"
fi
if [ "$used" != "$allowed" ]; then
    echo "[allowlist] selectors used in _eventkit.py differ from scripts/eventkit_selectors.allow:" >&2
    diff <(printf '%s\n' "$allowed") <(printf '%s\n' "$used") | grep -E '^[<>] .' | sed 's/^</  stale (allowed, unused):/; s/^>/  missing (used, not allowed):/' >&2
    fail=1
fi

exit "$fail"
