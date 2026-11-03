"""The three pictures the blind referee is shown for a take (docs/specs/muse-fix-ui.md, TICKET-280 AC-4).

All three are grey control renders made with `muse_fix_render.control_render` from SAM 3D Body meshes at the moment of the
take's latest picture run: the trainer's body at the matched moment (the reference), the follower's body as it was (the
original) and the follower's body with the faulted joint turned to the trainer's angle (the corrected one). They are
renders of measured meshes, so the referee judges movement, not a photograph. Any missing file is a `RenderError`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from part7 import models_used, muse_fix
from part7 import muse_fix_geom as geom
from part7 import muse_fix_render as render

RenderError = render.RenderError


def _trainer_part2(jobs_root: Path, entry_id: Any) -> Path:
    found = models_used.trainer_job(jobs_root, entry_id)
    if found is None:
        raise RenderError("the trainer's mesh is not available")
    return found / "work" / "trainer" / "part2"


def _first_person(part2: Path, frame: int) -> Any:
    head = render.read_json(part2 / "mesh3d.json")
    rows = head.get("frames") if isinstance(head, dict) else None
    row = next((f for f in rows or [] if f.get("frame") == frame), None)
    people = row.get("people") if isinstance(row, dict) else None
    if not people:
        raise RenderError("the trainer's mesh has no person at this moment")
    return people[0]["id"]


def referee_images(jobs_root: Path, job_dir: Path) -> tuple[bytes, bytes, bytes]:
    """`(reference, original, corrected)` PNG bytes from the take's newest picture run; RenderError when any is missing."""
    rows = muse_fix.records(job_dir)
    if not rows:
        raise RenderError("make the picture first")
    rec = rows[-1]
    follower = Path(job_dir) / "work" / "follower"
    part2 = follower / "part2"
    analysis, replay = render.read_json(follower / "analysis.json"), render.read_json(follower / "replay.json")
    job = render.read_json(Path(job_dir) / "job.json") or {}
    faults = analysis.get("faults") if isinstance(analysis, dict) else None
    idx = rec.get("fault_index")
    fault = faults[idx] if isinstance(faults, list) and isinstance(idx, int) and 0 <= idx < len(faults) else None
    moment = geom.choose_moment(replay, rec["joint"], fault.get("follower_frames") or []) if fault and isinstance(replay, dict) else None
    times = replay.get("expected_t") if isinstance(replay, dict) else None
    if moment is None or not isinstance(times, list) or moment["expected_frame"] >= len(times):
        raise RenderError("the trainer's moment is not available")
    person = job.get("person_id", 0)
    joints = muse_fix._pose(part2, rec["frame"], person)
    if joints is None:
        raise RenderError("the follower's pose is not available")
    original = render.control_render(part2, rec["frame"], rec["joint"], rec["follower_deg"], joints, person)
    corrected = render.control_render(part2, rec["frame"], rec["joint"], rec["target_deg"], joints, person)
    t_part2 = _trainer_part2(jobs_root, job.get("entry_id"))
    t_frame = muse_fix._mesh_frame(t_part2, float(times[moment["expected_frame"]]), -1)
    t_person = _first_person(t_part2, t_frame)
    t_joints = muse_fix._pose(t_part2, t_frame, t_person)
    if t_joints is None:
        raise RenderError("the trainer's pose is not available")
    reference = render.control_render(t_part2, t_frame, rec["joint"], rec["target_deg"], t_joints, t_person)
    return reference, original, corrected
