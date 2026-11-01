"""Backend registry and the GPU backend (AC-B01, AC-B02, AC-B05, AC-B11, AC-B-NFR-02).

Runs without torch: the GPU backend gets a fake torch module and a fake part2.body3d.estimate; the real model
runs in the smoke test (python -m part2.backends gpu --smoke) and make outputs.
"""
import importlib.util
import inspect
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from part2 import backends, body3d, canonical
from part2.backends import gpu_sam3db
from part2.joints import CANONICAL
from part2.schema import validate_pose3d

ROOT = Path(__file__).resolve().parents[1]
REFUSAL_GPU = "part2: the gpu backend needs CUDA and the gpu-cu128 profile (make setup-gpu); use --backend cpu"
DIGEST = "b" * 64


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("PART2_BACKEND", "SAM3D_REPO", "SAM3D_CKPT"):
        monkeypatch.delenv(name, raising=False)


# --- registry and precedence (AC-B01) ---

def test_names():
    assert backends.names() == ["cpu", "cpu-sam3db", "gpu"]


def test_unknown_name_names_the_choices():
    with pytest.raises(backends.UnknownBackend) as e:
        backends.get("x")
    assert str(e.value) == 'unknown backend "x"; choose gpu or cpu or cpu-sam3db'
    assert e.value.known == ["gpu", "cpu", "cpu-sam3db"]


def test_flag_wins_over_env(monkeypatch):
    monkeypatch.setenv("PART2_BACKEND", "gpu")
    assert backends.resolve("cpu") == "cpu"


def test_env_wins_without_flag(monkeypatch):
    monkeypatch.setattr(backends, "cuda_available", lambda: False)
    monkeypatch.setenv("PART2_BACKEND", "gpu")
    assert backends.resolve(None) == "gpu"


@pytest.mark.parametrize("cuda, expected", [(True, "gpu"), (False, "cpu")])
def test_default_follows_cuda(monkeypatch, cuda, expected):
    monkeypatch.setattr(backends, "cuda_available", lambda: cuda)
    monkeypatch.setenv("PART2_BACKEND", "")  # empty counts as unset
    assert backends.resolve(None) == expected


def test_unknown_env_value_is_refused(monkeypatch):
    monkeypatch.setenv("PART2_BACKEND", "tpu")
    with pytest.raises(backends.UnknownBackend, match='"tpu"; choose gpu or cpu or cpu-sam3db'):
        backends.resolve(None)


def test_cuda_unavailable_without_torch():
    if importlib.util.find_spec("torch") is not None:
        pytest.skip("torch installed here")
    assert backends.cuda_available() is False and backends.default() == "cpu"


def test_registered_backend_without_its_module_refuses(monkeypatch):
    monkeypatch.setitem(backends._MODULES, "cpu", "part2.backends._not_written")
    b = backends.get("cpu")
    assert b.available() == (False, "part2.backends._not_written is not built yet")
    with pytest.raises(backends.BackendUnavailable, match="^the cpu backend needs make setup-cpu$"):
        b.estimate("frames", "out.json")


# --- python -m part2.backends ---

def test_cli_unknown_exits_2(capsys):
    assert backends.main(["x"]) == 2
    assert capsys.readouterr().err.strip() == 'part2: unknown backend "x"; choose gpu or cpu or cpu-sam3db'


def test_cli_gpu_without_profile_refuses_plainly(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(gpu_sam3db, "PROFILE", tmp_path / "absent.json")
    assert backends.main(["gpu"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["available"] is False and "make setup-gpu" in out["reason"]
    assert backends.main(["gpu", "--smoke"]) == 1
    err = capsys.readouterr().err
    assert err.strip() == REFUSAL_GPU and "Traceback" not in err


def test_module_entry_point_runs_without_torch(tmp_path):
    r = subprocess.run([sys.executable, "-m", "part2.backends", "nope"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 2 and "choose gpu or cpu or cpu-sam3db" in r.stderr and "Traceback" not in r.stderr


def test_importing_the_backends_does_not_import_torch():
    code = ("import sys, part2.backends as b, part2.backends.gpu_sam3db; b.get('gpu').provenance(); "
            "assert 'torch' not in sys.modules")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# --- GPU backend with a fake torch and a fake estimator ---

class FakeOOM(RuntimeError):
    pass


def fake_torch(cuda=True):
    return SimpleNamespace(__version__="2.8.0+cu128", cuda=SimpleNamespace(
        is_available=lambda: cuda, get_device_capability=lambda i=0: (12, 0),
        get_device_name=lambda i=0: "Fake 5090", OutOfMemoryError=FakeOOM))


@pytest.fixture
def profile(tmp_path):
    repo, ckpt = tmp_path / "sam-3d-body", tmp_path / "snapshot"
    (repo / "sam_3d_body").mkdir(parents=True)
    (ckpt / "assets").mkdir(parents=True)
    (ckpt / "model.ckpt").write_bytes(b"0")
    (ckpt / "assets" / "mhr_model.pt").write_bytes(b"1")
    doc = {"profile": "gpu-cu128", "sam3d_repo": str(repo), "sam3d_ckpt": str(ckpt), "detector": "vitdet",
           "moge_path": str(tmp_path / "moge" / "model.pt"), "vitdet_path": str(tmp_path / "vitdet" / "m.pkl"),
           "models": [{"name": "sam-3d-body-dinov3", "source": "hf:jetjodh/sam-3d-body-dinov3@rev/model.ckpt",
                       "weights_sha256": DIGEST, "licence": "SAM License"}]}
    path = tmp_path / "part2-profile.json"
    path.write_text(json.dumps(doc))
    return path


def body3d_doc(n_frames=2, people=True):
    """A body3d.json document of the body3d.py shape: a standing subject 3 m in front of the camera."""
    K = [[1000.0, 0, 640], [0, 1000.0, 360], [0, 0, 1]]
    rng = np.random.default_rng(0)
    up = {"nose": -0.7, "left_eye": -0.73, "right_eye": -0.73, "left_ear": -0.71, "right_ear": -0.71,
          "left_shoulder": -0.5, "right_shoulder": -0.5, "left_elbow": -0.2, "right_elbow": -0.2,
          "left_wrist": 0.05, "right_wrist": 0.05, "left_hip": 0.0, "right_hip": 0.0,
          "left_knee": 0.45, "right_knee": 0.45, "left_ankle": 0.9, "right_ankle": 0.9}
    side = {j: (0.15 if j.startswith("left") else -0.15 if j.startswith("right") else 0.0) for j in CANONICAL}
    frames = []
    for i in range(n_frames):
        cam = np.array([[side[j], up[j], 3.0 + (0.08 if j == "nose" else 0.0)] for j in CANONICAL])
        cam += rng.normal(0, 0.005, cam.shape)
        uv = body3d.project(cam, K)
        person = {"id": 0, "bbox": [500.0, 100.0, 300.0, 500.0], "reproj_self_px": 0.0,
                  "kp3d_cam": {j: p.tolist() for j, p in zip(CANONICAL, cam)},
                  "kp2d": {j: q.tolist() for j, q in zip(CANONICAL, uv)}}
        frames.append({"frame": i, "t_ms": i * 200.0, "people": [person] if people else []})
    return {"model": "sam-3d-body-dinov3", "camera_frame": "opencv", "K": K, "image_size": [1280, 720],
            "frames": frames}


@pytest.fixture
def gpu(monkeypatch, profile):
    """The GPU backend on the fake profile, fake torch and a fake SAM 3D Body; records the calls."""
    calls = {}
    monkeypatch.setattr(gpu_sam3db, "_torch", lambda: fake_torch())

    def load_estimator(device, repo, ckpt, detector_path, fov_path):
        calls["load"] = (device, repo, ckpt, detector_path, fov_path)
        return "estimator"

    def estimate(frames_dir, out_path, boxes=None, estimator=None):
        calls["estimate"] = (frames_dir, boxes, estimator)
        doc = calls.get("doc") or body3d_doc()
        Path(out_path).write_text(json.dumps(doc))
        return doc

    monkeypatch.setattr(body3d, "load_estimator", load_estimator)
    monkeypatch.setattr(body3d, "estimate", estimate)
    return gpu_sam3db.Backend(profile_path=profile), calls


def test_registry_returns_the_gpu_backend():
    b = backends.get("gpu")
    assert isinstance(b, gpu_sam3db.Backend) and b.name == "gpu" and b.device == "cuda"


def test_gpu_available_on_cuda_with_profile(gpu):
    b, _ = gpu
    ok, reason = b.available()
    assert ok and "capability 12.0" in reason


def test_gpu_unavailable_without_cuda(monkeypatch, gpu):
    b, _ = gpu
    monkeypatch.setattr(gpu_sam3db, "_torch", lambda: fake_torch(cuda=False))
    assert b.available() == (False, "torch sees no CUDA device")
    with pytest.raises(backends.BackendUnavailable) as e:
        b.estimate("frames", "out.json")
    assert f"part2: {e.value}" == REFUSAL_GPU


def test_gpu_unavailable_without_torch(monkeypatch, gpu):
    b, _ = gpu
    monkeypatch.setattr(gpu_sam3db, "_torch", lambda: None)
    ok, reason = b.available()
    assert not ok and "torch is not installed" in reason


def test_gpu_unavailable_without_weights(gpu, profile):
    b, _ = gpu
    (Path(json.loads(profile.read_text())["sam3d_ckpt"]) / "assets" / "mhr_model.pt").unlink()
    ok, reason = b.available()
    assert not ok and "assets/mhr_model.pt" in reason


def test_env_paths_override_the_profile(monkeypatch, gpu, tmp_path):
    b, _ = gpu
    monkeypatch.setenv("SAM3D_REPO", "/elsewhere/sam-3d-body")
    monkeypatch.setenv("SAM3D_CKPT", "/elsewhere/ckpt")
    p = b.paths()
    assert (p["repo"], p["ckpt"]) == ("/elsewhere/sam-3d-body", "/elsewhere/ckpt")
    assert p["detector_path"] == str(tmp_path / "vitdet") and p["fov_path"] == str(tmp_path / "moge" / "model.pt")


def test_estimate_passes_profile_files_and_boxes_and_writes_provenance(gpu, tmp_path):
    b, calls = gpu
    boxes = {0: {"3": [1, 2, 3, 4]}}
    doc = b.estimate(tmp_path / "frames", tmp_path / "body3d.json", boxes=boxes)
    device, repo, ckpt, detector_path, fov_path = calls["load"]
    assert device == "cuda" and repo.endswith("sam-3d-body") and ckpt.endswith("snapshot")
    assert detector_path.endswith("vitdet") and fov_path.endswith("model.pt")
    assert calls["estimate"] == (tmp_path / "frames", boxes, "estimator")
    written = json.loads((tmp_path / "body3d.json").read_text())
    assert written == doc
    prov = written["provenance"]
    assert prov["backend"] == "gpu" and prov["detector"] == "vitdet" and prov["focal_source"] == "moge2"
    assert prov["env_profile"] == "gpu-cu128" and prov["models"][0]["weights_sha256"] == DIGEST


def test_estimator_loads_once(gpu, tmp_path):
    b, calls = gpu
    b.estimate(tmp_path, tmp_path / "a.json")
    calls.pop("load")
    b.estimate(tmp_path, tmp_path / "b.json")
    assert "load" not in calls


def test_output_shape_converts_to_valid_pose3d(gpu, tmp_path):
    """AC-B02: the GPU backend's body3d.json keeps the body3d.py shape and canonical.write accepts it."""
    b, _ = gpu
    doc = b.estimate(tmp_path, tmp_path / "body3d.json")
    assert {"model", "camera_frame", "K", "image_size", "frames"} <= set(doc)
    person = doc["frames"][0]["people"][0]
    assert set(person) == {"id", "bbox", "kp3d_cam", "kp2d", "reproj_self_px"}
    assert list(person["kp3d_cam"]) == CANONICAL == list(person["kp2d"])
    pose_path, cam_path = canonical.write(tmp_path / "body3d.json", tmp_path)
    validate_pose3d(json.loads(pose_path.read_text()))
    assert json.loads(cam_path.read_text())["K"] == doc["K"]


def test_no_person_in_any_frame_is_an_error(gpu, tmp_path):
    b, calls = gpu
    calls["doc"] = body3d_doc(n_frames=3, people=False)
    with pytest.raises(backends.NoPersonFound, match="^no person found in 3 frames$") as e:  # TICKET-047: exit 4
        b.estimate(tmp_path, tmp_path / "body3d.json")
    assert e.value.exit_code == 4 and isinstance(e.value, RuntimeError)


def test_no_person_found_is_a_plain_backends_attribute_and_loads_no_torch():
    """TICKET-047: the one exception type sits in the torch-free package module, with the exit code of CONTRACT.md."""
    code = ("import sys; from part2.backends import NoPersonFound, BackendUnavailable; "
            "assert NoPersonFound.exit_code == 4 and not issubclass(NoPersonFound, BackendUnavailable); "
            "assert 'torch' not in sys.modules")
    assert subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parent.parent).returncode == 0


def test_out_of_memory_removes_output_and_says_what_to_do(monkeypatch, gpu, tmp_path):
    b, _ = gpu
    out = tmp_path / "body3d.json"
    out.write_text("{}")  # an earlier run's file must not pass for this run's output

    def oom(*a, **k):
        raise FakeOOM("CUDA out of memory")

    monkeypatch.setattr(body3d, "estimate", oom)
    with pytest.raises(RuntimeError) as e:
        b.estimate(tmp_path, out)
    assert str(e.value) == "the GPU ran out of memory; free memory or use --backend cpu"
    assert not out.exists()


def test_provenance_without_profile_still_names_the_backend(tmp_path):
    prov = gpu_sam3db.Backend(profile_path=tmp_path / "absent.json").provenance()
    assert prov["backend"] == "gpu" and prov["models"] == []


def test_load_estimator_takes_a_device_defaulting_to_cuda():
    params = inspect.signature(body3d.load_estimator).parameters
    assert params["device"].default == "cuda"
    assert inspect.getsource(body3d).count('"cuda"') == 1
