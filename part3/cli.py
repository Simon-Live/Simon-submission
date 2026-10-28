"""Pipeline wiring (spec "Pipeline") and the `python3 -m part3` command line.

`process` and `process_all` are the Python API: a pose3d dict in, native skeleton dicts out, no file
I/O. `main` adds the views, the files and the exit codes (docs/specs/integration-contract.md).
"""

import argparse
import dataclasses
import errno
import hashlib
import importlib
import json
import os
import re
import sys

import numpy as np

from part3 import adapters, bones, facing, flips, io, mirror, people, profiles, resample, schema, standard
from part3 import person as person_step
from part3 import temporal, views
from part3.joints import BONES, GROUP_ORDER, JOINTS
from part3.schema import ContractError, FrameRateError, OptionError

DELEGATED = {"contract": "print the published schemas and the compatibility table",
             "doctor": "check a file against the contract and say which neighbour would reject it"}


class NoUsableFrames(ContractError):
    """The chosen person has no frame the pipeline can use (hips coincide or no hip line)."""


def _rounded(values):
    """Round to the output decimals and write -0.0 as 0.0."""
    return io.round_clean(values, io.OUTPUT_DECIMALS)


def _bone_block():
    return [{"name": name, "from": start, "to": end} for name, start, end in BONES]


def _rounded_lengths(lengths):
    return dict(zip(lengths, _rounded(np.array(list(lengths.values()))).tolist()))


def _joints_entry(coords, conf):
    return {name: {"x": coords[j][0], "y": coords[j][1], "z": coords[j][2], "conf": conf[j]}
            for j, name in enumerate(JOINTS)}


def _output_frames(slots, pid, coords, conf, repaired):
    """One frame per slot (frame, t_ms, row or None, source or None): the person at `row`, else nobody."""
    coords, conf = coords.tolist(), conf.tolist()
    out = []
    for frame, t_ms, row, source in slots:
        held = [] if row is None else [{"id": pid, "joints": _joints_entry(coords[row], conf[row]),
                                         "flips_repaired": repaired[row]}]
        out.append({"frame": frame, "t_ms": t_ms, "people": held, **({} if source is None else {"source": source})})
    return out


def _same_frames(frames, indices):
    """Slots for every input frame again: the person's row where `indices` says so."""
    row_of = {int(i): k for k, i in enumerate(indices)}
    return [(frame["frame"], frame["t_ms"], row_of.get(i), None) for i, frame in enumerate(frames)]


def _rebuild(n_frames, indices, framed, lengths, window=temporal.WINDOW):
    """Step 5b then step 6 (unrounded): filter inside runs of present frames over `window` frames
    (temporal.window_for), retarget to `lengths`."""
    present = np.zeros(n_frames, dtype=bool)
    present[indices] = True
    body = np.zeros((n_frames, len(JOINTS), 3))
    body[indices] = framed
    return bones.retarget(temporal.smooth(body, present, window)[indices], lengths)


def _select_person(doc, requested=None):
    """Steps 2 and the hip check: (chosen id, candidates, frame indices, J, conf, frames_dropped)."""
    frames = doc["frames"]
    if not frames:
        raise ContractError("pose3d.frames", "empty: the clip has no frames")
    chosen, candidates = person_step.choose(frames, requested)
    if chosen is None:
        raise ContractError("pose3d.frames", "no person in any frame")
    indices, J, conf = person_step.extract(frames, chosen)
    apart = person_step.hips_apart(J)
    if not apart.any():
        raise NoUsableFrames("pose3d.frames", "the chosen person has no usable frame (the hips coincide)")
    return chosen, candidates, np.array(indices)[apart], J[apart], conf[apart], int((~apart).sum())


def _person_block(chosen, requested, candidates, indices, dropped, measured, repaired):
    totals = {g: sum(g in r for r in repaired) for g in GROUP_ORDER}
    rule = {"rule": person_step.RULE} if requested is None else {"rule": person_step.RULE_REQUESTED,
                                                                 "requested": chosen}
    return {"id": chosen, **rule, "candidates": candidates, "frames_present": len(indices),
            "frames_dropped": dropped, "few_frames": len(indices) < schema.FEW_FRAMES_BELOW,
            "measured_bone_lengths_m": measured, "flips_repaired_total": totals}


@dataclasses.dataclass(frozen=True)
class Job:
    """One input made ready for the pipeline: adapted and validated, with the options that apply to it."""

    doc: dict
    adapters: list
    digest: str
    flip: str
    selection: profiles.Selection
    fps: object
    max_frames: object = None


def _job(doc, flip, sha256, body, stature, fps, input_fps, env, config, max_frames=None):
    if flip not in mirror.FLIP_VALUES:
        raise ValueError(f"flip must be one of {', '.join(mirror.FLIP_VALUES)} (got {flip!r})")
    fps = None if fps is None else resample.check_fps(fps)
    selection = body if isinstance(body, profiles.Selection) else profiles.resolve(
        api=body, stature_api=stature, env=env, config=config)
    adapted, names = adapters.adapt(doc, input_fps)
    schema.validate_pose3d(adapted)
    if fps is not None and adapted["frames"]:  # before any work: the grid grows with the time span, not the upload
        resample.check_grid([frame["t_ms"] for frame in adapted["frames"]], fps, max_frames)
    digest = sha256 or hashlib.sha256(json.dumps(doc, ensure_ascii=False).encode()).hexdigest()
    return Job(adapted, names, digest, flip, selection, fps, max_frames)


def _frames_for(job, indices, rebuilt, conf, repaired, lengths):
    """(slots, coords, conf, repaired) on the input's own frames or, with --fps, on the uniform grid."""
    frames = job.doc["frames"]
    if job.fps is None:
        return _same_frames(frames, indices), _rounded(rebuilt), conf, repaired
    times = [frame["t_ms"] for frame in frames]
    slots, coords, conf, repaired = resample.resample(times, [frame["frame"] for frame in frames], indices,
                                                      rebuilt, conf, repaired, lengths, job.fps, job.max_frames)
    if not len(coords):
        raise FrameRateError("--fps", "no output frame holds the person; use a higher --fps")
    return slots, coords, conf, repaired


def _single(job, requested=None, trace=None):
    """The native skeleton of one person of `job` (not yet validated as a whole)."""
    doc = job.doc
    chosen, candidates, indices, J, conf, dropped = _select_person(doc, requested)
    applied, reason = mirror.decide(job.flip, doc)
    if applied:
        J, conf = mirror.apply(J, conf)
    J, conf, repaired = flips.repair(J, conf)
    framed, valid, up, up_source = facing.body_frame(J)
    if trace is not None:
        trace["up_in_input"] = [float(v) for v in up]
        trace["up_source"] = up_source
    if not valid.any():
        raise NoUsableFrames("pose3d.frames", "the chosen person has no usable frame (no hip line)")
    dropped += int((~valid).sum())
    indices, J, conf, framed = indices[valid], J[valid], conf[valid], framed[valid]
    repaired = [r for r, ok in zip(repaired, valid) if ok]
    measured = _rounded_lengths(standard.measured_bone_lengths(J, conf))
    body = profiles.lengths_for(job.selection, measured)
    lengths = bones.lengths_array(body.bone_lengths_m)
    window = temporal.window_for([f.get("t_ms") for f in doc["frames"]])
    rebuilt = _rebuild(len(doc["frames"]), indices, framed, lengths, window)
    slots, coords, out_conf, out_repaired = _frames_for(job, indices, rebuilt, conf, repaired, lengths)
    frames = _output_frames(slots, chosen, coords, out_conf, out_repaired)
    skeleton = {
        "schema": schema.SCHEMA_ID,
        "units": dict(schema.UNITS),
        "frame": {**schema.FRAME_BLOCK, "up_source": up_source},
        "joints": list(JOINTS),
        "bones": _bone_block(),
        "standard": {"stature_m": body.stature_m, "sources": body.sources},
        "bone_lengths_m": body.bone_lengths_m,
        "body": body.block(),
        "person": _person_block(chosen, requested, candidates, indices, dropped, measured, repaired),
        "mirror": {"setting": job.flip, "applied": applied, "reason": reason},
        "input": {"sha256": job.digest, "adapters": job.adapters},
    }
    if job.fps is not None:
        skeleton["resample"] = resample.block(job.fps, len(doc["frames"]))
    skeleton["frames"] = frames
    return skeleton


def process(doc, flip="auto", sha256=None, trace=None, *, body=None, stature=None, person=None,
            fps=None, input_fps=None, env=None, config=None, max_frames=None):
    """A pose3d dict in, a skeleton.json dict out (no file I/O).

    `sha256` is the hex SHA-256 recorded in `input.sha256`. A caller that read the input from a file
    passes the hash of the file's bytes (as `main` does). Without it the hash is taken over a
    `json.dumps` re-serialisation of `doc`, which is stable for a given dict but is in general not
    the hash of the file's bytes.

    `body` is a `profiles.Selection` (used as is) or the name of a profile (the API channel, lowest
    in the precedence of docs/specs/integration-contract.md); `stature` is the API stature in metres.
    `person` keeps that id instead of the id in the most frames. `fps` resamples onto a uniform grid
    and `input_fps` gives the frame rate when the input has no `t_ms`. `env` (None: `os.environ`) and
    `config` (None: discover `PART3_CONFIG` and `./part3.toml`; False: no file; a path: that file) feed
    the profile channels. `max_frames` caps the frames `fps` may write (None: `resample.MAX_FRAMES`).
    `doc` is never modified.

    Raises ContractError for an invalid input or option, an empty clip and a clip without a person; its subclass
    FrameCapError for an `fps` grid over `max_frames` and FrameRateError for a clip that `fps` cannot resample (times
    that do not increase, or no output frame holding the person). Raises ValueError for a `flip` value other than
    auto, on or off. When `trace` is a dict it receives `up_in_input` (the clip body up in the label-repaired input
    coordinates) and `up_source`.
    """
    job = _job(doc, flip, sha256, body, stature, fps, input_fps, env, config, max_frames)
    skeleton = _single(job, person, trace)
    schema.validate_skeleton(skeleton)
    return skeleton


def process_all(doc, flip="auto", sha256=None, trace=None, *, body=None, stature=None, person=None,
                fps=None, input_fps=None, env=None, config=None, max_frames=None):
    """[(id, skeleton)] for every person id of `doc`, in first-seen id order.

    An id whose frames all fail the hip check comes back as (id, {"skipped": reason}). The other
    arguments are those of `process` (`person` is refused: it contradicts asking for everyone);
    `trace` receives the values of the first id that was processed.
    """
    if person is not None:
        raise ContractError("--person", "cannot be combined with --all-people")
    job = _job(doc, flip, sha256, body, stature, fps, input_fps, env, config, max_frames)
    results = []
    for pid in person_step.ids(job.doc["frames"]):
        scratch = {}
        try:
            skeleton = _single(job, pid, scratch)
        except NoUsableFrames as error:
            results.append((pid, {"skipped": error.msg}))
            continue
        schema.validate_skeleton(skeleton)
        results.append((pid, skeleton))
        if trace is not None and not trace:
            trace.update(scratch)
    return results


# --- command line -------------------------------------------------------------------------------

def _parser():
    parser = argparse.ArgumentParser(prog="python3 -m part3")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="pose3d.json in, skeleton.json out", allow_abbrev=False)
    run.add_argument("--in", dest="source", required=True, help="path of pose3d.json")
    run.add_argument("--out", dest="target", required=True,
                     help="path of skeleton.json to write (a directory with --all-people)")
    run.add_argument("--flip", choices=mirror.FLIP_VALUES, default="auto",
                     help="mirror correction for selfie recordings (default auto)")
    run.add_argument("--body", help="simon-standard, part4-rig, measured or file:<path> (default: part4-rig for "
                                     "--view part4, else simon-standard)")
    run.add_argument("--stature", help="scale the body to this stature in metres (0.5 to 2.5)")
    run.add_argument("--config", help="a part3.toml (default: PART3_CONFIG, then ./part3.toml)")
    run.add_argument("--view", default="native", help="native (default), part4 or part5")
    run.add_argument("--keyframes", help="keyframes.json of Part 1 or Part 4, or every:<n> (--view part4)")
    run.add_argument("--keyframes-person", help="the person of a Part 1 keyframes file (default: the first)")
    run.add_argument("--keyframes-out", help="also write the simon.keyframes.v1 file here (--view part4)")
    run.add_argument("--fps", help="resample onto a uniform grid of this many frames per second (1 to 240)")
    run.add_argument("--input-fps", help="frame rate of an input without t_ms")
    who = run.add_mutually_exclusive_group()
    who.add_argument("--person", help="keep this person id instead of the one in the most frames")
    who.add_argument("--all-people", action="store_true", help="write one skeleton per person id into --out")
    for name, text in DELEGATED.items():
        sub.add_parser(name, help=text, add_help=False)
    return parser


def _load_input(path):
    """(document, sha256, error message) of an input file; the message is None when it was read."""
    try:
        doc, digest = io.read_json(path)
    except OSError as error:
        return None, None, f"{path}: cannot read ({error.strerror or error})"
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        return None, None, f"{path}: not valid JSON ({error})"
    return doc, digest, None


def _id_arg(text):
    """A command-line person id: digits make an integer id, anything else a string id."""
    return None if text is None else int(text) if re.fullmatch(r"[0-9]+", text) else text


def _keyframes_options(args):
    return {"keyframes": args.keyframes, "keyframes_person": _id_arg(args.keyframes_person)}


def _render_one(args):
    """The function that makes {file name: document} of one native skeleton for the chosen view."""
    def render(skeleton):
        rendered = views.render(skeleton, args.view, **_keyframes_options(args))
        files = {people.SKELETON_FILE: rendered}
        companion = views.keyframes_doc(rendered)
        if companion is not None:
            files["keyframes.json"] = companion
        return files
    return render


def _process_options(args, digest, selection):
    return {"flip": args.flip, "sha256": digest, "body": selection, "fps": args.fps,
            "input_fps": args.input_fps}


def _documents(doc, digest, args, selection):
    """[(path, document)] to write for the command line `args`; raises ContractError before anything exists."""
    options = _process_options(args, digest, selection)
    render = _render_one(args)
    if args.all_people:
        return [(os.path.join(args.target, name), document)
                for name, document in people.layout(process_all(doc, **options), render)]
    skeleton = process(doc, person=_id_arg(args.person), **options)
    files = render(skeleton)
    out = [(args.target, files[people.SKELETON_FILE])]
    if args.keyframes_out:
        out.append((args.keyframes_out, files["keyframes.json"]))
    return out


def _check_options(args):
    """Raise ContractError for option combinations that make no sense, before any file is read."""
    if args.keyframes_out and args.all_people:
        raise ContractError("--keyframes-out", "not used with --all-people (keyframes.json is written "
                                               "beside each skeleton)")
    if args.keyframes_out and args.view != "part4":
        raise ContractError("--keyframes-out", "only applies to --view part4")
    if args.keyframes_out and _same_file(args.keyframes_out, args.target):
        raise OptionError("--keyframes-out", "must differ from --out")  # one file cannot hold both documents


def _same_file(first, second):
    """True when two paths name one file: the same real path, or one file on disk under two names."""
    if os.path.realpath(first) == os.path.realpath(second):
        return True
    try:
        return os.path.samefile(first, second)
    except OSError:  # one of them does not exist yet
        return False


def _write(files, source, mkdir):
    """Write every (path, document), creating folders when `mkdir`.

    Returns the exit code: 0 written, 2 when an id cannot be encoded (nothing written), 1 when a path
    is not writable. Each file goes to a temporary name beside its target first and is renamed once
    all of them are complete, so a failure of any one leaves none of this call's files behind
    (`--keyframes-out` failing cannot leave `skeleton.json`).
    """
    texts = [(path, io.dumps(document)) for path, document in files]
    try:
        for _, text in texts:
            text.encode("utf-8")
    except UnicodeEncodeError:
        print(f"{source}: pose3d.frames: an id cannot be written as UTF-8", file=sys.stderr)
        return 2
    staged, placed, current = [], [], None  # (temp, target) pairs; targets this call created; the file in hand
    try:
        for path, text in texts:
            current = path
            _check_writable(path)
            staged.append((_temp_name(path), path))
            io.write_text(staged[-1][0], text, mkdir=mkdir)
        for temp, path in staged:  # every file is complete on disk before the first one appears under its name
            current = path
            existed = os.path.lexists(path)
            os.replace(temp, path)
            placed += [] if existed else [path]
    except OSError as error:
        _remove([temp for temp, _ in staged] + placed)
        print(f"{current}: cannot write ({error.strerror or error})", file=sys.stderr)
        return 1
    return 0


def _check_writable(path):
    """PermissionError for an existing file the user cannot write: a rename over it would not notice."""
    if os.path.lexists(path) and not os.access(path, os.W_OK):
        raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(path))


def _temp_name(path):
    """A name beside `path` (same folder, so the rename stays on one disk) that no run mistakes for output."""
    folder, name = os.path.split(path)
    return os.path.join(folder, f".{name}.{os.getpid()}.part3tmp")


def _remove(paths):
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            pass


def _refuse(error):
    print(str(error), file=sys.stderr)
    return 2


def _run(args):
    try:
        _check_options(args)
    except ContractError as error:
        return _refuse(error)
    doc, digest, problem = _load_input(args.source)
    if problem:
        return _refuse(problem)
    try:
        selection = profiles.resolve(flag=args.body, stature_flag=args.stature, config=args.config, view=args.view)
        files = _documents(doc, digest, args, selection)
    except ContractError as error:
        return _refuse(error)
    return _write(files, args.source, mkdir=args.all_people)


def _delegate(name, rest):
    return importlib.import_module(f"part3.{name}").main(rest)  # imported when asked for: `run` does not load them


def main(argv=None):
    """Run the command line. Exit codes: 0 ok, 2 invalid input or options, 1 output not writable."""
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] in DELEGATED:
        return _delegate(argv[0], argv[1:])
    return _run(_parser().parse_args(argv))
