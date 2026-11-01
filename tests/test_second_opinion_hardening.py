"""The consolidated review of the rubric integration, the guard, the call and the document
(docs/specs/second-opinion.md; findings B2, R1, R3, R5, R6, R7, R9, R10, R13).

The Meta Model API is the fake client of tests/test_second_opinion.py; no socket is opened.
"""
import io
import json
import urllib.error
from pathlib import Path

import pytest

from part5.opinion import guard, meta_api
from part5.opinion.meta_api import OpinionError
from part5.output import OutputError, validate_analysis
from test_second_opinion import (  # noqa: F401  (the fixtures are used by name)
    UPPER, Fake, all_verdicts, answer, attach, clip_showing, meta, take)

ROOT = Path(__file__).resolve().parents[1]
REAL_PREPARE = meta_api.prepare   # the fixture `meta` replaces it; the real one is tested here
SHOWS = guard.supported(clip_showing(*UPPER))
LEFT_ARM_ONLY = guard.supported(clip_showing("left_elbow", "left_shoulder"))


def problem(text, shows=SHOWS):
    return guard.text_problem(text, 4.0, shows)


# ---- B2: any other number --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "The left elbow bends about ten degrees more.",
    "The left elbow drops three times.",
    "The left elbow drops twice.",
    "The left elbow bends by half as much.",
    "The left elbow drops 50% lower.",
    "The left elbow bends two inches more.",
    "The left elbow drops for five seconds.",
    "The left elbow bends a hundred percent.",
    "The left elbow bends by a dozen degrees.",
    "The left elbow is doubled over.",
])
def test_review_b2_a_number_in_words_units_or_counts_is_refused(text):
    assert problem(text) == "adds a number"


@pytest.mark.parametrize("text", [
    "One elbow stays bent at 1.5 s.",
    "The left elbow often drops before the rep ends.",
    "The left elbow stays level, as the teacher's does.",
    "The left elbow drops at 3 seconds, as the teacher's does.",
    "Between 1.0 s and 2.5 s the left elbow stays bent.",
])
def test_review_b2_a_time_inside_the_clip_and_words_that_are_not_numbers_pass(text):
    assert problem(text) is None


# ---- R5: more body words ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,group", [
    ("The shins stay vertical.", "foot"), ("The calves stay loose.", "foot"), ("The left calf stays loose.", "foot"),
    ("The soles stay flat.", "foot"),
])
def test_review_r5_a_leg_word_needs_the_leg_joints(text, group):
    assert problem(text) == f"names a body part the clip does not show ({group})"


@pytest.mark.parametrize("text", ["The quads stay soft.", "The hamstrings stay long.", "The groin stays loose."])
def test_review_r5_a_thigh_word_needs_the_hips_or_the_knees(text):
    assert problem(text, LEFT_ARM_ONLY) == "names a body part the clip does not show (thigh)"
    assert problem(text, guard.supported(clip_showing("left_knee", "right_knee"))) is None


@pytest.mark.parametrize("text,clip_joints,group", [
    ("The back rounds late.", ("left_elbow", "left_wrist"), "trunk"),
    ("Your upper back is flat.", ("left_elbow", "left_wrist"), "trunk"),
    ("Back stays straight.", ("left_elbow", "left_wrist"), "trunk"),
    ("The stomach stays tight.", ("left_elbow", "left_wrist"), "trunk"),
    ("The waist stays level.", ("left_shoulder", "right_shoulder", "left_elbow"), "hip"),
    ("The glutes stay tight.", ("left_shoulder", "right_shoulder", "left_elbow"), "hip"),
    ("The eyes look down.", tuple(j for j in UPPER if j != "nose"), "head"),
    ("The jaw stays relaxed.", tuple(j for j in UPPER if j != "nose"), "head"),
    ("The fingers spread wide.", ("left_elbow", "left_shoulder"), "hand"),
    ("The biceps stay relaxed.", ("left_shoulder", "left_hip"), "arm"),
])
def test_review_r5_a_body_word_outside_the_phrasing_vocabulary_needs_its_joints(text, clip_joints, group):
    assert problem(text, guard.supported(clip_showing(*clip_joints))) == \
        f"names a body part the clip does not show ({group})"


@pytest.mark.parametrize("text", [
    "The back rounds late.", "The shins stay vertical.", "The waist stays level.", "The eyes look down.",
])
def test_review_r5_the_same_words_pass_when_the_clip_shows_the_part(text):
    shows = guard.supported(clip_showing(*UPPER, "left_knee", "right_knee", "left_ankle", "right_ankle",
                                         "left_eye", "right_eye"))
    assert problem(text, shows) is None


@pytest.mark.parametrize("text", [
    "The left elbow swings back.", "The left elbow steps back to the start.", "The left elbow stays bent, back and forth.",
    "The left elbow goes back toward the teacher's position.",
])
def test_review_r5_back_as_a_direction_is_not_the_trunk(text):
    assert "trunk" not in LEFT_ARM_ONLY
    assert problem(text, LEFT_ARM_ONLY) is None


NO_TRUNK = guard.supported(clip_showing("left_shoulder", "left_elbow", "left_wrist", "left_hip", "right_hip", "left_knee",
                                         "left_ankle", "right_ankle"))   # no right shoulder: the trunk is not shown


@pytest.mark.parametrize("text", [
    "The back hip drops lower than the teacher's.", "The back hips drop lower than the teacher's.",
    "The back shoulder rolls forward.", "The back ankle turns out.", "The back toe lifts early.",
    "The back wrist bends late.", "The back side stays level.", "The back sides stay level.",
    "The weight shifts to the back.", "The weight moves toward the back.", "The weight moves towards the back.",
    "The left elbow moves back and forth.", "Back and forth, the left elbow bends.",
    "The back foot, the back leg and the back knee stay planted.", "The back heel lifts.",
])
def test_recheck_2_back_as_a_direction_or_the_far_one_of_a_pair_is_not_the_trunk(text):
    assert "trunk" not in NO_TRUNK
    assert problem(text, NO_TRUNK) is None


@pytest.mark.parametrize("text", [
    "The back rounds late.", "Your upper back is flat.", "Back stays straight.", "His back rounds.",
    "The back and shoulders drop together.", "The back rounds, and the weight shifts to the back.",
    "The lower back arches.",
])
def test_recheck_2_back_as_the_noun_is_still_the_trunk(text):
    assert problem(text, NO_TRUNK) == "names a body part the clip does not show (trunk)"


def test_recheck_2_the_pair_words_still_need_their_own_joints():
    assert problem("The back hip drops.", LEFT_ARM_ONLY) == "names a body part the clip does not show (hip)"
    assert problem("The back ankle turns out.", LEFT_ARM_ONLY) == "names a body part the clip does not show (foot)"


def test_recheck_1_the_guard_reads_face_after_a_body_part_as_a_verb_and_the_head_noun_as_the_head():
    feet_only = guard.supported(clip_showing("left_ankle", "right_ankle", "left_knee", "right_knee"))
    assert "head" not in feet_only
    for text in ("Your feet face out more than the teacher's.", "The knees face inward.", "The toes face out."):
        assert problem(text, feet_only) is None
    for text in ("Your face is level.", "The face turns down.", "Your face and feet turn out."):
        assert problem(text, feet_only) == "names a body part the clip does not show (head)"


@pytest.mark.parametrize("text", [
    "In the second half the left elbow drifts.", "The first half of the take is clean.",
    "The left elbow drifts in the other half.", "The left elbow drifts in the last half of the clip.",
    "The final half is steadier.", "The latter half is steadier.", "Over the lower half the left elbow stays bent.",
])
def test_recheck_3_half_as_a_stretch_of_the_take_is_not_a_number(text):
    assert problem(text) is None


@pytest.mark.parametrize("text", [
    "The left elbow bends by half as much.", "The left elbow lags half a beat.", "The left elbow bends half a degree more.",
    "The left elbow drops by half.", "The left elbow drops half the depth.", "Half the reps look the same.",
    "The left elbow bends in two halves.",
])
def test_recheck_3_half_as_an_amount_is_still_a_number(text):
    assert problem(text) == "adds a number"


# ---- R13: links and control characters -------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "See https://example.com for the left elbow.", "Visit www.example.org about the left elbow.",
    "The left elbow tips are at example.com/tips.", "Write to me@example.co about the left elbow.",
    "ftp://host/left-elbow", "mailto:someone about the left elbow",
])
def test_review_r13_a_link_or_domain_is_refused(text):
    assert problem(text) == "has a link"


@pytest.mark.parametrize("text", [
    "The left elbow\tdrops.", "The left elbow\x00 drops.", "The left elbow \x1b[31mdrops.", "The left \x07elbow drops.",
    "The left elbow inj​ury.", "The left elbow drops.‮", "The left⁠ elbow drops.", "The left elbow\x7f drops.",
])
def test_review_r13_a_control_or_invisible_character_is_refused(text):
    assert problem(text) == "has a control character"


def test_review_r13_cr_and_lf_are_still_the_more_than_one_line_reason():
    assert problem("The left elbow\rdrops.") == "more than one line"
    assert problem("The left elbow\r\ndrops.") == "more than one line"


@pytest.mark.parametrize("text", ["e.g. the left elbow stays bent.", "The left elbow stays bent.So does the right."])
def test_review_r13_full_stops_are_not_domains(text):
    assert problem(text) is None


# ---- R7: text equals coaching ----------------------------------------------------------------------------------------
def test_review_r7_a_phrasing_text_that_is_not_the_coaching_line_is_refused(take):
    doc = json.loads(json.dumps(take.analysis))
    assert validate_analysis(doc) is doc and doc["phrasing"]["faults"][0]["text"] == doc["faults"][0]["coaching"]
    doc["phrasing"]["faults"][1]["text"] = "Something else entirely."
    with pytest.raises(OutputError, match=r"phrasing\.faults\[1\]\.text must equal faults\[1\]\.coaching"):
        validate_analysis(doc)
    doc["phrasing"]["faults"][1]["text"] = doc["faults"][1]["coaching"]
    doc["faults"][0]["coaching"] = "A different line."
    with pytest.raises(OutputError, match=r"phrasing\.faults\[0\]\.text must equal faults\[0\]\.coaching"):
        validate_analysis(doc)


def test_review_r7_a_document_before_the_text_field_or_without_coaching_is_not_compared(take):
    doc = json.loads(json.dumps(take.analysis))
    for entry in doc["phrasing"]["faults"]:
        entry.pop("text")
    assert validate_analysis(doc)
    doc = json.loads(json.dumps(take.analysis))
    del doc["faults"][0]["coaching"]
    assert validate_analysis(doc)


# ---- R3: the cap before the upload -----------------------------------------------------------------------------------
def test_review_r3_a_ledger_at_the_cap_stops_the_run_before_any_upload(take, meta):
    meta.ledger.parent.mkdir(parents=True)
    meta.ledger.write_text(json.dumps({"usd": 5.0}) + "\n")
    fake = Fake(answer())
    block = attach(take, meta, fake)["second_opinion"]
    assert (block["status"], block["reason"]) == ("fallback", "spend cap reached")
    assert fake.uploaded == [] and fake.bodies == [] and fake.deleted == []
    assert len(meta.ledger.read_text().splitlines()) == 1   # the refused run wrote no line


def test_review_r3_a_ledger_below_the_cap_still_uploads_and_is_refused_on_the_estimate(take, meta):
    meta.ledger.parent.mkdir(parents=True)
    meta.ledger.write_text(json.dumps({"usd": 4.99}) + "\n")
    fake = Fake(answer())
    block = attach(take, meta, fake)["second_opinion"]
    assert (block["status"], block["reason"]) == ("fallback", "spend cap reached")
    assert len(fake.uploaded) == 2 and fake.bodies == [] and sorted(fake.deleted) == ["file-1", "file-2"]


# ---- R1: a call with no answer is recorded at its estimate -----------------------------------------------------------
class NoAnswer(Fake):
    """A call that fails without the API answering (a timeout or a dropped connection): no HTTP status."""

    def respond(self, body):
        self.bodies.append(body)
        self.last_status = None
        raise self.payload


def test_review_r1_a_timeout_is_recorded_at_the_pre_call_estimate_and_counts_toward_the_cap(take, meta, monkeypatch):
    fake = NoAnswer(OpinionError("timeout on responses"), count=9000)
    block = attach(take, meta, fake)["second_opinion"]
    assert (block["status"], block["reason"]) == ("fallback", "timeout on responses")
    [line] = [json.loads(x) for x in meta.ledger.read_text().splitlines()]
    assert line["http_status"] is None and line["estimated"] is True
    assert (line["input_tokens"], line["output_tokens"], line["usd"]) == (9000, 3000, 0.024)
    assert meta_api.spent() == pytest.approx(0.024)
    monkeypatch.setenv("PART5_META_SPEND_CAP_USD", "0.03")
    again = Fake(answer())
    block = attach(take, meta, again)["second_opinion"]
    assert (block["status"], block["reason"]) == ("fallback", "spend cap reached") and again.bodies == []


class Refused(Fake):
    """A call the API answered with an error status: it was refused, not billed."""

    def respond(self, body):
        self.bodies.append(body)
        self.last_status = 429
        raise self.payload


def test_review_r1_a_call_the_api_refused_is_recorded_at_zero(take, meta):
    attach(take, meta, Refused(OpinionError("HTTP 429 on responses")))
    [line] = [json.loads(x) for x in meta.ledger.read_text().splitlines()]
    assert line["http_status"] == 429 and line["usd"] == 0.0 and "estimated" not in line
    assert meta_api.spent() == 0.0


ESTIMATED = {"input_tokens": 1000, "output_tokens": 3000, "cached_tokens": 0, "usd": 0.014, "estimated": True}


@pytest.mark.parametrize("status", [None, 500, 502, 503, 504, 599])
def test_recheck_5_no_answer_or_a_5xx_is_recorded_at_the_estimate(status):
    """A gateway (502, 504) can answer after the model ran, so a 5xx is a call of unknown cost like a timeout."""
    assert meta_api.failed_usage(status, 1000, 0.014) == ESTIMATED


@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 408, 413, 429, 499])
def test_recheck_5_a_refusal_below_500_is_recorded_at_zero(status):
    usage = meta_api.failed_usage(status, 1000, 0.014)
    assert usage["usd"] == 0.0 and "estimated" not in usage


class Gateway(Fake):
    """A call a gateway answered with a 5xx: the model may have run."""

    def respond(self, body):
        self.bodies.append(body)
        self.last_status = 504
        raise self.payload


def test_recheck_5_a_5xx_answer_is_recorded_at_the_estimate_and_counts_toward_the_cap(take, meta, monkeypatch):
    block = attach(take, meta, Gateway(OpinionError("HTTP 504 on responses"), count=9000))["second_opinion"]
    assert (block["status"], block["reason"]) == ("fallback", "HTTP 504 on responses")
    [line] = [json.loads(x) for x in meta.ledger.read_text().splitlines()]
    assert line["http_status"] == 504 and line["estimated"] is True and line["usd"] == 0.024
    assert (line["input_tokens"], line["output_tokens"]) == (9000, 3000) and meta_api.spent() == pytest.approx(0.024)
    monkeypatch.setenv("PART5_META_SPEND_CAP_USD", "0.03")
    again = Fake(answer())
    block = attach(take, meta, again)["second_opinion"]
    assert (block["status"], block["reason"]) == ("fallback", "spend cap reached") and again.bodies == []


def without(payload, *path_and_value):
    """`payload` with its `usage` replaced by the given value (or removed when no value is given)."""
    doc = {k: v for k, v in payload.items() if k != "usage"}
    if path_and_value:
        doc["usage"] = path_and_value[0]
    return doc


@pytest.mark.parametrize("usage", [
    (), (None,), ("lots",), ([],), ({},), ({"output_tokens": 400},), ({"input_tokens": 9000},),
    ({"input_tokens": "9000", "output_tokens": 400},), ({"input_tokens": True, "output_tokens": 400},),
    ({"input_tokens": 9000, "output_tokens": 4.5},), ({"input_tokens": -5, "output_tokens": 400},),
])
def test_recheck_5_an_answer_with_no_token_counts_is_recorded_at_the_estimate(take, meta, usage):
    """HTTP 200 and a body, but the body does not say what the call cost: the estimate is recorded, not $0."""
    n = len(take.analysis["faults"])
    fake = Fake(without(answer(all_verdicts(n, True)), *usage), count=9000)
    block = attach(take, meta, fake)["second_opinion"]
    assert block["status"] == "ok" and len(block["verdicts"]) == n
    assert block["usage"] == {"input_tokens": 9000, "output_tokens": 3000, "cached_tokens": 0, "usd": 0.024, "estimated": True}
    [line] = [json.loads(x) for x in meta.ledger.read_text().splitlines()]
    assert line["http_status"] == 200 and line["estimated"] is True and line["usd"] == 0.024
    assert meta_api.spent() == pytest.approx(0.024)


def test_recheck_5_an_answer_that_says_what_it_cost_is_recorded_as_it_says(take, meta):
    n = len(take.analysis["faults"])
    block = attach(take, meta, Fake(answer(all_verdicts(n, True), tokens=(9000, 400))))["second_opinion"]
    assert block["usage"] == {"input_tokens": 9000, "output_tokens": 400, "cached_tokens": 0, "usd": 0.01295}
    [line] = [json.loads(x) for x in meta.ledger.read_text().splitlines()]
    assert "estimated" not in line and line["usd"] == 0.01295
    zero = {"input_tokens": 0, "output_tokens": 0}   # a stated zero is a statement, however odd
    assert meta_api.answered_usage(without(answer(), zero), 9000, 0.024)["usd"] == 0.0
    assert meta_api.answered_usage({"usage": {"input_tokens": 100, "output_tokens": 50}}, 9000, 0.024)["usd"] == pytest.approx(
        meta_api.price(100, 50))
    assert meta_api.answered_usage("not a body", 9000, 0.024)["estimated"] is True


def test_recheck_5_read_usage_reads_a_missing_or_negative_count_as_zero():
    assert meta_api.read_usage({}) == {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "usd": 0.0}
    odd = {"usage": {"input_tokens": -4, "output_tokens": 7, "input_tokens_details": {"cached_tokens": True}}}
    assert meta_api.read_usage(odd) == {"input_tokens": 0, "output_tokens": 7, "cached_tokens": 0, "usd": meta_api.price(0, 7)}


# ---- R6: a clip that cannot be read ----------------------------------------------------------------------------------
def test_review_r6_a_clip_that_cannot_be_read_when_sent_falls_back_without_ending_the_run(take, meta, monkeypatch):
    monkeypatch.setattr(meta_api.shutil, "which", lambda name: None)
    monkeypatch.setattr(meta_api, "prepare", lambda path, out: REAL_PREPARE(Path(path).with_name("vanished.mp4"), out))
    fake = Fake(answer())
    doc = attach(take, meta, fake)
    assert (doc["second_opinion"]["status"], doc["second_opinion"]["reason"]) == ("fallback", "clip not readable")
    assert fake.uploaded == [] and doc["faults"] == take.analysis["faults"]


def test_review_r6_a_file_that_cannot_be_opened_is_a_reason_on_both_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(meta_api.shutil, "which", lambda name: None)
    with pytest.raises(OpinionError) as raised:
        meta_api.prepare(tmp_path / "gone.mp4", tmp_path)
    assert raised.value.reason == "clip not readable"
    with pytest.raises(OpinionError) as raised:
        meta_api.HttpClient("k").upload(tmp_path / "gone.mp4")
    assert raised.value.reason == "clip not readable"


def test_review_r6_any_other_os_error_in_the_call_is_a_fallback_too(take, meta):
    fake = Fake(upload_error=OSError("disk full"))
    block = attach(take, meta, fake)["second_opinion"]
    assert (block["status"], block["reason"]) == ("fallback", "clip could not be prepared")


# ---- R9 and R10: the documents say what the code does ----------------------------------------------------------------
def test_review_r9_the_error_table_matches_the_reasons_of_the_code():
    # docs/specs is a workspace directory; a published checkout carries the generated copy under docs/design/specs
    source = ROOT / "docs/specs/second-opinion.md"
    spec = (source if source.is_file() else ROOT / "docs/design/specs/second-opinion.md").read_text()
    for reason in ("`HTTP <code> on <step>`", "`timeout on <step>`", "`usage ledger busy`", "`clip not readable`",
                   "`key file is empty`"):
        assert reason in spec
    assert "timeout after" not in spec
    error = urllib.error.HTTPError(meta_api.API, 413, "too big", {}, io.BytesIO(b""))
    assert meta_api._failure(error, "upload") == "HTTP 413 on upload"
    assert meta_api._failure(TimeoutError(), "responses") == "timeout on responses"


def test_review_r10_the_environment_table_lists_the_meta_variables():
    text = (ROOT / "docs/dev/DEVELOPING.md").read_text()
    for name in (meta_api.KEY_ENV, meta_api.USAGE_ENV, meta_api.CAP_ENV, meta_api.CALL_MAX_ENV):
        assert f"`{name}`" in text
    assert "Not read anywhere in `part5/`" not in text.split("`MODEL_API_KEY`")[1].split("\n")[0]
