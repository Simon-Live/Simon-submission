"""Part 6 probe for `api/health` that survives a slow child (TICKET-188).

A single 2 s probe that misses under host load must not turn `api/health` into a 503, because the staging
watchdog restarts the app on 503. The last good probe is kept; a miss younger than `SIMON7_HEALTH_PART6_STALE_S`
(default 120) answers ok with `stale_s`. Only a child unreachable for longer than that is reported down.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any, Callable

from part7 import applog, compute_mode, config, selfheal

_SHORT_SHA = re.compile(r"[0-9a-f]{9}")

WARN_EVERY_S = 30.0
PART6 = "part6"


class Part6Probe:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._good_at: float | None = None
        self._entries = 0
        self._warned_at: float | None = None

    def check(self, child: Any) -> tuple[bool, dict[str, Any]]:
        """Probe `child`; return (ok, the `part6` field of the health document)."""
        if child.health() is not None:
            entries = len(child.list_entries())
            with self._lock:
                self._good_at, self._entries = self._clock(), entries
            selfheal.record("health_stale_cache")
            return True, {"ok": True, "entries": entries}
        now = self._clock()
        with self._lock:
            good_at, entries = self._good_at, self._entries
            age = None if good_at is None else now - good_at
            if age is None or age > config.health_part6_stale_s():
                return False, {"ok": False, "entries": 0, "failed": True}
            warn = self._warned_at is None or now - self._warned_at >= WARN_EVERY_S
            if warn:
                self._warned_at = now
        if warn:
            applog.log(f"health: Part 6 probe missed; answering from the last good probe {age:.0f}s old", level=logging.WARNING)
        selfheal.record("health_stale_cache", f"Part 6 probe missed; answered from the last good probe {age:.0f}s old")
        return True, {"ok": True, "entries": entries, "stale_s": round(age)}


def failed_components(up: bool) -> list[str]:
    """What `api/health` names as failed. Fixed names only: the answer is public and holds no detail of the fault."""
    return [] if up else [PART6]


def public_doc(up: bool, sha: str, draining: bool, owner: bool) -> dict[str, Any]:
    """The `api/health` answer a stranger gets in prod (APP-L2): no pins, queue, GPU, spend or self-heal.

    Holds what firm/prod/CONTRACT.md "Health line" needs: `sha` (the full commit, which the promotion compares) and
    `compute`; under byok also `byok_idle_ttl_s` (the BYOK lane's TTL, through `config.byok_idle_ttl_s`), and in serverless
    mode `compute_provider` (serverless-compute.md AC-SC14).
    """
    doc: dict[str, Any] = {"ok": up, "sha": sha, "draining": draining, "jobs": "run" if owner else "standby"}
    if not up:
        doc["failed"] = failed_components(up)
    if compute_mode.serverless():
        return {**doc, "compute": compute_mode.SERVERLESS, "compute_provider": compute_mode.PROVIDER}
    return {**doc, "compute": os.environ.get("PROD_COMPUTE", "").strip() or "byok", "byok_idle_ttl_s": config.byok_idle_ttl_s()}


def public_build(build: dict[str, Any]) -> dict[str, Any]:
    """The `api/version` answer in prod: the commit, when this build started and the short sha of each part module (read
    from its `.firm-sha`). A release tree has no `.git`, so it has no commit time or subject: those keys are left out."""
    parts = build.get("parts") if isinstance(build.get("parts"), dict) else {}
    return {"sha": build.get("sha", "unknown"), "short": build.get("short", "unknown"),
            "started_at": build.get("started_at", "unknown"),
            "parts": {str(k): v for k, v in parts.items() if isinstance(v, str) and _SHORT_SHA.fullmatch(v)}, "environment": "prod"}
