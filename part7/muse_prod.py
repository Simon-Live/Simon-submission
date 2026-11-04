"""Prod's gate on the hosted Muse features (docs/specs/muse-prod.md; operator decision 2026-11-04, "bring them ALL back").

Seven features spend the operator's Meta and Baseten keys in prod: live feedback wording, second opinion, Ask about a take, Ask
about my takes, the comparison report wording, You doing it right and Part 1 key frames. Each asks this module first:
- the switch `SIMON7_POLICY_MUSE=on` (prod/compute.conf `SIMON7_MUSE_PROD=1`, a reviewed change and a release);
- the stop file: `touch <app state>/muse-stop` closes every feature at once, with no release or restart;
- no spend cap (operator: "no limits anywhere ever"): each run only adds its estimate (`FEATURE_USD`) to the day's file and the log,
  since Part 1 and Part 5 do their own calls in a child process.

Outside prod nothing here closes anything. A log line names the feature, the outcome and the site's estimate: never a person.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
from pathlib import Path
from typing import Any

from part7 import applog, config, consent_record, history_store, keys, prod_check, prod_mode, quota

SWITCH = "muse"
STOP_FILE = "muse-stop"
KEEP_DAYS = 7
PART5_CAP_UNLIMITED_USD = 1_000_000  # Part 5 has its own refusal past a cap and no way to turn it off; this keeps it out of reach
# What one press or one take is counted as. Temporary estimates from history_api.RATES and muse_fix_api.IMAGE_USD, until a
# real month of the ledger replaces them; they are not Meta's prices.
FEATURE_USD: dict[str, float] = {
    "phrasing": 0.01, "opinion": 0.10, "part1": 0.25, "ask_take": 0.05, "ask_history": 0.05, "compare": 0.25, "patterns": 0.25,
    "cross": 0.25, "reel": 0.25, "muse_fix": 0.03,
}
BASETEN_FEATURES = frozenset({"phrasing"})

MSG_OFF = "This feature is not available on this server."
MSG_STOPPED = "Simon has paused its AI features for now. Your takes and scores still work."


class Closed:
    """Why a feature cannot run now: an HTTP status, plain words for the person and a stable code."""

    def __init__(self, status: int, message: str, code: str) -> None:
        self.status, self.message, self.code = status, message, code


def switched_on() -> bool:
    return prod_mode.policy(SWITCH)


def stopped(state: Path | str | None = None) -> bool:
    return prod_mode.is_prod() and (config.state_root(state) / STOP_FILE).exists()


def open_now(state: Path | str | None = None) -> bool:
    """False while the switch is off or the stop file stands: what `api/policy` tells the web."""
    return switched_on() and not stopped(state)


def gate(state: Path | str | None = None) -> Closed | None:
    """The one check at the door to Meta and Baseten, read at the moment of the call and not at the press: every HTTP call
    (`history_api.HttpClient._call`) and every Part 1 or Part 5 child goes through it, so a queued job obeys the stop file too."""
    if not prod_mode.is_prod():
        return None
    if not switched_on():
        return Closed(503, MSG_OFF, "muse_off")
    return Closed(503, MSG_STOPPED, "muse_stopped") if stopped(state) else None


def _key_of(feature: str) -> str:
    return "BASETEN_API_KEY" if feature in BASETEN_FEATURES else "MODEL_API_KEY"


def _closed(feature: str, state: Path | str | None) -> Closed | None:
    if not keys.has_key(_key_of(feature)):
        return Closed(503, MSG_OFF, "muse_off")
    return gate(state)


def _day_file(state: Path | str | None) -> Path:
    folder = config.state_root(state) / "muse"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"spend-{quota._today()}.json"


def _prune(folder: Path) -> None:
    for old in sorted(folder.glob("spend-*.json"))[:-KEEP_DAYS]:
        old.unlink(missing_ok=True)


def _count(feature: str, user: str | None, state: Path | str | None) -> None:
    """Add one run's estimate to the day's file and the log, so the spend can be read afterwards. It refuses nothing."""
    usd, who = FEATURE_USD[feature], quota.visitor_key(f"account:{user}") if user else None
    path = _day_file(state)
    with open(path.with_suffix(".lock"), "w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {"site": 0.0, "people": {}}
        doc["site"] = round(doc.get("site", 0.0) + usd, 4)
        if who:
            doc.setdefault("people", {})[who] = round(doc.get("people", {}).get(who, 0.0) + usd, 4)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc), encoding="utf-8")
        os.replace(tmp, path)
        applog.log(f"muse {feature}: admitted, site estimate today {doc['site']:.2f} USD")
    _prune(path.parent)


def status(feature: str, user: str | None = None, state: Path | str | None = None) -> Closed | None:
    """Why `feature` cannot run for `user` now, spending nothing; None when it can. For `can_ask` and the like."""
    if not prod_mode.is_prod():
        return None
    return _closed(feature, state)


def admit(feature: str, user: str | None = None, state: Path | str | None = None) -> Closed | None:
    """Count one run of `feature` and return None, or return why it cannot run. Call only when a model call will follow."""
    if not prod_mode.is_prod():
        return None
    closed = _closed(feature, state)
    if closed is not None:
        applog.log(f"muse {feature}: refused, {closed.code}", level=logging.WARNING)
    else:
        _count(feature, user, state)
    return closed


_APPS: dict[Path, Any] = {}  # app state folder to its app, so a job that holds only a state can ask about a trainer


def bind(app: Any) -> None:
    """`server.build_app`: the queue and identity store `trainer_video_allowed` reads."""
    _APPS[config.state_root(app.state)] = app


def trainer_video_allowed(state: Path | str | None, entry_id: str) -> bool:
    """AC-MP5: a trainer's recording goes to Meta only with that trainer's tick. A person's entry whose job has aged out stays home;
    only an entry nobody owns (the operator's own catalog) goes without an answer. No app on file means no answer: nothing goes."""
    if not consent_record.required():
        return True
    app = _APPS.get(config.state_root(state))
    if app is None:
        return False
    answer = app.queue.trainer_meta_answer(entry_id)
    if answer is not None:
        return answer
    from part7 import auth  # auth imports modules that import this one

    return auth.identity(app).entry_owner(entry_id) is None


def video_allowed(state: Path | str | None, user: str, entry_id: str | None = None) -> bool:
    """AC-MP11, the one question for a path that sends a kept clip or frame to Meta: the account's own choice, which in a gated build
    holds only with the 18 statement (`history_store.consent`), and, when `entry_id` names a trainer's material, that trainer's tick."""
    if not history_store.consent(config.state_root(state), user)["video"]:
        return False
    return entry_id is None or trainer_video_allowed(state, entry_id)


def clear_video(packed: dict[str, Any], state: Path | str | None, user: str, entry_id: str | None = None) -> None:
    """Stamp `packed` with the answer. `history_api.ask` refuses video in a gated build without this stamp, so a new path cannot skip it.
    A teacher's clip with no entry to ask about is refused."""
    teacher = any(item.get("label") == "teacher" for item in packed.get("content") or [])
    packed["video_cleared"] = not (teacher and entry_id is None) and video_allowed(state, user, entry_id if teacher else None)


def part5_env(state: Path | str | None = None) -> dict[str, str]:
    """The env of a Part 5 child in prod: its key and ledger files by path (values never pass through here), and its own cap."""
    if not (prod_mode.is_prod() and switched_on()):
        return {}
    secrets, folder = prod_check.secrets_dir(), config.state_root(state) / "muse"
    return {"PART5_META_KEY_FILE": str(secrets / "MODEL_API_KEY"), "PART5_BASETEN_KEY_FILE": str(secrets / "BASETEN_API_KEY"),
            "PART5_META_USAGE_FILE": str(folder / f"part5-meta-{quota._today()}.jsonl"),
            "PART5_BASETEN_USAGE_FILE": str(folder / f"part5-baseten-{quota._today()}.jsonl"),
            "PART5_META_SPEND_CAP_USD": str(PART5_CAP_UNLIMITED_USD)}
