"""TICKET-228: the progress reel (docs/specs/history-reel.md). The model is a fake transport; ffmpeg is real.

The model answers below are HAND-WRITTEN TEST FIXTURE text, not model output.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from history_support import ENTRY, FIRST, OTHER, SECOND, USER, World, job_record, record_two, seed_job, world  # noqa: F401
from part7 import history_api, history_receipt, history_reel, history_report, history_store
from support import Api
from test_history_api import FakeTransport
from test_history_prompt import make

BASE = f"api/me/history/{ENTRY}"
GOOD = {"moments": [
    {"take": 2, "at_s": 0.9, "role": "early", "text": "The trunk leans forward at 0.9 s in Take 2."},
    {"take": 1, "at_s": 1.0, "role": "best", "text": "Take 1 stays upright at 1.0 s."}]}


def _as(user: str | None) -> dict[str, str]:
    return {"X-Test-User": user} if user else {}


def _json(api: Api, method: str, path: str, doc: Any = None, user: str | None = USER) -> tuple[int, Any]:
    return api.json(method, path, doc, headers={**_as(user), "Origin": f"http://127.0.0.1:{api.port}"})


def _streams(path: Path) -> tuple[list[str], float]:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    doc = json.loads(out)
    return [s["codec_type"] for s in doc["streams"]], float(doc["format"]["duration"])


# ----- choosing the clips (pure) --------------------------------------------------------------------------------
def test_select_takes_is_at_most_five_and_keeps_first_best_latest() -> None:
    facts, rows = make([50, 60, 95, 70, 72, 74, 76, 80, 82, 85], duration=10.0)
    chosen = history_reel.select_takes(rows, facts)
    assert len(chosen) == 5 and {1, 3, 10} <= set(chosen) and chosen == sorted(chosen)
    assert chosen == history_reel.select_takes(list(reversed(rows)), facts)  # same history, same choice


def test_select_takes_adds_the_take_where_a_fault_changed() -> None:
    facts, rows = make([50, 60, 70, 80, 90, 85], duration=10.0)
    facts["measures"] = [{"measure": "knee_valgus", "side": "left", "present_in": [2], "status": "fixed",
                          "first": {"take": 2}, "last": {"take": 2}}]
    chosen = history_reel.select_takes(rows, facts)
    assert 2 in chosen and 3 in chosen  # where it showed, and the take after, where it was gone


def test_select_takes_skips_private_and_clipless_and_long_takes() -> None:
    facts, rows = make([50, 60, 70, 80], duration=10.0, private=(1,))
    rows[1]["clip"] = None
    rows[2]["duration_s"] = history_reel.history_prompt.CLIP_MAX_S + 1
    assert history_reel.select_takes(rows, facts) == [4]  # take 1 is private, 2 has no clip, 3 is too long
    assert history_reel.select_takes([], facts) == []


def test_pack_sends_only_the_chosen_clips_and_prices_by_seconds() -> None:
    facts, rows = make([50, 60, 70, 80, 90, 85, 88], duration=10.0)
    chosen = history_reel.select_takes(rows, facts)
    packed = history_reel.pack("e1", facts, rows, chosen=chosen)
    videos = [i["label"] for i in packed["content"] if i["type"] == "video"]
    assert len(videos) == packed["clips_sent"] == len(chosen) <= 5 and packed["clip_takes"] == chosen
    assert packed["feature"] == "reel" and packed["prompt_version"] == "reel.v1" and packed["video_seconds"] == 10.0 * len(chosen)
    assert sum(1 for i in packed["content"] if i["type"] == "text" and i["text"].startswith("Take ")) == 7  # every take's digest rides along
    assert packed["content"][0]["text"] == history_reel.INSTRUCTIONS  # the stable part first


# ----- the guard on moments -------------------------------------------------------------------------------------------
def _facts() -> dict[str, Any]:
    facts, _ = make([60, 80], duration=6.0)
    facts["takes"][1]["faults"] = [{"measure": "trunk_lean_forward", "side": "center", "at_s": 0.9, "span": [0.5, 1.4]}]
    return facts


def test_guard_keeps_checked_moments_and_drops_the_rest() -> None:
    answer = {"moments": [
        {"take": 2, "at_s": 0.9, "role": "early", "text": "The trunk leans forward at 0.9 s in Take 2."},
        {"take": 1, "at_s": 2.0, "role": "best", "text": "Take 1 is upright at 2.0 s."},
        {"take": 2, "at_s": 99.0, "role": "latest", "text": "A time outside the take."},
        {"take": 7, "at_s": 1.0, "role": "later", "text": "A take that does not exist."},
        {"take": 1, "at_s": 1.0, "role": "later", "text": "The score went to 41 here."},
        {"take": 1, "at_s": 1.0, "role": "later", "text": "Great depth in Take 1."}]}
    kept, rejected = history_reel.guard_moments(answer, _facts(), [1, 2], history_reel.history_guard.DEFAULT_WORDS)
    assert [(m["take"], m["at_s"], m["role"]) for m in kept] == [(2, 0.9, "early"), (1, 2.0, "best")]
    assert {r["item"] for r in rejected} == {"moments[2]", "moments[3]", "moments[4]", "moments[5]"}
    assert all(m["label"] == "model_opinion" for m in kept)


def test_guard_drops_a_moment_of_a_take_whose_clip_was_not_sent() -> None:  # rule 8
    kept, rejected = history_reel.guard_moments(GOOD, _facts(), [2])
    assert [m["take"] for m in kept] == [2] and rejected[0]["rule"] == 8 and rejected[0]["item"] == "moments[1]"


def test_guard_drops_a_wrong_side_or_body_part() -> None:  # rule 9
    answer = {"moments": [{"take": 2, "at_s": 0.9, "role": "early", "text": "The left knee caves in at 0.9 s."}]}
    kept, rejected = history_reel.guard_moments(answer, _facts(), [2])
    assert kept == [] and rejected[0]["rule"] == 9


def test_guard_passes_more_than_three_moments_in_chunks() -> None:
    answer = {"moments": [{"take": 1, "at_s": 1.0 + i, "role": "later", "text": f"Take 1 at {1.0 + i:.1f} s."} for i in range(5)]}
    kept, rejected = history_reel.guard_moments(answer, _facts(), [1, 2])
    assert len(kept) == 5 and rejected == []
    assert history_reel.guard_moments("not json", _facts(), [1])[0] == []


# ----- cutting ------------------------------------------------------------------------------------------------------
def test_window_stays_inside_the_clip_and_the_reel_stays_under_thirty_seconds() -> None:
    assert history_reel.window(0.2, 10.0) == (0.0, 3.0)
    assert history_reel.window(5.0, 10.0) == (3.5, 6.5)
    assert history_reel.window(9.9, 10.0) == (7.0, 10.0)
    assert history_reel.window(1.0, 2.0) == (0.0, 2.0)
    moments = [{"take": 1, "at_s": float(i), "text": "x", "role": "later"} for i in range(1, 20)]
    segments = history_reel.plan_segments(moments, {1: 30.0})
    assert sum(s["end_s"] - s["start_s"] for s in segments) <= history_reel.MAX_REEL_S and len(segments) == 10


def test_render_joins_captioned_segments_without_audio(tmp_path: Path) -> None:
    from history_support import video
    clips = {1: video(tmp_path / "a.mp4", 6), 2: video(tmp_path / "b.mp4", 6, "480x854")}
    moments = [{"take": 1, "at_s": 2.0, "text": "A long sentence about the trunk leaning forward in the early take, wrapped.", "role": "early"},
               {"take": 2, "at_s": 3.0, "text": "The same moment later.", "role": "later"}]
    segments = history_reel.plan_segments(moments, {1: 6.0, 2: 6.0})
    out = tmp_path / "reel.mp4"
    history_reel.render(segments, clips, out)
    kinds, seconds = _streams(out)
    assert kinds == ["video"] and 5.5 <= seconds <= 6.5  # two cuts of about 3 s, no audio track
    assert history_reel.caption(segments[0]).startswith("Take 1, 2.0 s\n")
    with pytest.raises(history_reel.ReelError):
        history_reel.render([], clips, tmp_path / "none.mp4")
    with pytest.raises(history_reel.ReelError):
        history_reel.render(segments, {1: tmp_path / "missing.mp4", 2: clips[2]}, tmp_path / "bad.mp4")


# ----- routes -------------------------------------------------------------------------------------------------------------
@pytest.fixture()
def seeded(api: Api, world: World) -> Api:  # noqa: F811
    record_two(api.app.state, world)
    runner = history_reel.runner_for(api.app.state)
    runner.transport = FakeTransport(answer=json.dumps(GOOD), usage={"input_tokens": 9000, "output_tokens": 300, "input_tokens_details": {"cached_tokens": 0}})
    runner._failed.clear()
    return api


def _make(api: Api) -> dict[str, Any]:
    assert _json(api, "POST", f"{BASE}/reel")[0] in (202, 200)
    assert history_reel.runner_for(api.app.state).wait_idle(60)
    status, doc = _json(api, "GET", f"{BASE}/reel")
    assert status == 200
    return doc


def test_reel_needs_a_session_and_belongs_to_its_owner(seeded: Api) -> None:
    for method, path in (("GET", "reel"), ("POST", "reel"), ("GET", "reel.mp4")):
        assert _json(seeded, method, f"{BASE}/{path}", user=None)[0] == 401
        assert _json(seeded, method, f"{BASE}/{path}", user=OTHER)[0] == 404
    history_store.set_consent(seeded.app.state, USER, True, "video-v1")
    _make(seeded)
    assert _json(seeded, "GET", f"{BASE}/reel", user=OTHER)[0] == 404
    assert seeded.request("GET", f"{BASE}/reel.mp4", headers=_as(OTHER))[0] == 404
    assert seeded.request("GET", f"{BASE}/reel.mp4")[0] == 401


def test_reel_refuses_without_the_video_consent_and_without_keeping(seeded: Api, world: World) -> None:  # noqa: F811
    status, doc = _json(seeded, "POST", f"{BASE}/reel")
    assert status == 409 and doc["message"] == history_reel.MSG_VIDEO
    world.opted_in.discard(USER)
    assert _json(seeded, "POST", f"{BASE}/reel")[1]["message"] == history_reel.MSG_CONSENT
    assert _json(seeded, "GET", f"{BASE}/reel")[0] == 404 and not history_api.ledger_path(seeded.app.state).exists()


def test_reel_needs_two_clips(seeded: Api) -> None:
    history_store.set_consent(seeded.app.state, USER, True, "video-v1")
    for take in history_store.takes(seeded.app.state, USER, ENTRY):
        take["clip"].unlink()
    assert _json(seeded, "POST", f"{BASE}/reel")[0] == 422


def test_reel_is_made_from_the_clips_and_served_to_its_owner(seeded: Api) -> None:
    history_store.set_consent(seeded.app.state, USER, True, "video-v1")
    transport = history_reel.runner_for(seeded.app.state).transport
    doc = _make(seeded)
    assert doc["status"] == "ok" and doc["watched"] == [1, 2] and len(transport.uploaded) == 2 <= 5
    assert [(m["take"], m["at_s"]) for m in doc["moments"]] == [(2, 0.9), (1, 1.0)]
    assert doc["moments"][0]["clip"] == f"{BASE}/takes/{SECOND}/clip.mp4" and doc["seeded"] is False
    assert doc["video_url"] == f"{BASE}/reel.mp4" and 0 < doc["seconds"] <= 30 and str(seeded.app.state) not in json.dumps(doc)
    status, headers, body = seeded.request("GET", f"{BASE}/reel.mp4", headers=_as(USER))
    assert status == 200 and headers["content-type"] == "video/mp4" and len(body) > 1000
    path = history_reel.file_for(seeded.app.state, USER, ENTRY, doc["key"])
    assert _streams(path)[0] == ["video"] and _streams(path)[1] <= 30
    assert transport.deleted == ["file-1", "file-2"]  # uploaded copies are deleted
    sent = doc["sent"]  # the receipt: take numbers and counts only (TICKET-212)
    assert sent["feature"] == "reel" and sent["clip_takes"] == [1, 2] and sent["digest_takes"] == [1, 2] and sent["video_consent"] is True
    assert history_receipt.leaks(sent, str(seeded.app.state), USER, "@", "clip.mp4", FIRST, SECOND) == []  # negative: no path, id, email, job id
    rows = [json.loads(line) for line in history_api.ledger_path(seeded.app.state).read_text().splitlines()]
    assert {r["feature"] for r in rows} == {"reel"} and {r["prompt_version"] for r in rows} == {"reel.v1"}
    again = _json(seeded, "POST", f"{BASE}/reel")
    assert again[0] == 200 and len(transport.bodies) == 1  # served from the stored reel: no second call


def test_reel_of_a_seeded_history_is_labelled_seeded(seeded: Api) -> None:
    history_store.set_consent(seeded.app.state, USER, True, "video-v1")
    for take in history_store.takes(seeded.app.state, USER, ENTRY):
        meta = history_store.take_dir(seeded.app.state, USER, ENTRY, take["job_id"]) / history_store.META_NAME
        meta.write_text(json.dumps({**json.loads(meta.read_text()), "synthetic": True}))
    assert _make(seeded)["seeded"] is True


def test_a_failed_call_ends_in_a_plain_reason_and_can_be_tried_again(seeded: Api) -> None:
    history_store.set_consent(seeded.app.state, USER, True, "video-v1")
    runner = history_reel.runner_for(seeded.app.state)
    runner.transport = FakeTransport(fail="respond")
    doc = _make(seeded)
    assert doc["status"] == "failed" and doc["reason"] == history_report.MSG_MODEL_FAILED and "moments" not in doc
    _, key = runner.plan(USER, ENTRY)  # TICKET-330 R1: the screen gets plain words, the record keeps the call's own failure
    assert "HTTP 500" in json.loads(history_reel.failed_path(seeded.app.state, USER, ENTRY, key).read_text())["detail"]
    runner.transport = FakeTransport(answer=json.dumps({"moments": [GOOD["moments"][0]]}))  # one checked moment is not a reel
    assert _make(seeded)["reason"] == history_reel.MSG_NO_MOMENTS
    runner.transport = FakeTransport(answer=json.dumps(GOOD))
    assert _make(seeded)["status"] == "ok"


def test_reel_goes_with_consent_withdrawal_a_dropped_take_and_delete_my_data(seeded: Api) -> None:
    state = seeded.app.state
    history_store.set_consent(state, USER, True, "video-v1")
    doc = _make(seeded)
    path = history_reel.file_for(state, USER, ENTRY, doc["key"])
    assert path.is_file()
    history_store.set_consent(state, USER, False, "video-v1")  # video consent withdrawn
    assert not path.exists() and _json(seeded, "GET", f"{BASE}/reel")[0] == 404
    history_store.set_consent(state, USER, True, "video-v1")
    _make(seeded)
    assert history_store.drop_take(state, FIRST) == 1  # a take dropped
    assert history_reel.latest(state, USER, ENTRY) is None
    assert not list(history_reel.reels_dir(state, USER, ENTRY).glob("*.mp4"))


def test_forget_removes_the_reel_folder(seeded: Api) -> None:
    state = seeded.app.state
    history_store.set_consent(state, USER, True, "video-v1")
    _make(seeded)
    assert history_reel.reels_dir(state, USER, ENTRY).is_dir()
    assert history_store.forget(state, USER) == 2
    assert not history_store.entry_dir(state, USER, ENTRY).exists()


# ----- freeze fix: a reel that dies says so (staging: video consent turned off mid-run, then a silent 404) -------------
class ConsentOffTransport(FakeTransport):
    """Turns the video consent off while the model call is out, as a second tab of the same account did on staging."""

    def __init__(self, state: Path, **kw: Any) -> None:
        super().__init__(**kw)
        self.state = state

    def respond(self, body: dict[str, Any]) -> Any:
        history_store.set_consent(self.state, USER, False, "video-v1")
        return super().respond(body)


def test_video_consent_turned_off_mid_run_is_a_failed_reel_with_a_reason(seeded: Api, caplog: pytest.LogCaptureFixture) -> None:
    state = seeded.app.state
    history_store.set_consent(state, USER, True, "video-v1")
    runner = history_reel.runner_for(state)
    runner.transport = ConsentOffTransport(state, answer=json.dumps(GOOD))
    with caplog.at_level("INFO", logger="part7"):
        assert _json(seeded, "POST", f"{BASE}/reel")[0] == 202
        assert runner.wait_idle(60)
    status, doc = _json(seeded, "GET", f"{BASE}/reel")
    assert status == 200 and doc["status"] == "failed" and doc["reason"] == history_reel.MSG_VIDEO_OFF  # was a bare 404
    lines = [r.getMessage() for r in caplog.records if "history: reel" in r.getMessage()]
    assert any(line.endswith(": start") for line in lines) and any("failed: " + history_reel.MSG_VIDEO_OFF in line for line in lines)
    assert not list(history_reel.reels_dir(state, USER, ENTRY).glob("*.mp4"))  # negative: nothing is kept


def test_a_failure_outlives_the_worker_and_a_dead_job_reads_as_stopped(seeded: Api) -> None:
    state = seeded.app.state
    history_store.set_consent(state, USER, True, "video-v1")
    runner = history_reel.runner_for(state)
    runner.transport = FakeTransport(fail="respond")
    _make(seeded)
    runner._failed.clear()  # a restart forgets the worker's memory; the failure on disk stays
    status, doc = _json(seeded, "GET", f"{BASE}/reel")
    assert status == 200 and doc["status"] == "failed" and doc["reason"] == history_report.MSG_MODEL_FAILED
    _, key = runner.plan(USER, ENTRY)
    history_reel.failed_path(state, USER, ENTRY, key).unlink()
    history_store.write_json(history_reel.pending_path(state, USER, ENTRY, key), {"entry_id": ENTRY, "key": key})  # accepted, then the server died
    status, doc = _json(seeded, "GET", f"{BASE}/reel")
    assert status == 200 and doc["status"] == "failed" and doc["reason"] == history_reel.MSG_STOPPED
    runner.transport = FakeTransport(answer=json.dumps(GOOD), usage={"input_tokens": 9000, "output_tokens": 300, "input_tokens_details": {"cached_tokens": 0}})
    assert _make(seeded)["status"] == "ok"  # a new make clears the marker and the old failure
    assert not history_reel.pending_path(state, USER, ENTRY, key).exists() and not history_reel.failed_path(state, USER, ENTRY, key).exists()


def test_reel_of_the_seeded_demo_is_made(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The staging demo as seeded by tools/seed_history.py: its takes have clips (not read as model-only) and a reel is cut."""
    import sys
    import time

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    import seed_history
    from part7 import auth, identity

    monkeypatch.setenv("SIMON7_STAGING", "1")
    seed_history.seed(tmp_path)
    user = identity.IdentityStore(tmp_path, auth._pepper(tmp_path))._user_for("demo-ada@example.com", time.time())
    rows = history_store.takes(tmp_path, user, seed_history.SQUAT)
    assert rows and all(r["clip"] is not None and r["video_kept"] for r in rows)
    history_store.set_consent(tmp_path, user, True, "video-v1")
    runner = history_reel.ReelRunner(tmp_path)
    usable, key = runner.plan(user, seed_history.SQUAT)
    chosen = history_reel.select_takes(usable, history_reel.history_facts.build(usable, seed_history.SQUAT))
    answer = {"moments": [{"take": chosen[0], "at_s": 1.0, "role": "early", "text": f"Take {chosen[0]} at 1.0 s."},
                          {"take": chosen[-1], "at_s": 2.0, "role": "latest", "text": f"Take {chosen[-1]} at 2.0 s."}]}
    runner.transport = FakeTransport(answer=json.dumps(answer), usage={"input_tokens": 9000, "output_tokens": 300, "input_tokens_details": {"cached_tokens": 0}})
    assert runner.request(user, seed_history.SQUAT) == ("accepted", "queued")
    assert runner.wait_idle(120)
    assert runner.failure(user, seed_history.SQUAT, key) is None
    doc = history_reel.cached(tmp_path, user, seed_history.SQUAT, key)
    assert doc is not None and doc["seeded"] is True and len(doc["moments"]) == 2
