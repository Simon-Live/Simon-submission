"""TICKET-206 (b): the guard accepts a video claim only for a take whose clip was sent, matches side and body-part words
to the cited fault, and knows `came_back`. The model is the fake client of test_history_api; nothing is paid for."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from part7 import history_api, history_guard, history_prompt
from test_history_api import FakeTransport
from test_history_prompt import make

FAULT = {"measure": "knee_valgus", "side": "left", "at_s": 2.0, "span": [1.5, 3.0], "joint": "left_knee", "body_part": "legs",
         "cue": "Push your knee out"}
TRUNK = {"measure": "trunk_lean_forward", "side": "center", "at_s": 4.0, "span": [3.5, 5.0], "joint": "spine", "body_part": "torso",
         "cue": "Keep your chest up"}
ARM = {"measure": "upper_arm_out", "side": "both", "at_s": 1.0, "span": [0.5, 1.5], "joint": "shoulder", "body_part": "arms",
       "cue": "Elbows in"}


def facts(status: str = "persistent") -> dict[str, Any]:
    takes = [{"take": n, "score": 60 + n, "duration_s": 10.0, "faults": [FAULT, TRUNK, ARM], "cues": ["Push your knee out"]} for n in (1, 2, 3)]
    measures = [{"measure": f["measure"], "side": f["side"], "present_in": [1, 2, 3], "status": status, "first": 1, "last": 3}
                for f in (FAULT, TRUNK, ARM)]
    return {"entry_id": "e1", "takes": takes, "best": 3, "latest": 3, "measures": measures}


def trend(text: str, fault: dict[str, Any] = FAULT, kind: str = "persistent") -> dict[str, Any]:
    return {"kind": kind, "measure": fault["measure"], "side": fault["side"], "text": text, "cites": [{"take": 3, "at_s": fault["at_s"]}]}


def judge(clip_takes: Any = (1, 2, 3), **answer: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base = {"summary": {"text": "Take 1 scored 61.", "cites": [{"take": 1, "at_s": None}]}, "trends": [], "focus": None,
            "teacher_link": None, "observations": []}
    return history_guard.check({**base, **answer}, facts(), None, None, clip_takes=clip_takes)


def rules(rejected: list[dict[str, Any]]) -> list[Any]:
    return [r["rule"] for r in rejected if r["item"] != "summary"]


@pytest.mark.parametrize("text, ok", [
    ("The left knee caves in at 2 s in take 3.", True),
    ("The knees cave in at 2 s in take 3.", True),
    ("The right knee caves in at 2 s in take 3.", False),
    ("The left elbow drops at 2 s in take 3.", False),
    ("The left leg drifts at 2 s in take 3.", True),   # leg is the fault's body part
    ("The knee cue is back at 2 s in take 3.", True),
    ("The hips drift at 2 s in take 3.", False),
])
def test_side_words_and_body_part_words_must_match_the_cited_fault(text: str, ok: bool) -> None:
    kept, rejected = judge(trends=[trend(text)])
    assert (len(kept["trends"]) == 1) is ok, rejected
    if not ok:
        assert rules(rejected) == [9]


def test_a_side_word_on_a_centered_fault_and_the_parts_of_a_both_sided_one() -> None:
    kept, rejected = judge(trends=[trend("The left trunk leans at 4.0 s in take 3.", TRUNK)])
    assert kept["trends"] == [] and rules(rejected) == [9]
    kept, _ = judge(trends=[trend("The trunk leans at 4.0 s in take 3.", TRUNK)])
    assert len(kept["trends"]) == 1
    kept, _ = judge(trends=[trend("The left arm and the right shoulder show at 1.0 s in take 3.", ARM)])
    assert len(kept["trends"]) == 1   # `both` allows either side; arm and shoulder are the measure's body part and joint


def test_focus_words_are_checked_too() -> None:
    focus = {"measure": "knee_valgus", "side": "left", "cue": "Push your knee out", "text": "Work on the right knee at 2.0 s in take 3.",
             "cites": [{"take": 3, "at_s": 2.0}]}
    kept, rejected = judge(focus=focus)
    assert kept["focus"] is None and rules(rejected) == [9]
    kept, _ = judge(focus={**focus, "text": "Work on the left knee at 2.0 s in take 3."})
    assert kept["focus"] is not None


def test_came_back_is_a_kind_and_must_agree_with_the_table() -> None:
    came_back = {**facts(), "measures": [{**m, "status": "came_back"} for m in facts()["measures"]]}
    answer = {"summary": None, "trends": [trend("The left knee is back at 2.0 s in take 3.", kind="came_back")]}
    kept, _ = history_guard.check(answer, came_back, None, None)
    assert [t["kind"] for t in kept["trends"]] == ["came_back"]
    kept, rejected = history_guard.check(answer, facts(), None, None)   # the table says persistent
    assert kept["trends"] == [] and rules(rejected) == [3]
    unverified = {**facts(), "measures": [{**m, "status": "unverified"} for m in facts()["measures"]]}
    kept, _ = history_guard.check({"summary": None, "trends": [trend("The left knee is gone at 2.0 s in take 3.", kind="fixed")]}, unverified, None, None)
    assert kept["trends"] == []   # nothing can claim fixed for a fault no later take compared


def test_visible_an_observation_is_kept_only_for_a_take_whose_clip_was_sent() -> None:
    obs = [{"take": 1, "at_s": 8.0, "text": "The feet turn out at the bottom."}, {"take": 2, "at_s": 8.0, "text": "The feet turn out at the bottom."}]
    kept, rejected = judge(observations=obs, clip_takes=(2,))
    assert [o["take"] for o in kept["observations"]] == [2] and rules(rejected) == [8]
    kept, rejected = history_guard.check({"summary": None, "observations": obs}, facts(), None, None)   # no clip list: none sent
    assert kept["observations"] == [] and rules(rejected) == [8, 8]


def test_an_observation_agrees_with_a_fault_measured_at_that_moment() -> None:
    kept, rejected = judge(observations=[{"take": 3, "at_s": 2.0, "text": "The right knee caves in."}])
    assert kept["observations"] == [] and rules(rejected) == [9]
    kept, _ = judge(observations=[{"take": 3, "at_s": 2.0, "text": "The left knee caves in."},
                                  {"take": 3, "at_s": 9.0, "text": "The right hip rises."}])   # 9 s: no fault measured there
    assert len(kept["observations"]) == 2


def test_with_the_fake_client_only_sent_clips_can_be_claimed_about(tmp_path: Path) -> None:
    fact, rows = make([60, 62, 64, 66, 68, 70, 72])
    packed = history_prompt.pack("e1", fact, rows, teacher_clip="/t.mp4", teacher_duration_s=10.0, video_consent=True)
    sent, unsent = packed["clip_takes"], [n for n in range(1, 8) if n not in packed["clip_takes"]]
    assert packed["seen"] == {n: n in sent for n in range(1, 8)}
    assert sent and unsent and len(sent) == packed["clips_sent"] <= history_prompt.MAX_VIDEOS - 1
    observations = [{"take": n, "at_s": 5.0, "text": "The stance is wide."} for n in (sent[0], unsent[0])]
    answer = json.dumps({"summary": {"text": "Take 1 scored 60.", "cites": [{"take": 1, "at_s": None}]}, "trends": [], "focus": None,
                         "teacher_link": None, "observations": observations})
    text, _ = history_api.ask(packed, transport=FakeTransport(answer=answer), state=tmp_path)
    kept, rejected = history_guard.check(json.loads(text), packed["facts"], None, None, clip_takes=packed["clip_takes"])
    assert [o["take"] for o in kept["observations"]] == [sent[0]]
    assert [r["rule"] for r in rejected if r["item"].startswith("observations")] == [8]
