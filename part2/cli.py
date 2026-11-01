"""part2 command line.

    part2 frames --input clip.mp4 --out out/clip/frames [--fps 30]
    part2 frame-times --input clip.mp4 [--fps 5] [--out frames.json]   (the sampled times only: what run keeps)
    part2 run --mode single|multi --input clip.mp4 --out out/clip [--fps 30] [--mirrored]
              [--backend gpu|cpu|cpu-sam3db] [--lifter bones-prior|fixed-bones|motionbert] [--tracker NAME]
              [--tracker-order scored|bulk]
              [--refine RUNGS]   (single: the ladder's rungs, part2.refine; focal,kp2d-fit is what make outputs uses)
              [--mesh [--mesh-vertices N]]   (also mesh3d.json + mesh3d.bin; gpu or cpu-sam3db; not with --refine)
    part2 run --mode multi ... [--tracks tracks.json] [--ids ID,ID]   (reuse tracks; 3D only for the listed ids)
    part2 track --input clip.mp4 --out out/clip [--fps 10] [--tracker NAME] [--tracker-order scored|bulk]
    part2 contract [--json] [--schema NAME]      (also: python -m part2 contract)
    part2 doctor FILE [--for part3|part5|part6] [--json]   (FILE: pose3d, tracks, camera, frames or mesh3d json)
    part2 stock [--clip pexels-<id>[-<start>to<end>s]] [--backend gpu|cpu|cpu-sam3db]   (make stock-outputs)

Exit codes of `run` and `track`: 0 written, 1 failed, 2 bad option, 4 no person found in any frame (the message is
unchanged; CONTRACT.md "Exit codes"). The warm worker returns the same code to its client. `run --mesh` that found
people but no mesh vertices keeps pose3d.json, writes no mesh pair and exits 1 (docs/specs/mesh3d.md, AC-M16).

With the gpu backend, `part2 run` holds the host GPU lock (part2.gpu_guard) around each 3D estimate and refine
re-run; a SAM tracker takes the same lock itself while it tracks, so the two are never nested (AC-B-NFR-03).
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

from part2 import backends, canonical, contract, frames, output_steps, provenance
from part2.schema import ContractError, write_json


def _progress(stage: str, done: int, total: int) -> None:
    """`progress <stage> <done> <total>` on stdout when PART2_PROGRESS=1 (the staging job worker reads it)."""
    if os.environ.get("PART2_PROGRESS") == "1":
        print(f"progress {stage} {done} {total}", flush=True)


def _parse_ids(text: str | None) -> list[str] | None:
    """The --ids list as strings (None when not given); an empty entry is a bad option."""
    if text is None:
        return None
    ids = [t.strip() for t in text.split(",")]
    if not all(ids):
        raise ValueError(f"--ids {text!r} has an empty id")
    return ids


def _tracked_ids(doc: dict) -> dict[str, object]:
    """{str(id): id} for every person in a tracks document."""
    return {str(p["id"]): p["id"] for f in doc["frames"] for p in f["people"]}


def _check_ids(doc: dict, ids: list[str]) -> None:
    """ValueError naming the first listed id that no person in the tracks document has (AC-P06)."""
    known = _tracked_ids(doc)
    for i in ids:
        if i not in known:
            raise ValueError(f"unknown person id {i} in --ids; tracks.json has {', '.join(sorted(known, key=str)) or 'nobody'}")


def _load_tracks(path: Path) -> dict:
    """The --tracks file as a tracks document that passes the contract. A file that cannot be read, is not JSON or
    breaks the tracks contract is an input error naming the file (ValueError), not a broken output (AC-P09)."""
    try:
        doc = json.loads(Path(path).read_text())
    except OSError as e:
        raise ValueError(f"--tracks {path} cannot be read ({e.strerror or e})") from None
    except ValueError as e:
        raise ValueError(f"--tracks {path} is not valid JSON ({e})") from None
    try:
        contract.validate(doc, "tracks")
    except ContractError as e:
        raise ValueError(f"--tracks {path} breaks the tracks contract at {e.path}: {e.msg}") from None
    return doc


def _given_tracks(path: Path | None, ids: list[str] | None) -> dict | None:
    """The --tracks document (None without --tracks), loaded and checked against --ids before any frame is
    ingested: a bad file or an unknown id costs no ingest."""
    if path is None:
        return None
    doc = _load_tracks(path)
    if ids is not None:
        _check_ids(doc, ids)
    return doc


def _check_same_frames(path: Path, doc: dict, recs: list[dict]) -> None:
    """ValueError unless the tracks cover exactly the frames of this input: a file made at another --fps or from
    another clip would pair its boxes with the wrong frames (AC-P07)."""
    have, want = {f["frame"] for f in doc["frames"]}, {r["frame"] for r in recs}
    sizes = f"it covers {len(have)} frames, this input has {len(want)}"
    hint = "was it made with the same --input and --fps?"
    if want - have:
        raise ValueError(f"--tracks {path} has no entry for frame {min(want - have)} of this input ({sizes}; {hint})")
    if have - want:
        raise ValueError(f"--tracks {path} has an entry for frame {min(have - want)} that this input lacks ({sizes}; {hint})")


API_TRACKER = "api-sam31"


def _bulk_order_unnamed(args) -> bool:
    """True when the order picks the tracker and it is `bulk`: no --tracker, no PART2_TRACKER, and no --tracker-order
    or --tracker-order bulk (track.track's default). A named tracker and the `scored` order fail closed."""
    from part2 import trackers

    named = args.tracker or os.environ.get(trackers.ENV, "").strip()
    return not named and args.tracker_order in (None, "bulk")


def _next_bulk_tracker(after: str, n_frames: int):
    """The first tracker of the bulk order after `after` that can run here (None when there is none): a step needs its
    key, budget and packages. `after` is api-sam31, which follows local-sam31 in the order, so local-sam31 and its
    parity pass (trackers.resolve) never come up here."""
    from part2 import trackers

    order = trackers.ORDERS["bulk"]
    for name in order[order.index(after) + 1:]:
        tracker = trackers.get(name)
        if tracker.available(n_frames)[0]:
            return tracker
    return None


# The statuses a refusal takes in the wordings of requests ("403 Client Error"), urllib ("HTTP Error 403") and the
# Meta client ("HTTP 403"). trackers.call_with_key maps only the last to CredentialRefused, and that module is
# stamped into the scored sets, so the CLI reads the rest from the TrackerError it receives.
_REFUSAL_WORDING = re.compile(r"\b(?:HTTP(?: Error)? (?:401|403)\b|(?:401|403) Client Error)")


def _api_refusal(err):
    """The CredentialRefused for `err` when api-sam31 failed with a 401 or 403 in any of those wordings, else None."""
    from part2 import trackers

    if isinstance(err, trackers.CredentialRefused):
        return err
    if str(err).startswith(f"tracker {API_TRACKER}:") and _REFUSAL_WORDING.search(str(err)):
        return trackers.CredentialRefused(API_TRACKER)
    return None


def _run_tracker(args, recs) -> dict:
    """track.track, except that the bulk order moves on from a refused Meta credential (HTTP 401 or 403).
    A refusal is not a skip reason of the registry (it fails the run), so the caller does the move: one stderr line,
    the next usable tracker of the order runs (api-sam31 is not tried again in this run), and its tracks.json says
    fallback_from api-sam31, fallback_reason credential_refused. A named tracker and the scored order still raise
    the refusal, and so does a bulk order with nothing left to run (docs/specs/tracker-registry.md, AC-R11)."""
    from part2 import track, trackers

    frames_dir, tracks_path = args.out / "frames", args.out / "tracks.json"
    order = {} if args.tracker_order is None else {"purpose": args.tracker_order}  # absent: track.track's default
    try:
        return track.track(frames_dir, tracks_path, tracker=args.tracker, **order)
    except trackers.TrackerError as err:
        refusal = _api_refusal(err)
        if refusal is None or not (_bulk_order_unnamed(args) and refusal.tracker == API_TRACKER):
            raise
        tracker = _next_bulk_tracker(API_TRACKER, len(recs))
        if tracker is None:
            raise
        print(f"part2: {refusal}; tracking with {tracker.name} instead", file=sys.stderr)
        return tracker.track(frames_dir, tracks_path, skipped=[(API_TRACKER, provenance.CREDENTIAL_REFUSED)])


def _track_stage(args, recs, meta, backend_name, reuse: dict | None = None) -> dict:
    """Track the frames (or reuse the --tracks document `reuse`), write out/tracks.json and return the document.
    Raises trackers.UnknownTracker for a bad tracker name."""
    tracks_path = args.out / "tracks.json"
    if reuse is not None:  # reuse: no tracker runs, ids are kept as given (TICKET-041)
        _check_same_frames(args.tracks, reuse, recs)
        write_json(tracks_path, reuse)
        print(f"{len(_tracked_ids(reuse))} tracked people reused from {args.tracks} (no tracking run)")
        return reuse
    _progress("track", 0, len(recs))
    doc = _run_tracker(args, recs)
    output_steps.stamp_tracks(tracks_path, doc, output_steps.tracks_extras(meta, doc, backend_name))
    note = provenance.fallback_note(doc["provenance"])
    print(f"{len(_tracked_ids(doc))} tracked people -> {tracks_path} "
          f"(tracker {doc['provenance'].get('tracker')}{'; ' + note if note else ''})")
    return doc


def _pick_boxes(doc: dict, ids: list[str] | None) -> dict:
    """The 3D boxes of the listed ids only (all people without --ids). An unknown id is a ValueError naming it."""
    from part2 import multi3d

    if ids is None:
        return multi3d.tracks_to_boxes(doc)
    _check_ids(doc, ids)
    keep = set(ids)
    return multi3d.tracks_to_boxes({**doc, "frames": [
        {**f, "people": [p for p in f["people"] if str(p["id"]) in keep]} for f in doc["frames"]]})


class _Parser(argparse.ArgumentParser):
    """No option abbreviations: the warm worker forwards argv by exact option names (worker.strip_worker), so
    `--work` must be an argparse error, not a second spelling of --worker that the worker would send to itself."""

    def __init__(self, **kwargs):
        super().__init__(allow_abbrev=False, **kwargs)


def _input_parent(out_help: str) -> argparse.ArgumentParser:
    """The three arguments `frames`, `run` and `track` share (--input, --out, --fps), declared once and passed as
    `parents=`; only the help of --out differs by command."""
    p = _Parser(add_help=False)
    p.add_argument("--input", required=True, type=Path, help="video file or directory of images")
    p.add_argument("--out", required=True, type=Path, help=out_help)
    p.add_argument("--fps", type=float, help="resample video to this rate / timestamp an image dir")
    return p


def _tracking_parent(out_help: str, multi_only: bool) -> argparse.ArgumentParser:
    """The arguments `run` and `track` share: those of `_input_parent` plus --tracker and --tracker-order. `run`
    applies the tracker options to --mode multi only, which its help says. --tracker-order has no argparse default
    (None): `run --tracks` must tell a given option from an absent one (AC-P08); `track.track` supplies "bulk"."""
    scope = "multi: " if multi_only else ""
    p = _Parser(add_help=False, parents=[_input_parent(out_help)])
    p.add_argument("--tracker", help=f"{scope}api-sam31, local-sam31, local-open or bytetrack "
                   "(default: PART2_TRACKER, else the tracker order)")
    p.add_argument("--tracker-order", choices=["scored", "bulk"],
                   help=f"{scope}the order walked when no tracker is named" + (" (make outputs: scored)" if multi_only else ""))
    return p


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="part2", description="Simon Part 2: video frames to 3D poses.")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    sub.add_parser("frames", help="extract numbered frames + frames.json from a video or image dir",
                   parents=[_input_parent("output frames directory")])

    p_ft = sub.add_parser("frame-times", help="print or write the frames.json that run samples for a video and fps",
                          description="The frames.json document `run` and `track` use for this video and --fps: the "
                          "same ffprobe timestamps and sampling rule, without writing images.")
    p_ft.add_argument("--input", required=True, type=Path, help="video file")
    p_ft.add_argument("--fps", type=float, help="sample rate (default: every decoded frame)")
    p_ft.add_argument("--out", type=Path, help="write the document here (default: print it)")

    p_run = sub.add_parser("run", help="full pipeline: frames -> pose3d.json (+ tracks.json in multi mode)",
                           parents=[_tracking_parent("output directory", multi_only=True)])
    p_run.add_argument("--mode", required=True, choices=["single", "multi"], help="one-person or class recording")
    p_run.add_argument("--smooth", action="store_true", help="One-Euro smoothing of 3D joints over time")
    p_run.add_argument("--mirrored", action="store_true",
                       help="the saved video is a mirror image of the scene (front camera): writes mirrored: true")
    p_run.add_argument("--backend", help="gpu, cpu (RTMPose-x, 3D approximate) or cpu-sam3db (SAM 3D Body on the CPU, "
                       "gpu-cu128 profile, meets the 3D bar at 31.74 to 46.95 s per frame on 8 threads in two runs; chosen by name only) "
                       "(default: PART2_BACKEND, else gpu when CUDA is available, else cpu)")
    p_run.add_argument("--lifter", help="cpu backend: bones-prior, fixed-bones or motionbert (default: PART2_LIFTER, else "
                       "bones-prior, the lowest mean joint distance of the three, none passes the 3D bar)")
    p_run.add_argument("--refine", default="none",
                       help="single: comma-separated ladder rungs (part2.refine) run on the 3D before the canonical "
                       "frame; focal,kp2d-fit gives the scored outputs (make outputs); default none")
    p_run.add_argument("--worker", type=Path, help="socket of a running `part2 serve-worker`; used when it is up, "
                       "else this process runs the job itself")
    p_run.add_argument("--mesh", action="store_true",
                       help="also write mesh3d.json + mesh3d.bin, the decimated SAM 3D Body mesh per person per frame "
                            "(gpu or cpu-sam3db backend; not with --refine; docs/specs/mesh3d.md)")
    p_run.add_argument("--mesh-vertices", type=int, default=None,
                       help="--mesh: about this many vertices per body (default 2500)")
    p_run.add_argument("--tracks", type=Path, help="multi: reuse this tracks.json (no tracking run, ids unchanged)")
    p_run.add_argument("--ids", help="multi: comma-separated person ids; 3D runs for these people only")

    p_tr = sub.add_parser("track", help="frames + tracks.json only, no 3D (Part 7 people picker)",
                          parents=[_tracking_parent("output directory (frames/ and tracks.json)", multi_only=False)])
    p_tr.add_argument("--worker", type=Path, help="socket of a running `part2 serve-worker` (in-process when down)")

    p_sw = sub.add_parser("serve-worker", help="keep the models loaded and serve run and track requests on a socket")
    p_sw.add_argument("--socket", required=True, type=Path, help="Unix socket path to listen on")
    p_sw.add_argument("--backend", help="gpu, cpu or cpu-sam3db (default as for run)")
    p_sw.add_argument("--mode", choices=["3d", "track"], default="3d",
                      help="3d (default): keep the 3D backend warm, serve run and track; track: keep SAM 3.1 warm in "
                           "this separate process and serve track --tracker local-sam31 only (docs/specs/warm-track.md)")

    p_ev = sub.add_parser("eval-reproj", help="one-person metric: reprojection error vs hand-clicked joints (#12)")
    p_ev.add_argument("--pose3d", required=True, type=Path)
    p_ev.add_argument("--camera", required=True, type=Path)
    p_ev.add_argument("--labels", required=True, type=Path, help="labels_2d.json")
    p_ev.add_argument("--rule", choices=["every_frame", "mean"], default="every_frame")
    p_ev.add_argument("--per-frame", action="store_true", help="include per-frame rows in the output")

    sub.add_parser("check", help="done-check: metrics JSON for both modes, exit 0 only if all pass (#14)")

    p_ct = sub.add_parser("contract", help="list the schemas Part 2 publishes and the compatibility table")
    p_ct.add_argument("--json", action="store_true", help='print {"schemas": [...], "compatibility": [...]}')
    p_ct.add_argument("--schema", help="print one schema file verbatim: pose3d, tracks, camera, frames or mesh3d")

    p_dr = sub.add_parser("doctor", help="name a file's kind and say what each consumer would reject and the fix")
    p_dr.add_argument("file", type=Path, help="a pose3d.json, tracks.json, camera.json, frames.json or mesh3d.json "
                      "(its mesh3d.bin is checked with it)")
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

    return parser


MESH_REFINE_REFUSAL = "--mesh cannot be combined with --refine (the mesh comes from the unrefined run)"
MESH_EMPTY = "--mesh found no mesh vertices; no mesh3d pair written"


def _mesh_collector(args, backend_name: str, rungs: list) -> dict:
    """{"mesh": Collector} for backend.estimate when --mesh is set, else {} (the call is then unchanged). Every refusal
    is a ValueError raised before anything is removed or written; the collector is built (and its vertex count
    checked) here for that reason."""
    from part2 import mesh3d

    if args.mesh_vertices is not None and not args.mesh:
        raise ValueError("--mesh-vertices applies to --mesh only")
    if not args.mesh:
        return {}
    if backend_name not in mesh3d.BACKENDS:
        raise ValueError(mesh3d.REFUSAL)
    if rungs:  # the focal rung re-runs the model without the collector, so the mesh would be from another run
        raise ValueError(MESH_REFINE_REFUSAL)
    return {"mesh": mesh3d.Collector(mesh3d.DEFAULT_TARGET if args.mesh_vertices is None else args.mesh_vertices)}


def _clear_mesh(out: Path) -> None:
    """Remove a mesh pair an earlier run left in --out, so it is never read as this run's (TICKET-048). Called once
    the backend, lifter, --refine and --mesh options and the --tracks file (with --ids) have been accepted, and before
    frames.ingest reads --input. A failure after that point can follow the removal: an --input that cannot be read
    exits 1, and an unknown --tracker name, which the tracker stage checks once the frames are ingested, exits 2."""
    from part2 import mesh3d

    for name in (mesh3d.JSON_NAME, mesh3d.BIN_NAME):
        (out / name).unlink(missing_ok=True)


def _write_mesh(mesh: dict, out: Path) -> bool:
    """Write the pair the collector holds. False (one stderr line, nothing written) when --mesh was given and the run
    found people but no mesh vertices: every person had hips that give no canonical frame."""
    if not mesh:
        return True
    written = mesh["mesh"].write(out)
    if written is None:
        print(f"part2: {MESH_EMPTY}", file=sys.stderr)
        return False
    c = mesh["mesh"]
    print(f"mesh ({c.plan.count} of {c.source_vertex_count} vertices, {len(c.blocks)} person-frames) -> "
          f"{written[0]} + {written[1]}")
    return True


def _serve_worker(args) -> int:
    """`part2 serve-worker`: an unknown backend is exit 2 like `run --backend`, and so is --backend with --mode track
    (that worker loads no 3D model); a failed preload or socket falls to main's handler (a `part2: ...` line, exit 1)."""
    from part2 import worker

    if args.mode == "track" and args.backend is not None:
        print("part2: --backend applies to --mode 3d; the track worker loads no 3D model", file=sys.stderr)
        return 2
    try:
        if args.mode == "track":
            worker.serve(str(args.socket), mode="track")
        else:
            worker.serve(str(args.socket), args.backend)
    except backends.UnknownBackend as e:
        print(f"part2: {e}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if getattr(args, "worker", None) is not None:
        from part2 import worker

        code = worker.forward(str(args.worker), worker.strip_worker(list(sys.argv[1:] if argv is None else argv))[0])
        if code is not None:
            return code
        print(f"part2: no worker at {args.worker}; running in this process", file=sys.stderr)
    if args.command == "stock":
        from part2 import stock

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
        if args.command == "serve-worker":
            return _serve_worker(args)
        if args.command == "frame-times":
            from part2 import frame_times

            return frame_times.command(args.input, args.fps, args.out)
        if args.command == "frames":
            recs = frames.ingest(args.input, args.out, args.fps)
            print(f"{len(recs)} frames -> {args.out}")
            return 0
        if args.command == "track":
            from part2 import trackers

            recs = frames.ingest(args.input, args.out / "frames", args.fps)
            _progress("frames", len(recs), len(recs))
            print(f"{len(recs)} frames -> {args.out / 'frames'}")
            try:
                _track_stage(args, recs, frames.load_meta(args.out / "frames"), None)
            except trackers.UnknownTracker as e:
                print(f"part2: {e}", file=sys.stderr)
                return 2
            return 0
        from part2 import lifters, refine

        try:
            ids = _parse_ids(args.ids)
            if (args.tracks is not None or ids is not None) and args.mode != "multi":
                raise ValueError("--tracks and --ids apply to --mode multi only")
            given = [o for o, v in (("--tracker", args.tracker), ("--tracker-order", args.tracker_order)) if v is not None]
            if args.tracks is not None and given:  # AC-P08: the tracks file already fixed the tracker
                raise ValueError(f"{' and '.join(given)} cannot be combined with --tracks (the tracks file already fixed the tracker)")
            backend = backends.get(backends.resolve(args.backend))
            lifter = lifters.resolve(args.lifter)
            rungs = [] if args.refine.strip() in ("", "none") else refine.resolve(args.refine)
            if rungs and args.mode != "single":
                raise ValueError("--refine applies to --mode single only")
            mesh = _mesh_collector(args, backend.name, rungs)
        except (backends.UnknownBackend, lifters.UnknownLifter, ValueError) as e:
            print(f"part2: {e}", file=sys.stderr)
            return 2
        if backend.name == "cpu":
            backend.lifter = lifter
        reuse = _given_tracks(args.tracks, ids)  # before the ingest: a bad file or an unknown id costs nothing
        _clear_mesh(args.out)
        recs = frames.ingest(args.input, args.out / "frames", args.fps)
        _progress("frames", len(recs), len(recs))
        print(f"{len(recs)} frames -> {args.out / 'frames'}")
        meta = frames.load_meta(args.out / "frames")
        if args.mode == "single":
            _progress("pose", 0, len(recs))
            with output_steps.gpu_locked(backend):
                doc = backend.estimate(args.out / "frames", args.out / "body3d.json", **mesh)
            if rungs:
                output_steps.refine(rungs, doc, args.out / "frames", args.out, backend, model2d=refine.load_2d(rungs))
                print(f"refined by {', '.join(rungs)} (unrefined kept as {args.out / 'body3d-unrefined.json'})")
            _progress("write", 0, 1)
            print(f"camera-space 3D ({backend.name}) -> {args.out / 'body3d.json'}")
            pose_path, cam_path = canonical.write(args.out / "body3d.json", args.out, smooth=args.smooth,
                                                  extras=output_steps.pose_extras(meta, args.mirrored, backend, refine=rungs))
            print(f"{pose_path} + {cam_path}")
            if not _write_mesh(mesh, args.out):
                return 1
            _progress("write", 1, 1)
            return 0
        if args.mode == "multi":
            from part2 import multi3d, trackers

            try:
                doc = _track_stage(args, recs, meta, backend.name, reuse)
            except trackers.UnknownTracker as e:
                print(f"part2: {e}", file=sys.stderr)
                return 2
            boxes = _pick_boxes(doc, ids)
            _progress("pose", 0, len(recs))
            with output_steps.gpu_locked(backend):  # after tracking: a SAM tracker took and dropped the same lock itself
                b3d = backend.estimate(args.out / "frames", args.out / "body3d.json", boxes=boxes, **mesh)
            _progress("write", 0, 1)
            res = multi3d.write_pose_streams(b3d, args.out, smooth=args.smooth,
                                             extras=output_steps.pose_extras(meta, args.mirrored, backend, doc.get("provenance")))
            print(f"pose3d for people {res['people']} -> {args.out / 'pose3d.json'} "
                  f"(+ pose3d_person_<id>.json each)")
            if not _write_mesh(mesh, args.out):
                return 1
            _progress("write", 1, 1)
            return 0
    except ContractError as e:
        print(f"part2: output breaks the contract at {e.path}: {e.msg}", file=sys.stderr)
        return 1
    except backends.NoPersonFound as e:  # before RuntimeError, which it is: nobody found is exit 4, not a failure
        print(f"part2: {e}", file=sys.stderr)
        return e.exit_code
    except (OSError, ValueError, RuntimeError) as e:
        print(f"part2: {e}", file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled mode {args.mode}")


if __name__ == "__main__":
    sys.exit(main())
