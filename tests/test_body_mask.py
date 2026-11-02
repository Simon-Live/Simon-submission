"""The declared body mask's own rules (TICKET-084, ADR-0023, docs/specs/body-mask.md): the chains and presets, the NaN it
sets, parsing and its typed error, the `body_mask` block, its words and the validator's cross-check. GPU free, no
pipeline run except the goldens it reads."""
import copy
import json
import re
from pathlib import Path

import numpy as np
import pytest

from part5.detect import generic, load_rules
from part5.io import JOINTS, load_clip
from part5.measures import FOOT_MEASURES, MEASURES, compute, compute_feet, compute_view
from part5.normalise import normalise
from part5.output import OutputError, validate_analysis
from part5.mask import (CHAINS, FOOT_JOINTS, PRESETS, BodyMask, MaskError, chain_measures, dropped_by, hide_masked,
                        mask_from_request, mask_text, parse_mask)

ROOT = Path(__file__).resolve().parent.parent
CLIP = ROOT / "fixtures/input/followers/exercise/exercise_front_good_00_correct/skeleton.json"
GOLDEN = json.loads((ROOT / "fixtures/output/analysis.example.json").read_text())
DASHES = (chr(0x2014), chr(0x2013), " - ")
SIDES = ("left", "right")
# The spec's table: the body measures each chain drops on its own side (docs/specs/body-mask.md "The chains").
SPEC_TABLE = {"arm": {"elbow_flexion", "upper_arm_out", "upper_arm_forward", "forearm_out"},
              "forearm": {"elbow_flexion", "forearm_out"},
              "leg": {"knee_flexion", "knee_valgus", "thigh_out", "thigh_forward", "foot_out", "foot_rotation",
                      "ankle_inversion"}}
CENTRE = {"trunk_lean_forward", "trunk_lean_side", "shoulder_tilt", "head_forward"}


def kind_of(chain):
    return chain.split("_", 1)[1]


# ---------------------------------------------------------------- the chains and the presets
def test_the_chains_are_an_arm_a_forearm_and_a_leg_of_each_side_and_no_shin():
    assert list(CHAINS) == ["left_arm", "right_arm", "left_forearm", "right_forearm", "left_leg", "right_leg"]
    assert {c: CHAINS[c][0] for c in CHAINS} == {
        "left_arm": "left_shoulder", "right_arm": "right_shoulder", "left_forearm": "left_elbow",
        "right_forearm": "right_elbow", "left_leg": "left_hip", "right_leg": "right_hip"}
    assert PRESETS == {"seated": ("left_leg", "right_leg"), "full_body": ()}
    assert not any("knee" == CHAINS[c][0].split("_", 1)[1] for c in CHAINS)


@pytest.mark.parametrize("chain", CHAINS)
def test_each_chain_drops_the_measures_the_spec_table_names_on_its_own_side(chain):
    side = chain.split("_", 1)[0]
    scored = {n for n in (*MEASURES, *FOOT_MEASURES) if n in chain_measures(chain)}
    assert scored == {f"{side}_{m}" for m in SPEC_TABLE[kind_of(chain)]}
    assert not {f"{side}_{m}" for m in CENTRE} & chain_measures(chain) and not CENTRE & chain_measures(chain)


def test_every_chain_masked_leaves_exactly_the_four_centre_measures():
    everything = parse_mask(",".join(c for c in CHAINS if not c.endswith("forearm")))
    assert {n for n in MEASURES if n not in everything.measures} == CENTRE
    assert set(FOOT_MEASURES) <= everything.measures


def test_the_foot_joints_name_every_foot_measure_and_its_points():
    assert set(FOOT_JOINTS) == set(FOOT_MEASURES)


# ---------------------------------------------------------------- AC-BM-02: the same NaN as visibility
@pytest.fixture(scope="module")
def positions():
    return normalise(load_clip(CLIP)).positions


def nan_equal(a, b):
    return np.array_equal(np.asarray(a, float), np.asarray(b, float), equal_nan=True)


@pytest.mark.parametrize("chain", CHAINS)
def test_nan_at_the_masked_joints_is_exactly_the_dropped_measures(chain, positions):
    mask = parse_mask(chain)
    hidden = positions.copy()
    for j in mask.joints & set(JOINTS):
        hidden[:, JOINTS.index(j)] = np.nan   # every frame, the NaN hide_unseen sets
    before = {**compute(positions), **compute_view(positions)}
    after = {**compute(hidden), **compute_view(hidden)}
    assert {n for n, v in after.items() if np.isnan(v).all()} == {n for n in before if n in mask.measures}
    for n in before:
        if n not in mask.measures:
            assert nan_equal(before[n], after[n]), n
    masked = hide_masked(mask, before)
    assert all(nan_equal(masked[n], after[n]) for n in before)


@pytest.mark.parametrize("chain", ["left_leg", "right_leg"])
def test_a_leg_mask_drops_its_foot_measures_the_way_nan_foot_points_do(chain):
    rng = np.random.default_rng(84)
    names = ("left_hip", "right_hip", *(f"{s}_{p}" for s in SIDES for p in ("big_toe", "small_toe", "heel")))
    points = {n: rng.normal(size=(40, 3)) for n in names}
    hidden = {n: (np.full_like(v, np.nan) if n in parse_mask(chain).joints else v) for n, v in points.items()}
    before, after = compute_feet(points), compute_feet(hidden)
    mask = parse_mask(chain)
    for n in FOOT_MEASURES:
        if n in mask.measures:
            assert np.isnan(after[n]).all(), n
        else:
            assert nan_equal(before[n], after[n]), n


def test_without_a_mask_hide_masked_is_the_series_itself():
    series = {"left_elbow_flexion": np.arange(3.0)}
    assert hide_masked(None, series) is series
    full = hide_masked(parse_mask("full_body"), series)
    assert full is not series and nan_equal(full["left_elbow_flexion"], series["left_elbow_flexion"])


# ---------------------------------------------------------------- the shin is not offered (spec, Dissent 4)
def explanations():
    rules = load_rules()
    pairs = [(cause, key) for key, causes in rules["explained_by"].items() if not key.startswith("_") for cause in causes]
    return pairs + [(cause, key) for key, causes in rules["explained_by_opposite"].items() if not key.startswith("_")
                    for cause in causes]


def families(measures):
    return {generic(n)[0] for n in measures}


@pytest.mark.parametrize("chain", CHAINS)
def test_a_chain_explains_only_measures_of_its_own_chain(chain):
    """AC-BM-04 holds by construction only when no measure of a chain explains a measure outside it (rules.json)."""
    own = families(chain_measures(chain))
    assert [(c, k) for c, k in explanations() if c in own and k not in own] == []


def test_a_shin_mask_would_explain_a_thigh_fault_that_is_not_masked():
    shin = families(dropped_by(("left_ankle", "left_heel", "left_big_toe", "left_small_toe")))
    assert ("foot_out", "thigh_out") in explanations() and "foot_out" in shin and "thigh_out" not in shin


# ---------------------------------------------------------------- parsing and the typed error (AC-BM-08, AC-BM-09)
def test_parse_reads_presets_and_chains_each_once_in_order():
    mask = parse_mask(" left_arm , right_leg,left_arm ")
    assert mask == BodyMask(("left_arm", "right_leg"), frozenset({"left_arm", "right_leg"}), "cli")
    assert parse_mask("seated").chains == {"left_leg", "right_leg"} and parse_mask("full_body").chains == frozenset()
    assert parse_mask("seated,left_arm").chains == {"left_leg", "right_leg", "left_arm"}


@pytest.mark.parametrize("text,needle", [
    ("left_hand", "unknown name 'left_hand'"), ("Seated", "unknown name 'Seated'"), ("left_shin", "unknown name"),
    ("", "name a preset"), (" , ", "name a preset"), ("full_body,left_arm", "full_body masks nothing")])
def test_parse_refuses_a_bad_mask_with_a_typed_error(text, needle):
    with pytest.raises(MaskError, match=needle) as e:
        parse_mask(text)
    assert isinstance(e.value, ValueError) and str(e.value).startswith("mask: ")
    if "unknown" in needle:
        assert all(name in str(e.value) for name in (*PRESETS, *CHAINS))


def test_the_request_field_reads_null_a_string_or_a_list():
    assert mask_from_request(None) is None
    assert mask_from_request("seated") == BodyMask(("seated",), frozenset({"left_leg", "right_leg"}), "api")
    assert mask_from_request(["left_arm", "right_leg"]).declared == ("left_arm", "right_leg")
    for bad in ([], [""], 5, {"left_arm": True}, ["left_arm", 3], True):
        with pytest.raises(MaskError):
            mask_from_request(bad)


# ---------------------------------------------------------------- the block (AC-BM-07) and the words (AC-BM-12)
def test_block_of_a_forearm_keeps_its_arm_scored_and_an_arm_lists_its_forearm():
    forearm = parse_mask("left_forearm").block()
    assert forearm["not_scored_chains"] == ["left_forearm"] and "left_arm" in forearm["scored_chains"]
    assert forearm["masked_joints"] == ["left_wrist"]
    assert forearm["not_scored_measures"] == ["left_elbow_flexion", "left_forearm_out"]
    arm = parse_mask("left_arm").block()
    assert arm["not_scored_chains"] == ["left_arm", "left_forearm"] and arm["masked_joints"] == ["left_elbow", "left_wrist"]


@pytest.mark.parametrize("names", ["seated", "left_arm", "right_forearm", "left_arm,right_leg", "full_body",
                                   "left_arm,right_arm,left_leg,right_leg"])
def test_block_partitions_the_chains_and_has_its_keys_in_order(names):
    block = parse_mask(names).block()
    assert list(block) == ["declared", "source", "scored_chains", "not_scored_chains", "masked_joints",
                           "not_scored_measures", "text"]
    assert sorted(block["scored_chains"] + block["not_scored_chains"], key=list(CHAINS).index) == list(CHAINS)
    assert block["source"] == "cli" and block["declared"] == names.split(",")


@pytest.mark.parametrize("names,text", [
    ("seated", "Legs not scored, by your setting."),
    ("left_arm", "Left arm not scored, by your setting."),
    ("right_forearm", "Right forearm not scored, by your setting."),
    ("left_arm,left_forearm", "Left arm not scored, by your setting."),
    ("left_arm,right_leg", "Left arm and right leg not scored, by your setting."),
    ("left_arm,right_forearm,seated", "Left arm, right forearm and legs not scored, by your setting."),
    ("left_forearm,right_forearm", "Forearms not scored, by your setting."),
    ("left_arm,right_arm,left_leg,right_leg", "Arms and legs not scored, by your setting."),
    ("full_body", "Whole body scored, by your setting.")])
def test_text_names_the_largest_chains_not_scored(names, text):
    mask = parse_mask(names)
    assert mask.block()["text"] == text == mask_text(mask.not_scored_chains)
    assert not [d for d in DASHES if d in text] and not re.search(r"\d", text)


# ---------------------------------------------------------------- the validator (AC-BM-07)
def with_mask(doc, names):
    out = copy.deepcopy(doc)
    out["body_mask"] = parse_mask(names).block()
    return out


def test_the_validator_accepts_a_block_whose_document_names_no_masked_measure():
    """The golden reports the right elbow and both upper arms, so a leg mask fits it once its near misses, which name a
    knee, are taken out; with them it is refused."""
    doc = with_mask(GOLDEN, "seated")
    with pytest.raises(OutputError, match=r"near_misses\[\d+\] names knee_flexion"):
        validate_analysis(copy.deepcopy(doc))
    doc["diagnostics"]["near_misses"] = {"total": 0, "omitted": 0, "items": []}
    assert validate_analysis(doc)["body_mask"]["declared"] == ["seated"]


@pytest.mark.parametrize("names", ["left_arm", "right_forearm"])
def test_the_validator_refuses_a_document_that_faults_a_masked_measure(names):
    with pytest.raises(OutputError, match="which body_mask says is not scored"):
        validate_analysis(with_mask(GOLDEN, names))


@pytest.mark.parametrize("change,needle", [
    (lambda b: b.update(scored_chains=list(CHAINS)), "body_mask.scored_chains must be"),
    (lambda b: b.update(source="profile"), "body_mask.source must be one of"),
    (lambda b: b.update(declared=["left_hand"]), "body_mask.declared: mask: unknown name"),
    (lambda b: b.update(declared=[]), "body_mask.declared: mask: name a preset"),
    (lambda b: b.update(text=""), "body_mask.text must be a non-empty string"),
    (lambda b: b.pop("masked_joints"), "body_mask.masked_joints must be")])
def test_the_validator_refuses_a_block_that_does_not_follow_from_declared(change, needle):
    doc = with_mask(GOLDEN, "seated")
    change(doc["body_mask"])
    with pytest.raises(OutputError, match=re.escape(needle)):
        validate_analysis(doc)


def test_the_validator_refuses_a_block_that_is_not_an_object():
    doc = dict(GOLDEN, body_mask=["seated"])
    with pytest.raises(OutputError, match="body_mask must be an object"):
        validate_analysis(doc)
