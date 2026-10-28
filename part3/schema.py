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


class OptionError(ContractError):
    """A missing or unusable command line option; `str()` reads `<option> <message>` with no colon."""

    def __init__(self, option, msg):
        super().__init__(option, msg)
        self.args = (f"{option} {msg}",)


class FrameCapError(OptionError):
    """The output frame grid (`--fps`) or the key timeline (`--keyframes`) would hold more frames than the cap.

    `timeline` is True for the Part 4 key timeline and False for the `--fps` grid, so a caller tells the two apart by
    the attribute and never by the wording. The timeline's refusal keeps the `<path>: <message>` reading (the `--fps`
    refusal has none).
    """

    def __init__(self, path, msg, timeline=False):
        super().__init__(path, msg)
        self.timeline = timeline
        if timeline:
            self.args = (f"{path}: {msg}",)


class FrameRateError(ContractError):
    """The clip cannot be resampled at the chosen `--fps` for a reason that is not the frame cap.

    `times` is True when the input times do not increase, False when no output frame holds the person.
    """

    def __init__(self, path, msg, times=False):
        super().__init__(path, msg)
        self.times = times


def view_refusal_text(label, detail=None):
    """The run app's sentence for a View that cannot write the clip: no command line option in it, one next step."""
    shown = f": {detail.rstrip('.')}" if detail else ""
    return f"This clip cannot be written as {label}{shown}. Choose another View."


class ViewError(ContractError):
    """A View (`--view`) cannot write this clip. Every refusal a view raises is of this type, so the run app tells it
    from an invalid file by the type (docs/specs/compare-mode.md AC-M14), never by the path or the wording.

    `page_text` is the sentence the run app shows for it, with no command line option in it. `colon=False` gives the
    `<option> <message>` reading of a missing option.
    """

    def __init__(self, path, msg, page_text, colon=True):
        super().__init__(path, msg)
        self.page_text = page_text
        if not colon:
            self.args = (f"{path} {msg}",)


class LongWayError(ViewError):
    """Part 4 would reject the keys: `joint` turns `degrees` between keys `from_index` and `to_index`, over `limit_deg`.

    The numbers are attributes so a caller words the refusal for its own reader from them, not from `msg`; the page's
    sentence (`page_text`) is built from them here.
    """

    def __init__(self, path, msg, joint, degrees, from_index, to_index, limit_deg):
        detail = (f"{joint} turns {degrees} degrees between keys {from_index} and {to_index} "
                  f"(Part 4 allows {limit_deg:g})")
        super().__init__(path, msg, view_refusal_text("Part 4 keys", detail))
        self.joint, self.degrees = joint, degrees
        self.from_index, self.to_index, self.limit_deg = from_index, to_index, limit_deg


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_finite(value):
    if not _is_number(value):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def is_int(value):
    """True for a JSON whole number (an int that is not a bool)."""
    return isinstance(value, int) and not isinstance(value, bool)


_KINDS = ((type(None), "null"), (bool, "a boolean"), ((int, float), "a number"), (str, "a string"),
          (list, "an array"), (dict, "an object"))


def describe(value):
    """A parsed JSON value's kind in words, for a message: null, a boolean, a number, a string, an array or an object."""
    return next((name for kinds, name in _KINDS if isinstance(value, kinds)), type(value).__name__)


# The public names other modules import (one definition of "a JSON number" for all of Part 3).
is_number = _is_number
is_finite = _is_finite


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
        if axis not in joint:
            _fail(f"{path}.{axis}", "missing (expected a finite number)")
        _finite(joint.get(axis), f"{path}.{axis}")
    if "conf" not in joint:
        _fail(f"{path}.conf", "missing (expected a number in [0, 1])")
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
    if not (is_int(pid) or isinstance(pid, str)):
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
    if not is_int(frame.get("frame")):
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
    _expect_lengths(doc.get("bone_lengths_m"), f"{p}.bone_lengths_m")
    if "body" in doc:  # a body profile chose the numbers; `_check_body` checks them against it
        sources = std.get("sources")
        if not _is_finite(std.get("stature_m")):
            _fail(f"{p}.standard.stature_m", "expected a finite number")
        if not isinstance(sources, list) or not sources or not all(isinstance(s, str) for s in sources):
            _fail(f"{p}.standard.sources", "expected a non-empty list of strings")
        return
    # A file from before the body profiles holds the standard body.
    _expect_equal(std.get("stature_m"), standard.stature_m(), f"{p}.standard.stature_m")
    _expect_equal(std.get("sources"), standard.sources(), f"{p}.standard.sources")
    if doc["bone_lengths_m"] != standard.bone_lengths():
        _fail(f"{p}.bone_lengths_m", "expected the standard body of part3/standard_body.json")


def _check_body(doc, p):
    if "body" in doc:
        from part3 import profiles  # profiles imports this module for ContractError, so import it here
        profiles.validate_block(doc, p)


def _check_rule(block, pid, p):
    rule = block.get("rule")
    if rule == "requested":
        if "requested" not in block or type(block["requested"]) is not type(pid) or block["requested"] != pid:
            _fail(f"{p}.person.requested", "must equal person.id when rule is requested")
    elif rule != "most_frames":
        _fail(f"{p}.person.rule", 'expected "most_frames" or "requested"')
    elif "requested" in block:
        _fail(f"{p}.person.requested", 'only present when rule is "requested"')


def _check_person_block(doc, p):
    block = _expect_object(doc.get("person"), f"{p}.person")
    pid = block.get("id")
    if not (is_int(pid) or isinstance(pid, str)):
        _fail(f"{p}.person.id", "expected an integer or a string")
    _check_rule(block, pid, p)
    cands = _expect_object(block.get("candidates"), f"{p}.person.candidates")
    if str(pid) not in cands or not all(is_int(c) and c > 0 for c in cands.values()):
        _fail(f"{p}.person.candidates", "expected frame counts that include the chosen id")
    for key in ("frames_present", "frames_dropped"):
        if not is_int(block.get(key)) or block[key] < 0:
            _fail(f"{p}.person.{key}", "expected a non-negative integer")
    if cands[str(pid)] != block["frames_present"] + block["frames_dropped"]:
        _fail(f"{p}.person.candidates", "chosen id count must equal frames_present + frames_dropped")
    _expect_equal(block.get("few_frames"), block["frames_present"] < FEW_FRAMES_BELOW,
                  f"{p}.person.few_frames")
    _expect_lengths(block.get("measured_bone_lengths_m"), f"{p}.person.measured_bone_lengths_m")
    totals = _expect_object(block.get("flips_repaired_total"), f"{p}.person.flips_repaired_total")
    if list(totals) != list(GROUP_ORDER) or not all(is_int(v) and v >= 0 for v in totals.values()):
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
    block = _expect_object(doc.get("input"), f"{p}.input")
    digest = block.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        _fail(f"{p}.input.sha256", "expected a 64-character lowercase hex digest")
    adapters = block.get("adapters", [])
    if not isinstance(adapters, list) or not all(isinstance(name, str) for name in adapters):
        _fail(f"{p}.input.adapters", "expected a list of adapter names")


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


def _check_source(frame, path):
    source = frame.get("source")
    pair = source.get("frames") if isinstance(source, dict) else None
    if not (isinstance(pair, list) and len(pair) == 2 and all(is_int(n) for n in pair)):
        _fail(f"{path}.source.frames", "expected the two input frame numbers that bracket this frame")
    weight = source.get("weight")
    if not _is_finite(weight) or not 0 <= weight <= 1:
        _fail(f"{path}.source.weight", "expected a number in [0, 1]")


def _check_resample(doc, p):
    """The `resample` block and its per-frame `source` (a file without the block must have no `source`)."""
    frames = doc["frames"]
    if "resample" not in doc:
        for k, frame in enumerate(frames):
            if "source" in frame:
                _fail(f"{p}.frames[{k}].source", "only a resampled file (with a resample block) has it")
        return False
    block = _expect_object(doc["resample"], f"{p}.resample")
    if not _is_finite(block.get("fps")) or not 1 <= block["fps"] <= 240:
        _fail(f"{p}.resample.fps", "expected a number from 1 to 240")
    if not is_int(block.get("source_frames")) or block["source_frames"] < 1:
        _fail(f"{p}.resample.source_frames", "expected a positive integer")
    if not isinstance(block.get("method"), str):
        _fail(f"{p}.resample.method", "expected a string")
    for k, frame in enumerate(frames):
        _check_source(frame, f"{p}.frames[{k}]")
    return True


def _check_skeleton_frames(doc, p, block):
    tally = {"present": 0, **{g: 0 for g in GROUP_ORDER}}
    _check_frames(doc.get("frames"), p, _skeleton_person_hook(block, tally), max_people=1)
    if _check_resample(doc, p):
        return  # the person block describes the input clip, the frames are on the new grid
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
    _check_body(doc, p)
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
