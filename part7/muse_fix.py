"""'You, doing it right': the model side of TICKET-280 (docs/specs/muse-fix.md).

`run` takes one finished follow job and one fault. It finds the worst moment of the fault, draws a red guide on
the student's own frame (`muse_fix_render.guide_frame`: where the joint would put the limb at the trainer's angle), sends that
frame and a plain-words prompt to muse-image-1.0 (TICKET-343), has SAM 3D Body measure the picture that comes back and shows it only when the
joint is within THRESHOLD_DEG of the target. A picture that misses is never written to the job folder; a miss is retried once, so a press makes at most MAX_ATTEMPTS calls. The record
(`work/muse-fix/<id>.json`) keeps the model id, the cost and the measured error for every run, shown or not, and a
shown picture carries the label LABEL. `referee` is the blind comparison (`muse_referee`). Everything lives in the
job folder, so it goes with the take. Opt-in: with `consent` false nothing is read, sent or written.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from typing import Any, Callable

from part7 import history_api, muse_fix_api, muse_fix_geom as geom, muse_fix_measure, muse_fix_render as render, muse_referee

THRESHOLD_DEG = 8.0
MAX_ATTEMPTS = 2  # one retry when the first picture misses the gate (operator decision, TICKET-343)
LABEL = "AI-generated illustration"
MISSED = "The image model missed the pose."
NOT_DRAWN = "Simon could not draw the picture this time."  # the call failed; its reason stays in the record
FOLDER = "muse-fix"
REFEREE_FILE = "referee.json"
SCHEMA = "simon.muse-fix.v1"
IMAGE_NAME = "corrected"
Measurer = Callable[[Path], "dict[str, Any] | None"]


def _read(path: Path) -> Any:
    return render.read_json(path)


def folder(job_dir: Path) -> Path:
    return Path(job_dir) / "work" / FOLDER


def _stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, sort_keys=True, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def pick_fault(analysis: dict[str, Any]) -> int | None:
    """The index of the supported, timed fault with the largest magnitude, else None."""
    best, at = -1.0, None
    for i, f in enumerate(analysis.get("faults") or []):
        if not isinstance(f, dict) or f.get("joint") not in geom.SUPPORTED or not isinstance(f.get("follower_frames"), list):
            continue
        m = f.get("magnitude_deg")
        m = float(m) if isinstance(m, (int, float)) and not isinstance(m, bool) else 0.0
        if m > best:
            best, at = m, i
    return at


def _mesh_frame(part2: Path, t_s: float | None, fallback: int) -> int:
    """The mesh frame nearest in time to `t_s` (the replay is resampled; Part 2's frames are not)."""
    head = _read(part2 / "mesh3d.json")
    frames = head.get("frames") if isinstance(head, dict) else None
    if not isinstance(frames, list) or not frames or t_s is None:
        return fallback
    return int(min(frames, key=lambda f: abs(float(f["t_ms"]) - t_s * 1000.0))["frame"])


def _pose(part2: Path, frame: int, person: Any) -> dict[str, Any] | None:
    doc = _read(part2 / "pose3d.json")
    try:
        row = next(f for f in doc["frames"] if f["frame"] == frame)
        return next(p["joints"] for p in row["people"] if str(p["id"]) == str(person))
    except (KeyError, TypeError, StopIteration):
        return None


def _frame_jpg(part2: Path, frame: int) -> bytes | None:
    for ext in ("jpg", "jpeg", "png"):
        path = part2 / "frames" / f"{frame:06d}.{ext}"
        if path.is_file():
            try:
                return path.read_bytes()
            except OSError:
                return None
    return None


def _result(job_id: str, status: str, **fields: Any) -> dict[str, Any]:
    return {"schema": SCHEMA, "job_id": job_id, "status": status, "created_at": _stamp(), **fields}


def card(record: dict[str, Any]) -> dict[str, Any]:
    """What the page shows for a record: the picture with its label and error, or the miss message only."""
    if record.get("status") == "shown":
        return {"status": "shown", "label": LABEL, "image": record["image"], "joint": record["joint"],
                "error_deg": record["error_deg"], "target_deg": record["target_deg"],
                "error_text": f"Measured error: {record['error_deg']:.1f} degrees from the target pose."}
    return {"status": record.get("status"), "message": MISSED if record.get("status") == "missed" else NOT_DRAWN}


def run(job_dir: Path | str, *, consent: bool, fault_index: int | None = None, transport: Any = None,
        measurer: Measurer | None = None, state: Path | str | None = None, keys_dir: Path | str | None = None,
        person: Any = None, clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Make, measure and gate one picture. Returns `{status, ...}`; `status` is one of `no_consent` (nothing happened),
    `not_available` (no mesh, replay or supported fault: nothing sent), `shown`, `missed` or `failed` (the call failed)."""
    job_dir = Path(job_dir)
    if consent is not True:
        return {"status": "no_consent"}
    job_id = job_dir.name
    follower, part2 = job_dir / "work" / "follower", job_dir / "work" / "follower" / "part2"
    rec = _read(job_dir / "job.json")
    analysis, replay = _read(follower / "analysis.json"), _read(follower / "replay.json")
    if not (isinstance(rec, dict) and rec.get("kind") == "follow" and rec.get("status") == "done"
            and isinstance(analysis, dict) and isinstance(replay, dict)):
        return {"status": "not_available", "reason": "this take has no result to work from"}
    person = rec.get("person_id", 0) if person is None else person
    idx = pick_fault(analysis) if fault_index is None else fault_index
    faults = analysis.get("faults") or []
    fault = faults[idx] if isinstance(idx, int) and 0 <= idx < len(faults) and isinstance(faults[idx], dict) else None
    moment = geom.choose_moment(replay, fault["joint"], fault.get("follower_frames") or []) if fault else None
    if moment is None:
        return {"status": "not_available", "reason": "no moment of this fault can be drawn"}
    frame = _mesh_frame(part2, moment["t_s"], moment["follower_frame"])
    joints, jpg = _pose(part2, frame, person), _frame_jpg(part2, frame)
    try:
        if joints is None or jpg is None:
            raise render.RenderError("the frame of this moment is missing")
        spots = render.guide_points(part2, frame, fault["joint"], moment["target_deg"], joints, person, jpg)
        guided = render.guide_frame(part2, frame, jpg, fault["joint"], moment["target_deg"], joints, person, points=spots)
    except render.RenderError as exc:
        return {"status": "not_available", "reason": str(exc)}
    base = {"fault_index": idx, "joint": fault["joint"], "frame": frame, "t_s": moment["t_s"],
            "follower_deg": round(moment["follower_deg"], 1), "target_deg": round(moment["target_deg"], 1),
            "threshold_deg": THRESHOLD_DEG, "model": muse_fix_api.IMAGE_MODEL}
    prompt = muse_fix_api.edit_prompt(fault["joint"], moment["follower_deg"], moment["target_deg"], spots[0][2], spots[0][1])
    attempts: list[dict[str, Any]] = []
    for _ in range(MAX_ATTEMPTS):
        try:
            made = muse_fix_api.edit_image(guided, prompt, transport=transport, state=state, keys_dir=keys_dir, clock=clock)
        except history_api.HistoryError as exc:
            if not attempts:  # the first call failed: nothing was made, nothing to retry
                return _save(job_dir, _result(job_id, "failed", reason=exc.reason, cost_usd=_reserved(exc), error_deg=None, **base))
            attempts.append({"call": None, "cost_usd": _reserved(exc), "measured_deg": None, "error_deg": None, "reason": exc.reason})
            break  # the retry was refused or failed: the first miss stands
        measured = _measure_candidate(made, measurer or muse_fix_measure.measure)
        angle = geom.joint_angle(measured, fault["joint"]) if measured else None
        error = None if angle is None else round(abs(angle - moment["target_deg"]), 1)
        attempts.append({"call": made["call"], "cost_usd": made["cost_usd"], "measured_deg": None if angle is None else round(angle, 1),
                         "error_deg": error, "reason": None if error is not None and error <= THRESHOLD_DEG else
                         ("no person found in the picture" if angle is None else "the joint is outside the threshold")})
        if attempts[-1]["reason"] is None:
            break
    cost = round(sum(a["cost_usd"] for a in attempts), 6)
    base.update(cost_usd=cost, attempts=attempts)
    hit = next((a for a in attempts if a["reason"] is None), None)
    if hit is None:
        last = next(a for a in reversed(attempts) if a["call"])
        return _save(job_dir, _result(job_id, "missed", reason=last["reason"], measured_deg=last["measured_deg"],
                                      error_deg=last["error_deg"], call=last["call"], **base))
    name = f"{IMAGE_NAME}-{moment['follower_frame']}.{made['kind']}"
    out = folder(job_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_bytes(made["image"])  # written only here, after the gate; `made` is the attempt that passed
    return _save(job_dir, _result(job_id, "shown", measured_deg=hit["measured_deg"], error_deg=hit["error_deg"], image=name,
                                  label=LABEL, call=hit["call"], **base))


def _reserved(exc: history_api.HistoryError) -> float:
    """What the ledger still holds for a call that raised: its reserve when it got that far, else nothing."""
    return float(getattr(exc, "reserved_usd", 0.0))


def _measure_candidate(made: dict[str, Any], measurer: Measurer) -> dict[str, Any] | None:
    """Measure the returned picture from a scratch file that is removed at once; nothing of it reaches the job folder."""
    scratch = Path(tempfile.mkdtemp(prefix="muse-fix-candidate-"))
    try:
        path = scratch / f"candidate.{made['kind']}"
        path.write_bytes(made["image"])
        return measurer(path)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _save(job_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    _write(folder(job_dir) / f"run-{record['created_at'].replace(':', '')}-{record.get('fault_index')}.json", record)
    return record


def records(job_dir: Path | str) -> list[dict[str, Any]]:
    """Every run record of a job, oldest first."""
    out = []
    for path in sorted(folder(Path(job_dir)).glob("run-*.json")):
        doc = _read(path)
        if isinstance(doc, dict) and doc.get("schema") == SCHEMA:
            out.append(doc)
    return out


def latest_card(job_dir: Path | str) -> dict[str, Any] | None:
    """The card for the newest record of a job, or None when no run happened (consent off: no card)."""
    rows = records(job_dir)
    return card(rows[-1]) if rows else None


def referee(job_dir: Path | str, reference: bytes, original: bytes, corrected: bytes, *, consent: bool, seed: int | None = None,
            **api: Any) -> dict[str, Any]:
    """One blind trial for a take; stores the record (never the pictures) beside the take. Nothing happens without consent."""
    if consent is not True:
        return {"status": "no_consent"}
    try:
        trial = muse_referee.trial(reference, original, corrected, seed=seed, **api)
    except history_api.HistoryError as exc:
        return {"status": "failed", "reason": exc.reason}
    path = folder(Path(job_dir)) / REFEREE_FILE
    rows = _read(path) if path.is_file() else []
    rows = [*(rows if isinstance(rows, list) else []), {**trial, "created_at": _stamp(), "job_id": Path(job_dir).name}]
    _write(path, rows)
    return {"status": "ok", **trial, "summary": muse_referee.summary(rows)}


def delete(job_dir: Path | str) -> bool:
    """Remove the pictures and records of a take (Delete my data). True when a folder was removed."""
    target = folder(Path(job_dir))
    if not target.is_dir():
        return False
    shutil.rmtree(target, ignore_errors=True)
    return True


def report(jobs_root: Path | str) -> dict[str, Any]:
    """Pass rate and referee tally over every job under `jobs_root`: the real numbers, whatever they are (AC-3, AC-4)."""
    runs, trials = [], []
    for job in sorted(p for p in Path(jobs_root).iterdir() if p.is_dir()):
        for r in records(job):
            runs.append({"job_id": job.name, "status": r["status"], "error_deg": r.get("error_deg"), "cost_usd": r.get("cost_usd"),
                         "joint": r.get("joint"), "model": r.get("model")})
        rows = _read(folder(job) / REFEREE_FILE) if (folder(job) / REFEREE_FILE).is_file() else []
        trials += rows if isinstance(rows, list) else []
    shown = sum(r["status"] == "shown" for r in runs)
    scored = sum(r["status"] in ("shown", "missed") for r in runs)
    return {"runs": runs, "scored": scored, "shown": shown, "pass_rate": round(shown / scored, 3) if scored else None,
            "takes": len({r["job_id"] for r in runs}), "referee": muse_referee.summary(trials)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m part7.muse_fix")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="make and measure one picture for a done follow job (needs the Meta key and the GPU)")
    r.add_argument("state"), r.add_argument("job_id")
    r.add_argument("--consent", action="store_true", help="the owner opted in")
    r.add_argument("--fault", type=int)
    sub.add_parser("report", help="pass rate and referee tally").add_argument("state")
    args = ap.parse_args(argv)
    from part7 import config
    root = config.state_root(args.state) / "jobs"
    if args.cmd == "report":
        print(json.dumps(report(root), indent=1))
        return 0
    result = run(root / args.job_id, consent=args.consent, fault_index=args.fault, state=args.state)
    print(json.dumps({k: v for k, v in result.items() if k != "created_at"}, indent=1))
    return 0 if result["status"] in ("shown", "missed") else 1


if __name__ == "__main__":
    sys.exit(main())
