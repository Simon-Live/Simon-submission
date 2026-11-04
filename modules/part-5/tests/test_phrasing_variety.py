"""No phrase twice in one result (docs/specs/second-opinion.md AC-VA-01 to AC-VA-03, TICKET-045). No socket is opened.

The real fixture is the stock pair pexels-5034562 (the example) and pexels-8837221 (the take), which holds five faults.
The model is mocked by a client that answers per fault, so the answers do not depend on the order of the threads.
"""
import json
import re
from pathlib import Path

import pytest

from part5 import phrasing
from part5.phrasing import prompt, variety
from part5.phrasing.local_llm import HttpResult
from part5.pipeline import run
from test_phrasing import clean_env, no_network  # noqa: F401
from test_phrasing_muse_spark import live  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "fixtures/input/eval/real/pexels-5034562/skeleton.json"
FOLLOWER = ROOT / "fixtures/input/eval/real/pexels-8837221/skeleton.json"
WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")


@pytest.fixture(scope="module")
def faults():
    found = run(str(EXPECTED), str(FOLLOWER)).analysis["faults"]
    assert len(found) >= 4   # the fixture this test is about
    return found


class PerFault:
    """Answers each request from `answer(text_timed, shape_text)`; records the system prompts it saw."""

    def __init__(self, answer):
        self.answer, self.systems = answer, []

    def __call__(self, request):
        system, user = (m["content"] for m in request["body"]["messages"])
        self.systems.append(system)
        line = self.answer(json.loads(user)["text_timed"])
        return HttpResult(200, {"choices": [{"message": {"content": line}}]})


def shared_non_fact_runs(lines, faults):
    """Independent of `variety`: three-word runs two lines share, other than runs made of both faults' own words and
    function words. Empty means no phrase repeats."""
    def runs(text):
        words = WORD.findall(text.lower())
        return {tuple(words[i:i + 3]) for i in range(len(words) - 2)}

    shared = set()
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            facts = set(WORD.findall((faults[i]["text_timed"] + " " + faults[j]["text_timed"]).lower()))
            facts |= variety.FUNCTION_WORDS
            shared |= {r for r in runs(lines[i]) & runs(lines[j]) if not set(r) <= facts}
    return shared


def test_ac_va_03_a_filler_the_model_repeats_reaches_one_line_only(live, faults):  # noqa: F811
    client = PerFault(lambda timed: f"Your {timed}, keep it steady through the rep.")
    lines, record = phrasing.phrase(faults, "muse-spark", client=client)
    assert sum("keep it steady" in line for line in lines) == 1
    assert shared_non_fact_runs(lines, faults) == set()
    reasons = [e["fallback_reason"] for e in record["faults"]]
    assert reasons[0] is None and reasons[1:] == ["muse-spark: repeats a phrase of another line"] * (len(faults) - 1)
    assert [e["text"] for e in record["faults"]] == lines


def test_ac_va_03_varied_lines_are_all_kept(live, faults):  # noqa: F811
    endings = iter(["out past the recording", "well ahead of the teacher", "lower than the video shows",
                    "nearer each other in this clip", "wider apart by comparison", "as seen from the side"])
    answers = {f["text_timed"]: f"Your {f['text_timed']}, {next(endings)}." for f in faults}
    lines, record = phrasing.phrase(faults, "muse-spark", client=PerFault(answers.get))
    kept = [e["backend"] for e in record["faults"]]
    assert kept.count("muse-spark") >= 4 and shared_non_fact_runs(lines, faults) == set()
    assert "repeats a phrase of another line" not in json.dumps(record)


def test_ac_va_03_the_template_result_on_the_real_take_repeats_no_phrase(faults):
    lines, record = phrasing.phrase(faults, "template")
    assert shared_non_fact_runs(lines, faults) == set()
    assert variety.repeats(lines, faults, set(range(len(lines)))) == []


def test_ac_va_03_a_whole_live_analysis_holds_no_repeated_phrase_and_no_nice_effort(live):  # noqa: F811
    client = PerFault(lambda timed: f"Your {timed}, nice effort.")
    analysis = run(str(EXPECTED), str(FOLLOWER), phrasing="muse-spark", phrasing_client=client, live=True).analysis
    lines = [f["coaching"] for f in analysis["faults"]]
    assert "nice effort" not in json.dumps(analysis).lower()
    assert shared_non_fact_runs(lines, analysis["faults"]) == set()
    assert [e["text"] for e in analysis["phrasing"]["faults"]] == lines


def test_ac_va_01_the_prompt_offers_no_closing_phrase_and_a_shape_per_position(live, faults):  # noqa: F811
    client = PerFault(lambda timed: f"Your {timed}.")
    phrasing.phrase(faults, "muse-spark", client=client)
    assert all("keep going" not in s.lower() and "Add no closing phrase" in s for s in client.systems)
    shapes = [next(shape for shape in prompt.SHAPES if shape in s) for s in client.systems]
    assert len(set(shapes)) == min(len(faults), len(prompt.SHAPES))


def test_the_shape_with_fixed_opening_words_is_used_once_in_eight_faults():
    shapes = [prompt.shape_for(i) for i in range(8)]
    assert shapes.count(prompt.SHAPES[3]) == 1 and shapes[:4] == list(prompt.SHAPES)


def test_a_phrase_is_three_words_with_one_the_measurement_does_not_supply():
    fault = {"measure": "foot_out", "side": "right", "lateral": "right", "text": "right foot too far out",
             "text_timed": "right foot too far right at 1.9 s"}
    assert variety.phrases("Your right foot is too far right at 1.9 s.", fault) == set()
    assert ("keep", "it", "under") in variety.phrases("Your right foot is too far right, keep it under your hip", fault)


def test_a_template_line_is_never_replaced_even_when_it_repeats():
    fault = {"measure": "foot_out", "side": "right", "text": "x", "text_timed": "x"}
    lines = ["one two three", "one two three"]
    assert variety.repeats(lines, [fault, fault], replaceable=set()) == []
    assert variety.repeats(lines, [fault, fault], replaceable={1}, fallback_lines=["a", "b"]) == [1]
