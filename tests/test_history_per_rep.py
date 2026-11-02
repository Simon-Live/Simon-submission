"""Analysis 1.12.0 (TICKET-071, docs/specs/history-per-rep.md): the fields Part 7 compares takes with, rep by rep.

`faults[].rep_sizes` (a fault's size in each rep that found it), `score.per_rep[].rep` and `.tempo_ratio` (the rep's tempo,
null where unmeasured) and `diagnostics.near_misses.items[].margin_deg` (the size past the threshold). All three are
derived from what detection and the score already found: nothing reads them back, a 1.11.0 document still validates, and
the two baselines (fitness, detection) hash a document without them."""
import copy
import json
import math
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest

from part5 import profiles, profiles_report, repwise, score
from part5.detect import EXPLAINED_BY, FITNESS, PERSISTENCE, REPS, Detection, load_rules, margin_deg, summary
from part5.output import OutputError, fault_to_dict, validate_analysis
from part5.score_report import score_block
from test_contract_part7_history import as_version
from test_near_misses_reps import cand
from test_reps import compare_under, fast, rep, sided  # noqa: F401  (`fast` is a fixture)

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "contracts/analysis.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)
WHOLE = json.loads((ROOT / "fixtures/output/analysis.example.json").read_text())   # a take compared as a whole
LOW = {"quality": "low", "residual": 0.7, "timing_corr": 0.5, "limits": {"max_residual": 0.5677, "min_timing_corr": 0.8336}}


def schema_errors(doc):
    return [e.message[:100] for e in VALIDATOR.iter_errors(doc)]


def mutated(doc, change):
    out = copy.deepcopy(doc)
    change(out)
    return out


def rejects(doc, fragment):
    with pytest.raises(OutputError) as e:
        validate_analysis(doc)
    assert fragment in str(e.value)


# ---------------------------------------------------------------- the version
def test_the_schema_and_every_new_document_are_1_12_0_and_the_description_names_it():
    assert SCHEMA["version"] == "1.13.0" and "1.12.0 (TICKET-071" in SCHEMA["description"]
    assert "positive when the candidate went past the threshold" in SCHEMA["description"]
    assert WHOLE["schema_version"] == "1.13.0" and schema_errors(WHOLE) == []


def test_a_1_11_0_document_still_validates_with_none_of_the_new_fields(fast):
    old = as_version(fast.analysis, "1.11.0")
    assert old["schema_version"] == "1.11.0" and all("rep_sizes" not in f for f in old["faults"])
    assert all(set(e) == {"value", "grade"} for e in old["score"]["per_rep"])
    assert all("margin_deg" not in i for i in old["diagnostics"]["near_misses"]["items"])
    assert schema_errors(old) == [] and validate_analysis(old) is old
    assert schema_errors(as_version(WHOLE, "1.11.0")) == []


# ---------------------------------------------------------------- faults[].rep_sizes: the aggregation's occurrences
def sizes(reps):
    [(fault_, indices, occ)] = repwise.aggregate_faults(reps)
    return fault_, indices, repwise.rep_sizes(fault_, indices, occ, reps)


def test_a_fault_lists_its_size_in_each_rep_that_found_it_in_rep_order():
    reps4 = [rep(0, [sided("left", -12.0)]), rep(1, []), rep(2, [sided("left", -20.0)]), rep(3, [sided("left", -14.0)])]
    fault_, indices, listed = sizes(reps4)
    assert indices == [0, 2, 3]
    assert listed == [{"rep": 0, "magnitude_deg": -12.0, "side": "left", "body_part": "legs"},
                      {"rep": 2, "magnitude_deg": -20.0, "side": "left", "body_part": "legs"},
                      {"rep": 3, "magnitude_deg": -14.0, "side": "left", "body_part": "legs"}]
    assert fault_.magnitude_deg == -14.0 == sorted(e["magnitude_deg"] for e in listed)[1]   # the median of the listed sizes


def test_a_rep_that_found_both_sides_of_a_fault_reported_on_one_side_lists_the_both_sides_size():
    """N1 (recheck): right in reps 0 to 2 and `both` in rep 3 of 4. The take reports the right side, rep 3 is among the
    reps it was found in, and its entry is that rep's own `both` fault (the two sides' mean) with side `both`."""
    reps4 = [rep(i, [sided("right", -10.0 - i)]) for i in range(3)] + [rep(3, [sided("both", -30.0)])]
    fault_, indices, listed = sizes(reps4)
    assert (fault_.side, indices) == ("right", [0, 1, 2, 3])
    assert [(e["rep"], e["side"], e["magnitude_deg"]) for e in listed] == \
           [(0, "right", -10.0), (1, "right", -11.0), (2, "right", -12.0), (3, "both", -30.0)]
    assert fault_.magnitude_deg == -11.0     # sized from the right side's own reps: the both rep is listed, not averaged in


def test_a_fault_reported_on_both_sides_lists_the_side_each_rep_found_it_on():
    """B2 (pre-freeze review): a rep whose two sides did not merge counts once, as the larger side; the others as found."""
    reps4 = [rep(0, [sided("left"), sided("right", -20.0)]), rep(1, [sided("both", -14.0)]), rep(2, []), rep(3, [])]
    fault_, indices, listed = sizes(reps4)
    assert (fault_.side, indices) == ("both", [0, 1])
    assert [(e["rep"], e["side"], e["magnitude_deg"]) for e in listed] == [(0, "right", -20.0), (1, "both", -14.0)]


def test_a_rep_the_guard_refused_is_not_listed():
    reps3 = [rep(0, [sided("left", -12.0)]), rep(1, [sided("left", -50.0)], ok=False), rep(2, [sided("left", -14.0)])]
    _, indices, listed = sizes(reps3)
    assert indices == [e["rep"] for e in listed] == [0, 2]


def test_the_listed_reps_are_the_reps_of_the_fault_on_every_split(fast, monkeypatch):
    """Through `compare` on the real 8-rep take, with the sides scripted rep by rep and a different size in each."""
    calls = {"i": 0}
    monkeypatch.setattr(repwise, "continue_reported", lambda *a, **k: None)
    script = [["left"], ["both"], ["right"], ["both"], ["both"], [], [], []]

    def scripted(ref_m, fol_m, alignment, rules, candidates=False, fps=None):
        i, calls["i"] = calls["i"], calls["i"] + 1
        return Detection([replace(sided(s, -10.0 - i), measure="thigh_out", direction="less") for s in script[i]], [])

    monkeypatch.setattr(repwise, "detect_full", scripted)
    run_ = compare_under(fast, load_rules())
    [only] = run_.times
    assert only["reps"] == [0, 1, 2, 3, 4] and [e["rep"] for e in only["rep_sizes"]] == only["reps"]
    assert [(e["side"], e["magnitude_deg"]) for e in only["rep_sizes"]] == \
           [("left", -10.0), ("both", -11.0), ("right", -12.0), ("both", -13.0), ("both", -14.0)]
    assert run_.faults[0].side == "both" and all(e["body_part"] == "legs" for e in only["rep_sizes"])
    written = fault_to_dict(run_.faults[0], only)
    assert written["rep_sizes"] == only["rep_sizes"] and written["reps"] == only["reps"]


def test_fault_to_dict_writes_rep_sizes_only_when_given_and_as_plain_numbers():
    f = sided("left", -12.0)
    base = {"follower_t_s": [1.0, 2.0], "follower_runs": [[3, 9]], "reps": [0]}
    assert "rep_sizes" not in fault_to_dict(f, base) and "rep_sizes" not in fault_to_dict(f)
    entry = {"rep": 0, "magnitude_deg": -12, "side": "left", "body_part": "legs"}
    [written] = fault_to_dict(f, {**base, "rep_sizes": [entry]})["rep_sizes"]
    assert written == entry and isinstance(written["magnitude_deg"], float) and isinstance(written["rep"], int)


def test_a_take_compared_rep_by_rep_has_rep_sizes_on_every_fault_and_a_whole_clip_has_none(fast):
    faults = fast.analysis["faults"]
    assert faults and all("rep_sizes" in f and "reps" in f for f in faults)
    assert WHOLE["faults"] and all("rep_sizes" not in f and "reps" not in f for f in WHOLE["faults"])
    assert "per_rep" not in WHOLE["score"]


def test_the_real_take_lists_each_reps_size_and_the_median_of_the_reps_it_was_sized_from_is_the_faults(fast):
    for f in fast.analysis["faults"]:
        listed = f["rep_sizes"]
        assert [e["rep"] for e in listed] == f["reps"] == sorted(set(f["reps"]))
        assert all(e["body_part"] == f["body_part"] and e["magnitude_deg"] * f["magnitude_deg"] > 0 for e in listed)
        own = sorted(e["magnitude_deg"] for e in listed if f["side"] == "both" or e["side"] == f["side"])
        mid = len(own) // 2
        median = own[mid] if len(own) % 2 else (own[mid - 1] + own[mid]) / 2
        assert f["magnitude_deg"] == pytest.approx(median, abs=0.05), f["measure"]
    assert schema_errors(fast.analysis) == [] and validate_analysis(fast.analysis) is fast.analysis


def test_a_malformed_rep_sizes_is_an_error_naming_the_field(fast):
    doc = fast.analysis
    first = lambda d: d["faults"][0]   # noqa: E731

    def edit(change):
        return mutated(doc, lambda d: change(first(d)))

    rejects(edit(lambda f: f.update(rep_sizes=[])), "faults[0].rep_sizes must be a non-empty list")
    rejects(edit(lambda f: f.update(rep_sizes=f["rep_sizes"][:-1])), "one entry per rep in faults[0].reps")
    rejects(edit(lambda f: f.pop("reps")), "one entry per rep in faults[0].reps")
    rejects(edit(lambda f: f["rep_sizes"][0].update(side="up")), "faults[0].rep_sizes[0].side")
    rejects(edit(lambda f: f["rep_sizes"][0].update(body_part="feet")), "faults[0].rep_sizes[0].body_part")
    rejects(edit(lambda f: f["rep_sizes"][0].update(magnitude_deg=0)), "signed like the direction")
    rejects(edit(lambda f: f["rep_sizes"][0].update(magnitude_deg=-f["rep_sizes"][0]["magnitude_deg"])),
            "faults[0].rep_sizes[0].magnitude_deg")
    rejects(edit(lambda f: f["rep_sizes"][0].update(magnitude_deg="12")), "faults[0].rep_sizes[0].magnitude_deg")
    assert schema_errors(edit(lambda f: f["rep_sizes"][0].pop("body_part"))) != []
    assert schema_errors(edit(lambda f: f["rep_sizes"][0].update(rep=-1))) != []


# ---------------------------------------------------------------- score.per_rep[].rep and .tempo_ratio
def test_each_per_rep_entry_names_its_rep_and_carries_the_windows_own_tempo_ratio(fast):
    block = fast.analysis["score"]
    entries, timeline = block["per_rep"], block["timeline"]
    assert [e["rep"] for e in entries] == list(range(8)) and len(timeline) == 8
    for e in entries:
        window = timeline[e["rep"]]
        assert e["tempo_ratio"] == window["tempo"]["ratio"] and 0 < e["tempo_ratio"] < 0.5
        assert (e["value"], e["grade"]) == (window["value"], window["grade"])
    assert list(entries[0]) == ["value", "grade", "rep", "tempo_ratio"]


@pytest.mark.parametrize("profile", profiles.names())
def test_a_low_match_gives_a_null_tempo_ratio_for_every_rep_and_an_ok_take_keeps_its_ratios(fast, profile):
    """TICKET-063: on a low match the tempo is not measured, so no rep has a ratio; `score.tempo_ratio` is the one place a
    ratio is made and the per-rep entry reads the window's, so it cannot disagree."""
    rules = profiles.effective_rules(load_rules(), profile)
    ok = score_block(fast, rules)
    low = score_block(replace(fast, analysis={**fast.analysis, "match": LOW}), rules)
    assert [e["rep"] for e in low["per_rep"]] == [e["rep"] for e in ok["per_rep"]] == list(range(8))
    assert all(e["tempo_ratio"] is None for e in low["per_rep"])
    assert all(isinstance(e["tempo_ratio"], float) for e in ok["per_rep"])
    doc = {**fast.analysis, "match": LOW, "warnings": [{"code": "low_match", "text": "This take is a poor match."}],
           "score": low}
    assert validate_analysis(doc) is doc and schema_errors(doc) == []


def test_a_rep_whose_tempo_could_not_be_measured_has_a_null_ratio_and_the_others_keep_theirs(fast, monkeypatch):
    real = score.tempo_ratio
    calls = {"i": 0}

    def unmeasured_third(analysis, follower_t, expected_t):
        i, calls["i"] = calls["i"], calls["i"] + 1
        return None if i == 2 else real(analysis, follower_t, expected_t)

    monkeypatch.setattr(score, "tempo_ratio", unmeasured_third)
    block = score_block(fast)
    assert [e["tempo_ratio"] is None for e in block["per_rep"]] == [False, False, True] + [False] * 5
    assert block["timeline"][2]["tempo"] == {"ratio": None, "cue": None}
    assert all(e["tempo_ratio"] == block["timeline"][e["rep"]]["tempo"]["ratio"] for e in block["per_rep"])


def test_a_rep_that_did_not_match_is_left_out_and_the_others_keep_their_own_index(fast):
    reps = [replace(r, ok=False) if r.index == 2 else r for r in fast.reps]
    block = score_block(replace(fast, reps=reps))
    assert [e["rep"] for e in block["per_rep"]] == [0, 1, 3, 4, 5, 6, 7]
    assert block["timeline"][2]["compared"] is False
    assert all(e["tempo_ratio"] == block["timeline"][e["rep"]]["tempo"]["ratio"] for e in block["per_rep"])


def test_a_malformed_per_rep_entry_is_an_error_naming_the_field(fast):
    doc = fast.analysis

    def edit(change):
        return mutated(doc, lambda d: change(d["score"]["per_rep"][1]))

    rejects(edit(lambda e: e.update(rep=-1)), "score.per_rep[1].rep must be a rep index")
    rejects(edit(lambda e: e.update(rep=1.5)), "score.per_rep[1].rep must be a rep index")
    rejects(edit(lambda e: e.update(tempo_ratio="fast")), "score.per_rep[1].tempo_ratio must be a number")
    rejects(edit(lambda e: e.update(tempo_ratio=-0.3)), "score.per_rep[1].tempo_ratio must be a number")
    rejects(edit(lambda e: e.update(tempo_ratio=e["tempo_ratio"] + 0.5)), "must be the tempo.ratio of score.timeline[1]")
    assert schema_errors(edit(lambda e: e.update(tempo_ratio=-0.3))) != []
    assert schema_errors(edit(lambda e: e.update(tempo_ratio=None))) == []     # null is the unmeasured value
    old = as_version(doc, "1.11.0")   # an entry with a value and a grade only
    assert all("rep" not in e and "tempo_ratio" not in e for e in old["score"]["per_rep"]) and validate_analysis(old) is old


# ---------------------------------------------------------------- near_misses.items[].margin_deg
@pytest.mark.parametrize("magnitude,threshold,margin", [
    (79.1, 15.0, 64.1), (-79.1, 15.0, 64.1),       # past the threshold by that much, whichever way the fault points
    (17.2, 17.0, 0.2), (-17.2, 17.0, 0.2),
    (15.0, 15.0, 0.0), (-15.0, 15.0, 0.0),         # on it
    (12.0, 15.0, -3.0), (-12.0, 15.0, -3.0),       # short of it: the sign is defined although no candidate stays short today
    (14.96, 15.0, 0.0), (-15.04, 15.0, 0.0),       # a rounding to zero is 0.0, never -0.0
])
def test_the_margin_is_the_size_past_the_threshold_signed_positive_when_past(magnitude, threshold, margin):
    got = margin_deg(magnitude, threshold)
    assert got == margin and math.copysign(1.0, got) == (-1.0 if margin < 0 else 1.0)


REASON_FIELDS = [(PERSISTENCE, {}), (EXPLAINED_BY, {"explained_by": ("trunk_lean_forward", "center", "more")}),
                 (REPS, {"found_in_reps": 1, "needed_reps": 4}), (FITNESS, {"found_in_reps": 4, "needed_reps": 4})]


@pytest.mark.parametrize("outcome,extra", REASON_FIELDS)
@pytest.mark.parametrize("direction,magnitude", [("more", 15.0), ("less", -15.0)])
def test_every_near_miss_item_carries_its_margin_whatever_the_reason_and_direction(outcome, extra, direction, magnitude):
    miss = cand(direction=direction, outcome=outcome, magnitude_deg=magnitude, threshold_deg=13.0, **extra)
    item = miss.to_dict()
    assert item["margin_deg"] == 2.0 and item["reason"] == outcome
    assert list(item).index("margin_deg") == list(item).index("threshold_deg") + 1
    assert summary([miss])["items"][0]["margin_deg"] == 2.0


def near_misses(doc):
    return doc["diagnostics"]["near_misses"]["items"]


def test_the_committed_and_the_rep_by_rep_documents_carry_a_margin_that_agrees_with_the_item(fast):
    for doc in (WHOLE, fast.analysis):
        items = near_misses(doc)
        assert items, "a document without near misses would not exercise the field"
        for item in items:
            assert item["margin_deg"] == round(abs(item["magnitude_deg"]) - item["threshold_deg"], 1) >= 0
        assert schema_errors(doc) == [] and validate_analysis(doc) is doc


def test_every_seed_5_near_miss_of_every_profile_has_a_margin_of_zero_or_more(seed5):
    analyses, _ = seed5
    seen = 0
    for profile, takes in analyses.items():
        for take_id, doc in takes.items():
            for item in near_misses(doc):
                seen += 1
                assert item["margin_deg"] == margin_deg(item["magnitude_deg"], item["threshold_deg"]) >= 0, (profile, take_id)
            assert doc["schema_version"] == "1.13.0" and validate_analysis(doc) is doc
    assert seen > 100


def test_a_wrong_margin_is_an_error_naming_the_field_and_a_1_11_0_item_without_one_is_valid():
    def edit(change):
        return mutated(WHOLE, lambda d: change(near_misses(d)[0]))

    right = near_misses(WHOLE)[0]["margin_deg"]
    rejects(edit(lambda i: i.update(margin_deg=right + 0.5)), "diagnostics.near_misses.items[0].margin_deg")
    rejects(edit(lambda i: i.update(margin_deg="1.1")), "diagnostics.near_misses.items[0].margin_deg")
    rejects(edit(lambda i: i.update(margin_deg=True)), "diagnostics.near_misses.items[0].margin_deg")
    rejects(edit(lambda i: i.update(margin_deg=None)), "diagnostics.near_misses.items[0].margin_deg")
    assert schema_errors(edit(lambda i: i.update(margin_deg="1.1"))) != []
    assert validate_analysis(edit(lambda i: i.pop("margin_deg"))) and "margin_deg" in SCHEMA["$defs"]["near_miss"]["properties"]
    assert "margin_deg" not in SCHEMA["$defs"]["near_miss"]["required"]


def test_the_schema_defines_the_sign_of_the_margin():
    text = SCHEMA["$defs"]["near_miss"]["properties"]["margin_deg"]["description"]
    for phrase in ("abs(magnitude_deg) minus threshold_deg", "Positive", "went past the threshold", "0: it sat on",
                   "Negative", "stayed short of the threshold"):
        assert phrase in text


# ---------------------------------------------------------------- the baselines hash a document without the new fields
def without_1_12(doc):
    out = copy.deepcopy(doc)
    for f in out["faults"]:
        f.pop("rep_sizes", None)
    for e in out["score"].get("per_rep", []):
        e.pop("rep", None), e.pop("tempo_ratio", None)
    for i in near_misses(out):
        i.pop("margin_deg", None)
    return out


def test_the_fitness_digest_does_not_see_the_1_12_0_fields_and_still_sees_what_they_derive_from(fast):
    plain = without_1_12(fast.analysis)
    assert fast.analysis["faults"][0]["rep_sizes"] and profiles_report.analysis_digest(fast.analysis) == \
        profiles_report.analysis_digest(plain)
    for change in (lambda d: d["faults"][0].update(magnitude_deg=d["faults"][0]["magnitude_deg"] + 0.1),
                   lambda d: d["score"]["per_rep"][0].update(value=1),
                   lambda d: d["faults"].pop()):
        assert profiles_report.analysis_digest(mutated(fast.analysis, change)) != profiles_report.analysis_digest(plain)


def test_the_detection_digest_does_not_see_the_1_12_0_fields_and_still_sees_what_they_derive_from(fast):
    plain = without_1_12(fast.analysis)
    assert profiles_report.detection_digest(fast.analysis) == profiles_report.detection_digest(plain)
    for change in (lambda d: d["faults"][0].update(magnitude_deg=d["faults"][0]["magnitude_deg"] + 0.1),
                   lambda d: near_misses(d)[0].update(magnitude_deg=near_misses(d)[0]["magnitude_deg"] + 0.1)):
        assert profiles_report.detection_digest(mutated(fast.analysis, change)) != profiles_report.detection_digest(plain)
