"""The serverless route (deploy/serverless/): opt-in, and the client maps local files to the container's."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from part7 import config, modules, runner
from part7.parts import p2_pose


def _client():
    spec = importlib.util.spec_from_file_location("p2_client", config.REPO_ROOT / "deploy" / "serverless" / "p2_client.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_the_client_uploads_inputs_and_maps_out(tmp_path: Path) -> None:
    clip, tracks = tmp_path / "clip.mp4", tmp_path / "tracks.json"
    clip.write_bytes(b"video")
    tracks.write_text("{}")
    argv, inputs, out = _client().remote_argv(
        ["run", "--mode", "multi", "--input", str(clip), "--out", str(tmp_path / "part2"), "--fps", "10",
         "--tracks", str(tracks), "--ids", "1,2"]
    )
    assert argv == ["run", "--mode", "multi", "--input", "{in}/input.mp4", "--out", "{out}", "--fps", "10",
                    "--tracks", "{in}/tracks.json", "--ids", "1,2"]
    assert inputs == {"input.mp4": b"video", "tracks.json": b"{}"} and out == tmp_path / "part2"


def test_the_route_is_off_unless_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(p2_pose.REMOTE_ENV, raising=False)
    assert p2_pose.remote() is None
    monkeypatch.setenv(p2_pose.REMOTE_ENV, "Modal")
    assert p2_pose.remote() == "modal"


def test_with_modal_part2_runs_through_the_client_without_the_gpu_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(p2_pose.REMOTE_ENV, "modal")
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(runner, "run", lambda part, argv, **kw: calls.append({"argv": argv, **kw}) or runner.Step(exit=0))
    monkeypatch.setattr(p2_pose.gpu_lock, "acquire", lambda **_: pytest.fail("the GPU lock was taken"))
    monkeypatch.setattr(p2_pose, "has_worker", lambda *_: pytest.fail("a local warm worker was probed"))
    lk = modules.load()
    p2_pose.run(tmp_path / "clip.mp4", tmp_path, lock=lk, state=tmp_path)
    argv = calls[0]["argv"]
    assert argv[:5] == ["uv", "run", "--no-project", "--with", p2_pose.MODAL_REQ]
    assert argv[argv.index("--sha") + 1] == lk.sha("2")
    assert argv[argv.index("--") + 1:argv.index("--") + 3] == ["run", "--mode"]
    assert calls[0]["log_path"] == tmp_path / "steps" / "part2.log"


def _routes(monkeypatch: pytest.MonkeyPatch, exits: dict[str, int]) -> list[tuple[str, str]]:
    """Fake both routes: each call records (route, log name) and exits as `exits` says for that route."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(p2_pose.applog, "anomaly", lambda *a, **k: None)
    def on_route(route, sub, backend, work_p, log_name, *rest):
        calls.append((route, log_name))
        return runner.Step(exit=exits[route])
    monkeypatch.setattr(p2_pose, "_on_route", on_route)
    return calls


def _execute(tmp_path: Path) -> runner.Step:
    return p2_pose._execute(["run", "--mode", "single"], "gpu", tmp_path, "part2.log", modules.load(), tmp_path, True, None)


def test_without_the_fallback_a_failed_route_is_not_repeated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(p2_pose.REMOTE_ENV, "modal")
    monkeypatch.delenv(p2_pose.FALLBACK_ENV, raising=False)
    calls = _routes(monkeypatch, {"modal": 2, "local": 0})
    assert _execute(tmp_path)["exit"] == 2 and calls == [("modal", "part2.log")]


def test_with_the_fallback_a_failed_modal_call_runs_on_the_local_gpu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(p2_pose.REMOTE_ENV, "modal")
    monkeypatch.setenv(p2_pose.FALLBACK_ENV, "on")
    calls = _routes(monkeypatch, {"modal": 2, "local": 0})
    step = _execute(tmp_path)
    assert step["exit"] == 0 and step["route"] == "local"
    assert calls == [("modal", "part2.log"), ("local", "part2.fallback.log")], "the second route logs beside the first"


def test_with_the_fallback_a_failed_local_call_runs_on_modal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(p2_pose.REMOTE_ENV, raising=False)
    monkeypatch.setenv(p2_pose.FALLBACK_ENV, "on")
    calls = _routes(monkeypatch, {"modal": 0, "local": 1})
    assert _execute(tmp_path)["route"] == "modal" and calls == [("local", "part2.log"), ("modal", "part2.fallback.log")]


def test_the_fallback_never_repeats_a_success_and_tries_each_route_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(p2_pose.FALLBACK_ENV, "on")
    monkeypatch.setenv(p2_pose.REMOTE_ENV, "modal")
    assert (_routes(monkeypatch, {"modal": 0, "local": 0}), _execute(tmp_path))[0] == [("modal", "part2.log")]
    calls = _routes(monkeypatch, {"modal": 2, "local": 3})
    assert _execute(tmp_path)["exit"] == 3 and len(calls) == 2, "both failed: the second route's failure is reported"
    monkeypatch.setenv(p2_pose.FALLBACK_ENV, "off")
    assert p2_pose.fallback() is False


def test_a_named_tracker_from_the_env_replaces_auto(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(p2_pose.TRACKER_ENV, "local-open")
    calls: list[list[str]] = []
    monkeypatch.setattr(p2_pose, "_execute", lambda sub, *a, **k: calls.append(sub) or runner.Step(exit=0))
    monkeypatch.setattr(p2_pose, "api_tracker_allowed", lambda *a: pytest.fail("the API tracker was considered"))
    p2_pose.track(tmp_path / "clip.mp4", tmp_path, lock=modules.load())
    assert calls[0][-2:] == ["--tracker", "local-open"]


def test_check7_accepts_the_modal_route_instead_of_a_local_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    from part7 import check7
    monkeypatch.setattr(check7, "gpu_visible", lambda: False)
    monkeypatch.setenv(p2_pose.REMOTE_ENV, "modal")
    lk = modules.load()
    monkeypatch.setattr(check7.setup_parts, "setup_all", lambda **_: {"ok": True, "parts": {}})
    monkeypatch.setattr(check7.videos, "verify_all", lambda **_: [])
    assert "nvidia-smi" not in (check7.prerequisites(lk) or "")
    monkeypatch.delenv(p2_pose.REMOTE_ENV)
    assert "nvidia-smi found no GPU" in check7.prerequisites(lk)


def test_part2_fps_switch_and_sam31_retry(monkeypatch):
    """SIMON7_P2_FPS sets the rate Part 2 samples at (people step and 3D step alike); 10 by default.
    A failed local-sam31 run is retried with the free tracker, like api-sam31."""
    import importlib

    from part7.parts import p2_pose

    monkeypatch.delenv("SIMON7_P2_FPS", raising=False)
    assert importlib.reload(p2_pose).FPS == 10
    monkeypatch.setenv("SIMON7_P2_FPS", "5")
    mod = importlib.reload(p2_pose)
    assert mod.FPS == 5
    assert "local-sam31" in mod.REMOTE_RETRIED and "local-sam31" not in mod.RETRIED and mod.LOCAL_TRACKER == "local-open"
    monkeypatch.delenv("SIMON7_P2_FPS")
    importlib.reload(p2_pose)


def test_people_offered_only_when_they_move():
    """A track whose box stays put (a poster, a reflection) is not offered; one that moves is, and is picked
    automatically when it is the only one. A clip where nothing moves keeps everyone."""
    from part7 import people

    def track(pid, boxes):
        return [{"frame": i, "people": [{"id": pid, "bbox": b, "confidence": 0.9}]} for i, b in enumerate(boxes)]

    n = 20
    person = [[200, 100 + (i % 5) * 20, 120, 380 - (i % 5) * 40] for i in range(n)]  # hinges: height and top move
    poster = [[550, 200, 54, 35 + (i % 2)] for i in range(n)]                          # 1 px of jitter
    frames = [{"frame": i, "people": track("0", person)[i]["people"] + track("1", poster)[i]["people"]} for i in range(n)]
    offered = people.summarize(frames, 640, 480)
    assert [p["id"] for p in offered] == ["0"] and offered[0]["motion"] >= people.MIN_MOTION
    assert people.auto_id(offered) == "0"
    still_only = [{"frame": i, "people": track("1", poster)[i]["people"]} for i in range(n)]
    assert [p["id"] for p in people.summarize(still_only, 640, 480)] == ["1"]


def test_tracks_resampled_from_3_to_5_fps():
    """People tracked at 3 fps give the 3D run a box in every 5 fps frame: interpolated in time, mask from the
    nearer tracked frame, nobody invented past a person's last tracked step (#62)."""
    from part7 import track_resample

    def person(x):
        return {"id": 0, "bbox": [x, 100, 50, 200], "mask_rle": {"size": [480, 640], "counts": f"m{x}"}, "confidence": 0.9}

    doc = {"frames": [{"frame": n, "people": [person(100 + 30 * n)]} for n in range(4)],  # t = 0, 1/3, 2/3, 1 s
           "provenance": {"tracker": "local-sam31"}}
    out = track_resample.resample(doc, 3, 5, 1.0)
    assert [f["frame"] for f in out["frames"]] == list(range(7))  # 0..1.2 s at 5 fps
    xs = [f["people"][0]["bbox"][0] if f["people"] else None for f in out["frames"]]
    assert xs[:6] == [100, 118, 136, 154, 172, 190]  # x moves 90 px per second
    assert xs[6] == 190  # 0.2 s past the last tracked frame: held (within one tracked step)
    assert out["frames"][1]["people"][0]["mask_rle"]["counts"] == "m130"  # t 0.2 s: the frame at 1/3 s is nearer than 0 s
    assert out["provenance"]["tracker"] == "local-sam31" and out["provenance"]["resampled"]["to_fps"] == 5


def test_resampled_tracks_cover_exactly_the_frames_part2_samples():
    """Part 2 refuses tracks with more or fewer frames than it samples (its `_check_same_frames`); the resampled
    file follows Part 2's own nearest-frame rule, so a 10 s, 30 fps clip at 5 fps gives 51 frames (the 10.0 s step
    takes the last frame, 9.967 s), not the 52 the old range wrote (#62)."""
    from part7 import track_resample

    pts = [i / 30 for i in range(300)]  # 10 s at 30 fps, last frame at 9.967 s
    times = track_resample.sample_times(pts, 5)
    assert len(times) == 51 and times[0] == 0.0 and abs(times[-1] - 299 / 30) < 1e-6
    doc = {"frames": [{"frame": n, "people": [{"id": 0, "bbox": [10, 10, 50, 100], "mask_rle": {"size": [1, 1], "counts": "a"},
                                               "confidence": 0.9}]} for n in range(30)]}  # tracked at 3 fps
    out = track_resample.resample(doc, 3, 5, 10.0, None, times)
    assert [f["frame"] for f in out["frames"]] == list(range(51))
