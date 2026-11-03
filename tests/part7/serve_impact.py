"""Test helper only: the REAL Part 7 app on a throwaway state folder, seeded for the Impact page's browser test.

Run: python3 serve_impact.py <port>. Served under `/simon-part-7/`. Seeds three finished follow takes through the real
queue and a `persona-takes.json` in the state folder: `seated` and `home-rehab` name real takes, `remote-class` names a
QA take (which the page must not show) and `bodies` is not listed. Prints `ready <json of the seeded ids>`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="impact-real-"))
os.environ["SIMON7_KEYS_DIR"] = str(TMP / "keys")
os.environ["SIMON7_P2_WARM_WORKERS"] = "0"  # a test server never holds the GPU with a warm Part 2 worker
(TMP / "keys").mkdir()
for name in ("STAGING_BASE_PATH", "STAGING_ROUTE", "SIMON7_MAIL_TRANSPORT", "SIMON7_PERSONA_TAKES"):
    os.environ.pop(name, None)

from part7 import impact, server  # noqa: E402
from support import FakeChild, make_lock  # noqa: E402

CLIP = {"url": "https://www.pexels.com/video/test-clip/", "licence": "Pexels License", "file": "videos/test/take.mp4"}


def finished(app: server.App, entry: str, score: float, mode: str) -> str:
    rec = app.queue.submit("follow", lambda ctx: {"result": {"entry_id": entry, "score": score}}, entry_id=entry, mode=mode)
    assert app.queue.wait(rec["id"], 10)["status"] == "done"
    return rec["id"]


def row(persona: str, job_id: str, entry: str, mode: str) -> dict:
    return {"persona": persona, "job_id": job_id, "entry_id": entry, "take_url": "", "trainer_entry_url": "", "score": None,
            "mode": mode, "clip_source": CLIP, "why_this_clip": "Chosen for the browser test.",
            "recorded_utc": "2026-11-02T00:00:00Z", "staging_sha": "test"}


def main(port: int) -> None:
    app = server.build_app(TMP / "state", "/simon-part-7/", child=FakeChild(TMP / "catalog"), lock=make_lock(), phrasing="template")
    seated = finished(app, "seated-stretch-1a2b3c4d", 71, "rehab")
    rehab = finished(app, "shoulder-raise-5e6f7a8b", 66.4, "rehab")
    qa = finished(app, "qa-journey-qamvxvd3y", 99, "dance")
    rows = [row("seated", seated, "seated-stretch-1a2b3c4d", "rehab"), row("home-rehab", rehab, "shoulder-raise-5e6f7a8b", "rehab"),
            row("remote-class", qa, "qa-journey-qamvxvd3y", "dance")]
    (app.state / impact.STATE_FILE).write_text(json.dumps(rows), encoding="utf-8")
    http = server.make_server(app, port=port)
    print("ready " + json.dumps({"seated": seated, "home-rehab": rehab, "qa": qa}), flush=True)
    http.serve_forever()


if __name__ == "__main__":
    main(int(sys.argv[1]))
