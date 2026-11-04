"""The history opinion's guard (docs/specs/history-opinion.md AC-HO-04 to AC-HO-06, AC-HO-09; TICKET-072).

Observations are kept only when the five cited values are one fault of one take of the series and the sentence adds no
number, no time, no other body part and no other side. Each drop is counted by reason. No socket, no call: the guard is
fed the model's text directly.
"""
import json

import pytest
from test_history_opinion import GOOD, OTHER, SPANISH, analysis, cite, fault

from part5.opinion import guard, prompt
from part5.phrasing.lang import check_translated


@pytest.fixture(scope="module")
def series():
    """take_01: elbow_flexion right at 0.7, upper_arm_out both at 0.4; take_02: elbow_flexion right at 0.9 and a knee
    fault without a second; take_03: a correct take."""
    docs = [analysis([fault(), fault("upper_arm_out", "both", "arms", "more", 15.8, 0.4)]),
            analysis([fault(magnitude_deg=20.2, at_s=0.9), fault("knee_flexion", "left", "legs", "less", -12.0, None)]),
            analysis([])]
    return prompt.build_series(docs, ["take_01", "take_02", "take_03"])


def read(series, items, language="en", limit=5):
    return guard.read_history_answer(json.dumps({"observations": items}), series, language, limit)


def reasons(series, item, language="en"):
    found = read(series, [item], language)
    return found["observations"], found["dropped"]["reasons"]


# ---- AC-HO-04: the citation ----------------------------------------------------------------------------------------
def test_ac_ho_04_a_grounded_observation_is_kept_with_the_faults_own_values(series):
    found = read(series, [GOOD, OTHER])
    assert [(o["take_id"], o["at_s"], o["measure"], o["side"], o["body_part"]) for o in found["observations"]] == [
        ("take_02", 0.9, "elbow_flexion", "right", "arms"), ("take_01", 0.4, "upper_arm_out", "both", "arms")]
    assert found["dropped"] == {"count": 0, "reasons": {}} and found["translation_fallbacks"] == 0
    assert all(o["label"] == "model_opinion" for o in found["observations"])


@pytest.mark.parametrize("mutation,reason", [
    ({"take": "take_09"}, "take not in the input"),
    ({"take": 2}, "take not in the input"),
    ({"take": None}, "take not in the input"),
    ({"take": ["take_02"]}, "take not in the input"),
    ({"take": "TAKE_02"}, "take not in the input"),
    ({"at_s": 9.9}, "second not in the input"),
    ({"at_s": "0.9"}, "second not in the input"),
    ({"at_s": True}, "second not in the input"),
    ({"at_s": None}, "second not in the input"),
    ({"at_s": float("nan")}, "second not in the input"),
    ({"at_s": float("inf")}, "second not in the input"),
    ({"at_s": 10 ** 400}, "second not in the input"),   # math.isfinite raises OverflowError on an integer this large
    ({"at_s": -(10 ** 400)}, "second not in the input"),
    ({"at_s": 0.4}, "second not in the input"),   # a second of another take
    ({"measure": "trunk_lean_forward"}, "measure not in the input"),
    ({"measure": ["elbow_flexion"]}, "measure not in the input"),
    ({"side": "center"}, "side not in the input"),
    ({"side": None}, "side not in the input"),
    ({"body_part": "head"}, "body part not in the input"),
    ({"body_part": 5}, "body part not in the input"),
])
def test_ac_ho_04_a_citation_value_that_is_not_in_the_input_names_what_is_missing(series, mutation, reason):
    kept, dropped = reasons(series, {**GOOD, **mutation})
    assert kept == [] and dropped == {reason: 1}


def test_ac_ho_04_each_value_of_the_take_but_not_all_together_is_not_one_fault(series):
    # take_02 has an elbow fault at 0.9 on the right and a knee fault on the left with no second: each value is there
    # (at 0.9, knee_flexion, left, legs) but they are not one fault
    item = cite("take_02", 0.9, "knee_flexion", "left", "legs", "The left knee bends less than the recording.")
    kept, dropped = reasons(series, item)
    assert kept == [] and dropped == {"values are not one fault of that take": 1}


def test_ac_ho_04_a_fault_without_a_second_cannot_be_cited(series):
    # the knee fault of take_02 has no at_s: any second cited with it is another fault's
    for at_s in (0.9, 0.0, 1.2):
        kept, dropped = reasons(series, cite("take_02", at_s, "knee_flexion", "left", "legs", "The left knee drifts."))
        assert kept == [] and sum(dropped.values()) == 1


def test_ac_ho_04_a_take_without_faults_has_nothing_to_cite(series):
    kept, dropped = reasons(series, dict(GOOD, take="take_03"))
    assert kept == [] and dropped == {"second not in the input": 1}


def test_ac_ho_04_a_second_within_a_tenth_rounds_to_the_faults_own_second(series):
    found = read(series, [dict(GOOD, at_s=0.94)])
    assert [o["at_s"] for o in found["observations"]] == [0.9]
    assert read(series, [dict(GOOD, at_s=0.96)])["dropped"]["reasons"] == {"second not in the input": 1}


@pytest.mark.parametrize("item", ["a sentence", 5, None, ["take_01"], True])
def test_ac_ho_04_an_item_that_is_not_an_object_is_dropped(series, item):
    assert read(series, [item])["dropped"] == {"count": 1, "reasons": {"not an object": 1}}


def test_ac_ho_04_a_second_observation_for_the_same_fault_is_dropped(series):
    found = read(series, [GOOD, dict(GOOD, text="The right elbow stays bent more in this take.")])
    assert len(found["observations"]) == 1
    assert found["dropped"]["reasons"] == {"second observation for the same fault": 1}
    assert found["observations"][0]["text"] == GOOD["text"]


def test_ac_ho_04_observations_past_the_limit_are_dropped_and_bad_ones_use_no_slot(series):
    third = cite("take_01", 0.7, "elbow_flexion", "right", "arms", "The right elbow bends more in the first take.")
    items = [dict(GOOD, take="nope"), GOOD, dict(OTHER, at_s=7), OTHER, third]
    found = read(series, items, limit=2)
    assert [o["take_id"] for o in found["observations"]] == ["take_02", "take_01"]
    assert found["dropped"]["reasons"] == {"take not in the input": 1, "second not in the input": 1,
                                           "more than 2 observations": 1}
    assert found["dropped"]["count"] == 3


def test_ac_ho_04_the_count_of_drops_is_the_sum_of_its_reasons(series):
    items = [GOOD, "x", dict(GOOD, take="z"), dict(GOOD, take="y"), dict(OTHER, text="Bends 12 degrees."), 3]
    found = read(series, items)
    assert found["dropped"]["count"] == sum(found["dropped"]["reasons"].values()) == 5
    assert found["dropped"]["reasons"]["take not in the input"] == 2 and len(found["observations"]) == 1


# ---- AC-HO-05: the sentence ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,reason", [
    ("The right elbow bends more than the recording in the later takes too.", None),
    ("The right elbow bends more in the earlier takes.", None),
    ("The arms stay bent more than the recording in this take.", None),
    ("The elbow bends more than the recording at 0.9 s.", "names a time"),
    ("The elbow bends more than the recording at 0 s.", "names a time"),
    ("The elbow bends more than the recording at 2 seconds.", "names a time"),
    ("The right elbow bends 20 degrees more.", "adds a number"),
    ("The right elbow bends more by 10%.", "adds a number"),
    ("The right elbow bends more in three takes.", "adds a number"),
    ("The right elbow bends more than twice the recording.", "adds a number"),
    ("The right elbow bends more by half.", "adds a number"),
    ("The right elbow bends more in take_02.", "adds a number"),
    ("The right elbow bends more in take 2.", "adds a number"),
    ("The right knee bends more in the later takes.", "names a body part the cited fault does not name (knee)"),
    ("The right foot turns out in the later takes.", "names a body part the cited fault does not name (foot)"),
    ("The head drops while the right elbow bends more.", "names a body part the cited fault does not name (head)"),
    ("The back rounds while the elbow bends more.", "names a body part the cited fault does not name (trunk)"),
    ("The left elbow bends more than the recording.", "names a side the cited fault does not name (left elbow)"),
    ("The left arm bends more than the recording.", "names a side the cited fault does not name (left arm)"),
    ("A coach would fix the right elbow.", "uses a word this product does not use"),
    ("The right elbow bends more, a risk of injury.", "uses a word this product does not use"),
    ("A rehab cue for the right elbow.", "uses a word this product does not use"),
    ("Nice work on the right elbow.", "adds praise"),
    ("The right elbow is great, well done.", "adds praise"),
    ("See https://example.com for the right elbow.", "has a link"),
    ("The right elbow\nbends more.", "more than one line"),
    ("The right elbow bends more." + " x" * 70, "too long"),
    ("The right elbow​bends more.", "has a control character"),
    ("", "empty"), ("   ", "empty"), (None, "empty"), (5, "empty"),
])
def test_ac_ho_05_the_sentence_is_held_to_the_cited_fault(series, text, reason):
    kept, dropped = reasons(series, dict(GOOD, text=text))
    assert (dropped == {reason: 1} and kept == []) if reason else (dropped == {} and len(kept) == 1)


def test_ac_ho_05_the_cited_sides_decide_which_side_words_pass(series):
    # take_01's upper_arm_out is on both sides: either side word may be used for it; a right fault takes only "right"
    both = reasons(series, dict(OTHER, text="The left elbow swings out in this take."))
    right = reasons(series, dict(GOOD, text="The left elbow bends more in this take."))
    assert len(both[0]) == 1 and both[1] == {}
    assert right[0] == [] and list(right[1]) == ["names a side the cited fault does not name (left elbow)"]


def test_ac_ho_05_a_measure_that_names_a_group_allows_its_words_and_no_others(series):
    # elbow_flexion may name the elbow and the arm (template.NAMES); upper_arm_out also the shoulder
    arm = reasons(series, dict(OTHER, text="The arm swings out from the shoulder in this take."))
    assert len(arm[0]) == 1
    other = reasons(series, dict(GOOD, text="The shoulder lifts while the elbow bends more."))
    assert other[0] == [] and list(other[1]) == ["names a body part the cited fault does not name (shoulder)"]


def test_ac_ho_05_a_measure_the_names_table_lacks_falls_back_to_the_body_part_groups():
    new = prompt.build_series([analysis([fault("future_measure", "right", "arms", "more", 5.0, 0.5)])], ["t"])
    item = cite("t", 0.5, "future_measure", "right", "arms", "The right hand reaches further than the recording.")
    assert len(read(new, [item])["observations"]) == 1
    knee = dict(item, text="The right knee reaches further than the recording.")
    assert read(new, [knee])["observations"] == []


def test_ac_ho_05_the_text_is_trimmed_and_the_label_is_set_by_code_not_by_the_model(series):
    found = read(series, [dict(GOOD, text="  " + GOOD["text"] + "  ", label="verdict", lang="fr", evidence=5)])
    [obs] = found["observations"]
    assert obs["text"] == GOOD["text"] and obs["label"] == "model_opinion" and obs["lang"] == "en"
    assert obs["evidence"] == {"direction": "more", "magnitude_deg": 20.2}


# ---- AC-HO-05: the order of the series (the guard knows which take has nothing before or after it) -----------------
EARLIER = "The right elbow bends more than the recording in the earlier takes."
LATER = "The right elbow bends more than the recording in the later takes."
FIRST_REASON = "speaks of earlier takes but the cited take is the first"
LAST_REASON = "speaks of later takes but the cited take is the last"


def elbow(take, at_s, text, **extra):
    return cite(take, at_s, "elbow_flexion", "right", "arms", text, **extra)


@pytest.fixture(scope="module")
def elbows():
    """The same elbow fault in three takes: take_01 is the first of the series, take_03 the last."""
    docs = [analysis([fault(at_s=0.7)]), analysis([fault(at_s=0.9)]), analysis([fault(at_s=1.1)])]
    return prompt.build_series(docs, ["take_01", "take_02", "take_03"])


@pytest.mark.parametrize("take,at_s,text,reason", [
    ("take_01", 0.7, EARLIER, FIRST_REASON),
    ("take_01", 0.7, "The right elbow bends more than the recording in the previous take.", FIRST_REASON),
    ("take_01", 0.7, "The right elbow bends more than in prior takes.", FIRST_REASON),
    ("take_01", 0.7, LATER, None),
    ("take_01", 0.7, "The right elbow bends more than the recording in this take.", None),
    ("take_02", 0.9, EARLIER, None),
    ("take_02", 0.9, LATER, None),
    ("take_03", 1.1, LATER, LAST_REASON),
    ("take_03", 1.1, "The right elbow bends more than the recording in the next takes.", LAST_REASON),
    ("take_03", 1.1, "The right elbow bends more than in the following take.", LAST_REASON),
    ("take_03", 1.1, EARLIER, None),
    ("take_03", 1.1, "The right elbow bends more than the recording in this take.", None),
])
def test_ac_ho_05_earlier_takes_are_not_claimed_of_the_first_take_nor_later_takes_of_the_last(elbows, take, at_s, text,
                                                                                               reason):
    kept, dropped = reasons(elbows, elbow(take, at_s, text))
    assert (dropped == {reason: 1} and kept == []) if reason else (dropped == {} and len(kept) == 1)


ADVICE = "Keep the right elbow closer to the recording in your next take."


@pytest.mark.parametrize("take,at_s,text,reason", [
    ("take_03", 1.1, ADVICE, None),
    ("take_03", 1.1, "Try bending the right elbow less on their next take.", None),
    ("take_03", 1.1, "The right elbow bends more than the recording; aim for less in your next takes.", None),
    ("take_03", 1.1, "Keep the right elbow closer in the next take.", LAST_REASON),
    ("take_03", 1.1, "The right elbow bends more than the recording in the later takes.", LAST_REASON),
    ("take_03", 1.1, "Keep the right elbow closer in your next take, as it does in the following takes.", LAST_REASON),
    ("take_03", 1.1, "The right elbow bends more than the recording in other next takes.", LAST_REASON),
    # R2 of the 1.14.1 review: the possessive excused "next take" only, not "later takes" or "following takes"
    ("take_03", 1.1, "Your later takes show the right elbow closing in.", LAST_REASON),
    ("take_03", 1.1, "Your following takes show the right elbow closing in.", LAST_REASON),
    ("take_03", 1.1, "In their later take the right elbow bends more than the recording.", LAST_REASON),
    ("take_03", 1.1, "His following take shows the right elbow closing in.", LAST_REASON),
    ("take_03", 1.1, "Keep the right elbow closer in your next take.", None),
    ("take_02", 0.9, "Your later takes show the right elbow closing in.", None),
    ("take_01", 0.7, ADVICE, None),
    ("take_02", 0.9, ADVICE, None),
])
def test_tl_076_r9_advice_about_the_next_take_passes_and_a_claim_about_another_take_is_dropped_and_counted(
        elbows, take, at_s, text, reason):
    kept, dropped = reasons(elbows, elbow(take, at_s, text))
    assert (dropped == {reason: 1} and kept == []) if reason else (dropped == {} and len(kept) == 1)


def test_tl_076_r9_advice_about_the_next_take_passes_for_a_series_of_one_take_too():
    one = prompt.build_series([analysis([fault(at_s=0.7)])], ["take_01"])
    assert len(reasons(one, elbow("take_01", 0.7, ADVICE))[0]) == 1
    assert reasons(one, elbow("take_01", 0.7, LATER)) == ([], {LAST_REASON: 1})


def test_ac_ho_05_a_series_of_one_take_has_no_earlier_and_no_later_take():
    one = prompt.build_series([analysis([fault(at_s=0.7)])], ["take_01"])
    for text, reason in ((EARLIER, FIRST_REASON), (LATER, LAST_REASON)):
        assert reasons(one, elbow("take_01", 0.7, text)) == ([], {reason: 1})
    assert len(reasons(one, elbow("take_01", 0.7, "The right elbow bends more than the recording."))[0]) == 1


def test_ac_ho_05_the_order_is_checked_on_the_english_text_whatever_the_language_asked_for(elbows):
    found = read(elbows, [elbow("take_01", 0.7, EARLIER, line=SPANISH)], "es")
    assert found["observations"] == [] and found["dropped"]["reasons"] == {FIRST_REASON: 1}
    assert found["translation_fallbacks"] == 0


# ---- AC-HO-06: no invented numbers ----------------------------------------------------------------------------------
def test_ac_ho_06_every_number_that_is_kept_comes_from_the_input_and_the_text_has_none(series):
    items = [dict(GOOD, at_s=0.94, magnitude_deg=99, evidence={"magnitude_deg": 1}), dict(OTHER, at_s=0.4),
             dict(GOOD, text="Bends 5 degrees more."), dict(OTHER, text="It is three times larger.")]
    found = read(series, items)
    sent = {x for take in series.takes for row in take["faults"] for x in row.values() if isinstance(x, float)}
    for obs in found["observations"]:
        assert obs["at_s"] in sent and obs["evidence"]["magnitude_deg"] in sent
        assert not any(ch.isdigit() for ch in obs["text"])
    assert found["dropped"]["reasons"] == {"adds a number": 2}


# ---- the answer ------------------------------------------------------------------------------------------------------
def test_ac_ho_the_answer_may_come_with_words_around_the_json(series):
    text = "Here you go:\n```json\n" + json.dumps({"observations": [GOOD]}) + "\n```\nHope that helps."
    assert len(guard.read_history_answer(text, series, "en", 5)["observations"]) == 1


@pytest.mark.parametrize("text", ["no json here", "", "[]", "{}", '{"observations": null}', '{"observations": {}}',
                                  '{"observations": "none"}', '{"obs": []}', "{broken"])
def test_ac_ho_an_answer_without_an_observations_list_is_a_value_error(series, text):
    with pytest.raises(ValueError):
        guard.read_history_answer(text, series, "en", 5)


def test_ac_ho_an_empty_list_is_a_valid_answer(series):
    assert read(series, []) == {"observations": [], "dropped": {"count": 0, "reasons": {}}, "translation_fallbacks": 0}


# ---- AC-HO-09: the other language ----------------------------------------------------------------------------------
# ASM-014: a translated line that carries no number and no praise, with an English twin that passes the guard, says the
# same thing.
def test_ac_ho_09_a_checked_line_is_shown_and_its_english_twin_kept(series):
    [obs] = read(series, [dict(GOOD, line=f"  {SPANISH} ")], "es")["observations"]
    assert (obs["text"], obs["lang"], obs["text_en"]) == (SPANISH, "es", GOOD["text"])


@pytest.mark.parametrize("line", ["El codo se dobla 3 veces.", "Excelente trabajo con el codo.", "Bien hecho, codo.",
                                  "Gut gemacht!", "Linea\nDos", "", "   ", None, 7, ["x"], "y" * 201])
def test_ac_ho_09_a_line_that_fails_falls_back_and_is_counted_not_dropped(series, line):
    found = read(series, [dict(GOOD, line=line)], "es")
    [obs] = found["observations"]
    assert (obs["text"], obs["lang"], "text_en" in obs) == (GOOD["text"], "en", False)
    assert found["translation_fallbacks"] == 1 and found["dropped"]["count"] == 0


@pytest.mark.parametrize("line", [
    "El codo derecho se dobla mas, mira https://ejemplo.com para verlo.",
    "El codo derecho se dobla mas, mira www.ejemplo.com para verlo.",
    "El codo derecho se dobla mas; escribe a ayuda@ejemplo.com para verlo.",
    "El codo derecho se dobla mas\u200b que en la grabacion.",   # a zero-width space
    "El codo derecho se dobla mas\tque en la grabacion.",   # a tab
    "El coach dice que el codo derecho se dobla mas que en la grabacion.",
    "El codo derecho se dobla mas, un caso de rehab, que en la grabacion.",
])
def test_ac_ho_09_a_line_with_a_link_a_control_character_or_a_banned_word_falls_back_like_the_english_text(series, line):
    # check_translated let these through until N2 of the 1.14.0 recheck (TICKET-080); it now runs unsafe_problem itself
    assert check_translated({}, line, False) == f"translated line {guard.unsafe_problem(line)}"
    found = read(series, [dict(GOOD, line=line)], "es")
    [obs] = found["observations"]
    assert (obs["text"], obs["lang"], "text_en" in obs) == (GOOD["text"], "en", False)
    assert found["translation_fallbacks"] == 1 and found["dropped"]["count"] == 0


def test_ac_ho_09_english_asked_for_ignores_a_line_the_model_adds(series):
    [obs] = read(series, [dict(GOOD, line="Algo que no se pidio.")], "en")["observations"]
    assert (obs["text"], obs["lang"]) == (GOOD["text"], "en") and "text_en" not in obs


def test_ac_ho_09_a_line_cannot_rescue_an_english_text_that_fails(series):
    found = read(series, [dict(GOOD, text="The right knee bends more.", line=SPANISH)], "es")
    assert found["observations"] == [] and found["translation_fallbacks"] == 0
    assert list(found["dropped"]["reasons"]) == ["names a body part the cited fault does not name (knee)"]
