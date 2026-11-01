"""Each person's SAM 3D Body mesh of a finished follow job (docs/specs/result-redesign-additions.md R3, TICKET-143).

Part 2 writes `mesh3d.json` and `mesh3d.bin` next to `pose3d.json` when it runs with `--mesh` (Part 2 CONTRACT.md).
The follower's are in the job's `work/follower/part2/`, the trainer's in the newest done trainer job of the same
catalog entry, `work/trainer/part2/` (models_used.trainer_job). Part 7 serves the files unchanged.

- `GET results/<job>/mesh.json` answers a done follow job with `{trainer, you}`: each the URL of that person's
  `mesh3d.json` (relative to the app's base path), or both null unless all four files are present (the view needs both
  people). Always 200 for such a job, so a result without
  meshes makes no failing request; 404 for any other id, kind or state.
- `GET results/<job>/mesh/<trainer|you>/<mesh3d.json|mesh3d.bin>` serves the file; 404 when it is absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from part7 import job_lookup, jobs, models_used

INDEX = "mesh.json"
FILES = {"mesh3d.json": "application/json; charset=utf-8", "mesh3d.bin": "application/octet-stream"}
WHO = ("trainer", "you")
MSG_GONE = "This result is not available."


def _record(job_dir: Path) -> dict[str, Any] | None:
    rec = job_lookup.read_json(job_dir / "job.json")
    ok = isinstance(rec, dict) and rec.get("kind") == "follow" and rec.get("status") == "done"
    return rec if ok else None


def _folders(jobs_root: Path, job_id: str, trainer_too: bool = True) -> dict[str, Path | None] | None:
    """`{who: folder}` for done follow job `job_id` (one read of its record, one trainer lookup), or None when it is not one."""
    job_dir = jobs_root / job_id
    rec = _record(job_dir)
    if rec is None:
        return None
    trainer = models_used.trainer_job(jobs_root, rec.get("entry_id")) if trainer_too else None
    return {
        "you": job_dir / "work" / "follower" / "part2",
        "trainer": trainer / "work" / "trainer" / "part2" if trainer is not None else None,
    }


def _regular(folder: Path | None, name: str) -> Path | None:
    path = folder / name if folder is not None and name in FILES else None
    return path if path is not None and path.is_file() and not path.is_symlink() else None


def mesh_dir(jobs_root: Path, job_id: str, who: str) -> Path | None:
    """The folder holding `who`'s mesh files for done follow job `job_id`, or None when there is none."""
    folders = _folders(jobs_root, job_id, who == "trainer") if who in WHO else None
    return folders[who] if folders is not None else None


def mesh_file(jobs_root: Path, job_id: str, who: str, name: str) -> Path | None:
    """The mesh file `name` of `who`, when it is a regular file (never a symlink), else None."""
    return _regular(mesh_dir(jobs_root, job_id, who) if name in FILES else None, name)


def index(jobs_root: Path, job_id: str) -> dict[str, str | None] | None:
    """`{trainer, you}` mesh URLs (null when absent) for a done follow job, or None when it is not one.

    The job record and the trainer lookup are read once per request, not once per file.
    """
    folders = _folders(jobs_root, job_id)
    if folders is None:
        return None
    url = lambda who: f"api/results/{job_id}/mesh/{who}/mesh3d.json"  # noqa: E731
    both = all(_regular(folders[who], n) for who in WHO for n in FILES)
    return {who: (url(who) if both else None) for who in WHO}


def handle(h: Any, method: str, route: str) -> bool:
    """Answer the mesh index and the mesh files; False for any other route."""
    parts = route.split("/")
    if method not in ("GET", "HEAD") or len(parts) < 3 or parts[0] != "results":
        return False
    is_index = len(parts) == 3 and parts[2] == INDEX
    is_file = len(parts) == 5 and parts[2] == "mesh"
    if not (is_index or is_file):
        return False
    job_id = parts[1]
    if not jobs.JOB_ID_RE.match(job_id):
        h._error(404, MSG_GONE)
        return True
    root = h.app.queue.job_dir(job_id).parent
    if is_index:
        doc = index(root, job_id)
        h._json(200, doc) if doc is not None else h._error(404, MSG_GONE)
        return True
    path = mesh_file(root, job_id, parts[3], parts[4])
    if path is None:
        h._error(404, MSG_GONE)
        return True
    h._send(200, path.read_bytes(), FILES[parts[4]])
    return True
