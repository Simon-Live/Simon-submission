"""Spec: docs/specs/bench-faults.md. Every label here is SYNTHETIC test data (synthetic: true), generated for
the harness tests; none of it is a measurement of the pipeline."""
import hashlib
import json

import pytest

from part7 import bench_faults as bf


def sha(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


def label(name, faults, **over):
    doc = {"schema": bf.SCHEMA, "clip_sha256": sha(name), "movement": "squat", "labeller": "synthetic-test",
           "labelled_on": "2026-10-31", "synthetic": True,
           "faults": [{"type": t, "side": s, "at_s": a} for t, s, a in faults]}
    doc.update(over)
    return doc


def pred(t, s, a):
    return {"type": t, "side": s, "at_s": a}


def write_set(tmp_path, takes):
    """takes: {name: (label faults, predicted faults)} -> labels dir, analyses dir."""
    labels, analyses = tmp_path / "labels", tmp_path / "analyses"
    labels.mkdir()
    analyses.mkdir()
    for name, (lab, pr) in takes.items():
        (labels / f"{name}.json").write_text(json.dumps(label(name, lab)))
        faults = [{"measure": t, "side": s, "at_s": a} for t, s, a in pr]
        (analyses / f"{sha(name)}.json").write_text(json.dumps({"faults": faults}))
    return labels, analyses


# AC-001
def test_validate_label_accepts_good_and_names_each_defect():
    assert bf.validate_label(label("a", [("knee_flexion", "left", 1.0)]))
    assert bf.validate_label(label("clean", []))
    bad = [dict(label("a", []), schema="x"), label("a", [], clip_sha256="abc"), label("a", [], movement=" "),
           label("a", [], labeller=""), label("a", [], labelled_on="31/10/2026"),
           label("a", [("knee_flexion", "up", 1.0)]), label("a", [("knee_flexion", "left", -1)]),
           label("a", [("knee_flexion", "left", True)]), label("a", [("", "left", 1)]),
           label("a", [], synthetic="yes"), {"faults": "x"}]
    for doc in bad:
        with pytest.raises(bf.BenchError, match="label.json"):
            bf.validate_label(doc, "label.json")
    doc = label("a", [])
    del doc["faults"]
    with pytest.raises(bf.BenchError, match="faults must be a list"):
        bf.validate_label(doc)


# AC-002
def test_match_window_boundaries_and_one_to_one():
    lab = [pred("k", "left", 2.0)]
    assert bf.match(lab, [pred("k", "left", 2.5)])["tp"] == 1  # exactly the window
    assert bf.match(lab, [pred("k", "left", 2.51)]) == {"tp": 0, "fp": 1, "fn": 1, "timing_errors_s": []}
    assert bf.match(lab, [pred("k", "right", 2.0)])["fn"] == 1  # side must agree
    assert bf.match(lab, [pred("j", "left", 2.0)])["fn"] == 1  # type must agree
    two = bf.match(lab, [pred("k", "left", 2.1), pred("k", "left", 2.3)])  # one label matches once
    assert (two["tp"], two["fp"], two["fn"]) == (1, 1, 0)
    assert two["timing_errors_s"] == [pytest.approx(0.1)]
    assert bf.match([], [])["tp"] == 0


def test_match_prefers_closest_pairs():
    lab = [pred("k", "left", 1.0), pred("k", "left", 1.4)]
    m = bf.match(lab, [pred("k", "left", 1.3)])
    assert m["timing_errors_s"] == [pytest.approx(0.1)] and m["fn"] == 1


# AC-003
def test_score_precision_recall_timing():
    takes = [{"labelled": [pred("k", "left", 1.0), pred("a", "right", 3.0)],
              "predicted": [pred("k", "left", 1.2), pred("z", "left", 5.0)]},
             {"labelled": [], "predicted": []}]
    r = bf.score(takes)
    assert (r["tp"], r["fp"], r["fn"], r["takes"]) == (1, 1, 1, 2)
    assert r["precision"] == 0.5 and r["recall"] == 0.5
    assert r["timing_error_mean_s"] == pytest.approx(0.2) and r["timing_error_median_s"] == pytest.approx(0.2)


def test_score_empty_denominators_are_none():
    r = bf.score([{"labelled": [], "predicted": []}])
    assert r["precision"] is None and r["recall"] is None and r["timing_error_mean_s"] is None


# AC-004
def test_split_is_deterministic_disjoint_and_written_once(tmp_path):
    labels = {sha(str(i)): {} for i in range(10)}
    a, b = bf.make_split(labels), bf.make_split(labels)
    assert a["holdout"] == b["holdout"] and len(a["holdout"]) == 5
    assert not set(a["holdout"]) & set(a["dev"]) and set(a["holdout"]) | set(a["dev"]) == set(labels)
    path = tmp_path / "split.json"
    bf.write_split_once(path, labels)
    first = path.read_text()
    with pytest.raises(bf.BenchError, match="recorded once"):
        bf.write_split_once(path, labels)
    assert path.read_text() == first
    with pytest.raises(bf.BenchError, match="at least 2"):
        bf.make_split([sha("only")])
    assert len(bf.make_split([sha("a"), sha("b")])["holdout"]) == 1


# AC-005
def test_run_holdout_end_to_end_and_label_change_refused(tmp_path):
    takes = {f"t{i}": ([("knee_flexion", "left", 2.0)], [("knee_flexion", "left", 2.2)]) for i in range(4)}
    takes["t0"] = ([("knee_flexion", "left", 2.0)], [])  # one miss
    labels, analyses = write_set(tmp_path, takes)
    split = tmp_path / "split.json"
    bf.write_split_once(split, bf.load_labels(labels, allow_synthetic=True))
    hold = set(json.loads(split.read_text())["holdout"])
    r = bf.run(labels, analyses, split, "holdout", allow_synthetic=True)
    assert r["takes"] == 2 and r["synthetic"] is True and r["set"] == "holdout"
    assert r["tp"] + r["fn"] == 2 and r["fp"] == 0
    assert (r["recall"] == 0.5) == (sha("t0") in hold)
    assert bf.run(labels, analyses, split, "all", allow_synthetic=True)["takes"] == 4
    (labels / "extra.json").write_text(json.dumps(label("extra", [])))
    with pytest.raises(bf.BenchError, match="labels changed"):
        bf.run(labels, analyses, split, "holdout", allow_synthetic=True)


def test_analysis_layouts_and_missing(tmp_path):
    (tmp_path / sha("d")).mkdir()
    (tmp_path / sha("d") / "analysis.json").write_text(json.dumps({"faults": [
        {"measure": "k", "side": "left", "follower_t_s": [1.5, 2.0]}]}))
    assert bf.predicted_faults(bf.load_analysis(tmp_path, sha("d"))) == [pred("k", "left", 1.5)]
    with pytest.raises(bf.BenchError, match="no analysis"):
        bf.load_analysis(tmp_path, sha("nope"))
    (tmp_path / f"{sha('bad')}.json").write_text("{")
    with pytest.raises(bf.BenchError, match="not valid JSON"):
        bf.load_analysis(tmp_path, sha("bad"))
    (tmp_path / f"{sha('nf')}.json").write_text("{}")
    with pytest.raises(bf.BenchError, match="no faults list"):
        bf.load_analysis(tmp_path, sha("nf"))
    with pytest.raises(bf.BenchError, match="no at_s"):
        bf.predicted_faults({"faults": [{"measure": "k", "side": "left"}]})


# AC-006
def test_synthetic_and_bad_label_files_refused(tmp_path):
    d = tmp_path / "labels"
    d.mkdir()
    (d / "a.json").write_text(json.dumps(label("a", [])))
    with pytest.raises(bf.BenchError, match="synthetic labels cannot be scored"):
        bf.load_labels(d)
    assert len(bf.load_labels(d, allow_synthetic=True)) == 1
    (d / "b.json").write_text(json.dumps(label("a", [])))
    with pytest.raises(bf.BenchError, match="duplicate"):
        bf.load_labels(d, allow_synthetic=True)
    (d / "b.json").write_text("{")
    with pytest.raises(bf.BenchError, match="b.json: not valid JSON"):
        bf.load_labels(d, allow_synthetic=True)
    empty = tmp_path / "none"
    empty.mkdir()
    with pytest.raises(bf.BenchError, match="no label files"):
        bf.run(empty, tmp_path, tmp_path / "s.json")
    d2 = tmp_path / "l2"
    d2.mkdir()
    (d2 / "a.json").write_text(json.dumps(label("a", [], synthetic=False)))
    with pytest.raises(bf.BenchError, match="missing"):
        bf.run(d2, tmp_path, tmp_path / "nosplit.json")


# AC-007
def test_cli_exit_codes_and_report(tmp_path, capsys):
    takes = {f"c{i}": ([("k", "left", 1.0)], [("k", "left", 1.0)]) for i in range(4)}
    labels, analyses = write_set(tmp_path, takes)
    split = tmp_path / "split.json"
    base = ["--labels", str(labels), "--analyses", str(analyses), "--split", str(split)]
    # synthetic labels are refused by the CLI: exit 2 with the reason on stderr
    assert bf.main(base + ["--make-split"]) == 2
    assert "synthetic labels cannot be scored" in capsys.readouterr().err
    r = bf.score([{"labelled": [pred("k", "left", 1)], "predicted": [pred("k", "left", 1.25)]}])
    r.update({"set": "holdout", "synthetic": True})
    text = bf.format_report(r)
    assert "SYNTHETIC" in text and "precision 100%" in text and "0.25 s" in text and "0.5 s" in text
    r.update({"synthetic": False, "precision": None, "timing_error_mean_s": None, "timing_error_median_s": None})
    assert "SYNTHETIC" not in bf.format_report(r) and "n/a" in bf.format_report(r)
