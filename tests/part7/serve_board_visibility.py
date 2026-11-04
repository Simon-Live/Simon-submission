"""Test helper only: the real app (part7.server) at base path `/` in local mode with the FILE mail transport, so every mail
(sign-in codes and board invites) is written as an .eml under `<state>/outbox` and no real mail is sent.
Run: python3 serve_board_visibility.py <port> <state-dir>. Part 6 is a stand-in (tests/part7/support.FakeChild)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

port, state = int(sys.argv[1]), Path(sys.argv[2])
state.mkdir(parents=True, exist_ok=True)
for name in ("STAGING_ROUTE", "STAGING_BASE_PATH", "SIMON7_MAIL_TRANSPORT"):
    os.environ.pop(name, None)
os.environ.update(SIMON7_STATE_DIR=str(state), SIMON7_KEYS_DIR=str(state / "keys"), SIMON7_PUBLIC_ORIGIN=f"http://127.0.0.1:{port}")

from part7 import entry_access, server  # noqa: E402
from support import FakeChild, make_lock  # noqa: E402

app = server.build_app(state, "/", child=FakeChild(state / "catalog"), lock=make_lock(), phrasing="template")
entry_access.record(state, "lateral-raise", published=True, age_band="adult")
http = server.make_server(app, port=port)
print(f"serving on {http.server_address[1]}", flush=True)
http.serve_forever()
