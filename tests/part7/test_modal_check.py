"""TICKET-367 (parts-harness.md AC-H16): "Check my credentials". The subprocess is mocked: Modal is never called."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import stat
import subprocess
import threading
import time
import types
from typing import Any

import pytest

from auth_support import authenv, get, origin, sign_in  # noqa: F401
from part7 import auth, byok_crypto, byok_route, config, modal_check, modal_creds
from support import Api

TID, SECRET = "ak-A1b2C3d4E5f6G7h8", "as-SuperSecretValue99XYZ"
BOB_TID, BOB_SECRET = "ak-Bobbobbob1234", "as-BobSecretValue5678"


class Done:
    def __init__(self, code: int) -> None:
        self.returncode = code


def fake(code: int | None, seen: list[dict[str, Any]]) -> Any:
    def run(argv: list[str], **kw: Any) -> Done:
        seen.append({"argv": argv, **kw})
        if code is None:
            raise subprocess.TimeoutExpired(argv, kw["timeout"])
        return Done(code)
    return run


@pytest.fixture(autouse=True)
def _server_env(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    monkeypatch.setenv(byok_crypto.KEY_ENV, str(tmp_path_factory.mktemp("byok-key") / "k"))
    monkeypatch.setenv("MODAL_TOKEN_ID", "ak-ServerWideTokenXX")  # the server's own: must never reach a check
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "as-ServerWideSecretXX")
    monkeypatch.setenv("SIMON7_SOME_KEY", "server-only-value")


def test_the_env_carries_only_that_users_tokens(tmp_path: Path) -> None:
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    modal_creds.save(tmp_path, "bob", BOB_TID, BOB_SECRET)
    seen: list[dict[str, Any]] = []
    assert modal_check.run_check(tmp_path, "ann", fake(0, seen)) == modal_check.OK
    env = seen[0]["env"]
    assert env["MODAL_TOKEN_ID"] == TID and env["MODAL_TOKEN_SECRET"] == SECRET
    assert set(env) <= {"MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", *modal_check.PASS_ENV}, "built fresh, nothing else"
    assert BOB_SECRET not in json.dumps(env) and "ServerWide" not in json.dumps(env)
    assert seen[0]["timeout"] == 30 and seen[0]["stdout"] is subprocess.DEVNULL and seen[0]["stderr"] is subprocess.DEVNULL
    assert "capture_output" not in seen[0], "output is never read"
    registry = str(tmp_path / "own-clients")
    assert seen[0]["argv"][1:] == ["-I", str(byok_route.CLIENT), "--own", "--registry", registry, "--owner", "ann",
                                   "--check"], "the launcher, never a -c script, registered as a take's is (S-R2)"


@pytest.mark.parametrize("code, reason", [
    (0, "ok"), (77, "token rejected"), (2, "Simon's app is not in this Modal workspace (run the command shown)"),
    (3, "check failed"),
    (None, "timed out"), (1, "check failed"), (137, "check failed"),
])
def test_exit_codes_map_to_fixed_reasons(tmp_path: Path, code: int | None, reason: str,
                                         caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    assert modal_check.run_check(tmp_path, "ann", fake(code, [])) == reason
    stored = modal_check.result(tmp_path, "ann")
    assert stored is not None and stored["reason"] == reason and stored["ok"] is (reason == "ok")
    assert set(stored) == {"checked_at", "ok", "reason"}
    path = tmp_path / "credentials" / "ann.check.json"
    raw = path.read_text(encoding="utf-8")
    assert SECRET not in raw and TID not in raw and stat.S_IMODE(path.stat().st_mode) == 0o600
    assert SECRET not in caplog.text and TID not in caplog.text


def test_a_runner_crash_logs_the_type_only(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    modal_creds.save(tmp_path, "ann", TID, SECRET)

    def boom(argv: list[str], **kw: Any) -> Done:
        raise OSError(f"cannot start with {kw['env']['MODAL_TOKEN_SECRET']}")

    caplog.set_level(logging.DEBUG)
    assert modal_check.run_check(tmp_path, "ann", boom) == "check failed"
    assert SECRET not in caplog.text and "OSError" in caplog.text


def test_new_token_or_remove_drops_the_old_result(tmp_path: Path) -> None:
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    modal_check.run_check(tmp_path, "ann", fake(77, []))
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    assert modal_check.result(tmp_path, "ann") is None
    modal_check.run_check(tmp_path, "ann", fake(0, []))
    modal_creds.remove(tmp_path, "ann")
    assert modal_check.result(tmp_path, "ann") is None and not list((tmp_path / "credentials").iterdir())


def test_r4_a_check_of_a_replaced_token_is_never_stored_or_shown(tmp_path: Path) -> None:
    modal_creds.save(tmp_path, "ann", TID, SECRET)

    def replaced_meanwhile(argv: list[str], **kw: Any) -> Done:
        modal_creds.save(tmp_path, "ann", BOB_TID, BOB_SECRET)  # a new token lands while the old one is checked
        return Done(0)

    assert modal_check.run_check(tmp_path, "ann", replaced_meanwhile) == modal_check.OK
    assert modal_check.result(tmp_path, "ann") is None, "the ok of the old token is not the new token's"
    assert not (tmp_path / "credentials" / "ann.check.json").exists()
    modal_check.run_check(tmp_path, "ann", fake(0, []))
    stale = json.loads((tmp_path / "credentials" / "ann.check.json").read_text(encoding="utf-8"))
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    modal_creds.write_private(tmp_path / "credentials" / "ann.check.json", stale)  # a late write of the old result
    assert modal_check.result(tmp_path, "ann") is None, "a result names its save; another save's is not shown"


def test_r5_a_failed_store_leaves_no_temp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    modal_creds.save(tmp_path, "ann", TID, SECRET)

    def no_replace(src: Any, dst: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(modal_creds.os, "replace", no_replace)
    with pytest.raises(OSError):
        modal_check._store(tmp_path, "ann", modal_check.OK, "g")
    assert not [p for p in (tmp_path / "credentials").iterdir() if p.name.startswith(".tmp-")]


def test_the_app_name_matches_the_deployed_app() -> None:
    text = (config.REPO_ROOT / "deploy" / "serverless" / "part2_app.py").read_text(encoding="utf-8")
    assert re.search(r'^APP_NAME = "([^"]+)"', text, re.M).group(1) == modal_check.APP_NAME


def test_start_runs_off_the_calling_thread(tmp_path: Path) -> None:
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    gate, threads = threading.Event(), []

    def slow(argv: list[str], **kw: Any) -> Done:
        threads.append(threading.current_thread())
        gate.wait(5)
        return Done(0)

    assert modal_check.start(tmp_path, "ann", slow) is True
    assert modal_check.start(tmp_path, "ann", slow) is False, "one check at a time per user"
    gate.set()
    for _ in range(100):
        if modal_check.result(tmp_path, "ann"):
            break
        time.sleep(0.02)
    assert threads and threads[0] is not threading.main_thread()
    assert modal_check.result(tmp_path, "ann")["reason"] == "ok"


@pytest.mark.usefixtures("authenv")
def test_post_check_answers_202_and_get_shows_the_result(api: Api, monkeypatch: pytest.MonkeyPatch,
                                                         caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    seen: list[dict[str, Any]] = []

    class Proc:  # the default path's process: started through the gate, never `subprocess.run`
        pid = 4194303  # no such process: the registration names nothing Remove could stop

        def __init__(self, argv: list[str], **kw: Any) -> None:
            seen.append({"argv": argv, **kw})

        def wait(self, timeout: float | None = None) -> int:
            return 77

    monkeypatch.setattr(modal_check, "_spawn", Proc)
    sid = sign_in(api)
    hdr = {"Content-Type": "application/json", "Origin": origin(api), "Cookie": f"{auth.COOKIE}={sid}"}
    assert api.request("POST", "api/me/modal/check", b"{}", hdr)[0] == 409, "no token yet"
    api.request("PUT", "api/me/modal", json.dumps({"token_id": TID, "token_secret": SECRET}).encode(), hdr)
    status, _, body = api.request("POST", "api/me/modal/check", b"{}", hdr)
    assert status == 202 and json.loads(body)["checking"] is True
    doc = None
    for _ in range(100):
        doc = get(api, "api/me/modal", sid)[2]
        if doc.get("check"):
            break
        time.sleep(0.02)
    assert doc["check"]["reason"] == "token rejected" and doc["check"]["ok"] is False
    assert SECRET not in json.dumps(doc) and SECRET not in caplog.text and TID not in caplog.text
    assert seen[0]["env"]["MODAL_TOKEN_SECRET"] == SECRET


@pytest.mark.usefixtures("authenv")
def test_post_check_signed_out_is_401(api: Api) -> None:
    hdr = {"Content-Type": "application/json", "Origin": origin(api)}
    assert api.request("POST", "api/me/modal/check", b"{}", hdr)[0] == 401


def test_the_check_runs_the_modal_venv_prod_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-audit residual: "Check my credentials" uses the interpreter takes use, never a request-time install."""
    import importlib.util

    venv = "/srv/state/modal-venv/bin/python"
    monkeypatch.setenv("SIMON7_MODAL_PYTHON", venv)
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    seen: list[dict[str, Any]] = []
    assert modal_check.run_check(tmp_path, "ann", fake(0, seen)) == modal_check.OK
    env = seen[0]["env"]
    assert env["SIMON7_MODAL_PYTHON"] == venv
    spec = importlib.util.spec_from_file_location("p2_client_check", byok_route.CLIENT)
    client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    launched: list[list[str]] = []
    client.launch(["--check"], environ=env, run=lambda a, **kw: launched.append(a) or types.SimpleNamespace(returncode=0))
    assert launched[0][:2] == [venv, "-I"] and "uv" not in launched[0][:1]
    monkeypatch.delenv("SIMON7_MODAL_PYTHON")
    assert "SIMON7_MODAL_PYTHON" not in modal_check.env_of({modal_creds.ENV_ID: TID, modal_creds.ENV_SECRET: SECRET})
