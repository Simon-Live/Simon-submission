"""Lifter B `fixed-bones`: per-person bone lengths fitted once over the clip, joints placed on their rays.

Spec: docs/specs/backends-gpu-cpu.md ("Lifter B"); ADR-0002. No model, numpy only.

1. Rays r = K^-1 [u, v, 1]; q = their image-plane part (px / f).
2. Depth: Z0 = H_REF / P90 over frames of the nose to ankle-midpoint span in q.
3. Lengths: each of the 12 non-face bones (plus the nose to shoulder-midpoint "neck" and the
   shoulder-midpoint to hip-midpoint "torso" used for scale) is the 90th percentile over frames where
   both ends have conf >= 0.5 of its 2D length at depth Z; left/right pairs take their mean; a bone
   never seen falls back to its partner, then to RATIO (bone length over the 12-bone mean, measured
   on the GPU squat fixture fixtures/output/single, a different clip). Scale: the lengths are
   multiplied so neck + torso + thigh + shin (a standing nose to ankle span, posture-invariant) equals
   H_REF. Per-frame depth Z[t] is then the depth at which no confident bone exceeds its length (the
   bone most parallel to the image sets it), median-filtered over 5 frames; lengths are refitted once.
4. Placement walks the tree from the hip midpoint at Z[t]: the left hip at half the hip width, the right
   hip at the hip width from it, the left shoulder from the left hip, the right shoulder at the best fit
   to its side bone and the shoulder width, then elbows, wrists, knees and ankles. Each child
   solves |s r - P| = L (two roots: near or far); no real root takes the closest point on the ray and
   counts in `clipped`. Face joints sit on their rays at the shoulder-midpoint depth.
5. Signs: one bit per root choice (hip line, left torso side, eight limb bones; 2^10 configurations)
   chosen by Viterbi over the clip to minimise sign changes between frames (1 each) plus W_ANGLE per
   elbow or knee bent backwards past BENT_DEG, W_ANGLE for a torso leaning back past LEAN_BACK_DEG,
   W_FACE times the disagreement between the nose direction and the body's front, and W_WIDTH times
   the relative shoulder-width error.
6. Each joint's depth is median-filtered over 5 frames and every frame re-placed with the configuration
   closest to the smoothed depths. Every joint stays on its ray, so the output reprojects onto kp2d.

Deviations from the spec text, chosen label-free (2D only): step 2 uses one clip depth instead of
f * H_REF / h2d[t] per frame (on the single fixture h2d varies by a CV of 0.25 while the seated subject
stays in place), H_REF scales a standing chain instead of the seated span, and the hip line and torso
sides are solved with the limbs.
"""
from itertools import product

import numpy as np

from part2.lifters import BODY_BONES, J, ROOT_RANGE_M, bone_cv, rays

NAME = "fixed-bones"
H_REF = 1.60
CONF_MIN = 0.5
LENGTH_PCT = 90
BENT_DEG = 10.0
LEAN_BACK_DEG = 30.0
W_ANGLE, W_FACE, W_WIDTH = 1.0, 1.0, 1.0
MEDIAN_WIN = 5
SEGMENTS = list(BODY_BONES) + [("nose", "shoulder_mid"), ("shoulder_mid", "hip_mid")]
SEG = {s: i for i, s in enumerate(SEGMENTS)}
NECK, TORSO = len(BODY_BONES), len(BODY_BONES) + 1
PAIRS = [(("left_shoulder", "left_elbow"), ("right_shoulder", "right_elbow")),
         (("left_elbow", "left_wrist"), ("right_elbow", "right_wrist")),
         (("left_shoulder", "left_hip"), ("right_shoulder", "right_hip")),
         (("left_hip", "left_knee"), ("right_hip", "right_knee")),
         (("left_knee", "left_ankle"), ("right_knee", "right_ankle"))]
# Bone length / mean of the 12 body bones on the GPU squat fixture (SAM 3D Body, fixtures/output/single).
RATIO = np.array([0.914, 0.757, 0.684, 0.757, 0.688, 1.484, 1.506, 0.494, 1.219, 1.140, 1.219, 1.136, 0.813, 1.480])
CHAIN = [NECK, TORSO, SEG[("left_hip", "left_knee")], SEG[("left_knee", "left_ankle")]]  # standing nose to ankle
# A fitted length under this fraction of the RATIO prediction was never seen near full length: use RATIO.
# 0.75 sits outside the usual person-to-person spread of bone ratios (about 15%).
SHORT_FRACTION = 0.75
# Bits 1.. : (parent, child) solved from the parent; bit 0 is the hip line (left hip near or far).
CHAINS = [("left_hip", "left_shoulder"),
          ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
          ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
          ("left_hip", "left_knee"), ("left_knee", "left_ankle"),
          ("right_hip", "right_knee"), ("right_knee", "right_ankle")]
N_BITS = 1 + len(CHAINS)
CONFIGS = np.array(list(product([0, 1], repeat=N_BITS)), dtype=np.int8)  # (1024, 10)
FACE_JOINTS = ["nose", "left_eye", "right_eye", "left_ear", "right_ear"]
BODY_JOINTS = [J[name] for name in J if name not in FACE_JOINTS]
UP = np.array([0.0, -1.0, 0.0])  # camera up, as part2.canonical assumes a level camera
CHUNK = 32  # frames per batch of the 1024-configuration search (bounds memory on long clips)


class FixedBones:
    name = NAME

    def available(self) -> tuple[bool, str]:
        return True, "numpy only"

    def models(self) -> list:
        return []

    def licence_notes(self) -> list:
        return []

    def lift(self, kp2d, conf, K, image_size=None, fps=None) -> np.ndarray:
        return self.lift_info(kp2d, conf, K, image_size, fps)[0]

    def lift_info(self, kp2d, conf, K, image_size=None, fps=None) -> tuple[np.ndarray, dict]:
        kp2d, conf = np.asarray(kp2d, float), np.asarray(conf, float)
        if kp2d.ndim != 3 or kp2d.shape[1:] != (17, 2) or conf.shape != kp2d.shape[:2] or not len(kp2d):
            raise ValueError(f"fixed-bones: expected kp2d (n, 17, 2) and conf (n, 17), got {kp2d.shape}, {conf.shape}")
        r = rays(kp2d, K)
        lengths, Z, fit = fit_lengths(r[..., :2], conf >= CONF_MIN)
        pos, clipped = solve(r, lengths, Z, conf >= CONF_MIN)
        cv = bone_cv(pos)
        return pos, {"lifter": NAME, "H_ref_m": H_REF, "clipped": int(clipped), **fit,
                     "bone_lengths_m": {"-".join(b): round(float(lengths[i]), 4) for i, b in enumerate(BODY_BONES)},
                     "root_depth_m": [round(float(Z.min()), 3), round(float(np.median(Z)), 3), round(float(Z.max()), 3)],
                     "bone_cv_mean": round(float(cv.mean()), 5), "bone_cv_max": round(float(cv.max()), 5)}


def _points(q, name):
    if name == "shoulder_mid":
        return (q[:, J["left_shoulder"]] + q[:, J["right_shoulder"]]) / 2
    if name == "hip_mid":
        return (q[:, J["left_hip"]] + q[:, J["right_hip"]]) / 2
    return q[:, J[name]]


def _ok(valid, name):
    if name == "shoulder_mid":
        return valid[:, J["left_shoulder"]] & valid[:, J["right_shoulder"]]
    if name == "hip_mid":
        return valid[:, J["left_hip"]] & valid[:, J["right_hip"]]
    return valid[:, J[name]]


def segment_lengths(q, valid) -> tuple[np.ndarray, np.ndarray]:
    """(n, 14) image-plane lengths of SEGMENTS and (n, 14) both-ends-confident masks."""
    n2d = np.stack([np.linalg.norm(_points(q, a) - _points(q, b), axis=1) for a, b in SEGMENTS], axis=1)
    ok = np.stack([_ok(valid, a) & _ok(valid, b) for a, b in SEGMENTS], axis=1)
    return n2d, ok


def fit_lengths(q, valid) -> tuple[np.ndarray, np.ndarray, dict]:
    """Bone lengths (12,) in metres, per-frame root depth (n,) and fit notes (steps 2 and 3)."""
    n2d, ok = segment_lengths(q, valid)
    ankles = (_points(q, "left_ankle") + _points(q, "right_ankle")) / 2
    span = np.linalg.norm(_points(q, "nose") - ankles, axis=1)
    span_ok = valid[:, J["nose"]] & valid[:, J["left_ankle"]] & valid[:, J["right_ankle"]]
    use = span[span_ok] if span_ok.any() else span
    z = np.full(len(q), H_REF / max(float(np.percentile(use, LENGTH_PCT)), 1e-6))
    for _ in range(2):
        lengths, fallback = _percentile_lengths(n2d, ok, z)
        scale = H_REF / lengths[CHAIN].sum()
        lengths = lengths * scale
        z = frame_depths(n2d[:, :NECK], ok[:, :NECK], lengths[:NECK], np.median(z) * scale)
    return lengths[:NECK], z, {"fallback_bones": fallback, "scale_chain_m": round(float(H_REF / scale), 4)}


def _percentile_lengths(n2d, ok, z) -> tuple[np.ndarray, list]:
    lower = n2d * z[:, None]
    lengths = np.array([np.percentile(lower[ok[:, k], k], LENGTH_PCT) if ok[:, k].any() else np.nan
                        for k in range(len(SEGMENTS))])
    for a, b in PAIRS:
        i, k = SEG[a], SEG[b]
        lengths[i] = lengths[k] = np.nanmean([lengths[i], lengths[k]]) if ~np.isnan(lengths[[i, k]]).all() else np.nan
    seen = ~np.isnan(lengths)
    unit = float(np.median(lengths[seen] / RATIO[seen])) if seen.any() else H_REF / RATIO[CHAIN].sum()
    short = seen & (lengths < SHORT_FRACTION * RATIO * unit)  # never seen near full length (end-on all clip)
    use = seen & ~short
    unit = float(np.median(lengths[use] / RATIO[use])) if use.any() else unit
    lengths = np.where(use, lengths, RATIO * unit)
    return lengths, ["-".join(SEGMENTS[k]) for k in range(len(SEGMENTS)) if not use[k]]


def frame_depths(n2d, ok, lengths, z_default) -> np.ndarray:
    """Per frame, the largest depth at which every confident bone still fits its length; median over 5."""
    ratio = np.where(ok & (n2d > 1e-9), lengths[None] / np.maximum(n2d, 1e-9), np.inf)
    z = ratio.min(axis=1)
    z = np.where(np.isfinite(z), z, z_default)
    return np.clip(median_filter(z, MEDIAN_WIN), *ROOT_RANGE_M)


def median_filter(x, win) -> np.ndarray:
    """Centred running median along axis 0; the window shrinks at the ends."""
    x = np.asarray(x, float)
    h = win // 2
    return np.stack([np.median(x[max(0, t - h): t + h + 1], axis=0) for t in range(len(x))])


def _root(P, r, L, far):
    """Points s*r with |s r - P| = L: far (bool, broadcast) picks the larger s. Returns (points, clipped)."""
    a = (r * r).sum(-1)
    b = (r * P).sum(-1)
    c = (P * P).sum(-1) - L * L
    disc = b * b - a * c
    sq = np.sqrt(np.maximum(disc, 0.0))
    s = (b + np.where(far, sq, -sq)) / a
    return s[..., None] * r, disc < 0


def _two_lengths(r, P1, L1, P2, L2):
    """The point on ray r best keeping |X - P1| = L1 and |X - P2| = L2 (relative squared residuals):
    the best of each quadratic's roots and the midpoints of every root pair. Clipped: no root for P1."""
    cand = []
    for far1 in (False, True):
        a, clip = _root(P1, r, L1, far1)
        cand.append(a)
        for far2 in (False, True):
            b, _ = _root(P2, r, L2, far2)
            cand += [b, (a + b) / 2]
    cand = np.stack(cand)  # (m, ..., 3)
    res = ((np.linalg.norm(cand - P1, axis=-1) - L1) / L1) ** 2 + ((np.linalg.norm(cand - P2, axis=-1) - L2) / L2) ** 2
    best = res.argmin(axis=0)
    point = np.take_along_axis(cand, best[None, ..., None], axis=0)[0]
    return point, _root(P1, r, L1, False)[1]


def place(r, lengths, Z, bits) -> tuple[np.ndarray, np.ndarray]:
    """Joint positions (n, C, 17, 3) for configurations bits (n or 1, C, 10); clipped counts (n, C)."""
    n, C = len(r), bits.shape[1]
    L = {b: lengths[i] for i, b in enumerate(BODY_BONES)}
    rr = r[:, None]  # (n, 1, 17, 3)
    pos = np.zeros((n, C, 17, 3))
    clipped = np.zeros((n, C), dtype=int)
    root = (Z[:, None] * (r[:, J["left_hip"]] + r[:, J["right_hip"]]) / 2)[:, None]  # (n, 1, 3)
    lh, c0 = _root(root, rr[:, :, J["left_hip"]], L[("left_hip", "right_hip")] / 2, bits[..., 0] == 1)
    cand = [_root(lh, rr[:, :, J["right_hip"]], L[("left_hip", "right_hip")], far) for far in (False, True)]
    mid_err = [np.linalg.norm((lh + p) / 2 - root, axis=-1) for p, _ in cand]
    take_far = mid_err[1] < mid_err[0]
    pos[:, :, J["left_hip"]] = lh
    pos[:, :, J["right_hip"]] = np.where(take_far[..., None], cand[1][0], cand[0][0])
    clipped += c0 + np.where(take_far, cand[1][1], cand[0][1])
    for k, (parent, child) in enumerate(CHAINS, start=1):
        length = L[(parent, child)] if (parent, child) in L else L[(child, parent)]
        p, c = _root(pos[:, :, J[parent]], rr[:, :, J[child]], length, bits[..., k] == 1)
        pos[:, :, J[child]] = p
        clipped += c
        if child == "left_shoulder":
            rs, c = _two_lengths(rr[:, :, J["right_shoulder"]], pos[:, :, J["right_hip"]],
                                 L[("right_shoulder", "right_hip")], p, L[("left_shoulder", "right_shoulder")])
            pos[:, :, J["right_shoulder"]] = rs
            clipped += c
    z_face = (pos[:, :, J["left_shoulder"], 2] + pos[:, :, J["right_shoulder"], 2]) / 2
    for name in FACE_JOINTS:
        pos[:, :, J[name]] = z_face[..., None] * rr[:, :, J[name]]
    return pos, clipped


def _angle_bent(a, b) -> np.ndarray:
    cos = (a * b).sum(-1) / np.maximum(np.linalg.norm(a, axis=-1) * np.linalg.norm(b, axis=-1), 1e-12)
    return cos < np.cos(np.radians(BENT_DEG))


def body_axes(pos) -> tuple[np.ndarray, np.ndarray]:
    """Subject's left (horizontal hip line) and front (left x up), as part2.canonical defines them."""
    x = pos[..., J["left_hip"], :] - pos[..., J["right_hip"], :]
    x = x - (x @ UP)[..., None] * UP
    x = x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-12)
    return x, np.cross(x, UP)


def unary(pos, lengths, valid) -> np.ndarray:
    """Per frame and configuration: joint-angle, lean, facing and shoulder-width costs (step 5)."""
    x, front = body_axes(pos)
    P = lambda name: pos[..., J[name], :]  # noqa: E731
    cost = np.zeros(pos.shape[:2])
    for hip, knee, ankle in (("left_hip", "left_knee", "left_ankle"), ("right_hip", "right_knee", "right_ankle")):
        a, b = P(knee) - P(hip), P(ankle) - P(knee)
        cost += W_ANGLE * (_angle_bent(a, b) & ((np.cross(a, b) * x).sum(-1) < 0))
    for sh, el, wr in (("left_shoulder", "left_elbow", "left_wrist"), ("right_shoulder", "right_elbow", "right_wrist")):
        a, b = P(el) - P(sh), P(wr) - P(el)
        cost += W_ANGLE * (_angle_bent(a, b) & ((np.cross(a, b) * x).sum(-1) > 0))
    torso = (P("left_shoulder") + P("right_shoulder") - P("left_hip") - P("right_hip")) / 2
    back = (torso * front).sum(-1) < -np.linalg.norm(torso, axis=-1) * np.sin(np.radians(LEAN_BACK_DEG))
    cost += W_ANGLE * back
    width = lengths[SEG[("left_shoulder", "right_shoulder")]]
    cost += W_WIDTH * np.abs(np.linalg.norm(P("left_shoulder") - P("right_shoulder"), axis=-1) - width) / width
    return cost + W_FACE * facing(pos, front, valid)


def facing(pos, front, valid) -> np.ndarray:
    """max(0, -cos) between the nose direction (nose minus confident ears) and the body's front."""
    ears = np.stack([valid[:, J["left_ear"]], valid[:, J["right_ear"]]], axis=1).astype(float)
    have = valid[:, J["nose"]] & (ears.sum(1) > 0)
    ear_pts = (pos[..., J["left_ear"], :] * ears[:, None, :1] + pos[..., J["right_ear"], :] * ears[:, None, 1:])
    ear_pts = ear_pts / np.maximum(ears.sum(1), 1)[:, None, None]
    d = pos[..., J["nose"], :] - ear_pts
    cos = (d * front).sum(-1) / np.maximum(np.linalg.norm(d, axis=-1), 1e-12)
    return np.where(have[:, None], np.maximum(0.0, -cos), 0.0)


def viterbi(cost) -> np.ndarray:
    """Configuration index per frame minimising unary cost plus 1 per flipped bit between frames."""
    flips = (CONFIGS[:, None, :] != CONFIGS[None, :, :]).sum(-1).astype(np.float32)
    v = cost[0].astype(np.float32)
    back = np.zeros(cost.shape, dtype=np.int32)
    for t in range(1, len(cost)):
        tot = v[:, None] + flips
        back[t] = tot.argmin(axis=0)
        v = tot[back[t], np.arange(len(v))] + cost[t]
    path = np.zeros(len(cost), dtype=np.int32)
    path[-1] = int(v.argmin())
    for t in range(len(cost) - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    return path


def solve(r, lengths, Z, valid) -> tuple[np.ndarray, int]:
    """Steps 4 to 6: positions (n, 17, 3) and the clipped bone count of the final placement."""
    chunks = [slice(i, i + CHUNK) for i in range(0, len(r), CHUNK)]
    cost = np.concatenate([unary(place(r[c], lengths, Z[c], CONFIGS[None])[0], lengths, valid[c]) for c in chunks])
    path = viterbi(cost)
    first, _ = place(r, lengths, Z, CONFIGS[path][:, None])
    z = median_filter(first[:, 0, :, 2], MEDIAN_WIN)
    best = np.empty(len(r), dtype=int)
    for c in chunks:
        pos, _ = place(r[c], lengths, Z[c], CONFIGS[None])
        dev = np.abs(pos[..., BODY_JOINTS, 2] - z[c][:, None, BODY_JOINTS]).sum(-1)
        dev[np.arange(len(dev)), path[c]] -= 1e-9  # ties keep the step-5 choice
        best[c] = dev.argmin(axis=1)
    final, clipped = place(r, lengths, Z, CONFIGS[best][:, None])
    return final[:, 0], int(clipped.sum())
