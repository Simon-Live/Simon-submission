"""BYOK-H2, BYOK-M3, BYOK-M4 (docs/specs/byok-prod.md): the credential store is encrypted at rest, bound to its owner,
expires after 24 h unused (on use and by the sweeper), and its routes are rate limited. Modal is never called."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import stat
import threading
import time
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pytest

from auth_support import authenv, get, origin, sign_in  # noqa: F401
from part7 import auth, byok_crypto, modal_check, modal_creds, modal_creds_routes, run_on
from support import Api

TID, SECRET = "ak-CanaryTokenId0001", "as-CanarySecretValue0001"
HOUR = 3600.0


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> Path:
    key = tmp_path_factory.mktemp("byok-key") / "k"
    monkeypatch.setenv(byok_crypto.KEY_ENV, str(key))
    monkeypatch.delenv("FIRM_ENV", raising=False)
    return key


def files_holding(root: Path, *values: str) -> list[Path]:
    """Every file under `root` whose bytes hold any of `values`."""
    return [p for p in root.rglob("*") if p.is_file() and any(v.encode() in p.read_bytes() for v in values)]


def age(path: Path, seconds: float) -> None:
    then = time.time() - seconds
    os.utime(path, (then, then))


# ----- encryption at rest (BYOK-M4) ---------------------------------------------------------------------------------
def test_the_file_holds_no_value_and_opens_only_for_its_owner(tmp_path: Path) -> None:
    assert modal_creds.save(tmp_path, "ann", TID, SECRET)
    path = tmp_path / "credentials" / "ann.json"
    assert files_holding(tmp_path, TID, SECRET) == [], "encrypted: the value is in no file under the state dir"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert modal_creds.env_for(tmp_path, "ann") == {"MODAL_TOKEN_ID": TID, "MODAL_TOKEN_SECRET": SECRET}
    (tmp_path / "credentials" / "bob.json").write_bytes(path.read_bytes())  # copied to another owner's name
    assert modal_creds.env_for(tmp_path, "bob") is None, "the owner is associated data: another name does not open"
    assert not (tmp_path / "credentials" / "bob.json").exists() and modal_creds.tombstone(tmp_path, "bob") == "invalid"


def _flip(box: str, at: int) -> str:
    raw = bytearray(base64.b64decode(box))
    raw[at] ^= 0x01
    return base64.b64encode(bytes(raw)).decode("ascii")


def test_a_tampered_box_is_refused_and_deleted(tmp_path: Path) -> None:
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    path = tmp_path / "credentials" / "ann.json"
    doc = json.loads(path.read_text())
    doc["box"] = _flip(doc["box"], -1)  # one bit of the tag
    path.write_text(json.dumps(doc))
    assert modal_creds.env_for(tmp_path, "ann") is None and not path.exists()
    assert modal_creds.tombstone(tmp_path, "ann") == "invalid"


def test_aes_gcm_box_layout_and_every_tamper_point() -> None:
    key = AESGCM.generate_key(bit_length=256)
    box = byok_crypto.seal(key, b"value", b"ann")
    raw = base64.b64decode(box)
    assert raw[0] == byok_crypto.VERSION and len(raw) == 1 + 12 + len(b"value") + 16, "version, 96-bit nonce, ct, tag"
    assert byok_crypto.open_(key, box, b"ann") == b"value"
    for at in (0, 1, 13, len(raw) - 1):  # version byte, nonce, ciphertext, tag
        assert byok_crypto.open_(key, _flip(box, at), b"ann") is None, f"a flipped bit at {at} does not open"
    assert byok_crypto.open_(key, box[:-8], b"ann") is None and byok_crypto.open_(key, "not base64!", b"ann") is None
    assert byok_crypto.open_(key, {"v": 1}, b"ann") is None


def test_the_wrong_owner_or_the_wrong_key_does_not_open() -> None:
    key = AESGCM.generate_key(bit_length=256)
    box = byok_crypto.seal(key, b"value", b"simon7-byok:v3:ann:g1")
    assert byok_crypto.open_(key, box, b"simon7-byok:v3:bob:g1") is None, "another owner"
    assert byok_crypto.open_(key, box, b"simon7-byok:v3:ann:g2") is None, "another save of the same owner"
    assert byok_crypto.open_(AESGCM.generate_key(bit_length=256), box, b"simon7-byok:v3:ann:g1") is None, "another key"


def test_every_write_draws_a_fresh_nonce() -> None:
    key = AESGCM.generate_key(bit_length=256)
    nonces = {base64.b64decode(byok_crypto.seal(key, b"same value", b"ann"))[1:13] for _ in range(2000)}
    assert len(nonces) == 2000


def test_a_save_under_another_key_file_does_not_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path_factory: pytest.TempPathFactory) -> None:
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    monkeypatch.setenv(byok_crypto.KEY_ENV, str(tmp_path_factory.mktemp("other-key") / "k"))
    assert modal_creds.env_for(tmp_path, "ann") is None
    assert files_holding(tmp_path, TID, SECRET) == []


def test_a_key_file_of_the_wrong_length_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    short = tmp_path.parent / f"{tmp_path.name}-short.key"
    short.write_text("ab" * 16)
    os.chmod(short, 0o600)
    monkeypatch.setenv(byok_crypto.KEY_ENV, str(short))
    with pytest.raises(byok_crypto.ByokKeyError):
        modal_creds.save(tmp_path, "ann", TID, SECRET)


def test_the_159ec5d0_hmac_format_is_dropped_not_migrated(tmp_path: Path) -> None:
    folder = tmp_path / "credentials"
    folder.mkdir()
    old = {"v": 2, "gen": "0123abcd", "box": {"v": 1, "n": "AAAA", "c": "AAAA", "t": "AAAA"}}
    (folder / "ann.json").write_text(json.dumps(old))
    assert modal_creds.is_set(tmp_path, "ann") is False and not (folder / "ann.json").exists()
    assert modal_creds.tombstone(tmp_path, "ann") == "invalid"


def test_the_key_file_lives_outside_the_state_dir_and_is_private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                 _key: Path) -> None:
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    assert _key.is_file() and stat.S_IMODE(_key.stat().st_mode) == 0o600
    assert not str(_key.resolve()).startswith(str(tmp_path.resolve()))
    monkeypatch.setenv(byok_crypto.KEY_ENV, str(tmp_path / "inside.key"))
    with pytest.raises(byok_crypto.ByokKeyError):
        modal_creds.save(tmp_path, "ann", TID, SECRET)
    monkeypatch.setenv(byok_crypto.KEY_ENV, str(_key))
    os.chmod(_key, 0o644)
    with pytest.raises(byok_crypto.ByokKeyError):
        modal_creds.save(tmp_path, "bob", TID, SECRET)
    assert modal_creds.env_for(tmp_path, "ann") is None, "a key others can read is not used"
    assert (tmp_path / "credentials" / "ann.json").exists(), "and the user's file is kept for when it is fixed"


def test_prod_without_the_env_uses_the_prod_secrets_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(byok_crypto.KEY_ENV)
    monkeypatch.setenv("FIRM_ENV", "prod")
    monkeypatch.setenv(byok_crypto.PROD_DIR_ENV, str(tmp_path / "secrets"))
    assert byok_crypto.key_path(tmp_path / "state") == tmp_path / "secrets" / byok_crypto.KEY_NAME
    monkeypatch.delenv("FIRM_ENV")
    assert byok_crypto.key_path(tmp_path / "state") == tmp_path.resolve() / f".{byok_crypto.KEY_NAME}"


def test_the_plaintext_file_of_f18fc24e_is_deleted_on_read(tmp_path: Path) -> None:
    folder = tmp_path / "credentials"
    folder.mkdir()
    (folder / "ann.json").write_text(json.dumps({"token_id": TID, "token_secret": SECRET}))
    assert modal_creds.is_set(tmp_path, "ann") is False
    assert files_holding(tmp_path, TID, SECRET) == []


# ----- idle expiry (BYOK-H2) ----------------------------------------------------------------------------------------
def test_a_25_hour_old_record_is_gone_on_use_and_its_value_in_no_file(tmp_path: Path) -> None:
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    modal_check._store(tmp_path, "ann", modal_check.OK, modal_creds.generation(tmp_path, "ann"))
    age(tmp_path / "credentials" / "ann.json", 25 * HOUR)
    assert modal_creds.env_for(tmp_path, "ann") is None
    assert not (tmp_path / "credentials" / "ann.json").exists()
    assert not (tmp_path / "credentials" / "ann.check.json").exists(), "the check result goes with it"
    assert files_holding(tmp_path, TID, SECRET) == []
    assert modal_creds.tombstone(tmp_path, "ann") == "expired"
    assert modal_creds.hint(tmp_path, "ann") == {"set": False, "token_id_hint": None, "expired": True}


def test_a_25_hour_old_record_is_gone_by_the_sweeper_and_at_start_up(tmp_path: Path) -> None:
    for user in ("ann", "bob", "cy"):
        modal_creds.save(tmp_path, user, TID, SECRET)
    age(tmp_path / "credentials" / "ann.json", 25 * HOUR)
    age(tmp_path / "credentials" / "bob.json", 23 * HOUR)
    assert modal_creds.sweep(tmp_path)["expired"] == 1
    assert not (tmp_path / "credentials" / "ann.json").exists() and modal_creds.is_set(tmp_path, "bob")
    age(tmp_path / "credentials" / "cy.json", 25 * HOUR)
    stop = modal_creds.start_sweeper(tmp_path, interval_s=3600)
    try:
        assert not (tmp_path / "credentials" / "cy.json").exists(), "start-up sweeps before it returns"
        assert modal_creds.start_sweeper(tmp_path) is stop, "one sweeper per state dir"
    finally:
        stop.set()
    assert modal_creds.tombstone(tmp_path, "cy") == "expired"


def test_use_resets_the_idle_clock_and_a_view_does_not(tmp_path: Path) -> None:
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    path = tmp_path / "credentials" / "ann.json"
    age(path, 23 * HOUR)
    assert modal_creds.is_set(tmp_path, "ann") and modal_creds.hint(tmp_path, "ann")["set"]
    assert time.time() - path.stat().st_mtime > 22 * HOUR, "showing the Me page is not use"
    assert modal_creds.env_for(tmp_path, "ann") is not None
    assert time.time() - path.stat().st_mtime < 60, "a job about to run is use"
    age(path, 2 * HOUR)
    assert modal_creds.sweep(tmp_path)["expired"] == 0 and modal_creds.is_set(tmp_path, "ann")


def test_the_sweeper_removes_stale_temp_files_orphans_and_old_tombstones(tmp_path: Path) -> None:
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    folder = tmp_path / "credentials"
    stale, fresh = folder / ".tmp-dead", folder / ".tmp-live"
    stale.write_text(SECRET)
    fresh.write_text("{}")
    age(stale, 2 * modal_creds.TMP_MAX_AGE_S)
    (folder / "gone.check.json").write_text("{}")
    tomb = folder / "old.tomb.json"
    tomb.write_text(json.dumps({"reason": "expired", "at": 0}))
    age(tomb, modal_creds.TOMB_KEEP_S + 10)
    done = modal_creds.sweep(tmp_path)
    assert done == {"expired": 0, "tmp": 1, "orphans": 1}
    assert not stale.exists() and fresh.exists() and not tomb.exists() and modal_creds.is_set(tmp_path, "ann")
    assert files_holding(tmp_path, SECRET) == []


def test_saving_again_clears_the_tombstone(tmp_path: Path) -> None:
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    age(tmp_path / "credentials" / "ann.json", 25 * HOUR)
    modal_creds.sweep(tmp_path)
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    assert modal_creds.tombstone(tmp_path, "ann") is None and modal_creds.hint(tmp_path, "ann")["expired"] is False


def test_remove_leaves_nothing_of_the_user(tmp_path: Path) -> None:
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    modal_creds.save(tmp_path, "bob", TID, SECRET)
    assert modal_creds.remove(tmp_path, "ann") is True
    assert sorted(p.name for p in (tmp_path / "credentials").iterdir()) == ["bob.json", "bob.lock"]
    assert modal_creds.remove(tmp_path, "ann") is False


def test_the_per_user_lock_keeps_concurrent_saves_reads_and_sweeps_consistent(tmp_path: Path) -> None:
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    errors: list[BaseException] = []

    def hammer(work: Any) -> None:
        try:
            for _ in range(30):
                work()
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(w,)) for w in (
        lambda: modal_creds.save(tmp_path, "ann", TID, SECRET),
        lambda: modal_creds.env_for(tmp_path, "ann"),
        lambda: modal_creds.sweep(tmp_path),
        lambda: modal_creds.hint(tmp_path, "ann"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == []
    assert modal_creds.env_for(tmp_path, "ann") == {"MODAL_TOKEN_ID": TID, "MODAL_TOKEN_SECRET": SECRET}
    assert modal_creds.tombstone(tmp_path, "ann") is None, "no read ever saw a half-written file"
    assert not [p for p in (tmp_path / "credentials").iterdir() if p.name.startswith(".tmp-")]


def test_health_fields_report_the_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    assert run_on.health_fields() == {"compute": "host", "byok_idle_ttl_s": 86400}
    monkeypatch.setenv("FIRM_ENV", "prod")
    fields = run_on.health_fields()
    assert fields["compute"] == "byok" and isinstance(fields["byok_idle_ttl_s"], int) and fields["byok_idle_ttl_s"] <= 86400


# ----- routes: rate limits, HEAD, the key not set up (BYOK-M3, R3, R7) ----------------------------------------------
def _hdr(api: Api, sid: str) -> dict[str, str]:
    return {"Content-Type": "application/json", "Origin": origin(api), "Cookie": f"{auth.COOKIE}={sid}"}


@pytest.mark.usefixtures("authenv")
def test_put_is_rate_limited_per_user(api: Api) -> None:
    sid = sign_in(api, "ann@example.com")
    body = json.dumps({"token_id": TID, "token_secret": SECRET}).encode()
    codes = [api.request("PUT", "api/me/modal", body, _hdr(api, sid))[0] for _ in range(modal_creds_routes.PUT_LIMIT[0] + 1)]
    assert codes[:-1] == [200] * modal_creds_routes.PUT_LIMIT[0] and codes[-1] == 429
    other = sign_in(api, "bob@example.com")
    assert api.request("PUT", "api/me/modal", body, _hdr(api, other))[0] == 200, "another user has their own limit"


@pytest.mark.usefixtures("authenv")
def test_the_check_is_rate_limited_per_user(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(modal_check, "start", lambda state, user_id, run=None: True)
    sid = sign_in(api, "cy@example.com")
    api.request("PUT", "api/me/modal", json.dumps({"token_id": TID, "token_secret": SECRET}).encode(), _hdr(api, sid))
    first = api.request("POST", "api/me/modal/check", b"{}", _hdr(api, sid))
    second = api.request("POST", "api/me/modal/check", b"{}", _hdr(api, sid))
    assert first[0] == 202 and second[0] == 429
    assert json.loads(second[2])["message"] == modal_creds_routes.MSG_SLOW_DOWN


@pytest.mark.usefixtures("authenv")
def test_head_sends_no_body(api: Api) -> None:
    sid = sign_in(api, "dee@example.com")
    status, _, body = api.request("HEAD", "api/me/modal", None, {"Cookie": f"{auth.COOKIE}={sid}"})
    assert status == 200 and body == b""


@pytest.mark.usefixtures("authenv")
def test_a_key_file_that_is_not_usable_is_503_with_no_detail(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(byok_crypto.KEY_ENV, str(api.app.state / "inside.key"))
    sid = sign_in(api, "eve@example.com")
    status, _, body = api.request("PUT", "api/me/modal", json.dumps({"token_id": TID, "token_secret": SECRET}).encode(),
                                  _hdr(api, sid))
    assert status == 503 and json.loads(body)["message"] == modal_creds_routes.MSG_NO_KEY
    assert b"inside.key" not in body and SECRET.encode() not in body
    said = json.loads(body)["message"]  # go-live BYOK N4: the server's fault, worded as the card's key_unavailable line
    fault = "That is a fault on the server, not your token"
    assert "not set up" not in said and fault in said and fault in modal_creds.MSG_KEY_DOWN


@pytest.mark.usefixtures("authenv")
def test_get_says_expired_after_the_sweep(api: Api) -> None:
    sid = sign_in(api, "fay@example.com")
    api.request("PUT", "api/me/modal", json.dumps({"token_id": TID, "token_secret": SECRET}).encode(), _hdr(api, sid))
    user = auth.identity(api.app).session_user(sid)
    age(api.app.state / "credentials" / f"{user}.json", 25 * HOUR)
    modal_creds.sweep(api.app.state)
    doc = get(api, "api/me/modal", sid)[2]
    assert doc["set"] is False and doc["expired"] is True and doc["idle_ttl_s"] == 86400
