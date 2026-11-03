"""tools/eval_report.py and tools/eval_collect.py (docs/specs/eval-report.md)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


report = _load("eval_report")
collect = _load("eval_collect")


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "bench" / "results", tmp_path / "bench" / "results")
    (tmp_path / "docs").mkdir()
    shutil.copy(ROOT / "docs" / "evaluation.md", tmp_path / "docs" / "evaluation.md")
    shutil.copy(ROOT / "README.md", tmp_path / "README.md")
    pub = ROOT / "docs" / "audit" / "eval-public-2026-11"
    if pub.is_dir():
        (tmp_path / "docs" / "audit").mkdir()
        shutil.copytree(pub, tmp_path / "docs" / "audit" / "eval-public-2026-11",
                        ignore=shutil.ignore_patterns("*.py", "*.jsonl"))
    kc = ROOT / "docs" / "audit" / "kcurve-2026-11-02"
    if kc.is_dir():
        (tmp_path / "docs" / "audit").mkdir(exist_ok=True)
        shutil.copytree(kc, tmp_path / "docs" / "audit" / "kcurve-2026-11-02")
    own = ROOT / "docs" / "audit" / "ownref-video-2026-11-02"
    if own.is_dir():
        (tmp_path / "docs" / "audit").mkdir(exist_ok=True)
        shutil.copytree(own, tmp_path / "docs" / "audit" / "ownref-video-2026-11-02")
    real = ROOT / "demos" / "rubric" / "TICKET-339"
    if (real / "realdata-aggregates.json").is_file():
        shutil.copytree(real, tmp_path / "demos" / "rubric" / "TICKET-339", ignore=shutil.ignore_patterns("*.png"))
    return tmp_path


def _drop_optional(tree: Path) -> None:
    """The tree without any optional input, so each optional section starts absent."""
    for path in (tree / "bench" / "results").glob("*/mhr-bench.json"):
        path.unlink()
    shutil.rmtree(tree / "docs" / "audit", ignore_errors=True)
    shutil.rmtree(tree / "demos", ignore_errors=True)


def test_committed_doc_matches_and_rebuild_is_stable(tree, capsys):
    assert report.main(["--check", "--root", str(ROOT)]) == 0
    (tree / "docs" / "evaluation.md").write_text("stale\n")
    assert report.main(["--root", str(tree)]) == 0
    first = (tree / "docs" / "evaluation.md").read_bytes()
    assert first == (ROOT / "docs" / "evaluation.md").read_bytes()
    assert report.main(["--root", str(tree)]) == 0
    assert (tree / "docs" / "evaluation.md").read_bytes() == first


def test_every_table_names_its_source_and_sha(tree):
    text = (ROOT / "docs" / "evaluation.md").read_text()
    for name in ("part2-check.json", "part5-heldout-attempts.json", "check7-runs.json", "latency-jobs.json"):
        path = next((ROOT / "bench" / "results").glob(f"*/{name}"))
        assert f"`{path.relative_to(ROOT).as_posix()}`, sha256 `{hashlib.sha256(path.read_bytes()).hexdigest()}`" in text


def test_check_names_the_differing_line(tree, capsys):
    doc = tree / "docs" / "evaluation.md"
    doc.write_text(doc.read_text().replace("3.839%", "3.838%", 1))
    assert report.main(["--check", "--root", str(tree)]) == 1
    err = capsys.readouterr().err
    assert "docs/evaluation.md:" in err and "3.838%" in err
    readme = tree / "README.md"
    doc.write_text((ROOT / "docs" / "evaluation.md").read_text())
    readme.write_text(readme.read_text().replace("3.84%", "3.85%", 1))
    assert report.main(["--check", "--root", str(tree)]) == 1
    assert "README.md:" in capsys.readouterr().err


def test_check_fails_when_a_raw_number_changes(tree, capsys):
    path = next((tree / "bench" / "results").glob("*/part2-check.json"))
    doc = json.loads(path.read_text())
    doc["one_person"]["mean_pct"] = 9.999
    path.write_text(json.dumps(doc))
    assert report.main(["--check", "--root", str(tree)]) == 1
    assert "docs/evaluation.md:" in capsys.readouterr().err


def test_missing_input_and_marker_are_errors(tree, capsys):
    next((tree / "bench" / "results").glob("*/latency-jobs.json")).unlink()
    assert report.main(["--check", "--root", str(tree)]) == 2
    assert "latency-jobs.json" in capsys.readouterr().err
    other = tree / "other"
    shutil.copytree(ROOT / "bench", other / "bench")
    (other / "docs").mkdir()
    (other / "README.md").write_text("no markers\n")
    assert report.main(["--check", "--root", str(other)]) == 2
    assert "eval-report:accuracy:begin" in capsys.readouterr().err


def test_no_unsourced_phrase():
    text = (ROOT / "docs" / "evaluation.md").read_text()
    assert "not published" not in text
    assert chr(0x2014) not in text and chr(0x2013) not in text


def test_percentile_and_latency_stats():
    assert report.percentile([1.0], 95) == 1.0
    assert report.percentile([10.0, 20.0, 30.0, 40.0], 50) == 25.0
    assert report.percentile([0.0, 100.0], 95) == pytest.approx(95.0)
    doc = {"jobs": [
        {"id": "a", "kind": "follow", "status": "ok", "total_s": 100.0, "stages_s": {"pose": 80.0, "analyse": 2.0}},
        {"id": "b", "kind": "follow", "status": "ok", "total_s": 200.0, "stages_s": {"pose": 150.0}, "gpu_wait_s": {"pose": 30.0}},
        {"id": "c", "kind": "follow", "status": "failed", "total_s": 999.0, "stages_s": {}},
    ]}
    (row,) = report.latency_stats(doc)
    assert (row["n"], row["p50"], row["min"], row["max"], row["top"], row["ids"]) == (2, 150.0, 100.0, 200.0, "pose", ["a", "b"])
    assert report.gpu_wait_stats(doc)["n"] == 1
    assert report.ids_cell([str(i) for i in range(9)]) == "listed in the source file"


STATE_LOG = """\
2026-11-01T10:00:00Z INFO job aaa111 summary: kind=people status=ok total=5.0s upload=1.0s track=4.0s(gpu_wait=2.0s)
2026-11-02T10:00:00Z INFO job bbb222 summary: kind=follow status=ok total=100.0s pose=90.0s(gpu_wait=10.0s) part1=ok mode=fitness
2026-11-02T10:01:00Z INFO job ccc333 summary: kind=follow status=ok total=50.0s pose=40.0s
2026-11-02T10:02:00Z INFO job ddd444 summary: kind=people status=ok total=7.0s track=6.0s
2026-11-02T10:03:00Z INFO job eee555 summary: kind=people status=ok total=8.0s track=7.0s
2026-11-02T10:04:00Z INFO job fff666 summary: kind=people status=ok total=9.0s track=8.0s
not a summary line
"""


def test_collect_latency_drops_test_jobs(tmp_path):
    state = tmp_path / "state"
    (state / "jobs").mkdir(parents=True)
    (state / "part7.log").write_text(STATE_LOG)
    docs = {"aaa111": {"kind": "people"}, "bbb222": {"kind": "follow", "entry_id": "dance-1", "people_job": "ddd444"},
            "ccc333": {"kind": "follow", "entry_id": "verify-20261102-ab", "people_job": "eee555"},
            "ddd444": {"kind": "people"}, "eee555": {"kind": "people"}}
    for job_id, doc in docs.items():
        (state / "jobs" / job_id).mkdir()
        (state / "jobs" / job_id / "job.json").write_text(json.dumps({"id": job_id, **doc}))
    out = collect.collect_latency(state, "2026-11-02T00:00:00Z")
    assert [j["id"] for j in out["jobs"]] == ["bbb222", "ddd444"]
    assert out["excluded"] == {"test": 2, "unknown_job": 1, "before_cutoff": 1}
    first = out["jobs"][0]
    assert first["stages_s"] == {"pose": 90.0} and first["gpu_wait_s"] == {"pose": 10.0} and first["total_s"] == 100.0
    assert set(first) == {"id", "logged_at", "stages_s", "gpu_wait_s", "kind", "status", "total_s"}


def test_collect_check7_keeps_only_report_fields(tmp_path):
    run = tmp_path / "check" / "20261102T000000Z"
    run.mkdir(parents=True)
    (run / "metrics.json").write_text(json.dumps({
        "pass": False, "part7_commit": "abc", "gates": {"score_equal": False}, "steps": [{"argv": ["/home/x/secret"]}],
        "entry": {"animation_max_joint_diff_m_vs_direct": 0.0002}, "durations_s": {"total": 1.0},
        "takes": [{"clip": "c", "role": "follower", "score_app": 1, "score_direct": 2, "score_equal": False,
                   "faults_compared": 0, "faults_equal": True, "app": {"faults": []}}]}))
    doc = collect.collect_check7(tmp_path)
    assert "steps" not in json.dumps(doc) and doc["runs"][0]["takes"][0]["score_direct"] == 2


def test_optional_sections_absent_and_present(tree):
    _drop_optional(tree)
    inputs = report.Inputs(tree)
    assert report.section_mhr(inputs) == [] and report.section_spark(inputs) == [] and report.section_public(inputs) == []
    assert "MHR body bench" not in report.build_doc(inputs)
    day = tree / "bench" / "results" / "2026-11-09"
    day.mkdir()
    mhr = {"source_manifest_sha256": "f" * 64, "command": "x", "n": 2, "synthetic": True, "domain_gap_note": "Renders are not video.",
           "per_body": [{"shape_id": "tall", "angle": "front", "condition": "clean", "mpjpe_mm": 41.5, "pa_mpjpe_mm": 22.25,
                         "score": 91.0, "fault_planted": False, "fault_found": False},
                        {"shape_id": "tall", "angle": "front", "condition": "knee15", "mpjpe_mm": 43.0, "pa_mpjpe_mm": 23.0,
                         "score": 80.0, "fault_planted": True, "fault_found": True}],
           "summary": {"score_spread": 3.5, "fault_recall": 1.0, "n": 2},
           "flags": [{"kind": "score_outlier", "shape_id": "short", "angle": None, "detail": "clean score 70 is far"}]}
    (day / "mhr-bench.json").write_text(json.dumps(mhr))
    (day / "spark-agreement.json").write_text(json.dumps({"model": "m", "n": 4, "agreed": 3, "agreement": 0.75,
                                                          "rows": [{"case": "a", "agree": True}]}))
    pub = tree / "docs" / "audit" / "eval-public-2026-11"
    pub.mkdir(parents=True)
    (pub / "results.json").write_text(json.dumps({"dataset": "REHAB24-6", "rows": [{"slice": "good", "n": 5, "recall": 0.8}]}))
    text = report.build_doc(inputs)
    mhr_sha = hashlib.sha256((day / "mhr-bench.json").read_bytes()).hexdigest()
    assert "### MHR body bench" in text and f"sha256 `{mhr_sha}`" in text
    assert "| tall | front | clean | 41.5 | 22.25 | 91.0 | False | False |" in text
    assert "Clean score spread across bodies: 3.5 points." in text and "Planted fault recall: 1.0." in text
    assert "`" + "f" * 64 + "`" in text and "Flag, score_outlier, short" in text
    assert "### Second opinion agreement" in text and "- Agreement: 0.75." in text
    assert "### Public dataset" in text and "REHAB24-6" in text and "| good | 5 | 0.8 |" in text
    assert "no 3D ground-truth benchmark" not in text
    assert "docs/audit/eval-public-2026-11/results.json" in text


DETAILS = {"run": {"started": "2026-11-09T07:00:00Z", "ended": None},
           "aggregates": {"trainer-rehab": {"all": {"clips": 10, "analysed": 10, "confusion": {"tp": 4, "fn": 1, "fp": 4, "tn": 1},
                                                    "specificity": [0.2, 0.05, 0.6], "score_auc": [0.45, 0.3, 0.6],
                                                    "score_mean_correct": 40.0, "score_mean_incorrect": 45.0}},
                          "same-rehab": {"all": {"clips": 10, "analysed": 9, "confusion": {"tp": 3, "fn": 1, "fp": 2, "tn": 3},
                                                 "specificity": [0.6, 0.2, 0.9], "score_auc": [0.7, None, None],
                                                 "score_mean_correct": 85.0, "score_mean_incorrect": 70.0}}},
           "body_invariance": {"rehab": {"paired_correct_reps": 5, "mean_score_other_minus_own": [-40.0, -55.5, -20.25],
                                         "spearman_score_vs_stature_gap": -0.25, "stature_gap_m_range": [0.01, 0.2]}}}


def test_public_references_and_readme_rows(tree):
    _drop_optional(tree)
    inputs = report.Inputs(tree)
    assert report.section_public_refs(inputs) == [] and report.public_readme_rows(inputs) == []
    assert report.mhr_readme_rows(inputs) == []
    assert "No set of real people" in report.build_doc(inputs)
    pub = tree / "docs" / "audit" / "eval-public-2026-11"
    pub.mkdir(parents=True)
    (pub / "details.json").write_text(json.dumps(DETAILS))
    (pub / "sample.json").write_text(json.dumps({"per_class": 3, "exercises": {"1": [], "4": []}}))
    text = "\n".join(report.section_public_refs(inputs))
    assert "Interim: 10 reps of the 12 planned." in text and "had not ended" in text
    assert "| A correct rep by another person | 10 of 10 | 0.45 (0.30 to 0.60) | 4 of 5 | 20% (5% to 60%) | 40.0 / 45.0 |" in text
    assert "| The same person's own correct rep | 9 of 10 | 0.70 | 2 of 5 |" in text
    assert "lowers the mean score by 40.0 (95% 20.2 to 55.5) points" in text
    rows = "\n".join(report.public_readme_rows(inputs))
    assert "interim, 10 of 12 reps, 2026-11-09" in rows and "score AUC 0.45 (0.30 to 0.60), 0.5 is chance; 4 of 5" in rows
    assert "40.0 (95% 20.2 to 55.5) points lower" in rows
    doc = report.build_doc(inputs)
    assert "No set of real people" not in doc and "another person's recording" in doc


def test_mhr_angles_and_readme_rows(tree):
    _drop_optional(tree)
    day = tree / "bench" / "results" / "2026-11-09"
    day.mkdir()
    row = lambda angle, cond, mp, score, found: {"shape_id": f"s{mp}", "angle": angle, "condition": cond, "mpjpe_mm": mp,  # noqa: E731
                                                 "pa_mpjpe_mm": mp / 2, "score": score, "fault_planted": cond != "clean",
                                                 "fault_found": found}
    (day / "mhr-bench.json").write_text(json.dumps({"per_body": [
        row("side", "clean", 120.0, 50.0, False), row("front", "clean", 80.0, 0.0, False),
        row("front", "knee15", 90.0, 60.0, True), row("45", "knee15", 70.0, 0.0, False)], "summary": {"score_spread": 12.5}}))
    inputs = report.Inputs(tree)
    assert [a["angle"] for a in report.mhr_angles(json.loads((day / "mhr-bench.json").read_text()))] == ["front", "45", "side"]
    rows = "\n".join(report.mhr_readme_rows(inputs))
    assert "one squat on 4 body shapes, 4 renders (interim)" in rows and "spread 12.5 points across shapes; 2 of 4 renders scored 0" in rows
    assert "MPJPE 70 to 120 mm, PA-MPJPE 35 to 60 mm" in rows and "found front 1 of 1, 45 degrees 0 of 1, side 0 of 0" in rows
    doc = report.build_doc(inputs)
    assert "| front | 2 | 85.0 | 42.5 | 1 of 1 | 1 |" in doc and "do not transfer to video of people unchanged" in doc


def _kc_metric(auc, lo, hi, recall):
    return {"auc": auc, "ci95": [lo, hi], "recall80": recall, "spec_achieved": 0.8, "p": 0.005, "null_mean": 0.5,
            "null95": 0.52, "n_null": 200}


def test_kcurve_section_rows_and_pipeline(tree):
    _drop_optional(tree)
    inputs = report.Inputs(tree)
    assert report.section_kcurve(inputs) == [] and report.kcurve_readme_rows(inputs) == []
    assert "Leave-one-person-out" not in report.build_doc(inputs)
    kc = tree / "docs" / "audit" / "kcurve-2026-11-02"
    kc.mkdir(parents=True)
    pooled = {k: _kc_metric(0.5 + i / 100, 0.4, 0.7, 0.2 + i / 100) for i, k in enumerate(
        ("a", "b1", "b2", "b3", "b4", "b6", "bmax", "c"))}
    per = {e: {"_n": 10, "_people": 4, "a": _kc_metric(0.6, 0.5, 0.7, 0.2), "c": _kc_metric(0.8, 0.7, 0.9, 0.5),
               "b8": _kc_metric(0.65, 0.5, 0.8, 0.3) if e == "1" else {}} for e in ("1", "2")}
    (kc / "results.json").write_text(json.dumps({"pooled": pooled, "per_exercise": per}))
    text = "\n".join(report.section_kcurve(inputs))
    assert "A pre-registered leave-one-person-out run on REHAB24-6 motion capture" in text and "20 reps" in text
    assert "| One other person's correct rep (Simon's score) | 0.50 (0.40 to 0.70) | 0.20 | 0.52 |" in text
    assert "| 2 | 10 | 0.60 (0.50 to 0.70) | n/a | 0.80 (0.70 to 0.90) |" in text
    assert "4 correct people" in text and "video pipeline" not in text
    rows = "\n".join(report.kcurve_readme_rows(inputs))
    assert "REHAB24-6, 20 reps" in rows and "AUC 0.50 (0.40 to 0.70); recall 0.20 at 80% specificity" in rows
    assert "AUC 0.54 to 0.56; recall 0.24 to 0.26" in rows and "pooled.c" in rows
    (kc / "pipeline-summary.json").write_text(json.dumps({"summary": {
        "n": 5, "n_inc": 2, "people": 3, "envelope": {"auc_stratified": 0.375, "ci95": [0.16, 0.55], "p_perm": 0.61,
                                                      "recall": "1/2", "correct_flagged": "2/3"},
        "simon_trainer_rehab_stored": {"auc_stratified": 0.4, "ci95": [0.25, 0.63]}}}))
    text = "\n".join(report.section_kcurve(inputs))
    assert "AUC 0.375 (0.160 to 0.550)" in text and "Neither interval excludes 0.5" in text
    assert "AUC 0.375 (0.160 to 0.550); the interval includes 0.5" in "\n".join(report.kcurve_readme_rows(inputs))
    assert "motion capture of acted rehabilitation" in report.build_doc(inputs)


def _own_arm(people, up, median, wilcoxon, ctrl_people):
    return {"people": people, "groups": 3, "triples": 12, "share_ci95": [1.0, 1.0] if up == people else [0.5, 1.0],
            "people_up_down_tie": [up, people - up, 0], "median_change": median, "median_ci95": [1.0, 20.0],
            "mean_before": 60.0, "mean_after": 80.0, "wilcoxon_p_greater": wilcoxon, "null_p": 0.0033,
            "top_note_gone_on_after": {"pooled": 0.8, "n_triples": 10},
            "control_gone_on_other_incorrect": {"pooled": 0.5, "n_triples": 8, "people": ctrl_people}}


def _own_metric(auc, p):
    return {"auc_strat": auc, "ci95": [auc - 0.1, auc + 0.1], "within_person": auc, "recall80_spec": [0.4, 0.75],
            "per_exercise": {"1": auc, "2": auc}, "p_perm": p, "n_null": 300}


def test_ownref_section_rows_and_limit(tree):
    _drop_optional(tree)
    inputs = report.Inputs(tree)
    assert report.section_ownref(inputs) == [] and report.ownref_readme_rows(inputs) == []
    assert "own rep as the reference, on video" not in report.build_doc(inputs)
    own = tree / "docs" / "audit" / "ownref-video-2026-11-02"
    own.mkdir(parents=True)
    doc = {"A": {"n_test": 20, "n_excluded": 2, "n_incorrect": 8, "people": 5, "share_diff_session": 0.25,
                 "per_exercise_n": {"1": [12, 5, 3], "2": [8, 3, 2]}, "video": _own_metric(0.7, 0.0066),
                 "mocap": _own_metric(0.8, 0.0033), "gap_video_minus_mocap": {"est": -0.1, "ci95": [-0.2, 0.05]}},
           "B": {"video": _own_arm(4, 4, 12.6, 0.0625, 1), "mocap_matched": _own_arm(4, 3, 20.0, 0.125, 1),
                 "mocap_full": _own_arm(9, 9, 20.4, 0.002, 9)}}
    (own / "results.json").write_text(json.dumps(doc))
    text = "\n".join(report.section_ownref(inputs))
    assert "20 follower reps from 5 people, 8 of them incorrect; 2 were left out" in text
    assert "25% of test reps had a reference from another recording session" in text
    assert "| Video, the person's own correct rep | 0.70 (0.60 to 0.80) | 0.007 | 0.40 (0.75) | 0.70 |" in text
    assert "| Motion capture, the same pairs | 0.80 (0.70 to 0.90) | 0.003 (the floor for 300 runs) |" in text
    assert "the interval includes 0." in text and "| 1 | 12 (5, 3) | 0.70 | 0.80 |" in text
    assert "| Video | 4 (3, 12) | 4 of 4 | +12.6 (+1.0 to +20.0) | 60.0 / 80.0 | 0.062 |" in text
    assert "80% of 10 | 50% of 8 (1 person) |" in text and "| 3 of 4 |" in text
    assert "smallest possible one-sided Wilcoxon p is 0.062" in text and "degenerate" in text
    assert "not a coaching study" in text and "nobody received a cue" in text and "sha256" in text
    rows = "\n".join(report.ownref_readme_rows(inputs))
    assert "(REHAB24-6, 20 reps, 5 people) | AUC 0.70 (0.60 to 0.80); shuffled-label p 0.007; recall 0.40" in rows
    assert "| Same pairs on motion capture | AUC 0.80 (0.70 to 0.90) |" in rows
    assert "correct above incorrect for 4 of 4 people, median +12.6 points; Wilcoxon one-sided p 0.062" in rows
    assert "| Same, all motion-capture reps | 9 of 9 people, median +20.4 points |" in rows
    assert "75% of its references came from the same recording session" in report.build_doc(inputs)


def _card(job: str, rows: list[tuple[str, str, str, dict]]) -> dict:
    return {"job": job, "models": [{"id": i, "model": m, "maker": "Meta", "clip": "you", "status": st, "seconds": None,
                                    "facts": facts} for i, m, st, facts in rows]}


def test_realdata_section_cards_and_limit(tree):
    _drop_optional(tree)
    inputs = report.Inputs(tree)
    assert report.section_realdata(inputs) == []
    assert "Real people outside the lab" not in report.build_doc(inputs)
    base = tree / "demos" / "rubric" / "TICKET-339"
    (base / "mmfit").mkdir(parents=True)
    take = {"job": "aaa111", "models_card": "demos/rubric/TICKET-339/mmfit/aaa111-models.json", "seconds": 200,
            "score": 61, "grade": "D", "credit_points": 1234, "credit_max_points": 2000, "credit_percent": 61.7,
            "credit_grade": "D", "faults": 2, "verdicts": 1, "agrees": 1}
    refs = ("a", "b1", "b2", "b4", "b8", "b16", "c")
    doc = {"about": "Aggregates only.",
           "mmfit": {"dataset": "MM-Fit", "licence": "CC BY 4.0", "attribution": "Credit line.", "date": "2026-11-02",
                     "staging_build": "abc", "people": 3, "teacher": {"job": "t1", "entry": "e1", "seconds": 300},
                     "takes": [take]},
           "intellirehab": {"dataset": "IntelliRehabDS", "licence": "CC BY 4.0", "data": "skeletons", "exercises": 2,
                            "reps": 40, "incorrect": 9, "scorer": "a test scorer",
                            "macro_auc": {k: 0.6 + i / 100 for i, k in enumerate(refs)},
                            "p_global": {k: 0.002 for k in refs} | {"c": 0.2},
                            "within_person_null_mean": {k: 0.55 for k in refs},
                            "macro_auc_healthy": {k: 0.5 + i / 100 for i, k in enumerate(refs)},
                            "driver": "mostly by who the person is", "own_reference_subset": "a subset"},
           "pexels": {"dataset": "Pexels clips", "licence": "the Pexels License", "date": "2026-11-02", "clips": 3,
                      "clips_scored": 2, "followers": 8, "followers_with_credit": 7, "credit_percent_min": 50.0,
                      "credit_percent_max": 70.0, "match_limits": {"max_residual": 0.5, "min_timing_corr": 0.8},
                      "unscored_clip": "the third failed", "ticket": "Part 5 TICKET-101"}}
    (base / "realdata-aggregates.json").write_text(json.dumps(doc))
    with pytest.raises(report.ReportError, match="aaa111-models.json is missing"):
        report.section_realdata(inputs)
    (base / "mmfit" / "aaa111-models.json").write_text(json.dumps(_card("aaa111", [
        ("sam3d-you", "SAM 3D Body", "live", {}), ("spark-opinion", "Muse Spark", "live", {}),
        ("mms-tts", "MMS-TTS", "not_run", {"reason": "no_spoken_lines"})])))
    text = "\n".join(report.section_realdata(inputs))
    assert "| `aaa111` | 200 s | 1,234 of 2,000 points (61.7%), grade D | 61, D | 2 | 1 verdict, 1 agrees |" in text
    assert "SAM 3D Body (you), Muse Spark second opinion (you)" in text
    assert "by Part 5 ADR-0020" in text and "by design" in text and "not yet investigated" not in text
    assert "MMS-TTS (you): not_run, `no_spoken_lines`" in text
    assert "| Envelope of 16 other people | 0.650 | 0.550 | 0.550 |" in text
    assert "rises from 0.610 with one reference person to 0.650" in text and "(p 0.2)" in text
    assert "All 8 followers" in text and "`low_match`" in text and "Part 5 TICKET-101" in text
    assert "Source: `demos/rubric/TICKET-339/realdata-aggregates.json`, sha256" in text
    assert "MM-Fit, IntelliRehabDS and Pexels runs carry no label" in report.build_doc(inputs)
