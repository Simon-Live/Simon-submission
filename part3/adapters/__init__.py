"""Tolerant input adapters (spec integration-contract.md "Input adapters").

`adapt` runs every registered adapter whose shape is present, in registry order, on a copy of the
document and names the ones that fired. An adapter is any object with `NAME`, `DESCRIPTION`,
`applies(doc) -> bool` and `apply(doc, input_fps) -> doc` (a module works); a new tolerated shape is
one such object plus one line in `REGISTRY`. The five built-in adapters are defined below as
module-like objects, one self-contained block each.
"""

import copy
import math
import types

from part3.joints import JOINTS
from part3.schema import ContractError, is_number

T_DECIMALS = 3


def _adapter(name, description, applies, apply):
    return types.SimpleNamespace(NAME=name, DESCRIPTION=description, applies=applies, apply=apply)


def _frames(doc):
    """The frame objects of a pose3d-like document (empty when `frames` is not a list)."""
    listed = doc.get("frames") if isinstance(doc, dict) else None
    return [frame for frame in listed if isinstance(frame, dict)] if isinstance(listed, list) else []


def _people(doc):
    """Every person object in every frame (a `people` that is not a list is skipped)."""
    return [person for frame in _frames(doc) if isinstance(frame.get("people"), list)
            for person in frame["people"] if isinstance(person, dict)]


# --- flat-joints: a frame with `joints` and no `people` holds one person with id 0 ----------------

def _is_flat(frame):
    return "joints" in frame and "people" not in frame


def _flat_applies(doc):
    return any(_is_flat(frame) for frame in _frames(doc))


def _flat_apply(doc, input_fps=None):
    out = copy.deepcopy(doc)
    for frame in _frames(out):
        if _is_flat(frame):
            frame["people"] = [{"id": 0, "joints": frame.pop("joints")}]
    return out


flat_joints = _adapter("flat-joints", "a frame with `joints` and no `people` becomes people: [{id: 0, joints}]",
                       _flat_applies, _flat_apply)


# --- joint-arrays: [x, y, z] or [x, y, z, conf] arrays become {x, y, z, conf} -----------------------

def _is_row(value):
    return isinstance(value, list) and len(value) in (3, 4)


def _is_list_of_rows(joints):
    return isinstance(joints, list) and len(joints) == len(JOINTS) and all(_is_row(row) for row in joints)


def _needs_arrays(joints):
    if isinstance(joints, dict):
        return any(_is_row(value) for value in joints.values())
    return _is_list_of_rows(joints)


def _joint(row):
    x, y, z, *rest = row
    return {"x": x, "y": y, "z": z, "conf": rest[0] if rest else 1.0}


def _from_arrays(joints):
    if isinstance(joints, dict):
        return {name: _joint(value) if _is_row(value) else value for name, value in joints.items()}
    return {name: _joint(row) for name, row in zip(JOINTS, joints)}


def _arrays_applies(doc):
    return any(_needs_arrays(person.get("joints")) for person in _people(doc))


def _arrays_apply(doc, input_fps=None):
    out = copy.deepcopy(doc)
    for person in _people(out):
        if _needs_arrays(person.get("joints")):
            person["joints"] = _from_arrays(person["joints"])
    return out


joint_arrays = _adapter(
    "joint-arrays",
    "a person's `joints` as {name: [x, y, z]} / {name: [x, y, z, conf]}, or as a list of 17 such arrays in "
    "canonical order, becomes {name: {x, y, z, conf}}; a missing conf is 1.0",
    _arrays_applies, _arrays_apply)


# --- extra-joints: names outside the canonical 17 are dropped -----------------------------------------

def _has_extra(person):
    joints = person.get("joints")
    return isinstance(joints, dict) and any(name not in JOINTS for name in joints)


def _extra_applies(doc):
    return any(_has_extra(person) for person in _people(doc))


def _extra_apply(doc, input_fps=None):
    out = copy.deepcopy(doc)
    for person in _people(out):
        if _has_extra(person):
            person["joints"] = {name: value for name, value in person["joints"].items() if name in JOINTS}
    return out


extra_joints = _adapter("extra-joints",
                        "joint names outside the canonical 17 are dropped; a missing canonical joint still fails",
                        _extra_applies, _extra_apply)


# --- frame-index: frames without `frame` get their list position ---------------------------------------

def _index_applies(doc):
    return any("frame" not in frame for frame in _frames(doc))


def _index_apply(doc, input_fps=None):
    out = copy.deepcopy(doc)
    for position, frame in enumerate(out["frames"]):
        if isinstance(frame, dict) and "frame" not in frame:
            frame["frame"] = position
    return out


frame_index = _adapter("frame-index", "frames without `frame` get their list position",
                       _index_applies, _index_apply)


# --- derive-t_ms: frames without `t_ms` get frame * 1000 / fps ------------------------------------------

def _no_t_ms(frame):
    return "t_ms" not in frame


def _derive_applies(doc):
    return any(_no_t_ms(frame) for frame in _frames(doc))


def _fps_for(doc, input_fps):
    if input_fps is not None:
        return input_fps
    top = doc.get("fps")
    if is_number(top) and math.isfinite(top) and top > 0:
        return top
    first = next(k for k, frame in enumerate(doc["frames"]) if isinstance(frame, dict) and _no_t_ms(frame))
    raise ContractError(f"pose3d.frames[{first}].t_ms", "missing; pass --input-fps <n> or add a top-level fps")


def _derive_apply(doc, input_fps=None):
    fps = _fps_for(doc, input_fps)
    out = copy.deepcopy(doc)
    for frame in _frames(out):
        if _no_t_ms(frame) and is_number(frame.get("frame")):
            frame["t_ms"] = round(frame["frame"] * 1000.0 / fps, T_DECIMALS)
    return out


derive_t_ms = _adapter("derive-t_ms",
                       "frames without `t_ms` get frame * 1000 / fps; fps from --input-fps or a top-level numeric fps",
                       _derive_applies, _derive_apply)


REGISTRY = [flat_joints, joint_arrays, extra_joints, frame_index, derive_t_ms]


def parse_input_fps(value):
    """`value` (a number or numeric text) as a positive finite float, else ContractError("--input-fps")."""
    try:
        number = math.nan if isinstance(value, bool) else float(value)
    except (TypeError, ValueError):
        number = math.nan
    if not (math.isfinite(number) and number > 0):
        raise ContractError("--input-fps", f"must be a positive number (got {value})")
    return number


def adapt(doc, input_fps=None):
    """(canonical document, names of the adapters that fired); `doc` itself is never modified."""
    fps = None if input_fps is None else parse_input_fps(input_fps)
    names = []
    for module in REGISTRY:
        if module.applies(doc):
            doc = module.apply(doc, fps)
            names.append(module.NAME)
    return doc, names
