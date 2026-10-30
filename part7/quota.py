"""Per-visitor quota and daily GPU caps, counters on disk under `<state>/quota/` (app.md "Quotas and spend")."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Callable

from part7 import config

VISITOR_MESSAGE = "You have used today's analyses. Try again tomorrow."
DAILY_MESSAGE = "The app has reached today's limit. Try again tomorrow."
KEEP_DAYS = 3


class VisitorQuotaError(Exception):
    """The visitor used today's allowance (HTTP 429)."""


class DailyCapError(Exception):
    """The app reached today's GPU or trainer cap (HTTP 503)."""


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def limits_on() -> bool:
    """Daily and per-visitor caps apply only with SIMON7_LIMITS=on (off by default during testing)."""
    return os.environ.get("SIMON7_LIMITS", "off").strip().lower() == "on"


def visitor_key(visitor: str | None) -> str | None:
    """Return a short hash of the visitor address; the address itself is never stored."""
    if not visitor:
        return None
    return hashlib.sha256(visitor.encode("utf-8")).hexdigest()[:16]


class Quota:
    """Counts GPU jobs per UTC day, in total and per visitor. A trainer job also counts as a GPU job."""

    def __init__(
        self,
        state: Path | str,
        *,
        daily_gpu: int | None = None,
        daily_trainer: int | None = None,
        visitor_gpu: int = config.VISITOR_GPU_PER_DAY,
        visitor_trainer: int = config.VISITOR_TRAINER_PER_DAY,
        today: Callable[[], str] = _today,
    ) -> None:
        self.dir = Path(state) / "quota"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.daily_gpu = (
            daily_gpu if daily_gpu is not None else _env_int("SIMON7_DAILY_GPU", config.DAILY_GPU_JOBS_LIMIT)
        )
        self.daily_trainer = (
            daily_trainer
            if daily_trainer is not None
            else _env_int("SIMON7_DAILY_TRAINER", config.DAILY_TRAINER_JOBS_LIMIT)
        )
        self.visitor_gpu = visitor_gpu
        self.visitor_trainer = visitor_trainer
        self._today = today
        self._lock = threading.Lock()

    def _path(self) -> Path:
        return self.dir / f"{self._today()}.json"

    def _load(self) -> dict:
        try:
            doc = json.loads(self._path().read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                doc.setdefault("gpu", 0)
                doc.setdefault("trainer", 0)
                doc.setdefault("visitors", {})
                return doc
        except (OSError, ValueError):
            pass
        return {"gpu": 0, "trainer": 0, "visitors": {}}

    def _save(self, doc: dict) -> None:
        path = self._path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc), encoding="utf-8")
        tmp.replace(path)
        for old in sorted(self.dir.glob("????-??-??.json"))[:-KEEP_DAYS]:
            old.unlink(missing_ok=True)

    def gpu_jobs_today(self) -> int:
        with self._lock:
            return int(self._load()["gpu"])

    def reserve(self, kind: str, visitor: str | None) -> None:
        """Count one job of `kind` (`trainer` or `follow`) or raise; `visitor` None skips the visitor quota."""
        key = visitor_key(visitor)
        with self._lock:
            doc = self._load()
            if not limits_on():  # operator 2026-10-30: no limits during heavy testing; jobs are still counted
                self._bump(doc, doc["visitors"].setdefault(key, {"gpu": 0, "trainer": 0}) if key else None, kind, 1)
                self._save(doc)
                return
            if doc["gpu"] >= self.daily_gpu or (kind == "trainer" and doc["trainer"] >= self.daily_trainer):
                raise DailyCapError(DAILY_MESSAGE)
            mine = doc["visitors"].setdefault(key, {"gpu": 0, "trainer": 0}) if key else None
            if mine is not None and (
                mine["gpu"] >= self.visitor_gpu or (kind == "trainer" and mine["trainer"] >= self.visitor_trainer)
            ):
                raise VisitorQuotaError(VISITOR_MESSAGE)
            self._bump(doc, mine, kind, 1)
            self._save(doc)

    def release(self, kind: str, visitor: str | None) -> None:
        """Undo one `reserve` (the job never entered the queue)."""
        key = visitor_key(visitor)
        with self._lock:
            doc = self._load()
            self._bump(doc, doc["visitors"].get(key) if key else None, kind, -1)
            self._save(doc)

    @staticmethod
    def _bump(doc: dict, mine: dict | None, kind: str, delta: int) -> None:
        for target in (doc, mine):
            if target is None:
                continue
            target["gpu"] = max(0, target["gpu"] + delta)
            if kind == "trainer":
                target["trainer"] = max(0, target["trainer"] + delta)
