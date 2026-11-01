"""Test helper only: a fake of the sign-in routes of auth-design.md (api/auth/*, api/me/*) on top of fake_api.py.

Run: python3 fake_auth.py <port>. It serves web/, the fake Part 7 API and these routes. Nothing here is product code:
the real routes are part7/auth_routes.py. `GET __test/outbox` lists the mails the fake "sent" ({email, code, token}),
`POST __test/auth {available, reset, release}` flips the mail switch, clears everything or drops a claim, `GET __test/auth` shows the state.
Job ids known to the claim route are the keys of fake_challenges.SCORES plus `busy1` (a take whose delete is refused).
"""

from __future__ import annotations

import json
import re
import secrets
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_api  # noqa: E402
import fake_challenges  # noqa: E402

INVALID = "This link or code is not valid or has expired. Ask for a new one."
EMAIL = re.compile(r"^[^\s@]+@[^\s@.]+(\.[^\s@.]+)+$")
KNOWN = set(fake_challenges.SCORES) | {"busy1"}


def fresh() -> dict:
    return {"available": True, "outbox": [], "challenges": {}, "users": {}, "sessions": {}, "claims": {}, "deleted": set(),
            "consent": {}, "verify_calls": 0, "start_calls": 0}


STATE = fresh()


def _email_of(sid: str | None) -> str | None:
    return STATE["sessions"].get(sid) if sid else None


def _sid(handler) -> str | None:
    for part in (handler.headers.get("Cookie") or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == "s7_sid":
            return v
    return None


def _json(body: bytes):
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _me(handler) -> dict:
    email = _email_of(_sid(handler))
    if not STATE["available"]:
        return {"available": False, "signed_in": False}
    if not email:
        return {"available": True, "signed_in": False}
    user = STATE["users"][email]
    return {"available": True, "signed_in": True, "user_id": user["user_id"], "email": email,
            "retention": {"opted_in": user["opted_in"], "days": 90 if user["opted_in"] else 7, "consent_version": user["version"]}}


def _take(job: str) -> dict:
    entry, score, grade, _ = fake_challenges.SCORES.get(job, ("lateral-raise", 0, "F", None))
    kind = "group" if job.startswith("grp") else "follow"
    return {"job_id": job, "kind": kind, "entry_id": entry, "created_at": "2026-10-31T10:00:00Z", "status": "done",
            "score": score, "grade": grade}


def start(handler, data) -> None:
    STATE["start_calls"] += 1
    if not STATE["available"]:
        return handler.send(404, {"error": "not found"})
    email = str(data.get("email", "")).strip().lower()
    if not EMAIL.match(email):
        return handler.send(400, {"error": "Enter a valid email address."})
    token, code = secrets.token_urlsafe(32), f"{secrets.randbelow(10**6):06d}"
    STATE["challenges"] = {k: v for k, v in STATE["challenges"].items() if v["email"] != email}
    STATE["challenges"][token] = {"email": email, "code": code, "attempts": 0}
    STATE["outbox"].append({"email": email, "code": code, "token": token})
    return handler.send(202, {"ok": True})


def verify(handler, data) -> None:
    STATE["verify_calls"] += 1
    found = None
    if isinstance(data.get("token"), str) and data["token"] in STATE["challenges"]:
        found = data["token"]
    elif isinstance(data.get("code"), str):
        email = str(data.get("email", "")).strip().lower()
        for token, ch in STATE["challenges"].items():
            if ch["email"] == email:
                ch["attempts"] += 1
                if ch["code"] == data["code"] and ch["attempts"] <= 5:
                    found = token
                break
    if found is None:
        return handler.send(400, {"error": INVALID})
    email = STATE["challenges"].pop(found)["email"]
    user = STATE["users"].setdefault(email, {"user_id": "u-" + secrets.token_hex(12), "opted_in": False, "version": ""})
    sid = secrets.token_urlsafe(32)
    STATE["sessions"][sid] = email
    return handler.send(200, {"user_id": user["user_id"], "email": email},
                        extra={"Set-Cookie": f"s7_sid={sid}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"})


def _owned(email: str) -> list[str]:
    return [j for j, owner in STATE["claims"].items() if owner == email and j not in STATE["deleted"]]


def me_routes(handler, method: str, path: str, data) -> None:
    email = _email_of(_sid(handler))
    if not email:
        return handler.send(401, {"error": "Sign in to see this."})
    user = STATE["users"][email]
    if path == "api/me/takes" and method == "GET":
        return handler.send(200, {"takes": [_take(j) for j in reversed(_owned(email))]})
    if data is None:
        return handler.send(400, {"error": "The request is not valid JSON."})
    if path == "api/me/claims":
        job = data.get("job_id")
        if job not in KNOWN or job in STATE["deleted"]:
            return handler.send(404, {"error": "This result was not found. Results are kept for 7 days."})
        if STATE["claims"].setdefault(job, email) != email:
            return handler.send(409, {"error": "This take is kept by another account."})
        return handler.send(200, {"claimed": True, "kind": _take(job)["kind"]})
    if path == "api/me/consent":
        user["opted_in"], user["version"] = bool(data.get("retention")), str(data.get("version", ""))
        STATE["consent"][email] = dict(data)
        return handler.send(200, {"ok": True})
    if path == "api/me/delete":
        if data.get("confirm") != "delete":
            return handler.send(400, {"error": "Send confirm: delete."})
        busy = [j for j in _owned(email) if j == "busy1"]
        if busy:
            return handler.send(409, {"error": "Some takes are still running.", "busy": busy})
        removed = _owned(email)
        STATE["deleted"].update(removed)
        STATE["users"].pop(email, None)
        STATE["sessions"] = {k: v for k, v in STATE["sessions"].items() if v != email}
        STATE["outbox"] = [m for m in STATE["outbox"] if m["email"] != email]
        return handler.send(200, {"deleted": True, "takes_removed": len(removed), "entries_unlinked": 0},
                            extra={"Set-Cookie": "s7_sid=; Path=/; Max-Age=0"})
    return handler.send(404, {"error": "not found"})


class Handler(fake_api.Handler):
    def do_GET(self):
        path = urlsplit(self.path).path.lstrip("/")
        if path == "api/auth/me":
            return self.send(200, _me(self))
        if path == "api/me/takes":
            return me_routes(self, "GET", path, None)
        if path == "__test/outbox":
            return self.send(200, {"outbox": STATE["outbox"]})
        if path == "__test/auth":
            return self.send(200, {**{k: v for k, v in STATE.items() if k in ("available", "verify_calls", "start_calls", "consent")},
                                   "deleted": sorted(STATE["deleted"])})
        m = re.match(r"api/results/([^/]+)/", path)
        if m and m.group(1) in STATE["deleted"]:
            return self.send(404, {"error": "This result was not found. Results are kept for 7 days."})
        return super().do_GET()

    def do_POST(self):
        path = urlsplit(self.path).path.lstrip("/")
        if path.startswith(("api/auth/", "api/me/", "__test/auth")):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            data = _json(body)
            if path == "__test/auth":
                if (data or {}).get("reset"):
                    STATE.clear()
                    STATE.update(fresh())
                if data and data.get("release"):  # a running take finished: it is no longer in the way of a delete
                    STATE["claims"].pop(data["release"], None)
                if data and "available" in data:
                    STATE["available"] = bool(data["available"])
                return self.send(200, {"ok": True})
            if path == "api/auth/signout":
                STATE["sessions"].pop(_sid(self) or "", None)
                return self.send(204, b"", extra={"Set-Cookie": "s7_sid=; Path=/; Max-Age=0"})
            if path in ("api/auth/start", "api/auth/verify"):
                if data is None:
                    return self.send(400, {"error": "The request is not valid JSON."})
                return (start if path.endswith("start") else verify)(self, data)
            return me_routes(self, "POST", path, data)
        return super().do_POST()


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
