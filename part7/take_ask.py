"""Ask this take: one question about one take on its result page (docs/specs/take-ask.md, TICKET-269 Part 7 half).

Part 5 owns the agent (`part5 ask`, contract `simon.ask.v1`): it calls Muse Wonder with five tools that read only the take's
`analysis.json` and `replay.json`, validates that every number in the answer came from a tool result, and records the spend in its
own ledger (purpose `ask`). Part 7 owns who may ask: the caller must own the take (a stranger's job and a missing job give the
same 404 before any Part 5 call, so no tool runs) and keep takes, a private take is never sent, the question passes the same
question check as Ask my history, and the answer passes the same banned-word guard. Part 7 writes no spend line of its own, so
nothing is counted twice; the document's `spend` is shown beside the answer. `actions` come from Part 5's `ui_actions`, which the
player applies in order. Nothing is stored but a per-day count.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

from part7 import history_ask, history_ask_guard, history_facts, history_guard, history_receipt, history_report, history_store
from part7.parts import p5_ask

FEATURE = "ask_take"
PROMPT_VERSION = "ask_take.v2"
RUNS_FILE = "ask_take_runs.jsonl"
MAX_ACTIONS = 16
SOURCES = ("model", "cache", "measured_facts")
FIELDS = ["analysis.json", "replay.json"]  # what leaves for Part 5, for the receipt

MSG_NOT_FOUND = "That take was not found."
MSG_PRIVATE = "This take is private, so Simon does not send it to a model."
MSG_BUSY = "Simon is answering another question. Try again in a few seconds."
MSG_FAILED = "Simon could not answer just now. Try again in a moment."
MSG_UNAVAILABLE = "Asking about a take is not available on this server yet."
MSG_FILES = "This take's analysis files are not available, so Simon cannot answer about it."
MSG_UNCHECKED = "Simon could not check an answer to that against this take."

ASK: Callable[..., dict[str, Any]] = p5_ask.run  # tests replace it with a fake Part 5 responder
_LOCK = threading.Lock()  # one question at a time per server, as history_ask
Busy = history_ask.Busy  # another question is running; the route adds Retry-After


def available() -> bool:
    """True when a Part 5 `ask` can answer: the pinned Part 5 has the command (a replaced responder, as in tests, counts)."""
    return ASK is not p5_ask.run or p5_ask.available()


def asked_today(state: Path, user: str, now: float | None = None) -> int:
    return history_report.runs_today(state, user, now, RUNS_FILE)


def entry_of(entry_id: str, name: str, take: dict[str, Any]) -> dict[str, Any]:
    """The one-take movement: ownership proof and the source of the suggested questions."""
    facts = history_facts.build([take], entry_id)
    return {"entry_id": entry_id, "name": name, "takes": [take], "rows": facts["takes"], "facts": facts}


def suggestions(entry: dict[str, Any], words: dict[str, Any] | None = None) -> list[str]:
    """Up to three questions built from this take's own faults, each one the box accepts."""
    pool: list[str] = []
    for fault in entry["rows"][0]["faults"] if entry["rows"] else []:
        pool.append(f"When does my {history_ask._label(fault['measure'], fault['side'])} show up in this take?")
    pool += ["What is the biggest thing to fix in this take?", "Where in this take should I look first?"]
    out: list[str] = []
    for text in pool:
        if text not in out and history_ask.question_problem(text, words)[0] is not None:
            out.append(text)
    return out[:3]


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) != float("inf")


def clean_actions(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Part 5's valid `ui_actions` as the page applies them: `seek {t}` and `spotlight {t, limb, joints}`; anything else is left out."""
    out: list[dict[str, Any]] = []
    for item in doc.get("ui_actions") if isinstance(doc.get("ui_actions"), list) else []:
        if not isinstance(item, dict) or item.get("type") not in ("seek", "spotlight") or not _num(item.get("t")) or item["t"] < 0:
            continue
        joints = [j for j in item.get("joints") or [] if isinstance(j, str) and len(j) <= 40] if item["type"] == "spotlight" else []
        limb = item.get("limb") if isinstance(item.get("limb"), str) and len(item["limb"]) <= 40 else None
        out.append({"tool": item["type"], "t": item["t"], "limb": limb if item["type"] == "spotlight" else None, "joints": joints})
    return out[:MAX_ACTIONS]


def _spend(doc: dict[str, Any]) -> dict[str, Any] | None:
    spend = doc.get("spend") if isinstance(doc.get("spend"), dict) else None
    if spend is None:
        return None
    return {k: (spend.get(k) if _num(spend.get(k)) else 0) for k in ("input_tokens", "cached_tokens", "output_tokens", "usd", "calls")}


def _sent(doc: dict[str, Any], entry: dict[str, Any], usage: dict[str, Any] | None) -> dict[str, Any]:
    """The "What Simon sent" receipt: Part 7 sent the two files of this take and the question to Part 5, which names its model."""
    row = entry["rows"][0]
    packed = {"feature": FEATURE, "prompt_version": PROMPT_VERSION,
              "manifest": {"digest_takes": [row["take"]], "prompt_version": PROMPT_VERSION, "fields": FIELDS,
                           "digest_cites": [[entry["name"], row["take"]]]}}
    sent = history_receipt.build(packed, usage if usage and doc.get("live") is True else None, feature=FEATURE)
    model = doc.get("model") if isinstance(doc.get("model"), str) and history_receipt.SAFE_WORD.match(doc["model"]) else None
    return {**sent, "model": model}  # the model Part 5 used (muse-wonder-1.0), or none when no model call was made


def view_of(doc: dict[str, Any], entry: dict[str, Any], words: dict[str, Any] | None) -> dict[str, Any]:
    """The answer for the page from a Part 5 document. The text passes the same banned-word guard as Ask my history."""
    source = doc.get("source") if doc.get("source") in SOURCES else None
    text = doc.get("answer") if isinstance(doc.get("answer"), str) else ""
    usage = _spend(doc)
    base = {"source": source, "validated": doc.get("validated") is True, "live": doc.get("live") is True,
            "model": doc.get("model") if isinstance(doc.get("model"), str) else None,
            "tool_calls": [{"name": c["name"], "ok": c.get("ok") is True} for c in doc.get("tool_calls") or []
                           if isinstance(c, dict) and isinstance(c.get("name"), str)][:16],
            "replaced": len([n for n in doc.get("replaced_numbers") or []]) if isinstance(doc.get("replaced_numbers"), list) else 0,
            "usage": usage, "prompt_version": PROMPT_VERSION}
    if source is None or not text.strip() or history_guard.text_problem(" ".join(text.split()), history_guard.Words(words), 1200):
        return {**base, "status": "unverified", "text": None, "message": MSG_UNCHECKED, "actions": [], "sent": _sent(doc, entry, usage)}
    return {**base, "status": "ok", "text": " ".join(text.split()), "message": "", "actions": clean_actions(doc), "sent": _sent(doc, entry, usage)}


def run_question(state: Path, user: str, job_id: str, entry: dict[str, Any] | None, question: Any, now: float | None = None) -> dict[str, Any]:
    """The answer to one question about one take as a plain dict. `entry` is `entry_of(...)` for a take the caller owns, or None
    (a take that is not theirs or does not exist: 404 before any call). `history_report.Refused` (or `Busy`) for 400, 404, 409, 422, 503."""
    state = Path(state)
    if history_ask_guard.crisis(question):  # reels 3.10: a fixed crisis answer before any other check, no Part 5 call
        return history_ask_guard.crisis_reply(actions=[])
    if entry is None or not entry["takes"] or entry["takes"][0]["job_id"] != job_id:
        raise history_report.Refused(404, MSG_NOT_FOUND, "not_found")
    if entry["takes"][0]["private"]:
        raise history_report.Refused(422, MSG_PRIVATE, "private_take")
    if not history_store.retention_opt_in(state, user):
        raise history_report.Refused(409, history_report.MSG_CONSENT, "consent_required")
    words = history_guard.load_words()
    clean, message = history_ask.question_problem(question, words)
    if clean is None:
        if message == history_ask.MSG_REFUSED:  # no Part 5 call and not counted against the day
            return {"status": "refused", "text": None, "actions": [], "message": message, "usage": None, "source": None}
        raise history_report.Refused(400, message or history_ask.MSG_EMPTY, "invalid_question")
    work = state / "jobs" / job_id / "work"
    analysis, replay = work / "follower" / "analysis.json", work / "follower" / "replay.json"
    if not analysis.is_file() or not replay.is_file():
        raise history_report.Refused(422, MSG_FILES, "no_take_files")
    now = time.time() if now is None else now
    if not _LOCK.acquire(blocking=False):
        raise Busy(409, MSG_BUSY, "busy")
    try:
        history_report.muse_gate("ask_take", user, state)
        with history_store.locked(state):
            history_report.note_run(state, user, now, RUNS_FILE)
        try:
            doc = ASK(clean, analysis, replay, work)
        except p5_ask.AskError:
            return {"status": "failed", "text": None, "actions": [], "message": MSG_FAILED, "usage": None, "source": None}
        return view_of(doc, entry, words)
    finally:
        _LOCK.release()
