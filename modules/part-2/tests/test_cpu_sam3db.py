"""CPU variant `cpu-sam3db` (TICKET-044 B1; docs/specs/backends-gpu-cpu.md AC-B20 to AC-B26).

Runs without torch: a fake torch module (Tensor, device, TorchFunctionMode) and a fake SAM 3D Body estimator stand
in; the person shaping is the real part2.body3d._person on a fake 70-keypoint output. The real model runs in the
smoke (python -m part2.backends cpu-sam3db --smoke) and `make outputs BACKEND=cpu-sam3db`; the one real-torch test
here is skipped where torch is not installed.
"""
import json
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from test_backends import DIGEST, profile  # noqa: F401  (pytest fixtures)
from test_check import _cpu, _write, root  # noqa: F401  (pytest fixtures)
from test_eval_3d import _pose3d
from test_lifter_fixed_bones import skeleton
from test_outputs import FakeBackend, _use, env  # noqa: F401  (pytest fixtures)
from test_stamp import stamped, touch

from part2 import backends, body3d, canonical, check, eval_3d, output_steps, outputs, stamp
from part2 import frames as frames_mod
from part2.backends import cpu_sam3db, gpu_sam3db
from part2.joints import CANONICAL, EXTRA, MHR70_EXTRA_INDEX, MHR70_INDEX
from part2.schema import validate_pose3d

ROOT = Path(__file__).resolve().parents[1]
NAME = "cpu-sam3db"
MODE = "cpu-sam3db-single"
K = [[1000.0, 0.0, 640.0], [0.0, 1000.0, 360.0], [0.0, 0.0, 1.0]]
TIMING = {"load_s": 23.4, "seconds": 93.4, "frames": 2, "seconds_per_frame": 46.7, "threads": 22}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("PART2_BACKEND", "SAM3D_REPO", "SAM3D_CKPT", check.CPU_ENV):
        monkeypatch.delenv(name, raising=False)


# --- fakes --------------------------------------------------------------------------------------------------

class FakeTensor:
    """Stands in for torch.Tensor: .cuda() fails as it does with no GPU visible, .to() records the device."""

    def __init__(self, device="cpu"):
        self.device = device

    def cuda(self, *args, **kwargs):
        raise RuntimeError("No CUDA GPUs are available")

    def to(self, *args, **kwargs):
        dev = kwargs.get("device", args[0] if args else self.device)
        return FakeTensor(dev if isinstance(dev, str) else getattr(dev, "type", self.device))


class FakeDevice:
    def __init__(self, spec):
        self.type = spec.split(":")[0]


@pytest.fixture
def torch(monkeypatch):
    """A fake torch (and torch.overrides) in sys.modules; `active` lists the function modes entered and not left."""
    active = []

    class TorchFunctionMode:
        def __enter__(self):
            active.append(self)
            return self

        def __exit__(self, *exc):
            active.remove(self)

    fake = types.ModuleType("torch")
    fake.__version__ = "2.8.0+cpu"
    fake.Tensor, fake.device = FakeTensor, FakeDevice
    fake.cuda = types.SimpleNamespace(is_available=lambda: False, OutOfMemoryError=MemoryError)
    fake.get_num_threads = lambda: 22
    fake.active = active
    overrides = types.ModuleType("torch.overrides")
    overrides.TorchFunctionMode = TorchFunctionMode
    fake.overrides = overrides
    monkeypatch.setitem(sys.modules, "torch", fake)
    monkeypatch.setitem(sys.modules, "torch.overrides", overrides)
    monkeypatch.setattr(gpu_sam3db, "_torch", lambda: fake)
    return fake


class FakeMoGe:
    def infer(self, image, use_fp16=True):
        return {"use_fp16": use_fp16}


class FakeFov:
    def __init__(self):
        self.fov_estimator = FakeMoGe()

    def get_cam_intrinsics(self, rgb):
        return self.fov_estimator.infer(rgb)


def sam_output():
    """One SAM 3D Body person: 70 MHR keypoints in the camera frame (pred_cam_t 0), a standing body 3 m away."""
    rng = np.random.default_rng(1)
    kp3d = np.column_stack([rng.uniform(-0.3, 0.3, 70), rng.uniform(-0.8, 0.9, 70), rng.uniform(2.8, 3.2, 70)])
    up = np.linspace(-0.7, 0.9, len(CANONICAL))
    side = lambda name: 0.15 if name.startswith("left") else -0.15 if name.startswith("right") else 0.0
    for k, i in enumerate(MHR70_INDEX):
        kp3d[i] = [side(CANONICAL[k]), up[k], 3.0]
    for k, i in enumerate(MHR70_EXTRA_INDEX):
        kp3d[i] = [side(EXTRA[k]), 0.95, 3.0 + 0.05 * (k % 3)]
    uv = body3d.project(kp3d, K)
    return {"pred_keypoints_3d": kp3d, "pred_cam_t": np.zeros(3), "pred_keypoints_2d": uv,
            "bbox": np.array([500.0, 100.0, 800.0, 600.0])}


class FakeEstimator:
    """The SAM 3D Body estimator load_estimator returns; records the function modes active in each call."""

    def __init__(self, torch):
        self.torch, self.detector, self.fov_estimator, self.calls = torch, "vitdet", FakeFov(), []

    def process_one_image(self, img, bboxes=None, cam_int=None):
        self.calls.append(list(self.torch.active))
        return [sam_output()]


@pytest.fixture
def variant(monkeypatch, profile, torch):  # noqa: F811
    """The cpu-sam3db backend on the fake profile, fake torch and a fake SAM 3D Body; records the calls."""
    calls = {"load": []}

    def load_estimator(device, repo, ckpt, detector_path, fov_path):
        calls["load"].append((device, repo, ckpt, detector_path, fov_path))
        calls["raw"] = FakeEstimator(torch)
        return calls["raw"]

    def estimate(frames_dir, out_path, boxes=None, estimator=None):
        calls["fov"] = estimator.fov_estimator.get_cam_intrinsics(None)
        recs = frames_mod.load(frames_dir) if (Path(frames_dir) / frames_mod.MANIFEST).is_file() else \
            [{"frame": i, "t_ms": i * 200.0} for i in range(2)]
        frames = [{"frame": r["frame"], "t_ms": r["t_ms"], "people": [] if calls.get("empty") else
                   [body3d._person(0, o, np.array(K)) for o in estimator.process_one_image("img")]} for r in recs]
        doc = {"model": "sam-3d-body-dinov3", "camera_frame": "opencv", "K": K, "image_size": [1280, 720],
               "frames": frames}
        Path(out_path).write_text(json.dumps(doc))
        return doc

    monkeypatch.setattr(body3d, "load_estimator", load_estimator)
    monkeypatch.setattr(body3d, "estimate", estimate)
    return cpu_sam3db.Backend(profile_path=profile), calls


# --- registry (AC-B20) ----------------------------------------------------------------------------------------

def test_the_registry_resolves_the_variant_and_keeps_gpu_and_cpu():
    assert backends.names() == ["cpu", "cpu-sam3db", "gpu"]
    b = backends.get(NAME)
    assert isinstance(b, cpu_sam3db.Backend) and b.name == NAME and b.device == "cpu"
    assert isinstance(backends.get("gpu"), gpu_sam3db.Backend) and backends.get("gpu").device == "cuda"
    assert backends.resolve(NAME) == NAME
    assert backends.CHOICES == ("gpu", "cpu", NAME)  # the order of the unknown-backend message


def test_the_registry_holds_the_entry_and_its_refusal_line():
    assert backends._MODULES[NAME] == "part2.backends.cpu_sam3db"
    assert backends.REFUSAL[NAME] == cpu_sam3db.REFUSAL == (
        "the cpu-sam3db backend needs the gpu-cu128 profile and its venv python (make setup-gpu)")


def test_the_variant_is_chosen_only_by_name(monkeypatch):
    monkeypatch.setenv("PART2_BACKEND", NAME)
    assert backends.resolve(None) == NAME
    monkeypatch.delenv("PART2_BACKEND")
    for cuda, expected in ((True, "gpu"), (False, "cpu")):
        monkeypatch.setattr(backends, "cuda_available", lambda cuda=cuda: cuda)
        assert backends.resolve(None) == expected
    with pytest.raises(backends.UnknownBackend, match='^unknown backend "cpu-sam3"; choose gpu or cpu or cpu-sam3db$'):
        backends.resolve("cpu-sam3")


def test_rtmpose_x_and_both_lifters_stay_selectable():
    """AC-B26: the cpu route as ADR-0002 decided it, beside the variant."""
    from part2 import lifters
    from part2.backends import cpu_rtm

    cpu = backends.get("cpu")
    assert isinstance(cpu, cpu_rtm.Backend) and cpu.name == "cpu" and "rtmpose-x" in cpu_rtm.POSE["name"]
    assert lifters.names() == ["bones-prior", "fixed-bones", "motionbert"]
    assert [m.name for m in outputs.modes_for("cpu")] == ["cpu-single"]


# --- available() without CUDA (AC-B20) ------------------------------------------------------------------------

def test_available_without_cuda(variant, torch):
    b, _ = variant
    assert torch.cuda.is_available() is False
    assert b.available() == (True, "cpu device, 22 threads, torch 2.8.0+cpu")


def test_unavailable_without_torch_source_or_weights(monkeypatch, variant, profile, torch):  # noqa: F811
    b, _ = variant
    monkeypatch.setattr(gpu_sam3db, "_torch", lambda: None)
    assert b.available() == (False, ("torch is not installed in this interpreter; run part2 with the gpu-cu128 "
                                     "venv python"))
    monkeypatch.setattr(gpu_sam3db, "_torch", lambda: torch)
    prof = json.loads(profile.read_text())
    (Path(prof["sam3d_ckpt"]) / "model.ckpt").unlink()
    assert b.available() == (False, f"no model.ckpt in {prof['sam3d_ckpt']}")
    shutil.rmtree(Path(prof["sam3d_repo"]) / "sam_3d_body")
    assert b.available() == (False, f"no SAM 3D Body source at {prof['sam3d_repo']}")


def test_without_the_profile_it_refuses_plainly(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(gpu_sam3db, "PROFILE", tmp_path / "absent.json")
    assert backends.main([NAME]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["backend"] == NAME and out["available"] is False and "make setup-gpu" in out["reason"]
    assert backends.main([NAME, "--smoke"]) == 1
    err = capsys.readouterr().err
    assert err.strip() == f"part2: {backends.REFUSAL[NAME]}" and "Traceback" not in err
    with pytest.raises(backends.BackendUnavailable, match=f"^{re.escape(backends.REFUSAL[NAME])}$"):
        backends.get(NAME).estimate(tmp_path, tmp_path / "body3d.json")


def test_both_backends_run_one_list_of_install_checks():
    """The profile, torch, source and weight checks are gpu_sam3db.Backend.install_problem, once; the variant only
    leaves the CUDA check out."""
    assert cpu_sam3db.Backend.install_problem is gpu_sam3db.Backend.install_problem
    assert gpu_sam3db.Backend.needs_cuda is True and cpu_sam3db.Backend.needs_cuda is False


def test_the_two_backends_give_the_same_reason_for_everything_but_cuda(monkeypatch, variant, profile, torch):  # noqa: F811
    cpu, _ = variant
    gpu = gpu_sam3db.Backend(profile_path=profile)
    prof = json.loads(profile.read_text())

    def same_reason(want):
        assert gpu.available() == (False, want) and cpu.available() == (False, want)

    # all in place, no CUDA visible: only the gpu backend refuses, and with the CUDA line
    assert gpu.available() == (False, "torch sees no CUDA device")
    assert cpu.available() == (True, "cpu device, 22 threads, torch 2.8.0+cpu")
    torch.cuda.is_available = lambda: True  # CUDA visible: the gpu backend gets past that line
    torch.cuda.get_device_capability = lambda i=0: (12, 0)
    torch.cuda.get_device_name = lambda i=0: "Fake 5090"
    assert gpu.available() == (True, "Fake 5090, capability 12.0, torch 2.8.0+cpu") and cpu.available()[0] is True
    (Path(prof["sam3d_ckpt"]) / "model.ckpt").unlink()
    same_reason(f"no model.ckpt in {prof['sam3d_ckpt']}")
    shutil.rmtree(Path(prof["sam3d_repo"]) / "sam_3d_body")
    same_reason(f"no SAM 3D Body source at {prof['sam3d_repo']}")
    monkeypatch.setattr(gpu_sam3db, "_torch", lambda: None)
    same_reason("torch is not installed in this interpreter; run part2 with the gpu-cu128 venv python")
    profile.unlink()
    same_reason(f"no gpu-cu128 profile at {profile} (make setup-gpu)")


# --- the CPU redirections are scoped (AC-B21) -----------------------------------------------------------------

def test_cpu_call_keeps_every_cuda_move_on_the_cpu(torch):
    t = FakeTensor()
    assert cpu_sam3db.cpu_call(torch, FakeTensor.cuda, (t,), {}).device == "cpu"
    assert cpu_sam3db.cpu_call(torch, FakeTensor.to, (t, "cuda:0"), None).device == "cpu"
    assert cpu_sam3db.cpu_call(torch, FakeTensor.to, (t, FakeDevice("cuda")), {"non_blocking": True}).device == "cpu"
    assert cpu_sam3db.cpu_call(torch, FakeTensor.to, (t,), {"device": "cuda"}).device == "cpu"
    seen = []
    factory = lambda *a, **k: seen.append((a, k))
    cpu_sam3db.cpu_call(torch, factory, (3,), {"device": FakeDevice("cuda"), "dtype": "f32"})
    cpu_sam3db.cpu_call(torch, factory, ("cuda",), {"device": "meta"})  # only device arguments change
    assert seen == [((3,), {"device": "cpu", "dtype": "f32"}), (("cuda",), {"device": "meta"})]


def test_loading_and_running_the_variant_patches_no_torch_or_moge_attribute(variant, torch, tmp_path):
    b, calls = variant
    cuda, to, infer = torch.Tensor.cuda, torch.Tensor.to, FakeMoGe.__dict__["infer"]
    est = b.load()
    b.estimate(tmp_path, tmp_path / "body3d.json")
    assert torch.Tensor.cuda is cuda and torch.Tensor.to is to  # torch is never patched
    assert FakeMoGe.__dict__["infer"] is infer and FakeMoGe().infer(None) == {"use_fp16": True}
    assert est.fov_estimator.fov_estimator.infer(None) == {"use_fp16": False}  # only this backend's MoGe-2
    assert calls["fov"] == {"use_fp16": False}
    assert [len(active) for active in calls["raw"].calls] == [1, 1]  # each process_one_image inside one mode
    assert torch.active == []  # and the mode ended with the call
    assert est.detector == "vitdet" and isinstance(est, cpu_sam3db.CpuEstimator)
    assert calls["load"][0][0] == "cpu" and len(calls["load"]) == 1


def test_the_focal_rung_rerun_also_runs_inside_the_mode(variant, torch):
    from part2.refine import focal

    b, calls = variant
    fixed = focal.FixedK(b.load(), K)
    fixed.process_one_image("img")
    assert [[type(m).__name__ for m in active] for active in calls["raw"].calls] == [["OnCpu"]]
    assert torch.active == []


def test_the_mode_is_left_when_process_one_image_raises(variant, torch, tmp_path):
    """AC-B21: an estimator that fails inside the mode (the model, an out-of-memory) must not leave it active on the
    thread: the exception reaches the caller, `torch.active` is empty, and the next call enters and leaves again."""
    b, calls = variant
    est = b.load()
    seen, fail = [], [True]

    def process_one_image(img, bboxes=None, cam_int=None):
        seen.append(list(torch.active))
        if fail[0]:
            raise RuntimeError("the model failed")
        return [sam_output()]

    calls["raw"].process_one_image = process_one_image
    with pytest.raises(RuntimeError, match="^the model failed$"):
        est.process_one_image("img")
    assert [len(active) for active in seen] == [1] and torch.active == []  # it ran inside the mode; the mode ended
    with pytest.raises(RuntimeError, match="^the model failed$"):  # the same through the backend's own estimate
        b.estimate(tmp_path, tmp_path / "body3d.json")
    assert torch.active == [] and not (tmp_path / "body3d.json").exists()
    fail[0] = False
    assert len(est.process_one_image("img")) == 1 and torch.active == []
    assert [len(active) for active in seen] == [1, 1, 1]  # one mode per call, none left over from the failures


def test_on_cpu_with_real_torch_keeps_cuda_moves_on_the_cpu():
    torch = pytest.importorskip("torch")
    cuda, to = torch.Tensor.cuda, torch.Tensor.to
    with cpu_sam3db.on_cpu():
        moved = [torch.LongTensor([76, 40]).cuda(), torch.arange(3)[None].repeat(2, 1).cuda(),
                 torch.ones(2).to("cuda"), torch.ones(2).to(torch.device("cuda", 0), non_blocking=True),
                 torch.zeros(1, device="cuda")]
    assert [t.device.type for t in moved] == ["cpu"] * 5
    assert torch.Tensor.cuda is cuda and torch.Tensor.to is to


def test_on_cpu_with_real_torch_ends_with_the_block_that_raises():
    """AC-B21 on real torch: a CUDA move is redirected inside the mode and no longer after an exception left it. Needs
    a torch that cannot reach a GPU (CUDA_VISIBLE_DEVICES= hides it), else there is nothing to tell the two apart."""
    torch = pytest.importorskip("torch")
    if torch.cuda.is_available():
        pytest.skip("a GPU is visible; run with CUDA_VISIBLE_DEVICES= to tell a redirected move from a real one")
    with pytest.raises(RuntimeError, match="^the model failed$"), cpu_sam3db.on_cpu():
        assert torch.zeros(1, device="cuda").device.type == "cpu"
        raise RuntimeError("the model failed")
    with pytest.raises((RuntimeError, AssertionError)):  # the redirection ended with the block: CUDA is unreachable
        torch.zeros(1, device="cuda")


# --- output, provenance and speed (AC-B22, AC-B23) ------------------------------------------------------------

def test_provenance_names_the_variant_the_gpu_weights_the_device_and_timing(variant, profile, tmp_path):  # noqa: F811
    b, _ = variant
    doc = b.estimate(tmp_path, tmp_path / "body3d.json")
    assert json.loads((tmp_path / "body3d.json").read_text()) == doc
    prov = doc["provenance"]
    assert prov["backend"] == NAME and prov["device"] == "cpu" and prov["detector"] == "vitdet"
    assert prov["focal_source"] == "moge2" and prov["env_profile"] == "gpu-cu128"
    assert prov["models"] == gpu_sam3db.Backend(profile_path=profile).provenance()["models"]  # the same weights
    assert prov["models"][0]["weights_sha256"] == DIGEST
    t = prov["timing"]
    assert set(t) == {"load_s", "seconds", "frames", "seconds_per_frame", "threads", "warm"}
    assert t["frames"] == 2 and t["threads"] == 22 and t["seconds_per_frame"] >= 0 and t["load_s"] >= 0
    assert t["warm"] is False  # this estimate loaded the model


def clock(monkeypatch, *ticks):
    """cpu_sam3db's perf_counter answers `ticks` in order (a stand-in for the seconds the load and the estimates take)."""
    it = iter(ticks)
    monkeypatch.setattr(cpu_sam3db, "time", types.SimpleNamespace(perf_counter=lambda: next(it)))


def test_only_the_estimate_that_loaded_the_model_reports_the_load_time(monkeypatch, variant, tmp_path):
    """R11: a warm worker serves many requests from one backend; each says what it paid, not the first one's load."""
    b, calls = variant
    clock(monkeypatch, 0.0, 23.4,   # load
          100.0, 104.0,             # the first estimate: 4.0 s for 2 frames
          200.0, 206.0)             # the second: 6.0 s
    first = b.estimate(tmp_path, tmp_path / "one.json")["provenance"]["timing"]
    second = b.estimate(tmp_path, tmp_path / "two.json")["provenance"]["timing"]
    assert first == {"load_s": 23.4, "seconds": 4.0, "frames": 2, "seconds_per_frame": 2.0, "threads": 22,
                     "warm": False}
    assert second == {"load_s": 0.0, "seconds": 6.0, "frames": 2, "seconds_per_frame": 3.0, "threads": 22,
                      "warm": True}
    assert json.loads((tmp_path / "two.json").read_text())["provenance"]["timing"] == second  # the file says it too
    assert b.provenance()["timing"] == second and len(calls["load"]) == 1  # loaded once, the last timing is kept


def test_a_model_loaded_before_the_request_is_warm_for_every_request(monkeypatch, variant, tmp_path):
    """The worker's preload loads the model before any request: no request paid for it."""
    b, calls = variant
    clock(monkeypatch, 0.0, 23.4, 100.0, 104.0)
    b.load()
    timing = b.estimate(tmp_path, tmp_path / "body3d.json")["provenance"]["timing"]
    assert timing["load_s"] == 0.0 and timing["warm"] is True and len(calls["load"]) == 1


def test_a_failed_first_estimate_still_leaves_the_next_one_warm(monkeypatch, variant, tmp_path):
    b, calls = variant
    clock(monkeypatch, 0.0, 23.4, 100.0, 104.0, 200.0, 206.0)
    calls["empty"] = True
    with pytest.raises(backends.NoPersonFound, match="^no person found in 2 frames$"):  # TICKET-047: exit 4
        b.estimate(tmp_path, tmp_path / "body3d.json")  # it loaded the model, then found nobody
    calls["empty"] = False
    timing = b.estimate(tmp_path, tmp_path / "body3d.json")["provenance"]["timing"]
    assert timing["load_s"] == 0.0 and timing["warm"] is True


def test_check_reads_the_speed_of_a_cold_a_warm_and_a_committed_batch_run_file(tmp_path):
    """check.cpu_speed passes provenance.timing through whatever keys it has: the committed shape (no `warm`) keeps
    working beside the new one."""
    committed = {"load_s": 23.7, "seconds": 3523.5, "frames": 111, "seconds_per_frame": 31.74, "threads": 8}
    cold, warm = {**committed, "warm": False}, {**committed, "load_s": 0.0, "warm": True}
    for name, timing in (("committed", committed), ("cold", cold), ("warm", warm)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({"provenance": {"backend": NAME, "timing": timing}}))
        assert check.cpu_speed(path) == {"seconds_per_frame": 31.74, "timing": timing}, name


def test_pose3d_carries_the_foot_points_and_the_provenance_check_reads(variant, tmp_path):
    b, _ = variant
    doc = b.estimate(tmp_path, tmp_path / "body3d.json")
    person = doc["frames"][0]["people"][0]
    assert list(person["extra_kp3d_cam"]) == list(EXTRA) == list(person["extra_kp2d"])
    extras = output_steps.pose_extras({}, False, b, commit="abc")
    pose_path, _ = canonical.write(tmp_path / "body3d.json", tmp_path / "out", extras=extras)
    pose3d = json.loads(pose_path.read_text())
    validate_pose3d(pose3d)
    assert list(pose3d["frames"][0]["people"][0]["extra_joints"]) == list(EXTRA)
    prov = pose3d["provenance"]
    assert prov["backend"] == NAME and prov["device"] == "cpu" and prov["extra_joints"] == list(EXTRA)
    assert check.cpu_speed(pose_path) == {"seconds_per_frame": prov["timing"]["seconds_per_frame"],
                                          "timing": prov["timing"]}


def test_no_person_in_any_frame_is_an_error(variant, tmp_path):
    b, calls = variant
    calls["empty"] = True
    with pytest.raises(backends.NoPersonFound, match="^no person found in 2 frames$"):  # TICKET-047: exit 4
        b.estimate(tmp_path, tmp_path / "body3d.json")


def test_smoke_runs_fixture_frames_and_reports_seconds_per_frame(variant, tmp_path):
    b, _ = variant
    report = b.smoke(tmp_path / "smoke", n_frames=2)
    first = [r["frame"] for r in frames_mod.load(gpu_sam3db.FIXTURE)[:2]]
    assert report["backend"] == NAME and report["device"] == "cpu" and report["cuda_visible"] is False
    assert report["frame_numbers"] == first and report["frames"] == 2 and report["person_frames"] == 2
    assert report["foot_points"] is True and report["load_s"] >= 0
    assert report["seconds_per_frame"] >= 0 and report["threads"] == 22
    assert sorted(p.name for p in (tmp_path / "smoke" / "frames").iterdir()) == sorted(
        [frames_mod.MANIFEST] + [r["file"] for r in frames_mod.load(gpu_sam3db.FIXTURE)[:2]])


# --- make outputs mode (AC-B24) -------------------------------------------------------------------------------

def test_the_scored_mode_is_the_single_fixture_with_no_rung_by_default():
    mode = next(m for m in outputs.MODES if m.name == MODE)
    assert outputs.modes_for(NAME) == [mode] and mode.backend == NAME
    assert mode.frames == "fixtures/input/single/frames" and mode.one_person and mode.refine == ()
    assert "part2.output_steps" in mode.modules and MODE not in [m.name for m in outputs.modes_for("gpu")]


def test_make_outputs_runs_the_variant_into_its_own_dir_without_the_gpu_lock(env, monkeypatch, capsys):  # noqa: F811
    backend = _use(monkeypatch, FakeBackend(name=NAME, lock=env.lock))
    assert outputs.main(["--backend", NAME], root=env.root) == 0
    summary = json.loads(capsys.readouterr().out)
    assert list(summary) == [MODE] and summary[MODE]["backend"] == NAME and summary[MODE]["lifter"] is None
    out = env.scored / MODE
    assert sorted(p.name for p in out.iterdir()) == ["camera.json", "pose3d.json", "stamp.json"]
    doc = stamp.load(out)
    assert doc["backend"] == NAME and doc["host_gpu"] is None and stamp.check(out, env.root) is None
    assert {"part2/backends/cpu_sam3db.py", "part2/backends/gpu_sam3db.py", "part2/body3d.py"} <= set(doc["code_files"])
    assert backend.locked == [False]  # the CPU variant never holds the host GPU lock
    assert json.loads((out / "pose3d.json").read_text())["provenance"]["backend"] == NAME


def test_make_outputs_refuses_the_variant_plainly(env, monkeypatch, capsys):  # noqa: F811
    class NoProfile(FakeBackend):
        def available(self, lifter=None):
            return False, "no gpu-cu128 profile at /x (make setup-gpu)"

    _use(monkeypatch, NoProfile(name=NAME))
    assert outputs.main(["--backend", NAME], root=env.root) == 1
    assert capsys.readouterr().err == (f"outputs: {backends.REFUSAL[NAME]}\n"
                                       "outputs: no gpu-cu128 profile at /x (make setup-gpu)\n")
    assert outputs.main(["--backend", NAME, "--modes", "single"], root=env.root) == 2
    assert f'backend {NAME} does not make mode "single"; choose {MODE}' in capsys.readouterr().err


def test_the_variant_code_stales_only_its_own_mode():
    gpu = stamp.code_closure(ROOT, stamp.entry_modules("gpu"))
    cpu = stamp.code_closure(ROOT, stamp.entry_modules("cpu", lifter="fixed-bones"))
    mine = stamp.code_closure(ROOT, stamp.entry_modules(NAME))
    assert "part2/backends/cpu_sam3db.py" not in gpu + cpu and "part2/backends/cpu_sam3db.py" in mine
    assert {"part2/backends/gpu_sam3db.py", "part2/body3d.py"} <= set(mine)


# --- check-2-cpu on a named CPU dir (AC-B25) ------------------------------------------------------------------

def _variant(repo, offset=0.0, timing=TIMING):
    """scored/cpu-sam3db-single: the GPU reference shifted by `offset` m, provenance.timing as the variant writes."""
    ref = repo / "fixtures/output/scored/single"
    if not (ref / "pose3d.json").is_file():
        _write(ref / "pose3d.json", _pose3d(skeleton(6)))
        stamped(repo, "single")
    doc = json.loads((ref / "pose3d.json").read_text())
    for f in doc["frames"]:
        for j in f["people"][0]["joints"].values():
            j["x"] += offset
    doc["provenance"] = {"backend": NAME, "device": "cpu", **({"timing": timing} if timing else {})}
    _write(repo / "fixtures/output/scored" / MODE / "pose3d.json", doc)
    return stamped(repo, MODE, backend=NAME)


def test_the_default_block_still_scores_cpu_single_unchanged(root):  # noqa: F811
    _cpu(root, offset=0.0)
    _variant(root, offset=0.3)
    before = check.check_cpu_3d(root)
    assert before["pass"] is True and before["cpu"] == "fixtures/output/scored/cpu-single"
    assert "seconds_per_frame" not in before and "timing" not in before
    assert before["outputs"]["backend"] == "cpu" and check.cpu_mode() == "cpu-single"


def test_env_and_flag_name_the_variant_dir_and_the_block_reports_its_speed(root, monkeypatch, capsys):  # noqa: F811
    _cpu(root, offset=0.0)
    _variant(root, offset=0.3)
    monkeypatch.setenv(check.CPU_ENV, MODE)
    b = check.check_cpu_3d(root)
    assert b["cpu"] == f"fixtures/output/scored/{MODE}" and b["reference"] == "fixtures/output/scored/single"
    assert b["mean_m"] == pytest.approx(0.3, abs=1e-4) and b["pass"] is False and b["lifter"] is None
    assert b["seconds_per_frame"] == 46.7 and b["timing"] == TIMING and b["outputs"]["backend"] == NAME
    monkeypatch.setenv(check.CPU_ENV, "cpu-single")
    assert check.main(["--block", "cpu_backend_3d", "--cpu-mode", MODE], root=root) == 1  # the flag wins
    out = json.loads(capsys.readouterr().out)
    assert out["cpu"].endswith(MODE) and out["seconds_per_frame"] == 46.7
    _variant(root, offset=0.0, timing=None)
    assert check.main(["--block", "cpu_backend_3d", "--cpu-mode", MODE], root=root) == 0
    assert "seconds_per_frame" not in json.loads(capsys.readouterr().out)


def test_a_missing_or_stale_variant_dir_and_a_path_are_refused(root, capsys):  # noqa: F811
    assert check.main(["--block", "cpu_backend_3d", "--cpu-mode", MODE], root=root) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "no cpu outputs; run make outputs BACKEND=cpu-sam3db"  # the command that makes this dir
    assert out["cpu"] == f"fixtures/output/scored/{MODE}"
    for bad in ("../single", "out/cpu-single", ".."):
        assert check.main(["--block", "cpu_backend_3d", "--cpu-mode", bad], root=root) == 1
        assert json.loads(capsys.readouterr().out)["status"].startswith("error: ValueError: ")
    _cpu(root)
    _variant(root)
    touch(root / "part2" / "backends" / "cpu_sam3db.py")
    b = check.check_cpu_3d(root, mode=MODE)
    assert b["pass"] is False and f"{MODE} is stale" in b["status"]
    assert check.check_cpu_3d(root)["pass"] is True  # cpu-single and the reference stay fresh
    with pytest.raises(SystemExit) as e:
        check.main(["--block", "one_person", "--cpu-mode", MODE], root=root)
    assert e.value.code == 2


def test_a_missing_dir_names_the_make_outputs_backend_that_makes_it(root, capsys):  # noqa: F811
    """AC-K17: the hint is the command for the mode asked for; a name that is no CPU mode keeps the cpu hint."""
    hints = {"cpu-single": "cpu", MODE: NAME, "cpu-elsewhere": "cpu", "single": "cpu", "class": "cpu"}
    for mode, backend in hints.items():
        assert check.main(["--block", "cpu_backend_3d", "--cpu-mode", mode], root=root) == 2, mode
        out = json.loads(capsys.readouterr().out)
        assert out["status"] == f"no cpu outputs; run make outputs BACKEND={backend}", mode
    assert check.check_cpu_3d(root)["status"] == eval_3d.NO_CPU  # the default mode: the cpu-single hint as before


def test_the_gpu_reference_and_any_gpu_dir_are_not_a_cpu_mode(root, monkeypatch, capsys):  # noqa: F811
    """AC-K17: `make check-2-cpu CPU_MODE=single` used to score the reference against itself (mean 0.0, pass)."""
    _cpu(root)
    stamped(root, "gpu-copy")  # a dir made by the gpu backend, with a pose3d.json and a fresh stamp
    choose = "choose a dir made by cpu or cpu-sam3db"
    line = {"single": f"fixtures/output/scored/single is the GPU reference (backend gpu), not a CPU mode dir; {choose}",
            "gpu-copy": f"fixtures/output/scored/gpu-copy was made by backend gpu, not a CPU backend; {choose}"}
    for mode, status in line.items():
        assert check.main(["--block", "cpu_backend_3d", "--cpu-mode", mode], root=root) == 1, mode
        out = json.loads(capsys.readouterr().out)
        assert out["pass"] is False and out["status"] == status and "\n" not in status, mode
        assert out["cpu"] == f"fixtures/output/scored/{mode}" and "mean_m" not in out and "outputs" not in out
    monkeypatch.setenv(check.CPU_ENV, "single")  # the environment path make check-2-cpu CPU_MODE=single takes
    assert check.main(["--block", "cpu_backend_3d"], root=root) == 1
    assert json.loads(capsys.readouterr().out)["status"] == line["single"]
    assert check.run(root)["cpu_backend_3d"]["status"] == line["single"]  # and in the full report, never gated
    monkeypatch.delenv(check.CPU_ENV)
    assert check.check_cpu_3d(root)["pass"] is True  # cpu-single (backend cpu) is still scored


def test_the_reference_name_is_refused_whatever_its_stamp_says(root):  # noqa: F811
    """A `single` dir whose stamp claims a CPU backend is still the reference: refused by name, backend named."""
    _cpu(root)
    stamped(root, "single", backend="cpu", profile="cpu", lifter="fixed-bones")
    b = check.check_cpu_3d(root, mode="single")
    assert b["pass"] is False and b["status"].startswith(
        "fixtures/output/scored/single is the GPU reference (backend cpu), not a CPU mode dir")


def test_both_cpu_backends_are_accepted_and_an_unreadable_backend_is_left_to_the_stamp_check(root):  # noqa: F811
    _cpu(root)
    _variant(root)
    assert check.check_cpu_3d(root)["outputs"]["backend"] == "cpu"
    assert check.check_cpu_3d(root, mode=MODE)["outputs"]["backend"] == NAME
    out = root / "fixtures/output/scored" / MODE
    (out / stamp.NAME).write_text(json.dumps({"fingerprint": "v1"}))  # a v1 stamp names no backend
    assert check.check_cpu_3d(root, mode=MODE)["status"] == stamp.V1
    (out / stamp.NAME).unlink()
    missing = stamp.MISSING.format(path=f"{stamp.rel(out, root)}/stamp.json")
    assert check.check_cpu_3d(root, mode=MODE)["status"] == missing


def test_make_check_2_cpu_passes_cpu_mode_through():
    if shutil.which("make") is None:
        pytest.skip("make not installed")
    def run(*args):
        return subprocess.run(["make", "-n", "-s", "check-2-cpu", *args], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout
    assert run(f"CPU_MODE={MODE}").startswith(f"PART2_CPU_MODE={MODE} uv run --quiet python -m part2.check")
    assert "PART2_CPU_MODE" not in run() and run().startswith("uv run --quiet python -m part2.check --block")


def test_make_outputs_hides_cuda_for_the_variant_as_for_cpu():
    if shutil.which("make") is None:
        pytest.skip("make not installed")

    def run(backend):
        return subprocess.run(["make", "-n", "-s", "outputs", f"BACKEND={backend}"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout

    for backend in (NAME, "cpu"):
        assert run(backend).startswith("CUDA_VISIBLE_DEVICES= PYTHONPATH="), backend
        assert f"-m part2.outputs --backend {backend}" in run(backend)
    assert "CUDA_VISIBLE_DEVICES" not in run("gpu")
