"""Test helper only: the real app (part7.server) at base path `/` with the staging test mailbox (real sign-in, real challenge routes, real
policy) and a small seeding door on port+1000: `POST /seed?user=<id>&job=<12 hex>&score=<n>` makes a finished, scored follow take of
`lateral-raise` owned by that account (the one thing a real run needs a camera and a worker for). Part 6 is a stand-in (support.FakeChild).
Run: python3 serve_boards_real.py <port>   (docs/specs/board-discovery.md; used by boards_real.browser.mjs)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

port = int(sys.argv[1])
state = Path(tempfile.mkdtemp(prefix="s7-boards-"))
os.environ.setdefault("STAGING_ROUTE", "root")
os.environ.update(SIMON7_MAIL_TRANSPORT="outbox", SIMON7_STATE_DIR=str(state), SIMON7_KEYS_DIR=str(state / "keys"),
                  SIMON7_PUBLIC_ORIGIN=f"http://127.0.0.1:{port}")

from part7 import auth, server  # noqa: E402
from support import FakeChild, make_lock, published  # noqa: E402

app = server.build_app(state, "/", child=FakeChild(state / "catalog"), lock=make_lock(), phrasing="template")
published(state, "lateral-raise")


class Seed(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        q = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
        job, user, score = q["job"], q["user"], float(q.get("score", 70))
        folder = app.queue.job_dir(job) / "work" / "follower"
        folder.mkdir(parents=True, exist_ok=True)
        doc = {"status": {"code": "ok"}, "score": {"value": score, "grade": "B", "basis": "windows", "timeline": []}, "faults": []}
        (folder / "analysis.json").write_text(json.dumps(doc), encoding="utf-8")
        app.queue._jobs[job] = {"id": job, "kind": "follow", "status": "done", "entry_id": "lateral-raise", "stages": [], "note": None,
                                "result": {"entry_id": "lateral-raise", "score": score, "grade": "B"}}
        auth.identity(app).attach(job, user, "follow", "lateral-raise", None, "submit")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_a: object) -> None:
        pass


threading.Thread(target=HTTPServer(("127.0.0.1", port + 1000), Seed).serve_forever, daemon=True).start()
http = server.make_server(app, port=port)
print(f"serving on {http.server_address[1]}", flush=True)
http.serve_forever()
