"""The CPU 3D bar (docs/specs/backends-gpu-cpu.md "3D bar", AC-B09; docs/specs/check-2.md AC-K07)."""
import json

import numpy as np
import pytest
from test_lifter_fixed_bones import skeleton

from part2 import eval_3d
from part2.joints import CANONICAL


def _pose3d(points, frames=None, pid=0, extra_people=()):
    """pose3d.json from (n, 17, 3) points, hip-centred like the canonical frame."""
    pts = np.asarray(points, float)
    pts = pts - (pts[:, 11] + pts[:, 12])[:, None] / 2
    frames = list(range(len(pts))) if frames is None else frames
    out = []
    for f, p in zip(frames, pts):
        people = [{"id": pid, "joints": {j: {"x": float(x), "y": float(y), "z": float(z), "conf": 1.0}
                                         for j, (x, y, z) in zip(CANONICAL, p)}}]
        people += [{"id": e, "joints": people[0]["joints"]} for e in extra_people]
        out.append({"frame": f, "t_ms": f * 100.0, "people": people})
    return {"frames": out}


def test_identical_files_score_zero_and_pass():
    doc = _pose3d(skeleton(10))
    r = eval_3d.evaluate(doc, doc, lifter="fixed-bones")
    assert r["pass"] is True and r["mean_m"] == 0 and r["p95_m"] == 0 and r["frames"] == 10
    assert r["bone_cv_mean"] == pytest.approx(0, abs=1e-4) and r["lifter"] == "fixed-bones"
    assert set(r) >= {"pass", "mean_m", "p95_m", "worst_joint", "bone_cv_mean", "bone_cv_max", "frames", "lifter"}


def test_a_two_decimetre_offset_fails_on_distance():
    ref = _pose3d(skeleton(10))
    moved = json.loads(json.dumps(ref))
    for f in moved["frames"]:
        for j in f["people"][0]["joints"].values():
            j["x"] += 0.2
    r = eval_3d.evaluate(moved, ref)
    assert r["pass"] is False and r["mean_m"] == pytest.approx(0.2, abs=1e-4)
    assert r["bone_cv_mean"] == pytest.approx(0, abs=1e-4)  # rigid shift: stable bones, still failing


def test_bone_cv_fails_a_stretching_skeleton_even_at_small_distance():
    pts = skeleton(10)
    ref = _pose3d(pts)
    scale = np.where(np.arange(10) % 2, 1.12, 0.88)[:, None, None]
    r = eval_3d.evaluate(_pose3d(pts * scale), ref)
    assert r["bone_cv_mean"] == pytest.approx(0.12, abs=0.005) and r["pass"] is False


def test_worst_joint_and_p95_follow_the_largest_error():
    pts = skeleton(10)
    ref = _pose3d(pts)
    bad = json.loads(json.dumps(ref))
    for f in bad["frames"]:
        f["people"][0]["joints"]["right_wrist"]["z"] += 0.5
    r = eval_3d.evaluate(bad, ref)
    assert r["worst_joint"] == "right_wrist" and r["mean_m"] == pytest.approx(0.5 / 17, abs=1e-4)
    assert r["p95_m"] == pytest.approx(0.5, abs=1e-4)  # 1 joint in 17 is 5.9% of the distances


def test_matches_on_frame_number_and_person_zero_only():
    pts = skeleton(6)
    ref = _pose3d(pts, frames=[0, 2, 4, 6, 8, 10])
    cpu = _pose3d(pts[1:4], frames=[2, 4, 6], extra_people=(1,))
    r = eval_3d.evaluate(cpu, ref)
    assert r["frames"] == 3 and r["missing_frames"] == 3 and r["mean_m"] == 0
    assert eval_3d.evaluate(_pose3d(pts, pid=1), ref)["status"].startswith("no frames with person 0")


def test_lifter_comes_from_provenance_or_the_stamp(tmp_path):
    doc = _pose3d(skeleton(3))
    assert eval_3d.evaluate({**doc, "provenance": {"lifter": "motionbert"}}, doc)["lifter"] == "motionbert"
    (tmp_path / "pose3d.json").write_text(json.dumps(doc))
    (tmp_path / "stamp.json").write_text(json.dumps({"lifter": "fixed-bones"}))
    assert eval_3d.block(tmp_path / "pose3d.json", tmp_path / "pose3d.json")["lifter"] == "fixed-bones"


def test_block_and_exit_codes_for_missing_failing_and_passing(tmp_path):
    good = tmp_path / "ref.json"
    good.write_text(json.dumps(_pose3d(skeleton(4))))
    missing = tmp_path / "none.json"
    r = eval_3d.block(missing, good)
    assert r == {"pass": False, "status": eval_3d.NO_CPU, "reference": str(good)} and eval_3d.exit_code(r) == 2
    assert eval_3d.block(good, missing)["status"] == eval_3d.NO_REF
    assert eval_3d.exit_code(eval_3d.block(good, missing)) == 2
    assert eval_3d.exit_code(eval_3d.block(good, good)) == 0
    far = json.loads(good.read_text())
    for f in far["frames"]:
        f["people"][0]["joints"]["nose"]["y"] += 3.0
    (tmp_path / "far.json").write_text(json.dumps(far))
    assert eval_3d.exit_code(eval_3d.block(tmp_path / "far.json", good)) == 1


def test_missing_cpu_status_matches_check_2_spec():
    assert eval_3d.NO_CPU == "no cpu outputs; run make outputs BACKEND=cpu"


def test_viewer_html_works_as_the_reference(tmp_path):
    doc = _pose3d(skeleton(3))
    data = {"id": 0, "joints": CANONICAL, "frames": [
        {"frame": f["frame"], "t_ms": f["t_ms"], "file": "x.jpg",
         "joints": [[f["people"][0]["joints"][j][k] for k in "xyz"] for j in CANONICAL]} for f in doc["frames"]]}
    data["frames"].append({"frame": 3, "t_ms": 300.0, "file": "y.jpg", "joints": None})
    html = tmp_path / "viewer.html"
    html.write_text(f"<html><script>\nconst D = {json.dumps(data)};\nconst x = 1;</script></html>")
    ref = eval_3d.load_pose3d(html)
    assert len(ref["frames"]) == 4 and ref["frames"][3]["people"] == []
    r = eval_3d.evaluate(doc, ref)
    assert r["mean_m"] == 0 and r["frames"] == 3
    (tmp_path / "plain.html").write_text("<html></html>")
    with pytest.raises(ValueError, match="no embedded viewer data"):
        eval_3d.load_pose3d(tmp_path / "plain.html")


def test_cli_prints_the_block_and_exits_by_it(tmp_path, capsys):
    p = tmp_path / "pose3d.json"
    p.write_text(json.dumps(_pose3d(skeleton(3))))
    assert eval_3d.main(["--cpu", str(p), "--reference", str(p), "--lifter", "fixed-bones"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["pass"] is True and out["lifter"] == "fixed-bones"
    assert eval_3d.main(["--cpu", str(tmp_path / "missing.json"), "--reference", str(p)]) == 2
    capsys.readouterr()
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"frames": [{"frame": 0, "people": [{"id": 0, "joints": {}}]}]}))
    assert eval_3d.main(["--cpu", str(bad), "--reference", str(p)]) == 1
    assert json.loads(capsys.readouterr().out)["status"].startswith("error: KeyError")
