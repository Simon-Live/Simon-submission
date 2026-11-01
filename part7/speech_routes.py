"""The spoken-line route `GET api/jobs/<job>/speech/<i>.wav` (docs/specs/voice.md); `server.py` calls `handle`.

Any problem answers 404 so the browser speaks the line itself: unknown job or index, a language without an MMS
voice, or a synthesis that failed. A line that is not made yet answers 202 (Retry-After) while one background thread
makes it, 503 while another line is being made, 429 when a visitor starts too many; the browser speaks the line itself
meanwhile and asks again on the next play. A request never starts a model download for an unfinished or unknown job.
"""

from __future__ import annotations

import json
from typing import Any

from part7 import jobs, speech

MSG_GONE = "This spoken line is not available."
RETRY_S = 3
# Answer of `speech.start` -> (status, message); `ready` is served, `failed` is a 404.
WAIT = {
    "pending": (202, "This spoken line is being made."),
    "started": (202, "This spoken line is being made."),
    "busy": (503, "Another spoken line is being made. Try again shortly."),
    "limited": (429, "Too many spoken lines requested. Try again shortly."),
    "failed": (404, MSG_GONE),
}


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `jobs/<job>/speech/<i>.wav`; False when the route is not one."""
    parts = route.split("/")
    if len(parts) != 4 or parts[0] != "jobs" or parts[2] != "speech" or not parts[3].endswith(".wav"):
        return False
    if method not in ("GET", "HEAD"):
        h._error(405, "Method not allowed.")
        return True
    made = _wav(h, parts[1], parts[3][: -len(".wav")])
    if isinstance(made, str):
        status, message = WAIT[made]
        if status == 404:
            h._error(404, message)
        else:
            body = json.dumps({"ok": status == 202, "message": message}).encode("utf-8")
            h._send(status, body, "application/json; charset=utf-8", {"Retry-After": str(RETRY_S)})
    elif made is None:
        h._error(404, MSG_GONE)
    else:
        h._send(200, made.read_bytes(), "audio/wav")
    return True


def _wav(h: Any, job_id: str, index_text: str) -> Any:
    """The cached wav `Path`, a `speech.start` state word to wait on, or None for a 404."""
    if not jobs.JOB_ID_RE.match(job_id) or not speech.INDEX_RE.match(index_text):
        return None
    job = h.app.queue.get(job_id)
    if not job or job.get("status") != "done" or job.get("kind") != "follow":
        return None
    job_dir = h.app.queue.job_dir(job_id)
    index = int(index_text)
    line = speech.line_of(speech.read_analysis(job_dir / "work" / "follower" / "analysis.json"), index)
    lang3 = speech.lang_code(line[0]) if line else None
    if line is None or lang3 is None:
        return None
    state = speech.start(job_dir, index, lang3, line[1], visitor=h._visitor() or "")
    return speech.cache_path(job_dir, index, lang3, line[1]) if state == "ready" else state
