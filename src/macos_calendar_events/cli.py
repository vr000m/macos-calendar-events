"""``macos-calendar-events`` CLI: parse -> ``_api`` -> serialize -> exit code (R7, R11, R12).

Exit codes: 0 ok; 1 internal error; 2 usage/argument error; 3 calendar access not
granted; 4 EventKit unavailable; 5 calendar selector not found. On 1/3/4/5 the CLI
writes exactly one stderr line; stdout is written once, only after the output is built.
Every stdout write, ``--help`` and ``--version`` included, goes through ``_emit``: exit 0
only when every byte was written, else exit 1. A write that fails partway (for example a
full non-blocking pipe or a full disk) is undone when stdout is a regular file, which is cut
back to its length before the write; a pipe cannot take bytes back and can keep a prefix.
Stdout is valid only on exit 0.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import io
import os
import stat
import sys
from collections.abc import Callable, Sequence
from datetime import timedelta
from importlib.resources import files
from typing import Any

from . import __version__, _api, _eventkit, _mapping
from ._raw import EventSource
from .errors import (
    CalendarAccessError,
    CalendarNotFoundError,
    EventKitUnavailableError,
    InvalidQueryError,
)
from .models import SCHEMA_VERSION, calendars_to_json, window_to_json

PROG = "macos-calendar-events"
SCHEMA_NAMES = ("window-v1", "calendars-v1")

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_ACCESS = 3
EXIT_UNAVAILABLE = 4
EXIT_NOT_FOUND = 5


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Read-only macOS Calendar window queries as JSON (macOS 14+).",
        # No prefix matching: ``--pro``/``--i`` must not opt in to prompting or notes.
        allow_abbrev=False,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{PROG} {__version__} (schema_version {SCHEMA_VERSION})",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    window = sub.add_parser(
        "window", help="events overlapping [start, end) as JSON", allow_abbrev=False
    )
    window.add_argument("--start", required=True, help="epoch seconds or RFC 3339 UTC")
    window.add_argument("--end", required=True, help="epoch seconds or RFC 3339 UTC")
    window.add_argument(
        "--calendar",
        action="append",
        dest="calendars",
        metavar="ID_OR_TITLE",
        help="restrict to a calendar by id or title (repeatable)",
    )
    window.add_argument("--pad-minutes", type=int, default=0, metavar="N")
    window.add_argument("--include-notes", action="store_true")
    window.add_argument("--prompt", action="store_true", help="ask for Calendar access if needed")

    calendars = sub.add_parser("calendars", help="event calendars as JSON", allow_abbrev=False)
    calendars.add_argument(
        "--prompt", action="store_true", help="ask for Calendar access if needed"
    )

    schema = sub.add_parser("schema", help="print a packaged JSON Schema", allow_abbrev=False)
    schema.add_argument("name", choices=SCHEMA_NAMES)
    return parser


def _stderr_line(text: str) -> None:
    sys.stderr.write(" ".join(text.splitlines()) + "\n")
    sys.stderr.flush()


def _write_stdout(data: bytes) -> None:
    """Write every byte of ``data`` to stdout, or raise.

    Writes go to the unbuffered raw stream when there is one, so a failed write leaves
    nothing buffered for the interpreter's exit-time flush to retry (no second error, and
    no process-wide state is changed). A write that accepts no bytes (``None`` from a full
    non-blocking pipe, or 0) raises instead of being mistaken for success. Bytes already
    accepted stay written on a pipe, which cannot take them back, so a write that fails
    partway can leave a prefix there. When stdout is a regular file the bytes this call wrote
    are cut back off (see :func:`_undo_partial_write`), so a failed write leaves it as it was.

    A text-only stdout with no ``buffer`` (an in-process ``redirect_stdout(io.StringIO())``)
    gets the same UTF-8 text, with short writes continued and 0 a failure; ``None`` there is
    a legacy file-like's "all written" (``TextIOBase.write`` returns the count).
    """
    sys.stdout.flush()
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        text = data.decode("utf-8")
        while text:
            count = sys.stdout.write(text)
            if count is None:
                break
            if not count:
                raise BlockingIOError(errno.EAGAIN, "stdout accepted no characters")
            text = text[count:]
        sys.stdout.flush()
        return
    out = getattr(buffer, "raw", buffer)
    start = _file_position(out)
    view = memoryview(data)
    total = 0
    try:
        while view:
            written = out.write(view)
            if not written:
                raise BlockingIOError(errno.EAGAIN, "stdout accepted no bytes")
            view = view[written:]
            total += written
        out.flush()
    except Exception:
        if start is not None:
            _undo_partial_write(start[0], start[1], total)
        raise


def _file_position(out: Any) -> tuple[int, int] | None:
    """``(fd, offset)`` where this call's bytes start, when stdout is a regular file.

    ``None`` for a pipe, terminal, in-memory stream or anything else that cannot be rewound.
    An append-mode descriptor writes at the end of the file, so its start is the file size.
    """
    try:
        fd = out.fileno()
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None
        if fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_APPEND:
            return fd, info.st_size
        return fd, os.lseek(fd, 0, os.SEEK_CUR)
    except (AttributeError, OSError, ValueError):
        return None


def _undo_partial_write(fd: int, start: int, written: int) -> None:
    """Cut the ``written`` bytes this process put at ``start`` back off a regular file.

    Only when the file is exactly ``start + written`` long, so bytes another writer added or
    a file that was longer to begin with are never touched. Best effort: an error here
    leaves the prefix, as a pipe would, and the original write error is the one reported.
    """
    if not written:
        return
    try:
        if os.fstat(fd).st_size == start + written:
            os.ftruncate(fd, start)
            os.lseek(fd, start, os.SEEK_SET)
    except OSError:
        pass


def _emit(data: bytes) -> int:
    """The single stdout exit: EXIT_OK only when every byte was written (R11)."""
    try:
        _write_stdout(data)
    except Exception as exc:  # e.g. BrokenPipeError: one line, exit 1
        _stderr_line(f"internal error: {type(exc).__name__}")
        return EXIT_INTERNAL
    return EXIT_OK


def _run(args: argparse.Namespace, get_source: Callable[[], EventSource]) -> bytes:
    if args.command == "schema":
        return (files("macos_calendar_events") / "schema" / f"{args.name}.schema.json").read_bytes()
    if args.command == "calendars":
        found = _api.query_calendars(get_source, prompt=args.prompt)
        return calendars_to_json(found).encode("utf-8")
    # window: validate the raw input, then pad, then _api validates the padded window.
    start = _mapping.parse_instant_text(args.start)
    end = _mapping.parse_instant_text(args.end)
    if end <= start:
        raise InvalidQueryError("--end must be after --start")
    try:
        pad = timedelta(minutes=args.pad_minutes)
        padded = (start - pad, end + pad)
    except OverflowError:  # an absurd --pad-minutes is a usage error, not an internal one
        raise InvalidQueryError("--pad-minutes out of range") from None
    result = _api.query_events(
        get_source,
        *padded,
        calendars=args.calendars,
        include_notes=args.include_notes,
        prompt=args.prompt,
    )
    return window_to_json(result.events, window=padded).encode("utf-8")


def main(argv: Sequence[str] | None = None, *, source: EventSource | None = None) -> int:
    parser = _parser()
    printed = io.StringIO()
    try:
        # --help/--version text is captured and sent through _emit like any other output;
        # argparse's own write would ignore errors or leave them to the exit-time flush.
        with contextlib.redirect_stdout(printed):
            args = parser.parse_args(argv)  # usage errors: stderr, SystemExit(2)
    except SystemExit as exc:
        if exc.code not in (0, None):
            raise
        return _emit(printed.getvalue().encode("utf-8"))
    if args.command == "window" and args.pad_minutes < 0:
        parser.error("--pad-minutes must be >= 0")

    def get_source() -> EventSource:
        # ``source`` is the test seam; otherwise EventKit (looked up at call time).
        return source if source is not None else _eventkit.default_source()

    try:
        output = _run(args, get_source)
    except InvalidQueryError as exc:
        _stderr_line(f"{PROG}: error: {exc}")
        return EXIT_USAGE
    except EventKitUnavailableError as exc:
        _stderr_line(f"{PROG}: {exc}")
        return EXIT_UNAVAILABLE
    except CalendarAccessError as exc:
        _stderr_line(str(exc))
        return EXIT_ACCESS
    except CalendarNotFoundError as exc:
        _stderr_line(f"{PROG}: {exc}")
        return EXIT_NOT_FOUND
    except Exception as exc:
        _stderr_line(f"internal error: {type(exc).__name__}")
        return EXIT_INTERNAL
    return _emit(output)


if __name__ == "__main__":
    sys.exit(main())
