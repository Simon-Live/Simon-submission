"""Timed AI phrasing, the live default (ADR-0008; AC-P01, AC-P03 to AC-P05). No socket is opened."""
import json

import pytest

from part5 import phrasing
from part5.phrasing import muse_spark, prompt, template
from part5.phrasing.local_llm import HttpResult
from test_phrasing import bare, clean_env, make_fault, no_network  # noqa: F401
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


@pytest.mark.parametrize("plain,negated", [
    ("Your right foot is too far to the right at 1.9 s.", "Your right foot is not too far to the right at 1.9 s."),
    ("Your right foot is too far right at 1.9 s", "Your right foot isn't too far right at 1.9 s"),
    ("Your right foot is too far right at 1.9 s", "Your right foot is no longer too far right at 1.9 s"),
    ("Your right foot is too far to the right at 1.9 s", "Your right foot is never too far to the right at 1.9 s"),
    ("Your right feet are too far to the right at 1.9 s", "Your right feet aren't too far to the right at 1.9 s"),
    ("Your right foot is toward the right at 1.9 s", "Your right foot is not toward the right at 1.9 s"),
    ("Your right foot sits too far to the right at 1.9 s", "Your right foot is not at all too far to the right at 1.9 s"),
    ("Right foot too far right at 1.9 s, keep it in", "Right foot not too far right at 1.9 s, keep it in"),
])
def test_a_negation_within_three_words_before_the_lateral_phrase_reverses_the_direction(plain, negated):
    """N2 of the TICKET-057 delta review: "is not too far to the right" was read as "too far to the right"."""
    assert problem(RIGHT_FOOT, plain) is None
    assert problem(RIGHT_FOOT, negated) == "wrong direction"


def test_a_negated_phrase_never_carries_the_direction_of_the_fault_whichever_side_it_names():
    assert problem(RIGHT_FOOT, "Your right foot is too far to the left at 1.9 s") == "wrong direction"   # as before
    assert problem(RIGHT_FOOT, "Your right foot is not too far to the left at 1.9 s") == "wrong direction"
    inward = timed("foot_out", "right", "less", "left")   # a foot too far in is too far left: the other fault
    assert problem(inward, "Your right foot is too far to the left at 1.9 s") is None
    assert problem(inward, "Your right foot is not too far to the left at 1.9 s") == "wrong direction"
    assert problem(inward, "Your right foot is not too far to the right at 1.9 s") == "wrong direction"


@pytest.mark.parametrize("line", [
    "It is not true that your right foot is too far to the right at 1.9 s",   # the negation is four words back
    "Not bad. Your right foot drifts too far to the right at 1.9 s",           # another clause
    "Your right foot, not a small one, drifts too far to the right at 1.9 s",  # the negation is four words back
    "Your right foot is not wrong: it drifts too far to the right at 1.9 s",   # another clause
])
def test_a_negation_out_of_reach_or_in_another_clause_leaves_the_direction_alone(line):
    assert problem(RIGHT_FOOT, line) is None


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


# ---- no praise in a fault line (AC-P09) ----------------------------------------------------------
REQUIRED_PRAISE = ("nice effort", "great job", "well done", "good job", "nice work")
KNEE = timed("knee_flexion", "both", "less", None, at_s=1.4, joint="knee")
SPARK_LINE = "Your knees are not bent enough at 1.4 s, nice effort."   # the line QA flagged on 2026-10-31


def test_the_praise_list_holds_the_five_phrases_the_ruling_names():
    assert set(REQUIRED_PRAISE) <= set(template.PRAISE_PHRASES)


def test_the_line_qa_flagged_is_a_valid_fault_line_but_for_its_praise():
    assert problem(KNEE, SPARK_LINE) == "adds praise"
    assert problem(KNEE, SPARK_LINE.replace(", nice effort", "")) is None


@pytest.mark.parametrize("phrase", template.PRAISE_PHRASES)
@pytest.mark.parametrize("shape", [
    "Your knees are not bent enough at 1.4 s, {p}.",     # an ending
    "{p}, your knees are not bent enough at 1.4 s.",     # an opening
    "Your knees are not bent {p} enough at 1.4 s.",      # in the middle
])
@pytest.mark.parametrize("case", [str, str.upper, str.title])
def test_each_praise_phrase_is_rejected_in_any_place_and_any_case(phrase, shape, case):
    assert problem(KNEE, shape.format(p=case(phrase))) == "adds praise"


def test_praise_is_matched_across_extra_spaces_and_a_curly_apostrophe_line():
    assert problem(KNEE, "Your knees are not bent enough at 1.4 s, nice   effort.") == "adds praise"
    assert problem(KNEE, "Your knees aren’t bent enough at 1.4 s, well done.") == "adds praise"


@pytest.mark.parametrize("line", [
    "Your knees are not bent enough at 1.4 s.",
    "Your knees are not bent enough at 1.4 s, keep going.",
    "Your knees are not bent enough at 1.4 s, almost there.",
    "Your knees are not bent enough at 1.4 s, which is a good place to look.",   # "good" alone is not praise
    "Your knees are not bent enough at 1.4 s, as well as the example shows.",    # nor "well" alone
])
def test_a_line_without_praise_passes_as_before(line):
    assert problem(KNEE, line) is None, line


def test_a_praise_phrase_inside_a_longer_word_is_not_praise():
    assert not template._PRAISE.search("a bravoure, a congratsx and a nicework")


def test_no_template_phrase_in_any_size_carries_praise():
    from part5 import words
    for measure, by_direction in words.PHRASES.items():
        for direction, entry in by_direction.items():
            slots = (entry,) if isinstance(entry, str) else entry
            for size in words.QUALIFIERS:
                q, nq, aq = words.QUALIFIERS[size]
                for slot in slots:
                    line = slot.format(side="left", q=q, nq=nq, aq=aq)
                    assert not template._PRAISE.search(line), (measure, direction, line)


# ---- more praise forms, hyphens, zero-width characters, and the untimed path (AC-P09) -------------
NEW_FORMS = ("nice try", "great start", "looking good", "excellent work", "solid effort", "you're doing great",
             "you are doing great")   # the forms the review of the first praise list found missing
# Named, so that no invisible character sits in this source file (U+200B, U+200C, U+200D, U+2060, U+FEFF).
ZERO_WIDTH = ("\N{ZERO WIDTH SPACE}", "\N{ZERO WIDTH NON-JOINER}", "\N{ZERO WIDTH JOINER}", "\N{WORD JOINER}",
              "\N{ZERO WIDTH NO-BREAK SPACE}")
ZWSP = ZERO_WIDTH[0]
PLAIN_KNEE = make_fault("knee_flexion", "right", "less", "right knee not bent enough", "right_knee")   # untimed


def plain(line):
    return template.line_problem(PLAIN_KNEE, line)


def test_the_praise_list_holds_every_form_the_review_found_missing():
    assert set(NEW_FORMS) <= set(template.PRAISE_PHRASES)


def test_the_lines_below_are_fault_lines_but_for_the_praise_they_carry():
    assert problem(KNEE, "Your knees are not bent enough at 1.4 s.") is None
    assert plain("Your right knee is not bent enough.") is None


@pytest.mark.parametrize("form", NEW_FORMS)
@pytest.mark.parametrize("case", [str, str.upper, str.title])
def test_each_new_form_is_praise_at_the_end_the_start_and_the_middle_on_both_paths(form, case):
    said = case(form)
    for line in (f"Your knees are not bent enough at 1.4 s, {said}.", f"{said}, your knees are not bent enough at 1.4 s.",
                 f"Your knees are not bent {said} enough at 1.4 s."):
        assert problem(KNEE, line) == "adds praise", line
    for line in (f"Your right knee is not bent enough, {said}.", f"{said}, your right knee is not bent enough.",
                 f"Your right knee is not bent {said} enough."):
        assert plain(line) == "adds praise", line


@pytest.mark.parametrize("line", [
    "Your knees are not bent enough at 1.4 s. You’re doing great.",       # the curly apostrophe a model writes
    "Your knees are not bent enough at 1.4 s. You’re Doing Great!",
])
def test_you_are_doing_great_is_caught_with_a_curly_apostrophe(line):
    assert problem(KNEE, line) == "adds praise"


@pytest.mark.parametrize("phrase", template.PRAISE_PHRASES)
@pytest.mark.parametrize("sep", ["-", " - ", "--", "\N{NO-BREAK SPACE}", "\t"],
                         ids=["hyphen", "spaced hyphen", "two hyphens", "no-break space", "tab"])
def test_the_words_of_a_phrase_may_be_joined_by_hyphens_or_other_white_space(phrase, sep):
    said = sep.join(phrase.split())
    assert problem(KNEE, f"Your knees are not bent enough at 1.4 s, {said}.") == "adds praise"
    assert plain(f"Your right knee is not bent enough, {said}.") == "adds praise"


def test_the_hyphenated_nice_effort_the_review_named_is_praise():
    assert problem(KNEE, "Your knees are not bent enough at 1.4 s, nice-effort.") == "adds praise"
    assert plain("Your right knee is not bent enough, nice-effort.") == "adds praise"


@pytest.mark.parametrize("zero_width", ZERO_WIDTH, ids=[f"U+{ord(z):04X}" for z in ZERO_WIDTH])
@pytest.mark.parametrize("phrase", template.PRAISE_PHRASES)
@pytest.mark.parametrize("hide", [
    lambda p, z: p.replace(" ", z),            # "nice<z>effort": the character is all that separates the words
    lambda p, z: p.replace(" ", f" {z}"),      # after the space
    lambda p, z: p.replace(" ", f"{z} "),      # before the space
    lambda p, z: p[0] + z + p[1:],             # inside the first word
    lambda p, z: z + p + z,                    # round the phrase
], ids=["only separator", "after space", "before space", "inside a word", "round the phrase"])
def test_a_zero_width_character_hides_no_praise(zero_width, phrase, hide):
    said = hide(phrase, zero_width)
    assert problem(KNEE, f"Your knees are not bent enough at 1.4 s, {said}.") == "adds praise"
    assert plain(f"Your right knee is not bent enough, {said}.") == "adds praise"


def test_the_zero_width_nice_effort_the_review_named_is_praise():
    assert problem(KNEE, f"Your knees are not bent enough at 1.4 s, nice{ZWSP}effort.") == "adds praise"
    assert plain(f"Your right knee is not bent enough, nice{ZWSP}effort.") == "adds praise"


@pytest.mark.parametrize("ending", [
    "good form otherwise", "well aligned otherwise", "keep going", "well-aligned otherwise", "good-natured",
    "try to keep it solid", "a good start position", "you are doing the squat", "looking at the mirror",
    "done with one rep", "it is a well known cue", "nicely paced",
])
def test_lines_that_only_share_a_word_with_a_praise_phrase_pass_on_both_paths(ending):
    assert problem(KNEE, f"Your knees are not bent enough at 1.4 s, {ending}.") is None, ending
    assert plain(f"Your right knee is not bent enough, {ending}.") is None, ending


def test_zero_width_characters_in_a_line_without_praise_do_not_make_praise():
    assert problem(KNEE, f"Your knees are not bent enough at 1.4 s, keep{ZWSP}going.") is None
    assert plain(f"Your right knee is not bent enough, good{ZWSP} form otherwise.") is None
    assert plain(f"Your right knee is not bent enough, well{ZWSP}aligned otherwise.") is None


def test_the_untimed_test_rejects_praise_with_the_same_reason_as_the_timed_one():
    assert plain("Your right knee is not bent enough, nice effort.") == "adds praise"
    assert plain("Your right knee is not bent enough, nice effort.") == problem(KNEE, SPARK_LINE)


def test_the_untimed_test_checks_the_shape_before_the_praise():
    assert plain("") == "empty line"
    assert plain("nice effort\nright knee not bent enough") == "more than one line"


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
                   "fallback_reason": None, "lang": "en"}


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
    assert bare(record["faults"][1]) == {"backend": "template", "model": None, "fallback_reason": reason}
    assert [record["faults"][i]["backend"] for i in (0, 2)] == ["muse-spark"] * 2
    assert [record["faults"][i]["model"] for i in (0, 2)] == [muse_spark.MODEL] * 2


def test_a_validator_failure_names_the_check_and_never_the_model_text(live):  # noqa: F811
    out = phrasing.phrase_fault(RIGHT_FOOT, client=Client(reply("Your left foot is 12 degrees off at 1.9 s")))
    assert out["text"] == RIGHT_FOOT["text_timed"] and out["backend"] == "template" and out["model"] is None
    assert out["fallback_reason"] == "muse-spark: adds a number" and "12" not in out["fallback_reason"]


@pytest.mark.parametrize("praise", REQUIRED_PRAISE)
def test_a_praised_line_falls_back_to_the_template_line_for_that_fault_alone(live, praise):  # noqa: F811
    faults = [timed(at_s=1.9), timed("thigh_out", "left", "less", "right", at_s=3.2), timed(at_s=4.0)]
    good = ["Your right foot drifts too far to the right at 1.9 s", f"Your left knee is too far right at 3.2 s, {praise}.",
            "Your right foot is too far right at 4.0 s, keep going."]
    lines, record = phrasing.phrase(faults, "muse-spark", client=Client(reply(good[0]), reply(good[1]), reply(good[2])))
    assert lines == [good[0], faults[1]["text_timed"], good[2]]
    # The reason is the existing "muse-spark: <what>" kind (a free string in the schema), and it holds none of the model's text.
    assert bare(record["faults"][1]) == {"backend": "template", "model": None, "fallback_reason": "muse-spark: adds praise"}
    assert praise not in json.dumps(record)
    assert [record["faults"][i]["backend"] for i in (0, 2)] == ["muse-spark"] * 2
    assert record["fallback_reason"] == "muse-spark: adds praise"


def test_the_flagged_spark_line_never_reaches_the_user(live):  # noqa: F811
    out = phrasing.phrase_fault(KNEE, client=Client(reply(SPARK_LINE)))
    assert out == {"text": KNEE["text_timed"], "model": None, "backend": "template",
                   "fallback_reason": "muse-spark: adds praise", "lang": "en"}


def test_the_template_backend_writes_text_timed():
    lines, _ = phrasing.phrase([RIGHT_FOOT, make_fault()], "template")
    assert lines == [RIGHT_FOOT["text_timed"], make_fault()["text"]]


def test_without_a_key_the_fault_falls_back_with_the_reason(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMON5_LIVE", "1")
    out = phrasing.phrase_fault(RIGHT_FOOT, client=Client())
    assert out == {"text": RIGHT_FOOT["text_timed"], "model": None, "backend": "template", "fallback_reason": "no key",
                   "lang": "en"}


# ---- limits and ledger (AC-P05) -----------------------------------------------------------------
def test_the_31st_call_in_a_minute_falls_back_with_rate_limited(live):  # noqa: F811
    faults = [timed(at_s=1.9)] * 31
    client = Client(*[reply("Your right foot is too far right at 1.9 s")] * 30)
    lines, record = phrasing.phrase(faults, "muse-spark", client=client, budget_s=1e9)
    assert len(client.requests) == 30
    assert bare(record["faults"][30]) == {"backend": "template", "model": None, "fallback_reason": "rate limited"}
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


def test_ac_p08_the_timed_prompt_asks_for_normal_punctuation_and_a_full_stop():
    """No live call and no key: the system message is built from the module alone. Since TICKET-045 the prompt offers
    no closing phrase, so the comma rule for one is gone with it."""
    system = prompt.timed_messages(RIGHT_FOOT)[0]["content"]
    assert prompt.system_timed(0) in system
    assert "Use normal punctuation and end the sentence with a full stop" in system


def test_ac_p09_the_timed_prompt_offers_no_praise_and_asks_for_none():
    """No live call and no key: the prompt asks for a fault line without praise and holds no praise phrase,
    because a phrase in a prompt comes back in nearly every line."""
    system = prompt.timed_messages(RIGHT_FOOT)[0]["content"]
    lowered = system.lower()
    assert "nice effort" not in lowered
    assert [p for p in template.PRAISE_PHRASES if p in lowered] == []
    assert "almost there" not in lowered
    assert "carries no praise or congratulation" in system and "Say what is off" in system
    assert "keep going" not in lowered and "Add no closing phrase" in system   # TICKET-045: no offered ending


def test_the_prompt_example_and_the_ending_it_allows_pass_the_validator():
    assert problem(RIGHT_FOOT, EXAMPLE) is None
    assert problem(RIGHT_FOOT, EXAMPLE + ", keep going.") is None


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


def test_ac_p07_pick_takes_stock_first_then_kit_and_only_then_synthetic_each_spread_by_measure():
    """TICKET-061 (lost intent, salvage/ticket-038-partial): `pick` used to spread over all three tiers at once."""
    from part5.phrasing import review
    stock, kit, synthetic = "pexels-1", "squat_front_x", "exercise_front_good_03_y"
    faults = ([(stock, {"measure": m}) for m in "aab"] + [(kit, {"measure": m}) for m in "aabbc"]
              + [(synthetic, {"measure": m}) for m in "ddd"])
    def took(n):
        return [(review.source_of(t), f["measure"]) for t, f in review.pick(faults, n)]

    assert took(2) == [("stock", "a"), ("stock", "b")]                                  # the stock takes alone fill 2
    assert took(6) == [("stock", "a"), ("stock", "b"), ("stock", "a"),                  # all stock, then the kit takes
                       ("kit", "a"), ("kit", "b"), ("kit", "c")]                         # spread by measure
    assert took(8) == took(6) + [("kit", "a"), ("kit", "b")]                            # the kit takes run out last
    assert [s for s, _ in took(9)][-1] == "synthetic" and [s for s, _ in took(9)].count("synthetic") == 1
    assert len(took(99)) == len(faults) and review.pick(faults, 0) == []                 # never more than there are


def test_ac_p07_the_real_fixtures_give_7_stock_and_13_kit_lines_and_no_synthetic_one():
    """The stock takes hold 7 faults and the kit takes 14: 20 lines are 7 stock and 13 kit (it was 7, 9 and 4)."""
    from collections import Counter

    from part5.phrasing import review
    faults = review.timed_faults()
    held = Counter(review.source_of(take) for take, _ in faults)
    assert held["stock"] < 20 <= held["stock"] + held["kit"]                             # the case AC-P07 describes
    assert Counter(review.source_of(take) for take, _ in review.pick(faults, 20)) == {"stock": 7, "kit": 13}
    assert (held["stock"], held["kit"]) == (7, 14)


def test_review_exits_1_without_the_key_and_makes_no_call(capsys):
    from part5.phrasing import review
    assert review.main(["--n", "1"]) == 1
    assert "no key" in capsys.readouterr().err
