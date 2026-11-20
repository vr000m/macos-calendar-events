#!/usr/bin/env bash
# R16 guard: no real email addresses in the repository. Scans tracked files plus
# untracked, not-ignored files (git ls-files --cached --others --exclude-standard)
# in the git repository containing the current directory. Addresses on RFC 2606
# domains (example.com/.org/.net and their subdomains; .test/.example/.invalid/
# .localhost) and GitHub noreply addresses are allowed. Offending files are named,
# but the addresses themselves are never printed.
# Every listed path is scanned whatever its name (paths stay NUL-delimited end to end, so a
# newline in a name can't split it) and whatever its content (bytes are matched as text, so
# a NUL byte can't make grep skip the file as binary). Out of scope: addresses that are not
# plain ASCII bytes in the file (compressed, or UTF-16 encoded).
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

# The NUL-delimited listing can't live in a shell variable, so it goes through a temp file.
if ! listing="$(mktemp)"; then
    echo "[privacy-error] mktemp failed" >&2
    exit 2
fi
trap 'rm -f "$listing"' EXIT
if ! git ls-files -z --cached --others --exclude-standard > "$listing"; then
    echo "[privacy-error] git ls-files failed" >&2
    exit 2
fi
if ! LC_ALL=C sort -z -u -o "$listing" "$listing"; then
    echo "[privacy-error] sorting the file list failed" >&2
    exit 2
fi

fail=0
error=0
while IFS= read -r -d '' path; do
    [ -n "$path" ] || continue
    [ -f "$path" ] || continue # tracked but deleted from the worktree: skip
    shown="$(printf '%q' "$path")" # one line per message, even for a newline in the name
    # -a: binary content is scanned as text, never skipped. LC_ALL=C: byte semantics.
    # grep exit codes are read strictly: 0 match, 1 no match, anything else is an error
    # (e.g. an unreadable file) and must not pass as "clean".
    # "./": a path named "-" would otherwise make grep read stdin (the rest of the listing).
    found="$(LC_ALL=C grep -aohE -e "$email" -- "./$path" 2>/dev/null)"
    status=$?
    if [ "$status" -eq 1 ]; then
        continue
    elif [ "$status" -ne 0 ]; then
        echo "[privacy-error] $shown: could not be scanned (grep exit $status)" >&2
        error=1
        continue
    fi
    hits="$(printf '%s\n' "$found" | tr '[:upper:]' '[:lower:]' | LC_ALL=C grep -cvE "$allowed")"
    if [ "${hits:-0}" -gt 0 ]; then
        echo "[privacy] $shown: $hits disallowed address-shaped string(s)" >&2
        fail=1
    fi
done < "$listing"

if [ "$error" -ne 0 ]; then
    exit 2
fi
exit "$fail"
