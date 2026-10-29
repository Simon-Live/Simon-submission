"""Rung 2 `temporal` (TICKET-021, ADR-0004): smooth each person's camera-space joint trajectories over time.

Spec: docs/specs/check-2.md ("One-person ladder", "Ladder parameters"). Per person, over each run of consecutive
frames (frame numbers one apart), every joint coordinate is replaced by a local-linear Gaussian kernel fit in
time: bandwidth SIGMA_T seconds, kernel cut at 3 SIGMA_T. Local-linear keeps a steady movement where it is (no lag)
and only removes the frame-to-frame scatter. A person seen in one frame only, as in every COCO photo, passes
through unchanged. kp2d becomes the projection of the smoothed joints.

SIGMA_T comes from leave-one-out prediction (cv_error), which needs no label: each frame's projected joints are
predicted from the other frames of its run and compared with that frame's own, in % of the person's height H;
the bandwidth that predicts held-out frames best is the one whose smoothing error is lowest when the per-frame
scatter is independent from frame to frame. Values and numbers: docs/specs/check-2.md "Ladder parameters".
This module reads no label file and imports no eval module.
"""
import numpy as np

from part2.joints import CANONICAL
from part2.lifters import project

NAME = "temporal"
USES_2D = False
# Fixed 2026-10-29 (docs/specs/check-2.md "Ladder parameters"): leave-one-out 2D error, % of H, on the kp2d-fit
# output of the seated clip's 91 unlabelled frames / the dance clip, for SIGMA_T 0.1, 0.15, 0.2, 0.3, 0.4, 0.6, 0.8 s:
# 0.587/2.308, 0.608/2.669, 0.662/2.917, 0.849/4.116, 1.085/4.919, 1.602/5.434, 2.132/6.395. The narrowest bandwidth
# predicts best on both clips: at 5 fps the movement between frames outweighs the per-frame scatter. Applied after
# kp2d-fit: seated 2D acceleration 28.71 -> 21.70 % of H/s^2, 3D 0.522 -> 0.369 m/s^2, agreement 4.75 -> 4.75 %.
PARAMS = {"SIGMA_T": 0.1}
CUT = 3.0
NOSE, LA, RA = (CANONICAL.index(n) for n in ("nose", "left_ankle", "right_ankle"))


def apply(doc: dict, ctx=None, params: dict | None = None) -> dict:
    """A new body3d document with every person's joints smoothed over time (see the module docstring)."""
    sigma = {**PARAMS, **(params or {})}["SIGMA_T"]
    K = np.asarray(doc["K"], float)
    new = {}
    for pid, (where, t, X) in person_series(doc).items():
        for run in runs([doc["frames"][i]["frame"] for i, _ in where]):
            if len(run) < 2:
                continue
            Y = smooth(t[run], X[run], sigma)
            new.update({where[r]: y for r, y in zip(run, Y)})
    frames = []
    for i, f in enumerate(doc["frames"]):
        people = [with_joints(p, new[(i, k)], K) if (i, k) in new else p for k, p in enumerate(f["people"])]
        frames.append({**f, "people": people})
    return {**doc, "frames": frames}


def with_joints(person: dict, X: np.ndarray, K) -> dict:
    X = np.round(X, 4)
    uv = project(X, K)
    return {**person, "kp3d_cam": {j: x.tolist() for j, x in zip(CANONICAL, X)},
            "kp2d": {j: x.tolist() for j, x in zip(CANONICAL, np.round(uv, 2))}, "reproj_self_px": 0.0}


def person_series(doc: dict) -> dict:
    """{id: ([(frame index, person index)], t_s (n,), joints (n, 17, 3))} in document order."""
    out: dict = {}
    for i, f in enumerate(doc["frames"]):
        for k, p in enumerate(f["people"]):
            where, t, xs = out.setdefault(p["id"], ([], [], []))
            where.append((i, k))
            t.append(f["t_ms"] / 1000.0)
            xs.append([p["kp3d_cam"][j] for j in CANONICAL])
    return {pid: (w, np.array(t), np.array(xs, float)) for pid, (w, t, xs) in out.items()}


def runs(frame_numbers) -> list[np.ndarray]:
    """Index arrays of the runs of consecutive frame numbers."""
    fr = np.asarray(frame_numbers)
    if fr.size == 0:
        return []
    breaks = np.flatnonzero(np.diff(fr) != 1) + 1
    return np.split(np.arange(fr.size), breaks)


def weights(t: np.ndarray, sigma: float, leave_out: bool = False) -> np.ndarray:
    """(n, n) local-linear equivalent kernel: row i gives the weights that estimate frame i from the run."""
    d = t[None, :] - t[:, None]
    w = np.exp(-0.5 * (d / sigma) ** 2) * (np.abs(d) <= CUT * sigma)
    if leave_out:
        np.fill_diagonal(w, 0.0)
    s0, s1, s2 = w.sum(1), (w * d).sum(1), (w * d * d).sum(1)
    det = s0 * s2 - s1 * s1
    ok = det > 1e-12 * np.maximum(s0 * s2, 1e-30)
    lin = w * (s2[:, None] - d * s1[:, None]) / np.where(ok, det, 1.0)[:, None]
    const = w / np.maximum(s0, 1e-30)[:, None]  # too few neighbours for a line: their weighted mean
    return np.where(ok[:, None], lin, const)


def smooth(t, X, sigma: float, leave_out: bool = False) -> np.ndarray:
    """(n, ...) values smoothed along the first axis; rows with no neighbour keep their own value."""
    t, X = np.asarray(t, float), np.asarray(X, float)
    L = weights(t, sigma, leave_out)
    Y = np.einsum("ij,j...->i...", L, X)
    lonely = L.sum(1) < 1e-9
    Y[lonely] = X[lonely]
    return Y


def cv_error(doc: dict, sigma: float, frames=None) -> float | None:
    """Mean leave-one-out 2D prediction error (% of H) over the frames in `frames` (None: all) whose run has
    another frame; H is the person's largest projected nose to ankle-midpoint distance."""
    K = np.asarray(doc["K"], float)
    keep = None if frames is None else set(frames)
    errs = []
    for where, t, X in person_series(doc).values():
        uv = project(X, K)
        H = max(float(np.max(np.linalg.norm(uv[:, NOSE] - (uv[:, LA] + uv[:, RA]) / 2, axis=-1))), 1.0)
        fr = [doc["frames"][i]["frame"] for i, _ in where]
        for run in runs(fr):
            if len(run) < 2:
                continue
            L = weights(t[run], sigma, leave_out=True)
            pred = project(np.einsum("ij,j...->i...", L, X[run]), K)
            for r, p, has in zip(run, pred, L.sum(1) > 1e-9):
                if has and (keep is None or fr[r] in keep):
                    errs.append(100 * float(np.linalg.norm(p - uv[r], axis=-1).mean()) / H)
    return round(float(np.mean(errs)), 4) if errs else None
