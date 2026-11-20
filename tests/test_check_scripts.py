"""R10/R14/R16: the guard scripts fail on seeded violations, with distinct tags.

Seed email addresses are assembled at runtime from parts, so no tracked file holds an
address-shaped literal (R16).
"""

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
AT = "@"

CLEAN_ADAPTER = '"""stub adapter"""\n\n\ndef load() -> None:\n    import EventKit  # noqa: F401\n'


def _git(tree: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(tree), *args], check=True, capture_output=True)


def _run(script: str, root: Path) -> subprocess.CompletedProcess[str]:
    """Run the temp tree's copy of a script with the tree as working directory."""
    return subprocess.run(
        ["bash", str(root / "scripts" / script)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


Tree = Callable[..., Path]


@pytest.fixture
def tree(tmp_path: Path) -> Tree:
    """Build a temp repo with copies of the scripts plus the given files, all git-added."""

    def make(files: dict[str, str] | None = None, *, allow: str = "", add: bool = True) -> Path:
        root = tmp_path / "repo"
        (root / "scripts").mkdir(parents=True)
        for name in ("check_readonly.sh", "check_privacy.sh"):
            shutil.copy(SCRIPTS / name, root / "scripts" / name)
        (root / "scripts" / "eventkit_selectors.allow").write_text(allow)
        pkg = root / "src" / "macos_calendar_events"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "_eventkit.py").write_text(CLEAN_ADAPTER)
        for rel, text in (files or {}).items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        _git(root, "init", "-q")
        if add:
            _git(root, "add", "-A")
        return root

    return make


# --- check_readonly.sh ---------------------------------------------------------------


def test_readonly_clean_tree_passes(tree: Tree) -> None:
    proc = _run("check_readonly.sh", tree())
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""


DENYLIST = [
    "store.saveEvent_span_error_(e, 0, None)",
    "store.removeEvent_span_error_(e, 0, None)",
    "store.saveCalendar_commit_error_(c, True, None)",
    "store.removeCalendar_commit_error_(c, True, None)",
    "store.saveReminder_commit_error_(r, True, None)",
    "store.removeReminder_commit_error_(r, True, None)",
    "store.commit_(None)",
    "store.requestWriteOnlyAccessToEventsWithCompletion_(cb)",
    "store.requestAccessToEntityType_completion_(0, cb)",
    "store.reset()",
]


@pytest.mark.parametrize("line", DENYLIST)
def test_readonly_denylist(tree: Tree, line: str) -> None:
    root = tree({"src/macos_calendar_events/other.py": f"def f(store, e, c, r, cb):\n    {line}\n"})
    proc = _run("check_readonly.sh", root)
    assert proc.returncode != 0
    assert "[denylist]" in proc.stderr


def test_readonly_selector_missing_from_allowlist(tree: Tree) -> None:
    adapter = (
        CLEAN_ADAPTER + "\n\ndef cals(store, ent):\n    return store.calendarsForEntityType_(ent)\n"
    )
    root = tree({"src/macos_calendar_events/_eventkit.py": adapter})
    proc = _run("check_readonly.sh", root)
    assert proc.returncode != 0
    assert "[allowlist]" in proc.stderr


def test_readonly_allowlisted_selector_passes(tree: Tree) -> None:
    adapter = (
        CLEAN_ADAPTER + "\n\ndef cals(store, ent):\n    return store.calendarsForEntityType_(ent)\n"
    )
    root = tree(
        {"src/macos_calendar_events/_eventkit.py": adapter}, allow="calendarsForEntityType_\n"
    )
    proc = _run("check_readonly.sh", root)
    assert proc.returncode == 0, proc.stderr


def test_readonly_stale_allowlist_entry(tree: Tree) -> None:
    root = tree(allow="calendarWithIdentifier_\n")
    proc = _run("check_readonly.sh", root)
    assert proc.returncode != 0
    assert "[allowlist]" in proc.stderr


@pytest.mark.parametrize(
    "line", ["import EventKit", "from EventKit import EKEventStore", "import objc"]
)
def test_readonly_pyobjc_import_outside_adapter(tree: Tree, line: str) -> None:
    root = tree({"src/macos_calendar_events/other.py": f"{line}\n"})
    proc = _run("check_readonly.sh", root)
    assert proc.returncode != 0
    assert "[imports]" in proc.stderr


def test_readonly_comment_mentioning_pyobjc_passes(tree: Tree) -> None:
    root = tree(
        {"src/macos_calendar_events/other.py": "# talks to pyobjc via _eventkit only\nX = 1\n"}
    )
    proc = _run("check_readonly.sh", root)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(
    os.geteuid() == 0 if hasattr(os, "geteuid") else True, reason="root can read 000 files"
)
def test_readonly_unreadable_file_is_grep_error(tree: Tree) -> None:
    root = tree({"src/macos_calendar_events/other.py": "X = 1\n"})
    target = root / "src/macos_calendar_events/other.py"
    target.chmod(0)
    try:
        proc = _run("check_readonly.sh", root)
    finally:
        target.chmod(0o644)
    assert proc.returncode != 0
    assert "[grep-error]" in proc.stderr


def test_readonly_missing_src_fails(tree: Tree) -> None:
    root = tree()
    shutil.rmtree(root / "src")
    proc = _run("check_readonly.sh", root)
    assert proc.returncode != 0


# --- check_privacy.sh ----------------------------------------------------------------


def _addr(local: str, domain: str) -> str:
    return local + AT + domain


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        (_addr("someone", "Corp." + "COM"), 1),  # non-RFC-2606, uppercase domain
        (_addr("someone", "examp" + "1e.com"), 1),  # look-alike of example.com
        (_addr("someone", "example.com" + ".evil.io"), 1),  # example.com as a prefix
        (_addr("someone", "mail." + "example.org"), 0),  # RFC 2606 subdomain
        (_addr("12345+someone", "users.noreply." + "github.com"), 0),  # GitHub noreply
    ],
)
def test_privacy_tracked_addresses(tree: Tree, address: str, expected: int) -> None:
    root = tree({"notes.txt": f"contact: {address}\n"})
    proc = _run("check_privacy.sh", root)
    assert proc.returncode == expected, proc.stderr
    if expected:
        assert "[privacy]" in proc.stderr
    assert address.lower() not in proc.stderr.lower()  # addresses are never echoed


def test_privacy_non_git_directory(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    proc = subprocess.run(
        ["bash", str(SCRIPTS / "check_privacy.sh")],
        cwd=plain,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2


def test_privacy_git_listing_failure_is_an_error_not_a_pass(tree: Tree, tmp_path: Path) -> None:
    root = tree()
    real_git = shutil.which("git")
    assert real_git is not None
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "git"
    shim.write_text(f'#!/bin/bash\n[ "$1" = "ls-files" ] && exit 128\nexec "{real_git}" "$@"\n')
    shim.chmod(0o755)
    proc = subprocess.run(
        ["bash", str(root / "scripts" / "check_privacy.sh")],
        cwd=root,
        env={**os.environ, "PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2, proc.stderr
    assert "[privacy-error]" in proc.stderr


def test_privacy_untracked_not_ignored_file(tree: Tree) -> None:
    root = tree()
    (root / "scratch.txt").write_text(_addr("someone", "corp" + ".com") + "\n")
    proc = _run("check_privacy.sh", root)
    assert proc.returncode == 1
    assert "[privacy]" in proc.stderr


def test_privacy_ignored_file_is_skipped(tree: Tree) -> None:
    root = tree({".gitignore": "scratch.txt\n"})
    (root / "scratch.txt").write_text(_addr("someone", "corp" + ".com") + "\n")
    proc = _run("check_privacy.sh", root)
    assert proc.returncode == 0, proc.stderr


def test_privacy_deleted_tracked_file_is_skipped(tree: Tree) -> None:
    root = tree({"gone.txt": _addr("someone", "corp" + ".com") + "\n"})
    (root / "gone.txt").unlink()
    proc = _run("check_privacy.sh", root)
    assert proc.returncode == 0, proc.stderr


def test_privacy_self_test_on_real_repository() -> None:
    proc = subprocess.run(
        ["bash", str(SCRIPTS / "check_privacy.sh")],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_readonly_self_test_on_real_repository() -> None:
    proc = subprocess.run(
        ["bash", str(SCRIPTS / "check_readonly.sh")],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
