"""The report job (docs/specs/history.md "Report", TICKET-180 AC-3 to AC-6), with a fake `history_api` and guard."""

from __future__ import annotations

import json
from pathlib import Path
import threading
import time

import pytest

from history_support import ENTRY, FIRST, OTHER, SECOND, USER, World, record_two, seed_job, world  # noqa: F401
from part7 import history_report, history_store

ANSWER = json.dumps({"summary": {"text": "Take 2 scored 77.", "cites": [{"take": 2}]}, "trends": [], "observations": []})


@pytest.fixture()
def runner(tmp_path: Path, world: World, monkeypatch: pytest.MonkeyPatch) -> history_report.Runner:
    world.install_model(monkeypatch)
    record_two(tmp_path, world)
    return history_report.Runner(tmp_path, tmp_path / "catalog")


def _report(runner: history_report.Runner, user: str = USER) -> dict:
    kind, value = runner.request(user, ENTRY)
    assert runner.wait_idle(20)
    key = runner.plan(user, ENTRY)[1]
    return history_report.cached(runner.state, user, ENTRY, key) or value


def test_cache_key(tmp_path: Path, world: World) -> None:  # AC-4
    record_two(tmp_path, world)
    takes = history_store.takes(tmp_path, USER, ENTRY)
    key = history_report.cache_key("p1", "m", takes, "nsha", False)
    assert key == history_report.cache_key("p1", "m", list(reversed(takes)), "nsha", False)  # order does not matter
    assert len(key) == 64
    assert history_report.cache_key("p2", "m", takes, "nsha", False) != key
    assert history_report.cache_key("p1", "m2", takes, "nsha", False) != key
    assert history_report.cache_key("p1", "m", takes, "other", False) != key
    assert history_report.cache_key("p1", "m", takes, "nsha", True) != key
    assert history_report.cache_key("p1", "m", takes[:1], "nsha", False) != key
    takes[1]["analysis"].write_text(takes[1]["analysis"].read_text().replace('"value": 77', '"value": 78', 1))  # a changed take
    assert history_report.cache_key("p1", "m", takes, "nsha", False) != key
    takes[0]["clip"].write_bytes(b"other clip")
    assert history_report.cache_key("p1", "m", takes, "nsha", False) not in (key,)


def test_ok_report_is_written_and_served_from_cache(runner: history_report.Runner, world: World) -> None:  # AC-3, AC-4
    world.answers.append(ANSWER)
    kind, state = runner.request(USER, ENTRY)
    assert (kind, state) in (("accepted", "queued"), ("accepted", "running"))
    assert runner.wait_idle(20)
    report = history_report.cached(runner.state, USER, ENTRY, runner.plan(USER, ENTRY)[1])
    assert report["status"] == "ok" and report["format"] == "simon.history.v1" and report["reason"] == ""
    assert report["summary"]["text"] == "Take 2 scored 77." and report["usage"]["input_tokens"] == 1234 and report["usage"]["clips_sent"] == 2
    assert [t["take"] for t in report["takes"]] == [1, 2] and report["facts"]["format"] == "simon.history.facts.v1"
    assert report["trends"] and report["trends"][0]["source"] == "fact_table"  # the guard kept none, the table's stay
    kind, hit = runner.request(USER, ENTRY)
    assert kind == "cached" and hit["key"] == report["key"] and len(world.asked) == 1  # no second call


def test_packed_has_no_clips_without_video_consent_and_no_private_takes(tmp_path: Path, world: World,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:  # private
    world.install_model(monkeypatch)
    world.opted_in.add(USER)
    for job, extra in ((FIRST, {}), (SECOND, {}), ("aaaaaaaaaaaa", {"private": True})):
        if job == "aaaaaaaaaaaa":
            folder = seed_job(tmp_path, SECOND, **extra)  # reuse the fixture files under a private job id
            private = tmp_path / "jobs" / job
            folder.rename(private)
            record = json.loads((private / "job.json").read_text()) | {"id": job, "private": True, "finished_at": "2026-10-31T19:00:00Z"}
            (private / "job.json").write_text(json.dumps(record))
            folder = private
            world.owners[job] = USER
            assert history_store.record_take(tmp_path, record, folder)
        else:
            folder = seed_job(tmp_path, job, **extra)
            world.owners[job] = USER
            history_store.record_take(tmp_path, json.loads((folder / "job.json").read_text()), folder)
    assert len(history_store.takes(tmp_path, USER, ENTRY)) == 3
    runner = history_report.Runner(tmp_path, tmp_path / "catalog")
    world.answers.append(ANSWER)
    runner.request(USER, ENTRY)
    assert runner.wait_idle(20)
    packed = world.asked[0]
    assert packed["video_consent"] is False and [r["job_id"] for r in packed["rows"]] == [FIRST, SECOND]  # private job left out
    assert [t["take"] for t in packed["facts"]["takes"]] == [1, 2] and world.ask_state[0] == tmp_path
    assert world.guard_calls[0][1] is packed["facts"]  # the guard gets the facts of the takes sent
    history_store.set_consent(tmp_path, USER, True, "v1")  # a new key, now with video consent
    world.answers.append(ANSWER)
    runner.request(USER, ENTRY)
    assert runner.wait_idle(20)
    assert world.asked[1]["video_consent"] is True and not any(r["private"] for r in world.asked[1]["rows"])


def test_fallback_on_history_error(runner: history_report.Runner, world: World) -> None:  # AC-6
    import sys

    spent = {"input_tokens": 10, "usd": 0.001}
    world.answers.append(sys.modules["part7.history_api"].HistoryError("over the daily cap", spent))
    report = _report(runner)
    assert report["status"] == "fallback" and report["reason"] == "over the daily cap"
    assert report["usage"]["input_tokens"] == 10 and report["usage"]["output_tokens"] == 0  # what the failed call cost
    assert report["summary"]["source"] == "fact_table" and report["summary"]["label"]
    assert report["facts"]["measures"][0]["measure"] == "trunk_lean_forward" and report["usage"]["usd"] == 0.001
    assert report["focus"] is None and report["observations"] == [] and report["rejected"] == []


@pytest.mark.parametrize("answer", ["not json", "[1, 2]", ValueError("boom")])
def test_fallback_on_any_failure(runner: history_report.Runner, world: World, answer: object) -> None:  # AC-6
    world.answers.append(answer)
    report = _report(runner)
    assert report["status"] == "fallback" and report["reason"] and report["facts"]["takes"]


def test_fallback_when_the_guard_fails(runner: history_report.Runner, world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-6
    import sys

    def broken(*args: object) -> None:
        raise RuntimeError("guard broke")

    monkeypatch.setattr(sys.modules["part7.history_guard"], "check", broken)
    world.answers.append(ANSWER)
    assert _report(runner)["status"] == "fallback"


def test_skipped_without_the_model_modules(tmp_path: Path, world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-6
    monkeypatch.setitem(__import__("sys").modules, "part7.history_api", None)
    monkeypatch.setitem(__import__("sys").modules, "part7.history_guard", None)
    monkeypatch.setitem(__import__("sys").modules, "part7.history_prompt", None)
    record_two(tmp_path, world)
    runner = history_report.Runner(tmp_path)
    report = _report(runner)
    assert report["status"] == "skipped" and report["reason"] and report["summary"]["label"]


def test_guard_result_and_rejections_are_kept(runner: history_report.Runner, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    kept = {"summary": {"text": "kept", "cites": [{"take": 1}]}, "trends": [{"kind": "new", "measure": "m", "side": "center", "text": "t", "cites": []}],
            "focus": {"cue": "Keep your chest up"}, "teacher_link": None, "observations": [{"take": 2, "at_s": 1.0, "text": "o"}]}
    monkeypatch.setattr(sys.modules["part7.history_guard"], "check", lambda *a: (kept, [{"item": "x", "reason": "no cite"}]))
    world.answers.append(ANSWER)
    report = _report(runner)
    assert report["status"] == "ok" and report["summary"]["text"] == "kept" and report["trends"] == kept["trends"]
    assert report["focus"] == kept["focus"] and report["observations"] == kept["observations"]
    assert report["rejected"] == [{"item": "x", "reason": "no cite"}]


def test_background_single(runner: history_report.Runner, world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-5
    import sys

    gate, entered, order = threading.Event(), threading.Event(), []
    real = sys.modules["part7.history_api"].ask

    def slow(packed: dict, **kw: object) -> tuple:
        order.append(("start", threading.current_thread().name))
        entered.set()
        gate.wait(10)
        order.append(("end", ""))
        return real(packed, **kw)

    monkeypatch.setattr(sys.modules["part7.history_api"], "ask", slow)
    world.answers.extend([ANSWER, ANSWER])
    # a second signed-in user with the same two takes
    world.opted_in.add(OTHER)
    t0 = time.monotonic()
    first = runner.request(USER, ENTRY)
    assert time.monotonic() - t0 < 1.0 and first[0] == "accepted"  # the request does not wait for the model
    assert entered.wait(10)
    assert runner.status(USER, ENTRY, runner.plan(USER, ENTRY)[1]) == "running"
    assert runner.request(USER, ENTRY) == ("accepted", "running")  # the same report is not queued twice
    assert order == [("start", "part7-history")]  # off the request thread, and only one call so far
    gate.set()
    assert runner.wait_idle(20)
    assert [o[0] for o in order] == ["start", "end"] and len(world.asked) == 1


def test_second_report_waits_for_the_first(tmp_path: Path, world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-5
    import sys

    world.install_model(monkeypatch)
    record_two(tmp_path, world)
    # the same takes held by a second user: copy the first user's history folder
    other_root = tmp_path / "history" / OTHER
    __import__("shutil").copytree(tmp_path / "history" / USER, other_root)
    world.opted_in.add(OTHER)
    live, peak, gate = [0], [0], threading.Event()
    real = sys.modules["part7.history_api"].ask

    def counted(packed: dict, **kw: object) -> tuple:
        live[0] += 1
        peak[0] = max(peak[0], live[0])
        gate.wait(0.3)
        live[0] -= 1
        return real(packed, **kw)

    monkeypatch.setattr(sys.modules["part7.history_api"], "ask", counted)
    world.answers.extend([ANSWER, ANSWER])
    runner = history_report.Runner(tmp_path)
    runner.request(USER, ENTRY)
    assert runner.request(OTHER, ENTRY)[0] == "accepted"
    assert runner.wait_idle(20) and peak[0] == 1 and len(world.asked) == 2


def test_report_codes(runner: history_report.Runner, world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-3
    world.opted_in.discard(USER)
    with pytest.raises(history_report.Refused) as no_consent:
        runner.request(USER, ENTRY)
    assert no_consent.value.status == 409
    world.opted_in.add(USER)
    with pytest.raises(history_report.Refused) as few:
        runner.request(OTHER, ENTRY)  # no takes at all
    assert few.value.status == 409  # OTHER has not opted in
    world.opted_in.add(OTHER)
    with pytest.raises(history_report.Refused) as few:
        runner.request(OTHER, ENTRY)
    assert few.value.status == 422
    monkeypatch.setenv("SIMON7_HISTORY_DAILY", "2")
    world.answers.extend([ANSWER, ANSWER])
    now = time.time()
    runner.request(USER, ENTRY, now=now)
    assert runner.wait_idle(20)
    history_store.set_consent(runner.state, USER, True, "v1")  # a new key: not a cache hit
    runner.request(USER, ENTRY, now=now + 1)
    assert runner.wait_idle(20)
    history_store.set_consent(runner.state, USER, False, "v1")  # drops the video report; the first key's report stays
    kind, _ = runner.request(USER, ENTRY, now=now + 2)
    assert kind == "cached"  # a cache hit never counts toward the limit
    # change the takes so a third run is needed
    take = history_store.takes(runner.state, USER, ENTRY)[1]["analysis"]
    take.write_text(take.read_text().replace('"value": 77', '"value": 79', 1))
    with pytest.raises(history_report.Refused) as limit:
        runner.request(USER, ENTRY, now=now + 4)
    assert limit.value.status == 429 and history_report.runs_today(runner.state, USER, now + 4) == 2
    assert history_report.runs_today(runner.state, USER, now + 2 * 86400) == 0  # the next day starts clean
    monkeypatch.setenv("SIMON7_HISTORY_DAILY", "x")
    assert history_report.daily_limit() == 5


def test_rehab_take_is_included_like_any_other(tmp_path: Path, world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # private
    world.install_model(monkeypatch)
    world.opted_in.add(USER)
    for job, extra in ((FIRST, {"mode": "rehab"}), (SECOND, {})):  # rehab, and a record with no private field
        folder = seed_job(tmp_path, job, with_video=False, **extra)
        world.owners[job] = USER
        history_store.record_take(tmp_path, json.loads((folder / "job.json").read_text()), folder)
    runner = history_report.Runner(tmp_path)
    world.answers.append(ANSWER)
    runner.request(USER, ENTRY)
    assert runner.wait_idle(20)
    assert [t["take"] for t in world.asked[0]["facts"]["takes"]] == [1, 2] and len(world.guard_calls[0][1]["takes"]) == 2


def test_a_single_hostable_take_is_422(tmp_path: Path, world: World) -> None:  # AC-3, private
    world.opted_in.add(USER)
    for job, extra in ((FIRST, {}), (SECOND, {"private": True})):
        folder = seed_job(tmp_path, job, with_video=False, **extra)
        world.owners[job] = USER
        history_store.record_take(tmp_path, json.loads((folder / "job.json").read_text()), folder)
    with pytest.raises(history_report.Refused) as refused:
        history_report.Runner(tmp_path).request(USER, ENTRY)
    assert refused.value.status == 422


def test_a_take_dropped_during_the_run_voids_the_report(runner: history_report.Runner, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    real = sys.modules["part7.history_api"].ask

    def drop_then_answer(packed: dict, **kw: object) -> tuple:
        history_store.drop_take(runner.state, FIRST)
        return real(packed, **kw)

    monkeypatch.setattr(sys.modules["part7.history_api"], "ask", drop_then_answer)
    world.answers.append(ANSWER)
    runner.request(USER, ENTRY)
    assert runner.wait_idle(20)
    assert not list((runner.state / "history" / USER / ENTRY).glob("reports/*.json"))


def test_old_reports_are_pruned(runner: history_report.Runner, world: World) -> None:
    folder = history_store.reports_dir(runner.state, USER, ENTRY)
    for n in range(8):
        history_store.write_json(folder / f"old{n}.json", {"takes": []})
        __import__("os").utime(folder / f"old{n}.json", (n + 1, n + 1))
    world.answers.append(ANSWER)
    runner.request(USER, ENTRY)
    assert runner.wait_idle(20)
    assert len(list(folder.glob("*.json"))) == history_report.KEEP_REPORTS


def test_reason_is_short_and_redacted() -> None:
    error = RuntimeError("x")
    error.reason = "y" * 500  # type: ignore[attr-defined]
    assert len(history_report._reason(error)) == history_report.REASON_MAX
    assert history_report._reason(Exception()) == "Exception"


def test_a_report_made_with_video_is_dropped_when_the_consent_was_withdrawn_meanwhile(
        runner: history_report.Runner, world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # R9
    import sys

    history_store.set_consent(runner.state, USER, True, "video-v1")
    fake = sys.modules["part7.history_api"]
    real_ask = fake.ask

    def ask_then_withdraw(*args, **kwargs):
        out = real_ask(*args, **kwargs)
        history_store.set_consent(runner.state, USER, False, "video-v1")  # the student turns it off while the model works
        return out

    monkeypatch.setattr(fake, "ask", ask_then_withdraw)
    world.answers.append(ANSWER)
    runner.request(USER, ENTRY)
    assert runner.wait_idle(20)
    assert not list(history_store.reports_dir(runner.state, USER, ENTRY).glob("*.json"))  # nothing written


def test_global_daily_cap_refuses_with_a_clear_message(runner: history_report.Runner, world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # R7
    monkeypatch.setenv("SIMON7_HISTORY_GLOBAL_DAILY", "1")
    world.answers.extend([ANSWER, ANSWER])
    now = time.time()
    runner.request(USER, ENTRY, now=now)
    assert runner.wait_idle(20)
    assert history_report.global_runs_today(runner.state, now) == 1
    take = history_store.takes(runner.state, USER, ENTRY)[1]["analysis"]
    take.write_text(take.read_text().replace('"value": 77', '"value": 79', 1))  # a new key: not a cache hit
    with pytest.raises(history_report.Refused) as limit:
        runner.request(USER, ENTRY, now=now + 1)
    assert limit.value.status == 429 and limit.value.message == history_report.MSG_GLOBAL_LIMIT
    assert history_report.global_runs_today(runner.state, now + 2 * 86400) == 0
    monkeypatch.setenv("SIMON7_HISTORY_GLOBAL_DAILY", "x")
    assert history_report.global_daily_limit() == 50
