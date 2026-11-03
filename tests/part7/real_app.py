"""Test helper only: the REAL Part 7 app (real routes, real identity store, real web/) on a throwaway state folder, with a
stub Part 6 and the file outbox, for browser tests that must drive the real sign-in and session routes.

Run: python3 real_app.py <app-port> <helper-port>. The app is served under `/simon-part-7/`. A second tiny server on
<helper-port> answers `GET /code?email=<address>` with `{"code": "123456"}` read from the newest file-outbox mail for that
address, so a browser test can type the code the way a person would. Nothing here is product code or a fake of it.
"""

from __future__ import annotations

from email.parser import BytesParser
from email.policy import default as default_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="devices-real-"))
os.environ["SIMON7_KEYS_DIR"] = str(TMP / "keys")
(TMP / "keys").mkdir()
for name in ("STAGING_BASE_PATH", "STAGING_ROUTE", "SIMON7_MAIL_TRANSPORT"):
    os.environ.pop(name, None)

from part7 import server  # noqa: E402
from support import FakeChild, make_lock  # noqa: E402

CODE = re.compile(r"Your code: (\d{6})")


def newest_code(state: Path, email: str) -> str | None:
    folder = state / "outbox"
    for path in sorted(folder.glob("*.eml"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.is_dir() else []:
        msg = BytesParser(policy=default_policy).parsebytes(path.read_bytes())
        if email.lower() not in str(msg["To"]).lower():
            continue
        found = CODE.search(msg.get_body(("plain",)).get_content())
        if found:
            return found.group(1)
    return None


def main(app_port: int, helper_port: int) -> None:
    state = TMP / "state"
    child = FakeChild(TMP / "catalog")
    app = server.build_app(state, "/simon-part-7/", child=child, lock=make_lock(), phrasing="template")
    http = server.make_server(app, port=app_port)

    class Helper(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            code = newest_code(state, (parse_qs(parts.query).get("email") or [""])[0]) if parts.path == "/code" else None
            body = json.dumps({"code": code}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", helper_port), Helper).serve_forever, daemon=True).start()
    print("ready", flush=True)
    http.serve_forever()


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]))
