"""Helpers of the history tests: real cleared takes as fixtures, and fakes of the sibling lanes' modules.

The fixtures are the stored `analysis.json` and `job.json` of two real takes of `body-squat-19b06562`
(jobs cc7cd5469055, score 100, and 5277380db1e1, score 77), copied from staging read only, host paths shortened.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import types
from typing import Any

import pytest

from part7 import history_store

FIXTURES = Path(__file__).parent / "fixtures" / "history"
ENTRY = "body-squat-19b06562"
USER = "u-0123456789abcdef01234567"
OTHER = "u-fedcba9876543210fedcba98"
FIRST, SECOND = "cc7cd5469055", "5277380db1e1"  # recorded in that order
SESSION_HEADER = "X-Test-User"


def video(path: Path, seconds: float = 2, size: str = "320x240") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=15:duration={seconds}",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=" + str(seconds), "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True, timeout=120)
    return path


def seed_job(state: Path, job_id: str, *, with_video: bool = True, **fields: Any) -> Path:
    """A finished follow job folder in `<state>/jobs` from a real fixture."""
    folder = state / "jobs" / job_id
    (folder / "work" / "follower").mkdir(parents=True, exist_ok=True)
    record = {**json.loads((FIXTURES / job_id / "job.json").read_text(encoding="utf-8")), **fields}
    (folder / "job.json").write_text(json.dumps(record), encoding="utf-8")
    shutil.copyfile(FIXTURES / job_id / "analysis.json", folder / "work" / "follower" / "analysis.json")
    if with_video:
        video(folder / "work" / "video.mp4", 2)
    return folder


def job_record(state: Path, job_id: str) -> dict[str, Any]:
    return json.loads((state / "jobs" / job_id / "job.json").read_text(encoding="utf-8"))


from part7 import auth as _real_auth  # noqa: E402

_real_origin_ok = _real_auth.origin_ok


class World:
    """The sibling lanes' modules as fakes: who owns which job, who opted in, who is signed in."""

    def __init__(self) -> None:
        self.owners: dict[str, str] = {}
        self.opted_in: set[str] = set()
        self.answers: list[Any] = []
        self.asked: list[dict[str, Any]] = []
        self.packs: list[dict[str, Any]] = []
        self.ask_state: list[Any] = []
        self.guard_calls: list[tuple[Any, ...]] = []

    def install(self, mp: pytest.MonkeyPatch) -> None:
        identity = types.ModuleType("part7.identity")
        identity.owner_of_job = lambda state, job_id: self.owners.get(job_id)  # type: ignore[attr-defined]
        identity.retention_opt_in = lambda state, user: user in self.opted_in  # type: ignore[attr-defined]
        auth = types.ModuleType("part7.auth")
        auth.current_user = lambda h: h.headers.get(SESSION_HEADER) or None  # type: ignore[attr-defined]
        auth.origin_ok = _real_origin_ok  # type: ignore[attr-defined]  # the real CSRF guard: it needs no session
        mp.setitem(sys.modules, "part7.identity", identity)
        mp.setitem(sys.modules, "part7.auth", auth)

    def install_model(self, mp: pytest.MonkeyPatch) -> None:
        """`history_api.ask` returns the next queued answer (a string, or an exception to raise)."""
        api = types.ModuleType("part7.history_api")

        def ask(packed: dict[str, Any], *, state: Any = None, **_: Any) -> tuple[str, dict[str, Any]]:
            self.asked.append(packed)
            self.ask_state.append(state)
            nxt = self.answers.pop(0)
            if isinstance(nxt, BaseException):
                raise nxt
            return nxt, {"input_tokens": 1234, "cached_tokens": 0, "output_tokens": 55, "usd": 0.002, "clips_sent": 2}

        class HistoryError(Exception):
            def __init__(self, reason: str, usage: dict[str, Any] | None = None) -> None:
                super().__init__(reason)
                self.reason, self.usage = reason, usage

        api.ask, api.HistoryError = ask, HistoryError  # type: ignore[attr-defined]
        guard = types.ModuleType("part7.history_guard")

        def check(answer: dict[str, Any], facts: Any, narration: Any, words: Any, **_: Any) -> tuple[dict[str, Any], list[Any]]:
            self.guard_calls.append((answer, facts, narration, words))
            return answer, []

        guard.check = check  # type: ignore[attr-defined]
        guard.load_words = lambda: None  # type: ignore[attr-defined]  # the real one reads Part 5's word file, else its defaults
        prompt = types.ModuleType("part7.history_prompt")
        prompt.PROMPT_VERSION = "history.v1"  # type: ignore[attr-defined]

        def pack(entry_id: str, facts: dict[str, Any], rows: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
            """Like lc-history-meta's pack: private rows leave the facts; the rest of the shape is recorded."""
            sent = [r for r in rows if not r.get("private")]
            kept = {**facts, "takes": [t for t in facts["takes"] if t["take"] in {r["take"] for r in sent}]}
            packed = {"entry_id": entry_id, "facts": kept, "rows": rows, **kwargs}
            self.packs.append(packed)
            return packed

        prompt.pack = pack  # type: ignore[attr-defined]
        mp.setitem(sys.modules, "part7.history_prompt", prompt)
        mp.setitem(sys.modules, "part7.history_api", api)
        mp.setitem(sys.modules, "part7.history_guard", guard)


def record_two(state: Path, world: World, user: str = USER) -> None:
    """Both real takes owned by `user`, who opted in, recorded into the history."""
    world.opted_in.add(user)
    for job in (FIRST, SECOND):
        folder = seed_job(state, job)
        world.owners[job] = user
        assert history_store.record_take(state, job_record(state, job), folder)


@pytest.fixture()
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    w = World()
    w.install(monkeypatch)
    return w
