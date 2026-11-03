"""Test helper only: the real app at base path `/` over a temporary state holding the SEEDED class of tools/seed_class.py
(six finished follow jobs from three seeded followers, `synthetic: true`), for tests/part7/handout_timing.mjs. Part 6 is
the stub of support.py, so the movement has no name and the page titles it by id. Nothing here is product code.

Run: python3 serve_class.py <port>
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

port = int(sys.argv[1])
state = Path(tempfile.mkdtemp(prefix="s7-class-"))
# no warm Part 2 workers: a test server must never hold the GPU (operator rule 09)
os.environ.update(SIMON7_STATE_DIR=str(state), SIMON7_KEYS_DIR=str(state / "keys"), SIMON7_STAGING="1", SIMON7_P2_WARM_WORKERS="0")

from part7 import server  # noqa: E402
from support import FakeChild, make_lock  # noqa: E402

SPEC = importlib.util.spec_from_file_location("seed_class", HERE.parent.parent / "tools" / "seed_class.py")
seed_class = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seed_class)  # type: ignore[union-attr]

ENTRY = "lateral-raise"
seed_class.seed(state, ENTRY)
app = server.build_app(state, "/", child=FakeChild(state / "catalog"), lock=make_lock(), phrasing="template")
http = server.make_server(app, port=port)
print(f"serving on {http.server_address[1]}", flush=True)
http.serve_forever()
