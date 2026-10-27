"""Pipeline wiring (spec "Pipeline") and the `python3 -m part3 run` command line."""

import argparse
import hashlib
import json
import sys

import numpy as np

from part3 import bones, facing, flips, io, mirror, person, schema, standard, temporal
from part3.joints import BONES, GROUP_ORDER, JOINTS
from part3.schema import ContractError


def _rounded(values):
    """Round to the output decimals and write -0.0 as 0.0."""
    return io.round_clean(values, io.OUTPUT_DECIMALS)


def _bone_block():
    return [{"name": name, "from": start, "to": end} for name, start, end in BONES]


def _rounded_lengths(lengths):
    return dict(zip(lengths, _rounded(np.array(list(lengths.values()))).tolist()))


def _output_frames(frames, indices, pid, coords, conf, repaired):
    """Every input frame again: the rebuilt person where `indices` says so, else an empty list."""
    row_of = {int(i): k for k, i in enumerate(indices)}
    coords, conf = coords.tolist(), conf.tolist()
    out = []
    for i, frame in enumerate(frames):
        people = []
        if i in row_of:
            k = row_of[i]
            joints = {name: {"x": coords[k][j][0], "y": coords[k][j][1], "z": coords[k][j][2],
                             "conf": conf[k][j]} for j, name in enumerate(JOINTS)}
            people = [{"id": pid, "joints": joints, "flips_repaired": repaired[k]}]
        out.append({"frame": frame["frame"], "t_ms": frame["t_ms"], "people": people})
    return out


def _rebuild(n_frames, indices, framed):
    """Step 5b then step 6: filter inside runs of present frames, then retarget to the standard body."""
    present = np.zeros(n_frames, dtype=bool)
    present[indices] = True
    body = np.zeros((n_frames, len(JOINTS), 3))
    body[indices] = framed
    smooth = temporal.smooth(body, present)[indices]
    return _rounded(bones.retarget(smooth, standard.bone_lengths()))


def _select_person(doc):
    """Steps 2 and the hip check: (chosen id, candidates, frame indices, J, conf, frames_dropped)."""
    frames = doc["frames"]
    if not frames:
        raise ContractError("pose3d.frames", "empty: the clip has no frames")
    chosen, candidates = person.choose(frames)
    if chosen is None:
        raise ContractError("pose3d.frames", "no person in any frame")
    indices, J, conf = person.extract(frames, chosen)
    apart = person.hips_apart(J)
    if not apart.any():
        raise ContractError("pose3d.frames", "the chosen person has no usable frame (the hips coincide)")
    return chosen, candidates, np.array(indices)[apart], J[apart], conf[apart], int((~apart).sum())


def process(doc, flip="auto", sha256=None, trace=None):
    """A pose3d dict in, a skeleton.json dict out (no file I/O).

    `sha256` is the hex SHA-256 recorded in `input.sha256`. A caller that read the input from a file
    passes the hash of the file's bytes (as `main` does). Without it the hash is taken over a
    `json.dumps` re-serialisation of `doc`, which is stable for a given dict but is in general not
    the hash of the file's bytes.

    Raises ContractError for an invalid input, an empty clip or a clip without a person, and
    ValueError for a `flip` value other than auto, on or off. When `trace` is a dict it receives
    `up_in_input` (the clip body up in the label-repaired input coordinates) and `up_source`.
    """
    if flip not in mirror.FLIP_VALUES:
        raise ValueError(f"flip must be one of {', '.join(mirror.FLIP_VALUES)} (got {flip!r})")
    schema.validate_pose3d(doc)
    chosen, candidates, indices, J, conf, dropped = _select_person(doc)
    applied, reason = mirror.decide(flip, doc)
    if applied:
        J, conf = mirror.apply(J, conf)
    J, conf, repaired = flips.repair(J, conf)
    framed, valid, up, up_source = facing.body_frame(J)
    if trace is not None:
        trace["up_in_input"] = [float(v) for v in up]
        trace["up_source"] = up_source
    if not valid.any():
        raise ContractError("pose3d.frames", "the chosen person has no usable frame (no hip line)")
    dropped += int((~valid).sum())
    indices, J, conf, framed = indices[valid], J[valid], conf[valid], framed[valid]
    repaired = [r for r, ok in zip(repaired, valid) if ok]
    measured = _rounded_lengths(standard.measured_bone_lengths(J, conf))
    rebuilt = _rebuild(len(doc["frames"]), indices, framed)
    totals = {g: sum(g in r for r in repaired) for g in GROUP_ORDER}
    digest = sha256 or hashlib.sha256(json.dumps(doc, ensure_ascii=False).encode()).hexdigest()
    skeleton = {
        "schema": schema.SCHEMA_ID,
        "units": dict(schema.UNITS),
        "frame": {**schema.FRAME_BLOCK, "up_source": up_source},
        "joints": list(JOINTS),
        "bones": _bone_block(),
        "standard": {"stature_m": standard.stature_m(), "sources": standard.sources()},
        "bone_lengths_m": standard.bone_lengths(),
        "person": {"id": chosen, "rule": person.RULE, "candidates": candidates,
                   "frames_present": len(indices), "frames_dropped": dropped,
                   "few_frames": len(indices) < schema.FEW_FRAMES_BELOW,
                   "measured_bone_lengths_m": measured, "flips_repaired_total": totals},
        "mirror": {"setting": flip, "applied": applied, "reason": reason},
        "input": {"sha256": digest},
        "frames": _output_frames(doc["frames"], indices, chosen, rebuilt, conf, repaired),
    }
    schema.validate_skeleton(skeleton)
    return skeleton


def _parser():
    parser = argparse.ArgumentParser(prog="python3 -m part3")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="pose3d.json in, skeleton.json out")
    run.add_argument("--in", dest="source", required=True, help="path of pose3d.json")
    run.add_argument("--out", dest="target", required=True, help="path of skeleton.json to write")
    run.add_argument("--flip", choices=mirror.FLIP_VALUES, default="auto",
                     help="mirror correction for selfie recordings (default auto)")
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


def main(argv=None):
    """Run the command line. Exit codes: 0 ok, 2 invalid input or options, 1 output not writable."""
    args = _parser().parse_args(argv)
    doc, digest, problem = _load_input(args.source)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    try:
        skeleton = process(doc, flip=args.flip, sha256=digest)
        text = io.dumps(skeleton)
    except ContractError as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        io.write_text(args.target, text)
    except UnicodeEncodeError:
        print(f"{args.source}: pose3d.frames: an id cannot be written as UTF-8", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"{args.target}: cannot write ({error.strerror or error})", file=sys.stderr)
        return 1
    return 0
