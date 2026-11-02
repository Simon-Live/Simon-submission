"""Scoring validity (docs/specs/scoring-validity.md, TICKET-082): the planted errors, the dose-response read-outs, the
transforms of a clip, the chart and `make bench-score`'s run. GPU free; the takes are committed seed 5 fixtures.

The monotonicity test (AC-SV06) is in tests/test_score_monotone.py.
"""
import functools
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_bench_score as bench  # noqa: E402
import make_bench_score_chart as chart  # noqa: E402
import make_score_validity as sv  # noqa: E402
from part5 import score  # noqa: E402
from part5.io import InputError, JOINTS  # noqa: E402

TAKE_ID = "exercise_front_good_00_correct"
EXPECTED = ROOT / "fixtures/input/expected/exercise/animation.json"
JOINT_NAMES = tuple(sv.PLANTED)


def take_of(take_id=TAKE_ID):
    return next(t for t in sv.pool() if t["take_id"] == take_id)


@functools.lru_cache(maxsize=None)
def committed_rows():
    """The dose-response of the committed take: 4 joints, 13 steps (52 pipeline runs, once per process)."""
    return tuple(sv.dose_rows([take_of()]))


# ---------------------------------------------------------------- AC-SV01: planting
@pytest.mark.parametrize("joint", JOINT_NAMES)
def test_ac_sv01_a_planted_error_is_the_size_asked_for(joint):
    doc = sv.load_doc(ROOT / take_of()["follower"])
    for deg in (2.5, 15.0, 30.0):
        assert sv.realised_deg(doc, sv.plant(doc, joint, deg), joint) == pytest.approx(deg, abs=1.0)


@pytest.mark.parametrize("joint", JOINT_NAMES)
def test_ac_sv01_zero_degrees_plants_nothing(joint):
    doc = sv.load_doc(ROOT / take_of()["follower"])
    assert np.array_equal(sv.positions_of(sv.plant(doc, joint, 0.0))[1], sv.positions_of(doc)[1])


def test_ac_sv01_planting_leaves_the_hip_midpoint_at_the_origin_and_never_edits_its_argument():
    doc = sv.load_doc(ROOT / take_of()["follower"])
    before = json.dumps(doc)
    for joint in JOINT_NAMES:
        planted = sv.plant(doc, joint, 30.0)
        P = sv.positions_of(planted)[1]
        mid = (P[:, JOINTS.index("left_hip")] + P[:, JOINTS.index("right_hip")]) / 2
        assert np.abs(mid).max() <= 0.01   # the loader's own tolerance
        sv.analyse(EXPECTED, planted)   # the loader accepts it
    assert json.dumps(doc) == before


# ---------------------------------------------------------------- AC-SV02, AC-SV03: rows and first fire
def test_ac_sv02_a_row_names_the_matching_fault_and_the_other_faults():
    rows = {(r["joint"], r["planted_deg"]): r for r in committed_rows()}
    clean, planted = rows[("trunk", 0.0)], rows[("trunk", 30.0)]
    assert clean["matching"] is None and clean["extra_faults"] == [] and clean["value"] == 100 and clean["grade"] == "A"
    assert planted["matching"]["measure"] == "trunk_lean_forward" and planted["matching"]["direction"] == "more"
    assert planted["value"] < 100 and planted["planted_deg"] == 30.0 and planted["realised_deg"] == pytest.approx(30.0, abs=1.0)
    assert len(committed_rows()) == len(JOINT_NAMES) * len(sv.GRID)


def test_ac_sv02_a_hip_error_may_bring_a_second_fault_and_the_row_keeps_it():
    big = [r for r in committed_rows() if r["joint"] == "hip" and r["planted_deg"] == 30.0][0]
    assert big["matching"]["measure"] in sv.PLANTED["hip"].measures
    assert big["n_faults"] == 1 + len(big["extra_faults"])


def test_ac_sv03_first_fire_is_the_smallest_planted_angle_with_the_matching_fault():
    fires = sv.first_fire(list(committed_rows()))
    for joint in JOINT_NAMES:
        first = fires[joint][TAKE_ID]["first"]
        assert first is not None and fires[joint][TAKE_ID]["stable"]
        by_deg = {r["planted_deg"]: r for r in committed_rows() if r["joint"] == joint}
        assert by_deg[first]["matching"] and all(not by_deg[d]["matching"] for d in sv.GRID if d < first)


def test_ac_sv03_the_summary_counts_a_take_that_never_fires_as_above_the_grid():
    fires = {"knee": {"a": {"first": 5.0, "stable": True}, "b": {"first": 10.0, "stable": False},
                      "c": {"first": None, "stable": False}}}
    s = sv.fire_summary(fires)["knee"]
    assert s == {"median_low": 10.0, "min": 5.0, "max": None, "takes": 3, "never": 1, "stable": 1}


def test_ac_sv03_a_fault_that_stops_firing_is_not_stable():
    rows = [{"joint": "knee", "take_id": "a", "planted_deg": d, "value": 90, "matching": m}
            for d, m in ((0.0, None), (2.5, {"measure": "knee_flexion"}), (5.0, None))]
    assert sv.first_fire(rows)["knee"]["a"] == {"first": 2.5, "stable": False}


def test_ac_sv03_rises_lists_the_steps_where_a_score_goes_up():
    assert sv.rises([(0, 100), (5, 90), (10, 91), (15, 80)]) == [(5, 90, 10, 91)]


# ---------------------------------------------------------------- the transforms of a clip
def committed_doc():
    return sv.load_doc(ROOT / take_of()["follower"])


def test_mirror_twice_is_the_clip_and_one_mirror_swaps_the_sides():
    doc = committed_doc()
    t, P = sv.positions_of(doc)
    twice = sv.positions_of(sv.mirror_doc(sv.mirror_doc(doc)))[1]
    assert np.allclose(twice, P, atol=1e-12)
    M = sv.positions_of(sv.mirror_doc(doc))[1]
    assert np.allclose(M[:, JOINTS.index("right_wrist")], P[:, JOINTS.index("left_wrist")] * [-1, 1, 1])
    assert np.allclose(M[:, JOINTS.index("nose")], P[:, JOINTS.index("nose")] * [-1, 1, 1])


def test_the_measures_of_a_mirrored_pose_are_the_swapped_measures_with_the_lateral_two_negated():
    from part5.measures import compute
    P = sv.positions_of(committed_doc())[1]
    original, mirrored = compute(P), compute(sv.positions_of(sv.mirror_doc(committed_doc()))[1])
    for name, values in original.items():
        other = name.replace("left_", "@").replace("right_", "left_").replace("@", "right_")
        sign = -1.0 if name in sv.ODD_MEASURES else 1.0
        assert np.allclose(mirrored[other], sign * values, atol=1e-9, equal_nan=True), name


def test_mirrored_set_swaps_sides_and_turns_the_lateral_directions():
    got = sv.mirrored_set({("upper_arm_out", "left", "more"), ("trunk_lean_side", "center", "more"),
                           ("knee_flexion", "both", "less")})
    assert got == {("upper_arm_out", "right", "more"), ("trunk_lean_side", "center", "less"), ("knee_flexion", "both", "less")}


def test_yaw_turns_about_the_vertical_and_a_full_turn_is_the_clip():
    doc = committed_doc()
    P = sv.positions_of(doc)[1]
    turned = sv.positions_of(sv.yaw_doc(doc, 30))[1]
    assert np.allclose(turned[..., 1], P[..., 1])   # y (up) is untouched
    assert np.allclose(np.linalg.norm(turned[..., [0, 2]], axis=-1), np.linalg.norm(P[..., [0, 2]], axis=-1))
    assert np.allclose(sv.positions_of(sv.yaw_doc(doc, 360))[1], P, atol=1e-9)


def test_scale_translate_trim_and_null_frames():
    doc = committed_doc()
    t, P = sv.positions_of(doc)
    assert np.allclose(sv.positions_of(sv.scale_doc(doc, 1.25))[1], P * 1.25)
    assert np.allclose(sv.positions_of(sv.translate_doc(doc, [0.1, 0, 0]))[1], P + [0.1, 0, 0])
    trimmed = sv.trim_doc(doc, 0.5)
    t2, P2 = sv.positions_of(trimmed)
    assert len(t2) == len(t) - 15 and t2[0] == 0.0 and np.allclose(P2, P[15:])
    assert trimmed["frame_count"] == len(t2) and trimmed["frames"][0]["index"] == 0
    held = sv.positions_of(sv.null_frames(doc, [3, 4]))[1]
    assert np.isnan(held[[3, 4]]).all() and np.isfinite(held[[0, 1, 2, 5]]).all()
    assert sv.null_frames(doc, [3])["frames"][3]["joints"]["nose"] is None


def test_a_translation_beyond_a_centimetre_is_the_loaders_typed_refusal():
    with pytest.raises(InputError, match="hip midpoint"):
        sv.analyse(EXPECTED, sv.translate_doc(committed_doc(), [0.5, 0, 0]))


def test_noisy_doc_is_seeded_and_keeps_the_hip_midpoint_at_the_origin():
    a, b = sv.noisy_doc(committed_doc(), 0.01, 7), sv.noisy_doc(committed_doc(), 0.01, 7)
    assert a == b and a != sv.noisy_doc(committed_doc(), 0.01, 8)
    P = sv.positions_of(a)[1]
    assert np.abs((P[:, JOINTS.index("left_hip")] + P[:, JOINTS.index("right_hip")]) / 2).max() < 1e-12


# ---------------------------------------------------------------- AC-SV07: the invariance table
def test_ac_sv07_the_exact_transforms_are_exact_on_a_committed_take():
    rows = sv.invariance_rows([take_of()], names=["mirror_both", "mirror_follower", "translate_5mm", "scale_0.8", "scale_1.25"])
    assert {r["transform"] for r in rows} == {"mirror_both", "mirror_follower", "translate_5mm", "scale_0.8", "scale_1.25"}
    assert all(r["delta"] == 0 and r["fault_set_equal"] for r in rows)


def test_ac_sv07_a_translation_outside_the_contract_is_refused_not_an_error():
    (row,) = sv.invariance_rows([take_of()], names=["translate_0.5m"])
    assert row["variant"] is None and "hip midpoint" in row["refused"] and "error" not in row


def test_ac_sv07_a_faulted_take_keeps_its_fault_set_under_the_mirror_with_the_sides_swapped():
    take = take_of("exercise_front_good_02_arms_wider-right")
    (row,) = sv.invariance_rows([take], names=["mirror_both"])
    assert row["base"]["faults"][0][:2] == ("upper_arm_out", "right") and row["variant"]["faults"][0][:2] == ("upper_arm_out", "left")
    assert row["fault_set_equal"] and row["delta"] == 0


def test_ac_sv07_the_groups_and_the_summary(tmp_path):
    takes = [take_of(), take_of("exercise_front_good_02_arms_wider-right")]
    rows = sv.invariance_rows(takes, names=["trim_0.5s", "trim_lead_in", "mirror_follower", "yaw_45"], tmp=tmp_path)
    groups = {(r["transform"], r["group"]) for r in rows}
    assert ("mirror_follower", "symmetric example") in groups and ("yaw_45", "all takes") in groups
    assert all(g[1] in ("lead-in under 15 frames", "lead-in at least 15 frames") for g in groups if g[0] == "trim_0.5s")
    for lead in [r for r in rows if r["transform"] == "trim_lead_in"]:
        assert lead["lead_in_frames"] > 0   # a take with no lead-in has nothing to trim and is skipped
    summary = sv.summarise(rows)
    assert {(e["transform"], e["group"]) for e in summary} == groups
    mirror = next(e for e in summary if e["transform"] == "mirror_follower")
    assert mirror["verdict"] == "exact" and mirror["takes"] == 2 and mirror["max_abs_delta"] == 0
    yaw = next(e for e in summary if e["transform"] == "yaw_45")
    assert yaw["verdict"] != "exact" and yaw["value_changed"] >= 1   # a turn of 45 degrees moves the score: a found failure
    assert sv.claimed("yaw_45", "all takes") == "exact" and sv.claimed("trim_0.5s", "lead-in under 15 frames") == "reported"


def test_ac_sv07_the_asymmetric_example_is_not_symmetric_and_the_squat_is():
    assert sv.is_symmetric(sv.load_doc(EXPECTED))
    assert not sv.is_symmetric(sv.load_doc(ROOT / "fixtures/input/expected/dance/animation.json"))


def test_ac_sv07_a_summary_names_refusals_and_changes():
    row = lambda name, delta, same, refused=None: {"transform": name, "group": "all takes", "refused": refused, "delta": delta,   # noqa: E731
                                                  "fault_set_equal": same}
    got = {e["transform"]: e for e in sv.summarise([row("a", 0, True), row("a", 0, True), row("b", -3, True), row("b", 0, True),
                                                    row("c", 0, False), row("d", None, None, "InputError")])}
    assert [got[k]["verdict"] for k in "abcd"] == ["exact", "score moved", "fault set changed", "refused"]
    assert got["b"]["max_abs_delta"] == 3 and got["b"]["value_changed"] == 1 and got["b"]["min_delta"] == -3


# ---------------------------------------------------------------- AC-SV05: the chart
def toy_inputs():
    curves = {j: [(d, 100.0 - k * d, 100.0 - k * d, 100.0 - k * d) for d in sv.GRID]
              for k, j in enumerate(JOINT_NAMES, start=1)}
    fires = {j: {"median_low": 7.5 * (k % 3 + 1) / 3 * 2, "min": 5.0, "max": 10.0, "takes": 6, "never": 0, "stable": 6}
             for k, j in enumerate(JOINT_NAMES, start=1)}
    return curves, fires


def test_ac_sv05_the_chart_is_valid_svg_with_a_title_a_description_and_one_line_per_joint():
    curves, fires = toy_inputs()
    text = chart.dose_response_svg(curves, fires, score.BANDS)
    root = ET.fromstring(text)
    ns = {"s": "http://www.w3.org/2000/svg"}
    assert root.find("s:title", ns).text and root.find("s:desc", ns).text
    assert root.get("role") == "img" and root.get("aria-labelledby") == "chart-title chart-desc"
    assert len(root.findall("s:polyline", ns)) == len(JOINT_NAMES)
    assert chart.dose_response_svg(curves, fires, score.BANDS) == text   # deterministic bytes
    assert chr(0x2014) not in text and chr(0x2013) not in text   # no em or en dash
    for joint in JOINT_NAMES:
        assert joint in "".join(root.itertext())


def test_ac_sv05_the_title_states_the_finding_and_names_a_joint_that_never_fires():
    curves, fires = toy_inputs()
    assert chart.headline(curves, fires).startswith("Faults first fire at ")
    fires["elbow"] = {"median_low": None, "min": None, "max": None, "takes": 6, "never": 6, "stable": 0}
    assert "none for elbow" in chart.headline(curves, fires)
    assert "never fire" in chart.dose_response_svg(curves, fires, score.BANDS)


def test_ac_sv05_end_labels_never_overlap():
    placed = chart._spread_labels([(100.0, "a"), (101.0, "b"), (102.0, "c"), (300.0, "d")])
    ys = sorted(placed.values())
    assert all(b - a >= chart.MIN_LABEL_GAP for a, b in zip(ys, ys[1:])) and placed["d"] == 300.0


# ---------------------------------------------------------------- AC-SV04: the bench run, on a reduced pool
@pytest.fixture
def reduced(monkeypatch):
    """`bench_score.main` on 2 correct takes, 3 steps, 2 joints and 3 transforms: the same code path in a few seconds."""
    takes = [take_of(), take_of("exercise_front_good_01_correct")]
    monkeypatch.setattr(sv, "pool", lambda: takes)
    real_dose, real_inv = sv.dose_rows, sv.invariance_rows
    monkeypatch.setattr(sv, "dose_rows", lambda t: real_dose(t, grid=[0.0, 15.0, 30.0], joints=("trunk", "knee")))
    monkeypatch.setattr(sv, "invariance_rows", lambda t, tmp=".": real_inv(t, names=["mirror_both", "yaw_45", "translate_0.5m"], tmp=tmp))
    return takes


def test_ac_sv04_the_bench_writes_the_metrics_and_the_chart_and_exits_0(reduced, tmp_path, capsys):
    out, copy = tmp_path / "out", tmp_path / "docs" / "dose-response.svg"
    assert bench.main(["--out", str(out), "--chart-copy", str(copy)]) == 0
    m = json.loads((out / "metrics.json").read_text())
    assert m["format"] == "simon.part5.bench-score.v1" and m["exit_code"] == 0 and m["seed"] == 5
    assert m["command"] == "uv run python scripts/make_bench_score.py"
    assert m["sha"] == "unknown" or len(m["sha"]) == 40
    assert m["score"]["version"] == score.params_of(json.loads((ROOT / "part5/rules.json").read_text()))["version"]
    assert m["grid_deg"] == sv.GRID and len(m["dose_response"]["rows"]) == 2 * 2 * 3 and len(m["invariance"]["rows"]) == 2 * 3
    assert set(m["dose_response"]["first_fire"]["summary"]) == {"trunk", "knee"}
    assert any("yaw_45" in f for f in m["findings"])   # a claim the numbers miss is a finding, not a failed run
    assert (out / "dose-response.svg").read_text() == copy.read_text()
    assert "bench-score: wrote" in capsys.readouterr().out


def test_ac_sv04_two_runs_of_one_tree_write_the_same_bytes(reduced, tmp_path):
    for name in ("a", "b"):
        assert bench.main(["--out", str(tmp_path / name), "--chart-copy", ""]) == 0
    assert (tmp_path / "a" / "metrics.json").read_bytes() == (tmp_path / "b" / "metrics.json").read_bytes()
    assert (tmp_path / "a" / "dose-response.svg").read_bytes() == (tmp_path / "b" / "dose-response.svg").read_bytes()


def test_ac_sv04_a_row_that_cannot_run_is_recorded_and_the_run_exits_1(reduced, tmp_path, monkeypatch, capsys):
    from part5.pipeline import AnalysisError
    real = sv.dose_row

    def refuse_the_largest(take, base, expected, joint, deg):
        if deg == 30.0:
            raise AnalysisError("too long")
        return real(take, base, expected, joint, deg)

    monkeypatch.setattr(sv, "dose_row", refuse_the_largest)
    assert bench.main(["--out", str(tmp_path), "--chart-copy", ""]) == 1
    m = json.loads((tmp_path / "metrics.json").read_text())
    errors = [r for r in m["dose_response"]["rows"] if "error" in r]
    assert m["exit_code"] == 1 and len(errors) == 2 * 2 and all(r["planted_deg"] == 30.0 for r in errors)
    assert len(m["dose_response"]["mean_curve"]["trunk"]) == 2   # the steps that ran are still read
    assert "row trunk exercise_front_good_00_correct: too long" in capsys.readouterr().err


# ---------------------------------------------------------------- AC-SV02: the inputs are seed 5 only
def test_ac_sv02_a_labels_file_that_is_not_seed_5_is_refused_with_exit_2(tmp_path, monkeypatch, capsys):
    labels = json.loads(sv.retimed.LABELS.read_text())
    labels["seed"] = 29
    bad = tmp_path / "labels.json"
    bad.write_text(json.dumps(labels))
    monkeypatch.setattr(sv.retimed, "LABELS", bad)
    assert bench.main(["--out", str(tmp_path / "out"), "--chart-copy", ""]) == 2
    assert "bench-score:" in capsys.readouterr().err and not (tmp_path / "out").exists()


def test_ac_sv02_a_missing_take_file_is_refused_with_exit_2(tmp_path, monkeypatch, capsys):
    takes = [dict(take_of(), follower="fixtures/input/followers/exercise/nowhere/skeleton.json")]
    monkeypatch.setattr(sv, "pool", lambda: takes)
    assert bench.main(["--out", str(tmp_path / "out"), "--chart-copy", ""]) == 2
    assert "bench-score: missing take fixtures/input/followers/exercise/nowhere/skeleton.json" in capsys.readouterr().err


def test_ac_sv02_the_pool_is_the_good_light_clean_seed_5_takes_of_two_sets():
    takes = sv.pool()
    assert len(takes) == 54 and {t["set"] for t in takes} == {"exercise", "dance"}
    assert all(t["lighting"] == "good" and t["variant"] == "clean" for t in takes)
    assert len(sv.correct_exercise(takes)) == 6 and all(t["set"] == "exercise" and t["correct"] for t in sv.correct_exercise(takes))
    assert json.loads(sv.retimed.LABELS.read_text())["seed"] == sv.SEED == 5


def test_ac_sv10_the_bench_reads_no_held_out_set_and_names_no_frozen_file_to_write():
    for name in ("scripts/make_score_validity.py", "scripts/make_bench_score.py", "scripts/make_bench_score_chart.py"):
        text = (ROOT / name).read_text()
        assert "heldout" not in text and "fixtures/output" not in text and "profiles.json" not in text, name
