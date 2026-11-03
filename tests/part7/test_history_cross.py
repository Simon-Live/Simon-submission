"""The cross-movement model call, its guard, and the routes (TICKET-224 AC-2 to AC-7, TICKET-223 routes). SEEDED data, fake transport."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from history_all_support import DANCE, REHAB, SQUAT, seed
from history_support import OTHER, USER, World, world  # noqa: F401
from part7 import history_all, history_api, history_cross, history_cross_guard, history_guard, history_receipt, history_recap, history_report, history_store
from support import Api

BASE = "api/me/history"


def _bundles(state: Path) -> tuple[dict[str, Any], dict[str, str]]:
    found = history_all.included(history_all.gather(state, USER, lambda e: e.split("-")[0].title()))
    return {e["entry_id"]: e["facts"] for e in found}, {e["entry_id"]: e["name"] for e in found}


GOOD = {"text": "The left knee cue came up in Squat and in Dance.", "measure": "knee_valgus", "side": "left",
        "cites": [{"entry": SQUAT, "take": 1, "at_s": 2.0}, {"entry": DANCE, "take": 1, "at_s": 3.0}]}


@pytest.fixture()
def seeded(tmp_path: Path) -> Path:
    seed(tmp_path, USER)
    return tmp_path


def _check(state: Path, **answer: Any):
    bundles, names = _bundles(state)
    return history_cross_guard.check(json.dumps({"observations": [], "next_focus": None, **answer}), bundles, names, history_guard.DEFAULT_WORDS)


def test_guard_keeps_a_cross_movement_claim(seeded: Path) -> None:  # AC-3
    kept, rejected = _check(seeded, observations=[GOOD])
    assert rejected == [] and kept["observations"][0]["cites"][1] == {"entry": DANCE, "take": 1, "at_s": 3.0}
    assert kept["observations"][0]["label"] == "model_opinion"


@pytest.mark.parametrize("change,rule", [
    ({"cites": [{"entry": SQUAT, "take": 1, "at_s": 2.0}, {"entry": SQUAT, "take": 2, "at_s": 2.1}]}, 1),   # one movement is not a cross claim
    ({"cites": [{"entry": SQUAT, "take": 1, "at_s": 2.0}, {"entry": "ghost-12345678", "take": 1, "at_s": 3.0}]}, 1),  # not the user's movement
    ({"cites": [{"entry": SQUAT, "take": 3, "at_s": 4.0}, {"entry": DANCE, "take": 1, "at_s": 3.0}]}, 1),  # take 3 is private: not in the input
    ({"cites": [{"entry": SQUAT, "take": 1, "at_s": 2.0}, {"entry": REHAB, "take": 1, "at_s": 1.0}]}, 1),  # a rehab movement was not read
    ({"cites": [{"entry": SQUAT, "take": 1, "at_s": 2.0}, {"entry": DANCE, "take": 1, "at_s": 9.0}]}, 2),  # not where it was measured
    ({"cites": [{"entry": SQUAT, "take": 1, "at_s": 2.0}, {"entry": DANCE, "take": 1, "at_s": 30.0}]}, 1),  # outside the take
    ({"cites": []}, 1),
    ({"text": "You have a weak left knee in Squat and Dance."}, 6),                                         # AC-7: what came up, not what you have
    ({"text": "The left knee pain came up in Squat and in Dance."}, 6),                                    # a health word
    ({"text": "The left knee cue came up in Squat and in Dance, 5 times."}, 4),                            # an invented number
    ({"text": "The right knee cue came up in Squat and in Dance."}, 9),                                    # the wrong side
    ({"text": "The left elbow cue came up in Squat and in Dance."}, 9),                                    # the wrong body part
    ({"text": "Great left knee work in Squat and in Dance."}, 6),
])
def test_guard_drops(seeded: Path, change: dict[str, Any], rule: int) -> None:  # AC-3, AC-7
    kept, rejected = _check(seeded, observations=[{**GOOD, **change}])
    assert kept["observations"] == [] and rejected[0]["rule"] == rule, rejected


def test_guard_ignores_digits_in_a_movement_name_and_caps_the_list(seeded: Path) -> None:  # AC-3
    bundles, names = _bundles(seeded)
    names[SQUAT] = "5 minute squat"
    text = {**GOOD, "text": "The left knee cue came up in 5 minute squat and in Dance."}
    kept, rejected = history_cross_guard.check({"observations": [text] * 5, "next_focus": None}, bundles, names, None)
    assert len(kept["observations"]) == 3 and len(rejected) == 2


def test_next_focus_needs_a_measure_still_there(seeded: Path) -> None:  # AC-5
    focus = {**GOOD, "text": "The left knee cue is the one to work on.", "cites": [GOOD["cites"][1]]}
    kept, _ = _check(seeded, next_focus=focus)
    assert kept["next_focus"]["measure"] == "knee_valgus"
    gone = {**focus, "measure": "trunk_lean_forward", "side": "center", "text": "The chest cue is the one.", "cites": [{"entry": SQUAT, "take": 1, "at_s": 5.0}]}
    kept, rejected = _check(seeded, next_focus=gone)
    assert kept["next_focus"] is None and rejected[0]["rule"] == 3  # the table says the chest cue is gone
    assert _check(seeded, observations=[])[0] == {"observations": [], "next_focus": None}
    assert history_cross_guard.check("not json", *_bundles(seeded), None)[1][0]["item"] == "answer"


def test_pack_is_text_only_with_the_question_last_and_no_private_or_rehab(seeded: Path) -> None:  # AC-3
    found = history_all.included(history_all.gather(seeded, USER, str))
    packed = history_cross.pack("all", found)
    texts = [c["text"] for c in packed["content"]]
    assert all(c["type"] == "text" for c in packed["content"]) and texts[0] == history_cross.INSTRUCTIONS
    assert texts[-1].startswith("Question:") and (packed["feature"], packed["prompt_version"]) == ("cross", "cross.v1")
    joined = "\n".join(texts)
    assert REHAB not in joined and '"private"' not in joined and "Take 3 of squat" not in joined and "Take 4 of squat" in joined
    assert packed["clips_sent"] == 0 and packed["video_consent"] is False and packed["clip_takes"] == []
    assert history_cross.pack("recap", found, "2026-10")["content"][-1]["text"].endswith("The month is 2026-10.")


def test_cache_key_covers_every_take_of_every_movement(seeded: Path) -> None:  # AC-4
    found = history_all.included(history_all.gather(seeded, USER, str))
    key = history_cross.cache_key("all", found, None, "m")
    assert key == history_cross.cache_key("all", found, None, "m") and key != history_cross.cache_key("all", found[:1], None, "m")
    assert key != history_cross.cache_key("recap", found, "2026-10", "m")
    from history_all_support import fault, KNEE, put_take
    put_take(seeded, USER, DANCE, "2026-11-02T10:00:00Z", 80, [fault(KNEE, 3.0)], mode="dance")  # one more take of one movement
    assert history_cross.cache_key("all", history_all.included(history_all.gather(seeded, USER, str)), None, "m") != key


class Answers(list):
    """Queued model answers; `asked` holds every request the fake transport saw."""

    asked: list[Any]


@pytest.fixture()
def model(monkeypatch: pytest.MonkeyPatch) -> Answers:
    """The Meta transport as a fake: `answers` are returned in order (an exception is raised); `asked` records every packed request."""
    state = Answers()
    asked: list[Any] = []

    def ask(packed: dict[str, Any], **_: Any) -> tuple[str, dict[str, Any]]:
        asked.append(packed)
        nxt = state.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt, {"input_tokens": 900, "cached_tokens": 0, "output_tokens": 80, "usd": 0.001, "clips_sent": 0}

    monkeypatch.setattr(history_api, "ask", ask)
    state.asked = asked
    return state


def _answer(**extra: Any) -> str:
    return json.dumps({"observations": [GOOD], "next_focus": None, **extra})


def _runner(state: Path) -> history_cross.Runner:
    return history_cross.Runner(state, lambda e: e.split("-")[0].title())


def test_runner_writes_a_guarded_report_and_serves_it_from_cache(seeded: Path, world: World, model: Answers) -> None:  # AC-3, AC-4
    world.opted_in.add(USER)
    model.append(_answer(observations=[GOOD, {**GOOD, "cites": [GOOD["cites"][0]]}]))
    runner = _runner(seeded)
    assert runner.request(USER, "all") == ("accepted", "running")
    assert runner.wait_idle(20)
    verdict, doc = runner.request(USER, "all")
    assert verdict == "cached" and doc["status"] == "ok" and len(doc["observations"]) == 1 and len(doc["rejected"]) == 1
    assert [e["entry_id"] for e in doc["entries"]] == [SQUAT, DANCE] and doc["usage"]["input_tokens"] == 900
    assert len(model.asked) == 1 and model.asked[0]["feature"] == "cross"  # the second request made no call
    assert not (set(doc["takes"][0]) - {"entry_id", "job_id", "take"})
    sent = doc["sent"]  # the receipt, built from the allowlist (TICKET-212)
    assert sent["feature"] == "cross" and sent["settled"] and sent["input_tokens"] == 900 and sent["digest_takes"] and sent["clip_takes"] == []
    assert history_receipt.leaks(sent, str(seeded), USER, "@", *(t["job_id"] for t in doc["takes"])) == []  # negative: no path, id, email


def test_a_failing_model_leaves_the_table(seeded: Path, world: World, model: Answers) -> None:  # AC-3
    world.opted_in.add(USER)
    model.append(history_api.HistoryError("HTTP 500 on responses"))
    runner = _runner(seeded)
    runner.request(USER, "all")
    assert runner.wait_idle(20)
    doc = runner.request(USER, "all")[1]
    assert (doc["status"], doc["observations"], doc["reason"]) == ("fallback", [], history_report.MSG_MODEL_FAILED)
    assert doc["detail"] == "HTTP 500 on responses"  # TICKET-330 R1: kept in the record, never shown
    assert doc["sent"]["settled"] is False and doc["sent"]["feature"] == "cross"  # the call was made, so the receipt says what went


def test_the_recap_model_part_carries_a_receipt(seeded: Path, world: World, model: Answers) -> None:
    world.opted_in.add(USER)
    runner = _runner(seeded)
    found = runner.plan(USER, "recap", "2026-10")[0]
    model.append(_answer())
    called = runner.compose("recap", "2026-10", found)
    assert called["sent"]["feature"] == "recap" and called["sent"]["digest_takes"] and history_receipt.leaks(called["sent"], str(seeded), USER) == []


def test_runner_refusals(seeded: Path, world: World, model: Answers, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-1, AC-5
    runner = _runner(seeded)
    with pytest.raises(history_report.Refused) as no_consent:
        runner.request(USER, "all")
    assert no_consent.value.status == 409
    world.opted_in.add(USER)
    history_all.set_left_out(seeded, USER, [DANCE])
    with pytest.raises(history_report.Refused) as one:
        runner.request(USER, "all")
    assert one.value.status == 422
    with pytest.raises(history_report.Refused) as few:
        runner.request(USER, "recap", "2026-11")  # one take in November: the model part stays hidden
    assert few.value.status == 422
    history_all.set_left_out(seeded, USER, [])
    monkeypatch.setenv("SIMON7_HISTORY_DAILY", "1")
    model.append(_answer())
    runner.request(USER, "all")
    runner.wait_idle(20)
    with pytest.raises(history_report.Refused) as capped:
        runner.request(USER, "recap", "2026-10")  # a recap counts toward the same daily cap
    assert capped.value.status == 429 and model.asked and len(model.asked) == 1


def test_one_recap_per_month_and_deleting_a_take_deletes_it(seeded: Path, world: World, model: Answers) -> None:  # AC-4, AC-5
    world.opted_in.add(USER)
    focus = {**GOOD, "text": "The left knee cue is the one to work on.", "cites": [GOOD["cites"][1]]}
    model.append(_answer(next_focus=focus))
    runner = _runner(seeded)
    runner.request(USER, "recap", "2026-10")
    assert runner.wait_idle(20)
    doc = runner.request(USER, "recap", "2026-10")[1]
    assert doc["kind"] == "recap" and doc["next_focus"]["measure"] == "knee_valgus" and model.asked[0]["feature"] == "recap"
    assert (history_store.cross_dir(seeded, USER) / "recap-2026-10.json").is_file()
    job = history_store.takes(seeded, USER, DANCE)[0]["job_id"]
    history_store.drop_take(seeded, job)
    assert not (history_store.cross_dir(seeded, USER) / "recap-2026-10.json").exists()
    assert len(model.asked) == 1


def _as(user: str | None) -> dict[str, str]:
    return {"X-Test-User": user} if user else {}


def _json(api: Api, method: str, path: str, doc: Any = None, user: str | None = USER) -> tuple[int, Any]:
    return api.json(method, path, doc, headers={**_as(user), "Origin": f"http://127.0.0.1:{api.port}"})


@pytest.fixture()
def served(api: Api, world: World) -> Api:
    world.opted_in.add(USER)
    seed(api.app.state, USER)
    return api


def test_routes_are_owner_only(served: Api) -> None:  # AC-1, TICKET-207 constraints
    paths = [("GET", "all"), ("POST", "all/prefs"), ("POST", "all/report"), ("GET", "all/report"), ("GET", "recap"),
             ("POST", "recap/report"), ("GET", f"{SQUAT}/plan")]
    for method, path in paths:
        assert _json(served, method, f"{BASE}/{path}", {"left_out": []}, user=None)[0] == 401, path
    assert _json(served, "GET", f"{BASE}/all", user=OTHER)[0] == 422  # nothing of mine is theirs: one movement or none, no card
    assert _json(served, "GET", f"{BASE}/{SQUAT}/plan", user=OTHER)[0] == 404
    assert _json(served, "GET", f"{BASE}/recap", user=OTHER)[1]["recap"]["takes"] == 0
    assert _json(served, "POST", f"{BASE}/all/prefs", {"left_out": []}, user=OTHER)[0] == 422


def test_all_route_lists_what_the_report_reads_and_lets_one_out(served: Api) -> None:  # AC-1, AC-2
    status, doc = _json(served, "GET", f"{BASE}/all")
    assert status == 200 and doc["can_read"] and doc["report"] == "none"
    assert [(e["entry_id"], e["takes"], e["left_out"]) for e in doc["entries"]] == [(SQUAT, 3, False), (DANCE, 2, False)]
    assert doc["table"][0]["measure"] == "knee_valgus" and "Meta" in doc["disclosure"]
    assert "private" not in json.dumps(doc) and REHAB not in json.dumps(doc)
    status, doc = _json(served, "POST", f"{BASE}/all/prefs", {"left_out": [DANCE, "not-mine-1234"]})
    assert status == 200 and not doc["can_read"] and [e["left_out"] for e in doc["entries"]] == [False, True]
    assert _json(served, "POST", f"{BASE}/all/prefs", {"left_out": "x"})[0] == 400
    assert _json(served, "POST", f"{BASE}/all/report")[0] == 422  # fewer than two movements read
    assert _json(served, "DELETE", f"{BASE}/all")[0] == 405  # nothing deletes the table; Delete my data removes the reports


def test_all_report_over_http(served: Api, model: Answers) -> None:  # AC-3
    model.append(_answer())
    status, _ = _json(served, "POST", f"{BASE}/all/report")
    assert status == 202
    history_cross.runner_for(served.app.state, served.app.child).wait_idle(20)
    status, doc = _json(served, "GET", f"{BASE}/all/report")
    assert status == 200 and doc["status"] == "ok" and doc["observations"][0]["cites"][0]["entry"] == SQUAT
    assert _json(served, "GET", f"{BASE}/all")[1]["report"] == "ready"
    _json(served, "POST", f"{BASE}/all/prefs", {"left_out": [DANCE]})  # a leave-one-out change voids the report
    assert _json(served, "GET", f"{BASE}/all/report")[0] == 404


def test_recap_route(served: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-5
    monkeypatch.setattr(history_recap, "utc_now", lambda: __import__("datetime").datetime(2026, 11, 3, tzinfo=__import__("datetime").timezone.utc))
    status, doc = _json(served, "GET", f"{BASE}/recap")
    assert status == 200 and doc["recap"]["month"] == "2026-10" and doc["offer"]["month"] == "2026-10"  # the start of a month offers last month
    assert (doc["recap"]["takes"], doc["model_state"]) == (4, "none")
    assert _json(served, "GET", f"{BASE}/recap?month=2026-11")[1]["model_state"] == "hidden"  # one take: below 4
    assert _json(served, "GET", f"{BASE}/recap?month=2025-02")[1]["recap"]["takes"] == 0
    assert _json(served, "GET", f"{BASE}/recap?month=bad")[0] == 400
    listing = _json(served, "GET", BASE)[1]
    assert listing["across"] is True and listing["recap_offer"]["month"] == "2026-10"


def test_plan_route_after_a_take(served: Api) -> None:  # TICKET-223
    status, doc = _json(served, "GET", f"{BASE}/{SQUAT}/plan")
    assert status == 200 and [i["kind"] for i in doc["plan"]["items"]] == ["cue", "takes"] and "tomorrow" in doc["plan"]["spacing"]
    assert _json(served, "GET", f"{BASE}/{REHAB}/plan")[1] == {"plan": None}  # rehab: nothing added
    assert _json(served, "GET", f"{BASE}/nothing-here-123/plan")[0] == 404
    assert _json(served, "POST", f"{BASE}/{SQUAT}/plan")[0] == 405


def _no_overlap(api: Api, world: World) -> None:
    """OTHER reads two movements whose measures differ: a knee cue in the squat, a chest cue in the dance routine."""
    from history_all_support import CHEST, fault, KNEE, put_take
    world.opted_in.add(OTHER)
    put_take(api.app.state, OTHER, SQUAT, "2026-10-05T10:00:00Z", 60, [fault(KNEE, 2.0)])
    put_take(api.app.state, OTHER, DANCE, "2026-10-10T10:00:00Z", 50, [fault(CHEST, 3.0)], mode="dance")


def test_an_empty_cross_table_turns_the_read_off_with_the_reason(api: Api, world: World, model: Answers) -> None:  # DEF-1
    _no_overlap(api, world)
    status, doc = _json(api, "GET", f"{BASE}/all", user=OTHER)
    assert status == 200 and doc["can_read"] is False and doc["blocked"] == history_all.MSG_NO_OVERLAP
    assert history_all.across(doc["table"]) == [] and len(doc["entries"]) == 2
    status, refused = _json(api, "POST", f"{BASE}/all/report", user=OTHER)
    assert status == 422 and history_all.MSG_NO_OVERLAP in json.dumps(refused) and not model.asked  # the job uses the same rule


def test_an_overlap_keeps_the_read_on(served: Api) -> None:  # DEF-1 (negative of the above)
    status, doc = _json(served, "GET", f"{BASE}/all")
    assert status == 200 and doc["can_read"] is True and doc["blocked"] is None


def test_one_movement_left_gives_the_old_reason(served: Api) -> None:
    doc = _json(served, "POST", f"{BASE}/all/prefs", {"left_out": [DANCE]})[1]
    assert doc["can_read"] is False and "at least 2 movements" in doc["blocked"]
