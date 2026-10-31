"""Generate dummy follower takes in Part 4's `simon.animation.v1` format, with fault labels.

Reads only the expected clips in fixtures/input/expected/<set>/animation.json (copied from
Part 4's shipped output) and writes, under --out (default fixtures/input/followers):

  <out>/<set>/<take_id>/skeleton.json   one follower take, same format
  <out>/labels.json                     ground truth for every take (names the seed)

Each take is the expected clip performed by a different follower. The body is rescaled,
the timing is warped and has an idle lead-in, there is small natural variation, and the
3D estimate carries noise for that camera angle and lighting. A fault take also has one or
two deliberate faults. Faults rotate a limb chain about its joint, so bone lengths are
kept. Each label records the joint, side, measure, direction, magnitude and frame range.

Grid per set, angle and lighting: 2 correct takes, 6 single-fault takes (one per fault type,
including knee_caving) and 1 double-fault take, 9 takes; 12 cells make 108 takes per seed.

--dropout-variant adds, for every side and 45 degree take, a copy with a per-joint `conf` series
(lower on the far side and in low light) and short far-side dropouts (a joint null, or its `conf`
below 0.3, in bursts of a few frames). The copy's id ends in `_dropout` and its label says
`variant: "dropout"`. The clean takes are the same bytes with or without the flag.

--feet (TICKET-040, ASM-013, docs/specs/foot-keypoints.md "Calibration plan") adds planted synthetic feet,
written the way Part 2 writes them: a `pose3d.json` shaped side file `feet.json` beside every
skeleton.json (the take's own 17 joints plus the six `extra_joints` foot points), one `feet.json` per
expected set under fixtures/input/expected-feet/<set>/, `expected_feet` and `follower_feet` paths in each
label, and four more takes per cell after the nine base ones (numbers 09 to 12): `foot_turned_out`,
`foot_turned_in`, `ankle_rolled_in`, `ankle_rolled_out`. Everything foot-related draws from random streams
of its own (keyed by the take id), so every skeleton.json and every earlier label key is the same bytes
with or without the flag. A dropout copy masks the feet where it masks the ankle.

Deterministic: `python3 scripts/make_dummy_followers.py [--seed 5] [--out DIR] [--dropout-variant] [--feet]`.
Seed 5 is the tuning set (docs/specs/calibration.md); held-out seeds come from `make heldout-data`.
"""
import argparse
import copy
import json
import math
import random
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = ROOT / "fixtures" / "input" / "expected"
EXPECTED_FEET = ROOT / "fixtures" / "input" / "expected-feet"
OUT = ROOT / "fixtures" / "input" / "followers"
SETS = ["exercise", "dance"]
SIDES = ("left", "right")

# Camera yaw about world up; the camera sits at (sin yaw, 0, cos yaw) from the subject.
# 0° faces the subject (anterior), 90° is on the subject's left side.
ANGLES = {"front": 0, "45": 45, "side": 90}
# Noise sigmas in metres: across the image plane and along the camera's depth axis.
LIGHTING = {"good": {"lateral": 0.006, "depth": 0.015}, "low": {"lateral": 0.014, "depth": 0.035}}
CORRECT_TAKES_PER_CELL = 2

ARM = {"left": ["left_elbow", "left_wrist"], "right": ["right_elbow", "right_wrist"]}
LEG = {"left": ["left_knee", "left_ankle"], "right": ["right_knee", "right_ankle"]}
UPPER_BODY = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder",
              "left_elbow", "right_elbow", "left_wrist", "right_wrist"]

# Fault catalogue. `sides` lists the variants a take may get; "both" means mirrored on each side.
FAULTS = {
    "arms_wider": {"measure": "upper_arm_direction", "body_part": "arms", "direction": "more",
                   "sides": ["both", "left", "right"], "deg": (15, 25),
                   "text": {"both": "elbows wider than the example", "left": "left arm too far out",
                            "right": "right arm too far out"}},
    "foot_out": {"measure": "thigh_direction", "body_part": "legs", "direction": "more",
                 "sides": ["left", "right"], "deg": (12, 20),
                 "text": {"left": "left foot too far out", "right": "right foot too far out"}},
    "knees_shallow": {"measure": "knee_flexion", "body_part": "legs", "direction": "less",
                      "sides": ["both"], "frac": (0.35, 0.5),
                      "text": {"both": "knees not bent enough"}},
    "elbow_bent": {"measure": "elbow_flexion", "body_part": "arms", "direction": "more",
                   "sides": ["left", "right"], "deg": (25, 40),
                   "text": {"left": "left elbow bent, keep it straighter", "right": "right elbow bent, keep it straighter"}},
    "trunk_lean": {"measure": "trunk_lean_forward", "body_part": "torso", "direction": "more",
                   "sides": ["center"], "deg": (15, 25),
                   "text": {"center": "leaning forward more than the example"}},
    # ADR-0004: the knee moves toward the midline about the hip to ankle axis; deg is knee_valgus.
    "knee_caving": {"measure": "knee_valgus", "body_part": "legs", "direction": "more",
                    "sides": ["left", "right"], "deg": (15, 25),
                    "text": {"left": "left knee caving in", "right": "right knee caving in"}},
}
JOINT_OF = {"upper_arm_direction": "shoulder", "thigh_direction": "hip", "knee_flexion": "knee",
            "elbow_flexion": "elbow", "trunk_lean_forward": "spine", "knee_valgus": "knee"}
# Toward the midline, per side: the negative of the "out" direction of part5.measures.OUT.
INWARD = {"left": [-1.0, 0.0, 0.0], "right": [1.0, 0.0, 0.0]}
# Pairs a double-fault take may combine (knee_caving stays out: it shares the leg with foot_out).
DOUBLE_POOL = ["arms_wider", "foot_out", "trunk_lean", "elbow_bent"]
BASE_TAKES_PER_CELL = CORRECT_TAKES_PER_CELL + len(FAULTS) + 1   # the nine takes whose bytes never change

# --- planted feet (TICKET-040, ASM-013) ---
# Part 2's names and order for the six foot points (`extra_joints` of pose3d.json).
FOOT_JOINTS = ["left_big_toe", "left_small_toe", "left_heel", "right_big_toe", "right_small_toe", "right_heel"]
# Rigid foot template at body scale 1, metres: (point, ahead of the ankle, toward the outer edge, below the ankle).
FOOT_TEMPLATE = (("heel", -0.07, 0.0, 0.08), ("big_toe", 0.17, -0.035, 0.08), ("small_toe", 0.12, 0.035, 0.08))
TOE_OUT_DEG = (4.0, 10.0)        # a take's natural toe-out against the pelvis's forward, drawn once per take
EXPECTED_TOE_OUT_DEG = 7.0       # the expected clip's fixed toe-out
FOOT_DRIFT_DEG = 1.2             # slow drift of each foot's heading, the size natural_variation gives other joints
# Foot fault catalogue: `kind` yaw turns the foot about the vertical through the ankle (foot_rotation), roll turns the
# foot plane about its long axis (ankle_inversion); `sign` is the change of the measure per degree applied.
FOOT_FAULTS = {
    "foot_turned_out": {"measure": "foot_rotation", "direction": "more", "kind": "yaw", "sign": 1.0,
                        "sides": ["left", "right", "both"], "deg": (15, 25),
                        "text": {"left": "left foot turned out too far", "right": "right foot turned out too far",
                                 "both": "feet turned out more than the example"}},
    "foot_turned_in": {"measure": "foot_rotation", "direction": "less", "kind": "yaw", "sign": -1.0,
                       "sides": ["left", "right", "both"], "deg": (15, 25),
                       "text": {"left": "left foot not turned out enough", "right": "right foot not turned out enough",
                                "both": "feet not turned out enough"}},
    "ankle_rolled_in": {"measure": "ankle_inversion", "direction": "more", "kind": "roll", "sign": 1.0,
                        "sides": ["left", "right", "both"], "deg": (15, 25),
                        "text": {"left": "left ankle rolled in", "right": "right ankle rolled in",
                                 "both": "ankles rolled in"}},
    "ankle_rolled_out": {"measure": "ankle_inversion", "direction": "less", "kind": "roll", "sign": -1.0,
                         "sides": ["left", "right", "both"], "deg": (15, 25),
                         "text": {"left": "left ankle rolled out", "right": "right ankle rolled out",
                                  "both": "ankles rolled out"}},
}


# --- small vector helpers (stdlib only, so this runs before the project scaffold exists) ---
def sub(a, b): return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
def add(a, b): return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
def scale(a, s): return [a[0] * s, a[1] * s, a[2] * s]
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b): return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
def norm(a): return math.sqrt(dot(a, a))
def unit(a):
    n = norm(a)
    return scale(a, 1 / n) if n > 1e-9 else None
def lerp(a, b, w): return [a[i] + (b[i] - a[i]) * w for i in range(3)]


def rotate(p, pivot, axis, deg):
    """Rodrigues rotation of point p about `axis` through `pivot`."""
    k, th = unit(axis), math.radians(deg)
    v = sub(p, pivot)
    c, s = math.cos(th), math.sin(th)
    r = add(add(scale(v, c), scale(cross(k, v), s)), scale(k, dot(k, v) * (1 - c)))
    return add(pivot, r)


def angle_at(a, b, c):
    u, v = unit(sub(a, b)), unit(sub(c, b))
    return math.degrees(math.acos(max(-1.0, min(1.0, dot(u, v)))))


def seg_angle(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, dot(unit(a), unit(b))))))


def knee_valgus(f, s):
    """Master spec `knee_valgus`: how far the knee sits inside the hip to ankle line, in degrees.

    d = ((k - h) - proj_(a - h)(k - h)) . inward, valgus = atan2(d, |k - h|); positive is caving.
    """
    h, k, a = f[f"{s}_hip"], f[f"{s}_knee"], f[f"{s}_ankle"]
    thigh, axis = sub(k, h), unit(sub(a, h))
    off = sub(thigh, scale(axis, dot(thigh, axis)))
    return math.degrees(math.atan2(dot(off, INWARD[s]), norm(thigh)))


def measure(f, m, s):
    """The quantity a fault changes, so the label holds the size the follower really shows."""
    if m == "knee_valgus": return knee_valgus(f, s)
    if m == "upper_arm_direction": return sub(f[f"{s}_elbow"], f[f"{s}_shoulder"])
    if m == "thigh_direction": return sub(f[f"{s}_knee"], f[f"{s}_hip"])
    if m == "knee_flexion": return 180 - angle_at(f[f"{s}_hip"], f[f"{s}_knee"], f[f"{s}_ankle"])
    if m == "elbow_flexion": return 180 - angle_at(f[f"{s}_shoulder"], f[f"{s}_elbow"], f[f"{s}_wrist"])
    if m == "trunk_lean_forward": return scale(add(f["left_shoulder"], f["right_shoulder"]), 0.5)


def change(before, after):
    return seg_angle(before, after) if isinstance(before, list) else abs(after - before)


def envelope(n, rng):
    """Fault strength per frame: on over a window of the clip, with cosine ramps at each end."""
    start = int(n * rng.uniform(0.05, 0.2))
    end = int(n * rng.uniform(0.8, 0.95))
    ramp = 6
    w = []
    for i in range(n):
        if i < start or i > end:
            w.append(0.0)
        elif i < start + ramp:
            w.append(0.5 - 0.5 * math.cos(math.pi * (i - start) / ramp))
        elif i > end - ramp:
            w.append(0.5 - 0.5 * math.cos(math.pi * (end - i) / ramp))
        else:
            w.append(1.0)
    return w, start, end


def smooth_noise(n, sigma, rng, a=0.85):
    """AR(1) noise: jitter that drifts over a few frames, like a per-frame pose estimator."""
    out, x, b = [], rng.gauss(0, sigma), math.sqrt(1 - a * a)
    for _ in range(n):
        x = a * x + b * rng.gauss(0, sigma)
        out.append(x)
    return out


# --- faults: each edits frames in place and returns the largest change it made, in degrees ---
def swing_out(f, pivot, chain, side, deg):
    """Swing a limb chain away from the midline by `deg`, whatever direction it points."""
    seg = sub(f[chain[0]], f[pivot])
    out = [1, 0, 0] if side == "left" else [-1, 0, 0]
    axis = unit(cross(seg, out))
    if axis is None:
        return 0.0
    for j in chain:
        f[j] = rotate(f[j], f[pivot], axis, deg)
    return deg


def fault_arms_wider(frames, side, deg, w):
    for f, wi in zip(frames, w):
        for s in (["left", "right"] if side == "both" else [side]):
            swing_out(f, f"{s}_shoulder", ARM[s], s, deg * wi)
    return deg


def fault_foot_out(frames, side, deg, w):
    for f, wi in zip(frames, w):
        swing_out(f, f"{side}_hip", LEG[side], side, deg * wi)
    return deg


def fault_knees_shallow(frames, side, frac, w):
    worst = 0.0
    for f, wi in zip(frames, w):
        for s in ["left", "right"]:
            hip, knee, ank = f[f"{s}_hip"], f[f"{s}_knee"], f[f"{s}_ankle"]
            flex = 180 - angle_at(hip, knee, ank)
            axis = unit(cross(sub(knee, hip), sub(ank, knee)))
            if axis is None or flex < 1:
                continue
            # Rotating the shin by -d about thigh × shin reduces the flexion by d.
            d = flex * frac * wi
            f[f"{s}_ankle"] = rotate(ank, knee, axis, -d)
            worst = max(worst, d)
    return worst


def fault_elbow_bent(frames, side, deg, w):
    for f, wi in zip(frames, w):
        el = f[f"{side}_elbow"]
        # Flex forward: rotate the forearm about the subject's x axis, so the wrist moves anterior (+z).
        upper = sub(el, f[f"{side}_shoulder"])
        axis = unit(cross([0, 0, 1], upper)) or [1, 0, 0]
        f[f"{side}_wrist"] = rotate(f[f"{side}_wrist"], el, axis, -deg * wi)
    return deg


def cave_knee(f, side, target_deg):
    """Rotate the knee about the hip to ankle axis until `knee_valgus` reads `target_deg`.

    Both bone lengths stay. Where the knee bend is too small to reach the target, the knee goes as
    far inward as the bend allows.
    """
    h, k, a = f[f"{side}_hip"], f[f"{side}_knee"], f[f"{side}_ankle"]
    axis, thigh = unit(sub(a, h)), sub(k, h)
    off = sub(thigh, scale(axis, dot(thigh, axis)))
    inward = sub(INWARD[side], scale(axis, dot(INWARD[side], axis)))
    reach = norm(off) * norm(inward)
    if reach < 1e-9:
        return
    # Signed angle from the knee offset to the inward direction; rotating by theta leaves
    # the inward offset |off| |inward| cos(phi - theta), which must equal |k - h| tan(target).
    phi = math.atan2(dot(axis, cross(off, inward)), dot(off, inward))
    want = max(-1.0, min(1.0, norm(thigh) * math.tan(math.radians(target_deg)) / reach))
    theta = [math.remainder(phi - sign * math.acos(want), 2 * math.pi) for sign in (1, -1)]
    f[f"{side}_knee"] = rotate(k, h, axis, math.degrees(min(theta, key=abs)))


def fault_knee_caving(frames, side, deg, w):
    for f, wi in zip(frames, w):
        if wi > 0:
            cave_knee(f, side, knee_valgus(f, side) + deg * wi)
    return deg


def fault_trunk_lean(frames, side, deg, w):
    for f, wi in zip(frames, w):
        # +deg about x through the hip midpoint (origin) tips y-up toward +z (anterior).
        for j in UPPER_BODY:
            f[j] = rotate(f[j], [0, 0, 0], [1, 0, 0], deg * wi)
    return deg


APPLY = {"arms_wider": fault_arms_wider, "foot_out": fault_foot_out, "knees_shallow": fault_knees_shallow,
         "elbow_bent": fault_elbow_bent, "trunk_lean": fault_trunk_lean, "knee_caving": fault_knee_caving}


def natural_variation(frames, rng):
    """Small style differences a correct follower still has (a few degrees): not faults."""
    n = len(frames)
    sway = {k: smooth_noise(n, 1.2, rng, a=0.97) for k in ["la", "ra", "ll", "rl", "trunk"]}
    for i, f in enumerate(frames):
        for s, key in (("left", "la"), ("right", "ra")):
            for j in ARM[s]:
                f[j] = rotate(f[j], f[f"{s}_shoulder"], [0, 0, 1], sway[key][i])
        for s, key in (("left", "ll"), ("right", "rl")):
            for j in LEG[s]:
                f[j] = rotate(f[j], f[f"{s}_hip"], [0, 0, 1], sway[key][i] * 0.5)
        for j in UPPER_BODY:
            f[j] = rotate(f[j], [0, 0, 0], [1, 0, 0], sway["trunk"][i])


def time_warp(frames, speed, lead_in):
    """Follower plays the clip at `speed`, after holding the first pose for `lead_in` frames."""
    n = len(frames)
    m = int(round((n - 1) / speed)) + 1
    out = [dict(frames[0]) for _ in range(lead_in)]
    src_of = [None] * lead_in
    for k in range(m):
        u = min(k * speed, n - 1)
        i0 = int(math.floor(u)); i1 = min(i0 + 1, n - 1); a = u - i0
        out.append({j: lerp(frames[i0][j], frames[i1][j], a) for j in frames[0]})
        src_of.append(u)
    return out, src_of


def camera_noise(frames, joints, yaw_deg, light, rng):
    """Jitter the joints, then put the hip midpoint back at the origin; returns the midpoint of each frame."""
    jitter(frames, joints, yaw_deg, light, rng)
    midpoints = [scale(add(f["left_hip"], f["right_hip"]), 0.5) for f in frames]  # keep the frame contract: hip midpoint at the origin
    recentre(frames, joints, midpoints)
    return midpoints


def recentre(frames, joints, midpoints):
    for f, hm in zip(frames, midpoints):
        for j in joints:
            f[j] = sub(f[j], hm)


def jitter(frames, joints, yaw_deg, light, rng):
    """Smooth 3D estimate noise for the camera angle and lighting, added to each listed joint in place."""
    n = len(frames)
    th = math.radians(yaw_deg)
    depth = [math.sin(th), 0.0, math.cos(th)]
    lat = [math.cos(th), 0.0, -math.sin(th)]
    up = [0.0, 1.0, 0.0]
    sig = LIGHTING[light]
    # Joints on the side away from the camera are partly hidden, so their estimate is worse.
    far = "right" if yaw_deg > 0 else None
    far_mult = 1 + yaw_deg / 90.0
    for j in joints:
        m = far_mult if far and j.startswith(far) else 1.0
        nl = smooth_noise(n, sig["lateral"] * m, rng)
        nu = smooth_noise(n, sig["lateral"] * m, rng)
        nd = smooth_noise(n, sig["depth"] * m, rng)
        for i, f in enumerate(frames):
            f[j] = add(f[j], add(add(scale(lat, nl[i]), scale(up, nu[i])), scale(depth, nd[i])))


def median(xs):
    s = sorted(xs)
    return s[len(s) // 2]


# --- planted feet: a rigid foot under each ankle, flat on the floor, carried by the pelvis's heading ---
def plant_feet(frames, body, yaw, roll):
    """The six foot points of every frame (Part 2's names), from that frame's own hips and ankles.

    The pelvis's forward is the hip line (left minus right hip) in the ground plane turned a quarter turn
    (x, z) -> (-z, x). `yaw[side][i]` is the toe-out of that foot against the forward in degrees (away from the
    midline is positive, so `foot_rotation` reads it, less a constant for the big toe sitting inside the foot
    axis); `roll[side][i]` turns the foot plane about its long axis through the ankle, positive with the outer edge
    going down (`ankle_inversion` reads it). The template lengths scale with `body`.
    """
    out = []
    for i, f in enumerate(frames):
        hip = unit([f["left_hip"][0] - f["right_hip"][0], 0.0, f["left_hip"][2] - f["right_hip"][2]])
        ahead_of_pelvis = [-hip[2], 0.0, hip[0]]
        pts = {}
        for side, sgn in (("left", 1.0), ("right", -1.0)):
            psi, th = math.radians(yaw[side][i]), math.radians(roll[side][i])
            heading = add(scale(ahead_of_pelvis, math.cos(psi)), scale(hip, sgn * math.sin(psi)))
            outer = sub(scale(hip, sgn * math.cos(psi)), scale(ahead_of_pelvis, math.sin(psi)))
            for name, ahead, lat, below in FOOT_TEMPLATE:
                ahead, lat, below = ahead * body, lat * body, below * body
                across = lat * math.cos(th) - below * math.sin(th)       # along the foot's outer edge
                height = -lat * math.sin(th) - below * math.cos(th)      # along the world up
                pts[f"{side}_{name}"] = add(f[f"{side}_ankle"], add(add(scale(heading, ahead), scale(outer, across)),
                                                                    [0.0, height, 0.0]))
        out.append(pts)
    return out


def follower_weight(w, u):
    """The fault strength at expected-clip position `u` (None: the lead-in, before the clip starts)."""
    if u is None:
        return 0.0
    i0 = int(math.floor(u))
    i1 = min(i0 + 1, len(w) - 1)
    return w[i0] + (w[i1] - w[i0]) * (u - i0)


def plant_take_feet(frames, src_of, body, n, plan):
    """The pre-noise feet of a take and the labels of its foot faults.

    `plan` is {"rng": the take's own foot stream, "faults": [(type, side)]}; `n` the expected clip's frame count,
    `src_of` each follower frame's position in it (time_warp). A foot fault adds `deg` to the toe-out (or the roll)
    of its side(s), under the same cosine-ramped window as the body faults, so the label's size is exact.
    """
    rng, m = plan["rng"], len(frames)
    base = rng.uniform(*TOE_OUT_DEG)
    yaw = {s: [base + x for x in smooth_noise(m, FOOT_DRIFT_DEG, rng, a=0.97)] for s in SIDES}
    roll = {s: [0.0] * m for s in SIDES}
    labels = []
    for ftype, side in plan["faults"]:
        spec = FOOT_FAULTS[ftype]
        w, start, end = envelope(n, rng)
        amount = round(rng.uniform(*spec["deg"]), 1)
        wf = [follower_weight(w, u) for u in src_of]
        sides = list(SIDES) if side == "both" else [side]
        series = yaw if spec["kind"] == "yaw" else roll
        for s in sides:
            series[s] = [v + spec["sign"] * amount * wi for v, wi in zip(series[s], wf)]
        labels.append({"type": ftype, "measure": spec["measure"], "body_part": "feet",   # the analysis writes feet too
                       "joints": [f"{s}_ankle" for s in sides], "side": side, "direction": spec["direction"],
                       "magnitude_deg": amount, "peak_deg": amount, "_window": (start, end),
                       "text": spec["text"][side]})
    return plant_feet(frames, body, yaw, roll), labels


def build_take(expected, take_id, angle, light, faults, rng, feet=None):
    """One take and its meta. `feet` (a plan for plant_take_feet) adds the planted feet and any foot faults:
    the feet come back in `meta["_feet"]` for the caller to write; `rng` is never read for them."""
    joints = expected["joints"]
    frames = [{j: list(fr["joints"][j]) for j in joints} for fr in expected["frames"]]
    n = len(frames)

    body = rng.uniform(0.9, 1.1)
    frames = [{j: scale(p, body) for j, p in f.items()} for f in frames]

    labels = []
    for ftype, side in faults:
        spec = FAULTS[ftype]
        w, start, end = envelope(n, rng)
        amount = rng.uniform(*spec["frac"]) if "frac" in spec else rng.uniform(*spec["deg"])
        sides = ["left", "right"] if side == "both" else [side]
        probe = sides[0] if side != "center" else "left"
        full = [i for i, wi in enumerate(w) if wi == 1.0]
        before = [measure(frames[i], spec["measure"], probe) for i in full]
        APPLY[ftype](frames, side, amount, w)
        diffs = [change(b, measure(frames[i], spec["measure"], probe)) for i, b in zip(full, before)]
        mag, peak = median(diffs), max(diffs)
        labels.append({"type": ftype, "measure": spec["measure"], "body_part": spec["body_part"],
                       "joints": [f"{s}_{JOINT_OF[spec['measure']]}" for s in sides]
                       if side != "center" else ["spine"],
                       "side": side, "direction": spec["direction"], "magnitude_deg": round(mag, 1), "peak_deg": round(peak, 1),
                       "_window": (start, end), "text": spec["text"][side]})

    natural_variation(frames, rng)
    speed = rng.uniform(0.8, 1.25)
    lead_in = rng.randint(0, 15)
    frames, src_of = time_warp(frames, speed, lead_in)
    if feet is not None:   # after the 17 joints are final, before the camera noise (their own random stream)
        planted, foot_labels = plant_take_feet(frames, src_of, body, n, feet)
        labels += foot_labels
    midpoints = camera_noise(frames, joints, ANGLES[angle], light, rng)
    if feet is not None:
        jitter(planted, FOOT_JOINTS, ANGLES[angle], light, feet["rng"])
        recentre(planted, FOOT_JOINTS, midpoints)

    # Map each fault window from expected frames to follower frames.
    for lab in labels:
        s, e = lab.pop("_window")
        idx = [k for k, u in enumerate(src_of) if u is not None and s <= u <= e]
        lab["follower_frames"] = [idx[0], idx[-1]]
        lab["expected_frames"] = [s, e]

    fps = expected["fps"]
    bones = []
    for b in expected["bones"]:
        def pos(f, name):
            if name == "hip_mid": return scale(add(f["left_hip"], f["right_hip"]), 0.5)
            if name == "shoulder_mid": return scale(add(f["left_shoulder"], f["right_shoulder"]), 0.5)
            return f[name]
        bones.append({**b, "length_m": round(median([norm(sub(pos(f, b["child"]), pos(f, b["parent"])))
                                                      for f in frames]), 4)})
    doc = {
        "format": expected["format"], "fps": fps, "duration_s": round((len(frames) - 1) / fps, 6),
        "frame_count": len(frames), "movement": expected["movement"], "set": expected["set"],
        "coordinate_frame": expected["coordinate_frame"], "joints": joints, "bones": bones,
        "frames": [{"index": i, "t": round(i / fps, 6), "interpolated": False,
                    "joints": {j: [round(c, 4) for c in f[j]] for j in joints}}
                   for i, f in enumerate(frames)],
    }
    meta = {"take_id": take_id, "set": expected["set"], "movement": expected["movement"],
            "angle": angle, "camera_yaw_deg": ANGLES[angle], "lighting": light,
            "variant": "clean", "label_source": "synthetic", "correct": not labels, "body_scale": round(body, 3), "speed": round(speed, 3),
            "lead_in_frames": lead_in, "frame_count": len(frames), "faults": labels}
    if feet is not None:
        meta["_feet"] = planted   # per frame {foot point: [x, y, z]}; generate() takes it out before the labels are written
    return doc, meta


def fault_plan(rng):
    """One take per fault type with a random side, plus one take with two faults."""
    plan = [[(t, rng.choice(FAULTS[t]["sides"]))] for t in FAULTS]
    a, b = rng.sample(DOUBLE_POOL, 2)
    plan.append([(a, rng.choice(FAULTS[a]["sides"])), (b, rng.choice(FAULTS[b]["sides"]))])
    return plan


# --- the dropout variant (#25): per-joint conf, and short far-side dropouts ---
CONF_BASE = {"good": 0.95, "low": 0.8}
CONF_FAR_LOSS = 0.25       # confidence a joint loses on the far side from a 90 degree camera
CONF_FLOOR = 0.4           # outside a burst every joint stays above part5.io's 0.3 cutoff
DROPOUT_ANGLES = ("45", "side")
# Far-side joints that drop out. Never a hip: the hip midpoint must stay at the origin.
DROPOUT_JOINTS = ["right_elbow", "right_wrist", "right_knee", "right_ankle"]


def conf_series(joint, yaw_deg, light, n, rng):
    """Per-frame confidence of one joint: lower in low light and on the far side, with slow drift."""
    base = CONF_BASE[light]
    if joint.startswith("right_") and yaw_deg > 0:
        base -= CONF_FAR_LOSS * yaw_deg / 90.0
    return [round(min(1.0, max(CONF_FLOOR, base + x)), 3) for x in smooth_noise(n, 0.03, rng)]


def dropout_bursts(frames, conf, rng):
    """Two to four bursts of 3 to 8 frames: a far-side joint is null, or its conf drops below 0.3."""
    n, bursts = len(frames), []
    for _ in range(rng.randint(2, 4)):
        joint, length = rng.choice(DROPOUT_JOINTS), rng.randint(3, 8)
        start, lost = rng.randint(0, n - length), rng.random() < 0.5
        for i in range(start, start + length):
            if lost:
                frames[i]["joints"][joint] = None
                conf[joint][i] = 0.0
            else:
                conf[joint][i] = round(rng.uniform(0.05, 0.25), 3)
        bursts.append({"joint": joint, "follower_frames": [start, start + length - 1],
                       "mode": "null" if lost else "low_conf"})
    return sorted(bursts, key=lambda b: (b["follower_frames"][0], b["joint"]))


def dropout_copy(doc, meta, seed):
    """The same take with per-joint conf and far-side bursts; its own random stream, so the clean
    takes are the same bytes with or without --dropout-variant."""
    rng = random.Random(f"{seed}/{meta['take_id']}/dropout")
    out = copy.deepcopy(doc)
    n = len(out["frames"])
    conf = {j: conf_series(j, meta["camera_yaw_deg"], meta["lighting"], n, rng) for j in doc["joints"]}
    bursts = dropout_bursts(out["frames"], conf, rng)
    for i, fr in enumerate(out["frames"]):
        fr["conf"] = {j: conf[j][i] for j in doc["joints"]}
    new_meta = {**copy.deepcopy(meta), "take_id": f"{meta['take_id']}_dropout", "variant": "dropout",
                "dropouts": bursts}
    return out, new_meta


# --- the side files and the foot-fault takes (TICKET-040) ---
FOOT_FORMAT_NOTE = "pose3d.json shape (Part 2), synthetic: planted feet (ASM-013)"


def foot_plan(seed, take_id, faults=()):
    """A take's foot stream and faults. The stream is keyed by the take id, so it never reads or moves the
    base stream and a take's feet do not depend on the other takes."""
    return {"rng": random.Random(f"{seed}/{take_id}/feet"), "faults": list(faults)}


def foot_fault_plans(seed, set_name, angle, light):
    """One take per foot fault type for a cell, each with a side drawn from the cell's own stream."""
    rng = random.Random(f"{seed}/{set_name}/{angle}/{light}/foot-plan")
    return [[(t, rng.choice(FOOT_FAULTS[t]["sides"]))] for t in FOOT_FAULTS]


def pose3d_point(p, conf=1.0):
    return {"x": round(p[0], 4), "y": round(p[1], 4), "z": round(p[2], 4), "conf": conf}


def pose3d_doc(joint_names, frames, feet, provenance, joint_conf=None, foot_conf=None):
    """Part 2's pose3d.json shape for one person: the 17 joints and the six `extra_joints` per frame.

    `frames` are skeleton.json frames (`t`, `joints` as [x, y, z]); a joint's `conf` is 1.0 unless `joint_conf`
    ({joint: [per frame]}) says otherwise, and likewise `foot_conf` for the foot points. Part 2 never writes a
    null joint, so a masked joint keeps its position and carries a `conf` below the 0.3 cutoff instead.
    """
    out = []
    for i, fr in enumerate(frames):
        joints = {j: pose3d_point(fr["joints"][j], joint_conf[j][i] if joint_conf else 1.0) for j in joint_names}
        extra = {j: pose3d_point(feet[i][j], foot_conf[j][i] if foot_conf else 1.0) for j in FOOT_JOINTS}
        out.append({"frame": i, "t_ms": round(fr["t"] * 1000, 3),
                    "people": [{"id": 0, "joints": joints, "extra_joints": extra}]})
    return {"frames": out, "t0_pts_ms": 0.0, "provenance": provenance}


def provenance(seed, note):
    return {"source": "synthetic", "generator": "scripts/make_dummy_followers.py", "seed": seed, "note": note}


def expected_feet_doc(expected):
    """The expected clip's side file: Part 4's joints with feet planted at a fixed toe-out, no drift, no noise."""
    n = len(expected["frames"])
    frames = [{j: list(fr["joints"][j]) for j in expected["joints"]} for fr in expected["frames"]]
    yaw = {s: [EXPECTED_TOE_OUT_DEG] * n for s in SIDES}
    roll = {s: [0.0] * n for s in SIDES}
    return pose3d_doc(expected["joints"], expected["frames"], plant_feet(frames, 1.0, yaw, roll),
                      provenance(None, f"expected side: fixed {EXPECTED_TOE_OUT_DEG:g} degree toe-out, no noise; "
                                       f"{FOOT_FORMAT_NOTE}"))


def dropout_feet_doc(clean_doc, dropout_doc, feet, seed):
    """The side file of a dropout copy: the clean positions with the copy's per-joint `conf`, and each foot masked
    in the frames where its ankle is (the foot hangs off the ankle, so a lost ankle loses its foot)."""
    joints = clean_doc["joints"]
    conf = {j: [fr["conf"][j] for fr in dropout_doc["frames"]] for j in joints}
    foot_conf = {}
    for side in SIDES:
        ankle = conf[f"{side}_ankle"]
        for j in FOOT_JOINTS:
            if j.startswith(side):
                foot_conf[j] = [c if c < 0.3 else 1.0 for c in ankle]
    return pose3d_doc(joints, clean_doc["frames"], feet, provenance(seed, FOOT_FORMAT_NOTE + ", dropout copy"),
                      conf, foot_conf)


def clean_feet_doc(doc, feet, seed):
    return pose3d_doc(doc["joints"], doc["frames"], feet, provenance(seed, FOOT_FORMAT_NOTE))


# --- writing the set ---
def rel(path):
    """Path relative to the repo when inside it, else as given (a temp directory in tests)."""
    path = Path(path).resolve()
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def write_take(out, doc, meta, exp_path, feet_doc=None, exp_feet_path=None):
    """Write the take; with `feet_doc` also feet.json beside it. The two foot paths go into the label before
    `expected` and `follower`, so an older label file only gains lines."""
    path = out / meta["set"] / meta["take_id"] / "skeleton.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    if feet_doc is not None:
        feet_path = path.with_name("feet.json")
        feet_path.write_text(json.dumps(feet_doc, separators=(",", ":")) + "\n")
        meta["expected_feet"] = rel(exp_feet_path)
        meta["follower_feet"] = rel(feet_path)
    meta["expected"] = rel(exp_path)
    meta["follower"] = rel(path)


def write_expected_feet(expected, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(expected_feet_doc(expected), separators=(",", ":")) + "\n")


def generate(seed, out=OUT, dropout_variant=False, sets=SETS, angles=tuple(ANGLES), lights=tuple(LIGHTING),
             expected_dir=EXPECTED, feet=False, expected_feet_dir=EXPECTED_FEET):
    """Write the set under `out` and return the labels document. Clean takes come first, in grid
    order; the dropout copies follow in the same order.

    With `feet`, every take also gets a feet.json, each expected set one under `expected_feet_dir`, and the
    foot-fault takes follow the base takes in the clean list (their dropout copies the base copies)."""
    out, rng = Path(out), random.Random(seed)
    # Remove only what this script writes, so hand-written files (README.md) survive a rerun.
    for set_name in sets:
        if (out / set_name).exists():
            shutil.rmtree(out / set_name)
    (out / "labels.json").unlink(missing_ok=True)
    clean, dropped, foot_clean, foot_dropped = [], [], [], []
    expected_of, exp_feet_of = {}, {}
    for set_name in sets:
        exp_path = Path(expected_dir) / set_name / "animation.json"
        expected_of[set_name] = (json.loads(exp_path.read_text()), exp_path)
        if feet:
            exp_feet_of[set_name] = Path(expected_feet_dir) / set_name / "feet.json"
            write_expected_feet(expected_of[set_name][0], exp_feet_of[set_name])

    def emit(set_name, take_id, angle, light, faults, take_rng, plan, takes, copies):
        expected, exp_path = expected_of[set_name]
        doc, meta = build_take(expected, take_id, angle, light, faults, take_rng, plan)
        planted = meta.pop("_feet", None)
        write_take(out, doc, meta, exp_path, None if planted is None else clean_feet_doc(doc, planted, seed),
                   exp_feet_of.get(set_name))
        takes.append(meta)
        if dropout_variant and angle in DROPOUT_ANGLES:
            d_doc, d_meta = dropout_copy(doc, meta, seed)
            write_take(out, d_doc, d_meta, exp_path,
                       None if planted is None else dropout_feet_doc(doc, d_doc, planted, seed),
                       exp_feet_of.get(set_name))
            copies.append(d_meta)

    for set_name in sets:
        for angle in angles:
            for light in lights:
                plans = [[] for _ in range(CORRECT_TAKES_PER_CELL)] + fault_plan(rng)
                for k, faults in enumerate(plans):
                    tag = "correct" if not faults else "+".join(f"{t}-{s}" for t, s in faults)
                    take_id = f"{set_name}_{angle}_{light}_{k:02d}_{tag}"
                    emit(set_name, take_id, angle, light, faults, rng, foot_plan(seed, take_id) if feet else None,
                         clean, dropped)
    if feet:   # the foot-fault takes come after every base take and read streams of their own, so nothing above moves
        for set_name in sets:
            for angle in angles:
                for light in lights:
                    for k, faults in enumerate(foot_fault_plans(seed, set_name, angle, light), BASE_TAKES_PER_CELL):
                        take_id = f"{set_name}_{angle}_{light}_{k:02d}_" + "+".join(f"{t}-{s}" for t, s in faults)
                        emit(set_name, take_id, angle, light, [], random.Random(f"{seed}/{take_id}/body"),
                             foot_plan(seed, take_id, faults), foot_clean, foot_dropped)
    labels = {"format": "simon.part5.labels.v1", "generator": "scripts/make_dummy_followers.py",
              "seed": seed, "label_source": "synthetic", "angles": ANGLES, "lighting": LIGHTING,
              "takes": clean + foot_clean + dropped + foot_dropped}
    (out / "labels.json").write_text(json.dumps(labels, indent=1) + "\n")
    return labels


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--out", default=str(OUT), help="output directory (default fixtures/input/followers)")
    ap.add_argument("--dropout-variant", action="store_true",
                    help="add a dropout copy (per-joint conf, far-side bursts) of every side and 45 degree take")
    ap.add_argument("--feet", action="store_true",
                    help="add planted synthetic feet: a feet.json per take and expected set, and the foot-fault takes")
    ap.add_argument("--expected-feet-dir", default=str(EXPECTED_FEET),
                    help="where --feet writes each expected set's feet.json (default fixtures/input/expected-feet)")
    args = ap.parse_args(argv)
    labels = generate(args.seed, Path(args.out), args.dropout_variant, feet=args.feet,
                      expected_feet_dir=Path(args.expected_feet_dir))
    takes = labels["takes"]
    n_fault = sum(len(t["faults"]) for t in takes)
    dropped = sum(t["variant"] == "dropout" for t in takes)
    print(f"wrote {len(takes)} takes ({sum(t['correct'] for t in takes)} correct, {n_fault} labelled faults, "
          f"{dropped} dropout copies{', with feet' if args.feet else ''}) to {rel(args.out)}")


if __name__ == "__main__":
    main()
