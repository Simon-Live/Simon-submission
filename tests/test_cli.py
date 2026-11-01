"""`part2 run` writer rules (AC-C05 to AC-C08 at the command line) and the contract and doctor commands.

The GPU stages are replaced by fakes: a stand-in `torch` module and a `body3d.estimate` that writes a
body3d.json for the frames it is given. Everything after that (canonical frame, contract checks, files)
is the real code."""
import contextlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_canonical import _body3d

from conftest import fake_key
from part2 import backends, body3d, cli, contract, frames, gpu_guard, output_steps, track, trackers
from part2.schema import ContractError

ROOT = Path(__file__).resolve().parent.parent
needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")
NAN = float("nan")


def _image_dir(tmp_path, n=2):
    d = tmp_path / "imgs"
    d.mkdir()
    for i in range(n):
        (d / f"{i:03d}.jpg").write_bytes(b"\xff\xd8fake")
    return d


def _fake_estimate(frames_dir, out_path, boxes=None, estimator=None):
    recs = frames.load(frames_dir)
    doc = _body3d([0] * len(recs))
    for f, r in zip(doc["frames"], recs):
        f["frame"], f["t_ms"] = r["frame"], r["t_ms"]
        template = f["people"][0]
        ids = [0] if boxes is None else list(boxes.get(r["frame"], {}))
        f["people"] = [{**template, "id": pid} for pid in ids]
    Path(out_path).write_text(json.dumps(doc))
    return doc


class _FakeBackend:
    """Stands in for the registry's gpu backend; estimate goes through body3d.estimate so tests can fake it."""
    name = "gpu"

    def available(self):
        return True, ""

    def provenance(self):
        return {"backend": "gpu", "detector": "fake", "models": [{"name": "fake-3d", "source": "test", "weights_sha256": None}]}

    def estimate(self, frames_dir, out_path, boxes=None):
        return body3d.estimate(frames_dir, out_path, boxes=boxes)


def _use_fake_backend(monkeypatch, estimate=None):
    monkeypatch.setattr(backends, "get", lambda name: _FakeBackend())
    monkeypatch.setattr(backends, "resolve", lambda flag=None: flag or "gpu")
    monkeypatch.setattr(body3d, "estimate", estimate or _fake_estimate)
    fake_key("MODEL_API_KEY")


@pytest.fixture
def gpu(monkeypatch):
    """Pretend the GPU backend and the SAM 3.1 API tracker exist (a fake key, a fake API client)."""
    _use_fake_backend(monkeypatch)
    mask = [[0, 1], [1, 1]]
    monkeypatch.setattr(track, "load_sam31_tracker", lambda: lambda frames_dir, recs, **_: {
        r["frame"]: [{"id": i, "bbox": [0, 0, 2, 2], "mask": mask, "confidence": 0.9} for i in (4, 5)] for r in recs})


def _run(tmp_path, *extra, mode="single", src=None, name="out"):
    out = tmp_path / name
    code = cli.main(["run", "--mode", mode, "--input", str(src or _image_dir(tmp_path)), "--out", str(out), "--fps", "10", *extra])
    return code, out


def _load(path):
    return json.loads(Path(path).read_text())


# --- AC-C05: --mirrored -------------------------------------------------------------------------

def test_run_mirrored_writes_true_and_part3_doctor_accepts_it(gpu, tmp_path, capsys):
    code, out = _run(tmp_path, "--mirrored")
    assert code == 0
    pose = _load(out / "pose3d.json")
    assert pose["mirrored"] is True
    contract.validate(pose, "pose3d")
    contract.validate_part3(pose)
    assert cli.main(["doctor", str(out / "pose3d.json"), "--for", "part3"]) == 0
    assert "mirrored: Part 3 --flip auto" in capsys.readouterr().out


def test_run_without_mirrored_leaves_the_key_out(gpu, tmp_path):
    code, out = _run(tmp_path)
    assert code == 0 and "mirrored" not in _load(out / "pose3d.json")


def test_run_multi_mirrored_reaches_the_combined_and_per_person_files_but_not_tracks(gpu, tmp_path):
    code, out = _run(tmp_path, "--mirrored", mode="multi")
    assert code == 0
    for name in ("pose3d.json", "pose3d_person_0.json", "pose3d_person_1.json"):
        assert _load(out / name)["mirrored"] is True
    assert "mirrored" not in _load(out / "tracks.json")


# --- AC-C06: t0_pts_ms through the pipeline ----------------------------------------------------

@needs_ffmpeg
def test_run_copies_t0_pts_ms_into_pose3d_and_tracks(gpu, tmp_path):
    clip = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x48:rate=10", "-pix_fmt", "yuv420p",
                    "-output_ts_offset", "3", str(clip)], check=True)
    single, out_single = _run(tmp_path, src=clip, name="single")
    multi, out_multi = _run(tmp_path, mode="multi", src=clip, name="multi")
    assert single == multi == 0
    for doc in (_load(out_single / "pose3d.json"), _load(out_multi / "pose3d.json"), _load(out_multi / "tracks.json"),
                _load(out_multi / "pose3d_person_0.json")):
        assert doc["t0_pts_ms"] == pytest.approx(3000)
    assert _load(out_single / "pose3d.json")["frames"][0]["t_ms"] == 0


def test_an_image_directory_run_writes_no_t0_pts_ms(gpu, tmp_path):
    _, out = _run(tmp_path)
    assert "t0_pts_ms" not in _load(out / "pose3d.json")


# --- AC-C08: provenance names what ran ---------------------------------------------------------

def test_single_run_provenance_names_the_gpu_backend_and_no_tracker(gpu, tmp_path):
    _, out = _run(tmp_path)
    prov = _load(out / "pose3d.json")["provenance"]
    assert (prov["backend"], prov["tracker"], prov["lifter"], prov["refine"]) == ("gpu", None, None, [])
    assert prov["contract_version"] == "part2.pose3d/2026-10-28"
    assert [m["name"] for m in prov["models"]] == ["fake-3d"]
    assert not (out / "tracks.json").exists()


def test_multi_run_provenance_names_gpu_and_api_sam31_in_every_file(gpu, tmp_path):
    _, out = _run(tmp_path, mode="multi")
    for name in ("pose3d.json", "pose3d_person_0.json", "tracks.json"):
        prov = _load(out / name)["provenance"]
        assert (prov["backend"], prov["tracker"]) == ("gpu", "api-sam31")
    tracks = _load(out / "tracks.json")
    assert tracks["provenance"]["contract_version"] == "part2.tracks/2026-10-28"
    assert [m["name"] for m in tracks["provenance"]["models"]] == ["sam-3.1"]
    assert [m["name"] for m in _load(out / "pose3d.json")["provenance"]["models"]] == ["fake-3d", "sam-3.1"]


def test_the_written_files_stay_valid_without_provenance(gpu, tmp_path):
    _, out = _run(tmp_path, mode="multi")
    for name, kind in (("pose3d.json", "pose3d"), ("tracks.json", "tracks"), ("pose3d_person_1.json", "pose3d")):
        doc = _load(out / name)
        contract.validate(doc, kind)
        del doc["provenance"]
        contract.validate(doc, kind)
        if kind == "pose3d":
            contract.validate_part3(doc)
    assert cli.main(["doctor", str(out / "pose3d.json")]) == 0


def test_no_key_or_token_reaches_the_provenance(gpu, tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "fake-model-key-secret-value")
    monkeypatch.setenv("HF_TOKEN", "fake-hf-token-secret_value")
    _, out = _run(tmp_path, mode="multi")
    text = "".join(p.read_text() for p in out.glob("*.json"))
    assert "secret-value" not in text and "secret_value" not in text


# --- AC-C07 and the output error: the contract breaks, nothing is written ----------------------

def test_a_nan_from_the_backend_stops_the_run_and_writes_no_pose3d(tmp_path, capsys, monkeypatch):
    def nan_estimate(frames_dir, out_path, boxes=None, estimator=None):
        doc = _fake_estimate(frames_dir, out_path, boxes)
        doc["frames"][1]["people"][0]["kp3d_cam"]["nose"][0] = NAN
        Path(out_path).write_text(json.dumps(doc))
        return doc

    _use_fake_backend(monkeypatch, nan_estimate)
    code, out = _run(tmp_path)
    err = capsys.readouterr().err
    assert code == 1 and "part2: output breaks the contract at pose3d.frames[1].people[0].joints.nose.x: expected a finite number" in err
    assert not (out / "pose3d.json").exists() and not (out / "camera.json").exists()


def test_a_tracker_that_breaks_the_contract_leaves_no_stamped_tracks(tmp_path, capsys, monkeypatch):
    fake_key("MODEL_API_KEY")
    monkeypatch.setattr(track, "load_sam31_tracker", lambda: lambda frames_dir, recs, **_: {
        r["frame"]: [{"id": 0, "bbox": [0, 0, 2, NAN], "mask": [[1]], "confidence": 0.9}] for r in recs})
    code, out = _run(tmp_path, mode="multi")
    assert code == 1 and "part2: output breaks the contract at tracks.frames[0].people[0].bbox" in capsys.readouterr().err
    assert not (out / "tracks.json").exists()


def test_stamping_tracks_checks_the_contract_before_writing(tmp_path):
    path = tmp_path / "tracks.json"
    doc = {"frames": [{"frame": 0, "people": []}]}
    with pytest.raises(ContractError, match="tracks.provenance"):
        output_steps.stamp_tracks(path, doc, {"provenance": {"backend": 5}})
    assert not path.exists()
    output_steps.stamp_tracks(path, doc, {"t0_pts_ms": None, "provenance": {"backend": "gpu"}})
    assert _load(path) == {"frames": [{"frame": 0, "people": []}], "provenance": {"backend": "gpu"}}


# --- AC-002: backend and tracker selection through the CLI ---------------------------------------

def test_unknown_backend_or_tracker_exits_2(tmp_path, capsys, monkeypatch):
    code, _ = _run(tmp_path, "--backend", "tpu")
    assert code == 2 and 'part2: unknown backend "tpu"; choose' in capsys.readouterr().err
    _use_fake_backend(monkeypatch)
    code, _ = _run(tmp_path, "--tracker", "nope", mode="multi", name="m", src=tmp_path / "imgs")
    assert code == 2 and "nope" in capsys.readouterr().err


def test_unknown_lifter_exits_2_and_the_cpu_backend_takes_the_named_lifter(tmp_path, capsys, monkeypatch):
    code, _ = _run(tmp_path, "--backend", "cpu", "--lifter", "nope")
    assert code == 2 and "nope" in capsys.readouterr().err
    seen = []

    class FakeCpu(_FakeBackend):
        name, lifter = "cpu", None

        def estimate(self, frames_dir, out_path, boxes=None):
            seen.append(self.lifter)
            return _fake_estimate(frames_dir, out_path, boxes)

        def provenance(self):
            return {"backend": "cpu", "tracker": None, "lifter": self.lifter, "refine": [], "models": [],
                    "licence_notes": ["research-only training data"]}

    monkeypatch.setattr(backends, "get", lambda name: FakeCpu())
    code, out = _run(tmp_path, "--backend", "cpu", "--lifter", "motionbert", name="c", src=tmp_path / "imgs")
    prov = _load(out / "pose3d.json")["provenance"]
    assert code == 0 and seen == ["motionbert"]
    assert (prov["backend"], prov["lifter"], prov["licence_notes"]) == ("cpu", "motionbert", ["research-only training data"])


def test_provenance_names_the_backend_and_the_tracker_that_ran(gpu, tmp_path, capsys):
    code, out = _run(tmp_path, mode="multi")
    assert code == 0
    tprov = _load(out / "tracks.json")["provenance"]
    pprov = _load(out / "pose3d.json")["provenance"]
    assert tprov["tracker"] == pprov["tracker"] == "api-sam31"
    assert tprov["contract_version"] == contract.version("tracks")
    assert (pprov["backend"], pprov["detector"]) == ("gpu", "fake")
    assert [m["name"] for m in pprov["models"]][0] == "fake-3d"
    assert "tracker api-sam31" in capsys.readouterr().out


class FakeLock:
    """part2.gpu_guard.gpu_lock stand-in: counts each hold; taking it while held is the deadlock a real flock is."""

    def __init__(self):
        self.held, self.takes = False, 0

    def __call__(self, wait_s=None, poll_s=1.0):
        return self._hold()

    @contextlib.contextmanager
    def _hold(self):
        assert not self.held, "the GPU lock was taken while this process already held it"
        self.held, self.takes = True, self.takes + 1
        try:
            yield
        finally:
            self.held = False


@pytest.mark.parametrize("mode", ["single", "multi"])
def test_cli_estimate_runs_under_the_gpu_lock_given_the_gpu_backend(gpu, tmp_path, monkeypatch, mode):
    """AC-B-NFR-03: `part2 run` holds the host GPU lock around the gpu backend's estimate and not around the tracker
    stage, where a SAM tracker takes the same lock itself."""
    lock, seen, real_track = FakeLock(), {}, track.track

    def estimate(frames_dir, out_path, boxes=None, estimator=None):
        seen["estimate"] = lock.held
        return _fake_estimate(frames_dir, out_path, boxes)

    def tracking(*a, **kw):
        seen["track"] = lock.held
        return real_track(*a, **kw)

    monkeypatch.setattr(gpu_guard, "gpu_lock", lock)
    monkeypatch.setattr(body3d, "estimate", estimate)
    monkeypatch.setattr(track, "track", tracking)
    code, _ = _run(tmp_path, mode=mode)
    assert code == 0 and seen["estimate"] is True and lock.takes == 1 and lock.held is False
    assert seen.get("track") is (False if mode == "multi" else None)


def test_cli_takes_no_gpu_lock_given_the_cpu_backend(tmp_path, monkeypatch):
    lock = FakeLock()
    monkeypatch.setattr(gpu_guard, "gpu_lock", lock)

    class FakeCpu(_FakeBackend):
        name, lifter = "cpu", None

    _use_fake_backend(monkeypatch)
    monkeypatch.setattr(backends, "get", lambda name: FakeCpu())
    code, _ = _run(tmp_path, "--backend", "cpu")
    assert code == 0 and lock.takes == 0


def test_a_busy_gpu_lock_stops_the_run_with_the_plain_message(gpu, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gpu_guard, "gpu_lock", lambda wait_s=None, poll_s=1.0: trackers.gpu_lock(wait_s=0.1, poll_s=0.02))
    with trackers.gpu_lock():
        code, out = _run(tmp_path)
    assert code == 1 and "part2: another GPU job is running" in capsys.readouterr().err
    assert not (out / "pose3d.json").exists()


# --- AC-003: photo input --------------------------------------------------------------------------

@needs_ffmpeg
def test_run_photo(gpu, tmp_path):
    """`part2 run --mode single --input photo.jpg` on a committed fixture frame: one frame, one person."""
    photo = tmp_path / "photo.jpg"
    shutil.copyfile(ROOT / "fixtures" / "input" / "single" / "frames" / "000000.jpg", photo)
    out = tmp_path / "out"
    assert cli.main(["run", "--mode", "single", "--input", str(photo), "--out", str(out)]) == 0
    assert frames.load(out / "frames") == [{"frame": 0, "t_ms": 0.0, "file": "000000.jpg"}]
    pose = _load(out / "pose3d.json")
    assert len(pose["frames"]) == 1 and [p["id"] for p in pose["frames"][0]["people"]] == [0]
    contract.validate(pose, "pose3d")


# --- --refine: the ladder's rungs on a one-person run (ADR-0004) -----------------------------------

def test_run_refine_applies_the_rungs_and_names_them(gpu, tmp_path, monkeypatch):
    from test_refine_outputs import Fake2D

    from part2 import refine
    from part2.backends import cpu_rtm

    loads = []
    monkeypatch.setattr(refine, "load_2d", lambda names: loads.append(list(names)) or Fake2D())
    monkeypatch.setattr(cpu_rtm, "_sha256", lambda path: None)
    code, out = _run(tmp_path, "--refine", "kp2d_fit")
    assert code == 0 and loads == [["kp2d-fit"]]
    before, after = _load(out / "body3d-unrefined.json"), _load(out / "body3d.json")
    assert before["frames"][0]["people"][0]["kp3d_cam"] != after["frames"][0]["people"][0]["kp3d_cam"]
    prov = _load(out / "pose3d.json")["provenance"]
    assert prov["refine"] == ["kp2d-fit"] and prov["models"][-1]["name"].startswith("rtmpose-x")
    assert any("RTMPose-x" in n for n in prov["licence_notes"])


def test_run_without_refine_is_the_unrefined_pipeline(gpu, tmp_path, monkeypatch):
    from part2 import refine

    monkeypatch.setattr(refine, "apply", lambda *a, **k: pytest.fail("no rung may run without --refine"))
    imgs = _image_dir(tmp_path)
    for extra in ((), ("--refine", "none")):
        code, out = _run(tmp_path, *extra, name=f"out{len(extra)}", src=imgs)
        assert code == 0 and not (out / "body3d-unrefined.json").exists()
        assert _load(out / "pose3d.json")["provenance"]["refine"] == []


def test_run_refine_refuses_an_unknown_rung_or_multi_mode(gpu, tmp_path, capsys):
    code, out = _run(tmp_path, "--refine", "nope")
    assert code == 2 and 'part2: unknown refine rung "nope"' in capsys.readouterr().err
    assert not out.exists()
    code, out = _run(tmp_path, "--refine", "kp2d-fit", mode="multi", name="m", src=tmp_path / "imgs")
    assert code == 2 and "part2: --refine applies to --mode single only" in capsys.readouterr().err
    assert not out.exists()


def test_progress_lines_only_when_asked(gpu, tmp_path, capsys, monkeypatch):
    code, _ = _run(tmp_path)
    assert code == 0 and "progress " not in capsys.readouterr().out
    monkeypatch.setenv("PART2_PROGRESS", "1")
    code, _ = _run(tmp_path, mode="multi", name="m", src=tmp_path / "imgs")
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("progress ")]
    assert code == 0 and lines == ["progress frames 2 2", "progress track 0 2", "progress pose 0 2",
                                   "progress write 0 1", "progress write 1 1"]


# --- the contract and doctor commands, and python -m part2 --------------------------------------

def test_contract_command_through_the_cli(capsys):
    assert cli.main(["contract", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == contract.contract_json()
    assert cli.main(["contract", "--schema", "nope"]) == 2
    assert "contract: no schema 'nope'; schemas: pose3d, tracks, camera, frames, mesh3d" in capsys.readouterr().err


def test_doctor_command_through_the_cli(capsys):
    fixture = str(ROOT / "fixtures" / "output" / "single" / "pose3d.json")
    assert cli.main(["doctor", fixture, "--for", "part5"]) == 1
    assert capsys.readouterr().out.splitlines()[1].startswith("Part 5: would reject")
    assert cli.main(["doctor", fixture, "--for", "partx"]) == 2
    assert "doctor: unknown consumer 'partx'; choose part3, part5 or part6" in capsys.readouterr().err


def test_python_m_part2_is_the_same_entry_as_the_part2_script():
    r = subprocess.run([sys.executable, "-m", "part2", "--help"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0 and all(c in r.stdout for c in ("contract", "doctor", "run", "frames"))
    assert subprocess.run([sys.executable, "-m", "part2"], cwd=ROOT, capture_output=True).returncode == 2


def test_run_help_lists_mirrored(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["run", "--help"])
    assert e.value.code == 0 and "--mirrored" in capsys.readouterr().out
