"""Rung 3 `focal` (TICKET-021, ADR-0004): fit each clip's focal length instead of taking MoGe-2's estimate.

Spec: docs/specs/check-2.md ("One-person ladder", "Ladder parameters"). SAM 3D Body runs again on the clip once per
candidate focal f = s * f_MoGe2 (s in SCALES; same principal point; s = 1 is the input document), and the candidate
whose own projection agrees best with RTMPose-x replaces the input: the lowest mean over person-frames of the
score^GAMMA-weighted joint distance to RTMPose-x, each joint capped at CAP H (a swapped limb counts as CAP, not
more), in % of the person's height H. A photo is its own clip. The camera written to camera.json is the chosen one.

Needs the gpu backend: ctx.backend.load() gives the SAM 3D Body estimator, which part2.body3d.estimate drives with
the candidate K in place of MoGe-2's (FixedK), under ctx.lock (the host GPU lock). Values were fixed from
label-free objectives before the rung's gold scoring (docs/specs/check-2.md "Ladder parameters").
This module reads no label file and imports no eval module.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from part2.joints import CANONICAL
from part2.lifters import project

NAME = "focal"
USES_2D = True
# Fixed 2026-10-29 (docs/specs/check-2.md "Ladder parameters"): the seated clip's capped agreement on its unlabelled
# frames for s 0.7 ... 2.0 is 4.864, 4.710, 4.626, 4.556, 4.549, 4.557, 4.562 %: its optimum lies inside the range.
# CAP and GAMMA are rung 1's C and GAMMA.
PARAMS = {"SCALES": (0.7, 0.85, 1.0, 1.2, 1.4, 1.7, 2.0), "CAP": 0.2, "GAMMA": 2.0}
NOSE, LA, RA = (CANONICAL.index(n) for n in ("nose", "left_ankle", "right_ankle"))


class NeedsGpu(RuntimeError):
    """The focal rung re-runs SAM 3D Body; str() says why it cannot here."""


def apply(doc: dict, ctx, params: dict | None = None) -> dict:
    """The candidate document (input or a re-run at another focal) that agrees best with RTMPose-x."""
    p = {**PARAMS, **(params or {})}
    if getattr(ctx, "backend", None) is None or not hasattr(ctx.backend, "load"):
        raise NeedsGpu("refine rung focal re-runs SAM 3D Body and needs the gpu backend")
    kp = ctx.keypoints(doc)
    best, best_score, scores = doc, agreement(doc, kp, p["GAMMA"], p["CAP"]), {}
    scores[1.0] = best_score
    for s in p["SCALES"]:
        if s == 1.0:
            continue
        cand = rerun(doc, ctx, scaled_K(doc["K"], s), f"body3d-focal-{s:g}.json")
        scores[float(s)] = agreement(cand, kp, p["GAMMA"], p["CAP"])
        if scores[float(s)] < best_score:
            best, best_score = cand, scores[float(s)]
    chosen = next(s for s, v in scores.items() if v == best_score)
    return {**best, "focal_fit": {"scale": chosen, "agreement_pct": {f"{s:g}": round(v, 4) for s, v in scores.items()}}}


def scaled_K(K, s: float) -> list:
    K = np.array(K, float)
    K[0, 0] *= s
    K[1, 1] *= s
    return K.tolist()


class FixedK:
    """The SAM 3D Body estimator with its field-of-view estimator replaced by one fixed K."""

    def __init__(self, estimator, K):
        self._est = estimator
        self.fov_estimator = SimpleNamespace(get_cam_intrinsics=lambda rgb: np.array(K, float))

    def __getattr__(self, name):
        return getattr(self._est, name)


def rerun(doc: dict, ctx, K, name: str) -> dict:
    """SAM 3D Body on ctx.frames_dir with intrinsics K (one-person mode), written to ctx.work_dir/name."""
    from part2 import body3d

    out = Path(ctx.work_dir or ctx.frames_dir) / name
    est = FixedK(ctx.backend.load(), K)
    with ctx.lock():
        new = body3d.estimate(ctx.frames_dir, out, estimator=est)
    new = {**{k: v for k, v in doc.items() if k not in new}, **new}
    out.write_text(json.dumps(new))
    return new


def agreement(doc: dict, kp: dict, gamma: float, cap: float) -> float:
    """Mean over person-frames with RTMPose-x keypoints of the score^gamma-weighted, capped joint distance, % of H."""
    K = np.asarray(doc["K"], float)
    uv_by: dict = {}
    for f in doc["frames"]:
        for p in f["people"]:
            X = np.array([p["kp3d_cam"][j] for j in CANONICAL], float)
            uv_by.setdefault(p["id"], []).append((f["frame"], project(X, K)))
    vals = []
    for pid, rows in uv_by.items():
        H = max(max(float(np.linalg.norm(uv[NOSE] - (uv[LA] + uv[RA]) / 2)) for _, uv in rows), 1.0)
        for fr, uv in rows:
            got = kp.get((fr, pid))
            if got is None:
                continue
            u, s = got
            w = np.clip(np.asarray(s, float), 0, 1) ** gamma
            d = np.minimum(np.linalg.norm(uv - u, axis=1), cap * H)
            vals.append(100 * float(np.sum(w * d) / max(np.sum(w), 1e-9)) / H)
    return float(np.mean(vals)) if vals else float("inf")
