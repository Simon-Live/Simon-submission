"""Test helper only: the real app at base path `/` with ONE SEEDED finished group job stored the way staging jobs
dbf5d47d974d and 6be0bf0fb8fc were (44's dance run, 2026-11-02): four people, every one capped by low_match in their own
analysis.json, and no `shown` block in the stored result. For tests/part7/group_capped.browser.mjs. Nothing here is
product code.

Run: python3 serve_group_capped.py <port> <file for the job id as JSON>
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

port, id_file = int(sys.argv[1]), Path(sys.argv[2])
state = Path(tempfile.mkdtemp(prefix="s7-group-capped-"))
# no warm Part 2 workers: a test server must never hold the GPU (operator rule 09)
os.environ.update(SIMON7_STATE_DIR=str(state), SIMON7_KEYS_DIR=str(state / "keys"), SIMON7_P2_WARM_WORKERS="0")

from part7 import group, server  # noqa: E402
from support import FakeChild, make_lock  # noqa: E402

ENTRY = "dance-real-people"
# the shape of the staging people (score, grade F, status ok) and of their analyses (capped by low_match, with credit)
PEOPLE = {"1": 59, "4": 59, "0": 53, "2": 0}
CREDIT = {"version": "simon.credit.v1", "percent": 61.0, "grade": "D", "points": 9000, "max_points": 14754, "tolerance": "normal"}
app = server.build_app(state, "/", child=FakeChild(state / "catalog"), lock=make_lock(), phrasing="template")


def seed(ctx: object) -> dict:
    rows = []
    for pid, value in PEOPLE.items():
        folder = group.person_dir(ctx.dir, pid)  # type: ignore[attr-defined]
        folder.mkdir(parents=True, exist_ok=True)
        doc = {"status": {"code": "ok"}, "warnings": [{"code": "low_match", "text": "Low match."}],
               "score": {"value": value, "grade": "F", "capped_by": ["low_match"], "uncapped": {"value": 70, "grade": "C"}, "credit": CREDIT}}
        (folder / "analysis.json").write_text(json.dumps(doc), encoding="utf-8")
        rows.append({"id": pid, "label": "", "status_code": "ok", "score": value, "grade": "F", "faults": 0,
                     "analysis": f"api/results/{ctx.id}/{pid}/analysis.json", "replay": None})  # type: ignore[attr-defined]
    return {"result": {"entry_id": ENTRY, "trainer_id": 9, "people": rows}}


made = app.queue.submit("group", seed, entry_id=ENTRY, _people_owner="")  # made signed out: its id is its key (upload_owner.people_owner)
app.queue.wait(made["id"], 20)
id_file.write_text(json.dumps({"job": made["id"]}))
http = server.make_server(app, port=port)
print(f"serving on {http.server_address[1]}", flush=True)
http.serve_forever()
