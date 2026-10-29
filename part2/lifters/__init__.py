"""Lifter registry for the CPU backend: one person's 2D keypoint sequence -> camera-frame 3D in metres.

Spec: docs/specs/backends-gpu-cpu.md ("Lifter B", "Lifter C"); ADR-0002.

    l = lifters.get("fixed-bones")                  # or "motionbert"; unknown names raise UnknownLifter
    kp3d = l.lift(kp2d, conf, K, image_size, fps)   # (n, 17, 2) px, (n, 17) -> (n, 17, 3) m, OpenCV camera
    kp3d, info = l.lift_info(...)                   # same, plus counts for provenance (clipped, fallbacks)

Choice: flag, then PART2_LIFTER, then DEFAULT (resolve). Lifter modules load on first use, so importing
this package never imports torch. Shared geometry (rays, bone lengths, root depth search) lives here.
"""
import importlib
import os

import numpy as np

from part2.joints import BONES, CANONICAL

ENV = "PART2_LIFTER"
# Provisional (lower mean_m vs the HPC reference, neither lifter passes); TICKET-016 sets it from the
# local GPU measurement (AC-B10).
DEFAULT = "fixed-bones"
_REGISTRY = {"fixed-bones": ("part2.lifters.fixed_bones", "FixedBones"),
             "motionbert": ("part2.lifters.motionbert", "MotionBert")}

J = {name: i for i, name in enumerate(CANONICAL)}
FACE = {"nose", "left_eye", "right_eye", "left_ear", "right_ear"}
BODY_BONES = [b for b in BONES if not set(b) & FACE]  # the 12 non-face bones of the 3D bar
BODY_IDX = np.array([[J[a], J[b]] for a, b in BODY_BONES])
ROOT_RANGE_M = (1.0, 20.0)


class UnknownLifter(ValueError):
    def __init__(self, name, known):
        self.name, self.known = name, list(known)
        super().__init__(f'unknown lifter "{name}"; choose {" or ".join(self.known)}')


def names() -> list[str]:
    return sorted(_REGISTRY)


def resolve(flag: str | None = None, env=None) -> str:
    env = os.environ if env is None else env
    name = flag or env.get(ENV) or DEFAULT
    if name not in _REGISTRY:
        raise UnknownLifter(name, names())
    return name


def get(name: str):
    if name not in _REGISTRY:
        raise UnknownLifter(name, names())
    module, cls = _REGISTRY[name]
    return getattr(importlib.import_module(module), cls)()


def rays(kp2d, K) -> np.ndarray:
    """(..., 17, 2) px -> (..., 17, 3) rays K^-1 [u, v, 1] (z = 1)."""
    kp2d, K = np.asarray(kp2d, float), np.asarray(K, float)
    x = (kp2d[..., 0] - K[0, 2]) / K[0, 0]
    y = (kp2d[..., 1] - K[1, 2]) / K[1, 1]
    return np.stack([x, y, np.ones_like(x)], axis=-1)


def project(points, K) -> np.ndarray:
    """(..., 3) camera points -> (..., 2) px."""
    p, K = np.asarray(points, float), np.asarray(K, float)
    z = np.where(np.abs(p[..., 2]) < 1e-9, 1e-9, p[..., 2])
    return np.stack([p[..., 0] / z * K[0, 0] + K[0, 2], p[..., 1] / z * K[1, 1] + K[1, 2]], axis=-1)


def bone_lengths(kp3d) -> np.ndarray:
    """(n, 17, 3) -> (n, 12) lengths of BODY_BONES."""
    kp3d = np.asarray(kp3d, float)
    return np.linalg.norm(kp3d[:, BODY_IDX[:, 0]] - kp3d[:, BODY_IDX[:, 1]], axis=-1)


def bone_cv(kp3d) -> np.ndarray:
    """Per-bone std / mean over frames, (12,)."""
    lengths = bone_lengths(kp3d)
    mean = lengths.mean(axis=0)
    return np.where(mean > 0, lengths.std(axis=0) / np.where(mean > 0, mean, 1), 0.0)


def hip_mid(a) -> np.ndarray:
    return (np.asarray(a)[..., J["left_hip"], :] + np.asarray(a)[..., J["right_hip"], :]) / 2


def place_root(rel, kp2d, conf, K, zrange=ROOT_RANGE_M, iters=60) -> np.ndarray:
    """Translate root-relative poses (n, 17, 3), hip midpoint at the origin, onto the camera.

    The hip midpoint goes on the ray through the 2D hip midpoint at the depth in zrange that
    minimises the confidence-weighted squared reprojection error (coarse grid, then golden section).
    """
    rel, kp2d = np.asarray(rel, float), np.asarray(kp2d, float)
    w = np.clip(np.asarray(conf, float), 0.0, None)
    w = np.where(w.sum(axis=1, keepdims=True) > 0, w, 1.0)
    r0 = rays(hip_mid(kp2d), K)  # (n, 3)

    def cost(z):  # z (n, m) -> (n, m)
        pts = rel[:, None] + z[..., None, None] * r0[:, None, None, :]
        err = ((project(pts, K) - kp2d[:, None]) ** 2).sum(-1)
        return (err * w[:, None]).sum(-1)

    grid = np.geomspace(zrange[0], zrange[1], 64)
    c = cost(np.broadcast_to(grid, (len(rel), len(grid))))
    best = c.argmin(axis=1)
    lo, hi = grid[np.maximum(best - 1, 0)], grid[np.minimum(best + 1, len(grid) - 1)]
    g = (np.sqrt(5) - 1) / 2
    for _ in range(iters):
        a, b = hi - g * (hi - lo), lo + g * (hi - lo)
        ca, cb = cost(np.stack([a, b], axis=1)).T
        hi, lo = np.where(ca < cb, b, hi), np.where(ca < cb, lo, a)
    z = (lo + hi) / 2
    return rel + z[:, None, None] * r0[:, None, :]
