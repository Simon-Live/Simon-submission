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
import json
import re
import sys
from pathlib import Path

import pytest

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
