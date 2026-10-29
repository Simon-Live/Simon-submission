"""Rung 1 `kp2d-fit` (TICKET-020, ADR-0004): fit SAM 3D Body's joints, frame by frame, to RTMPose-x 2D keypoints,
keeping SAM's bone lengths (fixed per person over the clip) and SAM's depth as a prior.

Spec: docs/specs/check-2.md ("One-person ladder", "Ladder parameters"). Per frame and person the 17 camera-space
joints X minimise, starting from SAM's X0,

    sum_j |pi(X_j) - a_j|^2 / (S2D H)^2              SAM's own projection a_j: the prior in the image plane
  + sum_j w_j |pi(X_j) - u_j|^2 / (S2D H)^2          RTMPose-x keypoint u_j
  + sum_j (Z_j - Z0_j)^2 / SIGMA_Z^2                  SAM's depth
  + sum_b (|X_a - X_b| - L_b)^2 / (SIGMA_L L_b)^2     the 16 edges of part2.joints.BONES, L_b = SAM's per-person
                                                      median over the clip (one frame for a photo)

with w_j = BETA * min(score_j, 1)^GAMMA / (1 + (|pi(X_j) - u_j| / (C H))^2): RTMPose counts more where its own
score is high, and a joint that stays far from it (a swapped or hidden limb) stops pulling (Cauchy weights,
refreshed every iteration). H is the person's height in px from SAM's own projection: the largest nose to
ankle-midpoint distance over the clip. Gauss-Newton with Levenberg damping; the output's kp2d is its projection.

PARAMS were fixed from label-free objectives only and committed before the rung's one gold scoring: on the seated
clip's 91 unlabelled frames (seated) and the dance clip (dance), unrefined -> chosen, agreement with RTMPose-x
(score-weighted mean px distance, % of H) seated 5.91 -> 4.75, dance 4.32 -> 3.80; mean 2D joint acceleration
(% of H per s^2) seated 32.16 -> 28.71, dance 102.65 -> 99.16; mean 3D joint acceleration (m/s^2) seated 0.543 ->
0.522, dance 7.684 -> 7.673; bone-length CV seated 0.0408 -> 0.0041, dance 0.0638 -> 0.0027; mean 3D move 0.017 m
and 0.016 m. COCO photos, image-level agreement 1.63 -> 1.19 (max 4.31 -> 3.34), mean 3D move 0.007 m.
This module reads no label file and imports no eval module.
"""
import numpy as np

from part2.joints import BONES, CANONICAL
from part2.lifters import project

NAME = "kp2d-fit"
USES_2D = True
# Fixed 2026-10-29 by the label-free rule in docs/specs/check-2.md "Ladder parameters" (grid of 540 points; the
# argmin of the mean relative 2D joint acceleration on the seated clip's 91 unlabelled frames and the dance clip,
# among points whose 3D acceleration is no higher than the unrefined output's and whose bone CV is at most 0.01).
PARAMS = {"BETA": 1.0, "GAMMA": 2.0, "C": 0.2, "S2D": 0.01, "SIGMA_Z": 0.02, "SIGMA_L": 0.01, "ITERS": 15}
EDGES = np.array([[CANONICAL.index(a), CANONICAL.index(b)] for a, b in BONES])
NOSE, LA, RA = (CANONICAL.index(n) for n in ("nose", "left_ankle", "right_ankle"))


def apply(doc: dict, ctx, params: dict | None = None) -> dict:
    """A new body3d document whose people are fitted to ctx.keypoints(doc) (frame, id) -> (kp (17, 2), score (17,))."""
    p = {**PARAMS, **(params or {})}
    K = np.asarray(doc["K"], float)
    kp = ctx.keypoints(doc)
    tracks = person_tracks(doc)
    frames = []
    for f in doc["frames"]:
        people = []
        for person in f["people"]:
            X0 = joints(person)
            u, s = kp.get((f["frame"], person["id"]), (None, None))
            if u is None:
                people.append(person)
                continue
            L, H = tracks[person["id"]]
            X = fit(X0, u, s, K, L, H, p)
            people.append(with_joints(person, X, K))
        frames.append({**f, "people": people})
    return {**doc, "frames": frames}


def joints(person: dict) -> np.ndarray:
    return np.array([person["kp3d_cam"][j] for j in CANONICAL], dtype=float)


def with_joints(person: dict, X: np.ndarray, K) -> dict:
    """The person with new camera-space joints; kp2d is their projection (reproj_self_px 0)."""
    X = np.round(X, 4)
    uv = project(X, K)
    return {**person, "kp3d_cam": {j: x.tolist() for j, x in zip(CANONICAL, X)},
            "kp2d": {j: np.round(x, 2).tolist() for j, x in zip(CANONICAL, uv)}, "reproj_self_px": 0.0}


def person_tracks(doc: dict) -> dict:
    """{id: (bone lengths (16,), height px)}: SAM's median bone lengths and largest projected nose to ankle-mid."""
    K = np.asarray(doc["K"], float)
    by_id: dict = {}
    for f in doc["frames"]:
        for person in f["people"]:
            by_id.setdefault(person["id"], []).append(joints(person))
    out = {}
    for pid, xs in by_id.items():
        X = np.stack(xs)
        L = np.median(np.linalg.norm(X[:, EDGES[:, 0]] - X[:, EDGES[:, 1]], axis=-1), axis=0)
        uv = project(X, K)
        H = float(np.max(np.linalg.norm(uv[:, NOSE] - (uv[:, LA] + uv[:, RA]) / 2, axis=-1)))
        out[pid] = (L, max(H, 1.0))
    return out


def cauchy(e, scale) -> np.ndarray:
    return 1.0 / (1.0 + (np.asarray(e) / scale) ** 2)


def fit(X0, u, s, K, L, H, p: dict) -> np.ndarray:
    """The fitted (17, 3) joints for one person in one frame (see the module docstring)."""
    X0, u, K = np.asarray(X0, float), np.asarray(u, float), np.asarray(K, float)
    a = project(X0, K)
    score = np.clip(np.asarray(s, float), 0.0, 1.0) ** p["GAMMA"]
    px = p["S2D"] * H
    X, mu = X0.copy(), 1e-3
    for _ in range(int(p["ITERS"])):
        w = p["BETA"] * score * cauchy(np.linalg.norm(project(X, K) - u, axis=1), p["C"] * H)
        r, J = _system(X, X0, a, u, w, K, L, px, p)
        A = J.T @ J
        g = J.T @ r
        cost = r @ r
        while True:
            step = np.linalg.solve(A + mu * np.diag(np.diag(A) + 1e-9), -g)
            Xn = X + step.reshape(17, 3)
            if np.all(Xn[:, 2] > 1e-3):
                rn, _ = _system(Xn, X0, a, u, w, K, L, px, p)
                if rn @ rn <= cost:
                    X, mu = Xn, max(mu / 3, 1e-7)
                    break
            mu *= 4
            if mu > 1e6:
                return X
    return X


def _system(X, X0, a, u, w, K, L, px, p):
    """Stacked residuals and their Jacobian (rows: prior 2D, RTMPose 2D, depth, bones; columns: X.ravel())."""
    fx, fy = K[0, 0], K[1, 1]
    uv = project(X, K)
    Z = X[:, 2]
    dpi = np.zeros((17, 2, 3))  # d(u, v) / d(x, y, z) per joint
    dpi[:, 0, 0], dpi[:, 0, 2] = fx / Z, -fx * X[:, 0] / Z ** 2
    dpi[:, 1, 1], dpi[:, 1, 2] = fy / Z, -fy * X[:, 1] / Z ** 2
    sw = np.sqrt(w)
    rows_r, rows_j = [], []
    for res, scale in (((uv - a) / px, np.ones(17) / px), ((uv - u) * sw[:, None] / px, sw / px)):
        Jb = np.zeros((34, 51))
        for j in range(17):
            Jb[2 * j:2 * j + 2, 3 * j:3 * j + 3] = dpi[j] * scale[j]
        rows_r.append(res.ravel())
        rows_j.append(Jb)
    Jz = np.zeros((17, 51))
    Jz[np.arange(17), 3 * np.arange(17) + 2] = 1.0 / p["SIGMA_Z"]
    rows_r.append((Z - X0[:, 2]) / p["SIGMA_Z"])
    rows_j.append(Jz)
    d = X[EDGES[:, 0]] - X[EDGES[:, 1]]
    n = np.maximum(np.linalg.norm(d, axis=1), 1e-9)
    sl = p["SIGMA_L"] * np.maximum(L, 1e-3)
    Jl = np.zeros((len(EDGES), 51))
    for k, (ia, ib) in enumerate(EDGES):
        Jl[k, 3 * ia:3 * ia + 3] = d[k] / n[k] / sl[k]
        Jl[k, 3 * ib:3 * ib + 3] = -d[k] / n[k] / sl[k]
    rows_r.append((n - L) / sl)
    rows_j.append(Jl)
    return np.concatenate(rows_r), np.vstack(rows_j)
