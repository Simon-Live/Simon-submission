"""History copies of a signed-in student's takes (docs/specs/history.md "Store").

A job folder is kept 7 days. With the owner's retention consent, a finished follow take is also copied to
`<state>/history/<user>/<entry>/takes/<job>/` as `analysis.json`, `clip.mp4` (480 px short side, 8 fps, no audio)
and `meta.json`, and kept `SIMON7_HISTORY_DAYS` (90). Ownership and the retention consent live in the identity
store (`part7.identity`, read only); this module never reads a user id from `job.json`. When the identity
module is missing, nothing is owned and nothing is copied, so the feature stays off.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Iterator

from part7 import applog, labels, model_only, modes

USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,40}$")  # C-ID
JOB_ID_RE = re.compile(r"^[0-9a-f]{12}$")
VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")
DEFAULT_DAYS = 90
CLIP_SHORT_SIDE = 480
CLIP_FPS = 8
CLIP_MAX_SECONDS = 60
FFMPEG_TIMEOUT_S = 180
CLIP_NAME, ANALYSIS_NAME, META_NAME = "clip.mp4", "analysis.json", "meta.json"


def optional_module(name: str) -> Any | None:
    """A sibling lane's module (`part7.auth`, `part7.identity`, ...), or None when it is not there."""
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


# ----- layout ---------------------------------------------------------------------------------------
def root(state: Path | str) -> Path:
    return Path(state) / "history"


def days() -> int:
    try:
        value = int(os.environ.get("SIMON7_HISTORY_DAYS", DEFAULT_DAYS))
    except ValueError:
        return DEFAULT_DAYS
    return value if value > 0 else DEFAULT_DAYS


def valid_ids(user_id: Any, entry_id: Any = "x", job_id: Any = "0" * 12) -> bool:
    """True when every id is safe to build a path from."""
    return (
        isinstance(user_id, str) and bool(USER_ID_RE.match(user_id))
        and isinstance(entry_id, str) and bool(labels.ENTRY_ID_RE.match(entry_id))
        and isinstance(job_id, str) and bool(JOB_ID_RE.match(job_id))
    )


def user_dir(state: Path | str, user_id: str) -> Path:
    return root(state) / user_id


def entry_dir(state: Path | str, user_id: str, entry_id: str) -> Path:
    return user_dir(state, user_id) / entry_id


def take_dir(state: Path | str, user_id: str, entry_id: str, job_id: str) -> Path:
    return entry_dir(state, user_id, entry_id) / "takes" / job_id


CROSS_DIR = "_cross"  # across-my-movements reports and monthly recaps; "_" cannot start an entry id, so it never reads as an entry
CROSS_PREFS = "cross_prefs.json"  # the movements the user left out of those reports


def cross_dir(state: Path | str, user_id: str) -> Path:
    return user_dir(state, user_id) / CROSS_DIR


def reports_dir(state: Path | str, user_id: str, entry_id: str) -> Path:
    return entry_dir(state, user_id, entry_id) / "reports"


@contextmanager
def locked(state: Path | str) -> Iterator[None]:
    """One writer at a time across threads and processes: `flock` on `<state>/history/.lock`."""
    folder = root(state)
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / ".lock", "a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def write_json(path: Path, doc: Any) -> None:
    """Write `doc` to `path` atomically (temp file in the same folder, then replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(json.dumps(doc))
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def sha256_file(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ----- identity (read only, optional) -----------------------------------------------------------------
def owner_of(state: Path | str, job_id: str) -> str | None:
    identity = optional_module("part7.identity")
    if identity is None:
        return None
    owner = identity.owner_of_job(Path(state), job_id)
    return owner if isinstance(owner, str) and USER_ID_RE.match(owner) else None


def retention_opt_in(state: Path | str, user_id: str) -> bool:
    identity = optional_module("part7.identity")
    return bool(identity is not None and identity.retention_opt_in(Path(state), user_id))


# ----- recording ------------------------------------------------------------------------------------
def _seconds(job: dict[str, Any]) -> float | None:
    value = job.get("duration_ms")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return round(value / 1000.0, 3)
    trim = job.get("trim")
    if isinstance(trim, dict) and all(isinstance(trim.get(k), (int, float)) for k in ("start_ms", "end_ms")):
        span = trim["end_ms"] - trim["start_ms"]
        return round(span / 1000.0, 3) if span > 0 else None
    return None


def positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def timeline_end(analysis: Any) -> float | None:
    """The end of the compared span, `score.timeline[-1].t_s[1]`: a lower bound of the take's length."""
    score = analysis.get("score") if isinstance(analysis, dict) else None
    windows = score.get("timeline") if isinstance(score, dict) else None
    last = windows[-1] if isinstance(windows, list) and windows else None
    span = last.get("t_s") if isinstance(last, dict) else None
    end = span[1] if isinstance(span, list) and len(span) == 2 else None
    return round(float(end), 3) if positive(end) else None


def _replay_end(job_dir: Path) -> float | None:
    times = (read_json(job_dir / "work" / "follower" / "replay.json") or {}).get("follower_t")
    return round(float(times[-1]), 3) if isinstance(times, list) and times and positive(times[-1]) else None


def duration_of(job: dict[str, Any], job_dir: Path, analysis: Any) -> tuple[float | None, str | None]:
    """`(seconds, source)` for a take. Part 5's analysis has no follower duration, so: ffprobe of the job's video (exact),
    the job record's own duration or trim, `replay.json` `follower_t[-1]`, then the end of the compared span (a lower bound)."""
    try:
        from part7 import media
        probed = media.probe(job_dir / "work" / "video.mp4")["duration_ms"]
        if positive(probed):
            return round(probed / 1000.0, 3), "ffprobe"
    except (ValueError, KeyError, OSError):
        pass
    recorded = _seconds(job)
    if recorded is not None:
        return recorded, "job"
    for found, source in ((_replay_end(job_dir), "replay"), (timeline_end(analysis), "timeline")):
        if found is not None:
            return found, source
    return None, None


def is_private(job: dict[str, Any]) -> bool:
    return job.get("private") is True  # set by private mode (private-mode.md); teacher_stats tests it the same way


def _make_clip(video: Path, out: Path) -> bool:
    """Write the small history clip; False when ffmpeg cannot (the copy then has no clip)."""
    short = CLIP_SHORT_SIDE
    scale = f"scale=w='if(gt(iw,ih),-2,min({short},iw))':h='if(gt(iw,ih),min({short},ih),-2)'"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-t", str(CLIP_MAX_SECONDS), "-an",
           "-vf", f"fps={CLIP_FPS},{scale}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=FFMPEG_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0 and out.is_file() and out.stat().st_size > 0


def light_of(job: dict[str, Any]) -> dict[str, Any] | None:
    """The job result's `light` level (part7/light.py), the one field of it the shown score needs (one-letter.md)."""
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    light = result.get("light")
    return {"level": light["level"]} if isinstance(light, dict) and isinstance(light.get("level"), str) else None


def _score(analysis: Any) -> tuple[Any, Any] | None:
    score = analysis.get("score") if isinstance(analysis, dict) else None
    if not isinstance(score, dict) or isinstance(score.get("value"), bool) or not isinstance(score.get("value"), (int, float)):
        return None
    return score["value"], score.get("grade")


def reference_key(job: dict[str, Any]) -> str:
    """"teacher", or "own:<reference job id>": takes compared with different references are not one series (ADR-0019)."""
    from part7 import my_reference
    ref = job.get("reference")
    if my_reference.uses_own(job) and isinstance(ref.get("job_id"), str):
        return f"own:{ref['job_id']}"
    return "teacher"


def section_key(section: Any) -> str | None:
    """Which part of the movement a take covers: "full" for the whole movement, else `s<index>of<count>` (a joined
    ladder step `s<first>-<index>of<count>`, a slowed step `...@<speed>`). None when the record is not readable."""
    if section is None:
        return "full"
    if not isinstance(section, dict):
        return None
    index, count, first, speed = (section.get(k) for k in ("index", "count", "first", "speed"))
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 1 for v in (index, count)):
        return None
    key = f"s{first}-{index}of{count}" if isinstance(first, int) and not isinstance(first, bool) and 1 <= first < index else f"s{index}of{count}"
    if isinstance(speed, (int, float)) and not isinstance(speed, bool) and 0 < speed < 1:
        key += f"@{speed:g}"
    return key


def mode_of(job: dict[str, Any], analysis: Any) -> str:
    """The mode the student chose, else the profile Part 5 scored with, else fitness (Part 5's standard rules, ADR-0008)."""
    chosen = job.get("mode")
    if chosen in modes.MODES:
        return str(chosen)
    profile = analysis.get("profile") if isinstance(analysis, dict) else None
    return str(profile) if profile in modes.MODES else "fitness"


def score_version(analysis: Any) -> str | None:
    """`<score format>:<first 8 of the parameter hash>`: two scores are the same scale only when this agrees."""
    score = analysis.get("score") if isinstance(analysis, dict) else None
    version = score.get("version") if isinstance(score, dict) else None
    if not isinstance(version, str) or not version:
        return None
    digest = score.get("params_sha256")
    return f"{version}:{digest[:8]}" if isinstance(digest, str) and digest else version


def _copy(state: Path, user_id: str, job: dict[str, Any], job_dir: Path) -> bool:
    """Copy one finished, owned follow take; True when the copy is there afterwards."""
    job_id, entry_id = job.get("id"), job.get("entry_id")
    if not valid_ids(user_id, entry_id, job_id) or job.get("kind") != "follow" or job.get("status") != "done":
        return False
    final = take_dir(state, user_id, entry_id, job_id)
    if (final / META_NAME).is_file():
        return True
    source = job_dir / "work" / "follower" / ANALYSIS_NAME
    analysis = read_json(source)
    scored = _score(analysis)
    if scored is None:
        return False
    stage = root(state) / ".tmp" / f"{job_id}-{os.getpid()}-{time.time_ns()}"
    stage.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(source, stage / ANALYSIS_NAME)
        duration = duration_of(job, job_dir, analysis)
        video_kept = job.get("video_kept") is not False  # a model-only take keeps no clip (model-only-take.md)
        has_clip = video_kept and not model_only.view_only(job) and _make_clip(job_dir / "work" / "video.mp4", stage / CLIP_NAME)
        meta = {
            "job_id": job_id, "entry_id": entry_id, "at": job.get("finished_at") or job.get("created_at"),
            "duration_s": duration[0], "duration_source": duration[1], "score": scored[0], "grade": scored[1], "private": is_private(job),
            "section_key": section_key(job.get("section")), "mode": mode_of(job, analysis), "score_version": score_version(analysis),
            "reference": reference_key(job),
            "clip": has_clip, "video_kept": video_kept, "kept_ts": time.time(),
            "light": light_of(job),  # one-letter.md: the light cap is applied to the shown score at read time
        }
        from part7 import progress_sheet  # TICKET-283: a tracked take keeps its reps, peak angle, tempo and skeleton
        progress_sheet.extend_copy(state, job, job_dir, analysis, meta, stage)
        write_json(stage / META_NAME, meta)
        with locked(state):
            if not (final / META_NAME).is_file():
                final.parent.mkdir(parents=True, exist_ok=True)
                os.replace(stage, final)
        return True
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def record_take(state: Path | str, job: dict[str, Any], job_dir: Path) -> bool:
    """Copy a finished follow take of a signed-in student who opted in; False for anything else."""
    state = Path(state)
    job_id = job.get("id")
    if not isinstance(job_id, str) or not JOB_ID_RE.match(job_id):
        return False
    user_id = owner_of(state, job_id)
    if user_id is None or not retention_opt_in(state, user_id):
        return False
    try:
        return _copy(state, user_id, job, Path(job_dir))
    except OSError as exc:
        applog.log(f"history: copy of {job_id} failed: {applog.cause(exc)}")
        return False


def pending_take(state: Path | str, user_id: str, job_id: str) -> dict[str, Any] | None:
    """The take of a finished job the user owns, read from the job folder, before its history copy exists.

    Shaped like a row of `takes()` (no `take` number, no clip); None unless the user owns the job, kept the retention
    consent and the job is a finished, scored follow take."""
    state = Path(state)
    if not valid_ids(user_id) or not isinstance(job_id, str) or not JOB_ID_RE.match(job_id):
        return None
    if owner_of(state, job_id) != user_id or not retention_opt_in(state, user_id):
        return None
    job_dir = state / "jobs" / job_id
    job = read_json(job_dir / "job.json")
    source = job_dir / "work" / "follower" / ANALYSIS_NAME
    analysis = read_json(source)
    if not isinstance(job, dict) or job.get("id") != job_id or job.get("kind") != "follow" or job.get("status") != "done":
        return None
    scored, entry_id = _score(analysis), job.get("entry_id")
    if scored is None or not valid_ids(user_id, entry_id, job_id):
        return None
    return {"job_id": job_id, "entry_id": entry_id, "at": job.get("finished_at") or job.get("created_at"), "duration_s": None,
            "duration_source": None, "score": scored[0], "grade": scored[1], "private": is_private(job),
            "section_key": section_key(job.get("section")), "mode": mode_of(job, analysis), "score_version": score_version(analysis),
            "reference": reference_key(job),
            "video_kept": job.get("video_kept") is not False, "light": light_of(job), "analysis": source, "clip": None}


def claim(state: Path | str, user_id: str, job_id: str) -> bool:
    """Copy a finished job the user holds (the identity store already recorded the claim); a repeat is a no-op."""
    state = Path(state)
    if not valid_ids(user_id) or not isinstance(job_id, str) or not JOB_ID_RE.match(job_id):
        return False
    if owner_of(state, job_id) != user_id or not retention_opt_in(state, user_id):
        return False
    job_dir = state / "jobs" / job_id
    job = read_json(job_dir / "job.json")
    if not isinstance(job, dict) or job.get("id") != job_id:
        return False
    try:
        return _copy(state, user_id, job, job_dir)
    except OSError as exc:
        applog.log(f"history: claim copy of {job_id} failed: {applog.cause(exc)}")
        return False


# ----- reading --------------------------------------------------------------------------------------
def entries(state: Path | str, user_id: str) -> list[str]:
    """The entries the user has at least one copy of."""
    if not valid_ids(user_id):
        return []
    base = user_dir(state, user_id)
    if not base.is_dir():
        return []
    return sorted(e.name for e in base.iterdir() if e.is_dir() and labels.ENTRY_ID_RE.match(e.name) and (e / "takes").is_dir()
                  and any((e / "takes").iterdir()))


def _text(value: Any) -> str | None:
    """A recorded label, or None (unknown) for a record made before the field existed."""
    return value if isinstance(value, str) and value else None


def takes(state: Path | str, user_id: str, entry_id: str) -> list[dict[str, Any]]:
    """The user's takes of one entry, oldest first, numbered from 1 by their recorded time."""
    if not valid_ids(user_id, entry_id):
        return []
    folder = entry_dir(state, user_id, entry_id) / "takes"
    found = []
    for child in folder.iterdir() if folder.is_dir() else []:
        meta = read_json(child / META_NAME)
        if not (isinstance(meta, dict) and meta.get("job_id") == child.name and (child / ANALYSIS_NAME).is_file()):
            continue
        clip = child / CLIP_NAME
        video_kept = meta.get("video_kept") is not False  # one eligibility hook: a model-only take has no clip, whatever is on disk
        found.append({
            "job_id": child.name, "entry_id": entry_id, "at": meta.get("at"), "duration_s": meta.get("duration_s"), "duration_source": meta.get("duration_source"),
            "score": meta.get("score"), "grade": meta.get("grade"), "private": bool(meta.get("private")),
            "synthetic": meta.get("synthetic") is True,  # a seeded demo history is labelled so (TICKET-211)
            "section_key": _text(meta.get("section_key")), "mode": meta.get("mode") if meta.get("mode") in modes.MODES else None,
            "score_version": _text(meta.get("score_version")),
            "reference": _text(meta.get("reference")) or "teacher",  # which reference the take was compared with (ADR-0019)
            "video_kept": video_kept,
            "light": meta.get("light") if isinstance(meta.get("light"), dict) else None,  # None on a copy made before one-letter.md
            "analysis": child / ANALYSIS_NAME,
            "clip": clip if video_kept and clip.is_file() and not clip.is_symlink() else None,
        })
    found.sort(key=lambda t: (str(t["at"] or ""), t["job_id"]))
    for number, item in enumerate(found, 1):
        item["take"] = number
    return found


# ----- consent (the video consent only; retention consent is the identity store's) -----------------------
def consent(state: Path | str, user_id: str) -> dict[str, Any]:
    doc = read_json(user_dir(state, user_id) / "consent.json") if valid_ids(user_id) else None
    if isinstance(doc, dict) and doc.get("video") is True:
        return {"video": True, "version": doc.get("version"), "at": doc.get("at")}
    return {"video": False, "version": None, "at": None}


def set_consent(state: Path | str, user_id: str, video: bool, version: str) -> dict[str, Any]:
    """Record whether Muse Spark may watch the user's takes; ValueError for a bad id, flag or version."""
    if not valid_ids(user_id) or not isinstance(video, bool) or not isinstance(version, str) or not VERSION_RE.match(version):
        raise ValueError("history consent needs a user, a true or false and a version")
    doc = {"video": video, "version": version, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    with locked(state):
        write_json(user_dir(state, user_id) / "consent.json", doc)
        if not video:  # reports made with the user's video go; the copies stay
            _drop_reports_where(user_dir(state, user_id), lambda report: report.get("video") is True)
    return consent(state, user_id)


def withdraw_retention(state: Path | str, user_id: str) -> int:
    """The user withdrew the retention consent: every copy and report goes now; the number of takes removed.

    Job folders keep the normal 7-day rule. `api/me/consent` (lane lc-auth) calls this when `retention` is false.
    """
    return forget(state, user_id)


# ----- removing -------------------------------------------------------------------------------------
def _drop_reports_citing(reports: Path, job_ids: set[str]) -> int:
    """Remove the reports (and the reel files beside a reel's json) that cite one of the jobs."""
    removed = 0
    for path in [*reports.glob("*.json"), *reports.glob("patterns/*.json")] if reports.is_dir() else []:  # patterns: TICKET-221
        doc = read_json(path)
        cited = {t.get("job_id") for t in doc.get("takes", []) if isinstance(t, dict)} if isinstance(doc, dict) else set()
        if not isinstance(doc, dict) or cited & job_ids:  # an unreadable report cannot be shown to cite nothing
            path.unlink(missing_ok=True)
            path.with_suffix(".mp4").unlink(missing_ok=True)
            removed += 1
    return removed


def _drop_reports_where(base: Path, test: Any) -> int:
    removed = 0
    for path in [*base.glob("*/reports/*.json"), *base.glob("*/reports/patterns/*.json"), *base.glob("*/reels/*.json")] if base.is_dir() else []:
        doc = read_json(path)
        if isinstance(doc, dict) and test(doc):
            path.unlink(missing_ok=True)
            path.with_suffix(".mp4").unlink(missing_ok=True)  # a reel's film sits beside its json
            removed += 1
    return removed


def _remove_takes(entry: Path, job_ids: set[str]) -> int:
    from part7 import notes  # TICKET-237: a trainer's note about a take goes with the take's copy (<state>/history/<user>/<entry>)
    notes.drop_jobs(entry.parents[2], job_ids)
    count = 0
    for job_id in job_ids:
        target = entry / "takes" / job_id
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            count += 1
    _drop_reports_citing(entry / "reports", job_ids)
    _drop_reports_citing(entry / "reels", job_ids)  # the progress reel cuts from the clips, so it goes with them (TICKET-228)
    _drop_reports_citing(entry.parent / CROSS_DIR, job_ids)  # a report that read a deleted take goes with it (TICKET-224)
    for leftover in (entry / "takes", entry / "reports" / "patterns", entry / "reports", entry / "reels", entry):
        try:
            leftover.rmdir()
        except OSError:
            break
    return count


def _all_takes(state: Path | str) -> Iterator[tuple[Path, str]]:
    """Every `(entry folder, job id)` copy of every user."""
    for user in sorted(root(state).glob("*")) if root(state).is_dir() else []:
        if not (user.is_dir() and USER_ID_RE.match(user.name)):
            continue
        for entry in user.iterdir():
            if entry.is_dir() and labels.ENTRY_ID_RE.match(entry.name) and (entry / "takes").is_dir():
                for take in (entry / "takes").iterdir():
                    if take.is_dir() and JOB_ID_RE.match(take.name):
                        yield entry, take.name


def drop_take(state: Path | str, job_id: str) -> int:
    """Remove the copy of one job and every cached report that cites it; the number of copies removed."""
    if not isinstance(job_id, str) or not JOB_ID_RE.match(job_id):
        return 0
    from part7 import notes  # TICKET-237: the request goes with the take even when no copy was kept
    notes.drop_jobs(state, {job_id})
    with locked(state):
        found = [entry for entry, job in _all_takes(state) if job == job_id]
        return sum(_remove_takes(entry, {job_id}) for entry in found)


def forget(state: Path | str, user_id: str, entry_id: str | None = None) -> int:
    """Remove all of the user's history (or one entry's); the number of takes removed."""
    if not valid_ids(user_id, entry_id if entry_id is not None else "x"):
        return 0
    from part7 import notes  # TICKET-237: withdrawing retention or forgetting a movement removes its requests and notes
    from part7 import my_reference  # ADR-0019: an own reference goes with the account, "Delete my data" and a forgotten movement
    from part7 import reference_approval  # ADR-0019: waiting approvals and "no" answers go the same way; a teacher's approvals are taken off
    reference_approval.forget(state, user_id, entry_id)  # first: it leaves the mark that refuses an approval already under way
    my_reference.forget(state, user_id, entry_id)
    if entry_id is None:
        notes.drop_follower(state, user_id)
    else:
        notes.drop_follower_entry(state, user_id, entry_id)
    with locked(state):
        if entry_id is not None:
            return _forget_entry(entry_dir(state, user_id, entry_id))
        base = user_dir(state, user_id)
        count = sum(_forget_entry(e) for e in base.iterdir() if e.is_dir() and labels.ENTRY_ID_RE.match(e.name)) if base.is_dir() else 0
        shutil.rmtree(base / CROSS_DIR, ignore_errors=True)  # cross reports and recaps (TICKET-223/224)
        for name in ("consent.json", "runs.jsonl", "ask_runs.jsonl", "ask_take_runs.jsonl", CROSS_PREFS):
            (base / name).unlink(missing_ok=True)
        try:
            base.rmdir()
        except OSError:
            pass
        return count


def _forget_entry(entry: Path) -> int:
    folder = entry / "takes"
    ids = {t.name for t in folder.iterdir() if t.is_dir() and JOB_ID_RE.match(t.name)} if folder.is_dir() else set()
    count = _remove_takes(entry, ids)
    shutil.rmtree(entry / "reports", ignore_errors=True)  # a report of a forgotten entry goes with it
    shutil.rmtree(entry / "reels", ignore_errors=True)    # and so does its progress reel
    try:
        entry.rmdir()
    except OSError:
        pass
    return count


def sweep(state: Path | str, now: float | None = None) -> int:
    """Remove copies kept longer than `days()`; the number removed. Leftover staging folders go too."""
    if not root(state).is_dir():  # nobody kept anything: do not create the folder just to sweep it
        return 0
    cutoff = (now if now is not None else time.time()) - days() * 86400
    removed = 0
    with locked(state):
        for entry, job_id in list(_all_takes(state)):
            meta = read_json(entry / "takes" / job_id / META_NAME)
            kept = meta.get("kept_ts") if isinstance(meta, dict) else None
            if not isinstance(kept, (int, float)) or kept < cutoff:
                removed += _remove_takes(entry, {job_id})
        stale = root(state) / ".tmp"
        for leftover in stale.iterdir() if stale.is_dir() else []:
            if leftover.stat().st_mtime < cutoff:
                shutil.rmtree(leftover, ignore_errors=True)
    return removed
