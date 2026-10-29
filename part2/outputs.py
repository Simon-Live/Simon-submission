"""`make outputs`: regenerate the scored outputs on this host, straight into the scored dir, each with a stamp.

Spec: docs/specs/check-2.md ("Scored outputs and stamps", AC-K08, error "backend gpu without CUDA"). ADR-0006,
ADR-0003 (tracker order), ADR-0002 (backends).

    python -m part2.outputs [--backend gpu|cpu] [--tracker NAME] [--lifter NAME] [--modes a,b] [--scored DIR]

MODES lists every scored mode: its dir name, the backend that makes it, its frames, how it runs and which
tracker it uses. `--backend gpu` (default) runs the gpu modes (`single`, `class` by the scored tracker order,
`class-local-open` always by local-open); `--backend cpu` runs `cpu-single`. A new mode is one more Mode entry
(TICKET-037 adds `coco-single` with its own runner). Each mode runs in a scratch dir under out/, then its output
files replace scored/<mode>/ and stamp.json is written last, with the hashes taken before inference started.
GPU inference runs under the host GPU lock (`gpu_guard`). Exit 0 when every mode ran, 1 when one failed or
the backend cannot run here, 2 for an unknown name.
"""
import argparse
import contextlib
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
SCORED_ENV = "PART2_SCORED_DIR"
DEFAULT_SCORED = "fixtures/output/scored"
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


@dataclass
class Ctx:
    mode: Mode
    root: Path
    work: Path
    backend: object
    tracker: object = None
    skipped: list = field(default_factory=list)


def gpu_guard(wait_s: float | None = None):
    """The host's one-GPU-job lock: part2.gpu_guard.gpu_lock when present, else part2.trackers.gpu_lock."""
    try:
        from part2.gpu_guard import gpu_lock
    except ImportError:
        from part2.trackers import gpu_lock
    return gpu_lock() if wait_s is None else gpu_lock(wait_s=wait_s)


def _locked(ctx: Ctx):
    return gpu_guard() if ctx.backend.name == "gpu" else contextlib.nullcontext()


def run_single(ctx: Ctx) -> dict:
    from part2 import canonical, cli, frames

    frames_dir = ctx.root / ctx.mode.frames
    with _locked(ctx):
        doc = ctx.backend.estimate(frames_dir, ctx.work / "body3d.json")
    extras = cli._pose_extras(frames.load_meta(frames_dir), PARAMS["mirrored"], ctx.backend)
    canonical.write(ctx.work / "body3d.json", ctx.work, smooth=PARAMS["smooth"], extras=extras)
    people = {p["id"] for f in doc["frames"] for p in f["people"]}
    return {"files": ["pose3d.json", "camera.json"], "frames": len(doc["frames"]), "people": len(people)}


def run_multi(ctx: Ctx) -> dict:
    from part2 import cli, frames, multi3d

    frames_dir = ctx.root / ctx.mode.frames
    meta = frames.load_meta(frames_dir)
    doc = ctx.tracker.track(frames_dir, ctx.work / "tracks.json", skipped=ctx.skipped)
    cli._stamp_tracks(ctx.work / "tracks.json", doc, cli._tracks_extras(meta, doc, ctx.backend.name))
    with _locked(ctx):
        b3d = ctx.backend.estimate(frames_dir, ctx.work / "body3d.json", boxes=multi3d.tracks_to_boxes(doc))
    res = multi3d.write_pose_streams(b3d, ctx.work, smooth=PARAMS["smooth"],
                                     extras=cli._pose_extras(meta, PARAMS["mirrored"], ctx.backend, doc["provenance"]))
    return {"files": ["tracks.json", "pose3d.json", "camera.json"], "frames": len(doc["frames"]),
            "people": len(res["people"]), "tracker_provenance": doc["provenance"]}


def run_coco(ctx: Ctx) -> dict:
    """coco-single (TICKET-037): one photo run per selected COCO image into <image_id>/{pose3d,camera}.json, the
    layout part2.eval_coco scores. Images come from the cache (sha256 checked), never from the tree."""
    from part2 import canonical, cli, coco_set, frames

    recs = coco_set.load_manifest()["images"]
    files = []
    for r in recs:
        src = coco_set.stage_photo(r, ctx.work / "in")
        run_dir = ctx.work / str(r["image_id"])
        run_dir.mkdir(parents=True, exist_ok=True)
        with _locked(ctx):
            ctx.backend.estimate(src, run_dir / "body3d.json")
        extras = cli._pose_extras(frames.load_meta(src), PARAMS["mirrored"], ctx.backend)
        canonical.write(run_dir / "body3d.json", run_dir, smooth=False, extras=extras)
        files += [f"{r['image_id']}/pose3d.json", f"{r['image_id']}/camera.json"]
    return {"files": files, "frames": len(recs), "people": len(recs)}


MULTI = ("part2.track", "part2.multi3d")
MODES = [
    Mode("single", "gpu", "fixtures/input/single/frames", run_single),
    Mode("class", "gpu", "fixtures/input/class/frames", run_multi, tracker="scored", modules=MULTI),
    Mode("class-local-open", "gpu", "fixtures/input/class/frames", run_multi, tracker="local-open", modules=MULTI),
    Mode("cpu-single", "cpu", "fixtures/input/single/frames", run_single),
    Mode("coco-single", "gpu", "fixtures/input/coco/images", run_coco, modules=("part2.coco_set",)),
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


def scored_dir(root: Path, flag=None) -> Path:
    """The flag, then PART2_SCORED_DIR, then fixtures/output/scored; relative paths are under root."""
    d = Path(flag or os.environ.get(SCORED_ENV) or DEFAULT_SCORED)
    return d if d.is_absolute() else root / d


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


def run_mode(mode: Mode, backend, root: Path, scored: Path, tracker_flag=None, lifter=None) -> dict:
    """Run one mode into a scratch dir, then replace scored/<mode>/ with its outputs and the stamp."""
    from part2 import frames, stamp

    frames_dir = root / mode.frames
    n_frames = len(frames.load(frames_dir)) if mode.tracker else 0  # coco-single has images.json, no frames.json
    tracker, skipped = pick_tracker(mode, tracker_flag, n_frames)
    pre = stamp.prepare(root, mode.name, backend.name, frames_dir, mode.modules,
                        tracker=tracker.name if tracker else None, lifter=lifter)
    work = root / WORK / mode.name
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    t0 = time.perf_counter()
    res = mode.run(Ctx(mode, root, work, backend, tracker, list(skipped)))
    seconds = round(time.perf_counter() - t0, 1)
    tprov = res.get("tracker_provenance") or {}
    models = list(backend.provenance().get("models", [])) + list(tprov.get("models", []))
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
            **facts}


def backend_for(name: str, lifter: str | None):
    """(backend, None) ready to run, or (None, refusal line) when it cannot run here."""
    from part2 import backends

    b = backends.get(name)
    if name == "cpu":
        b.lifter = lifter
        ok, why = b.available(lifter)
        return (b, None) if ok else (None, f"outputs: {backends.REFUSAL['cpu']} ({why})")
    ok, why = b.available()
    return (b, None) if ok else (None, f"{NO_CUDA}\noutputs: {why}")


def main(argv=None, root: Path = ROOT) -> int:
    from part2 import backends, lifters, trackers

    ap = argparse.ArgumentParser(prog="python -m part2.outputs", description="Regenerate the scored outputs.")
    ap.add_argument("--backend", default="gpu", help="gpu (single, class, class-local-open) or cpu (cpu-single)")
    ap.add_argument("--tracker", help="class mode only: a registry name instead of the scored order")
    ap.add_argument("--lifter", help="cpu backend: fixed-bones or motionbert (default: PART2_LIFTER, else DEFAULT)")
    ap.add_argument("--modes", help="comma-separated subset of the backend's modes")
    ap.add_argument("--scored", help=f"output root (default: {SCORED_ENV}, else {DEFAULT_SCORED})")
    a = ap.parse_args(argv)
    try:
        backends.resolve(a.backend)
        lifter = lifters.resolve(a.lifter) if a.backend == "cpu" else None
        if a.tracker:
            trackers.get(a.tracker)
        modes = modes_for(a.backend, [n for n in (a.modes or "").split(",") if n])
    except (backends.UnknownBackend, lifters.UnknownLifter, trackers.UnknownTracker, ValueError) as e:
        print(f"outputs: {e}", file=sys.stderr)
        return 2
    backend, refusal = backend_for(a.backend, lifter)
    if backend is None:
        print(refusal, file=sys.stderr)
        return 1
    scored, summary, failed = scored_dir(root, a.scored), {}, False
    for mode in modes:
        print(f"outputs: {mode.name} ({a.backend}) ...", file=sys.stderr, flush=True)
        try:
            summary[mode.name] = run_mode(mode, backend, root, scored, a.tracker, lifter)
        except (RuntimeError, ValueError, FileNotFoundError, OSError) as e:
            failed = True
            summary[mode.name] = {"error": f"{type(e).__name__}: {e}"}
            print(f"outputs: {mode.name}: {e}", file=sys.stderr)
    print(json.dumps(summary, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
