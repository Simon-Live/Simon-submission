"""BYOK-M4 canary (docs/specs/byok-prod.md, HARDENING.md section 4): a canary token goes through every path a user's
own Modal token takes (save, view, export, check, a take whose Part 2 subprocess prints its env, expiry), then no file
under the test's whole tree and no log line holds it. The Part 2 subprocess is `sh`, never Modal, never the GPU."""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
import time
from typing import Any

import pytest

from auth_support import authenv, get, origin, post, sign_in  # noqa: F401
from part7 import auth, byok_crypto, byok_route, export_data, modal_check, modal_creds, modules, run_on
from part7.parts import p2_pose
from support import Api

CANARY_ID, CANARY_SECRET = "ak-CANARYid7f3a9q2", "as-CANARYsecret8d1e5w0"
pytestmark = pytest.mark.usefixtures("authenv")


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(byok_crypto.KEY_ENV, str(tmp_path / "secrets" / "byok.key"))  # outside the state dir
    for name in (p2_pose.REMOTE_ENV, p2_pose.FALLBACK_ENV, *run_on.TOKEN_ENV, "FIRM_ENV"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(run_on.CONFIG_PATH_ENV, str(tmp_path / "no-modal.toml"))


def holders(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*")
                  if p.is_file() and (CANARY_ID.encode() in p.read_bytes() or CANARY_SECRET.encode() in p.read_bytes()))


def test_the_canary_token_is_in_no_file_and_no_log_line(api: Api, tiny_mp4: Path, tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch,
                                                         caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    sid = sign_in(api, "canary@example.com")
    hdr = {"Content-Type": "application/json", "Origin": origin(api), "Cookie": f"{auth.COOKIE}={sid}"}
    body = json.dumps({"token_id": CANARY_ID, "token_secret": CANARY_SECRET}).encode()
    answers = [api.request("PUT", "api/me/modal", body, hdr)[2], json.dumps(get(api, "api/me/modal", sid)[2]).encode(),
               api.request("GET", "api/me/export", None, {"Cookie": f"{auth.COOKIE}={sid}"})[2]]
    user = auth.identity(api.app).session_user(sid)
    stored = json.loads((api.app.state / "credentials" / f"{user}.json").read_text(encoding="utf-8"))
    assert stored["v"] == modal_creds.FORMAT == 3 and base64.b64decode(stored["box"])[0] == byok_crypto.VERSION, "AES-GCM box"

    seen: list[dict[str, Any]] = []
    check_run = lambda argv, **kw: seen.append(kw) or type("D", (), {"returncode": 0})()  # noqa: E731
    assert modal_check.run_check(api.app.state, user, check_run) == modal_check.OK
    assert seen[0]["env"]["MODAL_TOKEN_SECRET"] == CANARY_SECRET

    # the take: Part 2 on the own route is a shell that prints the token variables into the step log
    monkeypatch.setattr(byok_route, "command",
                        lambda sub, sha: ["sh", "-c", 'echo "id=$MODAL_TOKEN_ID secret=$MODAL_TOKEN_SECRET"; env'])
    logs: list[Path] = []

    def part2(video: Any, work: Any, *a: Any, **k: Any) -> Any:
        work_p = Path(work)
        step = p2_pose._execute(["run"], "gpu", work_p, "part2.log", modules.load(), work_p, True, None)
        logs.append(work_p / "steps" / "part2.log")
        raise RuntimeError(f"stop after Part 2 (exit {step['exit']})")

    monkeypatch.setattr(p2_pose, "capabilities", lambda *a, **k: {"track": True, "ids": True})
    monkeypatch.setattr(p2_pose, "track", part2)
    monkeypatch.setattr(p2_pose, "run", part2)
    _, up = api.upload(tiny_mp4)
    status, _, doc = post(api, "api/follow", {"upload_id": up["upload_id"], "entry_id": "lateral-raise",
                                              "run_on": "serverless"}, cookie=sid)
    assert status == 202 and doc["run_on"] == "serverless", doc
    job = api.app.queue.wait(doc["job"], 60)
    assert job is not None and job.get("modal") == "own" and job.get("compute_owner") is True
    assert logs and "<redacted>" in logs[0].read_text(encoding="utf-8"), "the subprocess got the token, the log did not"

    for answer in answers:
        assert CANARY_ID.encode() not in answer and CANARY_SECRET.encode() not in answer
    assert holders(tmp_path) == [], "state, job records, logs, exports, the queue: no file holds the canary"
    assert CANARY_ID not in caplog.text and CANARY_SECRET not in caplog.text
    assert "MODAL_TOKEN_SECRET" not in os.environ

    # 25 h unused: the record goes, and the canary is still in no file
    then = time.time() - 25 * 3600
    os.utime(api.app.state / "credentials" / f"{user}.json", (then, then))
    modal_creds.sweep(api.app.state)
    assert not (api.app.state / "credentials" / f"{user}.json").exists() and holders(tmp_path) == []
    assert "modal" in export_data.EXPORTERS
