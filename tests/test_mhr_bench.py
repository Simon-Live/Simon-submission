"""Spec: docs/specs/mhr-bench.md. Every body, pose and score here is SYNTHETIC fixture data generated for the harness
tests (synthetic: true); none of it is a measurement of the pipeline."""
import hashlib
import json
import math

import pytest

from part7 import mhr_bench as mb

# A made-up standing body in mm, y up, x = subject's left, z forward (fixture only).
BASE = {
    "left_shoulder": (200, 1400, 0), "right_shoulder": (-200, 1400, 0), "left_elbow": (260, 1120, 40),
    "right_elbow": (-260, 1120, 40), "left_wrist": (280, 860, 80), "right_wrist": (-280, 860, 80),
    "left_hip": (100, 900, 0), "right_hip": (-100, 900, 0), "left_knee": (110, 480, 30),
    "right_knee": (-110, 480, 30), "left_ankle": (115, 80, 0), "right_ankle": (-115, 80, 0),
}


def rot_y(p, deg, scale=1.0, shift=(0, 0, 0)):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return (scale * (c * p[0] + s * p[2]) + shift[0], scale * p[1] + shift[1], scale * (-s * p[0] + c * p[2]) + shift[2])


def rot_xyz(p, ax, ay, az):
    cx, sx, cy, sy, cz, sz = (f(math.radians(a)) for a in (ax, ay, az) for f in (math.cos, math.sin))
    y, z = cx * p[1] - sx * p[2], sx * p[1] + cx * p[2]
    x, z = cy * p[0] + sy * z, -sy * p[0] + cy * z
    return (cz * x - sz * y, sz * x + cz * y, z)


def world_gt(deg=40):
    return {j: rot_y(p, deg, shift=(500, 0, -300)) for j, p in BASE.items()}


# ---- AC-001, AC-002: geometry and mapping

def test_procrustes_recovers_known_rotation_scale_translation():
    gt = list(BASE.values())
    pred = [tuple(0.5 * c for c in rot_xyz(p, 30, -50, 70)) for p in gt]
    pred = [(x + 11, y - 7, z + 3) for x, y, z in pred]
    assert mb.mpjpe(pred, gt) > 100
    assert mb.pa_mpjpe(pred, gt) == pytest.approx(0.0, abs=1e-6)


def test_procrustes_never_returns_a_reflection():
    gt = list(BASE.values())
    mirrored = [(-x, y, z) for x, y, z in gt]
    # a mirrored body cannot be matched by rotation, so the error stays above zero
    assert mb.pa_mpjpe(mirrored, gt) > 10


def test_procrustes_keeps_residual_of_a_single_moved_joint():
    gt = list(BASE.values())
    pred = list(gt)
    pred[5] = (gt[5][0], gt[5][1] + 60, gt[5][2])
    aligned = mb.procrustes_align(pred, gt)
    sq = lambda a: sum(mb._dot(mb._sub(p, g), mb._sub(p, g)) for p, g in zip(a, gt))  # noqa: E731
    assert sq(aligned) <= sq(pred) and mb.pa_mpjpe(pred, gt) > 0  # least squares: never worse than the identity fit


def test_joint_map_is_twelve_distinct_mhr70_joints():
    assert len(mb.COMPARED) == 12 and len(set(mb.MHR70_INDEX.values())) == 12
    assert mb.MHR70_INDEX["left_wrist"] == 62 and mb.MHR70_INDEX["right_wrist"] == 41
    assert not {"nose", "left_eye", "right_ear"} & set(mb.COMPARED)


def test_canonical_frame_ignores_world_yaw_and_shift():
    a = mb.canonicalize(world_gt(0))
    b = mb.canonicalize(world_gt(137))
    for j in BASE:
        assert a[j] == pytest.approx(b[j], abs=1e-6)
    assert a["left_hip"][0] > 0 > a["right_hip"][0]  # x is the subject's left
    assert a["left_hip"][1] == pytest.approx(0, abs=1e-9)


def test_degenerate_hips_are_an_error():
    pts = {**BASE, "left_hip": (0, 900, 0), "right_hip": (0, 900, 0)}
    with pytest.raises(mb.BenchError, match="degenerate"):
        mb.canonicalize(pts)


# ---- fixture builders (jobs, gt, manifest)

def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))


def make_render(root, shape, angle, condition, *, score, found=True, wrist_off_mm=0.0, at_s=1.0, window=(0.5, 1.5)):
    rid = f"{shape}-{angle}-{condition}"
    gt_world = world_gt(40)
    gt_frames = [{"frame": f, "joints": {j: list(p) for j, p in gt_world.items()}} for f in (0, 1, 2)]
    write(root / "gt" / f"{rid}.json", {"schema": mb.GT_SCHEMA, "unit": "mm", "up_axis": "y", "frames": gt_frames})
    can = mb.canonicalize(gt_world)
    can["left_wrist"] = (can["left_wrist"][0], can["left_wrist"][1] + wrist_off_mm, can["left_wrist"][2])
    pose = {"frames": [{"frame": f, "people": [{"id": 0, "joints": {j: {"x": p[0] / 1000, "y": p[1] / 1000, "z": p[2] / 1000, "conf": 1.0}
                                                                   for j, p in can.items()}}]} for f in (0, 1, 2)]}
    job = f"job-{rid}"
    write(root / "jobs" / job / "work" / "part2" / "pose3d.json", pose)
    faults = [{"measure": "knee_flexion", "side": "left", "at_s": at_s}] if found and condition == "knee15" else []
    write(root / "jobs" / job / "work" / "follower" / "analysis.json", {"score": {"value": score}, "faults": faults})
    planted = {"measure": "knee_flexion", "side": "left", "window_s": list(window), "magnitude_deg": 15} if condition == "knee15" else None
    return {"render_id": rid, "shape_id": shape, "shape_vector": [0.1, 0.2], "angle": angle, "condition": condition, "seed": 7,
            "intrinsics": {"fx": 1000, "fy": 1000, "cx": 360, "cy": 640, "width": 720, "height": 1280},
            "frames_sha256": [sha(rid + "0")], "gt_joints": f"gt/{rid}.json", "job_id": job, "planted_fault": planted}


def write_manifest(root, renders, **over):
    doc = {"schema": mb.MANIFEST_SCHEMA, "synthetic": True, "generator": "fixture", "renders": renders}
    doc.update(over)
    write(root / "manifest.json", doc)
    return root / "manifest.json"


def run(root, renders, **over):
    m = write_manifest(root, renders, **over)
    return mb.run(m, root / "jobs", repo_root=root, command="cmd")


# ---- AC-003: per render errors

def test_render_errors_match_a_known_joint_offset(tmp_path):
    r = make_render(tmp_path, "tall", "front", "clean", score=80, wrist_off_mm=30)
    rep = run(tmp_path, [r, make_render(tmp_path, "tall", "front", "knee15", score=75)])
    row = rep["per_body"][0]
    assert row["mpjpe_mm"] == pytest.approx(30 / 12, abs=0.01)
    assert row["pa_mpjpe_mm"] > 0
    assert rep["per_body"][1]["mpjpe_mm"] == 0.0


def test_no_shared_frame_is_an_error(tmp_path):
    r = make_render(tmp_path, "tall", "front", "clean", score=80)
    gt = json.loads((tmp_path / "gt" / "tall-front-clean.json").read_text())
    for fr in gt["frames"]:
        fr["frame"] += 100
    write(tmp_path / "gt" / "tall-front-clean.json", gt)
    with pytest.raises(mb.BenchError, match="share no frame"):
        run(tmp_path, [r, make_render(tmp_path, "tall", "front", "knee15", score=70)])


def test_gt_missing_a_joint_names_the_render(tmp_path):
    r = make_render(tmp_path, "tall", "front", "clean", score=80)
    gt = json.loads((tmp_path / "gt" / "tall-front-clean.json").read_text())
    del gt["frames"][0]["joints"]["left_knee"]
    write(tmp_path / "gt" / "tall-front-clean.json", gt)
    with pytest.raises(mb.BenchError, match="tall-front-clean.*left_knee"):
        run(tmp_path, [r])


# ---- AC-004: fault rule, spread, flags

def test_fault_found_rules():
    planted = {"measure": "knee_flexion", "side": "left", "window_s": [1.0, 2.0]}
    f = lambda **kw: {"faults": [{"measure": "knee_flexion", "side": "left", **kw}]}  # noqa: E731
    assert mb.fault_found(f(at_s=1.0), planted) and mb.fault_found(f(at_s=2.0), planted)
    assert not mb.fault_found(f(at_s=2.01), planted)
    assert mb.fault_found(f(follower_t_s=[1.5, 3.0]), planted)
    assert not mb.fault_found({"faults": [{"measure": "knee_flexion", "side": "right", "at_s": 1.5}]}, planted)
    assert not mb.fault_found({"faults": [{"measure": "foot_out", "side": "left", "at_s": 1.5}]}, planted)
    assert not mb.fault_found({"faults": []}, planted)


def test_spread_recall_and_flags(tmp_path):
    shapes = {"a": 80, "b": 82, "c": 69, "d": 81, "e": 79}
    renders = []
    for s, v in shapes.items():
        renders.append(make_render(tmp_path, s, "front", "clean", score=v))
        renders.append(make_render(tmp_path, s, "front", "knee15", score=v - 5, found=(s != "b")))
    rep = run(tmp_path, renders)
    assert rep["summary"] == {"score_spread": 13.0, "fault_recall": 0.8, "n": 10}
    kinds = {(f["kind"], f["shape_id"]) for f in rep["flags"]}
    assert kinds == {("missed_fault", "b"), ("score_outlier", "c")}  # median 80, c is 11 off


def test_outlier_boundary_is_strictly_more_than_ten_points():
    def rows(c_score):
        return [{"shape_id": s, "angle": "front", "condition": "clean", "score": v, "fault_planted": False, "fault_found": False}
                for s, v in {"a": 80, "b": 80, "c": c_score}.items()]
    assert mb._flags(rows(70)) == []  # exactly 10 off the median 80
    assert [f["shape_id"] for f in mb._flags(rows(69.9))] == ["c"]


def test_clean_score_is_the_mean_over_angles():
    rows = [{"shape_id": "a", "angle": g, "condition": "clean", "score": v} for g, v in (("front", 70), ("side", 80))]
    rows.append({"shape_id": "a", "angle": "front", "condition": "knee15", "score": 10})
    assert mb.body_clean_scores(rows) == {"a": 75}


def test_summary_needs_clean_and_planted_rows():
    clean_only = [{"shape_id": "a", "angle": "front", "condition": "clean", "score": 80, "fault_planted": False, "fault_found": False}]
    with pytest.raises(mb.BenchError, match="knee15"):
        mb.summarize(clean_only)
    with pytest.raises(mb.BenchError, match="clean"):
        mb.summarize([{**clean_only[0], "condition": "knee15", "fault_planted": True}])


# ---- AC-005..007: manifest validation, output contract, end to end

def test_manifest_validation_errors(tmp_path):
    good = [make_render(tmp_path, "a", "front", "clean", score=80), make_render(tmp_path, "a", "front", "knee15", score=70)]
    base = {"schema": mb.MANIFEST_SCHEMA, "synthetic": True, "renders": good}
    mb.validate_manifest(base)
    bad = [
        ({**base, "synthetic": False}, "synthetic must be true"),
        ({**base, "schema": "x"}, "schema"),
        ({**base, "renders": [{**good[0], "angle": "top"}]}, "angle"),
        ({**base, "renders": [{**good[0], "condition": "knee30"}]}, "condition"),
        ({**base, "renders": [good[0], good[0]]}, "duplicate"),
        ({**base, "renders": [{**good[1], "planted_fault": None}]}, "needs planted_fault"),
        ({**base, "renders": [{**good[0], "planted_fault": good[1]["planted_fault"]}]}, "planted_fault null"),
        ({**base, "renders": [{**good[0], "frames_sha256": ["abc"]}]}, "frames_sha256"),
        ({**base, "renders": []}, "non-empty"),
    ]
    for doc, msg in bad:
        with pytest.raises(mb.BenchError, match=msg):
            mb.validate_manifest(doc)


def test_missing_job_output_is_an_error(tmp_path):
    r = make_render(tmp_path, "a", "front", "clean", score=80)
    (tmp_path / "jobs" / r["job_id"] / "work" / "follower" / "analysis.json").unlink()
    with pytest.raises(mb.BenchError, match="analysis"):
        run(tmp_path, [r, make_render(tmp_path, "a", "front", "knee15", score=70)])


def test_end_to_end_fixture_and_cli(tmp_path, capsys):
    renders = [make_render(tmp_path, s, ang, cond, score=80 + (i % 3), wrist_off_mm=12.0 * i)
               for i, (s, ang, cond) in enumerate((s, a, c) for s in ("tall", "short") for a in ("front", "side") for c in ("clean", "knee15"))]
    m = write_manifest(tmp_path, renders)
    out = tmp_path / "out" / "mhr-bench.json"
    argv = ["--manifest", str(m), "--jobs-root", str(tmp_path / "jobs"), "--root", str(tmp_path), "--out", str(out)]
    assert mb.main(argv) == 0
    rep = json.loads(out.read_text())
    assert set(rep) == {"source_manifest_sha256", "command", "n", "per_body", "summary", "flags", "synthetic", "domain_gap_note"}
    assert rep["synthetic"] is True and rep["n"] == 8 and len(rep["per_body"]) == 8
    assert rep["source_manifest_sha256"] == hashlib.sha256(m.read_bytes()).hexdigest()
    assert set(rep["per_body"][0]) == {"shape_id", "angle", "condition", "mpjpe_mm", "pa_mpjpe_mm", "score", "fault_planted", "fault_found"}
    assert set(rep["summary"]) == {"score_spread", "fault_recall", "n"} and rep["summary"]["fault_recall"] == 1.0
    assert "domain gap" in rep["domain_gap_note"] and "python -m part7.mhr_bench" in rep["command"]
    assert "SYNTHETIC" in capsys.readouterr().out


def test_cli_exits_2_with_reason_on_bad_input(tmp_path, capsys):
    assert mb.main(["--manifest", str(tmp_path / "nope.json"), "--out", str(tmp_path / "o.json")]) == 2
    assert "mhr-bench: manifest" in capsys.readouterr().err
    assert not (tmp_path / "o.json").exists()
