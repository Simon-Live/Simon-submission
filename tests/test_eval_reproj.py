import json

import numpy as np
import pytest
from test_canonical import _body3d

from part2 import cli
from part2.canonical import convert
from part2.eval_reproj import body_height_px, evaluate
from part2.joints import CANONICAL


def _setup(n=20, side_every=4, noise_px=0.0, seed=0):
    yaws = [90 if side_every and i % side_every == 0 else 10 for i in range(n)]
    b = _body3d(yaws)
    pose3d, camera = convert(b)
    rng = np.random.default_rng(seed)
    labels = {"frames": [
        {"frame": f["frame"], "view": "side" if yaws[f["frame"]] == 90 else "front",
         "joints": {j: (np.array(f["people"][0]["kp2d"][j]) + rng.normal(0, noise_px, 2)).tolist() for j in CANONICAL}}
        for f in b["frames"]]}
    return pose3d, camera, labels


def test_perfect_prediction_passes():
    m = evaluate(*_setup())
    assert m["pass"] and m["n_frames"] == 20 and m["n_side_frames"] == 5
    assert m["max_pct"] < 0.1


def test_large_error_fails_and_names_worst_frame():
    pose3d, camera, labels = _setup()
    for j in CANONICAL:  # shift every click on frame 7 by 40 px (~16% of ~250 px height)
        labels["frames"][7]["joints"][j][0] += 40
    m = evaluate(pose3d, camera, labels)
    assert not m["pass"] and m["worst_frame"] == 7 and m["n_failed_frames"] == 1
    assert not m["checks"]["within_threshold"]
    # the same single bad frame passes under the looser mean rule
    assert evaluate(pose3d, camera, labels, rule="mean")["checks"]["within_threshold"]


def test_requires_twenty_frames_and_side_views():
    m = evaluate(*_setup(n=12))
    assert m["checks"] == {"enough_frames": False, "has_side_views": True, "within_threshold": True}
    m = evaluate(*_setup(side_every=None))
    assert not m["checks"]["has_side_views"] and not m["pass"]


def test_missing_prediction_fails_and_frame_without_nose_uses_clip_height():
    pose3d, camera, labels = _setup()
    pose3d["frames"][3]["people"] = []
    labels["frames"][5]["joints"]["nose"] = None
    rows = {r["frame"]: r for r in evaluate(pose3d, camera, labels)["per_frame"]}
    assert not rows[3]["ok"] and "no prediction" in rows[3]["note"]
    assert rows[5]["ok"] and rows[5]["frame_height_px"] is None and rows[5]["height_px"] > 0


def test_unmeasurable_height_fails_when_no_frame_has_nose():
    pose3d, camera, labels = _setup()
    for lf in labels["frames"]:
        lf["joints"]["nose"] = None
    m = evaluate(pose3d, camera, labels)
    assert not m["pass"] and all("height" in r["note"] for r in m["per_frame"])


def test_height_is_clip_max_so_a_folded_frame_is_not_penalised():
    pose3d, camera, labels = _setup()
    clip_h = max(r["frame_height_px"] for r in evaluate(pose3d, camera, labels)["per_frame"])
    lf = labels["frames"][7]
    for j in CANONICAL:  # 3% of clip height off on every joint
        lf["joints"][j][0] += 0.03 * clip_h
    lf["joints"]["nose"] = None  # stand-in for a fold: this frame's own height is unmeasurable/short
    m = evaluate(pose3d, camera, labels)
    row = next(r for r in m["per_frame"] if r["frame"] == 7)
    assert row["height_px"] == pytest.approx(clip_h, abs=0.1) and row["ok"]
    assert row["error_pct"] == pytest.approx(3.0, abs=0.2)
    assert all(r["height_px"] == pytest.approx(clip_h, abs=0.1) for r in m["per_frame"])
    assert m["body_height"].startswith("clip_max")


def test_unclicked_joints_are_not_scored():
    pose3d, camera, labels = _setup()
    labels["frames"][0]["joints"]["left_wrist"] = None
    row = evaluate(pose3d, camera, labels)["per_frame"][0]
    assert row["n_joints"] == 16 and row["ok"]


def test_body_height_uses_nose_to_ankle_midpoint():
    c = {"nose": np.array([0.0, 0]), "left_ankle": np.array([-10.0, 100]), "right_ankle": np.array([10.0, 100])}
    assert body_height_px(c) == pytest.approx(100)
    assert body_height_px({"nose": np.array([0.0, 0])}) is None


def test_cli_prints_metrics_and_exit_code(tmp_path, capsys):
    pose3d, camera, labels = _setup()
    for name, doc in [("pose3d", pose3d), ("camera", camera), ("labels", labels)]:
        (tmp_path / f"{name}.json").write_text(json.dumps(doc))
    args = ["eval-reproj", "--pose3d", str(tmp_path / "pose3d.json"), "--camera", str(tmp_path / "camera.json"),
            "--labels", str(tmp_path / "labels.json")]
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["pass"] is True
    labels["frames"][0]["joints"]["left_wrist"][1] += 1000
    (tmp_path / "labels.json").write_text(json.dumps(labels))
    assert cli.main(args) == 1


def test_labels_are_validated():
    pose3d, camera, labels = _setup()
    dup = {"frames": labels["frames"] + [labels["frames"][0]]}
    with pytest.raises(ValueError, match="listed twice"):
        evaluate(pose3d, camera, dup)
    labels["frames"][0]["joints"]["nosee"] = [1, 1]
    with pytest.raises(ValueError, match="unknown joints"):
        evaluate(pose3d, camera, labels)


def test_pose_without_camera_entry_scores_as_missing():
    pose3d, camera, labels = _setup()
    camera["frames"][2]["people"] = []
    row = evaluate(pose3d, camera, labels)["per_frame"][2]
    assert not row["ok"] and "no prediction" in row["note"]


def test_worst_joint_named():
    pose3d, camera, labels = _setup()
    labels["frames"][0]["joints"]["left_knee"][0] += 30
    assert evaluate(pose3d, camera, labels)["per_frame"][0]["worst_joint"] == "left_knee"
