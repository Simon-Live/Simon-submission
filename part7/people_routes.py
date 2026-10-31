"""HTTP routes of people choice and group mode (people.md "Part 7 server"); `server.py` calls `handle` first.

`handle(h, method, route)` answers the people, group, picture and per-person result routes and returns True;
`selection(h, doc)` reads `people_job` and `person_id` from a trainer or follow request.
"""

from __future__ import annotations

from pathlib import Path
import re
import threading
from typing import Any

from part7 import group, jobs, labels, media, people, quota, replay

PID_RE = re.compile(r"^[0-9A-Za-z_-]{1,40}$")
LABEL_MAX = 40
NAME_MAX = 80
MSG_NAME = "Give the movement a name of 80 characters at most."
MSG_CATEGORY = "Pick exercise or dance."
MSG_PEOPLE_GONE = "The people in this clip are no longer available. Choose the person again."
MSG_CHOOSE = "Choose who the recording is about."
MSG_NOT_THERE = "That person is not in the clip."
MSG_GROUP_LONG = "Group mode takes 30 seconds at most. Trim the clip shorter."
MSG_FOLLOWERS = "Choose 1 to 8 people to analyse."
MSG_TRAINER = "Choose one person as the trainer, and not among the people to analyse."
MSG_BUSY = "Your group is still being analysed. Wait for it to finish."
GROUP_ACTIVE = ("queued", "running")
_LOCK = threading.Lock()


# ----- shared request pieces ----------------------------------------------------------------------
def _people_result(h: Any, job_id: Any) -> tuple[dict[str, Any], Path] | None:
    """A finished people job's result and work folder, or None when it is not (or no longer) there."""
    if not isinstance(job_id, str) or not jobs.JOB_ID_RE.match(job_id):
        return None
    job = h.app.queue.get(job_id)
    if not job or job.get("kind") != "people" or job.get("status") != "done" or not isinstance(job.get("result"), dict):
        return None
    work = h.app.queue.job_dir(job_id) / "work"
    return (job["result"], work) if (work / "clip.mp4").is_file() and (work / "tracks.json").is_file() else None


def clip_record(h: Any, job_id: str) -> dict[str, Any]:
    """The job-record fields (`trim`, `duration_ms`) of a people job, which already cut the clip."""
    job = h.app.queue.get(job_id) or {}
    return {"trim": job.get("trim"), "duration_ms": job.get("duration_ms")}


def selection(h: Any, doc: dict[str, Any]) -> tuple[bool, people.PersonSel | None]:
    """`(True, sel)` from `people_job` and `person_id` (both absent: `(True, None)`); else answers 400, `(False, None)`."""
    job_id, pid = doc.get("people_job"), doc.get("person_id")
    if job_id is None and pid is None:
        return (True, None)
    found = _people_result(h, job_id)
    if found is None:
        h._error(400, MSG_PEOPLE_GONE)
        return (False, None)
    result, work = found
    pid = str(pid) if pid is not None else result.get("auto_id")
    if pid is None:
        h._error(400, MSG_CHOOSE)
        return (False, None)
    if pid not in {p["id"] for p in result["people"]}:
        h._error(400, MSG_NOT_THERE)
        return (False, None)
    return (True, people.PersonSel(id=pid, people_work=work))


# ----- POST api/people ----------------------------------------------------------------------------------
def _post_people(h: Any) -> None:
    doc = h._body_json()
    if doc is None:
        return
    raw = h._upload_for(doc)
    if raw is None:
        return
    clip = h._clip(doc, raw)  # one trim parser: the recorder's rules (recorder.md "Trim rules")
    if clip is None:
        return
    fn = people.people_job(raw, trim=clip[0], lock=h.app.lock, backend=h.app.backend)
    h._enqueue("people", fn, quota_kind="follow")  # finding people uses the GPU: it counts as one GPU job


# ----- POST api/group -----------------------------------------------------------------------------------
def _ids(value: Any) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(v, (str, int)) and not isinstance(v, bool) for v in value):
        return None
    return [str(v) for v in value]


def _labels(value: Any) -> tuple[dict[str, str], dict[str, Any]] | str:
    """Split `labels` into per-person names and the entry's `{tags, notes}`; the plain message when invalid."""
    if value is None:
        return ({}, {})
    if not isinstance(value, dict):
        return labels.MSG_LABELS
    try:
        entry = labels.validate({"tags": value.get("tags") or [], "notes": value.get("notes") or ""})
    except labels.LabelsError as exc:
        return str(exc)
    names = {str(k): str(v).strip()[:LABEL_MAX] for k, v in value.items() if k not in ("tags", "notes") and v}
    return (names, entry)


def _group_request(h: Any, doc: dict[str, Any]) -> dict[str, Any] | None:
    """Validate a group request; answers 400 itself and returns None, else the pieces the job needs."""
    name, category = str(doc.get("name") or "").strip(), str(doc.get("category") or "")
    if not 1 <= len(name) <= NAME_MAX:
        return h._error(400, MSG_NAME)
    if category not in ("exercise", "dance"):
        return h._error(400, MSG_CATEGORY)
    found = _people_result(h, doc.get("people_job"))
    if found is None:
        return h._error(400, MSG_PEOPLE_GONE)
    result, work = found
    followers, trainer = _ids(doc.get("follower_ids")), str(doc.get("trainer_id", ""))
    if followers is None or not 1 <= len(followers) <= people.GROUP_MAX_FOLLOWERS or len(set(followers)) != len(followers):
        return h._error(400, MSG_FOLLOWERS)
    known = {p["id"] for p in result["people"]}
    if trainer not in known or trainer in followers:
        return h._error(400, MSG_TRAINER)
    if not set(followers) <= known:
        return h._error(400, MSG_NOT_THERE)
    if media.probe(work / "clip.mp4")["duration_s"] > people.GROUP_MAX_SECONDS + 0.05:
        return h._error(400, MSG_GROUP_LONG)
    split = _labels(doc.get("labels"))
    if isinstance(split, str):
        return h._error(400, split)
    return {"name": name, "category": category, "work": work, "trainer": trainer, "followers": followers,
            "labels": split[0], "entry_labels": split[1], "save_entry": doc.get("save_entry", True) is not False}


def _post_group(h: Any) -> None:
    doc = h._body_json()
    if doc is None:
        return
    req = _group_request(h, doc)
    if req is None:
        return
    practice = h._practice(doc)  # mode is kept and used; a section is ignored for a group (practice-and-modes.md)
    if practice is None:
        return
    mode = practice.get("mode")
    app, visitor = h.app, h._visitor()
    key = quota.visitor_key(visitor)
    fn = group.group_job(
        people_work=req["work"], trainer_id=req["trainer"], follower_ids=req["followers"], name=req["name"],
        category=req["category"], catalog=app.child.catalog_dir, labels=req["labels"],
        entry_labels=req["entry_labels"], labels_state=app.state, save_entry=req["save_entry"],
        lock=app.lock, backend=app.backend, phrasing=app.phrasing, mode=mode,
    )
    with _LOCK:
        active = app.__dict__.setdefault("group_jobs", {})
        previous = app.queue.get(active[key]) if key in active else None
        if previous and previous["status"] in GROUP_ACTIVE:
            return h._error(429, MSG_BUSY)
        job = _submit_group(h, fn, 1 + len(req["followers"]), **({"mode": mode} if mode else {}))
        if job is not None and key:
            active[key] = job["id"]


def _submit_group(h: Any, fn: jobs.JobFn, gpu_jobs: int, **record: Any) -> dict[str, Any] | None:
    """Reserve 1 trainer job and the follower GPU jobs, queue `fn`; answers 202, 429 or 503."""
    app, visitor = h.app, h._visitor()
    if not app.queue.has_room():
        return h._error(503, jobs.QUEUE_FULL_MESSAGE)
    kinds = ["trainer", *["follow"] * (gpu_jobs - 1)]
    taken: list[str] = []
    try:
        for kind in kinds:
            app.quota.reserve(kind, visitor)
            taken.append(kind)
        job = app.queue.submit("group", fn, **record)
    except (quota.VisitorQuotaError, quota.DailyCapError, jobs.QueueFullError) as exc:
        for kind in taken:
            app.quota.release(kind, visitor)
        status = 429 if isinstance(exc, quota.VisitorQuotaError) else 503
        h._error(status, jobs.QUEUE_FULL_MESSAGE if isinstance(exc, jobs.QueueFullError) else str(exc))
        return None
    h._json(202, {"job": job["id"], **job})
    return job


# ----- GET routes ---------------------------------------------------------------------------------------
def _get_picture(h: Any, job_id: str, name: str) -> None:
    stem = name[:-4]
    job = h.app.queue.get(job_id) if jobs.JOB_ID_RE.match(job_id) else None
    path = h.app.queue.job_dir(job_id) / "people" / name
    if not name.endswith(".jpg") or not (stem == "frame" or PID_RE.match(stem)) or not job or job["kind"] != "people":
        return h._error(404, "Not found.")
    if not path.is_file():
        return h._error(404, "This picture is not available.")
    h._send(200, path.read_bytes(), "image/jpeg")


def _get_person_result(h: Any, job_id: str, pid: str, name: str) -> None:
    job = h.app.queue.get(job_id) if jobs.JOB_ID_RE.match(job_id) else None
    if not job or job["kind"] != "group" or not PID_RE.match(pid) or name not in ("analysis.json", "replay.json"):
        return h._error(404, "Not found.")
    path = group.person_dir(h.app.queue.job_dir(job_id), pid) / name
    if not path.is_file():
        return h._error(404, "This result is not available.")
    if name == "replay.json":
        raw, problems = replay.read_valid(path, h.app.lock, h.app.state)
        if raw is None:
            return h._error(422, "The replay file does not match its contract.", problems=problems)
    else:
        raw = path.read_bytes()
    h._send(200, raw, "application/json; charset=utf-8")


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `route` (below `api/`) when it belongs to people or group mode; False when it does not."""
    parts = route.split("/")
    if method == "POST" and route in ("people", "group"):
        (_post_people if route == "people" else _post_group)(h)
    elif method in ("GET", "HEAD") and len(parts) == 4 and parts[0] == "jobs" and parts[2] == "people":
        _get_picture(h, parts[1], parts[3])
    elif method in ("GET", "HEAD") and len(parts) == 4 and parts[0] == "results":
        _get_person_result(h, parts[1], parts[2], parts[3])
    else:
        return False
    return True
