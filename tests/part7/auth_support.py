"""Helpers of the sign-in tests: a guarded POST, outbox reading and a full sign-in (docs/specs/identity.md)."""

from __future__ import annotations

from email.parser import BytesParser
from email.policy import default as default_policy
import json
from pathlib import Path
import re
import time
from typing import Any

import pytest

from part7 import auth
from support import Api

EMAIL = "Ada.Lovelace@Example.com"
CODE_RE = re.compile(r"Your code: (\d{6})")
LINK_RE = re.compile(r"#/signin/(\S+)")


@pytest.fixture()
def authenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Local mode, a private keys folder, the real clock; returns the keys folder."""
    keys = tmp_path / "keys"
    keys.mkdir()
    monkeypatch.setenv("SIMON7_KEYS_DIR", str(keys))
    monkeypatch.delenv("STAGING_BASE_PATH", raising=False)
    monkeypatch.delenv("SIMON7_MAIL_TRANSPORT", raising=False)
    monkeypatch.setattr(auth, "CLOCK", time.time)
    return keys


def origin(api: Api) -> str:
    return f"http://127.0.0.1:{api.port}"


def post(api: Api, path: str, doc: Any = None, headers: dict[str, str] | None = None, cookie: str | None = None,
         guard: bool = True) -> tuple[int, dict[str, str], Any]:
    """POST JSON with the headers a same-origin page sends; `guard=False` sends none of them."""
    hdr: dict[str, str] = {"Content-Type": "application/json", "Origin": origin(api)} if guard else {}
    if cookie:
        hdr["Cookie"] = f"{auth.COOKIE}={cookie}"
    hdr.update(headers or {})
    status, head, data = api.request("POST", path, json.dumps({} if doc is None else doc).encode(), hdr)
    return status, head, (json.loads(data) if data else None)


def get(api: Api, path: str, cookie: str | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], Any]:
    hdr = dict(headers or {})
    if cookie:
        hdr["Cookie"] = f"{auth.COOKIE}={cookie}"
    status, head, data = api.request("GET", path, None, hdr)
    return status, head, (json.loads(data) if data else None)


def outbox(api: Api) -> list[Path]:
    folder = api.app.state / "outbox"
    return sorted(folder.glob("*.eml")) if folder.is_dir() else []


def last_mail(api: Api) -> tuple[str, str]:
    """(code, token) of the newest mail in the outbox."""
    text = plain_text(outbox(api)[-1])
    return CODE_RE.search(text).group(1), LINK_RE.search(text).group(1)


def plain_text(path: Path) -> str:
    """The decoded text part of a saved mail (the transfer encoding may wrap long lines)."""
    msg = BytesParser(policy=default_policy).parsebytes(path.read_bytes())
    return msg.get_body(("plain",)).get_content()


def cookie_of(head: dict[str, str]) -> str:
    found = re.match(rf"{auth.COOKIE}=([^;]*)", head["set-cookie"])
    assert found
    return found.group(1)


def sign_in(api: Api, email: str = EMAIL, by: str = "code", headers: dict[str, str] | None = None) -> str:
    """Start and verify; returns the new sid."""
    assert post(api, "api/auth/start", {"email": email}, headers)[0] == 202
    code, token = last_mail(api)
    body = {"email": email, "code": code} if by == "code" else {"token": token}
    status, head, _ = post(api, "api/auth/verify", body, headers)
    assert status == 200
    return cookie_of(head)
