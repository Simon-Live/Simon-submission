"""Ask this take's validator and measured facts (docs/specs/ask-this-take.md AC-ASK-03 and AC-ASK-04, the hub's AC-2;
TICKET-081): the numbers of an answer and of the tool results, the check, and the measured facts. A forged answer
played through the loop, and the word guard's replacements, are in tests/test_ask_agent.py."""
import pytest
from test_ask_tools import ANALYSIS, golden_take

from part5.ask import agent, tools
from part5.opinion import guard
from part5.phrasing.template import NUMBER


def run(take, *items):
    return [tools.run_tool(take, name, args)[0] for name, args in items]


def results():
    take = golden_take()
    return run(take, ("get_faults", ""), ("get_joint_angle", '{"joint": "right_elbow", "t0": 0.5, "t1": 1.5}'),
               ("compare_with_teacher", '{"joint": "right_elbow", "t": 0.7}'), ("seek", '{"t": 0.7}'))


# ---- the numbers of an answer -------------------------------------------------------------------------------------
def test_answer_numbers_are_digit_runs_and_number_words_in_reading_order():
    found = guard.answer_numbers("At 1.9 s it is twelve degrees, -9.80 less; 3D and two reps.")
    assert found == [("1.9", 1.9, 1), ("twelve", 12.0, 0), ("9.80", 9.8, 2), ("3", 3.0, 0), ("two", 2.0, 0)]


def test_the_number_words_are_those_the_student_word_test_counts():
    assert all(NUMBER.search(word) for word in guard.NUMBER_WORDS)
    assert not NUMBER.search("one") and "one" not in guard.NUMBER_WORDS


@pytest.mark.parametrize("written, ok", [("36.1", True), ("36", True), ("36.10", True), ("36.2", False), ("37", False),
                                         ("9.7", True), ("10", True), ("thirty", False), ("2", True), ("0.67", True)])
def test_a_number_is_found_within_its_rounding(written, ok):
    calls_ = results()   # magnitudes 36.1 and 15.8, count 2, times 0.7 and 0.67, the elbow's 9.7 mean of forearm out
    assert (guard.check_answer(f"It is {written} here.", calls_)[1] is None) is ok


def test_a_sign_is_not_a_number_and_text_inside_a_result_counts():
    calls_ = [{"name": "compare_with_teacher", "ok": True, "result": {"difference_deg": -9.8, "note": "at 1.9 s"}}]
    assert guard.check_answer("It is 9.8 degrees less at 1.9 s.", calls_)[1] is None


def test_r1_an_error_result_counts_for_nothing_even_the_take_span_it_names():
    take = golden_take()
    calls_ = run(take, ("seek", '{"t": 7}'))
    assert calls_[0]["result"]["error"].endswith("0.00 to 2.50 s")
    assert guard.check_answer("The take runs to 2.5 s.", calls_) == ("The take runs to 2.5 s.", guard.NUMBER_NOT_FOUND,
                                                                     ["2.5"])
    assert guard.check_answer("The take runs to 2.5 s.", calls_ + run(take, ("get_faults", "")))[1] is None


def test_r1_the_reviews_laundering_probe_is_refused():
    """R1 of the 1.14.0 review: `seek({"87.5": 1})` echoed 87.5 in its error and the answer passed. Now the error names
    no argument, and an error result counts for nothing even when it does hold the number."""
    take = golden_take()
    bad, _ = tools.run_tool(take, "seek", '{"87.5": 1}')
    assert not bad["ok"] and "87.5" not in bad["result"]["error"]
    answer = "Your knee bends 87.5 degrees."
    assert guard.check_answer(answer, results() + [bad]) == (answer, guard.NUMBER_NOT_FOUND, ["87.5"])
    forged = {"name": "seek", "arguments": {}, "ok": False, "result": {"error": "unknown argument 87.5"}}
    assert guard.check_answer(answer, [forged])[2] == ["87.5"]
    assert guard.result_numbers([forged, {**forged, "ok": "true"}]) == []


@pytest.mark.parametrize("text", [
    "Your right foot turns out twice as far as the example's.",          # the review's phrases (R2, 1.14.0 review)
    "Your foot turns out one and a half times as far as the example's.",
    "Your elbow bends a third more.",
    "It comes about half a beat late.",
    "Hundreds of frames, dozens of degrees off.",
    "On the fifth rep your foot turns out.",
    "It is a quarter turn off.",
    "The knee bends double the example's bend.",
    "The thirteenth frame and the twentieth differ.",
])
def test_r2_an_answer_that_counts_in_words_is_refused_as_the_second_opinion_refuses_it(text):
    assert guard.check_answer(text, results()) == (text, guard.COUNT_IN_WORDS, [])


@pytest.mark.parametrize("text", ["In the second half of the take your foot turns out.",
                                  "At first the elbow is bent, then a second later it straightens.",
                                  "Your right elbow bends 36.1 degrees more than the example at 0.7 s."])
def test_r2_positions_and_found_numbers_are_not_counts(text):
    assert guard.check_answer(text, results())[1] is None


def test_r2_numbers_are_checked_before_count_words_so_part7_gets_them():
    assert guard.check_answer("Twice as far: 87.5 degrees.", results())[1:] == (guard.NUMBER_NOT_FOUND, ["87.5"])


def test_r2_the_measured_facts_hold_no_count_word():
    facts = guard.measured_facts(results())
    assert not guard.QUANTITY.search(facts.lower()) and not guard.COUNT_WORDS.search(facts.lower())


@pytest.mark.parametrize("text, reason", [("Bend more‮ at the knee.", "has a control character"),
                                          ("See www.example.com now.", "has a link"),
                                          ("Well done on the squat.", "adds praise")])
def test_r1_the_word_guard_of_answers_and_arguments_is_one_function(text, reason):
    assert guard.shown_problem(text) == reason == guard.check_answer(text, results())[1]
    assert not tools.arguments_shown({"limb": text})


# ---- AC-ASK-03: the check and the measured facts ----------------------------------------------------------------------
def test_ac_ask_03_a_number_the_model_passed_to_a_ui_tool_is_one_it_may_say():
    calls_ = run(golden_take(), ("seek", '{"t": 1.25}'))
    assert guard.check_answer("Look at 1.25 s.", calls_)[1] is None


def test_ac_ask_03_the_measured_facts_pass_the_validator_for_every_tool():
    calls_ = results()
    facts = guard.measured_facts(calls_)
    assert guard.check_answer(facts, calls_) == (facts, None, [])
    for one in calls_[:3]:
        assert guard.check_answer(guard.measured_facts([one]), [one])[1] is None
    assert "Right elbow bend from 0.5 s to 1.5 s: from" in facts and "At 0.7 s, right elbow bend:" in facts


def test_ac_ask_03_the_measured_facts_of_a_correct_take_say_no_difference():
    take = agent.ask_take(dict(ANALYSIS, faults=[]), golden_take().replay)
    facts = guard.measured_facts(run(take, ("get_faults", "")))
    assert facts == "The measurement found no difference from the example."


def test_ac_ask_03_only_ui_actions_or_errors_hold_no_fact():
    assert guard.measured_facts(run(golden_take(), ("seek", '{"t": 1}'), ("seek", '{"t": 99}'))) is None


def many_faults(n):
    """The golden take with `n` faults, each the first golden fault with its own size: a take whose facts run long."""
    faults = [dict(ANALYSIS["faults"][0], magnitude_deg=round(10 + i / 10, 1)) for i in range(n)]
    return agent.ask_take(dict(ANALYSIS, faults=faults), golden_take().replay)


def test_r13_the_measured_facts_of_many_faults_are_held_to_the_schemas_answer_length():
    """R13 of the 1.14.0 review: the facts had no length cap; `answer.maxLength` is 4000."""
    calls_ = run(many_faults(120), ("get_faults", ""))
    full = " ".join(dict.fromkeys(line for call in calls_ for line in guard.FACTS[call["name"]](call["result"])))
    facts = guard.measured_facts(calls_)
    assert len(full) > guard.MAX_FACTS_CHARS >= len(facts) > guard.MAX_FACTS_CHARS - 200
    assert guard.MAX_FACTS_CHARS == 4000 and facts.endswith(" " + guard.FACTS_CUT)
    kept = facts.removesuffix(" " + guard.FACTS_CUT)
    assert full.startswith(kept + " ") and kept.endswith(".")   # whole sentences, in order, from the first
    known = guard.result_numbers(calls_)
    assert all(guard._found(value, places, known) for _, value, places in guard.answer_numbers(facts))


def test_r13_the_reviews_worst_case_on_the_golden_take_fits_whole():
    take = golden_take()
    t0, t1 = take.span
    items = [("get_faults", "")] + [
        ("get_joint_angle", f'{{"joint": "right_elbow", "t0": {t0 + 0.01 * i}, "t1": {t1}}}') if i % 2 == 0 else
        ("compare_with_teacher", f'{{"joint": "left_knee", "t": {t0 + 0.37 * i}}}') for i in range(7)]
    facts = guard.measured_facts(run(take, *items))
    assert len(facts) <= guard.MAX_FACTS_CHARS and guard.FACTS_CUT not in facts


def test_r13_one_sentence_over_the_limit_leaves_only_the_pointer_to_the_tool_calls():
    assert guard._held(["x" * 5000, "Short."]) == guard.FACTS_CUT
    assert guard._held(["A.", "B."], limit=10) == "A. B."
    assert len(guard._held(["A" * 30 + ".", "B" * 30 + "."], limit=len(guard.FACTS_CUT) + 40)) <= len(
        guard.FACTS_CUT) + 40


def test_ac_ask_03_a_measure_not_seen_is_said_so_without_a_number():
    calls_ = [{"name": "get_joint_angle", "ok": True, "result": {"t0": 0.5, "t1": 1.0, "measures": [
        {"side": "left", "means": "knee bend", "min": None}]}}]
    assert guard.measured_facts(calls_) == "Left knee bend could not be measured from 0.5 s to 1 s."
