"""Test helper only: the real app at base path `/` with the staging mailbox on and five finished rehab-mode follow takes
of one movement on four days (the real Part 5 analysis and replay), for tests/part7/progress-sheet.browser.mjs.
Run: python3 serve_progress.py <port> <file for the job ids>."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

port, id_file = int(sys.argv[1]), Path(sys.argv[2])
state = Path(tempfile.mkdtemp(prefix="s7-progress-"))
os.environ.setdefault("STAGING_ROUTE", "root")
os.environ.update(SIMON7_P2_WARM_WORKERS="0", SIMON7_MAIL_TRANSPORT="outbox", SIMON7_STATE_DIR=str(state),
                  SIMON7_KEYS_DIR=str(state / "keys"), SIMON7_PUBLIC_ORIGIN=f"http://127.0.0.1:{port}")

from part7 import server  # noqa: E402
from progress_support import DAYS, REAL_ANALYSIS, REAL_REPLAY  # noqa: E402
from support import FakeChild, make_lock  # noqa: E402

app = server.build_app(state, "/", child=FakeChild(state / "catalog"), lock=make_lock(), phrasing="template")


def seed(ctx: object) -> dict:
    folder = ctx.work / "follower"  # type: ignore[attr-defined]
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REAL_ANALYSIS, folder / "analysis.json")
    shutil.copyfile(REAL_REPLAY, folder / "replay.json")
    return {"result": {}}



def write_tokens(ids: list[str]) -> None:
    """The creator token of each seeded take, as the device that made it holds them (prod-data.md, LEG-H4)."""
    from part7 import creator
    Path(f"{id_file}.tokens.json").write_text(json.dumps({j: creator.token_for(app.state, j) for j in ids}))

ids = []
for day in DAYS:
    made = app.queue.submit("follow", seed, entry_id="lateral-raise", mode="rehab")
    app.queue.wait(made["id"], 20)
    record_path = app.queue.job_dir(made["id"]) / "job.json"
    record = json.loads(record_path.read_text())
    record["finished_at"] = f"{day}T09:05:00Z"  # the claim copies this day: five sessions on four days
    record_path.write_text(json.dumps(record))
    ids.append(made["id"])
trainer = app.queue.submit("trainer", lambda ctx: {"result": {"entry_id": "lateral-raise"}}, entry_id=None)  # its claim makes the owner the entry's author
app.queue.wait(trainer["id"], 20)
ids.append(trainer["id"])  # the last line: the trainer job behind the movement
write_tokens(ids)
id_file.write_text("\n".join(ids))
http = server.make_server(app, port=port)
print(f"serving on {http.server_address[1]}", flush=True)
http.serve_forever()
