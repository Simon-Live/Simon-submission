"""AC-SV09 (docs/specs/scoring-validity.md, TICKET-082; review B3 of 1.13.0): every figure in the tables of sections 1 and 2
of docs/evaluation.md is one `make bench-score` wrote to docs/evaluation/ (`first_fire.summary.json`, the dose-response
tables; `invariance.summary.json`, the invariance table), and those summaries are of the score this tree ships.

The tables are rendered from the summaries the way the doc writes a figure (one decimal at most, `7.5 to 15` for a range,
`A or B` for the grades) and compared cell by cell, both ways: a row the summary has and the doc lacks fails, and so does
a doc row the summary does not have. The section 3 table lists the properties of tests/test_score_properties.py, whose
figures are that file's parameters, not a bench output. The run itself is pinned by tests/test_score_validity.py; here the
committed take's first fires are recomputed (the rows that file caches) so a summary that no longer matches the pipeline
fails too.
"""
import inspect
import json
import re
import sys
from pathlib import Path

import pytest

from part5 import normalise

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_bench_score as bench  # noqa: E402
import make_score_validity as sv  # noqa: E402
from test_score_validity import TAKE_ID, committed_rows, reduced  # noqa: E402,F401  (`reduced` is a fixture)

DOC = ROOT / "docs" / "evaluation.md"
SUMMARIES = ROOT / "docs" / "evaluation"


def load(name):
    return json.loads((SUMMARIES / name).read_text())


def tables(text):
    """`{section heading: [table]}`; a table is its rows, each a list of cells, the header first, the `---` row left out."""
    out, section, table = {}, None, None
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        if not line.startswith("|"):
            table = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if table is None:
            table = []
            out.setdefault(section, []).append(table)
        if not all(re.fullmatch(r":?-+:?", c) for c in cells):
            table.append(cells)
    return out


def num(x):
    """A figure as the doc writes it: at most one decimal, no trailing zero (`10`, `7.5`, `93.2`)."""
    return f"{round(x, 1):g}"


def letters(grades):
    return grades[0] if len(grades) == 1 else ", ".join(grades[:-1]) + " or " + grades[-1]


def first_fire_cell(s):
    return "never" if s["median_low"] is None else f"{num(s['median_low'])} degrees ({num(s['min'])} to {num(s['max'])})"


def score_cell_matches(cell, c):
    """`93.2 (85 to 100) A or B`; the range may be left out only where every take scored the same."""
    m = re.fullmatch(r"(?P<mean>[\d.]+)(?: \((?P<lo>[\d.]+) to (?P<hi>[\d.]+)\))? (?P<grades>.+)", cell)
    if not m or m["mean"] != num(c["mean"]) or m["grades"] != letters(c["grades"]):
        return False
    return (m["lo"], m["hi"]) == (num(c["min"]), num(c["max"])) if m["lo"] else c["min"] == c["max"]


def group_of(cell):
    """The summary's group of a doc row: the words before a closing parenthesis; `all` and `all with a lead-in` are the
    group every take is in (`trim_lead_in` runs on the takes that have a lead-in only)."""
    text = re.sub(r"\s*\([^)]*\)$", "", cell)
    return "all takes" if text == "all" or text.startswith("all ") else text


def invariance_cells(e):
    """The cells after Transform and Group, as the doc writes them; a group every take of which was refused reads n/a."""
    if e["refused"] == e["takes"]:
        return [str(e["takes"]), str(e["refused"]), "n/a", "n/a", "n/a", "n/a", e["verdict"]]
    spread = str(e["min_delta"]) if e["min_delta"] == e["max_delta"] else f"{e['min_delta']} to {e['max_delta']}"
    return [str(e["takes"]), str(e["refused"]), str(e["value_changed"]), str(e["max_abs_delta"]), spread,
            str(e["fault_set_changed"]), e["verdict"]]


@pytest.fixture(scope="module")
def doc_tables():
    found = tables(DOC.read_text())
    dose = next(v for k, v in found.items() if k.startswith("1."))
    invariance = next(v for k, v in found.items() if k.startswith("2."))
    assert len(dose) == 2 and len(invariance) == 1, "a new table in sections 1 or 2 needs its figures checked here"
    return {"dose": dose[0], "per_take": dose[1], "invariance": invariance[0]}


def test_the_summaries_are_of_the_score_and_the_takes_this_tree_ships():
    first, inv = load(bench.FIRST_FIRE_SUMMARY), load(bench.INVARIANCE_SUMMARY)
    assert first["format"] == inv["format"] == bench.SUMMARY_FORMAT and first["seed"] == inv["seed"] == sv.SEED == 5
    assert first["score"] == inv["score"] == bench.score_of(), "the score changed: run `uv run make bench-score`"
    assert first["grid_deg"] == sv.GRID and first["takes"] == [t["take_id"] for t in sv.correct_exercise(sv.pool())]
    assert (first["of"], inv["of"]) == ("dose_response.first_fire", "invariance.summary")
    assert "sha" not in first and "sha" not in inv   # no commit in them, so a later run changes them only when a figure moves


def test_the_committed_takes_first_fires_and_scores_are_what_the_pipeline_gives_now():
    first = load(bench.FIRST_FIRE_SUMMARY)
    now = sv.first_fire(list(committed_rows()))
    assert {j: now[j][TAKE_ID]["first"] for j in now} == {j: first["per_take"][j][TAKE_ID]["first"] for j in sv.PLANTED}
    for r in committed_rows():
        if r["planted_deg"] in bench.SCORE_AT:
            cell = first["score_at"][r["joint"]][f"{r['planted_deg']:g}"]
            assert cell["min"] <= r["value"] <= cell["max"] and r["grade"] in cell["grades"], (r["joint"], r["planted_deg"])


def test_the_dose_response_table_is_the_first_fire_summary(doc_tables):
    first = load(bench.FIRST_FIRE_SUMMARY)
    header, *rows = doc_tables["dose"]
    assert f"of {len(first['takes'])} takes" in header[2]
    assert [int(re.search(r"\d+$", h).group()) for h in header[3:]] == list(bench.SCORE_AT)
    assert [r[0] for r in rows] == list(first["summary"]) == list(sv.PLANTED)
    for joint, _, fire, *scores in rows:
        assert fire == first_fire_cell(first["summary"][joint]), joint
        for deg, cell in zip(bench.SCORE_AT, scores):
            assert score_cell_matches(cell, first["score_at"][joint][str(deg)]), (joint, deg, cell)


def test_the_first_fire_per_take_table_is_the_summarys_per_take(doc_tables):
    first = load(bench.FIRST_FIRE_SUMMARY)
    header, *rows = doc_tables["per_take"]
    takes = [f"exercise_{angle}_good_{n}_correct" for angle, n in (h.split() for h in header[1:])]
    assert sorted(takes) == sorted(first["takes"])
    assert [r[0] for r in rows] == list(sv.PLANTED)
    for joint, *cells in rows:
        fires = [first["per_take"][joint][t]["first"] for t in takes]
        assert cells == ["never" if f is None else num(f) for f in fires], joint


def test_the_invariance_table_is_the_invariance_summary(doc_tables):
    summary = load(bench.INVARIANCE_SUMMARY)["summary"]
    header, *rows = doc_tables["invariance"]
    assert header[2:] == ["Takes", "Refused", "Score changed", "Largest change", "Range", "Fault set changed", "Verdict"]
    by_key = {(e["transform"], e["group"]): e for e in summary}
    seen = []
    for transform, group, *cells in rows:
        key = (re.match(r"`([^`]+)`", transform).group(1), group_of(group))
        assert key in by_key, f"the doc row {transform} | {group} is not in the summary"
        cells[-1] = re.sub(r"\s*\([^)]*\)$", "", cells[-1])   # `refused (`InputError`)` reads as its verdict
        assert cells == invariance_cells(by_key[key]), key
        seen.append(key)
    assert sorted(seen) == sorted(by_key), "every row of the summary is in the doc's table, once"


def test_the_bench_writes_both_summaries_beside_the_chart_copy_and_none_without_one(reduced, tmp_path):
    out, copy = tmp_path / "out", tmp_path / "docs" / "dose-response.svg"
    assert bench.main(["--out", str(out), "--chart-copy", str(copy)]) == 0
    first, inv = (json.loads((copy.parent / n).read_text()) for n in (bench.FIRST_FIRE_SUMMARY, bench.INVARIANCE_SUMMARY))
    m = json.loads((out / "metrics.json").read_text())
    assert first["summary"] == m["dose_response"]["first_fire"]["summary"] and first["per_take"] == m["dose_response"]["first_fire"]["takes"]
    assert inv["summary"] == m["invariance"]["summary"] and first["score"] == m["score"]
    assert set(first["score_at"]["trunk"]) == {"0", "30"}   # the reduced grid is 0, 15 and 30: the steps of SCORE_AT on it
    before = {n: (copy.parent / n).read_bytes() for n in (bench.FIRST_FIRE_SUMMARY, bench.INVARIANCE_SUMMARY)}
    assert bench.main(["--out", str(out), "--chart-copy", str(copy)]) == 0
    assert before == {n: (copy.parent / n).read_bytes() for n in before}   # the same tree writes the same bytes
    bare = tmp_path / "bare"
    assert bench.main(["--out", str(bare / "out"), "--chart-copy", ""]) == 0
    assert sorted(p.name for p in bare.rglob("*")) == ["dose-response.svg", "metrics.json", "out"]
    assert first["figures"] == bench.dose_figures(m["dose_response"]["rows"])     # TICKET-088 N2: the prose figures
    assert inv["figures"] == bench.invariance_figures(m["invariance"]["rows"], m["invariance"]["summary"])


# ---------------------------------------------------------------------------------------------- the prose (TICKET-088 N2)
WORDS = {6: "Six"}


def prose(prefix):
    """The text of the section whose heading starts with `prefix`, its tables left out, whitespace collapsed to one space."""
    text = DOC.read_text()
    start = text.index(f"\n## {prefix}")
    end = text.find("\n## ", start + 1)
    lines = [line for line in text[start:end if end >= 0 else None].splitlines() if not line.startswith("|")]
    return " ".join(" ".join(lines).split())


def points(n):
    return f"{n} point" if n == 1 else f"{n} points"


def test_section_1s_prose_figures_are_the_first_fire_summarys():
    """TICKET-088 N2: the figures section 1 states in words (the 116 and 196 rows, the 11 to 15 point drop, the realised gaps
    0.25 and 1.2, the second fault, the series) are read from `first_fire.summary.json`, so a later run that moves one fails
    here as a table figure would."""
    first = load(bench.FIRST_FIRE_SUMMARY)
    f, takes, text = first["figures"], first["takes"], prose("1.")
    assert f"{WORDS[len(takes)]} takes:" in text and f"{f['rows']} rows." in text and f["rows"] == len(takes) * len(sv.PLANTED) * len(sv.GRID)
    assert f"An error of 0 to {sv.GRID[-1]:g} degrees ({len(sv.GRID)} steps of {sv.GRID[1]:g})" in text
    assert f["series"] == len(takes) * len(sv.PLANTED) == f["series_never_rising"]
    assert f"All {f['series']} series ({len(sv.PLANTED)} joints, {len(takes)} takes) are non-increasing" in text
    assert all(s["never"] == 0 and s["stable"] == s["takes"] for s in first["summary"].values())
    assert f"stays on at every larger step in all {f['series']} series" in text
    without, fired = f["without_matching"], f["with_matching"]
    assert without["values"] == [100] and without["other_faults"] == 0 and without["rows"] + fired["rows"] == f["rows"]
    assert f"The {without['rows']} rows without the matching fault score exactly 100 and report no other fault" in text
    assert f"The {fired['rows']} rows with it score {fired['min']} to {fired['max']}, none an A" in text and "A" not in fired["grades"]
    drop, cost = f["first_fire_drop"], f["later_step_cost"]
    assert f"its score drops by {drop['min']} to {drop['max']} points" in text
    assert (f"each 2.5 degree step costs {cost['max']} points or fewer, except where the hip's second fault appears (up to "
            f"{cost['max_where_a_second_fault_appears']} points)") in text
    (second,) = f["second_faults"]
    assert second["joint"] == "hip"
    assert (f"The hip error brings a second fault: `{second['measure']}` {second['side']}, direction {second['direction']}, in "
            f"{second['takes']} of {len(takes)} takes, from {second['from_deg']:g} degrees") in text
    at_30 = {joint: first["score_at"][joint]["30"] for joint in sv.PLANTED}
    widest = max(at_30, key=lambda joint: at_30[joint]["max"] - at_30[joint]["min"])
    assert widest == "hip" and f"The hip's scores at 30 degrees range from {at_30['hip']['min']} to {at_30['hip']['max']}, the widest" in text
    gap = f["realised_gap_deg"]
    assert gap["hip"] == gap["trunk"]
    assert (f"differs from the planted degrees by at most {gap['knee']:g} for the knee, {gap['hip']:g} for the hip and the trunk, "
            f"and {gap['elbow']:g} for the elbow") in text


def test_the_code_figures_the_prose_quotes_are_the_shipped_ones():
    """The rule thresholds of section 1 are `part5/rules.json`'s; the 5 frames of section 2 is `normalise.smooth`'s window."""
    rules = json.loads((ROOT / "part5/rules.json").read_text())["measures"]
    assert ", ".join(f"`{m}` {rules[m]['threshold_deg']:g}" for m in ("elbow_flexion", "knee_flexion", "foot_out",
                                                                       "trunk_lean_forward")) + " degrees" in prose("1.")
    window = inspect.signature(normalise.smooth).parameters["window"].default
    assert f"`part5/normalise.py` smooths over {window} frames whatever the clip's rate" in prose("2.")


def test_section_2s_prose_figures_are_the_invariance_summarys():
    """TICKET-088 N2: the counts the bullets of section 2 state (and the two takes they name) are read from
    `invariance.summary.json`, its table rows and its `figures`."""
    doc = load(bench.INVARIANCE_SUMMARY)
    row = {(e["transform"], e["group"]): e for e in doc["summary"]}
    fig = {(e["transform"], e["group"]): e for e in doc["figures"]}
    assert list(fig) == list(row)
    text = prose("2.")
    every = row["fps_60", "all takes"]["takes"]
    assert f"{every} takes (good light, clean, numbers 00 to 08 of the exercise and dance sets" in text
    held = {key: e for key, e in row.items() if e["verdict"] == "exact"}
    for key, words in ((("mirror_both", "all takes"), "the mirror of both clips"),
                       (("mirror_follower", "symmetric example"), "the mirror of the follower against a left-right symmetric example"),
                       (("translate_5mm", "all takes"), "a translation within 1 cm")):
        assert f"{words} ({held[key]['takes']} of {held[key]['takes']})" in text, key
    s08, s125 = held["scale_0.8", "all takes"], held["scale_1.25", "all takes"]
    assert s08["takes"] == s125["takes"] and f"a uniform scale ({s08['takes']} of {s08['takes']} at 0.8 and at 1.25)" in text
    far = row["translate_0.5m", "all takes"]
    assert far["refused"] == far["takes"] and f"refused with an `InputError` in all {far['takes']}" in text

    fps, fps_fig = row["fps_60", "all takes"], fig["fps_60", "all takes"]
    change = fps_fig["only_fault_set_change"]
    assert fps["fault_set_changed"] == 1 and change["take_id"].startswith("dance_")
    assert {tuple(f) for f in change["from"]} ^ {tuple(f) for f in change["to"]} == {("upper_arm_out", "left", "more"),
                                                                                        ("upper_arm_out", "both", "more")}
    assert (f"A 60 frames per second follower moves {fps['value_changed']} of {fps['takes']} scores (largest "
            f"{fps['max_abs_delta']} points, one fault set: dance take `{change['take_id']}` reports `upper_arm_out` on the left at "
            "30 fps and on both sides at 60)") in text
    correct = fps_fig["correct"]
    assert correct["value_changed"] == 0 and f"The {fps['value_changed']} are faulted takes; the {correct['takes']} correct takes do not move" in text
    slow = row["fps_24", "all takes"]
    assert f"The 24 fps row, a non-integer ratio, moves {slow['value_changed']} takes by up to {slow['max_abs_delta']} points" in text

    long_in, long_fig = row["trim_0.5s", "lead-in at least 15 frames"], fig["trim_0.5s", "lead-in at least 15 frames"]
    only = long_fig["only_value_change"]
    assert (f"A 0.5 s trim moves {long_in['value_changed']} of the {long_in['takes']} takes whose idle lead-in is at least 15 frames, "
            f"by {points(long_in['max_abs_delta'])} (`{only['take_id']}`, {only['from']} to {only['to']})") in text
    short = row["trim_0.5s", "lead-in under 15 frames"]
    assert f"it moves {short['value_changed']} of {short['takes']} takes, up to {short['max_abs_delta']} points" in text
    lead, sets = row["trim_lead_in", "all takes"], fig["trim_lead_in", "all takes"]["by_set"]
    assert sets["exercise"]["value_changed"] == 0 and sets["dance"]["value_changed"] == lead["value_changed"]
    assert (f"it moves {lead['value_changed']} of {lead['takes']} takes (all in the dance set, {sets['dance']['value_changed']} of "
            f"{sets['dance']['takes']}; none in the exercise set, 0 of {sets['exercise']['takes']}), by up to "
            f"{lead['max_abs_delta']} points, with {lead['fault_set_changed']} fault sets changed") in text

    y5, y15, y45, both = (row[name, "all takes"] for name in ("yaw_5", "yaw_15", "yaw_45", "yaw_45_both"))
    c5, c15 = fig["yaw_5", "all takes"]["correct"], fig["yaw_15", "all takes"]["correct"]
    assert c5["value_changed"] == 0 and y45["value_changed"] == y45["takes"] and y45["max_delta"] < 0
    assert (f"At 5 degrees {y5['value_changed']} of {y5['takes']} scores move (the {c5['takes']} correct takes do not); at 15 degrees "
            f"{y15['value_changed']} of {y15['takes']} move and {c15['gained_a_fault']} of the {c15['takes']} correct takes gain a "
            f"fault; at 45 degrees all {y45['takes']} lose between {-y45['max_delta']} and {-y45['min_delta']} points") in text
    assert f"Turning the example too (`yaw_45_both`) still moves {both['value_changed']}" in text
    mirror = row["mirror_follower", "asymmetric example"]
    assert mirror["value_changed"] == mirror["takes"] and mirror["max_delta"] < 0
    assert (f"({mirror['value_changed']} of {mirror['takes']} moved, {-mirror['max_delta']} to {-mirror['min_delta']} points lower)"
            in text)
