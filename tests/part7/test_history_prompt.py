"""TICKET-181 AC-1 and AC-6 (packing side): history_prompt.pack, no network (docs/specs/history-meta.md)."""

from __future__ import annotations

import json
from typing import Any

from part7 import history_prompt as hp


def make(scores: list[int], *, duration: float = 10.0, private: tuple[int, ...] = ()) -> tuple[dict, list[dict]]:
    rows, takes = [], []
    for n, score in enumerate(scores, start=1):
        rows.append({"take": n, "job_id": f"job{n:09d}", "duration_s": duration, "score": score,
                     "private": n in private, "clip": f"/clips/take{n}.mp4"})
        takes.append({"take": n, "at": f"2026-11-{n:02d}T10:00:00Z", "score": score, "grade": "B", "duration_s": duration,
                      "faults": [], "cues": []})
    facts = {"entry_id": "e1", "takes": takes, "best": 1, "latest": len(scores),
             "measures": [{"measure": "m", "side": "left", "present_in": list(range(1, len(scores) + 1)),
                           "status": "persistent", "first": 1, "last": len(scores)}]}
    return facts, rows


def videos(packed: dict[str, Any]) -> list[str]:
    return [i["label"] for i in packed["content"] if i["type"] == "video"]


def texts(packed: dict[str, Any]) -> list[str]:
    return [i["text"] for i in packed["content"] if i["type"] == "text"]


NARRATION = {"cues": [{"index": 0, "start_s": 0.5, "end_s": 2.0, "text": "Chest up"}]}


def test_packing_order_instructions_teacher_narration_then_oldest_first():
    facts, rows = make([60, 70, 80])
    packed = hp.pack("e1", facts, list(reversed(rows)), teacher_clip="/t.mp4", teacher_duration_s=20.0,
                     narration=NARRATION, video_consent=True)
    kinds = [(i["type"], i.get("label") or i["text"][:12]) for i in packed["content"]]
    assert kinds[0] == ("text", hp.INSTRUCTIONS[:12])
    assert kinds[1][1] == "The teacher'" and kinds[2] == ("video", "teacher")
    assert kinds[3][1] == "What the tea"
    digest_order = [t[:7] for t in texts(packed) if t.startswith("Take ")]
    assert digest_order == ["Take 1 ", "Take 2 ", "Take 3 "]
    assert packed["prompt_version"] == hp.PROMPT_VERSION and packed["schema"] is hp.SCHEMA
    first_take = next(i for i, c in enumerate(packed["content"]) if c["type"] == "text" and c["text"].startswith("Take 1"))
    assert first_take > 3  # the stable prefix comes first so the automatic cache can reuse it as takes are added


def test_packing_labels_every_take_and_keeps_json_digests():
    facts, rows = make([60, 70])
    packed = hp.pack("e1", facts, rows, video_consent=False)
    digests = [t for t in texts(packed) if t.startswith("Take ")]
    assert len(digests) == 2
    body = json.loads(digests[1].split("(JSON): ", 1)[1])
    assert body["take"] == 2 and body["score"] == 70
    assert [i for i in packed["content"] if i["type"] == "video"] == []


def test_packing_clip_priority_first_latest_best_worst_with_five_videos_at_most():
    scores = [50, 90, 70, 20, 60, 65, 66, 67, 68, 69, 71, 72, 73, 74, 75]
    facts, rows = make(scores)
    packed = hp.pack("e1", facts, rows, teacher_clip="/t.mp4", teacher_duration_s=30.0, video_consent=True)
    sent = videos(packed)
    assert hp.MAX_VIDEOS == 5 and len(sent) == 5 and packed["clips_sent"] == 4  # clips_sent counts take clips, not the teacher clip
    assert sent[0] == "teacher"
    assert {int(s.split()[1]) for s in sent[1:]} == {1, 15, 2, 4}  # first, latest, best, worst
    assert hp.clip_order(rows)[:4] == [1, 15, 2, 4]
    assert len([t for t in texts(packed) if t.startswith("Take ")]) == 15  # every take still has its JSON digest
    assert packed["video_seconds"] == 30.0 + 4 * 10.0


def test_packing_never_more_than_five_videos_four_take_clips_and_fills_from_the_newest():
    facts, rows = make([60, 70, 80, 90, 50, 55, 65, 75, 85], duration=5.0)
    assert len(videos(hp.pack("e1", facts, rows, video_consent=True))) == 4  # no teacher clip: four take clips, as the consent copy says
    assert len(videos(hp.pack("e1", facts, rows, video_consent=True, teacher_clip="/t.mp4",
                              teacher_duration_s=5.0))) == 5
    facts, rows = make([70, 70, 70, 70, 70, 70])  # first, latest, best, worst coincide: fill with the newest others
    sent = videos(hp.pack("e1", facts, rows, video_consent=True, teacher_clip="/t.mp4", teacher_duration_s=5.0))
    assert sent == ["teacher", "Take 1", "Take 4", "Take 5", "Take 6"]


def test_packing_clip_order_handles_one_take_and_ties():
    facts, rows = make([80])
    assert hp.clip_order(rows) == [1]
    facts, rows = make([80, 80, 80])
    assert hp.clip_order(rows) == [1, 3, 2]  # best and worst tie to the earliest take, already chosen or next
    assert hp.clip_order([]) == []


def test_packing_clip_longer_than_60_s_is_not_sent():
    facts, rows = make([60, 70])
    rows[0]["duration_s"] = 61.0
    rows[1]["duration_s"] = 60.0
    packed = hp.pack("e1", facts, rows, video_consent=True, teacher_clip="/t.mp4", teacher_duration_s=60.1)
    assert videos(packed) == ["Take 2"]
    rows[1]["clip"] = None
    assert videos(hp.pack("e1", facts, rows, video_consent=True)) == []


def test_packing_stays_inside_the_input_budget_and_keeps_priority():
    facts, rows = make([60, 70, 80, 90])
    one_clip = hp.VIDEO_TOKENS_PER_S * 10
    base = hp.pack("e1", facts, rows, video_consent=False)["est_input_tokens"]
    packed = hp.pack("e1", facts, rows, video_consent=True, budget_tokens=base + 2 * one_clip + 5)
    assert videos(packed) == ["Take 1", "Take 4"]  # first and latest win; later priorities do not fit
    assert packed["est_input_tokens"] <= base + 2 * one_clip + 5
    assert hp.pack("e1", facts, rows, video_consent=True, budget_tokens=base)["clips_sent"] == 0
    assert hp.BUDGET_TOKENS == 250_000 and hp.MAX_VIDEOS == 5 and hp.CLIP_MAX_S == 60 and hp.VIDEO_TOKENS_PER_S == 220


def test_consent_and_private_no_consent_means_json_only():
    facts, rows = make([60, 70])
    packed = hp.pack("e1", facts, rows, teacher_clip="/t.mp4", teacher_duration_s=10.0, narration=NARRATION,
                     video_consent=False)
    assert videos(packed) == [] and packed["clips_sent"] == 0 and packed["video_consent"] is False
    assert any("What the teacher said" in t for t in texts(packed))  # the JSON still goes


def test_consent_and_private_takes_never_reach_the_call():
    facts, rows = make([60, 70, 80], private=(2,))
    packed = hp.pack("e1", facts, rows, video_consent=True)
    assert "Take 2" not in videos(packed)
    assert not any(t.startswith("Take 2 ") for t in texts(packed))
    assert [t["take"] for t in packed["facts"]["takes"]] == [1, 3]
    assert packed["facts"]["measures"][0]["present_in"] == [1, 3]
    blob = json.dumps(packed["content"])
    assert "/clips/take2.mp4" not in blob and "job000000002" not in blob
    assert facts["takes"][1]["take"] == 2  # the caller's facts are not changed


def test_schema_is_strict_ready_and_names_the_contract_fields():
    props = hp.SCHEMA["properties"]
    assert set(props) == {"summary", "trends", "focus", "teacher_link", "observations"}
    assert hp.SCHEMA["additionalProperties"] is False and set(hp.SCHEMA["required"]) == set(props)
    assert props["trends"]["items"]["properties"]["kind"]["enum"] == ["improved", "persistent", "fixed", "new"]
    for text in (hp.INSTRUCTIONS,):
        assert "coach" not in text.lower() and chr(0x2014) not in text and chr(0x2013) not in text


def test_packing_drops_takes_without_facts():
    facts, rows = make([60, 70])
    facts["takes"] = facts["takes"][:1]
    packed = hp.pack("e1", facts, rows, video_consent=True)
    assert [t["take"] for t in packed["facts"]["takes"]] == [1] and videos(packed) == ["Take 1"]


def test_seven_takes_without_a_teacher_clip_send_four_take_clips():  # the consent copy says "up to 4"
    facts, rows = make([50, 90, 70, 20, 60, 65, 66])
    packed = hp.pack("e1", facts, rows, video_consent=True)
    assert packed["clips_sent"] == 4 and len(videos(packed)) == 4
