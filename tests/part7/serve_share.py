"""Test helper only: the real app at base path `/` with the staging mailbox on and one finished follow take seeded
(a real analysis file), for tests/part7/share.browser.mjs. Run: python3 serve_share.py <port> <file for the job id>."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

port, id_file = int(sys.argv[1]), Path(sys.argv[2])
state = Path(tempfile.mkdtemp(prefix="s7-share-"))
os.environ.setdefault("STAGING_ROUTE", "root")
os.environ.update(SIMON7_MAIL_TRANSPORT="outbox", SIMON7_STATE_DIR=str(state),
                  SIMON7_KEYS_DIR=str(state / "keys"), SIMON7_PUBLIC_ORIGIN=f"http://127.0.0.1:{port}")

from part7 import auth, server  # noqa: E402
from support import FakeChild, make_lock  # noqa: E402

app = server.build_app(state, "/", child=FakeChild(state / "catalog"), lock=make_lock(), phrasing="template")
FIXTURE = HERE / "fixtures" / "history" / "cc7cd5469055" / "analysis.json"
FAULTS = [{"text": "right elbow bent more than the example"}, {"text": "arms not raised far enough forward"}]


def seed(ctx: object) -> dict:
    """The fixture take with two faults, so share.browser.mjs can compare the preview's faults with the viewer's."""
    folder = ctx.work / "follower"  # type: ignore[attr-defined]
    folder.mkdir(parents=True, exist_ok=True)
    analysis = json.loads(FIXTURE.read_text())
    (folder / "analysis.json").write_text(json.dumps({**analysis, "faults": analysis.get("faults") or FAULTS}))
    return {"result": {}}


INPUT = HERE.parent.parent / "fixtures" / "input"


def seed_capped(ctx: object) -> dict:
    """A warning-capped take (the low-match hero, 59 F) carrying analysis-credit.json's credit block (9,087 of 12,160, C),
    which ignores the cap: the shape of staging take f530a6875dfb (docs/specs/share.md "Score and cap")."""
    folder = ctx.work / "follower"  # type: ignore[attr-defined]
    folder.mkdir(parents=True, exist_ok=True)
    hero = json.loads((INPUT / "analysis-low-match-hero.json").read_text())
    credit = json.loads((INPUT / "analysis-credit.json").read_text())["score"]["credit"]
    (folder / "analysis.json").write_text(json.dumps({**hero, "score": {**hero["score"], "credit": credit}}))
    return {"result": {}}



def write_tokens(ids: list[str]) -> None:
    """The creator token of each seeded take, as the device that made it holds them (prod-data.md, LEG-H4)."""
    from part7 import creator
    Path(f"{id_file}.tokens.json").write_text(json.dumps({j: creator.token_for(app.state, j) for j in ids}))

made = app.queue.submit("follow", seed, entry_id="lateral-raise")
app.queue.wait(made["id"], 20)
capped = app.queue.submit("follow", seed_capped, entry_id="lateral-raise")
app.queue.wait(capped["id"], 20)
write_tokens([made["id"], capped["id"]])
id_file.with_suffix(".capped").write_text(capped["id"])
id_file.write_text(made["id"])  # written last: the drive starts when this file exists

def _skew() -> float:
    """Test helper only: seconds the clock is moved on, read from `<file>.skew` so share.browser.mjs can let a link expire."""
    try:
        return float(Path(f"{id_file}.skew").read_text())
    except (OSError, ValueError):
        return 0.0


auth.CLOCK = lambda: time.time() + _skew()
http = server.make_server(app, port=port)
print(f"serving on {http.server_address[1]}", flush=True)
http.serve_forever()
