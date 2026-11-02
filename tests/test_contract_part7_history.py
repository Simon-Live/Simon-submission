"""The analysis fields Part 7's takes-over-time report reads (docs/specs/integration-contract.md AC-C15, TICKET-049, Part 7
TICKET-183): `faults[].measure`, `side`, `at_s`, `follower_t_s`, `text_timed` and `cue`, `score.timeline[].misses[].cue`,
`score.value` and `score.grade`, and where the follower's duration can be read.

Part 7 reads these across many takes without importing Part 5, so this file imports nothing from `part5`: it pins name,
type and meaning in `contracts/analysis.schema.json` and in documents derived from the committed goldens
(`fixtures/output/`), for every schema version from 1.5.0, and pins which of them the schema leaves optional and what
their absence means. The goldens are written at the current version only; an earlier version's document is the golden
with what the later versions added taken out (`as_version`), the way the schema's description lists them."""
import copy
import json
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import jsonschema
import pytest

from shipped_score import IS_CAPPED, IS_V3, SHIPPED, capped_only, v3_only

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "contracts/analysis.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)
GOLDEN_FILES = {"double-fault": "analysis.example.json", "no-faults": "analysis.no-faults.example.json",
                # the samples with a ceiling: written only while the rules ship v2 or v3 (the second only v3); make score-fallback
                # removes them
                **({"fault-capped": "analysis.fault-capped.example.json"} if IS_CAPPED else {}),
                **({"double-capped": "analysis.double-capped.example.json"} if IS_V3 else {})}
GOLDENS = {name: json.loads((ROOT / "fixtures/output" / f).read_text()) for name, f in GOLDEN_FILES.items()}
REPLAY = json.loads((ROOT / "fixtures/output/replay.example.json").read_text())
OLD_1_1_0 = json.loads((ROOT / "tests/fixtures/analysis-1.1.0.example.json").read_text())

# Every analysis schema version from 1.5.0 (ADR-0014, the cues) to the schema's own.
VERSIONS = ("1.5.0", "1.6.0", "1.7.0", "1.8.0", "1.9.0", "1.10.0", "1.11.0", "1.12.0", "1.13.0")

FAULT = SCHEMA["$defs"]["fault"]["properties"]
SCORE = SCHEMA["properties"]["score"]["properties"]
WINDOW = SCORE["timeline"]["items"]["properties"]
MISS = WINDOW["misses"]["items"]["properties"]
BODY_MEASURES = {"elbow_flexion", "knee_flexion", "upper_arm_out", "upper_arm_forward", "forearm_out", "thigh_out",
                 "thigh_forward", "foot_out", "trunk_lean_forward", "trunk_lean_side", "shoulder_tilt", "head_forward",
                 "knee_valgus"}
FOOT_MEASURES = {"foot_rotation", "ankle_inversion"}
GRADES = ["A", "B", "C", "D", "F"]
CUE_PATTERN = r"^\S+(\s\S+){0,5}$"
FAULT_FIELDS = ("measure", "side", "at_s", "follower_t_s", "text_timed", "cue")
OPTIONAL_FAULT_FIELDS = ("at_s", "follower_t_s", "text_timed", "cue")


def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def version_of(text):
    return tuple(int(p) for p in text.split("."))


def as_version(doc, version):
    """`doc` (a current golden) as it was written at `version`: what a later version added is taken out."""
    doc = copy.deepcopy(doc)
    doc["schema_version"] = version
    v = version_of(version)
    if v < (1, 13, 0):   # score.credit, the DDR-style credit display (ADR-0020)
        doc["score"].pop("credit", None)
    if v < (1, 12, 0):   # faults[].rep_sizes, score.per_rep[].rep and .tempo_ratio, near_misses.items[].margin_deg (TICKET-071)
        for fault in doc["faults"]:
            fault.pop("rep_sizes", None)
        for entry in doc["score"].get("per_rep", []):
            entry.pop("rep", None), entry.pop("tempo_ratio", None)
        for item in doc["diagnostics"].get("near_misses", {}).get("items", []):
            item.pop("margin_deg", None)
    if v < (1, 11, 0) and doc["score"]["version"] == "simon.score.v3":   # simon.score.v3 and a fault_cap of 79 (ADR-0019)
        doc["score"]["version"] = "simon.score.v2"
        if "fault_cap" in doc["score"]:
            doc["score"]["fault_cap"] = 89
    if v < (1, 10, 0):   # score.fault_cap and simon.score.v2 (the version enum of v1 documents is v1)
        doc["score"].pop("fault_cap", None)
        doc["score"]["version"] = "simon.score.v1"
    if v < (1, 9, 0):   # phrasing.lang, phrasing.faults[].text and .lang, second_opinion, score.uncapped, source
        doc["phrasing"].pop("lang", None)
        for entry in doc["phrasing"]["faults"]:
            entry.pop("text", None), entry.pop("lang", None)
        for key in ("second_opinion", "source"):
            doc.pop(key, None)
        doc["score"].pop("uncapped", None)
    if v < (1, 8, 0):   # diagnostics.near_misses
        doc["diagnostics"].pop("near_misses", None)
    if v < (1, 7, 0):   # profile
        doc.pop("profile", None)
    if v < (1, 6, 0):   # diagnostics.feet
        doc["diagnostics"].pop("feet", None)
    if v < (1, 13, 0):   # quality, the reading of how well the camera saw the take (TICKET-079, ADR-0021)
        doc.pop("quality", None)
    return doc


def problems(doc):
    return [f"{'/'.join(map(str, e.absolute_path))}: {e.message[:120]}" for e in VALIDATOR.iter_errors(doc)]


def misses(doc):
    return [m for w in doc["score"].get("timeline", []) for m in w.get("misses", [])]


# ---------------------------------------------------------------- the versions covered are the versions the schema has
def test_the_versions_pinned_are_every_version_from_1_5_0_the_schema_describes():
    described = {m for m in re.findall(r"\b1\.\d+\.\d+\b", SCHEMA["description"]) if version_of(m) >= (1, 5, 0)}
    assert described == set(VERSIONS), "a new analysis schema version must be added to VERSIONS (and pinned here)"
    assert list(VERSIONS) == sorted(VERSIONS, key=version_of) and SCHEMA["version"] == VERSIONS[-1]


@pytest.mark.parametrize("name", GOLDENS)
def test_the_goldens_record_the_schemas_own_version_and_validate(name):
    assert GOLDENS[name]["schema_version"] == SCHEMA["version"]
    assert problems(GOLDENS[name]) == []


# ---------------------------------------------------------------- name, type and meaning in the schema
def test_measure_and_side_are_required_enums():
    fault = SCHEMA["$defs"]["fault"]
    assert {"measure", "side"} <= set(fault["required"])
    assert not set(OPTIONAL_FAULT_FIELDS) & set(fault["required"])
    measures = set(FAULT["measure"]["enum"])
    assert measures >= BODY_MEASURES | FOOT_MEASURES, "a measure Part 7 groups by was removed"
    assert "side-less" in FAULT["measure"]["description"] and "1.6.0" in FAULT["measure"]["description"]
    assert FAULT["side"]["enum"] == ["left", "right", "both", "center"]
    assert "subject's own" in FAULT["side"]["description"]


def test_the_time_fields_are_optional_numbers_on_the_followers_own_clock():
    assert FAULT["at_s"]["type"] == "number"
    assert "follower_t_s[0] rounded half up to 0.1 s" in FAULT["at_s"]["description"]
    t = FAULT["follower_t_s"]
    assert t["type"] == "array" and t["minItems"] == t["maxItems"] == 2
    assert t["prefixItems"] == [{"type": "number"}, {"type": "number"}]
    assert "follower file's own clock" in t["description"] and "follower_frames" in t["description"]
    assert FAULT["text_timed"]["type"] == "string" and FAULT["text_timed"]["minLength"] == 1
    assert "' at <at_s> s'" in FAULT["text_timed"]["description"]


@pytest.mark.parametrize("prop", [FAULT["cue"], MISS["cue"]], ids=["faults[].cue", "misses[].cue"])
def test_a_cue_is_a_short_imperative_added_in_1_5_0(prop):
    assert prop["type"] == "string" and prop["minLength"] == 1 and prop["pattern"] == CUE_PATTERN
    assert prop["description"].startswith("1.5.0") and "imperative of at most 6 words" in prop["description"]
    assert "never rewritten by a phrasing backend" in prop["description"]


def test_score_value_and_grade_and_what_the_schema_leaves_optional():
    assert SCORE["value"] == {"type": "integer", "minimum": 0, "maximum": 100}
    assert SCORE["grade"] == {"enum": GRADES}
    assert "score" not in SCHEMA["required"] and SCHEMA["properties"]["score"]["type"] == ["object", "null"]
    assert "Never null from 1.4.0" in SCHEMA["properties"]["score"]["description"]
    assert "required" not in SCHEMA["properties"]["score"], "score.value and grade are required by the producer, not the schema"
    assert "required" not in SCORE["timeline"]["items"] and "required" not in WINDOW["misses"]["items"]
    assert "minimum" not in SCORE["timeline"] and "capped_by" in SCORE
    assert "capped at 59" in SCHEMA["properties"]["score"]["description"] or "capped at 59" in SCHEMA["description"]


# ---------------------------------------------------------------- 1.10.0: the fault cap (ADR-0018, Part 7's answer)
def test_1_10_0_fault_cap_is_an_optional_integer_and_capped_by_keeps_its_meaning():
    cap = SCORE["fault_cap"]
    assert cap["type"] == "integer" and (cap["minimum"], cap["maximum"]) == (0, 100) and cap["description"].startswith("1.10.0")
    assert "faults list is not empty" in cap["description"] and "capped_by does not name it" in cap["description"]
    assert SCORE["version"] == {"enum": ["simon.score.v1", "simon.score.v2", "simon.score.v3"]}
    assert "required" not in SCHEMA["properties"]["score"], "fault_cap is optional: absent for a take with no faults"
    assert SCORE["capped_by"]["items"] == {"type": "string"} and "never in this list" in SCORE["capped_by"]["description"]
    assert "before every cap" in SCORE["uncapped"]["description"] and "no capped_by" in SCORE["uncapped"]["description"]


@capped_only
def test_1_10_0_the_sample_for_part_7_reports_a_fault_and_hits_the_cap_without_a_warning():
    doc = GOLDENS["fault-capped"]
    score = doc["score"]
    assert problems(doc) == [] and len(doc["faults"]) == 1 and "warnings" not in doc
    assert (score["version"], score["value"], score["grade"], score["fault_cap"]) == (SHIPPED, 89, "B", 89)
    assert score["uncapped"]["value"] > 89 and score["uncapped"]["grade"] == "A" and "capped_by" not in score


@capped_only
def test_1_10_0_a_take_with_both_caps_keeps_the_value_before_the_first_and_capped_by_names_the_warning_only():
    doc = copy.deepcopy(GOLDENS["fault-capped"])
    before = doc["score"]["uncapped"]
    doc["warnings"] = [{"code": "low_match", "text": "This take doesn't closely match the trainer's movement."}]
    doc["match"] = {"quality": "low", "residual": 0.2, "timing_corr": 0.1, "limits": {"max_residual": 0.18, "min_timing_corr": 0.5}}
    doc["score"].update(value=59, grade="F", capped_by=["low_match"])
    assert problems(doc) == [] and doc["score"]["uncapped"] == before and doc["score"]["fault_cap"] == 89


def test_1_10_0_a_take_with_no_fault_has_no_fault_cap():
    assert "fault_cap" not in GOLDENS["no-faults"]["score"] and GOLDENS["no-faults"]["faults"] == []
    if IS_CAPPED:
        double = GOLDENS["double-fault"]["score"]
        assert double["value"] <= double["fault_cap"] == (79 if IS_V3 else 89)   # two faults: 79 under v3 (ADR-0019), 89 under v2
    else:
        assert "fault_cap" not in GOLDENS["double-fault"]["score"]


def test_a_1_9_0_score_of_v1_validates_and_carries_no_fault_cap():
    doc = as_version(GOLDENS["double-fault"], "1.9.0")
    assert doc["score"]["version"] == "simon.score.v1" and "fault_cap" not in doc["score"] and problems(doc) == []


# ---------------------------------------------------------------- 1.11.0: simon.score.v3 and the ceiling in force (ADR-0019)
def test_1_11_0_fault_cap_is_the_ceiling_in_force_89_or_79_and_a_1_10_0_document_still_validates():
    cap = SCORE["fault_cap"]
    assert "79" in cap["description"] and "ceiling in force" in cap["description"] and "two or more" in cap["description"]
    assert "1.11.0" in SCHEMA["description"] and "never assume 89" in SCHEMA["description"] and SCHEMA["version"] == VERSIONS[-1]
    doc = as_version(GOLDENS["double-fault"], "1.10.0")   # what a 1.10.0 writer made of the same take: v2, ceiling 89
    assert doc["schema_version"] == "1.10.0" and problems(doc) == []
    if IS_CAPPED:
        assert doc["score"]["version"] == "simon.score.v2" and doc["score"]["fault_cap"] == 89


@v3_only
def test_1_11_0_the_double_capped_sample_reports_two_faults_and_hits_the_79_ceiling_without_a_warning():
    doc = GOLDENS["double-capped"]
    score = doc["score"]
    assert problems(doc) == [] and len(doc["faults"]) == 2 and "warnings" not in doc and doc["schema_version"] == VERSIONS[-1]
    assert (score["version"], score["value"], score["grade"], score["fault_cap"]) == ("simon.score.v3", 79, "C", 79)
    assert score["uncapped"]["value"] > 79 and "capped_by" not in score


@v3_only
def test_1_11_0_one_fault_has_ceiling_89_and_two_or_more_have_79_in_the_goldens():
    assert GOLDENS["fault-capped"]["score"]["fault_cap"] == 89 and len(GOLDENS["fault-capped"]["faults"]) == 1
    for name in ("double-fault", "double-capped"):
        assert GOLDENS[name]["score"]["fault_cap"] == 79 and len(GOLDENS[name]["faults"]) >= 2, name
    assert "fault_cap" not in GOLDENS["no-faults"]["score"]


@v3_only
def test_1_11_0_a_two_fault_take_with_both_caps_keeps_the_value_before_the_first_and_capped_by_names_the_warning_only():
    doc = copy.deepcopy(GOLDENS["double-capped"])
    before = doc["score"]["uncapped"]
    doc["warnings"] = [{"code": "low_match", "text": "This take doesn't closely match the trainer's movement."}]
    doc["match"] = {"quality": "low", "residual": 0.2, "timing_corr": 0.1, "limits": {"max_residual": 0.18, "min_timing_corr": 0.5}}
    doc["score"].update(value=59, grade="F", capped_by=["low_match"])
    assert problems(doc) == [] and doc["score"]["uncapped"] == before and doc["score"]["fault_cap"] == 79


# ---------------------------------------------------------------- the same fields in a document of each version
@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("name", GOLDENS)
def test_a_document_of_each_version_validates_and_carries_every_field_with_its_type(version, name):
    doc = as_version(GOLDENS[name], version)
    assert problems(doc) == [] and doc["schema_version"] == version
    for fault in doc["faults"]:
        assert fault["measure"] in set(FAULT["measure"]["enum"]) and fault["side"] in FAULT["side"]["enum"]
        assert number(fault["at_s"]) and fault["at_s"] >= 0
        t = fault["follower_t_s"]
        assert len(t) == 2 and all(number(x) for x in t) and 0 <= t[0] <= t[1]
        assert isinstance(fault["text_timed"], str) and fault["text_timed"]
        assert isinstance(fault["cue"], str) and re.fullmatch(CUE_PATTERN, fault["cue"])
    score = doc["score"]
    assert isinstance(score["value"], int) and not isinstance(score["value"], bool) and 0 <= score["value"] <= 100
    assert score["grade"] in GRADES
    for miss in misses(doc):
        assert isinstance(miss["cue"], str) and re.fullmatch(CUE_PATTERN, miss["cue"])


@pytest.mark.parametrize("version", VERSIONS)
def test_the_meaning_of_the_time_fields_and_the_cue_holds_in_a_document_of_each_version(version):
    doc = as_version(GOLDENS["double-fault"], version)
    assert doc["faults"], "the double-fault golden has faults"
    for fault in doc["faults"]:
        start = Decimal(str(fault["follower_t_s"][0]))
        assert fault["at_s"] == float(start.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)), "at_s is follower_t_s[0], half up to 0.1"
        assert fault["text_timed"].endswith(f" at {fault['at_s']} s"), "text_timed is the words plus ' at <at_s> s'"
    by_key = {(f["measure"], f["side"], f["at_s"]): f for f in doc["faults"]}
    found = misses(doc)
    assert found and {(m["measure"], m["side"], m["at_s"]) for m in found} <= set(by_key)
    for miss in found:
        fault = by_key[(miss["measure"], miss["side"], miss["at_s"])]
        assert miss["cue"] == fault["cue"], "a miss's cue is the cue of the fault it came from"
        assert miss["t_s"] == fault["follower_t_s"]


@pytest.mark.parametrize("version", VERSIONS)
def test_a_score_of_each_version_is_a_grade_of_its_value_and_a_clean_take_scores_100_a(version):
    clean = as_version(GOLDENS["no-faults"], version)
    assert clean["faults"] == [] and misses(clean) == []
    assert (clean["score"]["value"], clean["score"]["grade"]) == (100, "A")
    worse = as_version(GOLDENS["double-fault"], version)["score"]
    assert worse["value"] < 100 and GRADES.index(worse["grade"]) > 0
    assert all(w.get("compared") is True and "misses" in w for w in worse["timeline"])


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_a_foot_fault_reads_with_the_same_fields_from_1_6_0(version):
    doc = as_version(GOLDENS["double-fault"], version)
    for measure in sorted(FOOT_MEASURES):
        foot = {**doc["faults"][0], "measure": measure, "measure_kind": "direction", "body_part": "feet",
                "joint": "left_ankle", "side": "left", "joints": ["left_ankle"], "cue": "Turn your left foot in"}
        assert problems({**doc, "faults": [foot]}) == [], measure


# ---------------------------------------------------------------- optional means a reader must cope with its absence
@pytest.mark.parametrize("field", OPTIONAL_FAULT_FIELDS)
def test_a_fault_without_an_optional_field_validates(field):
    doc = as_version(GOLDENS["double-fault"], "1.9.0")
    for fault in doc["faults"]:
        del fault[field]
    assert problems(doc) == []


def test_a_miss_without_a_cue_and_a_document_without_a_score_validate():
    doc = as_version(GOLDENS["double-fault"], "1.9.0")
    for miss in misses(doc):
        del miss["cue"]
    assert problems(doc) == []
    del doc["score"]
    assert problems(doc) == []


def test_an_uncompared_window_has_no_misses_and_a_document_without_a_timeline_validates():
    doc = as_version(GOLDENS["double-fault"], "1.9.0")
    doc["score"]["timeline"].append({"t_s": [2.5, 5.0], "compared": False})
    assert problems(doc) == [] and len(misses(doc)) == len(misses(GOLDENS["double-fault"]))
    for key in ("timeline", "basis", "tempo"):
        doc["score"].pop(key, None)
    assert problems(doc) == [] and misses(doc) == []


def test_a_document_written_before_the_cues_validates_and_a_reader_leaves_the_cue_out():
    doc = as_version(GOLDENS["double-fault"], "1.9.0")
    doc["schema_version"] = "1.4.0"
    for fault in doc["faults"]:
        del fault["cue"], fault["cue_kind"]
    for miss in misses(doc):
        del miss["cue"], miss["cue_kind"]
    doc.pop("insights"), doc["score"].pop("tempo")
    assert problems(doc) == [] and all("cue" not in f for f in doc["faults"])


def test_a_1_1_0_document_has_no_time_fields_and_validates_so_absence_means_untimed():
    assert problems(OLD_1_1_0) == []
    assert OLD_1_1_0["schema_version"] == "1.1.0" and OLD_1_1_0["faults"]
    assert not any(k in f for f in OLD_1_1_0["faults"] for k in ("at_s", "follower_t_s", "text_timed", "cue"))
    assert "score" not in OLD_1_1_0


def test_part7s_own_no_person_document_has_a_score_and_no_timeline_or_faults():
    doc = json.loads((ROOT / "fixtures/input/contract/part7/analysis.no-person.json").read_text())
    assert problems(doc) == [] and doc["faults"] == [] and misses(doc) == []
    assert (doc["score"]["value"], doc["score"]["grade"]) == (0, "F") and "timeline" not in doc["score"]


# ---------------------------------------------------------------- the follower's duration
def test_the_analysis_has_no_follower_duration_field():
    """The finding behind AC-C15. When Part 5 adds a field this fails; update the spec, CONTRACT.md and Part 7 first."""
    ref = SCHEMA["$defs"]["clip_ref"]
    assert ref["required"] == ["path"] and set(ref["properties"]) == {"path"}
    assert "additionalProperties" not in ref, "extra ids the caller passes (take_id, set, movement) pass through"
    for doc in GOLDENS.values():
        assert not [k for k in doc["follower"] if "dur" in k or "frame" in k or k.startswith("t_")], doc["follower"]
        assert "duration_s" not in doc["diagnostics"] and "duration_s" not in doc


@pytest.mark.parametrize("name", GOLDENS)
def test_the_end_of_the_compared_span_is_in_the_timeline_and_the_replay_ends_at_the_followers_last_frame(name):
    doc = GOLDENS[name]
    timeline = doc["score"]["timeline"]
    end = timeline[-1]["t_s"][1]
    assert number(end) and timeline[-1]["t_s"][0] < end
    assert all(a["t_s"][1] <= b["t_s"][0] + 1e-9 for a, b in zip(timeline, timeline[1:])), "windows run in time order"
    assert all(f["follower_t_s"][1] <= end + 1e-9 for f in doc["faults"]), "no fault ends after the compared span"
    assert doc["score"]["basis"] == ("reps" if name in ("fault-capped", "double-capped") else "windows")   # a dance take and the real lateral raise are compared rep by rep


def test_the_replay_follower_clock_is_the_exact_duration_and_the_compared_span_never_exceeds_it():
    """Golden 'double-fault' compares the whole clip (span end equals the clip's end); 'no-faults' stands still at the
    end, so its span ends before the clip does: the timeline end is a lower bound, `follower_t[-1]` is the duration."""
    doc = GOLDENS["double-fault"]
    replay_end = REPLAY["follower_t"][-1]
    clip = json.loads((ROOT / doc["follower"]["path"]).read_text())
    assert number(replay_end) and REPLAY["follower_t"][0] == 0.0 and replay_end == clip["duration_s"]
    assert doc["score"]["timeline"][-1]["t_s"][1] == replay_end
    other = GOLDENS["no-faults"]
    longer = json.loads((ROOT / other["follower"]["path"]).read_text())
    assert other["score"]["timeline"][-1]["t_s"][1] < longer["duration_s"] == longer["frames"][-1]["t"]


# ---------------------------------------------------------------- the contract says it
def test_contract_md_names_every_field_the_report_reads_and_the_duration_finding():
    text = (ROOT / "CONTRACT.md").read_text()
    duty = text[text.index("10. **"):text.index("`python -m part5 doctor analysis.json --for part7` checks all")]
    for needle in ("`faults[].measure`", "`side`", "`at_s`", "`follower_t_s`", "`text_timed`", "`cue`",
                   "`score.timeline[].misses[].cue`", "`score.value`", "`score.grade`", "1.5.0",
                   "tests/test_contract_part7_history.py", "no field for the follower's duration",
                   "`score.timeline[-1].t_s[1]`", "`follower_t[-1]`", "`contracts/student-words.json`"):
        assert needle in duty, needle


@pytest.mark.skipif(not (ROOT / "docs/specs/integration-contract.md").is_file(), reason="docs/specs is a workspace directory")
def test_the_spec_lists_the_same_fields_and_names_this_test():
    spec = (ROOT / "docs/specs/integration-contract.md").read_text()
    ac = spec[spec.index("### AC-C15"):spec.index("### AC-C16")]
    for field in ("faults[].measure", "faults[].side", "faults[].at_s", "faults[].follower_t_s", "faults[].text_timed",
                  "faults[].cue", "score.timeline[].misses[].cue", "score.value", "score.grade"):
        assert f"`{field}`" in ac, field
    assert "tests/test_contract_part7_history.py" in ac and "follower_t[-1]" in ac
