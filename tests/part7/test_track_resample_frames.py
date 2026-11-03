"""TICKET-203: the resampled tracks have exactly the frames Part 2 samples from the 3D input, and a refusal by Part 2
for a frame mismatch is answered with one re-track at the 3D rate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from part7 import people, track_resample
from part7.parts import p2_pose

PART2 = Path(__file__).resolve().parents[2] / "modules" / "part-2"


def _real_clip(tmp_path: Path, duration: float, fps: int) -> Path:
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None or not (PART2 / "part2").is_dir():
        pytest.skip("needs ffmpeg and modules/part-2")
    clip = tmp_path / f"c_{duration}_{fps}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=64x48:rate={fps}:duration={duration}",
                    "-pix_fmt", "yuv420p", str(clip)], check=True)
    return clip


def _part2_times(clip: Path, tmp_path: Path) -> list[float]:
    """The frames `part2 frame-times` lists (the CLI; Part 2 is never imported)."""
    from part7 import modules

    listed = p2_pose.frame_times(clip, tmp_path / "w", 10, modules.load())
    if listed is None:
        pytest.skip("the pinned Part 2 has no frame-times")
    return listed


def _box(n: int) -> dict[str, Any]:
    return {"id": 0, "bbox": [n, 10, 50, 100], "mask_rle": {"size": [4, 4], "counts": "x"}, "confidence": 0.9}


def _doc(frames: int) -> dict[str, Any]:
    return {"frames": [{"frame": n, "people": [_box(n)]} for n in range(frames)]}


@pytest.mark.gpu_host
@pytest.mark.parametrize("duration", [8.6, 8.65, 8.69, 12.0, 6.966])
@pytest.mark.parametrize("source_fps", [25, 30])
def test_resampled_count_equals_part_2_sampled_count(duration: float, source_fps: int, tmp_path: Path) -> None:
    clip = _real_clip(tmp_path, duration, source_fps)
    expected = len(_part2_times(clip, tmp_path))
    at = track_resample.probe_sample_times(clip, 10)
    assert at is not None and len(at) == expected and at == pytest.approx(_part2_times(clip, tmp_path), abs=1e-3)
    out = track_resample.resample(_doc(int(duration * 3) + 1), 3, 10, duration, None, at)
    assert [f["frame"] for f in out["frames"]] == list(range(expected))
    assert abs(len(track_resample.uniform_sample_times(duration, source_fps, 10)) - expected) <= 1  # last resort: an estimate


def test_regression_job_b2edf38e4ede_86_frames_not_87() -> None:
    """The follower input of job b2edf38e4ede: Part 2 sampled 86 frames at 10 fps; the old count
    floor(duration * fps) + 2 made 87 and `part2 run --tracks` exited 1."""
    pts = [k / 30 for k in range(255)]  # the job input: 255 frames at 30 fps, 8.5 s
    at = track_resample.sample_times(pts, 10)
    assert len(at) == 86
    old = int(8.5 * 10) + 2
    assert old == 87
    out = track_resample.resample(_doc(26), 3, 10, 8.5, None, at)
    assert len(out["frames"]) == 86 and out["frames"][-1]["frame"] == 85
    assert all(f["people"] for f in out["frames"])  # a person present throughout has a box in every Part 2 frame


def test_frame_times_follow_the_timestamps_not_an_even_grid() -> None:
    pts = [0.5 + k / 30 for k in range(31)]  # a clip whose first frame is not at 0
    at = track_resample.sample_times(pts, 5)
    assert at[0] == 0.0 and at[1] == pytest.approx(0.2, abs=0.02)


def test_probe_failure_gives_none(tmp_path: Path) -> None:
    assert track_resample.probe_sample_times(tmp_path / "missing.mp4", 10) is None


class _Lock:
    def sha12(self, _n: Any) -> str:
        return "x"


def _wire(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, retrack_ids: list[int], runs: list[dict[str, Any]]):
    work = tmp_path / "job"
    (work / "steps").mkdir(parents=True)
    pw = tmp_path / "people"
    pw.mkdir()
    (pw / "tracks.json").write_text(json.dumps(_doc(10)), encoding="utf-8")
    (pw / "track_fps.json").write_text(json.dumps({"fps": 3, "mode": "single"}), encoding="utf-8")
    monkeypatch.setattr(track_resample, "probe_sample_times", lambda v, f: [i / 10 for i in range(87)])
    monkeypatch.setattr(p2_pose, "frame_times", lambda v, w, f, lk=None: None)  # the pin lacks `frame-times`: the copied rule
    monkeypatch.setattr(people.media, "probe", lambda v: {"duration_s": 8.6, "fps": 30})
    monkeypatch.setattr(p2_pose, "capabilities", lambda lk, st: {"ids": True, "track": True})

    def run(video: Any, w: Path, tracks: Path | None = None, **kw: Any) -> tuple[dict[str, Any], Path]:
        frames = len(json.loads(Path(tracks).read_text(encoding="utf-8"))["frames"])
        runs.append({"tracks": Path(tracks), "frames": frames})
        bad = len(runs) == 1
        (w / "steps" / "part2.log").write_text(
            "part2: --tracks t.json has an entry for frame 86 that this input lacks (it covers 87 frames)" if bad else "ok",
            encoding="utf-8")
        return ({"exit": 1 if bad else 0}, w / "part2" / "pose3d.json")

    def track(video: Any, w: Path, **kw: Any) -> tuple[dict[str, Any], Path]:
        w.mkdir(parents=True, exist_ok=True)
        doc = {"frames": [{"frame": 0, "people": [{"id": i, "bbox": [0, 0, 1, 1]} for i in retrack_ids]}]}
        (w / "tracks.json").write_text(json.dumps(doc), encoding="utf-8")
        return ({"exit": 0}, w / "tracks.json")

    monkeypatch.setattr(p2_pose, "run", run)
    monkeypatch.setattr(p2_pose, "track", track)
    return people.PersonSel(id="0", people_work=pw), work


def test_pose_for_retracks_once_at_the_3d_rate_when_part_2_refuses(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runs: list[dict[str, Any]] = []
    sel, work = _wire(monkeypatch, tmp_path, [0], runs)
    step, _pose, _note = people.pose_for(sel, ["0"], tmp_path / "v.mp4", work, "gpu", _Lock(), None)  # type: ignore[arg-type]
    assert step["exit"] == 0 and len(runs) == 2
    assert runs[0]["frames"] == 87 and runs[1]["tracks"].parent.name == "retrack_3d"


def test_pose_for_keeps_the_failure_when_the_retrack_loses_the_person(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runs: list[dict[str, Any]] = []
    sel, work = _wire(monkeypatch, tmp_path, [7], runs)
    step, _pose, _note = people.pose_for(sel, ["0"], tmp_path / "v.mp4", work, "gpu", _Lock(), None)  # type: ignore[arg-type]
    assert step["exit"] == 1 and len(runs) == 1


def test_write_at_rate_with_a_video_writes_part_2s_frames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(track_resample, "probe_pts", lambda v: [k / 30 for k in range(255)])
    src, dst = tmp_path / "t.json", tmp_path / "o.json"
    src.write_text(json.dumps(_doc(26)), encoding="utf-8")
    track_resample.write_at_rate(src, dst, 3, 10, 8.5, None, video=tmp_path / "v.mp4")
    assert len(json.loads(dst.read_text(encoding="utf-8"))["frames"]) == 86


def test_pose_for_uses_part_2_frame_times_when_the_pin_has_them(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Job b2edf38e4ede: Part 2 lists 86 frames where the old count made 87; the file follows Part 2's listing."""
    runs: list[dict[str, Any]] = []
    sel, work = _wire(monkeypatch, tmp_path, [0], runs)
    monkeypatch.setattr(p2_pose, "frame_times", lambda v, w, f, lk=None: [i / 10 for i in range(86)])
    monkeypatch.setattr(track_resample, "probe_sample_times", lambda v, f: pytest.fail("the copied rule is the fallback only"))
    people.pose_for(sel, ["0"], tmp_path / "v.mp4", work, "gpu", _Lock(), None)  # type: ignore[arg-type]
    assert runs[0]["frames"] == 86


def test_regression_121_not_122() -> None:
    """A 12.0 s, 30 fps input at 10 fps: Part 2 samples 121 frames (the 12.0 s step takes the last frame), the old
    count floor(12.0 * 10) + 2 wrote 122."""
    at = track_resample.sample_times([k / 30 for k in range(360)], 10)
    assert len(at) == 121 and int(12.0 * 10) + 2 == 122
    assert len(track_resample.resample(_doc(37), 3, 10, 12.0, None, at)["frames"]) == 121


@pytest.mark.gpu_host
def test_frame_times_from_the_part_2_command_on_a_real_clip(tmp_path: Path) -> None:
    """`p2_pose.frame_times` (the `part2 frame-times` CLI, no Python import) equals the copied rule on a real clip."""
    import shutil
    import subprocess

    from part7 import modules

    if shutil.which("ffmpeg") is None or not (PART2 / "part2").is_dir():
        pytest.skip("needs ffmpeg and modules/part-2")
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=30:duration=8.5",
                    "-pix_fmt", "yuv420p", str(clip)], check=True)
    listed = p2_pose.frame_times(clip, tmp_path / "w", 10, modules.load())
    if listed is None:
        pytest.skip("the pinned Part 2 has no frame-times")
    assert len(listed) == 86
    assert listed == pytest.approx(track_resample.probe_sample_times(clip, 10), abs=1e-3)


def test_frame_times_is_none_when_there_is_no_part_2_checkout(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """TICKET-328: a missing Part 2 directory is the same answer as a pin without `frame-times`, not a crash."""
    from part7 import modules

    lk = modules.Modules(root=tmp_path / "no-modules", shas={"2": "2" * 40})
    with caplog.at_level("INFO", logger="part7"):
        assert p2_pose.frame_times(tmp_path / "clip.mp4", tmp_path / "w", 10, lk) is None
    assert "part 2 frame-times: no Part 2 checkout at part-2, using Part 7's rule" in caplog.text
