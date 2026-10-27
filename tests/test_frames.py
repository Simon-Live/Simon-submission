import json
import shutil
import subprocess

import pytest

from part2 import cli, frames

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")


@pytest.fixture
def clip(tmp_path):
    """1 s synthetic video at 10 fps."""
    path = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x48:rate=10",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


@needs_ffmpeg
def test_video_keeps_every_frame_with_its_timestamp(clip, tmp_path):
    recs = frames.ingest(clip, tmp_path / "f")
    assert [r["frame"] for r in recs] == list(range(10))
    assert [r["t_ms"] for r in recs] == pytest.approx([i * 100 for i in range(10)])
    assert all((tmp_path / "f" / r["file"]).is_file() for r in recs)
    assert frames.load(tmp_path / "f") == recs


@needs_ffmpeg
def test_video_resampled_to_fps(clip, tmp_path):
    recs = frames.ingest(clip, tmp_path / "f", fps=5)
    assert len(recs) == 5
    assert [r["t_ms"] for r in recs] == pytest.approx([0, 200, 400, 600, 800])


@needs_ffmpeg
def test_reingest_replaces_old_frames(clip, tmp_path):
    frames.ingest(clip, tmp_path / "f")
    recs = frames.ingest(clip, tmp_path / "f", fps=5)
    assert len(list((tmp_path / "f").glob("*.jpg"))) == len(recs) == 5


@needs_ffmpeg
@pytest.mark.parametrize("fps", [0, -5])
def test_nonpositive_fps_rejected(clip, tmp_path, fps):
    with pytest.raises(ValueError, match="fps must be > 0"):
        frames.ingest(clip, tmp_path / "f", fps=fps)


@needs_ffmpeg
def test_corrupt_video_is_a_clean_error(tmp_path, capsys):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(RuntimeError, match="ffprobe failed"):
        frames.ingest(bad, tmp_path / "f")
    assert cli.main(["frames", "--input", str(bad), "--out", str(tmp_path / "f")]) == 1
    assert "ffprobe failed" in capsys.readouterr().err


@needs_ffmpeg
def test_variable_frame_rate_resample_uses_real_timestamps(tmp_path):
    """5 frames 100 ms apart, then 5 frames 300 ms apart; resampling to 10 fps must keep each
    picked frame's true timestamp, not an assumed i/fps."""
    vfr = tmp_path / "vfr.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10", "-frames:v", "10",
                    "-vf", "settb=1/1000,setpts='if(lt(N,5),N*100,500+(N-5)*300)'", "-fps_mode", "passthrough",
                    "-pix_fmt", "yuv420p", str(vfr)], check=True)
    all_t = [r["t_ms"] for r in frames.ingest(vfr, tmp_path / "all")]
    assert all_t == pytest.approx([0, 100, 200, 300, 400, 500, 800, 1100, 1400, 1700])
    picked = [r["t_ms"] for r in frames.ingest(vfr, tmp_path / "f", fps=10)]
    assert picked == pytest.approx(all_t)  # every source frame is nearest to some 100 ms step, none duplicated
    assert [r["t_ms"] for r in frames.ingest(vfr, tmp_path / "g", fps=2)] == pytest.approx([0, 500, 1100, 1400])


def _image_dir(tmp_path, names):
    d = tmp_path / "imgs"
    d.mkdir()
    for n in names:
        (d / n).write_bytes(b"\xff\xd8fake")
    return d


def test_image_dir_needs_fps_or_manifest(tmp_path):
    d = _image_dir(tmp_path, ["b.jpg", "a.jpg"])
    with pytest.raises(ValueError, match="--fps"):
        frames.ingest(d, tmp_path / "f")
    recs = frames.ingest(d, tmp_path / "f", fps=4)
    assert [(r["frame"], r["t_ms"], r["file"]) for r in recs] == [(0, 0, "000000.jpg"), (1, 250, "000001.jpg")]
    assert (tmp_path / "f" / "000000.jpg").read_bytes() == (d / "a.jpg").read_bytes()


def test_image_dir_uses_its_own_manifest(tmp_path):
    d = _image_dir(tmp_path, ["a.jpg", "b.jpg"])
    (d / "frames.json").write_text(json.dumps({"frames": [{"file": "a.jpg", "frame": 10, "t_ms": 10},
                                                          {"file": "b.jpg", "frame": 20, "t_ms": 45}]}))
    recs = frames.ingest(d, tmp_path / "f")
    assert [(r["frame"], r["t_ms"]) for r in recs] == [(10, 10), (20, 45)]


def test_image_dir_reingest_removes_stale_frames(tmp_path):
    out = tmp_path / "f"
    frames.ingest(_image_dir(tmp_path, ["a.jpg", "b.png", "c.jpg"]), out, fps=1)
    (tmp_path / "one").mkdir()
    (tmp_path / "one" / "x.jpg").write_bytes(b"x")
    recs = frames.ingest(tmp_path / "one", out, fps=1)
    assert sorted(p.name for p in out.iterdir()) == ["000000.jpg", "frames.json"] and len(recs) == 1


def test_cli_run_multi_tracks_then_reports_pending_3d(tmp_path, capsys, monkeypatch):
    from part2 import track

    mask = [[0, 1], [1, 1]]
    monkeypatch.setattr(track, "load_sam31_tracker", lambda: lambda frames_dir, recs: {
        r["frame"]: [{"id": 4, "bbox": [0, 0, 2, 2], "mask": mask, "confidence": 0.9}] for r in recs})
    d = _image_dir(tmp_path, ["a.jpg", "b.jpg"])
    assert cli.main(["run", "--mode", "multi", "--input", str(d), "--out", str(tmp_path / "o"), "--fps", "30"]) == 2
    out = capsys.readouterr()
    assert "1 tracked people" in out.out and "#11" in out.err
    doc = json.loads((tmp_path / "o" / "tracks.json").read_text())
    assert [len(f["people"]) for f in doc["frames"]] == [1, 1]


def test_cli_reports_bad_input(tmp_path, capsys):
    assert cli.main(["frames", "--input", str(tmp_path / "missing.mp4"), "--out", str(tmp_path / "f")]) == 1
    assert "missing.mp4" in capsys.readouterr().err


def test_cli_single_without_gpu_env_says_so(tmp_path, capsys, monkeypatch):
    import builtins

    real_import = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", lambda n, *a, **k: (_ for _ in ()).throw(ImportError(n)) if n == "torch" else real_import(n, *a, **k))
    d = _image_dir(tmp_path, ["a.jpg"])
    assert cli.main(["run", "--mode", "single", "--input", str(d), "--out", str(tmp_path / "o"), "--fps", "30"]) == 1
    assert "GPU environment" in capsys.readouterr().err
