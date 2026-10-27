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
    (d / "frames.json").write_text(json.dumps({"frames": [{"file": "a.jpg", "t_ms": 10}, {"file": "b.jpg", "t_ms": 45}]}))
    recs = frames.ingest(d, tmp_path / "f")
    assert [r["t_ms"] for r in recs] == [10, 45]


def test_cli_run_is_honest_about_pending_stages(tmp_path, capsys):
    d = _image_dir(tmp_path, ["a.jpg"])
    assert cli.main(["run", "--mode", "multi", "--input", str(d), "--out", str(tmp_path / "o"), "--fps", "30"]) == 2
    assert "#10" in capsys.readouterr().err
    assert (tmp_path / "o" / "frames" / "frames.json").is_file()


def test_cli_reports_bad_input(tmp_path, capsys):
    assert cli.main(["frames", "--input", str(tmp_path / "missing.mp4"), "--out", str(tmp_path / "f")]) == 1
    assert "missing.mp4" in capsys.readouterr().err
