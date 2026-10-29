"""CPU backend (docs/specs/backends-gpu-cpu.md "CPU backend", AC-B02, AC-B06 errors, AC-B11, AC-B-NFR-02).
RTMPose and the detector are faked; the real models run in `make outputs BACKEND=cpu`."""
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from test_lifter_fixed_bones import skeleton

from part2 import backends, canonical, contract
from part2.backends import cpu_rtm
from part2.lifters import project
from part2.schema import validate_pose3d

ROOT = Path(__file__).resolve().parent.parent
W, H = 1280, 720


class Fake2D:
    """Projects a synthetic person through the long-side K; the detector returns `boxes_per_frame`."""

    def __init__(self, n, dets=None):
        self.K = cpu_rtm.long_side_K(W, H)
        self.kp = project(skeleton(n, depth=5.0), self.K)
        self.dets = dets
        self.calls = {"detect": 0, "keypoints": 0}
        self.i = -1

    def read(self, path):
        self.i = int(Path(path).stem)
        return np.zeros((H, W, 3), np.uint8)

    def detect(self, img):
        self.calls["detect"] += 1
        if self.dets is not None:
            return np.asarray(self.dets[self.i], float).reshape(-1, 4)
        lo, hi = self.kp[self.i].min(0), self.kp[self.i].max(0)
        return np.array([[*lo, *hi]])

    def keypoints(self, img, xyxy):
        self.calls["keypoints"] += 1
        return np.repeat(self.kp[self.i][None], len(xyxy), 0), np.full((len(xyxy), 17), 0.9)


def _frames(tmp_path, n):
    d = tmp_path / "frames"
    d.mkdir()
    recs = [{"frame": i, "t_ms": i * 200.0, "file": f"{i:06d}.jpg"} for i in range(n)]
    for r in recs:
        (d / r["file"]).write_bytes(b"")
    (d / "frames.json").write_text(json.dumps({"source": "test", "frames": recs}))
    return d


def test_registry_returns_this_backend():
    b = backends.get("cpu")
    assert isinstance(b, cpu_rtm.Backend) and b.name == "cpu"


def test_ac_b02_body3d_shape_and_pose3d_contract(tmp_path):
    frames = _frames(tmp_path, 8)
    doc = cpu_rtm.Backend("fixed-bones").estimate(frames, tmp_path / "body3d.json", model2d=Fake2D(8))
    on_disk = json.loads((tmp_path / "body3d.json").read_text())
    assert on_disk == json.loads(json.dumps(doc))
    assert doc["model"] == "rtmpose-x+fixed-bones" and doc["camera_frame"] == "opencv" and doc["image_size"] == [W, H]
    assert doc["K"] == [[1280.0, 0.0, 640.0], [0.0, 1280.0, 360.0], [0.0, 0.0, 1.0]]
    assert [f["frame"] for f in doc["frames"]] == list(range(8)) and doc["frames"][3]["t_ms"] == 600.0
    p = doc["frames"][0]["people"][0]
    assert set(p) == {"id", "bbox", "kp3d_cam", "kp2d", "reproj_self_px"} and p["id"] == 0
    assert list(p["kp3d_cam"]) == list(p["kp2d"]) == canonical.CANONICAL and p["reproj_self_px"] < 0.05
    pose_path, cam_path = canonical.write(tmp_path / "body3d.json", tmp_path)
    pose3d = json.loads(pose_path.read_text())
    validate_pose3d(pose3d)
    contract.validate_part3(pose3d)


def test_ac_b11_provenance_names_backend_lifter_models_and_licence(tmp_path):
    frames = _frames(tmp_path, 4)
    prov = cpu_rtm.Backend("fixed-bones").estimate(frames, tmp_path / "b.json", model2d=Fake2D(4))["provenance"]
    assert prov["backend"] == "cpu" and prov["lifter"] == "fixed-bones" and prov["focal_source"] == "long-side"
    assert prov["detector"] == cpu_rtm.DETECTOR and prov["env_profile"] == "envs/cpu/requirements.txt"
    assert all({"name", "source", "weights_sha256", "licence"} <= set(m) for m in prov["models"])
    assert [m["source"] for m in prov["models"]] == [cpu_rtm.DET["url"], cpu_rtm.POSE["url"]]
    assert any("RTMPose" in n and "ADR-0005" in n for n in prov["licence_notes"])
    assert prov["timing"]["person_frames"] == 4 and "0" in prov["lifter_info"]
    mb = cpu_rtm.Backend("motionbert").provenance()
    assert mb["lifter"] == "motionbert" and len(mb["models"]) == 3 and len(mb["licence_notes"]) == 2


def test_write_outputs_puts_provenance_in_pose3d_and_camera(tmp_path):
    frames = _frames(tmp_path, 3)
    doc = cpu_rtm.Backend("fixed-bones").estimate(frames, tmp_path / "x.json", model2d=Fake2D(3))
    paths = cpu_rtm.write_outputs(doc, tmp_path / "out")
    assert [p.name for p in paths] == ["body3d.json", "pose3d.json", "camera.json"]
    for p in paths:
        assert json.loads(p.read_text())["provenance"]["lifter"] == "fixed-bones"
    validate_pose3d(json.loads(paths[1].read_text()))  # files with provenance still validate


def test_given_boxes_skip_the_detector_and_keep_their_ids(tmp_path):
    frames = _frames(tmp_path, 3)
    fake = Fake2D(3)
    boxes = {0: {"4": [10, 20, 100, 200]}, "1": {"4": [12, 20, 100, 200]}, 2: {}}
    doc = cpu_rtm.Backend("fixed-bones").estimate(frames, tmp_path / "b.json", boxes=boxes, model2d=fake)
    assert fake.calls["detect"] == 0
    assert [[p["id"] for p in f["people"]] for f in doc["frames"]] == [[4], [4], []]
    assert doc["frames"][0]["people"][0]["bbox"] == [10.0, 20.0, 100.0, 200.0]
    assert doc["provenance"]["detector"] == cpu_rtm.GIVEN_BOXES


def test_one_person_mode_follows_the_previous_box(tmp_path):
    frames = _frames(tmp_path, 3)
    subject, passerby = [100, 100, 200, 400], [300, 0, 700, 720]
    dets = [[subject], [passerby, [105, 98, 205, 402]], []]
    doc = cpu_rtm.Backend("fixed-bones").estimate(frames, tmp_path / "b.json", model2d=Fake2D(3, dets))
    assert doc["frames"][1]["people"][0]["bbox"] == [105.0, 98.0, 100.0, 304.0]
    assert doc["frames"][2]["people"] == []  # nobody detected: no person that frame


def test_no_person_in_any_frame_is_an_error(tmp_path):
    frames = _frames(tmp_path, 2)
    with pytest.raises(RuntimeError, match="^no person found in 2 frames$"):
        cpu_rtm.Backend("fixed-bones").estimate(frames, tmp_path / "b.json", model2d=Fake2D(2, [[], []]))
    assert not (tmp_path / "b.json").exists()


def test_missing_cpu_extras_refuse_with_the_spec_message(tmp_path, monkeypatch):
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "rtmlib" else real(name, *a))
    ok, why = cpu_rtm.Backend().available()
    assert ok is False and why.startswith("the cpu backend needs make setup-cpu")
    with pytest.raises(backends.BackendUnavailable, match="^the cpu backend needs make setup-cpu$"):
        cpu_rtm.Backend().estimate(_frames(tmp_path, 1), tmp_path / "b.json")


def test_unknown_lifter_is_refused(tmp_path):
    from part2.lifters import UnknownLifter

    with pytest.raises(UnknownLifter, match='"x"; choose fixed-bones or motionbert'):
        cpu_rtm.Backend("x").estimate(_frames(tmp_path, 1), tmp_path / "b.json", model2d=Fake2D(1))


def test_lifter_comes_from_the_environment_when_not_set(monkeypatch):
    monkeypatch.setenv("PART2_LIFTER", "motionbert")
    assert cpu_rtm.Backend().provenance()["lifter"] == "motionbert"
    assert cpu_rtm.Backend("fixed-bones").provenance()["lifter"] == "fixed-bones"


def test_download_failure_names_the_model_and_source():
    class Broken:
        def __init__(self, *a, **k):
            raise OSError("HTTP Error 404")

    with pytest.raises(RuntimeError, match=r"^could not download rtmpose-x .* weights from https://download\.openmmlab"):
        cpu_rtm._load(Broken, cpu_rtm.POSE)


def test_long_side_focal_and_centre_principal_point():
    np.testing.assert_allclose(cpu_rtm.long_side_K(720, 1280), [[1280, 0, 360], [0, 1280, 640], [0, 0, 1]])
    assert cpu_rtm.clip_fps([0, 200, 400]) == pytest.approx(5.0) and cpu_rtm.clip_fps([0]) is None


def test_saved_2d_round_trips(tmp_path):
    frames = _frames(tmp_path, 3)
    det = cpu_rtm.detect_2d(frames, json.loads((frames / "frames.json").read_text())["frames"], Fake2D(3))
    back = cpu_rtm.load_2d(cpu_rtm.save_2d(det, tmp_path / "rtmpose2d.json"))
    np.testing.assert_allclose(back["frames"][1]["people"][0]["kp2d"], det["frames"][1]["people"][0]["kp2d"], atol=1e-3)
    np.testing.assert_allclose(back["K"], det["K"])


def test_weights_digest_is_read_from_the_rtmlib_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("TORCH_HOME", str(tmp_path))
    path = cpu_rtm._onnx_path(cpu_rtm.POSE["url"])
    assert path == tmp_path / "hub" / "checkpoints" / "rtmpose-x_simcc-body7_pt-body7_700e-384x288-71d7b7e9_20230629.onnx"
    assert cpu_rtm.model_entry(cpu_rtm.POSE)["weights_sha256"] is None  # not downloaded yet
    path.parent.mkdir(parents=True)
    path.write_bytes(b"onnx")
    assert cpu_rtm.model_entry(cpu_rtm.POSE)["weights_sha256"] == hashlib.sha256(b"onnx").hexdigest()


def test_import_loads_no_heavy_module():
    code = ("import sys, part2.backends.cpu_rtm, part2.lifters.fixed_bones, part2.lifters.motionbert, part2.eval_3d; "
            "print([m for m in ('torch', 'rtmlib', 'onnxruntime', 'cv2') if m in sys.modules])")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"
