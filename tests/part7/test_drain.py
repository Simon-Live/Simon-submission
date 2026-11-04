"""Graceful drain and resume of queued jobs on a restart (TICKET-115; staging.md "Restart", processor.md "Restart")."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Iterator

import pytest

from auth_support import authenv, get, post, sign_in  # noqa: F401
from part7 import auth, avatar_jobs as aj, chain, config, jobs, model_import, own_clients, selfheal, server
from part7.jobs import JobQueue
from support import Api, FakeChild, make_lock
from test_avatar_jobs import env, make_model, status  # noqa: F401  (env is the avatar job fixture)
from test_server import _fake_follower, _fake_trainer, _upload


def _gate() -> tuple[threading.Event, threading.Event, Any]:
    """A job function that says it started, then waits to be released."""
    started, release = threading.Event(), threading.Event()

    def fn(ctx: Any) -> dict[str, Any]:
        started.set()
        release.wait(30)
        return {}

    return started, release, fn


def test_drain_waits_for_a_running_job_and_logs_it(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    q = JobQueue(tmp_path, workers=1)
    started, release, fn = _gate()
    job = q.submit("follow", fn)["id"]
    assert started.wait(10)
    threading.Timer(0.5, release.set).start()
    t0 = time.monotonic()
    assert q.drain(20, poll_s=0.1) == 0
    assert time.monotonic() - t0 >= 0.4
    assert q.get(job)["status"] == "done"
    assert "drain: waiting for 1 running job(s)" in caplog.text
    q.close()


def test_drain_refuses_new_jobs_and_does_not_start_queued_ones(tmp_path: Path) -> None:
    q = JobQueue(tmp_path, workers=1)
    started, release, fn = _gate()
    q.submit("follow", fn)
    assert started.wait(10)
    waiting = q.submit("follow", lambda ctx: {})["id"]
    done = threading.Thread(target=q.drain, args=(20,), kwargs={"poll_s": 0.1})
    done.start()
    deadline = time.monotonic() + 5
    while not q.draining and time.monotonic() < deadline:
        time.sleep(0.01)
    with pytest.raises(jobs.DrainingError):
        q.submit("follow", lambda ctx: {})
    release.set()
    done.join(10)
    time.sleep(0.2)
    assert q.get(waiting)["status"] == "queued"  # not started during the drain
    q.close()


def test_a_job_running_past_the_max_is_failed_with_a_reason_and_an_anomaly(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    q = JobQueue(tmp_path, workers=1)
    started, release, fn = _gate()
    job = q.submit("follow", fn)["id"]
    assert started.wait(10)
    assert q.drain(0.3, poll_s=0.1) == 1
    got = q.get(job)
    assert got["status"] == "failed" and got["reason"] == jobs.DRAIN_CUT_REASON
    assert f"ANOMALY drain_cut_off job={job}" in caplog.text
    on_disk = json.loads((tmp_path / "jobs" / job / "job.json").read_text())
    assert on_disk["status"] == "failed"
    release.set()
    q.close()


def test_a_queued_job_with_a_resume_spec_stays_queued_and_runs_after_the_restart(tmp_path: Path) -> None:
    first = JobQueue(tmp_path, start=False)
    job = first.submit("follow", lambda ctx: {}, _resume={"v": 1})["id"]
    plain = first.submit("follow", lambda ctx: {})["id"]
    first.close()
    again = JobQueue(tmp_path, workers=1)
    assert again.get(job)["status"] == "queued"
    assert again.get(plain)["status"] == "failed" and again.get(plain)["reason"] == "the server restarted"
    ran = threading.Event()
    assert again.resume(lambda record: (lambda ctx: ran.set() or {})) == 1
    assert again.wait(job, 10)["status"] == "done" and ran.is_set()
    assert "_resume" not in again.get(job)  # the spec is not public
    again.close()


def test_a_queued_job_that_cannot_be_rebuilt_is_failed(tmp_path: Path) -> None:
    first = JobQueue(tmp_path, start=False)
    job = first.submit("follow", lambda ctx: {}, _resume={"v": 1})["id"]
    first.close()
    again = JobQueue(tmp_path, start=False)
    assert again.resume(lambda record: None) == 0
    assert again.get(job)["status"] == "failed" and again.get(job)["reason"] == "the server restarted"


def test_a_running_job_cut_off_by_a_stop_is_still_failed_on_start(tmp_path: Path) -> None:
    q = JobQueue(tmp_path, workers=1)
    started, release, fn = _gate()
    job = q.submit("follow", fn, _resume={"v": 1})["id"]
    assert started.wait(10)
    again = JobQueue(tmp_path, start=False)  # the record on disk says running
    assert again.get(job)["status"] == "failed"
    release.set()
    q.close()


def test_the_drain_limit_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIMON7_DRAIN_MAX_S", raising=False)
    assert config.drain_max_s() == 600
    monkeypatch.setenv("SIMON7_DRAIN_MAX_S", "45")
    assert config.drain_max_s() == 45
    monkeypatch.setenv("SIMON7_DRAIN_MAX_S", "x")
    assert config.drain_max_s() == 600


def test_new_job_routes_answer_503_with_retry_after_while_draining(api: Api, tiny_mp4: Path) -> None:
    api.app.queue.drain(0)
    status, headers, body = api.request("POST", "api/uploads", tiny_mp4.read_bytes(), {"Content-Type": "video/mp4"})
    assert status == 503 and headers["retry-after"] == "60"
    assert json.loads(body)["message"] == "Restarting shortly, try again in a minute."
    status, headers, _ = api.request("POST", "api/follow", b"{}", {"Content-Type": "application/json"})
    assert status == 503 and "retry-after" in headers
    status, doc = api.json("GET", "api/health")
    assert status == 200 and doc["draining"] is True  # reads, and job polling, keep working
    assert api.request("POST", "api/client-log", b"{}", {"Content-Type": "application/json"})[0] != 503


# ---------------------------------------------------------------- model jobs (TICKET-306)
def _model_running(env: Any, monkeypatch: pytest.MonkeyPatch, mode: str, name: str) -> Path:
    """An avatar job whose Part 2 stand-in has started (`converting`), on a server that then begins to drain."""
    monkeypatch.setattr(aj, "_draining", False)  # restored after the test: the drain flag is per process
    monkeypatch.setenv("FAKE_MODE", mode)
    monkeypatch.setenv("FAKE_SLOW", "1.0")
    d, files = make_model(env, name=name * 32)
    aj.submit_images(d, files, "visitor-1")
    deadline = time.monotonic() + 10
    while not (status(d)["status"] == "converting" and env.calls()) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert status(d)["status"] == "converting"
    model_import.begin_drain()
    return d


def test_drain_waits_for_a_running_model_job_and_logs_it(
    env: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    d = _model_running(env, monkeypatch, "slow", "m")
    later, files = make_model(env, name="n" * 32)
    aj.submit_images(later, files, "visitor-1")  # queued while draining: on disk only, for the next server
    assert model_import.drain(time.monotonic() + 20, poll_s=0.05) == 0
    assert status(d)["status"] == "ready"
    assert "drain: waiting for 1 model job(s)" in caplog.text and "drain_cut_off" not in caplog.text
    time.sleep(0.2)
    assert status(later)["status"] == "queued" and len(env.calls()) == 1  # never started here


def test_drain_cuts_off_a_model_job_at_the_max_and_reports_it(
    env: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    d = _model_running(env, monkeypatch, "hang", "h")
    t0 = time.monotonic()
    assert model_import.drain(time.monotonic() + 0.3, poll_s=0.05) == 1
    assert time.monotonic() - t0 < 5
    assert status(d)["status"] == "failed" and status(d)["error"] == aj.STUCK_MESSAGE
    assert f"ANOMALY drain_cut_off job={d.name}" in caplog.text and "drain: models done, 1 model job(s) cut off" in caplog.text
    assert aj.wait_idle(10)  # the Part 2 group was killed, not left to run for its 60 s
    assert status(d)["status"] == "failed"  # the worker wrote nothing after the cut


def _fake_queue(calls: list[Any], root: Path) -> Any:
    return type("Q", (), {"root": root / "jobs", "drain": lambda self, max_s: calls.append(("takes", max_s)) or 0})()


def test_sigterm_drain_stops_model_jobs_first_and_shares_one_max(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[Any] = []
    monkeypatch.setenv("SIMON7_DRAIN_MAX_S", "50")
    monkeypatch.setattr(model_import, "begin_drain", lambda: calls.append("begin"))
    monkeypatch.setattr(model_import, "drain", lambda deadline: calls.append(("models", deadline - time.monotonic())) or 1)
    monkeypatch.setattr(own_clients, "stop_all", lambda state, parent=None: calls.append("own") or 0)
    stopped = type("S", (), {"shutdown": lambda self: calls.append("shutdown")})()
    server._drain_then_stop(_fake_queue(calls, tmp_path), stopped)
    assert calls[0] == "begin" and calls[1] == ("takes", 50.0) and calls[2] == "own" and calls[4] == "shutdown"
    assert calls[3][0] == "models" and 45 < calls[3][1] <= 50


def test_sigterm_drain_ends_this_servers_own_route_clients(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """BYOK-M6: right after the take drain, the launchers this server started end; another server's stay."""
    calls: list[Any] = []
    stops: list[tuple[Path, int | None]] = []
    monkeypatch.setattr(model_import, "begin_drain", lambda: None)
    monkeypatch.setattr(model_import, "drain", lambda deadline: 0)
    monkeypatch.setattr(selfheal, "record", lambda *a, **k: None)
    monkeypatch.setattr(own_clients, "stop_all", lambda state, parent=None: stops.append((Path(state), parent)) or 0)
    stopped = type("S", (), {"shutdown": lambda self: calls.append("shutdown")})()
    server._drain_then_stop(_fake_queue(calls, tmp_path), stopped)
    assert stops == [(tmp_path, os.getpid())]
    assert calls == [("takes", config.drain_max_s()), "shutdown"]


def test_a_model_upload_answers_503_while_draining(api: Api) -> None:
    api.app.queue.drain(0)
    status_code, headers, body = api.request("POST", "api/models?name=x&licence=CC0", b"glTF", {"Content-Type": "model/gltf-binary"})
    assert status_code == 503 and headers["retry-after"] == "60"
    assert json.loads(body)["message"] == jobs.DRAINING_MESSAGE


@pytest.fixture()
def two_apps(tmp_path: Path, state_dir: Path) -> Iterator[Any]:
    created: list[Any] = []

    def make(start: bool) -> Api:
        child = FakeChild(tmp_path / "catalog")
        app = server.build_app(state_dir, "/simon-part-7/", child=child, lock=make_lock(), phrasing="template",
                               start_queue=start)
        http = server.make_server(app)
        threading.Thread(target=http.serve_forever, daemon=True).start()
        created.append((app, http, child))
        return Api(app, http)

    yield make
    for app, http, child in created:
        http.shutdown()
        http.server_close()
        app.queue.close()
        child.close()


def test_a_trainer_job_queued_at_a_stop_runs_after_the_restart(
    two_apps: Any, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chain, "trainer", _fake_trainer("squat"))
    before = two_apps(False)  # nothing runs: the job stays queued, as at a stop
    upload_id = _upload(before, tiny_mp4)
    status, queued = before.json("POST", "api/trainer", {"upload_id": upload_id, "name": "A", "category": "dance"})
    assert status == 202
    before.app.queue.close()
    after = two_apps(True)
    got = after.app.queue.wait(queued["job"], 60)
    assert got["status"] == "done", got
    assert got["entry_id"] == "squat"


# ----- TICKET-287: a job about one person of a people job resumes too ------------------------------------------------
PEOPLE_JOB = "beef00000001"


def _seed_people_job(state: Path, clip: Path) -> Path:
    """A finished people job on disk, as the people route leaves it: result, trimmed clip and tracks in its work folder."""
    folder = state / "jobs" / PEOPLE_JOB
    (folder / "work").mkdir(parents=True)
    (folder / "work" / "clip.mp4").write_bytes(clip.read_bytes())
    (folder / "work" / "tracks.json").write_text("{}", encoding="utf-8")
    record = {"id": PEOPLE_JOB, "kind": "people", "status": "done", "stage": "done", "stages": ["upload", "track"],
              "trim": None, "duration_ms": 2000, "result": {"people": [{"id": "0"}, {"id": "1"}], "auto_id": None},
              "_people_owner": ""}  # made signed out: its job id is its key (people_routes.OWNER_FIELD)
    (folder / "job.json").write_text(json.dumps(record), encoding="utf-8")
    return folder


def _person_take(two_apps: Any, state: Path, clip: Path, route: str, body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Submit a take about person 1 to a server that runs nothing (as at a stop); its job id and its `_resume` on disk."""
    _seed_people_job(state, clip)
    before = two_apps(False)
    status, queued = before.json("POST", route, {"upload_id": _upload(before, clip), "people_job": PEOPLE_JOB,
                                                 "person_id": "1", **body})
    assert status == 202, queued
    before.app.queue.close()
    record = json.loads((state / "jobs" / queued["job"] / "job.json").read_text(encoding="utf-8"))
    return queued["job"], record["_resume"]


def _spy(fake: Any, seen: list[Any]) -> Any:
    def run(*args: Any, **kw: Any) -> dict[str, Any]:
        seen.append(kw.get("person"))
        return fake(*args, **kw)

    return run


def test_a_person_trainer_job_queued_at_a_stop_runs_after_the_restart(
    two_apps: Any, state_dir: Path, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []
    monkeypatch.setattr(chain, "trainer", _spy(_fake_trainer("squat"), seen))
    job, spec = _person_take(two_apps, state_dir, tiny_mp4, "api/trainer", {"name": "A", "category": "dance"})
    assert spec["v"] == 2 and spec["people_job"] == PEOPLE_JOB and spec["person_id"] == "1" and spec["name"] == "A"
    after = two_apps(True)
    got = after.app.queue.wait(job, 60)
    assert got["status"] == "done", got
    assert got["people_job"] == PEOPLE_JOB and got["person_id"] == "1"
    assert seen and seen[0].id == "1" and seen[0].people_work == state_dir / "jobs" / PEOPLE_JOB / "work"


def test_a_person_follow_job_queued_at_a_stop_runs_after_the_restart(
    two_apps: Any, state_dir: Path, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []
    monkeypatch.setattr(chain, "follower", _spy(_fake_follower(), seen))
    job, spec = _person_take(two_apps, state_dir, tiny_mp4, "api/follow", {"entry_id": "lateral-raise"})
    assert spec["v"] == 2 and spec["people_job"] == PEOPLE_JOB and spec["person_id"] == "1"
    after = two_apps(True)
    got = after.app.queue.wait(job, 60)
    assert got["status"] == "done", got
    assert got["result"]["score"] == 72
    assert seen and seen[0].id == "1" and seen[0].people_work == state_dir / "jobs" / PEOPLE_JOB / "work"


def test_a_person_job_whose_people_folder_is_gone_fails_with_the_reason_logged(
    two_apps: Any, state_dir: Path, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    seen: list[Any] = []
    monkeypatch.setattr(chain, "trainer", _spy(_fake_trainer("squat"), seen))
    job, _ = _person_take(two_apps, state_dir, tiny_mp4, "api/trainer", {"name": "A", "category": "dance"})
    shutil.rmtree(state_dir / "jobs" / PEOPLE_JOB / "work")
    after = two_apps(True)
    got = after.app.queue.get(job)
    assert got["status"] == "failed" and got["reason"] == "the server restarted", got
    assert f"resume: its people job {PEOPLE_JOB} or that job's work folder is gone" in caplog.text
    assert "resumed: queued again" not in caplog.text and seen == []


def test_a_person_no_longer_in_the_people_job_fails_with_the_reason_logged(
    two_apps: Any, state_dir: Path, tiny_mp4: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    job, _ = _person_take(two_apps, state_dir, tiny_mp4, "api/follow", {"entry_id": "lateral-raise"})
    record_path = state_dir / "jobs" / PEOPLE_JOB / "job.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["result"]["people"] = [{"id": "0"}]
    record_path.write_text(json.dumps(record), encoding="utf-8")
    after = two_apps(True)
    assert after.app.queue.get(job)["status"] == "failed"
    assert f"resume: person 1 is no longer in people job {PEOPLE_JOB}" in caplog.text


def test_a_v1_record_still_resumes(two_apps: Any, state_dir: Path, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "trainer", _fake_trainer("squat"))
    before = two_apps(False)
    status, queued = before.json("POST", "api/trainer", {"upload_id": _upload(before, tiny_mp4), "name": "A", "category": "dance"})
    assert status == 202
    before.app.queue.close()
    path = state_dir / "jobs" / queued["job"] / "job.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["_resume"]["v"] == 1 and "people_job" not in record["_resume"]  # no person: the spec is the v1 shape
    record["_resume"] = {k: record["_resume"][k] for k in ("v", "upload_id", "name", "category", "labels")}
    path.write_text(json.dumps(record), encoding="utf-8")  # exactly what a server before TICKET-287 wrote
    after = two_apps(True)
    assert after.app.queue.wait(queued["job"], 60)["status"] == "done"


# ----- TICKET-287 AC-6: a resumed trainer job's entry is owned by the person who submitted it ------------------------
OWNED = "lateral-raise"  # an entry FakeChild knows, so the teacher page can be asked for it


def _owned_take(two_apps: Any, state: Path, clip: Path, person: bool, signed_in: bool = True) -> tuple[Any, str, str | None]:
    """Submit a trainer take (signed in or not, with person 1 or not) to a server that runs nothing, as at a stop;
    the stopped server, the job id and the sid."""
    if person:
        _seed_people_job(state, clip)
    before = two_apps(False)
    sid = sign_in(before) if signed_in else None
    body = {"upload_id": _upload(before, clip), "name": "A", "category": "dance",
            **({"people_job": PEOPLE_JOB, "person_id": "1"} if person else {})}
    status, _, queued = post(before, "api/trainer", body, cookie=sid)
    assert status == 202, queued
    before.app.queue.close()
    return before, queued["job"], sid


@pytest.mark.parametrize("person", [False, True])
def test_a_resumed_trainer_job_makes_an_entry_owned_by_its_submitter(
    authenv: Path, two_apps: Any, state_dir: Path, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch, person: bool  # noqa: F811
) -> None:
    monkeypatch.setattr(chain, "trainer", _fake_trainer(OWNED))
    before, job, sid = _owned_take(two_apps, state_dir, tiny_mp4, person)
    owner = get(before, "api/auth/me", cookie=sid)[2]["user_id"]
    after = two_apps(True)
    assert after.app.queue.wait(job, 60)["status"] == "done"
    assert auth.identity(after.app).entry_owner(OWNED) == (owner, False)
    assert [e["entry_id"] for e in get(after, "api/me/entries", cookie=sid)[2]["entries"]] == [OWNED]


def test_an_only_me_entry_from_a_resumed_job_stays_hidden_from_another_user(
    authenv: Path, two_apps: Any, state_dir: Path, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    monkeypatch.setattr(chain, "trainer", _fake_trainer(OWNED))
    _, job, ada = _owned_take(two_apps, state_dir, tiny_mp4, person=True)
    after = two_apps(True)
    assert after.app.queue.wait(job, 60)["status"] == "done"
    grace = sign_in(after, "grace@example.com")
    assert post(after, f"api/me/entries/{OWNED}", {"only_me": True}, cookie=grace)[0] == 404  # not the owner
    assert post(after, f"api/me/entries/{OWNED}", {"only_me": True}, cookie=ada)[0] == 200
    assert get(after, f"api/teacher/{OWNED}", cookie=grace)[0] == 404
    assert get(after, f"api/teacher/{OWNED}")[0] == 404  # signed out
    assert get(after, f"api/teacher/{OWNED}", cookie=ada)[0] == 200


def test_a_signed_out_take_resumes_with_no_owner_and_no_error(
    authenv: Path, two_apps: Any, state_dir: Path, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(chain, "trainer", _fake_trainer(OWNED))
    _, job, _ = _owned_take(two_apps, state_dir, tiny_mp4, person=False, signed_in=False)
    after = two_apps(True)
    assert after.app.queue.wait(job, 60)["status"] == "done"
    assert not auth.ident.db_path(after.app.state).is_file() or auth.identity(after.app).entry_owner(OWNED) is None
    assert "could not read the owner" not in caplog.text and "could not record the owner" not in caplog.text


def test_a_step_that_dies_during_the_drain_is_counted_as_cut_off(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Prod 2026-11-04: a take failed 15 s into a drain with this reason while the drain logged 0 cut off."""
    release, started = threading.Event(), threading.Event()

    def work(ctx: Any) -> None:
        started.set()
        release.wait(10)
        raise jobs.JobFailed("pose", jobs.DRAIN_CUT_REASON, "restart")

    q = jobs.JobQueue(tmp_path)
    q.submit("follow", work)
    assert started.wait(5)
    timer = threading.Timer(0.2, release.set)
    timer.start()
    with caplog.at_level(logging.INFO, logger="part7"):
        assert q.drain(20, poll_s=0.05) == 1
    timer.join()
    assert len([r for r in caplog.records if r.getMessage().startswith("ANOMALY drain_cut_off")]) == 1
    assert "drain: done, 1 job(s) cut off" in caplog.text
    q.close()
