"""Test helper only: the real app (part7.server) at base path `/` with the staging test mailbox, the consent gate required and the Muse switch
on, so the consent step shows its Meta tick. Real sign-in, real `api/policy`, real `api/auth/*`; only Part 6 is a stand-in (support.FakeChild).
Run: python3 serve_consent_real.py <port>   (docs/specs/consent-and-age.md AC-CA20; used by consent_account.browser.mjs)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

port = int(sys.argv[1])
state = Path(tempfile.mkdtemp(prefix="s7-consent-"))
os.environ.setdefault("STAGING_ROUTE", "root")
os.environ.update(SIMON7_MAIL_TRANSPORT="outbox", SIMON7_STATE_DIR=str(state), SIMON7_KEYS_DIR=str(state / "keys"),
                  SIMON7_PUBLIC_ORIGIN=f"http://127.0.0.1:{port}", SIMON7_CONSENT_GATE="on", SIMON7_POLICY_MUSE="on")

from part7 import server  # noqa: E402
from support import FakeChild, make_lock  # noqa: E402

app = server.build_app(state, "/", child=FakeChild(state / "catalog"), lock=make_lock(), phrasing="template")
http = server.make_server(app, port=port)
print(f"serving on {http.server_address[1]}", flush=True)
http.serve_forever()
