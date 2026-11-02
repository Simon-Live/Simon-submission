"""The declared body mask on committed seed 5 fixtures (TICKET-084 AC-2, ADR-0023, docs/specs/body-mask.md AC-BM-03 to
AC-BM-06, AC-BM-10, AC-BM-11), GPU free. For every chain X and every fixture: masking X leaves every other chain's faults,
misses and score contributions unchanged, and X itself is never faulted, cued or named."""
import copy
import functools
import json
import re
from pathlib import Path

import numpy as np
import pytest

from part5 import score
from part5.detect import load_rules
from part5.measures import ALL_SPECS, MEASURES
from part5.pipeline import run
from part5.score_report import aligned_of, feet_kwargs, score_block
from part5.mask import CHAINS, parse_mask

ROOT = Path(__file__).resolve().parent.parent
TAKES = {t["take_id"]: t for t in json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())["takes"]}
FIXTURES = ("exercise_front_good_08_arms_wider-both+elbow_bent-right",   # compared as a whole, a `both` arm fault
            "dance_front_good_08_foot_out-left+trunk_lean-center",       # compared rep by rep, a leg and the trunk
            "exercise_front_good_09_foot_turned_out-right",              # with its feet files, a foot measure
            "exercise_front_good_07_knee_caving-left")                   # a knee fault that explains others
EVERY_CHAIN = "left_arm,right_arm,left_leg,right_leg"
SIDES = ("left", "right")
# Words a masked chain's limb is said with (words.py, cues.py), by chain kind; the side is filled in.
LIMB_WORDS = {"arm": ("{s} arm", "{s} elbow", "{s} hand", "arms", "elbows", "hands"),
              "forearm": ("{s} hand", "{s} elbow", "hands"),
              "leg": ("{s} knee", "{s} thigh", "{s} foot", "{s} ankle", "knees", "thighs", "feet", "ankles")}


@functools.lru_cache(maxsize=None)
def analysed(take_id, names=None):
    """The take's `PipelineResult` (template phrasing, the shipped score), masked by `names` or not; never mutated."""
    t = TAKES[take_id]
    return run(str(ROOT / t["expected"]), {"path": str(ROOT / t["follower"]), "take_id": take_id}, score=score_block,
               mask=None if names is None else parse_mask(names), **feet_kwargs(t, ROOT))


def sides_of(side):
    return SIDES if side == "both" else (side,)


def sided(measure, side):
    return measure if side == "center" else f"{side}_{measure}"


def keys(doc):
    """The per-side fault keys: a `both` fault counts as its left and its right."""
    return {(f["measure"], s, f["direction"]) for f in doc["faults"] for s in sides_of(f["side"])}


def dropped(names):
    return {n for n in ALL_SPECS if n in parse_mask(names).measures}


def touched(names):
    """The measure families (side-less names) with a side the mask drops."""
    return {ALL_SPECS[n].name.removeprefix("left_").removeprefix("right_") for n in dropped(names)}


def untouched(items, families):
    return sorted((i for i in items if i.get("measure") not in families),
                  key=lambda i: (i["measure"], i["side"], i["direction"], i.get("at_s") or 0))


def aligned_sets(result):
    """The `aligned` inputs the score read: the whole take's, or one per accepted rep."""
    if result.reps:
        return [aligned_of(r, result.vis, result.mask) for r in result.reps if r.ok]
    return [aligned_of(result)]


def z_by_measure(aligned, rules):
    return dict(zip(MEASURES, score._z_rows(aligned, rules)))


CASES = [(t, c) for t in FIXTURES for c in CHAINS]


def test_the_fixtures_cover_both_comparison_bases_and_report_faults():
    docs = {t: analysed(t).analysis for t in FIXTURES}
    assert {d["score"]["basis"] for d in docs.values()} == {"windows", "reps"}
    assert all(d["faults"] for d in docs.values())
    assert any(f["side"] == "both" for d in docs.values() for f in d["faults"])


# ---------------------------------------------------------------- AC-BM-04: every other chain is unchanged
@pytest.mark.parametrize("take,chain", CASES)
def test_masking_a_chain_leaves_every_other_chain_unchanged(take, chain):
    a, b = analysed(take).analysis, analysed(take, chain).analysis
    off, fam = dropped(chain), touched(chain)
    assert keys(b) == {k for k in keys(a) if sided(k[0], k[1]) not in off}
    assert untouched(a["faults"], fam) == untouched(b["faults"], fam)
    wa, wb = a["score"]["timeline"], b["score"]["timeline"]
    assert [(w["t_s"], w["compared"]) for w in wa] == [(w["t_s"], w["compared"]) for w in wb]
    for x, y in zip(wa, wb):
        assert untouched(x.get("misses", []), fam) == untouched(y.get("misses", []), fam)
    near_b = b["diagnostics"]["near_misses"]["items"]
    assert all(i in near_b for i in a["diagnostics"]["near_misses"]["items"] if i["measure"] not in fam)
    rules = load_rules()
    for xa, xb in zip(aligned_sets(analysed(take)), aligned_sets(analysed(take, chain)), strict=True):
        za, zb = z_by_measure(xa, rules), z_by_measure(xb, rules)
        for name in MEASURES:
            if name in off:
                assert np.isnan(zb[name]).all(), name
            else:
                assert np.array_equal(za[name], zb[name], equal_nan=True), name


@pytest.mark.parametrize("take,chain", CASES)
def test_alignment_guard_and_segmentation_ignore_the_mask(take, chain):
    """AC-BM-03: timing, the guard, the repetitions and the warnings read the whole body."""
    a, b = analysed(take).analysis, analysed(take, chain).analysis
    for key in ("alignment_residual", "alignment_measures", "follower_span", "guard", "expected_reference"):
        assert a["diagnostics"].get(key) == b["diagnostics"].get(key), key
    assert (a.get("warnings"), a.get("match"), a["score"]["basis"]) == (b.get("warnings"), b.get("match"), b["score"]["basis"])


# ---------------------------------------------------------------- AC-BM-05: the masked chain is never named
def texts(doc):
    misses = [m for w in doc["score"]["timeline"] for m in w.get("misses", [])]
    return ([f[k] for f in doc["faults"] for k in ("text", "text_timed", "coaching", "cue") if f.get(k)]
            + [m[k] for m in misses for k in ("text", "cue") if m.get(k)]
            + [i[k] for i in doc["insights"] for k in ("cue", "why") if i.get(k)])


@pytest.mark.parametrize("take,chain", CASES)
def test_a_masked_chain_is_never_faulted_cued_or_named(take, chain):
    doc = analysed(take, chain).analysis
    off = dropped(chain)
    misses = [m for w in doc["score"]["timeline"] for m in w.get("misses", [])]
    named = [*doc["faults"], *misses, *doc["insights"], *doc["diagnostics"]["near_misses"]["items"]]
    assert not [i for i in named if i.get("measure") and {sided(i["measure"], s) for s in sides_of(i["side"])} & off]
    side, kind = chain.split("_", 1)
    words = [w.format(s=side) for w in LIMB_WORDS[kind]]
    assert not [(t, w) for t in texts(doc) for w in words if re.search(rf"\b{w}\b", t.lower())]
    assert doc["body_mask"]["declared"] == [chain] and chain in doc["body_mask"]["not_scored_chains"]


def test_the_word_check_finds_the_limb_in_the_unmasked_analysis():
    """Control: the words of LIMB_WORDS are what the unmasked fixtures say."""
    said = " ".join(texts(analysed(FIXTURES[0]).analysis)).lower()
    assert "elbows" in said and "right elbow" in said and "right arm" in said


# ---------------------------------------------------------------- AC-BM-06: no mask, no change
@pytest.mark.parametrize("take", FIXTURES)
def test_full_body_is_the_unmasked_analysis_apart_from_the_block(take):
    a, b = analysed(take).analysis, copy.deepcopy(analysed(take, "full_body").analysis)
    assert b.pop("body_mask")["text"] == "Whole body scored, by your setting."
    assert json.dumps(a) == json.dumps(b) and "body_mask" not in a


def test_no_mask_writes_no_block_and_the_same_bytes_as_a_call_that_names_none():
    t = TAKES[FIXTURES[0]]
    plain = run(str(ROOT / t["expected"]), {"path": str(ROOT / t["follower"]), "take_id": FIXTURES[0]},
                score=score_block, **feet_kwargs(t, ROOT)).analysis
    assert json.dumps(plain) == json.dumps(analysed(FIXTURES[0]).analysis) and "body_mask" not in plain


# ---------------------------------------------------------------- AC-BM-10: how the score renormalises, verified
@pytest.mark.parametrize("take", FIXTURES)
@pytest.mark.parametrize("names", ["left_arm", "seated"])
def test_the_score_renormalises_on_the_remaining_measures(take, names):
    rules, off = load_rules(), dropped(names)
    for xa, xb in zip(aligned_sets(analysed(take)), aligned_sets(analysed(take, names)), strict=True):
        za = z_by_measure(xa, rules)
        rest = np.vstack([z for n, z in za.items() if n not in off])
        cells = rest[np.isfinite(rest)]
        assert score.mean_z(xb, rules) == pytest.approx(float(np.mean(np.minimum(cells, score.CLIP_Z))), abs=1e-12)
        counted = [z for n, z in za.items() if n not in off and np.isfinite(z).mean() >= score.CREDIT_MIN_SEEN]
        assert np.array_equal(score.credit_z(xb, rules), np.vstack(counted), equal_nan=True)
    doc = analysed(take, names).analysis
    for w in doc["score"]["timeline"]:
        if w["compared"]:
            spent = sum(m["points"] for m in w["misses"])
            assert abs(w["components"]["faults"] - spent) <= 0.05 * len(w["misses"]) + 0.01
    assert doc["score"]["credit"]["max_points"] < analysed(take).analysis["score"]["credit"]["max_points"]


# ---------------------------------------------------------------- AC-BM-11: every chain masked
@pytest.mark.parametrize("take", FIXTURES)
def test_every_chain_masked_scores_the_centre(take):
    a, b = analysed(take).analysis, analysed(take, EVERY_CHAIN).analysis
    assert {f["side"] for f in b["faults"]} <= {"center"}
    assert b.get("warnings") == a.get("warnings") and b["score"]["timeline"][0]["compared"]
    assert b["body_mask"]["scored_chains"] == [] and b["body_mask"]["text"] == "Arms and legs not scored, by your setting."
    for aligned in aligned_sets(analysed(take, EVERY_CHAIN)):
        finite = {n for n, z in z_by_measure(aligned, load_rules()).items() if np.isfinite(z).any()}
        assert finite == {"trunk_lean_forward", "trunk_lean_side", "shoulder_tilt", "head_forward"}


# ---------------------------------------------------------------- ADR-0023's evidence, and a real seated take
def held_left_arm(doc):
    """`doc` with the left elbow and wrist kept at their first-frame offset from the left shoulder (an arm held still)."""
    out = copy.deepcopy(doc)
    first = out["frames"][0]["joints"]
    offsets = {j: np.subtract(first[j], first["left_shoulder"]) for j in ("left_elbow", "left_wrist")}
    for frame in out["frames"]:
        for j, off in offsets.items():
            frame["joints"][j] = [round(float(x), 4) for x in np.add(frame["joints"]["left_shoulder"], off)]
    return out


def test_a_held_arm_is_faulted_without_the_mask_and_not_with_it_and_the_guard_reads_it_both_times(tmp_path):
    t = TAKES["dance_front_good_00_correct"]
    path = tmp_path / "held.json"
    path.write_text(json.dumps(held_left_arm(json.loads((ROOT / t["follower"]).read_text()))))
    plain = run(str(ROOT / t["expected"]), str(path), score=score_block).analysis
    masked = run(str(ROOT / t["expected"]), str(path), score=score_block, mask=parse_mask("left_arm")).analysis
    assert plain["faults"] and {(f["measure"], f["side"]) for f in plain["faults"]} <= {
        ("upper_arm_out", "left"), ("upper_arm_forward", "left")}
    assert masked["faults"] == [] and (masked["score"]["value"], masked["score"]["grade"]) == (100, "A")
    assert masked["diagnostics"]["guard"] == plain["diagnostics"]["guard"] and "warnings" not in masked
    assert masked["diagnostics"]["guard"]["residual"] < load_rules()["guard"]["max_residual"]


def test_a_real_seated_stretch_against_itself_scores_without_its_legs():
    clip = str(ROOT / "fixtures/input/mismatch/part2-stretch/skeleton.json")
    doc = run(clip, clip, score=score_block, mask=parse_mask("seated")).analysis
    assert doc["faults"] == [] and doc["body_mask"]["not_scored_chains"] == ["left_leg", "right_leg"]
    assert doc["body_mask"]["text"] == "Legs not scored, by your setting." and doc["score"]["grade"] == "A"
