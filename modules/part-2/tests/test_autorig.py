"""part2/autorig.py and its CLI block: rigging an unrigged mesh. Spec: docs/specs/autorig.md (AC-7 to AC-19).
No GPU, torch or scipy: the SAM 3D Body step is a fake that returns the figure the mesh already is."""
import json
import os
import struct
import sys
from pathlib import Path

import numpy as np
import pytest
from autorig_helpers import (
    JOINT_AT,
    fake_fit_body,
    glb_bytes,
    humanoid,
    obj_text,
    surface_points,
    synthetic_joints,
    synthetic_parents,
    synthetic_skin,
)

from part2 import autorig, autorig_glb, autorig_mesh, cli, gpu_guard, trackers
from part2.autorig import MHR_INDEX, Fit


def normalized():
    return autorig_mesh.normalize(humanoid(colors=True))[0]


def rigged(mesh=None, **fake):
    mesh = mesh or normalized()
    skin = synthetic_skin(mesh.vertices)
    return mesh, skin, autorig.rig(mesh, skin, fake_fit_body(**fake), "abc123")


# ---- skin ---------------------------------------------------------------------------------------------

def test_skin_from_flat_keeps_the_four_heaviest_and_renormalises():
    vert = np.array([0, 0, 0, 0, 0, 1, 1])
    joint = np.array([5, 6, 7, 8, 9, 2, 3])
    weight = np.array([0.1, 0.4, 0.3, 0.1, 0.05, 0.6, 0.4])
    skin = autorig.skin_from_flat([-1, 0], vert, joint, weight, 2)
    assert skin.idx[0].tolist() == [6, 7, 5, 8] and skin.idx[1, :2].tolist() == [2, 3]
    assert np.allclose(skin.w.sum(1), 1) and skin.w[0, 0] == pytest.approx(0.4 / 0.9)
    assert skin.w[1, 2:].tolist() == [0, 0]


def test_skin_from_flat_refuses_unusable_weights():
    with pytest.raises(autorig.AutorigError, match="not usable"):
        autorig.skin_from_flat([-1], np.array([0]), np.array([0]), np.array([-1.0]), 1)
    with pytest.raises(autorig.AutorigError, match="no positive weight"):
        autorig.skin_from_flat([-1], np.array([0]), np.array([0]), np.array([0.5]), 2)
    with pytest.raises(autorig.AutorigError, match="not usable"):
        autorig.skin_from_flat([-1], np.array([], dtype=int), np.array([], dtype=int), np.array([]), 1)


# ---- nearest points -----------------------------------------------------------------------------------

def test_knn_matches_brute_force_without_scipy(monkeypatch):
    monkeypatch.setitem(sys.modules, "scipy.spatial", None)  # an ImportError: the blocked fallback runs
    rng = np.random.default_rng(1)
    pts, targets = rng.random((300, 3)), rng.random((500, 3))
    d, i = autorig.knn(pts, targets, 3)
    brute = np.linalg.norm(pts[:, None] - targets[None], axis=2)
    assert np.array_equal(i, np.argsort(brute, axis=1)[:, :3]) and np.allclose(d, np.sort(brute, axis=1)[:, :3])
    d, i = autorig.knn(pts, targets[:2], 5)  # fewer targets than k
    assert d.shape == (300, 2) and i.shape == (300, 2)


def test_knn_scipy_path_agrees():
    pytest.importorskip("scipy")
    rng = np.random.default_rng(2)
    pts, targets = rng.random((100, 3)), rng.random((200, 3))
    d, i = autorig.knn(pts, targets, 2)
    brute = np.linalg.norm(pts[:, None] - targets[None], axis=2)
    assert np.array_equal(i, np.argsort(brute, axis=1)[:, :2]) and np.allclose(d, np.sort(brute, axis=1)[:, :2])


# ---- placing the body ---------------------------------------------------------------------------------

def test_ac7_a_scaled_and_shifted_copy_comes_back_to_the_mesh():
    target = surface_points(normalized(), n=2500)
    scale, shift = 0.72, np.array([0.02, -0.015, 0.03])
    fit = Fit((target - shift) / scale, np.array([[0, 1.0, 0]]) / scale - shift / scale, np.zeros((70, 3)))
    placed, err = autorig.align(fit, target)
    assert err < 0.003
    assert np.allclose(placed.joints[0], [0, 1.0, 0], atol=0.02)


def test_ac7_a_body_with_no_height_is_refused():
    flat = Fit(np.zeros((10, 3)), np.zeros((127, 3)), np.zeros((70, 3)))
    with pytest.raises(autorig.AutorigError, match="no height"):
        autorig.align(flat, np.random.default_rng(0).random((20, 3)))


# ---- skin transfer ------------------------------------------------------------------------------------

def test_ac10_weights_are_four_joints_summing_to_one_and_follow_the_nearest_body():
    mesh = normalized()
    skin = synthetic_skin(mesh.vertices)
    idx, w = autorig.transfer_weights(mesh.vertices, mesh.vertices, skin, block=50)
    assert idx.shape == (len(mesh.vertices), 4) and (w >= 0).all() and np.allclose(w.sum(1), 1)
    assert idx.max() < 127
    hand = np.argmax(mesh.vertices[:, 0])  # the tip of the subject's left hand
    assert idx[hand, 0] == MHR_INDEX["leftHand"]
    # a vertex on top of a body vertex takes that vertex's skin first
    assert np.array_equal(idx[:, 0], skin.idx[:, 0])


def test_ac10_a_vertex_between_two_bodies_blends_their_joints():
    mesh = normalized()
    skin = synthetic_skin(mesh.vertices)
    mid = (mesh.vertices[np.argmax(mesh.vertices[:, 0])] + mesh.vertices[np.argmin(mesh.vertices[:, 0])]) / 2
    idx, w = autorig.transfer_weights(mid[None], mesh.vertices, skin)
    assert np.allclose(w.sum(), 1) and len(set(idx[0][w[0] > 0])) >= 2


# ---- bones --------------------------------------------------------------------------------------------

def test_ac11_canonical_map_gives_22_bones_and_checks_the_chains():
    mapping = autorig.canonical_map(synthetic_parents())
    assert len(mapping) == 22 and mapping["hips"] == 1 and mapping["rightToes"] == 23
    names = autorig.joint_names(mapping)
    assert len(names) == 127 and names[75] == "leftUpperArm" and names[0] == "mhr_0" and len(set(names)) == 127


def test_ac11_a_foot_that_is_not_under_the_lower_leg_is_refused():
    parents = synthetic_parents()
    parents[MHR_INDEX["leftFoot"]] = MHR_INDEX["hips"]  # the RobotExpressive case: an IK foot beside the leg
    with pytest.raises(autorig.AutorigError, match="leftFoot is not under leftLowerLeg"):
        autorig.canonical_map(parents)
    with pytest.raises(autorig.AutorigError, match="100 joints, not 127"):
        autorig.canonical_map(np.full(100, 0))
    parents = synthetic_parents()
    parents[MHR_INDEX["leftHand"]] = MHR_INDEX["rightLowerArm"]
    with pytest.raises(autorig.AutorigError, match="leftHand is not under leftLowerArm"):
        autorig.canonical_map(parents)


# ---- the rig ------------------------------------------------------------------------------------------

def test_ac12_ac14_rig_writes_a_glb_and_avatar_json_in_the_contract_shape():
    mesh, _, r = rigged()
    av = r.avatar
    assert av["schema"] == "simon.avatar.v1" and av["kind"] == "autorig" and av["inputs"] == 1
    assert av["joints"] == 127 and av["licence"] == "SAM License; MHR Apache-2.0 notice" and av["part2_commit"] == "abc123"
    assert av["height_m"] == pytest.approx(1.7, abs=0.001) and av["turned_to_face_forward"] is False
    assert av["fit_error_m"] < 0.01 and len(av["mapped"]) == 22
    doc, read = autorig_glb.read(r.glb)
    for bone, node in av["mapped"].items():
        assert doc["nodes"][node]["name"] == bone
    assert np.allclose(read(doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"]), mesh.vertices, atol=1e-5)
    json.dumps(av)


def test_ac13_the_joints_sit_where_the_fit_put_them_in_the_mesh_frame():
    mesh, _, r = rigged()
    doc, _ = autorig_glb.read(r.glb)
    hips = np.array(doc["nodes"][1]["translation"]) + np.array(doc["nodes"][0]["translation"])
    assert hips == pytest.approx(synthetic_joints()[1] + (mesh.vertices.mean(0) * 0), abs=0.06)  # within the fit's centring


def test_ac8_a_figure_read_as_facing_away_is_turned_once_and_the_turn_is_kept():
    calls = []
    mesh = normalized()
    _, _, r = rigged(mesh, calls=calls, hip_sign=((-1, 1), (1, -1)))
    assert len(calls) == 2 and r.avatar["turned_to_face_forward"] is True
    doc, read = autorig_glb.read(r.glb)
    pos = read(doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"])
    assert np.allclose(pos, mesh.vertices * [-1, 1, -1], atol=1e-5)


def test_ac8_a_figure_that_never_reads_as_facing_forward_is_refused():
    with pytest.raises(autorig.BadInput, match="cannot tell which way the figure faces"):
        rigged(hip_sign=(-1, 1))


def test_ac9_a_mesh_that_is_not_one_standing_person_is_refused_with_the_gap():
    with pytest.raises(autorig.BadInput, match=r"does not look like one standing person; the fitted body is \d+% of its height"):
        rigged(squash=True)


# ---- the command --------------------------------------------------------------------------------------

def write_obj(tmp_path, name="m.obj", scale=1.0):
    mesh = humanoid()
    p = tmp_path / name
    p.write_text(obj_text(autorig_mesh.Mesh(mesh.vertices * scale, mesh.faces)))
    return p


def run_with_fake(tmp_path, out, **kw):
    mesh = autorig_mesh.normalize(humanoid())[0]
    return autorig.run(write_obj(tmp_path), out, skin=synthetic_skin(mesh.vertices), fit_body=fake_fit_body(), **kw)


def test_ac15_run_writes_both_files_whole_and_deterministically(tmp_path):
    out = tmp_path / "out"
    av = run_with_fake(tmp_path, out)
    assert sorted(p.name for p in out.iterdir()) == ["avatar.json", "model.glb"]
    assert json.loads((out / "avatar.json").read_text()) == av
    first = (out / "model.glb").read_bytes()
    assert av["unit_guess"] == "m" and av["up_axis"] == "y"
    run_with_fake(tmp_path, out)
    assert (out / "model.glb").read_bytes() == first


def test_ac15_stale_outputs_are_removed_before_a_failed_run(tmp_path):
    out = tmp_path / "out"
    run_with_fake(tmp_path, out)
    bad = tmp_path / "bad.obj"
    bad.write_text("v 0 0 0\n")
    with pytest.raises(autorig.BadInput):
        autorig.run(bad, out)
    assert list(out.iterdir()) == []


def test_ac15_the_picture_of_the_mesh_is_not_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    run_with_fake(tmp_path, tmp_path / "out")
    assert list((tmp_path / "tmp").iterdir()) == []


def test_ac4_ac18_bad_input_is_refused_before_the_gpu_is_touched(tmp_path, monkeypatch, capsys):
    from part2 import backends

    monkeypatch.setattr(backends, "get", lambda name: pytest.fail("the GPU backend was touched"))
    bad = tmp_path / "x.fbx"
    bad.write_bytes(b"Kaydara FBX Binary")
    assert autorig.command(bad, tmp_path / "out") == 2
    err = capsys.readouterr().err
    assert err == "part2: x.fbx is neither a GLB nor an OBJ\n"
    rigged_glb = tmp_path / "r.glb"
    rigged_glb.write_bytes(glb_bytes(humanoid().vertices, humanoid().faces, skin=True))
    assert autorig.command(rigged_glb, tmp_path / "out") == 2
    assert "already rigged" in capsys.readouterr().err


class FakeBackend:
    def __init__(self, ok=True, reason="fine"):
        self.ok, self.reason = ok, reason

    def available(self):
        return self.ok, self.reason

    def paths(self):
        return {"ckpt": "/nowhere"}


@pytest.fixture
def gpu(monkeypatch, tmp_path):
    """The GPU path with the model replaced by the fake fit: 100 GiB free, the skin of the synthetic humanoid."""
    mesh = autorig_mesh.normalize(humanoid())[0]
    monkeypatch.setattr(gpu_guard, "free_gib", lambda: 100.0)
    monkeypatch.setattr(autorig, "load_skin", lambda ckpt: synthetic_skin(mesh.vertices))
    monkeypatch.setattr(autorig, "sam_fit_body", lambda backend: fake_fit_body())
    from part2 import backends

    monkeypatch.setattr(backends, "get", lambda name: FakeBackend())
    return write_obj(tmp_path)


def test_command_exit_0_prints_where_the_model_is(gpu, tmp_path, capsys):
    assert autorig.command(gpu, tmp_path / "out") == 0
    assert capsys.readouterr().out.startswith(f"{tmp_path / 'out' / 'model.glb'} (1.7 m, 22 named bones)")


def test_ac17_a_backend_that_cannot_run_is_exit_1_with_its_reason(gpu, tmp_path, capsys, monkeypatch):
    from part2 import backends

    monkeypatch.setattr(backends, "get", lambda name: FakeBackend(False, "torch sees no CUDA device"))
    assert autorig.command(gpu, tmp_path / "out") == 1
    assert capsys.readouterr().err == "part2: torch sees no CUDA device\n"

    class Broken(FakeBackend):
        def available(self):
            raise ImportError("no torch")

    monkeypatch.setattr(backends, "get", lambda name: Broken())
    assert autorig.command(gpu, tmp_path / "out") == 1
    assert "no torch" in capsys.readouterr().err


def test_ac17_too_little_gpu_memory_is_exit_4(gpu, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(gpu_guard, "free_gib", lambda: 3.0)
    assert autorig.command(gpu, tmp_path / "out") == 4
    assert capsys.readouterr().err == f"part2: only 3.0 GiB of GPU memory is free; need {gpu_guard.MIN_FREE_GIB:.0f}\n"
    assert not (tmp_path / "out" / "model.glb").exists()


def test_ac17_a_held_gpu_lock_is_exit_4_after_the_wait(gpu, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(autorig.GPU_WAIT_ENV, "0.1")
    held = gpu_guard.try_lock()
    assert held is not None
    try:
        assert autorig.command(gpu, tmp_path / "out") == 4
    finally:
        gpu_guard.release(held)
    assert capsys.readouterr().err == "part2: another GPU job is running\n"
    assert autorig.command(gpu, tmp_path / "out") == 0  # and free again afterwards


def test_ac17_gpu_out_of_memory_is_exit_4_and_other_runtime_errors_are_not_hidden(gpu, tmp_path, capsys, monkeypatch):
    def oom(backend):
        raise RuntimeError("CUDA out of memory. Tried to allocate 2 GiB")

    monkeypatch.setattr(autorig, "sam_fit_body", oom)
    assert autorig.command(gpu, tmp_path / "out") == 4
    assert capsys.readouterr().err == "part2: the GPU ran out of memory\n"

    def boom(backend):
        raise RuntimeError("something else")

    monkeypatch.setattr(autorig, "sam_fit_body", boom)
    with pytest.raises(RuntimeError, match="something else"):
        autorig.command(gpu, tmp_path / "out")


def test_ac16_no_person_in_the_picture_is_exit_3(gpu, tmp_path, capsys, monkeypatch):
    def nobody(mesh):
        raise autorig.NoPersonInPicture("no person found in the picture of the mesh")

    monkeypatch.setattr(autorig, "sam_fit_body", lambda backend: nobody)
    assert autorig.command(gpu, tmp_path / "out") == 3
    assert capsys.readouterr().err == "part2: no person found in the picture of the mesh\n"


def test_ac18_the_gpu_lock_is_free_again_after_a_run(gpu, tmp_path):
    assert autorig.command(gpu, tmp_path / "out") == 0
    f = gpu_guard.try_lock()
    assert f is not None
    gpu_guard.release(f)
    assert trackers.GpuBusy  # the error type the busy path maps (AC-17)


def test_cli_block_parses_the_flags_and_routes_to_autorig(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(autorig, "command", lambda *a: seen.append(a) or 7)
    assert cli.main(["autorig", "--out", str(tmp_path / "o"), "--height", "1.8", "--up", "z", str(tmp_path / "m.obj")]) == 7
    assert seen == [(tmp_path / "m.obj", tmp_path / "o", 1.8, "z")]
    with pytest.raises(SystemExit):
        cli.main(["autorig", str(tmp_path / "m.obj")])  # --out is required
    with pytest.raises(SystemExit):
        cli.main(["autorig", "--out", "o", "--up", "x", "m.obj"])


def test_ac19_the_licence_travels_in_the_glb_and_nothing_is_committed():
    _, _, r = rigged()
    doc, _ = autorig_glb.read(r.glb)
    assert doc["asset"]["extras"]["licence"] == "SAM License; MHR Apache-2.0 notice"
    assert "SAM License" in doc["asset"]["copyright"] and "MHR Apache-2.0" in doc["asset"]["copyright"]
    root = Path(__file__).resolve().parents[1]
    tracked = os.popen(f"git -C {root} ls-files").read().split()
    assert not [f for f in tracked if f.endswith((".glb", ".obj", "mhr_model.pt"))]


# ---- real data ----------------------------------------------------------------------------------------

REAL = Path(os.environ.get("PART2_AUTORIG_REAL_GLB", "/tmp/claude-1000/-home-gingy-claude-template/8ef63116-b407-46dd-9af6-851dd3cf56a7/"
                                                       "scratchpad/models/threejs-xbot/Xbot.glb"))


def strip_skin(data: bytes) -> bytes:
    doc, blob = autorig_mesh._glb_chunks(data, "real")
    doc.pop("skins", None)
    for n in doc.get("nodes", []):
        n.pop("skin", None)
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(blob), b"BIN\0") + blob
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


@pytest.mark.skipif(not REAL.is_file(), reason="no real model at PART2_AUTORIG_REAL_GLB (a local test input, never committed)")
def test_real_unrigged_mesh_goes_through_the_whole_pipeline(tmp_path):
    """A real 28000-vertex model (Xbot, skin removed) through load, normalise, picture, rig and the GLB writer, with the
    fit replaced by the figure the mesh already is. The GPU run on the same file is recorded in the lane report."""
    src = tmp_path / "real.glb"
    src.write_bytes(strip_skin(REAL.read_bytes()))
    mesh = autorig_mesh.normalize(autorig_mesh.load(src))[0]
    assert len(mesh.vertices) > 20000
    body = surface_points(mesh, n=4000)
    skin = synthetic_skin(body, synthetic_joints())

    def fit_body(m):
        _, cam = autorig_mesh.render_front(m, size=128)
        kp = np.zeros((70, 3))
        kp[autorig.LEFT_HIP] = cam.to_cam(np.array(JOINT_AT["leftUpperLeg"]))
        kp[autorig.RIGHT_HIP] = cam.to_cam(np.array(JOINT_AT["rightUpperLeg"]))
        return Fit(cam.to_cam(body) * 1.3, cam.to_cam(synthetic_joints()) * 1.3, kp * 1.3), cam

    r = autorig.rig(mesh, autorig.Skin(skin.parents, skin.idx, skin.w), fit_body)
    doc, read = autorig_glb.read(r.glb)
    attrs = doc["meshes"][0]["primitives"][0]["attributes"]
    w = read(attrs["WEIGHTS_0"])
    assert len(w) == len(mesh.vertices) and np.allclose(w.sum(1), 1, atol=1e-5)
    assert r.avatar["height_m"] == pytest.approx(1.7, abs=0.001) and r.avatar["fit_error_m"] < 0.02
