"""TICKET-280: the owner-only routes over muse_fix (docs/specs/muse-fix-ui.md). Fakes only: no network, no GPU, no paid call."""

from __future__ import annotations

import functools
import json
import time
from pathlib import Path
from typing import Any

import pytest

from history_support import OTHER, USER, World, world  # noqa: F401
from part7 import delete_routes, history_store, muse_fix, muse_fix_inputs, muse_fix_routes as routes
from support import Api
from test_muse_fix import PNG, Fake

ENTRY = "lateral-raise-0f13199f"


def origin(api: Api, user: str | None = USER) -> dict[str, str]:
    return {"Origin": f"http://127.0.0.1:{api.port}", **({"X-Test-User": user} if user else {})}


def consent(api: Api, on: bool = True) -> None:
    history_store.set_consent(api.app.state, USER, on, "v1")


class Env:
    def __init__(self, api: Api, world: World, **fields: Any) -> None:  # noqa: F811
        self.api, self.runs = api, []

        def fn(ctx: Any) -> dict[str, Any]:
            return {"result": {"entry_id": ENTRY}}

        self.id = api.app.queue.submit("follow", fn, entry_id=ENTRY)["id"]
        assert api.app.queue.wait(self.id, 10)["status"] == "done"
        world.owners[self.id] = USER
        self.dir = api.app.queue.job_dir(self.id)
        if fields:
            rec = json.loads((self.dir / "job.json").read_text())
            (self.dir / "job.json").write_text(json.dumps({**rec, **fields}))
            api.app.queue._jobs[self.id].update(fields)

    def get(self, path: str = "", user: str | None = USER) -> tuple[int, Any]:
        return self.api.json("GET", f"api/jobs/{self.id}/muse-fix{path}", headers={"X-Test-User": user} if user else {})

    def post(self, what: str, user: str | None = USER, headers: dict[str, str] | None = None) -> tuple[int, Any]:
        return self.api.json("POST", f"api/jobs/{self.id}/muse-fix", {"what": what}, headers=headers if headers is not None else origin(self.api, user))

    def settle(self) -> None:
        for _ in range(200):
            if not routes.active(self.id):
                return
            time.sleep(0.05)
        raise AssertionError("the worker did not finish")


def fake_run(env: Env, status: str = "shown"):
    def run(job_dir: Path, *, consent: bool, **kw: Any) -> dict[str, Any]:
        env.runs.append((consent, kw.get("state")))
        rec = {"schema": muse_fix.SCHEMA, "job_id": env.id, "status": status, "created_at": "2026-11-01T10:00:00Z", "fault_index": 0,
               "joint": "left_elbow", "error_deg": 3.4, "target_deg": 90.0, "image": "corrected-12.png", "model": "muse-image-1.0",
               "cost_usd": 0.01, "frame": 12, "follower_deg": 120.0}
        out = muse_fix.folder(job_dir)
        out.mkdir(parents=True, exist_ok=True)
        if status == "shown":
            (out / "corrected-12.png").write_bytes(PNG)
        (out / "run-x.json").write_text(json.dumps(rec))
        return rec
    return run


@pytest.fixture()
def env(api: Api, world: World, monkeypatch: pytest.MonkeyPatch) -> Env:  # noqa: F811
    e = Env(api, world)
    monkeypatch.setattr(muse_fix, "run", fake_run(e))
    return e


def test_consent_off_means_no_call_no_card_no_files(env: Env) -> None:  # AC-5 negative
    assert env.post("image")[0] == 403
    consent(env.api, False)
    status, doc = env.post("image")
    assert status == 403 and doc["code"] == "consent_needed" and env.post("referee")[0] == 403
    env.settle()
    state = env.get()[1]
    assert env.runs == [] and state["consent"] is False and state["card"] is None and state["image"] is None
    assert not muse_fix.folder(env.dir).exists() and env.get("/image")[0] == 404


def test_the_picture_is_made_in_the_background_and_served_with_its_label(env: Env) -> None:  # AC-2
    consent(env.api)
    status, _ = env.post("image")
    assert status == 202
    env.settle()
    assert env.runs == [(True, env.api.app.state)]
    state = env.get()[1]
    assert state["card"]["status"] == "shown" and state["card"]["label"] == "AI-generated illustration"
    assert state["card"]["error_text"] == "Measured error: 3.4 degrees from the target pose." and state["image"] == f"api/jobs/{env.id}/muse-fix/image"
    status, headers, body = env.api.request("GET", state["image"], headers={"X-Test-User": USER})
    assert status == 200 and body == PNG and headers["content-type"] == "image/png"


def test_a_miss_shows_only_the_plain_message_and_no_image(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-1
    consent(env.api)
    monkeypatch.setattr(muse_fix, "run", fake_run(env, "missed"))
    env.post("image")
    env.settle()
    state = env.get()[1]
    assert state["card"] == {"status": "missed", "message": "The image model missed the pose."} and state["image"] is None
    assert env.get("/image")[0] == 404 and state["referee"] is None


def test_owner_only_401_signed_out_404_other_user_403_without_origin(env: Env) -> None:
    consent(env.api)
    assert env.get(user=None)[0] == 401 and env.get("/image", None)[0] == 401 and env.post("image", None, headers={"Origin": f"http://127.0.0.1:{env.api.port}"})[0] == 401
    assert env.get(user=OTHER)[0] == 404 and env.get("/image", OTHER)[0] == 404 and env.post("image", OTHER)[0] == 404
    assert env.post("image", headers={"X-Test-User": USER})[0] == 403  # no same-origin header
    assert env.api.json("GET", "api/jobs/ffffffffffff/muse-fix", headers={"X-Test-User": USER})[0] == 404
    assert env.post("bogus")[0] == 400
    assert env.runs == []


@pytest.mark.parametrize("fields", [{"private": True}, {"mode": "rehab"}])
def test_private_and_rehab_takes_are_never_eligible(api: Api, world: World, monkeypatch: pytest.MonkeyPatch, fields: dict[str, Any]) -> None:  # noqa: F811
    e = Env(api, world, **fields)
    monkeypatch.setattr(muse_fix, "run", fake_run(e))
    consent(api)
    assert e.get()[1]["eligible"] is False
    assert e.post("image")[0] == 409 and e.runs == []


def test_a_second_tap_while_it_runs_starts_nothing_more(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    gate = threading.Event()
    inner = fake_run(env)
    monkeypatch.setattr(muse_fix, "run", lambda *a, **k: (gate.wait(10), inner(*a, **k))[1])
    consent(env.api)
    assert env.post("image")[0] == 202 and env.get()[1]["running"] is True
    assert env.post("image")[0] == 202
    gate.set()
    env.settle()
    assert len(env.runs) == 1


def test_referee_needs_the_picture_then_records_the_models_opinion(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-4
    consent(env.api)
    assert env.post("referee")[0] == 409
    env.post("image")
    env.settle()
    fake = Fake(letter="A")
    monkeypatch.setattr(muse_fix_inputs, "referee_images", lambda root, job_dir: (PNG, PNG, PNG))
    monkeypatch.setattr(muse_fix, "referee", functools.partial(muse_fix.referee, transport=fake, seed=1))
    assert env.post("referee")[0] == 202
    env.settle()
    ref = env.get()[1]["referee"]
    assert len(fake.bodies) == 1 and ref["mine"]["model"] == "muse-spark-1.3" and isinstance(ref["mine"]["picked_corrected"], bool)
    assert set(ref["mine"]) == {"picked_corrected", "model"}, "no seed and no key reach the page"
    s = ref["summary"]
    assert (s["n"], s["badge"]) == (1, False) and s["k"] in (0, 1) and "p" in s


def test_delete_my_data_removes_the_folder_and_waits_for_a_running_worker(env: Env) -> None:
    consent(env.api)
    env.post("image")
    env.settle()
    assert muse_fix.folder(env.dir).is_dir()
    routes._running.add(env.id)
    try:
        assert delete_routes.delete_take(env.api.app, env.id)[0] == 409
    finally:
        routes._running.discard(env.id)
    status, body = delete_routes.delete_take(env.api.app, env.id)
    assert status == 200 and "muse-fix" in body["removed"] and not muse_fix.folder(env.dir).exists()
