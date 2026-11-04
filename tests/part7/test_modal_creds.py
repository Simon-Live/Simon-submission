"""TICKET-367 (parts-harness.md AC-H16): a user's own Modal credentials. Modal is never called: the runner is mocked."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import stat
from typing import Any

import pytest

from auth_support import authenv, get, origin, post, sign_in  # noqa: F401
from part7 import auth, byok_crypto, export_data, modal_creds, modal_creds_routes, modules, run_on, runner
from part7.parts import p2_pose
from support import Api

pytestmark = pytest.mark.usefixtures("authenv")
TID, SECRET = "ak-A1b2C3d4E5f6G7h8", "as-SuperSecretValue99XYZ"
ANN, BOB = "ann@example.com", "bob@example.com"


@pytest.fixture(autouse=True)
def _no_server_modal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    monkeypatch.setenv(byok_crypto.KEY_ENV, str(tmp_path_factory.mktemp("byok-key") / "k"))
    monkeypatch.delenv("FIRM_ENV", raising=False)
    for name in (p2_pose.REMOTE_ENV, p2_pose.FALLBACK_ENV, *run_on.TOKEN_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(run_on.CONFIG_PATH_ENV, str(tmp_path / "no-modal.toml"))


def send(api: Api, method: str, sid: str | None, doc: Any = None) -> tuple[int, bytes]:
    hdr = {"Content-Type": "application/json", "Origin": origin(api)}
    if sid:
        hdr["Cookie"] = f"{auth.COOKIE}={sid}"
    status, _, body = api.request(method, "api/me/modal", json.dumps({} if doc is None else doc).encode(), hdr)
    return status, body


def user_of(api: Api, sid: str) -> str:
    return auth.identity(api.app).session_user(sid)


def path_of(api: Api, sid: str) -> Path:
    return api.app.state / "credentials" / f"{user_of(api, sid)}.json"


# ----- storage -----------------------------------------------------------------------------------------------------
def test_put_get_delete_shapes_and_file_mode(api: Api) -> None:
    sid = sign_in(api, ANN)
    assert get(api, "api/me/modal", sid)[2] == {"set": False, "token_id_hint": None, "expired": False, "check": None, "idle_ttl_s": 86400,
                                                "key_unavailable": False, "paused": False}
    status, body = send(api, "PUT", sid, {"token_id": TID, "token_secret": SECRET})
    assert status == 200 and json.loads(body)["set"] is True
    assert json.loads(body)["message"] == modal_creds_routes.MSG_SAVED
    assert get(api, "api/me/modal", sid)[2] == {"set": True, "token_id_hint": "ak-…G7h8", "expired": False, "check": None, "idle_ttl_s": 86400,
                                                "key_unavailable": False, "paused": False}
    assert SECRET.encode() not in path_of(api, sid).read_bytes() and TID.encode() not in path_of(api, sid).read_bytes(), "encrypted at rest"
    path = api.app.state / "credentials" / f"{user_of(api, sid)}.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    for db in api.app.state.rglob("*.db"):
        assert SECRET.encode() not in db.read_bytes(), "never in the identity database"
    status, body = send(api, "DELETE", sid)
    assert status == 200 and json.loads(body)["set"] is False and not path.exists()
    assert get(api, "api/me/modal", sid)[2]["set"] is False


@pytest.mark.parametrize("doc", [
    {"token_id": "ak-short", "token_secret": SECRET}, {"token_id": TID, "token_secret": "xx-" + "a" * 20},
    {"token_id": TID}, {"token_id": [TID], "token_secret": SECRET}, {"token_id": TID, "token_secret": "as-a/../b12345678"},
])
def test_a_bad_shape_is_400_with_no_value_echoed(api: Api, doc: dict[str, Any]) -> None:
    sid = sign_in(api, ANN)
    status, body = send(api, "PUT", sid, doc)
    assert status == 400 and json.loads(body)["message"] == modal_creds.MSG_SHAPE
    assert SECRET.encode() not in body and TID.encode() not in body and b"aaaaaaaa" not in body
    assert not (api.app.state / "credentials").exists() or not any((api.app.state / "credentials").iterdir())


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
def test_signed_out_is_401(api: Api, method: str) -> None:
    status, _ = send(api, method, None, {"token_id": TID, "token_secret": SECRET})
    assert status == 401
    assert not (api.app.state / "credentials").exists()


def test_put_without_the_csrf_headers_is_refused(api: Api) -> None:
    sid = sign_in(api, ANN)
    status, _, _ = api.request("PUT", "api/me/modal", json.dumps({"token_id": TID, "token_secret": SECRET}).encode(),
                               {"Cookie": f"{auth.COOKIE}={sid}"})
    assert status == 403 and not (api.app.state / "credentials").exists()


def test_delete_account_removes_the_file(api: Api) -> None:
    sid = sign_in(api, ANN)
    send(api, "PUT", sid, {"token_id": TID, "token_secret": SECRET})
    path = api.app.state / "credentials" / f"{user_of(api, sid)}.json"
    assert path.is_file()
    assert post(api, "api/me/delete", {"confirm": "delete"}, cookie=sid)[0] == 200
    assert not path.exists()


def test_export_says_set_without_values(api: Api) -> None:
    sid = sign_in(api, ANN)
    send(api, "PUT", sid, {"token_id": TID, "token_secret": SECRET})
    status, _, raw = api.request("GET", "api/me/export", None, {"Cookie": f"{auth.COOKIE}={sid}"})
    assert status == 200 and b"modal credentials" in raw and b'"set"' in raw
    assert SECRET.encode() not in raw and TID.encode() not in raw
    assert "modal" in export_data.EXPORTERS


def test_the_secret_never_reaches_logs_or_responses(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    sid = sign_in(api, ANN)
    bodies = [send(api, "PUT", sid, {"token_id": TID, "token_secret": SECRET})[1],
              send(api, "PUT", sid, {"token_id": TID, "token_secret": SECRET + "!"})[1],
              json.dumps(get(api, "api/me/modal", sid)[2]).encode(), send(api, "DELETE", sid)[1]]
    for body in bodies:
        assert SECRET.encode() not in body and TID.encode() not in body
    assert SECRET not in caplog.text and TID not in caplog.text
    for log in api.app.state.rglob("*.log"):
        assert SECRET.encode() not in log.read_bytes()


# ----- use ---------------------------------------------------------------------------------------------------------
class Ctx:
    def __init__(self, job_id: str = "job1") -> None:
        self.id = job_id


def _fake_runner(monkeypatch: pytest.MonkeyPatch, exit_code: int = 0) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(p2_pose.applog, "anomaly", lambda *a, **k: None)

    def fake_run(part: Any, argv: list[str], cwd: Any, env_extra: dict[str, str] | None = None, **kw: Any) -> runner.Step:
        modal = argv == ["p2_client"]
        calls.append({"route": "modal" if modal else "local", "env": dict(env_extra or {})})
        return runner.Step(exit=exit_code if modal else 0)

    monkeypatch.setattr(p2_pose.runner, "run", fake_run)
    monkeypatch.setattr(p2_pose, "_remote_command", lambda sub, lk: ["p2_client"])
    monkeypatch.setattr(p2_pose.byok_route, "command", lambda sub, sha: ["p2_client"])
    monkeypatch.setattr(p2_pose, "has_worker", lambda *a: False)
    monkeypatch.setattr(p2_pose, "_attempt", lambda *a, **k: calls.append({"route": "local", "env": {}}) or runner.Step(exit=0))
    return calls


def _part2_job(tmp_path: Path) -> Any:
    return lambda ctx: {"result": {"step": p2_pose._execute(["run"], "gpu", tmp_path, "part2.log", modules.load(), tmp_path, True, None)["exit"]}}


def test_own_env_reaches_only_that_subprocess(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_runner(monkeypatch)
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    before = dict(os.environ)
    assert run_on.parse({"run_on": "serverless"}, tmp_path, "ann") == ("serverless", None)
    owner = run_on.owner_for("serverless", tmp_path, "ann")
    assert run_on.record("serverless", owner) == {"run_on": "serverless", "modal": "own", "compute_owner": True}
    run_on.bind(_part2_job(tmp_path), "serverless", tmp_path, owner)(Ctx())
    assert calls == [{"route": "modal", "env": {"MODAL_TOKEN_ID": TID, "MODAL_TOKEN_SECRET": SECRET}}]
    assert dict(os.environ) == before and "MODAL_TOKEN_SECRET" not in os.environ, "nothing in os.environ"
    assert SECRET not in json.dumps(run_on.record("serverless", owner))


def test_another_users_job_has_no_token_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_runner(monkeypatch)
    monkeypatch.setenv(p2_pose.REMOTE_ENV, "modal")  # the server's own route, so Bob may choose serverless
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    run_on.bind(_part2_job(tmp_path), "serverless", tmp_path, "ann")(Ctx("a"))
    bob = run_on.owner_for("serverless", tmp_path, "bob")
    assert bob is None and run_on.record("serverless", bob) == {"run_on": "serverless"}
    run_on.bind(_part2_job(tmp_path), "serverless", tmp_path, bob)(Ctx("b"))
    assert calls[0]["env"]["MODAL_TOKEN_SECRET"] == SECRET
    assert calls[1] == {"route": "modal", "env": {}}, "Bob's subprocess gets no token env"


def test_removed_before_the_run_means_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                            caplog: pytest.LogCaptureFixture) -> None:
    calls = _fake_runner(monkeypatch)
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    fn = run_on.bind(_part2_job(tmp_path), "serverless", tmp_path, run_on.owner_for("serverless", tmp_path, "ann"))
    modal_creds.remove(tmp_path, "ann")  # after submit, before the run
    with caplog.at_level(logging.WARNING):
        fn(Ctx())
    assert calls == [{"route": "local", "env": {}}]
    assert "credentials are gone" in caplog.text


def test_refused_credentials_fall_back_to_local_with_the_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_runner(monkeypatch, exit_code=p2_pose.CREDS_REFUSED_EXIT)
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    out = run_on.bind(_part2_job(tmp_path), "serverless", tmp_path, "ann")(Ctx())
    assert [c["route"] for c in calls] == ["modal", "local"], "fallback without SIMON7_PART2_FALLBACK"
    assert out["result"]["run_on_note"] == "Your Modal credentials did not work; this take ran on this machine."
    assert SECRET not in json.dumps(out)


def test_the_runner_redacts_a_token_in_env_extra(tmp_path: Path) -> None:
    log = tmp_path / "step.log"
    step = runner.run(2, ["sh", "-c", 'echo "id $MODAL_TOKEN_ID s $MODAL_TOKEN_SECRET"'], cwd=tmp_path,
                      env_extra={"MODAL_TOKEN_ID": TID, "MODAL_TOKEN_SECRET": SECRET}, log_path=log)
    assert step["exit"] == 0
    text = log.read_text(encoding="utf-8")
    assert SECRET not in text and TID not in text and "<redacted>" in text
    assert "MODAL_TOKEN_SECRET" not in os.environ


def test_negative_no_credentials_and_no_server_modal_changes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_runner(monkeypatch)
    assert run_on.offered(tmp_path, "ann") is False and run_on.offered(tmp_path, None) is False
    assert run_on.parse({"run_on": "serverless"}, tmp_path, "ann") == (None, run_on.MSG_NOT_SET_UP)
    assert run_on.owner_for("local", tmp_path, "ann") is None and run_on.record(None, None) == {}
    fn = _part2_job(tmp_path)
    assert run_on.bind(fn, None, tmp_path, None) is fn
    fn(Ctx())
    assert calls == [{"route": "local", "env": {}}]
    assert not (tmp_path / "credentials").exists()


def test_a_crafted_user_id_never_leaves_the_folder(tmp_path: Path) -> None:
    assert modal_creds.save(tmp_path, "../evil", TID, SECRET) is False
    assert modal_creds.env_for(tmp_path, "../evil") is None and not (tmp_path / "evil.json").exists()
