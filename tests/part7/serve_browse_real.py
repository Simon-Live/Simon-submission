"""Test helper only: the real app (part7.server) with two published movements, for home-browse-real.browser.mjs. Real routes and
real `api/catalog/search`; only Part 6 is a stand-in (support.FakeChild). Run: python3 serve_browse_real.py <port>"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

port = int(sys.argv[1])
state = Path(tempfile.mkdtemp(prefix="s7-browse-"))
os.environ.setdefault("STAGING_ROUTE", "root")
os.environ.update(SIMON7_STATE_DIR=str(state), SIMON7_KEYS_DIR=str(state / "keys"), SIMON7_PUBLIC_ORIGIN=f"http://127.0.0.1:{port}")

from part7 import server  # noqa: E402
from support import FakeChild, make_lock, published  # noqa: E402

child = FakeChild(state / "catalog")
child.entries = {i: {"id": i, "name": name, "category": "exercise", "duration_ms": 20_000, "created_at": "2026-10-01T00:00:00Z",
                     "video_uri": None, "animation": "animation.json", "files_source": "mock"}
                 for i, name in (("squat-a", "Goblet squat"), ("raise-b", "Lateral raise"))}
app = server.build_app(state, "/", child=child, lock=make_lock(), phrasing="template")
published(state, *child.entries)
http = server.make_server(app, port=port)
print(f"serving on {http.server_address[1]}", flush=True)
http.serve_forever()
