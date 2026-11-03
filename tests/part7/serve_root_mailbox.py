"""Test helper only: the real app (part7.server) at base path `/` as staging's own origin serves it, with the staging test
mailbox on (STAGING_ROUTE=root, SIMON7_MAIL_TRANSPORT=outbox). Run: python3 serve_root_mailbox.py <port>.
Part 6 is a stand-in (tests/part7/support.FakeChild); everything under part7/auth*.py and staging_mailbox.py is real."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

port = int(sys.argv[1])
state = Path(tempfile.mkdtemp(prefix="s7-mailbox-"))
os.environ.setdefault("STAGING_ROUTE", "root")
os.environ.update(SIMON7_MAIL_TRANSPORT="outbox", SIMON7_STATE_DIR=str(state),
                  SIMON7_KEYS_DIR=str(state / "keys"), SIMON7_PUBLIC_ORIGIN=f"http://127.0.0.1:{port}")

from part7 import server  # noqa: E402
from support import FakeChild, make_lock  # noqa: E402

app = server.build_app(state, "/", child=FakeChild(state / "catalog"), lock=make_lock(), phrasing="template")
http = server.make_server(app, port=port)
print(f"serving on {http.server_address[1]}", flush=True)
http.serve_forever()
