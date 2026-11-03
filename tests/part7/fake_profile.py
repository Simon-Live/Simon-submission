"""Test helper only: a fake of the profile routes (GET/PUT/DELETE api/me/profile, GET api/avatars) and a SEEDED history list
(api/me/history, labelled seeded: invented rows for the browser test) on top of fake_auth.py. Nothing here is product code:
the real routes are part7/profile.py. Wire keys follow the release 20 contract (docs/specs/profile.md).

Run: python3 fake_profile.py <port>. Profiles are kept per signed-in account in memory.
"""

from __future__ import annotations

import json
import re
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_auth  # noqa: E402

AVATARS = ["fern", "ember", "tide", "moss", "dusk", "sun", "stone", "wave"]  # the real built-in list (part7/profile.py)
MODES = ["dance", "rehab", "fitness"]
GOALS = {"learn_the_moves": "Learn the moves", "match_trainer_timing": "Match the trainer's timing",
         "steady_practice": "Keep a steady practice"}
KEYS = {"public_name", "avatar", "modes", "goals", "show_name", "credit_me_as_trainer", "default_model_id", "model_only_view"}
MODEL_RE = re.compile(r"^(?:person|skeleton|(?:lib|up):[A-Za-z0-9][A-Za-z0-9_.-]{0,63})$")  # as part7/profile.py
PROFILES: dict[str, dict] = {}
SEEDED_HISTORY = {"entries": [{"entry_id": "lateral-raise", "name": "Lateral raise", "takes": 3,
                               "latest": {"take": "t3", "at": "2026-10-31T10:00:00Z", "score": 71, "grade": "C"}}],
                  "consent": {}, "retention": {}}


def default() -> dict:
    return {"public_name": None, "avatar": None, "modes": [], "goals": [], "show_name": False, "credit_me_as_trainer": False,
            "default_model_id": None, "model_only_view": False, "created_utc": None, "updated_utc": None}


def invalid(data: dict) -> str | None:
    if set(data) - KEYS:
        return "unknown key"
    name = data.get("public_name")
    if name is not None and (not isinstance(name, str) or not 1 <= len(name.strip()) <= 40 or "@" in name):
        return "bad name"
    if data.get("avatar") not in (None, *AVATARS):
        return "bad avatar"
    if any(m not in MODES for m in data.get("modes", [])) or any(g not in GOALS for g in data.get("goals", [])):
        return "bad choice"
    model = data.get("default_model_id")
    if model is not None and (not isinstance(model, str) or not MODEL_RE.match(model)):
        return "bad model"
    return None


class Handler(fake_auth.Handler):
    def _who(self) -> str | None:
        return fake_auth._email_of(fake_auth._sid(self))

    def _profile_route(self, method: str, body: bytes) -> None:
        who = self._who()
        if not who:
            return self.send(401, {"error": "Sign in to see this."})
        if method == "GET":
            return self.send(200, PROFILES.get(who, default()))
        if method == "DELETE":
            PROFILES[who] = default()
            return self.send(200, {"deleted": True, **PROFILES[who]})
        data = fake_auth._json(body)
        if data is None or invalid(data):
            return self.send(400, {"error": "Those choices were not accepted."})
        PROFILES[who] = {**default(), **PROFILES.get(who, {}), **data}  # only the keys sent change, as in part7/profile.py
        return self.send(200, PROFILES[who])

    def do_GET(self):
        path = urlsplit(self.path).path.lstrip("/")
        if path == "api/me/profile":
            return self._profile_route("GET", b"")
        if path == "api/avatars":
            return self.send(200, {"avatars": AVATARS, "modes": MODES,
                                   "goals": [{"key": k, "label": v} for k, v in GOALS.items()], "name_max": 40})
        if path == "api/me/history":
            return self.send(200, SEEDED_HISTORY) if self._who() else self.send(401, {"error": "Sign in to see this."})
        if path == "__test/profiles":
            return self.send(200, json.dumps(PROFILES).encode())
        return super().do_GET()

    def _with_body(self, method: str) -> None:
        path = urlsplit(self.path).path.lstrip("/")
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if path == "api/me/profile":
            return self._profile_route(method, body)
        return self.send(404, {"error": "not found"})

    def do_PUT(self):
        self._with_body("PUT")

    def do_DELETE(self):
        self._with_body("DELETE")


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
