"""The pattern finder job (docs/specs/history-patterns.md, TICKET-221 AC-7): one text-only call in the background.

`PatternRunner.request` answers at once (a stored result, or "accepted" while a worker runs the call) or raises
`history_report.Refused`. The call is built by `history_longpack.build` and checked by `history_patterns.check`. It counts
against the same per-user and global daily report limits as a report, and has its own ledger feature `pattern`. A result
is stored in `<entry>/reports/patterns/`, so Delete my data, the retention withdrawal and a deleted take remove it with
the reports. Any failure ends in a result with `status: fallback` (the table in plain sentences), never an error.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import queue
import threading
import time
from typing import Any

from part7 import applog, history_facts, history_guard, history_longpack, history_patterns, history_prompt, history_receipt, history_report, history_store

FORMAT = "simon.history.patterns.v1"
KEEP = 3
MSG_FEW = "Patterns need at least 3 takes of the same section and mode of this movement."
ZERO_USAGE = {"input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "usd": 0.0, "clips_sent": 0}


def store_dir(state: Path | str, user_id: str, entry_id: str) -> Path:
    return history_store.reports_dir(state, user_id, entry_id) / "patterns"


def cached(state: Path | str, user_id: str, entry_id: str, key: str) -> dict[str, Any] | None:
    doc = history_store.read_json(store_dir(state, user_id, entry_id) / f"{key}.json")
    return doc if isinstance(doc, dict) and doc.get("format") == FORMAT else None


def sent_receipt(full: int, digest: int) -> dict[str, Any]:
    """What was sent, for the receipt line: keys, counts and the destination. Never a value."""
    keys = sorted(f"{group}.{name}" for group, names in history_prompt.ALLOWLIST.items() for name in names)
    return {"to": "Meta's model (muse-spark-1.3)", "keys": keys, "takes_full": full, "takes_digest": digest, "video": False}


class PatternRunner:
    """One worker thread; calls run one at a time and the HTTP request never waits on the model."""

    def __init__(self, state: Path | str, catalog_dir: Path | str | None = None, transport: Any = None) -> None:
        self.state, self.catalog_dir, self.transport = Path(state), Path(catalog_dir) if catalog_dir else None, transport
        self._queue: queue.Queue[tuple[str, str, str]] = queue.Queue()
        self._lock = threading.Lock()
        self._active: dict[tuple[str, str, str], str] = {}
        self._worker: threading.Thread | None = None

    # ----- the plan -----------------------------------------------------------------------------------
    def plan(self, user_id: str, entry_id: str) -> tuple[list[dict[str, Any]], dict[str, Any], str, Any]:
        """`(member rows, their fact table, cache key, narration)`: the user's hostable takes of the latest take's section and mode."""
        usable = history_report.hostable(history_store.takes(self.state, user_id, entry_id))
        facts = history_facts.build(usable, entry_id)
        members = {t["take"] for t in facts["takes"] if t.get("in_group")}
        rows = [t for t in usable if t["take"] in members]
        narration, narration_sha = history_report._narration(self.catalog_dir, entry_id, self.state)
        _, model = history_report._versions()
        parts = sorted([t["take"], history_store.sha256_file(t["analysis"])] for t in rows)
        parts += history_longpack.key_parts(history_longpack.owner_notes(self.state, user_id, entry_id, rows))  # a new note makes a new result
        blob = json.dumps([history_patterns.PROMPT_VERSION, history_longpack.LONGPACK_VERSION, model, parts, narration_sha],
                          separators=(",", ":"))
        return rows, facts, hashlib.sha256(blob.encode("utf-8")).hexdigest(), narration

    def eligibility(self, user_id: str, entry_id: str) -> dict[str, Any]:
        """What the page shows before a run: the takes in the latest take's section and mode, and whether that is enough.
        The one source for both the page and `request`, so the button never disagrees with the 422."""
        count = len(self.plan(user_id, entry_id)[0])
        enough = count >= history_patterns.MIN_TAKES
        return {"eligible": enough, "group_takes": count, "min_takes": history_patterns.MIN_TAKES, "reason": None if enough else MSG_FEW}

    def status(self, user_id: str, entry_id: str, key: str) -> str | None:
        with self._lock:
            return self._active.get((user_id, entry_id, key))

    def request(self, user_id: str, entry_id: str, now: float | None = None) -> tuple[str, Any]:
        """`("cached", result)` or `("accepted", "queued"|"running")`; `Refused` for 409 and 422."""
        if not history_store.retention_opt_in(self.state, user_id):
            raise history_report.Refused(409, history_report.MSG_CONSENT)
        if not self.eligibility(user_id, entry_id)["eligible"]:
            raise history_report.Refused(422, MSG_FEW, "too_few_takes")
        _, _, key, _ = self.plan(user_id, entry_id)
        hit = cached(self.state, user_id, entry_id, key)
        if hit is not None and hit.get("status") == "ok":  # a failed call may be asked again (it counts against the daily limit)
            return ("cached", hit)
        job = (user_id, entry_id, key)
        now = time.time() if now is None else now
        with self._lock:
            if job in self._active:
                return ("accepted", self._active[job])
            history_report.muse_gate("patterns", user_id, self.state)
            with history_store.locked(self.state):
                history_report._note_run(self.state, user_id, now)
            self._active[job] = "queued"
            self._queue.put(job)
            if self._worker is None:
                self._worker = threading.Thread(target=self._loop, name="part7-patterns", daemon=True)
                self._worker.start()
        return ("accepted", "queued")

    def wait_idle(self, timeout: float = 30.0) -> bool:
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
                with self._lock:
                    if self._queue.empty():
                        self._worker = None
                        return
                continue
            with self._lock:
                self._active[job] = "running"
            try:
                self._run(*job)
            except Exception as exc:  # the worker outlives any one result
                applog.log(f"history: patterns crashed: {applog.cause(exc)}", level=logging.ERROR)
            finally:
                with self._lock:
                    self._active.pop(job, None)

    # ----- one result ---------------------------------------------------------------------------------
    def _run(self, user_id: str, entry_id: str, key: str) -> None:
        rows, facts, current, narration = self.plan(user_id, entry_id)
        if current != key or len(rows) < history_patterns.MIN_TAKES:  # the takes changed since the request
            return
        doc = self.compose(user_id, entry_id, rows, facts, narration)
        doc["key"] = key
        with history_store.locked(self.state):
            alive = {t["job_id"] for t in history_store.takes(self.state, user_id, entry_id)}
            if all(row["job_id"] in alive for row in doc["takes"]):  # a take dropped meanwhile voids the result
                history_store.write_json(store_dir(self.state, user_id, entry_id) / f"{key}.json", doc)
                self._prune(user_id, entry_id)

    def _prune(self, user_id: str, entry_id: str) -> None:
        folder = store_dir(self.state, user_id, entry_id)
        for old in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[KEEP:]:
            old.unlink(missing_ok=True)

    def compose(self, user_id: str, entry_id: str, rows: list[dict[str, Any]], facts: dict[str, Any], narration: Any) -> dict[str, Any]:
        member_facts = history_facts.build(rows, entry_id)
        items = [history_longpack.evidence(r) for r in rows]
        table = history_patterns.count_table(items)
        _, model = history_report._versions()
        base: dict[str, Any] = {
            "format": FORMAT, "entry_id": entry_id, "status": "fallback", "reason": "", "model": model, "feature": history_patterns.FEATURE,
            "prompt_version": history_patterns.PROMPT_VERSION, "takes": [history_report._row(t) for t in rows],
            "patterns": history_patterns.fallback(table, member_facts), "rejected": [], "usage": dict(ZERO_USAGE),
            "reach": sent_receipt(len(rows), 0), "sent": None, "label": history_facts.SUMMARY_LABEL,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        api = history_store.optional_module("part7.history_api")
        if api is None:
            return {**base, "status": "skipped", "reason": "the model step is not available"}
        try:
            packed = history_longpack.build(
                [{"entry_id": entry_id, "rows": rows, "facts": member_facts, "narration": narration, "notes": history_longpack.owner_notes(self.state, user_id, entry_id, rows)}], user_id=user_id, scope=entry_id,
                question=history_patterns.question_blocks(table), schema=history_patterns.SCHEMA, schema_name=history_patterns.SCHEMA_NAME,
                feature=history_patterns.FEATURE, prompt_version=history_patterns.PROMPT_VERSION)
        except ValueError as exc:
            return {**base, "reason": history_report._reason(exc)}
        base["reach"] = sent_receipt(packed["full_takes"], packed["digest_takes"])
        # Rule: every history feature that calls the model shows "What Simon sent" (docs/specs/history-receipt.md)
        receipt_pack = {**packed, "manifest": {"digest_takes": [r["take"] for r in rows], "fields": base["reach"]["keys"], "notes_sent": packed["notes_sent"]}}
        base["sent"] = history_receipt.build(receipt_pack, None, feature=history_patterns.FEATURE)
        try:
            kwargs = {"transport": self.transport} if self.transport is not None else {}
            text, usage = api.ask(packed, state=self.state, **kwargs)
            kept, rejected = history_patterns.check(text, packed["facts"], table, history_guard.load_words())
        except Exception as exc:  # HistoryError, bad JSON or a guard fault: all end in the table
            spent = getattr(exc, "usage", None)
            return {**base, "reason": history_report._reason(exc), "detail": history_report.reason_detail(exc), "usage": {**ZERO_USAGE, **(spent if isinstance(spent, dict) else {})},
                    "sent": history_receipt.build(receipt_pack, spent if isinstance(spent, dict) else None, feature=history_patterns.FEATURE)}
        usage = {**ZERO_USAGE, **(usage if isinstance(usage, dict) else {})}
        return {**base, "status": "ok", "patterns": kept or base["patterns"], "rejected": rejected, "usage": usage,
                "sent": history_receipt.build(receipt_pack, usage, feature=history_patterns.FEATURE), "label": "", "meter": history_longpack.meter(usage),
                "table": {"takes_total": table["takes_total"]}}


_RUNNERS: dict[str, PatternRunner] = {}
_RUNNERS_LOCK = threading.Lock()


def runner_for(state: Path | str, catalog_dir: Path | str | None) -> PatternRunner:
    key = str(Path(state).resolve())
    with _RUNNERS_LOCK:
        if key not in _RUNNERS:
            _RUNNERS[key] = PatternRunner(state, catalog_dir)
        return _RUNNERS[key]
