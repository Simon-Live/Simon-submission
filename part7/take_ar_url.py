"""Short-lived signed links to one take's AR file (docs/specs/take-ar.md, "Signed links").

Android Scene Viewer fetches the GLB without the person's cookie, so the page asks for a link first:
`GET api/results/<job>/take-ar-url?who=<trainer|you>&kind=<glb|usdz>[&ghost=1]` answers `{url, expires_utc}` to whoever
may view the take (take_ar.may_view; anyone else gets 404). The link is `api/take-ar/<token>`, stateless:
`token = base64url(payload) "." base64url(HMAC-SHA256(key, payload))`, payload `job|who|kind|ghost|expiry`. The key is
derived from the auth pepper (info `simon7-take-ar-v1`), so it is not the share key. A link names one take and one file,
expires after TTL_S, and carries no cookie or user id. There is no permanent public path to a body mesh.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from part7 import auth, jobs, take_ar

TTL_S = 300
INFO = b"simon7-take-ar-v1"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,200}\.[A-Za-z0-9_-]{43}$")
CLOCK: Callable[[], float] = time.time  # tests replace it


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _key(state: Any) -> bytes:
    prk = hmac.new(b"simon7-take-ar-salt", auth._pepper(state), hashlib.sha256).digest()
    return hmac.new(prk, INFO + b"\x01", hashlib.sha256).digest()


def _mac(state: Any, payload: str) -> str:
    return _b64(hmac.new(_key(state), payload.encode("ascii"), hashlib.sha256).digest())


def sign(state: Any, job_id: str, who: str, kind: str, ghost: bool, now: float | None = None) -> tuple[str, int]:
    """The token and its expiry (epoch seconds)."""
    expiry = int((CLOCK() if now is None else now) + TTL_S)
    payload = f"{job_id}|{who}|{kind}|{int(ghost)}|{expiry}"
    return f"{_b64(payload.encode('ascii'))}.{_mac(state, payload)}", expiry


def verify(state: Any, token: str, now: float | None = None) -> tuple[str, str, str, bool] | None:
    """`(job, who, kind, ghost)` for a genuine, unexpired token, else None."""
    if not isinstance(token, str) or not TOKEN_RE.match(token):
        return None
    body, mac = token.split(".")
    try:
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode("ascii")
        job_id, who, kind, ghost, expiry = payload.split("|")
        expires = int(expiry)
    except (ValueError, UnicodeDecodeError):
        return None
    if not hmac.compare_digest(_mac(state, payload), mac) or (CLOCK() if now is None else now) >= expires:
        return None
    if not jobs.JOB_ID_RE.match(job_id) or who not in take_ar.WHO or kind not in take_ar.KINDS or ghost not in ("0", "1"):
        return None
    return job_id, who, kind, ghost == "1"


def _iso(ts: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def handle(h: Any, method: str, route: str) -> bool:
    """Answer the link request and the signed file; False for any other route."""
    parts = route.split("/")
    if method in ("GET", "HEAD") and len(parts) == 2 and parts[0] == "take-ar":
        got = verify(h.app.state, parts[1])
        data = take_ar.render(h.app.queue.job_dir(got[0]).parent, got[0], got[1], got[2], got[3]) if got else None
        if got is None or data is None:
            h._error(404, take_ar.MSG_GONE)
        else:
            take_ar.send_file(h, data, got[2], f"simon-{got[1]}-{got[0]}{'-ghost' if got[3] else ''}.{got[2]}")
        return True
    if method != "GET" or len(parts) != 3 or parts[0] != "results" or parts[2] != "take-ar-url":
        return False
    query = parse_qs(urlsplit(h.path).query)
    who, kind = query.get("who", [""])[0], query.get("kind", [""])[0]
    ghost = query.get("ghost", [""])[0] == "1"
    job_id = parts[1]
    ok = jobs.JOB_ID_RE.match(job_id) and who in take_ar.WHO and kind in take_ar.KINDS and take_ar.may_view(h, job_id)
    root = h.app.queue.job_dir(job_id).parent if ok else None
    doc = take_ar.index(root, job_id) if root else None
    entry = doc.get(who) if doc else None
    if not entry or (ghost and f"{kind}_ghost" not in entry):
        h._error(404, take_ar.MSG_GONE)
        return True
    token, expiry = sign(h.app.state, job_id, who, kind, ghost)
    h._json(200, {"url": f"api/take-ar/{token}", "expires_utc": _iso(expiry)})
    return True
