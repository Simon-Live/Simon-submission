"""The trainer's 2D ghost for the live camera preview (docs/specs/follow-ghost.md, TICKET-264).

`GET api/ghost/<entry_id>.json` answers a `simon.skeleton2d.v1` document (the format `skeleton2d.py` writes for a
follower) made from the entry's own trainer data. Part 7 measures nothing new and runs no pose model.

- `source: "part2"`, `box: "image"`: the trainer's own Part 2 `pose3d.json` projected through its `camera.json`
  (`skeleton2d.build`, the follower's overlay), from the newest done trainer job of the entry
  (`models_used.trainer_job`). Points are shares of the trainer's image, so the browser draws the ghost where the
  trainer was in their own frame, and a seated or side-on trainer keeps the length of their thighs. A joint Part 2
  placed outside the image (conf 0.3) is null, so a chest-up trainer has no guessed legs.
- The image ghost is kept in Part 7's own state, `<state>/ghosts/<entry_id>.json`, because the job sweep removes the
  trainer job folder after 7 days while the entry stays. `sweep` (with each job sweep, every 10 minutes) keeps it
  for the newest done trainer jobs and drops the copy of an entry that left the catalog; the route also keeps it the
  first time it builds one. `forget` removes it when the trainer take is deleted (delete_routes.py).
- Fallback for an entry with no trainer Part 2 files (an import, or a trainer job removed since):
  `source: "animation"|"skeleton"`, `box: "body"`. Part 4's `animation.json` (30 frames a second) or Part 3's
  `skeleton.json` with the depth axis dropped (x the subject's left, y up, hip midpoint at the origin) and the
  body's full height over the clip scaled to 1, as before this fix. A joint the clip never saw is null: one in
  Part 4's `unseen_joints`, or whose frame or joint `conf` is at or below 0.3.

Both pictures are the camera's own view of the trainer: the subject's left is on the image's right for a trainer
facing it. The browser mirrors the ghost when the reference video is mirrored.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Any

from part7 import applog, auth, history_store, job_lookup, models_used, skeleton2d
from part7.skeleton2d import BONES, JOINTS

ENTRY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
ROUTE_RE = re.compile(r"^ghost/(?P<id>[a-z0-9][a-z0-9-]{0,62})\.json$")
FORMAT = "simon.skeleton2d.v1"
KEEP_FORMAT = "simon.ghost-keep.v1"
KEEP_DIR = "ghosts"
SWEEP_LIMIT = 500  # newest trainer jobs a sweep looks at; one already kept costs one cached read
UNSEEN_AT = 0.3  # Parts 2 and 3 give a joint placed outside the image conf 0.3 (Part 4 CONTRACT.md "Visibility")
_NO_GHOST: set[str] = set()  # trainer job ids a sweep found no image ghost in (this process; cleared when large)
MSG_NONE = "This movement has no trainer skeleton to show."
MSG_ENTRY = "This movement is not in the catalog."


# ----- the trainer's own Part 2 files (box "image") ----------------------------------------------------------------
def _part2(job_dir: Path) -> tuple[Path, str | None]:
    """`(work/trainer/part2 folder, person id)` of one trainer job folder."""
    rec = job_lookup.read_json(job_dir / "job.json")
    person = rec.get("person_id") if isinstance(rec, dict) else None
    return job_dir / "work" / "trainer" / "part2", (None if person in (None, "") else str(person))


def trainer_part2(jobs_root: Path | None, entry_id: str) -> tuple[Path, str | None, str] | None:
    """`(work/trainer/part2 folder, person id, job id)` of the newest done trainer job that made `entry_id`, or None."""
    found = models_used.trainer_job(jobs_root, entry_id) if jobs_root is not None else None
    return (*_part2(found), found.name) if found is not None else None


def from_part2(part2_dir: Path, person_id: str | None = None) -> dict[str, Any] | None:
    """The image ghost of a trainer's Part 2 folder, or None when it is missing, malformed or shows no seen joint.

    Strict: a frame where the trainer (or their place in `camera.json`) is missing draws nothing, never another person."""
    try:
        doc = skeleton2d.build(part2_dir, person_id, min_conf=UNSEEN_AT, strict=True)
    except (AttributeError, KeyError, TypeError, ValueError, IndexError) as exc:  # valid JSON of the wrong shape
        applog.log(f"ghost: unreadable Part 2 files in {part2_dir}: {applog.cause(exc)}", level=logging.WARNING)
        return None
    if doc is None or not any(p is not None for f in doc["frames"] for p in f["pts"]):
        return None
    return {**doc, "box": "image", "mirrored": False}


# ----- the kept copy, which outlives the trainer job folder --------------------------------------------------------
def kept_path(state: Path | str, entry_id: str) -> Path:
    return Path(state) / KEEP_DIR / f"{entry_id}.json"


def kept(state: Path | str | None, entry_id: str) -> tuple[str, dict[str, Any]] | None:
    """`(trainer job id, image ghost)` kept for `entry_id`, or None. A copy that is not an image ghost with frames is
    absent (the route and the sweep rebuild it)."""
    if state is None or not ENTRY_RE.match(entry_id):
        return None
    doc = job_lookup.read_json(kept_path(state, entry_id))
    if not isinstance(doc, dict) or doc.get("format") != KEEP_FORMAT or doc.get("entry_id") != entry_id:
        return None
    saved = doc.get("ghost")
    if not isinstance(saved, dict) or saved.get("box") != "image":
        return None
    frames = saved.get("frames")
    return (str(doc.get("trainer_job") or ""), saved) if isinstance(frames, list) and frames else None


def keep(state: Path | str | None, entry_id: str, job_id: str, part2_dir: Path,
         person_id: str | None) -> dict[str, Any] | None:
    """Build the image ghost of a trainer job and keep it for `entry_id` (when `state` is set); the ghost or None."""
    ghost = from_part2(part2_dir, person_id)
    if ghost is None or state is None or not ENTRY_RE.match(entry_id):
        return ghost
    try:
        history_store.write_json(kept_path(state, entry_id),
                                 {"format": KEEP_FORMAT, "entry_id": entry_id, "trainer_job": job_id, "ghost": ghost})
    except OSError as exc:  # the route still answers the ghost; the next sweep tries again
        applog.log(f"ghost: could not keep {entry_id}: {applog.cause(exc)}", level=logging.WARNING)
    return ghost


def forget(state: Path | str, entry_id: str, job_id: str) -> bool:
    """Remove the kept ghost of `entry_id` when it was made from trainer job `job_id` (that take was deleted); True when
    removed. A copy made from a newer take of the entry stays."""
    path = kept_path(state, entry_id) if ENTRY_RE.match(entry_id) else None
    saved = kept(state, entry_id) if path is not None else None
    if path is None or saved is None or saved[0] != job_id:
        return False
    path.unlink(missing_ok=True)
    return True


def sweep(state: Path | str, catalog: Path | str, queue: Any) -> int:
    """Keep the image ghost of the newest done trainer job of each entry; drop the copies of entries that left the
    catalog. Returns how many were written."""
    written, seen = 0, set()
    listed = Path(catalog).is_dir()  # never skip or prune against a missing catalog
    if len(_NO_GHOST) > 4 * SWEEP_LIMIT:
        _NO_GHOST.clear()
    for job_id, entry_id in queue.recent_trainer_entries(SWEEP_LIMIT):
        if entry_id in seen or not ENTRY_RE.match(entry_id):
            continue
        seen.add(entry_id)  # newest first: the newest trainer job of an entry wins
        if job_id in _NO_GHOST or (listed and not (Path(catalog) / entry_id).is_dir()):
            continue  # no picture last time, or the movement left the catalog: nothing to parse
        saved = kept(state, entry_id)
        if saved is None or saved[0] != job_id:
            made = keep(state, entry_id, job_id, *_part2(Path(queue.job_dir(job_id)))) is not None
            written += made
            if not made:
                _NO_GHOST.add(job_id)  # a job's files do not change: do not parse them again every sweep
    folder = Path(state) / KEEP_DIR
    if listed and folder.is_dir():
        for path in folder.glob("*.json"):
            if not (Path(catalog) / path.stem).is_dir():  # the entry's folder is gone: the movement was removed
                path.unlink(missing_ok=True)
    return written


def image_ghost(entry_id: str, jobs_root: Path | None, state: Path | str | None) -> dict[str, Any] | None:
    """The trainer's own picture: the kept copy while it matches the newest trainer job (or that job is gone), else
    built from the job's files and kept; None without either."""
    trainer = trainer_part2(jobs_root, entry_id)
    saved = kept(state, entry_id)
    if saved is not None and (trainer is None or saved[0] == trainer[2]):
        return saved[1]
    built = keep(state, entry_id, trainer[2], trainer[0], trainer[1]) if trainer is not None else None
    return built if built is not None or saved is None else saved[1]  # a job that gives no picture keeps the saved one


# ----- the entry's Part 4 animation or Part 3 skeleton (box "body") ------------------------------------------------
def _point(joint: Any) -> tuple[float, float, float] | None:
    """`(x, y, conf)` of one joint in either layout ({x, y, z[, conf]} or [x, y, z]); None when missing."""
    try:
        if isinstance(joint, dict):
            return float(joint["x"]), float(joint["y"]), float(joint.get("conf", 1.0))
        if isinstance(joint, (list, tuple)) and len(joint) >= 2:
            return float(joint[0]), float(joint[1]), 1.0
    except (KeyError, TypeError, ValueError):
        return None
    return None


def _conf(frame_conf: Any, name: str) -> float:
    """A Part 4 frame's own conf of joint `name`: absent means seen (as in Part 5), unreadable means unseen."""
    try:
        return float(frame_conf.get(name, 1.0)) if isinstance(frame_conf, dict) else 1.0
    except (TypeError, ValueError):
        return 0.0


def _frames(doc: Any) -> list[tuple[float, dict[str, Any], Any]]:
    """`[(t seconds, {joint: value}, frame conf)]` of an animation (both Part 4 layouts) or a Part 3 skeleton."""
    if not isinstance(doc, dict) or not isinstance(doc.get("frames"), list):
        return []
    fps = doc.get("fps") if isinstance(doc.get("fps"), (int, float)) and doc.get("fps") > 0 else 30
    out = []
    for i, f in enumerate(doc["frames"]):
        if not isinstance(f, dict):
            continue
        if isinstance(f.get("t"), (int, float)):
            t = float(f["t"])
        elif isinstance(f.get("t_ms"), (int, float)):
            t = float(f["t_ms"]) / 1000.0
        else:
            t = i / fps
        joints = f.get("joints")
        if not isinstance(joints, dict):
            people = f.get("people")
            first = people[0] if isinstance(people, list) and people and isinstance(people[0], dict) else {}
            joints = first.get("joints")
        if isinstance(joints, dict):
            out.append((t, joints, f.get("conf")))
    return sorted(out, key=lambda fr: fr[0])


def _unseen(doc: Any) -> set[str]:
    """Part 4's `unseen_joints`: joints at or below conf 0.3 at every key frame."""
    names = doc.get("unseen_joints") if isinstance(doc, dict) else None
    return {str(n) for n in names} if isinstance(names, list) else set()


def build(doc: Any) -> dict[str, Any] | None:
    """The body ghost of one trainer animation or skeleton, or None when it has no seen joint.

    The body box is the first build's (every joint with a conf above 0 sets the height), so a standing trainer's ghost
    is unchanged; only a joint the clip never saw is now null."""
    frames, unseen = _frames(doc), _unseen(doc)
    points = [[_point(joints.get(n)) for n in JOINTS] for _, joints, _ in frames]
    ys = [p[1] for pts in points for p in pts if p is not None and p[2] > 0]
    if not ys or max(ys) - min(ys) <= 0:
        return None
    top, height = max(ys), max(ys) - min(ys)
    out, drawn = [], 0
    for (t, _, frame_conf), pts in zip(frames, points):
        row = []
        for n, p in zip(JOINTS, pts):
            seen = p is not None and n not in unseen and min(p[2], _conf(frame_conf, n)) > UNSEEN_AT
            row.append([round(0.5 + p[0] / height, 4), round((top - p[1]) / height, 4)] if seen else None)
            drawn += seen
        out.append({"t": round(t, 3), "pts": row})
    if not drawn:
        return None
    return {"format": FORMAT, "box": "body", "mirrored": False, "image_size": [1, 1], "joints": list(JOINTS),
            "bones": [list(b) for b in BONES], "frames": out}


# ----- the route ---------------------------------------------------------------------------------------------------
def _entry_ghost(child: Any, entry_id: str, manifest: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """`(source, body ghost)` from the entry's animation, else its skeleton, or None."""
    for key in ("animation", "skeleton"):
        name = manifest.get(key)
        raw = child.get_entry_file(entry_id, str(name)) if isinstance(name, str) and name else None
        if raw is None:
            continue
        try:
            ghost = build(json.loads(raw.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            ghost = None
        if ghost is not None:
            return key, ghost
    return None


def for_entry(child: Any, entry_id: str, jobs_root: Path | None = None,
              state: Path | str | None = None) -> tuple[int, dict[str, Any]]:
    """`(200, ghost)`; `(200, {available: false})` for an entry with no trainer joints; `(404, error)` for no entry.

    The trainer's own picture (`image_ghost`: kept under `state`, or built from the trainer job under `jobs_root`)
    comes first; the entry's animation or skeleton is the fallback."""
    manifest = child.get_entry(entry_id)
    if not isinstance(manifest, dict):
        return 404, {"error": MSG_ENTRY}
    image = image_ghost(entry_id, jobs_root, state)
    found = ("part2", image) if image is not None else _entry_ghost(child, entry_id, manifest)
    if found is None:
        return 200, {"available": False, "entry_id": entry_id, "reason": MSG_NONE}  # not an error: no ghost shown
    return 200, {**found[1], "available": True, "entry_id": entry_id, "source": found[0]}


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `ghost/<entry_id>.json`; False for any other route."""
    m = ROUTE_RE.match(route)
    if not m or method not in ("GET", "HEAD"):
        return False
    if not auth.may_view_entry(h, m.group("id")):  # app-surface B1: a hidden movement answers as a missing one
        h._error(404, MSG_ENTRY)
        return True
    status, body = for_entry(h.app.child, m.group("id"), h.app.queue.root, h.app.state)
    if status == 200:
        h._json(200, body)
    else:
        h._error(status, body["error"])
    return True
