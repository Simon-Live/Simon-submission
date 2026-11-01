"""A refused Meta credential must not fail every take: api-sam31 falls back to `--tracker local-open`.

Reported on moalborati/simon#61: the retry used Part 2's default order, which tried api-sam31 again, and both
attempts wrote one log. The retry names `local-open` and has its own log; a double failure names both reasons.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

import pytest

from part7 import runner
from part7.parts import p2_pose
from support import Api
from test_clip_size import _log, wide_mp4  # noqa: F401 (fixture)
from test_gpu_wait import _Lock
from test_people import VISITOR, Fakes, _people_job, tracks_doc

REFUSED = "the credential was refused"
NO_GPU = "local-open could not load its model"


class _Part2:
    """Fake `part2 track`: refuses api-sam31 and the default order (it tries api-sam31 first); local-open obeys `local_ok`."""

    def __init__(self, mp: pytest.MonkeyPatch, local_ok: bool = True) -> None:
        self.local_ok = local_ok
        self.argvs: list[list[str]] = []
        self.real = runner.run
        mp.setattr(runner, "run", self.run)
        mp.setattr(p2_pose, "api_tracker_allowed", lambda *a, **k: True)
        # TICKET-191: the GPU is not the subject here; a full host card must not fail these tests.
        mp.setattr(p2_pose.gpu_lock, "acquire", lambda **kw: contextlib.nullcontext())

    def run(self, part: int, argv: list[str], **kw: Any) -> runner.Step:
        if "track" not in argv or "--input" not in argv:
            return self.real(part, argv, **kw)
        self.argvs.append(argv)
        tracker = argv[argv.index("--tracker") + 1] if "--tracker" in argv else None
        ok = tracker == "local-open" and self.local_ok
        text = f"tracker {tracker}: " + ("ok" if ok else (NO_GPU if tracker == "local-open" else REFUSED)) + "\n"
        log = Path(kw["log_path"])
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(text, encoding="utf-8")
        if ok:
            out = Path(argv[argv.index("--out") + 1])
            (out / "tracks.json").write_text(json.dumps(tracks_doc({0: 20})), encoding="utf-8")
        return runner.Step(part=2, argv=argv, exit=0 if ok else 1, timed_out=False, duration_s=0.0, log=str(log),
                           stdout=text)

    def trackers(self) -> list[str | None]:
        return [a[a.index("--tracker") + 1] if "--tracker" in a else None for a in self.argvs]


def _with_lock(mp: pytest.MonkeyPatch, real_track: Any) -> None:
    mp.setattr(p2_pose, "track", lambda clip, work, **kw: real_track(clip, work, **{**kw, "lock": _Lock(Path(work))}))


def test_a_refused_api_tracker_retries_with_local_open_and_its_own_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _Part2(monkeypatch)
    work = tmp_path / "work"
    step, tracks = p2_pose.track(tmp_path / "clip.mp4", work, lock=_Lock(tmp_path))
    assert fake.trackers() == [p2_pose.API_TRACKER, "local-open"]  # never Part 2's default order
    assert step["exit"] == 0 and tracks.is_file() and step["first_try"]["exit"] == 1
    first, retry = work / "steps" / "part2_track.api.log", work / "steps" / "part2_track_retry.log"
    assert step["log"] == str(retry) and step["first_try"]["log"] == str(first)
    assert REFUSED in first.read_text(encoding="utf-8") and "tracker local-open: ok" in retry.read_text(encoding="utf-8")
    assert not (work / "steps" / "part2_track.log").exists()


def test_a_named_non_api_tracker_keeps_its_default_order_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _Part2(monkeypatch)
    p2_pose.track(tmp_path / "clip.mp4", tmp_path / "work", lock=_Lock(tmp_path), tracker="local-sam31", acquire_lock=False)
    assert fake.trackers() == ["local-sam31", None]


def test_a_take_is_analysed_when_the_api_credential_is_refused(api: Api, wide_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_track = p2_pose.track  # before `Fakes` replaces it
    Fakes(monkeypatch, {0: 20})
    fake = _Part2(monkeypatch)
    _with_lock(monkeypatch, real_track)
    monkeypatch.setenv(p2_pose.TRACK_FPS_ENV, "10")  # the fake's still box is no participant: no TICKET-198 repeat at 10 fps
    job = _people_job(api, wide_mp4)
    assert job["status"] == "done", job
    assert fake.trackers() == [p2_pose.API_TRACKER, "local-open"]


def test_both_trackers_failing_names_both_reasons_and_both_logs(api: Api, wide_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_track = p2_pose.track  # before `Fakes` replaces it
    Fakes(monkeypatch, {0: 20})
    _Part2(monkeypatch, local_ok=False)
    _with_lock(monkeypatch, real_track)
    status, up = api.upload(wide_mp4)
    assert status == 201
    status, doc = api.json("POST", "api/people", {"upload_id": up["upload_id"]}, VISITOR)
    assert status == 202, doc
    job = api.app.queue.wait(doc["job"], 60)
    assert job and job["status"] == "failed", job
    assert REFUSED in job["error"] and NO_GPU in job["error"], job
    text = _log(api, job)
    assert "part2_track.api.log" in text and "part2_track_retry.log" in text


def test_the_wait_deadline_grows_with_host_load_and_never_shrinks(monkeypatch: pytest.MonkeyPatch) -> None:
    from support import load_scaled

    monkeypatch.setattr("os.cpu_count", lambda: 8)
    monkeypatch.setattr("os.getloadavg", lambda: (0.5, 0.0, 0.0))
    assert load_scaled(60) == 60
    monkeypatch.setattr("os.getloadavg", lambda: (16.0, 0.0, 0.0))
    assert load_scaled(60) == 240
    monkeypatch.setattr("os.getloadavg", lambda: (800.0, 0.0, 0.0))
    assert load_scaled(60) == 600  # capped
