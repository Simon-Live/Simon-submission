"""Timed AI phrasing, the live default (ADR-0008; AC-P01, AC-P03 to AC-P05). No socket is opened."""
import json

import pytest

from part5 import phrasing
from part5.phrasing import muse_spark, prompt, template
from part5.phrasing.local_llm import HttpResult
from test_phrasing import clean_env, make_fault, no_network  # noqa: F401
from test_phrasing_muse_spark import SENTINEL, Client, http_error, live, reply  # noqa: F401,F401


def timed(measure="foot_out", side="right", direction="more", lateral="right", at_s=1.9, **extra):
    word = {"foot_out": "foot", "thigh_out": "knee", "upper_arm_out": "arm", "forearm_out": "hand"}.get(measure)
    base = f"{side} {word} too far {lateral}" if lateral and word else f"{side} {measure} {direction}"
    fault = make_fault(measure, side, direction, text=f"{side} {measure}", at_s=at_s, lateral=lateral,
                       text_timed=f"{base} at {at_s:.1f} s")
    fault.update(extra)
    return fault


RIGHT_FOOT = timed()
EXAMPLE = "Your right foot drifts too far to the right at 1.9 s; keep it under your hip"


def problem(fault, line):
    return template.line_problem(fault, line, timed=True)


# ---- validator (AC-P03) -------------------------------------------------------------------------
def test_the_spec_example_passes_for_a_right_foot_at_1_9_s():
    assert problem(RIGHT_FOOT, EXAMPLE) is None


@pytest.mark.parametrize("line", [
    "Your right foot is too far right at 1.9s.",
    "At 1.9 seconds your right foot sits too far to the right",
    "right foot toward the right at 1.9 s, keep it near your shoulder",
    "Right foot too far right at 1.9 s",
])
def test_other_friendly_forms_pass(line):
    assert problem(RIGHT_FOOT, line) is None


@pytest.mark.parametrize("line,reason", [
    ("Your right foot drifts too far to the right; keep it under your hip", "does not say the time"),
    ("Your right foot drifts too far to the right at 2.0 s", "wrong time"),
    ("Your right foot drifts too far to the right at 1.9 s and again at 1.9 s", "says the time more than once"),
    ("Your right foot drifts 8 degrees too far to the right at 1.9 s", "adds a number"),
    ("Your right foot drifts too far to the right at 1.9 s by eight degrees", "adds a number"),
    ("Your right foot drifts too far to the left at 1.9 s", "wrong direction"),
    ("Your left foot drifts too far to the right at 1.9 s", "wrong side"),
    ("Your right foot drifts too far to the right at 1.9 s; keep your head up", "adds another body part (head)"),
    ("Your right foot drifts too far to the right at 1.9 s;\nkeep it under your hip", "more than one line"),
    ("Your right foot drifts too far to the right at 1.9 s" + " x" * 60, "line too long"),
    ("", "empty line"),
])
def test_these_lines_fail_with_the_reason_named(line, reason):
    assert problem(RIGHT_FOOT, line) == reason


def test_161_characters_fail_and_160_pass():
    base = "Your right foot drifts too far to the right at 1.9 s;"
    assert problem(RIGHT_FOOT, base + " a" * 53) is None and len(base + " a" * 53) == 159
    assert problem(RIGHT_FOOT, base + " " + "a" * 106) is None
    assert problem(RIGHT_FOOT, base + " " + "a" * 107) == "line too long"


def test_the_shoulder_is_not_allowed_for_a_knee_flexion_fault():
    fault = timed("knee_flexion", "right", "less", None, joint="right_knee")
    assert problem(fault, "Your right knee is not bent enough at 1.9 s") is None
    assert problem(fault, "Your right knee is not bent enough at 1.9 s; drop your shoulder") \
        == "adds another body part (shoulder)"


def test_the_time_is_checked_to_a_tenth_so_two_seconds_may_be_written_2s():
    fault = timed(at_s=2.0)
    assert problem(fault, "Your right foot is too far right at 2s") is None
    assert problem(fault, "Your right foot is too far right at 2.1 s") == "wrong time"


def test_a_timed_check_without_a_time_in_the_fault_is_refused():
    fault = timed()
    del fault["at_s"]
    assert problem(fault, EXAMPLE) == "no time to check against"


@pytest.mark.parametrize("measure,side,direction,lateral,line", [
    ("foot_out", "left", "more", "left", "left foot too far left at 0.4 s"),
    ("foot_out", "left", "less", "right", "left foot too far right at 0.4 s"),
    ("thigh_out", "right", "more", "right", "right knee too far right at 0.4 s"),
    ("upper_arm_out", "left", "less", "right", "left arm too far right at 0.4 s"),
    ("forearm_out", "right", "less", "left", "right hand too far left at 0.4 s"),
    ("knee_valgus", "left", "more", "right", "left knee caving in at 0.4 s"),
    ("knee_valgus", "left", "less", "left", "left knee pushed out at 0.4 s"),
    ("thigh_forward", "right", "less", None, "right thigh not raised enough at 0.4 s"),
    ("thigh_forward", "right", "less", None, "right thigh not quite raised enough at 0.4 s"),
    ("thigh_forward", "both", "less", None, "thighs nowhere near raised enough at 0.4 s"),
    ("upper_arm_forward", "both", "less", None, "arms too low at 0.4 s"),
    ("trunk_lean_side", "center", "more", "left", "leaning to the left at 0.4 s"),
    ("trunk_lean_side", "center", "less", "right", "leaning to the right at 0.4 s"),
    ("elbow_flexion", "right", "more", None, "right elbow bent more than the example at 0.4 s"),
])
def test_the_timed_template_words_pass_their_own_test_and_fail_the_opposite(measure, side, direction, lateral, line):
    fault = timed(measure, side, direction, lateral, at_s=0.4)
    assert problem(fault, line) is None, line
    flipped = dict(fault, direction="less" if direction == "more" else "more",
                   lateral={"left": "right", "right": "left"}.get(lateral))
    assert problem(flipped, line) is not None, line


THIGH = timed("thigh_forward", "right", "less", None, at_s=1.9)


@pytest.mark.parametrize("line", [
    "Your right thigh is not raised enough at 1.9 s",
    "Your right thigh isn't lifted high enough at 1.9 s",
    "Right thigh nowhere near raised enough at 1.9 s",
    "Your right thigh stays short of the example at 1.9 s",
])
def test_a_thigh_that_is_not_lifted_is_phrased_as_not_raised_enough(line):
    assert problem(THIGH, line) is None, line


@pytest.mark.parametrize("line", [
    "Your right thigh is too low at 1.9 s",
    "Your right thigh hangs low at 1.9 s",
    "Your right thigh drops at 1.9 s",
    "Your right thigh is lower than the example at 1.9 s",
])
def test_calling_such_a_thigh_too_low_fails_because_it_reads_as_squatting_too_deep(line):
    # R9: on a squat "too low" means the opposite of the fault, so it carries no direction for thigh_forward
    assert problem(THIGH, line) == "wrong direction", line
    assert problem(dict(THIGH, direction="more"), line) is not None


def test_not_raised_enough_and_too_low_in_one_line_contradict():
    assert problem(THIGH, "Your right thigh is not raised enough, too low at 1.9 s") \
        == "contradicts itself on the direction"


def test_an_arm_held_too_low_is_still_phrased_as_too_low():
    arm = timed("upper_arm_forward", "left", "less", None, at_s=1.9)
    assert problem(arm, "Your left arm is too low at 1.9 s") is None


def test_the_untimed_test_is_unchanged_and_still_bans_numbers():
    assert template.line_problem(RIGHT_FOOT, "right foot too far out at 1.9 s") == "adds a number"


# ---- live default (AC-P01) ----------------------------------------------------------------------
def test_select_backend(monkeypatch):
    assert phrasing.select_backend() == ("template", "default")
    assert phrasing.select_backend("template", live=True) == ("template", "flag")
    assert phrasing.select_backend(None, live=True) == ("muse-spark", "live")
    for name in ("SIMON5_LIVE", "META_LIVE"):
        monkeypatch.setenv(name, "1")
        assert phrasing.select_backend() == ("muse-spark", "live")
        assert phrasing.select_backend("local-llm") == ("local-llm", "flag")
        monkeypatch.delenv(name)
    monkeypatch.setenv("SIMON5_LIVE", "0")
    assert phrasing.select_backend() == ("template", "default")


def test_the_live_flag_or_simon5_live_opens_the_gate_with_the_key(live, monkeypatch):  # noqa: F811
    monkeypatch.delenv("META_LIVE")
    assert muse_spark.unavailable() is not None and muse_spark.unavailable(live=True) is None
    monkeypatch.setenv("SIMON5_LIVE", "1")
    assert muse_spark.unavailable() is None


def test_the_record_carries_selected_by():
    _, record = phrasing.phrase([RIGHT_FOOT], "template", selected_by="default")
    assert record["selected_by"] == "default"
    assert "selected_by" not in phrasing.phrase([RIGHT_FOOT], "template")[1]


# ---- the call and the fallback (AC-P04) ---------------------------------------------------------
def test_phrase_fault_returns_text_model_backend_and_reason(live):  # noqa: F811
    out = phrasing.phrase_fault(RIGHT_FOOT, client=Client(reply(EXAMPLE)))
    assert out == {"text": EXAMPLE, "model": "meta-models/muse-spark-open-1026", "backend": "muse-spark",
                   "fallback_reason": None}


def test_the_request_carries_the_timed_facts_and_a_roomy_token_budget(live):  # noqa: F811
    client = Client(reply(EXAMPLE))
    phrasing.phrase_fault(RIGHT_FOOT, client=client)
    request = client.requests[0]
    assert request["url"] == "https://inference.baseten.co/v1/chat/completions"
    assert request["body"]["model"] == "meta-models/muse-spark-open-1026"
    assert request["body"]["max_tokens"] >= 512 and request["timeout_s"] == 10
    user = json.loads(request["body"]["messages"][1]["content"])
    assert user == prompt.timed_record(RIGHT_FOOT)
    assert user["at_s"] == "1.9" and user["lateral"] == "right" and user["side"] == "right"
    assert user["text_timed"] == "right foot too far right at 1.9 s"


def test_an_untimed_fault_keeps_the_untimed_prompt(live):  # noqa: F811
    client = Client(reply("left foot sticking out too far"))
    phrasing.phrase([make_fault()], "muse-spark", client=client)
    assert "at_s" not in client.requests[0]["body"]["messages"][1]["content"]


@pytest.mark.parametrize("bad,reason", [
    (TimeoutError("read timed out"), "muse-spark: timeout after 10 s"),
    (http_error(500), "muse-spark: HTTP 500"),
    (reply(""), "muse-spark: empty content"),
    (reply("Your right foot drifts too far to the right"), "muse-spark: does not say the time"),
    (reply("Your right foot drifts too far to the right at 2.5 s"), "muse-spark: wrong time"),
])
def test_one_failing_fault_falls_back_to_text_timed_and_the_others_keep_the_model(live, bad, reason):  # noqa: F811
    faults = [timed(at_s=1.9), timed("thigh_out", "left", "less", "right", at_s=3.2), timed(at_s=4.0)]
    good = ["Your right foot drifts too far to the right at 1.9 s", "Your left knee is too far right at 3.2 s",
            "Your right foot is too far right at 4.0 s"]
    lines, record = phrasing.phrase(faults, "muse-spark", client=Client(reply(good[0]), bad, reply(good[2])))
    assert lines == [good[0], faults[1]["text_timed"], good[2]]
    assert record["faults"][1] == {"backend": "template", "model": None, "fallback_reason": reason}
    assert [record["faults"][i]["backend"] for i in (0, 2)] == ["muse-spark"] * 2
    assert [record["faults"][i]["model"] for i in (0, 2)] == [muse_spark.MODEL] * 2


def test_a_validator_failure_names_the_check_and_never_the_model_text(live):  # noqa: F811
    out = phrasing.phrase_fault(RIGHT_FOOT, client=Client(reply("Your left foot is 12 degrees off at 1.9 s")))
    assert out["text"] == RIGHT_FOOT["text_timed"] and out["backend"] == "template" and out["model"] is None
    assert out["fallback_reason"] == "muse-spark: adds a number" and "12" not in out["fallback_reason"]


def test_the_template_backend_writes_text_timed():
    lines, _ = phrasing.phrase([RIGHT_FOOT, make_fault()], "template")
    assert lines == [RIGHT_FOOT["text_timed"], make_fault()["text"]]


def test_without_a_key_the_fault_falls_back_with_the_reason(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMON5_LIVE", "1")
    out = phrasing.phrase_fault(RIGHT_FOOT, client=Client())
    assert out == {"text": RIGHT_FOOT["text_timed"], "model": None, "backend": "template", "fallback_reason": "no key"}


# ---- limits and ledger (AC-P05) -----------------------------------------------------------------
def test_the_31st_call_in_a_minute_falls_back_with_rate_limited(live):  # noqa: F811
    faults = [timed(at_s=1.9)] * 31
    client = Client(*[reply("Your right foot is too far right at 1.9 s")] * 30)
    lines, record = phrasing.phrase(faults, "muse-spark", client=client, budget_s=1e9)
    assert len(client.requests) == 30
    assert record["faults"][30] == {"backend": "template", "model": None, "fallback_reason": "rate limited"}
    assert lines[30] == faults[30]["text_timed"] and len(live["ledger"].read_text().splitlines()) == 30


def test_the_per_minute_limit_can_be_set_and_slides(live, monkeypatch):  # noqa: F811
    monkeypatch.setenv("PART5_MUSE_PER_MINUTE", "2")
    muse_spark._take_slot(0.0)
    muse_spark._take_slot(10.0)
    with pytest.raises(phrasing.BackendError, match="rate limited"):
        muse_spark._take_slot(59.9)
    muse_spark._take_slot(60.0)


class SlowClient(Client):
    """Each call advances a fake clock by `step` seconds."""

    def __init__(self, clock, step, *script):
        super().__init__(*script)
        self.clock, self.step = clock, step

    def __call__(self, request):
        self.clock[0] += self.step
        return super().__call__(request)


def test_a_slow_model_spends_the_budget_and_later_faults_fall_back(live):  # noqa: F811
    now = [0.0]
    client = SlowClient(now, 8.0, *[reply("Your right foot is too far right at 1.9 s")] * 4)
    lines, record = phrasing.phrase([RIGHT_FOOT] * 4, "muse-spark", client=client, budget_s=20.0,
                                    clock=lambda: now[0])
    assert [e["backend"] for e in record["faults"]] == ["muse-spark", "muse-spark", "template", "template"]
    assert [e["fallback_reason"] for e in record["faults"][2:]] == ["time budget spent"] * 2
    assert len(client.requests) == 2 and lines[3] == RIGHT_FOOT["text_timed"]


def test_the_budget_comes_from_the_environment(live, monkeypatch):  # noqa: F811
    monkeypatch.setenv("PART5_PHRASING_BUDGET_S", "5")
    client = Client(reply(EXAMPLE))
    _, record = phrasing.phrase([RIGHT_FOOT], "muse-spark", client=client)
    assert record["faults"][0]["fallback_reason"] == "time budget spent" and client.requests == []


def test_the_key_never_appears_in_a_timed_result_or_the_ledger(live):  # noqa: F811
    out = phrasing.phrase_fault(RIGHT_FOOT, client=Client(reply(EXAMPLE), HttpResult(200, {})))
    assert SENTINEL not in json.dumps(out) + live["ledger"].read_text()


# ---- request options and the review helpers (TICKET-037) ---------------------------------------
def test_the_request_asks_for_low_reasoning_effort_so_a_call_fits_the_10_s_timeout(live):  # noqa: F811
    client = Client(reply(EXAMPLE))
    phrasing.phrase_fault(RIGHT_FOOT, client=client)
    assert client.requests[0]["body"]["reasoning_effort"] == "low"


def test_the_prompt_lists_only_the_measures_landmarks():
    assert prompt.timed_record(RIGHT_FOOT)["may_mention"] == ["hip", "shoulder"]
    assert prompt.timed_record(timed("knee_flexion", "right", "less", None))["may_mention"] == []


def test_ac_p08_the_timed_prompt_asks_for_normal_punctuation_with_a_comma_before_a_closing_phrase():
    """No live call and no key: the system message is built from the module alone."""
    system = prompt.timed_messages(RIGHT_FOOT)[0]["content"]
    assert prompt.SYSTEM_TIMED in system
    assert "Use normal punctuation: put a comma before a closing phrase" in system
    assert "end the sentence with a full stop" in system


def test_review_keeps_no_copy_of_the_time_and_direction_rules():
    from part5.phrasing import review
    for name in ("lateral_of", "at_s_of", "timed_words", "OUT_MEASURES", "WORD", "FLIP"):
        assert not hasattr(review, name), name


def test_review_faults_are_the_analyses_own_so_the_model_is_given_what_a_user_is_told(monkeypatch, tmp_path):
    """The J-1 and J-2 tables are tested where they live (`lateral_for`, `describe_timed`, `round_half_up_tenth`);
    the review reads `at_s`, `lateral` and `text_timed` from the analysis."""
    import shutil
    from pathlib import Path

    from part5.phrasing import review
    from part5.pipeline import run
    repo = Path(__file__).resolve().parent.parent
    take = "exercise_front_good_03_foot_out-right"
    expected, follower = review.SYNTHETIC_EXPECTED, f"{review.SYNTHETIC_DIR}/{take}/skeleton.json"
    for rel in (expected, follower):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(repo / rel, tmp_path / rel)
    monkeypatch.setattr(review, "ROOT", tmp_path)
    monkeypatch.setattr(review, "STOCK_FOLLOWERS", ())
    got = review.timed_faults()
    want = run(str(repo / expected), str(repo / follower)).analysis["faults"]
    assert want and got == [(take, fault) for fault in want]
    assert got[0][1]["lateral"] in ("left", "right") and got[0][1]["text_timed"].endswith(f"at {got[0][1]['at_s']:.1f} s")


def test_review_pick_spreads_over_the_measures_first():
    from part5.phrasing import review
    faults = [("t", {"measure": m}) for m in ["a", "a", "a", "b", "c"]]
    assert [f["measure"] for _, f in review.pick(faults, 4)] == ["a", "b", "c", "a"]


def test_review_exits_1_without_the_key_and_makes_no_call(capsys):
    from part5.phrasing import review
    assert review.main(["--n", "1"]) == 1
    assert "no key" in capsys.readouterr().err
