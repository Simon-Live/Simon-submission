"""The done-check (AC-009): thresholds, pass rule, printing, exit code, and the machinery end to end."""

import functools
import json

import numpy as np
import pytest

from conftest import ROOT, SYNTH_DIR
from part3 import bones, metrics
from part3.temporal import centred_mean
from part3.angles import ANGLE_NAMES, joints_array
from part3.geometry import body_up, pelvis_frame
from part3.joints import GROUPS, INDEX, JOINTS, PAIRS, swap_index

# The "Metrics JSON" example of the output contract (field names final, 2026-10-27), copied here so the
# test runs in the published repository, which does not carry the workspace's docs/specs/.
CONTRACT_METRICS = json.loads("""
{
  "part": 3,
  "data_source": "synthetic",
  "data": {"real_clip": "fixtures/input/part2-single/pose3d.json",
           "takes": "fixtures/input/synthetic-4take/"},
  "alignment": {"method": "dtw", "reference_take": 1, "band_fraction": 0.25,
                "signal": "mean of 8 interior joint angles in degrees, 5-frame centred moving average",
                "frame_map": "middle paired frame, 3-frame centred mean, linear interpolation"},
  "angles": ["left_elbow", "right_elbow", "left_shoulder", "right_shoulder",
             "left_hip", "right_hip", "left_knee", "right_knee", "trunk_inclination"],
  "thresholds": {
    "bone_length_variation_max":     {"value": 0.0, "max": 0.02, "pass": true},
    "lr_flips":                      {"value": 0,   "max": 0,    "pass": true},
    "joint_angle_agreement_p95_deg": {"value": 0.0, "max": 10.0, "pass": true},
    "negative_control_p95_deg":      {"value": 0.0, "min_exclusive": 10.0, "pass": true}
  },
  "context": {"agreement_median_deg": 0.0, "agreement_mean_deg": 0.0, "agreement_max_deg": 0.0,
              "agreement_per_angle_p95_deg": {"left_elbow": 0.0},
              "agreement_linear_p95_deg": 0.0, "frames_compared": 0,
              "input_bone_length_variation_max": 0.0,
              "flips_injected": 27, "flips_repaired": 0, "real_clip_flips_detected_after_repair": 0,
              "up_error_max_deg": 0.0, "mirror_take_max_angle_diff_deg": 0.0},
  "pass": true
}
""")
STANDARD = bones.lengths_array(json.loads((ROOT / "part3" / "standard_body.json").read_text())["bone_lengths_m"])


# ---- an oracle stand-in for part3.cli.process --------------------------------------------------

@functools.lru_cache(maxsize=None)
def read_oracle_truth():
    """First-frame JSON -> injected swaps per frame, for every synthetic take (the oracle's knowledge)."""
    known = {}
    for folder in ("take-1", "take-2", "take-3", "take-4", "negative-armraise"):
        doc = json.loads((SYNTH_DIR / folder / "pose3d.json").read_text())
        truth = json.loads((SYNTH_DIR / folder / "truth.json").read_text())
        known[json.dumps(doc["frames"][0])] = [f["swapped"] for f in truth["frames"]]
    return known


def oracle_process(doc, flip="auto", sha256=None, trace=None):
    """Stand-in pipeline: undo the injected swaps from the truth, then Part 2 frame with the body up,
    5-frame mean and the standard body. Not the real pipeline; it lets the metrics machine run alone."""
    known = read_oracle_truth()
    J = joints_array(doc)
    conf = np.array([[j["conf"] for j in f["people"][0]["joints"].values()] for f in doc["frames"]])
    if flip == "on":
        perm = swap_index(PAIRS)
        J, conf = J[:, perm] * np.array([-1.0, 1.0, 1.0]), conf[:, perm]
    swapped = known.get(json.dumps(doc["frames"][0]), [[] for _ in J])
    for i, groups in enumerate(swapped):
        for group in groups:
            perm = swap_index(GROUPS[group])
            J[i], conf[i] = J[i][perm], conf[i][perm]
            if group == "body":
                J[i] = J[i] * np.array([-1.0, 1.0, -1.0])
    up, _ = body_up(J)
    P = bones.retarget(centred_mean(pelvis_frame(J, up)[0], 5), STANDARD)
    if trace is not None:
        trace["up_in_input"] = up.tolist()
    frames = [{"frame": f["frame"], "t_ms": f["t_ms"], "people": [{"id": 0, "flips_repaired": swapped[i], "joints": {
        name: {"x": round(float(P[i, j, 0]), 4), "y": round(float(P[i, j, 1]), 4),
               "z": round(float(P[i, j, 2]), 4), "conf": float(conf[i, j])} for j, name in enumerate(JOINTS)}}]}
        for i, f in enumerate(doc["frames"])]
    return {"bone_lengths_m": dict(zip(bones.BONE_NAMES, STANDARD.tolist())), "frames": frames}


def blind_process(doc, flip="auto", sha256=None, trace=None):
    """The same stand-in without any flip repair."""
    out = oracle_process(doc, flip, sha256, trace)
    for frame in out["frames"]:
        frame["people"][0]["flips_repaired"] = []
    return out


# ---- thresholds, pass and printing ---------------------------------------------------------------

def measured(**over):
    samples = [np.full((20, 9), v) for v in (10.0, 11.0, 12.0, 13.0)]
    stats = metrics.spread_stats(samples)
    base = {"agreement": stats, "linear": stats, "control": {**stats, "p95": 25.0}, "bone_max": 0.005,
            "input_bone_max": 0.24, "lr_flips": 0, "injected": 27, "repaired": 27, "real_flags": 0,
            "up_error": 1.2, "mirror_diff": 0.0}
    base.update(over)
    return base


def with_p95(entry, value):
    return {**entry, "p95": value}


def test_all_good_values_pass():
    m = metrics.build_metrics(measured())
    assert m["pass"] is True and all(t["pass"] for t in m["thresholds"].values())
    assert metrics.failure_reasons(m) == []


@pytest.mark.parametrize("over, name", [
    ({"bone_max": 0.02}, "bone_length_variation_max"),
    ({"lr_flips": 1}, "lr_flips"),
    ({"agreement": with_p95(measured()["agreement"], 10.0000001)}, "joint_angle_agreement_p95_deg"),
    ({"control": with_p95(measured()["control"], 10.0)}, "negative_control_p95_deg"),
])
def test_each_threshold_alone_fails_the_check(over, name):
    m = metrics.build_metrics(measured(**over))
    assert m["pass"] is False
    assert [k for k, t in m["thresholds"].items() if not t["pass"]] == [name]


def test_limits_are_inclusive_or_exclusive_as_the_contract_says():
    just_pass = measured(bone_max=0.0199999, agreement=with_p95(measured()["agreement"], 10.0),
                         control=with_p95(measured()["control"], 10.0000001))
    assert metrics.build_metrics(just_pass)["pass"] is True


def test_pass_uses_unrounded_values_while_printing_rounds():
    m = metrics.build_metrics(measured(agreement=with_p95(measured()["agreement"], 10.0004)))
    printed = metrics.round_numbers(m)
    assert printed["thresholds"]["joint_angle_agreement_p95_deg"]["value"] == 10.0
    assert m["thresholds"]["joint_angle_agreement_p95_deg"]["pass"] is False and m["pass"] is False
    control = metrics.build_metrics(measured(control=with_p95(measured()["control"], 10.0004)))
    assert metrics.round_numbers(control)["thresholds"]["negative_control_p95_deg"]["value"] == 10.0
    assert control["pass"] is True  # 10.0004 is strictly above 10 although it prints as 10.0


def test_round_numbers_rounds_floats_only():
    out = metrics.round_numbers({"a": 1.23456, "b": 7, "c": True, "d": None, "e": [0.00049, 2.0005]})
    assert out == {"a": 1.235, "b": 7, "c": True, "d": None, "e": [0.0, 2.001]}


def test_too_permissive_and_too_short_reasons():
    m = metrics.build_metrics(measured(control=with_p95(measured()["control"], 9.5)))
    assert metrics.failure_reasons(m) == ["alignment too permissive"]
    assert metrics.failure_reasons(m, short_takes=[3]) == ["take 3 too short", "alignment too permissive"]


def shape(obj):
    if isinstance(obj, dict):
        return {k: shape(v) for k, v in obj.items()}
    return "bool" if isinstance(obj, bool) else "number" if isinstance(obj, (int, float)) else type(obj).__name__


def test_metrics_json_has_exactly_the_contract_keys():
    contract = CONTRACT_METRICS
    built = metrics.build_metrics(measured())
    assert list(built) == list(contract)
    assert shape(built["thresholds"]) == shape(contract["thresholds"])
    per_angle = "agreement_per_angle_p95_deg"  # the contract shows one example entry; all 9 are checked below
    assert {k: v for k, v in shape(built["context"]).items() if k != per_angle} == {
        k: v for k, v in shape(contract["context"]).items() if k != per_angle}
    assert list(built["context"]) == list(contract["context"])
    assert built["angles"] == contract["angles"] == list(ANGLE_NAMES)
    assert built["alignment"] == contract["alignment"] and built["data"] == contract["data"]
    assert list(built["context"]["agreement_per_angle_p95_deg"]) == list(ANGLE_NAMES)
    assert built["data_source"] == "synthetic" and built["part"] == 3


# ---- statistics ------------------------------------------------------------------------------

def test_spread_is_max_minus_min_across_takes_and_skips_incomplete_frames():
    a = np.zeros((5, 9))
    b = a + np.arange(9)
    c = a - 2.0
    d = a.copy()
    d[3] = np.nan
    stats = metrics.spread_stats([a, b, c, d])
    # angle j holds 0, j, -2, 0 across the takes: spread j + 2, in the four frames every take has
    expected = np.tile(np.arange(9.0) + 2.0, 4)
    assert stats["frames_compared"] == 4
    assert np.isnan(stats["per_frame_max"][3]) and np.allclose(stats["per_frame_max"][[0, 1, 2, 4]], 10.0)
    assert stats["max"] == 10.0 and stats["median"] == np.median(expected) and stats["mean"] == expected.mean()
    assert stats["p95"] == np.percentile(expected, 95)
    assert list(stats["per_angle_p95"]) == list(ANGLE_NAMES)
    assert list(stats["per_angle_p95"].values()) == list(np.arange(9.0) + 2.0)
    assert metrics.spread_stats([np.full((3, 9), np.nan)] * 4) is None


def test_linear_samples_use_rint_of_the_scaled_index():
    ref = np.zeros((5, 9))
    other = np.arange(9.0)[:, None] * np.ones((1, 9))
    samples = metrics.linear_samples([ref, other])
    assert np.allclose(samples[0], 0) and np.allclose(samples[1][:, 0], [0, 2, 4, 6, 8])


def test_bone_variation_measures_against_the_stated_and_the_median_lengths():
    doc = oracle_process(json.loads((ROOT / "fixtures/input/part2-single/pose3d.json").read_text()))
    assert metrics.bone_variation(doc, STANDARD) < 0.01  # only 4-decimal rounding
    real = json.loads((ROOT / "fixtures/input/part2-single/pose3d.json").read_text())
    assert metrics.input_bone_variation(real) > 0.1  # the real clip's bones vary a lot
    assert metrics.bone_variation(doc, STANDARD * 1.05) == pytest.approx(0.05, abs=0.01)


def test_flip_helpers():
    doc = {"frames": [{"people": [{"flips_repaired": ["legs"]}]}, {"people": []},
                      {"people": [{"flips_repaired": []}]}]}
    assert metrics.flip_sets(doc, "flips_repaired") == [{"legs"}, set(), set()]
    assert metrics.flagged_frames(doc) == [0]


def test_up_error_ignores_body_swapped_frames():
    truth = {"frames": [{"swapped": [], "up_in_input": [0, 1, 0]}, {"swapped": ["body"], "up_in_input": [0, 1, 0]},
                        {"swapped": ["legs"], "up_in_input": [0, 1, 0]}]}
    assert metrics.up_error_deg([0, 1, 0], truth) == pytest.approx(0.0, abs=1e-6)
    tilted = [0, np.cos(np.radians(2)), np.sin(np.radians(2))]
    assert metrics.up_error_deg(tilted, truth) == pytest.approx(2.0, abs=1e-6)


# ---- main: printing, files, exit code ------------------------------------------------------------

def stub_compute(passing):
    m = metrics.build_metrics(measured(**({} if passing else {"lr_flips": 3})))
    return lambda out_dir=metrics.DEFAULT_OUT: (m, {"failures": [] if passing else ["lr_flips: value 3 fails the limit"]})


def test_main_exits_zero_when_every_threshold_passes(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(metrics, "compute", stub_compute(True))
    assert metrics.main(str(tmp_path)) == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["pass"] is True and out.err == ""
    assert (tmp_path / "metrics.json").read_text() == out.out


def test_main_exits_one_and_names_the_reason_on_stderr_when_a_threshold_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(metrics, "compute", stub_compute(False))
    assert metrics.main(str(tmp_path)) == 1
    out = capsys.readouterr()
    printed = json.loads(out.out)
    assert printed["pass"] is False and printed["thresholds"]["lr_flips"]["pass"] is False
    assert "lr_flips" in out.err
    assert "failures" not in printed  # exactly the contract fields on stdout


def test_main_prints_indent_two_and_three_decimals(monkeypatch, tmp_path, capsys):
    m = metrics.build_metrics(measured(bone_max=0.0123456))
    monkeypatch.setattr(metrics, "compute", lambda out_dir: (m, {"failures": []}))
    metrics.main(str(tmp_path))
    text = capsys.readouterr().out
    assert text.startswith('{\n  "part": 3,\n') and '"value": 0.012,' in text


# ---- the machinery end to end with the stand-in pipeline ------------------------------------------

@pytest.fixture(scope="module")
def oracle_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("check3-oracle")
    return metrics.compute(str(out), process=oracle_process), out


def test_oracle_pipeline_passes_every_threshold(oracle_run):
    m, detail = oracle_run[0]
    assert detail["failures"] == [] and m["pass"] is True
    t = m["thresholds"]
    assert t["lr_flips"]["value"] == 0 and t["joint_angle_agreement_p95_deg"]["value"] <= 10.0
    assert t["negative_control_p95_deg"]["value"] > 10.0
    c = m["context"]
    assert c["flips_injected"] == 27 and c["flips_repaired"] == 27 and c["real_clip_flips_detected_after_repair"] == 0
    assert c["up_error_max_deg"] < 3.0 and c["mirror_take_max_angle_diff_deg"] < 1.0
    assert c["input_bone_length_variation_max"] > 0.1 and c["frames_compared"] > 100
    assert c["agreement_linear_p95_deg"] > t["joint_angle_agreement_p95_deg"]["value"]


def test_oracle_run_writes_every_output_and_the_detail_the_viewer_needs(oracle_run):
    (m, detail), out = oracle_run
    for rel in ("part2-single", "synthetic-4take/take-1", "synthetic-4take/take-2", "synthetic-4take/take-3",
                "synthetic-4take/take-4", "synthetic-4take/take-1-mirrored", "synthetic-4take/negative-armraise"):
        assert (out / rel / "skeleton.json").is_file(), rel
    assert [t["take"] for t in detail["takes"]] == [1, 2, 3, 4]
    n1 = len(detail["takes"][0]["input"]["frames"])
    for take in detail["takes"]:
        assert set(take) == {"take", "camera", "input", "output", "map", "flips"}
        assert take["map"].shape == (n1,) and set(take["camera"]) == {"azimuth_deg", "pitch_deg", "roll_deg"}
    assert np.array_equal(detail["takes"][0]["map"], np.arange(n1))
    assert detail["takes"][3]["flips"] == list(range(20, 25)) + list(range(61, 66))
    assert detail["takes"][2]["flips"] == list(range(30, 36)) + list(range(80, 84)) + [86, 87, 88]
    spread = detail["spread_max_per_frame"]
    assert spread.shape == (n1,) and np.isfinite(spread).sum() == m["context"]["frames_compared"]


def test_blind_pipeline_counts_every_unrepaired_swap(tmp_path):
    m, detail = metrics.compute(str(tmp_path), process=blind_process)
    assert m["thresholds"]["lr_flips"]["value"] == 27 and m["pass"] is False
    assert m["context"]["flips_repaired"] == 0 and "lr_flips" in " ".join(detail["failures"])


def test_a_take_with_fewer_than_ten_frames_with_a_person_fails_with_its_reason(tmp_path):
    def short_process(doc, flip="auto", sha256=None, trace=None):
        out = oracle_process(doc, flip, sha256, trace)
        if trace is not None:  # the synthetic takes only
            for frame in out["frames"][5:]:
                frame["people"] = []
        return out
    m, detail = metrics.compute(str(tmp_path), process=short_process)
    assert [r for r in detail["failures"] if r.endswith("too short")] == [
        "take 1 too short", "take 2 too short", "take 3 too short", "take 4 too short", "take 6 too short"]
    assert m["thresholds"]["joint_angle_agreement_p95_deg"]["value"] is None and m["pass"] is False


def test_process_is_called_with_the_flip_setting_and_a_trace(tmp_path):
    calls = []

    def spy(doc, flip="auto", sha256=None, trace=None):
        calls.append((len(doc["frames"]), doc.get("mirrored"), flip, sha256 is not None, trace is not None))
        return oracle_process(doc, flip, sha256, trace)
    metrics.compute(str(tmp_path), process=spy)
    mirrored = [c for c in calls if c[1]]
    assert mirrored == [(113, True, "on", True, False)]
    assert all(c[2] == "auto" for c in calls if not c[1])
    assert [c[4] for c in calls[2:6]] == [True] * 4  # takes 1 to 4 carry a trace


# ---- the real pipeline end to end ----------------------------------------------------------------

SYNTHETIC_OUTPUTS = ("take-1", "take-2", "take-3", "take-4", "take-1-mirrored", "negative-armraise")


def facing_violations(doc):
    """(frames with a person where the left hip is not at +x or the nose is not ahead of the ears
    along +z, frames with a person) of a pose3d or skeleton document."""
    J = joints_array(doc)
    seen = np.isfinite(J).all(axis=(1, 2))
    ear_z = (J[:, INDEX["left_ear"], 2] + J[:, INDEX["right_ear"], 2]) / 2.0
    facing = (J[:, INDEX["left_hip"], 0] > 0) & (J[:, INDEX["nose"], 2] > ear_z)
    return int((seen & ~facing).sum()), int(seen.sum())


def test_the_facing_check_catches_the_injected_body_swaps():
    swapped_input = json.loads((SYNTH_DIR / "take-4" / "pose3d.json").read_text())
    assert facing_violations(swapped_input)[0] == 10  # 2 runs of 5 body swaps turn the person around


def test_end_to_end_with_the_real_pipeline(tmp_path, capsys):
    assert metrics.main(str(tmp_path)) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["pass"] is True and printed["data_source"] == "synthetic"
    assert (tmp_path / "metrics.json").is_file()
    context = printed["context"]
    assert context["up_error_max_deg"] < 3.0  # AC-006: the body up of every take recovered
    assert context["mirror_take_max_angle_diff_deg"] < 1.0  # AC-007: the mirrored take with flip on
    for folder in SYNTHETIC_OUTPUTS:  # AC-006: left hip line along +x and the face towards +z
        skeleton = json.loads((tmp_path / "synthetic-4take" / folder / "skeleton.json").read_text())
        violations, seen = facing_violations(skeleton)
        assert seen >= metrics.MIN_FRAMES and violations == 0, folder
