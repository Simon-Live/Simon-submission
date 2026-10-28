"""`python3 -m part3 doctor <file> [--for part3|part4|part5] [--json]`: name a file, check it, say who rejects it.

Names the kind and version, validates (the schema in `contracts/` plus Part 3's own validator where one
exists) and says per consumer whether it accepts the file or would reject it, with the field and the option
that fixes it. The consumer rules come from the neighbours' documentation (Part 4 README "Edge cases",
Part 5 `docs/schemas.md`); nothing is imported from another part. Plain one-line findings, never a
traceback. Spec: docs/specs/integration-contract.md "Contract and doctor"; ACs AC-C04, AC-C05, AC-C06.
Exit codes: 0 known kind and valid (and the `--for` consumer accepts), 1 valid but the `--for` consumer
would reject it, 2 unreadable, not JSON, unknown kind or invalid. A Part 4 rule doctor cannot check is a
rejection, never an accept (review B3).
"""

import argparse
import json
import math
import pathlib
import sys
from dataclasses import dataclass, field
from typing import NamedTuple

import numpy as np

from part3 import adapters, bones, contract, jsonschema_lite, rig
from part3.joints import BONE_NAMES, COORDINATE_FRAME, JOINTS
from part3.rig import HIERARCHY
from part3.schema import (ContractError, describe, is_finite, is_int, is_number, validate_pose3d,
                          validate_skeleton)

FPS = 30
KEY_T_TOLERANCE_S = 1e-6
FK_TOLERANCE_M = 1e-3
QUATERNION_MIN_NORM = 1e-8  # Part 4 rejects a rotation with a smaller norm
BONE_TOLERANCE = 0.02  # a frame bone may differ from bone_lengths_m by this share
HIP_TOLERANCE_M = 0.01
MAX_FINDINGS = 5
MAX_ERRORS_SHOWN = 10
ASSUMED_INPUT_FPS = 30.0  # only used to check the rest of a file whose t_ms an adapter would derive

PART5_FORMATS = {"simon.animation.v1": "frames", "simon.skeleton.v1": "keyframes"}

RUN = "python3 -m part3 run ..."
FIX_PART4 = f"{RUN} --view part4 --keyframes <keyframes.json>"
FIX_PART5 = f"{RUN} --view part5"
FIX_KEYFRAMES_OUT = f"{RUN} --view part4 --keyframes <keyframes.json> --keyframes-out <dir>/keyframes.json"
FIX_LONG_WAY = rig.LONG_WAY_FIX
FIX_PRODUCER = "fix the producer of this file (Part 3 did not write it)"

# kind: (label, schema name, consumers that read this kind)
KINDS = {
    "pose3d": ("Part 2 pose3d.json", "pose3d", ("part3",)),
    "native": ("Part 3 skeleton.json, native", "skeleton", ("part3", "part4", "part5")),
    "part4-view": ("Part 3 skeleton.json, part4 view", "skeleton-part4", ("part3", "part4", "part5")),
    "part4-other": ("simon.skeleton.v1 (not written by Part 3)", "skeleton-part4", ("part4", "part5")),
    "animation": ("animation clip (Part 3 part5 view or Part 4 animation.json)", "animation-part5", ("part5",)),
    "keyframes-part4": ("Part 4 keyframes.json", "keyframes-part4", ("part3", "part4")),
    "keyframes-part1": ("Part 1 keyframes.json", "keyframes-part1", ("part3", "part4")),
    "body-profile": ("body profile file", "body-profile", ("part3",)),
    "people-index": ("people.json from --all-people", "people-index", ()),
    "follower-labels": ("follower take labels", "follower-labels", ()),
}
PART_NAMES = {"part3": "Part 3", "part4": "Part 4", "part5": "Part 5"}
# Version string to kind. The string may sit in `format` or in `schema`: Part 5 style files use
# `format`, Part 3's own use `schema`, and the follower labels use `format` like Part 5's labels.
VERSION_KINDS = {
    "simon.skeleton.v1": "part4-view", "simon.animation.v1": "animation", "simon.keyframes.v1": "keyframes-part4",
    "simon.body_profile/1": "body-profile", "simon.part3.people/1": "people-index",
    "simon.part3.follower_labels/1": "follower-labels",
}
NATIVE_VERSION = "simon.skeleton/1"


class Verdict(NamedTuple):
    """What one consumer does with the file. `fix` names the option; `reason` the field and the problem."""
    accepts: bool
    reason: str
    fix: str


class Finding(str):
    """A rejection reason that carries its own fix; a plain str takes the consumer's default fix."""

    def __new__(cls, reason, fix=""):
        item = super().__new__(cls, reason)
        item.fix = fix
        return item


@dataclass
class Report:
    path: str | None
    kind: str | None
    label: str | None
    version: str | None
    valid: bool
    errors: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    consumers: dict = field(default_factory=dict)

    def to_dict(self):
        return {"path": self.path, "kind": self.kind, "label": self.label, "version": self.version,
                "valid": self.valid, "errors": self.errors, "notes": self.notes,
                "consumers": {name: v._asdict() for name, v in self.consumers.items()}}


def _yes(reason="", fix=""):
    return Verdict(True, reason, fix)


def _no(reason, fix):
    return Verdict(False, reason, fix)


def _from_findings(findings, fix):
    if not findings:
        return _yes()
    more = f" (and {len(findings) - 1} more)" if len(findings) > 1 else ""
    return _no(findings[0] + more, getattr(findings[0], "fix", "") or fix)


def _is_point(value):
    return isinstance(value, list) and len(value) == 3 and all(is_finite(c) for c in value)


def _positive(value):
    return is_finite(value) and value > 0


# --- kind detection ----------------------------------------------------------------------------

def _looks_like_part1(doc):
    people = doc.get("people")
    return isinstance(people, list) and (
        any(isinstance(p, dict) and isinstance(p.get("repetitions"), list) for p in people)
        or (not people and "video" in doc))


def _looks_like_pose3d(doc):
    frames = doc.get("frames")
    return isinstance(frames, list) and (
        not frames or any(isinstance(f, dict) and ("people" in f or "joints" in f) for f in frames))


def _is_part4_view(doc):
    """True when a simon.skeleton.v1 file has Part 3's native record (frames or input); Part 4's own has neither."""
    return "frames" in doc or "input" in doc


def detect_kind(doc):
    """The kind name of a parsed document (a key of KINDS), or None when it is not a file of the contract."""
    if not isinstance(doc, dict):
        return None
    fmt, schema = doc.get("format"), doc.get("schema")
    for value in (fmt, schema):  # format first: a part4 view carries both
        if isinstance(value, str) and value in VERSION_KINDS:
            kind = VERSION_KINDS[value]
            return "part4-other" if kind == "part4-view" and not _is_part4_view(doc) else kind
    if isinstance(fmt, str):
        return None  # a native skeleton has no format
    if schema == NATIVE_VERSION:
        return "native"
    if isinstance(schema, str):
        return None
    if _looks_like_part1(doc):
        return "keyframes-part1"
    return "pose3d" if _looks_like_pose3d(doc) else None


def _unknown_message(doc, where):
    key = next((k for k in ("format", "schema") if isinstance(doc, dict) and isinstance(doc.get(k), str)), None)
    known = ", ".join(sorted({*VERSION_KINDS, NATIVE_VERSION}))
    detail = f': {key} "{doc[key]}" is not one Part 3 reads (known: {known})' if key else ""
    return f"{where}: unknown kind (not a file of the Part 3 contract){detail}"


# --- validation --------------------------------------------------------------------------------

def _merge(lite, own):
    """Schema errors plus Part 3's own error; Part 3's wording wins for the same path."""
    if own is None:
        return list(lite)
    return [str(own)] + [e for e in lite if not e.startswith(own.path + ":")]


def _own_error(check, doc, lite):
    try:
        check(doc)
    except ContractError as error:
        return error
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
        if lite:
            return None  # the schema errors already say what is wrong with the shape
        return ContractError("document", f"Part 3's own check could not read it ({error})")
    return None


def _checked(doc, info, root, check=None):
    lite = jsonschema_lite.validate(doc, info["schema"], root=root)
    own = _own_error(check, doc, lite) if check else None
    return _merge(lite, own)


def _adapted(doc):
    """(canonical document, names of the input adapters that fire): Part 3's own adapt() on a copy of `doc`.

    A stand-in frame rate lets derive-t_ms run so the rest of the file is checked; `_pose3d_part3` reports it.
    """
    if not isinstance(doc.get("frames"), list):
        return doc, []
    return adapters.adapt(doc, input_fps=ASSUMED_INPUT_FPS)


def _validate_pose3d(doc, info):
    canon, forms = _adapted(doc)
    why = {module.NAME: module.DESCRIPTION for module in adapters.REGISTRY}
    ctx = {"forms": forms, "fps_missing": "derive-t_ms" in forms and not _positive(doc.get("fps"))}
    notes = [f"tolerated form: adapter {name}: {why[name]}" for name in forms]
    return _checked(canon, info, "pose3d", validate_pose3d), notes, ctx


def _bone_errors(rows, expected):
    """One error per row [(label, 17 points)] with a bone over BONE_TOLERANCE off `expected` ({bone: m})."""
    if not rows:
        return []
    measured = bones.measure(np.array([points for _, points in rows]))
    wanted = bones.lengths_array(expected)
    errors = []
    for (label, _), got, row in zip(rows, measured, measured / wanted - 1.0):
        k = int(np.argmax(np.abs(row)))
        if abs(row[k]) > BONE_TOLERANCE:
            side = "longer" if row[k] > 0 else "shorter"
            errors.append(f"{label}: bone {BONE_NAMES[k]} measures {got[k]:.4f} m, {abs(row[k]) * 100:.1f}% {side} "
                          f"than bone_lengths_m ({wanted[k]:.4f}); the limit is {BONE_TOLERANCE * 100:.0f}%")
    return errors


def _frame_bone_errors(doc):
    """Per-frame bone lengths of a native skeleton against its bone_lengths_m (the frames holding the person)."""
    rows = [(f"skeleton.frames[{i}].people[{k}]", [[person["joints"][name][axis] for axis in "xyz"] for name in JOINTS])
            for i, frame in enumerate(doc["frames"]) for k, person in enumerate(frame["people"])]
    return _bone_errors(rows, doc["bone_lengths_m"])


def _key_bone_errors(doc):
    """Per-key bone lengths of a part4 view against its bone_lengths_m."""
    rows = [(f"skeleton.keyframes[{i}].joints", list(_key_points(key["joints"]).values()))  # in JOINTS order
            for i, key in enumerate(doc["keyframes"])]
    return _bone_errors(rows, doc["bone_lengths_m"])


def _validate_native(doc, info):
    notes = []
    body = doc.get("body")
    if isinstance(body, dict) and isinstance(body.get("profile"), str):
        notes.append(f'body profile {body["profile"]} (selected by {body.get("selected_by")})')
    errors = _checked(doc, info, "skeleton", validate_skeleton)
    return errors or _frame_bone_errors(doc), notes, {}


def _validate_part4_view(doc, info):
    errors, notes, ctx = _validate_native(doc, info)
    fit = doc["rig"].get("fit") if isinstance(doc.get("rig"), dict) else None
    if isinstance(fit, dict) and is_finite(fit.get("max_m")):
        notes.append(f"rig.fit: key poses were snapped to Part 4's rig; worst residual {fit['max_m'] * 1000:.1f} mm "
                     f"at {fit.get('worst_joint')} (key {fit.get('worst_index')}) against the native frame")
    return errors or _key_bone_errors(doc), notes, ctx


def _validate_part4_other(doc, info):
    """Part 4's own simon.skeleton.v1 files have no native record, so only the shape Part 4 and Part 5 read counts."""
    errors = [] if isinstance(doc.get("keyframes"), list) else ["keyframes: must be a list of key poses"]
    return errors, ["not written by Part 3 (no frames or input block): Part 3's schema is not applied; "
                    "the Part 4 and Part 5 rules are"], {}


def _validate_profile(doc, info):
    errors = _checked(doc, info, "profile")
    lengths = doc.get("bone_lengths_m")
    for left, right in (("left_pelvis", "right_pelvis"), ("left_clavicle", "right_clavicle")):
        if isinstance(lengths, dict) and is_number(lengths.get(left)) and is_number(lengths.get(right)) \
                and lengths[left] != lengths[right]:
            errors.append(f"profile.bone_lengths_m.{right}: must equal {left} ({lengths[left]}), "
                          "else the hip and shoulder midpoints move")
    return errors, [], {}


def _validate_plain(root):
    def check(doc, info):
        return _checked(doc, info, root), [], {}
    return check


_VALIDATORS = {
    "pose3d": _validate_pose3d, "native": _validate_native, "part4-view": _validate_part4_view,
    "part4-other": _validate_part4_other, "animation": _validate_plain("animation"),
    "keyframes-part4": _validate_plain("keyframes"), "keyframes-part1": _validate_plain("keyframes"),
    "body-profile": _validate_profile,
    "people-index": _validate_plain("people"), "follower-labels": _validate_plain("labels"),
}


# --- Part 5 rules (docs/schemas.md and part5/io.py as documented) ------------------------------

def _part5_frame(frame, where, fps, index):
    """(findings, t, hip midpoint offset) of one frame under Part 5's documented rules."""
    found = []
    if not isinstance(frame, dict):
        return [f"{where}: must be an object, got {describe(frame)}"], None, 0.0
    t = None
    if "t" in frame:
        if is_finite(frame["t"]):
            t = frame["t"]
        else:
            found.append(f"{where}.t: must be a number, got {json.dumps(frame['t'])}")
    elif fps:
        t = frame.get("index", index) / fps if is_finite(frame.get("index", index)) else None
    else:
        found.append(f"{where}: needs t (or a top-level fps)")
    if not isinstance(frame.get("interpolated", False), bool):
        found.append(f"{where}.interpolated: must be true or false")
    joints = frame.get("joints")
    if not isinstance(joints, dict):
        return found + [f"{where}.joints: must be an object"], t, 0.0
    found += _part5_joints(joints, frame.get("conf", {}), where)
    return found, t, _hip_offset(joints)


def _part5_joints(joints, conf, where):
    found = [f"{where}.joints.{name}: unknown joint name" for name in joints if name not in JOINTS]
    for name in JOINTS:
        point = joints.get(name)
        if point is not None and not _is_point(point):
            found.append(f"{where}.joints.{name}: must be [x, y, z] finite numbers, found {describe(point)}")
    if not isinstance(conf, dict):
        return found + [f"{where}.conf: must be an object of joint to 0..1"]
    found += [f"{where}.conf.{name}: must be a number in 0..1" for name, v in conf.items()
              if not (is_finite(v) and 0 <= v <= 1)]
    return found


def _hip_offset(joints):
    left, right = joints.get("left_hip"), joints.get("right_hip")
    if not (_is_point(left) and _is_point(right)):
        return 0.0
    return max(abs((a + b) / 2) for a, b in zip(left, right))


def _part5_header(doc):
    cf = doc.get("coordinate_frame", {})
    if not isinstance(cf, dict):
        return ["coordinate_frame: must be an object"]
    found = [f'coordinate_frame.{k}: must be "{v}", got {json.dumps(cf[k])}'
             for k, v in COORDINATE_FRAME.items() if k in cf and cf[k] != v]
    if "joints" in doc and doc["joints"] != list(JOINTS):
        found.append("joints: must be the canonical 17 joints in order")
    if doc.get("fps") is not None and not _positive(doc["fps"]):
        found.append("fps: must be a positive number")
    return found


def part5_findings(doc):
    """Reasons Part 5 would reject `doc`, from its documented rules; empty when it would read it."""
    if not isinstance(doc, dict):
        return ["the top level must be an object"]
    fmt = doc.get("format")
    if fmt is None:
        return ['no "format"']
    if fmt not in PART5_FORMATS:
        return [f"format {json.dumps(fmt)} is not simon.animation.v1 or simon.skeleton.v1"]
    found = _part5_header(doc)
    key = PART5_FORMATS[fmt]
    frames = doc.get(key)
    if not isinstance(frames, list) or not frames:
        return found + [f"{key}: must be a non-empty list"]
    fps = doc["fps"] if _positive(doc.get("fps")) else None
    previous, worst_hip = None, 0.0
    for i, frame in enumerate(frames):
        problems, t, hip = _part5_frame(frame, f"{key}[{i}]", fps, i)
        found += problems
        worst_hip = max(worst_hip, hip)
        if t is not None and previous is not None and t <= previous:
            found.append(f"{key}[{i}].t: times must strictly increase ({t} after {previous})")
        previous = t if t is not None else previous
        if len(found) >= MAX_FINDINGS:
            return found[:MAX_FINDINGS]
    if worst_hip > HIP_TOLERANCE_M:
        found.append(f"hip midpoint must sit at the origin in every frame (largest offset {worst_hip:.3f} m, "
                     f"limit {HIP_TOLERANCE_M} m)")
    return found


# --- Part 4 rules (README "Edge cases" and "The file is rejected") -----------------------------

def _rest_offset_findings(rest):
    if not isinstance(rest, dict):
        return ["rest_offsets_m: missing (Part 4 poses the rig from it)"]
    found = []
    for joint, parent in HIERARCHY.items():
        entry = rest.get(joint)
        if not isinstance(entry, dict):
            found.append(f"rest_offsets_m.{joint}: missing (Part 4 needs every joint of its rig)")
        elif entry.get("parent") != parent:
            found.append(f'rest_offsets_m.{joint}.parent: must be "{parent}", got {json.dumps(entry.get("parent"))}')
        elif not _is_point(entry.get("offset")):
            found.append(f"rest_offsets_m.{joint}.offset: must be [x, y, z] finite numbers")
    return found


def _timeline_findings(timeline):
    """(findings, frame_count or None) of a timeline block or a simon.keyframes.v1 header."""
    found, frame_count = [], None
    if timeline.get("fps") != FPS:
        found.append(f"fps: must be {FPS}, got {json.dumps(timeline.get('fps'))}")
    duration, count = timeline.get("duration_s"), timeline.get("frame_count")
    if is_finite(duration) and is_int(count):
        frame_count = count
        if count != round(duration * FPS) + 1:
            found.append(f"frame_count: {count} does not match duration_s {duration} "
                         f"(expected round(duration_s * {FPS}) + 1 = {round(duration * FPS) + 1})")
    return found, frame_count


def _key_findings(keys, frame_count, prefix):
    found, previous = [], None
    for i, key in enumerate(keys):
        where = f"{prefix}[{i}]"
        if not isinstance(key, dict) or not is_int(key.get("index")) or not is_finite(key.get("t")):
            found.append(f"{where}: needs an integer index and a numeric t")
            continue
        index = key["index"]
        if previous is not None and index <= previous:
            found.append(f"{where}.index: key indices must strictly increase ({index} after {previous})")
        if index < 0:
            found.append(f"{where}.index: {index} is before the first frame")
        elif frame_count is not None and index > frame_count - 1:
            found.append(f"{where}.index: {index} is after the last frame ({frame_count - 1})")
        off = abs(key["t"] - index / FPS)
        if off > KEY_T_TOLERANCE_S + 1e-12:
            found.append(f"{where}.t: {key['t']} is not index / {FPS} = {index / FPS:.6f} "
                         f"(off by {off * 1e6:.0f} microseconds, Part 4 allows 1)")
        previous = index
    return found


def _rotation_findings(keys):
    found = []
    for i, key in enumerate(keys):
        rotations = key.get("local_rotations") if isinstance(key, dict) else None
        if not isinstance(rotations, dict):
            found.append(f"keyframes[{i}].local_rotations: missing (Part 4 needs 19 quaternions per key)")
            continue
        for name in rig.ROTATED:
            q = rotations.get(name)
            where = f"keyframes[{i}].local_rotations.{name}"
            if q is None:
                found.append(f"{where}: missing (a joint without a rotation would freeze on the rest pose)")
            elif not (isinstance(q, list) and len(q) == 4 and all(is_finite(c) for c in q)):
                found.append(f"{where}: must be a quaternion [x, y, z, w]")
            elif math.hypot(*q) < QUATERNION_MIN_NORM:
                found.append(f"{where}: norm {math.hypot(*q):.1e} is under {QUATERNION_MIN_NORM:.0e} "
                             "(Part 4 rejects a zero rotation)")
    return found


def _key_points(joints):
    """{name: (x, y, z)} from a key's joints given as [x, y, z] or {x, y, z}; None when unreadable."""
    points = {}
    for name in JOINTS:
        p = joints.get(name) if isinstance(joints, dict) else None
        if isinstance(p, dict):
            p = [p.get("x"), p.get("y"), p.get("z")]
        if not _is_point(p):
            return None
        points[name] = tuple(float(c) for c in p)
    return points


def _fk_findings(keys, rest):
    """The forward kinematics of each key's rotations against its joints; a key it cannot pose is a finding."""
    found = []
    for i, key in enumerate(keys):
        points = _key_points(key.get("joints"))
        if points is None:
            found.append(f"keyframes[{i}].joints: must hold the 17 joints as [x, y, z] (Part 4 compares them "
                         "with forward kinematics)")
            continue
        try:
            fk = rig.forward(key["local_rotations"], rest)
        except (TypeError, ValueError, KeyError, AttributeError, IndexError) as error:
            return found + [f"keyframes[{i}]: forward kinematics could not be checked ({error}); "
                            "a rule doctor cannot check counts as a rejection"]
        worst, joint = max((math.dist(points[n], tuple(fk[n])), n) for n in JOINTS)
        if worst > FK_TOLERANCE_M:
            found.append(f"keyframes[{i}].joints.{joint}: forward kinematics of local_rotations misses it by "
                         f"{worst * 1000:.1f} mm (Part 4 allows 1 mm)")
    return found


def _long_way_findings(keys):
    """Part 4's rule: no joint turns over 180 degrees between neighbouring keys in rotation-vector space."""
    return [Finding(f"{step['joint']} turns {step['deg']} degrees between keys {step['from_index']} and "
                    f"{step['to_index']} (Part 4 allows {rig.MAX_ROTVEC_STEP_DEG:.0f})", FIX_LONG_WAY)
            for step in rig.long_way(keys)]


def _first_difference(theirs, ours):
    """Where two index lists first differ, e.g. 'key 2: it lists 30, this file has 20' (or one list ends early)."""
    for position, (a, b) in enumerate(zip(theirs, ours)):
        if a != b:
            return f"key {position}: it lists {a}, this file has {b}"
    shorter = min(len(theirs), len(ours))
    return f"key {shorter}: " + ("it lists none" if len(theirs) == shorter else "this file has none")


def _beside_findings(path, keys):
    """Findings about the keyframes.json Part 4 reads from the same folder as skeleton.json."""
    if path is None:
        return [Finding("keyframes.json: cannot look for it beside this file (no file path given); "
                        "Part 4 needs keyframes.json beside skeleton.json", FIX_KEYFRAMES_OUT)]
    other = pathlib.Path(path).parent / "keyframes.json"
    if not other.is_file():
        return [Finding("keyframes.json: not found beside this file (Part 4 needs keyframes.json beside "
                        "skeleton.json)", FIX_KEYFRAMES_OUT)]
    try:
        doc = json.loads(other.read_bytes().decode("utf-8"))
        theirs = [k["index"] for k in doc["keyframes"]]
    except (OSError, ValueError, KeyError, TypeError):
        return [Finding(f"{other.name}: beside this file but not a readable simon.keyframes.v1 list",
                        FIX_KEYFRAMES_OUT)]
    ours = [k.get("index") for k in keys if isinstance(k, dict)]
    if theirs == ours:
        return []
    return [Finding(f"{other.name}: key indices differ at {_first_difference(theirs, ours)} "
                    f"(it lists {len(theirs)} keys, this file has {len(ours)}); Part 4 needs the same list in both",
                    FIX_KEYFRAMES_OUT)]


def part4_skeleton_findings(doc):
    """Reasons Part 4 would reject a simon.skeleton.v1 file on its own, from Part 4's documented rules."""
    if doc.get("format") != "simon.skeleton.v1":
        return ['no "format" and no keyframes[] (Part 4 reads simon.skeleton.v1)']
    found = []
    if "joints" in doc and doc["joints"] != list(JOINTS):
        found.append("joints: must be the canonical 17 joints in order")
    found += _rest_offset_findings(doc.get("rest_offsets_m"))
    frame_count = None
    if isinstance(doc.get("timeline"), dict):
        problems, frame_count = _timeline_findings(doc["timeline"])
        found += [f"timeline.{p}" for p in problems]
    keys = doc.get("keyframes")
    if not isinstance(keys, list) or not keys:
        return found + ["keyframes: the skeleton has no keyframes"]
    found += _key_findings(keys, frame_count, "keyframes")
    found += _rotation_findings(keys)
    if not found:  # the rules below need readable keys, rotations and rest offsets
        with np.errstate(over="ignore", invalid="ignore"):  # a quaternion near 1e308 overflows its norm: a finding, not a warning
            found += _fk_findings(keys, doc["rest_offsets_m"])
            found += _long_way_findings(keys)
    return found


def part4_findings(doc, path):
    """Everything Part 4 checks: the file's own rules, then the keyframes.json beside it."""
    return part4_skeleton_findings(doc) or _beside_findings(path, doc["keyframes"])


def part4_keyframes_findings(doc):
    """Reasons Part 4 would reject a simon.keyframes.v1 file."""
    found, frame_count = _timeline_findings(doc)
    keys = doc.get("keyframes")
    if not isinstance(keys, list) or not keys:
        return found + ["keyframes: no keys"]
    return found + _key_findings(keys, frame_count, "keyframes")


# --- consumers ---------------------------------------------------------------------------------

def _not_read(part, what, fix):
    return _no(f"{part} does not read {what}", fix)


def _part3_as_input(doc):
    try:
        validate_pose3d(doc)
    except ContractError as error:
        return _no(str(error), "run Part 3 again on the original pose3d.json")
    return _yes("a skeleton.json is also a valid pose3d.json")


def _ids_in(doc):
    """Person ids in order of first appearance (canonical frames only)."""
    ids = []
    for frame in doc.get("frames", []):
        people = frame.get("people") if isinstance(frame, dict) else None
        for person in people if isinstance(people, list) else []:
            if isinstance(person, dict) and person.get("id") not in ids:
                ids.append(person.get("id"))
    return ids


def _adapters_text(forms, doc):
    text = f"adapter {forms[0]} fires" if len(forms) == 1 else f"adapters {', '.join(forms)} fire"
    if "derive-t_ms" in forms and _positive(doc.get("fps")):
        text += f" (t_ms from the top-level fps {doc['fps']})"
    return text


def _pose3d_part3(doc, ctx):
    frames = doc.get("frames")
    if not frames:
        return _no("pose3d.frames: empty, the clip has no frames", "give Part 3 a clip with at least one frame")
    if ctx["fps_missing"]:
        first = next(i for i, f in enumerate(frames) if isinstance(f, dict) and "t_ms" not in f)
        return _no(f"pose3d.frames[{first}].t_ms: missing; adapter derive-t_ms needs a frame rate",
                   "pass --input-fps <n> or add a top-level fps")
    parts = []
    if ctx["forms"]:
        parts.append(_adapters_text(ctx["forms"], doc))
    ids = _ids_in(doc)
    if len(ids) > 1:
        shown = ", ".join(str(i) for i in ids[:20])
        return _yes("; ".join(parts + [f"{len(ids)} people (ids {shown}); Part 3 keeps the one seen in most frames"]),
                    "--person <id> keeps one, --all-people writes one file per person")
    return _yes("; ".join(parts))


def _consumers_pose3d(doc, ctx, path):
    return {"part3": _pose3d_part3(doc, ctx),
            "part4": _not_read("Part 4", "pose3d.json (it reads simon.skeleton.v1)", FIX_PART4),
            "part5": _not_read("Part 5", "pose3d.json (it reads simon.animation.v1 or simon.skeleton.v1)", FIX_PART5)}


def _consumers_native(doc, ctx, path):
    return {"part3": _part3_as_input(doc),
            "part4": _no('no "format" and no keyframes[] (Part 4 reads simon.skeleton.v1)', FIX_PART4),
            "part5": _from_findings(part5_findings(doc), FIX_PART5)}


def _consumers_part4_view(doc, ctx, path):
    ours = _is_part4_view(doc)  # Part 4's own file is no pose3d.json and Part 3 cannot repair its producer
    part4 = part4_findings(doc, path)
    if not ours:  # a finding's own fix is a Part 3 run command, which cannot repair another producer's file
        part4 = [str(finding) for finding in part4]
    verdicts = {"part4": _from_findings(part4, FIX_KEYFRAMES_OUT if ours else FIX_PRODUCER),
                "part5": _from_findings(part5_findings(doc), FIX_PART4 if ours else FIX_PRODUCER)}
    return {"part3": _part3_as_input(doc), **verdicts} if ours else verdicts


def _consumers_animation(doc, ctx, path):
    by_part3 = doc.get("producer") == "part3"
    return {"part3": _not_read("Part 3", "simon.animation.v1 (it reads pose3d.json)",
                               "give Part 3 the pose3d.json this clip came from"),
            "part4": _not_read("Part 4", "simon.animation.v1 (Part 4 writes it)", FIX_PART4),
            "part5": _from_findings(part5_findings(doc), FIX_PART5 if by_part3 else FIX_PRODUCER)}


def _consumers_keyframes_part1(doc, ctx, path):
    return {"part3": _yes("", "--view part4 --keyframes <this file>"),
            "part4": _no('no "format": "simon.keyframes.v1" (Part 1 keys sit on the video clock, not the 30 fps index)',
                         f"{RUN} --view part4 --keyframes <this file> --keyframes-out <dir>/keyframes.json")}


def _consumers_keyframes_part4(doc, ctx, path):
    found = part4_keyframes_findings(doc)
    part3 = _no("fps: must be 30 (Part 3 keys on a 30 fps index)", "export the keys at 30 fps") \
        if doc.get("fps") != FPS else _yes("", "--view part4 --keyframes <this file>")
    return {"part3": part3,
            "part4": _from_findings(found, "rewrite the file: each t must be index / 30 and the indices strictly increase")}


def _consumers_profile(doc, ctx, path):
    return {"part3": _yes("", "--body file:<this file>")}


_CONSUMERS = {
    "pose3d": _consumers_pose3d, "native": _consumers_native, "part4-view": _consumers_part4_view,
    "part4-other": _consumers_part4_view, "animation": _consumers_animation,
    "keyframes-part1": _consumers_keyframes_part1, "keyframes-part4": _consumers_keyframes_part4,
    "body-profile": _consumers_profile,
    "people-index": lambda doc, ctx, path: {}, "follower-labels": lambda doc, ctx, path: {},
}


# --- report ------------------------------------------------------------------------------------

def diagnose(doc, path=None):
    """Name `doc`, validate it and ask each consumer. Never raises for a bad document."""
    shown = str(path) if path else None
    kind = detect_kind(doc)
    if kind is None:
        return Report(shown, None, None, None, False, [_unknown_message(doc, shown or "<input>")])
    label, schema_name, _ = KINDS[kind]
    info = contract.SCHEMAS[schema_name]
    errors, notes, ctx = _VALIDATORS[kind](doc, info)
    report = Report(shown, kind, label, info["version"], not errors, errors, notes)
    if not errors:
        report.consumers = _CONSUMERS[kind](doc, ctx, path)
    return report


def exit_code(report, target=None):
    """0 valid (and `target` accepts), 1 valid but `target` would reject, 2 not valid."""
    if not report.valid:
        return 2
    return 1 if target and not (target in report.consumers and report.consumers[target].accepts) else 0


def verdict_line(part, verdict):
    name = PART_NAMES[part]
    if not verdict.accepts:
        return f"{name} would reject: {verdict.reason}; fix: {verdict.fix}"
    line = f"{name} accepts" + (f": {verdict.reason}" if verdict.reason else "")
    return line + (f"; option: {verdict.fix}" if verdict.fix else "")


def format_report(report, target=None):
    """The plain-text lines `doctor` prints."""
    lines = [f"file: {report.path}"] if report.path else []
    if report.kind is None:
        return lines + report.errors
    lines.append(f"kind: {report.kind} ({report.label}), version {report.version}")
    lines.append(f"valid: {'yes' if report.valid else 'no'}")
    shown = report.errors[:MAX_ERRORS_SHOWN]
    lines += [f"error: {e}" for e in shown]
    if len(report.errors) > len(shown):
        lines.append(f"error: and {len(report.errors) - len(shown)} more")
    lines += [f"note: {n}" for n in report.notes]
    wanted = [p for p in PART_NAMES if p in KINDS[report.kind][2] or p == target]
    lines += [verdict_line(p, report.consumers[p]) for p in wanted if p in report.consumers]
    if target and report.valid and target not in report.consumers:
        lines.append(f"{PART_NAMES[target]} does not read this kind of file")
    return lines


def _parser():
    parser = argparse.ArgumentParser(
        prog="python3 -m part3 doctor",
        description="Name a Part 3 contract file, validate it and say which consumer would reject it.")
    parser.add_argument("file", help="the JSON file to check")
    parser.add_argument("--for", dest="target", choices=sorted(PART_NAMES),
                        help="exit 1 when this consumer would reject a valid file")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    return parser


def _read(path):
    """(document, problem): the parsed file, or None and a one-line problem."""
    try:
        raw = pathlib.Path(path).read_bytes()
    except OSError as error:
        return None, f"{path}: cannot read ({error.strerror or error})"
    try:
        return json.loads(raw.decode("utf-8")), None
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        return None, f"{path}: not valid JSON ({error})"


def _emit(report, target, as_json, code):
    if as_json:
        print(json.dumps({**report.to_dict(), "exit_code": code}, indent=2, ensure_ascii=False))
    else:
        print("\n".join(format_report(report, target)))


def main(argv=None):
    """Exit codes: 0 known and valid, 1 valid but the `--for` consumer would reject it, 2 anything else."""
    try:
        args = _parser().parse_args(argv)
    except SystemExit as stop:
        return int(stop.code or 0)
    document, problem = _read(args.file)
    if problem:
        report = Report(args.file, None, None, None, False, [problem])
        print(json.dumps({**report.to_dict(), "exit_code": 2}, indent=2) if args.json else problem,
              file=sys.stdout if args.json else sys.stderr)
        return 2
    try:
        report = diagnose(document, args.file)
    except Exception as error:  # the contract is a plain line, never a traceback
        print(f"{args.file}: doctor could not check this file ({type(error).__name__}: {error})", file=sys.stderr)
        return 2
    code = exit_code(report, args.target)
    _emit(report, args.target, args.json, code)
    return code


if __name__ == "__main__":
    sys.exit(main())
