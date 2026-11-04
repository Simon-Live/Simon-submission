"""`contracts/history-fields.json`, the allowlist of the `analysis.json` fields a report across a person's takes reads
(docs/specs/integration-contract.md AC-C19, TICKET-070, CONTRACT.md "History across takes").

tests/test_contract_part7_history.py pins nine fields Part 7's takes-over-time report reads. This file pins the wider list
Part 7's pattern finder and Ask read, one entry per field path, against the schema and the committed examples:

- every path exists in `contracts/analysis.schema.json`, and renaming one fails (a control renames each in turn);
- every `since` agrees with the schema's own words (the version a description opens with, or the clause that lists the
  additions of 1.1.0 to 1.3.0) and with the committed documents: a golden at each version from 1.5.0 (derived by
  `as_version`, the way the schema's description lists the additions), the 1.1.0 example and Part 7's own no-person
  document carry no path before its `since`, and the always-written paths are where `since` says;
- the file describes the schema's own version, so a new analysis schema version fails until the file is updated;
- the score versions, the measures and the side convention the file states are the ones the schema and the rules have.

Like the file it sits beside, it reads the files and imports nothing from `part5`."""
import json
import re
from pathlib import Path

import pytest

from shipped_score import v3_only
from test_contract_part7_history import GOLDENS, OLD_1_1_0, SCHEMA, VERSIONS, as_version, version_of

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "contracts/history-fields.json"
TEXT = FILE.read_text(encoding="utf-8")
HISTORY = json.loads(TEXT)
FIELDS = HISTORY["fields"]
BY_PATH = {f["path"]: f for f in FIELDS}
PART7_NO_PERSON = json.loads((ROOT / "fixtures/input/contract/part7/analysis.no-person.json").read_text())

EARLY = ("1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0")   # before the versions test_contract_part7_history pins
KNOWN_VERSIONS = EARLY + VERSIONS
ENTRY_KEYS = {"path", "meaning", "units", "direction", "side_convention", "since", "stability", "presence", "notes"}
LETTER_LISTS = {"score.credit.grades"}   # a list of letters: direction none, but an `order` like each letter field
UNITS = {"degrees", "metres", "seconds", "score points", "ratio", "fraction", "count", "index", "millimetres", "none"}
# The paths the ticket names; removing one from the file fails (TICKET-070 acceptance).
REQUIRED = {
    *(f"faults[].{leaf}" for leaf in (
        "measure", "side", "joint", "joints", "body_part", "direction", "magnitude_deg", "peak_deg", "threshold_deg", "at_s",
        "follower_t_s", "runs", "follower_runs", "reps", "cue", "cue_kind", "text", "text_timed", "confidence")),
    *(f"score.{leaf}" for leaf in (
        "value", "grade", "version", "params_sha256", "basis", "fault_cap", "uncapped", "capped_by", "per_rep", "tempo",
        "timeline[].t_s", "timeline[].compared", "timeline[].value", "timeline[].misses[]", "timeline[].tempo")),
    "insights[]", "profile", "status", "warnings", "match", "diagnostics.near_misses", "schema_version",
}
# The eight fields analysis 1.12.0 adds (TICKET-071), listed from the version the schema introduces them in.
ADDED_IN_1_12_0 = {
    "faults[].rep_sizes", "faults[].rep_sizes[].rep", "faults[].rep_sizes[].magnitude_deg", "faults[].rep_sizes[].side",
    "faults[].rep_sizes[].body_part", "score.per_rep[].rep", "score.per_rep[].tempo_ratio",
    "diagnostics.near_misses.items[].margin_deg",
}
SIDE_FIELDS = ("faults[].side", "faults[].joint", "faults[].joints", "faults[].lateral", "score.timeline[].misses[].side",
               "diagnostics.near_misses.items[].side")


# ---------------------------------------------------------------- the schema, walked by path
def deref(node):
    """`node` with a `$ref` replaced by what it points at (the use site's own keys win)."""
    while "$ref" in node:
        target = SCHEMA
        for part in node["$ref"].lstrip("#/").split("/"):
            target = target[part]
        node = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
    return node


def schema_node(path):
    """The schema node a history path names, or None when the schema has no such field. A dot goes into a property, [] into
    the items of an array."""
    node = deref(SCHEMA)
    for part in path.split("."):
        found = re.fullmatch(r"([A-Za-z_0-9]+)((?:\[\])*)", part)
        if not found or "properties" not in node or found.group(1) not in node["properties"]:
            return None
        node = deref(node["properties"][found.group(1)])
        for _ in range(len(found.group(2)) // 2):
            if not isinstance(node.get("items"), dict):
                return None
            node = deref(node["items"])
    return node


def renamed(path):
    """`path` with its last field renamed: what a rename in the schema would leave the file pointing at."""
    return re.sub(r"([A-Za-z_0-9]+)((?:\[\])*)$", r"\1_renamed\2", path)


def doc_paths(doc):
    """Every field path a document holds, written like the file's paths (a list adds [] and its items are walked)."""
    out = set()

    def walk(node, path):
        if path:
            out.add(path)
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for item in node:
                walk(item, path + "[]")

    walk(doc, "")
    return out


def holds(paths, path):
    """Does a document with these paths hold `path`? An array path (ending in []) holds when the list is there, empty or not."""
    return (path[:-2] if path.endswith("[]") else path) in paths


def written(doc, path):
    """Is `path` in `doc` where its presence says it is: in the document, or on every fault for `faults[].x`?"""
    if path.startswith("faults[]."):
        return all(path[len("faults[]."):] in fault for fault in doc["faults"])
    return holds(doc_paths(doc), path)


# What the committed goldens hold now, and each of them as it was written at every version the history test pins.
CURRENT = {name: doc_paths(doc) for name, doc in GOLDENS.items()}
DERIVED = {(name, version): doc_paths(as_version(doc, version)) for name, doc in GOLDENS.items() for version in VERSIONS}


def known_before(path, version):
    return version_of(BY_PATH[path]["since"]) <= version_of(version)


# ---------------------------------------------------------------- the file itself
def test_the_file_is_the_versioned_allowlist_of_the_schema_it_describes():
    assert HISTORY["format"] == "simon.part5.history-fields.v1"
    assert re.fullmatch(r"\d+\.\d+\.\d+", HISTORY["version"])
    assert HISTORY["analysis_schema_version"] == SCHEMA["version"], \
        "a new analysis schema version needs its fields in contracts/history-fields.json and the file's version raised"
    assert HISTORY["analysis_schema_version"] == VERSIONS[-1]
    for key in ("how_to_read", "side_convention", "compare_like_with_like", "absent_means", "score_versions", "measures",
                "score_changes_without_a_version", "detection_changes_without_a_version", "fields", "not_listed"):
        assert HISTORY[key], key


def test_the_paths_are_unique_and_every_path_the_ticket_names_is_listed():
    paths = [f["path"] for f in FIELDS]
    assert len(paths) == len(set(paths))
    assert REQUIRED <= set(paths), sorted(REQUIRED.difference(paths))


def test_the_eight_fields_of_1_12_0_are_listed_from_1_12_0_and_the_file_adds_no_other_path_of_that_version():
    """TICKET-071: the schema's 1.12.0 fields are all here, dated 1.12.0, and nothing else claims that version. The schema
    walk below proves each path exists, so a field the schema dropped or renamed fails there."""
    assert ADDED_IN_1_12_0 <= set(BY_PATH), sorted(ADDED_IN_1_12_0.difference(BY_PATH))
    assert {p for p, f in BY_PATH.items() if f["since"] == "1.12.0"} == ADDED_IN_1_12_0
    assert len(ADDED_IN_1_12_0) == 8
    assert BY_PATH["score.per_rep"]["since"] == "1.3.0" and BY_PATH["score.per_rep"]["stability"] == "additive"
    assert "null" in BY_PATH["score.per_rep[].tempo_ratio"]["notes"] and "never on time" in BY_PATH["score.per_rep[].tempo_ratio"]["notes"]


@pytest.mark.parametrize("path", BY_PATH)
def test_an_entry_has_the_keys_and_values_the_file_defines(path):
    entry, how = BY_PATH[path], HISTORY["how_to_read"]
    lettered = entry["direction"] == "later_letter_is_worse" or path in LETTER_LISTS   # review R3 of 1.13.0: `order`
    assert set(entry) == ENTRY_KEYS | ({"present_when"} if entry["presence"] == "conditional" else set()) | (
        {"order"} if lettered else set())
    assert entry["units"] in UNITS
    assert entry["direction"] in how["direction_values"]
    assert entry["stability"] in how["stability_values"] and entry["stability"] in ("stable", "additive")
    assert entry["presence"] in how["presence_values"]
    assert entry["since"] in KNOWN_VERSIONS and version_of(entry["since"]) <= version_of(SCHEMA["version"])
    assert entry["side_convention"] in (None, "subject_own")
    for key in ("meaning", "notes"):
        assert isinstance(entry[key], str) and entry[key].strip(), key
    if entry["presence"] == "conditional":
        assert entry["present_when"].strip()


def test_the_definitions_cover_exactly_the_values_the_entries_use():
    how = HISTORY["how_to_read"]
    assert {f["direction"] for f in FIELDS} <= set(how["direction_values"])
    assert {f["presence"] for f in FIELDS} == set(how["presence_values"])
    assert set(how["stability_values"]) == {"stable", "additive"} == {f["stability"] for f in FIELDS}
    assert {f["units"] for f in FIELDS} <= UNITS


# ---------------------------------------------------------------- every path is in the schema; a rename fails
@pytest.mark.parametrize("path", BY_PATH)
def test_every_path_exists_in_the_analysis_schema(path):
    assert schema_node(path) is not None, f"{path} is not in contracts/analysis.schema.json"


@pytest.mark.parametrize("path", BY_PATH)
def test_renaming_a_path_fails_the_schema_check(path):
    assert schema_node(path) is not None and schema_node(renamed(path)) is None, renamed(path)


def test_the_check_reports_a_renamed_entry_by_name():
    fields = [dict(f) for f in FIELDS]
    fields[[f["path"] for f in fields].index("faults[].magnitude_deg")]["path"] = "faults[].magnitude"
    assert [f["path"] for f in fields if schema_node(f["path"]) is None] == ["faults[].magnitude"]
    assert [f["path"] for f in FIELDS if schema_node(f["path"]) is None] == []


def test_the_walk_of_the_schema_reads_each_kind_of_path():
    assert schema_node("faults[]")["type"] == "object" and schema_node("faults[].measure")["enum"][0] == "elbow_flexion"
    assert schema_node("score.timeline[].misses[].points") is not None and schema_node("diagnostics.near_misses.items[].side")
    assert schema_node("faults[].measure.x") is None and schema_node("faults.measure") is None and schema_node("nope") is None


# ---------------------------------------------------------------- since agrees with what the schema says
VERSION_OPENING = re.compile(r"^(\d+\.\d+\.\d+)(?: \(|:)")
DESC = SCHEMA["description"]
CLAUSES = {   # the additions the schema's opening description lists for the first three versions
    "1.1.0": DESC[DESC.index("(schema_version"):DESC.index("1.2.0: faults")],
    "1.2.0": DESC[DESC.index("1.2.0: faults"):DESC.index("1.3.0: faults")],
    "1.3.0": DESC[DESC.index("1.3.0: faults"):DESC.index("A document without them keeps")],
}


def levels(path):
    """`path` and every field around it, innermost first: score.timeline[].tempo, score.timeline[], score.timeline, score."""
    out, prefix = [], ""
    for part in path.split("."):
        prefix = f"{prefix}.{part.replace('[]', '')}" if prefix else part.replace("[]", "")
        out.append(prefix)
        for _ in range(part.count("[]")):
            prefix += "[]"
            out.append(prefix)
    return out[::-1]


def dated_by_description(path):
    """The version the description of the field, or of the nearest field around it, opens with ("1.5.0 (ADR-0014): ..."), else None."""
    for level in levels(path):
        node = schema_node(level) or {}   # a path not in the schema is the existence test's to report
        found = VERSION_OPENING.match(node.get("description", ""))
        if found:
            return found.group(1)
    return None


def clause_token(path):
    """The word the clauses of the opening description use for this field: its own name, or `score` for a part of the score."""
    parts = path.split(".")
    head = parts[0].replace("[]", "")
    return parts[1].replace("[]", "") if head in ("faults", "diagnostics", "phrasing") and len(parts) > 1 else head


def named(token, text):
    return re.search(rf"(?<!\w){re.escape(token)}(?!\w)", text) is not None


@pytest.mark.parametrize("path", BY_PATH)
def test_since_is_the_version_the_schema_description_opens_with(path):
    expected = dated_by_description(path)
    if expected:
        assert BY_PATH[path]["since"] == expected, f"{path}: the schema says {expected}"


@pytest.mark.parametrize("path", [p for p, f in BY_PATH.items() if f["since"] in CLAUSES and not dated_by_description(p)])
def test_a_field_of_1_1_0_to_1_3_0_is_in_the_clause_the_schema_lists_that_version_s_additions_in(path):
    since = BY_PATH[path]["since"]
    assert named(clause_token(path), CLAUSES[since]), f"{path} is not among the {since} additions in the schema"


@pytest.mark.parametrize("path", [p for p, f in BY_PATH.items() if f["since"] == "1.0.0" and p != "faults[]"])
def test_a_field_of_1_0_0_is_in_none_of_the_clauses_that_list_later_additions(path):
    leaf = path.split(".")[-1].replace("[]", "")
    assert not [v for v, clause in CLAUSES.items() if named(leaf, clause)], f"{path} is listed as an addition"


def test_every_field_from_1_4_0_is_dated_by_the_schema_or_by_the_score_timeline_row_of_docs_schemas_md():
    undated = {p for p, f in BY_PATH.items() if version_of(f["since"]) >= (1, 4, 0) and not dated_by_description(p)}
    assert undated and all(p == "score.basis" or p.startswith("score.timeline") for p in undated), sorted(undated)
    assert {BY_PATH[p]["since"] for p in undated} == {"1.5.0"}


@pytest.mark.skipif(not (ROOT / "docs/schemas.md").is_file(), reason="docs/schemas.md is not in this tree")
def test_docs_schemas_md_lists_the_score_basis_and_timeline_under_1_5_0():
    row = re.search(r"^\| `1\.5\.0` \| (.*?) \|", (ROOT / "docs/schemas.md").read_text(), re.M).group(1)
    assert "score.basis" in row and "timeline" in row


# ---------------------------------------------------------------- since agrees with the committed documents
ALWAYS = ("always", "per_fault", "when_compared")


def test_a_golden_at_each_version_holds_a_path_exactly_from_its_since():
    """as_version() takes out what a later version added; a path in the file that a golden holds appears in its
    version-derived document exactly when the version is its `since` or later."""
    for path in BY_PATH:
        if not any(holds(paths, path) for paths in CURRENT.values()):
            continue   # no committed example holds it (a foot fault, a warning): the other tests date it
        for version in VERSIONS:
            derived = any(holds(DERIVED[name, version], path) for name in GOLDENS)
            assert derived == known_before(path, version), f"{path} at {version}: since {BY_PATH[path]['since']}"


def test_the_1_1_0_example_holds_no_path_from_a_later_version_and_every_always_written_path_of_1_1_0():
    paths = doc_paths(OLD_1_1_0)
    assert OLD_1_1_0["schema_version"] == "1.1.0"
    for path, entry in BY_PATH.items():
        if holds(paths, path):
            assert known_before(path, "1.1.0"), f"{path} is in a 1.1.0 document but its since is {entry['since']}"
        elif entry["presence"] in ("always", "per_fault"):
            assert not known_before(path, "1.1.0"), f"{path} is written from {entry['since']} but a 1.1.0 document lacks it"


def test_part7s_own_1_4_0_no_person_document_holds_no_path_from_a_later_version():
    paths = doc_paths(PART7_NO_PERSON)
    assert PART7_NO_PERSON["schema_version"] == "1.4.0"
    held = {p for p in BY_PATH if holds(paths, p)}
    assert {"schema_version", "status", "status.code", "warnings", "warnings[].code", "score", "score.version", "score.value",
            "score.grade"} <= held
    assert all(known_before(p, "1.4.0") for p in held), sorted(p for p in held if not known_before(p, "1.4.0"))


@pytest.mark.parametrize("name", GOLDENS)
def test_a_golden_holds_every_path_the_file_says_is_always_written(name):
    doc = GOLDENS[name]
    for path, entry in BY_PATH.items():
        if entry["presence"] in ALWAYS:
            assert written(doc, path), f"{name} lacks {path} ({entry['presence']})"


# ---------------------------------------------------------------- the statements the file makes
def test_the_side_convention_is_the_performers_own_and_every_side_field_says_so():
    text = HISTORY["side_convention"]["subject_own"]
    assert "performer's own" in text and "never the image's" in text and "do not depend on the camera angle" in text
    assert "subject's own" in schema_node("faults[].side")["description"]
    sided = {p for p, f in BY_PATH.items() if f["side_convention"]}
    assert set(SIDE_FIELDS) <= sided and {p for p in BY_PATH if p.endswith(".side")} <= sided
    assert not {p for p, f in BY_PATH.items() if f["units"] == "degrees"} & sided   # a size has no side of its own
    assert set(HISTORY["side_convention"]) == {"subject_own", "both", "center", "sources"}


def test_the_measures_block_is_the_schemas_measure_enum_with_the_foot_measures_from_1_6_0():
    listed = HISTORY["measures"]["list"]
    assert set(listed) == set(schema_node("faults[].measure")["enum"])
    assert {m for m, spec in listed.items() if spec["kind"] == "angle"} == {"elbow_flexion", "knee_flexion"}
    assert set(schema_node("faults[].measure_kind")["enum"]) == {"angle", "direction"}
    assert {m for m, spec in listed.items() if spec["since"] == "1.6.0"} == {"foot_rotation", "ankle_inversion"}
    assert {spec["body_part"] for spec in listed.values()} == set(schema_node("faults[].body_part")["enum"])
    assert all(spec["more"] and spec["less"] for spec in listed.values())
    assert HISTORY["measures"]["units"].startswith("degrees for every measure")
    assert schema_node("faults[].unit")["const"] == "degrees" and BY_PATH["faults[].unit"]["units"] == "none"
    assert BY_PATH["faults[].magnitude_deg"]["units"] == BY_PATH["faults[].peak_deg"]["units"] == "degrees"
    assert [p for p, f in BY_PATH.items() if f["units"] == "metres"] == ["faults[].lateral_m"]


def test_the_sign_of_a_fault_matches_its_direction_in_every_golden():
    for doc in GOLDENS.values():
        for fault in doc["faults"]:
            assert (fault["magnitude_deg"] > 0) == (fault["direction"] == "more"), fault["measure"]
            assert fault["unit"] == "degrees" and fault["threshold_deg"] > 0


def adr_exists(adr):
    """An ADR named by the file is in the workspace's docs/adr or in the published design copy, docs/design/adr (the publish
    tree carries only the copy, docs/specs/simon-publish.md)."""
    return any(list((ROOT / folder).glob(f"{adr}-*.md")) for folder in ("docs/adr", "docs/design/adr"))


def test_the_score_versions_are_the_schemas_with_the_adrs_that_ruled_them():
    versions = HISTORY["score_versions"]["versions"]
    assert list(versions) == schema_node("score.version")["enum"]
    assert versions["simon.score.v1"]["adr"] == ["ADR-0007"] and versions["simon.score.v2"]["adr"] == ["ADR-0018"]
    assert versions["simon.score.v3"]["adr"] == ["ADR-0019", "ADR-0018"]
    for adr in ("ADR-0007", "ADR-0018", "ADR-0019"):
        assert adr_exists(adr), adr
    assert versions["simon.score.v1"]["fault_cap"] == "none" and "89" in versions["simon.score.v2"]["fault_cap"]
    assert "89" in versions["simon.score.v3"]["fault_cap"] and "79" in versions["simon.score.v3"]["fault_cap"]
    assert "Nothing is renamed or rescaled by a score version" in HISTORY["score_versions"]["the_score_only"]
    assert "never assume 89" in SCHEMA["description"] and "never assume 89" in versions["simon.score.v3"]["fault_cap"]


@v3_only
def test_the_ceilings_the_file_states_are_the_ones_in_the_rules_the_tree_ships():
    block = json.loads((ROOT / "part5/rules.json").read_text())["score"]
    assert (block["fault_cap"], block["fault_cap_many"], block["many_faults"]) == (89, 79, 2)
    assert block["v2"]["fault_cap"] == 89 and "fault_cap" not in block["v1"]
    assert [[floor, letter] for floor, letter in block["bands"]] == [[90, "A"], [80, "B"], [70, "C"], [60, "D"], [0, "F"]]
    grade = BY_PATH["score.grade"]["meaning"]
    assert all(band in grade for band in ("A 90 and above", "B 80 to 89", "C 70 to 79", "D 60 to 69", "F below 60"))
    assert "two or more" in HISTORY["score_versions"]["versions"]["simon.score.v3"]["rule"]


def test_what_a_missing_thing_means_is_stated_for_each_case_the_ticket_names():
    absent = HISTORY["absent_means"]
    assert {"fault", "tempo", "measure", "near_misses"} <= set(absent)
    assert "not compared" in absent["fault"] and "diagnostics.visibility.excluded" in absent["fault"]
    assert "diagnostics.feet.compared" in absent["fault"] and "diagnostics.near_misses" in absent["fault"]
    assert "not measured" in absent["tempo"] and "TICKET-063" in absent["tempo"] and "never on time" in absent["tempo"]
    assert "neither flagged nor proven fine" in absent["measure"]
    assert "considered and dropped" in absent["near_misses"] and "not a list of faults" in absent["near_misses"]
    ratio = schema_node("score.tempo.ratio")
    assert ratio["type"] == ["number", "null"] and "null when the example side spans under 1 s" in schema_node("score.tempo")["description"]
    assert "capped_by" in absent["score_fields"] and "fault_cap" in absent["score_fields"]


def test_detection_changes_that_no_version_marks_are_listed_with_their_dates():
    changes = HISTORY["detection_changes_without_a_version"]
    assert [c["when"] for c in changes] == ["2026-10-31", "2026-11-01", "2026-11-01"]
    assert "trunk_lean_side" in changes[0]["what"] and "ADR-0017" in changes[0]["what"]
    assert "ADR-0015 Amendment 4" in changes[1]["what"] and "TICKET-063" in changes[2]["what"]
    for adr in ("ADR-0014", "ADR-0015", "ADR-0017"):
        assert adr_exists(adr), adr


def paragraph(text, opening):
    """The paragraph of `text` that starts with `opening` (the history section is written in bold-led paragraphs)."""
    start = text.index(opening)
    end = text.find("\n\n", start)
    return text[start:end if end != -1 else len(text)]


def history_section():
    text = (ROOT / "CONTRACT.md").read_text()
    return text[text.index("## History across takes"):text.index("## What Part 5 accepts")]


def test_a_tempo_insights_points_equal_the_dance_components_tempo_and_are_null_under_the_other_profiles():
    """TICKET-074 R2: part5/insights.py sets a tempo item's points to score.components.tempo, which only the dance profile
    writes (ADR-0016), so "null for a tempo item" was wrong under dance."""
    notes = BY_PATH["insights[].points"]["notes"]
    assert "Null for a tempo item outside the dance profile" in notes and "score.components.tempo" in notes
    assert "ADR-0016" in notes and "under dance it equals" in notes and "take without a timeline" in notes
    assert "Null for a tempo item and" not in notes
    assert "components.tempo arrived in 1.7.0 and only under dance" in BY_PATH["score.components"]["notes"]   # the claim's source


def test_the_attempt_4_entry_says_the_schema_stayed_1_8_0_and_that_1_9_0_came_later_the_same_day():
    """TICKET-074 R3: attempt 4 merged (a716ce1, 2026-10-31 18:57) while the schema was 1.8.0; 1.9.0 landed at 21:25."""
    attempt_4 = HISTORY["detection_changes_without_a_version"][0]
    assert attempt_4["when"] == "2026-10-31" and "Attempt 4" in attempt_4["what"]
    assert "schema_version stayed 1.8.0" in attempt_4["marked_by"] and "1.9.0 came later the same day" in attempt_4["marked_by"]
    assert "stayed 1.9.0" not in attempt_4["marked_by"] and "from 1.9.0 on has it" in attempt_4["marked_by"]


def test_the_score_change_of_adr_0013_that_no_version_marked_is_listed_with_the_two_fields_it_introduced():
    """TICKET-074 R4: a simon.score.v1 take became the mean of its windows on 2026-10-30 (05312b7) with no new score.version,
    params_sha256 or schema_version, and score.basis and score.timeline were written under 1.4.0 until d3250dc made it 1.5.0."""
    (change,) = HISTORY["score_changes_without_a_version"]
    assert change["when"] == "2026-10-30" and adr_exists("ADR-0013")
    for needle in ("ADR-0013", "05312b7", "simon.score.v1", "mean of its windows", "score.basis", "score.timeline", "77"):
        assert needle in change["what"], needle
    for needle in ("Nothing at the time", "score.version stayed simon.score.v1", "score.params_sha256 did not change",
                   "schema_version was not changed", "1.2.0, 1.3.0 or 1.4.0 by the content", "d3250dc", "1.5.0"):
        assert needle in change["marked_by"], needle
    for path in ("score.basis", "score.timeline"):
        assert BY_PATH[path]["since"] == "1.5.0" and "score_changes_without_a_version" in BY_PATH[path]["notes"]
        assert "1.2.0, 1.3.0 or 1.4.0 document (by content) written after 05312b7" in BY_PATH[path]["notes"]
    section = history_section()
    assert "`score_changes_without_a_version`" in section and "ADR-0013" in paragraph(section, "**Score v1 to v3.**")


def test_a_measure_is_fine_only_when_status_code_is_ok_in_the_file_and_in_contract_md():
    """TICKET-074 R6: a refusal from before 1.4.0 has faults [] and no warnings, yet nothing was compared."""
    measure = HISTORY["absent_means"]["measure"]
    assert "fine only when status.code is ok" in measure and "before 1.4.0 has faults [] and no warnings" in measure
    assert measure.index("status.code is ok") < measure.index("the take has no warnings")
    absent = paragraph(history_section(), "**An absent measure.**")
    assert "only when `status.code` is `ok`" in absent and "before `1.4.0`" in absent and "nothing was compared" in absent
    assert absent.index("`status.code` is `ok`") < absent.index("the take has no `warnings`")


def test_the_fields_left_out_are_named_with_the_reason_and_none_is_also_listed():
    left_out = {n["path"] for n in HISTORY["not_listed"]}
    assert {"faults[].expected_frames", "faults[].follower_frames", "phrasing", "second_opinion", "source"} <= left_out
    assert not left_out & set(BY_PATH)
    assert schema_node("faults[].expected_frames") is not None and schema_node("second_opinion") is not None


# ---------------------------------------------------------------- the contract says it, in words with no dash
DASHES = (chr(0x2014), chr(0x2013), " " + chr(0x2d) + " ")   # an em dash, an en dash, a spaced hyphen


def test_the_file_and_the_history_section_of_contract_md_use_no_dash():
    text = (ROOT / "CONTRACT.md").read_text()
    section = text[text.index("## History across takes"):text.index("## What Part 5 accepts")]
    for name, body in (("history-fields.json", TEXT), ("CONTRACT.md history section", section)):
        assert not [d for d in DASHES if d in body], name
        assert len(body) > 1000, "control: the search runs on the whole text"


def test_contract_md_points_at_the_file_and_answers_the_four_questions():
    text = (ROOT / "CONTRACT.md").read_text()
    section = text[text.index("## History across takes"):text.index("## What Part 5 accepts")]
    for needle in ("`contracts/history-fields.json`", "`simon.part5.history-fields.v1`", "`tests/test_contract_history_fields.py`",
                   "`part5 contract --json`", "`history_fields`", "**Units, and which way is worse.**", "**Side.**",
                   "**Score v1 to v3.**", "**An absent measure.**", "never the image's", "performer's own", "degrees",
                   "divide by `threshold_deg`", "compare `score.value` only within one `score.version`", "No measure is renamed or rescaled",
                   "TICKET-063", "never on time", "`diagnostics.near_misses`", "`diagnostics.visibility.excluded`",
                   "`diagnostics.feet.compared`"):
        assert needle in section, needle
    assert "contracts/history-fields.json" in text[:text.index("## History across takes")], "named under Schemas and Check a file now"
    assert "(History across takes, below)" in text


@pytest.mark.skipif(not (ROOT / "docs/specs/integration-contract.md").is_file(), reason="docs/specs is a workspace directory")
def test_the_spec_names_the_file_and_this_test():
    spec = (ROOT / "docs/specs/integration-contract.md").read_text()
    ac = spec[spec.index("### AC-C19"):spec.index("### AC-C10")]
    assert "contracts/history-fields.json" in ac and "tests/test_contract_history_fields.py" in ac
    assert "tests/test_contract_cli.py" in ac and "`history_fields`" in ac
