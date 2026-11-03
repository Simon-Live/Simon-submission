"""TICKET-220: the history faithfulness eval harness, every metric on canned answers (docs/specs/history-eval.md).

No paid call and no network: answers come from `ScriptedTransport`, the fake of the Meta transport. The model answers
below are HAND-WRITTEN TEST FIXTURE text, not model output.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

import history_eval as ev
from part7 import history_api, history_facts, history_longpack, history_prompt

CASES = {c["id"]: c for c in ev.load_cases()}


def run_answers(case_id: str, answers: list[Any], tmp_path: Path, packer: Any = ev.digest_packer) -> list[dict[str, Any]]:
    case = CASES[case_id]
    transport = ev.ScriptedTransport(answers)
    return [ev.run_once(case, packer, transport, tmp_path) for _ in answers]


def scored(case_id: str, answers: list[Any], tmp_path: Path) -> dict[str, Any]:
    return ev.score_case(CASES[case_id], run_answers(case_id, answers, tmp_path))


def good(case_id: str) -> dict[str, Any]:
    return copy.deepcopy(CASES[case_id]["answers"][0])


# ----- the fixtures -------------------------------------------------------------------------------
def test_at_least_ten_cases_each_labelled_with_expected_facts():
    assert len(CASES) >= 10
    for case in CASES.values():
        assert case["origin"] in ("synthetic", "real") and case["note"] and "statuses" in case["expect"]
    assert any(c["origin"] == "real" for c in CASES.values()) and any(c["origin"] == "synthetic" for c in CASES.values())


def test_expected_statuses_are_what_the_product_fact_table_computes():
    for case in CASES.values():
        facts = case["facts"]
        recomputed = history_facts.measures([t for t in facts["takes"] if t["in_group"]])
        assert recomputed == facts["measures"], case["id"]
        assert case["expect"]["statuses"] == {f"{m['measure']}|{m['side']}": m["status"] for m in recomputed}


def test_update_fixture_is_came_back_and_middle_fixture_has_the_fault_only_in_take_15():
    assert CASES["came_back_update"]["expect"]["statuses"]["trunk_lean_forward|center"] == "came_back"
    middle = CASES["middle_of_thirty"]
    assert len(middle["facts"]["takes"]) == 30
    assert [t["take"] for t in middle["facts"]["takes"] if t["faults"]] == [15]


# ----- every case, canned good answers --------------------------------------------------------------
def test_canned_good_answers_are_kept_whole_and_meet_every_expectation(tmp_path: Path):
    run = ev.evaluate(list(CASES.values()))
    assert run["mode"] == "canned" and run["spend_usd"] == 0.0 and run["stopped"] is None
    m = run["metrics"]
    assert m["errors"] == 0 and m["guard_pass_rate"]["all"] == 1.0 and m["coverage"]["rate"] == 1.0
    for name in ("focus", "update", "middle", "distractor_never_cited", "abstention"):
        assert m[name]["total"] >= 1 and m[name]["rate"] == 1.0, name
    assert 0 < m["stability"] < 1  # the persistent case varies on purpose


# ----- guard pass rate per rule -----------------------------------------------------------------------
def test_guard_pass_rate_counts_each_rejecting_rule(tmp_path: Path):
    answer = good("persistent_stability")
    bad = copy.deepcopy(answer["trends"][0])
    answer["trends"] = [answer["trends"][0],
                        {**bad, "cites": [{"take": 9, "at_s": None}]},            # rule 1
                        {**bad, "text": "A great start at 0.9 s in take 3."},     # rule 6
                        {**bad, "kind": "new"}]                                    # rule 3
    result = scored("persistent_stability", [answer], tmp_path)
    assert result["guard"] == {"items": 6, "by_rule": {"1": 1, "3": 1, "6": 1}}
    rates = ev.pass_rates([result["guard"]])
    assert rates["1"] == rates["3"] == rates["6"] == 0.8333 and rates["2"] == 1.0 and rates["all"] == 0.5


def test_guard_pass_rate_has_no_number_without_items():
    assert ev.pass_rates([])["all"] is None
    assert ev.guard_stats("not json", [{"item": "answer", "rule": None, "reason": "x"}]) == {"items": 0, "by_rule": {}}


# ----- coverage -----------------------------------------------------------------------------------
def test_coverage_counts_persistent_new_and_came_back_a_kept_trend_names(tmp_path: Path):
    full = scored("mixed_statuses", [good("mixed_statuses")], tmp_path)
    assert full["coverage"] == {"hit": 2, "total": 2}  # the fixed hip shift is not counted
    answer = good("mixed_statuses")
    answer["trends"] = answer["trends"][:1]
    assert scored("mixed_statuses", [answer], tmp_path)["coverage"] == {"hit": 1, "total": 2}
    assert scored("abstain_clean", [good("abstain_clean")], tmp_path)["coverage"] == {"hit": 0, "total": 0}


def test_coverage_needs_the_same_kind_and_side(tmp_path: Path):
    answer = good("sides")
    answer["trends"][1]["side"] = "left"  # the right knee claim now names the left side: rule 3 drops it
    assert scored("sides", [answer], tmp_path)["coverage"] == {"hit": 1, "total": 2}


# ----- focus ----------------------------------------------------------------------------------------
def test_focus_correct_only_with_the_expected_measure_side_and_cue(tmp_path: Path):
    assert scored("persistent_stability", [good("persistent_stability")], tmp_path)["focus"] is True
    wrong = good("sides")
    wrong["focus"].update(side="right", text="Work on the right knee cave at 2.0 s in take 3.")
    assert scored("sides", [wrong], tmp_path)["focus"] is False  # the guard keeps it, the case expects the left side
    none = good("persistent_stability")
    none["focus"] = None
    assert scored("persistent_stability", [none], tmp_path)["focus"] is False
    assert scored("fixed", [good("fixed")], tmp_path)["focus"] is None


# ----- update test ----------------------------------------------------------------------------------
def test_update_test_passes_for_came_back_and_fails_for_a_missing_or_improved_claim(tmp_path: Path):
    assert scored("came_back_update", [good("came_back_update")], tmp_path)["update"] is True
    improved = good("came_back_update")
    improved["trends"][0]["kind"] = "improved"
    result = scored("came_back_update", [improved], tmp_path)
    assert result["update"] is False and result["rejected"][0]["rule"] == 3  # the guard never shows it
    silent = good("came_back_update")
    silent["trends"] = []
    assert scored("came_back_update", [silent], tmp_path)["update"] is False
    assert ev.update_test({"trends": [{"kind": "came_back", "measure": "m", "side": "s"},
                                      {"kind": "improved", "measure": "m", "side": "s"}]},
                          {"came_back": [{"measure": "m", "side": "s"}]}) is False


# ----- middle test ----------------------------------------------------------------------------------
def test_middle_test_needs_a_kept_trend_citing_take_15(tmp_path: Path):
    assert scored("middle_of_thirty", [good("middle_of_thirty")], tmp_path)["middle"] is True
    late = good("middle_of_thirty")
    late["trends"][0]["cites"] = [{"take": 30, "at_s": None}]
    late["trends"][0]["text"] = "The hip shift was in an earlier take."
    result = scored("middle_of_thirty", [late], tmp_path)
    assert result["middle"] is False
    nothing = good("middle_of_thirty")
    nothing["trends"] = []
    assert scored("middle_of_thirty", [nothing], tmp_path)["middle"] is False


def test_thirty_takes_all_reach_the_request():
    packed = ev.digest_packer(CASES["middle_of_thirty"])
    assert sum(item["text"].startswith("Take ") for item in packed["content"]) == 30


# ----- distractor -----------------------------------------------------------------------------------
def test_distractor_digests_are_labelled_in_the_request_and_not_in_the_facts():
    packed = ev.digest_packer(CASES["distractor"])
    labelled = [i["text"] for i in packed["content"] if "from a different movement" in i["text"]]
    assert len(labelled) == 2 and labelled[0].startswith("Take 4 digest") and "squat-other-entry" in labelled[0]
    assert {t["take"] for t in packed["facts"]["takes"]} == {1, 2, 3}
    assert packed["content"][-1]["text"] == labelled[-1]  # the student's takes come first


def test_distractor_citation_is_caught_before_and_after_the_guard(tmp_path: Path):
    answer = good("distractor")
    answer["trends"].append({**answer["trends"][0], "text": "A wrist flare shows in take 4.", "cites": [{"take": 4, "at_s": 1.5}]})
    result = scored("distractor", [answer], tmp_path)
    assert result["distractor_raw"] == [4]  # the model cited it
    assert result["distractor"] == []       # rule 1 kept it from the student
    assert result["guard"]["by_rule"] == {"1": 1}
    assert ev.distractor_cited({"trends": [{"cites": [{"take": 5}]}], "observations": [{"take": 4}]}, [4, 5]) == [4, 5]
    assert ev.distractor_cited({}, []) is None and ev.raw_cited({}, []) is None


# ----- abstention -----------------------------------------------------------------------------------
@pytest.mark.parametrize("case_id", ["abstain_clean", "abstain_unverified"])
def test_abstention_holds_when_the_guard_drops_every_claim_and_fails_when_one_is_kept(case_id: str, tmp_path: Path):
    assert scored(case_id, [good(case_id)], tmp_path)["abstain"] is True
    lean = CASES["persistent_stability"]["answers"][0]
    claims = good(case_id)
    claims["trends"] = [lean["trends"][0]]
    claims["focus"] = lean["focus"]
    result = scored(case_id, [claims], tmp_path)
    assert result["abstain"] is True and sum(result["guard"]["by_rule"].values()) == 2  # nothing the table backs
    assert ev.abstained({"trends": [{"kind": "new"}]}, {"abstain": True}) is False
    assert ev.abstained({"focus": {"cue": "c"}}, {"abstain": True}) is False
    assert ev.abstained({"trends": []}, {}) is None


def test_unverified_measure_cannot_be_claimed_gone(tmp_path: Path):
    answer = good("abstain_unverified")
    answer["trends"] = [{"kind": "fixed", "measure": "trunk_lean_forward", "side": "center",
                         "text": "The forward lean at 0.9 s in take 1 is gone in take 2.",
                         "cites": [{"take": 1, "at_s": 0.9}, {"take": 2, "at_s": None}]}]
    result = scored("abstain_unverified", [answer], tmp_path)
    assert result["abstain"] is True and result["guard"]["by_rule"] == {"3": 1}


# ----- stability ------------------------------------------------------------------------------------
def test_stability_is_the_mean_pairwise_jaccard_of_kept_items():
    a = {"trends": [{"kind": "new", "measure": "m", "side": "s"}], "focus": {"measure": "m", "side": "s", "cue": "c"}}
    b = {"trends": [{"kind": "new", "measure": "m", "side": "s"}]}
    assert ev.stability([a, a, a]) == 1.0
    assert ev.stability([a, a, b]) == round((1 + 0.5 + 0.5) / 3, 4)
    assert ev.stability([{}, {}, {}]) == 1.0 and ev.stability([a]) is None
    assert ev.stability([{"trends": [{"kind": "new", "measure": "x", "side": "s"}]}, b]) == 0.0


def test_stability_of_the_persistent_case_from_three_canned_runs(tmp_path: Path):
    case = CASES["persistent_stability"]
    assert len(case["answers"]) == 3
    result = scored("persistent_stability", case["answers"], tmp_path)
    assert result["runs"] == 3 and result["stability"] == round((0.5 + 0.5 + 1) / 3, 4)


# ----- runs, errors and the ledger --------------------------------------------------------------------
def test_text_answer_wrapped_in_prose_still_parses(tmp_path: Path):
    text = "Here it is: " + json.dumps(good("fixed"))
    assert scored("fixed", [text], tmp_path)["guard"]["items"] == 2


def test_unreadable_answer_ends_as_a_guard_rejection_not_a_crash(tmp_path: Path):
    result = scored("fixed", ["no json at all"], tmp_path)
    assert result["guard"]["items"] == 0 and result["rejected"][0]["item"] == "answer"


def test_canned_run_writes_a_ledger_line_labelled_eval_with_the_prompt_version(tmp_path: Path):
    run_answers("fixed", [good("fixed")], tmp_path)
    rows = history_api.read_ledger(history_api.ledger_path(tmp_path))
    assert {r["feature"] for r in rows} == {"eval"} and {r["prompt_version"] for r in rows} == {history_prompt.PROMPT_VERSION}
    assert history_api.spent_by_feature(history_api.ledger_path(tmp_path)) == {"eval": 0.0}


def test_a_failing_call_is_counted_as_an_error(tmp_path: Path):
    class Down(ev.ScriptedTransport):
        def respond(self, body: dict[str, Any]) -> Any:
            raise history_api.HistoryError("HTTP 500 on responses")

    run = ev.run_once(CASES["fixed"], ev.digest_packer, Down([]), tmp_path)
    assert run["error"] == "HTTP 500 on responses"
    result = ev.score_case(CASES["fixed"], [run])
    assert result["errors"] == ["HTTP 500 on responses"] and "guard" not in result
    assert ev.aggregate([result])["errors"] == 1


# ----- live mode and the cap ------------------------------------------------------------------------
def test_live_mode_refuses_without_the_opt_in(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv(ev.LIVE_ENV, raising=False)
    with pytest.raises(PermissionError, match=ev.LIVE_ENV):
        ev.evaluate([CASES["fixed"]], live=True, state=tmp_path)
    assert ev.main(["--live", "--out", str(tmp_path / "r.json")]) == 2
    assert not (tmp_path / "r.json").exists() and not history_api.ledger_path(tmp_path).exists()
    monkeypatch.setenv(ev.LIVE_ENV, "yes")
    assert ev.live_allowed() is False
    monkeypatch.setenv(ev.LIVE_ENV, "1")
    assert ev.live_allowed() is True


def test_live_mode_with_the_opt_in_asks_through_the_ledger_as_eval(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Opt-in on, the transport swapped for the scripted one: the live path asks with feature eval and no default cap."""
    monkeypatch.setenv(ev.LIVE_ENV, "1")
    for name in ("SIMON7_HISTORY_EVAL_CAP_USD", "SIMON7_HISTORY_CAP_USD", "SIMON7_HISTORY_CALL_MAX_USD"):
        monkeypatch.delenv(name, raising=False)
    sent = ev.ScriptedTransport([good("fixed")] * ev.RUNS)
    monkeypatch.setattr(history_api, "HttpClient", lambda key: sent)
    monkeypatch.setattr(history_api.keys, "read_key", lambda *a, **k: "not-a-real-key")
    run = ev.evaluate([CASES["fixed"]], live=True, state=tmp_path)
    assert run["mode"] == "live" and run["metrics"]["errors"] == 0 and len(sent.bodies) == ev.RUNS
    assert {r["feature"] for r in history_api.read_ledger(history_api.ledger_path(tmp_path))} == {"eval"}


def test_eval_cap_stops_the_run_once_the_ledger_passes_it(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv(ev.LIVE_ENV, "1")
    monkeypatch.setenv("SIMON7_HISTORY_EVAL_CAP_USD", "0.5")
    ledger = history_api.ledger_path(tmp_path)
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({"call": "x", "kind": "reserve", "usd": 0.6, "feature": "eval"}) + "\n")
    run = ev.evaluate(list(CASES.values()), live=True, state=tmp_path)
    assert run["results"] == [] and "eval cap" in run["stopped"]


# ----- A/B ------------------------------------------------------------------------------------------
def test_ab_runs_each_packer_side_by_side():
    def noisy(case: dict[str, Any]) -> dict[str, Any]:
        packed = ev.digest_packer(case)
        packed["facts"] = {**packed["facts"], "takes": packed["facts"]["takes"][:1]}  # a variant that sees less
        return packed

    out = ev.ab([CASES["persistent_stability"]], {"digest": ev.digest_packer, "narrow": noisy})
    assert out["digest"]["guard_pass_rate"]["all"] == 1.0
    assert out["narrow"]["guard_pass_rate"]["all"] < 1.0  # the same canned answer cites takes this variant never showed
    assert set(out) == {"digest", "narrow"}
    both = ev.ab([CASES["persistent_stability"]])
    assert set(both) == {"digest", "full_analysis"} and both["full_analysis"]["guard_pass_rate"]["all"] == 1.0


# ----- the full-analysis arm (TICKET-221) -------------------------------------------------------------
@pytest.mark.parametrize("case_id", sorted(CASES))
def test_full_analysis_packer_builds_within_budget_and_cites_only_fixture_takes(case_id: str):
    case = CASES[case_id]
    packed = ev.full_analysis_packer(case)
    fixture_takes = {t["take"] for t in case["facts"]["takes"]}
    assert packed["est_input_tokens"] <= history_longpack.budget()
    assert packed["feature"] == "eval" and packed["prompt_version"] == ev.FULL_VERSION
    assert (packed["full_takes"], packed["digest_takes"]) == (len(fixture_takes), 0)
    labelled = {int(c["text"].split()[1]) for c in packed["content"] if " of " in c["text"][:30] and c["text"].startswith("Take ")
                and "analysis (JSON data)" in c["text"]}
    assert labelled == fixture_takes and {t["take"] for t in packed["facts"]["takes"]} == fixture_takes
    answer = good(case_id)
    kept, rejected = ev.history_guard.check(answer, packed["facts"], case.get("narration"), ev.history_guard.DEFAULT_WORDS)
    assert rejected == [] and cited_in(kept) <= fixture_takes


def cited_in(kept: dict[str, Any]) -> set[int]:
    return ev.cited_takes(kept)


def test_full_analysis_pack_holds_the_synthetic_faults_and_puts_the_question_last_and_the_distractors_after():
    packed = ev.full_analysis_packer(CASES["distractor"])
    texts = [c["text"] for c in packed["content"]]
    assert texts[0] == history_longpack.LONG_INSTRUCTIONS and "trunk_lean_forward" in texts[1] and '"follower_t_s":[0.9,3.2]' in texts[1]
    assert [t for t in texts if "different movement" in t] == texts[-2:]
    assert texts[-3] == history_prompt.INSTRUCTIONS
    assert ev.synthetic_analysis(CASES["fixed"]["facts"]["takes"][0])["faults"][0]["measure"] == "hip_shift"


def test_full_analysis_arm_runs_on_the_scripted_transport_at_no_cost(tmp_path: Path):
    run = ev.evaluate(list(CASES.values()), packer=ev.full_analysis_packer)
    assert run["spend_usd"] == 0.0 and run["metrics"]["errors"] == 0 and run["metrics"]["guard_pass_rate"]["all"] == 1.0


# ----- the report -----------------------------------------------------------------------------------
def test_report_holds_commit_prompt_version_model_and_spend(tmp_path: Path):
    out = tmp_path / "progress" / "history-eval-test.json"
    path = ev.write_report(ev.evaluate([CASES["fixed"]]), out)
    doc = json.loads(path.read_text())
    assert doc["prompt_version"] == history_prompt.PROMPT_VERSION and doc["model"] == history_api.MODEL
    assert doc["spend_usd"] == 0.0 and doc["mode"] == "canned" and len(doc["commit"]) == 40
    assert doc["metrics"]["cases"] == 1


def test_default_report_name_is_progress_history_eval_date(tmp_path: Path):
    path = ev.write_report(ev.evaluate([CASES["fixed"]]), root=tmp_path)
    assert path.parent == tmp_path / "progress" and path.name.startswith("history-eval-") and path.suffix == ".json"


def test_main_runs_the_fixtures_with_one_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    out = tmp_path / "r.json"
    assert ev.main(["--out", str(out), "--ab"]) == 0
    printed = capsys.readouterr().out
    assert '"guard_pass_rate"' in printed and "report:" in printed
    doc = json.loads(out.read_text())
    assert doc["ab"]["digest"] == doc["metrics"] and doc["ab"]["full_analysis"]["cases"] == len(CASES)
    assert '"full_analysis"' in printed or doc["ab"]["full_analysis"]["errors"] == 0
