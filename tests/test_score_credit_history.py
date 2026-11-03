"""TICKET-078: `contracts/history-fields.json` 1.2.0 covers every `score.credit` path (ADR-0020), and this file pins it.

tests/test_contract_history_fields.py pins each listed path against the schema and the committed goldens, but it never says
which paths a new schema version must list. The other half is here for 1.13.0, the way `ADDED_IN_1_12_0` is there for 1.12.0:
the keys of `score.credit` are the ones pinned below, each key is listed from 1.13.0, and every path a committed golden holds
under `score.credit` is either listed or lies inside a listed container (`levels`, `per_window[]`, `bands`, `grades`) whose
meaning names every field on the way down. CONTRACT.md says `score.credit` is reported only, and names the credit's own grade
scale (`grades`: the team's S 95, A 85, B 75, C 65, D 55, E 40, F under 40; the team's 8f135ee, E and F moved in 93a95db).

Like the files it sits beside, it reads the files and imports nothing from `part5`."""
import copy
import re
from pathlib import Path

import jsonschema
import pytest

from test_contract_history_fields import BY_PATH, HISTORY, doc_paths, named, schema_node
from test_contract_part7_history import GOLDENS, SCHEMA

ROOT = Path(__file__).resolve().parent.parent
CREDIT_KEYS = ("version", "percent", "grade", "points", "max_points", "tolerance", "levels", "bands",
               "points_per_measure_second", "per_window", "grades")
# The paths the file lists for the credit: the block, each of its keys, and the per-window entry (an array lists as `[]`).
CREDIT_PATHS = {"score.credit", *(f"score.credit.{k}" for k in CREDIT_KEYS if k != "per_window"), "score.credit.per_window[]"}
CONTRACT_MD = (ROOT / "CONTRACT.md").read_text(encoding="utf-8")


def credit_paths(doc):
    return {p for p in doc_paths(doc) if p == "score.credit" or p.startswith("score.credit.")}


def covering(path):
    """The listed path that holds `path`: itself, else the nearest listed path around it; None when there is none."""
    while path:
        if path in BY_PATH:
            return path
        path = path[:-2] if path.endswith("[]") else path.rpartition(".")[0]
    return None


def test_the_schema_holds_exactly_the_credit_keys_pinned_here():
    """A new key of `score.credit` fails here until it is listed in the history file and added to CREDIT_KEYS."""
    assert set(schema_node("score.credit")["properties"]) == set(CREDIT_KEYS)


def test_the_file_lists_the_block_and_each_of_its_keys_from_1_13_0_and_no_other_path_claims_that_version():
    assert CREDIT_PATHS <= set(BY_PATH), sorted(CREDIT_PATHS.difference(BY_PATH))
    # the quality block (TICKET-079, tests/test_quality_history.py) ships in 1.13.0 too, so its paths may be dated 1.13.0 as well
    assert {p for p, f in BY_PATH.items() if f["since"] == "1.13.0" and p != "quality" and not p.startswith("quality.")} == CREDIT_PATHS
    assert len(CREDIT_PATHS) == 12
    assert HISTORY["version"] == "1.3.0" and HISTORY["analysis_schema_version"] == "1.14.0" == SCHEMA["version"]


@pytest.mark.parametrize("path", sorted(CREDIT_PATHS - {"score.credit"}))
def test_a_credit_key_is_conditional_on_the_block_and_additive(path):
    entry = BY_PATH[path]
    assert entry["presence"] == "conditional" and "score.credit is not null" in entry["present_when"]
    assert entry["stability"] == "additive"


def test_the_block_itself_is_always_present_and_may_be_null():
    entry = BY_PATH["score.credit"]
    assert entry["presence"] == "always" and "Null when nothing was compared" in entry["notes"]


@pytest.mark.parametrize("name", GOLDENS)
def test_every_credit_path_of_a_golden_is_listed_or_named_by_the_listed_container_around_it(name):
    paths = credit_paths(GOLDENS[name])
    assert {"score.credit.version", "score.credit.levels.hard.max_points", "score.credit.per_window[].t_s"} <= paths
    for path in sorted(paths):
        holder = covering(path)
        assert holder, f"{path} is neither listed in contracts/history-fields.json nor inside a listed path"
        for key in re.findall(r"\.([A-Za-z_0-9]+)", path[len(holder):]):
            assert named(key, BY_PATH[holder]["meaning"]), f"{path}: the meaning of {holder} does not name {key}"


def test_the_goldens_hold_every_listed_credit_key():
    held = set().union(*(credit_paths(doc) for doc in GOLDENS.values()))
    for path in CREDIT_PATHS:
        assert path.replace("[]", "") in held, f"no committed golden holds {path}"


def test_the_history_file_and_contract_md_say_the_credit_is_reported_only():
    notes = BY_PATH["score.credit"]["notes"]
    assert "score.value, score.grade and the caps do not read it" in notes and "read warnings first" in notes
    assert "Reported only" in BY_PATH["score.credit.percent"]["notes"]
    paragraph = re.search(r"^\*\*Score credit \(1\.13\.0\)\.\*\*.*$", CONTRACT_MD, re.M).group(0)
    assert "It is reported only" in paragraph
    assert "no grade of the score, no cap and no gate" in paragraph
    assert "the warning cap of 59 does not apply to it" in paragraph
    assert "`score.value` and `score.grade` never read it" in paragraph


def test_the_credit_grade_entry_is_not_the_scores_grade():
    assert "Not the score's grade" in BY_PATH["score.credit.grade"]["notes"]
    assert BY_PATH["score.credit.grade"]["direction"] == BY_PATH["score.grade"]["direction"] == "later_letter_is_worse"


def test_the_credit_grade_is_called_informational_wherever_it_is_described():
    """Review B1 of TICKET-078: the grade stays, and every place that describes it says it is informational."""
    assert BY_PATH["score.credit.grade"]["notes"].startswith("Informational.")
    assert "ignores warnings and caps" in BY_PATH["score.credit.grade"]["notes"]
    assert schema_node("score.credit.grade")["description"].startswith("Informational:")
    assert "`score.credit.grade` is informational" in CONTRACT_MD
    schemas_md = (ROOT / "docs/schemas.md").read_text(encoding="utf-8")
    assert "It is informational: it is not `score.grade`" in schemas_md
    # the published design copy: docs/adr/ is a workspace directory, not in a published tree (review B1 of 1.13.0)
    adr = (ROOT / "docs/design/adr/ADR-0020-score-credit-ddr-display.md").read_text(encoding="utf-8")
    assert "## Part 5 review (TICKET-078)" in adr and "The credit's grade stays and is informational" in adr


# The team's game scale for the credit's letters (the team's 8f135ee, moalborati/simon#61 issuecomment-6569445776; E and F
# moved in the team's 93a95db, issuecomment-6596716382), as text.
GRADE_SCALE = [[95, "S"], [85, "A"], [75, "B"], [65, "C"], [55, "D"], [40, "E"], [0, "F"]]


def test_the_history_file_lists_the_grades_and_names_the_credits_own_scale():
    """`score.credit.grades` is listed with the scale every golden carries; the grade's meaning reads its letters off it, and
    the direction that ranks letters says S is the credit's best, not the alphabet's last."""
    meaning = BY_PATH["score.credit.grades"]["meaning"]
    assert all(doc["score"]["credit"]["grades"] == GRADE_SCALE for doc in GOLDENS.values())
    assert '[[95, "S"], [85, "A"], [75, "B"], [65, "C"], [55, "D"], [40, "E"], [0, "F"]]' in meaning
    assert "not the score's bands" in BY_PATH["score.credit.grades"]["notes"]
    grade = BY_PATH["score.credit.grade"]["meaning"]
    assert all(band in grade for band in ("S 95 and above", "A 85 to 94.9", "B 75 to 84.9", "E 40 to 54.9", "F below 40"))
    assert "under the score's bands" not in grade
    assert "S, A, B, C, D, E, F for score.credit.grade (S is best" in HISTORY["how_to_read"]["direction_values"][
        "later_letter_is_worse"]


def test_the_grades_enum_is_the_scales_letters_in_the_grade_and_in_each_grades_entry():
    credit = schema_node("score.credit")["properties"]
    letters = [letter for _, letter in GRADE_SCALE]
    assert credit["grade"]["enum"] == letters == credit["grades"]["items"]["prefixItems"][1]["enum"]
    assert "grades" in schema_node("score.credit")["required"]
    assert credit["grade"]["description"].startswith("Informational:") and "grades" in credit["grade"]["description"]


def test_every_letter_field_carries_its_order_and_the_order_is_the_schemas_enum():
    """Review R3 of 1.13.0: `later_letter_is_worse` covers two letter orders, A to F and S to F, and a reader ranking letters
    by the alphabet would put S last. Each letter field names its own order, best first, and it is the schema's enum."""
    lettered = [f for f in HISTORY["fields"] if f["direction"] == "later_letter_is_worse" or "order" in f]
    assert {"score.grade", "score.credit.grade", "score.credit.grades"} <= {f["path"] for f in lettered}
    for field in lettered:
        node = schema_node(field["path"])
        enum = node["items"]["prefixItems"][1]["enum"] if node.get("type") == "array" else node["enum"]
        assert field["order"] == enum, field["path"]
    assert BY_PATH["score.grade"]["order"] == ["A", "B", "C", "D", "F"]
    assert BY_PATH["score.credit.grade"]["order"] == BY_PATH["score.credit.grades"]["order"] == [g for _, g in GRADE_SCALE]
    assert sorted(BY_PATH["score.credit.grade"]["order"]) != BY_PATH["score.credit.grade"]["order"]   # not the alphabet's
    assert "order" in HISTORY["how_to_read"]["entry_keys"]
    assert "rank by it, never by the alphabet" in HISTORY["how_to_read"]["direction_values"]["later_letter_is_worse"]
    assert "carries `order`" in CONTRACT_MD and "never by the alphabet" in CONTRACT_MD


def test_contract_md_names_the_credits_own_grade_scale():
    paragraph = re.search(r"^\*\*Score credit \(1\.13\.0\)\.\*\*.*$", CONTRACT_MD, re.M).group(0)
    assert "S 95, A 85, B 75, C 65, D 55, E 40, and F under 40" in paragraph
    assert "`.grades`" in paragraph and "never `score.grade`, whose bands stay A to F" in paragraph


def test_the_credit_entry_is_defined_once_and_the_levels_and_per_window_use_it():
    """Review B5: the three levels and the per-window items were one block written four times; now `$defs.credit_entry`."""
    ref = {"$ref": "#/$defs/credit_entry"}
    credit = schema_node("score.credit")["properties"]
    assert SCHEMA["$defs"]["credit_entry"]["required"] == ["percent", "points", "max_points"]
    assert [credit["levels"]["properties"][level] for level in ("easy", "normal", "hard")] == [ref, ref, ref]
    assert credit["per_window"]["items"]["allOf"] == [ref] and credit["per_window"]["items"]["required"] == ["t_s"]
    assert credit["levels"]["required"] == ["easy", "normal", "hard"]


@pytest.mark.parametrize("where", ["levels.easy.points", "levels.normal.max_points", "levels.hard.percent",
                                   "per_window.0.points", "per_window.0.max_points", "per_window.0.percent", "per_window.0.t_s"])
def test_a_level_or_a_window_missing_a_number_is_still_refused_through_the_shared_definition(where):
    doc = copy.deepcopy(GOLDENS["double-fault"])
    node = doc["score"]["credit"]
    *path, leaf = where.split(".")
    for key in path:
        node = node[int(key)] if key.isdigit() else node[key]
    del node[leaf]
    assert list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(doc)), where
