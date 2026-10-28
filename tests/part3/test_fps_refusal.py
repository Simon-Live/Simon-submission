"""A frame rate the clip cannot take is not the frame cap (TICKET-032, review residuals 1 and 3; TICKET-033, residuals
1 and 2; docs/specs/compare-mode.md "Errors", "Review residual 1").

The pipeline names its refusals by type: `FrameCapError` for the frame cap, `FrameRateError` for a clip that cannot be
resampled at the chosen frame rate for another reason. `runapi` answers by type, so a sparse upload is told which
Frame rate option the page has to try (the next higher one, else Source), and a clip whose times do not increase is
told to fix the times or choose Source, in words with no command line flag.
"""

import copy
import json
import re

import pytest

from conftest import ROOT
from part3 import cli, keyframes, resample, runapi
from part3.schema import ContractError, FrameCapError, FrameRateError, LongWayError, OptionError, ViewError
from runapikit import code_of, options_for, serving

NO_PERSON_30 = "No frame at 30 per second holds the person. Choose 60 per second or Source."
NO_PERSON_60 = "No frame at 60 per second holds the person. Choose Source."
TIMES = ("pose3d.frames[2].t_ms: the times must increase to change the frame rate. "
         "Choose Source, or fix the times.")
TOO_LONG = "This clip is too long for that frame rate here. Choose a lower frame rate or a shorter clip."
CLI_NO_PERSON = "--fps: no output frame holds the person; use a higher --fps"
CLI_TIMES = "pose3d.frames[2].t_ms: must increase for --fps"
TAKE_1 = "fixtures/input/synthetic-4take/take-1/pose3d.json"


@pytest.fixture(scope="module")
def real():
    with serving() as client:
        yield client


@pytest.fixture(scope="module")
def take_1():
    return json.loads((ROOT / TAKE_1).read_text())


def sparse_clip(take_1, step_ms=12.0):
    """take-1 cut to 6 frames `step_ms` apart (12 ms: 60 ms in all); the person is in frames 1 and 2 only.

    At 12 ms no frame of the 30 per second grid holds the person but the 60 per second grid has one; at 3 ms the
    whole clip is 15 ms and neither grid does."""
    doc = copy.deepcopy(take_1)
    doc["frames"] = doc["frames"][:6]
    for index, frame in enumerate(doc["frames"]):
        frame["t_ms"] = step_ms * index
        if index not in (1, 2):
            frame["people"] = []
    return doc


def equal_times(take_1):
    """take-1's first 3 frames with two equal t_ms."""
    doc = copy.deepcopy(take_1)
    doc["frames"] = doc["frames"][:3]
    for index, t_ms in enumerate((0.0, 33.0, 33.0)):
        doc["frames"][index]["t_ms"] = t_ms
    return doc


def post(doc, query, name="clip.json"):
    return runapi.handle(None, "auto", name, json.dumps(doc).encode(), options_for(query))


# ---- the types ---------------------------------------------------------------------------------

def test_the_grid_count_over_the_cap_is_a_frame_cap_error_with_the_same_text():
    for last_ms, message in ((100_000_000.0, "--fps 1 would write 100001 frames; the limit is 100000"),
                             (1e308 * 10, "--fps 1 would write more frames than the limit of 100000: "
                                          "the clip span (first to last t_ms) is not finite")):
        with pytest.raises(FrameCapError) as caught:
            resample.grid_count(0.0, last_ms, 1)
        assert isinstance(caught.value, OptionError) and str(caught.value) == message
        assert caught.value.path == "--fps 1"


def test_the_part4_timeline_over_the_cap_is_a_frame_cap_error_with_the_same_text():
    with pytest.raises(FrameCapError) as caught:
        keyframes.frame_count(0.0, 10_000_000.0)
    assert isinstance(caught.value, OptionError) and caught.value.path == "--keyframes"
    assert str(caught.value) == "--keyframes: the 30 fps timeline would have 300001 ticks; the limit is 100000"
    with pytest.raises(FrameCapError, match=r"^--keyframes: the 30 fps timeline would have more ticks than the limit "
                                            r"of 100000: the clip span \(first to last t_ms\) is not finite$"):
        keyframes.frame_count(0.0, float("inf"))


def test_no_output_frame_holding_the_person_is_a_frame_rate_error_not_a_frame_cap_error(take_1):
    with pytest.raises(FrameRateError) as caught:
        cli.process(sparse_clip(take_1), fps=30, env={}, config=False)
    error = caught.value
    assert not isinstance(error, (FrameCapError, OptionError)) and isinstance(error, ContractError)
    assert (error.path, error.times, str(error)) == ("--fps", False, CLI_NO_PERSON)


def test_times_that_do_not_increase_are_a_frame_rate_error_not_a_frame_cap_error(take_1):
    with pytest.raises(FrameRateError) as caught:
        cli.process(equal_times(take_1), fps=30, env={}, config=False)
    error = caught.value
    assert not isinstance(error, FrameCapError)
    assert (error.path, error.times, str(error)) == ("pose3d.frames[2].t_ms", True, CLI_TIMES)


@pytest.mark.parametrize("doc_of, fps, message", [
    (sparse_clip, "30", CLI_NO_PERSON),
    (equal_times, "30", CLI_TIMES),
])
def test_the_command_line_says_what_it_said_before(tmp_path, capsys, take_1, doc_of, fps, message):
    source = tmp_path / "pose3d.json"
    source.write_text(json.dumps(doc_of(take_1)))
    code = cli.main(["run", "--in", str(source), "--out", str(tmp_path / "skeleton.json"), "--fps", fps])
    captured = capsys.readouterr()
    assert (code, captured.out, captured.err) == (2, "", message + "\n")
    assert not (tmp_path / "skeleton.json").exists()


# ---- residual 1: a sparse clip at a rate too low for it ----------------------------------------

def test_a_sparse_clip_at_30_is_a_422_fps_refused_that_names_the_next_option_the_page_has(take_1):
    status, error = code_of(post(sparse_clip(take_1), "fps=30"))
    assert (status, error["code"], error["field"], error["message"]) == (422, "fps_refused", "fps", NO_PERSON_30)
    assert "--" not in error["message"] and "lower" not in error["message"] and "blank" not in error["message"]


def test_a_clip_with_no_person_even_at_60_is_told_to_choose_source_alone(take_1):
    clip = sparse_clip(take_1, step_ms=3.0)
    status, error = code_of(post(clip, "fps=60"))
    assert (status, error["code"], error["field"], error["message"]) == (422, "fps_refused", "fps", NO_PERSON_60)
    assert "--" not in error["message"] and "higher" not in error["message"]
    assert code_of(post(clip, "fps=30"))[1]["message"] == NO_PERSON_30
    assert post(clip, "")[0] == 200  # Source keeps the input's own frames


def test_the_same_sparse_clip_at_60_or_with_no_frame_rate_runs(take_1):
    for query in ("fps=60", ""):
        status, body = post(sparse_clip(take_1), query)
        assert status == 200 and body["ok"] is True, query
    assert post(sparse_clip(take_1), "fps=60")[1]["metrics"]["frames_present"] >= 1


def test_the_sparse_clip_over_the_part4_view_at_30_gives_the_same_refusal(take_1):
    status, error = code_of(post(sparse_clip(take_1), "view=part4&fps=30"))
    assert (status, error["code"], error["field"], error["message"]) == (422, "fps_refused", "fps", NO_PERSON_30)


def test_the_real_frame_cap_is_still_400_too_long_and_the_sparse_clip_is_not_that(take_1, monkeypatch):
    monkeypatch.setattr(runapi, "too_long", lambda doc, options: False)
    monkeypatch.setattr(runapi, "SERVER_MAX_FRAMES", 1)
    status, error = code_of(post(sparse_clip(take_1), "fps=60"))
    assert (status, error["code"], error["field"], error["message"]) == (400, "too_long", None, TOO_LONG)
    monkeypatch.setattr(runapi, "SERVER_MAX_FRAMES", 20_000)
    assert code_of(post(sparse_clip(take_1), "fps=30"))[1]["code"] == "fps_refused"


@pytest.mark.parametrize("fps, options, text", [
    (30, (30, 60), "No frame at 30 per second holds the person. Choose 60 per second or Source."),
    (60, (30, 60), "No frame at 60 per second holds the person. Choose Source."),
    # the rule, not the two values the page has now: the next higher option, else Source alone
    (24, (24, 30, 60), "No frame at 24 per second holds the person. Choose 30 per second or Source."),
    (25, (24, 30, 60), "No frame at 25 per second holds the person. Choose 30 per second or Source."),
    (45, (30, 60), "No frame at 45 per second holds the person. Choose 60 per second or Source."),
    (120, (30, 60), "No frame at 120 per second holds the person. Choose Source."),
    (None, (30, 60), "No frame at that frame rate holds the person. Choose Source."),
])
def test_the_no_person_text_names_only_choices_the_page_has(monkeypatch, fps, options, text):
    monkeypatch.setattr(runapi, "FPS_VALUES", options)
    assert runapi._no_person_text(fps) == text


def test_the_texts_name_the_pages_own_option_labels():
    """The page's Frame rate select (web/app.html, web/compare.html): Source (value blank), 30 per second, 60 per second."""
    labels = []
    for page in ("app.html", "compare.html"):
        html = (ROOT / "web" / page).read_text(encoding="utf-8")
        select = re.search(r'<select id="fps-select".*?</select>', html, re.S).group(0)
        labels.append(re.findall(r'<option value="(\d*)"[^>]*>([^<]+)</option>', select))
    assert labels[0] == labels[1] == [("", "Source"), ("30", "30 per second"), ("60", "60 per second")]
    assert runapi.SOURCE == "Source" and tuple(int(v) for v, _ in labels[0] if v) == runapi.FPS_VALUES


def test_fps_refused_is_in_the_error_table_with_the_fps_field():
    status, body = runapi.error("fps_refused")
    assert status == 422 and runapi.ERRORS["fps_refused"][0] == 422
    assert body["error"]["code"] == "fps_refused" and body["error"]["field"] == "fps"
    assert "--" not in runapi.ERRORS["fps_refused"][1]


def test_the_sparse_clip_over_http(real, take_1):
    raw = json.dumps(sparse_clip(take_1)).encode()
    refused = real.run("name=sparse.json&fps=30", raw)
    error = refused.json()["error"]
    assert (refused.status, error["code"], error["field"], error["message"]) == (422, "fps_refused", "fps", NO_PERSON_30)
    assert b"Traceback" not in refused.body and "--" not in error["message"]
    assert real.run("name=sparse.json&fps=60", raw).status == 200
    assert real.run("name=sparse.json", raw).status == 200


def test_the_clip_with_no_person_at_60_over_http(real, take_1):
    raw = json.dumps(sparse_clip(take_1, step_ms=3.0)).encode()
    refused = real.run("name=sparser.json&fps=60", raw)
    error = refused.json()["error"]
    assert (refused.status, error["code"], error["field"], error["message"]) == (422, "fps_refused", "fps", NO_PERSON_60)
    assert real.run("name=sparser.json", raw).status == 200


# ---- residual 3: times that do not increase ----------------------------------------------------

def test_two_equal_times_with_a_frame_rate_are_a_422_fps_refused_with_no_flag_text(take_1):
    status, error = code_of(post(equal_times(take_1), "fps=30"))
    assert (status, error["code"], error["field"]) == (422, "fps_refused", "fps")
    assert error["message"] == TIMES
    assert "--" not in error["message"]


def test_the_same_file_with_no_frame_rate_runs(take_1):
    status, body = post(equal_times(take_1), "")
    assert status == 200 and body["ok"] is True


def test_two_equal_times_over_http(real, take_1):
    raw = json.dumps(equal_times(take_1)).encode()
    refused = real.run("name=equal.json&fps=30", raw)
    error = refused.json()["error"]
    assert (refused.status, error["code"], error["field"]) == (422, "fps_refused", "fps")
    assert error["message"] == TIMES and "--" not in error["message"]
    assert real.run("name=equal.json", raw).status == 200


def test_the_time_path_in_the_page_text_is_cut_like_any_field():
    problem = FrameRateError("x" * 500, "must increase for --fps", times=True)
    message = code_of(runapi._contract_failure(problem, runapi.DEFAULT_OPTIONS))[1]["message"]
    assert message.startswith("x" * runapi.FIELD_MAX + ": the times must increase")
    assert "x" * (runapi.FIELD_MAX + 1) not in message


# ---- the answer follows the type, not the path or the words ------------------------------------

@pytest.mark.parametrize("problem, code, status", [
    (FrameCapError("--fps 60", "any words"), "too_long", 400),
    (FrameCapError("--keyframes", "any words", timeline=True), "too_long", 400),
    (FrameRateError("--fps", "any words"), "fps_refused", 422),
    (FrameRateError("pose3d.frames[2].t_ms", "any words", times=True), "fps_refused", 422),
    (ViewError("anything", "any words", "Any page sentence."), "view_refused", 422),
    (LongWayError("any path", "any words", "left_hip", 200.0, 0, 10, 180.0), "view_refused", 422),
    # the same paths as plain ContractErrors (or an option error) are not the cap, not a frame rate refusal and not a
    # View refusal: the type decides
    (ContractError("--fps", "no output frame holds the person; use a higher --fps"), "contract", 422),
    (ContractError("--keyframes", "the 30 fps timeline would have 9 ticks; the limit is 8"), "contract", 422),
    (ContractError("--keyframes-person x", "not in the file"), "contract", 422),
    (ContractError("--view part4", "needs --keyframes <keyframes.json> or every:<n>"), "contract", 422),
    (ContractError("--view part5", "frame 3: times must strictly increase"), "contract", 422),
    (OptionError("--view part4", "needs --keyframes <keyframes.json> or every:<n>"), "contract", 422),
])
def test_runapi_classifies_a_refusal_by_its_type_and_not_by_its_path(problem, code, status):
    answered_status, error = code_of(runapi._contract_failure(problem, runapi.DEFAULT_OPTIONS))
    assert (answered_status, error["code"]) == (status, code)
