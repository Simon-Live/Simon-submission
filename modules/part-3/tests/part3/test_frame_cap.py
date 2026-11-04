"""The server's frame cap and the page wording of a missing t_ms (docs/specs/compare-mode.md "Review B1" and review
residual 11; docs/specs/integration-contract.md "Resampling" frame cap).

The work of a run grows with the clip's time span, not with the upload's size. `runapi.too_long` counts the frames
a request would write (span times rate, plus one) and refuses over SERVER_MAX_FRAMES before `cli.process` runs.
"""

import json
import time

import pytest

from clipkit import two_frames
from part3 import cli, runapi
from part3.schema import FrameCapError
from runapikit import across_the_body, code_of, options_for, serving, take1_with_arms

TOO_LONG = "This clip is too long to run here. Choose a shorter clip."  # the table: no Frame rate was chosen
# TICKET-034 residual 1: worded by rate, naming only the lower choices the page has at which the clip fits.
TOO_LONG_60 = "This clip is too long for 60 per second here. Choose 30 per second, Source or a shorter clip."
TOO_LONG_60_SOURCE = "This clip is too long for 60 per second here. Choose Source or a shorter clip."
TOO_LONG_30 = "This clip is too long for 30 per second here. Choose Source or a shorter clip."
TIMELINE_TOO_LONG = "This clip is too long for Part 4 keys here. Choose another View or a shorter clip."
MISSING_T_MS = ("This file is not a valid pose3d.json: pose3d.frames[0].t_ms: "
                "missing; add t_ms to every frame or a top-level fps.")


@pytest.fixture(scope="module")
def real():
    with serving() as client:
        yield client


def post_long(doc, query):
    return runapi.handle(None, "auto", "long.json", json.dumps(doc).encode(), options_for(query))


def without_t_ms(real_doc):
    doc = two_frames(real_doc)
    for frame in doc["frames"]:
        del frame["t_ms"]
    return doc


# ---- runapi: refused before anything runs ------------------------------------------------------

def test_the_server_frame_cap_and_its_message():
    assert runapi.SERVER_MAX_FRAMES == 20_000
    assert runapi.ERRORS["too_long"] == (400, TOO_LONG)


@pytest.mark.parametrize("query, message", [
    ("fps=60", TOO_LONG_60_SOURCE), ("fps=30", TOO_LONG_30), ("body=measured&view=part5&fps=60", TOO_LONG_60_SOURCE),
    # View part4: the timeline is 30 per second whatever the Frame rate, and 10,000,000 ms at 30 is over the cap
    ("view=part4", TIMELINE_TOO_LONG), ("view=part4&fps=30", TIMELINE_TOO_LONG), ("view=part4&fps=60", TIMELINE_TOO_LONG),
])
def test_a_two_frame_file_ten_million_ms_long_is_refused_before_anything_runs(real_doc, monkeypatch, query, message):
    def explode(*args, **kwargs):
        raise AssertionError("the pipeline ran")
    monkeypatch.setattr(cli, "process", explode)
    started = time.perf_counter()
    status, error = code_of(post_long(two_frames(real_doc), query))
    assert time.perf_counter() - started < 1.0
    assert (status, error["code"], error["field"], error["message"]) == (400, "too_long", None, message)


@pytest.mark.parametrize("query", ["", "view=part5", "view=native&body=part4-rig", "stature=1.9"])
def test_a_native_run_of_a_long_clip_with_no_frame_rate_is_not_refused(real_doc, query):
    """Nothing is written along the clock: the output keeps the input's own two frames."""
    status, body = post_long(two_frames(real_doc), query)
    assert status == 200 and body["metrics"]["frames"] == 2


def test_the_squat_still_runs_at_30_and_60_per_second_and_as_the_part4_view():
    """The 107-frame clip is about 7 s: far under the cap at every rate the page offers."""
    for query in ("fps=30", "fps=60", "view=part4", "view=part4&fps=60"):
        status, body = runapi.handle("part2-squat", "auto", None, b"", options_for(query))
        assert status == 200 and body["metrics"]["frames"] > 100, query
        profile = "part4-rig" if "part4" in query else "simon-standard"  # the View's default body (ASM-012)
        assert body["options"] == {**options_for(query), "body": profile}


@pytest.mark.parametrize("fps, span_ms, refused", [
    (30, 666_600, False),    # 666,600 * 30 / 1000 + 1 = 19,999 frames
    (30, 666_633.3, False),  # 19,999.999 frames
    (30, 666_633.4, True),   # 20,000.002 frames
    (30, 666_700, True),
    (60, 333_300, False),
    (60, 333_400, True),
    (30, 0, False),
    (60, -5_000, False),     # backwards time is the pipeline's to report, not a long clip
])
def test_the_cap_is_on_span_times_rate_plus_one_frame(real_doc, fps, span_ms, refused):
    assert runapi.too_long(two_frames(real_doc, span_ms), options_for(f"fps={fps}")) is refused


def test_the_rate_of_the_part4_view_is_30_unless_a_higher_rate_is_chosen(real_doc):
    doc = two_frames(real_doc, 400_000)  # 12,001 frames at 30, 24,001 at 60
    assert runapi.too_long(doc, options_for("view=part4")) is False
    assert runapi.too_long(doc, options_for("fps=30")) is False
    assert runapi.too_long(doc, options_for("view=part4&fps=60")) is True
    assert runapi.too_long(doc, options_for("fps=60")) is True
    assert runapi.too_long(doc, options_for("")) is False and runapi.too_long(doc, options_for("view=part5")) is False


@pytest.mark.parametrize("query, message", [("fps=60", TOO_LONG_60), ("view=part4&fps=60", TOO_LONG_60),
                                            ("view=part5&fps=60", TOO_LONG_60)])
def test_a_clip_that_fits_at_30_per_second_is_told_to_choose_30_at_60(real_doc, query, message):
    """TICKET-034 residual 1: 400,000 ms is 24,001 frames at 60 and 12,001 at 30, so 30 per second is named, and the
    part4 timeline (30 per second) fits, so View part4 at 60 gets the same advice."""
    status, error = code_of(post_long(two_frames(real_doc, 400_000), query))
    assert (status, error["code"], error["message"]) == (400, "too_long", message)


def test_the_span_is_the_last_frame_minus_the_first_not_the_last_alone(real_doc):
    assert runapi.too_long(two_frames(real_doc, 10_000_000, 9_990_000), options_for("fps=60")) is False


@pytest.mark.parametrize("first, last", [(-1e308, 1e308), (0, 1e308 * 10), (0, float("nan")), (float("inf"), 0),
                                         (0, 10 ** 400), (-10 ** 400, 10 ** 400)])
def test_a_span_that_is_not_a_finite_number_is_refused(real_doc, first, last):
    status, error = code_of(post_long(two_frames(real_doc, last, first), "fps=30"))
    assert (status, error["code"]) == (400, "too_long")


def test_a_missing_t_ms_is_derived_the_way_the_pipeline_does_before_the_span_is_taken(real_doc):
    doc = without_t_ms(real_doc)
    doc["frames"][1]["frame"] = 10_000  # 10,000 frames at the top-level 1 per second: 10,000,000 ms
    doc["fps"] = 1
    status, error = code_of(post_long(doc, "fps=60"))
    assert (status, error["code"]) == (400, "too_long")
    doc["fps"] = 1000  # the same two frames are 10 ms apart
    assert runapi.too_long(doc, options_for("fps=60")) is False


@pytest.mark.parametrize("edit", [
    lambda doc: doc["frames"][1].pop("t_ms"),            # no time and no fps: the pipeline names the field
    lambda doc: doc["frames"][1].update(t_ms="late"),
    lambda doc: doc["frames"][1].update(t_ms=True),
    lambda doc: doc.update(frames=[]),
    lambda doc: doc.update(frames="x"),
])
def test_a_file_whose_times_cannot_be_read_goes_on_to_the_pipeline_which_reports_why(real_doc, edit):
    doc = two_frames(real_doc)
    edit(doc)
    status, error = code_of(post_long(doc, "fps=60"))
    assert (status, error["code"]) == (422, "contract")


def test_a_non_object_document_is_the_pipelines_to_refuse():
    assert runapi.too_long([1, 2], options_for("fps=60")) is False
    assert code_of(post_long([1, 2], "fps=60"))[1]["code"] == "contract"


# ---- review R1: the pipeline's own frame cap is the same too_long, not an invalid file -----------

@pytest.mark.parametrize("query, cap, message", [
    ("fps=60", 50, TOO_LONG_60), ("fps=30", 50, TOO_LONG_30),  # no span here: every lower rate is named
    ("view=part4", 3, TIMELINE_TOO_LONG),  # the key timeline's FrameCapError (its `timeline` attribute is True)
    # the 30 per second grid is over the cap first, in cli.process; the 30 per second timeline would be too
    ("view=part4&fps=30", 3, TIMELINE_TOO_LONG),
    ("view=part4&fps=60", 50, TOO_LONG_60),  # the 60 grid is over; at 30 the timeline may fit
])
def test_the_pipelines_own_cap_is_answered_too_long_and_names_no_command_line_flag(monkeypatch, query, cap, message):
    """With the span pre-check out of the way, `cli.process` (`--fps`) or the part4 timeline (`--keyframes`) refuses the
    clip itself with a `FrameCapError`: the frames it would write are over the cap, not a bad file. Only that type is
    answered `too_long`; the other `--fps` refusals are `FrameRateError`s (test_fps_refusal.py). The timeline's own
    error (marked by its `timeline` attribute) is worded for the View, as a lower frame rate cannot help it."""
    monkeypatch.setattr(runapi, "too_long", lambda doc, options: False)
    monkeypatch.setattr(runapi, "SERVER_MAX_FRAMES", cap)
    status, error = code_of(runapi.handle("part2-squat", "auto", None, b"", options_for(query)))
    assert (status, error["code"], error["field"], error["message"]) == (400, "too_long", None, message)
    assert "--" not in error["message"]


def test_the_timeline_cap_is_told_from_the_grid_cap_by_the_attribute_and_not_by_the_words():
    same_words = "the limit is 3"
    timeline = FrameCapError("--keyframes", same_words, timeline=True)
    grid = FrameCapError("--keyframes", same_words)  # the same path and words, not the timeline
    assert code_of(runapi._contract_failure(timeline, runapi.DEFAULT_OPTIONS))[1]["message"] == TIMELINE_TOO_LONG
    assert code_of(runapi._contract_failure(grid, runapi.DEFAULT_OPTIONS))[1]["message"] == TOO_LONG
    assert runapi.ERRORS["too_long"] == (400, TOO_LONG)  # the table's text: no Frame rate was chosen


def test_the_pipelines_own_cap_is_the_same_answer_over_http(real, monkeypatch):
    monkeypatch.setattr(runapi, "too_long", lambda doc, options: False)
    monkeypatch.setattr(runapi, "SERVER_MAX_FRAMES", 50)
    reply = real.run("sample=part2-squat&fps=60")
    assert (reply.status, reply.error_code()) == (400, "too_long")
    assert reply.json()["error"] == {"code": "too_long", "field": None, "message": TOO_LONG_60}
    monkeypatch.setattr(runapi, "SERVER_MAX_FRAMES", 3)
    timeline = real.run("sample=part2-squat&view=part4")
    assert (timeline.status, timeline.error_code()) == (400, "too_long")
    assert timeline.json()["error"] == {"code": "too_long", "field": None, "message": TIMELINE_TOO_LONG}


def test_a_clip_part4_would_reject_is_a_view_refusal_over_http_and_still_runs_natively(real):
    raw = json.dumps(take1_with_arms(across_the_body)).encode()
    refused = real.run("name=sweep.json&view=part4", raw)
    error = refused.json()["error"]
    assert (refused.status, error["code"], error["field"]) == (422, "view_refused", "view")
    assert error["message"].startswith("This clip cannot be written as Part 4 keys: left_shoulder turns ")
    assert error["message"].endswith(" degrees between keys 110 and 120 (Part 4 allows 180). Choose another View.")
    assert "--" not in error["message"] and b"Traceback" not in refused.body
    assert real.run("name=sweep.json&view=native", raw).status == 200


def test_a_clip_part5_would_reject_is_a_view_refusal_over_http_and_still_runs_natively(real, real_doc):
    raw = json.dumps(two_frames(real_doc, 0)).encode()  # two frames at one time: valid natively, not for Part 5
    refused = real.run("name=equal.json&view=part5", raw)
    error = refused.json()["error"]
    assert (refused.status, error["code"], error["field"]) == (422, "view_refused", "view")
    assert error["message"] == ("This clip cannot be written as a Part 5 animation: frame 1: times must strictly "
                                "increase (Part 5 rejects a clip whose times do not). Choose another View.")
    assert "--" not in error["message"] and b"Traceback" not in refused.body
    assert real.run("name=equal.json&view=native", raw).status == 200


# ---- residual 11: the page does not tell a visitor to use a command line flag ------------------

def test_a_missing_t_ms_is_explained_without_the_command_line_flag(real_doc):
    doc = without_t_ms(real_doc)
    for query in ("", "fps=60", "view=part4"):
        status, error = code_of(post_long(doc, query))
        assert (status, error["code"], error["field"]) == (422, "contract", "pose3d.frames[0].t_ms"), query
        assert error["message"] == MISSING_T_MS and "--input-fps" not in error["message"]


def test_other_contract_reasons_are_left_as_they_are():
    assert runapi._page_reason("missing (expected a number in [0, 1])") == "missing (expected a number in [0, 1])"
    assert "--input-fps" not in runapi._page_reason("missing; pass --input-fps <n> or add a top-level fps")


# ---- over HTTP ---------------------------------------------------------------------------------

def raw_two_frames(real_doc, last_ms):
    return json.dumps(two_frames(real_doc, last_ms)).encode()


@pytest.mark.parametrize("query, message", [("fps=60", TOO_LONG_60_SOURCE), ("view=part4", TIMELINE_TOO_LONG),
                                            ("view=part4&fps=60", TIMELINE_TOO_LONG)])
def test_a_tiny_file_with_a_ten_million_ms_span_is_refused_400_too_long_at_once_over_http(real, real_doc, query,
                                                                                       message):
    """The review's 2.5 KB upload used 6.7 GiB and 45 s at 60 frames per second before the frame count was checked."""
    raw = raw_two_frames(real_doc, 10_000_000)
    assert len(raw) < 3000
    started = time.perf_counter()
    reply = real.run(f"name=gap.json&{query}", raw)
    elapsed = time.perf_counter() - started
    assert (reply.status, reply.error_code()) == (400, "too_long")
    assert reply.json()["error"] == {"code": "too_long", "field": None, "message": message}
    assert elapsed < 1.0 and b"Traceback" not in reply.body
    assert real.run("sample=take-1").status == 200 and real.run("sample=take-2").status == 200  # both slots are free


def test_the_same_tiny_file_with_no_frame_rate_still_runs_over_http(real, real_doc):
    reply = real.run("name=gap.json", raw_two_frames(real_doc, 10_000_000))
    assert reply.status == 200 and reply.json()["metrics"]["frames"] == 2


def test_a_squat_at_30_per_second_still_runs_over_http(real):
    reply = real.run("sample=part2-squat&fps=30")
    assert reply.status == 200 and reply.json()["options"]["fps"] == 30


def test_a_missing_t_ms_is_explained_to_the_page_over_http(real, real_doc):
    reply = real.run("name=no-time.json", json.dumps(without_t_ms(real_doc)).encode())
    error = reply.json()["error"]
    assert (reply.status, error["code"], error["field"]) == (422, "contract", "pose3d.frames[0].t_ms")
    assert error["message"] == MISSING_T_MS
