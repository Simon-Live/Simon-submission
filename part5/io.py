"""Read and validate the input clips.

Accepted formats (documented in docs/schemas.md):
- `simon.animation.v1`: Part 4's 30 fps `animation.json`, used for the expected clip and,
  until upstream says otherwise, for the follower's `skeleton.json`.
- `simon.skeleton.v1`: a skeleton sampled at keyframes (`keyframes[]` instead of `frames[]`).
"""
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

JOINTS = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder",
          "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip",
          "left_knee", "right_knee", "left_ankle", "right_ankle"]
FORMATS = {"simon.animation.v1": "frames", "simon.skeleton.v1": "keyframes"}
COORDINATE_FRAME = {"origin": "hip_midpoint", "x": "subject_left", "y": "world_up", "z": "anterior",
                    "position_unit": "metres", "angle_unit": "degrees"}
HIP_TOLERANCE_M = 0.01
MIN_CONF = 0.3


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


class InputError(ValueError):
    """An input file breaks the contract; the message says where."""


@dataclass
class Clip:
    format: str
    fps: float | None
    t: np.ndarray            # (F,) seconds
    positions: np.ndarray    # (F, 17, 3) metres, NaN where a joint is missing
    mask: np.ndarray         # (F, 17) True where the joint is usable
    interpolated: np.ndarray  # (F,) bool
    meta: dict = field(default_factory=dict)

    @property
    def n_frames(self):
        return len(self.t)


def load_clip(path):
    path = Path(path)
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise InputError(f"{path}: cannot read JSON ({e})") from e
    return parse_clip(doc, source=str(path))


def parse_clip(doc, source="<input>"):
    def fail(msg):
        raise InputError(f"{source}: {msg}")

    if not isinstance(doc, dict):
        fail("top level must be an object")
    fmt = doc.get("format")
    if not isinstance(fmt, str) or fmt not in FORMATS:
        fail(f"format must be one of {sorted(FORMATS)}, got {fmt!r}")
    cf = doc.get("coordinate_frame", {})
    if not isinstance(cf, dict):
        fail(f"coordinate_frame must be an object, got {type(cf).__name__}")
    for k, v in COORDINATE_FRAME.items():
        if k in cf and cf[k] != v:
            fail(f"coordinate_frame.{k} must be {v!r}, got {cf[k]!r}")
    if "joints" in doc and doc["joints"] != JOINTS:
        fail(f"joints must be the canonical 17 in order {JOINTS}")
    fps = doc.get("fps")
    if fps is not None and (not isinstance(fps, (int, float)) or fps <= 0):
        fail(f"fps must be a positive number, got {fps!r}")

    frames = doc.get(FORMATS[fmt])
    if not isinstance(frames, list) or not frames:
        fail(f"{FORMATS[fmt]} must be a non-empty list")

    n = len(frames)
    t = np.zeros(n)
    pos = np.full((n, len(JOINTS), 3), np.nan)
    mask = np.zeros((n, len(JOINTS)), bool)
    interp = np.zeros(n, bool)
    for i, fr in enumerate(frames):
        where = f"{FORMATS[fmt]}[{i}]"
        if not isinstance(fr, dict):
            fail(f"{where} must be an object, got {type(fr).__name__}")
        if "t" in fr:
            if not _is_number(fr["t"]):
                fail(f"{where}.t must be a number, got {fr['t']!r}")
            t[i] = fr["t"]
        elif fps:
            index = fr.get("index", i)
            if not _is_number(index):
                fail(f"{where}.index must be a number, got {index!r}")
            t[i] = index / fps
        else:
            fail(f"{where}: needs 't' (or a top-level fps)")
        interp[i] = bool(fr.get("interpolated", False))
        joints = fr.get("joints")
        if not isinstance(joints, dict):
            fail(f"{where}.joints must be an object")
        unknown = set(joints) - set(JOINTS)
        if unknown:
            fail(f"{where}.joints has unknown names {sorted(unknown)}")
        conf = fr.get("conf", {})
        if not isinstance(conf, dict):
            fail(f"{where}.conf must be an object of joint → 0..1, got {type(conf).__name__}")
        bad = {k: v for k, v in conf.items() if not _is_number(v)}
        if bad:
            fail(f"{where}.conf values must be numbers, got {bad!r}")
        for j, name in enumerate(JOINTS):
            p = joints.get(name)
            if p is None:
                continue
            if (not isinstance(p, list) or len(p) != 3
                    or not all(_is_number(c) for c in p)):
                fail(f"{where}.joints.{name} must be [x, y, z] finite numbers, got {p!r}")
            pos[i, j] = p
            mask[i, j] = conf.get(name, 1.0) >= MIN_CONF
    if np.any(np.diff(t) <= 0):
        fail("frame times must strictly increase")

    hip = (pos[:, JOINTS.index("left_hip")] + pos[:, JOINTS.index("right_hip")]) / 2
    off = np.nanmax(np.abs(hip)) if np.isfinite(hip).any() else 0.0
    if off > HIP_TOLERANCE_M:
        fail(f"hip midpoint must be at the origin per frame (max offset {off:.3f} m > {HIP_TOLERANCE_M} m)")

    meta = {k: doc[k] for k in ("set", "movement", "duration_s", "frame_count") if k in doc}
    meta["source"] = source
    return Clip(fmt, fps, t, pos, mask, interp, meta)
