"""Test helper only: serves web/ plus a tiny fake of the Part 7 API and the Part 6 proxy.

Not the product server (part7/server.py). Run: python3 fake_api.py <port>
`GET __test/state` returns what the fake saw (uploads, jobs created) for the driver's witnesses.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_challenges  # noqa: E402  (challenge lane: in-memory api/challenges)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from part7 import ghost as part7_ghost  # noqa: E402  (TICKET-264: the real ghost builder on the fake animation)

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
FIXTURES = ROOT / "fixtures" / "input"
MIME = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".md": "text/plain"}

FAKE_BUILD = {"sha": "fake (test server)", "short": "fake (test server)", "subject": "fake (test server)",
              "started_at": "unknown", "committed_at": "unknown", "parts": {}}
ENTRIES = [
    {"id": "lateral-raise", "name": "Dumbbell lateral raise", "category": "exercise", "files_source": "import",
     "video_uri": "video.webm", "animation": "animation.json", "skeleton": "skeleton.json"},
    {"id": "reverse-lunge", "name": "Reverse lunge", "category": "exercise", "files_source": "fixture",
     "video_uri": None, "animation": None, "skeleton": "skeleton.json"},
    {"id": "salsa-basic", "name": "Salsa basic step", "category": "dance", "files_source": "fixture",
     "video_uri": None, "animation": "animation.json", "skeleton": "skeleton.json"},
]
TRAINER_STAGES = ["upload", "keyframes", "pose", "skeleton", "animation", "catalog"]
FOLLOW_STAGES = ["upload", "pose", "skeleton", "analyse"]

STATE = {"uploads": [], "jobs": {}, "polls": {}, "range_requests": 0, "people_jobs": 0, "idem": {}, "replays": 0,
         "people": None}
STATE["ghost_requests"] = 0  # TICKET-264: how often the ghost was asked for
# TICKET-260: the stage split a done follow job answers with (part7/stage_split.py); POST __test/timing changes it
TIMING = {"recorded": True, "status": "ok", "total_s": 41.2, "picker": "skipped", "people_s": 9.4,
          "stages": [{"name": "upload", "seconds": 0.4}, {"name": "pose", "seconds": 33.1}, {"name": "analyse", "seconds": 7.7}]}
STATE["timing"] = TIMING
_video = {}


def video_bytes() -> bytes:
    if "b" not in _video:
        out = Path(tempfile.mkdtemp()) / "t.webm"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15",
                        "-t", "3", "-c:v", "libvpx", "-b:v", "200k", str(out)], check=True)
        _video["b"] = out.read_bytes()
    return _video["b"]


# A small standing figure in the shape of a real animation.json: named joints, 3D points per frame
# (the left wrist swings), bones. The Watch viewer needs `joints` to draw anything (TICKET-068).
_FIGURE = {
    "nose": (0, 1.7, 0), "left_shoulder": (0.2, 1.5, 0), "right_shoulder": (-0.2, 1.5, 0),
    "left_elbow": (0.3, 1.25, 0), "right_elbow": (-0.3, 1.25, 0), "left_wrist": (0.35, 1.0, 0),
    "right_wrist": (-0.35, 1.0, 0), "left_hip": (0.12, 1.0, 0), "right_hip": (-0.12, 1.0, 0),
    "left_knee": (0.12, 0.55, 0), "right_knee": (-0.12, 0.55, 0), "left_ankle": (0.12, 0.1, 0),
    "right_ankle": (-0.12, 0.1, 0),
}


def animation() -> dict:
    frames = []
    for i in range(30):
        pts = {n: list(p) for n, p in _FIGURE.items()}
        pts["left_wrist"] = [0.35 + 0.002 * i, 1.0 + 0.01 * i, 0]
        frames.append({"t": i / 30, "joints": pts})
    return {"fps": 30, "joints": list(_FIGURE), "bones": [], "frames": frames}


def people_job_view(job_id: str) -> tuple[int, dict]:
    """The people check every take runs after the trim: one person found, so the picker is skipped."""
    person = {"id": "0", "coverage": 0.9, "frames": 40, "box_mid": [10, 10, 50, 120]}
    result = {"people": [person], "auto_id": "0", "frame": "people/frame.jpg"}
    if STATE.get("people"):  # a test chose the people job's answer (POST __test/people), e.g. two people and no auto_id
        result = {**STATE["people"], "frame": "people/frame.jpg"}
    return 200, {"id": job_id, "kind": "people", "status": "done", "stage": "people", "entry_id": None, "note": "",
                 "queue_position": None, "result": result}


def job_view(job_id: str) -> tuple[int, dict]:
    if job_id.startswith("pj"):
        return people_job_view(job_id)
    job = STATE["jobs"].get(job_id)
    if not job:
        return 404, {"error": "unknown job"}
    n = STATE["polls"][job_id] = STATE["polls"].get(job_id, 0) + 1
    stages = TRAINER_STAGES if job["kind"] == "trainer" else FOLLOW_STAGES
    base = {"id": job_id, "kind": job["kind"], "entry_id": job.get("entry_id"), "result": None, "note": ""}
    if job_id.startswith("bad"):
        return 200, {**base, "status": "failed", "stage": "pose", "note": "No person was found in the video.", "queue_position": None}
    if n == 1:
        return 200, {**base, "status": "queued", "stage": stages[0], "queue_position": 2}
    if n - 2 < len(stages):
        return 200, {**base, "status": "running", "stage": stages[n - 2], "queue_position": None}
    entry = "lateral-raise" if job["kind"] == "trainer" else job.get("entry_id")
    timing = {"timing": STATE["timing"]} if job["kind"] == "follow" and STATE.get("timing") is not None else {}
    return 200, {**base, "status": "done", "stage": stages[-1], "entry_id": entry, "queue_position": None, **timing}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # quiet
        pass

    def send(self, code, body=b"", ctype="application/json", extra=None):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0].lstrip("/")
        if path == "api/challenges" or path.startswith("api/challenges/"):
            return fake_challenges.get(self, self.path)
        if path.startswith("__harness/"):  # harness pages beside the tests, served at /__harness/<file>
            page = (Path(__file__).resolve().parent / "harness" / path[len("__harness/"):]).resolve()
            ok = page.is_file() and page.parent == (Path(__file__).resolve().parent / "harness")
            return self.send(200, page.read_bytes(), MIME.get(page.suffix, "text/html")) if ok else self.send(404, {"error": "not found"})
        if path == "api/config":
            return self.send(200, {"base": "", "limits": {"max_seconds": 60, "max_bytes": 95000000, "recorder_bps": 2500000},
                                   "phrasing": "template", "movement": "lateral-raise", "fixture_result": True,
                                   "part5": {"lang": True, "video": True, "private": True}})
        if path == "api/health":  # says plainly that this is the test stand-in (TICKET-204): the app shows a banner
            return self.send(200, {"ok": True, "fake": True, "build": FAKE_BUILD})
        if path == "api/version":
            return self.send(200, FAKE_BUILD)
        if path == "__test/state":
            return self.send(200, STATE)
        if path == "catalog/api/entries":
            return self.send(200, {"entries": ENTRIES})
        m = re.match(r"catalog/api/entries/([^/]+)(?:/(.+))?$", path)
        if m:
            return self.entry(m.group(1), m.group(2))
        if path == "catalog/":
            return self.send(200, b"<!doctype html><title>Entry</title><p>Part 6 entry page</p>", "text/html")
        m = re.match(r"api/jobs/([^/]+)$", path)
        if m:
            return self.send(*job_view(m.group(1)))
        if re.match(r"api/jobs/[^/]+/muse-fix$", path):  # TICKET-280: what the real route answers for a take with no corrected pose
            return self.send(200, {"eligible": False, "consent": False, "running": False, "card": None, "image": None, "referee": None})
        m = re.match(r"api/ghost/([^/]+)\.json$", path)
        if m:  # the trainer's ghost (part7/ghost.py on this fake's animation); an entry with no animation has none
            STATE["ghost_requests"] += 1
            has = any(e["id"] == m.group(1) and e.get("animation") for e in ENTRIES)
            doc = part7_ghost.build(animation()) if has else None
            return self.send(200, {**doc, "available": True, "entry_id": m.group(1), "source": "animation"} if doc
                             else {"available": False, "entry_id": m.group(1), "reason": part7_ghost.MSG_NONE})
        if path == "api/fixture-result":
            return self.send(200, {"analysis": json.loads((FIXTURES / "analysis-1.2.0.json").read_text()),
                                   "replay": json.loads((FIXTURES / "replay.json").read_text())})
        if re.match(r"api/results/([^/]+)/([^/]+/)?video\.mp4$", path):  # the follower clip (result_media.py), Range like the app
            return self.follower_video()
        m = re.match(r"api/results/([^/]+)/(analysis|replay)\.json$", path)
        if m:
            f = "analysis-1.2.0.json" if m.group(2) == "analysis" else "replay.json"
            return self.send(200, (FIXTURES / f).read_bytes())
        return self.static(path)

    def follower_video(self):
        data, rng = video_bytes(), self.headers.get("Range")
        STATE["follower_video"] = STATE.get("follower_video", 0) + 1
        if rng:
            a, _, b = rng.removeprefix("bytes=").partition("-")
            start, end = int(a or 0), int(b) if b else len(data) - 1
            return self.send(206, data[start:end + 1], "video/webm", {"Content-Range": f"bytes {start}-{end}/{len(data)}"})
        return self.send(200, data, "video/webm")

    def entry(self, eid, file):
        entry = next((e for e in ENTRIES if e["id"] == eid), None)
        if not entry:
            return self.send(404, {"error": "not found"})
        if file is None:
            return self.send(200, entry)
        if file == "animation.json":
            return self.send(200, animation())
        if file == "video.webm":
            data, rng = video_bytes(), self.headers.get("Range")
            if rng:
                STATE["range_requests"] += 1
                a, _, b = rng.removeprefix("bytes=").partition("-")
                start = int(a or 0)
                end = int(b) if b else len(data) - 1
                return self.send(206, data[start:end + 1], "video/webm",
                                 {"Content-Range": f"bytes {start}-{end}/{len(data)}"})
            return self.send(200, data, "video/webm")
        return self.send(404, {"error": "not found"})

    def static(self, path):
        p = (WEB / (path or "index.html")).resolve()
        if p.is_dir():
            p = p / "index.html"
        if WEB not in p.parents or not p.is_file():
            return self.send(404, {"error": "not found"})
        return self.send(200, p.read_bytes(), MIME.get(p.suffix, "application/octet-stream"))

    def do_POST(self):
        path = self.path.split("?")[0].lstrip("/")
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        key = (self.headers.get("Idempotency-Key") or "").strip().lower()
        idem_route = path in ("api/uploads", "api/trainer", "api/follow", "api/group") and re.fullmatch(r"[0-9a-f-]{36}", key)
        ikey = f"{path}|{key}"
        if path.startswith("api/challenges") or path == "__test/challenges":
            return fake_challenges.post(self, self.path, body)
        if idem_route and ikey in STATE["idem"]:  # the same key on the same route: the original answer, nothing new
            STATE["replays"] += 1
            code, answer = STATE["idem"][ikey]
            return self.send(code, answer)
        if path == "__test/reset":  # forget uploads, jobs, keys and the chosen people answer
            STATE.update({"uploads": [], "jobs": {}, "polls": {}, "people_jobs": 0, "idem": {}, "replays": 0, "people": None})
            STATE.update({"timing": TIMING, "ghost_requests": 0})  # ours (TICKET-260, TICKET-264), beside the client's line
            return self.send(200, {"ok": True})
        if path == "__test/timing":  # the next done follow jobs answer with this timing (null: no field)
            STATE["timing"] = json.loads(body or b"null")
            return self.send(204)
        if path == "__test/people":  # the next people jobs answer with this {people, auto_id}
            STATE["people"] = json.loads(body or b"null")
            return self.send(200, {"ok": True})
        code, answer = self.create(path, body)
        if idem_route and code in (201, 202):
            STATE["idem"][ikey] = (code, answer)
        return self.send(code, answer) if code != 204 else self.send(204)

    def create(self, path, body):
        """The POST routes; returns (status, body). Kept apart so a repeated Idempotency-Key can replay the answer."""
        if path == "api/uploads":
            if not (self.headers.get("Content-Type") or "").startswith("video/"):
                return 400, {"error": "not a video"}
            STATE["uploads"].append({"size": len(body), "type": self.headers.get("Content-Type")})
            return 201, {"upload_id": f"u{len(STATE['uploads'])}", "duration_ms": 3000, "width": 320, "height": 240}
        if path == "api/people":
            STATE["people_jobs"] += 1
            return 202, {"job": f"pj{STATE['people_jobs']}"}
        if path == "api/client-log":  # the browser's own events (app.md "Client log"), as the real app answers
            return 204, None
        data = json.loads(body or b"{}")
        if path in ("api/trainer", "api/follow", "api/group"):
            kind = path.rsplit("/", 1)[1]
            if kind == "follow" and data.get("entry_id") == "nope":
                return 404, {"error": "unknown entry"}
            jid = f"bad{len(STATE['jobs'])}" if data.get("name") == "Fails" else f"job{len(STATE['jobs']) + 1}"
            STATE["jobs"][jid] = {"kind": kind, **data}
            return 202, {"job": {"id": jid}}
        return 404, {"error": "not found"}


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
