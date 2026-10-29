"""Validators for the shared files (README "Shared-file context") and the JSON writer every
output goes through. Validators raise ContractError(path, msg), a ValueError whose text is
`<path>: <msg>`; NaN and infinity are refused everywhere, in a validator or at write time."""
import json
import math
from pathlib import Path

from part2.joints import CANONICAL

# Optional top-level keys of pose3d.json (CONTRACT.md): the mirror flag, the first frame's PTS and
# the provenance block. Readers ignore them.
OPTIONAL_POSE3D = ("mirrored", "t0_pts_ms", "provenance")


class ContractError(ValueError):
    """A document breaks the contract. `path` says where, `msg` says which rule."""

    def __init__(self, path: str, msg: str):
        super().__init__(f"{path}: {msg}")
        self.path, self.msg = path, msg


def validate_pose3d(doc) -> None:
    """{frames: [{frame, t_ms, people: [{id, joints: {<joint>: {x, y, z, conf}}}]}], mirrored?, fps?, t0_pts_ms?, provenance?}"""
    frames = _list(doc, "frames", "pose3d")
    _optional(doc, "pose3d", ("mirrored", "fps", "t0_pts_ms", "provenance"))
    for i, f in enumerate(frames):
        at = f"pose3d.frames[{i}]"
        _int(f, "frame", at)
        _num(f, "t_ms", at)
        for k, p in enumerate(_list(f, "people", at)):
            pat = f"{at}.people[{k}]"
            _id(p, pat)
            joints = _dict(p, "joints", pat)
            if set(joints) != set(CANONICAL):
                raise ContractError(f"{pat}.joints", f"expected the 17 canonical joints, got {sorted(joints)}")
            for name, j in joints.items():
                for key in ("x", "y", "z", "conf"):
                    _num(j, key, f"{pat}.joints.{name}")
                if not 0 <= j["conf"] <= 1:
                    raise ContractError(f"{pat}.joints.{name}.conf", f"{j['conf']} not in [0, 1]")
    _increasing([f["frame"] for f in frames], "pose3d.frames[].frame")


def validate_tracks(doc) -> None:
    """{frames: [{frame, people: [{id, bbox: [x, y, w, h], mask_rle: {size, counts}, confidence}]}], t0_pts_ms?, provenance?}"""
    frames = _list(doc, "frames", "tracks")
    _optional(doc, "tracks", ("t0_pts_ms", "provenance"))
    for i, f in enumerate(frames):
        at = f"tracks.frames[{i}]"
        _int(f, "frame", at)
        ids = []
        for k, p in enumerate(_list(f, "people", at)):
            pat = f"{at}.people[{k}]"
            ids.append(_id(p, pat))
            bbox = p.get("bbox")
            if not (isinstance(bbox, list) and len(bbox) == 4 and all(is_number(v) for v in bbox) and bbox[2] >= 0 and bbox[3] >= 0):
                raise ContractError(f"{pat}.bbox", f"expected [x, y, w, h] finite with w, h >= 0, got {bbox!r}")
            rle = _dict(p, "mask_rle", pat)
            size, counts = rle.get("size"), rle.get("counts")
            if not (isinstance(size, list) and len(size) == 2 and all(isinstance(v, int) and v > 0 for v in size)
                    and isinstance(counts, (str, list)) and len(counts) > 0):
                raise ContractError(f"{pat}.mask_rle", "expected COCO RLE {size: [h, w] > 0, counts: non-empty}")
            _num(p, "confidence", pat)
            if not 0 <= p["confidence"] <= 1:
                raise ContractError(f"{pat}.confidence", f"{p['confidence']} not in [0, 1]")
        if len(set(ids)) != len(ids):
            raise ContractError(f"{at}.people", f"duplicate ids {ids}")
    _increasing([f["frame"] for f in frames], "tracks.frames[].frame")


def optional_top(doc: dict, extras: dict | None = None) -> dict:
    """The optional pose3d.json keys found in `doc`, overridden by the non-None values in `extras`."""
    out = {k: doc[k] for k in OPTIONAL_POSE3D if k in doc}
    out.update({k: v for k, v in (extras or {}).items() if k in OPTIONAL_POSE3D and v is not None})
    return out


def check_finite(node, at: str) -> None:
    """Raise ContractError at the first NaN, infinity or number too large for a double anywhere inside
    `node` (extra keys included)."""
    items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else ()
    for key, value in items:
        here = f"{at}[{key}]" if isinstance(key, int) else f"{at}.{key}"
        if isinstance(value, (dict, list)):
            check_finite(value, here)
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and not is_number(value):
            raise ContractError(here, "NaN or infinity is not allowed" if isinstance(value, float)
                                else "number too large for a double")


def write_json(path, doc, **dumps_kwargs) -> Path:
    """Write `doc` as JSON. NaN and infinity are refused (allow_nan=False) before the file is touched."""
    path = Path(path)
    check_finite(doc, path.name)
    text = json.dumps(doc, allow_nan=False, **dumps_kwargs)
    path.write_text(text)
    return path


def is_number(v) -> bool:
    """A JSON number Part 2 accepts: not a bool, not NaN or infinity, small enough to be a double."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        return math.isfinite(v)
    except OverflowError:  # an integer of hundreds of digits
        return False


def _num(obj, key, at):
    if not is_number(obj.get(key) if isinstance(obj, dict) else None):
        raise ContractError(f"{at}.{key}", "expected a finite number")


def _int(obj, key, at):
    if not isinstance(obj.get(key), int) or isinstance(obj.get(key), bool):
        raise ContractError(f"{at}.{key}", "expected an integer")


def _id(obj, at):
    v = obj.get("id")
    if not (isinstance(v, (int, str)) and not isinstance(v, bool)):
        raise ContractError(f"{at}.id", "expected an int or string id")
    return v


def _list(obj, key, at):
    if not isinstance(obj, dict) or not isinstance(obj.get(key), list):
        raise ContractError(f"{at}.{key}", "expected a list")
    return obj[key]


def _dict(obj, key, at):
    if not isinstance(obj.get(key), dict):
        raise ContractError(f"{at}.{key}", "expected an object")
    return obj[key]


def _optional(doc: dict, at: str, keys: tuple) -> None:
    """Type rules for those of the optional top-level `keys` that are present."""
    for key in (k for k in keys if k in doc):
        if key == "mirrored" and not isinstance(doc[key], bool):
            raise ContractError(f"{at}.{key}", "expected true or false")
        if key == "provenance" and not isinstance(doc[key], dict):
            raise ContractError(f"{at}.{key}", "expected an object")
        if key in ("fps", "t0_pts_ms"):
            _num(doc, key, at)
        if key == "fps" and doc[key] <= 0:
            raise ContractError(f"{at}.{key}", f"{doc[key]} not above 0")


def _increasing(xs, at):
    if any(b <= a for a, b in zip(xs, xs[1:])):
        raise ContractError(at, "frame indices must be strictly increasing")
