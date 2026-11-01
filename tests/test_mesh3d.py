"""part2 run --mesh: the mesh3d.json + mesh3d.bin pair (docs/specs/mesh3d.md, TICKET-048).

The SAM 3D Body model is replaced by a fake estimator returning a tube mesh around a known body; cv2 and torch are
stand-in modules. body3d.estimate, the decimation, the canonical frame, the writer, read and doctor are real, and so
are the estimate methods of the two SAM 3D Body backends (gpu_sam3db.Backend and cpu_sam3db.Backend, whose `load`
hands them the fake estimator): the no-person check (exit 4), the `mesh` pass-through and the `warm` timing are
production code."""
import contextlib
import hashlib
import inspect
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from test_canonical import BODY, K, _yaw
from test_cli import _FakeBackend, _image_dir, gpu  # noqa: F401  (gpu is a fixture)
from test_cli_track import MOVED_ON, REFUSAL, refuse_the_api_credential, tracker_finds_nobody

from conftest import fake_key
from part2 import backends, body3d, canonical, cli, contract, gpu_guard, mesh3d
from part2.backends import cpu_sam3db, gpu_sam3db
from part2.joints import CANONICAL, MHR70_INDEX
from part2.lifters import project
from part2.schema import ContractError

ROOT = Path(__file__).resolve().parent.parent
CAM_T = np.array([0.1, 0.3, 4.0])


def tube(rings=60, segs=60, radius=0.15, height=1.6, x=0.0):
    """A closed-side cylinder (rings x segs vertices) along y, centred at the origin."""
    a = np.linspace(0, 2 * np.pi, segs, endpoint=False)
    y = np.linspace(-height / 2, height / 2, rings)
    v = np.array([[x + radius * np.cos(t), h, radius * np.sin(t)] for h in y for t in a])
    f = []
    for r in range(rings - 1):
        for s in range(segs):
            i, j = r * segs + s, r * segs + (s + 1) % segs
            f += [[i, j, i + segs], [j, j + segs, i + segs]]
    return v, np.array(f)


def decode(header, payload, offset):
    """One person-frame block as metres (vertex_count x 3), read without the writer's own module."""
    q = np.frombuffer(payload, dtype="<i2", count=header["vertex_count"] * 3, offset=offset)
    return q.reshape(-1, 3).astype(float) * header["vertices"]["unit_m"]


def body_cam(deg=0.0):
    can = np.array([BODY[j] for j in CANONICAL])
    return can @ _yaw(deg).T + CAM_T


# --- AC-M03: decimation --------------------------------------------------------------------------

def test_plan_hits_the_target_and_keeps_faces_valid():
    v, f = tube()
    p = mesh3d.plan(v, f, 500)
    assert 250 <= p.count <= 500 and len(p.labels) == len(v)
    assert p.faces.max() < p.count and p.faces.min() >= 0
    assert not ((p.faces[:, 0] == p.faces[:, 1]) | (p.faces[:, 1] == p.faces[:, 2]) | (p.faces[:, 0] == p.faces[:, 2])).any()
    assert len(np.unique(np.sort(p.faces, axis=1), axis=0)) == len(p.faces)
    np.testing.assert_allclose(mesh3d.apply(p, v).mean(0), v.mean(0), atol=0.02)


def test_small_mesh_is_kept_whole():
    v, f = tube(rings=5, segs=8)
    p = mesh3d.plan(v, f, 500)
    assert p.count == len(v) and np.array_equal(p.labels, np.arange(len(v)))
    np.testing.assert_allclose(mesh3d.apply(p, v), v)


def test_touching_but_unconnected_parts_never_share_a_vertex():
    a, fa = tube(x=0.0, radius=0.1)
    b, fb = tube(x=0.2005, radius=0.1)  # 0.5 mm apart at x=0.1
    v, f = np.concatenate([a, b]), np.concatenate([fa, fb + len(a)])
    p = mesh3d.plan(v, f, 400)
    assert not set(p.labels[: len(a)]) & set(p.labels[len(a):])


# --- AC-M04, AC-M05: frame and listing ----------------------------------------------------------

def test_vertices_are_in_the_pose3d_canonical_frame(tmp_path):
    v, f = tube()
    joints = body_cam(35)
    verts = v @ _yaw(35).T + CAM_T
    c = mesh3d.Collector(500)
    c.frame(0, 0.0)
    assert c.add(0, verts, f, joints)
    c.write(tmp_path)
    header, payload = mesh3d.read(tmp_path / "mesh3d.json")
    got = decode(header, payload, header["frames"][0]["people"][0]["offset"])
    R, t = canonical.frame_axes(joints)
    want = canonical.to_canonical(mesh3d.apply(c.plan, verts), R, t)
    np.testing.assert_allclose(got, want, atol=0.6e-4)
    assert header["clipped"] == 0 and header["frame_of_reference"].startswith("pose3d canonical")


def test_frames_and_people_are_listed_with_offsets_and_degenerate_hips_are_left_out(tmp_path):
    v, f = tube()
    c = mesh3d.Collector(500)
    c.frame(0, 0.0)
    assert c.add(0, v + CAM_T, f, body_cam())
    assert c.add(7, v + CAM_T, f, body_cam(90))
    c.frame(1, 100.0)  # nobody
    c.frame(2, 200.0)
    flat = body_cam()
    flat[CANONICAL.index("left_hip")] = flat[CANONICAL.index("right_hip")]
    assert not c.add(0, v + CAM_T, f, flat)
    json_path, bin_path = c.write(tmp_path)
    header = json.loads(json_path.read_text())
    assert [fr["frame"] for fr in header["frames"]] == [0, 1, 2]
    assert [fr["t_ms"] for fr in header["frames"]] == [0.0, 100.0, 200.0]
    assert [p["id"] for p in header["frames"][0]["people"]] == [0, 7]
    assert header["frames"][1]["people"] == header["frames"][2]["people"] == []
    o0, o1 = (p["offset"] for p in header["frames"][0]["people"])
    assert o1 - o0 == mesh3d.bytes_per_person_frame(header["vertex_count"]) and o0 % 4 == 0
    assert bin_path.stat().st_size == header["bin_bytes"] == o1 + mesh3d.bytes_per_person_frame(header["vertex_count"])


def test_nothing_collected_writes_nothing(tmp_path):
    c = mesh3d.Collector()
    c.frame(0, 0.0)
    assert c.write(tmp_path) is None and not list(tmp_path.iterdir())


# --- AC-NFR-M01: size ---------------------------------------------------------------------------

def test_size_per_person_frame_meets_the_budget():
    v, f = tube(rings=150, segs=120)  # 18000 vertices, about the MHR mesh
    p = mesh3d.plan(v, f, mesh3d.DEFAULT_TARGET)
    assert p.count <= mesh3d.DEFAULT_TARGET
    assert mesh3d.bytes_per_person_frame(mesh3d.DEFAULT_TARGET) * 10 <= 160_000  # 10 fps, one person


# --- AC-M02: the stored bytes -------------------------------------------------------------------

def _joined_payload(c):
    """The bin as it was built before the write streamed: the padded faces and labels, then every block, joined."""
    def pad(b):
        return b + b"\0" * (-len(b) % 4)
    return pad(c.plan.faces.astype("<u2").tobytes()) + pad(c.vertex_joint.astype(np.uint8).tobytes()) + \
        b"".join(b.tobytes() for b in c.blocks)


def test_the_streamed_bin_is_byte_identical_to_the_joined_payload(tmp_path):
    v, f = tube(rings=12, segs=10)
    c = mesh3d.Collector(100)
    for i in range(3):
        c.frame(i, i * 100.0)
        for pid, deg in ((0, 0), (4, 40 + i)):  # two people, moving
            assert c.add(pid, v * (1 + 0.1 * pid) + CAM_T, f, body_cam(deg))
    c.frame(3, 300.0)  # nobody
    json_path, bin_path = c.write(tmp_path)
    want = _joined_payload(c)
    header = json.loads(json_path.read_text())
    assert bin_path.read_bytes() == want and len(c.blocks) == 6
    assert header["bin_bytes"] == len(want) and header["bin_sha256"] == hashlib.sha256(want).hexdigest()
    block = mesh3d.bytes_per_person_frame(header["vertex_count"])
    head_len = len(want) - len(c.blocks) * block
    assert [p["offset"] for fr in header["frames"] for p in fr["people"]] == [head_len + i * block for i in range(6)]
    mesh3d.read(json_path)  # and the reader accepts it


def test_write_never_builds_the_whole_bin_in_memory(tmp_path, monkeypatch):
    """The bin is hashed and written one block at a time: nothing the size of the payload is ever handed to sha256 or
    to a single write of the bin file (190 MB for 601 frames of 7 people at 2500 vertices before it streamed)."""
    v, f = tube(rings=12, segs=10)
    c = mesh3d.Collector(100)
    for i in range(20):
        c.frame(i, i * 100.0)
        c.add(0, v + CAM_T, f, body_cam(i))
    sizes = []
    real_sha = hashlib.sha256

    class Spy:
        def __init__(self, data=b""):
            sizes.append(len(data))
            self._h = real_sha(data)

        def update(self, data):
            sizes.append(len(data))
            self._h.update(data)

        def hexdigest(self):
            return self._h.hexdigest()

    writes = []
    real_open = open

    class WriteSpy:  # the file mesh3d.write opens for the bin: records the size of every write call
        def __init__(self, path, mode):
            self._file = real_open(path, mode)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._file.close()

        def write(self, data):
            writes.append(len(data))
            return self._file.write(data)

    monkeypatch.setattr(mesh3d.hashlib, "sha256", Spy)
    monkeypatch.setattr(mesh3d, "open", WriteSpy, raising=False)
    _, bin_path = c.write(tmp_path)
    total = bin_path.stat().st_size
    assert total > 20 * mesh3d.bytes_per_person_frame(c.plan.count) and len(sizes) > 20
    assert max(sizes) * 4 < total  # the faces and labels, or one block: never the payload
    assert sum(writes) == total and len(writes) > 20  # the spy saw the whole bin: the head, then one write per block
    assert max(writes) * 4 < total  # no single write carries more than a quarter of the payload


def test_coordinates_beyond_3_2767_m_clamp_and_are_counted_not_wrapped(tmp_path):
    joints = body_cam()
    R, t = canonical.frame_axes(joints)
    v, f = tube(rings=5, segs=8)  # kept whole, so the plan is the identity and vertex i is vertex i
    v = v + t
    far = np.array([[5.0, 0.0, 0.0],      # beyond +3.2767 in x
                    [-5.0, 0.0, 0.0],     # beyond -3.2767 in x
                    [0.0, 40.0, -9.0],    # two coordinates; 40 m is 400000 units, which int16 would wrap to 6784
                    [3.2767, 0.0, 0.0],   # exactly the limit: kept, not counted
                    [-3.2768, 0.0, 0.0]])  # one unit past it
    v[:5] = canonical.to_camera(far, R, t)
    c = mesh3d.Collector(500)
    c.frame(0, 0.0)
    assert c.add(0, v, f, joints)
    json_path, _ = c.write(tmp_path)
    header, payload = mesh3d.read(json_path)
    q = np.frombuffer(payload, dtype="<i2", count=header["vertex_count"] * 3,
                      offset=header["frames"][0]["people"][0]["offset"]).reshape(-1, 3)
    assert q[:5].tolist() == [[32767, 0, 0], [-32767, 0, 0], [0, 32767, -32767], [32767, 0, 0], [-32767, 0, 0]]
    assert header["clipped"] == 5 and c.clipped == 5
    assert np.abs(q[5:]).max() < 20000  # the body itself is not touched
    assert decode(header, payload, header["frames"][0]["people"][0]["offset"])[0, 0] == pytest.approx(3.2767)


# --- AC-M08: integrity --------------------------------------------------------------------------

def _pair(tmp_path):
    v, f = tube()
    c = mesh3d.Collector(300)
    c.frame(0, 0.0)
    c.add(0, v + CAM_T, f, body_cam())
    return c.write(tmp_path)


def test_read_refuses_size_sha_and_path_mismatch(tmp_path):
    json_path, bin_path = _pair(tmp_path)
    raw = bin_path.read_bytes()
    bin_path.write_bytes(raw + b"\0\0")
    with pytest.raises(ContractError, match="bytes, header says"):
        mesh3d.read(json_path)
    bin_path.write_bytes(raw[:-2] + b"\x01\x01")
    with pytest.raises(ContractError, match="sha256"):
        mesh3d.read(json_path)
    header = json.loads(json_path.read_text())
    json_path.write_text(json.dumps({**header, "bin": "../mesh3d.bin"}))
    with pytest.raises(ContractError, match="file name beside"):
        mesh3d.read(json_path)


def test_validate_refuses_a_face_index_past_the_vertices_and_an_offset_outside_the_bin(tmp_path):
    json_path, bin_path = _pair(tmp_path)
    header, payload = mesh3d.read(json_path)
    with pytest.raises(ContractError, match="face index"):
        mesh3d.validate({**header, "vertex_count": 3}, payload)
    bad = json.loads(json.dumps(header))
    bad["frames"][0]["people"][0]["offset"] = header["bin_bytes"]
    with pytest.raises(ContractError, match="whole block"):
        mesh3d.validate(bad, payload)


def test_schema_file_is_draft_2020_12_with_id_title_and_version():
    s = json.loads(mesh3d.SCHEMA.read_text())
    assert s["$schema"] == contract.DRAFT and s["$id"].endswith("/mesh3d.schema.json") and s["title"]
    assert s["x-simon-version"] == mesh3d.FORMAT
    contract.check_schema({}, {"type": "object"})  # the checker the schema goes through
    with pytest.raises(ContractError, match="required"):
        mesh3d.validate({}, b"")


# --- AC-M01, AC-M02, AC-M06: part2 run ----------------------------------------------------------

_real_estimate = body3d.estimate  # kept before any fixture replaces it (the `gpu` fixture of test_cli does)
NO_PROFILE = Path("/nonexistent/part2-profile.json")  # the backends read {} from it: no models, no timing inputs


class _Estimator:
    """SAM 3D Body stand-in: `people` detections per frame (0 or 1), a tube mesh around the BODY joints at CAM_T."""

    def __init__(self, people=1):
        v, self.faces = tube()
        self.verts = v
        dets = np.array([[100.0, 50, 400, 700]])[:people]
        self.detector = types.SimpleNamespace(run_human_detection=lambda *a, **k: dets)
        self.fov_estimator = types.SimpleNamespace(get_cam_intrinsics=lambda rgb: np.array(K))

    def process_one_image(self, path, bboxes, cam_int):
        kp = np.repeat(CAM_T[None], 70, axis=0)
        kp[MHR70_INDEX] = body_cam()
        uv = project(kp, np.array(K))
        return [{"pred_keypoints_3d": kp - CAM_T, "pred_keypoints_2d": uv, "pred_cam_t": CAM_T,
                 "pred_vertices": self.verts, "bbox": b} for b in bboxes]


class _Gpu(gpu_sam3db.Backend):
    """The real gpu Backend.estimate (the no-person check, provenance, the `mesh` pass-through) on the fake estimator."""

    def __init__(self, people=1):
        super().__init__(profile_path=NO_PROFILE)
        self._estimator = _Estimator(people)

    def load(self):
        return self._estimator


class _FlatHipsEstimator(_Estimator):
    """People are found, but their hips coincide: no person-frame has a canonical frame, so no mesh vertices are kept."""

    def process_one_image(self, path, bboxes, cam_int):
        outs = super().process_one_image(path, bboxes, cam_int)
        for o in outs:
            kp = o["pred_keypoints_3d"].copy()
            kp[MHR70_INDEX[CANONICAL.index("left_hip")]] = kp[MHR70_INDEX[CANONICAL.index("right_hip")]]
            o["pred_keypoints_3d"] = kp
        return outs


class _FlatHipsGpu(_Gpu):
    def __init__(self):
        super().__init__()
        self._estimator = _FlatHipsEstimator()


class _CpuSam3db(cpu_sam3db.Backend):
    """The real cpu-sam3db Backend.estimate (the `warm` timing included) on the fake estimator, wrapped in the real
    CpuEstimator so that `est.faces` reaches the mesh code through its __getattr__ as it does with the real model."""

    def __init__(self, people=1):
        super().__init__(profile_path=NO_PROFILE)
        self.people = people

    def load(self):
        if self._estimator is None:
            self._estimator, self._load_s = cpu_sam3db.CpuEstimator(_Estimator(self.people)), 0.0
        return self._estimator


class _Cpu(_FakeBackend):
    name = "cpu"


@pytest.fixture
def sam3db(monkeypatch):
    """The stand-ins for cv2, torch and the host GPU lock; returns use(backend), which makes `backends.get` return
    that backend. The default is a gpu backend over the fake estimator."""
    monkeypatch.setitem(sys.modules, "cv2", types.SimpleNamespace(
        imread=lambda p: np.zeros((720, 1280, 3), np.uint8), cvtColor=lambda img, code: img, COLOR_BGR2RGB=4))
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(tensor=lambda a, dtype=None: a, float32=None))
    monkeypatch.setattr(gpu_sam3db, "_torch", lambda: types.SimpleNamespace(
        get_num_threads=lambda: 4, cuda=types.SimpleNamespace(OutOfMemoryError=MemoryError)))
    monkeypatch.setattr(cpu_sam3db, "on_cpu", contextlib.nullcontext)  # the torch function mode needs real torch
    monkeypatch.setattr(body3d, "estimate", _real_estimate)
    monkeypatch.setattr(backends, "resolve", lambda flag=None: flag or "gpu")
    monkeypatch.setattr(gpu_guard, "gpu_lock", lambda *a, **k: contextlib.nullcontext())
    fake_key("MODEL_API_KEY")

    def use(backend):
        monkeypatch.setattr(backends, "get", lambda name: backend)
        return backend

    use(_Gpu())
    return use


def _run(tmp_path, *extra, mode="single", name="out"):
    src = tmp_path / "imgs"
    out = tmp_path / name
    if not src.exists():
        _image_dir(tmp_path, 3)
    return cli.main(["run", "--mode", mode, "--input", str(src), "--out", str(out), "--fps", "10", *extra]), out


def test_run_with_mesh_writes_the_pair_next_to_pose3d(sam3db, tmp_path, capsys):
    code, out = _run(tmp_path, "--mesh", "--mesh-vertices", "400")
    assert code == 0, capsys.readouterr().err
    header, payload = mesh3d.read(out / "mesh3d.json")
    assert (out / "pose3d.json").is_file() and header["vertex_count"] <= 400
    pose = json.loads((out / "pose3d.json").read_text())
    assert [f["frame"] for f in header["frames"]] == [f["frame"] for f in pose["frames"]]
    assert [f["t_ms"] for f in header["frames"]] == [f["t_ms"] for f in pose["frames"]]
    assert "mesh (" in capsys.readouterr().out
    assert cli.main(["doctor", str(out / "mesh3d.json")]) == 0
    assert "kind mesh3d" in capsys.readouterr().out


def test_pose3d_and_camera_are_the_same_with_and_without_mesh(sam3db, tmp_path):
    """The mesh only listens: the frames of pose3d.json and camera.json come out equal (provenance carries a time)."""
    assert _run(tmp_path, "--mesh", "--mesh-vertices", "300", name="with")[0] == 0
    assert _run(tmp_path, name="without")[0] == 0
    with_mesh, without = tmp_path / "with", tmp_path / "without"
    assert _pose(with_mesh)["frames"] == _pose(without)["frames"] != []
    assert (with_mesh / "camera.json").read_bytes() == (without / "camera.json").read_bytes()
    assert (with_mesh / "body3d.json").read_text() == (without / "body3d.json").read_text()
    assert not (without / "mesh3d.json").exists() and not (without / "mesh3d.bin").exists()


def test_mirrored_writes_the_flag_only_the_mesh_stays_in_the_same_unmirrored_frame_as_the_joints(sam3db, tmp_path):
    """AC-M17: --mirrored flips nothing. pose3d.json gets `mirrored: true` over the unmirrored joints, and the mesh is
    the same bytes with and without it, so a reader that mirrors the joints must mirror the mesh the same way."""
    assert _run(tmp_path, "--mesh", "--mesh-vertices", "300", "--mirrored", name="mirrored")[0] == 0
    assert _run(tmp_path, "--mesh", "--mesh-vertices", "300", name="plain")[0] == 0
    mirrored, plain = tmp_path / "mirrored", tmp_path / "plain"
    assert _pose(mirrored)["mirrored"] is True and "mirrored" not in _pose(plain)
    assert _pose(mirrored)["frames"] == _pose(plain)["frames"] != []
    for name in ("mesh3d.json", "mesh3d.bin"):
        assert (mirrored / name).read_bytes() == (plain / name).read_bytes()
    assert "mirrored" not in _header(mirrored)


def test_run_without_mesh_writes_no_mesh_file_and_removes_a_stale_pair(sam3db, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "mesh3d.json").write_text("{}")
    (out / "mesh3d.bin").write_bytes(b"x")
    code, out = _run(tmp_path)
    assert code == 0 and (out / "pose3d.json").is_file()
    assert not (out / "mesh3d.json").exists() and not (out / "mesh3d.bin").exists()


REFINE_REFUSAL = "--mesh cannot be combined with --refine (the mesh comes from the unrefined run)"
REFUSALS = [
    (["--mesh", "--mesh-vertices", "50"], "--mesh-vertices must be at least 100"),
    (["--mesh", "--mesh-vertices", "0"], "--mesh-vertices must be at least 100"),  # 0 is a count, not "unset"
    (["--mesh", "--mesh-vertices", "-7"], "--mesh-vertices must be at least 100"),
    (["--mesh-vertices", "500"], "--mesh-vertices applies to --mesh only"),
    (["--mesh-vertices", "0"], "--mesh-vertices applies to --mesh only"),
    (["--mesh", "--backend", "cpu"], mesh3d.REFUSAL),
    (["--mesh", "--refine", "focal"], REFINE_REFUSAL),
    (["--mesh", "--refine", "kp2d-fit"], REFINE_REFUSAL),
    (["--mesh", "--refine", "focal,kp2d-fit", "--mesh-vertices", "400"], REFINE_REFUSAL),
]


@pytest.mark.parametrize("extra, message", REFUSALS)
def test_mesh_refusals_exit_2_and_write_nothing(sam3db, tmp_path, capsys, extra, message):
    if "cpu" in extra:
        sam3db(_Cpu())  # the refusal is by the backend's name; the others are about the options
    code, out = _run(tmp_path, *extra)
    err = capsys.readouterr().err
    assert code == 2 and err == f"part2: {message}\n" and "Traceback" not in err
    assert not out.exists()  # refused before any frame was ingested: nothing written


def _leave_an_earlier_run(out):
    out.mkdir()
    (out / "pose3d.json").write_text("{earlier}")
    (out / "mesh3d.json").write_text("{old}")
    (out / "mesh3d.bin").write_bytes(b"old")


@pytest.mark.parametrize("extra, message", REFUSALS)
def test_a_refused_command_leaves_a_pair_already_in_out_untouched(sam3db, tmp_path, capsys, extra, message):
    """The old pair is removed only by a run that goes on to write (TICKET-048 R2): a refusal removes nothing."""
    out = tmp_path / "out"
    _leave_an_earlier_run(out)
    if "cpu" in extra:
        sam3db(_Cpu())
    code, _ = _run(tmp_path, *extra)
    assert code == 2 and message in capsys.readouterr().err
    assert (out / "mesh3d.json").read_text() == "{old}" and (out / "mesh3d.bin").read_bytes() == b"old"
    assert not (out / "frames").exists()


def test_refine_none_is_not_a_refinement_so_mesh_runs_with_it(sam3db, tmp_path, capsys):
    for n, refine in enumerate(("none", "", " none ")):
        code, out = _run(tmp_path, "--mesh", "--mesh-vertices", "300", "--refine", refine, name=f"r{n}")
        assert code == 0, capsys.readouterr().err
        assert (out / "mesh3d.json").is_file()


def test_a_run_refused_for_a_bad_tracks_file_leaves_the_old_pair_in_place(gpu, sam3db, tmp_path, capsys):
    """--tracks is read before anything is ingested or removed; a missing file costs the old pair nothing."""
    out = tmp_path / "out"
    _leave_an_earlier_run(out)
    code, _ = _run(tmp_path, "--mesh", "--tracks", str(tmp_path / "no-such-tracks.json"), mode="multi")
    assert code == 1 and "--tracks" in capsys.readouterr().err
    assert (out / "mesh3d.json").read_text() == "{old}" and (out / "mesh3d.bin").read_bytes() == b"old"


def _input_that_cannot_be_read(tmp_path):
    return "single", ["--input", str(tmp_path / "no-such-input"), "--fps", "10"], "part2: "


def _fps_of_zero(tmp_path):
    return "single", ["--input", str(_image_dir(tmp_path, 3)), "--fps", "0"], "part2: fps must be > 0"


def _tracks_made_for_other_frames(tmp_path):
    (tmp_path / "other").mkdir()
    tracked = ["track", "--input", str(_image_dir(tmp_path / "other", 2)), "--out", str(tmp_path / "first"), "--fps", "10"]
    assert cli.main(tracked) == 0  # a tracks file for 2 frames, run against an input of 3
    return "multi", ["--input", str(_image_dir(tmp_path, 3)), "--fps", "10",
                     "--tracks", str(tmp_path / "first" / "tracks.json")], "has no entry for frame 2 of this input"


@pytest.mark.parametrize("case", [_input_that_cannot_be_read, _fps_of_zero, _tracks_made_for_other_frames],
                         ids=["input-unreadable", "fps-0", "tracks-for-other-frames"])
def test_a_run_that_fails_after_the_removal_exits_1_and_leaves_no_pair_beside_the_earlier_pose3d(gpu, sam3db, tmp_path, capsys, case):
    """The removal comes just before the input is read (CONTRACT.md, mesh3d section): these three failures follow it,
    so the pose3d.json of the earlier run stays, with no mesh pair beside it."""
    mode, argv, message = case(tmp_path)
    out = tmp_path / "out"
    _leave_an_earlier_run(out)
    capsys.readouterr()
    code = cli.main(["run", "--mode", mode, *argv, "--out", str(out), "--mesh"])
    err = capsys.readouterr().err
    assert code == 1 and err.startswith("part2: ") and message in err and "Traceback" not in err
    assert not (out / "mesh3d.json").exists() and not (out / "mesh3d.bin").exists()
    assert (out / "pose3d.json").read_text() == "{earlier}"


def test_a_run_with_an_unknown_tracker_exits_2_after_removing_the_old_pair(gpu, sam3db, tmp_path, capsys):
    """The tracker name is checked once the frames are ingested, so this exit 2 follows the removal."""
    out = tmp_path / "out"
    _image_dir(tmp_path, 3)
    _leave_an_earlier_run(out)
    code, _ = _run(tmp_path, "--mesh", "--tracker", "no-such-tracker", mode="multi")
    assert code == 2 and "no-such-tracker" in capsys.readouterr().err
    assert not (out / "mesh3d.json").exists() and not (out / "mesh3d.bin").exists()
    assert (out / "pose3d.json").read_text() == "{earlier}"


def _header(out):
    return json.loads((out / "mesh3d.json").read_text())


def _pose(out):
    return json.loads((out / "pose3d.json").read_text())


# --- AC-M16: people found, no mesh collected ------------------------------------------------------

@pytest.mark.parametrize("mode", ["single", "multi"])
def test_people_found_but_no_mesh_vertices_is_exit_1_with_pose3d_kept_and_no_pair(gpu, sam3db, tmp_path, capsys, mode):
    sam3db(_FlatHipsGpu())
    out = tmp_path / "out"
    _leave_an_earlier_run(out)  # the earlier pair is gone: this run did start
    code, _ = _run(tmp_path, "--mesh", "--mesh-vertices", "300", mode=mode)
    captured = capsys.readouterr()
    assert code == 1 and captured.err == "part2: --mesh found no mesh vertices; no mesh3d pair written\n"
    assert "mesh (" not in captured.out and "Traceback" not in captured.err
    assert _pose(out)["frames"]  # this run's pose3d.json replaced the earlier one
    assert not (out / "mesh3d.json").exists() and not (out / "mesh3d.bin").exists()


def test_the_same_run_without_mesh_exits_0(gpu, sam3db, tmp_path):
    sam3db(_FlatHipsGpu())
    assert _run(tmp_path)[0] == 0


# --- AC-M10: cpu-sam3db is supported ------------------------------------------------------------

def test_cpu_sam3db_writes_the_same_pair_as_gpu_and_keeps_its_warm_timing(sam3db, tmp_path, capsys):
    code, on_gpu = _run(tmp_path, "--mesh", "--mesh-vertices", "400", name="gpu")
    assert code == 0, capsys.readouterr().err
    sam3db(_CpuSam3db())
    runs = [_run(tmp_path, "--mesh", "--mesh-vertices", "400", "--backend", "cpu-sam3db", name=n) for n in ("cold", "warm")]
    assert [c for c, _ in runs] == [0, 0], capsys.readouterr().err
    (_, cold), (_, warm) = runs
    for out in (cold, warm):
        assert _header(out) == _header(on_gpu)
        assert (out / "mesh3d.bin").read_bytes() == (on_gpu / "mesh3d.bin").read_bytes()
        assert cli.main(["doctor", str(out / "mesh3d.json")]) == 0
    prov = {n: _pose(o)["provenance"] for n, o in (("cold", cold), ("warm", warm))}
    assert prov["cold"]["backend"] == "cpu-sam3db" and prov["cold"]["timing"]["warm"] is False
    assert prov["warm"]["timing"]["warm"] is True and prov["warm"]["timing"]["load_s"] == 0.0  # TICKET-046, with --mesh


def test_mesh_backends_are_exactly_the_registry_backends_whose_estimate_takes_mesh():
    takes = {n for n in backends.CHOICES if "mesh" in inspect.signature(type(backends.get(n)).estimate).parameters}
    assert takes == set(mesh3d.BACKENDS) == {"gpu", "cpu-sam3db"}


@pytest.mark.parametrize("make", [_Gpu, _CpuSam3db], ids=["gpu", "cpu-sam3db"])
def test_body3d_estimate_is_called_as_before_without_a_collector_and_gets_it_with_one(sam3db, tmp_path, monkeypatch, make):
    seen = []

    def spy(frames_dir, out_path, boxes=None, estimator=None, **extra):
        seen.append(extra)
        return {"frames": [{"frame": 0, "t_ms": 0.0, "people": [{}]}]}

    monkeypatch.setattr(body3d, "estimate", spy)
    backend, collector = make(), mesh3d.Collector()
    backend.estimate(tmp_path, tmp_path / "body3d.json")
    backend.estimate(tmp_path, tmp_path / "body3d.json", mesh=collector)
    assert seen == [{}, {"mesh": collector}]
    assert gpu_sam3db.mesh_kwargs(None) == {} and gpu_sam3db.mesh_kwargs(collector) == {"mesh": collector}


# --- AC-M11: no person found --------------------------------------------------------------------

@pytest.mark.parametrize("make", [_Gpu, _CpuSam3db], ids=["gpu", "cpu-sam3db"])
def test_no_person_found_with_mesh_exits_4_writes_no_mesh_and_leaves_no_stale_pair(sam3db, tmp_path, capsys, make):
    sam3db(make(people=0))
    out = tmp_path / "out"
    out.mkdir()
    (out / "mesh3d.json").write_text("{}")
    (out / "mesh3d.bin").write_bytes(b"x")
    code, _ = _run(tmp_path, "--mesh")
    assert code == 4 and capsys.readouterr().err == "part2: no person found in 3 frames\n"  # the unchanged line
    assert not (out / "mesh3d.json").exists() and not (out / "mesh3d.bin").exists()
    assert not (out / "pose3d.json").exists() and not (out / "camera.json").exists()


def test_no_person_found_by_the_tracker_with_mesh_exits_4_and_writes_no_mesh(gpu, sam3db, tmp_path, monkeypatch, capsys):
    tracker_finds_nobody(monkeypatch)
    code, out = _run(tmp_path, "--mesh", mode="multi")
    assert code == 4 and capsys.readouterr().err == "part2: no person found to track\n"
    assert not (out / "mesh3d.json").exists() and not (out / "mesh3d.bin").exists() and not (out / "pose3d.json").exists()


# --- AC-M12: multi mode and the tracker fallback ------------------------------------------------

def test_mesh_in_multi_mode_follows_a_refused_credential_to_the_fallback_tracker(gpu, sam3db, tmp_path, monkeypatch, capsys):
    calls = refuse_the_api_credential(monkeypatch)
    code, out = _run(tmp_path, "--mesh", "--mesh-vertices", "400", mode="multi")
    assert code == 0 and capsys.readouterr().err == MOVED_ON  # TICKET-045: one line, then the next tracker
    assert calls == {"api": 1, "local-open": 1}
    pose = _pose(out)
    assert (pose["provenance"]["tracker"], pose["provenance"]["fallback_from"]) == ("local-open", "api-sam31")
    header, _ = mesh3d.read(out / "mesh3d.json")
    listed = {p["id"] for f in header["frames"] for p in f["people"]}
    assert listed and listed == {p["id"] for f in pose["frames"] for p in f["people"]}
    assert [f["frame"] for f in header["frames"]] == [f["frame"] for f in pose["frames"]]


def test_mesh_in_multi_mode_covers_only_the_listed_people(gpu, sam3db, tmp_path, capsys):
    tracked = ["track", "--input", str(_image_dir(tmp_path, 3)), "--out", str(tmp_path / "first"), "--fps", "10"]
    assert cli.main(tracked) == 0
    code, out = _run(tmp_path, "--mesh", "--mesh-vertices", "400", "--tracks", str(tmp_path / "first" / "tracks.json"),
                     "--ids", "1", mode="multi")
    assert code == 0, capsys.readouterr().err
    header, _ = mesh3d.read(out / "mesh3d.json")
    assert {p["id"] for f in header["frames"] for p in f["people"]} == {1}


def test_a_named_api_tracker_that_is_refused_exits_1_and_writes_no_mesh(gpu, sam3db, tmp_path, monkeypatch, capsys):
    refuse_the_api_credential(monkeypatch)
    code, out = _run(tmp_path, "--mesh", "--tracker", "api-sam31", mode="multi")
    assert code == 1 and capsys.readouterr().err == REFUSAL + "\n"
    assert not (out / "mesh3d.json").exists() and not (out / "mesh3d.bin").exists()


# --- AC-M14: the licence in every header --------------------------------------------------------

def test_every_header_carries_the_licence_naming_both_sources(sam3db, tmp_path):
    headers = []
    for n, backend in enumerate((_Gpu(), _CpuSam3db())):
        sam3db(backend)
        code, out = _run(tmp_path, "--mesh", "--mesh-vertices", "300", name=f"run{n}")
        assert code == 0
        headers.append(_header(out))
    (tmp_path / "pair").mkdir()
    headers.append(json.loads(_pair(tmp_path / "pair")[0].read_text()))
    for header in headers:
        assert header["licence"] == mesh3d.LICENCE
        assert "SAM License" in header["licence"] and "Apache-2.0" in header["licence"] and "MHR" in header["licence"]


def test_a_header_without_a_licence_is_refused(tmp_path):
    header, payload = mesh3d.read(_pair(tmp_path)[0])
    for bad in ({k: v for k, v in header.items() if k != "licence"}, {**header, "licence": ""}):
        with pytest.raises(ContractError, match="licence"):
            mesh3d.validate(bad, payload)


# --- AC-M15: nothing of the mesh is committed ---------------------------------------------------

needs_git = pytest.mark.skipif(not (shutil.which("git") and (ROOT / ".git").exists()), reason="not a git checkout")


@needs_git
def test_git_tracks_no_mesh_output_and_no_mhr_asset():
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    assert [t for t in tracked if Path(t).name in ("mesh3d.json", "mesh3d.bin", "mhr_model.pt")] == []


@needs_git
@pytest.mark.parametrize("where", ["out/clip", "fixtures/output/class", "fixtures/output/single", "tests"])
def test_git_ignores_the_mesh_pair_wherever_it_lands(where):
    for name in ("mesh3d.json", "mesh3d.bin"):
        assert subprocess.run(["git", "check-ignore", "-q", f"{where}/{name}"], cwd=ROOT).returncode == 0, f"{where}/{name}"


# --- AC-M07: doctor -----------------------------------------------------------------------------

def test_doctor_rejects_a_tampered_bin_and_says_no_consumer_reads_it(tmp_path, capsys):
    json_path, bin_path = _pair(tmp_path)
    assert cli.main(["doctor", str(json_path)]) == 0
    assert cli.main(["doctor", str(json_path), "--for", "part3"]) == 1
    assert "does not read mesh3d.json" in capsys.readouterr().out
    bin_path.write_bytes(bin_path.read_bytes()[:-2])
    assert cli.main(["doctor", str(json_path), "--json"]) == 1
    assert "header says" in json.loads(capsys.readouterr().out)["schema_error"]


def _header_copy(tmp_path, mutate, name="bad.json"):
    """A valid pair's header with `mutate` applied, written beside its bin; returns the new header's path."""
    json_path, _ = _pair(tmp_path)
    header = json.loads(json_path.read_text())
    mutate(header)
    bad = tmp_path / name
    bad.write_text(json.dumps(header))
    return bad


def _no_people(h):
    h["frames"][0]["people"] = 3


def _no_vertex_count(h):
    del h["vertex_count"]


MALFORMED = [
    (lambda h: h.update(frames=5), "mesh3d.frames: expected array, got int", (0, 0)),
    (_no_people, "mesh3d.frames[0].people: expected array, got int", (0, 1)),
    (lambda h: h.update(frames=[3]), "mesh3d.frames[0]: expected object, got int", (0, 1)),
    (lambda h: h["frames"][0]["people"].__setitem__(0, 3), "mesh3d.frames[0].people[0]: expected object, got int", (0, 1)),
    (_no_vertex_count, "mesh3d.vertex_count: required", (1, 1)),
    (lambda h: h.pop("frames"), "mesh3d.frames: required", (0, 0)),
]


@pytest.mark.parametrize("mutate, where, counts", MALFORMED, ids=["frames-int", "people-int", "frame-int", "person-int",
                                                                   "missing-key", "no-frames-key"])
def test_doctor_reports_a_malformed_header_like_it_does_for_pose3d_and_exits_1(tmp_path, capsys, mutate, where, counts):
    """AC-M07: any header that breaks the schema is a report and exit 1, never a traceback (--json included)."""
    bad = _header_copy(tmp_path, mutate)
    assert cli.main(["doctor", str(bad)]) == 1
    out, err = capsys.readouterr()
    people, frames = counts
    assert err == "" and "kind mesh3d, version part2.mesh3d/2026-10-31 (by its format field)" in out
    assert f"schema: breaks part2.mesh3d/2026-10-31 at {where}" in out
    assert cli.main(["doctor", str(bad), "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["schema_error"] == where and result["exit"] == 1 and result["kind"] == "mesh3d"
    assert (result["people"], result["frames"]) == (people, frames)


def test_doctor_on_a_valid_pair_exits_0_with_no_schema_line_and_counts(tmp_path, capsys):
    bad = _header_copy(tmp_path, lambda h: None, name="copy.json")  # a copy of a valid header
    assert cli.main(["doctor", str(bad)]) == 0
    out = capsys.readouterr().out
    assert out.splitlines() == [f"{bad}: kind mesh3d, version part2.mesh3d/2026-10-31 (by its format field), 1 person, 1 frame"]
    assert cli.main(["doctor", str(bad), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema_error"] is None and result["exit"] == 0 and (result["people"], result["frames"]) == (1, 1)


def test_doctor_reports_a_missing_bin_as_a_schema_line_not_a_traceback(tmp_path, capsys):
    json_path, bin_path = _pair(tmp_path)
    bin_path.unlink()
    assert cli.main(["doctor", str(json_path)]) == 1
    out = capsys.readouterr().out
    assert "schema: breaks part2.mesh3d/2026-10-31 at mesh3d.bin: cannot be read (No such file or directory)" in out
    with pytest.raises(ContractError, match="cannot be read"):
        mesh3d.read(json_path)


# --- vertex_joint: the nearest joint of each vertex, for limb tinting ------------------------------

def test_each_vertex_is_labelled_with_its_nearest_joint(tmp_path):
    joints = body_cam()
    v, f = tube(rings=5, segs=8)  # kept whole, so the plan is the identity
    knee = CANONICAL.index("left_knee")
    v = v * 0.01 + joints[knee]  # a small tube around the left knee, in camera space
    c = mesh3d.Collector(500)
    c.frame(0, 0.0)
    c.add(0, v, f, joints)
    json_path, _ = c.write(tmp_path)
    header, payload = mesh3d.read(json_path)
    vj = header["vertex_joint"]
    labels = np.frombuffer(payload, dtype=np.uint8, count=header["vertex_count"], offset=vj["offset"])
    assert vj["names"] == CANONICAL and set(labels.tolist()) == {knee}


def test_validate_refuses_a_label_that_is_not_a_joint(tmp_path):
    json_path, bin_path = _pair(tmp_path)
    header, payload = mesh3d.read(json_path)
    with pytest.raises(ContractError, match="label is not an index"):
        mesh3d.validate({**header, "vertex_joint": {**header["vertex_joint"], "names": ["nose"]}}, payload)
