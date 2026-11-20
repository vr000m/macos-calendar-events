# /// script
# requires-python = ">=3.11"
# dependencies = ["pyobjc-framework-EventKit>=13"]
# ///
"""Phase 0 EventKit/TCC spike (throwaway; deleted in the second Phase 0 commit).

PRIVACY: this script records counts, booleans, enum ints, type names, timings and
shape categories ONLY. It never stores or prints titles, names, emails, notes, URLs,
locations, calendar titles, or identifier values. Per-item inspection is wrapped so an
exception records only the exception *type name*.

READ-ONLY: it calls only EventKit getters, predicate queries and the access request.

Modes:
  (default)          probe in this process; writes .spike/<label>-<time>.json
  --as-parent        do not touch EventKit; spawn the probe as a child process and
                     record parent context + child exit/stderr shape (koda's path)
  --write-plist      write a launchd agent plist that runs --as-parent (user loads it)
  --write-tool-pkg   write a throwaway package for `uv tool install` (entry-point case)
  --import-only      time `import EventKit` and exit (no store, no TCC)
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import ctypes
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_T0 = time.perf_counter()
_BAKED_OUT_DIR: str | None = None  # set in the uv-tool copy so results land in the repo
SCRIPT = Path(__file__).resolve()
DEFAULT_OUT_DIR = Path(_BAKED_OUT_DIR) if _BAKED_OUT_DIR else SCRIPT.parent.parent / ".spike"
HOME = str(Path.home())
DAY = 86400.0

EK_STATUS = {0: "not_determined", 1: "restricted", 2: "denied", 3: "full_access", 4: "write_only"}


# ---------------------------------------------------------------- helpers (no EventKit)
def tilde(p: str | None) -> str | None:
    if p is None:
        return None
    return "~" + p[len(HOME):] if p.startswith(HOME) else p


def exe_category(path: str | None) -> dict[str, Any]:
    """Basename plus enclosing .app bundle name; no other path parts."""
    if not path:
        return {"basename": None, "app_bundle": None}
    m = re.search(r"([^/]+\.app)/", path)
    return {"basename": os.path.basename(path), "app_bundle": m.group(1) if m else None,
            "under_home_local_bin": path.startswith(os.path.join(HOME, ".local/bin"))}


def pid_path(pid: int) -> str | None:
    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
        buf = ctypes.create_string_buffer(4096)
        n = libproc.proc_pidpath(ctypes.c_int(pid), buf, ctypes.c_uint32(4096))
        return buf.value.decode() if n > 0 else None
    except Exception:
        return None


def responsible_pid(pid: int) -> int | None:
    """Best effort: the process TCC treats as responsible (private libquarantine symbol)."""
    for lib in ("/usr/lib/libSystem.B.dylib", "/usr/lib/system/libquarantine.dylib"):
        try:
            fn = ctypes.CDLL(lib).responsibility_get_pid_responsible_for_pid
            fn.restype = ctypes.c_int
            fn.argtypes = [ctypes.c_int]
            r = fn(pid)
            return r if r > 0 else None
        except Exception:
            continue
    return None


def process_context() -> dict[str, Any]:
    chain: list[dict[str, Any]] = []
    pid = os.getpid()
    for _ in range(12):
        info = exe_category(pid_path(pid))
        info["is_launchd_pid1"] = pid == 1
        chain.append(info)
        if pid <= 1:
            break
        try:
            out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True,
                                 text=True, timeout=5).stdout.strip()
            pid = int(out)
        except Exception:
            break
    rp = responsible_pid(os.getpid())
    path_env = os.environ.get("PATH", "")
    return {
        "ancestor_chain": chain,  # [self, parent, grandparent, ...] basenames/app bundles only
        "responsible_process": exe_category(pid_path(rp)) if rp else None,
        "responsible_is_self": rp == os.getpid() if rp else None,
        "env": {
            "TERM_PROGRAM": os.environ.get("TERM_PROGRAM"),
            "has_XPC_SERVICE_NAME": "XPC_SERVICE_NAME" in os.environ,
            "PATH_has_home_local_bin": os.path.join(HOME, ".local/bin") in path_env.split(":"),
            "PATH_entry_count": len([p for p in path_env.split(":") if p]),
            "isatty_stdin": sys.stdin.isatty() if sys.stdin else None,
        },
    }


def interpreter_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "sys_executable": tilde(sys.executable),
        "sys_executable_realpath": tilde(os.path.realpath(sys.executable)),
        "python_version": platform.python_version(),
        "macos": platform.mac_ver()[0],
        "machine": platform.machine(),
    }
    try:
        import objc  # noqa: PLC0415

        info["pyobjc_version"] = objc.__version__
    except Exception as exc:
        info["pyobjc_version"] = f"unavailable:{type(exc).__name__}"
    return info


@contextlib.contextmanager
def capture_fd2(sink: dict[str, Any], key: str) -> Iterator[None]:
    """Count bytes/lines that frameworks write to fd 2. Content is never kept."""
    sys.stderr.flush()
    saved = os.dup(2)
    with tempfile.TemporaryFile() as tmp:
        os.dup2(tmp.fileno(), 2)
        try:
            yield
        finally:
            sys.stderr.flush()
            os.dup2(saved, 2)
            os.close(saved)
            tmp.seek(0)
            data = tmp.read()
            sink[key] = stderr_shape(data)


def stderr_shape(data: bytes) -> dict[str, Any]:
    text = data.decode("utf-8", "replace")
    return {"bytes": len(data), "lines": len(text.splitlines()),
            "mentions_TCC": "TCC" in text, "mentions_EventKit": "EventKit" in text or "EK" in text,
            "mentions_objc": "objc" in text.lower()}


class Results:
    def __init__(self, path: Path, label: str, mode: str) -> None:
        self.path = path
        self.data: dict[str, Any] = {"spike": "phase0", "label": label, "mode": mode,
                                     "started_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                     "stage": "init", "errors": collections.Counter()}

    def stage(self, name: str) -> None:
        self.data["stage"] = name
        self.write()

    def err(self, where: str, exc: BaseException) -> None:
        self.data["errors"][f"{where}:{type(exc).__name__}"] += 1

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True, default=_jsonable))
        tmp.replace(self.path)


def _jsonable(o: Any) -> Any:
    if isinstance(o, collections.Counter):
        return {str(k): v for k, v in sorted(o.items(), key=lambda kv: str(kv[0]))}
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    return str(type(o).__name__)


def ctr() -> collections.Counter:
    return collections.Counter()


# ---------------------------------------------------------------- EventKit probe
class EK:
    """Lazy imports so --as-parent / --write-* never load EventKit."""

    def __init__(self) -> None:
        t = time.perf_counter()
        import EventKit  # noqa: PLC0415
        import Foundation  # noqa: PLC0415

        self.import_s = time.perf_counter() - t
        self.EventKit = EventKit
        self.F = Foundation
        self.ENT = EventKit.EKEntityTypeEvent

    def status(self) -> int:
        return int(self.EventKit.EKEventStore.authorizationStatusForEntityType_(self.ENT))

    def store(self) -> Any:
        return self.EventKit.EKEventStore.alloc().init()

    def date(self, epoch: float) -> Any:
        return self.F.NSDate.dateWithTimeIntervalSince1970_(epoch)

    def query(self, store: Any, start: float, end: float) -> list[Any]:
        pred = store.predicateForEventsWithStartDate_endDate_calendars_(self.date(start), self.date(end), None)
        return list(store.eventsMatchingPredicate_(pred) or [])

    def pump(self, seconds: float) -> None:
        self.F.NSRunLoop.currentRunLoop().runUntilDate_(self.F.NSDate.dateWithTimeIntervalSinceNow_(seconds))


def ep(d: Any) -> float | None:
    return None if d is None else float(d.timeIntervalSince1970())


def request_access(ek: EK, store: Any, wait: str, timeout: float, R: Results) -> dict[str, Any]:
    done = threading.Event()
    box: dict[str, Any] = {}

    def handler(granted: bool, error: Any) -> None:
        box["granted"] = bool(granted)
        box["error_present"] = error is not None
        if error is not None:
            try:
                box["error_domain"] = str(error.domain())
                box["error_code"] = int(error.code())
            except Exception as exc:
                box["error_detail_exc"] = type(exc).__name__
        box["on_main_thread"] = threading.current_thread() is threading.main_thread()
        done.set()

    out: dict[str, Any] = {"wait_mode": wait, "timeout_s": timeout}
    t = time.perf_counter()
    store.requestFullAccessToEventsWithCompletion_(handler)
    out["request_call_returned_s"] = round(time.perf_counter() - t, 3)
    R.stage("access_request_waiting")
    delivered = "never"
    if wait == "event":
        if done.wait(timeout):
            delivered = "threading_event_without_runloop"
        else:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not done.is_set():
                ek.pump(0.1)
            if done.is_set():
                delivered = "only_after_runloop_pump"
    else:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not done.is_set():
            ek.pump(0.1)
        if done.is_set():
            delivered = "runloop_pump"
    out["callback_delivered"] = delivered
    out["callback_elapsed_s"] = round(time.perf_counter() - t, 3)
    out.update(box)
    return out


def overlaps(s: float, e: float, ws: float, we: float) -> bool:
    if e == s:
        return ws <= s < we
    return s < we and e > ws


def ekey(ev: Any) -> tuple[Any, ...]:
    """In-process identity only; never stored or printed."""
    return (ev.eventIdentifier(), ep(ev.occurrenceDate()), ep(ev.startDate()))


IANA_RE = re.compile(r"^(UTC|GMT|[A-Za-z_]+(/[A-Za-z0-9_+\-]+)+)$")
GMT_OFF_RE = re.compile(r"^(GMT|UTC)[+-]\d{1,2}(:?\d{2})?$")


def tz_category(name: str | None) -> str:
    if name is None:
        return "nil"
    if GMT_OFF_RE.match(name):
        return "gmt_offset"
    if IANA_RE.match(name):
        return "iana_like"
    return "other"


def local_hms(ek: EK, d: Any) -> tuple[tuple[int, int, int], tuple[int, int, int]] | None:
    F = ek.F
    units = (F.NSCalendarUnitYear | F.NSCalendarUnitMonth | F.NSCalendarUnitDay
             | F.NSCalendarUnitHour | F.NSCalendarUnitMinute | F.NSCalendarUnitSecond)
    c = F.NSCalendar.currentCalendar().components_fromDate_(units, d)
    return (int(c.year()), int(c.month()), int(c.day())), (int(c.hour()), int(c.minute()), int(c.second()))


def probe_calendars(ek: EK, store: Any, R: Results) -> dict[str, Any]:
    out: dict[str, Any] = {}
    cals = list(store.calendarsForEntityType_(ek.ENT) or [])
    out["count"] = len(cals)
    st, ctype, nils, cspace, srgb = ctr(), ctr(), ctr(), ctr(), ctr()
    try:
        import AppKit  # noqa: PLC0415

        srgb_space = AppKit.NSColorSpace.sRGBColorSpace()
    except Exception as exc:
        R.err("appkit_import", exc)
        srgb_space = None
    for c in cals:
        try:
            if c.title() is None:
                nils["title"] += 1
            if c.calendarIdentifier() is None:
                nils["calendarIdentifier"] += 1
            src = c.source()
            if src is None:
                nils["source"] += 1
            else:
                st[int(src.sourceType())] += 1
                if src.title() is None:
                    nils["source_title"] += 1
            ctype[int(c.type())] += 1
            col = c.color()
            if col is None:
                cspace["nil_color"] += 1
                continue
            try:
                cs = col.colorSpace()
                cspace[f"model={int(cs.colorSpaceModel())}|{cs.localizedName()}"] += 1
            except Exception as exc:
                cspace[f"colorSpace_exc:{type(exc).__name__}"] += 1
            if srgb_space is not None:
                conv = col.colorUsingColorSpace_(srgb_space)
                if conv is None:
                    srgb["conversion_nil"] += 1
                else:
                    r, g, b = conv.redComponent(), conv.greenComponent(), conv.blueComponent()
                    ok = all(0.0 <= x <= 1.0 for x in (r, g, b))
                    srgb["hex_ok" if ok else "component_out_of_range"] += 1
        except Exception as exc:
            R.err("calendar", exc)
    out.update(source_type_counts=st, calendar_type_counts=ctype, nil_counts=nils,
               color_space_counts=cspace, srgb_hex=srgb)
    try:
        srcs = list(store.sources() or [])
        dsrcs = list(store.delegateSources() or [])
        ids = {s.sourceIdentifier() for s in srcs}
        out["sources"] = {"count": len(srcs), "types": collections.Counter(int(s.sourceType()) for s in srcs),
                          "title_nil": sum(1 for s in srcs if s.title() is None)}
        out["delegate_sources"] = {"count": len(dsrcs),
                                   "types": collections.Counter(int(s.sourceType()) for s in dsrcs),
                                   "also_in_default_sources": sum(1 for s in dsrcs if s.sourceIdentifier() in ids)}
    except Exception as exc:
        R.err("sources", exc)
    return out


def probe_shapes(ek: EK, events: list[Any], R: Results) -> dict[str, Any]:
    nil, skip, tzc, tzrej = ctr(), ctr(), ctr(), 0
    ptype, prole, pstat, scheme, mshape, status_c, avail = ctr(), ctr(), ctr(), ctr(), ctr(), ctr(), ctr()
    xtab, detached, allday = ctr(), ctr(), collections.defaultdict(ctr)
    self_att: dict[int, collections.Counter] = collections.defaultdict(ctr)
    org_c = ctr()
    base_keys: collections.Counter = collections.Counter()
    by_evid: dict[Any, list[bool]] = collections.defaultdict(list)
    series_ext: dict[Any, set] = collections.defaultdict(set)
    ext_cals: dict[Any, set] = collections.defaultdict(set)
    ext_srcs: dict[Any, set] = collections.defaultdict(set)
    ext_occ: dict[Any, list] = collections.defaultdict(list)
    floating = 0
    try:
        from zoneinfo import ZoneInfo  # noqa: PLC0415
    except Exception:
        ZoneInfo = None  # type: ignore[assignment,misc]
    for ev in events:
        try:
            ext = ev.calendarItemExternalIdentifier()
            evid = ev.eventIdentifier()
            occ, s, e = ep(ev.occurrenceDate()), ep(ev.startDate()), ep(ev.endDate())
            cal = ev.calendar()
            cal_id = cal.calendarIdentifier() if cal is not None else None
            src = cal.source() if cal is not None else None
            stype = int(src.sourceType()) if src is not None else -1
            tz = ev.timeZone()
            tzname = str(tz.name()) if tz is not None else None
            allday_flag = bool(ev.isAllDay())
            for k, v in (("calendarItemExternalIdentifier", ext), ("title", ev.title()), ("eventIdentifier", evid),
                         ("occurrenceDate", occ), ("timeZone", tz), ("event.calendar", cal),
                         ("calendar.title", cal.title() if cal is not None else None),
                         ("calendar.calendarIdentifier", cal_id),
                         ("source", src), ("source.title", src.title() if src is not None else None),
                         ("startDate", s), ("endDate", e), ("organizer", ev.organizer())):
                if v is None:
                    nil[k] += 1
            if ext is not None and str(ext) == "":
                nil["externalIdentifier_empty_string"] += 1
            if s is None or e is None or cal_id is None:
                skip["would_skip"] += 1
                if s is None:
                    skip["startDate_nil"] += 1
                if e is None:
                    skip["endDate_nil"] += 1
                if cal_id is None:
                    skip["calendar_id_nil"] += 1
            occ_eff = occ if occ is not None else s
            base_keys[(cal_id, ext or evid or "", occ_eff, s, e)] += 1
            hrr, det = bool(ev.hasRecurrenceRules()), bool(ev.isDetached())
            xtab[f"hasRecurrenceRules={hrr}|isDetached={det}"] += 1
            if det:
                detached["occurrence_nil" if occ is None else ("occ_eq_start" if occ == s else "occ_ne_start")] += 1
            if evid is not None:
                by_evid[evid].append(det)
            if hrr or det:
                series_ext[(cal_id, ev.calendarItemIdentifier())].add(ext)
            if ext:
                ext_cals[ext].add(cal_id)
                ext_srcs[ext].add(stype)
                ext_occ[(ext, occ_eff)].append(cal_id)
            tzc[tz_category(tzname)] += 1
            if tzname is not None and ZoneInfo is not None:
                try:
                    ZoneInfo(tzname)
                except Exception:
                    tzrej += 1
            if tzname is None and not allday_flag:
                floating += 1
            status_c[int(ev.status())] += 1
            avail[int(ev.availability())] += 1
            if allday_flag and s is not None and e is not None:
                a = allday
                a["count"]["n"] += 1
                a["tz_nil"][tzname is None] += 1
                a["utc_start_offset_hours"][round((s % DAY) / 3600, 2)] += 1
                a["duration_days"][round((e - s) / DAY, 4)] += 1
                ls, le = local_hms(ek, ev.startDate()), local_hms(ek, ev.endDate())
                if ls and le:
                    a["local_start_hms"]["{:02d}:{:02d}:{:02d}".format(*ls[1])] += 1
                    a["local_end_hms"]["{:02d}:{:02d}:{:02d}".format(*le[1])] += 1
                    d0 = datetime(*ls[0]).date()
                    d1 = datetime(*le[0]).date()
                    a["local_end_minus_start_dates"][(d1 - d0).days] += 1
            atts = ev.attendees()
            parts = list(atts or [])
            org = ev.organizer()
            n_self = 0
            org_url = None
            if org is not None:
                try:
                    org_url = str(org.URL().absoluteString()) if org.URL() is not None else None
                    org_c["organizer_isCurrentUser"] += int(bool(org.isCurrentUser()))
                except Exception as exc:
                    R.err("organizer", exc)
            for p in parts + ([org] if org is not None else []):
                try:
                    u = p.URL()
                    if u is None:
                        nil["participant.URL"] += 1
                    else:
                        sch = u.scheme()
                        scheme[str(sch).lower() if sch is not None else "nil"] += 1
                        if sch is not None and str(sch) != str(sch).lower():
                            mshape["scheme_not_lowercase"] += 1
                        rs = str(u.resourceSpecifier() or "")
                        if str(sch).lower() == "mailto":
                            if rs == "":
                                mshape["mailto_empty"] += 1
                            if "?" in rs:
                                mshape["mailto_has_query"] += 1
                            if "%" in rs:
                                mshape["mailto_percent_encoded"] += 1
                            if rs.startswith("//"):
                                mshape["mailto_double_slash"] += 1
                    if p.name() is None:
                        nil["participant.name"] += 1
                except Exception as exc:
                    R.err("participant", exc)
            for p in parts:
                try:
                    ptype[int(p.participantType())] += 1
                    prole[int(p.participantRole())] += 1
                    pstat[int(p.participantStatus())] += 1
                    if bool(p.isCurrentUser()):
                        n_self += 1
                    if org_url is not None and p.URL() is not None and str(p.URL().absoluteString()) == org_url:
                        org_c["organizer_repeated_in_attendees"] += 1
                except Exception as exc:
                    R.err("attendee", exc)
            bucket = "attendees_nil" if atts is None else ("0" if n_self == 0 else ("1" if n_self == 1 else ">1"))
            self_att[stype][bucket] += 1
        except Exception as exc:
            R.err("event", exc)
    dup_groups = [c for c in base_keys.values() if c > 1]
    evid_groups = [v for v in by_evid.values() if len(v) > 1]
    collisions = [v for v in ext_occ.values() if len(v) > 1]
    return {
        "events": len(events),
        "nil_counts": nil,
        "r3_skip_candidates": skip,
        "id_base_key": {"distinct": len(base_keys), "colliding_keys": len(dup_groups),
                        "rows_in_collisions": sum(dup_groups)},
        "eventIdentifier_sharing": {"ids_shared_by_multiple_rows": len(evid_groups),
                                    "rows_sharing": sum(len(v) for v in evid_groups),
                                    "groups_mixing_detached_and_regular": sum(1 for v in evid_groups if any(v) and not all(v))},
        "floating_timed_events": floating,
        "tz_categories": tzc,
        "tz_names_rejected_by_zoneinfo": tzrej,
        "recurring_series": {"series_with_rows": len(series_ext),
                             "series_one_external_id": sum(1 for v in series_ext.values() if len(v) == 1),
                             "series_multiple_external_ids": sum(1 for v in series_ext.values() if len(v) > 1)},
        "same_external_id_in_multiple_calendars": {
            "observed": any(len(v) > 1 for v in ext_cals.values()),
            "external_ids": len(ext_cals),
            "external_ids_in_2plus_calendars": sum(1 for v in ext_cals.values() if len(v) > 1),
            "external_ids_in_2plus_source_types": sum(1 for v in ext_srcs.values() if len(v) > 1)},
        "external_id_occurrence_collisions": {
            "colliding_keys": len(collisions),
            "same_calendar": sum(1 for v in collisions if len(set(v)) == 1),
            "cross_calendar": sum(1 for v in collisions if len(set(v)) > 1)},
        "participant_url_schemes": scheme,
        "mailto_shapes": mshape,
        "participant_type": ptype, "participant_role": prole, "participant_status": pstat,
        "event_status": status_c, "event_availability": avail,
        "recurrence_x_detached": xtab,
        "detached_occurrence_vs_start": detached,
        "all_day": {k: v for k, v in allday.items()},
        "self_attendees_by_source_type": {str(k): v for k, v in self_att.items()},
        "organizer": org_c,
    }


def probe_edges(ek: EK, store: Any, events: list[Any], samples: int, R: Results) -> dict[str, Any]:
    timed = [e for e in events if e.startDate() is not None and e.endDate() is not None and not e.isAllDay()]
    nonzero = [e for e in timed if ep(e.endDate()) != ep(e.startDate())][:samples]
    zero = [e for e in timed if ep(e.endDate()) == ep(e.startDate())][:samples]
    out: dict[str, Any] = {}

    def case(name: str, evs: list[Any], win: Any) -> None:
        c = ctr()
        for ev in evs:
            try:
                k = ekey(ev)
                s, e = ep(ev.startDate()), ep(ev.endDate())
                ws, we = win(s, e)
                narrow = {ekey(x) for x in ek.query(store, ws, we)}
                wide = ek.query(store, ws - DAY, we + DAY)
                widek = {ekey(x) for x in wide}
                c["n"] += 1
                c["narrow_included"] += int(k in narrow)
                c["widened_contains"] += int(k in widek)
                c["widened_then_filtered_included"] += int(k in widek and overlaps(s, e, ws, we))
            except Exception as exc:
                R.err(f"edge_{name}", exc)
        out[name] = c

    case("ends_exactly_at_window_start", nonzero, lambda s, e: (e, e + 3600))
    case("starts_exactly_at_window_end", nonzero, lambda s, e: (s - 3600, s))
    case("zero_length_at_window_start", zero, lambda s, e: (s, s + 3600))
    case("zero_length_at_window_end", zero, lambda s, e: (s - 3600, s))
    return out


def probe_four_year(ek: EK, store: Any, R: Results) -> dict[str, Any]:
    now = time.time()
    start = now - 730 * DAY
    out: dict[str, Any] = {}

    def run(name: str, s: float, days: float) -> set:
        t = time.perf_counter()
        try:
            evs = ek.query(store, s, s + days * DAY)
            keys = {ekey(x) for x in evs}
            starts = [ep(x.startDate()) for x in evs if x.startDate() is not None]
            out[name] = {"rows": len(evs), "distinct": len(keys), "seconds": round(time.perf_counter() - t, 3),
                         "latest_start_offset_days": round((max(starts) - s) / DAY, 1) if starts else None}
            return keys
        except Exception as exc:
            R.err(f"four_year_{name}", exc)
            out[name] = {"exception": type(exc).__name__}
            return set()

    whole = run("q1460", start, 1460)
    parts: set = set()
    rows = 0
    for i in range(4):
        parts |= run(f"q365_{i}", start + i * 365 * DAY, 365)
        rows += out.get(f"q365_{i}", {}).get("rows", 0)
    out["sum_four_365_rows"] = rows
    out["union_four_365_distinct"] = len(parts)
    out["in_union_not_in_1460"] = len(parts - whole)
    for d in (1461, 1462, 1500):
        run(f"q{d}", start, d)
    return out


def run_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    path = Path(args.out) if args.out else out_dir / f"{args.label}-{time.strftime('%Y%m%dT%H%M%S')}.json"
    R = Results(path, args.label, "probe")
    D = R.data
    D["interpreter"] = interpreter_info()
    D["process"] = process_context()
    D["args"] = {"prompt": args.prompt, "wait": args.wait, "days_back": args.days_back,
                 "days_forward": args.days_forward, "four_year": not args.skip_four_year}
    D["stderr"] = {}
    R.stage("import")
    with capture_fd2(D["stderr"], "import"):
        ek = EK()
    D["timing"] = {"since_interpreter_start_to_import_done_s": round(time.perf_counter() - _T0, 3),
                   "import_eventkit_s": round(ek.import_s, 3)}
    R.stage("status")
    with capture_fd2(D["stderr"], "status_check"):
        s0 = ek.status()
    D["status_initial"] = {"int": s0, "name": EK_STATUS.get(s0, "unknown")}
    R.stage("store_create")
    t = time.perf_counter()
    with capture_fd2(D["stderr"], "store_create"):
        store_before = ek.store()
    D["timing"]["cold_store_create_s"] = round(time.perf_counter() - t, 3)
    granted_here = False
    if s0 == 0 and args.prompt:
        R.stage("access_request")
        with capture_fd2(D["stderr"], "access_request"):
            D["access_request"] = request_access(ek, store_before, args.wait, args.prompt_timeout, R)
        granted_here = bool(D["access_request"].get("granted"))
    elif s0 == 0:
        D["access_request"] = {"skipped": "status not_determined and --prompt not given"}
    with capture_fd2(D["stderr"], "status_recheck"):
        s1 = ek.status()
    D["status_final"] = {"int": s1, "name": EK_STATUS.get(s1, "unknown")}
    now = time.time()
    if s1 != 3:
        R.stage("no_full_access")
        with capture_fd2(D["stderr"], "denied_path_reads"):
            try:
                D["no_access_reads"] = {"calendars": len(list(store_before.calendarsForEntityType_(ek.ENT) or [])),
                                        "events_pm7d": len(ek.query(store_before, now - 7 * DAY, now + 7 * DAY))}
            except Exception as exc:
                R.err("denied_reads", exc)
        R.stage("done")
        summarize(D, args.summary, path)
        return 0
    R.stage("store_lifetime")
    with capture_fd2(D["stderr"], "store_lifetime"):
        fresh = ek.store()
        D["store_lifetime"] = {
            "first_time_grant_in_this_process": granted_here,
            "store_before_grant": {"calendars": len(list(store_before.calendarsForEntityType_(ek.ENT) or [])),
                                   "events_pm7d": len(ek.query(store_before, now - 7 * DAY, now + 7 * DAY))},
            "fresh_store": {"calendars": len(list(fresh.calendarsForEntityType_(ek.ENT) or [])),
                            "events_pm7d": len(ek.query(fresh, now - 7 * DAY, now + 7 * DAY))},
        }
    R.stage("timing")
    with capture_fd2(D["stderr"], "timing"):
        t = time.perf_counter()
        cold = ek.store()
        q15 = ek.query(cold, now - 900, now + 900)
        D["timing"]["cold_store_plus_pm15min_query_s"] = round(time.perf_counter() - t, 3)
        D["timing"]["pm15min_rows"] = len(q15)
        t = time.perf_counter()
        q7 = ek.query(cold, now - 7 * DAY, now + 7 * DAY)
        D["timing"]["pm7d_query_s"] = round(time.perf_counter() - t, 3)
        D["timing"]["pm7d_rows"] = len(q7)
        t = time.perf_counter()
        ek.query(cold, now - 7 * DAY, now + 7 * DAY)
        D["timing"]["pm7d_query_warm_s"] = round(time.perf_counter() - t, 3)
    R.stage("calendars")
    with capture_fd2(D["stderr"], "calendars"):
        D["calendars"] = probe_calendars(ek, fresh, R)
    R.stage("shapes")
    with capture_fd2(D["stderr"], "shapes"):
        t = time.perf_counter()
        events = ek.query(fresh, now - args.days_back * DAY, now + args.days_forward * DAY)
        D["shapes_window"] = {"days_back": args.days_back, "days_forward": args.days_forward,
                              "query_s": round(time.perf_counter() - t, 3)}
        D["shapes"] = probe_shapes(ek, events, R)
    D["system_tz_category"] = tz_category(str(ek.F.NSTimeZone.systemTimeZone().name()))
    R.stage("edges")
    with capture_fd2(D["stderr"], "edges"):
        D["predicate_edges"] = probe_edges(ek, fresh, events, args.edge_samples, R)
    if not args.skip_four_year:
        R.stage("four_year")
        with capture_fd2(D["stderr"], "four_year"):
            D["four_year"] = probe_four_year(ek, fresh, R)
    D["timing"]["total_s"] = round(time.perf_counter() - _T0, 3)
    R.stage("done")
    summarize(D, args.summary, path)
    return 0


def summarize(D: dict[str, Any], show: bool, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(D, indent=2, sort_keys=True, default=_jsonable))
    if show:
        lines = [f"label={D['label']} mode={D['mode']} stage={D.get('stage')}"]
        for k in ("status_initial", "status_final", "access_request", "store_lifetime", "timing",
                  "child", "launch_context"):
            if k in D:
                lines.append(f"{k}: {json.dumps(D[k], sort_keys=True, default=_jsonable)}")
        if "shapes" in D:
            sh = D["shapes"]
            lines.append(f"shapes: events={sh['events']} skip={dict(sh['r3_skip_candidates'])} "
                         f"cross_calendar_ext_id_observed={sh['same_external_id_in_multiple_calendars']['observed']}")
        if D.get("errors"):
            lines.append(f"errors(type names only): {json.dumps(D['errors'], default=_jsonable)}")
        print("\n".join(lines))
    print(f"results written: {tilde(str(path))}")


# ---------------------------------------------------------------- parent / launchd / tool
def run_parent(args: argparse.Namespace, argv: list[str]) -> int:
    out_dir = Path(args.out_dir)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    path = out_dir / f"{args.label}-{stamp}.json"
    child_out = out_dir / f"{args.label}-child-{stamp}.json"
    R = Results(path, args.label, "parent")
    R.data["interpreter"] = interpreter_info()
    R.data["launch_context"] = process_context()
    fwd: list[str] = []
    skip_next = False
    for a in argv:
        if skip_next:
            skip_next = False
            continue
        if a in ("--as-parent", "--summary"):
            continue
        if a in ("--child-cmd", "--label", "--out"):
            skip_next = True
            continue
        fwd.append(a)
    base = [args.child_cmd] if args.child_cmd else [sys.executable, str(SCRIPT)]
    cmd = base + fwd + ["--label", f"{args.label}-child", "--out", str(child_out)]
    R.data["child_cmd_shape"] = {"executable": exe_category(cmd[0]), "via_child_cmd": bool(args.child_cmd)}
    R.stage("child_running")
    t = time.perf_counter()
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=args.prompt_timeout + 900)
        rc = p.returncode
        R.data["child"] = {"returncode": rc, "killed_by_signal": signal.Signals(-rc).name if rc < 0 else None,
                           "wall_s": round(time.perf_counter() - t, 3), "stdout_bytes": len(p.stdout),
                           "stderr": stderr_shape(p.stderr)}
    except FileNotFoundError as exc:
        R.data["child"] = {"exception": type(exc).__name__}
    except subprocess.TimeoutExpired as exc:
        R.data["child"] = {"exception": type(exc).__name__}
    if child_out.exists():
        try:
            R.data["child_results"] = json.loads(child_out.read_text())
        except Exception as exc:
            R.err("child_json", exc)
    R.data["stage"] = "done"
    summarize(R.data, True, path)
    return 0


def write_plist(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir).resolve()
    ld = out_dir / "launchd"
    ld.mkdir(parents=True, exist_ok=True)
    label = f"local.mce-spike.{args.label}"
    py = Path(args.python) if args.python else out_dir / "venv" / "bin" / "python"
    if "/builds-v0/" in str(py) or "/.tmp" in str(py):
        print(f"refusing: {tilde(str(py))} is an ephemeral uv env that is deleted when `uv run` exits; "
              "run --make-venv and use .spike/venv/bin/python")
        return 2
    if not py.is_file() or not os.access(py, os.X_OK):
        print(f"refusing: interpreter {tilde(str(py))} does not exist; run --make-venv first")
        return 2
    py = py.absolute()  # keep the venv path (not its symlink target) so the venv's site-packages load
    prog = [str(py), str(SCRIPT), "--as-parent", "--label", args.label, "--out-dir", str(out_dir),
            "--prompt-timeout", str(int(args.prompt_timeout)), "--wait", args.wait]
    if args.prompt:
        prog.append("--prompt")
    if args.skip_four_year:
        prog.append("--skip-four-year")
    if args.child_cmd:
        prog += ["--child-cmd", args.child_cmd]
    import plistlib  # noqa: PLC0415

    # Run once at load; no KeepAlive, so a failure never respawns.
    plist = {"Label": label, "ProgramArguments": prog, "RunAtLoad": True,
             "WorkingDirectory": str(SCRIPT.parent.parent),
             "StandardOutPath": str(ld / f"{args.label}.out.log"),
             "StandardErrorPath": str(ld / f"{args.label}.err.log")}
    path = ld / f"{label}.plist"
    for log in (ld / f"{args.label}.out.log", ld / f"{args.label}.err.log"):
        log.unlink(missing_ok=True)  # so a wait loop never matches a stale log
    path.write_bytes(plistlib.dumps(plist))
    uid = os.getuid()
    print(f"wrote {tilde(str(path))}")
    print(f"load:   launchctl bootstrap gui/{uid} {path}")
    print(f"unload: launchctl bootout gui/{uid}/{label}")
    return 0


def make_venv(args: argparse.Namespace) -> int:
    venv = Path(args.out_dir).resolve() / "venv"
    uv = shutil.which("uv")
    if uv is None:
        print("refusing: uv not found on PATH")
        return 2
    cmds = [[uv, "venv", "--python", "3.12", str(venv)],
            [uv, "pip", "install", "--python", str(venv / "bin" / "python"), "pyobjc-framework-EventKit>=13"]]
    if venv.exists():
        cmds = cmds[1:]
    for c in cmds:
        r = subprocess.run(c)
        if r.returncode != 0:
            print(f"failed: {' '.join(c[1:3])} exit {r.returncode}")
            return r.returncode
    print(f"venv ready: {tilde(str(venv / 'bin' / 'python'))}")
    return 0


def write_tool_pkg(args: argparse.Namespace) -> int:
    root = Path(args.out_dir).resolve() / "toolpkg"
    if root.exists():
        shutil.rmtree(root)
    pkg = root / "src" / "mce_spike_probe"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    src = SCRIPT.read_text().replace("_BAKED_OUT_DIR: str | None = None",
                                     f"_BAKED_OUT_DIR: str | None = {str(Path(args.out_dir).resolve())!r}", 1)
    (pkg / "probe.py").write_text(src)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "mce-spike-probe"\nversion = "0.0.0"\nrequires-python = ">=3.11"\n'
        'dependencies = ["pyobjc-framework-EventKit>=13"]\n\n'
        '[project.scripts]\nmce-spike-probe = "mce_spike_probe.probe:main"\n\n'
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n\n'
        '[tool.hatch.build.targets.wheel]\npackages = ["src/mce_spike_probe"]\n')
    print(f"wrote {tilde(str(root))}")
    print(f"install:   uv tool install --python 3.12 {root}")
    print("uninstall: uv tool uninstall mce-spike-probe")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", default="terminal", help="run name, e.g. terminal, iterm, vscode, launchd")
    ap.add_argument("--summary", action="store_true", help="print a counts-only summary")
    ap.add_argument("--prompt", action="store_true", help="request access if status is not_determined")
    ap.add_argument("--wait", choices=["event", "runloop"], default="event",
                    help="event: threading.Event.wait first, then pump 15 s; runloop: pump NSRunLoop from the start")
    ap.add_argument("--prompt-timeout", type=float, default=120.0)
    ap.add_argument("--days-back", type=float, default=30.0)
    ap.add_argument("--days-forward", type=float, default=30.0)
    ap.add_argument("--edge-samples", type=int, default=20)
    ap.add_argument("--skip-four-year", action="store_true")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--out", default=None)
    ap.add_argument("--as-parent", action="store_true")
    ap.add_argument("--child-cmd", default=None, help="absolute path of the child executable (uv tool case)")
    ap.add_argument("--write-plist", action="store_true")
    ap.add_argument("--python", default=None, help="interpreter for the launchd plist (default .spike/venv/bin/python)")
    ap.add_argument("--make-venv", action="store_true", help="create the persistent .spike/venv used by launchd runs")
    ap.add_argument("--write-tool-pkg", action="store_true")
    ap.add_argument("--import-only", action="store_true")
    args = ap.parse_args(argv)
    if args.make_venv:
        return make_venv(args)
    if args.write_plist:
        return write_plist(args)
    if args.write_tool_pkg:
        return write_tool_pkg(args)
    if args.as_parent:
        return run_parent(args, argv)
    if args.import_only:
        t = time.perf_counter()
        import EventKit  # noqa: F401, PLC0415

        print(json.dumps({"import_eventkit_s": round(time.perf_counter() - t, 3),
                          "since_interpreter_start_s": round(time.perf_counter() - _T0, 3),
                          **interpreter_info()}))
        return 0
    try:
        return run_probe(args)
    except Exception as exc:  # never print a repr: type name only
        print(f"probe failed: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
