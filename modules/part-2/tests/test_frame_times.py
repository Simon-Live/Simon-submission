"""frame-times: the sampled frame times equal what `run`/`track` write (frames.ingest), docs/specs/frame-times.md."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from part2 import cli, contract, frame_times, frames

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")


def _make(path: Path, seconds: int, vf: str | None = None) -> Path:
    cmd = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=64x48:rate=30"]
    cmd += (["-vf", vf, "-fps_mode", "vfr"] if vf else []) + ["-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture(scope="module")
def cfr(tmp_path_factory):
    return _make(tmp_path_factory.mktemp("v") / "cfr.mp4", 10)


@pytest.fixture(scope="module")
def vfr(tmp_path_factory):
    """30 fps source with frames dropped in an irregular pattern, so the timestamps have gaps."""
    return _make(tmp_path_factory.mktemp("v") / "vfr.mp4", 6, vf="select='lt(mod(n,7),4)+eq(mod(n,11),0)'")


def _ingested(clip, tmp_path, fps):
    frames.ingest(clip, tmp_path / "f", fps)
    return json.loads((tmp_path / "f" / "frames.json").read_text())


@needs_ffmpeg
def test_ac1_ten_seconds_at_5_fps_is_51_frames_equal_to_ingest(cfr, tmp_path):
    doc = frame_times.frame_times(cfr, 5)
    assert len(doc["frames"]) == 51
    assert doc == _ingested(cfr, tmp_path, 5)


@needs_ffmpeg
@pytest.mark.parametrize("fps", [None, 3, 7.5, 10, 24])
def test_ac2_equal_to_ingest_for_other_rates_and_no_fps(cfr, tmp_path, fps):
    assert frame_times.frame_times(cfr, fps) == _ingested(cfr, tmp_path, fps)


@needs_ffmpeg
@pytest.mark.parametrize("fps", [None, 3, 5, 12])
def test_ac3_variable_frame_rate_equal_to_ingest(vfr, tmp_path, fps):
    pts = frames._probe_timestamps(vfr)
    gaps = {round(b - a, 3) for a, b in zip(pts, pts[1:])}
    assert len(gaps) > 1, "the fixture must really be variable frame rate"
    assert frame_times.frame_times(vfr, fps) == _ingested(vfr, tmp_path, fps)


@needs_ffmpeg
def test_ac4_document_passes_the_frames_contract(cfr):
    contract.validate(frame_times.frame_times(cfr, 5), "frames")


@needs_ffmpeg
def test_ac5_cli_prints_the_document(cfr, capsys):
    assert cli.main(["frame-times", "--input", str(cfr), "--fps", "5"]) == 0
    assert json.loads(capsys.readouterr().out) == frame_times.frame_times(cfr, 5)


@needs_ffmpeg
def test_ac5_cli_out_writes_the_same_bytes_as_ingest(cfr, tmp_path, capsys):
    out = tmp_path / "sub" / "times.json"
    assert cli.main(["frame-times", "--input", str(cfr), "--fps", "5", "--out", str(out)]) == 0
    frames.ingest(cfr, tmp_path / "f", 5)
    assert out.read_bytes() == (tmp_path / "f" / "frames.json").read_bytes()
    assert "51 frames" in capsys.readouterr().out


@needs_ffmpeg
def test_ac6_writes_no_images(cfr, tmp_path):
    cli.main(["frame-times", "--input", str(cfr), "--fps", "5", "--out", str(tmp_path / "t.json")])
    assert [p.name for p in tmp_path.iterdir()] == ["t.json"]


def test_ac7_sample_times_is_the_private_rule():
    pts = [0.0, 0.03, 0.07, 0.1, 0.4, 0.43, 0.5]
    assert frame_times.sample_times(pts, 5) == frames._nearest_per_step(pts, 5)
    assert frame_times.sample_times(pts) == list(range(7))


@pytest.mark.parametrize("fps", [0, -3])
def test_ac8_nonpositive_fps_is_exit_1(tmp_path, fps, capsys):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    assert cli.main(["frame-times", "--input", str(clip), "--fps", str(fps)]) == 1
    assert "fps must be > 0" in capsys.readouterr().err
    with pytest.raises(ValueError, match="fps must be > 0"):
        frame_times.sample_times([0.0, 1.0], fps)


def test_ac8_missing_file_and_directory_and_empty_pts(tmp_path, capsys):
    assert cli.main(["frame-times", "--input", str(tmp_path / "none.mp4")]) == 1
    assert "none.mp4" in capsys.readouterr().err
    assert cli.main(["frame-times", "--input", str(tmp_path)]) == 1
    assert "is a directory" in capsys.readouterr().err
    with pytest.raises(ValueError, match="no video frames"):
        frame_times.sample_times([], 5)


@needs_ffmpeg
def test_ac8_a_file_that_is_not_a_video_is_exit_1(tmp_path, capsys):
    bad = tmp_path / "bad.mp4"
    bad.write_text("not a video")
    assert cli.main(["frame-times", "--input", str(bad), "--fps", "5"]) == 1
    assert capsys.readouterr().err.startswith("part2:")


def test_ac8_missing_input_option_is_exit_2(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["frame-times", "--fps", "5"])
    assert e.value.code == 2
