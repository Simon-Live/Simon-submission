"""The history report job (docs/specs/history.md "Report"): fact table first, then one model call in the background.

`Runner.request` answers at once: a cached report, "accepted" while a worker thread runs the call (one report at a
time, whoever asked), or a `Refused` with the HTTP status. The call itself is `history_api.ask(packed)` and the
check is `history_guard.check(...)` (both lane lc-history-meta, read through `optional_module`). Any failure ends in
`status: fallback` with the fact table and a reason, never an error.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
from typing import Any

from part7 import applog, history_facts, history_longpack, history_receipt, history_store, keys, shown_score

FORMAT = "simon.history.v1"
DEFAULT_PROMPT_VERSION = "simon.history.v1"
DEFAULT_MODEL = "muse-spark-1.3"
# Both daily limits are off unless SIMON7_HISTORY_DAILY / SIMON7_HISTORY_GLOBAL_DAILY hold a positive integer.
KEEP_REPORTS = 5
RETRY_AFTER_S = 5
MIN_TAKES = 2
REASON_MAX = 120
MSG_FEW = "Record at least 2 takes of this movement before comparing them."
MSG_CONSENT = "Keeping your takes needs your OK first. Turn it on in your account."
MSG_GLOBAL_LIMIT = "Comparisons are paused for today because many were made. Try again tomorrow."
MSG_LIMIT_FMT = "You have compared your takes {n} times today. Try again tomorrow."
ZERO_USAGE = {"input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "usd": 0.0, "clips_sent": 0}


class Refused(Exception):
    """The request cannot start; `status` is the HTTP code and `message` is plain words, `code` a stable machine name ("" when none)."""

    def __init__(self, status: int, message: str, code: str = "") -> None:
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


def _env_limit(name: str) -> int | None:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return None
    return value if value > 0 else None


def daily_limit() -> int | None:
    """Reports per user per UTC day; None (no limit) unless SIMON7_HISTORY_DAILY is set."""
    return _env_limit("SIMON7_HISTORY_DAILY")


def global_daily_limit() -> int | None:
    """Paid comparisons per UTC day across everyone (R7); None unless SIMON7_HISTORY_GLOBAL_DAILY is set."""
    return _env_limit("SIMON7_HISTORY_GLOBAL_DAILY")


def _today_start(now: float) -> float:
    moment = datetime.fromtimestamp(now, timezone.utc)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def runs_today(state: Path, user_id: str, now: float | None = None, name: str = "runs.jsonl") -> int:
    """How many reports the user started since 00:00 UTC (`name` is another day-count file, e.g. history_ask's)."""
    now = time.time() if now is None else now
    try:
        lines = (history_store.user_dir(state, user_id) / name).read_text(encoding="utf-8").split()
    except OSError:
        return 0
    return sum(1 for line in lines if line.replace(".", "", 1).isdigit() and float(line) >= _today_start(now))


def global_runs_today(state: Path, now: float | None = None) -> int:
    """How many reports anyone started since 00:00 UTC."""
    base = history_store.root(state)
    if not base.is_dir():
        return 0
    total = 0
    for folder in base.iterdir():
        if folder.is_dir() and history_store.USER_ID_RE.match(folder.name):
            total += runs_today(state, folder.name, now)
    return total


def _note_run(state: Path, user_id: str, now: float, name: str = "runs.jsonl") -> None:
    path = history_store.user_dir(state, user_id) / name
    keep = [line for line in (path.read_text(encoding="utf-8").split() if path.is_file() else [])
            if line.replace(".", "", 1).isdigit() and float(line) >= _today_start(now) - 86400]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([*keep, f"{now:.3f}"]) + "\n", encoding="utf-8")


note_run = _note_run  # the public name, for history_ask


# ----- the plan: which takes, which key -----------------------------------------------------------
def hostable(takes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Takes that may reach a hosted call: private-mode takes never do."""
    return [t for t in takes if not t["private"]]


def cache_key(prompt_version: str, model: str, takes: list[dict[str, Any]], narration_sha: str, consent: bool,
              notes: list[dict[str, Any]] | None = None) -> str:
    """sha256 of prompt version, model, sorted (take, analysis sha, clip sha), narration sha, video consent and the
    owner's trainer notes (`history_longpack.owner_notes`), so a new note makes a new report."""
    parts = sorted([t["take"], history_store.sha256_file(t["analysis"]), history_store.sha256_file(t["clip"])] for t in takes)
    extra = [history_longpack.key_parts(notes)] if notes else []  # no notes: the key is what it was before notes
    blob = json.dumps([prompt_version, model, parts, narration_sha, bool(consent), *extra], separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _versions() -> tuple[str, str]:
    prompt, api = history_store.optional_module("part7.history_prompt"), history_store.optional_module("part7.history_api")
    return (str(getattr(prompt, "PROMPT_VERSION", DEFAULT_PROMPT_VERSION)), str(getattr(api, "MODEL", DEFAULT_MODEL)))


def _narration(catalog_dir: Path | None, entry_id: str) -> tuple[Any, str]:
    path = Path(catalog_dir) / entry_id / "narration.json" if catalog_dir else None
    doc = history_store.read_json(path) if path else None
    return (doc if isinstance(doc, dict) else None), history_store.sha256_file(path)


def report_path(state: Path, user_id: str, entry_id: str, key: str) -> Path:
    return history_store.reports_dir(state, user_id, entry_id) / f"{key}.json"


def cached(state: Path, user_id: str, entry_id: str, key: str) -> dict[str, Any] | None:
    doc = history_store.read_json(report_path(state, user_id, entry_id, key))
    return doc if isinstance(doc, dict) and doc.get("format") == FORMAT else None


def _row(take: dict[str, Any]) -> dict[str, Any]:
    return {"take": take["take"], "job_id": take["job_id"], "at": take["at"], "score": take["score"],
            "grade": take["grade"], "duration_s": take["duration_s"], "clip": take["clip"] is not None,
            "shown": shown_score.of_take(take)}  # one-letter.md: a report cached before this has no block (shownRow falls back)


def _duration(path: Path | None) -> float | None:
    """The clip's length in seconds by ffprobe, or None."""
    if path is None:
        return None
    try:
        done = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                              capture_output=True, text=True, timeout=30, check=False)
        value = float(done.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return value if value > 0 else None


MSG_MODEL_FAILED = "Simon could not get an answer from Muse Spark this time. Try again later."
_TRANSPORT_RE = re.compile(r"^(?:HTTP \d{3}|timeout|request failed|unreadable response) on ")


def screen_reason(reason: str, plain: str = MSG_MODEL_FAILED) -> str:
    """What a page shows for a failure reason: `plain` for a transport failure (status, Meta's message, timeout), which
    stays in logs and records only; any other reason (a cap, a missing key) is already plain words and is kept."""
    return plain if _TRANSPORT_RE.match(reason or "") else reason


def reason_detail(exc: BaseException) -> str:
    """The failure as logged and recorded: the reason itself (Meta's masked message included), one line, cut short."""
    reason = getattr(exc, "reason", None)
    text = reason if isinstance(reason, str) and reason else type(exc).__name__
    return keys.redact(" ".join(text.split()))[:REASON_MAX]


def _reason(exc: BaseException) -> str:
    """What the page shows: plain words; a transport failure is logged with its detail and shown as one plain line."""
    detail = reason_detail(exc)
    shown = screen_reason(detail)
    if shown != detail:
        applog.log(f"history: model call failed: {detail}", level=logging.WARNING)
    return shown


# ----- the runner ---------------------------------------------------------------------------------
class Runner:
    """One worker thread; reports run one at a time and the HTTP request never waits on the model."""

    def __init__(self, state: Path | str, catalog_dir: Path | str | None = None) -> None:
        self.state, self.catalog_dir = Path(state), Path(catalog_dir) if catalog_dir else None
        self._queue: queue.Queue[tuple[str, str, str]] = queue.Queue()
        self._lock = threading.Lock()
        self._active: dict[tuple[str, str, str], str] = {}
        self._worker: threading.Thread | None = None

    def plan(self, user_id: str, entry_id: str) -> tuple[list[dict[str, Any]], str, Any]:
        """`(hostable takes, cache key, narration)` for the user's takes of one entry."""
        usable = hostable(history_store.takes(self.state, user_id, entry_id))
        narration, narration_sha = _narration(self.catalog_dir, entry_id)
        video = history_store.consent(self.state, user_id)["video"]
        prompt_version, model = _versions()
        notes = history_longpack.owner_notes(self.state, user_id, entry_id, usable)
        return usable, cache_key(prompt_version, model, usable, narration_sha, video, notes), narration

    def status(self, user_id: str, entry_id: str, key: str) -> str | None:
        with self._lock:
            return self._active.get((user_id, entry_id, key))

    def request(self, user_id: str, entry_id: str, now: float | None = None) -> tuple[str, Any]:
        """`("cached", report)` or `("accepted", "queued"|"running")`; `Refused` for 409, 422 and 429."""
        if not history_store.retention_opt_in(self.state, user_id):
            raise Refused(409, MSG_CONSENT)
        usable, key, _ = self.plan(user_id, entry_id)
        if len(usable) < MIN_TAKES:
            raise Refused(422, MSG_FEW)
        hit = cached(self.state, user_id, entry_id, key)
        if hit is not None:
            return ("cached", hit)
        job = (user_id, entry_id, key)
        now = time.time() if now is None else now
        with self._lock:
            if job in self._active:
                return ("accepted", self._active[job])
            per_user, overall = daily_limit(), global_daily_limit()
            if per_user is not None and runs_today(self.state, user_id, now) >= per_user:
                raise Refused(429, MSG_LIMIT_FMT.format(n=per_user))
            if overall is not None and global_runs_today(self.state, now) >= overall:
                raise Refused(429, MSG_GLOBAL_LIMIT)
            with history_store.locked(self.state):
                _note_run(self.state, user_id, now)
            self._active[job] = "queued"
            self._queue.put(job)
            self._start_worker()
        return ("accepted", "queued")

    def _start_worker(self) -> None:
        if self._worker is None:
            self._worker = threading.Thread(target=self._loop, name="part7-history", daemon=True)
            self._worker.start()

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Block until the queue is empty and nothing runs (tests, shutdown)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if not self._active:
                    return True
            time.sleep(0.01)
        return False

    def _loop(self) -> None:
        while True:
            try:
                job = self._queue.get(timeout=30)
            except queue.Empty:
                with self._lock:  # `request` queues under this lock, so an empty queue here stays empty
                    if self._queue.empty():
                        self._worker = None
                        return
                continue
            with self._lock:
                self._active[job] = "running"
            try:
                self._run(*job)
            except Exception as exc:  # the worker outlives any one report
                applog.log(f"history: report crashed: {applog.cause(exc)}", level=logging.ERROR)
            finally:
                with self._lock:
                    self._active.pop(job, None)

    # ----- one report ---------------------------------------------------------------------------
    def _run(self, user_id: str, entry_id: str, key: str) -> None:
        usable, current, narration = self.plan(user_id, entry_id)
        if current != key or len(usable) < MIN_TAKES:  # the takes changed since the request; that key is stale
            return
        facts = history_facts.build(usable, entry_id)
        report = self.compose(user_id, entry_id, usable, facts, narration)
        report["key"] = key
        with history_store.locked(self.state):
            alive = {t["job_id"] for t in history_store.takes(self.state, user_id, entry_id)}
            watched = report.get("video") is not True or history_store.consent(self.state, user_id)["video"]  # withdrawn meanwhile
            if watched and all(row["job_id"] in alive for row in report["takes"]):  # a take dropped meanwhile voids the report
                history_store.write_json(report_path(self.state, user_id, entry_id, key), report)
                self._prune(user_id, entry_id)

    def _prune(self, user_id: str, entry_id: str) -> None:
        folder = history_store.reports_dir(self.state, user_id, entry_id)
        newest = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in newest[KEEP_REPORTS:]:
            old.unlink(missing_ok=True)

    def packed(self, entry_id: str, takes: list[dict[str, Any]], facts: dict[str, Any], narration: Any,
               video: bool, notes: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        """`history_prompt.pack(...)` over the C-STORE rows; None when that module is not there. `notes` are the owner's
        answered trainer notes on these takes (`history_longpack.owner_notes`), sent as quoted data after their take."""
        prompt = history_store.optional_module("part7.history_prompt")
        if prompt is None:
            return None
        teacher = Path(self.catalog_dir) / entry_id / "video.mp4" if self.catalog_dir else None
        teacher = teacher if teacher and teacher.is_file() else None
        by_job = {t["job_id"]: t["take"] for t in takes}
        texts = {n: history_longpack.note_block(entry_id, n, [x for x in notes or [] if by_job.get(x["job_id"]) == n]) for n in by_job.values()}
        return prompt.pack(entry_id, facts, takes, teacher_clip=teacher, teacher_duration_s=_duration(teacher),
                           narration=narration, video_consent=video, notes={n: t for n, t in texts.items() if t})

    def compose(self, user_id: str, entry_id: str, takes: list[dict[str, Any]], facts: dict[str, Any],
                narration: Any) -> dict[str, Any]:
        prompt_version, model = _versions()
        video = history_store.consent(self.state, user_id)["video"]
        base: dict[str, Any] = {
            "video": video, "format": FORMAT, "entry_id": entry_id, "status": "fallback", "reason": "", "model": model,
            "prompt_version": prompt_version, "takes": [_row(t) for t in takes], "facts": facts,
            "summary": history_facts.fallback_summary(facts), "trends": history_facts.fallback_trends(facts),
            "focus": None, "teacher_link": None, "observations": [], "rejected": [], "usage": dict(ZERO_USAGE),
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        api, guard = (history_store.optional_module("part7.history_api"), history_store.optional_module("part7.history_guard"))
        packed = self.packed(entry_id, takes, facts, narration, video, history_longpack.owner_notes(self.state, user_id, entry_id, takes)) if api and guard else None
        if packed is None:
            return {**base, "status": "skipped", "reason": "the model step is not available"}
        try:
            text, usage = api.ask(packed, state=self.state)
            answer = json.loads(text)
            if not isinstance(answer, dict):
                raise ValueError("the answer is not an object")
            kept, rejected = guard.check(answer, packed["facts"], narration, guard.load_words(), clip_takes=packed.get("clip_takes", ()))  # Part 5's student-words.json, else the guard's defaults  # the facts of the takes sent
        except Exception as exc:  # HistoryError, bad JSON or a guard fault: all end in the fact table
            spent = getattr(exc, "usage", None)
            return {**base, "reason": _reason(exc), "detail": reason_detail(exc), "sent": history_receipt.build(packed, spent if isinstance(spent, dict) else None),
                    "usage": {**ZERO_USAGE, **(spent if isinstance(spent, dict) else {})}}
        return self._merge({**base, "sent": history_receipt.build(packed, usage)}, kept, rejected, usage)

    @staticmethod
    def _merge(base: dict[str, Any], kept: Any, rejected: Any, usage: Any) -> dict[str, Any]:
        kept = kept if isinstance(kept, dict) else {}
        summary = kept.get("summary") if isinstance(kept.get("summary"), dict) else None
        merged = {**base, "status": "ok", "reason": "", "rejected": rejected if isinstance(rejected, list) else [],
                  "usage": {**ZERO_USAGE, **(usage if isinstance(usage, dict) else {})}}
        if summary:
            merged["summary"] = summary
        if kept.get("trends"):  # the guard may drop every trend; then the table's own stay
            merged["trends"] = kept["trends"]
        for name in ("focus", "teacher_link"):
            merged[name] = kept.get(name) if isinstance(kept.get(name), dict) else None
        merged["observations"] = kept.get("observations") if isinstance(kept.get("observations"), list) else []
        return merged


_RUNNERS: dict[str, Runner] = {}
_RUNNERS_LOCK = threading.Lock()


def runner_for(state: Path | str, catalog_dir: Path | str | None) -> Runner:
    """The one runner of a state folder (one report at a time per server)."""
    key = str(Path(state).resolve())
    with _RUNNERS_LOCK:
        if key not in _RUNNERS:
            _RUNNERS[key] = Runner(state, catalog_dir)
        return _RUNNERS[key]
