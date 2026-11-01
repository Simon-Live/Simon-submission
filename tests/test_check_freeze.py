"""`make check-5`, the freeze and the attempts (docs/specs/check-5.md; ADR-0003, ADR-0017; AC-K07, AC-K08, AC-K09,
pre-freeze review B3 and R7): the rules must be the ones frozen for the seed, a seed is scored once and in order, and an
attempt's record is the one `make check-5` reads.

Split out of tests/test_check.py when that file passed 800 lines (recheck residual 9); no test was lost or changed in the
move. The synthetic world (the analyse table, the temp labels, the freeze record) is the one tests/test_check.py builds.
"""
import json
import re

import pytest

from part5 import check
from test_check import ROOT, RULES_SHA, World, errors_of, freeze_section, green, world

IN_FORCE_SEEDS = [71, 73]    # the seeds scored under part5/rules.json as it is: attempt 5 and its confirmation
IN_FORCE_FREEZE = "4c55af0"  # the one freeze commit they share


def test_ac_k07_exits_2_when_rules_changed_after_the_freeze(tmp_path, monkeypatch, capsys):
    (tmp_path / "thresholds.md").write_text(freeze_section(29, sha="0" * 64))
    code, out, err = world(tmp_path, monkeypatch, seed=29).run(capsys)
    assert code == 2 and out == ""
    assert "part5/rules.json differs from the hash frozen for seed 29 in docs/thresholds.md" in err
    assert not (tmp_path / "out/metrics.json").exists()


def recorded_scores(sha=None):
    """A `## Score` section whose `detection_sha256` is that of part5/rules.json now (the current freeze)."""
    return f"\n## Score\n\n### Freeze check\ndetection_sha256: `{sha or check.detection_hash()}`\n"


def test_b3_a_scored_seed_is_checked_against_its_own_freeze_and_is_refused_before_any_analysis(tmp_path, monkeypatch, capsys):
    """Pre-freeze review B3: the `detection_sha256` under "Score" is the current freeze, so it equalled the rules and
    `require_frozen` let the retired seed 37 through; `analyse_set` ran and only `require_unchanged_scores` refused,
    after the rescore. Seed 37's own record holds the detection hash it was frozen with, which differs: refused first."""
    own = "1" * 64
    (tmp_path / "thresholds.md").write_text(
        f"## Attempt 3: seed 37\nFreeze commit: `abc1234`\nrules_sha256: `{'0' * 64}`\ndetection_sha256: `{own}`\n"
        "Approach family: a new measure\n" + recorded_scores())
    w = world(tmp_path, monkeypatch, seed=37)
    w.attempts([recorded(s, False) for s in (29, 31, 37)])
    spied = []
    monkeypatch.setattr(check, "analyse_set", lambda *a, **k: spied.append(a) or ({}, []))
    code, out, err = w.run(capsys)
    assert code == 2 and out == "" and spied == []       # nothing was analysed: no take of the held-out set was scored
    assert "seed 37" in err and "differs from the hash frozen for seed 37" in err and "retired" in err
    assert not (tmp_path / "out/metrics.json").exists()


def test_b3_the_current_freeze_still_covers_a_seed_not_scored_yet_and_a_score_only_edit(tmp_path, monkeypatch, capsys):
    """A seed that has no attempt yet is frozen by the record the orchestrator writes for it: its own detection hash
    when it has the line, else the one under "Score". A change that leaves the detection rules alone (a score edit)
    still passes the detection check for a scored seed whose own record says so."""
    current = check.detection_hash()
    for section in (f"## Attempt 4: seed 29\nFreeze commit: `abc1234`\nrules_sha256: `{'0' * 64}`\n" + recorded_scores(),
                    f"## Attempt 4: seed 29\nFreeze commit: `abc1234`\nrules_sha256: `{'0' * 64}`\n"
                    f"detection_sha256: `{current}`\n"):
        (tmp_path / "thresholds.md").write_text(section)
        code, out, err = world(tmp_path, monkeypatch, seed=29).run(capsys)
        assert code == 0, err
    # a scored seed whose own record carries the current detection hash passes (only its score block moved)
    (tmp_path / "thresholds.md").write_text(f"## Attempt 1: seed 29\nFreeze commit: `abc1234`\n"
                                            f"rules_sha256: `{'0' * 64}`\ndetection_sha256: `{current}`\n")
    w = world(tmp_path, monkeypatch, seed=29)
    first = json.loads(w.run(capsys)[1])
    w.attempts([{**recorded(29, True), "slices": first["gate"]["metrics"]["slices"]}])
    assert w.run(capsys)[0] == 0


def test_b3_a_new_attempt_4_record_on_seed_67_is_found_and_freezes_the_current_rules(tmp_path, monkeypatch, capsys):
    """`thresholds_record` finds the `### Attempt 4: seed 67` heading as it found the others; the record the orchestrator
    writes at the freeze (the file hash, or the detection hash when only the score block moved) lets seed 67 through, and
    the three retired seeds before it do not."""
    current = check.detection_hash()
    older = [recorded(s, False) for s in (29, 31, 37)]
    for record in (f"### Attempt 4: seed 67\nFreeze commit: `abc1234`\nrules_sha256: `{RULES_SHA}`\nDate: 2026-11-01\n",
                   f"### Attempt 4: seed 67\nFreeze commit: `abc1234`\nrules_sha256: `{'0' * 64}`\n"
                   f"detection_sha256: `{current}`\nApproach family: persistence per rep\n"):
        (tmp_path / "thresholds.md").write_text(record + recorded_scores())
        w = world(tmp_path, monkeypatch, seed=67)
        w.attempts(older)
        code, out, err = w.run(capsys)
        assert code == 0 and json.loads(out)["gate"]["seed"] == 67, err
        assert [a["seed"] for a in json.loads(out)["attempts"]] == [29, 31, 37, 67]


def test_b3_require_frozen_cases():
    frozen = {"rules_sha256": "a" * 64, "detection_sha256": "d" * 64}
    cases = [  # (frozen record, sha, detection, the one under "Score", scored) -> passes
        (frozen, "a" * 64, "x" * 64, "x" * 64, True),     # the whole file is the frozen one
        (frozen, "b" * 64, "d" * 64, "x" * 64, True),     # only the score block moved
        (frozen, "b" * 64, "x" * 64, "x" * 64, True),     # the current freeze is not this seed's: refused
        ({"rules_sha256": "a" * 64}, "b" * 64, "x" * 64, "x" * 64, True),    # a scored seed without its own line: refused
        ({"rules_sha256": "a" * 64}, "b" * 64, "x" * 64, "x" * 64, False),   # not scored yet: the current freeze's hash
        ({"rules_sha256": "a" * 64}, "b" * 64, "y" * 64, "x" * 64, False),   # not scored yet and changed: refused
        (frozen, "b" * 64, "x" * 64, "x" * 64, False),                       # its own line wins over the current freeze's
    ]
    outcomes = []
    for record, sha, detection, current, scored in cases:
        try:
            check.require_frozen(37, sha, record, detection, current, scored)
            outcomes.append(True)
        except check.CheckError:
            outcomes.append(False)
    assert outcomes == [True, True, False, False, True, False, False]


def test_b3_the_committed_record_refuses_every_scored_seed_under_other_rules():
    """Each scored attempt carries its own detection hash. A seed scored under other rules than the current ones
    stops at the freeze check before analysing a take; only the newest scored attempts (an attempt and its confirmation) can have been scored under the
    rules in force, and they pass the check, so the done-check can reproduce their recorded numbers. The seeds that pass
    are pinned (`IN_FORCE_SEEDS`: 71 and 73 today). Between a candidate's rules change and the scoring of its seed
    (attempt 5 before seed 71) no scored seed holds the rules in force, so none passes and the pin is edited with the
    new freeze."""
    text = (ROOT / "docs/thresholds.md").read_text()
    current = check.detection_hash()
    passed_under_current = []
    scored = json.loads(check.ATTEMPTS.read_text())["attempts"]
    for a in scored:
        record = check.thresholds_record(a["seed"], text)
        assert re.fullmatch("[0-9a-f]{64}", record.get("detection_sha256", "")), a["seed"]
        if record["detection_sha256"] == current:
            check.require_frozen(a["seed"], check.rules_hash(), record, current,
                                 check.recorded_detection_hash(text), scored=True)
            passed_under_current.append(a["seed"])
            continue
        with pytest.raises(check.CheckError, match=f"differs from the hash frozen for seed {a['seed']}"):
            check.require_frozen(a["seed"], check.rules_hash(), record, current,
                                 check.recorded_detection_hash(text), scored=True)
    # The seeds scored under the rules in force are exactly attempt 5 on seed 71 and its confirmation, attempt 6 on
    # seed 73, both frozen at 4c55af0, and they are the newest scored seeds. Put rules.json back to an earlier attempt's
    # bytes and this list is shorter; change the rules for a new candidate and it is empty until that candidate is
    # scored: the list is then edited on purpose, with the new freeze, and not loosened to "any newest seeds"
    # (TICKET-051, pre-freeze review of attempt 5, residual 5).
    assert passed_under_current == IN_FORCE_SEEDS
    assert [a["seed"] for a in scored[-len(IN_FORCE_SEEDS):]] == IN_FORCE_SEEDS
    assert {a["freeze_commit"][:7] for a in scored if a["seed"] in IN_FORCE_SEEDS} == {IN_FORCE_FREEZE}


def test_ac_k07_exits_2_when_the_current_seed_has_no_freeze_record(tmp_path, monkeypatch, capsys):
    # A record for another seed does not freeze this one; neither does a section without a hash.
    for text in (freeze_section(31), "## Attempt 1: seed 29\nFreeze commit: `abc1234`\n", ""):
        (tmp_path / "thresholds.md").write_text(text)
        code, out, err = world(tmp_path, monkeypatch, seed=29).run(capsys)
        assert code == 2 and out == ""
        assert "docs/thresholds.md has no freeze record (rules_sha256) for seed 29" in err


def test_ac_k07_exits_2_when_thresholds_md_is_missing(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch, seed=29)
    (tmp_path / "thresholds.md").unlink()
    code, out, err = w.run(capsys)
    assert code == 2 and out == "" and "no freeze record" in err


def test_ac_k07_an_attempts_entry_does_not_stand_in_for_the_freeze_record(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch, seed=29)
    (tmp_path / "thresholds.md").write_text("")
    w.attempts([{**recorded(29, True), "rules_sha256": RULES_SHA}])
    assert w.run(capsys)[0] == 2


def test_ac_k07_gate_seed_is_read_from_the_labels_for_each_held_out_seed(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch, seed=31)
    w.attempts([recorded(29, True)])      # the seeds are scored in order: 31 follows a scored 29 (R7)
    code, out, _ = w.run(capsys)
    assert code == 0 and json.loads(out)["gate"]["seed"] == 31


@pytest.mark.parametrize("seed", [5, 28, 30, 59, 61, 99])
def test_a_seed_that_is_not_a_held_out_seed_exits_2_naming_it(tmp_path, monkeypatch, capsys, seed):
    """59 and 61 are reserved for the score's retries (ADR-0007); they are not held-out detection seeds."""
    code, out, err = world(tmp_path, monkeypatch, seed=seed).run(capsys)
    assert code == 2 and out == "" and f"names seed {seed}" in err and "29, 31, 37, 67, 71, 73" in err


def test_the_held_out_seeds_are_the_two_series_in_order():
    """ADR-0017: the second series 67, 71, 73 follows 29, 31, 37, fixed before any detection change of attempt 4."""
    assert check.HELDOUT_SEEDS == (29, 31, 37, 67, 71, 73)
    assert not {59, 61, 41, 43, 47, 53} & set(check.HELDOUT_SEEDS)   # the score protocol's seeds (ADR-0007)


@pytest.mark.parametrize("scored, wanted", [([], 29), ([29], 31), ([29, 31], 37), ([29, 31, 37], 67),
                                            ([29, 31, 37, 67], 71), ([29, 31, 37, 67, 71], 73),
                                            ([29, 31, 37, 67, 71, 73], None)])
def test_the_next_unused_seed_runs_through_both_series_with_none_skipped(scored, wanted):
    assert check.next_unused_seed([{"seed": s} for s in scored]) == wanted


def test_attempts_list_orders_the_second_series_after_the_first():
    current = {"seed": 67, "passed": False}
    earlier = [{"seed": 37}, {"seed": 29}, {"seed": 31}]
    assert [a["seed"] for a in check.attempts_list(67, current, earlier)] == [29, 31, 37, 67]
    assert [a["seed"] for a in check.attempts_list(71, {"seed": 71}, earlier + [current])] == [29, 31, 37, 67, 71]


def test_a_seed_of_the_second_series_is_accepted_once_the_first_series_is_scored(tmp_path):
    attempts = [{"seed": s} for s in (29, 31, 37)]
    check.check_seed(67, attempts, tmp_path)         # the next unused seed: no error
    with pytest.raises(check.CheckError, match=r"seed 37 is retired: seed 67 was already scored.*71"):
        check.check_seed(37, attempts + [{"seed": 67}], tmp_path)
    with pytest.raises(check.CheckError, match="names seed 41"):
        check.check_seed(41, attempts, tmp_path)


def test_r7_a_seed_that_skips_the_next_unused_one_is_refused(tmp_path):
    """Pre-freeze review R7: 71 while 67 is unscored (or 37 while 31 is) is refused before anything is analysed."""
    scored = [{"seed": s} for s in (29, 31, 37)]
    with pytest.raises(check.CheckError, match=r"seed 71 skips seed 67, which is not scored yet.*\(67\)"):
        check.check_seed(71, scored, tmp_path)
    with pytest.raises(check.CheckError, match=r"seed 37 skips seed 31"):
        check.check_seed(37, scored[:1], tmp_path)
    with pytest.raises(check.CheckError, match=r"seed 31 skips seed 29"):
        check.check_seed(31, [], tmp_path)
    check.check_seed(29, [], tmp_path)                       # the first seed
    check.check_seed(67, scored, tmp_path)                   # the next unused seed
    check.check_seed(37, scored, tmp_path)                   # the latest scored seed, rerun only to verify it
    check.check_seed(31, scored[:2], tmp_path)


def test_r7_run_check_refuses_a_skipped_seed_before_it_analyses_anything(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch, seed=31)             # no seed is scored yet: 29 is next
    monkeypatch.setattr(check, "analyse_set", lambda *a, **k: pytest.fail("analysed a skipped seed"))
    code, out, err = w.run(capsys)
    assert code == 2 and out == "" and "seed 31 skips seed 29" in err


def test_the_tuning_set_must_be_seed_5(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    w.add("heldout", 29, *green("h"))
    w.add("followers", 29, *green("t", dropout=False))
    code, out, err = w.run(capsys)
    assert code == 2 and "tuning set is seed 5" in err


def test_a_held_out_set_that_is_not_generated_yet_exits_2_naming_the_command(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    w.add("followers", 5, *green("t", dropout=False))
    code, out, err = w.run(capsys)
    assert code == 2 and out == "" and "has no labels.json" in err and "make heldout-data SEED=29" in err


def test_the_hint_names_the_next_unused_seed(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    w.add("followers", 5, *green("t", dropout=False))
    w.attempts([{"seed": 29, "freeze_commit": "abc1234", "rules_sha256": "a" * 64, "approach": "rules",
                 "passed": False, "slices": {}}])
    code, _, err = w.run(capsys)
    assert code == 2 and "make heldout-data SEED=31" in err


def test_ac_k08_a_take_whose_file_is_missing_exits_2_naming_the_take(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch)
    (tmp_path / "h_45_good_clean_f1.json").unlink()
    code, out, err = w.run(capsys)
    assert code == 2 and out == ""
    assert "check-5: h_45_good_clean_f1: h_45_good_clean_f1.json not found" in err


def test_ac_k08_every_unanalysable_take_is_named(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch)
    (tmp_path / "h_45_good_clean_f1.json").unlink()
    (tmp_path / "t_side_low_clean_c0.json").unlink()
    code, _, err = w.run(capsys)
    assert code == 2 and "h_45_good_clean_f1" in err and "t_side_low_clean_c0" in err


def test_ac_k08_an_analysis_error_exits_2_naming_the_take(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch)

    def boom(expected, follower):
        raise ValueError("only 20% of the body could be measured")

    monkeypatch.setattr(check, "analyse", boom)
    code, out, err = w.run(capsys)
    assert code == 2 and out == "" and "only 20% of the body could be measured" in err


def recorded(seed, passed, commit="abc1234"):
    return {"seed": seed, "freeze_commit": commit, "rules_sha256": "a" * 64, "approach": f"family {seed}",
            "passed": passed, "slices": {"good/front": {"tp": 1, "fp": 0, "fn": 0, "takes": 1, "correct_takes": 0,
                                                       "faults_on_correct_takes": 0, "precision": 1.0, "recall": 1.0}}}


def test_ac_k09_a_red_then_a_green_attempt_are_both_listed_and_the_exit_follows_the_current(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch, seed=31)
    w.attempts([recorded(29, False)])
    code, out, _ = w.run(capsys)
    doc = json.loads(out)
    assert code == 0 and [a["seed"] for a in doc["attempts"]] == [29, 31]
    assert [a["passed"] for a in doc["attempts"]] == [False, True]
    assert doc["attempts"][0] == recorded(29, False)  # earlier attempts are published as recorded
    assert doc["attempts"][-1]["slices"] == doc["gate"]["metrics"]["slices"]
    assert doc["attempts"][-1]["passed"] == doc["gate"]["passed"]
    assert errors_of(doc) == []


def test_ac_k09_a_green_then_a_red_attempt_exits_1(tmp_path, monkeypatch, capsys):
    held = green("h", {("front", "good", "clean"): {"miss": 3}})
    w = world(tmp_path, monkeypatch, seed=31, held=held)
    w.attempts([recorded(29, True)])
    code, out, _ = w.run(capsys)
    doc = json.loads(out)
    assert code == 1 and [a["passed"] for a in doc["attempts"]] == [True, False]
    assert doc["attempts"][-1]["passed"] is False and doc["gate"]["passed"] is False


def test_ac_k09_rerunning_the_current_set_lists_it_once_and_keeps_its_freeze_commit(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch, seed=29)
    _, first, _ = w.run(capsys)
    slices = json.loads(first)["gate"]["metrics"]["slices"]
    w.attempts([{**recorded(29, True, commit="feedbee"), "slices": slices}])
    code, out, _ = w.run(capsys)
    doc = json.loads(out)
    assert code == 0 and len(doc["attempts"]) == 1
    assert doc["attempts"][0]["freeze_commit"] == "feedbee" and doc["attempts"][0]["passed"] is True


ATTEMPT_CORE = ["seed", "freeze_commit", "rules_sha256", "approach", "passed", "slices"]
SCORED_FIELDS = {"scored": "2026-11-01", "scored_at": "47fce0ca21b05d7b4c4ce9e183a981c56e727580",
                 "command": "make check-5", "exit": 0}


def test_r4a_a_recorded_seed_carries_every_field_of_its_record(tmp_path, monkeypatch, capsys):
    """TICKET-058 R4a: the rerun of the newest scored seed lists the entry with every recorded field, as the earlier
    attempts are listed, a field this code does not know about included; the six core fields keep their order."""
    w = world(tmp_path, monkeypatch, seed=29)
    slices = json.loads(w.run(capsys)[1])["gate"]["metrics"]["slices"]
    record = {**recorded(29, True, commit="feedbee"), "slices": slices, **SCORED_FIELDS, "note": "kept verbatim"}
    w.attempts([record])
    code, out, _ = w.run(capsys)
    entry = json.loads(out)["attempts"][0]
    assert code == 0 and entry == record
    assert list(entry) == ATTEMPT_CORE + ["scored", "scored_at", "command", "exit", "note"]


def test_r4a_a_seed_with_no_record_keeps_the_six_core_fields(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch, seed=31)
    w.attempts([recorded(29, False)])
    code, out, _ = w.run(capsys)
    doc = json.loads(out)
    assert code == 0 and list(doc["attempts"][-1]) == ATTEMPT_CORE   # the current, unrecorded attempt
    assert list(doc["attempts"][0]) == ATTEMPT_CORE                  # a record that has only the core fields


def test_r4a_with_no_attempts_file_at_all_the_entry_has_the_six_core_fields(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch, seed=29)
    code, out, _ = w.run(capsys)
    assert code == 0 and list(json.loads(out)["attempts"][0]) == ATTEMPT_CORE


def test_r4a_current_attempt_keeps_this_runs_gate_and_numbers_over_the_record():
    live = {"slices": {"good/front": {"tp": 2}}}
    record = {**recorded(73, False), **SCORED_FIELDS}
    entry = check.current_attempt(73, True, live, "b" * 64, dict(record), record)
    assert entry["passed"] is True and entry["slices"] == live["slices"]          # this run's, as before
    assert {k: entry[k] for k in SCORED_FIELDS} == SCORED_FIELDS
    assert entry["freeze_commit"] == record["freeze_commit"] and entry["rules_sha256"] == record["rules_sha256"]
    assert list(check.current_attempt(73, True, live, "b" * 64, {}, None)) == ATTEMPT_CORE
    assert list(check.current_attempt(73, True, live, "b" * 64, {}, {})) == ATTEMPT_CORE


def test_r4a_the_committed_record_of_every_scored_seed_comes_out_whole():
    """The committed fixtures/heldout-attempts.json: the entry built for any of its seeds has every key and value of it."""
    for rec in check.load_attempts(check.ATTEMPTS):
        entry = check.current_attempt(rec["seed"], rec["passed"], {"slices": rec["slices"]}, rec["rules_sha256"],
                                      dict(rec), rec)
        assert entry == rec and list(entry) == list(rec)
        assert {"scored", "scored_at", "command", "exit"} <= set(entry)


def test_a_scored_seed_that_scores_differently_from_its_record_exits_2(tmp_path, monkeypatch, capsys):
    """ADR-0003: a retired seed is only verified; changed scores mean scoring changed after the freeze."""
    w = world(tmp_path, monkeypatch, seed=29)
    w.attempts([recorded(29, True, commit="feedbee")])  # its slices differ from this world's scores
    code, out, err = w.run(capsys)
    assert code == 2 and out == "" and "scores differently from its recorded attempt" in err and "good/45" in err


def test_a_retired_seed_is_refused(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch, seed=29)
    w.attempts([recorded(29, False), recorded(31, False)])
    code, out, err = w.run(capsys)
    assert code == 2 and out == "" and "seed 29 is retired" in err and "37" in err


# ----------------------------------------------------------------- recheck residual 4: each scored seed's own line
def second_series_world(tmp_path, monkeypatch, record):
    """Seed 67 in a temp world whose thresholds.md holds `record` (the text of its section, and what follows)."""
    (tmp_path / "thresholds.md").write_text(record)
    return world(tmp_path, monkeypatch, seed=67)


def test_r4_a_scored_seed_of_the_second_series_needs_its_own_detection_line_and_is_refused_before_analysis(
        tmp_path, monkeypatch, capsys):
    """Recheck residual 4: seed 67 is scored (it has an attempt) and its record has the right `rules_sha256` but no
    `detection_sha256` line of its own. The record cannot say what it was scored with, so the check refuses before it
    analyses a take, though the rules hash matches."""
    record = (f"### Attempt 4: seed 67\nFreeze commit: `abc1234`\nrules_sha256: `{RULES_SHA}`\n"
              "Approach family: persistence per rep\n" + recorded_scores())
    w = second_series_world(tmp_path, monkeypatch, record)
    w.attempts([recorded(s, False) for s in (29, 31, 37, 67)])
    spied = []
    monkeypatch.setattr(check, "analyse_set", lambda *a, **k: spied.append(a) or ({}, []))
    code, out, err = w.run(capsys)
    assert code == 2 and out == "" and spied == []
    assert "no detection_sha256 line in the attempt record of seed 67" in err
    assert not (tmp_path / "out/metrics.json").exists()


def test_r4_the_line_is_required_only_once_the_seed_is_scored_and_only_in_the_second_series():
    """A seed with no attempt yet (the freeze record the orchestrator writes) is judged as before, and the legacy seeds
    29, 31 and 37 keep the rule they were recorded under: `require_frozen` asks for the line for none of them."""
    frozen, det = {"rules_sha256": RULES_SHA}, check.detection_hash()
    check.require_frozen(67, RULES_SHA, frozen, det, det, scored=False)          # not scored yet: no line needed
    for seed in (29, 31, 37):
        check.require_frozen(seed, RULES_SHA, frozen, det, det, scored=True)     # the first series: as recorded
    for seed in (67, 71, 73):
        with pytest.raises(check.CheckError, match=f"no detection_sha256 line in the attempt record of seed {seed}"):
            check.require_frozen(seed, RULES_SHA, frozen, det, det, scored=True)
        check.require_frozen(seed, RULES_SHA, {**frozen, "detection_sha256": det}, det, det, scored=True)
    assert check.SECOND_SERIES == (67, 71, 73)


def test_r4_known_limit_the_line_hashes_the_rules_not_the_code_and_the_recorded_numbers_are_the_guard(
        tmp_path, monkeypatch, capsys):
    """Stakeholder-proxy ruling on recheck residual 4, pinned. What the per-attempt line covers: the bytes of rules.json.
    What it does not: a deliberate revert of rules.json to a retired attempt's bytes, under later code, passes
    `require_frozen` (the hash is the attempt's own; there is no code-diff requirement on `part5/`). The guard is the
    check after the analysis, `require_unchanged_scores`: numbers that differ from the recorded attempt are refused
    (exit 2), and only numbers that match it to the last digit pass, which is the limit."""
    own = check.detection_hash()
    record = (f"### Attempt 4: seed 67\nFreeze commit: `abc1234`\nrules_sha256: `{'0' * 64}`\ndetection_sha256: `{own}`\n"
              "Approach family: persistence per rep\n")
    frozen = check.thresholds_record(67, record)
    check.require_frozen(67, RULES_SHA, frozen, own, None, scored=True)     # the reverted bytes are its own: not caught here
    older = [recorded(s, False) for s in (29, 31, 37)]
    w = second_series_world(tmp_path, monkeypatch, record)
    w.attempts(older + [recorded(67, True)])                                # later code scores seed 67 differently
    code, out, err = w.run(capsys)
    assert code == 2 and out == "" and "seed 67 scores differently from its recorded attempt" in err
    w.attempts(older)
    slices = json.loads(w.run(capsys)[1])["gate"]["metrics"]["slices"]
    w.attempts(older + [{**recorded(67, True), "slices": slices}])         # the same numbers: nothing can tell
    assert w.run(capsys)[0] == 0


