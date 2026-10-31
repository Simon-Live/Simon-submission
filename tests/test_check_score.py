"""`make check-5`, the score side (docs/specs/check-5.md; ADR-0007, AC-S04, AC-S06, AC-K10): a correct good-light take
must be an A, the sweep must not rise, and the score params are frozen with the detection rules.

The synthetic world (the analyse table, the temp labels, the freeze record) is the one tests/test_check.py builds.
"""
import json

import pytest

from part5 import check
from test_check import A_SCORE, errors_of, freeze_section, green, world


# ----------------------------------------------------------------- the score (ADR-0007, AC-S04, AC-S06)
def with_score(analyses, take_id, value, grade):
    analyses[take_id] = {**analyses[take_id], "score": {**A_SCORE, "value": value, "grade": grade}}


def test_ac_s04_a_correct_good_light_take_below_a_exits_1_and_names_it(tmp_path, monkeypatch, capsys):
    held = green("h")
    with_score(held[1], "h_front_good_clean_c0", 88, "B")
    code, out, _ = world(tmp_path, monkeypatch, held=held).run(capsys)
    doc = json.loads(out)
    assert code == 1 and doc["gate"]["passed"] is False
    assert doc["gate"]["failures"] == ["h_front_good_clean_c0: scored 88 (B), a correct good-light take must be an A"]


def test_ac_s04_an_ok_take_with_no_score_fails_the_gate(tmp_path, monkeypatch, capsys):
    held = green("h")
    held[1]["h_side_good_clean_c1"] = {**held[1]["h_side_good_clean_c1"], "score": None}
    code, out, _ = world(tmp_path, monkeypatch, held=held).run(capsys)
    assert code == 1 and "h_side_good_clean_c1: no score" in json.loads(out)["gate"]["failures"][0]


def test_ac_s04_a_rising_sweep_exits_1_and_names_the_step(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch)
    monkeypatch.setattr(check, "run_sweep", lambda out_dir: {"arms_wider both": [(0, 100), (5, 80), (10, 84)]})
    code, out, _ = w.run(capsys)
    assert code == 1
    assert json.loads(out)["gate"]["failures"] == [
        "sweep arms_wider both: score rises from 80 at 5 degrees to 84 at 10 degrees"]


def test_ac_s04_low_light_and_faulty_takes_never_gate(tmp_path, monkeypatch, capsys):
    held = green("h")
    for tid in list(held[1]):
        if "_low_" in tid or tid.rsplit("_", 1)[1].startswith("f"):
            with_score(held[1], tid, 20, "F")
    code, out, _ = world(tmp_path, monkeypatch, held=held).run(capsys)
    doc = json.loads(out)
    assert code == 0 and errors_of(doc) == []
    sc = doc["report"]["score"]
    assert sc["gated"] is False and sc["heldout"]["slices"]["good/0"]["grades"] == {"A": 10}
    assert sc["heldout"]["slices"]["low/0"]["grades"] == {"F": 10}
    assert sc["heldout"]["targets"]["good/0"] == "pass" and sc["tuning"]["seed"] == 5


def test_ac_s04_the_summary_prints_the_grade_distribution(tmp_path, monkeypatch, capsys):
    _, _, err = world(tmp_path, monkeypatch).run(capsys)
    assert "check-5: score good/0" in err and "A 10" in err and "{" not in err


def score_lines(err):
    return [line for line in err.splitlines() if line.startswith("check-5: score ")]


def test_ac_k11_a_missed_score_target_reads_as_reported_not_gated_above_a_pass(tmp_path, monkeypatch, capsys):
    """Stderr: a good-light fault take graded F misses the good/1 target. The line says it is reported and not gated,
    never "fail", and the run still ends `check-5: PASS` with exit 0 and the same numbers on stdout."""
    held = green("h")
    for tid in list(held[1]):
        if "_good_" in tid and tid.rsplit("_", 1)[1].startswith("f"):
            with_score(held[1], tid, 30, "F")
    code, out, err = world(tmp_path, monkeypatch, held=held).run(capsys)
    doc = json.loads(out)
    assert code == 0 and err.splitlines()[-1] == "check-5: PASS" and errors_of(doc) == []
    assert doc["report"]["score"]["heldout"]["targets"] == {"good/0": "pass", "good/1": "fail", "good/2": "no takes"}
    lines = {line.split()[2]: line for line in score_lines(err)}
    assert lines["good/0"].endswith("  target met")
    assert lines["good/1"].endswith("  target missed (reported, not gated)")
    assert lines["good/2"].endswith("  target not judged (no takes)")
    assert lines["low/0"].endswith("  (reported)")
    assert not [line for line in score_lines(err) if "verdict" in line or " fail" in line.lower()]


def test_ac_k11_the_summary_words_cover_every_verdict_the_score_report_can_give():
    from part5 import score_report
    verdicts = score_report.verdicts(score_report.distribution([]))
    assert set(check.TARGET_WORDS) == {"pass", "fail", "no takes"} and set(verdicts.values()) <= set(check.TARGET_WORDS)


def freeze_by_detection(tmp_path):
    section = f"\n## Score\n\n### Freeze check\ndetection_sha256: `{check.detection_hash()}`\n"
    (tmp_path / "thresholds.md").write_text(freeze_section(29, sha="0" * 64) + section)


def test_ac_s06_the_detection_hash_stands_in_for_the_whole_file_hash(tmp_path, monkeypatch, capsys):
    freeze_by_detection(tmp_path)
    code, out, err = world(tmp_path, monkeypatch, seed=29).run(capsys)
    doc = json.loads(out)
    assert code == 0, err
    assert doc["detection_sha256"] == check.detection_hash() and doc["attempts"][-1]["rules_sha256"] == "0" * 64


def test_ac_s06_a_changed_detection_key_exits_2(tmp_path, monkeypatch, capsys):
    freeze_by_detection(tmp_path)
    rules = json.loads(check.RULES_PATH.read_text())
    rules["default"]["threshold_deg"] += 1
    changed = tmp_path / "rules.json"
    changed.write_text(json.dumps(rules))
    monkeypatch.setattr(check, "RULES_PATH", changed)
    code, out, err = world(tmp_path, monkeypatch, seed=29).run(capsys)
    assert code == 2 and out == "" and "part5/rules.json differs from the hash frozen for seed 29" in err


def edit_score_block(tmp_path, monkeypatch):
    """A rules.json whose detection keys are the frozen ones and whose `score` slope is one higher; returns its path."""
    rules = json.loads(check.RULES_PATH.read_text())
    rules["score"]["slope"] += 1
    changed = tmp_path / "rules.json"
    changed.write_text(json.dumps(rules))
    monkeypatch.setattr(check, "RULES_PATH", changed)
    return changed


def score_record(tmp_path, *hashes):
    path = tmp_path / "score-heldout.json"
    path.write_text(json.dumps({"format": "simon.part5.score-heldout.v1",
                                "attempts": [{"seed": 47 + i, "params_sha256": h} for i, h in enumerate(hashes)]}))
    return path


def test_ac_s06_editing_only_the_score_block_leaves_the_detection_freeze_passing(tmp_path, monkeypatch, capsys):
    """The detection hash leaves `score` out (ADR-0007), so the detection freeze itself still passes; the score
    freeze below is what catches the edit."""
    freeze_by_detection(tmp_path)
    changed = edit_score_block(tmp_path, monkeypatch)
    monkeypatch.setattr(check, "SCORE_RECORD", score_record(tmp_path, check.score_params_hash(changed)))
    assert world(tmp_path, monkeypatch, seed=29).run(capsys)[0] == 0


def test_ac_k10_the_committed_score_params_are_the_ones_the_score_report_froze():
    recorded = json.loads(check.SCORE_RECORD.read_text())["attempts"]
    assert recorded and check.score_params_hash() == check.recorded_score_hash(check.SCORE_RECORD)
    assert {a["params_sha256"] for a in recorded} == {check.score_params_hash()}


def test_ac_k10_editing_a_score_param_after_the_freeze_exits_2_with_a_plain_message(tmp_path, monkeypatch, capsys):
    freeze_by_detection(tmp_path)
    edit_score_block(tmp_path, monkeypatch)
    code, out, err = world(tmp_path, monkeypatch, seed=29).run(capsys)
    assert code == 2 and out == ""
    assert err.startswith("check-5: the score params in part5/rules.json (sha256 ")
    assert "differ from the ones frozen in fixtures/score-heldout.json" in err and "ADR-0007" in err
    assert not (tmp_path / "out" / "metrics.json").exists()   # nothing is scored against the wrong params


def test_ac_k10_the_unedited_score_params_pass_against_the_committed_record(tmp_path, monkeypatch, capsys):
    freeze_by_detection(tmp_path)
    assert world(tmp_path, monkeypatch, seed=29).run(capsys)[0] == 0


def test_ac_k10_the_newest_attempts_hash_is_the_one_that_counts(tmp_path, monkeypatch, capsys):
    freeze_by_detection(tmp_path)
    now = check.score_params_hash()
    monkeypatch.setattr(check, "SCORE_RECORD", score_record(tmp_path, "0" * 64, now))
    assert world(tmp_path, monkeypatch, seed=29).run(capsys)[0] == 0


def test_ac_k10_an_older_attempts_hash_does_not_stand_in_for_the_newest(tmp_path, monkeypatch, capsys):
    freeze_by_detection(tmp_path)
    monkeypatch.setattr(check, "SCORE_RECORD", score_record(tmp_path, check.score_params_hash(), "0" * 64))
    code, _, err = world(tmp_path, monkeypatch, seed=29).run(capsys)
    assert code == 2 and "differ from the ones frozen" in err


@pytest.mark.parametrize("content", [None, "not json", '{"attempts": []}', '{"attempts": [{"seed": 47}]}'])
def test_ac_k10_a_missing_or_empty_score_record_exits_2(tmp_path, monkeypatch, capsys, content):
    freeze_by_detection(tmp_path)
    record = tmp_path / "score-heldout.json"
    if content is not None:
        record.write_text(content)
    monkeypatch.setattr(check, "SCORE_RECORD", record)
    code, out, err = world(tmp_path, monkeypatch, seed=29).run(capsys)
    assert code == 2 and out == "" and "fixtures/score-heldout.json has no frozen score params" in err
