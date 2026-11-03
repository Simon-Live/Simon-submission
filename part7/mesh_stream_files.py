"""The follower's SAM 3D Body mesh while the job runs (TICKET-284; docs/specs/mesh-stream.md).

Part 2 run with `--mesh --mesh-stream` writes `mesh3d.stream/` (head.bin, chunk-NNNN.bin, stream.json) into the job's
`work/follower/part2/` as each frame finishes (Part 2 CONTRACT.md, spec AC-M19 to AC-M23). This module reads that folder for
a follow job in any state and hands the route layer plain data; it owns no route and decides no access (the caller checks
the job's owner first, like every other job read). Pure file reads: no GPU, no model, no network.

- `snapshot(jobs_root, job_id)` answers `{frames_done, frames_total, done, vertex_count, block_bytes, blocks, files}` or
  None when the job is not a follow job or no frame has been flushed yet (the page then shows the plain progress view).
- `stream_file(jobs_root, job_id, name)` the bytes' path for one of the three file shapes, never a symlink, else None.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from part7 import job_lookup, jobs

FOLDER = "mesh3d.stream"
MANIFEST = "stream.json"
FORMAT_PREFIX = "part2.mesh3d-stream/"
NAME_RE = re.compile(r"^(?:stream\.json|head\.bin|chunk-\d{4}\.bin)$")
TYPES = {".json": "application/json; charset=utf-8", ".bin": "application/octet-stream"}


def _folder(jobs_root: Path, job_id: str) -> Path | None:
    if not jobs.JOB_ID_RE.match(job_id):
        return None
    rec = job_lookup.read_json(jobs_root / job_id / "job.json")
    if not isinstance(rec, dict) or rec.get("kind") != "follow":
        return None
    return jobs_root / job_id / "work" / "follower" / "part2" / FOLDER


def stream_file(jobs_root: Path, job_id: str, name: str) -> Path | None:
    """The file `name` of the job's stream when `name` is one of the three shapes and a regular file, else None."""
    folder = _folder(jobs_root, job_id) if NAME_RE.match(name) else None
    path = folder / name if folder is not None else None
    return path if path is not None and path.is_file() and not path.is_symlink() else None


def content_type(name: str) -> str:
    return TYPES[Path(name).suffix]


def _count(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def snapshot(jobs_root: Path, job_id: str) -> dict[str, Any] | None:
    """What the viewer needs to draw the frames done so far, or None when there is nothing to draw (a manifest that
    is missing, unreadable, of another format or listing a chunk that is absent counts as nothing)."""
    path = stream_file(jobs_root, job_id, MANIFEST)
    doc = job_lookup.read_json(path) if path is not None else None
    if not isinstance(doc, dict) or not str(doc.get("format", "")).startswith(FORMAT_PREFIX):
        return None
    head, chunks, frames = doc.get("head"), doc.get("chunks"), doc.get("frames")
    if not isinstance(head, dict) or not isinstance(chunks, list) or not isinstance(frames, list) or not chunks:
        return None
    names = [c.get("file") if isinstance(c, dict) else None for c in chunks]
    if any(not isinstance(n, str) or not NAME_RE.match(n) or stream_file(jobs_root, job_id, n) is None for n in names):
        return None
    if stream_file(jobs_root, job_id, str(head.get("file"))) is None:
        return None
    base = f"api/results/{job_id}/mesh-stream/"
    return {
        "frames_done": len(frames),
        "frames_total": _count(doc.get("frames_total")),
        "done": doc.get("done") is True,
        "vertex_count": _count(head.get("vertex_count")),
        "block_bytes": _count(doc.get("block_bytes")),
        "blocks": sum(_count(c.get("blocks")) or 0 for c in chunks),
        "manifest": base + MANIFEST,
        "head": base + str(head["file"]),
        "chunks": [base + n for n in names],
    }
