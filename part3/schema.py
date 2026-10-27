"""Step 1: validators for pose3d.json (input) and skeleton.json (output).

Contracts: docs/specs/contract-pose3d-input.md and docs/specs/contract-skeleton-output.md.
`python3 -m part3.schema <file>` validates a skeleton.json: exit 0, or exit 2 with the path on stderr.
"""

import json
import math
import re
import sys

from part3 import standard
from part3.io import OUTPUT_DECIMALS
from part3.joints import BONES, BONE_NAMES, GROUP_ORDER, JOINTS
from part3.mirror import FLIP_VALUES

SCHEMA_ID = "simon.skeleton/1"
UNITS = {"length": "m", "angle": "deg", "time": "ms"}
FRAME_BLOCK = {"origin": "hip_midpoint", "x": "subject_left", "y": "body_up", "z": "anterior"}
UP_SOURCES = ("standing_frames", "all_frames")
MIRROR_REASONS = ("flag on", "flag off", "auto: input mirrored true", "auto: input mirrored false",
                  "auto: no mirrored key in input")
FEW_FRAMES_BELOW = 5


class ContractError(Exception):
    """A contract violation at `path` (for example `pose3d.frames[3].people[0].joints.nose.conf`)."""

    def __init__(self, path, msg):
        super().__init__(f"{path}: {msg}")
        self.path = path
        self.msg = msg


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_finite(value):
    if not _is_number(value):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _fail(path, msg):
    raise ContractError(path, msg)


def _finite(value, path):
    if not _is_finite(value):
        _fail(path, "expected a finite number")


# --- pose3d.json --------------------------------------------------------------------------------

def _check_joint(joint, path):
    if not isinstance(joint, dict):
        _fail(path, "expected an object with x, y, z and conf")
    for axis in "xyz":
        _finite(joint.get(axis), f"{path}.{axis}")
    conf = joint.get("conf")
    if not _is_number(conf):
        _fail(f"{path}.conf", "expected a number in [0, 1]")
    if not 0 <= conf <= 1:
        _fail(f"{path}.conf", f"{conf} not in [0, 1]")


def _check_joints(joints, path):
    if not isinstance(joints, dict) or set(joints) != set(JOINTS):
        found = set(joints) if isinstance(joints, dict) else set()
        detail = [f"missing {n}" for n in JOINTS if n not in found]
        detail += [f"unexpected {n}" for n in sorted(map(str, found - set(JOINTS)))]
        _fail(path, "expected the 17 canonical joints" + (f" ({'; '.join(detail)})" if detail else ""))
    for name in JOINTS:
        _check_joint(joints[name], f"{path}.{name}")


def _check_person(person, path, seen_ids, person_hook):
    if not isinstance(person, dict):
        _fail(path, "expected an object")
    pid = person.get("id")
    if not (_is_int(pid) or isinstance(pid, str)):
        _fail(f"{path}.id", "expected an integer or a string")
    if (type(pid), pid) in seen_ids:
        _fail(f"{path}.id", f"duplicate id {pid!r} in this frame")
    seen_ids.add((type(pid), pid))
    _check_joints(person.get("joints"), f"{path}.joints")
    if person_hook is not None:
        person_hook(person, path)


def _check_frame(frame, path, person_hook, max_people):
    if not isinstance(frame, dict):
        _fail(path, "expected an object")
    if not _is_int(frame.get("frame")):
        _fail(f"{path}.frame", "expected an integer")
    _finite(frame.get("t_ms"), f"{path}.t_ms")
    people = frame.get("people")
    if not isinstance(people, list):
        _fail(f"{path}.people", "expected a list")
    if max_people is not None and len(people) > max_people:
        _fail(f"{path}.people", f"expected 0 or {max_people} people")
    seen = set()
    for k, person in enumerate(people):
        _check_person(person, f"{path}.people[{k}]", seen, person_hook)


def _check_frames(frames, prefix, person_hook=None, max_people=None):
    if not isinstance(frames, list):
        _fail(f"{prefix}.frames", "expected a list")
    previous = None
    for i, frame in enumerate(frames):
        path = f"{prefix}.frames[{i}]"
        _check_frame(frame, path, person_hook, max_people)
        if previous is not None and frame["frame"] <= previous:
            _fail(f"{path}.frame", "frame indices must be strictly increasing")
        previous = frame["frame"]


def validate_pose3d(doc):
    """Raise ContractError unless `doc` is a valid pose3d.json (unknown extra keys are ignored)."""
    if not isinstance(doc, dict):
        _fail("pose3d", "expected an object")
    _check_frames(doc.get("frames"), "pose3d")
    if "mirrored" in doc and not isinstance(doc["mirrored"], bool):
        _fail("pose3d.mirrored", "expected true or false")


# --- skeleton.json ------------------------------------------------------------------------------

def _expect_equal(value, expected, path):
    if value != expected or type(value) is not type(expected):
        _fail(path, f"expected {json.dumps(expected)}")


def _expect_object(value, path):
    if not isinstance(value, dict):
        _fail(path, "expected an object")
    return value


def _expect_lengths(value, path):
    """A {bone: finite positive metres} object with exactly the 18 bone names."""
    _expect_object(value, path)
    if list(value) != list(BONE_NAMES):
        _fail(path, "expected exactly the 18 bones in contract order")
    for name in BONE_NAMES:
        if not _is_finite(value[name]) or value[name] <= 0:
            _fail(f"{path}.{name}", "expected a positive finite number")


def _check_header(doc, p):
    _expect_equal(doc.get("schema"), SCHEMA_ID, f"{p}.schema")
    _expect_equal(doc.get("units"), UNITS, f"{p}.units")
    block = _expect_object(doc.get("frame"), f"{p}.frame")
    for key, expected in FRAME_BLOCK.items():
        _expect_equal(block.get(key), expected, f"{p}.frame.{key}")
    if block.get("up_source") not in UP_SOURCES:
        _fail(f"{p}.frame.up_source", f"expected one of {', '.join(UP_SOURCES)}")
    _expect_equal(doc.get("joints"), list(JOINTS), f"{p}.joints")
    bones = [{"name": n, "from": a, "to": b} for n, a, b in BONES]
    if doc.get("bones") != bones:
        _fail(f"{p}.bones", "expected exactly the 18 bones of the contract, in order")


def _check_standard(doc, p):
    std = _expect_object(doc.get("standard"), f"{p}.standard")
    _expect_equal(std.get("stature_m"), standard.stature_m(), f"{p}.standard.stature_m")
    _expect_equal(std.get("sources"), standard.sources(), f"{p}.standard.sources")
    _expect_lengths(doc.get("bone_lengths_m"), f"{p}.bone_lengths_m")
    if doc["bone_lengths_m"] != standard.bone_lengths():
        _fail(f"{p}.bone_lengths_m", "expected the standard body of part3/standard_body.json")


def _check_person_block(doc, p):
    block = _expect_object(doc.get("person"), f"{p}.person")
    pid = block.get("id")
    if not (_is_int(pid) or isinstance(pid, str)):
        _fail(f"{p}.person.id", "expected an integer or a string")
    _expect_equal(block.get("rule"), "most_frames", f"{p}.person.rule")
    cands = _expect_object(block.get("candidates"), f"{p}.person.candidates")
    if str(pid) not in cands or not all(_is_int(c) and c > 0 for c in cands.values()):
        _fail(f"{p}.person.candidates", "expected frame counts that include the chosen id")
    for key in ("frames_present", "frames_dropped"):
        if not _is_int(block.get(key)) or block[key] < 0:
            _fail(f"{p}.person.{key}", "expected a non-negative integer")
    if cands[str(pid)] != block["frames_present"] + block["frames_dropped"]:
        _fail(f"{p}.person.candidates", "chosen id count must equal frames_present + frames_dropped")
    _expect_equal(block.get("few_frames"), block["frames_present"] < FEW_FRAMES_BELOW,
                  f"{p}.person.few_frames")
    _expect_lengths(block.get("measured_bone_lengths_m"), f"{p}.person.measured_bone_lengths_m")
    totals = _expect_object(block.get("flips_repaired_total"), f"{p}.person.flips_repaired_total")
    if list(totals) != list(GROUP_ORDER) or not all(_is_int(v) and v >= 0 for v in totals.values()):
        _fail(f"{p}.person.flips_repaired_total", "expected counts for body, legs, arms, face")
    return block


def _check_mirror_and_input(doc, p):
    mirror = _expect_object(doc.get("mirror"), f"{p}.mirror")
    if mirror.get("setting") not in FLIP_VALUES:
        _fail(f"{p}.mirror.setting", f"expected one of {', '.join(FLIP_VALUES)}")
    if not isinstance(mirror.get("applied"), bool):
        _fail(f"{p}.mirror.applied", "expected true or false")
    if mirror.get("reason") not in MIRROR_REASONS:
        _fail(f"{p}.mirror.reason", "expected one of the documented reasons")
    digest = _expect_object(doc.get("input"), f"{p}.input").get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        _fail(f"{p}.input.sha256", "expected a 64-character lowercase hex digest")


def _check_output_number(value, path):
    if not _is_finite(value) or round(value, OUTPUT_DECIMALS) != value:
        _fail(path, f"expected a number with at most {OUTPUT_DECIMALS} decimals")
    if value == 0 and math.copysign(1.0, value) < 0:
        _fail(path, "-0.0 must be written as 0.0")


def _skeleton_person_hook(block, tally):
    def hook(person, path):
        if person.get("id") != block["id"] or type(person["id"]) is not type(block["id"]):
            _fail(f"{path}.id", "must equal person.id")
        flips = person.get("flips_repaired")
        if (not isinstance(flips, list) or len(set(flips)) != len(flips)
                or not all(g in GROUP_ORDER for g in flips)
                or flips != [g for g in GROUP_ORDER if g in flips]):
            _fail(f"{path}.flips_repaired", "expected a subset of body, legs, arms, face in that order")
        for g in flips:
            tally[g] += 1
        for name in JOINTS:
            for axis in "xyz":
                _check_output_number(person["joints"][name][axis], f"{path}.joints.{name}.{axis}")
        tally["present"] += 1
    return hook


def _check_skeleton_frames(doc, p, block):
    tally = {"present": 0, **{g: 0 for g in GROUP_ORDER}}
    _check_frames(doc.get("frames"), p, _skeleton_person_hook(block, tally), max_people=1)
    if tally["present"] != block["frames_present"]:
        _fail(f"{p}.person.frames_present", f"expected {tally['present']}, the frames holding the person")
    if {g: tally[g] for g in GROUP_ORDER} != block["flips_repaired_total"]:
        _fail(f"{p}.person.flips_repaired_total", "does not match the frames' flips_repaired")


def validate_skeleton(doc):
    """Raise ContractError unless `doc` is a valid skeleton.json (and so a valid pose3d.json)."""
    p = "skeleton"
    _expect_object(doc, p)
    _check_header(doc, p)
    _check_standard(doc, p)
    block = _check_person_block(doc, p)
    _check_mirror_and_input(doc, p)
    _check_skeleton_frames(doc, p, block)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python3 -m part3.schema <skeleton.json>", file=sys.stderr)
        return 2
    try:
        with open(args[0], encoding="utf-8") as handle:
            doc = json.load(handle)
        validate_skeleton(doc)
    except ContractError as error:
        print(str(error), file=sys.stderr)
        return 2
    except (OSError, ValueError, RecursionError) as error:
        print(f"{args[0]}: cannot read as JSON ({error})", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
