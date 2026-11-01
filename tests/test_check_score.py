"""`make check-5`, the score side (docs/specs/check-5.md; ADR-0007, AC-S04, AC-S06, AC-K10): a correct good-light take
must be an A, the sweep must not rise, and the score params are frozen with the detection rules.

The synthetic world (the analyse table, the temp labels, the freeze record) is the one tests/test_check.py builds.
"""
import json

import pytest

from part5 import check
from shipped_score import SHIPPED, V1, V2, V3, capped_only, frozen_v1
from test_check import A_SCORE, REAL_SCORE_RECORD as COMMITTED_RECORD, errors_of, freeze_section, green, world


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


def score_record(tmp_path, *hashes, version=None):
    """A score record whose newest entries freeze `hashes` for `version` (default: the version the shipped rules name):
    v2 and v3 hashes are `freezes` entries (ADR-0018, ADR-0019), v1 hashes are attempts (ADR-0007)."""
    version = version or check.score_version()
    path = tmp_path / "score-heldout.json"
    doc = {"format": "simon.part5.score-heldout.v1", "attempts": [], "freezes": []}
    for i, h in enumerate(hashes):
        if version in check.SCORE_SEEDS:
            doc["freezes"].append({"version": version, "params_sha256": h, "seed": check.SCORE_SEEDS[version]})
        else:
            doc["attempts"].append({"seed": 47 + i, "params_sha256": h})
    path.write_text(json.dumps(doc))
    return path


def test_ac_s06_editing_only_the_score_block_leaves_the_detection_freeze_passing(tmp_path, monkeypatch, capsys):
    """The detection hash leaves `score` out (ADR-0007), so the detection freeze itself still passes; the score
    freeze below is what catches the edit."""
    freeze_by_detection(tmp_path)
    changed = edit_score_block(tmp_path, monkeypatch)
    monkeypatch.setattr(check, "SCORE_RECORD", score_record(tmp_path, check.score_params_hash(changed)))
    assert world(tmp_path, monkeypatch, seed=29).run(capsys)[0] == 0


def test_ac_k10_the_committed_score_params_are_the_ones_the_record_froze_or_the_freeze_is_not_recorded_yet():
    """v1 (ADR-0007): the attempts for seeds 47 and 53 froze the block. v2 and v3 (ADR-0018, ADR-0019): the orchestrator records
    the freeze in `freezes` before the version's seed (59, 61); until then there is none and `make check-5` exits 2 (the next
    test)."""
    doc = json.loads(check.SCORE_RECORD.read_text())
    version = check.score_version()
    frozen = check.recorded_score_hash(check.SCORE_RECORD, version)
    if version == "simon.score.v1":   # the attempts that froze v1: those with no version (47, 53); a seed 59 or 61 attempt is later
        v1_attempts = [a for a in doc["attempts"] if a.get("version", "simon.score.v1") == "simon.score.v1"]
        assert v1_attempts and {a["params_sha256"] for a in v1_attempts} == {check.score_params_hash()} == {frozen}
    elif frozen is None:
        assert version in check.SCORE_SEEDS and not [f for f in doc.get("freezes", []) if f.get("version") == version]
    else:
        newest = [f for f in doc["freezes"] if f.get("version") == version][-1]
        assert frozen == check.score_params_hash() and newest["seed"] == check.SCORE_SEEDS[version]
    # the attempts of seeds 47 and 53 froze the v1 block, which v2 carries verbatim as `score.v1`
    shipped = json.loads(check.RULES_PATH.read_text())["score"]
    assert {a["params_sha256"] for a in doc["attempts"] if a["seed"] in (47, 53)} == {
        check.params_sha256(shipped["v1"] if "v1" in shipped else shipped)}


def test_adr_0018_a_v2_block_is_checked_against_the_freezes_and_a_v1_attempt_does_not_stand_in(tmp_path):
    v2, v1 = "simon.score.v2", "simon.score.v1"
    path = tmp_path / "score-heldout.json"
    path.write_text(json.dumps({"attempts": [{"seed": 47, "params_sha256": "a" * 64}],
                                "freezes": [{"version": v2, "params_sha256": "b" * 64, "seed": 59}]}))
    assert check.recorded_score_hash(path, v2) == "b" * 64
    assert check.recorded_score_hash(path, v1) == "a" * 64
    assert check.recorded_score_hash(path) == "a" * 64   # no version: the newest attempt, as before
    path.write_text(json.dumps({"attempts": [{"seed": 47, "params_sha256": "a" * 64}]}))
    assert check.recorded_score_hash(path, v2) is None   # no freeze recorded yet: nothing to compare with
    path.write_text(json.dumps({"attempts": [{"seed": 47, "params_sha256": "a" * 64},
                                             {"seed": 59, "version": v2, "params_sha256": "c" * 64}]}))
    assert check.recorded_score_hash(path, v1) == "a" * 64   # a v2 attempt is not the v1 freeze


def test_adr_0018_a_second_v2_freeze_is_refused_not_taken_for_the_newest(tmp_path):
    """Before the pre-freeze review R1 the newest of two freezes counted; now a record holds one freeze per version."""
    path = tmp_path / "score-heldout.json"
    path.write_text(json.dumps({"attempts": [], "freezes": [
        {"version": "simon.score.v2", "params_sha256": "a" * 64}, {"version": "simon.score.v2", "params_sha256": "b" * 64}]}))
    with pytest.raises(check.CheckError, match="holds 2 simon.score.v2 freeze entries.*re-freeze"):
        check.require_held(path, "simon.score.v2")


def test_adr_0018_the_refusal_names_the_version_that_has_no_freeze():
    with pytest.raises(check.CheckError) as e:
        check.require_score_frozen("a" * 64, None, "simon.score.v2")
    assert "has no frozen score params (params_sha256) for simon.score.v2" in e.value.messages[0]
    with pytest.raises(check.CheckError) as e:
        check.require_score_frozen("a" * 64, "b" * 64, "simon.score.v2")
    assert "ADR-0018" in e.value.messages[0] and "differ from the ones frozen" in e.value.messages[0]
    check.require_score_frozen("a" * 64, "a" * 64, "simon.score.v2")


def test_adr_0018_the_report_names_the_score_version_the_rules_ship_and_its_slice_targets(tmp_path, monkeypatch, capsys):
    freeze_by_detection(tmp_path)
    doc = json.loads(world(tmp_path, monkeypatch, seed=29).run(capsys)[1])
    sc = doc["report"]["score"]
    assert sc["version"] == check.score_version() == SHIPPED
    assert set(sc["heldout"]["targets"]) == {"good/0", "good/1", "good/2"}


def test_ac_k10_editing_a_score_param_after_the_freeze_exits_2_with_a_plain_message(tmp_path, monkeypatch, capsys):
    freeze_by_detection(tmp_path)
    edit_score_block(tmp_path, monkeypatch)
    code, out, err = world(tmp_path, monkeypatch, seed=29).run(capsys)
    assert code == 2 and out == ""
    assert err.startswith("check-5: the score params in part5/rules.json (sha256 ")
    assert "differ from the ones frozen in fixtures/score-heldout.json" in err and "ADR-0007" in err
    assert not (tmp_path / "out" / "metrics.json").exists()   # nothing is scored against the wrong params


def test_ac_k10_the_unedited_score_params_pass_against_a_record_that_freezes_them(tmp_path, monkeypatch, capsys):
    freeze_by_detection(tmp_path)
    assert world(tmp_path, monkeypatch, seed=29).run(capsys)[0] == 0


def test_adr_0018_against_the_committed_record_check_5_passes_once_the_v2_freeze_is_recorded_and_exits_2_before(
        tmp_path, monkeypatch, capsys):
    freeze_by_detection(tmp_path)
    monkeypatch.setattr(check, "SCORE_RECORD", COMMITTED_RECORD)
    code, out, err = world(tmp_path, monkeypatch, seed=29).run(capsys)
    if check.recorded_score_hash(check.SCORE_RECORD, check.score_version()) is None:
        assert code == 2 and out == "" and f"has no frozen score params (params_sha256) for {SHIPPED}" in err
    else:
        assert code == 0


def v1_rules_hash(tmp_path, monkeypatch):
    """Point `check` at a copy of the rules that ships the frozen v1 block (what `make score-fallback` leaves) and return the hash
    of that block: the v1 freeze is the newest attempt of the record (ADR-0007), which is what these two tests are about."""
    rules = json.loads(check.RULES_PATH.read_text())
    rules["score"] = frozen_v1()
    changed = tmp_path / "rules-v1.json"
    changed.write_text(json.dumps(rules))
    monkeypatch.setattr(check, "RULES_PATH", changed)
    return check.score_params_hash(changed)


def test_ac_k10_the_newest_attempts_hash_is_the_one_that_counts(tmp_path, monkeypatch, capsys):
    freeze_by_detection(tmp_path)
    now = v1_rules_hash(tmp_path, monkeypatch)
    monkeypatch.setattr(check, "SCORE_RECORD", score_record(tmp_path, "0" * 64, now, version=V1))
    assert world(tmp_path, monkeypatch, seed=29).run(capsys)[0] == 0


def test_ac_k10_an_older_attempts_hash_does_not_stand_in_for_the_newest(tmp_path, monkeypatch, capsys):
    freeze_by_detection(tmp_path)
    monkeypatch.setattr(check, "SCORE_RECORD", score_record(tmp_path, v1_rules_hash(tmp_path, monkeypatch), "0" * 64, version=V1))
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




# ---------------------------------------------------------------- N4: check-5 refuses a v2 or v3 block whose recorded attempt did not hold
LATER = [(V2, 59, "ADR-0018"), (V3, 61, "ADR-0019")]   # the versions after v1, their score seeds and the ADR each is judged under


def attempts_record(tmp_path, *later_attempts, v1_hash="a" * 64, freezes=()):
    path = tmp_path / "attempts-record.json"
    path.write_text(json.dumps({"attempts": [{"seed": 47, "params_sha256": v1_hash}, {"seed": 53, "params_sha256": v1_hash},
                                             *later_attempts], "freezes": list(freezes)}))
    return path


def later_attempt(version, **over):
    return {"seed": check.SCORE_SEEDS[version], "version": version, "params_sha256": "b" * 64, "holds": True, **over}


@pytest.mark.parametrize("version, seed, adr", LATER)
def test_n4_a_block_with_no_attempt_of_its_version_yet_or_one_that_held_is_not_refused(tmp_path, version, seed, adr):
    check.require_held(attempts_record(tmp_path), version)                           # before its seed is scored
    check.require_held(attempts_record(tmp_path, later_attempt(version)), version)   # it held
    check.require_held(tmp_path / "missing.json", version)                           # no record: the freeze check owns that


@pytest.mark.parametrize("version, seed, adr", LATER)
def test_n4_a_block_whose_recorded_attempt_has_holds_false_is_refused_pointing_to_the_fallback(tmp_path, version, seed, adr):
    with pytest.raises(check.CheckError) as e:
        check.require_held(attempts_record(tmp_path, later_attempt(version, holds=False)), version)
    assert f"{version} did not hold every target on seed {seed} (holds false)" in e.value.messages[0]
    assert "make score-fallback" in e.value.messages[0] and adr in e.value.messages[0]


@pytest.mark.parametrize("version, seed, adr", LATER)
@pytest.mark.parametrize("holds", ["absent", "yes", None])
def test_n4_an_attempt_that_does_not_record_holds_fails_closed(tmp_path, version, seed, adr, holds):
    attempt = later_attempt(version, holds=holds)
    if holds == "absent":
        del attempt["holds"]
    with pytest.raises(check.CheckError) as e:
        check.require_held(attempts_record(tmp_path, attempt), version)
    assert "does not record `holds`" in e.value.messages[0] and "make score-fallback" in e.value.messages[0]


@pytest.mark.parametrize("version", [V1, None])
def test_n4_a_v1_block_is_never_judged_by_a_later_attempt_since_v1_shipped_with_its_misses(tmp_path, version):
    for later in (V2, V3):
        check.require_held(attempts_record(tmp_path, later_attempt(later, holds=False)), version)
        check.require_held(attempts_record(tmp_path, {"seed": check.SCORE_SEEDS[later], "version": later}), version)


def test_adr_0019_a_version_is_judged_by_its_own_attempt_only(tmp_path):
    """The record holds v2's failed attempt on 59: a v3 block must not be refused by it (nor a v2 block by a failed v3)."""
    failed_v2 = later_attempt(V2, holds=False)
    check.require_held(attempts_record(tmp_path, failed_v2, later_attempt(V3)), V3)
    with pytest.raises(check.CheckError, match="did not hold"):
        check.require_held(attempts_record(tmp_path, failed_v2, later_attempt(V3)), V2)
    with pytest.raises(check.CheckError, match="simon.score.v3 did not hold"):
        check.require_held(attempts_record(tmp_path, failed_v2, later_attempt(V3, holds=False)), V3)
    check.require_held(attempts_record(tmp_path, later_attempt(V2), later_attempt(V3, holds=False)), V2)


@capped_only
def test_n4_check_5_on_the_shipped_block_exits_2_when_the_recorded_attempt_did_not_hold(tmp_path, monkeypatch, capsys):
    freeze_by_detection(tmp_path)
    record = score_record(tmp_path, check.score_params_hash())
    doc = json.loads(record.read_text())
    doc["attempts"].append(later_attempt(SHIPPED, holds=False, params_sha256=check.score_params_hash()))
    record.write_text(json.dumps(doc))
    monkeypatch.setattr(check, "SCORE_RECORD", record)
    code, out, err = world(tmp_path, monkeypatch, seed=29).run(capsys)
    assert code == 2 and out == "" and "holds false" in err and "make score-fallback" in err


@capped_only
def test_n4_check_5_on_the_shipped_block_passes_when_the_recorded_attempt_held(tmp_path, monkeypatch, capsys):
    freeze_by_detection(tmp_path)
    record = score_record(tmp_path, check.score_params_hash())
    doc = json.loads(record.read_text())
    doc["attempts"].append(later_attempt(SHIPPED, holds=True, params_sha256=check.score_params_hash()))
    record.write_text(json.dumps(doc))
    monkeypatch.setattr(check, "SCORE_RECORD", record)
    assert world(tmp_path, monkeypatch, seed=29).run(capsys)[0] == 0


@pytest.mark.parametrize("later", [V2, V3])
def test_n4_check_5_on_a_v1_block_passes_with_a_failed_later_attempt_in_the_record(tmp_path, monkeypatch, capsys, later):
    """After `make score-fallback` the rules ship v1 again; the record keeps the freezes and the failed attempts."""
    freeze_by_detection(tmp_path)
    rules = json.loads(check.RULES_PATH.read_text())
    rules["score"] = frozen_v1()
    changed = tmp_path / "rules-v1.json"
    changed.write_text(json.dumps(rules))
    monkeypatch.setattr(check, "RULES_PATH", changed)
    record = attempts_record(tmp_path, later_attempt(later, holds=False), v1_hash=check.score_params_hash(changed))
    monkeypatch.setattr(check, "SCORE_RECORD", record)
    assert world(tmp_path, monkeypatch, seed=29).run(capsys)[0] == 0


# ---------------------------------------------------------------- R-c: a failed attempt recorded without its version is still its version's
def freeze_of(version, **over):
    return {"version": version, "freeze_commit": "abc1234", "params_sha256": "b" * 64, "seed": check.SCORE_SEEDS[version], **over}


@pytest.mark.parametrize("version, seed, adr", LATER)
def test_rc_a_failed_attempt_for_the_versions_seed_without_a_version_is_refused(tmp_path, version, seed, adr):
    versionless = {"seed": seed, "params_sha256": "b" * 64, "holds": False}
    with pytest.raises(check.CheckError) as e:
        check.require_held(attempts_record(tmp_path, versionless), version)
    assert "holds false" in e.value.messages[0] and f"seed {seed}" in e.value.messages[0]
    assert "make score-fallback" in e.value.messages[0]


@pytest.mark.parametrize("version, seed, adr", LATER)
def test_rc_an_attempt_with_the_versions_freeze_hash_is_its_versions_whatever_its_seed_or_version(tmp_path, version, seed, adr):
    other_seed = {"seed": 99, "params_sha256": freeze_of(version)["params_sha256"], "holds": False}
    with pytest.raises(check.CheckError, match="holds false"):
        check.require_held(attempts_record(tmp_path, other_seed, freezes=[freeze_of(version)]), version)
    check.require_held(attempts_record(tmp_path, {**other_seed, "params_sha256": "d" * 64}, freezes=[freeze_of(version)]), version)


@pytest.mark.parametrize("version, seed, adr", LATER)
def test_rc_a_versionless_attempt_that_records_no_holds_fails_closed_and_one_that_held_is_accepted(tmp_path, version, seed, adr):
    with pytest.raises(check.CheckError, match="does not record `holds`"):
        check.require_held(attempts_record(tmp_path, {"seed": seed, "params_sha256": "b" * 64}), version)
    check.require_held(attempts_record(tmp_path, {"seed": seed, "params_sha256": "b" * 64, "holds": True}), version)


@pytest.mark.parametrize("version, seed, adr", LATER)
def test_rc_the_v1_attempts_of_47_and_53_are_not_taken_for_a_later_versions(tmp_path, version, seed, adr):
    """They carry no version and no `holds`, and their hash is v1's, not a freeze's."""
    check.require_held(attempts_record(tmp_path, freezes=[freeze_of(version)]), version)


@pytest.mark.parametrize("version, seed, adr", LATER)
def test_rc_a_v1_block_is_not_judged_by_a_failed_versionless_attempt_for_a_later_seed(tmp_path, version, seed, adr):
    check.require_held(attempts_record(tmp_path, {"seed": seed, "params_sha256": "b" * 64, "holds": False}), V1)


@pytest.mark.parametrize("version, seed, adr", LATER)
def test_adr_0019_the_v1_hash_is_not_taken_from_a_later_attempt_whether_or_not_it_names_its_version(tmp_path, version, seed, adr):
    """A failed v3 attempt written without its `version` (or a v2 one) must not become the hash a v1 block is checked against."""
    bare = {"seed": seed, "params_sha256": "c" * 64, "holds": False}
    by_hash = {"seed": 99, "params_sha256": "e" * 64}
    path = attempts_record(tmp_path, bare, by_hash, freezes=[freeze_of(version, params_sha256="e" * 64)])
    assert check.recorded_score_hash(path, V1) == "a" * 64
    assert check.recorded_score_hash(path, version) == "e" * 64


def test_adr_0019_a_v2_freeze_does_not_stand_in_for_v3s_and_two_v3_freezes_are_refused_not_taken_for_the_newest(tmp_path):
    path = tmp_path / "score-heldout.json"
    path.write_text(json.dumps({"attempts": [], "freezes": [{"version": V2, "params_sha256": "a" * 64}]}))
    assert check.recorded_score_hash(path, V3) is None and check.recorded_score_hash(path, V2) == "a" * 64   # v2's freeze is not v3's
    check.require_held(path, V3)   # and a v2 freeze beside none of v3's is nothing to refuse
    path.write_text(json.dumps({"attempts": [], "freezes": [
        {"version": V2, "params_sha256": "a" * 64}, {"version": V3, "params_sha256": "b" * 64}, {"version": V3, "params_sha256": "c" * 64}]}))
    with pytest.raises(check.CheckError, match="holds 2 simon.score.v3 freeze entries.*re-freeze.*ADR-0019"):
        check.require_held(path, V3)
    check.require_held(path, V2)   # one v2 freeze: not refused, whatever v3's record holds


@capped_only
def test_rc_check_5_on_the_shipped_block_exits_2_for_a_failed_attempt_recorded_without_its_version(tmp_path, monkeypatch, capsys):
    freeze_by_detection(tmp_path)
    record = score_record(tmp_path, check.score_params_hash())
    doc = json.loads(record.read_text())
    doc["attempts"].append({"seed": check.SCORE_SEEDS[SHIPPED], "params_sha256": check.score_params_hash(), "holds": False})
    record.write_text(json.dumps(doc))
    monkeypatch.setattr(check, "SCORE_RECORD", record)
    code, out, err = world(tmp_path, monkeypatch, seed=29).run(capsys)
    assert code == 2 and out == "" and "holds false" in err and "make score-fallback" in err


# ---------------------------------------------------------------- R1: a retune after the seed was scored is refused
@capped_only
def test_r1_a_second_freeze_after_a_passing_attempt_is_refused_by_check_5(tmp_path, monkeypatch, capsys):
    """The review's scenario: freezes [scored, X], X the block now shipped (a retune that was never scored), and the seed's attempt
    held with the scored block's hash. The newest freeze X used to pass both the freeze check and the held check. Now the record
    is refused for holding two freezes."""
    freeze_by_detection(tmp_path)
    scored = "f" * 64
    record = score_record(tmp_path, scored, check.score_params_hash())
    doc = json.loads(record.read_text())
    doc["attempts"].append(later_attempt(SHIPPED, holds=True, params_sha256=scored))
    record.write_text(json.dumps(doc))
    monkeypatch.setattr(check, "SCORE_RECORD", record)
    code, out, err = world(tmp_path, monkeypatch, seed=29).run(capsys)
    assert code == 2 and out == "" and f"holds 2 {SHIPPED} freeze entries" in err and "re-freeze" in err


@pytest.mark.parametrize("version, seed, adr", LATER)
def test_r1_the_shipped_hash_must_be_the_one_the_recorded_attempt_was_scored_with(tmp_path, version, seed, adr):
    path = attempts_record(tmp_path, later_attempt(version, params_sha256="b" * 64))
    check.require_held(path, version, "b" * 64)   # scored with exactly this block
    with pytest.raises(check.CheckError) as e:
        check.require_held(path, version, "c" * 64)
    assert f"{version} attempt for seed {seed}" in e.value.messages[0] and "scored with the score params of sha256 bbbbbbbbbbbb" in e.value.messages[0]
    assert "ccccccccccc" in e.value.messages[0] and adr in e.value.messages[0]


@pytest.mark.parametrize("version, seed, adr", LATER)
def test_r1_an_attempt_that_records_no_params_hash_cannot_show_the_block_was_scored(tmp_path, version, seed, adr):
    attempt = later_attempt(version)
    del attempt["params_sha256"]
    with pytest.raises(check.CheckError, match="scored with the score params of sha256 None"):
        check.require_held(attempts_record(tmp_path, attempt), version, "c" * 64)
    check.require_held(attempts_record(tmp_path, attempt), version)   # callers that give no hash (the lookup tests) are not asked


def test_r1_holds_false_is_still_the_first_reason_given(tmp_path):
    path = attempts_record(tmp_path, later_attempt(V3, holds=False, params_sha256="b" * 64))
    with pytest.raises(check.CheckError, match="holds false"):
        check.require_held(path, V3, "c" * 64)


@capped_only
def test_r1_check_5_exits_2_when_the_shipped_block_differs_from_the_one_the_attempt_was_scored_with(tmp_path, monkeypatch, capsys):
    """One freeze (the shipped block's, so the freeze check passes) and an attempt that held, recorded with another block's hash."""
    freeze_by_detection(tmp_path)
    record = score_record(tmp_path, check.score_params_hash())
    doc = json.loads(record.read_text())
    doc["attempts"].append(later_attempt(SHIPPED, holds=True, params_sha256="d" * 64))
    record.write_text(json.dumps(doc))
    monkeypatch.setattr(check, "SCORE_RECORD", record)
    code, out, err = world(tmp_path, monkeypatch, seed=29).run(capsys)
    assert code == 2 and out == "" and "scored with the score params of sha256 dddddddddddd" in err
