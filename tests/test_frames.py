import json
import shutil
import subprocess
from pathlib import Path

import pytest

from part2 import cli, frames

ROOT = Path(__file__).resolve().parent.parent
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


@needs_ffmpeg
@pytest.mark.parametrize("ext", [".jpg", ".png"])
def test_photo_one_frame(tmp_path, ext, capsys):
    """AC-003: `part2 frames` on one photo (a committed fixture frame, saved as .jpg or .png) writes one record, t_ms 0."""
    from PIL import Image

    photo = tmp_path / f"photo{ext}"
    Image.open(ROOT / "fixtures" / "input" / "single" / "frames" / "000000.jpg").save(photo)
    out = tmp_path / "f"
    assert cli.main(["frames", "--input", str(photo), "--out", str(out)]) == 0
    assert "1 frames ->" in capsys.readouterr().out
    recs = frames.load(out)
    assert recs == [{"frame": 0, "t_ms": 0.0, "file": "000000.jpg"}] and (out / "000000.jpg").is_file()


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


def test_cli_run_multi_without_gpu_env_keeps_tracks(tmp_path, capsys, monkeypatch):
    import builtins

    from part2 import track

    real_import = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", lambda n, *a, **k: (_ for _ in ()).throw(ImportError(n)) if n == "torch" else real_import(n, *a, **k))

    mask = [[0, 1], [1, 1]]
    # the tracker is resolved through part2.trackers: name api-sam31, with a fake key dir and ledger
    keydir = tmp_path / "keys"
    keydir.mkdir(mode=0o700)
    (keydir / "MODEL_API_KEY").write_text("fake")
    (keydir / "MODEL_API_KEY").chmod(0o600)
    monkeypatch.setenv("PART2_KEY_DIR", str(keydir))
    monkeypatch.setenv("PART2_TRACKER", "api-sam31")
    monkeypatch.setenv("META_SPEND_LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setattr(track, "load_sam31_tracker", lambda: lambda frames_dir, recs, **kw: {
        r["frame"]: [{"id": 4, "bbox": [0, 0, 2, 2], "mask": mask, "confidence": 0.9}] for r in recs})
    d = _image_dir(tmp_path, ["a.jpg", "b.jpg"])
    assert cli.main(["run", "--mode", "multi", "--input", str(d), "--out", str(tmp_path / "o"), "--fps", "30"]) == 1
    out = capsys.readouterr()
    assert "1 tracked people" in out.out and "part2: the cpu backend needs" in out.err
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
    assert "part2: the cpu backend needs" in capsys.readouterr().err


# --- AC-C06: t_ms starts at 0 and t0_pts_ms carries the first PTS ---------------------------------

def _offset_clip(tmp_path, offset_s):
    """1 s synthetic video at 10 fps whose first presentation time is `offset_s`."""
    path = tmp_path / f"offset{offset_s}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x48:rate=10",
                    "-pix_fmt", "yuv420p", "-output_ts_offset", str(offset_s), str(path)], check=True)
    return path


@needs_ffmpeg
def test_first_pts_not_zero_gives_t_ms_from_zero_and_t0_pts_ms_equal_to_the_offset(tmp_path):
    recs = frames.ingest(_offset_clip(tmp_path, 2.5), tmp_path / "f")
    assert [r["t_ms"] for r in recs] == pytest.approx([i * 100 for i in range(10)])
    assert frames.load_meta(tmp_path / "f") == {"t0_pts_ms": pytest.approx(2500)}
    manifest = json.loads((tmp_path / "f" / "frames.json").read_text())
    assert manifest["t0_pts_ms"] == pytest.approx(2500) and list(manifest) == ["source", "t0_pts_ms", "frames"]


@needs_ffmpeg
def test_resampling_keeps_the_same_time_origin(tmp_path):
    recs = frames.ingest(_offset_clip(tmp_path, 2.5), tmp_path / "f", fps=5)
    assert [r["t_ms"] for r in recs] == pytest.approx([0, 200, 400, 600, 800])
    assert frames.load_meta(tmp_path / "f")["t0_pts_ms"] == pytest.approx(2500)


@needs_ffmpeg
def test_a_video_that_starts_at_zero_writes_t0_pts_ms_zero(clip, tmp_path):
    frames.ingest(clip, tmp_path / "f")
    assert frames.load_meta(tmp_path / "f") == {"t0_pts_ms": 0}


@needs_ffmpeg
def test_frames_command_writes_t0_pts_ms_that_validates(tmp_path):
    from part2 import contract

    assert cli.main(["frames", "--input", str(_offset_clip(tmp_path, 1.25)), "--out", str(tmp_path / "f")]) == 0
    doc = json.loads((tmp_path / "f" / "frames.json").read_text())
    contract.validate(doc, "frames")
    assert doc["t0_pts_ms"] == pytest.approx(1250)


def test_image_dir_has_no_t0_pts_ms_unless_its_own_manifest_carries_one(tmp_path):
    d = _image_dir(tmp_path, ["a.jpg", "b.jpg"])
    frames.ingest(d, tmp_path / "f", fps=4)
    assert frames.load_meta(tmp_path / "f") == {} and "t0_pts_ms" not in json.loads((tmp_path / "f" / "frames.json").read_text())
    own = [{"file": "a.jpg", "frame": 0, "t_ms": 0}, {"file": "b.jpg", "frame": 1, "t_ms": 40}]
    (d / "frames.json").write_text(json.dumps({"t0_pts_ms": 7.5, "frames": own}))
    frames.ingest(d, tmp_path / "g")
    assert frames.load_meta(tmp_path / "g") == {"t0_pts_ms": 7.5}
    (d / "frames.json").write_text(json.dumps({"t0_pts_ms": "soon", "frames": own}))  # not a number: dropped, not copied
    frames.ingest(d, tmp_path / "h")
    assert frames.load_meta(tmp_path / "h") == {}


def test_manifest_is_written_without_nan(tmp_path):
    from part2.schema import ContractError

    d = _image_dir(tmp_path, ["a.jpg"])
    (d / "frames.json").write_text('{"frames": [{"file": "a.jpg", "frame": 0, "t_ms": NaN}]}')
    with pytest.raises(ContractError, match="frames.json.frames.*NaN or infinity"):
        frames.ingest(d, tmp_path / "f")
    assert not (tmp_path / "f" / "frames.json").exists()


def test_contract_md_states_the_t_ms_rule():
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "CONTRACT.md").read_text()
    assert "t_ms = (pts[k] - pts[0]) * 1000" in text and "t0_pts_ms" in text and "t_ms + t0_pts_ms" in text


@needs_ffmpeg
def test_j06_a_rotate_tagged_mp4_comes_out_upright(tmp_path):
    from PIL import Image

    from part2 import runapi

    plain, tagged = tmp_path / "plain.mp4", tmp_path / "rot.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
                    "-pix_fmt", "yuv420p", str(plain)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-display_rotation", "90", "-i", str(plain), "-c", "copy",
                    str(tagged)], check=True)
    recs = frames.ingest(tagged, tmp_path / "f")
    with Image.open(tmp_path / "f" / recs[0]["file"]) as first:
        assert first.size == (240, 320)
    assert runapi.probe_video(tagged, runapi.Limits()) == ".mp4"


# --- AC-J09 (docs/specs/journey-followup.md, R17): the timestamp read cannot hang --------------------------------

def test_run_waits_without_a_timeout_and_kills_at_one():
    import sys
    import time

    assert frames._run([sys.executable, "-c", "print('ok')"]) == "ok\n"
    started = time.monotonic()
    with pytest.raises(RuntimeError, match=r" timed out after 0\.2 s$"):
        frames._run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.2)
    assert time.monotonic() - started < 3


def test_the_probe_timeout_is_one_named_constant_that_clears_a_60_s_upload():
    assert frames.PROBE_TIMEOUT_S >= 60  # 60 s of 1080p decodes in about 2 s; see the spec for the measurements


def test_a_hung_ffprobe_is_killed_at_the_timeout_and_the_error_names_it(hanging_ffprobe, tmp_path):
    import time

    started = time.monotonic()
    with pytest.raises(RuntimeError, match=r"^ffprobe timed out after 0\.3 s$"):
        frames._probe_timestamps(tmp_path / "stuck.mp4")
    assert time.monotonic() - started < 3 and hanging_ffprobe == [0.3]


@pytest.mark.parametrize("command", ["frames", "track", "run"])
def test_a_hung_ffprobe_is_a_plain_exit_1_line_and_writes_no_frames(hanging_ffprobe, tmp_path, capsys, command):
    stuck, out = tmp_path / "stuck.mp4", tmp_path / "out"
    stuck.write_bytes(b"not read: ffprobe is the thing that hangs")
    extra = ["--mode", "single", "--backend", "cpu"] if command == "run" else []
    code = cli.main([command, "--input", str(stuck), "--out", str(out if command == "frames" else out / "o"), *extra])
    err = capsys.readouterr().err
    assert code == 1 and "part2: ffprobe timed out after 0.3 s" in err and "Traceback" not in err
    assert hanging_ffprobe == [0.3] and not list(out.rglob("*.jpg")) and not list(out.rglob("frames.json"))
