"""The 2026-11-03 go-live audit fixes of request authorization (docs/specs/prod-hardening.md items 15 and 16,
AC-PH14 to AC-PH16; docs/specs/byok-prod.md AC-BY14; docs/specs/source-credit.md AC-S15).

Real sessions through the sign-in routes, the real identity store, the real queue and the stub Part 6 catalog.
Account A owns the movements; account B is someone else; "anon" sends no cookie.
"""

from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import stat
import types
from typing import Any

import pytest

from auth_support import authenv, get, origin, outbox, plain_text, post, sign_in  # noqa: F401  authenv is a fixture
from part7 import auth, byok_crypto, creator, entry_access, modal_check, modal_creds_routes, prod_check
from part7 import quota, runner, server
from support import Api
from test_ghost import _anim
from test_private_default import follow, trainer, user_of

pytestmark = pytest.mark.usefixtures("authenv")
OTHER = "grace.hopper@example.com"
UNPUBLISHED, ONLY_ME, MINOR = "hidden-move-1a2b3c4d", "only-me-move-1a2b3c4d", "teen-move-1a2b3c4d"
# Every route that takes a movement id in its path (pre-mortem of the audit: a side route nobody checked). A new route
# of that kind belongs here. `me/` routes answer 401 to a signed-out caller, which says nothing about the movement.
MOVEMENT_ROUTES = (
    "catalog/api/entries/{e}",
    "api/labels/{e}",
    "api/narration/{e}",
    "api/narration/{e}/cue-1.wav",
    "api/takes-on/{e}",
    "api/teacher/{e}",
    "api/ghost/{e}.json",
    "api/source/entry/{e}",
    "api/programmes/{e}",
    "api/me/progress/{e}",
)
TID, SECRET = "ak-AuthzAuditToken0001", "as-AuthzAuditSecret0001"


def _movement(api: Api, entry: str, owner: str, **row: Any) -> str:
    """A movement of `owner` with a trainer job, an animation the ghost can draw and an access row; returns the job."""
    job_id = trainer(api, entry)
    api.app.child.entries[entry] = {"id": entry, "animation": f"anim-{entry}.json", "skeleton": None}
    api.app.child.files[f"anim-{entry}.json"] = json.dumps(_anim(3)).encode()
    entry_access.record(api.app.state, entry, trainer_job=job_id, owner=owner, **row)
    auth.identity(api.app).attach_entry(entry, owner, job_id)
    return job_id


@pytest.fixture()
def world(api: Api) -> types.SimpleNamespace:
    # the minor's movement has its own account: a 13 to 17 answer hides every movement of that account, which would
    # hide the other two for a reason that is not theirs
    a, b, m = sign_in(api), sign_in(api, OTHER), sign_in(api, "teen@example.com")
    owner, teen = user_of(api, a), user_of(api, m)
    jobs = {UNPUBLISHED: _movement(api, UNPUBLISHED, owner, published=False),
            ONLY_ME: _movement(api, ONLY_ME, owner, published=True, age_band="adult"),
            MINOR: _movement(api, MINOR, teen, published=True, age_band="minor")}
    assert auth.identity(api.app).set_only_me(ONLY_ME, owner, True)
    assert entry_access.get(api.app.state, MINOR)["published"] is False, "a minor's movement is never published"
    assert entry_access.visible(api.app.state, ONLY_ME, None, None), "only the only-me flag hides this one"
    return types.SimpleNamespace(api=api, a=a, b=b, owner=owner, jobs=jobs, sid={UNPUBLISHED: a, ONLY_ME: a, MINOR: m})


# ----- B1 and the enumeration: every movement route hides a hidden movement --------------------------------------------
@pytest.mark.parametrize("entry", [UNPUBLISHED, ONLY_ME, MINOR])
@pytest.mark.parametrize("route", MOVEMENT_ROUTES)
def test_every_movement_route_answers_404_for_a_hidden_movement(world: types.SimpleNamespace, route: str, entry: str) -> None:
    path = route.format(e=entry)
    status_b = get(world.api, path, cookie=world.b)[0]
    status_anon = get(world.api, path)[0]
    assert status_b == 404, f"{path} as another account answered {status_b}"
    assert status_anon == (401 if path.startswith("api/me/") else 404), f"{path} signed out answered {status_anon}"


def test_the_hidden_movements_are_in_no_list(world: types.SimpleNamespace) -> None:
    for cookie in (None, world.b):
        labels = get(world.api, "api/labels", cookie=cookie)[2]
        listed = json.dumps(get(world.api, "catalog/api/entries", cookie=cookie)[2])
        for entry in (UNPUBLISHED, ONLY_ME, MINOR):
            assert entry not in labels and entry not in listed


@pytest.mark.parametrize("entry", [UNPUBLISHED, ONLY_ME, MINOR])
def test_the_ghost_answers_the_owner_with_the_trainer_joints(world: types.SimpleNamespace, entry: str) -> None:
    status, _, body = get(world.api, f"api/ghost/{entry}.json", cookie=world.sid[entry])
    assert status == 200 and body["available"] is True and body["frames"], "the owner still follows their own movement"


@pytest.mark.parametrize("entry", [UNPUBLISHED, MINOR])
def test_the_ghost_answers_the_holder_of_the_creator_token(world: types.SimpleNamespace, entry: str) -> None:
    token = creator.token_for(world.api.app.state, world.jobs[entry])
    status, _, body = get(world.api, f"api/ghost/{entry}.json", headers={entry_access.HEADER: token})
    assert status == 200 and body["available"] is True
    assert get(world.api, f"api/ghost/{entry}.json", headers={entry_access.HEADER: "x" * 43})[0] == 404, "a wrong token"


def test_a_published_movement_still_answers_everyone(world: types.SimpleNamespace) -> None:
    entry = "open-move-1a2b3c4d"
    _movement(world.api, entry, world.owner, published=True, age_band="adult")
    for cookie in (None, world.b):
        assert get(world.api, f"api/ghost/{entry}.json", cookie=cookie)[0] == 200
        assert get(world.api, f"api/source/entry/{entry}", cookie=cookie)[0] == 200


# ----- R1: a take's credit is its owner's ------------------------------------------------------------------------
def test_the_credit_of_another_accounts_take_is_404(world: types.SimpleNamespace) -> None:
    job = follow(world.api, "lateral-raise", owner=world.owner)
    assert get(world.api, f"api/source/take/{job}", cookie=world.a)[0] == 200
    assert get(world.api, f"api/source/take/{job}", cookie=world.b)[0] == 404
    assert get(world.api, f"api/source/take/{job}")[0] == 404


# ----- R3: a cookie-carrying state change must come from this origin -------------------------------------------------
def _raw(api: Api, method: str, path: str, body: bytes, headers: dict[str, str]) -> tuple[int, Any]:
    status, _, data = api.request(method, path, body, headers)
    return status, json.loads(data or b"null")


@pytest.mark.parametrize("route", ["api/follow", "api/trainer", "api/people", "api/group", "api/challenges",
                                   "api/client-log", "api/jobs/0123456789ab/export"])
@pytest.mark.parametrize("sent", [{"Origin": "https://evil.example"}, {}, {"Sec-Fetch-Site": "same-site"}])
def test_a_cookie_from_another_site_starts_nothing(api: Api, route: str, sent: dict[str, str]) -> None:
    headers = {"Content-Type": "application/json", "Cookie": f"{auth.COOKIE}={sign_in(api)}", **sent}
    if "Sec-Fetch-Site" in sent:
        headers["Origin"] = origin(api)  # the right Origin, but the browser says the page was another site's
    status, body = _raw(api, "POST", route, b'{"upload_id": "0123456789abcdef"}', headers)
    assert status == 403 and body["message"] == server.MSG_CSRF


def test_the_origin_rule_leaves_signed_out_and_same_origin_requests_to_their_routes(api: Api) -> None:
    doc = b'{"upload_id": "0123456789abcdef", "entry_id": "lateral-raise"}'
    signed_out = _raw(api, "POST", "api/follow", doc, {"Content-Type": "application/json"})
    same = _raw(api, "POST", "api/follow", doc, {"Content-Type": "application/json", "Origin": origin(api),
                                                 "Cookie": f"{auth.COOKIE}={sign_in(api)}"})
    assert signed_out[0] != 403 and same[0] != 403, (signed_out, same)
    assert same[1]["message"] == server.MSG_NO_UPLOAD, "the route itself answered"


def test_a_cross_site_upload_with_a_cookie_is_refused_before_a_byte_is_kept(api: Api, tiny_mp4: Path) -> None:
    status, body = api.upload(tiny_mp4, headers={"Cookie": f"{auth.COOKIE}={sign_in(api)}", "Origin": "https://evil.example"})
    assert status == 403 and body["message"] == server.MSG_CSRF
    assert not api.app.uploads.exists() or not any(api.app.uploads.iterdir())


@pytest.mark.parametrize("ctype", ["text/plain", "application/x-www-form-urlencoded", ""])
def test_a_body_that_is_not_sent_as_json_is_415(api: Api, ctype: str) -> None:
    headers = {"Origin": origin(api), **({"Content-Type": ctype} if ctype else {})}
    status, body = _raw(api, "POST", "api/follow", b'{"upload_id": "0123456789abcdef"}', headers)
    assert status == 415 and body["message"] == server.MSG_NOT_JSON


# ----- R2: a malformed Content-Length on the delete routes -------------------------------------------------------
@pytest.mark.parametrize("path", ["api/entries/x-move-1a2b3c4d/delete", "api/jobs/0123456789ab/delete"])
def test_a_delete_with_a_malformed_length_is_400_not_a_crash(api: Api, path: str) -> None:
    conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=10)
    conn.putrequest("POST", api.app.base + path)
    for key, value in {"Content-Type": "application/json", "Origin": origin(api), "Content-Length": "abc"}.items():
        conn.putheader(key, value)
    conn.endheaders()
    resp = conn.getresponse()
    status, body = resp.status, json.loads(resp.read())
    conn.close()
    assert status == 400 and body["message"] == "The request has a Content-Length that is not a number."


# ----- R6: one client address rule for every limiter ----------------------------------------------------------------
def _h(peer: str, **headers: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(client_address=(peer, 5000), headers=headers)


def test_one_client_address_rule_trusts_a_forwarded_address_from_the_gateway_only() -> None:
    assert auth.client_addr(_h("127.0.0.1", **{"Cf-Connecting-Ip": "203.0.113.7"})) == "203.0.113.7"
    assert auth.client_addr(_h("127.0.0.1", **{"X-Forwarded-For": "203.0.113.8"})) == "203.0.113.8"
    assert auth.client_addr(_h("127.0.0.1", **{"X-Forwarded-For": "1.1.1.1, 2.2.2.2"})) is None, "a chain is not trusted"
    assert auth.client_addr(_h("127.0.0.1")) is None, "a direct local probe"
    spoofed = _h("198.51.100.4", **{"Cf-Connecting-Ip": "203.0.113.7"})
    assert auth.client_addr(spoofed) == "198.51.100.4", "a header from a non-loopback peer is ignored"
    assert server._Handler._visitor(spoofed) == "198.51.100.4", "the upload, job and challenge limits use the same rule"
    assert auth.client_key(spoofed) == quota.visitor_key("198.51.100.4")
    assert auth.client_key(_h("127.0.0.1")) == quota.visitor_key("127.0.0.1")


# ----- R7 and R4: prod refuses a signed-out upload and model upload --------------------------------------------------
@pytest.fixture()
def prod(api: Api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Api:
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    for name in list(os.environ):
        if name.startswith(("SIMON7_KEYS", "SIMON7_MAIL", "SIMON7_PUBLIC", "STAGING", "SIMON7_STAGING")):
            monkeypatch.delenv(name, raising=False)
    for name, value in {"FIRM_ENV": "prod", "PROD_SECRETS_DIR": str(secrets), "PROD_PUBLIC_URL": "https://simon.example",
                        "PROD_COMPUTE": "byok", "SIMON7_BYOK": "on"}.items():
        monkeypatch.setenv(name, value)
    return api


GATEWAY = {"Host": "simon.example", "Cf-Connecting-Ip": "203.0.113.7", "Origin": "https://simon.example"}


def test_prod_answers_401_to_a_signed_out_upload_and_keeps_nothing(prod: Api, tiny_mp4: Path) -> None:
    status, body = prod.upload(tiny_mp4, headers=GATEWAY)
    assert status == 401 and body["message"] == server.MSG_UPLOAD_SIGN_IN
    assert not prod.app.uploads.exists() or not any(prod.app.uploads.iterdir())


def test_prod_lets_a_signed_in_upload_past_the_sign_in_rule(prod: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "current_user", lambda h: "u-signed-in")
    status, body = prod.upload(tiny_mp4, headers=GATEWAY)
    assert status != 401 and body.get("message") != server.MSG_UPLOAD_SIGN_IN


def test_prod_answers_401_to_a_signed_out_model_upload(prod: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    from part7 import model_import

    head = {**GATEWAY, "Content-Type": "model/gltf-binary"}
    status, body = _raw(prod, "POST", "api/models?licence=cc0", b"glTF" + b"\0" * 64, head)
    assert status == 401 and body["message"] == model_import.MSG_SIGN_IN_MODEL
    monkeypatch.setattr(auth, "current_user", lambda h: "u-signed-in")
    status, body = _raw(prod, "POST", "api/models?licence=cc0", b"glTF" + b"\0" * 64, head)
    assert status != 401, body


def test_outside_prod_a_signed_out_upload_is_still_kept(api: Api, tiny_mp4: Path) -> None:
    assert api.upload(tiny_mp4)[0] == 201


# ----- byok R7: the pepper never sits in the state dir in prod ------------------------------------------------------
def test_the_start_check_refuses_a_pepper_in_the_state_dir(tmp_path: Path) -> None:
    state = tmp_path / "app"
    (state / "identity").mkdir(parents=True)
    env = {"SIMON7_STATE_DIR": str(state)}
    assert prod_check._pepper_problem(env) is None
    (state / "identity" / "SIMON7_AUTH_PEPPER").write_text("ab" * 32, encoding="utf-8")
    found = [p for p in prod_check.problems(env) if "SIMON7_AUTH_PEPPER" in p]
    assert found == ["SIMON7_AUTH_PEPPER is in the state dir (identity/); move it to PROD_SECRETS_DIR so no backup holds it"]
    assert "ab" * 32 not in " ".join(prod_check.problems(env)), "no value in the message"


def test_prod_writes_the_pepper_to_the_secrets_dir_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secrets, state = tmp_path / "secrets", tmp_path / "state"
    secrets.mkdir()
    state.mkdir()
    monkeypatch.delenv("SIMON7_KEYS_DIR", raising=False)
    monkeypatch.setenv("FIRM_ENV", "prod")
    monkeypatch.setenv("PROD_SECRETS_DIR", str(secrets))
    first = auth._pepper(state)
    assert (secrets / "SIMON7_AUTH_PEPPER").is_file() and not (state / "identity" / "SIMON7_AUTH_PEPPER").exists()
    assert auth._pepper(state) == first
    (secrets / "SIMON7_AUTH_PEPPER").unlink()
    secrets.chmod(stat.S_IRUSR | stat.S_IXUSR)  # the secrets dir cannot be written: still nothing in the state dir
    try:
        auth._pepper(state)
    finally:
        secrets.chmod(stat.S_IRWXU)
    assert not (state / "identity" / "SIMON7_AUTH_PEPPER").exists()


# ----- byok R3: a save mails the account; the check is limited per token ---------------------------------------------
@pytest.fixture()
def byok(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    monkeypatch.setenv(byok_crypto.KEY_ENV, str(tmp_path_factory.mktemp("byok-key") / "k"))
    monkeypatch.delenv("FIRM_ENV", raising=False)
    monkeypatch.setattr(modal_check, "start", lambda state, user_id, run=None: True)  # Modal is never called
    for limit in modal_creds_routes._CHECKS:
        limit._hits.clear()


def _modal(api: Api, method: str, sid: str, route: str = "api/me/modal", doc: Any = None) -> int:
    return post(api, route, doc, cookie=sid, headers=None)[0] if method == "POST" else api.request(
        method, route, json.dumps(doc or {}).encode(),
        {"Content-Type": "application/json", "Origin": origin(api), "Cookie": f"{auth.COOKIE}={sid}"})[0]


def _new_mail(api: Api, before: set[Path]) -> list[str]:
    """The text of each mail written since `before` (names start with the clock, which can step back here)."""
    return [plain_text(path) for path in outbox(api) if path not in before]


@pytest.mark.usefixtures("byok")
def test_a_save_and_a_replace_each_mail_the_account(api: Api) -> None:
    sid = sign_in(api)
    before = set(outbox(api))
    assert _modal(api, "PUT", sid, doc={"token_id": TID, "token_secret": SECRET}) == 200
    [added] = _new_mail(api, before)
    assert added.startswith("A Modal token was added to your Simon account at ") and "ends in 0001" in added
    assert "remove the token" in added and SECRET not in added and TID not in added
    before = set(outbox(api))
    assert _modal(api, "PUT", sid, doc={"token_id": "ak-AuthzAuditToken0002", "token_secret": SECRET}) == 200
    [replaced] = _new_mail(api, before)
    assert replaced.startswith("The Modal token on your Simon account was replaced at ") and "ends in 0002" in replaced
    before = set(outbox(api))
    assert _modal(api, "PUT", sid, doc={"token_id": "ak-short", "token_secret": SECRET}) == 400
    assert _new_mail(api, before) == [], "a refused save mails nothing"


@pytest.mark.usefixtures("byok")
def test_the_check_is_limited_per_token_across_accounts(api: Api) -> None:
    a, b, c = sign_in(api), sign_in(api, OTHER), sign_in(api, "third@example.com")
    for sid in (a, b):
        assert _modal(api, "PUT", sid, doc={"token_id": TID, "token_secret": SECRET}) == 200
    assert _modal(api, "PUT", c, doc={"token_id": "ak-AuthzAuditOther0003", "token_secret": SECRET}) == 200
    assert _modal(api, "POST", a, "api/me/modal/check") == 202
    assert _modal(api, "POST", b, "api/me/modal/check") == 429, "a second account testing the same token"
    assert _modal(api, "POST", c, "api/me/modal/check") == 202, "another token is not slowed"


# ----- byok R5: a step log hides what the job knows and token shapes --------------------------------------------------
def test_a_step_log_hides_secret_values_and_token_shapes() -> None:
    env = {"MODAL_TOKEN_ID": TID, "MODEL_API_KEY": "meta-key-value-12345", "HF_TOKEN": "hf_known", "SIMON7_FLAG": "on",
           "SOME_PASSWORD": "pw-value-9999"}
    redact = runner._hiding(lambda text: text, env)
    line = (f"id {TID} key meta-key-value-12345 pw pw-value-9999 hf hf_{'a' * 30} pair as-{'B' * 20} "
            f"ak-{'c' * 18} flag on peak-performance-as-is-ok")
    out = redact(line)
    for secret in (TID, "meta-key-value-12345", "pw-value-9999", f"hf_{'a' * 30}", f"as-{'B' * 20}", f"ak-{'c' * 18}"):
        assert secret not in out
    assert "flag on" in out and "peak-performance-as-is-ok" in out, "ordinary text and short switches stay"
    assert runner._hiding(lambda text: text, None)(f"log hf_{'z' * 24}") == "log <redacted>"


def test_a_step_log_of_a_run_hides_a_token_shape_the_job_never_held(tmp_path: Path) -> None:
    leaked = "hf_" + "Q" * 30
    log = tmp_path / "step.log"
    step = runner.run(7, ["python3", "-c", f"print('container says {leaked}')"], cwd=tmp_path, log_path=log, timeout_s=30)
    assert step.exit == 0 and leaked not in log.read_text(encoding="utf-8") and "<redacted>" in log.read_text(encoding="utf-8")
