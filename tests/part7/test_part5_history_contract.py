"""Part 7's side of the Part 5 history pins (TICKET-183, ASM-023).

Part 5 pins the analysis fields and publishes `contracts/student-words.json` (its `test_contract_part7_history.py`,
Part 5 d6700e8, TICKET-049). Here the pinned Part 5 checkout (`modules/part-5`) is the input: its own golden analysis
and its words file go through the code that reads them, so a Part 5 bump that renames a field or reshapes the words
file fails in Part 7 at the pin bump, before a student sees a wrong report. Part 5 is read as files, never imported.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from part7 import config, history_facts, history_guard

P5 = config.part_dir(5)
SCHEMA = P5 / "contracts" / "analysis.schema.json"
WORDS = P5 / "contracts" / "student-words.json"
GOLDEN = P5 / "fixtures" / "output" / "analysis.example.json"
NO_FAULTS = P5 / "fixtures" / "output" / "analysis.no-faults.example.json"

pytestmark = pytest.mark.skipif(not WORDS.is_file(), reason="modules/part-5 is not checked out (git submodule update --init)")

# The analysis fields history reads (docs/specs/history.md "Facts"; Part 5 TICKET-049).
FAULT_FIELDS = ("measure", "side", "at_s", "follower_t_s", "text_timed", "cue", "magnitude_deg")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def take(path: Path, n: int = 1) -> dict[str, Any]:
    return {"take": n, "analysis": path, "at": f"t{n}", "score": None, "grade": None, "duration_s": 9.9, "entry_id": "squat"}


def test_the_schema_still_names_every_field_history_reads() -> None:  # AC-1
    schema = load(SCHEMA)
    fault = schema["$defs"]["fault"]["properties"]
    assert not [name for name in FAULT_FIELDS if name not in fault], "Part 5 renamed or removed a fault field history reads"
    miss = schema["properties"]["score"]["properties"]["timeline"]["items"]["properties"]["misses"]["items"]["properties"]
    assert "cue" in miss and {"measure", "side"} <= set(schema["$defs"]["fault"]["required"])


def test_the_schema_still_names_the_series_fields() -> None:  # TICKET-218 AC-6, and the status the "absent fault" rule reads
    schema = load(SCHEMA)
    score = schema["properties"]["score"]["properties"]
    assert "reps" in schema["$defs"]["fault"]["properties"] and {"tempo", "per_rep", "version"} <= set(score)
    assert "code" in schema["properties"]["status"]["properties"]


def test_the_golden_analysis_goes_through_the_facts_with_every_pinned_field() -> None:  # AC-1
    analysis = load(GOLDEN)
    assert analysis["faults"], "Part 5's golden has no fault: it cannot pin the fields"
    facts = history_facts.build([take(GOLDEN)])
    row = facts["takes"][0]
    assert len(row["faults"]) == len({(f["measure"], f["side"]) for f in analysis["faults"]})
    for read in row["faults"]:
        source = next(f for f in analysis["faults"] if f["measure"] == read["measure"] and f["side"] == read["side"])
        assert read["at_s"] == source.get("at_s") and read["text_timed"] == source.get("text_timed") and read["cue"] == source.get("cue")
        assert read["span"] == source.get("follower_t_s")
        assert read["at_s"] is not None and read["text_timed"] and read["cue"] and read["span"], "a pinned field is missing in the golden"
    window_cues = [m["cue"] for w in analysis["score"]["timeline"] for m in w.get("misses", []) if m.get("cue")]
    assert row["cues"] == list(dict.fromkeys(window_cues)) and row["cues"]


def test_a_take_with_no_fault_reads_as_an_empty_row() -> None:  # negative
    facts = history_facts.build([take(NO_FAULTS)])
    assert facts["takes"][0]["faults"] == [] and facts["measures"] == []


def test_the_words_file_parses_in_the_shape_the_guard_reads() -> None:  # AC-2
    doc = load(WORDS)
    assert doc["format"] == "simon.student-words.v1" and doc["version"].count(".") == 2
    for key in ("banned", "praise", "ignored_characters"):
        assert doc[key] and all(isinstance(x, str) and x for x in doc[key]), key
    words = history_guard.load_words()
    assert words is not history_guard.DEFAULT_WORDS, "the guard fell back to its defaults: the file's shape changed"
    assert words["banned"] == doc["banned"] and words["praise"] == doc["praise"] and words["ignored"] == doc["ignored_characters"]


def test_every_banned_stem_and_praise_phrase_of_part_5_is_refused_by_the_guard() -> None:  # AC-2
    doc, rules = load(WORDS), history_guard._Words(history_guard.load_words())
    for stem in doc["banned"]:
        assert rules.banned.search(f"a {stem.rstrip('*')}ish knee"), stem
    for phrase in doc["praise"]:
        assert rules.praise.search(f"{phrase.replace(' ', '-')}!"), phrase
    assert not rules.banned.search("your knee tracks over the toes") and not rules.praise.search("your knee tracks over the toes")  # negative


def test_the_fields_the_fair_line_and_the_steadier_status_read_are_still_in_the_schema() -> None:  # TICKET-208 AC-7, TICKET-214 AC-7
    schema = load(SCHEMA)
    top, score = schema["properties"], schema["properties"]["score"]["properties"]
    assert "profile" in top and "diagnostics" in top
    assert {"version", "params_sha256", "fault_cap", "uncapped", "value", "grade"} <= set(score), "Part 5 renamed a score field"
    assert {"lateral_m", "magnitude_deg"} <= set(schema["$defs"]["fault"]["properties"])
    near = schema["properties"]["diagnostics"]["properties"]["near_misses"]["properties"]["items"]["items"]
    assert near == {"$ref": "#/$defs/near_miss"} and {"measure", "side"} <= set(schema["$defs"]["near_miss"]["properties"])
    assert {"measure", "side"} <= set(schema["$defs"]["near_miss"]["required"])


def test_a_score_version_string_the_pin_does_not_know_is_still_its_own_line() -> None:  # TICKET-208 AC-8 (v3 waits for the pin bump)
    from part7 import history_store

    for version in ("simon.score.v1", "simon.score.v2", "simon.score.v3"):
        assert history_store.score_version({"score": {"version": version, "params_sha256": "ab" * 32}}) == f"{version}:abababab"
    assert history_store.score_version({"score": {}}) is None


def test_the_pinned_part_5_commit_carries_the_contract_test() -> None:  # AC-3
    assert (P5 / "tests" / "test_contract_part7_history.py").is_file(), "the pin is older than Part 5 TICKET-049"


# ---- Part 5 TICKET-070: every analysis path history_facts reads is in Part 5's history-fields.json ----
FIELDS = P5 / "contracts" / "history-fields.json"
# The analysis paths part7/history_facts.py reads. `source` is Part 7's own marker on its no_person document: Part 5's file
# lists it under not_listed ("Part 5 never writes it"), so it is checked there instead.
READS = (
    "faults[].measure", "faults[].side", "faults[].at_s", "faults[].follower_t_s", "faults[].text_timed", "faults[].cue",
    "faults[].magnitude_deg", "faults[].lateral_m", "faults[].joint", "faults[].body_part",
    "score.value", "score.grade", "score.fault_cap", "score.uncapped", "score.timeline[].t_s", "score.timeline[].compared",
    "score.timeline[].misses[].cue", "diagnostics.near_misses.items[].measure", "diagnostics.near_misses.items[].side", "profile",
    # history-fields 1.1.0 (analysis 1.12.0): read when present, by history_facts and part7/history_prompt.py
    "faults[].rep_sizes", "faults[].rep_sizes[].rep", "faults[].rep_sizes[].magnitude_deg", "faults[].rep_sizes[].side",
    "faults[].rep_sizes[].body_part", "score.per_rep", "score.per_rep[].rep", "score.per_rep[].value", "score.per_rep[].tempo_ratio",
    "diagnostics.near_misses.items[].margin_deg", "diagnostics.near_misses.items[].magnitude_deg",
    "diagnostics.visibility.excluded", "diagnostics.feet.compared", "status.code", "warnings",
)
PART_7_OWN = ("source",)
NO_FIELDS = pytest.mark.skipif(not FIELDS.is_file(), reason="the pinned Part 5 predates contracts/history-fields.json")


def listed_in(path: str, listed: set[str]) -> bool:
    """Covered when the path, or an array or object that holds it (`score.timeline[].misses[]`), is listed."""
    parts = path.split(".")
    return any(".".join(parts[:n]) in listed for n in range(1, len(parts) + 1))


@NO_FIELDS
def test_every_analysis_path_history_facts_reads_is_listed_in_part_5s_history_fields() -> None:
    doc = load(FIELDS)
    listed = {f["path"] for f in doc["fields"]}
    assert doc["format"] == "simon.part5.history-fields.v1"
    missing = [p for p in READS if not listed_in(p, listed)]
    assert not missing, f"history_facts reads paths Part 5 does not list in history-fields.json: {missing}"
    assert not listed_in("faults[].nonexistent_field_zz", {"scores"}), "the coverage check must be able to fail"
    assert set(PART_7_OWN) <= {n["path"] for n in doc["not_listed"]}, "Part 5 changed how it treats `source`; recheck Part 7's read"


@NO_FIELDS
def test_the_reads_list_covers_every_analysis_key_history_facts_reads() -> None:  # keeps READS honest when the code changes
    import re

    source = Path(history_facts.__file__).read_text(encoding="utf-8")
    keys = set(re.findall(r'(?:\.get\(|\[)"([a-z_0-9]+)"', source))
    known = {seg for p in READS for seg in p.replace("[]", "").split(".")} | set(PART_7_OWN)
    # keys of Part 7's own rows and take records (what history_facts builds and is handed), not of analysis.json; score_changes_without_a_version, what and when are keys of history-fields.json
    known |= {"analysis", "at", "best", "duration_s", "entry_id", "first", "in_group", "job_id", "last", "latest", "magnitude",
              "measures", "mode", "no_person", "private", "rep_numbers", "feet_compared", "status_ok", "warned", "score_changes_without_a_version", "what", "when",
              "score_version", "reference", "light", "section_key", "size", "status", "still_close",
              "take", "takes", "unit", "windows"}
    unknown = sorted(keys - known)
    assert not unknown, f"history_facts reads keys that READS does not name (add the path, or Part 5 must list it): {unknown}"


_LONGPACK_SPEC = Path(__file__).resolve().parents[2] / "docs" / "specs" / "history-longpack.md"


@pytest.mark.skipif(not _LONGPACK_SPEC.is_file(), reason="docs/specs is not published; the workspace runs this check")
def test_the_history_fields_file_is_linked_from_the_longpack_spec() -> None:
    spec = _LONGPACK_SPEC
    assert "modules/part-5/contracts/history-fields.json" in spec.read_text(encoding="utf-8")


# ---- Part 5 ec67dc1: history-fields 1.1.0 and the analysis 1.12.0 fields ----
@NO_FIELDS
def test_the_pin_carries_history_fields_1_1_0_with_the_new_additive_fields() -> None:
    doc = load(FIELDS)
    assert tuple(int(x) for x in doc["version"].split(".")) >= (1, 1, 0) and len(doc["fields"]) >= 79
    listed = {f["path"]: f for f in doc["fields"]}
    for path in ("faults[].rep_sizes", "score.per_rep[].rep", "score.per_rep[].tempo_ratio", "diagnostics.near_misses.items[].margin_deg"):
        assert listed[path]["since"] == "1.12.0", path
    assert load(SCHEMA)["$defs"]["fault"]["properties"].get("rep_sizes"), "analysis schema 1.12.0 has faults[].rep_sizes"


@NO_FIELDS
def test_the_rescale_day_is_read_from_part_5s_list_and_falls_back_without_it() -> None:
    entry = next(e for e in load(FIELDS)["score_changes_without_a_version"] if "simon.score.v1" in e["what"])
    assert history_facts.rescale_day() == entry["when"]
    assert history_facts._rescale_day_from({}) is None and history_facts._rescale_day_from({"score_changes_without_a_version": [{"when": "soon", "what": "simon.score.v1"}]}) is None
    assert history_facts._rescale_day_from({"score_changes_without_a_version": [{"when": "2026-11-05", "what": "simon.score.v1 changed"},
                                                                                 {"when": "2026-09-01", "what": "simon.score.v1 earlier"},
                                                                                 {"when": "2027-01-01", "what": "another version"}]}) == "2026-11-05"


def test_a_rescale_day_that_moves_moves_the_scale_split(monkeypatch: pytest.MonkeyPatch) -> None:  # the fact comes from Part 5, not a date in code
    monkeypatch.setattr(history_facts, "rescale_day", lambda: "2026-11-05")
    old = {"score_version": "simon.score.v1:abcd", "at": "2026-11-01T10:00:00Z"}
    assert history_facts.scale_of(old) == "simon.score.v1:abcd@before-rescale"
    assert history_facts.scale_of({**old, "at": "2026-11-05T00:00:00Z"}) == "simon.score.v1:abcd"


# ---- Part 5 03137b9: history-fields 1.2.0 and the analysis 1.13.0 fields (quality, score.credit) ----
@NO_FIELDS
def test_the_pin_carries_history_fields_1_2_0_with_the_quality_and_credit_paths() -> None:
    doc = load(FIELDS)
    assert tuple(int(x) for x in doc["version"].split(".")) >= (1, 2, 0) and len(doc["fields"]) >= 108
    listed = {f["path"]: f for f in doc["fields"]}
    for path in ("quality.level", "quality.score_cap", "quality.reasons[].words", "score.credit.percent", "score.credit.max_points", "score.credit.grades"):
        assert listed[path]["since"] == "1.13.0", path
    props = load(SCHEMA)["properties"]
    assert {"quality", "score"} <= set(props) and {"credit", "uncapped"} <= set(props["score"]["properties"])


@NO_FIELDS
def test_every_letter_field_carries_an_explicit_order_best_first() -> None:  # history-fields 1.2.0: no reader guesses A to F
    letter = [f for f in load(FIELDS)["fields"] if f["direction"] == "later_letter_is_worse"]
    assert {f["path"] for f in letter} >= {"score.grade", "score.credit.grade"}
    for field in letter:
        assert isinstance(field.get("order"), list) and len(field["order"]) >= 2 and len(set(field["order"])) == len(field["order"]), field["path"]
    by_path = {f["path"]: f["order"] for f in letter}
    assert by_path["score.grade"] == ["A", "B", "C", "D", "F"] and by_path["score.credit.grade"] == ["S", "A", "B", "C", "D", "E", "F"]


@NO_FIELDS
def test_the_quality_and_credit_blocks_keep_the_names_part_7_reads() -> None:  # part7/quality_cap.py and web/model/score-credit.js
    schema = load(SCHEMA)
    block = schema["$defs"]["quality"]
    assert {"level", "reasons", "score_cap", "signals", "version"} <= set(block["required"])
    assert block["properties"]["level"]["enum"] == ["ok", "degraded", "major"]
    assert {"code", "words"} <= set(block["properties"]["reasons"]["items"]["required"])
    credit = schema["properties"]["score"]["properties"]["credit"]["properties"]
    assert {"percent", "points", "max_points", "grades", "levels", "tolerance"} <= set(credit)
