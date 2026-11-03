"""TICKET-364 (parts-harness.md AC-H12): the per-take "Run on" choice. Modal is never called: `_on_route` is faked."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from part7 import jobs, modules, run_on, runner
from part7 import server as server_mod
from part7.parts import p2_pose

SECRET = "tok-must-never-leak-123"


@pytest.fixture(autouse=True)
def _no_modal_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in (p2_pose.REMOTE_ENV, p2_pose.FALLBACK_ENV, *run_on.TOKEN_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(run_on.CONFIG_PATH_ENV, str(tmp_path / "no-modal.toml"))


def _routes(monkeypatch: pytest.MonkeyPatch, exits: dict[str, int] | None = None) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(p2_pose.applog, "anomaly", lambda *a, **k: None)

    def on_route(route: str, *rest: Any) -> runner.Step:
        calls.append(route)
        return runner.Step(exit=(exits or {}).get(route, 0))

    monkeypatch.setattr(p2_pose, "_on_route", on_route)
    return calls


def _execute(tmp_path: Path) -> runner.Step:
    return p2_pose._execute(["run", "--mode", "single"], "gpu", tmp_path, "part2.log", modules.load(), tmp_path, True, None)


def test_flag_false_and_no_choice_keeps_the_env_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative: without Modal configuration the flag is false, serverless is refused, and the route is unchanged."""
    assert run_on.modal_configured() is False
    assert run_on.parse({"run_on": "serverless"}) == (None, run_on.MSG_NOT_SET_UP)
    calls = _routes(monkeypatch)
    _execute(tmp_path)
    assert calls == ["local"], "no env, no choice: the local GPU as before"
    monkeypatch.setenv(p2_pose.REMOTE_ENV, "modal")
    _execute(tmp_path)
    assert calls[-1] == "modal", "no choice: SIMON7_PART2_REMOTE still picks the route"


def test_a_job_with_no_stored_choice_keeps_the_old_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fn = lambda ctx: {"result": {}}  # noqa: E731
    assert run_on.bind(fn, None) is fn, "no wrapper at all"
    assert run_on.record(None) == {} and run_on.parse({}) == (None, None)


def test_a_serverless_job_stores_it_and_calls_execute_with_modal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_TOKEN_ID", SECRET)
    monkeypatch.setenv("MODAL_TOKEN_SECRET", SECRET)
    choice, error = run_on.parse({"run_on": "serverless"})
    assert (choice, error) == ("serverless", None)
    calls = _routes(monkeypatch)
    seen: list[str | None] = []

    def job(ctx: jobs.JobContext) -> dict[str, Any]:
        seen.append(p2_pose.job_route())
        _execute(tmp_path)
        return {"result": {}}

    queue = jobs.JobQueue(tmp_path / "state", workers=1)
    try:
        made = queue.submit("follow", run_on.bind(job, choice), **run_on.record(choice))
        done = queue.wait(made["id"], timeout=10)
    finally:
        queue.close()
    assert done is not None and done["status"] == "done", done
    stored = json.loads((tmp_path / "state" / "jobs" / made["id"] / "job.json").read_text(encoding="utf-8"))
    assert stored["run_on"] == "serverless", "the job record keeps the choice"
    assert seen == ["modal"] and calls == ["modal"], "the job's Part 2 call goes to Modal (faked)"
    assert p2_pose.job_route() is None, "the route does not leak out of the job"


def test_the_choice_overrides_the_env_and_the_fallback_still_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(p2_pose.REMOTE_ENV, "modal")
    calls = _routes(monkeypatch)
    with p2_pose.job_route_set("local"):
        _execute(tmp_path)
    assert calls == ["local"], "This machine wins over SIMON7_PART2_REMOTE=modal"
    monkeypatch.delenv(p2_pose.REMOTE_ENV)
    monkeypatch.setenv(p2_pose.FALLBACK_ENV, "on")
    calls = _routes(monkeypatch, {"modal": 2, "local": 0})
    with p2_pose.job_route_set("modal"):
        step = _execute(tmp_path)
    assert calls == ["modal", "local"] and step["route"] == "local", "SIMON7_PART2_FALLBACK behaves as before"


def test_an_unknown_choice_is_refused() -> None:
    assert run_on.parse({"run_on": "cloud"}) == (None, run_on.MSG_BAD)
    assert run_on.parse({"run_on": "local"}) == ("local", None)


def test_the_flag_never_exposes_a_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = tmp_path / "modal.toml"
    profile.write_text(f'[default]\ntoken_id = "{SECRET}"\ntoken_secret = "{SECRET}"\n', encoding="utf-8")
    monkeypatch.setenv(run_on.CONFIG_PATH_ENV, str(profile))
    opened: list[str] = []
    real_open = Path.open

    def spy_open(self: Path, *a: Any, **k: Any) -> Any:
        opened.append(str(self))
        return real_open(self, *a, **k)

    monkeypatch.setattr(Path, "open", spy_open)
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: pytest.fail(f"read {self}"))
    flag = run_on.modal_configured()
    assert flag is True and type(flag) is bool, "a plain bool, no value"
    assert str(profile) not in opened, "the profile file is never opened"
    monkeypatch.setenv("MODAL_TOKEN_ID", SECRET)
    monkeypatch.setenv("MODAL_TOKEN_SECRET", SECRET)
    assert SECRET not in json.dumps({"serverless": run_on.modal_configured()})


# ----- the routes: api/config, api/people, api/follow ------------------------------------------------------------
def test_api_config_says_serverless_false_without_modal(api: Any) -> None:
    status, doc = api.json("GET", "api/config")
    assert status == 200 and doc["serverless"] is False


def test_api_config_says_serverless_true_without_leaking_the_token(api: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_TOKEN_ID", SECRET)
    monkeypatch.setenv("MODAL_TOKEN_SECRET", SECRET)
    status, _, body = api.request("GET", "api/config")
    assert status == 200 and json.loads(body)["serverless"] is True
    assert SECRET.encode() not in body


def test_api_people_refuses_serverless_when_not_set_up(api: Any, tiny_mp4: Path) -> None:
    _, up = api.upload(tiny_mp4)
    for value, message in (("serverless", run_on.MSG_NOT_SET_UP), ("cloud", run_on.MSG_BAD)):
        status, doc = api.json("POST", "api/people", {"upload_id": up["upload_id"], "run_on": value})
        assert status == 400 and message in json.dumps(doc), doc


def test_api_people_stores_the_choice_and_runs_part2_on_it(api: Any, tiny_mp4: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_TOKEN_ID", SECRET)
    monkeypatch.setenv("MODAL_TOKEN_SECRET", SECRET)
    calls: list[str] = []

    def part2(*a: Any, **k: Any) -> Any:  # the stub tree has no Part 2 clone; record the job's first route, then fail
        calls.append(p2_pose.first_route())
        raise RuntimeError("no Part 2 in this test")

    monkeypatch.setattr(p2_pose, "capabilities", lambda *a, **k: {"track": True, "ids": True})
    monkeypatch.setattr(p2_pose, "track", part2)
    monkeypatch.setattr(p2_pose, "run", part2)
    _, up = api.upload(tiny_mp4)
    status, doc = api.json("POST", "api/people", {"upload_id": up["upload_id"], "run_on": "serverless"})
    assert status == 202 and doc["run_on"] == "serverless", doc
    job = api.app.queue.wait(doc["job"], 60)
    assert job is not None and job["run_on"] == "serverless"
    assert calls and set(calls) == {"modal"}, f"the job's Part 2 call tries Modal first: {calls}"



@pytest.mark.parametrize("route", ["api/people", "api/follow"])
def test_a_list_or_dict_run_on_is_a_400_not_a_crash(api: Any, tiny_mp4: Path, route: str,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    crashes: list[Any] = []
    monkeypatch.setattr(server_mod.selfheal, "note_crash", lambda *a, **k: crashes.append(a))
    _, up = api.upload(tiny_mp4)
    for value in ([], {}):
        status, doc = api.json("POST", route, {"upload_id": up["upload_id"], "entry_id": "lateral-raise", "run_on": value})
        assert status == 400 and run_on.MSG_BAD in json.dumps(doc), (route, value, doc)
    assert crashes == [], "no crash note"


def _fake_part2(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def part2(*a: Any, **k: Any) -> Any:  # no real Part 2 and never Modal: record the job's first route, then fail
        calls.append(p2_pose.first_route())
        raise RuntimeError("no Part 2 in this test")

    monkeypatch.setattr(p2_pose, "capabilities", lambda *a, **k: {"track": True, "ids": True})
    monkeypatch.setattr(p2_pose, "track", part2)
    monkeypatch.setattr(p2_pose, "run", part2)
    return calls


def test_api_follow_refuses_serverless_when_not_set_up(api: Any, tiny_mp4: Path) -> None:
    _, up = api.upload(tiny_mp4)
    status, doc = api.json("POST", "api/follow", {"upload_id": up["upload_id"], "entry_id": "lateral-raise",
                                                  "run_on": "serverless"})
    assert status == 400 and run_on.MSG_NOT_SET_UP in json.dumps(doc), doc


def test_api_follow_stores_the_choice_and_runs_part2_on_it(api: Any, tiny_mp4: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_TOKEN_ID", SECRET)
    monkeypatch.setenv("MODAL_TOKEN_SECRET", SECRET)
    calls = _fake_part2(monkeypatch)
    _, up = api.upload(tiny_mp4)
    status, doc = api.json("POST", "api/follow", {"upload_id": up["upload_id"], "entry_id": "lateral-raise",
                                                  "run_on": "serverless"})
    assert status == 202 and doc["run_on"] == "serverless", doc
    job = api.app.queue.wait(doc["job"], 60)
    assert job is not None and job["run_on"] == "serverless"
    assert calls == ["modal"], f"the follow job's Part 2 call tries Modal first: {calls}"


def test_a_resumed_job_checks_its_stored_choice_again(caplog: pytest.LogCaptureFixture) -> None:
    assert run_on.resumed(None, "j1") is None, "no stored choice: the env route"
    assert run_on.resumed("local", "j1") == "local"
    assert run_on.resumed(["x"], "j1") is None, "an invalid stored value keeps the env route"
    assert run_on.resumed("serverless", "j1") == "local", "serverless no longer set up runs on this machine"
    assert "serverless is no longer set up" in caplog.text and "is not valid" in caplog.text
