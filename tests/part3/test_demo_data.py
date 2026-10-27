"""demo-viewer.md: web/data/demo.json is built from the metrics and the per-take detail."""
import json
import math

import numpy as np
import pytest

from part3 import demo_data, io
from part3.joints import BONES, JOINTS
from part3.metrics import compute

CAMERAS = [
    {"azimuth_deg": 0.0, "pitch_deg": 0.0, "roll_deg": 0.0},
    {"azimuth_deg": 45.0, "pitch_deg": 10.0, "roll_deg": 0.12345},
    {"azimuth_deg": 90.0, "pitch_deg": -8.0, "roll_deg": 15.0},
    {"azimuth_deg": 135.0, "pitch_deg": 20.0, "roll_deg": -12.0},
]


def make_doc(n_frames, empty=(), person_id=0, skeleton=False):
    """A pose3d (or skeleton) dict; frames in `empty` hold no person."""
    frames = []
    for i in range(n_frames):
        people = []
        if i not in empty:
            joints = {name: {"x": 0.123456789 + j, "y": -0.000001 * i, "z": 0.5 * i + 0.00004,
                             "conf": 1.0} for j, name in enumerate(JOINTS)}
            people = [{"id": person_id, "joints": joints}]
        frames.append({"frame": i, "t_ms": i * 66.667, "people": people})
    doc = {"frames": frames}
    if skeleton:
        doc["person"] = {"id": person_id}
    return doc


def make_metrics():
    return {
        "part": 3, "data_source": "synthetic", "pass": True,
        "thresholds": {
            "bone_length_variation_max": {"value": 0.00123456, "max": 0.02, "pass": True},
            "lr_flips": {"value": 0, "max": 0, "pass": True},
            "joint_angle_agreement_p95_deg": {"value": np.float64(6.123456), "max": 10.0, "pass": True},
            "negative_control_p95_deg": {"value": 31.98765, "min_exclusive": 10.0, "pass": True},
        },
        "context": {"frames_compared": 3, "flips_injected": 27, "flips_repaired": 27,
                    "agreement_per_angle_p95_deg": {"left_elbow": 1.23456}},
    }


def make_detail(n1=3, other_frames=(4, 2, 5), empty_output=()):
    frame_counts = (n1,) + tuple(other_frames)
    takes = []
    for k in range(1, 5):
        n = frame_counts[k - 1]
        takes.append({
            "take": k, "camera": CAMERAS[k - 1],
            "input": make_doc(n),
            "output": make_doc(n, empty=empty_output if k == 2 else (), skeleton=True),
            "map": np.linspace(0, n - 1, n1),
            "flips": [1] if k == 3 else [],
        })
    return {"takes": takes, "spread_max_per_frame": np.array([1.23456, np.nan, 3.0])}


def test_four_takes_with_colours_in_order():
    obj = demo_data.build(make_metrics(), make_detail())
    assert [t["take"] for t in obj["takes"]] == [1, 2, 3, 4]
    assert [t["color"] for t in obj["takes"]] == ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
    assert obj["fps"] == 15


def test_takes_are_ordered_even_when_the_detail_is_not():
    detail = make_detail()
    detail["takes"].reverse()
    obj = demo_data.build(make_metrics(), detail)
    assert [t["take"] for t in obj["takes"]] == [1, 2, 3, 4]


def test_camera_angles_rounded_to_three_decimals():
    obj = demo_data.build(make_metrics(), make_detail())
    assert obj["takes"][1]["camera"] == {"azimuth_deg": 45.0, "pitch_deg": 10.0, "roll_deg": 0.123}


def test_coordinates_rounded_to_four_decimals_in_canonical_order():
    obj = demo_data.build(make_metrics(), make_detail())
    frame = obj["takes"][0]["input"][1]
    assert len(frame) == 17 and all(len(point) == 3 for point in frame)
    assert frame[0] == [0.1235, 0.0, 0.5]
    assert frame[3][0] == 3.1235  # joint index 3 is left_ear: x = 0.1234... + 3


def test_negative_zero_is_folded_to_zero():
    obj = demo_data.build(make_metrics(), make_detail())
    assert "-0.0" not in demo_data.dumps(obj)


def test_null_frames_when_nobody_is_in_the_frame():
    obj = demo_data.build(make_metrics(), make_detail(empty_output=(1,)))
    assert obj["takes"][1]["output"][1] is None
    assert obj["takes"][1]["output"][0] is not None
    assert all(f is not None for f in obj["takes"][1]["input"])


def test_map_length_equals_take_one_frame_count():
    obj = demo_data.build(make_metrics(), make_detail(n1=3, other_frames=(4, 2, 5)))
    assert [len(t["map"]) for t in obj["takes"]] == [3, 3, 3, 3]
    assert [len(t["input"]) for t in obj["takes"]] == [3, 4, 2, 5]
    assert obj["takes"][3]["map"] == [0.0, 2.0, 4.0]


def test_bones_are_the_18_contract_bones_with_virtual_endpoints():
    obj = demo_data.build(make_metrics(), make_detail())
    bones = obj["bones"]
    assert len(bones) == 18 == len(BONES)
    assert bones[0] == [-1, JOINTS.index("left_hip")]      # left_pelvis: root -> left_hip
    assert bones[6] == [-1, -2]                             # spine: root -> neck
    assert bones[7] == [-2, JOINTS.index("left_shoulder")]  # left_clavicle: neck -> left_shoulder
    assert bones[13] == [-2, JOINTS.index("nose")]          # head: neck -> nose
    assert all(-2 <= a < 17 and -2 <= b < 17 for a, b in bones)


def test_nan_becomes_null():
    detail = make_detail()
    detail["takes"][1]["map"] = np.array([0.0, np.nan, 1.0])
    obj = demo_data.build(make_metrics(), detail)
    assert obj["spread_max_per_frame"] == [1.235, None, 3.0]
    assert obj["takes"][1]["map"] == [0.0, None, 1.0]
    json.loads(demo_data.dumps(obj))  # allow_nan=False would have raised on a stray NaN


def test_flips_listed_per_take():
    obj = demo_data.build(make_metrics(), make_detail())
    assert [t["flips"] for t in obj["takes"]] == [[], [], [1], []]


def test_agreement_figure_is_the_metrics_value_rounded_to_three():
    metrics = make_metrics()
    obj = demo_data.build(metrics, make_detail())
    page = obj["metrics"]["thresholds"]["joint_angle_agreement_p95_deg"]["value"]
    assert page == round(float(metrics["thresholds"]["joint_angle_agreement_p95_deg"]["value"]), 3) == 6.123


def test_metrics_rounding_keeps_ints_and_bools():
    out = demo_data.build(make_metrics(), make_detail())["metrics"]
    assert out["thresholds"]["lr_flips"]["value"] == 0 and isinstance(out["thresholds"]["lr_flips"]["value"], int)
    assert out["thresholds"]["lr_flips"]["pass"] is True
    assert out["pass"] is True
    assert out["context"]["flips_injected"] == 27 and isinstance(out["context"]["flips_injected"], int)
    assert out["thresholds"]["bone_length_variation_max"]["value"] == 0.001
    assert out["context"]["agreement_per_angle_p95_deg"]["left_elbow"] == 1.235
    assert out["data_source"] == "synthetic"


def test_metrics_rounding_rejects_values_the_page_cannot_show():
    with pytest.raises(TypeError):
        demo_data.round_metrics({"x": object()})


def test_takes_must_be_one_to_four():
    detail = make_detail()
    detail["takes"][3]["take"] = 5
    with pytest.raises(ValueError):
        demo_data.build(make_metrics(), detail)


def test_person_chosen_by_the_skeleton_person_id():
    detail = make_detail()
    other = make_doc(3, person_id=7)
    for frame in other["frames"]:
        for person in frame["people"]:
            for joint in person["joints"].values():
                joint["x"] = 9.0
    # input frame 0 holds a decoy person first, the kept person (id 0, as in the skeleton) second
    decoy = other["frames"][0]["people"][0]
    kept = detail["takes"][0]["input"]["frames"][0]["people"][0]
    detail["takes"][0]["input"]["frames"][0]["people"] = [decoy, kept]
    obj = demo_data.build(make_metrics(), detail)
    assert obj["takes"][0]["input"][0][0][0] == 0.1235


def test_output_is_deterministic_and_compact():
    a = demo_data.dumps(demo_data.build(make_metrics(), make_detail()))
    b = demo_data.dumps(demo_data.build(make_metrics(), make_detail()))
    assert a == b and a.endswith("\n") and ", " not in a and ": " not in a


def test_main_writes_the_file_from_compute(tmp_path, monkeypatch, capsys):
    calls = []

    def fake_compute(out_dir):
        calls.append(out_dir)
        return make_metrics(), make_detail()

    monkeypatch.setattr(demo_data, "compute", fake_compute)
    target = tmp_path / "web" / "data" / "demo.json"
    monkeypatch.setattr(demo_data, "OUT_PATH", target)
    monkeypatch.setattr(io, "REPO", tmp_path)
    assert demo_data.main() == 0
    assert calls == ["out/check-3"]
    written = json.loads(target.read_text())
    assert [t["take"] for t in written["takes"]] == [1, 2, 3, 4]
    assert "web/data/demo.json" in capsys.readouterr().out


def test_real_build_agreement_matches_compute(tmp_path):
    """Runs the real pipeline and builds the demo data from its metrics and detail."""
    measured, detail = compute(out_dir=str(tmp_path))
    obj = demo_data.build(measured, detail)
    key = "joint_angle_agreement_p95_deg"
    assert obj["metrics"]["thresholds"][key]["value"] == round(measured["thresholds"][key]["value"], 3)
    n1 = len(obj["takes"][0]["input"])
    assert all(len(t["map"]) == n1 for t in obj["takes"])
    assert len(obj["spread_max_per_frame"]) == n1
    assert math.isfinite(obj["metrics"]["thresholds"][key]["value"])
