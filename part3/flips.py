"""Step 4: left/right label-flip repair (spec step 4).

Works in the input coordinates (Part 2's per-frame pelvis frame, camera up = +y) on the frames that
hold the chosen person, after mirroring. For each group, a two-state Viterbi pass (0 = labels kept,
1 = labels swapped) picks the cheapest state sequence. Costs are pairwise: the move from the previous
repaired frame depends on both frames' states.

- state cost (unary) = BONE_WEIGHT x mean |L / clip median - 1| over the group's bones; for `body`
  also relu(-signature), the 180-degree signature (face ahead of the ears, knees ahead of the leg line);
- transition cost = confidence-weighted mean distance (metres) of the group's joints to the previous
  frame, plus the group's switching penalty when the state changes;
- switching penalty = PENALTY_FACTOR x the clip median of the mean left-right distance of the group.
"""

import numpy as np

from part3.bones import measure
from part3.joints import BONE_NAMES, GROUP_ORDER, GROUPS, INDEX, N_JOINTS, swap_index

# Final constants (internal tuning, spec step 4). BONE_WEIGHT is 0.25, not the starting 1.0: on the
# real clip smoothed and re-noised at the measured jitter, 1.0 invented swap runs in about 1 clip in
# 60 (the symmetric face bones are mostly noise), while 0.25 made no error in 300 clips at twice that
# noise and still repaired every injected swap (1 to 30 frames; the motion jump decides).
PENALTY_FACTOR = 0.25
BONE_WEIGHT = 0.25
LOW_CONF_WEIGHT = 0.3
TIE_EPS = 1e-12

_GROUP_BONES = {
    "legs": ("left_thigh", "right_thigh", "left_shank", "right_shank"),
    "arms": ("left_upper_arm", "right_upper_arm", "left_forearm", "right_forearm"),
    "face": ("left_eye_link", "right_eye_link", "left_ear_link", "right_ear_link"),
    "body": BONE_NAMES,
}
_BONE_IDX = {g: [BONE_NAMES.index(b) for b in names] for g, names in _GROUP_BONES.items()}
_PERM = {g: swap_index(GROUPS[g]) for g in GROUP_ORDER}
_JOINTS = {g: ([INDEX[n] for pair in GROUPS[g] for n in pair] if g != "body" else list(range(N_JOINTS)))
           for g in GROUP_ORDER}
_ROT180_Y = np.array([-1.0, 1.0, -1.0])
_LEGS = (("left_hip", "left_knee", "left_ankle"), ("right_hip", "right_knee", "right_ankle"))


def _swapped(J, conf, group):
    """The group's candidate under state 1: pairs swapped (conf travels along); body also turns 180 deg."""
    perm = _PERM[group]
    P = J[:, perm]
    if group == "body":
        P = P * _ROT180_Y
    return P, conf[:, perm]


def _signature(P):
    """Metres: nose ahead of the ear midpoint plus mean knee advance over the hip-ankle line (z)."""
    z = P[..., 2]
    face = z[:, INDEX["nose"]] - 0.5 * (z[:, INDEX["left_ear"]] + z[:, INDEX["right_ear"]])
    knees = np.mean([z[:, INDEX[k]] - 0.5 * (z[:, INDEX[h]] + z[:, INDEX[a]]) for h, k, a in _LEGS], axis=0)
    return face + knees


def _unary(J, swapped, group):
    """(n, 2) state costs: bone-length deviation from the clip medians (+ 180-degree signature, body)."""
    idx = _BONE_IDX[group]
    kept, flipped = measure(J)[:, idx], measure(swapped)[:, idx]
    median = np.median(kept, axis=0)
    median = np.where(median > 0, median, 1.0)
    cost = BONE_WEIGHT * np.stack([np.abs(kept / median - 1).mean(axis=1),
                                   np.abs(flipped / median - 1).mean(axis=1)], axis=1)
    if group == "body":
        cost += np.stack([np.maximum(-_signature(J), 0.0), np.maximum(-_signature(swapped), 0.0)], axis=1)
    return cost


def _steps(cands, confs, joints):
    """(n-1, 2, 2): weighted mean joint distance from state a at t-1 to state b at t."""
    n = len(cands[0])
    out = np.zeros((max(n - 1, 0), 2, 2))
    for a in (0, 1):
        for b in (0, 1):
            dist = np.linalg.norm(cands[b][1:, joints] - cands[a][:-1, joints], axis=-1)
            low = np.minimum(confs[b][1:, joints], confs[a][:-1, joints]) < 1.0
            weight = np.where(low, LOW_CONF_WEIGHT, 1.0)
            out[:, a, b] = (weight * dist).sum(axis=-1) / weight.sum(axis=-1)
    return out


def _penalty(J, group):
    """Switching penalty: PENALTY_FACTOR x clip median of the mean left-right distance of the group."""
    gaps = [np.linalg.norm(J[:, INDEX[left]] - J[:, INDEX[right]], axis=-1) for left, right in GROUPS[group]]
    return PENALTY_FACTOR * float(np.median(np.mean(gaps, axis=0)))


def _viterbi(unary, steps, penalty):
    """Cheapest state sequence (bool per frame). Starts from a virtual frame in state 0; ties keep 0."""
    n = len(unary)
    cost = [unary[0, 0], unary[0, 1] + penalty]
    back = np.zeros((n, 2), dtype=int)
    for t in range(1, n):
        fresh = [0.0, 0.0]
        for b in (0, 1):
            from_kept = cost[0] + steps[t - 1, 0, b] + (penalty if b else 0.0)
            from_swapped = cost[1] + steps[t - 1, 1, b] + (0.0 if b else penalty)
            back[t, b] = 1 if from_swapped < from_kept - TIE_EPS else 0
            fresh[b] = unary[t, b] + (from_swapped if back[t, b] else from_kept)
        cost = fresh
    state = 1 if cost[1] < cost[0] - TIE_EPS else 0
    states = np.zeros(n, dtype=bool)
    for t in range(n - 1, -1, -1):
        states[t] = bool(state)
        state = back[t, state]
    return states


def _decide(J, conf, group):
    """Boolean (n,): frames in which `group` is swapped relative to the clip's start."""
    flipped, flipped_conf = _swapped(J, conf, group)
    steps = _steps((J, flipped), (conf, flipped_conf), _JOINTS[group])
    return _viterbi(_unary(J, flipped, group), steps, _penalty(J, group))


def _undo(J, conf, group, swapped):
    flipped, flipped_conf = _swapped(J, conf, group)
    return np.where(swapped[:, None, None], flipped, J), np.where(swapped[:, None], flipped_conf, conf)


def repair(J, conf):
    """Undo label swaps. J is (n, 17, 3), conf is (n, 17), both for the frames that hold the person.

    Returns (J_repaired, conf_repaired, flips) where flips[i] lists the groups repaired in frame i
    (subset of body, legs, arms, face, in that order). `body` is decided first; legs, arms and face are
    decided independently on the body-repaired frames.
    """
    J = np.array(J, dtype=float, copy=True)
    conf = np.array(conf, dtype=float, copy=True)
    decided = {}
    if len(J):
        decided["body"] = _decide(J, conf, "body")
        J, conf = _undo(J, conf, "body", decided["body"])
        decided.update({g: _decide(J, conf, g) for g in GROUP_ORDER[1:]})
        for g in GROUP_ORDER[1:]:
            J, conf = _undo(J, conf, g, decided[g])
    flips = [[g for g in GROUP_ORDER if decided[g][i]] for i in range(len(J))]
    return J, conf, flips
