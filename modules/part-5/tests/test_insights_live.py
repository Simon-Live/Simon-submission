"""An insight that points at a fault with a validated live English line repeats that line's observation clause
(ADR-0014, Amendment 2, AC-CUE-07, TICKET-057). Hand-built documents for the rule, one mocked-client run through the
pipeline. No socket is opened and no key is read."""
import copy
import json
from pathlib import Path

import pytest

from part5.insights import insights_of
from part5.phrasing.local_llm import HttpResult
from part5.pipeline import run
from part5.score_report import score_block
from test_phrasing import clean_env, no_network  # noqa: F401
from test_phrasing_muse_spark import live  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
SEED5 = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())

KNEES = "At 1.4 s, your knees are not bent enough."
FOOT = "Your right foot drifts too far to the right at 1.9 s; keep it under your hip"
LIVE = {"backend": "muse-spark", "model": "m", "fallback_reason": None, "lang": "en"}


def _knee_fault(coaching=KNEES):
    return {"measure": "knee_flexion", "side": "both", "direction": "less", "joint": "knee",
            "text": "knees not bent enough", "text_timed": "knees not bent enough at 1.4 s", "at_s": 1.4,
            "cue": "Bend your knees more", "cue_kind": "range", "coaching": coaching}


def _foot_fault(coaching=FOOT, at=1.9):
    return {"measure": "foot_out", "side": "right", "direction": "more", "joint": "right_ankle", "lateral": "right",
            "text": "right foot too far out", "text_timed": f"right foot too far right at {at:.1f} s", "at_s": at,
            "cue": "Step your right foot in", "cue_kind": "position", "coaching": coaching}


def _miss(fault, at, points=10.0):
    return {"text": fault["text"], "measure": fault["measure"], "side": fault["side"], "joint": fault["joint"],
            "t_s": [at, at + 1], "at_s": at, "points": points, "cue": fault["cue"], "cue_kind": fault["cue_kind"],
            "direction": fault["direction"]}


def _doc(fault, misses_at, n_windows, entry=LIVE, basis="reps"):
    """A scored document: `n_windows` compared windows, a miss of `fault` in each window of `misses_at` ({index: at_s})."""
    windows = [{"t_s": [5 * k, 5 * k + 5], "misses": [_miss(fault, misses_at[k])] if k in misses_at else []}
               for k in range(n_windows)]
    doc = {"faults": [fault], "score": {"basis": basis, "timeline": windows}}
    if entry is not None:
        doc["phrasing"] = {"faults": [dict(entry)]}
    return doc


def _why(doc):
    (insight,) = insights_of(doc)
    return insight["why"]


# --- the two examples of the ruling -----------------------------------------------------------------------
def test_a_clause_that_already_says_the_time_is_kept_and_the_count_follows():
    doc = _doc(_knee_fault(), {0: 1.4, 1: 6.0}, 2)
    assert _why(doc) == "At 1.4 s, your knees are not bent enough (2 of 2 reps)"


def test_the_clause_is_cut_at_the_semicolon_and_set_at_the_insights_own_time():
    doc = _doc(_foot_fault(), {1: 1.7, 3: 3.1, 5: 4.2}, 8)
    insight = insights_of(doc)[0]
    assert insight["at_s"] == 1.7
    assert insight["why"] == "Your right foot drifts too far to the right at 1.7 s (3 of 8 reps)"


def test_windows_say_how_many_times_and_one_window_says_nothing_more_than_the_clause():
    twice = _doc(_foot_fault(), {0: 1.9, 2: 3.0}, 3, basis="windows")
    assert _why(twice) == "Your right foot drifts too far to the right at 1.9 s (2 times)"
    once = _doc(_foot_fault(), {0: 1.9}, 3, basis="windows")
    assert _why(once) == "Your right foot drifts too far to the right at 1.9 s"


def test_without_a_timeline_the_insight_is_the_fault_itself_and_has_no_count():
    fault = _foot_fault()
    doc = {"faults": [fault], "phrasing": {"faults": [dict(LIVE)]}}
    (insight,) = insights_of(doc)
    assert insight["why"] == "Your right foot drifts too far to the right at 1.9 s" and insight["points"] is None
    assert insights_of({"faults": [fault]})[0]["why"] == "Right foot too far right at 1.9 s"   # no record: as before


# --- the cut -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("coaching,want", [
    ("Your right foot drifts too far to the right at 1.9 s!", "Your right foot drifts too far to the right at 1.7 s"),
    ("your right foot drifts too far to the right at 1.9 s.", "Your right foot drifts too far to the right at 1.7 s"),
    ("Your right foot drifts too far to the right at 1.9 seconds; keep it in; then relax",
     "Your right foot drifts too far to the right at 1.7 seconds"),
    ("  At 1.9 s, your right foot drifts too far to the right ;keep it in.  ",
     "At 1.7 s, your right foot drifts too far to the right"),
    ("Your right foot drifts too far to the right at 1.90 s.", "Your right foot drifts too far to the right at 1.7 s"),
    # N3 of the delta review: any closing run of ".", "!" and "?" goes, so nothing is left before the count
    ("Your right foot drifts too far to the right at 1.9 s...", "Your right foot drifts too far to the right at 1.7 s"),
    ("Your right foot drifts too far to the right at 1.9 s?", "Your right foot drifts too far to the right at 1.7 s"),
    ("Your right foot drifts too far to the right at 1.9 s?!", "Your right foot drifts too far to the right at 1.7 s"),
    ("Your right foot drifts too far to the right at 1.9 s !! ; keep it in...",
     "Your right foot drifts too far to the right at 1.7 s"),
])
def test_the_closing_mark_the_unit_and_the_capital_are_handled_as_ruled(coaching, want):
    doc = _doc(_foot_fault(coaching), {0: 1.7, 1: 2.0}, 4, basis="windows")
    assert _why(doc) == want + " (2 times)"


@pytest.mark.parametrize("coaching", [
    "Your right foot drifts too far to the right; hold it at 1.9 s",                       # the cut loses the time
    "Your right foot drifts too far to the right at 1.9 s and again at 2.5 s; keep it in",  # the time twice
    "Your right foot drifts too far to the right at 1.2 s; keep it under your hip",         # not the fault's time
    "Your left foot drifts too far to the right at 1.9 s; keep it under your hip",          # the wrong side
    "; Your right foot drifts too far to the right at 1.9 s",                               # nothing before the cut
    "Your right foot is not too far to the right at 1.9 s; keep it under your hip",         # N2: a negated phrase
    "Your right foot isn't too far to the right at 1.9 s.",
])
def test_a_cut_that_fails_the_timed_word_test_falls_back_to_the_template_form(coaching):
    doc = _doc(_foot_fault(coaching), {1: 1.7, 3: 3.1, 5: 4.2}, 8)
    assert _why(doc) == "Right foot too far right at 1.7 s (3 of 8 reps)"


# --- what is out of scope keeps today's why ----------------------------------------------------------------
@pytest.mark.parametrize("entry", [
    {"backend": "template", "model": None, "fallback_reason": "muse-spark: wrong side", "lang": "en"},   # fell back
    {"backend": "template", "model": None, "fallback_reason": None, "lang": "en"},                       # the template
    {"backend": "muse-spark", "model": "m", "fallback_reason": "muse-spark: wrong side", "lang": "en"},
    {"backend": "muse-spark", "model": "m", "fallback_reason": None, "lang": "es"},                      # translated
    {"model": "m", "fallback_reason": None, "lang": "en"},                                                # no backend
    None,                                                                                                 # no record
])
def test_a_template_a_fallen_back_and_a_translated_line_keep_the_template_form(entry):
    doc = _doc(_foot_fault(), {1: 1.7, 3: 3.1, 5: 4.2}, 8, entry=entry)
    assert _why(doc) == "Right foot too far right at 1.7 s (3 of 8 reps)"


def test_a_translated_line_in_spanish_is_never_cut():
    fault = _foot_fault("Tu pie derecho se desvia demasiado a la derecha en 1.9 s; mantenlo bajo la cadera")
    doc = _doc(fault, {0: 1.9}, 2, entry={**LIVE, "lang": "es"}, basis="windows")
    assert _why(doc) == "Right foot too far right at 1.9 s"


def test_a_record_shorter_than_the_faults_and_an_entry_without_lang_are_read_gracefully():
    doc = _doc(_foot_fault(), {0: 1.9}, 2, entry=None, basis="windows")
    doc["phrasing"] = {"faults": []}
    assert _why(doc) == "Right foot too far right at 1.9 s"
    doc["phrasing"] = {"faults": [{"backend": "muse-spark", "fallback_reason": None}]}   # lang absent means English
    assert _why(doc) == "Your right foot drifts too far to the right at 1.9 s"


def test_only_the_fault_the_miss_repeats_is_read():
    other = {**_foot_fault("Your left foot drifts too far to the left at 2.2 s", 2.2), "side": "left",
             "lateral": "left", "cue": "Step your left foot in"}
    doc = _doc(_foot_fault(), {0: 1.9}, 2, basis="windows")
    doc["faults"] = [other, doc["faults"][0]]
    doc["phrasing"] = {"faults": [{**LIVE, "lang": "es"}, dict(LIVE)]}   # the first fault's line is translated
    assert _why(doc) == "Your right foot drifts too far to the right at 1.9 s"


def test_a_miss_no_reported_fault_matches_and_a_tempo_item_are_untouched():
    fault = _foot_fault()
    doc = _doc(fault, {0: 1.9}, 2, basis="windows")
    doc["faults"] = [{**fault, "side": "left"}]   # another side: not the fault this miss repeats
    assert _why(doc) == "Right foot too far out at 1.9 s"
    tempo = {"ratio": 1.4, "cue": "Speed up to match the trainer"}
    doc = _doc(_knee_fault(), {}, 2, basis="windows")
    doc["score"]["tempo"] = tempo
    assert insights_of(doc)[-1]["why"] == "You took 1.4 times the trainer's time"


def test_the_same_document_always_gives_the_same_insights_and_is_not_changed():
    doc = _doc(_foot_fault(), {1: 1.7, 3: 3.1}, 8)
    before = copy.deepcopy(doc)
    assert insights_of(doc) == insights_of(doc) and doc == before


def test_the_template_form_does_not_depend_on_the_phrasing_record():
    for entry in (None, {"backend": "template", "model": None, "fallback_reason": None, "lang": "en"}):
        doc = _doc(_knee_fault(), {0: 1.4, 1: 6.0}, 2, entry=entry)
        assert _why(doc) == "Knees not bent enough at 1.4 s (2 of 2 reps)"


# --- through the pipeline, with a mocked client -------------------------------------------------------------
def _take(prefix):
    label = next(t for t in SEED5["takes"] if t["take_id"].startswith(prefix))
    return str(ROOT / label["expected"]), str(ROOT / label["follower"])


def _client(answer):
    """A mocked model: answers every request from `answer(text_timed)`."""
    def call(request):
        user = request["body"]["messages"][1]["content"]
        return HttpResult(200, {"choices": [{"message": {"content": answer(json.loads(user)["text_timed"])}}]})
    return call


def test_a_live_analysis_has_the_fault_rows_clause_in_its_insight(live):  # noqa: F811
    expected, follower = _take("exercise_front_good_03_foot_out-right")
    reply = lambda timed: f"Your {timed.replace(' at ', ', at ')}; keep it under your hip."   # noqa: E731
    a = run(expected, follower, score=score_block, phrasing="muse-spark", phrasing_client=_client(reply),
            live=True).analysis
    fault, insight = a["faults"][0], a["insights"][0]
    assert a["phrasing"]["faults"][0]["backend"] == "muse-spark" and a["phrasing"]["faults"][0]["fallback_reason"] is None
    assert fault["coaching"] == "Your right foot too far right, at 1.9 s; keep it under your hip."
    assert insight["cue"] == fault["cue"]
    assert insight["why"] == "Your right foot too far right, at 1.9 s"
    assert fault["coaching"].startswith(insight["why"])


def test_an_unscored_live_analysis_makes_its_insights_after_the_lines_are_written(live):  # noqa: F811
    expected, follower = _take("exercise_front_good_03_foot_out-right")
    reply = lambda timed: f"Your {timed.replace(' at ', ', at ')}; keep it under your hip."   # noqa: E731
    a = run(expected, follower, phrasing="muse-spark", phrasing_client=_client(reply), live=True).analysis
    assert "score" not in a and a["insights"][0]["why"] == "Your right foot too far right, at 1.9 s"
    assert a["insights"] == insights_of(a)


def test_the_same_analysis_phrased_by_the_template_keeps_the_template_insight():
    expected, follower = _take("exercise_front_good_03_foot_out-right")
    plain = run(expected, follower, score=score_block).analysis
    assert plain["insights"][0]["why"] == "Right foot too far right at 1.9 s"
    stripped = {k: v for k, v in plain.items() if k != "phrasing"}
    assert insights_of(stripped) == plain["insights"]


def test_a_live_line_that_fell_back_keeps_the_template_insight(live):  # noqa: F811
    expected, follower = _take("exercise_front_good_03_foot_out-right")
    a = run(expected, follower, score=score_block, phrasing="muse-spark",
            phrasing_client=_client(lambda timed: "Great job, nice effort."), live=True).analysis
    assert a["phrasing"]["faults"][0]["backend"] == "template" and a["phrasing"]["faults"][0]["fallback_reason"]
    assert a["insights"][0]["why"] == "Right foot too far right at 1.9 s"
