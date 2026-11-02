"""Put the fitted skeleton in the middle of the mesh, in depth. numpy only, no GPU.

    joints, info = centre_in_depth(vertices, joints, parents, mapping)

SAM 3D Body fits a human body to a front picture of the mesh; the body's depth is a guess, and the generated or uploaded
mesh may be thinner or thicker than a person, so the fitted joints can sit at the back of the surface or behind it. The
skin weights do not mind, but a bone turns about its joint: a knee 10 cm behind the leg swings the shin 10 cm off. Each
canonical joint therefore moves along Z to the middle of the mesh cylinder round it (the mesh points within RADIUS_M of
the joint in X and Y), clipped to MAX_SHIFT_M and left alone where too few points are near. The other joints follow the
nearest canonical joint above them in the tree. The bind pose does not change (the weights stay, the inverse bind
matrices are translations by the new positions). Spec: docs/specs/autorig.md (AC-22).
"""
import numpy as np

RADIUS_M = 0.06
MIN_POINTS = 24
MAX_SHIFT_M = 0.25
PERCENTILES = (5, 95)        # the cylinder's depth, trimmed so a stray tip or a cape does not set the middle


def depth_offsets(vertices: np.ndarray, joints: np.ndarray, mapping: dict) -> dict:
    """{canonical bone: the shift along Z that centres it in the mesh} for the bones with enough mesh points near."""
    out = {}
    for name, j in mapping.items():
        near = np.linalg.norm(vertices[:, :2] - joints[j, :2], axis=1) <= RADIUS_M
        if near.sum() >= MIN_POINTS:
            lo, hi = np.percentile(vertices[near, 2], PERCENTILES)
            out[name] = float(np.clip((lo + hi) / 2 - joints[j, 2], -MAX_SHIFT_M, MAX_SHIFT_M))
    return out


def centre_in_depth(vertices, joints, parents, mapping: dict):
    """(joints moved along Z, info {"median_shift_m", "max_shift_m", "bones"}). A canonical bone with no shift of its own
    takes the median of the others; any other joint takes its nearest canonical ancestor's shift."""
    vertices, joints, parents = np.asarray(vertices, dtype=float), np.asarray(joints, dtype=float), np.asarray(parents)
    own = depth_offsets(vertices, joints, mapping)
    fallback = float(np.median(list(own.values()))) if own else 0.0
    shift = np.full(len(joints), np.nan)
    for name, j in mapping.items():
        shift[j] = own.get(name, fallback)
    for j in range(len(joints)):
        k = j
        while np.isnan(shift[k]) and parents[k] >= 0:
            k = int(parents[k])
        shift[j] = 0.0 if np.isnan(shift[k]) else shift[k]
    moved = joints.copy()
    moved[:, 2] += shift
    canon = np.array([shift[j] for j in mapping.values()])
    return moved, {"median_shift_m": round(float(np.median(canon)), 4), "max_shift_m": round(float(np.abs(canon).max()), 4),
                   "bones": len(own)}
