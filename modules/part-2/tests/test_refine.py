"""Ladder rungs (part2.refine; docs/specs/check-2.md "One-person ladder", ADR-0004) on synthetic body3d documents.

No GPU, no RTMPose weights and no label file: 2D keypoints are made here from a known skeleton.
"""
import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from test_canonical import BODY, K, _yaw

from part2 import refine
from part2.joints import CANONICAL
from part2.lifters import project
from part2.refine import kp2d_fit

ROOT = Path(__file__).resolve().parent.parent
# AC-K06 / TICKET-020: the gold label files are never edited (sha256 of the committed bytes).
LABEL_SHA256 = {
    "fixtures/input/single/labels_2d.json": "b830ee137c5cfd8d261bd7a00759673ba79e41df3098ccffbd92f92b450e3a7b",
    "fixtures/input/coco/labels_2d.json": "e5a6922b070b54d6bc5d1f5b8184f1843ec128c492f60a60e0e640339b4ab465",
}
T = np.array([0.1, 0.2, 3.0])


def camera_joints(deg=30.0, shift=(0.0, 0.0, 0.0)) -> np.ndarray:
    can = np.array([BODY[j] for j in CANONICAL], float)
    return can @ _yaw(deg).T + T + np.asarray(shift)


def person(X, pid=0) -> dict:
    uv = project(X, K)
    return {"id": pid, "bbox": [500.0, 100.0, 300.0, 600.0], "kp3d_cam": {j: x.tolist() for j, x in zip(CANONICAL, X)},
            "kp2d": {j: x.tolist() for j, x in zip(CANONICAL, uv)}, "reproj_self_px": 0.0}


def doc_of(seq, ids=(0,)) -> dict:
    return {"model": "test", "camera_frame": "opencv", "K": K, "image_size": [1280, 720],
            "frames": [{"frame": i, "t_ms": i * 200.0, "people": [person(X, pid) for pid in ids]}
                       for i, X in enumerate(seq)]}


class Ctx:
    def __init__(self, kp):
        self.kp = kp

    def keypoints(self, doc):
        return self.kp


def kp_for(doc, uv_by_frame, score=0.9) -> dict:
    return {(f["frame"], p["id"]): (np.asarray(uv_by_frame[f["frame"]], float), np.full(17, score))
            for f in doc["frames"] for p in f["people"]}


def joints_of(doc, i=0, pid=0) -> np.ndarray:
    p = next(p for p in doc["frames"][i]["people"] if p["id"] == pid)
    return np.array([p["kp3d_cam"][j] for j in CANONICAL])


def lengths(X) -> np.ndarray:
    return np.linalg.norm(X[kp2d_fit.EDGES[:, 0]] - X[kp2d_fit.EDGES[:, 1]], axis=1)


# ---- registry ----------------------------------------------------------------------------------------------------

def test_resolve_reads_names_lists_and_underscores():
    assert refine.resolve("") == [] and refine.resolve(None) == []
    assert refine.resolve("kp2d_fit") == ["kp2d-fit"] == refine.resolve(["kp2d-fit", "kp2d-fit"])
    assert refine.resolve(" kp2d-fit , ") == ["kp2d-fit"]
    with pytest.raises(refine.UnknownRung, match='unknown refine rung "smooth"; choose kp2d-fit'):
        refine.resolve("kp2d-fit,smooth")
    assert isinstance(refine.UnknownRung("x"), ValueError)


def test_every_registered_rung_is_a_module_with_apply():
    for name in refine.ORDER:
        mod = refine.module(name)
        assert mod.NAME == name and callable(mod.apply) and isinstance(mod.USES_2D, bool)


def test_models_and_licence_name_rtmpose_only_when_a_rung_uses_it(monkeypatch):
    from part2.backends import cpu_rtm

    monkeypatch.setattr(cpu_rtm, "_sha256", lambda path: None)  # no hashing of a local weights file in tests
    assert refine.models([]) == [] and refine.licence_notes([]) == [] and refine.load_2d([]) is None
    (entry,) = refine.models(["kp2d-fit"])
    assert entry["name"].startswith("rtmpose-x") and set(entry) >= {"name", "source", "weights_sha256"}
    assert "RTMPose-x" in refine.licence_notes(["kp2d-fit"])[0]


# ---- kp2d-fit ----------------------------------------------------------------------------------------------------

P = {**kp2d_fit.PARAMS, "BETA": 1.0, "GAMMA": 1.0, "C": 0.2}


def test_no_2d_weight_keeps_sams_joints():
    X0 = camera_joints()
    u = project(camera_joints(shift=(0.03, 0, 0)), K)
    X = kp2d_fit.fit(X0, u, np.full(17, 0.9), K, lengths(X0), 500.0, {**P, "BETA": 0.0})
    np.testing.assert_allclose(X, X0, atol=1e-9)


def test_agreeing_models_leave_the_pose_unchanged():
    X0 = camera_joints()
    X = kp2d_fit.fit(X0, project(X0, K), np.full(17, 0.9), K, lengths(X0), 500.0, P)
    np.testing.assert_allclose(X, X0, atol=1e-6)


def test_a_shifted_2d_pulls_the_projection_towards_it_and_keeps_bones_and_depth():
    X0 = camera_joints()
    a, u = project(X0, K), project(camera_joints(shift=(0.02, 0.0, 0.0)), K)  # about 6.7 px to the right
    X = kp2d_fit.fit(X0, u, np.full(17, 1.0), K, lengths(X0), 500.0, {**P, "BETA": 3.0})
    got = project(X, K)
    gap0, gap = np.linalg.norm(a - u, axis=1).mean(), np.linalg.norm(got - u, axis=1).mean()
    assert gap < 0.35 * gap0  # BETA 3: three quarters of the way to RTMPose
    np.testing.assert_allclose(lengths(X), lengths(X0), rtol=0.01)
    assert np.abs(X[:, 2] - X0[:, 2]).max() < 0.02


def test_equal_weight_lands_halfway():
    X0 = camera_joints()
    a, u = project(X0, K), project(camera_joints(shift=(0.01, 0.0, 0.0)), K)
    X = kp2d_fit.fit(X0, u, np.full(17, 1.0), K, lengths(X0), 500.0, {**P, "BETA": 1.0, "SIGMA_L": 1.0})
    np.testing.assert_allclose(project(X, K), (a + u) / 2, atol=0.3)


def test_a_far_off_keypoint_stops_pulling():
    X0 = camera_joints()
    a = project(X0, K)
    u = a.copy()
    w = CANONICAL.index("right_wrist")
    u[w] += [300.0, 200.0]  # a swapped limb: far beyond C * H
    X = kp2d_fit.fit(X0, u, np.full(17, 1.0), K, lengths(X0), 500.0, {**P, "C": 0.05})
    assert np.linalg.norm(project(X, K)[w] - a[w]) < 5.0


def test_the_score_scales_rtmposes_pull():
    X0 = camera_joints()
    a, u = project(X0, K), project(camera_joints(shift=(0.02, 0, 0)), K)
    sure = kp2d_fit.fit(X0, u, np.full(17, 1.0), K, lengths(X0), 500.0, P)
    unsure = kp2d_fit.fit(X0, u, np.full(17, 0.2), K, lengths(X0), 500.0, P)
    gap = lambda X: np.linalg.norm(project(X, K) - u, axis=1).mean()  # noqa: E731
    assert gap(sure) < gap(unsure) < np.linalg.norm(a - u, axis=1).mean()


def test_apply_fits_each_person_and_keeps_the_document_shape():
    seq = [camera_joints(deg) for deg in (20, 25, 30)]
    doc = doc_of(seq, ids=(0, 1))
    before = copy.deepcopy(doc)
    uv = {i: project(camera_joints(deg, (0.02, 0, 0)), K) for i, deg in enumerate((20, 25, 30))}
    kp = kp_for(doc, uv)
    del kp[(1, 1)]  # no 2D for one person in one frame: that person is passed through
    out = kp2d_fit.apply(doc, Ctx(kp), {"BETA": 2.0})
    assert doc == before  # the input document is not changed
    assert [f["frame"] for f in out["frames"]] == [0, 1, 2] and out["K"] == K
    assert out["frames"][1]["people"][1] == doc["frames"][1]["people"][1]
    for f in out["frames"]:
        for p in f["people"]:
            X = np.array([p["kp3d_cam"][j] for j in CANONICAL])
            np.testing.assert_allclose([p["kp2d"][j] for j in CANONICAL], project(X, K), atol=0.01)
    moved = np.linalg.norm(project(joints_of(out, 0), K) - uv[0], axis=1).mean()
    assert moved < np.linalg.norm(project(seq[0], K) - uv[0], axis=1).mean()


def test_bone_lengths_are_the_persons_clip_median():
    big = (camera_joints() - T) * 1.1 + T
    doc = doc_of([camera_joints(), camera_joints(), big])
    tracks = kp2d_fit.person_tracks(doc)
    L, H = tracks[0]
    np.testing.assert_allclose(L, lengths(camera_joints()), rtol=1e-9)
    uv = project(big, K)
    assert H == pytest.approx(np.linalg.norm(uv[0] - (uv[15] + uv[16]) / 2))


# ---- package apply and 2D context ------------------------------------------------------------------------------------

class Fake2D:
    """read/keypoints like part2.backends.cpu_rtm.Rtm2D, from a table of 2D per frame file."""

    def __init__(self, uv_by_file):
        self.uv, self.boxes = uv_by_file, []

    def read(self, path):
        return Path(path).name

    def keypoints(self, img, xyxy):
        self.boxes.append(np.asarray(xyxy).tolist())
        n = len(xyxy)
        return np.stack([self.uv[img]] * n), np.full((n, 17), 0.8)


def frames_dir(tmp_path, n) -> Path:
    d = tmp_path / "frames"
    d.mkdir()
    (d / "frames.json").write_text(json.dumps({"source": "test", "frames": [
        {"frame": i, "t_ms": i * 200.0, "file": f"{i:06d}.jpg"} for i in range(n)]}))
    return d


def test_package_apply_runs_rtmpose_on_each_persons_box(tmp_path):
    seq = [camera_joints(deg) for deg in (20, 30)]
    doc = doc_of(seq)
    model = Fake2D({f"{i:06d}.jpg": project(camera_joints(deg, (0.02, 0, 0)), K) for i, deg in enumerate((20, 30))})
    out = refine.apply("kp2d-fit", doc, frames_dir(tmp_path, 2), model2d=model)
    assert model.boxes == [[[500.0, 100.0, 800.0, 700.0]]] * 2  # [x, y, w, h] -> xyxy
    assert not np.allclose(joints_of(out, 1), seq[1])
    assert refine.apply([], doc, tmp_path) is doc


def test_context_computes_keypoints_once(tmp_path):
    doc = doc_of([camera_joints()])
    model = Fake2D({"000000.jpg": project(camera_joints(), K)})
    ctx = refine.Context(frames_dir(tmp_path, 1), model)
    assert ctx.keypoints(doc) is ctx.keypoints(doc) and len(model.boxes) == 1


def test_frames_without_people_need_no_image(tmp_path):
    doc = doc_of([camera_joints()])
    doc["frames"].append({"frame": 1, "t_ms": 200.0, "people": []})
    kp = refine.keypoints_2d(doc, frames_dir(tmp_path, 2), Fake2D({"000000.jpg": project(camera_joints(), K)}))
    assert list(kp) == [(0, 0)]


# ---- label-free objectives ----------------------------------------------------------------------------------------

def test_objectives_of_an_unchanged_document():
    seq = [camera_joints(20 + 2 * i) for i in range(6)]
    doc = doc_of(seq)
    kp = kp_for(doc, {i: project(X, K) for i, X in enumerate(seq)})
    o = refine.objectives(doc, doc, kp)
    assert o["agree_pct"] == o["agree_before_pct"] == 0.0 and o["dist3d_m"] == 0.0
    assert o["acc3d"] == o["acc3d_before"] and o["bone_cv"] == pytest.approx(0.0, abs=1e-6)


def test_objectives_count_only_kept_frames_and_full_triples():
    seq = [camera_joints(20, (0.01 * (i % 2), 0, 0)) for i in range(6)]  # a 1 cm zigzag
    doc = doc_of(seq)
    kp = kp_for(doc, {i: project(camera_joints(20), K) for i in range(6)})
    smooth = doc_of([camera_joints(20)] * 6)
    all_frames = refine.objectives(smooth, doc, kp)
    assert all_frames["acc3d"] == pytest.approx(0.02 / 0.04)  # |x[i+1] - 2x[i] + x[i-1]| / dt^2
    assert all_frames["acc3d_before"] == 0.0 and all_frames["dist3d_m"] == pytest.approx(0.005)
    some = refine.objectives(smooth, doc, kp, frames=[0, 1, 3, 4, 5])
    assert some["acc3d"] == pytest.approx(0.5)  # only the 3-4-5 triple is whole
    assert refine.objectives(smooth, doc, kp, frames=[0, 2, 4])["acc3d"] is None
    assert some["agree_before_pct"] == 0.0 and some["agree_pct"] > 0


def test_objectives_refuse_mismatched_frames():
    doc = doc_of([camera_joints()] * 3)
    shorter = doc_of([camera_joints()] * 2)
    with pytest.raises(ValueError, match="refined frames differ"):
        refine.objectives(doc, shorter, {})


# ---- gold labels untouched ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("rel", sorted(LABEL_SHA256))
def test_label_files_are_unchanged(rel):
    assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == LABEL_SHA256[rel]


# ---- temporal --------------------------------------------------------------------------------------------------------

from part2.refine import temporal  # noqa: E402


def test_runs_split_at_gaps_in_frame_numbers():
    assert [r.tolist() for r in temporal.runs([0, 1, 2, 5, 6, 9])] == [[0, 1, 2], [3, 4], [5]]
    assert temporal.runs([]) == []


def test_the_local_linear_kernel_keeps_steady_movement_and_sums_to_one():
    t = np.arange(8) * 0.2
    L = temporal.weights(t, 0.3)
    np.testing.assert_allclose(L.sum(1), 1.0)
    line = np.stack([t * 0.5 + 1.0, -t], axis=1)
    np.testing.assert_allclose(temporal.smooth(t, line, 0.3), line, atol=1e-12)
    np.testing.assert_allclose(temporal.smooth(t, line, 0.3, leave_out=True), line, atol=1e-12)


def test_temporal_damps_scatter_and_passes_photos_through():
    seq = [camera_joints(20, (0.01 * (i % 2), 0, 0)) for i in range(7)]  # a 1 cm zigzag
    doc = doc_of(seq)
    doc["frames"].append({"frame": 40, "t_ms": 9000.0, "people": [person(camera_joints(), pid=0)]})  # alone in its run
    before = copy.deepcopy(doc)
    out = temporal.apply(doc, None, {"SIGMA_T": 0.2})
    assert doc == before and out["frames"][7]["people"][0] == doc["frames"][7]["people"][0]
    zig = lambda d: np.abs(np.diff([joints_of(d, i)[0, 0] for i in range(7)])).mean()  # noqa: E731
    assert zig(out) < 0.5 * zig(doc)
    for f in out["frames"]:
        for p in f["people"]:
            X = np.array([p["kp3d_cam"][j] for j in CANONICAL])
            np.testing.assert_allclose([p["kp2d"][j] for j in CANONICAL], project(X, K), atol=0.01)


def test_a_photo_document_is_unchanged():
    doc = doc_of([camera_joints()])
    assert temporal.apply(doc) == doc
    assert temporal.cv_error(doc, 0.1) is None


def test_cv_error_is_zero_for_steady_movement_and_counts_kept_frames_only():
    steady = doc_of([camera_joints(20, (0.01 * i, 0, 0)) for i in range(6)])
    assert temporal.cv_error(steady, 0.2) == pytest.approx(0.0, abs=1e-6)
    zig = doc_of([camera_joints(20, (0.01 * (i % 2), 0, 0)) for i in range(6)])
    assert temporal.cv_error(zig, 0.2) > 0
    assert temporal.cv_error(zig, 0.2, frames=[2, 3]) != temporal.cv_error(zig, 0.2)
    assert temporal.cv_error(zig, 0.05) is None  # no neighbour within 3 sigma of any frame


def test_objectives_project_each_document_through_its_own_camera():
    doc = doc_of([camera_joints(20)] * 3)
    kp = kp_for(doc, {i: project(camera_joints(20), K) for i in range(3)})
    wide = copy.deepcopy(doc)
    wide["K"] = [[1200.0, 0, 640], [0, 1200.0, 360], [0, 0, 1]]
    o = refine.objectives(doc, wide, kp)
    assert o["agree_before_pct"] == 0.0 and o["agree_pct"] > 0


# ---- focal -----------------------------------------------------------------------------------------------------------

from part2.refine import focal  # noqa: E402


class FakeSam:
    """Backend stand-in: load() gives an estimator; body3d.estimate is replaced to return the same 3D joints
    whatever K it is given, so only the camera decides how they project."""

    def __init__(self):
        self.loads = 0

    def load(self):
        self.loads += 1
        return object()


def _fake_estimate(monkeypatch, seen):
    from part2 import body3d

    def estimate(frames_dir, out_path, boxes=None, estimator=None):
        Kc = estimator.fov_estimator.get_cam_intrinsics(None).tolist()
        seen.append(Kc[0][0])
        d = doc_of([camera_joints(20)] * 2)
        return {**d, "K": Kc}

    monkeypatch.setattr(body3d, "estimate", estimate)


def test_focal_picks_the_camera_that_agrees_best_with_rtmpose(tmp_path, monkeypatch):
    seen, locks = [], []
    _fake_estimate(monkeypatch, seen)
    doc = doc_of([camera_joints(20)] * 2)
    K12 = focal.scaled_K(K, 1.2)
    kp = kp_for(doc, {i: project(camera_joints(20), K12) for i in range(2)})

    class Lock:
        def __enter__(self):
            locks.append(1)

        def __exit__(self, *a):
            return False

    ctx = refine.Context(tmp_path, keypoints=kp, backend=FakeSam(), lock=Lock, work_dir=tmp_path)
    out = focal.apply(doc, ctx, {"SCALES": (0.85, 1.0, 1.2, 1.4)})
    assert seen == [850.0, 1200.0, 1400.0] and len(locks) == 3  # s = 1 is the input, never re-run
    assert out["focal_fit"]["scale"] == 1.2 and out["K"][0][0] == 1200.0
    assert out["focal_fit"]["agreement_pct"]["1.2"] == 0.0 < out["focal_fit"]["agreement_pct"]["1"]
    assert (tmp_path / "body3d-focal-1.4.json").is_file() and out["model"] == "test"


def test_focal_keeps_the_input_when_moge_was_right(tmp_path, monkeypatch):
    _fake_estimate(monkeypatch, [])
    doc = doc_of([camera_joints(20)] * 2)
    kp = kp_for(doc, {i: project(camera_joints(20), K) for i in range(2)})
    out = focal.apply(doc, refine.Context(tmp_path, keypoints=kp, backend=FakeSam(), work_dir=tmp_path))
    assert out["focal_fit"]["scale"] == 1.0 and out["frames"] == doc["frames"] and out["K"] == K


def test_focal_needs_the_gpu_backend(tmp_path):
    with pytest.raises(focal.NeedsGpu, match="needs the gpu backend"):
        focal.apply(doc_of([camera_joints()]), refine.Context(tmp_path, keypoints={}))


def test_focal_agreement_caps_each_joint():
    doc = doc_of([camera_joints()])
    u = project(camera_joints(), K)
    u[CANONICAL.index("left_wrist")] += 10000.0
    kp = {(0, 0): (u, np.full(17, 1.0))}
    uv = project(camera_joints(), K)
    H = np.linalg.norm(uv[0] - (uv[15] + uv[16]) / 2)
    assert focal.agreement(doc, kp, 2.0, 0.2) == pytest.approx(100 * 0.2 * H / 17 / H)
    assert focal.agreement(doc, {}, 2.0, 0.2) == float("inf")
