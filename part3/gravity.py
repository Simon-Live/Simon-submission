"""The phone's gravity as the up of every frame (TICKET-041, ADR-0004 amendment 3).

Part 2 (`part2 run --gravity`, TICKET-055) writes, per person and frame, `up` = R^T up_camera: the true vertical in
that frame's own canonical axes. Part 2 rebuilds those axes every frame from the hip line, so x and z of `up` turn
with the pelvis while y stays cos(tilt). One clip-level vector would therefore be wrong once the hips turn; the
per-frame values go to `geometry.pelvis_frame` as they are. `resolve` validates them, fills a missing or invalid frame
from the nearest valid one, and keeps a fixed-frame summary (for `trace.up_in_input` and the body-rule angle only).
A phone that moves during the take is NOT visible in Part 2's input (one up_camera per take, so every frame has the
same tilt and spread_deg is 0); `body_rule_max_deg` is the only check that can see it. Without any `up` in the input
nothing is read and nothing is added to the output.
"""

import collections

import numpy as np

from part3 import geometry

UNIT_TOL = 1e-2          # |norm - 1| allowed on a per-frame up (Part 2 writes 6 decimals; its validator allows 1e-3)
MIN_VALID_SHARE = 0.5    # at least this share of the person's frames must hold a valid up
SPREAD_WARN_DEG = 5.0    # warn when the per-frame tilts (angle from +y, unchanged by pelvis yaw) differ by more
OUTLIER_DEG = 30.0       # a frame whose tilt is further than this from the median tilt is invalid (one flipped frame)
# Heuristic, fitted to nothing: over the aligned frames, the largest angle between the body line and gravity. A phone
# that moved during the take (Part 2 writes ONE up_camera per take, so spread_deg cannot see it) leaves the body
# line off gravity by the movement. Aligned = straight knees and the trunk within ALIGN_DEG of the leg line (hip
# midpoint to ankle midpoint), so a hinge (good morning, forward fold, single-leg RDL) is left out: there the trunk is
# not the body line, and a still level phone would show 27 to 67 degrees.
MAX_BODY_ANGLE_WARN_DEG = 25.0
ALIGN_DEG = 15.0
MISSING = object()


def collect(doc, frame_positions, chosen):
    """The raw `up` of the chosen person in each frame at `frame_positions` (MISSING when the key is absent).

    Returns None when the input carries no gravity at all (no top-level `gravity` and no `up` on this person).
    """
    frames = doc["frames"]
    raw = []
    for position in frame_positions:
        entry = next(e for e in frames[int(position)]["people"]
                     if type(e["id"]) is type(chosen) and e["id"] == chosen)
        raw.append(entry["up"] if "up" in entry else MISSING)
    if "gravity" not in doc and all(r is MISSING for r in raw):
        return None
    return raw


def _valid_up(value):
    """The value as a float vector of length 1 (within UNIT_TOL), or None when it is not three finite numbers."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    if any(isinstance(c, bool) or not isinstance(c, (int, float)) for c in value):
        return None
    v = np.array(value, dtype=float)
    if not np.all(np.isfinite(v)) or abs(float(np.linalg.norm(v)) - 1.0) > UNIT_TOL:
        return None
    return v


Gravity = collections.namedtuple("Gravity", "per_frame summary")   # per_frame (n, 3); summary (3,) fixed-frame only


def _ignored(reason):
    return None, {"gravity_ignored": reason}


def _nearest_valid(ok):
    """For each row the index of the nearest valid row (ties to the earlier one)."""
    positions = np.flatnonzero(ok)
    at = np.searchsorted(positions, np.arange(len(ok)))
    lo, hi = positions[np.clip(at - 1, 0, len(positions) - 1)], positions[np.clip(at, 0, len(positions) - 1)]
    idx = np.arange(len(ok))
    return np.where(np.abs(idx - lo) <= np.abs(hi - idx), lo, hi)


def _summary(good):
    """One fixed-frame vector for the trace and the body-rule angle: the median tilt about the median horizontal."""
    tilt = np.radians(np.median(geometry.angle_between(good, geometry.INPUT_UP)))
    flat = np.median(good[:, [0, 2]], axis=0)
    flat = flat / np.linalg.norm(flat) if np.linalg.norm(flat) > 1e-9 else np.array([0.0, 1.0])
    return np.array([np.sin(tilt) * flat[0], np.cos(tilt), np.sin(tilt) * flat[1]])


def _aligned_angles(J, per_frame):
    """Angles between the feet-to-shoulders line and that frame's gravity over the aligned frames (may be empty).

    Aligned: both knees straight and the trunk (hip to shoulder midpoint) within ALIGN_DEG of the leg line (hip
    midpoint to ankle midpoint).
    """
    J = np.asarray(J, dtype=float)
    ankle_mid = 0.5 * (geometry.point(J, "left_ankle") + geometry.point(J, "right_ankle"))
    straight = np.all(geometry.knee_angles(J) > geometry.STANDING_KNEE_DEG, axis=-1)
    trunk = geometry.point(J, geometry.NECK) - geometry.point(J, geometry.ROOT)
    leg = geometry.point(J, geometry.ROOT) - ankle_mid
    aligned = straight & (geometry.angle_between(trunk, leg) <= ALIGN_DEG)   # NaN (no trunk) compares False
    line = geometry.point(J, geometry.NECK) - ankle_mid
    return geometry.angle_between(line[aligned], per_frame[aligned])


def resolve(raw, J, mirrored, floor_work):
    """(Gravity or None, frame-block additions) from the raw per-frame values aligned with the rows of J (n, 17, 3).

    `mirrored` is true when Part 3 mirrors J (x negated), so each vertical's x is negated with it. A refused gravity
    gives (None, {"gravity_ignored": reason}). A frame is invalid when its value is not three finite unit-length
    numbers or its tilt from +y is more than OUTLIER_DEG from the median tilt; with no valid frame, or fewer than half
    valid, gravity is refused. Otherwise `per_frame` holds each row's own valid up (an invalid row takes the nearest
    valid one) and the block records frames used and seen, `spread_deg` (largest difference between a frame's tilt and
    the median tilt; pelvis yaw does not change it; it only sees a producer whose per-frame values disagree), the body
    rules alone (without the floor-work hint) as `body_rule_source`, and over the aligned frames the median and the
    largest angle between the feet-to-shoulders line and gravity (`body_rule_angle_deg`, `body_rule_max_deg`; the
    summary to the body rule and no max when no frame is aligned). `warning`s: spread over SPREAD_WARN_DEG; and, on an
    exercise not marked floor work (where a lying body is expected to differ), the largest angle over
    MAX_BODY_ANGLE_WARN_DEG, which is the only sign of a phone that moved. There is no separate median rule: the
    largest is never below the median. Gravity is preferred in every case.
    """
    total = len(raw)
    ups = [_valid_up(r) for r in raw]
    ok = np.array([u is not None for u in ups], dtype=bool)
    if not ok.any():
        return _ignored("no frame holds a valid up (three finite numbers, unit length)")
    good = np.array([u for u in ups if u is not None], dtype=float)
    if mirrored:
        good = good * np.array([-1.0, 1.0, 1.0])
    tilts = geometry.angle_between(good, geometry.INPUT_UP)
    near = np.abs(tilts - np.median(tilts)) <= OUTLIER_DEG
    ok[np.flatnonzero(ok)[~near]] = False
    good, tilts = good[near], tilts[near]
    if ok.sum() < MIN_VALID_SHARE * total:
        return _ignored(f"only {int(ok.sum())} of {total} frames hold a valid up")
    spread = float(np.max(np.abs(tilts - np.median(tilts))))
    full = np.zeros((total, 3))
    full[ok] = good
    full = full[_nearest_valid(ok)]
    summary = _summary(good)
    body_up, body_source = geometry.body_up(J)   # the body rules alone, without the floor-work hint
    angles = _aligned_angles(J, full)
    block = {"frames_used": int(ok.sum()), "frames_total": total, "spread_deg": round(spread, 3),
             "body_rule_source": body_source,
             "body_rule_angle_deg": round(float(np.median(angles)) if angles.size
                                          else float(geometry.angle_between(summary, body_up)), 3)}
    if angles.size:
        block["body_rule_max_deg"] = round(float(angles.max()), 3)
    warnings = []
    if spread > SPREAD_WARN_DEG:
        warnings.append(f"the per-frame ups tilt {spread:.1f} degrees apart (limit {SPREAD_WARN_DEG:.0f})")
    if angles.size and not floor_work and block["body_rule_max_deg"] > MAX_BODY_ANGLE_WARN_DEG:
        warnings.append(f"gravity is {block['body_rule_max_deg']:.1f} degrees from the body line in the worst "
                        f"aligned frame (limit {MAX_BODY_ANGLE_WARN_DEG:.0f}); the phone may have moved")
    if warnings:
        block["warning"] = "; ".join(warnings) + "; gravity was used"
    return Gravity(full, summary), {"gravity": block}
