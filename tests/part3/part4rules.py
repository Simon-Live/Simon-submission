"""Test support: Part 4's documented input rules and an independent forward kinematics (not a test module).

Written from Part 4's README and the rules its check applies, with plain tuples and the textbook
Hamilton product, so the tests can compare `part3.rig` against a second implementation instead of
against itself.
"""

import math

CANONICAL = ("nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder",
             "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip",
             "left_knee", "right_knee", "left_ankle", "right_ankle")
PARENT = {
    "left_hip": "pelvis", "left_knee": "left_hip", "left_ankle": "left_knee",
    "right_hip": "pelvis", "right_knee": "right_hip", "right_ankle": "right_knee",
    "neck": "pelvis", "left_shoulder": "neck", "left_elbow": "left_shoulder", "left_wrist": "left_elbow",
    "right_shoulder": "neck", "right_elbow": "right_shoulder", "right_wrist": "right_elbow",
    "nose": "neck", "left_eye": "nose", "left_ear": "left_eye", "right_eye": "nose", "right_ear": "right_eye",
}
FK_ORDER = tuple(PARENT)  # parents before children, Part 4's order
ROTATED = ("pelvis",) + FK_ORDER
MAX_KEY_ERROR_M = 0.001
MAX_T_ERROR_S = 1e-6
MAX_STEP_DEG = 180.0  # Part 4 README: no more than this between two neighbouring keys in rotation-vector space


def q_mul(a, b):
    """Hamilton product of (x, y, z, w) quaternions: applies b, then a."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def q_unit(q):
    n = math.sqrt(sum(c * c for c in q))
    return tuple(c / n for c in q)


def q_rotate(q, v):
    """q v q^-1 for a unit quaternion, through two Hamilton products."""
    x, y, z, w = q_unit(q)
    rotated = q_mul(q_mul((x, y, z, w), (v[0], v[1], v[2], 0.0)), (-x, -y, -z, w))
    return rotated[:3]


def forward_kinematics(local_rotations, rest_offsets):
    """{joint: (x, y, z)} of the 17 canonical joints from the hip midpoint, Part 4's convention."""
    rot, pos = {"pelvis": q_unit(local_rotations["pelvis"])}, {"pelvis": (0.0, 0.0, 0.0)}
    for joint in FK_ORDER:
        parent = rest_offsets[joint]["parent"]
        turned = q_rotate(rot[parent], rest_offsets[joint]["offset"])
        pos[joint] = tuple(p + t for p, t in zip(pos[parent], turned))
        rot[joint] = q_unit(q_mul(rot[parent], q_unit(local_rotations[joint])))
    mid = tuple((a + b) / 2 for a, b in zip(pos["left_hip"], pos["right_hip"]))
    return {name: tuple(p - m for p, m in zip(pos[name], mid)) for name in CANONICAL}


def _rotation_vector(q):
    """Axis times angle (radians) of a unit quaternion (x, y, z, w) taken with w >= 0: angle 0 to 180 degrees."""
    x, y, z, w = q if q[3] >= 0 else tuple(-c for c in q)
    sine = math.sqrt(x * x + y * y + z * z)
    if sine < 1e-12:
        return (0.0, 0.0, 0.0)
    angle = 2.0 * math.atan2(sine, w)
    return (x / sine * angle, y / sine * angle, z / sine * angle)


def long_way_steps(keys):
    """[(joint, from index, to index, degrees)] for every step over 180 degrees between neighbouring keys.

    Written from Part 4's README (its own code, not `part3.rig.long_way`): each key's quaternion is flipped
    into the hemisphere of the previous key's (the first against identity), turned into a rotation vector,
    and the distance between neighbouring rotation vectors is the step.
    """
    found = []
    for joint in ROTATED:
        before, vector, at = (0.0, 0.0, 0.0, 1.0), None, None
        for key in keys:
            q = q_unit(key["local_rotations"][joint])
            if sum(a * b for a, b in zip(q, before)) < 0:
                q = tuple(-c for c in q)
            now = _rotation_vector(q)
            if vector is not None:
                degrees = math.degrees(math.dist(now, vector))
                if degrees > MAX_STEP_DEG:
                    found.append((joint, at, key["index"], degrees))
            before, vector, at = q, now, key["index"]
    return found


def _joint_xyz(value):
    return (value["x"], value["y"], value["z"]) if isinstance(value, dict) else tuple(value)


def key_fk_error(key, rest_offsets):
    """Largest distance in metres between a key's `joints` and the FK of its `local_rotations`."""
    posed = forward_kinematics(key["local_rotations"], rest_offsets)
    return max(math.dist(posed[name], _joint_xyz(key["joints"][name])) for name in CANONICAL)


def violations(skeleton, companion=None):
    """Part 4's input rules applied to a part4 `skeleton` dict (and its keyframes `companion`); [] when met."""
    found = []
    timeline = skeleton.get("timeline", {})
    fps, count, duration = timeline.get("fps"), timeline.get("frame_count"), timeline.get("duration_s")
    if fps != 30:
        found.append(f"fps is {fps}, expected 30")
    if count != round(duration * 30) + 1:
        found.append(f"frame_count {count} does not match duration_s {duration}")
    found += _rig_violations(skeleton)
    keys = skeleton.get("keyframes") or []
    if not keys:
        found.append("no keyframes")
    found += _key_violations(keys, count, skeleton.get("rest_offsets_m", {}))
    if all(joint in key["local_rotations"] for key in keys for joint in ROTATED):  # else already reported as missing
        found += [f"{joint} takes the long way between keys {a} and {b} ({degrees:.1f} degrees)"
                  for joint, a, b, degrees in long_way_steps(keys)]
    if companion is not None:
        found += _companion_violations(companion, keys, timeline)
    return found


def _rig_violations(skeleton):
    found = []
    offsets = skeleton.get("rest_offsets_m", {})
    for joint in FK_ORDER:
        entry = offsets.get(joint)
        if not isinstance(entry, dict) or entry.get("parent") != PARENT[joint]:
            found.append(f"rest_offsets_m.{joint}: missing or wrong parent")
        elif math.dist(entry["offset"], (0, 0, 0)) < 1e-8:
            found.append(f"rest_offsets_m.{joint}: zero length")
    if "joints" in skeleton and list(skeleton["joints"]) != list(CANONICAL):
        found.append("joints is not the canonical 17 in order")
    return found


def _key_violations(keys, count, offsets):
    found, previous = [], -1
    for key in keys:
        index = key["index"]
        if index <= previous:
            found.append(f"key {index}: not strictly increasing")
        if not 0 <= index <= (count or 0) - 1:
            found.append(f"key {index}: outside the clip")
        if abs(key["t"] - index / 30) > MAX_T_ERROR_S:
            found.append(f"key {index}: t {key['t']} is not index / 30")
        missing = [j for j in ROTATED if j not in key["local_rotations"]]
        if missing:
            found.append(f"key {index}: missing rotation for {missing[0]}")
        elif not offsets:
            found.append(f"key {index}: no rest offsets")
        elif key_fk_error(key, offsets) > MAX_KEY_ERROR_M:
            found.append(f"key {index}: FK misses the joints by over 1 mm")
        previous = index
    return found


def _companion_violations(companion, keys, timeline):
    found = []
    if companion.get("format") != "simon.keyframes.v1":
        found.append("keyframes format is not simon.keyframes.v1")
    if companion.get("fps") != 30 or companion.get("frame_count") != timeline.get("frame_count"):
        found.append("keyframes fps or frame_count differs from the skeleton")
    if [k["index"] for k in companion.get("keyframes", [])] != [k["index"] for k in keys]:
        found.append("keyframes index list differs from skeleton keyframes")
    return found
