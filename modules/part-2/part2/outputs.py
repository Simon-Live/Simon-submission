"""`make outputs`: regenerate the scored outputs on this host, straight into the scored dir, each with a stamp.

Spec: docs/specs/check-2.md ("Scored outputs and stamps", AC-K08, error "backend gpu without CUDA"). ADR-0006,
ADR-0003 (tracker order), ADR-0002 (backends).

    python -m part2.outputs [--backend gpu|cpu|cpu-sam3db] [--tracker NAME] [--lifter NAME] [--modes a,b]
                            [--scored DIR] [--refine RUNGS]

MODES lists every scored mode: its dir name, the backend that makes it, its frames, how it runs and which
tracker it uses. `--backend gpu` (default) runs the gpu modes (`single`, `class` by the scored tracker order,
`class-local-open` always by local-open); `--backend cpu` runs `cpu-single`; `--backend cpu-sam3db` runs
`cpu-sam3db-single` (TICKET-044 B1: SAM 3D Body on the CPU device, scored by `make check-2-cpu CPU_MODE=...` only,
run with CUDA_VISIBLE_DEVICES=). A new mode is one more Mode entry
(TICKET-037 adds `coco-single` with its own runner). Each mode runs in a scratch dir under out/, then its output
files replace scored/<mode>/ and stamp.json is written last, with the hashes taken before inference started.
GPU inference runs under the host GPU lock (`output_steps.gpu_locked`). The commit and dirty state of the
tree (`provenance.part2_commit`) are measured once, before the first mode writes anything, and every mode's
pose3d.json and tracks.json provenance carries that value (review residuals R14, N3). Exit 0 when every mode ran, 1 when one failed or
the backend cannot run here, 2 for an unknown name.

`--refine kp2d-fit[,...]` (one-person ladder, ADR-0004) runs those part2.refine rungs on each one-person mode's
body3d.json before the canonical frame (single, coco-single, cpu-single, cpu-sam3db-single; any other mode with it
exits 2); the stamp names the rungs and adds their code and models, pose3d.json's provenance.refine lists them.
"""
import argparse
import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from part2.check import DEFAULT_SCORED, SCORED_ENV, scored_dir  # one rule for the scored dir, shared with check-2

ROOT = Path(__file__).resolve().parent.parent
WORK = "out/.outputs-work"
NO_CUDA = "outputs: backend gpu needs CUDA (make setup-gpu)"
PARAMS = {"smooth": False, "mirrored": False}  # pipeline options of every run, recorded in the stamp


@dataclass(frozen=True)
class Mode:
    name: str                   # scored/<name>/
    backend: str                # the BACKEND that makes it
    frames: str                 # repo-relative frames dir (with frames.json)
    run: Callable               # run(ctx) -> {"files": [rel paths in ctx.work], "frames": n, "people": n}
    tracker: str | None = None  # None: no tracker; "scored": the scored order; else a fixed registry name
    modules: tuple = ()         # the mode's own code modules (stamp code_files)
    one_person: bool = False    # takes --refine rungs
    refine: tuple = ()          # the rungs `make outputs` applies by default (the ladder's chosen rung, ADR-0004)


@dataclass
class Ctx:
    mode: Mode
    root: Path
    work: Path
    backend: object
    tracker: object = None
    skipped: list = field(default_factory=list)
    refine: list = field(default_factory=list)
    model2d: object = None
    commit: str | None = None   # part2_commit measured before the run wrote anything; None: measured per file


def refined(ctx: Ctx, doc: dict, frames_dir: Path, work_dir: Path) -> dict:
    """doc after the run's refine rungs, written to work_dir/body3d.json (the unrefined one kept as
    body3d-unrefined.json); doc itself when there are none."""
    if not ctx.refine:
        return doc
    from part2 import output_steps, refine

    if ctx.model2d is None:
        ctx.model2d = refine.load_2d(ctx.refine)
    return output_steps.refine(ctx.refine, doc, frames_dir, work_dir, ctx.backend, model2d=ctx.model2d,
                               lock=lambda: output_steps.gpu_locked(ctx.backend))


def extras_for(ctx: Ctx, meta: dict) -> dict:
    """output_steps.pose_extras with the refine rungs and their models in provenance (the same keys
    `part2 run --refine` writes) and the run's one commit measure."""
    from part2 import output_steps

    return output_steps.pose_extras(meta, PARAMS["mirrored"], ctx.backend, refine=ctx.refine, commit=ctx.commit)


def run_single(ctx: Ctx) -> dict:
    from part2 import canonical, frames, output_steps

    frames_dir = ctx.root / ctx.mode.frames
    with output_steps.gpu_locked(ctx.backend):
        doc = ctx.backend.estimate(frames_dir, ctx.work / "body3d.json")
    doc = refined(ctx, doc, frames_dir, ctx.work)
    extras = extras_for(ctx, frames.load_meta(frames_dir))
    canonical.write(ctx.work / "body3d.json", ctx.work, smooth=PARAMS["smooth"], extras=extras)
    people = {p["id"] for f in doc["frames"] for p in f["people"]}
    return {"files": ["pose3d.json", "camera.json"], "frames": len(doc["frames"]), "people": len(people)}


def run_multi(ctx: Ctx) -> dict:
    from part2 import frames, multi3d, output_steps

    frames_dir = ctx.root / ctx.mode.frames
    meta = frames.load_meta(frames_dir)
    doc = ctx.tracker.track(frames_dir, ctx.work / "tracks.json", skipped=ctx.skipped)
    output_steps.stamp_tracks(ctx.work / "tracks.json", doc,
                              output_steps.tracks_extras(meta, doc, ctx.backend.name, commit=ctx.commit))
    with output_steps.gpu_locked(ctx.backend):
        b3d = ctx.backend.estimate(frames_dir, ctx.work / "body3d.json", boxes=multi3d.tracks_to_boxes(doc))
    res = multi3d.write_pose_streams(b3d, ctx.work, smooth=PARAMS["smooth"],
                                     extras=output_steps.pose_extras(meta, PARAMS["mirrored"], ctx.backend,
                                                                     doc["provenance"], commit=ctx.commit))
    return {"files": ["tracks.json", "pose3d.json", "camera.json"], "frames": len(doc["frames"]),
            "people": len(res["people"]), "tracker_provenance": doc["provenance"]}


def run_coco(ctx: Ctx) -> dict:
    """coco-single (TICKET-037): one photo run per selected COCO image into <image_id>/{pose3d,camera}.json, the
    layout part2.eval_coco scores. Images come from the cache (sha256 checked), never from the tree."""
    from part2 import canonical, coco_set, frames, output_steps

    recs = coco_set.load_manifest()["images"]
    files = []
    for r in recs:
        src = coco_set.stage_photo(r, ctx.work / "in")
        run_dir = ctx.work / str(r["image_id"])
        run_dir.mkdir(parents=True, exist_ok=True)
        with output_steps.gpu_locked(ctx.backend):
            doc = ctx.backend.estimate(src, run_dir / "body3d.json")
        refined(ctx, doc, src, run_dir)
        extras = extras_for(ctx, frames.load_meta(src))
        canonical.write(run_dir / "body3d.json", run_dir, smooth=False, extras=extras)
        files += [f"{r['image_id']}/pose3d.json", f"{r['image_id']}/camera.json"]
    return {"files": files, "frames": len(recs), "people": len(recs)}


# The ladder's choice (progress/ladder.md rows 24 and 25): rung 3, `focal` then `kp2d-fit`, the first rung green on
# both one-person sets. `make outputs` applies it by default so it reproduces the committed outputs.
CHOSEN_RUNGS = ("focal", "kp2d-fit")
# ADR-0006, AC-K15: the steps every mode shares with `part2 run` and `part2 stock` (part2.output_steps) are code a
# scored output depends on, so every mode lists them and its stamp hashes them.
STEPS = ("part2.output_steps",)
MULTI = ("part2.track", "part2.multi3d", *STEPS)
MODES = [
    Mode("single", "gpu", "fixtures/input/single/frames", run_single, modules=STEPS, one_person=True,
         refine=CHOSEN_RUNGS),
    Mode("class", "gpu", "fixtures/input/class/frames", run_multi, tracker="scored", modules=MULTI),
    Mode("class-local-open", "gpu", "fixtures/input/class/frames", run_multi, tracker="local-open", modules=MULTI),
    Mode("cpu-single", "cpu", "fixtures/input/single/frames", run_single, modules=STEPS, one_person=True),
    # TICKET-044 B1 (ADR-0002 amendment 2026-10-31): the CPU variant on the bar fixture, no rung by default (as
    # cpu-single); committed under fixtures/output/scored/ (f76f19d) but never part of make check-2's gated blocks.
    Mode("cpu-sam3db-single", "cpu-sam3db", "fixtures/input/single/frames", run_single, modules=STEPS,
         one_person=True),
    Mode("coco-single", "gpu", "fixtures/input/coco/images", run_coco, modules=("part2.coco_set", *STEPS),
         one_person=True, refine=CHOSEN_RUNGS),
]


def modes_for(backend: str, names=None) -> list[Mode]:
    """The modes `backend` makes, in MODES order, optionally only `names`; ValueError for a name it does not make."""
    mine = [m for m in MODES if m.backend == backend]
    if not names:
        return mine
    known = {m.name: m for m in mine}
    unknown = [n for n in names if n not in known]
    if unknown:
        raise ValueError(f'backend {backend} does not make mode "{unknown[0]}"; choose {", ".join(known)}')
    return [known[n] for n in names]


def pick_tracker(mode: Mode, flag: str | None, n_frames: int):
    """(tracker, skipped): the flag for the class mode, else the mode's fixed tracker or the scored order."""
    from part2 import trackers

    if mode.tracker is None:
        return None, []
    if mode.tracker == "scored":
        return trackers.select(flag, n_frames=n_frames) if flag else trackers.resolve("scored", n_frames=n_frames)
    return trackers.select(mode.tracker, n_frames=n_frames)


def host_gpu(backend_name: str) -> str | None:
    if backend_name != "gpu":
        return None
    import torch

    return torch.cuda.get_device_name(0)


def run_mode(mode: Mode, backend, root: Path, scored: Path, tracker_flag=None, lifter=None, refine=(),
             shared: dict | None = None, commit: str | None = None) -> dict:
    """Run one mode into a scratch dir, then replace scored/<mode>/ with its outputs and the stamp. `shared`
    keeps the 2D model the refine rungs load across modes. `commit` is the run's one part2_commit measure
    (main() takes it before the first mode writes anything); a direct caller without it gets it measured here,
    before this mode writes."""
    from part2 import frames, provenance, stamp

    commit = commit or provenance.part2_commit()

    frames_dir = root / mode.frames
    n_frames = len(frames.load(frames_dir)) if mode.tracker else 0  # coco-single has images.json, no frames.json
    tracker, skipped = pick_tracker(mode, tracker_flag, n_frames)
    pre = stamp.prepare(root, mode.name, backend.name, frames_dir, mode.modules,
                        tracker=tracker.name if tracker else None, lifter=lifter, refine=refine)
    work = root / WORK / mode.name
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    t0 = time.perf_counter()
    shared = {} if shared is None else shared
    ctx = Ctx(mode, root, work, backend, tracker, list(skipped), list(refine), shared.get("model2d"), commit)
    res = mode.run(ctx)
    shared["model2d"] = ctx.model2d
    seconds = round(time.perf_counter() - t0, 1)
    tprov = res.get("tracker_provenance") or {}
    models = list(backend.provenance().get("models", [])) + list(tprov.get("models", []))
    if refine:
        from part2 import refine as refine_mod

        models += refine_mod.models(refine)
    dest = scored / mode.name
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    for f in res["files"]:
        (dest / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(work / f, dest / f)
    facts = {"frames": res["frames"], "people": res["people"], "seconds": seconds, "params": dict(PARAMS)}
    facts.update({k: tprov[k] for k in ("fallback_from", "fallback_reason", "spend_usd") if k in tprov})
    stamp.finish(pre, dest, res["files"], models=models, host_gpu=host_gpu(backend.name), run=facts)
    return {"dir": stamp.rel(dest, root), "backend": backend.name, "tracker": pre["tracker"], "lifter": lifter,
            **({"refine": list(refine)} if refine else {}), **facts}


def backend_for(name: str, lifter: str | None):
    """(backend, None) ready to run, or (None, refusal line) when it cannot run here."""
    from part2 import backends

    b = backends.get(name)
    if name == "cpu":
        b.lifter = lifter
        ok, why = b.available(lifter)
        return (b, None) if ok else (None, f"outputs: {backends.REFUSAL['cpu']} ({why})")
    ok, why = b.available()
    head = NO_CUDA if name == "gpu" else f"outputs: {backends.REFUSAL[name]}"
    return (b, None) if ok else (None, f"{head}\noutputs: {why}")


def main(argv=None, root: Path = ROOT) -> int:
    from part2 import backends, lifters, provenance, refine, trackers

    ap = argparse.ArgumentParser(prog="python -m part2.outputs", description="Regenerate the scored outputs.")
    ap.add_argument("--backend", default="gpu", help="gpu (single, class, class-local-open), cpu (cpu-single, RTMPose-x, "
                    "3D approximate) or cpu-sam3db (cpu-sam3db-single, SAM 3D Body on the CPU, meets the 3D bar)")
    ap.add_argument("--tracker", help="class mode only: a registry name instead of the scored order")
    ap.add_argument("--lifter", help="cpu backend: bones-prior, fixed-bones or motionbert (default: PART2_LIFTER, else "
                    "bones-prior)")
    ap.add_argument("--modes", help="comma-separated subset of the backend's modes")
    ap.add_argument("--scored", help=f"output root (default: {SCORED_ENV}, else {DEFAULT_SCORED})")
    ap.add_argument("--refine", default="", help="one-person modes: comma-separated ladder rungs (part2.refine); "
                    "default: each mode's chosen rungs; `none` runs no rung")
    a = ap.parse_args(argv)
    try:
        backends.resolve(a.backend)
        lifter = lifters.resolve(a.lifter) if a.backend == "cpu" else None
        if a.tracker:
            trackers.get(a.tracker)
        modes = modes_for(a.backend, [n for n in (a.modes or "").split(",") if n])
        explicit = a.refine.strip() not in ("", "none")
        rungs = refine.resolve(a.refine) if explicit else []
        if explicit and any(not m.one_person for m in modes):
            raise ValueError(f"--refine applies to one-person modes only; pass --modes "
                             f"{','.join(m.name for m in modes if m.one_person) or 'single'}")
    except (backends.UnknownBackend, lifters.UnknownLifter, trackers.UnknownTracker, ValueError) as e:
        print(f"outputs: {e}", file=sys.stderr)
        return 2
    backend, refusal = backend_for(a.backend, lifter)
    if backend is None:
        print(refusal, file=sys.stderr)
        return 1
    scored, summary, failed, shared = scored_dir(root, a.scored), {}, False, {}
    commit = provenance.part2_commit()  # once, before any mode rewrites the tracked outputs (R14)
    for mode in modes:
        print(f"outputs: {mode.name} ({a.backend}) ...", file=sys.stderr, flush=True)
        try:
            mode_rungs = rungs if explicit else ([] if a.refine.strip() == "none" else list(mode.refine))
            summary[mode.name] = run_mode(mode, backend, root, scored, a.tracker, lifter, mode_rungs, shared, commit)
        except (RuntimeError, ValueError, FileNotFoundError, OSError) as e:
            failed = True
            summary[mode.name] = {"error": f"{type(e).__name__}: {e}"}
            print(f"outputs: {mode.name}: {e}", file=sys.stderr)
    print(json.dumps(summary, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
