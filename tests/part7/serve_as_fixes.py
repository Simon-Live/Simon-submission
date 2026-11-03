"""Test helper only: serve_share.py plus one trainer account that already owns the entry `lateral-raise` (made directly in
the identity store, labelled seeded), for tests/part7/as_fixes.browser.mjs. Everything else is the real app and real routes.
Run: python3 serve_as_fixes.py <port> <file for the seeded job id>. The trainer signs in with coach@example.com."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

port, id_file = int(sys.argv[1]), Path(sys.argv[2])
state = Path(tempfile.mkdtemp(prefix="s7-asfix-"))
os.environ.setdefault("STAGING_ROUTE", "root")
os.environ.update(SIMON7_MAIL_TRANSPORT="outbox", SIMON7_STATE_DIR=str(state),
                  SIMON7_KEYS_DIR=str(state / "keys"), SIMON7_PUBLIC_ORIGIN=f"http://127.0.0.1:{port}")

from part7 import auth, server  # noqa: E402
from support import FakeChild, make_lock  # noqa: E402

app = server.build_app(state, "/", child=FakeChild(state / "catalog"), lock=make_lock(), phrasing="template")
FIXTURE = HERE / "fixtures" / "history" / "5277380db1e1" / "analysis.json"
store = auth.identity(app)
coach = store._user_for("coach@example.com", time.time())  # seeded: the trainer who owns the entry
store.attach_entry("lateral-raise", coach)


def seed(ctx: object) -> dict:
    folder = ctx.work / "follower"  # type: ignore[attr-defined]
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE, folder / "analysis.json")
    return {"result": {}}


made = app.queue.submit("follow", seed, entry_id="lateral-raise")
app.queue.wait(made["id"], 20)
id_file.write_text(made["id"])
http = server.make_server(app, port=port)
print(f"serving on {http.server_address[1]}", flush=True)
http.serve_forever()
