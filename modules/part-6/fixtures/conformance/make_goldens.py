#!/usr/bin/env python3
"""Writes the golden suite for the format adapters into fixtures/conformance/formats/.

Deterministic and stdlib only: the same run always writes the same bytes. Every file is a small
synthetic movement in the shape one neighbour part writes (Part 1 keyframes, Part 3 skeleton,
Part 4 animation, skeleton keys and keyframes), plus invalid files for every error of
docs/specs/formats.md (AC-F09). `cases.json` lists what each reader must say about each file.

The expected summaries are computed here from the parameters used to build each file (frame
counts, rates, names, the joint values written), never by importing part6/formats.py. The held
skeleton animation is worked out a second way, with exact fractions, so the suite tests the
readers instead of recording them.

Case fields: `file` (golden file or null), `kind` (keyframes, skeleton, animation, detect or
playable), `expect` (a summary, `{"kind": ...}` for detect, or `{"error": "<exact message>"}`).
Optional: `name` (the file name handed to the reader, default `file`), `expect_animation` (the
summary of the skeleton played as its own animation), `animation` and `skeleton` (files for a
playable case), `error_id` (the E-id of an error case, E1 to E16) and `note`.

A parse-level case is a file the strict JSON parse refuses before any reader runs: its expectation
is `{"error": "<file>: is not valid JSON"}` and it has no `error_id`. The runners read every file
the way the product does (part6.validate.parse_json in Python, parseStrictJson from web/formats.js
in JavaScript), so a file with a number beyond a double lands here, not in E8, and so does a file
with a byte that is not valid UTF-8. There are exactly two: invalid-json-number-overflow.json and
invalid-json-bad-utf8.json (the only golden file that is not valid UTF-8, so it is written as bytes).

Run: python3 fixtures/conformance/make_goldens.py
"""
from __future__ import annotations

import json
import math
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

OUT = Path(__file__).resolve().parent / "formats"

A1, AV1 = "simon.animation/1", "simon.animation.v1"
S1, SV1 = "simon.skeleton/1", "simon.skeleton.v1"
K1, KV1 = "simon.keyframes/part1", "simon.keyframes.v1"
IDS = {"animation": f"{A1}, {AV1}", "skeleton": f"{S1}, {SV1}", "keyframes": f"{K1}, {KV1}"}

JOINTS = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
    "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle",
)
BASE = {
    "nose": (0.0, 0.68, 0.10), "left_eye": (0.03, 0.72, 0.08), "right_eye": (-0.03, 0.72, 0.08),
    "left_ear": (0.075, 0.70, 0.02), "right_ear": (-0.075, 0.70, 0.02),
    "left_shoulder": (0.19, 0.50, 0.0), "right_shoulder": (-0.19, 0.50, 0.0),
    "left_elbow": (0.21, 0.22, 0.0), "right_elbow": (-0.21, 0.22, 0.0),
    "left_wrist": (0.21, -0.04, 0.02), "right_wrist": (-0.21, -0.04, 0.02),
    "left_hip": (0.09, 0.0, 0.0), "right_hip": (-0.09, 0.0, 0.0),
    "left_knee": (0.10, -0.43, 0.02), "right_knee": (-0.10, -0.43, 0.02),
    "left_ankle": (0.10, -0.85, 0.0), "right_ankle": (-0.10, -0.85, 0.0),
}
# Per joint, how far y and z move at full squat depth (hip-centred frame, metres).
REACH = {
    "nose": (0.0, 0.12), "left_eye": (0.0, 0.12), "right_eye": (0.0, 0.12),
    "left_ear": (0.0, 0.12), "right_ear": (0.0, 0.12),
    "left_shoulder": (0.0, 0.12), "right_shoulder": (0.0, 0.12),
    "left_elbow": (0.12, 0.25), "right_elbow": (0.12, 0.25),
    "left_wrist": (0.42, 0.32), "right_wrist": (0.42, 0.32),
    "left_knee": (0.08, 0.25), "right_knee": (0.08, 0.25),
    "left_ankle": (0.30, 0.0), "right_ankle": (0.30, 0.0),
}
UNITS_MS = {"length": "m", "angle": "deg", "time": "ms"}
FRAME = {"origin": "hip_midpoint", "x": "subject_left", "y": "body_up", "z": "anterior",
         "up_source": "standing_frames"}
COORD4 = {"origin": "hip_midpoint", "x": "subject_left", "y": "world_up", "z": "anterior",
          "position_unit": "metres", "angle_unit": "degrees"}

FILES = {}
CASES = []


# ---- poses and joint spellings ---------------------------------------------------------------

def depth(i, n):
    """Squat depth of frame i of n: a triangle from 0 up to 1 and back, 4 decimals."""
    return 0.0 if n < 2 else round(1.0 - abs(2.0 * i / (n - 1) - 1.0), 4)


def pose(d, shift=0.0):
    """The 17 joints as {name: [x, y, z]} at depth d; `shift` moves the whole body along x."""
    out = {}
    for name in JOINTS:
        x, y, z = BASE[name]
        dy, dz = REACH.get(name, (0.0, 0.0))
        out[name] = [round(x + shift, 4), round(y + dy * d, 4), round(z + dz * d, 4)]
    return out


def as_conf(p):
    return {n: {"x": v[0], "y": v[1], "z": v[2], "conf": 1.0} for n, v in p.items()}


def as_xyz(p):
    return {n: {"x": v[0], "y": v[1], "z": v[2]} for n, v in p.items()}


def as_arr(p):
    return {n: list(v) for n, v in p.items()}


def ms(i, fps):
    """Part 3 and Part 6 frame time in milliseconds, 3 decimals."""
    return round(i * 1000 / fps, 3)


# ---- registry --------------------------------------------------------------------------------

def put(name, data):
    FILES[name] = json.dumps(data, separators=(",", ":")) + "\n"


def put_raw(name, text):
    """A file written as given: text (written as UTF-8) or bytes (written untouched)."""
    FILES[name] = text


def case(file, kind, expect, **extra):
    CASES.append({"file": file, "kind": kind, "expect": expect, **extra})


def bad(name, kind, data, error_id, message, raw=None, **extra):
    """An invalid file and the exact message its reader must raise."""
    if raw is None:
        put(name, data)
    else:
        put_raw(name, raw)
    case(name, kind, {"error": message}, error_id=error_id, **extra)


def unparsable(name, kind, raw, **extra):
    """A file the strict parse refuses, so no reader runs and the case has no `error_id`."""
    put_raw(name, raw)
    case(name, kind, {"error": not_json(name)}, **extra)


# ---- expected values, from parameters -----------------------------------------------------------

def exp_anim(fmt, by, fps, times, flags, poses):
    n = len(times)
    return {"kind": "animation", "format": fmt, "detected_by": by, "source_kind": "animation",
            "fps": float(fps), "frame_count": n, "duration_s": times[-1],
            "interpolated_count": sum(1 for f in flags if f), "held": False,
            "nose_first": poses[0]["nose"], "left_ankle_mid": poses[n // 2]["left_ankle"],
            "right_wrist_last": poses[-1]["right_wrist"]}


def exp_skel(fmt, by, frame_count, present, key_names):
    return {"kind": "skeleton", "format": fmt, "detected_by": by, "frame_count": frame_count,
            "present_count": present, "key_count": len(key_names), "key_names": list(key_names)}


def exp_keys(fmt, by, clock_fps, marks):
    """marks: [(name, t, frame at 30 fps)] already in time order."""
    return {"kind": "keyframes", "format": fmt, "detected_by": by, "clock_fps": clock_fps,
            "mark_count": len(marks), "marks": [[m[0], m[1]] for m in marks],
            "frames_at_30": [m[2] for m in marks]}


def sec(value):
    """A seconds value as the exact decimal written in the file."""
    return Fraction(repr(value))


def millis(value):
    return Fraction(repr(value)) / 1000


def exp_held(fmt, by, samples):
    """Summary of a skeleton played at 30 fps with poses held (AC-F07), by exact arithmetic.

    samples: [(time in seconds as Fraction, pose)] in file order.
    """
    s = sorted(samples, key=lambda item: item[0])
    n = max(1, math.floor(s[-1][0] * 30 + Fraction(1, 2)) + 1)
    shown, flags = [], []
    for k in range(n):
        limit = Fraction(k, 30) + Fraction(1, 10 ** 6)
        chosen = s[0]
        for sample in s:
            if sample[0] <= limit:
                chosen = sample
        shown.append(chosen[1])
        flags.append(all(math.floor(x[0] * 30 + Fraction(1, 2)) != k for x in s))
    return {"kind": "animation", "format": fmt, "detected_by": by, "source_kind": "skeleton",
            "fps": 30, "frame_count": n, "duration_s": (n - 1) / 30,
            "interpolated_count": sum(1 for f in flags if f), "held": True,
            "nose_first": shown[0]["nose"], "left_ankle_mid": shown[n // 2]["left_ankle"],
            "right_wrist_last": shown[-1]["right_wrist"]}


# ---- error messages, typed from the AC-F09 table -----------------------------------------------

def e1(f):
    return f"{f}: is not a JSON object"


def e2(f, field, value, kind):
    shown = value if len(value) <= 60 else value[:57] + "..."
    return f'{f}: {field} "{shown}" is not a version Part 6 reads (it reads {IDS[kind]})'


def e3(f, ident, other, kind):
    return f"{f}: holds {ident}, which belongs in {other}.json, not {kind}.json"


def e4(f, kind):
    return f"{f}: has no format or schema field and its shape matches no {kind} reader"


def e5(f):
    return f"{f}: fps: must be a number above 0"


def e6(f):
    return f"{f}: frames: must be a non-empty list"


def e7(f, where, joint):
    return f"{f}: {where}.joints.{joint}: missing"


def e8(f, where, joint):
    return f"{f}: {where}.joints.{joint}: needs three finite numbers"


def not_json(f):
    """The sentence for a file the strict parse refuses (no E-id: no reader runs)."""
    return f"{f}: is not valid JSON"


def e9(f, where):
    return f"{f}: {where}: has no person"


def e9s(f):
    return f"{f}: no frame has a person and there are no key poses"


def e10(f, where):
    return f"{f}: {where}: time must be later than the frame before"


def e11(f, where):
    return f"{f}: {where}: needs t_ms or t"


def e11_key(f, where):
    return f"{f}: {where}: needs t or index"


E12 = "nothing to play: add an animation.json or a skeleton.json"


def e13(f, field):
    return f"{f}: {field}: must be a list"


def e14(f, where, v1=False):
    need = "t, or index with fps" if v1 else "t_ms, or frame with fps"
    return f"{f}: {where}: needs {need}"


def e15(f, where):
    return f"{f}: {where}.name: must be a string"


def e16(f, where):
    return f"{f}: {where}: time must be from 0 to two hours"


# ---- file builders -----------------------------------------------------------------------------

def a1_data(n, fps=30.0, with_t=True):
    frames = []
    for i in range(n):
        fr = {"frame": i}
        if with_t:
            fr["t_ms"] = ms(i, fps)
        fr["interpolated"] = False
        fr["people"] = [{"id": 0, "joints": as_conf(pose(depth(i, n)))}]
        frames.append(fr)
    return {"schema": A1, "units": UNITS_MS, "frame": FRAME, "joints": list(JOINTS),
            "fps": fps, "frames": frames}


def v1_data(n, fps=30, extra=None):
    frames = [{"index": i, "t": round(i / fps, 6), "interpolated": False,
               "joints": as_arr(pose(depth(i, n)))} for i in range(n)]
    data = {"format": AV1, "fps": fps, "frame_count": n, "joints": list(JOINTS), "frames": frames}
    data.update(extra or {})
    return data


def sk1_data(n, fps=15, extra=None):
    frames = [{"frame": i, "t_ms": ms(i, fps),
               "people": [{"id": 0, "joints": as_conf(pose(depth(i, n))), "flips_repaired": []}]}
              for i in range(n)]
    data = {"schema": S1, "units": UNITS_MS, "frame": FRAME, "joints": list(JOINTS),
            "bone_lengths_m": {"left_thigh": 0.43, "right_thigh": 0.43}, "frames": frames}
    data.update(extra or {})
    return data


def sk_keys(indices, names, joints_as=as_conf):
    return [{"index": idx, "t": round(idx / 30, 6), "name": nm,
             "joints": joints_as(pose(depth(j, len(indices))))}
            for j, (idx, nm) in enumerate(zip(indices, names))]


def skv1_data(n=3):
    return {"format": SV1, "schema": S1, "set": "exercise", "movement": "squat",
            "units": {"length": "m", "angle": "deg", "time": "s"}, "joints": list(JOINTS),
            "keyframes": sk_keys(list(range(0, 15 * n, 15)), [f"k{j}" for j in range(n)])}


def mark(name, frame=None, t_ms=None):
    m = {"name": name}
    if frame is not None:
        m["frame"] = frame
    if t_ms is not None:
        m["t_ms"] = t_ms
    return m


def p1_data(reps, fps=30.0, pid=0, extra=None):
    """Part 1 shape. reps: list of mark lists, one per repetition."""
    data = {"video": "video.webm", "fps": fps, "analysis_fps": 8.0, "quality": {"verdict": "fine"},
            "people": [{"id": pid, "repetitions": [
                {"rep": r + 1, "movement": "squat", "keyframes": marks} for r, marks in enumerate(reps)]}]}
    data.update(extra or {})
    return data


def v1k_data(items, fps=30, extra=None):
    data = {"format": KV1, "set": "exercise", "movement": "squat", "fps": fps, "keyframes": items}
    data.update(extra or {})
    return data


# ---- valid animations ----------------------------------------------------------------------------

def animations():
    n = 13
    poses = [pose(depth(i, n)) for i in range(n)]
    flags = [i % 2 == 1 for i in range(n)]
    d = a1_data(n)
    for fr, flag in zip(d["frames"], flags):
        fr["interpolated"] = flag
    put("animation-1-part6.json", d)
    times = [ms(i, 30.0) / 1000 for i in range(n)]
    case("animation-1-part6.json", "animation", exp_anim(A1, "version", 30.0, times, flags, poses))

    n = 9
    poses = [pose(depth(i, n)) for i in range(n)]
    d = a1_data(n, fps=15.0, with_t=False)
    d["frames"][4]["t_ms"] = "later"
    for i in (1, 3, 5):
        d["frames"][i]["interpolated"] = True
    for i in (0, 2, 4, 6):
        del d["frames"][i]["interpolated"]
    put("animation-1-no-t-ms.json", d)
    flags = [i in (1, 3, 5) for i in range(n)]
    case("animation-1-no-t-ms.json", "animation",
         exp_anim(A1, "version", 15.0, [i / 15.0 for i in range(n)], flags, poses),
         note="t_ms missing or not a number: time is frame index over fps")

    n = 5
    poses = [pose(depth(i, n)) for i in range(n)]
    d = a1_data(n)
    for i, fr in enumerate(d["frames"]):
        fr["t"] = 50.0 + i
    put("animation-1-both-t.json", d)
    case("animation-1-both-t.json", "animation",
         exp_anim(A1, "version", 30.0, [ms(i, 30.0) / 1000 for i in range(n)], [False] * n, poses),
         note="t_ms and t both present: the /1 reader prefers t_ms")

    n = 64  # 2.1 s: the conformance entries and the fake Part 4 processor play this file
    poses = [pose(depth(i, n)) for i in range(n)]
    flags = [i % 2 == 1 for i in range(n)]
    d = v1_data(n, 30, {"duration_s": round((n - 1) / 30, 6), "movement": "squat", "set": "exercise",
                        "coordinate_frame": COORD4,
                        "bones": [{"name": "spine", "parent": "hip_mid", "child": "shoulder_mid",
                                   "length_m": 0.49}]})
    for fr, flag in zip(d["frames"], flags):
        fr["interpolated"] = flag
    put("animation-v1-part4.json", d)
    case("animation-v1-part4.json", "animation",
         exp_anim(AV1, "version", 30, [round(i / 30, 6) for i in range(n)], flags, poses))

    indices = [0, 1, 2, 3, 5, 6, 8]
    n = len(indices)
    poses = [pose(depth(i, n)) for i in range(n)]
    frames = []
    for j, idx in enumerate(indices):
        joints = {k: v + [0.9] for k, v in as_arr(poses[j]).items()}
        joints["pelvis"] = [0.0, 0.0, 0.0]
        frames.append({"index": idx, "interpolated": j % 3 == 0, "joints": joints})
    put("animation-v1-index-only.json", {"format": AV1, "fps": 24, "frames": frames})
    case("animation-v1-index-only.json", "animation",
         exp_anim(AV1, "version", 24, [idx / 24 for idx in indices],
                  [j % 3 == 0 for j in range(n)], poses),
         note="no t: time is index over fps; arrays longer than 3 and extra joints are ignored")

    n = 5
    poses = [pose(depth(i, n)) for i in range(n)]
    frames = [{"joints": as_xyz(poses[i])} for i in range(n)]
    put("animation-v1-bare.json", {"format": AV1, "fps": 10, "frames": frames})
    case("animation-v1-bare.json", "animation",
         exp_anim(AV1, "version", 10, [i / 10 for i in range(n)], [False] * n, poses),
         note="no t and no index: time is the position in the file over fps")

    n = 4
    poses = [pose(depth(i, n)) for i in range(n)]
    d = v1_data(n, 30)
    for i, fr in enumerate(d["frames"]):
        fr["t_ms"] = 9000 + i
    put("animation-v1-both-t.json", d)
    case("animation-v1-both-t.json", "animation",
         exp_anim(AV1, "version", 30, [round(i / 30, 6) for i in range(n)], [False] * n, poses),
         note="t and t_ms both present: the v1 reader prefers t")

    n = 6
    poses = [pose(depth(i, n)) for i in range(n)]
    d = a1_data(n)
    del d["schema"], d["units"], d["frame"], d["joints"]
    put("animation-shape-people.json", d)
    case("animation-shape-people.json", "animation",
         exp_anim(A1, "shape", 30.0, [ms(i, 30.0) / 1000 for i in range(n)], [False] * n, poses),
         note="no version field: fps and frames[0].people")

    frames = [{"t": round(i / 30, 6), "joints": as_xyz(poses[i])} for i in range(n)]
    put("animation-shape-joints.json", {"fps": 30, "frames": frames})
    case("animation-shape-joints.json", "animation",
         exp_anim(AV1, "shape", 30, [round(i / 30, 6) for i in range(n)], [False] * n, poses),
         note="no version field: fps and frames[0].joints")

    n = 5
    real = [pose(depth(i, n)) for i in range(n)]
    decoy = pose(0.77, shift=1.0)
    d = a1_data(n)
    people = [
        [{"id": 1, "joints": as_conf(decoy)}, {"id": 0, "joints": as_conf(real[0])}],
        [{"id": 0, "joints": as_conf(real[1])}],
        [{"id": 7, "joints": as_conf(real[2])}],
        [{"id": 0, "joints": as_conf(real[3])}],
        [{"id": 0, "joints": as_conf(real[4])}, {"id": 1, "joints": as_conf(decoy)}],
    ]
    for fr, group in zip(d["frames"], people):
        fr["people"] = group
    put("animation-1-people-choice.json", d)
    case("animation-1-people-choice.json", "animation",
         exp_anim(A1, "version", 30.0, [ms(i, 30.0) / 1000 for i in range(n)], [False] * n, real),
         note="person with id 0, else the first person")

    put("animation-1-single.json", a1_data(1))
    case("animation-1-single.json", "animation",
         exp_anim(A1, "version", 30.0, [0.0], [False], [pose(0.0)]),
         note="one frame: duration 0, plays as a still")


# ---- valid skeletons -----------------------------------------------------------------------------

def skeletons():
    n = 33  # 2.13 s at 15 fps; the middle held frame is sample 16, whose t_ms 1066.667 is rounded up
    poses = [pose(depth(i, n)) for i in range(n)]
    d = sk1_data(n, 15, {"person": {"id": 0, "rule": "most_frames", "frames_present": n,
                                    "frames_dropped": 0},
                         "mirror": {"setting": "auto", "applied": False}})
    put("skeleton-1-part3.json", d)
    held = exp_held(S1, "version", [(millis(ms(i, 15)), poses[i]) for i in range(n)])
    case("skeleton-1-part3.json", "skeleton", exp_skel(S1, "version", n, n, []),
         expect_animation=held, note="Part 3 shape at 15 fps")

    names = ["stand", "descend", "bottom", "ascend", "stand"]
    idx = [0, 16, 32, 48, 63]
    put("skeleton-v1-keys-part4.json", skv1_data_for(idx, names))
    kp = [pose(depth(j, len(idx))) for j in range(len(idx))]
    held = exp_held(SV1, "version", [(sec(round(i / 30, 6)), kp[j]) for j, i in enumerate(idx)])
    case("skeleton-v1-keys-part4.json", "skeleton", exp_skel(SV1, "version", 0, 0, names),
         expect_animation=held, note="Part 4 keyframes only, format and schema both present")

    n = 6
    poses = [pose(depth(i, n)) for i in range(n)]
    d = sk1_data(n, 15)
    d["part4"] = {"format": SV1, "keyframes": sk_keys([0, 30, 60], ["low", "high", "low"])}
    put("skeleton-mixed-nested.json", d)
    held = exp_held(S1, "version", [(millis(ms(i, 15)), poses[i]) for i in range(n)])
    case("skeleton-mixed-nested.json", "skeleton", exp_skel(S1, "version", n, n, ["low", "high", "low"]),
         expect_animation=held, note="frames plus a Part 3 --view part4 block in one object field")

    n = 4
    poses = [pose(depth(i, n)) for i in range(n)]
    d = sk1_data(n, 30)
    d = {"format": SV1, **d, "keyframes": sk_keys([0, 90], ["first", "last"], as_arr)}
    put("skeleton-mixed-toplevel.json", d)
    held = exp_held(SV1, "version", [(millis(ms(i, 30)), poses[i]) for i in range(n)])
    case("skeleton-mixed-toplevel.json", "skeleton", exp_skel(SV1, "version", n, n, ["first", "last"]),
         expect_animation=held, note="format v1 and schema /1 on one file with frames and keys")

    n = 4
    poses = [pose(depth(i, n)) for i in range(n)]
    d = sk1_data(n, 15)
    for field, names in (("B", ["bee"]), ("9", ["nine"]), ("10", ["ten-a", "ten-b"]), ("A", ["ay"])):
        d[field] = {"format": SV1, "keyframes": sk_keys(list(range(0, 30 * len(names), 30)), names)}
    put("skeleton-mixed-several-blocks.json", d)
    held = exp_held(S1, "version", [(millis(ms(i, 15)), poses[i]) for i in range(n)])
    case("skeleton-mixed-several-blocks.json", "skeleton",
         exp_skel(S1, "version", n, n, ["ten-a", "ten-b"]), expect_animation=held,
         note="several key blocks: the first in sorted key order, here 10 (file order says B, "
              "integer-first object order says 9)")

    n = 8
    poses = [pose(depth(i, n)) for i in range(n)]
    d = sk1_data(n, 10)
    for i in range(n):
        d["frames"][i]["t_ms"] = i * 100.0
    gone = (0, 1, 5, 7)
    for i in gone:
        d["frames"][i]["people"] = []
    put("skeleton-1-dropped.json", d)
    here = [i for i in range(n) if i not in gone]
    held = exp_held(S1, "version", [(millis(i * 100.0), poses[i]) for i in here])
    case("skeleton-1-dropped.json", "skeleton", exp_skel(S1, "version", n, len(here), []),
         expect_animation=held, note="frames with the person dropped are not samples")

    n = 6
    poses = [pose(depth(i, n)) for i in range(n)]
    d = sk1_data(n, 30)
    del d["schema"], d["units"], d["frame"], d["joints"], d["bone_lengths_m"]
    d["frames"][0]["people"] = []
    put("skeleton-shape-frames.json", d)
    held = exp_held(S1, "shape", [(millis(ms(i, 30)), poses[i]) for i in range(1, n)])
    case("skeleton-shape-frames.json", "skeleton", exp_skel(S1, "shape", n, n - 1, []),
         expect_animation=held, note="no version field; frame 0 has an empty people list")

    idx = [0, 15, 30, 45]
    items = sk_keys(idx, ["start", "x", "mid", "end"], as_arr)
    for it in items:
        del it["t"]
    del items[1]["name"]
    put("skeleton-shape-keys.json", {"keyframes": items})
    kp = [pose(depth(j, 4)) for j in range(4)]
    held = exp_held(SV1, "shape", [(Fraction(i, 30), kp[j]) for j, i in enumerate(idx)])
    case("skeleton-shape-keys.json", "skeleton", exp_skel(SV1, "shape", 0, 0, ["start", "", "mid", "end"]),
         expect_animation=held, note="no version field; no t so index over 30; a key without a name")

    poses = [pose(0.2), pose(0.4), pose(0.6), pose(0.8)]
    d = sk1_data(4, 15)
    times = [("t", 0.2), ("t_ms", 0.0), ("t", 0.1), ("t_ms", 300.0)]
    for fr, p, (field, value) in zip(d["frames"], poses, times):
        del fr["t_ms"]
        fr[field] = value
        fr["people"][0]["joints"] = as_conf(p)
    d["frames"][1]["t"] = 9.0
    put("skeleton-1-t-seconds.json", d)
    held = exp_held(S1, "version", [(sec(0.2), poses[0]), (sec(0.0), poses[1]),
                                    (sec(0.1), poses[2]), (millis(300.0), poses[3])])
    case("skeleton-1-t-seconds.json", "skeleton", exp_skel(S1, "version", 4, 4, []),
         expect_animation=held, note="t in seconds, out of order, t_ms wins over t")

    d = sk1_data(1, 15)
    put("skeleton-1-single.json", d)
    held = exp_held(S1, "version", [(Fraction(0), pose(0.0))])
    case("skeleton-1-single.json", "skeleton", exp_skel(S1, "version", 1, 1, []),
         expect_animation=held, note="one pose: frame count 1, duration 0")


def skv1_data_for(idx, names):
    return {"format": SV1, "schema": S1, "set": "exercise", "movement": "squat",
            "units": {"length": "m", "angle": "deg", "time": "s"}, "joints": list(JOINTS),
            "standard": {"stature_m": 1.7}, "bone_lengths_m": {"left_thigh": 0.4165},
            "keyframes": sk_keys(idx, names)}


# ---- valid key frames ------------------------------------------------------------------------------

def keyframes():
    d = p1_data([[mark("start", 15, 500), mark("bottom", 60, 2000), mark("top", 105, 3500)],
                 [mark("start", 120, 4000), mark("bottom", 165, 5500), mark("top", 210, 7000)]])
    put("keyframes-part1.json", d)
    marks = [("start", 0.5, 15), ("bottom", 2.0, 60), ("top", 3.5, 105),
             ("start", 4.0, 120), ("bottom", 5.5, 165), ("top", 7.0, 210)]
    case("keyframes-part1.json", "keyframes", exp_keys(K1, "shape", 30.0, marks))

    d = p1_data([[mark("start", 120, 2000), mark("bottom", 150, 2500), mark("top", 180, 3000)],
                 [mark("start", 240, 4000), mark("bottom", 270, 4500), mark("top", 300, 5000)]], fps=60.0)
    put("keyframes-part1-60fps.json", d)
    marks = [("start", 2.0, 60), ("bottom", 2.5, 75), ("top", 3.0, 90),
             ("start", 4.0, 120), ("bottom", 4.5, 135), ("top", 5.0, 150)]
    case("keyframes-part1-60fps.json", "keyframes", exp_keys(K1, "shape", 60.0, marks),
         note="a mark at frame 120 of a 60 fps video is frame 60 of a 30 fps animation")

    d = p1_data([[mark("start", 90), mark("bottom", 150), mark("dup", 90), mark("top", 30, 3500),
                  mark("x", 60, -5), mark("zero", None, 0)]], fps=60.0)
    put("keyframes-part1-no-tms.json", d)
    marks = [("zero", 0.0, 0), ("x", 1.0, 30), ("start", 1.5, 45), ("dup", 1.5, 45),
             ("bottom", 2.5, 75), ("top", 3.5, 105)]
    case("keyframes-part1-no-tms.json", "keyframes", exp_keys(K1, "shape", 60.0, marks),
         note="frame over fps when t_ms is missing or negative; t_ms 0 is valid; equal times keep file order")

    d = {"video": None, "fps": 30.0, "people": [
        {"id": 1, "repetitions": [{"rep": 1, "keyframes": [mark("decoy", None, 100)]}]},
        {"id": 0, "repetitions": [
            {"movement": "lunge", "keyframes": [mark("top", None, 3000), mark("start", None, 0)]},
            {"movement": "lunge", "keyframes": [mark("bottom", None, 4500)]}]}]}
    put("keyframes-part1-people.json", d)
    marks = [("start", 0.0, 0), ("top", 3.0, 90), ("bottom", 4.5, 135)]
    case("keyframes-part1-people.json", "keyframes", exp_keys(K1, "shape", 30.0, marks),
         note="person with id 0, else the first; marks come out in time order")

    put("keyframes-part1-empty.json", {"video": None, "people": []})
    case("keyframes-part1-empty.json", "keyframes", exp_keys(K1, "shape", None, []),
         note="no marks is valid; no fps gives a null clock")

    d = {"people": [{"id": 0, "repetitions": [{"rep": 1, "keyframes": [
        mark("a", None, 1000), mark("b", 99, 2000)]}]}]}
    put("keyframes-part1-no-fps.json", d)
    case("keyframes-part1-no-fps.json", "keyframes",
         exp_keys(K1, "shape", None, [("a", 1.0, 30), ("b", 2.0, 60)]))

    items = [{"index": i, "t": round(i / 30, 6), "name": nm} for i, nm in
             [(0, "stand"), (16, "descend"), (32, "bottom"), (40, "hold"), (48, "rise"), (63, "stand")]]
    put("keyframes-v1.json", v1k_data(items, 30, {"duration_s": 2.1, "frame_count": 64}))
    marks = [(nm, round(i / 30, 6), i) for i, nm in
             [(0, "stand"), (16, "descend"), (32, "bottom"), (40, "hold"), (48, "rise"), (63, "stand")]]
    case("keyframes-v1.json", "keyframes", exp_keys(KV1, "version", 30.0, marks))

    items = [{"index": 12, "name": "a"}, {"index": 24, "t": 0.75, "name": "b"},
             {"index": 0, "name": "z"}, {"t": 2.0, "name": "c"}]
    d = v1k_data(items, 24)
    del d["format"]
    put("keyframes-v1-index.json", d)
    marks = [("z", 0.0, 0), ("a", 0.5, 15), ("b", 0.75, 23), ("c", 2.0, 60)]
    case("keyframes-v1-index.json", "keyframes", exp_keys(KV1, "shape", 24.0, marks),
         note="t wins over index; index over fps otherwise; 0.75 s is 22.5 frames, which rounds up to 23")

    put("keyframes-v1-empty.json", v1k_data([], 30))
    case("keyframes-v1-empty.json", "keyframes", exp_keys(KV1, "version", 30.0, []))


# ---- detect and playable ---------------------------------------------------------------------------

def detections():
    rows = [
        ("animation-v1-part4.json", None, "animation", "version id"),
        ("skeleton-v1-keys-part4.json", None, "skeleton", "version id (format and schema)"),
        ("skeleton-1-part3.json", None, "skeleton", "version id (schema)"),
        ("keyframes-v1.json", None, "keyframes", "version id"),
        ("animation-v1-part4.json", "skeleton.json", "animation", "version id beats the file name"),
        ("keyframes-part1.json", "take-1.json", "keyframes", "shape: people"),
        ("animation-shape-people.json", "movement.json", "animation", "shape: fps with frames"),
        ("skeleton-shape-frames.json", "movement.json", "skeleton", "shape: frames without fps"),
        ("skeleton-shape-keys.json", "x.json", "skeleton", "shape: keyframes[0] with joints"),
        ("keyframes-v1-index.json", "x.json", "keyframes", "shape: keyframes without joints"),
        ("animation-shape-people.json", "My-SKELETON-take.json", "skeleton", "name beats shape, any case"),
        ("animation-shape-people.json", "keyframe-skeleton-animation.json", "keyframes",
         "name order: keyframe, skeleton, animation"),
        ("invalid-e2-animation-version.json", "animation-v2.json", "animation",
         "an unknown version falls to the name; the reader then says E2"),
    ]
    for file, name, kind, note in rows:
        extra = {"name": name} if name else {}
        case(file, "detect", {"kind": kind}, note=note, **extra)
    case("invalid-e4-shape.json", "detect",
         {"error": "notes.json: has no format or schema field and its shape matches no reader"},
         name="notes.json", error_id="E4")
    case("invalid-e1-array.json", "detect", {"error": e1("x.json")}, name="x.json", error_id="E1")


def playables():
    a, s = "animation-v1-part4.json", "skeleton-1-part3.json"
    ea = next(c["expect"] for c in CASES if c["file"] == a and c["kind"] == "animation")
    es = next(c["expect_animation"] for c in CASES if c["file"] == s and c["kind"] == "skeleton")
    case(a, "playable", ea, animation=a, skeleton=s, note="both: the animation plays")
    case(a, "playable", ea, animation=a, skeleton=None, note="animation only")
    case(s, "playable", es, animation=None, skeleton=s, note="skeleton only: played as its own animation")
    case(None, "playable", {"error": E12}, animation=None, skeleton=None, error_id="E12")


# ---- invalid files ----------------------------------------------------------------------------------

def invalid_framing():
    bad("invalid-e1-array.json", "animation", [1, 2, 3], "E1", e1("invalid-e1-array.json"))
    bad("invalid-e1-string.json", "keyframes", "keyframes", "E1", e1("invalid-e1-string.json"))

    d = a1_data(2)
    del d["schema"]
    d["format"] = "simon.animation.v2"
    bad("invalid-e2-animation-version.json", "animation", d, "E2",
        e2("invalid-e2-animation-version.json", "format", "simon.animation.v2", "animation"))
    d = sk1_data(2)
    d["schema"] = "simon.skeleton/2"
    bad("invalid-e2-skeleton-schema.json", "skeleton", d, "E2",
        e2("invalid-e2-skeleton-schema.json", "schema", "simon.skeleton/2", "skeleton"))
    d = p1_data([[mark("a", 1, 10)]])
    d["format"] = "keyframes-v9"
    bad("invalid-e2-keyframes-format.json", "keyframes", d, "E2",
        e2("invalid-e2-keyframes-format.json", "format", "keyframes-v9", "keyframes"))
    d = a1_data(2)
    d["format"], d["schema"] = "x.v9", "y/2"
    bad("invalid-e2-both-fields.json", "animation", d, "E2",
        e2("invalid-e2-both-fields.json", "format", "x.v9", "animation"))
    f = "animation-unknown-format-known-schema.json"
    d = a1_data(3)
    d["format"] = "simon.animation.v9"
    bad(f, "animation", d, "E2", e2(f, "format", "simon.animation.v9", "animation"),
        note="AC-F02: an unknown format is E2 even when schema is a known id; never read by a guess")
    n = 3
    d = a1_data(n)
    d["format"] = 2
    put("animation-1-format-not-text.json", d)
    case("animation-1-format-not-text.json", "animation",
         exp_anim(A1, "version", 30.0, [ms(i, 30.0) / 1000 for i in range(n)], [False] * n,
                  [pose(depth(i, n)) for i in range(n)]),
         note="a format that is not a string is skipped; schema decides")
    f = "invalid-e3-format-decides.json"
    d = sk1_data(2)
    d["format"] = AV1
    bad(f, "skeleton", d, "E3", e3(f, AV1, "animation", "skeleton"),
        note="a string format decides, so another kind's id there is E3 even when schema fits")

    case("animation-v1-part4.json", "skeleton", {"error": e3("animation-v1-part4.json", AV1, "animation", "skeleton")},
         error_id="E3")
    case("skeleton-1-part3.json", "keyframes", {"error": e3("skeleton-1-part3.json", S1, "skeleton", "keyframes")},
         error_id="E3")
    case("keyframes-v1.json", "animation", {"error": e3("keyframes-v1.json", KV1, "keyframes", "animation")},
         error_id="E3")

    bad("invalid-e4-shape.json", "animation", {"note": "no version and no known shape"}, "E4",
        e4("invalid-e4-shape.json", "animation"))
    case("animation-shape-people.json", "skeleton", {"error": e4("animation-shape-people.json", "skeleton")},
         error_id="E4", note="fps rules out the skeleton shape")
    case("skeleton-shape-keys.json", "keyframes", {"error": e4("skeleton-shape-keys.json", "keyframes")},
         error_id="E4", note="key poses are not key frames")
    case("keyframes-v1-index.json", "skeleton", {"error": e4("keyframes-v1-index.json", "skeleton")},
         error_id="E4")

    f = "invalid-e2-long-format.json"
    d = a1_data(2)
    del d["schema"]
    d["format"] = "simon.animation.v" + "x" * 63
    bad(f, "animation", d, "E2", e2(f, "format", d["format"], "animation"),
        note="an 80 character value is cut to its first 57 characters plus three dots")
    f = "invalid-e2-long-astral.json"
    d = p1_data([[mark("a", 1, 10)]])
    d["format"] = "\U0001F600" * 30 + "a" * 31
    bad(f, "keyframes", d, "E2", e2(f, "format", d["format"], "keyframes"),
        note="61 characters counted as characters, not UTF-16 units: 30 emoji, then 27 letters and dots")
    f = "invalid-e2-60-chars.json"
    d = sk1_data(2)
    d["schema"] = "simon.skeleton/" + "y" * 45
    bad(f, "skeleton", d, "E2", e2(f, "schema", d["schema"], "skeleton"),
        note="exactly 60 characters is shown whole")
    f = "invalid-e2-61-chars.json"
    d = sk1_data(2)
    d["schema"] = "simon.skeleton/" + "y" * 46
    bad(f, "skeleton", d, "E2", e2(f, "schema", d["schema"], "skeleton"),
        note="61 characters is cut")


def invalid_animation():
    d = a1_data(2)
    d["fps"] = 0
    bad("invalid-e5-fps-zero.json", "animation", d, "E5", e5("invalid-e5-fps-zero.json"))
    d = v1_data(2, 30)
    d["fps"] = "30"
    bad("invalid-e5-fps-string.json", "animation", d, "E5", e5("invalid-e5-fps-string.json"))
    d = a1_data(2)
    del d["fps"]
    bad("invalid-e5-fps-missing.json", "animation", d, "E5", e5("invalid-e5-fps-missing.json"))
    d = p1_data([[mark("a", 1, 10)]])
    d["fps"] = "sixty"
    bad("invalid-e5-keyframes-fps.json", "keyframes", d, "E5", e5("invalid-e5-keyframes-fps.json"))

    d = a1_data(2)
    d["frames"] = []
    bad("invalid-e6-frames-empty.json", "animation", d, "E6", e6("invalid-e6-frames-empty.json"))
    d = v1_data(2, 30)
    del d["frames"]
    bad("invalid-e6-frames-missing.json", "animation", d, "E6", e6("invalid-e6-frames-missing.json"))

    d = v1_data(4, 30)
    del d["frames"][2]["joints"]["left_knee"]
    bad("invalid-e7-v1-joint.json", "animation", d, "E7",
        e7("invalid-e7-v1-joint.json", "frames[2]", "left_knee"))
    d = a1_data(3)
    del d["frames"][1]["people"][0]["joints"]["right_ear"]
    bad("invalid-e7-a1-joint.json", "animation", d, "E7",
        e7("invalid-e7-a1-joint.json", "frames[1].people[0]", "right_ear"))

    d = a1_data(3)
    d["frames"][1]["people"][0]["joints"]["nose"]["x"] = "NaN"
    bad("invalid-e8-string-number.json", "animation", d, "E8",
        e8("invalid-e8-string-number.json", "frames[1].people[0]", "nose"))
    d = v1_data(2, 30)
    d["frames"][0]["joints"]["left_wrist"] = [0.1, 0.2]
    bad("invalid-e8-short-array.json", "animation", d, "E8",
        e8("invalid-e8-short-array.json", "frames[0]", "left_wrist"))
    d = v1_data(3, 30)
    d["frames"][2]["joints"]["right_hip"] = [0.0, "x", 0.0]
    bad("invalid-e8-array-text.json", "animation", d, "E8",
        e8("invalid-e8-array-text.json", "frames[2]", "right_hip"),
        note="an array of three with a text part is not three numbers")
    d = v1_data(3, 30)
    d["frames"][1]["joints"]["left_hip"] = [0.0, True, 0.0]
    bad("invalid-e8-array-bool.json", "animation", d, "E8",
        e8("invalid-e8-array-bool.json", "frames[1]", "left_hip"),
        note="a boolean is not a number, though Python counts True as an int")

    d = v1_data(3, 30)
    d["frames"][2]["joints"]["right_hip"] = [0.0, "__BIG__", 0.0]
    raw = json.dumps(d, separators=(",", ":")).replace('"__BIG__"', "1e999") + "\n"
    unparsable("invalid-json-number-overflow.json", "animation", raw,
               note="an otherwise valid animation; 1e999 does not fit a double, so the strict parse "
                    "refuses the whole file before any reader runs")

    d = v1_data(3, 30)
    d["note"] = "__BAD_BYTE__"
    raw = json.dumps(d, separators=(",", ":")).encode("utf-8").replace(b'"__BAD_BYTE__"', b'"caf\xff"') + b"\n"
    unparsable("invalid-json-bad-utf8.json", "animation", raw,
               note="an otherwise valid animation; one 0xFF byte (never valid UTF-8) sits inside its "
                    "ignored note field, so the strict decode refuses the whole file before any reader runs")

    d = a1_data(4)
    d["frames"][3]["people"] = []
    bad("invalid-e9-no-person.json", "animation", d, "E9", e9("invalid-e9-no-person.json", "frames[3]"))

    d = a1_data(4)
    d["frames"][3]["t_ms"] = 50.0
    bad("invalid-e10-a1-order.json", "animation", d, "E10", e10("invalid-e10-a1-order.json", "frames[3]"))
    d = v1_data(3, 30)
    d["frames"][2]["t"] = d["frames"][1]["t"]
    bad("invalid-e10-v1-equal.json", "animation", d, "E10", e10("invalid-e10-v1-equal.json", "frames[2]"))


def invalid_skeleton():
    d = sk1_data(3)
    del d["frames"][1]["people"][0]["joints"]["nose"]
    bad("invalid-e7-skeleton-frame.json", "skeleton", d, "E7",
        e7("invalid-e7-skeleton-frame.json", "frames[1].people[0]", "nose"))
    d = skv1_data(3)
    del d["keyframes"][1]["joints"]["right_ankle"]
    bad("invalid-e7-skeleton-key.json", "skeleton", d, "E7",
        e7("invalid-e7-skeleton-key.json", "keyframes[1]", "right_ankle"))
    d = sk1_data(2)
    d["part4"] = {"format": SV1, "keyframes": sk_keys([0, 30], ["a", "b"])}
    del d["part4"]["keyframes"][0]["joints"]["nose"]
    bad("invalid-e7-skeleton-nested-key.json", "skeleton", d, "E7",
        e7("invalid-e7-skeleton-nested-key.json", "part4.keyframes[0]", "nose"))

    d = skv1_data(3)
    d["keyframes"][1]["joints"]["left_eye"] = None
    bad("invalid-e8-key-null.json", "skeleton", d, "E8",
        e8("invalid-e8-key-null.json", "keyframes[1]", "left_eye"))
    d = sk1_data(2)
    del d["frames"][0]["people"][0]["joints"]["left_hip"]["z"]
    bad("invalid-e8-missing-z.json", "skeleton", d, "E8",
        e8("invalid-e8-missing-z.json", "frames[0].people[0]", "left_hip"))

    d = sk1_data(3)
    for fr in d["frames"]:
        fr["people"] = []
    bad("invalid-e9s-no-pose.json", "skeleton", d, "E9s", e9s("invalid-e9s-no-pose.json"))
    bad("invalid-e9s-no-frames.json", "skeleton", {"schema": S1, "units": UNITS_MS}, "E9s",
        e9s("invalid-e9s-no-frames.json"))

    d = sk1_data(3)
    del d["frames"][2]["t_ms"]
    bad("invalid-e11-frame-time.json", "skeleton", d, "E11", e11("invalid-e11-frame-time.json", "frames[2]"))
    d = skv1_data(3)
    del d["keyframes"][1]["t"], d["keyframes"][1]["index"]
    bad("invalid-e11-key-time.json", "skeleton", d, "E11",
        e11_key("invalid-e11-key-time.json", "keyframes[1]"))

    d = skv1_data(3)
    d["keyframes"][1]["name"] = 7
    bad("invalid-e15-skeleton-key-name.json", "skeleton", d, "E15",
        e15("invalid-e15-skeleton-key-name.json", "keyframes[1]"))


def invalid_keyframes():
    f = "invalid-e13-people.json"
    bad(f, "keyframes", {"schema": K1, "people": {"id": 0}}, "E13", e13(f, "people"))
    f = "invalid-e13-keyframes.json"
    bad(f, "keyframes", {"format": KV1, "fps": 30, "keyframes": {"a": 1}}, "E13", e13(f, "keyframes"))
    f = "invalid-e13-repetitions.json"
    bad(f, "keyframes", {"fps": 30, "people": [{"id": 0, "repetitions": "none"}]}, "E13",
        e13(f, "people[0].repetitions"))
    f = "invalid-e13-rep-keyframes.json"
    d = p1_data([[mark("a", 1, 10)], [mark("b", 2, 20)]])
    d["people"][0]["repetitions"][1]["keyframes"] = "none"
    bad(f, "keyframes", d, "E13", e13(f, "people[0].repetitions[1].keyframes"))

    f = "invalid-e14-part1-no-fps.json"
    d = p1_data([[mark("a", None, 500), mark("b", 60)]])
    del d["fps"]
    bad(f, "keyframes", d, "E14", e14(f, "people[0].repetitions[0].keyframes[1]"))
    f = "invalid-e14-part1-bad-tms.json"
    d = p1_data([[mark("a", None, 500)], [mark("b", None, "2000")]])
    bad(f, "keyframes", d, "E14", e14(f, "people[0].repetitions[1].keyframes[0]"))
    f = "invalid-e14-v1-no-time.json"
    d = v1k_data([{"index": 0, "name": "a"}, {"t": 1.0, "name": "b"}, {"name": "c"}], 30)
    bad(f, "keyframes", d, "E14", e14(f, "keyframes[2]", v1=True))
    f = "invalid-e14-v1-no-fps.json"
    d = v1k_data([{"index": 5, "name": "a"}], 30)
    del d["fps"]
    bad(f, "keyframes", d, "E14", e14(f, "keyframes[0]", v1=True))

    f = "invalid-e15-part1-name.json"
    d = p1_data([[{"name": 5, "frame": 3, "t_ms": 100}]])
    bad(f, "keyframes", d, "E15", e15(f, "people[0].repetitions[0].keyframes[0]"))
    f = "invalid-e15-v1-name.json"
    d = v1k_data([{"index": 0, "name": "a"}, {"index": 5}], 30)
    bad(f, "keyframes", d, "E15", e15(f, "keyframes[1]"))


def limit_files():
    """Times at and over the two hour limit (7200 s), AC-F09 E16; 7200 itself is valid."""
    n = 3
    poses = [pose(depth(i, n)) for i in range(n)]
    frames = [{"index": idx, "joints": as_arr(poses[j])} for j, idx in enumerate((0, 3600, 7200))]
    put("animation-v1-limit.json", {"format": AV1, "fps": 1, "frames": frames})
    case("animation-v1-limit.json", "animation",
         exp_anim(AV1, "version", 1, [0.0, 3600.0, 7200.0], [False] * n, poses),
         note="index over fps equal to 7200 s is allowed")

    put("keyframes-part1-limit.json",
        p1_data([[mark("a", None, 7200000), mark("b", 216000), mark("c", None, 0)]]))
    case("keyframes-part1-limit.json", "keyframes",
         exp_keys(K1, "shape", 30.0, [("c", 0.0, 0), ("a", 7200.0, 216000), ("b", 7200.0, 216000)]),
         note="t_ms 7200000 and frame 216000 at 30 fps are 7200 s: allowed")

    d = sk1_data(2, 15)
    d["frames"][1]["t_ms"] = 7200000.0
    put("skeleton-1-limit.json", d)
    held = exp_held(S1, "version", [(Fraction(0), pose(depth(0, 2))), (Fraction(7200), pose(depth(1, 2)))])
    case("skeleton-1-limit.json", "skeleton", exp_skel(S1, "version", 2, 2, []),
         expect_animation=held, note="the longest skeleton: 216001 held frames")

    f = "invalid-e16-animation-t-ms.json"
    d = a1_data(3)
    d["frames"][1]["t_ms"] = 7200001.0
    bad(f, "animation", d, "E16", e16(f, "frames[1]"))
    negative_times()
    f = "invalid-e16-animation-fps.json"
    d = a1_data(10, fps=0.001, with_t=False)
    bad(f, "animation", d, "E16", e16(f, "frames[8]"), note="frame 8 at 0.001 fps is 8000 s")
    f = "invalid-e16-animation-index.json"
    d = v1_data(3, 1)
    d["frames"][2]["index"] = 7201
    del d["frames"][2]["t"]
    bad(f, "animation", d, "E16", e16(f, "frames[2]"), note="index over fps")
    f = "invalid-e16-skeleton-frame.json"
    d = sk1_data(3)
    d["frames"][1]["t_ms"] = 7200000.5
    bad(f, "skeleton", d, "E16", e16(f, "frames[1]"))
    f = "invalid-e16-skeleton-seconds.json"
    d = sk1_data(2)
    del d["frames"][0]["t_ms"]
    d["frames"][0]["t"] = 1e12
    bad(f, "skeleton", d, "E16", e16(f, "frames[0]"), note="t in seconds, a trillion of them")
    f = "invalid-e16-skeleton-key.json"
    d = skv1_data(3)
    d["keyframes"][2]["index"] = 300000
    del d["keyframes"][2]["t"]
    bad(f, "skeleton", d, "E16", e16(f, "keyframes[2]"), note="index over 30")
    f = "invalid-e16-part1-t-ms.json"
    d = p1_data([[mark("a", None, 1000)], [mark("b", None, 7200001)]])
    bad(f, "keyframes", d, "E16", e16(f, "people[0].repetitions[1].keyframes[0]"))
    f = "invalid-e16-part1-frame.json"
    d = p1_data([[mark("a", 500000)]], fps=60.0)
    bad(f, "keyframes", d, "E16", e16(f, "people[0].repetitions[0].keyframes[0]"),
        note="frame over fps: 8333 s")
    f = "invalid-e16-v1-t.json"
    d = v1k_data([{"t": 1.0, "name": "a"}, {"t": 7200.5, "name": "b"}], 30)
    bad(f, "keyframes", d, "E16", e16(f, "keyframes[1]"))
    f = "invalid-e16-v1-index.json"
    d = v1k_data([{"index": 216001, "name": "a"}], 30)
    bad(f, "keyframes", d, "E16", e16(f, "keyframes[0]"), note="index over fps: 7200.03 s")


def negative_times():
    """Times below 0, and values so far below 0 that they are minus infinity once divided (E16)."""
    huge = -1e308
    f = "invalid-e16-animation-negative.json"
    d = a1_data(3)
    d["frames"][1]["t_ms"] = -5.0
    bad(f, "animation", d, "E16", e16(f, "frames[1]"), note="/1 t_ms below 0")
    f = "invalid-e16-animation-huge-negative.json"
    d = v1_data(3, 30)
    d["frames"][0]["t"] = huge
    bad(f, "animation", d, "E16", e16(f, "frames[0]"), note="v1 t of -1e308")
    f = "invalid-e16-animation-index-negative.json"
    d = v1_data(3, 30)
    del d["frames"][1]["t"]
    d["frames"][1]["index"] = -2
    bad(f, "animation", d, "E16", e16(f, "frames[1]"), note="v1 index below 0")
    f = "invalid-e16-animation-index-huge-negative.json"
    d = v1_data(3, 0.001)
    del d["frames"][1]["t"]
    d["frames"][1]["index"] = huge
    bad(f, "animation", d, "E16", e16(f, "frames[1]"), note="index of -1e308 over 0.001 fps is -inf")

    f = "invalid-e16-skeleton-negative.json"
    d = sk1_data(3)
    d["frames"][1]["t_ms"] = -1.0
    bad(f, "skeleton", d, "E16", e16(f, "frames[1]"))
    f = "invalid-e16-skeleton-huge-negative.json"
    d = sk1_data(3)
    d["frames"][0]["t_ms"] = huge
    bad(f, "skeleton", d, "E16", e16(f, "frames[0]"))
    f = "invalid-e16-skeleton-key-negative.json"
    d = skv1_data(3)
    d["keyframes"][1]["t"] = -0.5
    bad(f, "skeleton", d, "E16", e16(f, "keyframes[1]"))
    f = "invalid-e16-skeleton-key-huge-negative.json"
    d = skv1_data(3)
    del d["keyframes"][2]["t"]
    d["keyframes"][2]["index"] = huge
    bad(f, "skeleton", d, "E16", e16(f, "keyframes[2]"))

    where = "people[0].repetitions[0].keyframes[0]"
    for name, marks, extra in (
            ("part1-negative-t-ms", [mark("a", None, -5)], {}),
            ("part1-huge-negative-t-ms", [mark("a", None, huge)], {}),
            ("part1-negative-frame", [mark("a", -5)], {}),
            ("part1-huge-negative-frame", [mark("a", huge)], {"fps": 0.5})):
        f = f"invalid-e16-{name}.json"
        bad(f, "keyframes", p1_data([marks], **extra), "E16", e16(f, where))
    for name, item, fps in (
            ("v1-negative-t", {"t": -0.5, "name": "a"}, 30),
            ("v1-huge-negative-t", {"t": huge, "name": "a"}, 30),
            ("v1-negative-index", {"index": -2, "name": "a"}, 30),
            ("v1-huge-negative-index", {"index": huge, "name": "a"}, 0.001)):
        f = f"invalid-e16-{name}.json"
        bad(f, "keyframes", v1k_data([item], fps), "E16", e16(f, "keyframes[0]"))


# ---- main ------------------------------------------------------------------------------------------

def build():
    animations()
    skeletons()
    keyframes()
    invalid_framing()
    invalid_animation()
    invalid_skeleton()
    invalid_keyframes()
    limit_files()
    detections()
    playables()


def write_all():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, content in FILES.items():
        (OUT / name).write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    for old in OUT.glob("*.json"):
        if old.name not in FILES and old.name != "cases.json":
            old.unlink()
    lines = ",\n".join(json.dumps(c, separators=(",", ":")) for c in CASES)
    (OUT / "cases.json").write_text("[\n" + lines + "\n]\n", encoding="utf-8")


if __name__ == "__main__":
    build()
    write_all()
    print(f"wrote {len(FILES)} golden files and {len(CASES)} cases to {OUT}")
