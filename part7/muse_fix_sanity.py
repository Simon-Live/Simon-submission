"""Is the measured picture one whole person, and did the joint move the way the cue asks (docs/specs/muse-fix.md, R14).

Pure functions over the joints `pose3d.json` already returns for the picture: no new call, nothing paid. The angle gate alone
said yes to a picture of two half bodies, because one joint angle can land on target by chance. So a picture is shown only when
`verdict` finds no problem: enough joints seen, body proportions a person can have, both sides of the body alike, every joint near
the same torso, and the corrected joint moved from the original frame's angle in the cue's direction.
"""

from __future__ import annotations

from typing import Any

from part7 import muse_fix_geom as geom, skeleton2d

MIN_SEEN = 13  # of the 17 joints (a hidden ankle or ear is allowed; half a body is not)
MIN_MOVE_DEG = 3.0  # the joint must have moved at least this far toward the cue from the original frame
LIMB = {"upper arm": ("shoulder", "elbow"), "forearm": ("elbow", "wrist"), "thigh": ("hip", "knee"), "shin": ("knee", "ankle")}
LIMB_RATIO = (0.3, 1.8)  # each limb segment against the torso length
SIDE_RATIO = 1.6  # the left and right of one limb differ by less than this factor
SHOULDER_RATIO = (0.4, 2.0)
HEAD_RATIO = 1.6  # nose to mid-shoulder against the torso length
REACH_RATIO = 4.5  # no joint further from mid-hip than this many torsos
TORSO_MIN_M, TORSO_MAX_M = 0.15, 1.2
NOT_A_PERSON = "the picture does not show one whole person"
WRONG_WAY = "the joint did not move the way the cue asks"


def _point(joints: dict[str, Any], name: str) -> geom.Vec | None:
    j = joints.get(name)
    if not isinstance(j, dict) or skeleton2d.is_unseen(j.get("conf")):
        return None
    return geom._xyz(j)


def _dist(a: geom.Vec, b: geom.Vec) -> float:
    return geom._norm(geom._sub(a, b))


def _mid(a: geom.Vec, b: geom.Vec) -> geom.Vec:
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)


def whole_person(joints: Any) -> str | None:
    """None when `joints` can be one standing or crouching person, else the reason in plain words."""
    if not isinstance(joints, dict):
        return NOT_A_PERSON
    seen = {n: p for n in joints if (p := _point(joints, n)) is not None}
    if len(seen) < MIN_SEEN:
        return NOT_A_PERSON
    torso = [seen.get(n) for n in ("left_shoulder", "right_shoulder", "left_hip", "right_hip")]
    if any(p is None for p in torso):
        return NOT_A_PERSON
    ls, rs, lh, rh = torso  # type: ignore[misc]
    top, bottom = _mid(ls, rs), _mid(lh, rh)
    length = _dist(top, bottom)
    if not TORSO_MIN_M <= length <= TORSO_MAX_M:
        return NOT_A_PERSON
    if not SHOULDER_RATIO[0] * length <= _dist(ls, rs) <= SHOULDER_RATIO[1] * length:
        return NOT_A_PERSON
    nose = seen.get("nose")
    if nose is not None and _dist(nose, top) > HEAD_RATIO * length:
        return NOT_A_PERSON
    if any(_dist(p, bottom) > REACH_RATIO * length for p in seen.values()):
        return NOT_A_PERSON
    return _limbs_alike(seen, length)


def _limbs_alike(seen: dict[str, geom.Vec], torso: float) -> str | None:
    for a, b in LIMB.values():
        sizes = [_dist(seen[f"{s}_{a}"], seen[f"{s}_{b}"]) for s in ("left", "right") if f"{s}_{a}" in seen and f"{s}_{b}" in seen]
        if any(not LIMB_RATIO[0] * torso <= v <= LIMB_RATIO[1] * torso for v in sizes):
            return NOT_A_PERSON
        if len(sizes) == 2 and max(sizes) > SIDE_RATIO * min(sizes):
            return NOT_A_PERSON
    return None


def moved_toward_cue(original_deg: float | None, measured_deg: float, target_deg: float, want: int | None) -> bool:
    """True when the joint went from the original frame's angle toward the target by `MIN_MOVE_DEG` or more.

    `want` is the cue's direction (+1 opens the joint, -1 closes it, `geom.wanted_move`); with none, the target's side decides.
    With no original angle there is nothing to compare, and the picture does not pass."""
    if original_deg is None:
        return False
    way = want if want in (1, -1) else (1 if target_deg > original_deg else -1)
    return (measured_deg - original_deg) * way >= MIN_MOVE_DEG


def verdict(measured: dict[str, Any] | None, joint: str, *, original: dict[str, Any] | None, target_deg: float,
            want: int | None) -> str | None:
    """None when the picture passes both checks, else why it does not. `original` is the pose3d joints of the student's own frame."""
    problem = whole_person(measured)
    if problem:
        return problem
    angle = geom.joint_angle(measured or {}, joint)
    before = geom.joint_angle(original, joint) if isinstance(original, dict) else None
    if angle is None or not moved_toward_cue(before, angle, target_deg, want):
        return WRONG_WAY
    return None

