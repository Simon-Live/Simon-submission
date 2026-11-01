"""Which Meta models ran for one follow job, read from the job's own files (docs/specs/models-and-skeleton-data.md R1, TICKET-142).

`collect(jobs_root, job)` returns `{job, job_seconds, models: [row, ...]}`. A row is
`{id, model, maker, clip, status, seconds, facts}` with `status` one of `live`, `cached`, `fallback`, `not_run` or
`unknown`. Every value comes from a file the pipeline wrote: Part 1's log and `keyframes.json` of the trainer job,
Part 2's provenance blocks, Part 5's `phrasing` block and the job's `steps/part7.log`. Nothing here says a model ran
unless a file says so; no file means `unknown`.

`handle(h, method, route)` answers `results/<job>/models.json`, `skeleton2d.json` (skeleton2d.py) and `trainer-visibility.json` (trainer_visibility.py) for
done follow jobs, and returns False for every other route.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any

from part7 import job_lookup, jobs, skeleton2d, trainer_visibility

ROUTES = ("models.json", "skeleton2d.json", "trainer-visibility.json")
MSG_GONE = "This result is not available."
_PART_OK = re.compile(r"\bpart (\d) exit 0 in ([0-9.]+) s \(([^)]+)\)")
SAM3D = "sam-3d-body"
LIVE_TRACKERS = {"api-sam31": "meta_api", "local-sam31": "local_weights"}
TRACK_LOGS = ("part2_track.api.log", "part2_track_retry.log", "part2_track.log")
SPARK_BACKEND = "muse-spark"


def _json(path: Path) -> Any:
    return job_lookup.read_json(path)  # cached by mtime; the value is shared, read only


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def step_seconds(job_dir: Path) -> dict[str, float]:
    """`{step log name: seconds}` of every part call that exited 0, from the job's `steps/part7.log`."""
    out: dict[str, float] = {}
    for m in _PART_OK.finditer(_text(job_dir / "steps" / "part7.log")):
        out[m.group(3)] = float(m.group(2))
    return out


def _row(rid: str, model: str, clip: str, status: str, seconds: float | None = None, **facts: Any) -> dict[str, Any]:
    return {"id": rid, "model": model, "maker": "Meta", "clip": clip, "status": status, "seconds": seconds,
            "facts": {k: v for k, v in facts.items() if v is not None}}


def _job_seconds(record: dict[str, Any]) -> float | None:
    try:
        start = datetime.strptime(str(record["started_at"]), "%Y-%m-%dT%H:%M:%SZ")
        end = datetime.strptime(str(record["finished_at"]), "%Y-%m-%dT%H:%M:%SZ")
    except (KeyError, ValueError):
        return None
    return max(0.0, (end - start).total_seconds())


def trainer_job(jobs_root: Path, entry_id: str | None) -> Path | None:
    """The folder of the newest done trainer job that made catalog entry `entry_id`, or None."""
    if not entry_id:
        return None
    lookup = job_lookup.registered(jobs_root)
    if lookup is not None:  # the queue answers from memory
        job_id = lookup(entry_id)
        return jobs_root / job_id if job_id else None
    found: list[tuple[str, Path]] = []
    for path in jobs_root.glob("*/job.json"):
        rec = _json(path)
        if not isinstance(rec, dict) or rec.get("kind") != "trainer" or rec.get("status") != "done":
            continue
        made = rec.get("entry_id") or (rec.get("result") or {}).get("entry_id")
        if made == entry_id:
            found.append((str(rec.get("finished_at") or ""), path.parent))
    return max(found)[1] if found else None


# ----- the trainer's video (Part 1) ----------------------------------------------------------------------------
def trainer_rows(trainer_dir: Path | None) -> list[dict[str, Any]]:
    """SAM 3.1 tracking and Muse Spark sections of the trainer video, from the trainer job's Part 1 files."""
    if trainer_dir is None:
        return [_row("sam31-trainer", "SAM 3.1", "trainer", "unknown", reason="no_trainer_job"),
                _row("spark-sections", "Muse Spark", "trainer", "unknown", reason="no_trainer_job")]
    rec = _json(trainer_dir / "job.json") or {}
    parts = (rec.get("result") or {}).get("parts") or {}
    work = trainer_dir / "work" / "trainer"
    log = _text(work / "steps" / "part1.log")
    secs = step_seconds(trainer_dir).get("part1.log")
    if parts.get("keyframes") == 3 or not log:
        reason = "part1_not_run" if not log else "part3_keyframes"
        return [_row("sam31-trainer", "SAM 3.1", "trainer", "fallback", ran="part3_keyframes", reason=reason),
                _row("spark-sections", "Muse Spark", "trainer", "fallback", ran="part3_keyframes", reason=reason)]
    cached = "rebuilt from saved SAM and Spark results" in log
    sam = "cached" if cached else "live" if "SAM frames" in log else "unknown"
    frames = re.search(r"SAM frames (\d+)", log)
    rows = [_row("sam31-trainer", "SAM 3.1", "trainer", sam, secs, via="meta_api",
                 frames=int(frames.group(1)) if frames else None)]
    kf = _json(work / "keyframes.json")
    names = kf.get("spark_names") if isinstance(kf, dict) else None
    reps = sum(len(p.get("repetitions") or []) for p in kf.get("people") or [] if isinstance(p, dict)) \
        if isinstance(kf, dict) else None
    if names == "spark":
        rows.append(_row("spark-sections", "Muse Spark", "trainer", "cached" if cached else "live", secs,
                         via="meta_api", repetitions=reps))
    elif names == "fallback":
        rows.append(_row("spark-sections", "Muse Spark", "trainer", "fallback", secs, ran="standard_phase_names"))
    else:
        rows.append(_row("spark-sections", "Muse Spark", "trainer", "unknown", reason="no_keyframes"))
    return rows


# ----- your video (Part 2) -------------------------------------------------------------------------------------
def _tracker_row(prov: Any, secs: float | None, failed_api: bool) -> dict[str, Any]:
    tracker = prov.get("tracker") if isinstance(prov, dict) else None
    if tracker in LIVE_TRACKERS:
        return _row("sam31-you", "SAM 3.1", "you", "live", secs, via=LIVE_TRACKERS[tracker])
    return _row("sam31-you", "SAM 3.1", "you", "fallback", secs, ran=tracker or "unknown",
                reason=(prov or {}).get("fallback_reason") or ("api_attempt_failed" if failed_api else None))


def follower_rows(jobs_root: Path, job_dir: Path, record: dict[str, Any]) -> list[dict[str, Any]]:
    """SAM 3.1 tracking and SAM 3D Body pose of the follower video."""
    work = job_dir / "work" / "follower"
    pose = _json(work / "part2" / "pose3d.json")
    prov = pose.get("provenance") if isinstance(pose, dict) else None
    people_job = record.get("people_job")
    if people_job and jobs.JOB_ID_RE.match(str(people_job)):
        pdir = jobs_root / str(people_job)
        tracks = _json(pdir / "work" / "tracks.json")
        secs = step_seconds(pdir)
        ran = next((secs[n] for n in TRACK_LOGS[1:] if n in secs), secs.get(TRACK_LOGS[0]))
        failed_api = (pdir / "work" / "steps" / TRACK_LOGS[0]).is_file() and TRACK_LOGS[0] not in secs
        if isinstance(tracks, dict):
            track = _tracker_row(tracks.get("provenance"), ran, failed_api)
        else:
            track = _row("sam31-you", "SAM 3.1", "you", "unknown", reason="no_tracks")
    elif isinstance(prov, dict) and prov.get("tracker"):
        track = _tracker_row(prov, None, False)
    elif isinstance(prov, dict):
        track = _row("sam31-you", "SAM 3.1", "you", "not_run", reason="one_person")
    else:
        track = _row("sam31-you", "SAM 3.1", "you", "unknown", reason="no_pose_file")
    secs = step_seconds(job_dir).get("part2.log")
    if not isinstance(prov, dict):
        body = _row("sam3d-you", "SAM 3D Body", "you", "unknown", reason="no_pose_file")
    else:
        names = [str(m.get("name") or "") for m in prov.get("models") or [] if isinstance(m, dict)]
        if any(n.startswith(SAM3D) for n in names):
            body = _row("sam3d-you", "SAM 3D Body", "you", "live", secs, via="local_gpu",
                        frames=len(pose.get("frames") or []))
        else:
            body = _row("sam3d-you", "SAM 3D Body", "you", "fallback", secs,
                        ran=prov.get("lifter") or prov.get("backend") or "unknown")
    return [track, body]


# ----- the feedback words (Part 5) -----------------------------------------------------------------------------
def phrasing_row(job_dir: Path) -> dict[str, Any]:
    """Muse Spark phrasing from Part 5's `phrasing` block in `analysis.json`."""
    doc = _json(job_dir / "work" / "follower" / "analysis.json")
    ph = doc.get("phrasing") if isinstance(doc, dict) else None
    secs = next((v for k, v in step_seconds(job_dir).items() if k.startswith("part5_analyse")), None)
    if not isinstance(ph, dict):
        return _row("spark-phrasing", "Muse Spark", "you", "unknown", reason="no_phrasing_record")
    per = [f for f in ph.get("faults") or [] if isinstance(f, dict)]
    live = sum(1 for f in per if f.get("backend") == SPARK_BACKEND)
    if ph.get("requested") == "template":
        return _row("spark-phrasing", "Muse Spark", "you", "not_run", reason="template_chosen")
    if not per and ph.get("backend") != SPARK_BACKEND:
        return _row("spark-phrasing", "Muse Spark", "you", "not_run", reason="no_faults")
    if live:
        return _row("spark-phrasing", "Muse Spark", "you", "live", secs, model_id=ph.get("model"), lines=len(per),
                    lines_live=live, reason=ph.get("fallback_reason") if live < len(per) else None)
    return _row("spark-phrasing", "Muse Spark", "you", "fallback", secs, ran="template", lines=len(per),
                reason=ph.get("fallback_reason"))


def collect(jobs_root: Path, job_id: str) -> dict[str, Any] | None:
    """The models of done follow job `job_id`, or None when it is not one."""
    job_dir = jobs_root / job_id
    record = _json(job_dir / "job.json")
    if not isinstance(record, dict) or record.get("kind") != "follow" or record.get("status") != "done":
        return None
    rows = [*trainer_rows(trainer_job(jobs_root, record.get("entry_id"))),
            *follower_rows(jobs_root, job_dir, record), phrasing_row(job_dir)]
    order = ("sam31-trainer", "spark-sections", "sam31-you", "sam3d-you", "spark-phrasing")
    rows.sort(key=lambda r: order.index(r["id"]))
    return {"job": job_id, "job_seconds": _job_seconds(record), "models": rows}


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `results/<job>/models.json`, `skeleton2d.json` and `trainer-visibility.json`; False for any other route."""
    parts = route.split("/")
    if method not in ("GET", "HEAD") or len(parts) != 3 or parts[0] != "results" or parts[2] not in ROUTES:
        return False
    job_id = parts[1]
    if not jobs.JOB_ID_RE.match(job_id):
        h._error(404, MSG_GONE)
        return True
    root = h.app.queue.job_dir(job_id).parent
    if parts[2] == "models.json":
        doc = collect(root, job_id)
    else:
        record = _json(root / job_id / "job.json")
        ok = isinstance(record, dict) and record.get("kind") == "follow" and record.get("status") == "done"
        if parts[2] == "trainer-visibility.json":  # the trainer's unseen joints (compare-view.md, TICKET-116)
            doc = trainer_visibility.build(root / job_id / "work" / "expected_skeleton.json") if ok else None
        else:
            doc = skeleton2d.build(root / job_id / "work" / "follower" / "part2", record.get("person_id")) if ok else None
    if doc is None:
        h._error(404, MSG_GONE)
    else:
        h._json(200, doc)
    return True
