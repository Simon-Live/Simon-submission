"""Test support: build pose3d documents from arrays and inject label swaps (not a test module)."""

import copy
import functools
import json

import numpy as np

from conftest import REAL_CLIP
from part3 import cli
from part3.joints import GROUPS, JOINTS, swap_index
from part3.standard import bone_lengths
from part3.synth import FPS


@functools.lru_cache(maxsize=1)
def _real_skeleton():
    return cli.process(json.loads(REAL_CLIP.read_text()))


def real_skeleton():
    """A private copy of the skeleton of the real Part 2 fixture (computed once per session)."""
    return copy.deepcopy(_real_skeleton())


def doc_arrays(doc, person_index=0):
    """(J (n, 17, 3), conf (n, 17)) of one person per frame (every frame must hold a person)."""
    J = np.array([[[f["people"][person_index]["joints"][j][a] for a in "xyz"] for j in JOINTS]
                  for f in doc["frames"]])
    conf = np.array([[f["people"][person_index]["joints"][j]["conf"] for j in JOINTS]
                     for f in doc["frames"]])
    return J, conf


def make_doc(J, conf, pid=0, frame_ids=None, extra=None):
    """A pose3d dict for one person from arrays; frame numbers default to 0.. at the synthetic FPS."""
    n = len(J)
    frame_ids = list(range(n)) if frame_ids is None else frame_ids
    frames = [{"frame": int(fid), "t_ms": round(1000.0 * int(fid) / FPS, 3),
               "people": [{"id": pid, "joints": {
                   name: {"x": float(J[i, j, 0]), "y": float(J[i, j, 1]), "z": float(J[i, j, 2]),
                          "conf": float(conf[i, j])} for j, name in enumerate(JOINTS)}}]}
              for i, fid in enumerate(frame_ids)]
    return {"frames": frames, **(extra or {})}


def swap_frames(J, conf, frames, group):
    """Copy of (J, conf) with `group` label-swapped in `frames`; `body` also turns 180 degrees about y."""
    J, conf = J.copy(), conf.copy()
    perm = swap_index(GROUPS[group])
    for i in frames:
        J[i], conf[i] = J[i][perm], conf[i][perm]
        if group == "body":
            J[i] = J[i] * np.array([-1.0, 1.0, -1.0])
    return J, conf


def skeleton_arrays(skeleton):
    """(J (n, 17, 3), conf (n, 17), present mask) of a skeleton dict; absent frames are zeros."""
    n = len(skeleton["frames"])
    J, conf, present = np.zeros((n, 17, 3)), np.zeros((n, 17)), np.zeros(n, dtype=bool)
    for i, frame in enumerate(skeleton["frames"]):
        if frame["people"]:
            present[i] = True
            joints = frame["people"][0]["joints"]
            J[i] = [[joints[name][a] for a in "xyz"] for name in JOINTS]
            conf[i] = [joints[name]["conf"] for name in JOINTS]
    return J, conf, present


def flipped_frames(skeleton):
    """{group: sorted frame indices} listed in the skeleton's flips_repaired."""
    found = {}
    for i, frame in enumerate(skeleton["frames"]):
        for person in frame["people"]:
            for group in person["flips_repaired"]:
                found.setdefault(group, []).append(i)
    return found


def with_mirrored(doc, value):
    out = copy.deepcopy(doc)
    out["mirrored"] = value
    return out


def crowd(real_doc, ids=("b",), frames=20, absent=None, move=1.5):
    """The real clip's first `frames` frames with extra people (copies moved sideways) added.

    `absent` maps an id to the frame positions where it is missing; person 0 keeps the clip's own id.
    """
    doc = copy.deepcopy(real_doc)
    doc["frames"] = doc["frames"][:frames]
    absent = absent or {}
    for i, frame in enumerate(doc["frames"]):
        keep = [p for p in frame["people"] if i not in absent.get(p["id"], ())]
        for k, pid in enumerate(ids):
            if i in absent.get(pid, ()):
                continue
            other = copy.deepcopy(frame["people"][0])
            other["id"] = pid
            for joint in other["joints"].values():
                joint["x"] += move * (k + 1)
            keep.append(other)
        frame["people"] = keep
    return doc


def coincident_hips(doc, pid):
    """`doc` with the right hip of `pid` moved onto its left hip in every frame."""
    for frame in doc["frames"]:
        for entry in frame["people"]:
            if entry["id"] == pid:
                entry["joints"]["right_hip"] = dict(entry["joints"]["left_hip"])
    return doc


def write_profile(path, **changes):
    profile = {"schema": "simon.body_profile/1", "name": "tall-test", "stature_m": 1.9,
               "bone_lengths_m": {name: round(value * 1.9 / 1.7, 4) for name, value in bone_lengths().items()},
               "source": "unit test"}
    profile.update(changes)
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


def two_frames(doc, last_ms=10_000_000, first_ms=0):
    """A copy of the first two frames of `doc` placed `last_ms - first_ms` apart: a tiny upload with a long span."""
    out = copy.deepcopy(doc)
    out["frames"] = out["frames"][:2]
    out["frames"][0]["t_ms"], out["frames"][1]["t_ms"] = first_ms, last_ms
    return out


def equal_times(doc):
    """A copy of the first 3 frames of `doc` with two equal t_ms (0, 33, 33): valid natively, not for Part 5 or --fps."""
    out = copy.deepcopy(doc)
    out["frames"] = out["frames"][:3]
    for frame, t_ms in zip(out["frames"], (0.0, 33.0, 33.0)):
        frame["t_ms"] = t_ms
    return out
