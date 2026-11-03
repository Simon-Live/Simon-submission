"""Test helper only: the real app (part7.server) at base path `/` with the staging test mailbox on and two SEEDED accounts
(invented, labelled seeded): ada@example.com keeps 3 takes and a report, grace@example.com keeps 2 takes of another movement.
Run: python3 serve_export_seed.py <port>. Part 6 is a stand-in (support.FakeChild); every route is the real one."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

port = int(sys.argv[1])
state = Path(tempfile.mkdtemp(prefix="s7-export-"))
os.environ.setdefault("STAGING_ROUTE", "root")
os.environ.update(SIMON7_MAIL_TRANSPORT="outbox", SIMON7_STATE_DIR=str(state),
                  SIMON7_KEYS_DIR=str(state / "keys"), SIMON7_PUBLIC_ORIGIN=f"http://127.0.0.1:{port}")

from export_seed import ENTRY, seed_report, seed_takes  # noqa: E402
from part7 import identity, profile, server  # noqa: E402
from support import FakeChild, make_lock  # noqa: E402

store = identity.IdentityStore(state, b"seeded-pepper-not-used-by-the-app")
ada, grace = (store._user_for(email, store.clock()) for email in ("ada@example.com", "grace@example.com"))
store.set_consent(ada, "retention-90-v2", True)
ada_jobs = seed_takes(state, store, ada, "ada", 3)
seed_takes(state, store, grace, "grace", 2, entry="side-lunge-0a1b2c3d")
seed_report(state, ada, ENTRY, ada_jobs)
profile.update(store, ada, {"public_name": "Ada L"})
profile.update(store, grace, {"public_name": "Grace Secret"})

app = server.build_app(state, "/", child=FakeChild(state / "catalog"), lock=make_lock(), phrasing="template")
http = server.make_server(app, port=port)
print(f"serving on {http.server_address[1]}", flush=True)
http.serve_forever()
