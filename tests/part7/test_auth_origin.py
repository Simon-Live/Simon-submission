"""Sign-in on the app's own origin (TICKET-177, ADR-0014): route root, cookie scope, Origin check, shared-origin refusal.

The hub's `route: root` serves the app at `/` on its own port and tunnel hostname and leaves `STAGING_BASE_PATH` empty.
Mail providers are faked: no test calls a real SMTP server or mail API.
"""

from __future__ import annotations

import io
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Iterator
from urllib import error as urlerror

import pytest

from auth_support import EMAIL, authenv, get, post  # noqa: F401
from part7 import auth, auth_routes, config, mail, server
from support import Api, FakeChild, make_lock

HOST = "simon-abc.tunnel.example"
TUNNEL = {"Host": HOST, "Origin": f"https://{HOST}", "Cf-Connecting-Ip": "203.0.113.5", "X-Forwarded-Proto": "https"}
MSG = mail.build_message  # alias for brevity


@pytest.fixture()
def root_api(tmp_path: Path, state_dir: Path) -> Iterator[Api]:
    """The app at base path `/`, as the hub's root route serves it."""
    child = FakeChild(tmp_path / "catalog")
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<h1>Simon</h1>", encoding="utf-8")
    app = server.build_app(state_dir, "/", child=child, lock=make_lock(), web_dir=web, phrasing="template")
    http = server.make_server(app)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    yield Api(app, http)
    http.shutdown()
    http.server_close()
    app.queue.close()
    child.close()


def provider_keys(keys: Path) -> None:
    (keys / "SIMON7_MAIL_FROM").write_text("Simon <signin@example.com>\n")
    (keys / "SIMON7_MAIL_API_KEY").write_text("re_test_0123456789\n")


def a_message() -> Any:
    return MSG("ada@example.com", "S <s@example.com>", "123456", "https://x/#/signin/t", mail.datetime.now(mail.timezone.utc))


@pytest.fixture()
def sent(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """A fake mail API: records (url, key, message) instead of calling a provider."""
    box: list[Any] = []
    monkeypatch.setattr(mail, "_api_send", lambda url, key, msg: box.append((url, key, msg)) or True)
    return box


def wait_for(box: list[Any]) -> Any:
    for _ in range(100):
        if box:
            return box[-1]
        time.sleep(0.02)
    raise AssertionError("no mail was sent")


def test_staging_route_reads_the_route_then_the_base_path(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("STAGING_ROUTE", "STAGING_BASE_PATH"):
        monkeypatch.delenv(name, raising=False)
    assert config.staging_route() is None and mail.is_local()
    monkeypatch.setenv("STAGING_BASE_PATH", "/simon-part-7/")
    assert config.staging_route() == "prefix" and not mail.is_local()
    monkeypatch.setenv("STAGING_BASE_PATH", "/")
    assert config.staging_route() == "root"
    monkeypatch.setenv("STAGING_BASE_PATH", "")  # the hub's root route leaves it empty
    assert config.staging_route() is None
    monkeypatch.setenv("STAGING_ROUTE", "root")
    assert config.staging_route() == "root" and not mail.is_local()  # root mode is staging, not local
    monkeypatch.setenv("STAGING_ROUTE", "bogus")
    assert config.staging_route() is None


@pytest.mark.parametrize("route,expect", [("root", "api"), ("prefix", "off"), ("strip", "off")])
def test_provider_is_used_only_on_the_own_origin(authenv, monkeypatch: pytest.MonkeyPatch, route: str, expect: str) -> None:
    provider_keys(authenv)
    monkeypatch.setenv("STAGING_ROUTE", route)
    assert mail.select_transport() == expect
    assert mail.provider_blocked_by_origin() is (route != "root")


def test_no_provider_keeps_signin_off_on_the_own_origin(authenv, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAGING_ROUTE", "root")
    assert mail.select_transport() == "off" and mail.file_refused_on_staging()  # the outbox is never used on staging


def test_prefix_origin_stays_off_with_keys_and_logs_one_line(authenv, root_api: Api, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    provider_keys(authenv)
    monkeypatch.setenv("STAGING_ROUTE", "prefix")
    with caplog.at_level(logging.INFO, logger="part7"):
        assert get(root_api, "api/auth/me")[2] == {"available": False, "signed_in": False}
        assert post(root_api, "api/auth/start", {"email": EMAIL}, TUNNEL)[0] == 404
    assert len([r for r in caplog.records if "shares the gateway origin" in r.getMessage()]) == 1 and "re_test" not in caplog.text


def test_own_origin_sign_in_end_to_end_with_a_fake_mail_api(authenv, root_api: Api, monkeypatch: pytest.MonkeyPatch, sent: list[Any]) -> None:
    provider_keys(authenv)
    monkeypatch.setenv("STAGING_ROUTE", "root")
    assert get(root_api, "api/auth/me")[2] == {"available": True, "signed_in": False}
    assert post(root_api, "api/auth/start", {"email": EMAIL}, TUNNEL)[0] == 202
    url, key, msg = wait_for(sent)
    assert url == mail.DEFAULT_API_URL and key == "re_test_0123456789" and msg["From"] == "Simon <signin@example.com>"
    text = msg.get_body(("plain",)).get_content()
    code = re.search(r"Your code: (\d{6})", text).group(1)
    assert f"https://{HOST}/#/signin/" in text  # the link carries the tunnel host and the root base path
    status, head, _ = post(root_api, "api/auth/verify", {"email": EMAIL, "code": code}, TUNNEL)
    cookie = head["set-cookie"]
    assert status == 200 and re.match(r"^s7_sid=[A-Za-z0-9_-]{43}; Path=/; HttpOnly; SameSite=Lax; Max-Age=\d+; Secure$", cookie)
    sid = re.match(r"s7_sid=([^;]*)", cookie).group(1)
    me = get(root_api, "api/auth/me", cookie=sid)[2]
    assert me["signed_in"] and me["email"] == "ada.lovelace@example.com"


def test_origin_check_accepts_the_tunnel_origin_and_refuses_a_sibling(authenv, root_api: Api, monkeypatch: pytest.MonkeyPatch, sent: list[Any]) -> None:  # AC-2
    provider_keys(authenv)
    monkeypatch.setenv("STAGING_ROUTE", "root")
    assert post(root_api, "api/auth/start", {"email": EMAIL}, TUNNEL)[0] == 202
    sibling = {**TUNNEL, "Origin": "https://gateway-xyz.tunnel.example", "Sec-Fetch-Site": "cross-site"}  # a page on another origin
    status, _, body = post(root_api, "api/auth/start", {"email": EMAIL}, sibling)
    assert status == 403 and body["message"] == auth_routes.MSG_CSRF
    under_same_parent = {**TUNNEL, "Origin": f"https://other.{HOST}"}  # another host is another origin
    assert post(root_api, "api/auth/signout", {}, under_same_parent)[0] == 403


def test_cookie_header_path_is_the_base_path(root_api: Api) -> None:
    class H:
        app = root_api.app
        client_address = ("127.0.0.1", 1)
        headers = {"Cf-Connecting-Ip": "1.2.3.4"}

    assert auth.cookie_header(H(), "abc") == "s7_sid=abc; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000; Secure"
    assert auth.cookie_header(H(), None).endswith("Max-Age=0; Secure")


def test_mail_api_failure_logs_the_outcome_only(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    def refuse(req: Any, timeout: int) -> Any:
        raise urlerror.HTTPError(req.full_url, 403, "no ada@example.com", {}, io.BytesIO(b"secret body"))

    monkeypatch.setattr(mail.urlrequest, "urlopen", refuse)
    with caplog.at_level(logging.INFO, logger="part7"):
        assert mail._api_send(mail.DEFAULT_API_URL, "re_key_value", a_message()) is False
        assert mail._api_send("http://insecure.example/mail", "re_key_value", a_message()) is False  # https only
    assert "HTTP 403" in caplog.text
    for leaked in ("ada@example.com", "re_key_value", "secret body"):
        assert leaked not in caplog.text


def test_mail_api_posts_resend_style_json_with_a_bearer_key(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class Resp:
        status = 200

        def __enter__(self) -> "Resp":
            return self

        def __exit__(self, *a: object) -> None:
            return None

    def fake(req: Any, timeout: int) -> Resp:
        seen.update(url=req.full_url, auth=req.get_header("Authorization"), body=json.loads(req.data), method=req.get_method())
        return Resp()

    monkeypatch.setattr(mail.urlrequest, "urlopen", fake)
    assert mail._api_send("https://mail.example.com/v1/send", "re_k", a_message()) is True
    assert seen["method"] == "POST" and seen["auth"] == "Bearer re_k" and seen["url"] == "https://mail.example.com/v1/send"
    assert seen["body"]["to"] == ["ada@example.com"] and "Your code: 123456" in seen["body"]["text"] and "<strong>123456</strong>" in seen["body"]["html"]


def test_smtp_settings_from_separate_key_files(authenv) -> None:
    assert mail.smtp_url() is None and mail.provider() is None
    (authenv / "SIMON7_SMTP_HOST").write_text("smtp.example.com\n")
    assert mail.smtp_url() == "smtp://smtp.example.com:587" and mail.provider() is None  # no sender yet
    (authenv / "SIMON7_MAIL_FROM").write_text("Simon <signin@example.com>\n")
    assert mail.provider() == "smtp"
    (authenv / "SIMON7_SMTP_USER").write_text("us@er\n")
    (authenv / "SIMON7_SMTP_PASSWORD").write_text("p/w\n")
    (authenv / "SIMON7_SMTP_PORT").write_text("465\n")
    assert mail.smtp_url() == "smtps://us%40er:p%2Fw@smtp.example.com:465"
    (authenv / "SIMON7_SMTP_URL").write_text("smtps://whole:url@other.example.com:465\n")
    assert mail.smtp_url() == "smtps://whole:url@other.example.com:465"  # the URL file wins


def test_smtp_provider_is_chosen_before_the_api_key(authenv) -> None:
    provider_keys(authenv)
    assert mail.provider() == "api"
    (authenv / "SIMON7_SMTP_URL").write_text("smtps://user:pw@smtp.example.com:465\n")
    assert mail.provider() == "smtp"


def test_mailer_dispatches_to_the_api_and_the_smtp_transport(authenv, tmp_path: Path, sent: list[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    provider_keys(authenv)
    (authenv / "SIMON7_MAIL_API_URL").write_text("https://mail.example.com/v1/send\n")
    mail.Mailer(tmp_path).send_sign_in("ada@example.com", "123456", "https://x/#/signin/t")
    assert wait_for(sent)[0] == "https://mail.example.com/v1/send"
    smtp_calls: list[Any] = []
    monkeypatch.setattr(mail, "_smtp_send", lambda url, msg: smtp_calls.append((url, msg["To"])) or True)
    (authenv / "SIMON7_SMTP_URL").write_text("smtps://user:pw@smtp.example.com:465\n")
    mail.Mailer(tmp_path).send_sign_in("ada@example.com", "123456", "https://x/#/signin/t")
    assert wait_for(smtp_calls) == ("smtps://user:pw@smtp.example.com:465", "ada@example.com")
