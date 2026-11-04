"""TICKET-086, AC-Q16: `quality.signals.heading_offset_deg`, the heading left between the example and the follower over the aligned
frames (the hip and shoulder lines in the horizontal plane), and the reason `heading_offset` from 5 degrees, degraded only: Part 7
chose that a heading offset never makes a take major (the camera's angle, not the follower's form), so the 15 degree major limit the
lane proposed is gone. The limit comes from TICKET-082's seed 5 bench (docs/evaluation.md); the planted yaw is the bench's own
transform (`scripts/make_score_validity.py`, `yaw_doc`)."""
import copy
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_score_validity as sv  # noqa: E402
from part5 import output, pipeline, quality  # noqa: E402
from part5.io import JOINTS, load_clip  # noqa: E402
from part5.output import OutputError, validate_analysis  # noqa: E402
from part5.score_report import feet_kwargs  # noqa: E402

EXPECTED = {name: ROOT / f"fixtures/input/expected/{name}/animation.json" for name in ("exercise", "dance")}
LABELS = {t["take_id"]: t for t in json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())["takes"]}
BENCH_TAKE = "exercise_front_good_00_correct"   # a bench take (TICKET-082's 54: good light, clean, numbers 00 to 08)
REPS_TAKE = "dance_side_good_04_knees_shallow-both"   # compared rep by rep
GOLDEN = json.loads((ROOT / "fixtures/output/analysis.no-faults.example.json").read_text())


def turned(positions, deg):
    """`positions` turned `deg` degrees about the vertical, as `sv.yaw_doc` turns a clip."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    out = np.array(positions, dtype=float)
    out[..., 0], out[..., 2] = c * positions[..., 0] + s * positions[..., 2], -s * positions[..., 0] + c * positions[..., 2]
    return out


@pytest.fixture(scope="module")
def frames():
    return load_clip(EXPECTED["exercise"]).positions[:12].copy()


def heading_of(analysis):
    return analysis["quality"]["signals"]["heading_offset_deg"]


# ---------------------------------------------------------------------------------------------- the reading
@pytest.mark.parametrize("deg", [0.0, 5.0, 15.0, 45.0, 90.0, 179.0])
def test_the_offset_is_the_angle_the_follower_is_turned_by(frames, deg):
    assert quality.heading_offset_deg(frames, turned(frames, deg)) == deg
    assert quality.heading_offset_deg(frames, turned(frames, -deg)) == deg   # an angle between, never signed


def test_the_offset_wraps_round_the_back():
    p = load_clip(EXPECTED["exercise"]).positions[:4]
    assert quality.heading_offset_deg(turned(p, 170.0), turned(p, -170.0)) == 20.0


def test_one_line_is_enough_and_a_pair_with_neither_line_is_not_measured(frames):
    no_hips = frames.copy()
    no_hips[:, [JOINTS.index("left_hip"), JOINTS.index("right_hip")]] = np.nan
    assert quality.heading_offset_deg(no_hips, turned(no_hips, 15.0)) == 15.0
    neither = no_hips.copy()
    neither[:, [JOINTS.index("left_shoulder"), JOINTS.index("right_shoulder")]] = np.nan
    assert np.isnan(quality.headings(neither)).all() and quality.heading_offset_deg(neither, frames) is None


def test_a_line_seen_end_on_has_no_direction(frames):
    end_on = frames.copy()
    for left, right in quality.HEADING_LINES:
        end_on[:, JOINTS.index(left), [0, 2]] = end_on[:, JOINTS.index(right), [0, 2]]
    assert np.isnan(quality.headings(end_on)).all()


def test_a_take_that_could_not_be_aligned_has_no_heading():
    assert pipeline._heading_offset(SimpleNamespace(guard=None)) is None
    readings = quality.with_heading(quality.Readings({"position_jitter_mm": 1.0}), None)
    assert readings.signals == {"position_jitter_mm": 1.0, "heading_offset_deg": None}


# ---------------------------------------------------------------------------------------------- through the pipeline
@pytest.mark.parametrize("name", ["exercise", "dance"])
def test_an_example_against_itself_reads_0_and_has_no_heading_reason(name):
    doc = sv.load_doc(EXPECTED[name])
    got = sv.analyse(doc, copy.deepcopy(doc), "twin")
    assert heading_of(got) == 0.0 and "heading_offset" not in [r["code"] for r in got["quality"]["reasons"]]


@pytest.mark.parametrize("deg", [5.0, 15.0, 45.0])
def test_a_planted_yaw_on_an_example_against_itself_is_read_back_and_is_degraded_only(deg):
    doc = sv.load_doc(EXPECTED["exercise"])
    got = sv.analyse(doc, sv.yaw_doc(doc, deg), f"yaw {deg}")
    block = got["quality"]
    assert heading_of(got) == pytest.approx(deg, abs=0.5)
    assert block["level"] == "degraded" and block["score_cap"] is None   # TICKET-086: never major, so never the cap of 59
    reason = next(r for r in block["reasons"] if r["code"] == "heading_offset")
    assert reason["value"] == heading_of(got) and reason["threshold"] == 5.0
    assert reason["words"] == f"The body was turned about {heading_of(got):.0f} degrees from the way the example faces."
    assert "joint" not in reason


@pytest.mark.parametrize("deg", [5.0, 15.0, 45.0])
def test_a_planted_yaw_on_a_seed_5_bench_take_is_read_back_within_its_own_heading_noise(deg):
    take = LABELS[BENCH_TAKE]
    got = sv.analyse(ROOT / take["expected"], sv.yaw_doc(sv.load_doc(ROOT / take["follower"]), deg), BENCH_TAKE)
    assert heading_of(got) == pytest.approx(deg, abs=3.5)


def test_a_take_compared_rep_by_rep_reads_its_heading_over_the_aligned_reps():
    take = LABELS[REPS_TAKE]
    result = pipeline.run(str(ROOT / take["expected"]), str(ROOT / take["follower"]), **feet_kwargs(take, ROOT))
    assert result.reps and heading_of(result.analysis) is not None and heading_of(result.analysis) < 5.0
    assert result.analysis["quality"]["level"] == "ok"


# ---------------------------------------------------------------------------------------------- the limits and the document
def test_the_limit_is_5_from_the_seed_5_bench_and_there_is_no_major_limit():
    assert quality.load_thresholds()["heading_offset_deg"] == (5.0, None)
    doc = json.loads(quality.THRESHOLDS_PATH.read_text())
    assert doc["version"] == "1.1.0" and "TICKET-082" in doc["basis"]["heading_offset_deg"]
    assert doc["signals"]["heading_offset_deg"] == {"degraded": 5.0, "major": None} and "degraded only" in doc["basis"]["heading_offset_deg"]
    assert all(major is not None for name, (_, major) in quality.load_thresholds().items() if name != "heading_offset_deg")
    assert ("heading_offset", "heading_offset_deg") in quality.SIGNAL_REASONS and "heading_offset" in output.QUALITY_CODES


def test_a_1_14_0_block_must_have_the_signal_and_a_1_13_0_block_may_lack_it():
    block = copy.deepcopy(GOLDEN["quality"])
    assert GOLDEN["schema_version"] == "1.14.0" and "heading_offset_deg" in block["signals"]
    del block["signals"]["heading_offset_deg"]
    with pytest.raises(OutputError, match="heading_offset_deg"):
        validate_analysis(dict(GOLDEN, quality=block))
    validate_analysis(dict(GOLDEN, quality=block, schema_version="1.13.0"))


@pytest.mark.parametrize("value", [-0.1, 180.1, "5", True])
def test_the_validator_refuses_a_heading_outside_0_to_180(value):
    block = copy.deepcopy(GOLDEN["quality"])
    block["signals"]["heading_offset_deg"] = value
    with pytest.raises(OutputError, match="heading_offset_deg must be a number from 0 to 180 or null"):
        validate_analysis(dict(GOLDEN, quality=block))
    block["signals"]["heading_offset_deg"] = None
    validate_analysis(dict(GOLDEN, quality=block))
