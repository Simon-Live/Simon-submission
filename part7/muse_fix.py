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
import contextlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from typing import Any, Callable, Iterator

from part7 import history_api, muse_fix_api, muse_fix_geom as geom, muse_fix_measure, muse_fix_render as render, muse_fix_sanity, muse_referee, serverless_route

# The switch (release 14): False hides the feature on every server, staging and prod alike. To turn it on, change this line to
# `DRAW_ENABLED = True`, once a clean take has produced a picture someone has looked at.
DRAW_ENABLED = False
THRESHOLD_DEG = 8.0
MAX_ATTEMPTS = 2  # one retry when the first picture misses the gate (operator decision, TICKET-343)
LABEL = "AI-generated illustration"
MISSED = "The image model missed the pose."
NOT_DRAWN = "Simon could not draw the picture this time."  # the call failed; its reason stays in the record
NOTHING_SENT = "Simon could not find a moment to draw in this take. Nothing was sent."  # not_available: retrying finds the same
NO_CHECK = "Simon cannot check pictures on this server, so it does not draw one. Nothing was sent."
SWITCHED_OFF = "Drawing you doing it right is switched off for now, so Simon does not draw one. Nothing was sent."
NO_ROUTE = "Simon cannot reach the service that checks pictures right now, so it does not draw one. Nothing was sent."
CHECK_FAILED = "the picture could not be checked"
FOLDER = "muse-fix"
REFEREE_FILE = "referee.json"
SCHEMA = "simon.muse-fix.v1"
IMAGE_NAME = "corrected"
Measurer = Callable[[Path], "dict[str, Any] | None"]


def _read(path: Path) -> Any:
    return render.read_json(path)


def blocker() -> str | None:
    """Why no picture can be drawn on this server, in plain words, else None. Cheap: reads settings and files, calls nothing."""
    if not DRAW_ENABLED:
        return SWITCHED_OFF
    return None if muse_fix_measure.available() else NO_CHECK


def folder(job_dir: Path) -> Path:
    return Path(job_dir) / "work" / FOLDER


def _stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, sort_keys=True, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _ranked_faults(analysis: dict[str, Any]) -> list[int]:
    """The indexes of the supported, timed faults, largest magnitude first (a tie keeps the file's order)."""
    found: list[tuple[float, int]] = []
    for i, f in enumerate(analysis.get("faults") or []):
        if not isinstance(f, dict) or f.get("joint") not in geom.SUPPORTED or not isinstance(f.get("follower_frames"), list):
            continue
        m = f.get("magnitude_deg")
        found.append((float(m) if isinstance(m, (int, float)) and not isinstance(m, bool) else 0.0, i))
    return [i for _, i in sorted(found, key=lambda row: -row[0])]


def pick_fault(analysis: dict[str, Any]) -> int | None:
    """The index of the supported, timed fault with the largest magnitude, else None."""
    return next(iter(_ranked_faults(analysis)), None)


def can_offer(job_dir: Path | str) -> bool:
    """False when the take's analysis has no fault this can draw (spine, neck, ankle, a joint with no side). A take with
    no readable analysis stays True: `run` looks and leaves a record that says so."""
    analysis = _read(Path(job_dir) / "work" / "follower" / "analysis.json")
    return not isinstance(analysis, dict) or pick_fault(analysis) is not None


def _want(fault: dict[str, Any]) -> int | None:
    """Which way the fault's cue asks its joint's angle to go (+1 opens, -1 closes), None when unknown."""
    return geom.wanted_move(fault.get("measure"), fault.get("direction"))


def _first_moment(analysis: dict[str, Any], replay: dict[str, Any]) -> tuple[int | None, dict[str, Any] | None]:
    """The biggest supported fault that has a moment to draw, and that moment."""
    faults = analysis.get("faults") or []
    for i in _ranked_faults(analysis):
        moment = geom.choose_moment(replay, faults[i]["joint"], faults[i].get("follower_frames") or [], _want(faults[i]))
        if moment is not None:
            return i, moment
    return None, None


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
    """The frame's bytes, None when no such file exists; a read fault raises RenderBusy (R5: never saved as `not_available`)."""
    for ext in ("jpg", "jpeg", "png"):
        path = part2 / "frames" / f"{frame:06d}.{ext}"
        if path.is_file():
            try:
                return path.read_bytes()
            except OSError:
                raise render.RenderBusy("the frame of this moment could not be read this time") from None  # a transient fault, not a missing frame
    return None


def _result(job_id: str, status: str, **fields: Any) -> dict[str, Any]:
    return {"schema": SCHEMA, "job_id": job_id, "status": status, "created_at": _stamp(), **fields}


def card(record: dict[str, Any]) -> dict[str, Any]:
    """What the page shows for a record: the picture with its label and error, or the miss message only."""
    if record.get("status") == "shown":
        return {"status": "shown", "label": LABEL, "image": record["image"], "joint": record["joint"],
                "error_deg": record["error_deg"], "target_deg": record["target_deg"],
                "error_text": f"Measured error: {record['error_deg']:.1f} degrees from the target pose."}
    words = {"missed": MISSED, "not_available": NOTHING_SENT}
    return {"status": record.get("status"), "message": words.get(str(record.get("status")), NOT_DRAWN)}


def not_drawn(job_dir: Path | str, status: str, reason: str) -> dict[str, Any]:
    """Leave the record of a press that made no picture, so the card has something to say. A folder that is no job stays as it is."""
    job_dir = Path(job_dir)
    return _save(job_dir, _result(job_dir.name, status, reason=reason, cost_usd=0.0, error_deg=None)) if job_dir.is_dir() else {"status": status, "reason": reason}


def run(job_dir: Path | str, *, consent: bool, fault_index: int | None = None, transport: Any = None,
        measurer: Measurer | None = None, state: Path | str | None = None, keys_dir: Path | str | None = None,
        person: Any = None, clock: Callable[[], float] = time.monotonic, probe: bool = True) -> dict[str, Any]:
    """Make, measure and gate one picture. Returns `{status, ...}`; `status` is one of `no_consent` (nothing happened),
    `not_available` (no mesh, replay or supported fault: nothing sent), `shown`, `missed` or `failed` (the call failed)."""
    job_dir = Path(job_dir)
    if consent is not True:
        return {"status": "no_consent"}
    if not DRAW_ENABLED:  # the switch: nothing is read, sent or paid
        return {"status": "no_check", "reason": SWITCHED_OFF}
    job_id = job_dir.name
    follower, part2 = job_dir / "work" / "follower", job_dir / "work" / "follower" / "part2"
    rec = _read(job_dir / "job.json")
    analysis, replay = _read(follower / "analysis.json"), _read(follower / "replay.json")
    if not (isinstance(rec, dict) and rec.get("kind") == "follow" and rec.get("status") == "done"
            and isinstance(analysis, dict) and isinstance(replay, dict)):
        return not_drawn(job_dir, "not_available", "this take has no result to work from")
    person = rec.get("person_id", 0) if person is None else person
    faults = analysis.get("faults") or []
    if fault_index is None:
        idx, moment = _first_moment(analysis, replay)
    else:
        idx = fault_index
        chosen = faults[idx] if 0 <= idx < len(faults) and isinstance(faults[idx], dict) else None
        moment = geom.choose_moment(replay, chosen["joint"], chosen.get("follower_frames") or [], _want(chosen)) if chosen else None
    if moment is None:
        return not_drawn(job_dir, "not_available", "no moment of this fault can be drawn")
    if measurer is None and not muse_fix_measure.available():  # before any paid call: a picture nobody can check is never made
        return {"status": "no_check", "reason": NO_CHECK}
    if measurer is None and probe and not muse_fix_measure.reachable():  # R1: Modal stopped or the app gone, so nothing is paid for a picture that cannot be checked
        return {"status": "no_check", "reason": NO_ROUTE}
    fault = faults[idx]
    frame = _mesh_frame(part2, moment["t_s"], moment["follower_frame"])
    joints = _pose(part2, frame, person)
    try:
        jpg = _frame_jpg(part2, frame)
        if joints is None or jpg is None:
            raise render.RenderError("the frame of this moment is missing")
        spots = render.guide_points(part2, frame, fault["joint"], moment["target_deg"], joints, person, jpg)
        guided = render.guide_frame(part2, frame, jpg, fault["joint"], moment["target_deg"], joints, person, points=spots)
    except render.RenderBusy as exc:  # this try only: the card keeps its Try again
        return not_drawn(job_dir, "failed", str(exc))
    except render.RenderError as exc:
        return not_drawn(job_dir, "not_available", str(exc))
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
        try:
            with _modal_job(job_dir):
                measured = _measure_candidate(made, measurer or muse_fix_measure.measure)
        except muse_fix_measure.CheckFailed as exc:  # no answer about the picture: it is not shown, and a retry would pay again for the same outage
            attempts.append({"call": made["call"], "cost_usd": made["cost_usd"], "measured_deg": None, "error_deg": None,
                             "reason": f"{CHECK_FAILED} ({exc})"})
            break
        angle = geom.joint_angle(measured, fault["joint"]) if measured else None
        error = None if angle is None else round(abs(angle - moment["target_deg"]), 1)
        attempts.append({"call": made["call"], "cost_usd": made["cost_usd"], "measured_deg": None if angle is None else round(angle, 1),
                         "error_deg": error, "reason": _why_not(measured, angle, error, fault, moment, joints)})
        if attempts[-1]["reason"] is None:
            break
    cost = round(sum(a["cost_usd"] for a in attempts), 6)
    base.update(cost_usd=cost, attempts=attempts)
    hit = next((a for a in attempts if a["reason"] is None), None)
    if hit is None:
        last = next(a for a in reversed(attempts) if a["call"])
        if str(last["reason"]).startswith(CHECK_FAILED):
            return _save(job_dir, _result(job_id, "failed", reason=last["reason"], call=last["call"], error_deg=None, **base))
        return _save(job_dir, _result(job_id, "missed", reason=last["reason"], measured_deg=last["measured_deg"],
                                      error_deg=last["error_deg"], call=last["call"], **base))
    name = f"{IMAGE_NAME}-{moment['follower_frame']}.{made['kind']}"
    out = folder(job_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_bytes(made["image"])  # written only here, after the gate; `made` is the attempt that passed
    return _save(job_dir, _result(job_id, "shown", measured_deg=hit["measured_deg"], error_deg=hit["error_deg"], image=name,
                                  label=LABEL, call=hit["call"], **base))


def _why_not(measured: dict[str, Any] | None, angle: float | None, error: float | None, fault: dict[str, Any],
             moment: dict[str, Any], original: dict[str, Any]) -> str | None:
    """None when the picture passes every check; else the first reason. The angle alone is not enough (R14): the picture must
    also be one whole person, with the joint moved from the student's own frame the way the cue asks."""
    if angle is None:
        return "no person found in the picture"
    sane = muse_fix_sanity.verdict(measured, fault["joint"], original=original, target_deg=moment["target_deg"], want=_want(fault))
    if sane:
        return sane
    return None if error is not None and error <= THRESHOLD_DEG else "the joint is outside the threshold"


@contextlib.contextmanager
def _modal_job(job_dir: Path) -> Iterator[None]:
    """In serverless mode the check's Modal call belongs to this take (its ledger entry goes with a delete)."""
    if serverless_route.enabled():
        with serverless_route.job(job_dir.parent.parent, job_dir.name):
            yield
    else:
        yield


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
    if not DRAW_ENABLED:  # R14b B4: the switch is off, so nothing is sent and nothing is paid, whatever picture was shown before
        return {"status": "no_check", "reason": SWITCHED_OFF}
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
    """Pass rate and referee tally over every job under `jobs_root`: the real numbers, whatever they are (AC-3, AC-4).
    `takes` counts takes where something was sent: a take whose only record is `not_available` is none."""
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
            "takes": len({r["job_id"] for r in runs if r["status"] in ("shown", "missed") or (r.get("cost_usd") or 0) > 0}), "referee": muse_referee.summary(trials)}


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
