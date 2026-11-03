"""The self-heal report: which automatic checks exist, when each last ran and what it last found (TICKET-204).

`record(check, finding)` is called where a mechanism acts; `applog.anomaly` also feeds it, so an `ANOMALY` line of a
known kind marks its check without each module importing this one. The record is kept in memory and, once
`configure(state)` named a state folder, in `<state>/selfheal.json` so `part7 selfheal-status` (another process) and
`api/health` read the same facts. A finding counts as an issue for `ISSUE_WINDOW_S` or until the check runs clean.
The two staging scripts run outside this process; they are read from `<state>/stale.log`. Spec: docs/specs/self-healing.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import logging
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable

OTHER_WORK = "other GPU work"  # job_gpu.OTHER_WORK: the reason a job record carries for an outside holder

ISSUE_WINDOW_S = 24 * 3600.0  # a finding older than this is history, not an open issue
WRITE_EVERY_S = 30.0  # an unchanged result is written to disk at most this often
FILE = "selfheal.json"
EXTERNAL_LOG = "stale.log"
DEFERRED_FILE = "adoption-deferred"  # written by the gate helper while an adoption waits, removed when it ends (TICKET-245)

# (name, what it watches, where it runs)
CHECKS: tuple[tuple[str, str, str], ...] = (
    ("staging_watchdog", "the firm watchdog calls staging/up.sh when a part main moved or the app stops answering", "external"),
    ("stale_restart", "staging/stale.sh finds a part main that moved and up.sh restarts after a drain", "external"),
    ("restart_drain", "SIGTERM waits for running jobs, then cuts off any left (ANOMALY drain_cut_off)", "server"),
    ("parts_gate", "a moved part main is checked in a throwaway worktree before staging adopts it", "gate"),
    ("parts_adoption", "a validated part sha waits for staging to be idle before the restart (staging/parts-gate-run.sh)", "gate"),
    ("warm_worker", "the warm Part 2 worker and tracker restart when unhealthy or when their pin changes", "server"),
    ("gpu_busy_routing", "a track that gets no GPU admission goes to api-sam31 or local-open (ANOMALY p2_track_gpu_busy)", "server"),
    ("refused_upload_logging", "a refused upload is logged and its file kept for a week (ANOMALY upload_refused)", "server"),
    ("entry_content", "a saved movement's video matches the clip that was recorded (ANOMALY entry_video_mismatch)", "server"),
    ("health_stale_cache", "api/health answers from the last good Part 6 probe while a probe is missed", "server"),
    ("route_errors", "a route that answers 5xx (ANOMALY http_5xx) stays an open finding until it is quiet for 15 minutes", "server"),
    ("client_errors", "5 browser errors of one kind in 10 minutes (ANOMALY client_error) open a finding until it is quiet", "server"),
)
CHECKS += (("gpu_starved", "a take waits over 300 s (SIMON7_GPU_STARVE_S) for the GPU while work outside staging holds it; "
            "an alert only, nothing is killed (ANOMALY gpu_starved)", "server"),)
NAMES = tuple(c[0] for c in CHECKS)
# ANOMALY kinds (applog.anomaly) that mark a check with a finding.
ANOMALY_CHECKS = {
    "drain_cut_off": "restart_drain",
    "parts_gate_red": "parts_gate",
    "parts_gate_skipped": "parts_gate",
    "p2_worker_unhealthy": "warm_worker",
    "p2_tracker_unhealthy": "warm_worker",
    "p2_track_gpu_busy": "gpu_busy_routing",
    "p2_track_gpu_busy_final": "gpu_busy_routing",
    "upload_refused": "refused_upload_logging",
    "entry_video_mismatch": "entry_content",
}

# Checks whose findings come and go on their own: open while new events keep arriving, closed after a quiet period.
QUIET_S = {"route_errors": 15 * 60.0, "client_errors": 10 * 60.0, "gpu_starved": 10 * 60.0}  # gpu_starved also closes when the wait ends
CLIENT_ERRORS_N = 5  # client_error anomalies of one kind within QUIET_S["client_errors"] that open a finding
GPU_STARVE_S = 300.0  # env SIMON7_GPU_STARVE_S: a GPU admission wait longer than this behind other GPU work is starvation
LOG_EVERY_S = 60.0  # "selfheal: not recording" is logged at most this often
# A designed answer is not a fault: the same rule as web/errors.js `isDesignedBusy` (429 or 503 on a spoken line).
_SPEECH_PATH = re.compile(r"(^|/)api/jobs/[^/]+/speech/\d+\.wav$")
_ID_PART = re.compile(r"^(?=.*\d)[A-Za-z0-9_-]{6,}$")

INFORMATIONAL = {"refused_upload_logging"}  # a refused file is the visitor's, not a fault: shown, never an open issue

_LOCK = threading.Lock()
_STATE: Path | None = None
_MEM: dict[str, dict[str, Any]] = {}
_WRITTEN: dict[str, float] = {}
_FINDINGS: dict[str, dict[str, Any]] = {}  # "<check>|<key>" -> {check, finding, first_seen, last_seen, count, ts}
_HITS: dict[str, list[float]] = {}  # client_error kind -> times within the window
_CRASH: dict[str, str] = {}  # "METHOD path" -> exception type of the last handler crash
_STARVED: set[str] = set()  # jobs whose `ANOMALY gpu_starved` is logged
_BROKEN: dict[str, Any] = {"reason": None, "logged": -LOG_EVERY_S}  # why selfheal cannot record, once it cannot


def configure(state: Path | str | None) -> None:
    """Name the state folder that keeps `selfheal.json` (None keeps the record in memory only)."""
    global _STATE
    with _LOCK:
        _STATE = Path(state) if state is not None else None
        _MEM.clear()
        _WRITTEN.clear()
        _FINDINGS.clear()
        _HITS.clear()
        _CRASH.clear()
        _STARVED.clear()
        _BROKEN.update(reason=None, logged=-LOG_EVERY_S)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_file(state: Path | None) -> dict[str, dict[str, Any]]:
    if state is None:
        return {}
    try:
        doc = json.loads((state / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in doc.items() if isinstance(v, dict)} if isinstance(doc, dict) else {}


def _log(msg: str, level: int = logging.INFO) -> None:
    from part7 import applog  # applog imports this module; the import waits until a line is written

    try:
        applog.log(msg, level=level)
    except Exception:  # a log line never stops the work it describes
        pass


def _stopped(reason: str) -> None:
    """Selfheal could not record: remember why (health shows it) and log it, at most once a minute."""
    with _LOCK:
        _BROKEN["reason"] = reason
        due = time.monotonic() - _BROKEN["logged"] >= LOG_EVERY_S
        if due:
            _BROKEN["logged"] = time.monotonic()
    if due:
        _log(f"selfheal: not recording ({reason})", logging.ERROR)


def _flush(state: Path) -> None:
    """Write the record and the findings to `<state>/selfheal.json`; the caller holds the lock."""
    doc: dict[str, Any] = {**_read_file(state), **_MEM}
    doc["_findings"] = {**doc.get("_findings", {}), **_FINDINGS}
    for key in [k for k in doc["_findings"] if k not in _FINDINGS and not _alive(doc["_findings"][k])]:
        del doc["_findings"][key]
    if "gpu_starved|gpu" not in _FINDINGS:
        doc["_findings"].pop("gpu_starved|gpu", None)  # closed when the wait ended (TICKET-305), not after the quiet backstop
    tmp = state / f".{FILE}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    os.replace(tmp, state / FILE)
    _BROKEN["reason"] = None


def _alive(f: dict[str, Any]) -> bool:
    return time.time() - float(f.get("ts", 0)) < QUIET_S.get(f.get("check", ""), 0.0)


def record(check: str, finding: str | None = None) -> None:
    """Note that `check` ran now, with `finding` (one plain line) or None for a clean run. Never raises."""
    if check not in NAMES:
        return
    try:
        row = {"last_run": _now(), "last_finding": finding}
        with _LOCK:
            was = _MEM.get(check)
            _MEM[check] = row
            state = _STATE
            quiet = (was is not None and was["last_finding"] == finding
                     and time.monotonic() - _WRITTEN.get(check, 0.0) < WRITE_EVERY_S)
            if state is None or quiet:
                return
            _WRITTEN[check] = time.monotonic()
            _flush(state)
    except OSError as exc:
        _stopped(f"cannot write {FILE}: {exc.strerror or type(exc).__name__}")
    except Exception as exc:  # record() itself failed: say so, never raise into the request path
        _stopped(f"record failed: {type(exc).__name__}: {exc}"[:160])


def _route_key(method: str, path: str) -> str:
    """`GET api/jobs/<id>/speech/0.wav`: ids in the path do not make a new route."""
    parts = [("<id>" if _ID_PART.match(p) else p) for p in path.strip("/").split("/")]
    return f"{method} " + "/".join(parts)


def note_crash(method: str, path: str, exc: BaseException) -> None:
    """The server calls this for a handler crash, so the 5xx finding names the error type."""
    with _LOCK:
        _CRASH[f"{method} {path}"] = type(exc).__name__
        while len(_CRASH) > 200:
            del _CRASH[next(iter(_CRASH))]


def _touch(check: str, key: str, finding: str) -> None:
    """Open the finding `key` of `check`, or count one more event on it; log when it opens."""
    now, opened, failed = time.time(), False, ""
    stamp = _now()
    with _LOCK:
        f = _FINDINGS.get(f"{check}|{key}")
        if f is None or not _alive(f):
            opened = True
            f = {"check": check, "finding": finding, "first_seen": stamp, "count": 0}
            _FINDINGS[f"{check}|{key}"] = f
        f.update(finding=finding, last_seen=stamp, ts=now, count=f["count"] + 1)
        state = _STATE
        if state is not None and (opened or time.monotonic() - _WRITTEN.get(f"{check}|{key}", 0.0) >= WRITE_EVERY_S):
            _WRITTEN[f"{check}|{key}"] = time.monotonic()
            try:
                _flush(state)
            except OSError as exc:
                failed = f"cannot write {FILE}: {exc.strerror or type(exc).__name__}"
    if failed:
        _stopped(failed)
    if opened:
        _log(f"selfheal: open {check}: {finding}")
        record(check, finding)


def sweep() -> None:
    """Close the findings that went quiet (logs each closing). Called by status and by every new event."""
    closed = []
    with _LOCK:
        for key, f in list(_FINDINGS.items()):
            if not _alive(f):
                closed.append(f)
                del _FINDINGS[key]
        for kind in [k for k, t in _HITS.items() if not t or time.time() - t[-1] >= QUIET_S["client_errors"]]:
            del _HITS[kind]
    for f in closed:
        minutes = max(1, round(QUIET_S[f["check"]] / 60))
        if f["check"] == "gpu_starved":
            _STARVED.clear()
        _log(f"selfheal: closed {f['check']} after {minutes} min quiet")
        record(f["check"], None)


def _starve_limit() -> float:
    try:
        return float(os.environ.get("SIMON7_GPU_STARVE_S", GPU_STARVE_S))
    except ValueError:
        return GPU_STARVE_S


def check_gpu_starved(waits: list[tuple[str, float, str]], holder: Callable[[], str], now: float | None = None) -> None:
    """TICKET-305: `waits` are `(job id, wait start epoch, reason)` of jobs in GPU admission; the heartbeat calls this each
    beat. A wait past the limit with reason `other GPU work` opens a finding and logs one `ANOMALY gpu_starved` per job;
    when no such wait is left the finding closes. Nothing is killed: the finding is the alert. Never raises."""
    try:
        from part7 import applog  # applog imports this module

        now = time.time() if now is None else now
        late = sorted(((jid, now - since) for jid, since, why in waits if why == OTHER_WORK and now - since > _starve_limit()),
                      key=lambda w: -w[1])
        if not late:
            _close_starved()
            return
        who = holder()
        with _LOCK:
            fresh = [(j, w) for j, w in late if j not in _STARVED]
            _STARVED.intersection_update({j for j, _ in late})
            _STARVED.update(j for j, _ in fresh)
        for job, waited in fresh:
            applog.anomaly("gpu_starved", job=job, waited=round(waited), holder=who)
        job, waited = late[0]
        more = f" (and {len(late) - 1} more)" if len(late) > 1 else ""
        _touch("gpu_starved", "gpu", f"take {job} has waited {waited:.0f} s for the GPU, held by {who}{more}")
    except Exception as exc:
        _stopped(f"gpu_starved check failed: {type(exc).__name__}: {exc}"[:160])


def _close_starved() -> None:
    with _LOCK:
        f = _FINDINGS.pop("gpu_starved|gpu", None)
        _STARVED.clear()
        state = _STATE
        if f is not None and state is not None:
            try:
                _flush(state)
            except OSError:
                pass
    if f is not None:
        _log("selfheal: closed gpu_starved, no take waits for the GPU behind other work")
        record("gpu_starved", None)


def _client_benign(fields: dict[str, Any]) -> bool:
    status = fields.get("status")
    return (fields.get("source") == "fetch" and status in (429, 503) and isinstance(fields.get("path"), str)
            and bool(_SPEECH_PATH.search(fields["path"])))


def _watch(kind: str, fields: dict[str, Any]) -> None:
    sweep()
    if kind == "http_5xx":
        method, path = str(fields.get("method", "?")), str(fields.get("path", "?"))
        with _LOCK:
            err = _CRASH.get(f"{method} {path}")
        route = _route_key(method, path)
        _touch("route_errors", route, f"{route} answered {fields.get('status', '5xx')}, error {err or 'not named'}")
    elif kind == "client_error" and not _client_benign(fields):
        source = str(fields.get("source") or "script")
        now = time.time()
        with _LOCK:
            hits = _HITS.setdefault(source, [])
            hits.append(now)
            hits[:] = [t for t in hits if now - t < QUIET_S["client_errors"]]
            n = len(hits)
        if n >= CLIENT_ERRORS_N:
            example = fields.get("path") or fields.get("page") or "-"
            _touch("client_errors", source, f"client_error source={source} {n} in 10 min, e.g. {example}")


def observe_anomaly(kind: str, detail: str = "", fields: dict[str, Any] | None = None) -> None:
    """`applog.anomaly` calls this: a known kind marks its check with that line as the finding."""
    try:
        _watch(kind, fields or {})
    except Exception as exc:
        _stopped(f"watch failed: {type(exc).__name__}: {exc}"[:160])
    check = ANOMALY_CHECKS.get(kind)
    if check:
        record(check, " ".join(f"{kind} {detail}".split())[:200])


def _external(state: Path | None, name: str) -> dict[str, Any]:
    if state is None or name not in ("staging_watchdog", "stale_restart"):
        return {}
    path = state / EXTERNAL_LOG
    try:
        stamp = path.stat().st_mtime
        lines = [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    except OSError:
        return {}
    return {"last_run": datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last_finding": lines[-1][:200] if lines else None, "external": True}


def _deferred(state: Path | None) -> dict[str, Any] | None:
    """The `parts_adoption` finding while `<state>/adoption-deferred` exists (its first line is the finding), else None."""
    if state is None:
        return None
    path = state / DEFERRED_FILE
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return None
    return {"check": "parts_adoption", "finding": (text[0] if text else "adoption deferred: staging busy")[:200],
            "first_seen": stamp, "count": 1, "last_seen": stamp}


def _is_open(row: dict[str, Any], name: str = "") -> bool:
    if not row.get("last_finding") or row.get("external") or name in INFORMATIONAL or name in QUIET_S:
        return False
    try:
        stamp = datetime.strptime(row["last_run"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (KeyError, ValueError):
        return True
    return time.time() - stamp < ISSUE_WINDOW_S


def open_findings(state: Path | str | None = None) -> list[dict[str, Any]]:
    """The open findings of the quiet-period checks: `{check, finding, first_seen, count, last_seen}`, newest last."""
    folder = Path(state) if state is not None else _STATE
    sweep()
    with _LOCK:
        disk = _read_file(folder).get("_findings", {})
        found = {**{k: v for k, v in disk.items() if isinstance(v, dict)}, **_FINDINGS}
    keep = ("check", "finding", "first_seen", "count", "last_seen")
    return sorted(({k: f.get(k) for k in keep} for f in found.values() if _alive(f)), key=lambda f: f.get("last_seen") or "")


def status(state: Path | str | None = None) -> dict[str, Any]:
    """`{checks, findings, issues, open, degraded, summary}`: `findings` lists the open ones; `degraded` is why selfheal cannot record, or None."""
    folder = Path(state) if state is not None else _STATE
    findings = open_findings(folder)
    deferred = _deferred(folder)
    if deferred:
        findings = sorted([*findings, deferred], key=lambda f: f.get("last_seen") or "")
    with _LOCK:
        disk, mem, degraded = _read_file(folder), dict(_MEM), _BROKEN["reason"]
    open_checks = {f["check"] for f in findings}
    rows = []
    for name, what, where in CHECKS:
        got = {**disk.get(name, {}), **mem.get(name, {})} or _external(folder, name)
        if name == "parts_adoption" and deferred:
            got = {"last_run": deferred["last_seen"], "last_finding": deferred["finding"]}
        rows.append({"name": name, "what": what, "where": where, "last_run": got.get("last_run"),
                     "last_finding": got.get("last_finding"), "open": _is_open(got, name) or name in open_checks})
    names = [r["name"] for r in rows if r["open"]]
    parts = (["degraded"] if degraded else []) + ([f"issues:{len(names)}"] if names else [])
    return {"checks": rows, "findings": findings, "issues": len(names), "open": names, "degraded": degraded, "state": "degraded" if degraded else "ok",
            "summary": ",".join(parts) or "ok"}


def summary(state: Path | str | None = None) -> str:
    """`ok`, `issues:N` or `degraded` (selfheal cannot record)."""
    return status(state)["summary"]


def heartbeat_text(state: Path | str | None = None) -> str:
    """The heartbeat's value: the summary plus the names of the open checks (`issues:2 open=route_errors,warm_worker`)."""
    doc = status(state)
    return doc["summary"] + (f" open={','.join(doc['open'])}" if doc["open"] else "")


def cli_selfheal_status(state: Path | str, as_json: bool = False) -> int:
    """`part7 selfheal-status`: print every check with its last run and finding; exit 0 ok, 1 open issues."""
    doc = status(state)
    if as_json:
        print(json.dumps(doc, indent=2))
        return 0 if doc["issues"] == 0 else 1
    print(f"self-heal: {doc['summary']} (state {state})")
    for row in doc["checks"]:
        ran = row["last_run"] or "not run in this state folder"
        finding = row["last_finding"] or "none"
        print(f"  {row['name']:<24} last run {ran}; last finding: {finding}{' (open)' if row['open'] else ''}")
    return 0 if doc["issues"] == 0 else 1
