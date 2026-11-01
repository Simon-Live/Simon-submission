"""The local backend's grammar rules and the doubled body-part test (Part 7, Muse Glimmer 30B wrote "Arms elbows wider
than the example at 0.4 s"; docs/specs/second-opinion.md AC-VA-03). No socket is opened: every client is a fake."""
import pytest

from part5 import phrasing
from part5.phrasing import local_llm, template
from test_phrasing import FAULTS, bare, clean_env, make_fault, no_network  # noqa: F401
from test_phrasing_muse_spark import Client, live, reply  # noqa: F401

GLIMMER_LINE = "Arms elbows wider than the example at 0.4 s."


def elbows(at_s=0.4):
    """Both elbows wider than the example, as the analysis words it: `body_part` arms, the part named in the words."""
    return make_fault("upper_arm_out", "both", "more", text="elbows wider than the example", joint="left_elbow",
                      body_part="arms", at_s=at_s, lateral=None, text_timed=f"elbows wider than the example at {at_s:.1f} s")


def problem(fault, line):
    return template.line_problem(fault, line, timed=fault.get("at_s") is not None)


@pytest.fixture
def ollama(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
    monkeypatch.setenv("PART5_OLLAMA_MODEL", "tiny-coach")


def system_text(request):
    return request["body"]["messages"][0]["content"]


# ---------------------------------------------------------------- the word test
def test_the_glimmer_line_fails_the_word_test_with_the_doubled_noun_named():
    assert problem(elbows(), GLIMMER_LINE) == "doubles the body part (arms elbows)"


@pytest.mark.parametrize("line", [
    "Your elbows are wider than the example at 0.4 s.",
    "Elbows wider than the example at 0.4 s.",
    "At 0.4 s, your arms and elbows are wider than the example.",   # a conjunction between two nouns is not a doubling
    "Your arms are wider than the example, elbows included, at 0.4 s.",
    "Your elbows are wider than the example at 0.4 s, out past your trunk.",
])
def test_the_repaired_line_and_other_sound_lines_pass(line):
    assert problem(elbows(), line) is None


@pytest.mark.parametrize("line,pair", [
    ("Arm elbow wider than the example at 0.4 s.", "arm elbow"),
    ("Your arms elbows are wider than the example at 0.4 s.", "arms elbows"),
    ("Your elbows elbows are wider than the example at 0.4 s.", "elbows elbows"),
    ("At 0.4 s your shoulder arms are wider than the example.", "shoulder arms"),
    ("ARMS ELBOWS wider than the example at 0.4 s", "arms elbows"),
])
def test_two_body_part_nouns_side_by_side_fail(line, pair):
    assert problem(elbows(), line) == f"doubles the body part ({pair})"


def test_a_doubled_noun_fails_before_the_facts_are_checked_and_in_an_untimed_line_too():
    knee = make_fault("knee_flexion", "right", "less", "right knee not bent enough", "right_knee", body_part="legs")
    assert problem(knee, "right leg knee not bent enough") == "doubles the body part (leg knee)"
    assert problem(knee, "right knee not bent enough") is None


@pytest.mark.parametrize("line", [
    "Your feet face out at 1.2 s.", "Your knees face inward at 1.2 s.", "Your hips face the side at 1.2 s.",
    "Your toes face out at 1.2 s.", "Feet shoulder-width apart at 1.2 s.", "Your feet shoulder width apart at 1.2 s.",
    "Your heels shoulder-height at 1.2 s.",
])
def test_review_r4_face_as_a_verb_and_shoulder_width_are_not_a_doubled_noun(line):
    assert template._doubled_part(line.lower()) is None


@pytest.mark.parametrize("line,pair", [
    ("Arms elbows wider than the example at 0.4 s.", "arms elbows"),
    ("Your feet shoulders are wide at 1.2 s.", "feet shoulders"),
    ("Your hand wrist is bent at 1.2 s.", "hand wrist"),
    ("Your shoulder arms are wide at 1.2 s.", "shoulder arms"),
])
def test_review_r4_a_real_doubling_is_still_rejected(line, pair):
    assert template._doubled_part(line.lower()) == f"doubles the body part ({pair})"


def at(measure, side, direction, text, body_part, joint="left_ankle", at_s=1.2):
    """A timed fault of `measure`, worded `text` (the part named once), for the word test."""
    return make_fault(measure, side, direction, text=text, joint=joint, body_part=body_part, at_s=at_s, lateral=None,
                      text_timed=f"{text} at {at_s:.1f} s")


FACE_FAULTS = {   # the lines of Part 7's review: "face" is the verb of the feet, toes, knees and hips
    "Your feet face out at 1.2 s.": at("foot_rotation", "both", "more", "feet turned out", "feet"),
    "Your toes face out at 1.2 s.": at("foot_rotation", "both", "more", "toes turned out", "feet"),
    "Your knees face inward at 1.2 s.": at("knee_valgus", "both", "more", "knees caving in", "legs", "left_knee"),
    "Your hips face out to the side at 1.2 s.": at("thigh_out", "both", "more", "legs too far out", "legs", "left_hip"),
}


@pytest.mark.parametrize("line", FACE_FAULTS)
def test_recheck_1_face_as_a_verb_after_a_plural_part_passes_the_word_test_the_student_sees(line):
    """The review of the doubled-noun fix: `_doubled_part` passed these lines but the body test read "face" as the
    head and sent them back to the template ("adds another body part (head)")."""
    fault = FACE_FAULTS[line]
    assert template._doubled_part(line.lower()) is None
    assert problem(fault, line) is None
    assert template.line_problem(fault, line.replace(" at 1.2 s", ""), timed=False) is None   # and without the time


def test_recheck_1_the_head_noun_face_is_still_the_head():
    foot = FACE_FAULTS["Your feet face out at 1.2 s."]
    assert problem(foot, "Your face and feet turn out at 1.2 s.") == "adds another body part (head)"
    assert problem(foot, "Your feet turn out, face forward, at 1.2 s.") == "adds another body part (head)"
    assert problem(foot, "Your face is level and your feet turn out at 1.2 s.") == "adds another body part (head)"
    head = make_fault("head_forward", "center", "more", "head too far forward", "nose", "head", at_s=1.2, lateral=None,
                      text_timed="head too far forward at 1.2 s")
    assert problem(head, "Your face pokes forward at 1.2 s.") is None


def test_recheck_1_face_after_a_part_is_a_verb_only_after_a_body_part_noun():
    assert template.parts_named("your feet face out") == {"foot"}
    assert template.parts_named("your face and feet") == {"head", "foot"}
    assert template.parts_named("face the wall, feet out") == {"head", "foot"}
    assert template.parts_named("your hips face the side") == {"hip"}
    assert template.without_face_verbs("knees face inward, toes face out") == "knees inward, toes out"
    assert template.without_face_verbs("her face is level") == "her face is level"


def test_review_r4_a_sound_line_with_shoulder_width_passes_the_word_test():
    feet = make_fault("foot_out", "both", "more", text="feet too far out", joint="left_ankle", body_part="legs",
                      at_s=1.2, lateral=None, text_timed="feet too far out at 1.2 s")
    assert problem(feet, "Your feet are shoulder-width apart at 1.2 s.") is None
    assert problem(feet, "Your feet shoulders are apart at 1.2 s.") == "doubles the body part (feet shoulders)"


def test_a_doubled_noun_makes_the_registry_fall_back_to_the_template_line(ollama):
    fault = elbows()
    lines, record = phrasing.phrase([fault], "local-llm", client=Client(reply(GLIMMER_LINE)))
    assert lines == [fault["text_timed"]]
    entry = record["faults"][0]
    assert entry["backend"] == "template"
    assert entry["fallback_reason"] == "local-llm: doubles the body part (arms elbows)"


def test_the_repaired_line_is_kept_by_the_registry(ollama):
    lines, record = phrasing.phrase([elbows()], "local-llm", client=Client(reply("Your elbows are wider than the example at 0.4 s.")))
    assert lines == ["Your elbows are wider than the example at 0.4 s."]
    assert record["faults"][0]["backend"] == "local-llm" and record["fallback_reason"] is None


# ---------------------------------------------------------------- the local prompt
def test_the_local_timed_prompt_carries_the_grammar_rules_and_one_example(ollama):
    client = Client(reply("Your elbows are wider than the example at 0.4 s."))
    phrasing.phrase([elbows()], "local-llm", client=client)
    text = system_text(client.requests[0])
    assert local_llm.GRAMMAR_PART_ONCE_TIMED in text
    assert "Name the body part once" in text and "leave the group word out" in text
    assert "\"is\" after one part, \"are\" after two or more" in text
    assert "Your knees are not bent enough at <at_s> s." in text
    assert "arms elbows" not in text.lower()          # the failing line is never shown to the model
    assert text.endswith(local_llm.GRAMMAR_PART_ONCE_TIMED)


def test_the_local_plain_prompt_carries_the_part_once_rule_only(ollama):
    client = Client(*(reply(line) for line in ["left foot sticking out too far", "right knee not bent enough",
                                               "leaning forward more than the example"]))
    phrasing.phrase(FAULTS, "local-llm", client=client)
    for request in client.requests:
        text = system_text(request)
        assert text.endswith(local_llm.GRAMMAR_PART_ONCE) and "Grammar example" not in text
        assert local_llm.SYSTEM in text


def test_the_grammar_is_added_to_the_local_backend_alone(live):
    client = Client(reply("Your elbows are wider than the example at 0.4 s."))
    phrasing.phrase([elbows()], "muse-spark", client=client)
    assert "Name the body part once" not in system_text(client.requests[0])
    assert "Grammar example" not in system_text(client.requests[0])


def test_the_default_messages_have_no_grammar_so_muse_sparks_prompt_is_unchanged():
    fault = elbows()
    assert local_llm.messages(fault) == local_llm.messages(fault, extra_rules="")
    assert "Name the body part once" not in local_llm.messages(fault)[0]["content"]
    assert local_llm.messages(fault, extra_rules="X")[0]["content"].endswith("X")
    assert local_llm.grammar(fault) == "\n" + local_llm.GRAMMAR_PART_ONCE_TIMED
    assert local_llm.grammar(dict(fault, at_s=None)) == "\n" + local_llm.GRAMMAR_PART_ONCE


def test_the_grammar_text_obeys_the_writers_bans():
    text = local_llm.GRAMMAR_PART_ONCE + local_llm.GRAMMAR_PART_ONCE_TIMED
    assert "\N{EM DASH}" not in text and "\N{EN DASH}" not in text and " - " not in text
