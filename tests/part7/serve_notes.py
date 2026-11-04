"""Test helper only: the real app at base path `/` with the staging test mailbox on and TWO SEEDED finished follow takes of
one movement (a real fixture analysis plus one fault at 2.4 s, and a tiny real video), for tests/part7/notes.browser.mjs.
A second tiny server on <port + 1> answers `GET /own?email=<address>` by making that signed-in account the owner of the
movement (what a trainer's own upload does through Part 6, which is a stub here). Nothing here is product code.

Run: python3 serve_notes.py <port> <file for the job ids as JSON>
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

port, id_file = int(sys.argv[1]), Path(sys.argv[2])
state = Path(tempfile.mkdtemp(prefix="s7-notes-"))
os.environ.setdefault("STAGING_ROUTE", "root")
os.environ.update(SIMON7_MAIL_TRANSPORT="outbox", SIMON7_STATE_DIR=str(state),
                  SIMON7_KEYS_DIR=str(state / "keys"), SIMON7_PUBLIC_ORIGIN=f"http://127.0.0.1:{port}")

from part7 import auth, creator, server  # noqa: E402
from support import FakeChild, ffmpeg_video, make_lock  # noqa: E402

ENTRY = "lateral-raise"
app = server.build_app(state, "/", child=FakeChild(state / "catalog"), lock=make_lock(), phrasing="template")
FIXTURE = json.loads((HERE / "fixtures" / "history" / "cc7cd5469055" / "analysis.json").read_text(encoding="utf-8"))
FIXTURE["faults"] = [{"measure": "elbow", "side": "left", "at_s": 2.4, "text_timed": "Your left elbow drifts out at 2.4 s"}]
VIDEO = ffmpeg_video(state / "seed.mp4", 2)


def seed(ctx: object) -> dict:
    folder = ctx.work / "follower"  # type: ignore[attr-defined]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "analysis.json").write_text(json.dumps(FIXTURE), encoding="utf-8")
    shutil.copyfile(VIDEO, ctx.work / "video.mp4")  # type: ignore[attr-defined]
    return {"result": {}}


ids = []
for _ in range(2):
    made = app.queue.submit("follow", seed, entry_id=ENTRY)
    app.queue.wait(made["id"], 20)
    ids.append(made["id"])


class Helper(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        email = (parse_qs(parts.query).get("email") or [""])[0]
        store = auth.identity(app)
        rows = store.fetch("SELECT user_id FROM users WHERE email = ?", (email.lower(),)) if parts.path == "/own" else []
        if rows:
            store.attach_entry(ENTRY, rows[0]["user_id"])
        body = json.dumps({"owned": bool(rows)}).encode()
        self.send_response(200 if rows else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", port + 1), Helper).serve_forever, daemon=True).start()
# what the submit answer gives the device that made a take (part7/creator.py): the test puts them in the follower's browser
tokens = {job: creator.token_for(state, job) for job in ids}
id_file.write_text(json.dumps({"first": ids[0], "second": ids[1], "entry": ENTRY, "tokens": tokens}))
http = server.make_server(app, port=port)
print(f"serving on {http.server_address[1]}", flush=True)
http.serve_forever()
