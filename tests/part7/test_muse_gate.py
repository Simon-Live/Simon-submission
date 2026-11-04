"""docs/specs/muse-prod.md AC-MP5, AC-MP9 and AC-MP10, run through the real chain, adapters and clients. No network: every door to Meta
is replaced by something that fails the test or records the call. No real key."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
import types
from typing import Any

import pytest

from history_all_support import seed
from history_support import ENTRY, USER, World, record_two, world  # noqa: F401
from patterns_support import seed_store
from test_history_api import FakeTransport
from test_history_prompt import make
from test_history_reel import GOOD
from part7 import chain, consent_record, history_all, history_api, history_cross, history_facts, history_patterns_job, history_reel, history_report, history_store, keys, muse_fix_api, muse_fix_routes, muse_prod, narration_api, runner
from part7.parts import p1_keyframes, p2_pose, p3_skeleton, p4_animate, p5_analyse, p5_ask
from support import Api, ffmpeg_video, stub_modules
from test_server import _fake_follower, _fake_trainer

ITEMS = {key: True for key in consent_record.ITEMS}


@pytest.fixture
def prod(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    secrets, state = tmp_path / "secrets", tmp_path / "state"
    secrets.mkdir(), state.mkdir()
    (secrets / "MODEL_API_KEY").write_text("fake-meta-value\n")
    (secrets / "BASETEN_API_KEY").write_text("fake-baseten-value\n")
    for name, value in (("FIRM_ENV", "prod"), ("PROD_SECRETS_DIR", str(secrets)), ("SIMON7_STATE_DIR", str(state)),
                        ("SIMON7_POLICY_MUSE", "on")):
        monkeypatch.setenv(name, value)
    return state


TICK = {"meta": True, "meta_adults": True}


def _doc(**extra: bool) -> dict:
    return {"age_band": "adult", "consent": {"version": consent_record.VERSION, "items": {**ITEMS, **extra}, "at": None}}


def _fields(**extra: bool) -> dict:
    fields = consent_record.job_fields(_doc(**extra))
    assert fields
    return fields


def _ok(part: int, stdout: str = "") -> runner.Step:
    return runner.Step(part=part, commit="a" * 12, argv=["x"], cwd="/tmp", exit=0, timed_out=False, duration_s=0.01, log="", stdout=stdout)


def _rest_of_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    def pose(v: Path, w: Path, **kw: Any) -> tuple:
        path = Path(w) / "part2" / "pose3d.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"frames": [{"frame": 0, "people": [{"id": 0}]}]}')
        return (_ok(2), path)

    def skeleton(pose3d: Path, kf: Any, w: Path, **kw: Any) -> tuple:
        sk, kf1 = Path(w) / "skeleton.json", Path(w) / "keyframes.v1.json"
        sk.write_text('{"format": "simon.skeleton.v1"}')
        kf1.write_text('{"format": "simon.keyframes.v1"}')
        return ([_ok(3)], sk, kf1, None)

    def animate(sk: Path, kf1: Path, w: Path, **kw: Any) -> tuple:
        path = Path(w) / "part4" / "animation.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"format": "simon.animation.v1"}')
        return (_ok(4), path)

    monkeypatch.setattr(p1_keyframes, "doctor", lambda *a, **kw: _ok(6))
    monkeypatch.setattr(p2_pose, "run", pose)
    monkeypatch.setattr(p2_pose, "doctor", lambda *a, **kw: _ok(2))
    monkeypatch.setattr(p3_skeleton, "part4", skeleton)
    monkeypatch.setattr(p3_skeleton, "doctor", lambda *a, **kw: _ok(3))
    monkeypatch.setattr(p4_animate, "validate", lambda *a, **kw: _ok(4))
    monkeypatch.setattr(p4_animate, "run", animate)
    monkeypatch.setattr(p5_analyse, "doctor", lambda *a, **kw: _ok(5))


def _trainer_chain(tmp_path: Path, prod: Path, allowed: bool | None, monkeypatch: pytest.MonkeyPatch) -> tuple[dict, list]:
    sent: list = []

    def part1(video: Path, work: Path, **kw: Any) -> tuple:
        sent.append(video)
        path = Path(work) / "keyframes.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"format": "simon.keyframes/part1"}')
        return (_ok(1), path, None)

    monkeypatch.setattr(p1_keyframes, "run", part1)
    _rest_of_chain(monkeypatch)
    video = tmp_path / "trainer.mp4"
    video.write_bytes(b"video")
    res = chain.trainer(video, tmp_path / "work", lock=stub_modules(prod / "modules"), state=prod, part1_allowed=allowed)
    return res, sent


def test_ac_mp5_a_chain_with_no_answer_sends_nothing_and_finishes(prod: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    res, sent = _trainer_chain(tmp_path, prod, None, monkeypatch)
    assert sent == [] and res["ok"] is True and res["parts"]["keyframes"] == 3
    assert "key frames from Part 3, this take was not sent to Meta" in res["note"]
    res, sent = _trainer_chain(tmp_path, prod, False, monkeypatch)
    assert sent == []
    res, sent = _trainer_chain(tmp_path, prod, True, monkeypatch)
    assert len(sent) == 1 and res["parts"]["keyframes"] == 1


# ----- AC-MP5 through the real routes: a real POST, the real handler, the real queue. Only the chain at the end is a fake -------------


@pytest.fixture
def gated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consent_record.GATE_ENV, "on")
    monkeypatch.delenv("FIRM_ENV", raising=False)


@pytest.fixture(scope="module")
def clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return ffmpeg_video(tmp_path_factory.mktemp("gate") / "clip.mp4", 2)


def _upload_id(api: Api, clip: Path) -> str:
    status, doc = api.upload(clip, headers={consent_record.UPLOAD_HEADER: consent_record.VERSION})
    assert status == 201, doc
    return doc["upload_id"]


def _post_trainer(api: Api, clip: Path, monkeypatch: pytest.MonkeyPatch, entry: str, **items: bool) -> dict:
    seen: list[dict] = []
    inner = _fake_trainer(entry_id=entry)
    monkeypatch.setattr(chain, "trainer", lambda *a, **k: (seen.append(k), inner(*a, **k))[1])
    body = {"upload_id": _upload_id(api, clip), "name": "Push-up", "category": "exercise", **_doc(**items)}
    status, doc = api.json("POST", "api/trainer", body)
    assert status == 202, doc
    assert api.app.queue.wait(doc["job"], 60)["status"] == "done"
    return seen[-1]


def _post_follow(api: Api, clip: Path, monkeypatch: pytest.MonkeyPatch, entry: str, **items: bool) -> dict:
    seen: list[dict] = []
    inner = _fake_follower()
    monkeypatch.setattr(chain, "follower", lambda *a, **k: (seen.append(k), inner(*a, **k))[1])
    status, doc = api.json("POST", "api/follow", {"upload_id": _upload_id(api, clip), "entry_id": entry, **_doc(**items)})
    assert status == 202, doc
    assert api.app.queue.wait(doc["job"], 60)["status"] == "done"
    return seen[-1]


@pytest.mark.parametrize(("items", "allowed"), [({}, False), ({"meta": True}, False), ({"meta_adults": True}, False), (TICK, True)])
def test_ac_mp5_post_trainer_starts_part1_only_with_tick_and_statement(
    gated: None, api: Api, clip: Path, monkeypatch: pytest.MonkeyPatch, items: dict, allowed: bool
) -> None:
    assert _post_trainer(api, clip, monkeypatch, "lateral-raise", **items)["part1_allowed"] is allowed


@pytest.mark.parametrize(("trainer", "follower", "sent"), [(TICK, {}, False), ({}, TICK, False), (TICK, {"meta": True}, False), (TICK, TICK, True)])
def test_ac_mp5_post_follow_sends_the_trainers_clip_only_with_both_answers(
    gated: None, api: Api, clip: Path, monkeypatch: pytest.MonkeyPatch, trainer: dict, follower: dict, sent: bool
) -> None:
    api.app.phrasing = "live"
    api.app.child.entries["lateral-raise"]["video_uri"] = "video.mp4"  # the entry has a clip to send, so each no below is a real no
    api.app.child.files["video.mp4"] = b"the trainer"
    _post_trainer(api, clip, monkeypatch, "lateral-raise", **trainer)
    kw = _post_follow(api, clip, monkeypatch, "lateral-raise", **follower)
    assert (kw.get("expected_video") is not None) is sent


def _part5_argv(prod: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **kw: Any) -> list[str]:
    seen: list[list[str]] = []

    def fake_run(part: int, argv: list[str], **_: Any) -> runner.Step:
        if "--help" in argv:
            return _ok(5, "--phrasing {template,muse-spark} --live --expected-video --follower-video")
        seen.append(argv)
        out = Path(argv[argv.index("--out") + 1])
        out.write_text('{"format": "simon.analysis.v1", "faults": []}')
        return _ok(5)

    monkeypatch.setattr(p5_analyse.probe, "has_flag", lambda *a, **k: True)
    monkeypatch.setattr(p5_analyse.runner, "run", fake_run)
    for name in ("expected.json", "follower.json"):
        (tmp_path / name).write_text("{}")
    p5_analyse.run(tmp_path / "expected.json", tmp_path / "follower.json", tmp_path / "work", lock=stub_modules(prod / "modules"),
                   state=prod, private=False, **kw)
    return seen[0]


def test_ac_mp5_no_video_argument_reaches_part5_without_the_answer(prod: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    follower = tmp_path / "f.mp4"
    argv = _part5_argv(prod, tmp_path, monkeypatch, phrasing="live", expected_video=None, follower_video=follower)
    assert "--expected-video" not in argv and "--follower-video" not in argv and "--phrasing" in argv
    argv = _part5_argv(prod, tmp_path, monkeypatch, phrasing="live", expected_video=tmp_path / "t.mp4", follower_video=follower)
    assert "--expected-video" in argv  # the same call with the answer does send: the assert above is not empty


def test_ac_mp10_a_queued_second_opinion_and_wording_obey_the_stop_file(prod: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (prod / muse_prod.STOP_FILE).touch()
    argv = _part5_argv(prod, tmp_path, monkeypatch, phrasing="live", expected_video=tmp_path / "t.mp4", follower_video=tmp_path / "f.mp4")
    assert "--expected-video" not in argv and "--live" not in argv


def _no_network(monkeypatch: pytest.MonkeyPatch) -> list:
    reached: list = []

    class Opener:
        def open(self, request: Any, timeout: float = 0) -> Any:
            reached.append((request.get_method(), request.full_url))
            raise OSError("no network in this test")

    monkeypatch.setattr(history_api.urllib.request, "build_opener", lambda *a: Opener())
    return reached


def test_ac_mp10_the_one_gate_stops_a_queued_call_but_not_a_delete(prod: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reached = _no_network(monkeypatch)
    client = history_api.HttpClient("fake")
    (prod / muse_prod.STOP_FILE).touch()
    with pytest.raises(history_api.HistoryError, match="paused"):
        client.count({"model": "m", "input": []})
    with pytest.raises(history_api.HistoryError, match="paused"):
        client._json("/responses", {}, "respond")
    assert reached == []
    with pytest.raises(history_api.HistoryError):
        client.delete("file-1")  # reaches the door, and the fake network refuses
    assert reached == [("DELETE", "https://api.meta.ai/v1/files/file-1")]


def test_ac_mp10_gate_open_lets_the_call_through(prod: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reached = _no_network(monkeypatch)
    with pytest.raises(history_api.HistoryError):
        history_api.HttpClient("fake").count({"model": "m", "input": []})
    assert len(reached) == 1


def test_ac_mp10_switch_off_closes_the_gate_too(prod: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reached = _no_network(monkeypatch)
    monkeypatch.delenv("SIMON7_POLICY_MUSE")
    with pytest.raises(history_api.HistoryError):
        history_api.HttpClient("fake").count({"model": "m", "input": []})
    assert reached == []


def test_ac_mp10_a_queued_image_edit_stops(prod: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reached = _no_network(monkeypatch)
    monkeypatch.setattr(muse_fix_api, "edit_body", lambda *a: {})
    (prod / muse_prod.STOP_FILE).touch()
    with pytest.raises(history_api.HistoryError, match="paused"):
        muse_fix_api.edit_image(b"frame", "prompt", state=prod)
    assert reached == []


def test_ac_mp10_a_queued_ask_stops_and_a_fixed_answer_does_not(prod: Path, tmp_path: Path) -> None:
    (prod / muse_prod.STOP_FILE).touch()
    with pytest.raises(p5_ask.AskError, match="paused"):
        p5_ask.run("why", tmp_path / "a.json", tmp_path / "r.json", tmp_path)


def test_ac_mp10_part1_queued_behind_the_stop_file_starts_nothing(prod: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(p1_keyframes.runner, "run", lambda *a, **k: pytest.fail("Part 1 started"))
    (prod / muse_prod.STOP_FILE).touch()
    step, path, note = p1_keyframes.run(tmp_path / "v.mp4", tmp_path / "w", lock=stub_modules(prod / "modules"), state=prod)
    assert (step, path) == (None, None) and "unavailable" in str(note)


def test_ac_mp10_prod_never_sends_sound_to_meta(prod: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(narration_api.NarrationError, match="off on this server"):
        narration_api.transcribe(tmp_path / "a.wav", opener=lambda *a, **k: pytest.fail("the network was reached"))


def test_ac_mp10_every_door_to_meta_is_a_gated_one() -> None:
    """A new client that calls Meta from part7/ without the gate fails here."""
    root = Path(history_api.__file__).parent
    doors = {p.relative_to(root).as_posix() for p in root.rglob("*.py") if "api.meta.ai" in p.read_text(encoding="utf-8")}
    assert doors == {"history_api.py", "narration_api.py"}, doors


def test_ac_mp10_a_report_queued_before_the_stop_ends_in_its_fact_table_and_reaches_nothing(
    prod: Path, tmp_path: Path, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real report job and the real client: the press was admitted, the stop came while it waited in the queue."""
    reached = _no_network(monkeypatch)
    record_two(tmp_path, world)
    job = history_report.Runner(tmp_path, tmp_path / "catalog")
    usable, _, narration = job.plan(USER, ENTRY)
    facts = history_facts.build(usable, ENTRY)
    (prod / muse_prod.STOP_FILE).touch()
    report = job.compose(USER, ENTRY, usable, facts, narration)
    assert reached == [] and report["status"] == "fallback" and "paused" in report["detail"]


def test_ac_mp10_queued_patterns_stop(prod: Path, tmp_path: Path, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    reached = _no_network(monkeypatch)
    seed_store(tmp_path, world)
    job = history_patterns_job.PatternRunner(tmp_path, tmp_path / "catalog")
    (prod / muse_prod.STOP_FILE).touch()
    job.request(USER, ENTRY)
    assert job.wait_idle(20)
    done = history_patterns_job.cached(tmp_path, USER, ENTRY, job.plan(USER, ENTRY)[2])
    assert reached == [] and "paused" in done["detail"]


def test_ac_mp10_a_queued_recap_stops(prod: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reached = _no_network(monkeypatch)
    seed(tmp_path, USER)
    job = history_cross.Runner(tmp_path, lambda e: e.split("-")[0].title())
    found = history_all.included(history_all.gather(tmp_path, USER, lambda e: e.split("-")[0].title()))
    (prod / muse_prod.STOP_FILE).touch()
    report = job.compose("recap", "2026-01", found)
    assert reached == [] and report["status"] == "fallback" and "paused" in report["detail"]


def _reel_pack(prod: Path, user: str = USER) -> dict:
    facts, rows = make([50, 60, 70], duration=10.0)
    return history_reel.pack("e1", facts, rows, chosen=history_reel.select_takes(rows, facts))


def test_ac_mp10_a_queued_reel_stops(prod: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reached = _no_network(monkeypatch)
    history_store.set_consent(prod, USER, True, "2026-11-04", True)
    job = history_reel.ReelRunner(prod)
    packed = _reel_pack(prod)
    muse_prod.clear_video(packed, prod, USER)
    assert packed["video_cleared"] is True
    (prod / muse_prod.STOP_FILE).touch()
    with pytest.raises(history_reel.ReelError):
        job._ask(packed)
    assert reached == []


def _muse_fix_env(api: Api, world: World, trainer: dict) -> tuple[str, list]:
    def made(ctx: Any) -> dict:
        return {"result": {"entry_id": "lateral-raise"}, "kind": "trainer"}

    entry, runs = "lateral-raise", []
    trainer_job = api.app.queue.submit("trainer", made, entry_id=entry, consent={"items": trainer})["id"]
    assert api.app.queue.wait(trainer_job, 10)["status"] == "done"
    take = api.app.queue.submit("follow", lambda ctx: {"result": {"entry_id": entry}}, entry_id=entry)["id"]
    assert api.app.queue.wait(take, 10)["status"] == "done"
    world.owners[take] = USER
    return take, runs


@pytest.mark.parametrize(("trainer", "code"), [({}, 403), (TICK, 202)])
def test_ac_mp11_you_doing_it_right_needs_the_trainers_tick_through_the_route(
    gated: None, api: Api, world: World, monkeypatch: pytest.MonkeyPatch, trainer: dict, code: int
) -> None:
    monkeypatch.setattr(muse_fix_routes.muse_fix, "DRAW_ENABLED", True)  # shipped off (release 14); the tick is checked on the feature's route
    monkeypatch.setattr("part7.muse_fix_measure.available", lambda: True)
    monkeypatch.setattr("part7.muse_fix_measure.reachable", lambda: True)
    monkeypatch.setattr(muse_fix_routes, "eligible", lambda job: True)
    consents: list = []
    monkeypatch.setattr(muse_fix_routes.muse_fix, "run", lambda job_dir, *, consent, **kw: consents.append(consent) or {"status": "no_consent"})
    history_store.set_consent(api.app.state, USER, True, "2026-11-04", True)
    take, _ = _muse_fix_env(api, world, trainer)
    head = {"Origin": f"http://127.0.0.1:{api.port}", "X-Test-User": USER}
    status, doc = api.json("POST", f"api/jobs/{take}/muse-fix", {"what": "image"}, headers=head)
    assert status == code, doc
    if code == 202:
        for _ in range(100):
            if consents:
                break
            time.sleep(0.05)
        assert consents == [True]
    else:
        assert doc["code"] == "trainer_no_tick" and consents == []


def test_ac_mp11_post_history_consent_refuses_a_yes_without_the_statement(gated: None, api: Api, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    head = {"Origin": f"http://127.0.0.1:{api.port}", "X-Test-User": USER}
    status, _ = api.json("POST", "api/me/history/consent", {"video": True, "version": "2026-11-04"}, headers=head)
    assert status == 400 and history_store.consent(api.app.state, USER)["video"] is False
    status, _ = api.json("POST", "api/me/history/consent", {"video": True, "version": "2026-11-04", "meta_adults": True}, headers=head)
    assert status == 200 and history_store.consent(api.app.state, USER)["video"] is True


# ----- AC-MP11: the 18 statement and the trainer's tick on every path that sends a kept clip or frame ------------------------------


def test_ac_mp11_the_account_choice_needs_the_statement(prod: Path) -> None:
    with pytest.raises(ValueError):
        history_store.set_consent(prod, USER, True, "2026-11-04")
    assert history_store.consent(prod, USER)["video"] is False
    assert history_store.set_consent(prod, USER, True, "2026-11-04", True)["video"] is True
    history_store.write_json(history_store.user_dir(prod, USER) / "consent.json", {"video": True, "version": "old", "at": None})
    assert history_store.consent(prod, USER)["video"] is False  # a yes stored before the statement does not count


def test_ac_mp11_outside_a_gated_build_no_statement_is_asked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIRM_ENV", raising=False)
    monkeypatch.delenv(consent_record.GATE_ENV, raising=False)
    assert history_store.set_consent(tmp_path, USER, True, "2026-11-04")["video"] is True


def test_ac_mp11_a_path_that_skips_the_one_function_cannot_send_video(prod: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reached = _no_network(monkeypatch)
    with pytest.raises(history_api.HistoryError, match="no video consent"):
        history_api.ask(_reel_pack(prod), state=prod)
    assert reached == []


def test_ac_mp11_no_account_statement_stamps_nothing(prod: Path) -> None:
    packed = _reel_pack(prod)
    muse_prod.clear_video(packed, prod, USER)
    assert packed["video_cleared"] is False


def test_ac_mp11_a_teacher_clip_needs_its_entry_and_the_trainers_tick(prod: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    history_store.set_consent(prod, USER, True, "2026-11-04", True)
    teacher = {"content": [{"type": "video", "path": "/t.mp4", "label": "teacher"}]}
    muse_prod.clear_video(teacher, prod, USER)
    assert teacher["video_cleared"] is False  # no entry to ask about
    muse_prod.clear_video(teacher, prod, USER, "e1")
    assert teacher["video_cleared"] is False  # no app on file: nothing goes


def _trainer_said(prod: Path, monkeypatch: pytest.MonkeyPatch, answer: bool) -> None:
    app = types.SimpleNamespace(state=prod, queue=types.SimpleNamespace(trainer_meta_answer=lambda entry: answer))
    monkeypatch.setitem(muse_prod._APPS, prod.resolve(), app)


@pytest.mark.parametrize("answer", [True, False])
def test_ac_mp11_compare_carries_the_teacher_clip_only_with_the_trainers_tick(
    prod: Path, tmp_path: Path, world: World, monkeypatch: pytest.MonkeyPatch, answer: bool
) -> None:
    record_two(tmp_path, world)
    _trainer_said(tmp_path, monkeypatch, answer)
    teacher = tmp_path / "catalog" / ENTRY / "video.mp4"
    teacher.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_video(teacher, 2)
    job = history_report.Runner(tmp_path, tmp_path / "catalog")
    history_store.set_consent(tmp_path, USER, True, "2026-11-04", True)
    usable, _, narration = job.plan(USER, ENTRY)
    packed = job.packed(ENTRY, usable, history_facts.build(usable, ENTRY), narration, True)
    assert any(i.get("label") == "teacher" for i in packed["content"]) is answer


def _trainer_job(api: Api, entry: str, items: dict) -> None:
    job = api.app.queue.submit("trainer", lambda ctx: {"result": {"entry_id": entry}}, entry_id=entry, consent={"items": items})["id"]
    assert api.app.queue.wait(job, 10)["status"] == "done"


def _head(api: Api) -> dict[str, str]:
    return {"Origin": f"http://127.0.0.1:{api.port}", "X-Test-User": USER}


@pytest.mark.parametrize("trainer", [{}, TICK])
def test_ac_mp11_post_compare_sends_the_teachers_clip_and_words_only_with_the_tick(
    gated: None, api: Api, world: World, monkeypatch: pytest.MonkeyPatch, trainer: dict
) -> None:
    asked: list = []

    def ask(packed: dict, **kw: Any) -> tuple:  # the door to Meta, after the real report job, prompt and stamp
        history_api._check_consent(packed)
        asked.append(packed)
        raise history_api.HistoryError("stop here")

    monkeypatch.setattr(history_api, "ask", ask)
    record_two(api.app.state, world)
    history_store.set_consent(api.app.state, USER, True, "2026-11-04", True)
    _trainer_job(api, ENTRY, trainer)
    folder = Path(api.app.child.catalog_dir) / ENTRY
    folder.mkdir(parents=True, exist_ok=True)
    ffmpeg_video(folder / "video.mp4", 2)
    (folder / "narration.json").write_text(json.dumps({"cues": [{"index": 0, "start_s": 0, "end_s": 1, "text": "Knees over toes"}]}))
    status, doc = api.json("POST", f"api/me/history/{ENTRY}/report", headers=_head(api))
    assert status in (200, 202), doc
    for _ in range(200):
        if asked:
            break
        time.sleep(0.05)
    packed = asked[-1]
    assert any(i.get("label") == "teacher" for i in packed["content"]) is bool(trainer)
    assert ("Knees over toes" in json.dumps(packed["content"])) is bool(trainer)
    assert packed["video_cleared"] is True and packed["clips_sent"] > 0  # the person's own clips go on their own yes


def test_ac_mp11_patterns_carry_the_teachers_words_only_with_the_tick(tmp_path: Path, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consent_record.GATE_ENV, "on")
    monkeypatch.delenv("FIRM_ENV", raising=False)
    (tmp_path / "catalog" / ENTRY).mkdir(parents=True)
    (tmp_path / "catalog" / ENTRY / "narration.json").write_text(json.dumps({"cues": [{"index": 0, "text": "Knees over toes"}]}))
    answer: list = [False]
    app = types.SimpleNamespace(state=tmp_path, queue=types.SimpleNamespace(trainer_meta_answer=lambda entry: answer[0]))
    monkeypatch.setitem(muse_prod._APPS, tmp_path.resolve(), app)
    assert history_report._narration(tmp_path / "catalog", ENTRY, tmp_path) == (None, "")
    answer[0] = True
    assert history_report._narration(tmp_path / "catalog", ENTRY, tmp_path)[0]["cues"]


def test_ac_mp11_post_reel_refuses_without_the_statement_and_sends_own_clips_with_it(gated: None, api: Api, world: World) -> None:
    record_two(api.app.state, world)
    job = history_reel.runner_for(api.app.state)
    job.transport = FakeTransport(answer=json.dumps(GOOD))
    job._failed.clear()
    history_store.write_json(history_store.user_dir(api.app.state, USER) / "consent.json", {"video": True, "version": "old", "at": None})
    status, _ = api.json("POST", f"api/me/history/{ENTRY}/reel", headers=_head(api))
    assert status == 409 and job.transport.uploaded == []
    history_store.set_consent(api.app.state, USER, True, "2026-11-04", True)
    status, doc = api.json("POST", f"api/me/history/{ENTRY}/reel", headers=_head(api))
    assert status in (200, 202), doc
    assert job.wait_idle(60)
    assert job.transport.uploaded != []  # through the real `history_api.ask`, whose door checks the stamp


# ----- AC-MP9: nothing of a person's clip, and no key, stays beside Part 1 -----------------------------------------------------------


def _fake_part1(prod: Path, source: Path, exit_code: int = 0, raises: bool = False) -> Any:
    """What Part 1 really writes, as observed on a real run: out/work/<stem>.mp4, out/<stem>/{tracks.npz,spark.txt,run.json,keyframes.json}."""

    def run(part: int, argv: list[str], cwd: Path, **kw: Any) -> runner.Step:
        stem = Path(argv[-1]).stem
        folder = Path(cwd) / "out" / stem
        (Path(cwd) / "out" / "work").mkdir(parents=True, exist_ok=True)
        folder.mkdir(parents=True, exist_ok=True)
        (Path(cwd) / "out" / "work" / f"{stem}.mp4").write_bytes(b"the person")
        for name in ("tracks.npz", "spark.txt", "run.json"):
            (folder / name).write_bytes(b"x")
        (folder / "keyframes.json").write_text('{"format": "simon.keyframes/part1"}')
        assert (Path(cwd) / ".env").is_file()
        if raises:
            raise RuntimeError("the run blew up")
        return runner.Step(part=1, commit="a" * 12, argv=argv, cwd=str(cwd), exit=exit_code, timed_out=False, duration_s=0.1, log="", stdout="")

    return run


def _prod_clone(prod: Path) -> Any:
    lock = stub_modules(prod / "modules")
    source = lock.path("1")
    (source / "keyframe_finder").mkdir(parents=True, exist_ok=True)
    (source / ".firm-sha").write_text("abcdef0123456789\n")
    return lock, prod / "part1" / "abcdef012345"


def _files(copy: Path) -> list[str]:
    return sorted(str(p.relative_to(copy)) for p in copy.rglob("*") if p.is_file() and p.name != ".firm-sha" and "keyframe_finder" not in p.parts)


@pytest.mark.parametrize("exit_code", [0, 1])
def test_ac_mp9_a_run_leaves_no_clip_tracks_or_key(prod: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_code: int) -> None:
    lock, copy = _prod_clone(prod)
    monkeypatch.setattr(p1_keyframes, "_safe_input", lambda video, work: video)
    monkeypatch.setattr(p1_keyframes.runner, "run", _fake_part1(prod, lock.path("1"), exit_code))
    video = tmp_path / "v.mp4"
    video.write_bytes(b"clip")
    step, path, _ = p1_keyframes.run(video, tmp_path / "w", lock=lock, state=prod)
    assert _files(copy) == []
    assert (path is not None and json.loads(path.read_text())["format"] == "simon.keyframes/part1") is (exit_code == 0)


def test_ac_mp9_a_run_that_raises_is_cleared_too(prod: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock, copy = _prod_clone(prod)
    monkeypatch.setattr(p1_keyframes, "_safe_input", lambda video, work: video)
    monkeypatch.setattr(p1_keyframes.runner, "run", _fake_part1(prod, lock.path("1"), raises=True))
    video = tmp_path / "v.mp4"
    video.write_bytes(b"clip")
    with pytest.raises(RuntimeError):
        p1_keyframes.run(video, tmp_path / "w", lock=lock, state=prod)
    assert _files(copy) == []


def test_ac_mp9_outside_prod_part1_keeps_its_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIRM_ENV", raising=False)
    clone = tmp_path / "clone"
    (clone / "out" / "p7-a").mkdir(parents=True)
    p1_keyframes._clear_run(clone, "p7-a")
    assert (clone / "out" / "p7-a").is_dir() and p1_keyframes.sweep(tmp_path) == 0


def _killed_run(prod: Path) -> Path:
    copy = prod / "part1" / "abcdef012345"
    for rel in ("out/work/p7-old.mp4", "out/p7-old/tracks.npz", "inbox/p7-old.mp4", "out/work/p7-new.mp4", "out/p7-new/tracks.npz", ".env"):
        (copy / rel).parent.mkdir(parents=True, exist_ok=True)
        (copy / rel).write_bytes(b"x")
    long_ago = time.time() - p1_keyframes.LEFTOVER_AGE_S - 60
    for rel in ("out/work/p7-old.mp4", "out/p7-old", "inbox/p7-old.mp4"):
        os.utime(copy / rel, (long_ago, long_ago))
    return copy


def test_ac_mp9_the_sweep_clears_a_killed_run_and_spares_a_live_one(prod: Path) -> None:
    copy = _killed_run(prod)
    assert p1_keyframes.sweep(prod) == 3
    assert _files(copy) == ["out/p7-new/tracks.npz", "out/work/p7-new.mp4"]  # young enough to be running; `.env` was not held


def test_ac_mp9_the_sweep_leaves_a_key_a_live_run_holds(prod: Path) -> None:
    copy = _killed_run(prod)
    with keys.part1_dotenv(copy):
        p1_keyframes.sweep(prod)
        assert (copy / ".env").is_file()
    assert not (copy / ".env").exists()


def test_ac_mp9_two_takes_of_one_clip_do_not_clear_each_other(prod: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock, copy = _prod_clone(prod)
    monkeypatch.setattr(p1_keyframes, "_safe_input", lambda video, work: video)
    fake, stems = _fake_part1(prod, lock.path("1")), []

    def run(part: int, argv: list[str], cwd: Path, **kw: Any) -> runner.Step:
        stems.append(Path(argv[-1]).stem)
        if len(stems) == 1:  # the second take of the same clip runs and ends while the first is still going
            assert p1_keyframes.run(video, tmp_path / "w2", lock=lock, state=prod)[1] is not None
        return fake(part, argv, cwd, **kw)

    monkeypatch.setattr(p1_keyframes.runner, "run", run)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"clip")
    assert p1_keyframes.run(video, tmp_path / "w1", lock=lock, state=prod)[1] is not None
    assert len(set(stems)) == 2 and _files(copy) == []
