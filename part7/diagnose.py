"""`python -m part7 diagnose [--staging|--state DIR] [--since 2h] [--json]` (TICKET-091, observability.md).

Reads `part7.log` and its rotated files, collects the `ANOMALY` lines and the older free-text signs (long GPU
waits, job failures, Part 1 timeouts, `body_dimmed` reports), and prints a ranked report: per kind the count, the
worst example, the affected job ids and one likely cause. Exit 0 when clean, 1 when anything was found.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import shlex
import sys
from typing import Any, Callable

from part7 import state_flags

GPU_WAIT_MIN_S = 30.0  # a `gpu wait` shorter than this is normal queueing, not a finding
STAMP = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)Z (\w+) (.*)$")
ANOMALY = re.compile(r"^ANOMALY (\w+)(?: (.*))?$")
GPU_WAIT = re.compile(r"^(?:job (\w+): )?gpu wait ([0-9.]+) s \(reason: ([^)]*)\)")
PART1_TIMEOUT = re.compile(r"^(?:job (\w+): )?part 1 failed in ([0-9.]+) s: .*timed out")
LEGACY_FAIL = re.compile(r"^job (\w+): (?:failed at|crashed at) (\S+)")
BODY_DIMMED = re.compile(r"^client \w+ body_dimmed page=(\S*) (.*)$")
SINCE = re.compile(r"^(\d+)([smhd])$")
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

# kind -> rank (higher first)
SEVERITY = {
    "job_failed": 100, "heartbeat_stale": 90, "part_failed": 85, "http_5xx": 80, "part1_timeout": 75,
    "queue_backlog": 70, "disk_low": 65, "client_error": 60, "slow_job": 55, "slow_stage": 50,
    "gpu_wait": 45, "slow_request": 40, "body_dimmed": 30,
}

# The rules table: (kind, test on the worst example's fields, one-line likely cause). First match wins.
Rule = tuple[str, Callable[[dict[str, str]], bool], str]
RULES: list[Rule] = [
    ("slow_stage", lambda f: f.get("stage") == "pose", "Part 2 pose is slow: the GPU is shared or busy; check gpu_wait and gpu_free_mib in the heartbeat."),
    ("slow_stage", lambda f: f.get("stage") == "keyframes", "Part 1 key frames are slow: a long or large clip, or Part 1 hit its timeout."),
    ("slow_stage", lambda f: True, "A chain stage ran past its limit: look at the job's steps/part7.log for the part inside it."),
    ("slow_job", lambda f: True, "The whole job ran long: read its summary line to see which stage (and GPU wait) took the time."),
    ("job_failed", lambda f: "timed out" in f.get("detail", "") or "too long" in f.get("detail", ""), "A part timed out: see part_failed and part1_timeout for the same job."),
    ("job_failed", lambda f: True, "A stage failed: the detail names the visitor-facing reason; steps/<part>.log has the part's own error."),
    ("part_failed", lambda f: f.get("timed_out") == "true", "A part hit its time limit: the clip is too heavy for the limit, or the GPU was contended."),
    ("part_failed", lambda f: True, "A part exited non-zero: the detail is the last meaningful line of its log."),
    ("queue_backlog", lambda f: True, "Jobs queue faster than they finish: one slow job holds the GPU, or the worker count is too low."),
    ("heartbeat_stale", lambda f: True, "A job runs far longer than any stage should: a wedged part or a held GPU lock."),
    ("disk_low", lambda f: True, "The state disk is nearly full: clean old jobs, uploads and catalog files."),
    ("http_5xx", lambda f: True, "The server answered with an error: the request line before it in part7.log has the exception."),
    ("slow_request", lambda f: f.get("path", "").endswith("uploads"), "A slow upload (over the 20 s upload limit): the visitor's connection is slow or the file is big; compare bytes with seconds."),
    ("slow_request", lambda f: True, "A request took over the limit: a handler is doing slow work on the request thread."),
    ("client_error", lambda f: f.get("source") == "fetch", "The browser could not reach or got an error from an api path: look for http_5xx or a restart."),
    ("client_error", lambda f: True, "A script error in the browser: the detail and page name the screen; fix in web/."),
    ("gpu_wait", lambda f: "flock" in f.get("reason", ""), "Another Part 7 process holds the GPU lock (flock): a second server or a stuck job."),
    ("gpu_wait", lambda f: "MiB" in f.get("reason", ""), "Not enough free GPU memory: another process uses the GPU."),
    ("gpu_wait", lambda f: True, "Jobs wait their turn for the GPU."),
    ("part1_timeout", lambda f: True, "Part 1 timed out: Part 3 picked the key frames instead; a long or crowded clip."),
    ("body_dimmed", lambda f: True, "The 3D body had joints dimmed or hidden: the pose of that take has low confidence."),
]


@dataclass
class Finding:
    kind: str
    count: int = 0
    jobs: list[str] = field(default_factory=list)
    worst: dict[str, str] = field(default_factory=dict)
    worst_score: float = -1.0
    worst_time: str = ""

    def add(self, when: str, fields: dict[str, str], job: str | None, score: float) -> None:
        self.count += 1
        if job and job not in self.jobs:
            self.jobs.append(job)
        if score > self.worst_score:
            self.worst_score, self.worst, self.worst_time = score, fields, when


def parse_fields(rest: str) -> dict[str, str]:
    """`key=value ...[ detail=<text>]` of an ANOMALY line to a dict (quoted values unquoted, detail to the end)."""
    head, sep, detail = rest.partition(" detail=")
    if rest.startswith("detail="):
        head, sep, detail = "", " ", rest[len("detail="):]
    try:
        tokens = shlex.split(head)
    except ValueError:
        tokens = head.split()
    out = {k: v for k, _, v in (t.partition("=") for t in tokens) if _}
    if sep:
        out["detail"] = detail
    return out


def parse_since(text: str) -> timedelta:
    found = SINCE.match(text.strip())
    if not found:
        raise ValueError(f"--since needs a number and s, m, h or d (for example 2h), not {text!r}")
    return timedelta(seconds=int(found.group(1)) * UNITS[found.group(2)])


def log_files(state: Path) -> list[Path]:
    """`part7.log.3` .. `part7.log.1`, `part7.log`: oldest first."""
    rotated = [state / f"part7.log.{n}" for n in range(9, 0, -1)]
    return [p for p in (*rotated, state / "part7.log") if p.is_file()]


def _number(fields: dict[str, str], key: str = "seconds") -> float:
    try:
        return float(fields.get(key, ""))
    except ValueError:
        return 0.0


class Scan:
    """Collects findings from log lines (oldest first)."""

    def __init__(self) -> None:
        self.found: dict[str, Finding] = {}
        self.lines = 0
        self._legacy: list[tuple[str, str, dict[str, str], str | None, float]] = []
        self._anomaly_jobs: dict[str, set[str]] = {}  # kind -> jobs that have the ANOMALY line

    def _add(self, kind: str, when: str, fields: dict[str, str], job: str | None, score: float) -> None:
        self.found.setdefault(kind, Finding(kind)).add(when, fields, job, score)

    def line(self, text: str) -> None:
        stamp = STAMP.match(text)
        if not stamp:
            return
        self.lines += 1
        when, _level, msg = stamp.groups()
        anomaly = ANOMALY.match(msg)
        if anomaly:
            fields = parse_fields(anomaly.group(2) or "")
            job = fields.get("job")
            kind = anomaly.group(1)
            if job:
                self._anomaly_jobs.setdefault(kind, set()).add(job)
            score = _number(fields) or _number(fields, "oldest_running_s") or _number(fields, "queued")
            self._add(kind, when, fields, job, score)
            return
        gpu = GPU_WAIT.match(msg)
        if gpu and float(gpu.group(2)) >= GPU_WAIT_MIN_S:
            self._add("gpu_wait", when, {"seconds": gpu.group(2), "reason": gpu.group(3), "line": msg}, gpu.group(1), float(gpu.group(2)))
            return
        timeout = PART1_TIMEOUT.match(msg)
        if timeout:
            self._legacy.append(("part1_timeout", when, {"seconds": timeout.group(2), "line": msg}, timeout.group(1), float(timeout.group(2))))
            return
        failed = LEGACY_FAIL.match(msg)
        if failed:
            self._legacy.append(("job_failed", when, {"stage": failed.group(2), "line": msg}, failed.group(1), 0.0))
            return
        dimmed = BODY_DIMMED.match(msg)
        if dimmed:
            self._add("body_dimmed", when, {"page": dimmed.group(1), "line": msg}, None, 0.0)

    def finish(self) -> dict[str, Finding]:
        """Add the older free-text signs the ANOMALY lines do not already cover for the same job."""
        covered = {"part1_timeout": self._anomaly_jobs.get("part_failed", set()), "job_failed": self._anomaly_jobs.get("job_failed", set())}
        for kind, when, fields, job, score in self._legacy:
            if job is None or job not in covered[kind]:
                self._add(kind, when, fields, job, score)
        return self.found


def cause_of(finding: Finding) -> str:
    for kind, test, text in RULES:
        if kind == finding.kind and test(finding.worst):
            return text
    return "Unknown kind: read the worst example."


def scan_state(state: Path, since: timedelta | None, now: datetime | None = None) -> tuple[dict[str, Finding], int, list[Path]]:
    now = now or datetime.now(timezone.utc)
    cutoff = (now - since).strftime("%Y-%m-%dT%H:%M:%S") if since else ""
    scan, files = Scan(), log_files(state)
    for path in files:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if raw[:19] >= cutoff or not STAMP.match(raw):
                    scan.line(raw.rstrip("\n"))
    return scan.finish(), scan.lines, files


def ranked(found: dict[str, Finding]) -> list[Finding]:
    return sorted(found.values(), key=lambda f: (-SEVERITY.get(f.kind, 0), -f.count, f.kind))


def report(found: dict[str, Finding], lines: int, files: list[Path], since: str) -> dict[str, Any]:
    items = []
    for f in ranked(found):
        items.append({"kind": f.kind, "count": f.count, "jobs": f.jobs, "worst": {"time": f.worst_time, **f.worst},
                      "likely_cause": cause_of(f)})
    return {"clean": not items, "since": since, "lines_scanned": lines, "files": [str(p) for p in files], "findings": items}


def render(doc: dict[str, Any]) -> str:
    out = [f"diagnose: {doc['lines_scanned']} log lines since {doc['since']} in {len(doc['files'])} file(s)"]
    if doc["clean"]:
        out.append("clean: no anomalies found")
    for n, item in enumerate(doc["findings"], 1):
        worst = " ".join(f"{k}={v}" for k, v in item["worst"].items() if k not in ("line",))
        jobs = ", ".join(item["jobs"][:8]) + (" ..." if len(item["jobs"]) > 8 else "") if item["jobs"] else "-"
        out += [f"{n}. {item['kind']} x{item['count']}", f"   worst: {worst}", f"   jobs: {jobs}", f"   likely: {item['likely_cause']}"]
    return "\n".join(out)


def add_parser(sub: Any) -> None:
    p = sub.add_parser("diagnose", help="Scan part7.log for anomalies and print a ranked report (exit 1 when found).")
    state_flags.add_flags(p)
    p.add_argument("--since", default="24h", help="Only lines newer than this, such as 90m, 2h or 1d (default 24h).")
    p.add_argument("--json", action="store_true", help="Print the report as JSON.")


def main(args: argparse.Namespace) -> int:
    try:
        since = parse_since(args.since)
    except ValueError as exc:
        print(f"diagnose: {exc}", file=sys.stderr)
        return 2
    state = state_flags.state_dir(args)
    found, lines, files = scan_state(state, since)
    doc = report(found, lines, files, args.since)
    print(json.dumps(doc, indent=2) if args.json else render(doc))
    return 0 if doc["clean"] else 1
