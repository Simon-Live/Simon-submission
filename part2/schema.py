"""Validators for the shared files (README "Shared-file context"). Raise ValueError naming the path."""
import math

from part2.joints import CANONICAL


def validate_pose3d(doc) -> None:
    """{frames: [{frame, t_ms, people: [{id, joints: {<joint>: {x, y, z, conf}}}]}]}"""
    frames = _list(doc, "frames", "pose3d")
    for i, f in enumerate(frames):
        at = f"pose3d.frames[{i}]"
        _int(f, "frame", at)
        _num(f, "t_ms", at)
        for k, p in enumerate(_list(f, "people", at)):
            pat = f"{at}.people[{k}]"
            _id(p, pat)
            joints = _dict(p, "joints", pat)
            if set(joints) != set(CANONICAL):
                raise ValueError(f"{pat}.joints: expected the 17 canonical joints, got {sorted(joints)}")
            for name, j in joints.items():
                for key in ("x", "y", "z", "conf"):
                    _num(j, key, f"{pat}.joints.{name}")
                if not 0 <= j["conf"] <= 1:
                    raise ValueError(f"{pat}.joints.{name}.conf: {j['conf']} not in [0, 1]")
    _increasing([f["frame"] for f in frames], "pose3d.frames[].frame")


def validate_tracks(doc) -> None:
    """{frames: [{frame, people: [{id, bbox: [x, y, w, h], mask_rle: {size, counts}, confidence}]}]}"""
    frames = _list(doc, "frames", "tracks")
    for i, f in enumerate(frames):
        at = f"tracks.frames[{i}]"
        _int(f, "frame", at)
        ids = []
        for k, p in enumerate(_list(f, "people", at)):
            pat = f"{at}.people[{k}]"
            ids.append(_id(p, pat))
            bbox = p.get("bbox")
            if not (isinstance(bbox, list) and len(bbox) == 4 and all(_isnum(v) for v in bbox) and bbox[2] >= 0 and bbox[3] >= 0):
                raise ValueError(f"{pat}.bbox: expected [x, y, w, h] with w, h >= 0, got {bbox!r}")
            rle = _dict(p, "mask_rle", pat)
            if not (isinstance(rle.get("size"), list) and len(rle["size"]) == 2 and isinstance(rle.get("counts"), (str, list))):
                raise ValueError(f"{pat}.mask_rle: expected COCO RLE {{size: [h, w], counts}}")
            _num(p, "confidence", pat)
        if len(set(ids)) != len(ids):
            raise ValueError(f"{at}.people: duplicate ids {ids}")
    _increasing([f["frame"] for f in frames], "tracks.frames[].frame")


def _isnum(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _num(obj, key, at):
    if not _isnum(obj.get(key) if isinstance(obj, dict) else None):
        raise ValueError(f"{at}.{key}: expected a finite number")


def _int(obj, key, at):
    if not isinstance(obj.get(key), int) or isinstance(obj.get(key), bool):
        raise ValueError(f"{at}.{key}: expected an integer")


def _id(obj, at):
    v = obj.get("id")
    if not (isinstance(v, (int, str)) and not isinstance(v, bool)):
        raise ValueError(f"{at}.id: expected an int or string id")
    return v


def _list(obj, key, at):
    if not isinstance(obj, dict) or not isinstance(obj.get(key), list):
        raise ValueError(f"{at}.{key}: expected a list")
    return obj[key]


def _dict(obj, key, at):
    if not isinstance(obj.get(key), dict):
        raise ValueError(f"{at}.{key}: expected an object")
    return obj[key]


def _increasing(xs, at):
    if any(b <= a for a, b in zip(xs, xs[1:])):
        raise ValueError(f"{at}: frame indices must be strictly increasing")
