"""byok-prod.md AC-BY13 (prod verify lifecycle R1 to R3): the credential key is made once and never replaced over
stored records, an unusable key is named as the server's fault, and the sweeper removes a user's lock with the last
of their files."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time

import pytest

from auth_support import authenv, origin, sign_in  # noqa: F401
from part7 import auth, byok_crypto, modal_check, modal_creds, modal_creds_routes, run_on
from support import Api

TID, SECRET = "ak-LifecycleToken001", "as-LifecycleSecret01"


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> Path:
    key = tmp_path_factory.mktemp("byok-key") / "k"
    monkeypatch.setenv(byok_crypto.KEY_ENV, str(key))
    for name in ("FIRM_ENV", "PROD_COMPUTE"):
        monkeypatch.delenv(name, raising=False)
    return key


def hdr(api: Api, sid: str) -> dict[str, str]:
    return {"Content-Type": "application/json", "Origin": origin(api), "Cookie": f"{auth.COOKIE}={sid}"}


# ----- R1 -----------------------------------------------------------------------------------------------------------
def test_the_key_is_made_once_and_a_lost_key_is_never_replaced(tmp_path: Path, _key: Path) -> None:
    assert byok_crypto.missing_problem(tmp_path) is None and not _key.exists(), "first start: nothing yet"
    assert modal_creds.save(tmp_path, "ann", TID, SECRET)
    record = tmp_path / "credentials" / "ann.json"
    assert _key.is_file() and (tmp_path / byok_crypto.MARKER).is_file()
    _key.rename(_key.with_name("away"))
    with pytest.raises(byok_crypto.ByokKeyError, match="restore it"):
        byok_crypto.load_key(tmp_path)
    assert not _key.exists(), "no new key was made"
    assert modal_creds.hint(tmp_path, "ann")["set"] is False and modal_creds.env_for(tmp_path, "ann") is None
    assert record.is_file() and modal_creds.tombstone(tmp_path, "ann") is None, "the record is kept, not deleted"
    assert byok_crypto.missing_problem(tmp_path) == byok_crypto.MSG_MISSING
    _key.with_name("away").rename(_key)  # the operator restores it: everything opens again
    assert modal_creds.env_for(tmp_path, "ann") == {"MODAL_TOKEN_ID": TID, "MODAL_TOKEN_SECRET": SECRET}


def test_a_record_without_the_marker_also_blocks_a_new_key(tmp_path: Path, _key: Path) -> None:
    """A state from before the marker: a stored record alone says a key existed."""
    assert modal_creds.save(tmp_path, "ann", TID, SECRET)
    (tmp_path / byok_crypto.MARKER).unlink()
    _key.unlink()
    assert byok_crypto.had_key(tmp_path)
    with pytest.raises(byok_crypto.ByokKeyError):
        byok_crypto.load_key(tmp_path)
    assert not _key.exists()


def test_a_tombstone_or_check_file_alone_does_not_count_as_a_record(tmp_path: Path) -> None:
    folder = tmp_path / "credentials"
    folder.mkdir()
    (folder / "ann.tomb.json").write_text("{}")
    (folder / "ann.check.json").write_text("{}")
    assert not byok_crypto.had_key(tmp_path)
    byok_crypto.load_key(tmp_path)  # first use: made


# ----- R2 -----------------------------------------------------------------------------------------------------------
@pytest.mark.usefixtures("authenv")
def test_with_an_unusable_key_the_check_says_the_servers_key_is_unavailable(api: Api, _key: Path,
                                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(modal_check, "start", lambda *a, **k: pytest.fail("a check was started"))
    sid = sign_in(api, "ann@example.com")
    body = json.dumps({"token_id": TID, "token_secret": SECRET}).encode()
    assert api.request("PUT", "api/me/modal", body, hdr(api, sid))[0] == 200
    user = next(p.stem for p in (api.app.state / "credentials").glob("*.json") if "." not in p.stem)
    for broken in ("mode", "gone"):
        if broken == "mode":
            _key.chmod(0o640)
        else:
            _key.chmod(0o600)
            _key.rename(_key.with_name("away"))
        status, _, data = api.request("POST", "api/me/modal/check", b"{}", hdr(api, sid))
        assert status == 503 and json.loads(data)["message"] == modal_creds.MSG_KEY_DOWN, broken
        assert "No token is set" not in data.decode()
        view = json.loads(api.request("GET", "api/me/modal", None, hdr(api, sid))[2])
        assert view["set"] is False and view["key_unavailable"] is True, broken
    monkeypatch.setenv("PROD_COMPUTE", "byok")
    assert run_on.parse({}, api.app.state, user) == (None, run_on.MSG_KEY_DOWN)
    _key.with_name("away").rename(_key)
    assert json.loads(api.request("GET", "api/me/modal", None, hdr(api, sid))[2])["key_unavailable"] is False


@pytest.mark.usefixtures("authenv")
def test_without_a_saved_token_the_check_still_says_no_token(api: Api) -> None:
    sid = sign_in(api, "bob@example.com")
    status, _, data = api.request("POST", "api/me/modal/check", b"{}", hdr(api, sid))
    assert status == 409 and json.loads(data)["message"] == modal_creds_routes.MSG_NONE


# ----- R3 -----------------------------------------------------------------------------------------------------------
def test_the_sweeper_removes_the_lock_once_the_tombstone_goes(tmp_path: Path) -> None:
    assert modal_creds.save(tmp_path, "ann", TID, SECRET) and modal_creds.save(tmp_path, "bob", TID, SECRET)
    folder = tmp_path / "credentials"
    now = time.time()
    modal_creds.sweep(tmp_path, now=now + modal_creds.IDLE_TTL_S + 10)  # both expire, tombstones written
    assert (folder / "ann.tomb.json").is_file() and (folder / "ann.lock").is_file()
    modal_creds.sweep(tmp_path, now=now + modal_creds.IDLE_TTL_S + 20)
    assert (folder / "ann.lock").is_file(), "the tombstone is young: the lock stays"
    assert modal_creds.save(tmp_path, "bob", TID, SECRET)  # bob saves again: a pair exists
    tomb_age = now + modal_creds.IDLE_TTL_S + modal_creds.TOMB_KEEP_S + 100
    (folder / "bob.tomb.json").write_text("{}")
    os.utime(folder / "bob.json", (tomb_age, tomb_age))  # fresh pair at sweep time
    modal_creds.sweep(tmp_path, now=tomb_age)
    assert not (folder / "ann.tomb.json").exists() and not (folder / "ann.lock").exists()
    assert (folder / "bob.lock").is_file() and (folder / "bob.json").is_file(), "a user with a pair keeps the lock"
    assert (tmp_path / byok_crypto.MARKER).is_file(), "the key marker is never swept"
