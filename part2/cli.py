"""part2 command line.

    part2 frames --input clip.mp4 --out out/clip/frames [--fps 30]
    part2 run --mode single|multi --input clip.mp4 --out out/clip [--fps 30] [--mirrored]
              [--backend gpu|cpu] [--lifter fixed-bones|motionbert] [--tracker NAME] [--tracker-order scored|bulk]
              [--refine RUNGS]   (single: the ladder's rungs, part2.refine; focal,kp2d-fit is what make outputs uses)
    part2 contract [--json] [--schema NAME]      (also: python -m part2 contract)
    part2 doctor FILE [--for part3|part5|part6] [--json]
    part2 stock [--clip pexels-<id>[-<start>to<end>s]] [--backend gpu|cpu]   (make stock-outputs)

With the gpu backend, `part2 run` holds the host GPU lock (part2.gpu_guard) around each 3D estimate and refine
re-run; a SAM tracker takes the same lock itself while it tracks, so the two are never nested (AC-B-NFR-03).
"""
import argparse
import contextlib
import json
import os
import sys
from pathlib import Path

from part2 import backends, canonical, contract, frames, provenance
from part2.schema import ContractError, write_json

# Keys of a backend's provenance() that block() takes as arguments rather than as extra keys.
_BLOCK_ARGS = ("backend", "tracker", "lifter", "refine", "models", "licence_notes", "kind")
_FALLBACK = ("fallback_from", "fallback_reason")


def _progress(stage: str, done: int, total: int) -> None:
    """`progress <stage> <done> <total>` on stdout when PART2_PROGRESS=1 (the staging job worker reads it)."""
    if os.environ.get("PART2_PROGRESS") == "1":
        print(f"progress {stage} {done} {total}", flush=True)


def _gpu_locked(backend):
    """The host GPU lock for a gpu backend's inference; nothing for the cpu backend."""
    if backend.name != "gpu":
        return contextlib.nullcontext()
    from part2 import gpu_guard

    return gpu_guard.gpu_lock()


def _pose_extras(meta: dict, mirrored: bool, backend, tracks_prov: dict | None = None, refine=()) -> dict:
    """The optional top-level keys of the pose3d.json this run writes: the time origin, the mirror flag and
    the provenance of what ran (the backend's models plus, in multi mode, the tracker that ran and any
    fallback; one-person mode runs no tracker; with refine rungs, the rungs and their models)."""
    bprov = backend.provenance()
    tprov = tracks_prov or {}
    models = [m for m in list(bprov.get("models", [])) + list(tprov.get("models", []))]
    extra = {k: v for k, v in bprov.items() if k not in _BLOCK_ARGS}
    extra.update({k: tprov[k] for k in _FALLBACK if tprov.get(k)})
    prov = provenance.block(backend.name, tprov.get("tracker"), bprov.get("lifter"), bprov.get("refine", ()),
                            models, kind="pose3d", licence_notes=bprov.get("licence_notes", ()), **extra)
    if refine:
        from part2 import refine as rungs

        prov = {**prov, "refine": list(refine), "models": list(prov.get("models", [])) + rungs.models(refine),
                "licence_notes": list(prov.get("licence_notes", [])) + rungs.licence_notes(refine)}
    return {"t0_pts_ms": meta.get("t0_pts_ms"), "mirrored": True if mirrored else None, "provenance": prov}


def _refine(rungs, doc: dict, frames_dir: Path, work_dir: Path, backend, model2d=None, lock=None) -> dict:
    """doc after the refine rungs (part2.refine.apply, ADR-0004), written to work_dir/body3d.json with the unrefined
    one kept as body3d-unrefined.json; doc itself when there are none. A rung that re-runs the 3D model does so
    under `lock` (a context manager factory; default: the host GPU lock for the gpu backend)."""
    if not rungs:
        return doc
    from part2 import refine

    (work_dir / "body3d-unrefined.json").write_text(json.dumps(doc))
    out = refine.apply(rungs, doc, frames_dir, model2d=model2d, backend=backend,
                       lock=lock or (lambda: _gpu_locked(backend)), work_dir=work_dir)
    (work_dir / "body3d.json").write_text(json.dumps(out))
    return out


def _tracks_extras(meta: dict, doc: dict, backend_name: str) -> dict:
    """The tracker's own provenance block (it names the tracker, its models and any fallback), stamped with
    the contract version and the backend this run uses (AC-C08), plus the time origin."""
    prov = {**(doc.get("provenance") or {}), "contract_version": contract.version("tracks"), "backend": backend_name}
    return {"t0_pts_ms": meta.get("t0_pts_ms"), "provenance": prov}


def _stamp_tracks(path: Path, doc: dict, extras: dict) -> None:
    """Add the optional keys to the tracks.json the tracker wrote, after checking it against the contract."""
    doc.update({k: v for k, v in extras.items() if v is not None})
    contract.validate(doc, "tracks")
    write_json(path, doc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="part2", description="Simon Part 2: video frames to 3D poses.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_frames = sub.add_parser("frames", help="extract numbered frames + frames.json from a video or image dir")
    p_frames.add_argument("--input", required=True, type=Path, help="video file or directory of images")
    p_frames.add_argument("--out", required=True, type=Path, help="output frames directory")
    p_frames.add_argument("--fps", type=float, help="resample video to this rate / timestamp an image dir")

    p_run = sub.add_parser("run", help="full pipeline: frames -> pose3d.json (+ tracks.json in multi mode)")
    p_run.add_argument("--mode", required=True, choices=["single", "multi"], help="one-person or class recording")
    p_run.add_argument("--input", required=True, type=Path, help="video file or directory of images")
    p_run.add_argument("--out", required=True, type=Path, help="output directory")
    p_run.add_argument("--fps", type=float, help="resample video to this rate / timestamp an image dir")
    p_run.add_argument("--smooth", action="store_true", help="One-Euro smoothing of 3D joints over time")
    p_run.add_argument("--mirrored", action="store_true",
                       help="the saved video is a mirror image of the scene (front camera): writes mirrored: true")
    p_run.add_argument("--backend", help="gpu or cpu (default: PART2_BACKEND, else gpu when CUDA is available, else cpu)")
    p_run.add_argument("--lifter", help="cpu backend: fixed-bones or motionbert (default: PART2_LIFTER, else fixed-bones)")
    p_run.add_argument("--tracker", help="multi: api-sam31, local-sam31, local-open or bytetrack "
                       "(default: PART2_TRACKER, else the tracker order)")
    p_run.add_argument("--tracker-order", choices=["scored", "bulk"], default="bulk",
                       help="multi: the order walked when no tracker is named (make outputs: scored)")
    p_run.add_argument("--refine", default="none",
                       help="single: comma-separated ladder rungs (part2.refine) run on the 3D before the canonical "
                       "frame; focal,kp2d-fit gives the scored outputs (make outputs); default none")

    p_ev = sub.add_parser("eval-reproj", help="one-person metric: reprojection error vs hand-clicked joints (#12)")
    p_ev.add_argument("--pose3d", required=True, type=Path)
    p_ev.add_argument("--camera", required=True, type=Path)
    p_ev.add_argument("--labels", required=True, type=Path, help="labels_2d.json")
    p_ev.add_argument("--rule", choices=["every_frame", "mean"], default="every_frame")
    p_ev.add_argument("--per-frame", action="store_true", help="include per-frame rows in the output")

    sub.add_parser("check", help="done-check: metrics JSON for both modes, exit 0 only if all pass (#14)")

    p_ct = sub.add_parser("contract", help="list the schemas Part 2 publishes and the compatibility table")
    p_ct.add_argument("--json", action="store_true", help='print {"schemas": [...], "compatibility": [...]}')
    p_ct.add_argument("--schema", help="print one schema file verbatim: pose3d, tracks, camera or frames")

    p_dr = sub.add_parser("doctor", help="name a file's kind and say what each consumer would reject and the fix")
    p_dr.add_argument("file", type=Path, help="a pose3d.json, tracks.json, camera.json or frames.json")
    p_dr.add_argument("--for", dest="consumer", help="part3 (default), part5 or part6")
    p_dr.add_argument("--json", action="store_true")

    p_an = sub.add_parser("annotate", help="label ground truth in the browser (#6)")
    p_an.add_argument("what", choices=["joints", "ids"], help="joints: 17 joints per frame; ids: person boxes + ids")
    p_an.add_argument("--frames", required=True, type=Path, help="frames dir (from part2 frames)")
    p_an.add_argument("--out", required=True, type=Path, help="labels_2d.json (joints) or gt_tracks.json (ids)")
    p_an.add_argument("--prefill", type=Path, help="body3d.json (joints) or tracks.json (ids) to start from")
    p_an.add_argument("--count", type=int, default=20, help="joints: frames to label, spread over the clip")
    p_an.add_argument("--every-s", type=float, default=1.0, help="ids: seconds between keyframes")
    p_an.add_argument("--port", type=int, default=8765)
    p_an.add_argument("--no-browser", action="store_true")

    p_demo = sub.add_parser("demo", help="viewer.html (rotatable 3D skeleton) or overlay.mp4 (#16)")
    p_demo.add_argument("what", choices=["viewer", "overlay"])
    p_demo.add_argument("--run", required=True, type=Path, help="part2 run output dir (frames/, pose3d.json, camera.json)")
    p_demo.add_argument("--id", help="viewer: person id to show (default: first)")
    p_demo.add_argument("--out", type=Path)
    p_demo.add_argument("--embed", action="store_true", help="viewer: inline the frames so the .html shares on its own")

    from part2 import stock

    p_st = sub.add_parser("stock", help="Pexels follower takes for Part 5 -> fixtures/output/stock/<take>/")
    p_st.add_argument("--clip", choices=list(stock.TAKES),
                      help="one take: a whole clip or a cut <clip>-<start>to<end>s (default: every take)")
    p_st.add_argument("--backend", choices=list(backends.CHOICES), help="default: PART2_BACKEND, else gpu when CUDA is available")

    args = parser.parse_args(argv)
    if args.command == "stock":
        return stock.command(args.clip, args.backend)
    if args.command == "demo":
        from part2 import demo

        path = demo.viewer(args.run, args.id, args.out, embed=args.embed) if args.what == "viewer" else demo.overlay(args.run, args.out)
        print(path)
        return 0
    if args.command == "check":
        from part2 import check

        report = check.run()
        print(json.dumps(report, indent=2))
        return 0 if report["pass"] else 1
    if args.command == "annotate":
        from part2 import annotate

        annotate.serve(args.what, args.frames, args.out, args.prefill, args.count, args.every_s, args.port,
                       open_browser=not args.no_browser)
        return 0
    if args.command == "eval-reproj":
        from part2 import eval_reproj

        m = eval_reproj.evaluate_files(args.pose3d, args.camera, args.labels, rule=args.rule)
        if not args.per_frame:
            m.pop("per_frame")
        print(json.dumps(m, indent=2))
        return 0 if m["pass"] else 1
    if args.command == "contract":
        return contract.command(args.json, args.schema)
    if args.command == "doctor":
        from part2 import doctor

        return doctor.command(args.file, args.consumer, args.json)
    try:
        if args.command == "frames":
            recs = frames.ingest(args.input, args.out, args.fps)
            print(f"{len(recs)} frames -> {args.out}")
            return 0
        from part2 import lifters, refine

        try:
            backend = backends.get(backends.resolve(args.backend))
            lifter = lifters.resolve(args.lifter)
            rungs = [] if args.refine.strip() in ("", "none") else refine.resolve(args.refine)
            if rungs and args.mode != "single":
                raise ValueError("--refine applies to --mode single only")
        except (backends.UnknownBackend, lifters.UnknownLifter, ValueError) as e:
            print(f"part2: {e}", file=sys.stderr)
            return 2
        if backend.name == "cpu":
            backend.lifter = lifter
        recs = frames.ingest(args.input, args.out / "frames", args.fps)
        _progress("frames", len(recs), len(recs))
        print(f"{len(recs)} frames -> {args.out / 'frames'}")
        meta = frames.load_meta(args.out / "frames")
        if args.mode == "single":
            _progress("pose", 0, len(recs))
            with _gpu_locked(backend):
                doc = backend.estimate(args.out / "frames", args.out / "body3d.json")
            if rungs:
                _refine(rungs, doc, args.out / "frames", args.out, backend, model2d=refine.load_2d(rungs))
                print(f"refined by {', '.join(rungs)} (unrefined kept as {args.out / 'body3d-unrefined.json'})")
            _progress("write", 0, 1)
            print(f"camera-space 3D ({backend.name}) -> {args.out / 'body3d.json'}")
            pose_path, cam_path = canonical.write(args.out / "body3d.json", args.out, smooth=args.smooth,
                                                  extras=_pose_extras(meta, args.mirrored, backend, refine=rungs))
            print(f"{pose_path} + {cam_path}")
            _progress("write", 1, 1)
            return 0
        if args.mode == "multi":
            from part2 import multi3d, track, trackers

            try:
                _progress("track", 0, len(recs))
                doc = track.track(args.out / "frames", args.out / "tracks.json", tracker=args.tracker,
                                  purpose=args.tracker_order)
            except trackers.UnknownTracker as e:
                print(f"part2: {e}", file=sys.stderr)
                return 2
            _stamp_tracks(args.out / "tracks.json", doc, _tracks_extras(meta, doc, backend.name))
            ids = {p["id"] for f in doc["frames"] for p in f["people"]}
            note = trackers.describe_fallback(doc["provenance"])
            print(f"{len(ids)} tracked people -> {args.out / 'tracks.json'} "
                  f"(tracker {doc['provenance'].get('tracker')}{'; ' + note if note else ''})")
            _progress("pose", 0, len(recs))
            with _gpu_locked(backend):  # after tracking: a SAM tracker took and dropped the same lock itself
                b3d = backend.estimate(args.out / "frames", args.out / "body3d.json", boxes=multi3d.tracks_to_boxes(doc))
            _progress("write", 0, 1)
            res = multi3d.write_pose_streams(b3d, args.out, smooth=args.smooth,
                                             extras=_pose_extras(meta, args.mirrored, backend, doc["provenance"]))
            print(f"pose3d for people {res['people']} -> {args.out / 'pose3d.json'} "
                  f"(+ pose3d_person_<id>.json each)")
            _progress("write", 1, 1)
            return 0
    except ContractError as e:
        print(f"part2: output breaks the contract at {e.path}: {e.msg}", file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"part2: {e}", file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled mode {args.mode}")


if __name__ == "__main__":
    sys.exit(main())
