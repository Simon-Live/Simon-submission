"""Which Meta models ran for one follow job, read from the job's own files (docs/specs/models-and-skeleton-data.md R1, TICKET-142).

`collect(jobs_root, job)` returns `{job, job_seconds, models: [row, ...]}`. A row is
`{id, model, maker, clip, status, seconds, facts}` with `status` one of `live`, `cached`, `fallback`, `not_run` or
`unknown`. Every value comes from a file the pipeline wrote: Part 1's log and `keyframes.json` of the trainer job,
Part 2's provenance blocks, Part 5's `phrasing` and `second_opinion` blocks, the entry's `narration.json`, the job's
`steps/part7.log` and, for the signed-in owner only, their stored history reports and generated avatars (TICKET-262).
TICKET-300 adds the MHR rig (pose provenance), Muse Glimmer (private `local-llm` phrasing), MMS-TTS (the job's cached
`speech/` wavs) and, for the owner only, SAM 3D Objects (their image3d models) and Muse Image (`work/muse-fix/` records).
Nothing here says a model ran unless a file says so; no file means `unknown`, or `not_run` for the rows added by TICKET-262
and TICKET-300.

`handle(h, method, route)` answers `results/<job>/models.json`, `skeleton2d.json` (skeleton2d.py) and `trainer-visibility.json` (trainer_visibility.py) for
done follow jobs, and returns False for every other route.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any

from part7 import (history_report, history_store, job_lookup, jobs, labels, model_store, muse_fix, narration, narration_api,
                   skeleton2d, trainer_visibility)

ROUTES = ("models.json", "skeleton2d.json", "trainer-visibility.json")
MSG_GONE = "This result is not available."
_PART_OK = re.compile(r"\bpart (\d) exit 0 in ([0-9.]+) s \(([^)]+)\)")
SAM3D = "sam-3d-body"
LIVE_TRACKERS = {"api-sam31": "meta_api", "local-sam31": "local_weights"}
TRACK_LOGS = ("part2_track.api.log", "part2_track_retry.log", "part2_track.log")
SPARK_BACKEND = "muse-spark"
# The pipeline story (TICKET-300): a picture becomes a 3D model, SAM 3D Body and the MHR rig give it a body, then the
# tracking, scoring and coaching models of the take. The view groups rows by clip in the order they first appear here.
ORDER = ("image3d", "avatar", "sam31-trainer", "spark-sections", "narration", "sam31-you", "sam3d-you", "mhr-you",
         "spark-phrasing", "glimmer-phrasing", "spark-opinion", "muse-image", "mms-tts", "spark-history")
MHR = "mhr"  # Part 2's provenance name of the Momentum Human Rig file the SAM 3D Body mesh is posed on
GLIMMER_BACKEND, GLIMMER_MODEL = "local-llm", "muse-glimmer"  # Part 5's private-mode backend and the model it loads
IMAGE3D_KIND, IMAGE3D_LIVE = "image3d", "sam3do"  # Part 2 image3d's kind and its SAM 3D Objects backend
AVATAR_KINDS = ("image", "autorig", IMAGE3D_KIND)  # generated models whose rig SAM 3D Body fitted to the MHR body
SPEECH_WAV = re.compile(r"^[0-9]{1,3}-([a-z]{3})-[0-9a-f]{10}\.wav$")  # speech.cache_path names
SPEECH_FAILED = re.compile(r"\bspeech: [a-z]{3} line [0-9]+ (?:failed|not made|crashed)")  # speech.py log lines


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
    kf = _json(work / "keyframes.json")
    # Part 1 prints "SAM frames N" only for every 200 frames, so a clip of fewer than 200 analysis frames has no such
    # line. Its own record of the call is then the cost line it printed before the call ("<n> frames, SAM about $x")
    # together with the keyframes.json it wrote from the tracks: a file with at least one tracked person.
    sized = re.search(r"(\d+) frames, SAM about \$", log)
    tracked = isinstance(kf, dict) and any(isinstance(p, dict) for p in kf.get("people") or [])
    sam = "cached" if cached else "live" if "SAM frames" in log or (sized and tracked) else "unknown"
    frames = re.search(r"SAM frames (\d+)", log) or sized
    rows = [_row("sam31-trainer", "SAM 3.1", "trainer", sam, secs, via="meta_api",
                 frames=int(frames.group(1)) if frames else None)]
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


def people_tracking_row(jobs_root: Path, people_job: Any) -> dict[str, Any]:
    """The SAM 3.1 row of the follower's people job (single follow or one person of a group): its tracks provenance."""
    if not people_job or not jobs.JOB_ID_RE.match(str(people_job)):
        return _row("sam31-you", "SAM 3.1", "you", "unknown", reason="no_tracks")
    pdir = jobs_root / str(people_job)
    tracks = _json(pdir / "work" / "tracks.json")
    if not isinstance(tracks, dict):
        return _row("sam31-you", "SAM 3.1", "you", "unknown", reason="no_tracks")
    secs = step_seconds(pdir)
    ran = next((secs[n] for n in TRACK_LOGS[1:] if n in secs), secs.get(TRACK_LOGS[0]))
    failed_api = (pdir / "work" / "steps" / TRACK_LOGS[0]).is_file() and TRACK_LOGS[0] not in secs
    return _tracker_row(tracks.get("provenance"), ran, failed_api)


def follower_rows(jobs_root: Path, job_dir: Path, record: dict[str, Any]) -> list[dict[str, Any]]:
    """SAM 3.1 tracking and SAM 3D Body pose of the follower video."""
    work = job_dir / "work" / "follower"
    pose = _json(work / "part2" / "pose3d.json")
    prov = pose.get("provenance") if isinstance(pose, dict) else None
    people_job = record.get("people_job")
    if people_job and jobs.JOB_ID_RE.match(str(people_job)):
        track = people_tracking_row(jobs_root, people_job)
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
def phrasing_row(job_dir: Path, analysis: Path | None = None) -> dict[str, Any]:
    """Muse Spark phrasing from Part 5's `phrasing` block in `analysis.json` (`analysis`: a group person's own file)."""
    doc = _json(analysis or job_dir / "work" / "follower" / "analysis.json")
    ph = doc.get("phrasing") if isinstance(doc, dict) else None
    secs = next((v for k, v in step_seconds(job_dir).items() if k.startswith("part5_analyse")), None)
    if not isinstance(ph, dict):
        return _row("spark-phrasing", "Muse Spark", "you", "unknown", reason="no_phrasing_record")
    per = [f for f in ph.get("faults") or [] if isinstance(f, dict)]
    live = sum(1 for f in per if f.get("backend") == SPARK_BACKEND)
    if ph.get("requested") == "template":
        return _row("spark-phrasing", "Muse Spark", "you", "not_run", reason="template_chosen")
    if ph.get("requested") == GLIMMER_BACKEND:  # private mode asked Part 5 for local wording: the glimmer row has it
        return _row("spark-phrasing", "Muse Spark", "you", "not_run", reason="private_mode")
    if not per and ph.get("backend") != SPARK_BACKEND:
        return _row("spark-phrasing", "Muse Spark", "you", "not_run", reason="no_faults")
    if live:
        return _row("spark-phrasing", "Muse Spark", "you", "live", secs, model_id=ph.get("model"), lines=len(per),
                    lines_live=live, reason=ph.get("fallback_reason") if live < len(per) else None)
    return _row("spark-phrasing", "Muse Spark", "you", "fallback", secs, ran="template", lines=len(per),
                reason=ph.get("fallback_reason"))


# ----- the second opinion, the trainer's voice, the history and the avatar (TICKET-262) ------------------------
def _short(text: Any) -> str | None:
    """A reason Part 5 wrote, kept only when it is a short plain line."""
    return text.strip() if isinstance(text, str) and 0 < len(text.strip()) <= 80 else None


def opinion_row(job_dir: Path, analysis: Path | None = None) -> dict[str, Any]:
    """Muse Spark's video second opinion from the `second_opinion` block of `analysis.json`. No block, no run."""
    doc = _json(analysis or job_dir / "work" / "follower" / "analysis.json")
    block = doc.get("second_opinion") if isinstance(doc, dict) else None
    if not isinstance(block, dict) or block.get("status") not in ("ok", "fallback", "skipped"):
        return _row("spark-opinion", "Muse Spark", "you", "not_run", reason="no_second_opinion")
    if block["status"] == "ok":
        usage = block.get("usage") if isinstance(block.get("usage"), dict) else {}
        return _row("spark-opinion", "Muse Spark", "you", "live", via="meta_api", model_id=block.get("model"),
                    verdicts=len(block.get("verdicts") or []), observations=len(block.get("observations") or []),
                    cached_tokens=usage.get("cached_tokens") or None)
    if block["status"] == "fallback":
        return _row("spark-opinion", "Muse Spark", "you", "fallback", ran="measured_faults", reason=_short(block.get("reason")))
    return _row("spark-opinion", "Muse Spark", "you", "not_run", reason=_short(block.get("reason")) or "second_opinion_skipped")


def narration_row(catalog_dir: Path | None, entry_id: Any) -> dict[str, Any]:
    """Muse Voice Transcribe from the entry's `narration.json`, which only a transcription call writes."""
    model = "Muse Voice Transcribe"
    ok = catalog_dir is not None and isinstance(entry_id, str) and bool(labels.ENTRY_ID_RE.match(entry_id))
    doc = _json(catalog_dir / entry_id / narration.FILE_NAME) if ok else None
    cues = [c for c in (doc.get("cues") if isinstance(doc, dict) else None) or [] if isinstance(c, dict)]
    if not isinstance(doc, dict) or doc.get("source") != narration_api.MODEL or not cues:
        return _row("narration", model, "trainer", "not_run", reason="no_narration")
    clips = sum(1 for c in cues if isinstance(c.get("clip"), dict))
    return _row("narration", model, "trainer", "live", via="meta_api", cues=len(cues), clips=clips or None)


def history_row(state: Path, user_id: str, entry_id: Any, job_id: str) -> dict[str, Any]:
    """Muse Spark over the viewer's own takes, from their stored history report that compared this take."""
    base = ("spark-history", "Muse Spark", "account")
    if not isinstance(entry_id, str) or not history_store.valid_ids(user_id, entry_id):
        return _row(*base, "not_run", reason="no_history_report")
    found = []
    for path in history_store.reports_dir(state, user_id, entry_id).glob("*.json"):
        doc = _json(path)
        takes = doc.get("takes") if isinstance(doc, dict) else None
        if isinstance(doc, dict) and doc.get("format") == history_report.FORMAT and isinstance(takes, list) \
                and any(isinstance(t, dict) and t.get("job_id") == job_id for t in takes):
            found.append((str(doc.get("created_at") or ""), doc))
    if not found:
        return _row(*base, "not_run", reason="no_history_report")
    doc = max(found, key=lambda f: f[0])[1]
    usage = doc.get("usage") if isinstance(doc.get("usage"), dict) else {}
    sent = doc.get("sent") if isinstance(doc.get("sent"), dict) else {}
    if doc.get("status") != "ok":
        return _row(*base, "fallback", ran="fact_table", reason=_short(doc.get("reason")))
    return _row(*base, "live", via="meta_api", takes=len(doc.get("takes") or []),
                videos=len(sent.get("clip_takes") or []) or None,
                input_tokens=usage.get("input_tokens") or None, cached_tokens=usage.get("cached_tokens") or None)


def avatar_row(state: Path, user_id: str) -> dict[str, Any]:
    """SAM 3D Body and MHR from the viewer's generated avatars: the `generated` block Part 2 wrote in `avatar.json`."""
    kinds = [made["kind"] for made in _ready_generated(state, user_id) if made.get("kind") in AVATAR_KINDS]
    if not kinds:
        return _row("avatar", "SAM 3D Body", "account", "not_run", reason="no_avatar")
    return _row("avatar", "SAM 3D Body", "account", "live", via="local_gpu", avatars=len(kinds),
                from_photos=kinds.count("image") or None, from_mesh=kinds.count("autorig") or None,
                from_picture=kinds.count(IMAGE3D_KIND) or None)


# ----- the picture model, the rig, private wording, the corrected picture and the voice (TICKET-300) -----------
def _ready_generated(state: Path, user_id: str) -> list[dict[str, Any]]:
    """The `generated` block (Part 2's avatar.json) of each ready generated model the viewer owns."""
    out = []
    for rec in model_store.owned(state, user_id):
        folder = model_store.model_dir(state, rec.get("id"))
        card = model_store.read_json(folder / "character.json") if folder is not None and rec.get("status") == "ready" else None
        made = card.get("generated") if isinstance(card, dict) and card.get("kind") == "generated" else None
        if isinstance(made, dict) and made.get("schema") == "simon.avatar.v1":
            out.append(made)
    return out


def image3d_row(state: Path, user_id: str) -> dict[str, Any]:
    """SAM 3D Objects from the viewer's picture models: Part 2 image3d names its generator in `backend.backend`."""
    base = ("image3d", "SAM 3D Objects", "account")
    made = [g for g in _ready_generated(state, user_id) if g.get("kind") == IMAGE3D_KIND]
    if not made:
        return _row(*base, "not_run", reason="no_picture_model")
    names = [(g.get("backend") or {}).get("backend") if isinstance(g.get("backend"), dict) else None for g in made]
    live = names.count(IMAGE3D_LIVE)
    if live:
        return _row(*base, "live", via="local_gpu", pictures=live)
    return _row(*base, "fallback", ran=next((n for n in names if isinstance(n, str) and n), "unknown"),
                reason="sam3do_unavailable")


def mhr_row(job_dir: Path) -> dict[str, Any]:
    """The MHR rig of the follower's 3D body: Part 2 lists the `mhr` file beside SAM 3D Body in the pose provenance."""
    base = ("mhr-you", "MHR", "you")
    pose = _json(job_dir / "work" / "follower" / "part2" / "pose3d.json")
    prov = pose.get("provenance") if isinstance(pose, dict) else None
    if not isinstance(prov, dict):
        return _row(*base, "unknown", reason="no_pose_file")
    names = [str(m.get("name") or "") for m in prov.get("models") or [] if isinstance(m, dict)]
    if not any(n.startswith(SAM3D) for n in names):
        return _row(*base, "not_run", reason="no_body_model")
    if MHR not in names:
        return _row(*base, "unknown", reason="no_rig_record")
    return _row(*base, "live", step_seconds(job_dir).get("part2.log"), via="local_gpu", frames=len(pose.get("frames") or []))


def glimmer_row(job_dir: Path, record: dict[str, Any], analysis: Path | None = None) -> dict[str, Any]:
    """Muse Glimmer private wording from Part 5's `phrasing` block: requested `local-llm`, lines by that backend."""
    base = ("glimmer-phrasing", "Muse Glimmer", "you")
    doc = _json(analysis or job_dir / "work" / "follower" / "analysis.json")
    ph = doc.get("phrasing") if isinstance(doc, dict) else None
    if not isinstance(ph, dict) or ph.get("requested") != GLIMMER_BACKEND:
        if record.get("private") is True:  # the take asked for it; Part 7 gave Part 5 the template plan instead
            return _row(*base, "fallback", ran="template", reason="private_mode_unavailable")
        return _row(*base, "not_run", reason="private_mode_off")
    per = [f for f in ph.get("faults") or [] if isinstance(f, dict)]
    local = [f for f in per if f.get("backend") == GLIMMER_BACKEND]
    secs = next((v for k, v in step_seconds(job_dir).items() if k.startswith("part5_analyse")), None)
    if not per:
        return _row(*base, "not_run", reason="no_faults")
    if not local:
        return _row(*base, "fallback", secs, ran="template", lines=len(per), reason=_short(ph.get("fallback_reason")))
    model = str(local[0].get("model") or "")
    if not model.startswith(GLIMMER_MODEL):  # another local model wrote the lines: not a Glimmer run
        return _row(*base, "fallback", secs, ran=_short(model) or "unknown", reason="other_local_model")
    return _row(*base, "live", secs, via="local_weights", model_id=model, lines=len(per), lines_live=len(local),
                reason=_short(ph.get("fallback_reason")) if len(local) < len(per) else None)


def muse_image_row(job_dir: Path) -> dict[str, Any]:
    """Muse Image from the take's `work/muse-fix/run-*.json` records (muse_fix.py): one per call, shown or not."""
    base = ("muse-image", "Muse Image", "you")
    runs = muse_fix.records(job_dir)
    if not runs:
        return _row(*base, "not_run", reason="no_corrected_picture")
    called = [r for r in runs if r.get("status") in ("shown", "missed")]
    if not called:
        return _row(*base, "fallback", ran="measured_faults", reason=_short(runs[-1].get("reason")) or "image_call_failed")
    shown = sum(1 for r in called if r.get("status") == "shown")
    return _row(*base, "live", via="meta_api", model_id=called[-1].get("model"), pictures=len(called), shown=shown)


def speech_row(job_dir: Path) -> dict[str, Any]:
    """MMS-TTS from the wavs speech.py cached under the job's `speech/`, or its failure lines in `steps/part7.log`."""
    base = ("mms-tts", "MMS-TTS", "you")
    try:
        names = [p.name for p in (job_dir / "speech").glob("*.wav") if p.is_file() and p.stat().st_size > 0]
    except OSError:
        names = []
    langs = sorted({m.group(1) for m in map(SPEECH_WAV.match, names) if m})
    spoken = sum(1 for n in names if SPEECH_WAV.match(n))
    if spoken:
        return _row(*base, "live", via="local_weights", spoken=spoken, languages=langs)
    if SPEECH_FAILED.search(_text(job_dir / "steps" / "part7.log")):
        return _row(*base, "fallback", ran="browser_voice", reason="speech_failed")
    return _row(*base, "not_run", reason="no_spoken_lines")


def collect(jobs_root: Path, job_id: str, *, catalog_dir: Path | None = None, state: Path | None = None,
            owner: str | None = None) -> dict[str, Any] | None:
    """The models of done follow job `job_id`, or None when it is not one.

    `owner` is the signed-in viewer when they own the job. Only then do the account rows (history, avatar, image3d) and
    the owner-only Muse Image row appear, so a stranger or a signed-out visitor never learns what an account ran."""
    job_dir = jobs_root / job_id
    record = _json(job_dir / "job.json")
    if not isinstance(record, dict) or record.get("kind") != "follow" or record.get("status") != "done":
        return None
    rows = [*trainer_rows(trainer_job(jobs_root, record.get("entry_id"))), narration_row(catalog_dir, record.get("entry_id")),
            *follower_rows(jobs_root, job_dir, record), phrasing_row(job_dir), opinion_row(job_dir),
            mhr_row(job_dir), glimmer_row(job_dir, record), speech_row(job_dir)]
    if owner and state is not None:
        rows += [history_row(state, owner, record.get("entry_id"), job_id), avatar_row(state, owner),
                 image3d_row(state, owner), muse_image_row(job_dir)]
    rows.sort(key=lambda r: ORDER.index(r["id"]))
    return {"job": job_id, "job_seconds": _job_seconds(record), "models": rows}


def _viewer_owns(h: Any, job_id: str) -> str | None:
    """The signed-in user's id when they own `job_id`, else None (identity is optional and never raises here)."""
    auth = history_store.optional_module("part7.auth")
    user = auth.current_user(h) if auth is not None else None
    if not isinstance(user, str) or not history_store.USER_ID_RE.match(user):
        return None
    return user if history_store.owner_of(h.app.state, job_id) == user else None


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
        doc = collect(root, job_id, catalog_dir=h.app.child.catalog_dir, state=h.app.state, owner=_viewer_owns(h, job_id))
    else:
        record = _json(root / job_id / "job.json")
        ok = isinstance(record, dict) and record.get("kind") == "follow" and record.get("status") == "done"
        if parts[2] == "trainer-visibility.json":  # the trainer's unseen joints (compare-view.md, TICKET-116)
            doc = trainer_visibility.build(root / job_id / "work" / "expected_skeleton.json") if ok else None
        else:
            doc = skeleton2d.build(root / job_id / "work" / "follower" / "part2", record.get("person_id"),
                                    min_conf=skeleton2d.UNSEEN_CONF) if ok else None  # TICKET-376: an unseen joint is not drawn
    if doc is None:
        h._error(404, MSG_GONE)
    else:
        h._json(200, doc)
    return True
