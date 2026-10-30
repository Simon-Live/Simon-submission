"""The phrasing registry, the template backend and the word test (ADR-0005; AC-010, AC-012, AC-NFR-002)."""
import json
import socket
from pathlib import Path

import jsonschema
import pytest

from part5 import phrasing
from part5.detect import generic
from part5.measures import MEASURES
from part5.phrasing import muse_spark, template
from part5.words import PHRASES, QUALIFIERS, phrase as words_phrase

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "contracts/analysis.schema.json").read_text())
PHRASING_SCHEMA = jsonschema.Draft202012Validator(SCHEMA["properties"]["phrasing"])


class NetworkUsed(BaseException):
    """Raised by the socket guard. A BaseException, so no `except Exception` in the code can hide it."""


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """AC-NFR-002: nothing in these tests may open a socket."""
    def refuse(*args, **kwargs):
        raise NetworkUsed("a test tried to use the network")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """Hermetic: no live gate, no model, and the key and ledger point into tmp, never at the real files."""
    for name in ("META_LIVE", "SIMON5_LIVE", "PART5_OLLAMA_MODEL", "PART5_MUSE_PER_MINUTE", "PART5_PHRASING_BUDGET_S"):
        monkeypatch.delenv(name, raising=False)
    # Scripted clients answer in call order, so these tests run one call at a time; the concurrent
    # tests (test_phrasing_concurrent) set PART5_PHRASING_CONCURRENCY themselves.
    monkeypatch.setenv("PART5_PHRASING_CONCURRENCY", "1")
    muse_spark._calls.clear()  # the process-wide rate limit starts empty in every test
    monkeypatch.setenv("PART5_BASETEN_KEY_FILE", str(tmp_path / "no-key-here"))
    monkeypatch.setenv("PART5_BASETEN_USAGE_FILE", str(tmp_path / "usage.jsonl"))


def make_fault(measure="foot_out", side="left", direction="more", text=None, joint="left_ankle",
               body_part="legs", **extra):
    fault = {"measure": measure, "joint": joint, "side": side, "direction": direction,
             "body_part": body_part, "magnitude_deg": 14.2, "threshold_deg": 6.0, "peak_deg": 18.0,
             "expected_frames": [20, 52], "follower_frames": [22, 55],
             "text": text or f"{side} {measure} {direction}"}
    fault.update(extra)
    return fault


FOOT = make_fault(text="left foot too far out")
KNEE = make_fault("knee_flexion", "right", "less", "right knee not bent enough", "right_knee")
TRUNK = make_fault("trunk_lean_forward", "center", "more", "leaning forward more than the example",
                   "spine", "torso")
FAULTS = [FOOT, KNEE, TRUNK]


# ---- the registry and the template backend -----------------------------------------------------
def test_template_returns_each_faults_text_in_order():
    lines, record = phrasing.phrase(FAULTS)
    assert lines == [f["text"] for f in FAULTS]
    assert record == {"requested": "template", "backend": "template", "model": None,
                      "fallback_reason": None,
                      "faults": [{"backend": "template", "model": None, "fallback_reason": None}] * 3}


def test_template_is_the_default_and_needs_no_network_or_files():
    assert phrasing.phrase(FAULTS) == phrasing.phrase(FAULTS, "template")


def test_ac012_template_is_deterministic():
    runs = [phrasing.phrase(FAULTS, "template") for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]
    assert json.dumps(runs[0], sort_keys=True) == json.dumps(runs[2], sort_keys=True)


def test_template_with_no_faults():
    lines, record = phrasing.phrase([], "template")
    assert lines == [] and record["faults"] == [] and record["backend"] == "template"


def test_an_unknown_backend_raises_value_error():
    with pytest.raises(ValueError, match="unknown phrasing backend 'gpt'"):
        phrasing.phrase(FAULTS, "gpt")


def test_the_registry_names_the_three_backends_of_the_schema():
    assert set(phrasing.BACKENDS) == set(SCHEMA["properties"]["phrasing"]["properties"]["requested"]["enum"])


@pytest.mark.parametrize("backend", ["template", "local-llm", "muse-spark"])
def test_ac010_the_record_validates_against_the_analysis_schema(backend):
    _, record = phrasing.phrase(FAULTS, backend)
    PHRASING_SCHEMA.validate(record)
    assert list(record) == ["requested", "backend", "model", "fallback_reason", "faults"]
    assert len(record["faults"]) == len(FAULTS)


@pytest.mark.parametrize("backend", ["local-llm", "muse-spark"])
def test_a_backend_with_no_faults_phrases_nothing_and_reports_template(backend, monkeypatch, tmp_path):
    key = tmp_path / "key"
    key.write_text("k\n")
    monkeypatch.setenv("PART5_BASETEN_KEY_FILE", str(key))
    monkeypatch.setenv("META_LIVE", "1")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ollama")
    monkeypatch.setenv("PART5_OLLAMA_MODEL", "tiny")
    lines, record = phrasing.phrase([], backend)
    assert lines == [] and record["backend"] == "template"
    assert record["requested"] == backend and record["fallback_reason"] == phrasing.NO_FAULTS


# ---- the word test: the template passes its own test ---------------------------------------------
def generic_measures():
    return {generic(m)[0]: generic(m)[1] for m in MEASURES}


def template_cases():
    """(measure, side, direction, line) for every phrase `words` can write, every size."""
    cases = []
    for measure, direction_map in PHRASES.items():
        centre = generic_measures().get(measure) == "center"
        for direction in direction_map:
            for side in (["center"] if centre else ["left", "right", "both"]):
                for size in QUALIFIERS:
                    cases.append((measure, side, direction, words_phrase(measure, direction, side, size)))
    # knee_valgus words land with the knee caving work: "caving in" for more, "pushed out" for less.
    for side, subject in (("left", "left knee"), ("right", "right knee"), ("both", "knees")):
        for q in ("", "slightly ", "much "):
            cases.append(("knee_valgus", side, "more", f"{subject} {q}caving in"))
            cases.append(("knee_valgus", side, "less", f"{subject} {q}pushed out"))
    return cases


TEMPLATE_CASES = template_cases()


@pytest.mark.parametrize("measure,side,direction,line", TEMPLATE_CASES)
def test_every_template_line_passes_the_word_test(measure, side, direction, line):
    fault = make_fault(measure, side, direction)
    assert template.line_problem(fault, line) is None, line


def test_the_word_test_has_a_rule_for_every_measure_words_writes():
    assert set(PHRASES) <= set(template.RULES) and set(template.NAMES) == set(template.RULES)
    assert len(TEMPLATE_CASES) > 150


@pytest.mark.parametrize("measure,side,direction,line", TEMPLATE_CASES)
def test_a_template_line_fails_the_word_test_for_the_opposite_direction(measure, side, direction, line):
    flipped = make_fault(measure, side, "less" if direction == "more" else "more")
    assert template.line_problem(flipped, line) == "wrong direction", line


# ---- the word test: lines it must accept --------------------------------------------------------
@pytest.mark.parametrize("fault,line", [
    (FOOT, "left foot too far out"),
    (FOOT, "Left foot sticking out too far."),
    (FOOT, "your left foot is turned out wider than the example"),
    (KNEE, "right knee isn't bent enough"),
    (KNEE, "right knee straighter than the example"),
    (make_fault("knee_flexion", "right", "more"), "right knee bent more than the example"),
    (make_fault("upper_arm_out", "both", "more"), "both elbows wider than the example"),
    (make_fault("upper_arm_out", "both", "less"), "arms tucked in against the body"),
    (make_fault("thigh_forward", "left", "less"), "left thigh not lifted high enough"),
    (make_fault("trunk_lean_forward", "center", "less"), "standing more upright than the example"),
    (make_fault("head_forward", "center", "more"), "head poking further forward than the example"),
    (make_fault("shoulder_tilt", "center", "less"), "right shoulder higher than the example"),
    (make_fault("knee_valgus", "left", "more"), "left knee collapsing inward"),
])
def test_it_accepts_a_fair_rewording(fault, line):
    assert template.line_problem(fault, line) is None


# ---- the word test: lines it must refuse, with the reason ---------------------------------------
@pytest.mark.parametrize("fault,line,reason", [
    (FOOT, "right foot too far out", "wrong side"),
    (FOOT, "foot too far out", "wrong side"),
    (FOOT, "left and right foot too far out", "wrong side"),
    (make_fault("upper_arm_out", "both", "more"), "left elbow wider than the example", "wrong side"),
    (make_fault("head_forward", "center", "more"), "left of the head is further forward", "wrong side"),
    (FOOT, "left foot 12 degrees too far out", "adds a number"),
    (FOOT, "left foot too far out by 12", "adds a number"),
    (FOOT, "left foot twelve degrees too far out", "adds a number"),
    (FOOT, "left foot too far out, about 30%", "adds a number"),
    (FOOT, "left foot too far out by two inches", "adds a number"),
    (FOOT, "left knee too far out", "does not name the body part"),
    (FOOT, "left too far out", "does not name the body part"),
    (FOOT, "left foot and knee too far out", "adds another body part (knee)"),
    (FOOT, "left foot too far out and your head is forward", "adds another body part (head)"),
    (make_fault("trunk_lean_forward", "center", "more"), "leaning forward and the knees are bent",
     "adds another body part (knee)"),
    (FOOT, "left foot too far in", "wrong direction"),
    (FOOT, "left foot too far out and too far in", "contradicts itself on the direction"),
    (FOOT, "left foot is a problem", "does not say how it differs"),
    (make_fault("knee_flexion", "left", "more"), "left knee bent less than the example", "wrong direction"),
    (make_fault("knee_flexion", "left", "more"), "left knee not bent enough", "wrong direction"),
    (make_fault("knee_flexion", "left", "less"), "left knee bent more than the example", "wrong direction"),
    (make_fault("upper_arm_forward", "left", "more"), "left arm not raised enough", "wrong direction"),
    (make_fault("trunk_lean_side", "center", "more"), "leaning to the right", "wrong direction"),
    (make_fault("trunk_lean_side", "center", "more"), "leaning to the left and to the right",
     "contradicts itself on the direction"),
    (FOOT, "", "empty line"),
    (FOOT, "   ", "empty line"),
    (FOOT, "left foot too far out\nright foot too far out", "more than one line"),
    (FOOT, "left foot too far out " + "and so on " * 20, "line too long"),
    (make_fault("not_a_measure", "left", "more"), "left foot too far out", "no word test for measure 'not_a_measure'"),
])
def test_it_refuses_a_line_that_does_not_match_the_fault(fault, line, reason):
    assert template.line_problem(fault, line) == reason


def test_a_curly_apostrophe_counts_as_a_negation():
    assert template.line_problem(KNEE, "right knee isn’t bent enough") is None


def test_the_reason_never_quotes_the_line():
    problem = template.line_problem(FOOT, "left foot too far out SENTINEL-TEXT 77")
    assert "SENTINEL-TEXT" not in problem and "77" not in problem
