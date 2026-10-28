"""Test support for the contract tests: documents of every kind built by hand to the spec shapes.

Not a test module. Native skeletons come from the pipeline (`part3.cli.process` on the Part 2 fixture);
part4 and part5 views, keyframes, profiles, people and labels are built here from the spec text, so the
tests do not depend on the views other lanes write. `forward` is a reference implementation of Part 4's
rotation convention (spec "Part 4 rig and rotations"), used to give key poses exact joints and to check
the rig doctor uses against it.
"""

import copy
import json
import math

from clipkit import real_skeleton
from conftest import REAL_CLIP
from part3 import standard
from part3.joints import JOINTS
from part3.rig import HIERARCHY as PARENTS

RIG_JOINTS = ("pelvis", "neck") + JOINTS
ORDER = ["pelvis"] + list(PARENTS)  # every parent before its children


def pose3d_head(frames=6):
    """The first `frames` frames of the Part 2 fixture (a canonical pose3d document)."""
    doc = json.loads(REAL_CLIP.read_text())
    doc["frames"] = doc["frames"][:frames]
    return doc


def two_person_pose3d():
    """Part 2 fixture head with a second person (id 1) in the first four frames."""
    doc = pose3d_head(6)
    for frame in doc["frames"][:4]:
        other = copy.deepcopy(frame["people"][0])
        other["id"] = 1
        for joint in other["joints"].values():
            joint["x"] = round(joint["x"] + 0.5, 4)
        frame["people"].append(other)
    return doc


def _array_joints(joints, conf=True):
    return {n: [j["x"], j["y"], j["z"]] + ([j["conf"]] if conf else []) for n, j in joints.items()}


def as_arrays(doc):
    out = copy.deepcopy(doc)
    for frame in out["frames"]:
        for person in frame["people"]:
            person["joints"] = _array_joints(person["joints"])
    return out


def as_list17(doc):
    out = copy.deepcopy(doc)
    for frame in out["frames"]:
        for person in frame["people"]:
            person["joints"] = [_array_joints({n: person["joints"][n]})[n] for n in JOINTS]
    return out


def as_flat(doc):
    out = copy.deepcopy(doc)
    for frame in out["frames"]:
        frame["joints"] = frame.pop("people")[0]["joints"]
    return out


def with_extra_joint(doc):
    out = copy.deepcopy(doc)
    for frame in out["frames"]:
        for person in frame["people"]:
            person["joints"]["head_top"] = {"x": 0.0, "y": 0.7, "z": 0.0, "conf": 1.0}
    return out


def without(doc, key):
    out = copy.deepcopy(doc)
    for frame in out["frames"]:
        frame.pop(key)
    return out


# --- Part 4 rig reference ----------------------------------------------------------------------

def _unit_scaled(vector, length):
    norm = math.sqrt(sum(c * c for c in vector))
    return [c / norm * length for c in vector]


def rest_offsets(lengths=None):
    """{joint: {"parent", "offset"}} for the 18 non-root joints of Part 4's rig."""
    lengths = lengths or standard.bone_lengths()
    head = json.loads(standard.STANDARD_BODY_PATH.read_text())["neutral_head_m"]
    sub = lambda a, b: [x - y for x, y in zip(head[a], head[b])]  # noqa: E731
    L = lengths
    offsets = {
        "left_hip": [L["left_pelvis"], 0, 0], "right_hip": [-L["right_pelvis"], 0, 0],
        "left_knee": [0, -L["left_thigh"], 0], "right_knee": [0, -L["right_thigh"], 0],
        "left_ankle": [0, -L["left_shank"], 0], "right_ankle": [0, -L["right_shank"], 0],
        "neck": [0, L["spine"], 0],
        "left_shoulder": [L["left_clavicle"], 0, 0], "right_shoulder": [-L["right_clavicle"], 0, 0],
        "left_elbow": [L["left_upper_arm"], 0, 0], "right_elbow": [-L["right_upper_arm"], 0, 0],  # T-pose arms
        "left_wrist": [L["left_forearm"], 0, 0], "right_wrist": [-L["right_forearm"], 0, 0],
        "nose": _unit_scaled(sub("nose", "neck"), L["head"]),
        "left_eye": _unit_scaled(sub("left_eye", "nose"), L["left_eye_link"]),
        "right_eye": _unit_scaled(sub("right_eye", "nose"), L["right_eye_link"]),
        "left_ear": _unit_scaled(sub("left_ear", "left_eye"), L["left_ear_link"]),
        "right_ear": _unit_scaled(sub("right_ear", "right_eye"), L["right_ear_link"]),
    }
    return {j: {"parent": PARENTS[j], "offset": [round(c, 6) for c in offsets[j]]} for j in PARENTS}


def axis_angle(axis, degrees):
    """Quaternion (x, y, z, w) for a rotation of `degrees` about `axis`."""
    half = math.radians(degrees) / 2
    n = math.sqrt(sum(c * c for c in axis))
    s = math.sin(half) / n
    return [round(axis[0] * s, 6), round(axis[1] * s, 6), round(axis[2] * s, 6), round(math.cos(half), 6)]


def _qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz]


def _rotate(q, v):
    x, y, z, w = q
    t = [2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])]
    return [v[0] + w * t[0] + (y * t[2] - z * t[1]), v[1] + w * t[1] + (z * t[0] - x * t[2]),
            v[2] + w * t[2] + (x * t[1] - y * t[0])]


def forward(rotations, rest):
    """{joint: [x, y, z]} for the 17 canonical joints: global[j] = global[parent] * local[j];
    position[j] = position[parent] + rotate(global[parent], offset[j]); pelvis at the origin."""
    glob, pos = {"pelvis": list(rotations["pelvis"])}, {"pelvis": [0.0, 0.0, 0.0]}
    for joint in ORDER[1:]:
        parent = rest[joint]["parent"]
        moved = _rotate(glob[parent], rest[joint]["offset"])
        pos[joint] = [p + m for p, m in zip(pos[parent], moved)]
        glob[joint] = _qmul(glob[parent], rotations[joint])
    return {name: pos[name] for name in JOINTS}


def _rotations(step):
    """Local rotations for key number `step`: a bend that grows with the step; pelvis stays upright."""
    rotations = {name: [0.0, 0.0, 0.0, 1.0] for name in RIG_JOINTS}
    rotations["left_hip"] = axis_angle([1, 0, 0], -20 * (step + 1))
    rotations["right_hip"] = axis_angle([1, 0, 0], -20 * (step + 1))
    rotations["left_knee"] = axis_angle([1, 0, 0], 30 * (step + 1))
    rotations["right_knee"] = axis_angle([1, 0, 0], 30 * (step + 1))
    rotations["left_shoulder"] = axis_angle([0, 0, 1], 10 * step)
    return rotations


def part4_view(indices=(0, 10, 20), names=("start", "down", "up")):
    """A part4-view skeleton.json built by hand to the spec: native frames plus Part 4's block."""
    doc = real_skeleton()
    rest = rest_offsets(doc["bone_lengths_m"])
    keys = []
    for step, (index, name) in enumerate(zip(indices, names)):
        rotations = _rotations(step)
        joints = {n: [round(c, 6) for c in p] for n, p in forward(rotations, rest).items()}
        keys.append({"index": index, "t": round(index / 30, 6), "name": name, "source_frame": index // 2,
                     "source_t_ms": round(index * 1000 / 30, 3), "joints": joints,
                     "conf": {n: 1.0 for n in JOINTS}, "local_rotations": rotations})
    doc.update({
        "format": "simon.skeleton.v1",
        "fps": 30,
        "coordinate_frame": coordinate_frame(),
        "root_joint": "pelvis",
        "virtual_joints": ["pelvis", "neck"],
        "rest_offsets_m": rest,
        "timeline": {"fps": 30, "duration_s": 7.0, "frame_count": 211, "t0_ms": 0.0, "source_kind": "part1",
                     "person": 0, "dropped": []},
        "rig": {"convention": "quaternion (x, y, z, w), Hamilton product, active rotation",
                "fit": {"max_m": 0.012, "mean_m": 0.004, "worst_joint": "nose", "worst_index": indices[-1]}},
        "keyframes": keys,
    })
    return doc


def with_rotation(view, key, joint, quaternion):
    """A copy of the part4 `view` whose key number `key` has `quaternion` at `joint`; the key's joints follow."""
    out = copy.deepcopy(view)
    entry = out["keyframes"][key]
    entry["local_rotations"][joint] = quaternion
    entry["joints"] = {n: [round(c, 6) for c in p]
                       for n, p in forward(entry["local_rotations"], out["rest_offsets_m"]).items()}
    return out


def keyframes_beside(view):
    """The keyframes.json Part 4 reads beside `view`: the same key indices and names."""
    keys = view.get("keyframes") or []
    return keyframes_part4(indices=[k["index"] for k in keys], names=[k["name"] for k in keys])


def part4_authored(view=None):
    """A simon.skeleton.v1 file as Part 4 authors its own (fixtures/input/exercise/skeleton.json): no native
    `frames` or `input` block, joints as {x, y, z, conf} objects, and the authoring fields `set`, `movement`."""
    view = view or part4_view()
    keys = [{"index": k["index"], "t": k["t"], "name": k["name"], "local_rotations": k["local_rotations"],
             "joints": {n: {"x": p[0], "y": p[1], "z": p[2], "conf": 1.0} for n, p in k["joints"].items()}}
            for k in view["keyframes"]]
    return {
        "format": "simon.skeleton.v1", "schema": "simon.skeleton/1", "set": "exercise", "movement": "squat",
        "units": {"length": "m", "angle": "deg", "time": "s", "rotation": "quaternion"},
        "coordinate_frame": {**coordinate_frame(), "notes": "z = x cross y. Hip midpoint is subtracted per frame."},
        "frame": {"origin": "hip_midpoint", "x": "subject_left", "y": "world_up", "z": "anterior",
                  "up_source": "authored"},
        "joints": list(JOINTS), "root_joint": "pelvis", "virtual_joints": ["pelvis", "neck"],
        "bone_lengths_m": view["bone_lengths_m"], "rest_offsets_m": view["rest_offsets_m"],
        "person": {"id": "synthetic", "rule": "authored", "frames_present": len(keys), "frames_dropped": 0},
        "mirror": {"setting": "none", "applied": False, "reason": "Synthetic fixture. There is no image to mirror."},
        "keyframes": keys,
    }


def coordinate_frame():
    return {"origin": "hip_midpoint", "x": "subject_left", "y": "world_up", "z": "anterior",
            "position_unit": "metres", "angle_unit": "degrees"}


def part5_view(skeleton=None):
    """The part5 view of a native skeleton, built to the spec: frames that hold the person only."""
    skeleton = skeleton or real_skeleton()
    present = [f for f in skeleton["frames"] if f["people"]]
    t0 = skeleton["frames"][0]["t_ms"]
    frames = [{"index": f["frame"], "t": round((f["t_ms"] - t0) / 1000, 6), "interpolated": False,
               "joints": {n: [f["people"][0]["joints"][n][a] for a in "xyz"] for n in JOINTS},
               "conf": {n: f["people"][0]["joints"][n]["conf"] for n in JOINTS}} for f in present]
    lengths = skeleton["bone_lengths_m"]
    return {
        "format": "simon.animation.v1", "producer": "part3", "view": "part5", "fps": 15.0,
        "duration_s": frames[-1]["t"], "frame_count": len(frames),
        "coordinate_frame": coordinate_frame(), "joints": list(JOINTS),
        "bones": [{"name": b["name"], "parent": b["from"], "child": b["to"], "length_m": lengths[b["name"]]}
                  for b in skeleton["bones"]],
        "person": skeleton["person"], "mirror": skeleton["mirror"],
        "source": {"schema": "simon.skeleton/1", "sha256": skeleton["input"]["sha256"]},
        "frames_skipped": len(skeleton["frames"]) - len(present),
        "frames": frames,
    }


def body_block(**extra):
    return {"profile": "simon-standard", "selected_by": "default", "stature_m": 1.7, "scale": 1.0,
            "source": "part3/standard_body.json", "symmetrized": False, **extra}


# --- other files -------------------------------------------------------------------------------

def keyframes_part1():
    return {"video": "inbox/example.mp4", "fps": 60.0, "analysis_fps": 8.0, "quality": {"verdict": "fine"},
            "people": [{"id": 0, "repetitions": [{"rep": 1, "movement": "squat", "keyframes": [
                {"name": "start", "frame": 0, "t_ms": 0}, {"name": "bottom", "frame": 210, "t_ms": 3500},
                {"name": "top", "frame": 420, "t_ms": 7000}]}]}]}


def keyframes_part4(indices=(0, 105, 210), names=("start", "bottom", "top")):
    return {"format": "simon.keyframes.v1", "producer": "part3", "fps": 30, "duration_s": 7.0,
            "frame_count": 211,
            "keyframes": [{"index": i, "t": round(i / 30, 6), "name": n} for i, n in zip(indices, names)]}


def body_profile(scale=1.0):
    lengths = {n: round(v * scale, 4) for n, v in standard.bone_lengths().items()}
    return {"schema": "simon.body_profile/1", "name": "unit-test-body", "stature_m": round(1.7 * scale, 3),
            "bone_lengths_m": lengths, "source": "built by the contract tests"}


def people_index():
    return {"schema": "simon.part3.people/1", "people": [
        {"id": 0, "dir": "person-0", "frames_present": 107, "file": "person-0/skeleton.json"},
        {"id": "a/b", "dir": "person-p1", "frames_present": 40, "file": "person-p1/skeleton.json"},
        {"id": 7, "frames_present": 0, "skipped": "the hips coincide in every frame"}]}


def follower_labels():
    fault = {"type": "feet_wide", "measure": "ankle_lateral_offset", "body_part": "legs",
             "joints": ["left_ankle", "right_ankle"], "side": "both", "direction": "more",
             "magnitude_m": 0.2, "text": "feet too wide", "measured_in_output": 0.19}
    return {"format": "simon.part3.follower_labels/1", "takes": [
        {"take_id": "squat_front_correct", "angle": "front", "camera_yaw_deg": 0, "correct": True, "faults": []},
        {"take_id": "squat_45_feet_wide", "angle": "45", "camera_yaw_deg": 45, "correct": False,
         "faults": [fault]}]}


def every_kind():
    """{kind name: document} for each file kind of the contract (the schema name is the key)."""
    skeleton = real_skeleton()
    skeleton["body"] = body_block()
    return {
        "pose3d": pose3d_head(), "keyframes-part1": keyframes_part1(), "keyframes-part4": keyframes_part4(),
        "body-profile": body_profile(), "skeleton": skeleton, "skeleton-part4": part4_view(),
        "animation-part5": part5_view(), "people-index": people_index(), "follower-labels": follower_labels(),
    }
