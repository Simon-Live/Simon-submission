"""The progress sheet of a measure-only home programme (docs/specs/progress-sheet.md, TICKET-283).

Recording (AC-1): when a tracked take is copied to history (`programme.tracked`: a rehab-mode take, or any take of a
programme entry), `extend_copy` adds `rehab` to its `meta.json` (reps, peak angle of the primary measure, every measure's
peak, tempo; `rehab_measure.take_facts`) and writes `skeleton.json` (the follower's joints, no pixels). Both are
additive files in the take's own folder, so deleting the take deletes them; identity.db is not touched. `backfill`
fills takes copied before this existed, from their job folder while it is kept (7 days); a second run changes nothing.

The sheet (AC-2): `build` answers a calendar of sessions, the trend of degrees reached per day, every tracked take and
a skeleton-only replay of the latest one. It never names a clip or any video path. `public` is what a share holds.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys
from typing import Any

from part7 import applog, history_store, programme, rehab_measure

SKELETON_NAME = "skeleton.json"
FORMAT = "simon.progress.sheet.v1"


# ----- recording -----------------------------------------------------------------------------------------
def facts_for(state: Path | str, entry_id: str, mode: Any, analysis: Any, replay: Any) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    """`(rehab facts, skeleton)` for a tracked take, else None."""
    if not programme.tracked(mode, state, entry_id):
        return None
    facts = rehab_measure.take_facts(analysis, replay, programme.declared(state, entry_id))
    return facts, rehab_measure.skeleton(replay)


def extend_copy(state: Path | str, job: dict[str, Any], job_dir: Path, analysis: Any, meta: dict[str, Any], stage: Path) -> None:
    """Called by `history_store._copy` before the meta is written: adds `meta["rehab"]` and `stage/skeleton.json`."""
    replay = history_store.read_json(Path(job_dir) / "work" / "follower" / "replay.json")
    try:
        found = facts_for(state, str(job.get("entry_id")), meta.get("mode"), analysis, replay)
    except (ValueError, TypeError, KeyError, IndexError) as exc:  # an odd replay never costs the person their copy
        applog.log(f"progress sheet: facts of {job.get('id')} not kept: {applog.cause(exc)}")
        return
    if found is None:
        return
    meta["rehab"] = found[0]
    if found[1] is not None:
        history_store.write_json(stage / SKELETON_NAME, found[1])


def backfill(state: Path | str) -> dict[str, int]:
    """Add the facts to tracked copies that have none, from the job folder while it is kept. Idempotent."""
    done = {"filled": 0, "already": 0, "untracked": 0, "job_gone": 0}
    with history_store.locked(state):
        for entry, job_id in list(history_store._all_takes(state)):
            folder = entry / "takes" / job_id
            meta = history_store.read_json(folder / history_store.META_NAME)
            if not isinstance(meta, dict):
                continue
            if isinstance(meta.get("rehab"), dict):
                done["already"] += 1
                continue
            job_dir = Path(state) / "jobs" / job_id
            replay = history_store.read_json(job_dir / "work" / "follower" / "replay.json")
            found = facts_for(state, entry.name, meta.get("mode"), history_store.read_json(folder / history_store.ANALYSIS_NAME), replay)
            if found is None:
                done["untracked"] += 1
                continue
            if replay is None:
                done["job_gone"] += 1  # the job folder is gone: reps and tempo still come from the copied analysis
            if found[1] is not None and not (folder / SKELETON_NAME).is_file():
                history_store.write_json(folder / SKELETON_NAME, found[1])
            history_store.write_json(folder / history_store.META_NAME, {**meta, "rehab": found[0]})
            done["filled"] += 1
    return done


# ----- reading --------------------------------------------------------------------------------------------
def _facts(take: dict[str, Any]) -> dict[str, Any] | None:
    meta = history_store.read_json(take["analysis"].parent / history_store.META_NAME)
    facts = meta.get("rehab") if isinstance(meta, dict) else None
    return facts if isinstance(facts, dict) else None


def _measure(state: Path | str, entry_id: str, facts: list[dict[str, Any]]) -> str | None:
    declared = programme.declared(state, entry_id)
    if declared:
        return declared
    seen = Counter(f.get("measure") for f in facts if f.get("measure") in programme.LABELS)
    return min(seen, key=lambda m: (-seen[m], m)) if seen else None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _row(take: dict[str, Any], facts: dict[str, Any], measure: str | None) -> dict[str, Any]:
    peaks = facts.get("peaks") if isinstance(facts.get("peaks"), dict) else {}
    reps = facts.get("reps")
    return {"job_id": take["job_id"], "at": take["at"], "day": str(take["at"] or "")[:10] or None,
            "reps": reps if isinstance(reps, int) and not isinstance(reps, bool) else None,
            "peak_deg": _number(peaks.get(measure)) if measure else None, "tempo_ratio": _number(facts.get("tempo_ratio")),
            "synthetic": bool(take.get("synthetic"))}


def _days(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_day: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row["day"]:
            continue
        slot = by_day.setdefault(row["day"], {"day": row["day"], "sessions": 0, "peak_deg": None})
        slot["sessions"] += 1
        if row["peak_deg"] is not None and (slot["peak_deg"] is None or row["peak_deg"] > slot["peak_deg"]):
            slot["peak_deg"] = row["peak_deg"]
    return [by_day[d] for d in sorted(by_day)]


def project(skel: dict[str, Any], measure: str | None) -> dict[str, Any] | None:
    """2D points in a 0..1 box (y down), seen from the side for a bend or a raise forward, else from the front."""
    frames = rehab_measure.frames_of({"joints": skel.get("joints"), "follower": skel.get("frames")})
    if not frames:
        return None
    view = rehab_measure.plane(measure)
    flat = [[(p[2] if view == "side" else p[0], -p[1]) if p else None for p in f.values()] for f in frames]
    seen = [q for f in flat for q in f if q]
    if not seen:
        return None
    lo_x, lo_y = min(q[0] for q in seen), min(q[1] for q in seen)
    size = max(max(q[0] for q in seen) - lo_x, max(q[1] for q in seen) - lo_y) or 1.0
    pad_x = (size - (max(q[0] for q in seen) - lo_x)) / 2
    points = [[[round((q[0] - lo_x + pad_x) / size, 3), round((q[1] - lo_y) / size, 3)] if q else None for q in f] for f in flat]
    found = rehab_measure.peak(rehab_measure.series(frames, measure)) if measure else None
    return {"view": view, "bones": skel.get("bones") or [], "t": skel.get("t") or [], "frames": points,
            "peak_frame": found[1] if found else None}


def build(state: Path | str, user_id: str, entry_id: str, name: str | None = None) -> dict[str, Any] | None:
    """The owner's sheet for one entry, or None when the user has no tracked take of it (private takes are left out)."""
    takes = [t for t in history_store.takes(state, user_id, entry_id) if not t["private"]]
    tracked = [(t, f) for t in takes if (f := _facts(t)) is not None]
    if not tracked:
        return None
    measure = _measure(state, entry_id, [f for _, f in tracked])
    rows = [_row(t, f, measure) for t, f in tracked]
    latest = next((t for t, _ in reversed(tracked) if (t["analysis"].parent / SKELETON_NAME).is_file()), None)
    skel = history_store.read_json(latest["analysis"].parent / SKELETON_NAME) if latest else None
    return {
        "format": FORMAT, "entry_id": entry_id, "title": name or entry_id, "measure": measure,
        "measure_label": programme.LABELS.get(measure or ""), "declared": programme.declared(state, entry_id) is not None,
        "error": {"deg": rehab_measure.ERROR_DEG, "source": rehab_measure.ERROR_SOURCE},
        "days": _days(rows), "takes": rows, "sessions": len(rows),
        "skeleton": project(skel, measure) if isinstance(skel, dict) else None,
        "skeleton_on": latest["at"] if latest else None,
        "synthetic": any(r["synthetic"] for r in rows),
    }


def public(sheet: dict[str, Any]) -> dict[str, Any]:
    """What a share link holds: the sheet without the entry id or any job id. There is no video in either."""
    rows = [{k: v for k, v in r.items() if k != "job_id"} for r in sheet["takes"]]
    return {k: v for k, v in sheet.items() if k not in ("entry_id", "takes")} | {"takes": rows}


def drop_shares(db: Any, owner_id: str, entry_id: str | None = None) -> int:
    """Delete the owner's progress-sheet shares (of one entry, or all): the link and its stored copy go together."""
    if not db.has_table("shares"):
        return 0
    if entry_id is None:
        return db.write("DELETE FROM shares WHERE owner_id = ? AND kind = 'progress_sheet'", (owner_id,))
    return db.write("DELETE FROM shares WHERE owner_id = ? AND kind = 'progress_sheet' AND item_ref = ?", (owner_id, entry_id))


def main(argv: list[str]) -> int:
    """`python3 -m part7.progress_sheet backfill <state>`: prints the counts, exit 0."""
    if len(argv) != 2 or argv[0] != "backfill":
        print("usage: python3 -m part7.progress_sheet backfill <state dir>", file=sys.stderr)
        return 2
    print(backfill(argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

