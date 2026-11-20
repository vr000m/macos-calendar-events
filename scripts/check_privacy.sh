#!/usr/bin/env bash
# R16 guard: no real email addresses in the repository. Scans tracked files plus
# untracked, not-ignored files (git ls-files --cached --others --exclude-standard)
# in the git repository containing the current directory. Addresses on RFC 2606
# domains (example.com/.org/.net and their subdomains; .test/.example/.invalid/
# .localhost) and GitHub noreply addresses are allowed. Offending files are named,
# but the addresses themselves are never printed.
# Exit: 0 clean, 1 violation, 2 error (e.g. not a git repository, or a file that can't be
# read); an error wins over a violation.
set -u
# pipefail: a failing `git ls-files` must reach the error branch below, not be masked by `sort`.
set -o pipefail

if ! top="$(git rev-parse --show-toplevel 2>/dev/null)"; then
    echo "[privacy-error] not inside a git repository" >&2
    exit 2
fi
cd "$top" || exit 2

email='[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}'
allowed='@(([a-z0-9-]+\.)*example\.(com|org|net)|([a-z0-9-]+\.)*(test|example|invalid|localhost)|([a-z0-9-]+\.)*noreply\.github\.com)$'

if ! listing="$(git ls-files -z --cached --others --exclude-standard | tr '\0' '\n' | LC_ALL=C sort -u)"; then
    echo "[privacy-error] git ls-files failed" >&2
    exit 2
fi

fail=0
error=0
while IFS= read -r path; do
    [ -n "$path" ] || continue
    [ -f "$path" ] || continue # tracked but deleted from the worktree: skip
    # grep exit codes are read strictly: 0 match, 1 no match (or binary), anything else is
    # an error (e.g. an unreadable file) and must not pass as "clean".
    found="$(grep -IohE -e "$email" -- "$path" 2>/dev/null)"
    status=$?
    if [ "$status" -eq 1 ]; then
        continue
    elif [ "$status" -ne 0 ]; then
        echo "[privacy-error] $path: could not be scanned (grep exit $status)" >&2
        error=1
        continue
    fi
    hits="$(printf '%s\n' "$found" | tr '[:upper:]' '[:lower:]' | grep -cvE "$allowed")"
    if [ "${hits:-0}" -gt 0 ]; then
        echo "[privacy] $path: $hits disallowed address-shaped string(s)" >&2
        fail=1
    fi
done <<< "$listing"

if [ "$error" -ne 0 ]; then
    exit 2
fi
exit "$fail"
