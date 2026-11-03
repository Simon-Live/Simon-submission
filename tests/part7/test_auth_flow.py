"""Sign-in routes, limits, CSRF, sessions and mail (docs/specs/identity.md AC-AU-1 to AC-AU-8, AC-AU-11; TICKET-172)."""

from __future__ import annotations

import logging
import re

import pytest

from auth_support import EMAIL, authenv, cookie_of, get, last_mail, outbox, plain_text, post, sign_in  # noqa: F401
from part7 import auth, auth_routes, mail
from support import Api

pytestmark = pytest.mark.usefixtures("authenv")


def test_flow_by_code_and_by_link(api: Api) -> None:  # AC-AU-1
    assert get(api, "api/auth/me")[2] == {"available": True, "signed_in": False}
    sid = sign_in(api, by="code")
    status, _, me = get(api, "api/auth/me", cookie=sid)
    assert status == 200 and me["signed_in"] and re.match(r"^u-[0-9a-f]{24}$", me["user_id"])
    assert me["email"] == "ada.lovelace@example.com" and me["retention"] == {"opted_in": False, "days": 90, "consent_version": None}
    sid2 = sign_in(api, by="link")  # the same address, by the link: the same account, a new session
    assert get(api, "api/auth/me", cookie=sid2)[2]["user_id"] == me["user_id"] and sid2 != sid
    assert len(outbox(api)) == 2


def test_mail_holds_code_and_fragment_link_and_no_ip(api: Api) -> None:  # AC-AU-1
    assert post(api, "api/auth/start", {"email": EMAIL}, {"Cf-Connecting-Ip": "203.0.113.9"})[0] == 202
    text = plain_text(outbox(api)[0])
    code, token = last_mail(api)
    assert f"https://127.0.0.1:{api.port}/simon-part-7/#/signin/{token}" in text  # Cf-Connecting-Ip: the gateway rule says https
    raw = outbox(api)[0].read_text(encoding="utf-8")
    assert "To: ada.lovelace@example.com" in raw and "203.0.113.9" not in raw + text and "If you did not ask, ignore this mail." in text
    assert "?" not in re.search(r"http\S+", text).group(0)  # the token is in the fragment, not the query
    assert oct(outbox(api)[0].stat().st_mode & 0o777) == "0o600"


def test_start_limits(api: Api) -> None:  # AC-AU-2
    first = post(api, "api/auth/start", {"email": EMAIL})
    other = post(api, "api/auth/start", {"email": "new.person@example.org"})
    assert first[0] == other[0] == 202 and first[2] == other[2] == {"ok": True}  # new and known: identical
    for _ in range(4):
        assert post(api, "api/auth/start", {"email": EMAIL})[0] == 202
    mails = len(outbox(api))
    status, _, body = post(api, "api/auth/start", {"email": EMAIL})  # the 6th for one address in an hour
    assert (status, body) == (202, {"ok": True}) and len(outbox(api)) == mails == 6  # silent: no mail
    assert post(api, "api/auth/start", {"email": "bad"})[0] == 400
    assert post(api, "api/auth/start", {})[0] == 400 and post(api, "api/auth/start", {"email": 7})[0] == 400


def test_start_per_ip_429_after_ten_an_hour(api: Api) -> None:  # AC-AU-2
    for n in range(10):
        assert post(api, "api/auth/start", {"email": f"p{n}@example.com"}, {"Cf-Connecting-Ip": "198.51.100.1"})[0] == 202
    status, _, body = post(api, "api/auth/start", {"email": "p99@example.com"}, {"Cf-Connecting-Ip": "198.51.100.1"})
    assert status == 429 and body["message"] == auth_routes.MSG_RATE
    assert post(api, "api/auth/start", {"email": "p99@example.com"}, {"Cf-Connecting-Ip": "198.51.100.2"})[0] == 202  # another visitor


def test_start_per_ip_window_slides(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-AU-2
    now = [1_800_000_000.0]
    monkeypatch.setattr(auth, "CLOCK", lambda: now[0])
    for n in range(10):
        post(api, "api/auth/start", {"email": f"w{n}@example.com"})
    assert post(api, "api/auth/start", {"email": "w10@example.com"})[0] == 429
    now[0] += 3601
    assert post(api, "api/auth/start", {"email": "w10@example.com"})[0] == 202


def test_start_survives_a_mail_failure_with_the_same_202(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-AU-2
    def boom(*a: object, **k: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(mail, "_write_outbox", boom)
    assert post(api, "api/auth/start", {"email": EMAIL}) [0] == 202


def test_start_body_limits(api: Api) -> None:  # AC-AU-2
    status, _, body = post(api, "api/auth/start", {"email": "a@example.com", "pad": "x" * 5000})
    assert status == 413 and body["message"] == auth_routes.MSG_TOO_BIG
    status, _, _ = api.request("POST", "api/auth/start", b"[1]", {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{api.port}"})
    assert status == 400


def test_verify_failures_share_one_400(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-AU-3
    now = [1_800_000_000.0]
    monkeypatch.setattr(auth, "CLOCK", lambda: now[0])
    post(api, "api/auth/start", {"email": EMAIL})
    code, token = last_mail(api)
    wrong = "000000" if code != "000000" else "111111"
    bodies = [
        post(api, "api/auth/verify", {"token": "nope"}),
        post(api, "api/auth/verify", {"email": EMAIL, "code": wrong}),
        post(api, "api/auth/verify", {"email": "unknown@example.com", "code": "123456"}),  # no such account: the same
        post(api, "api/auth/verify", {"email": EMAIL}),
        post(api, "api/auth/verify", {}),
        post(api, "api/auth/verify", {"token": 5}),
    ]
    assert {(s, b["message"]) for s, _, b in bodies} == {(400, auth_routes.MSG_INVALID)}
    assert all("set-cookie" not in h for _, h, _ in bodies)
    now[0] += 16 * 60  # expired
    assert post(api, "api/auth/verify", {"token": token})[0] == 400
    assert post(api, "api/auth/verify", {"email": EMAIL, "code": code})[2]["message"] == auth_routes.MSG_INVALID


def test_verify_used_up_challenge(api: Api) -> None:  # AC-AU-3
    post(api, "api/auth/start", {"email": EMAIL})
    code, token = last_mail(api)
    assert post(api, "api/auth/verify", {"token": token})[0] == 200
    assert post(api, "api/auth/verify", {"token": token})[0] == 400  # a used token
    assert post(api, "api/auth/verify", {"email": EMAIL, "code": code})[0] == 400  # and its code died with it


def test_verify_five_wrong_codes_then_even_the_right_one_fails(api: Api) -> None:  # AC-AU-3
    post(api, "api/auth/start", {"email": EMAIL})
    code, _ = last_mail(api)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert post(api, "api/auth/verify", {"email": EMAIL, "code": wrong})[0] == 400
    assert post(api, "api/auth/verify", {"email": EMAIL, "code": code})[0] == 400


def test_verify_per_ip_429_after_thirty_in_ten_minutes(api: Api) -> None:  # AC-AU-3
    for _ in range(30):
        assert post(api, "api/auth/verify", {"token": "x"}, {"Cf-Connecting-Ip": "198.51.100.7"})[0] == 400
    status, _, body = post(api, "api/auth/verify", {"token": "x"}, {"Cf-Connecting-Ip": "198.51.100.7"})
    assert status == 429 and body["message"] == auth_routes.MSG_RATE
    assert post(api, "api/auth/verify", {"token": "x"}, {"Cf-Connecting-Ip": "198.51.100.8"})[0] == 400


@pytest.mark.parametrize("path,doc", [
    ("api/auth/start", {"email": EMAIL}), ("api/auth/verify", {"token": "x"}), ("api/auth/signout", {}),
    ("api/me/claims", {"job_id": "aaaaaaaaaaaa"}), ("api/me/consent", {"retention": True, "version": "v1"}),
    ("api/me/delete", {"confirm": "delete"}), ("api/me/entries/lateral-raise", {"only_me": True}),
])
def test_csrf_refusals_are_403(api: Api, path: str, doc: dict) -> None:  # AC-AU-4
    base = f"http://127.0.0.1:{api.port}"
    cases = [
        {"guard": False},  # no Origin, no content type
        {"headers": {"Origin": ""}},  # an empty Origin
        {"headers": {"Origin": "https://evil.example"}},  # another site
        {"headers": {"Origin": "http://127.0.0.1:1"}},  # same host, another port
        {"headers": {"Origin": "null"}},
        {"headers": {"Content-Type": "text/plain"}},  # a form-style POST
        {"headers": {"Content-Type": "application/x-www-form-urlencoded"}},
        {"headers": {"Sec-Fetch-Site": "cross-site"}},
        {"headers": {"Sec-Fetch-Site": "same-site"}},
    ]
    for case in cases:
        status, head, body = post(api, path, doc, **case)
        assert status == 403 and body["message"] == auth_routes.MSG_CSRF, case
        assert head["referrer-policy"] == "no-referrer"
    assert not outbox(api)
    assert base  # the happy header set is covered by every other test


def test_csrf_same_origin_with_charset_and_sec_fetch_passes(api: Api) -> None:  # AC-AU-4
    headers = {"Content-Type": "application/json; charset=utf-8", "Sec-Fetch-Site": "same-origin"}
    assert post(api, "api/auth/start", {"email": EMAIL}, headers)[0] == 202


def test_get_routes_need_no_origin(api: Api) -> None:  # AC-AU-4
    assert get(api, "api/auth/me")[0] == 200


def test_fixation_a_new_sid_and_the_presented_one_is_revoked(api: Api) -> None:  # AC-AU-5
    first = sign_in(api)
    post(api, "api/auth/start", {"email": EMAIL})
    code, _ = last_mail(api)
    status, head, _ = post(api, "api/auth/verify", {"email": EMAIL, "code": code}, cookie=first)
    second = cookie_of(head)
    assert status == 200 and second != first
    assert get(api, "api/auth/me", cookie=first)[2]["signed_in"] is False  # the presented sid died
    assert get(api, "api/auth/me", cookie=second)[2]["signed_in"] is True


def test_fixation_a_sid_in_a_body_or_url_is_never_accepted(api: Api) -> None:  # AC-AU-5
    sid = sign_in(api)
    assert get(api, f"api/auth/me?s7_sid={sid}")[2]["signed_in"] is False
    assert get(api, "api/auth/me", headers={"Authorization": f"Bearer {sid}"})[2]["signed_in"] is False


def test_signout_invalidates_a_copied_cookie(api: Api) -> None:  # AC-AU-5
    sid = sign_in(api)
    copy = f"{sid}"
    status, head, _ = post(api, "api/auth/signout", cookie=sid)
    assert status == 204 and "Max-Age=0" in head["set-cookie"] and head["set-cookie"].startswith("s7_sid=;")
    assert get(api, "api/auth/me", cookie=copy)[2]["signed_in"] is False
    assert get(api, "api/me/takes", cookie=copy)[0] == 401
    assert post(api, "api/auth/signout")[0] == 204  # also when not signed in


def test_expired_sessions_are_refused(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-AU-5
    now = [1_800_000_000.0]
    monkeypatch.setattr(auth, "CLOCK", lambda: now[0])
    sid = sign_in(api)
    now[0] += 15 * 86400
    assert get(api, "api/auth/me", cookie=sid)[2]["signed_in"] is False  # idle 15 days
    sid = sign_in(api)
    for _ in range(4):  # used every 10 days: never idle
        now[0] += 10 * 86400
        assert get(api, "api/auth/me", cookie=sid)[2]["signed_in"] is (now[0] < 1_800_000_000.0 + 15 * 86400 + 30 * 86400)


def test_cookie_flags(api: Api) -> None:  # AC-AU-6
    post(api, "api/auth/start", {"email": EMAIL})
    code, _ = last_mail(api)
    cookie = post(api, "api/auth/verify", {"email": EMAIL, "code": code})[1]["set-cookie"]
    assert re.match(r"^s7_sid=[A-Za-z0-9_-]{43}; Path=/simon-part-7/; HttpOnly; SameSite=Lax; Max-Age=2592000$", cookie)
    assert "Secure" not in cookie  # plain http on 127.0.0.1


@pytest.mark.parametrize("headers", [{"Cf-Connecting-Ip": "203.0.113.5"}, {"X-Forwarded-Proto": "https"}])
def test_cookie_secure_under_the_gateway_https_rule(api: Api, headers: dict[str, str]) -> None:  # AC-AU-6
    post(api, "api/auth/start", {"email": EMAIL}, headers)
    code, _ = last_mail(api)
    cookie = post(api, "api/auth/verify", {"email": EMAIL, "code": code}, headers)[1]["set-cookie"]
    assert cookie.endswith("; Secure") and "Path=/simon-part-7/" in cookie
    link = re.search(r"http\S+", plain_text(outbox(api)[0])).group(0)
    assert link.startswith("https://127.0.0.1")


def test_https_rule_ignores_forwarding_headers_from_a_non_loopback_peer() -> None:  # AC-AU-6
    class H:
        client_address = ("203.0.113.9", 5000)
        headers = {"Cf-Connecting-Ip": "198.51.100.1", "X-Forwarded-Proto": "https"}

    assert auth.is_https(H()) is False and auth.client_key(H()) == auth.client_key(H())
    H.client_address = ("127.0.0.1", 5000)
    assert auth.is_https(H()) is True


def test_client_key_prefers_cf_then_single_xff_then_peer() -> None:  # AC-AU-2
    class H:
        client_address = ("127.0.0.1", 1)
        headers: dict[str, str] = {}

    h = H()
    peer = auth.client_key(h)
    H.headers = {"X-Forwarded-For": "198.51.100.1"}
    xff = auth.client_key(h)
    H.headers = {"X-Forwarded-For": "198.51.100.1, 10.0.0.1"}  # a chain is not trusted: the peer
    assert auth.client_key(h) == peer and xff != peer
    H.headers = {"Cf-Connecting-Ip": "198.51.100.2", "X-Forwarded-For": "198.51.100.1"}
    assert auth.client_key(h) not in (peer, xff)


def test_every_auth_answer_carries_no_referrer(api: Api) -> None:  # AC-AU-4
    sid = sign_in(api)
    for path in ("api/auth/me", "api/me/takes", "api/me/entries"):
        assert get(api, path, cookie=sid)[1]["referrer-policy"] == "no-referrer"
    assert post(api, "api/auth/verify", {"token": "x"})[1]["referrer-policy"] == "no-referrer"
    assert get(api, "api/me/takes")[1]["referrer-policy"] == "no-referrer"  # the 401 too


def test_transport_select_smtp_file_off(tmp_path, monkeypatch: pytest.MonkeyPatch, authenv) -> None:  # AC-AU-7
    assert mail.select_transport() == "file"  # local, no keys
    (authenv / "SIMON7_SMTP_URL").write_text("smtps://user:pw@smtp.example.com:465\n")
    assert mail.select_transport() == "file"  # one key file is not enough
    (authenv / "SIMON7_MAIL_FROM").write_text("Simon <signin@example.com>\n")
    assert mail.select_transport() == "smtp"
    monkeypatch.setenv("STAGING_BASE_PATH", "/simon-part-7/")
    assert mail.select_transport() == "off"  # the shared gateway origin never shows sign-in (ADR-0014, TICKET-177)
    monkeypatch.setenv("STAGING_ROUTE", "root")
    assert mail.select_transport() == "smtp"  # SMTP works on the app's own origin
    (authenv / "SIMON7_SMTP_URL").unlink()
    assert mail.select_transport() == "off" and mail.file_refused_on_staging()  # the file outbox is refused there
    monkeypatch.delenv("STAGING_ROUTE")
    monkeypatch.delenv("STAGING_BASE_PATH")
    assert mail.select_transport() == "file"
    monkeypatch.setenv("SIMON7_MAIL_TRANSPORT", "off")
    assert mail.select_transport() == "off"


def test_staging_refuses_the_file_outbox_with_one_log_line(api: Api, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:  # AC-AU-7
    monkeypatch.setenv("STAGING_BASE_PATH", "/simon-part-7/")
    with caplog.at_level(logging.INFO, logger="part7"):
        status, _, body = post(api, "api/auth/start", {"email": EMAIL})
        post(api, "api/auth/start", {"email": EMAIL})
    lines = [r.getMessage() for r in caplog.records if "outbox refused" in r.getMessage()]
    assert status == 404 and body["message"] == auth_routes.MSG_OFF and len(lines) == 1
    assert not outbox(api)


def test_smtp_sends_through_the_stdlib_with_starttls_and_login(api: Api, authenv, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-AU-7
    (authenv / "SIMON7_SMTP_URL").write_text("smtp://us%40er:p%2Fw@smtp.example.com:2525\n")
    (authenv / "SIMON7_MAIL_FROM").write_text("Simon <signin@example.com>\n")
    seen: dict[str, object] = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            seen["addr"] = (host, port)

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *a: object) -> None:
            seen["closed"] = True

        def starttls(self, context: object) -> None:
            seen["tls"] = context

        def login(self, user: str, password: str) -> None:
            seen["login"] = (user, password)

        def send_message(self, msg: object) -> None:
            seen["msg"] = msg

    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    url = "smtp://us%40er:p%2Fw@smtp.example.com:2525"
    msg = mail.build_message("ada@example.com", "Simon <signin@example.com>", "123456", "http://x/#/signin/t", mail.datetime.now(mail.timezone.utc))
    assert mail._smtp_send(url, msg) is True
    assert seen["addr"] == ("smtp.example.com", 2525) and seen["login"] == ("us@er", "p/w") and seen["tls"] is not None
    assert seen["msg"]["To"] == "ada@example.com" and seen["msg"]["From"] == "Simon <signin@example.com>"
    assert api.app and not outbox(api)  # SMTP mode writes no file


def test_smtp_failure_logs_the_type_only(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-AU-7
    class Down:
        def __init__(self, *a: object, **k: object) -> None:
            raise OSError("cannot reach ada@example.com")

    monkeypatch.setattr(mail.smtplib, "SMTP", Down)
    msg = mail.build_message("ada@example.com", "S <s@example.com>", "123456", "http://x/#/signin/t", mail.datetime.now(mail.timezone.utc))
    with caplog.at_level(logging.INFO, logger="part7"):
        assert mail._smtp_send("smtp://smtp.example.com", msg) is False
        assert mail._smtp_send("http://nonsense", msg) is False
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "OSError" in text and "ada@example.com" not in text


def test_off_hides_signin(api: Api, monkeypatch: pytest.MonkeyPatch, authenv) -> None:  # AC-AU-8
    monkeypatch.setenv("SIMON7_MAIL_TRANSPORT", "off")
    assert get(api, "api/auth/me")[2] == {"available": False, "signed_in": False}
    status, _, body = post(api, "api/auth/start", {"email": EMAIL})
    assert status == 404 and body["message"] == auth_routes.MSG_OFF
    assert post(api, "api/auth/verify", {"token": "x"})[0] == 404  # nothing to verify against
    for route in ("api/me/takes", "api/me/entries"):
        assert get(api, route)[0] == 404
    for route, doc in (("api/me/claims", {"job_id": "x"}), ("api/me/consent", {"retention": True, "version": "1"}),
                       ("api/me/delete", {"confirm": "delete"}), ("api/me/entries/e1", {"only_me": True})):
        assert post(api, route, doc)[0] == 404
    assert get(api, "api/auth/me", cookie="garbage-sid")[2] == {"available": False, "signed_in": False}
    # nothing touched the disk: no identity folder, no pepper key (R1)
    assert not (api.app.state / "identity").exists()
    assert not list(authenv.rglob("SIMON7_AUTH_PEPPER"))


def test_log_grep_after_a_full_sign_in_has_no_secret_or_address(api: Api, caplog: pytest.LogCaptureFixture) -> None:  # AC-AU-11
    with caplog.at_level(logging.DEBUG, logger="part7"):
        post(api, "api/auth/start", {"email": EMAIL})
        code, token = last_mail(api)
        wrong = "000000" if code != "000000" else "111111"
        post(api, "api/auth/verify", {"email": EMAIL, "code": wrong})
        status, head, _ = post(api, "api/auth/verify", {"token": token})
        sid = cookie_of(head)
        get(api, "api/me/takes", cookie=sid)
        post(api, "api/auth/signout", cookie=sid)
        sid = sign_in(api)
        post(api, "api/me/delete", {"confirm": "delete"}, cookie=sid)
    log = "\n".join(r.getMessage() for r in caplog.records)
    assert "auth: sign-in started" in log and "auth: signed in u-" in log
    for secret in (token, code, sid, EMAIL, EMAIL.lower(), "example.com", "ada.lovelace"):
        assert secret not in log, secret


def test_pepper_is_made_once_private_and_reused(api: Api, authenv) -> None:
    sign_in(api)
    pepper = authenv / "SIMON7_AUTH_PEPPER"
    assert pepper.is_file() and oct(pepper.stat().st_mode & 0o777) == "0o600" and len(pepper.read_text().strip()) == 64
    before = pepper.read_text()
    assert auth._pepper(api.app.state) == bytes.fromhex(before.strip()) and pepper.read_text() == before


def test_pepper_falls_back_to_the_identity_folder(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_KEYS_DIR", str(tmp_path / "file-not-folder"))
    (tmp_path / "file-not-folder").write_text("x")  # cannot be a folder
    first = auth._pepper(tmp_path / "state")
    assert (tmp_path / "state" / "identity" / "SIMON7_AUTH_PEPPER").is_file() and auth._pepper(tmp_path / "state") == first


def test_unknown_methods_and_paths_fall_through(api: Api) -> None:
    assert api.request("GET", "api/auth/start")[0] in (404, 405)
    assert api.request("GET", "api/auth/nothing")[0] in (404, 405)
    assert post(api, "api/auth/me", {})[0] in (404, 405)


def test_mail_html_escapes_the_link() -> None:  # R10
    msg = mail.build_message("a@example.com", "S <s@example.com>", "123456", 'http://x/#/t?a=1&b="2"><i>',
                             mail.datetime.now(mail.timezone.utc))
    page = msg.get_body(("html",)).get_content()
    assert "<i>" not in page and "&amp;b=&quot;2&quot;&gt;&lt;i&gt;" in page
