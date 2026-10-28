"""View `part5`: the `simon.animation.v1` shape Part 5 reads (its `docs/schemas.md`).

Only frames that hold the person are written, each with `interpolated: false`. `t` is seconds from
the first input frame; `index` is the input `frame` (the grid index when the skeleton was resampled).
`frame_count` is the number of frames written, `frames_skipped` the input frames left out, and
`duration_s` spans the whole clip. `y` is `world_up` because Part 3's body up is its estimate of world
up (the native file calls the same axis `body_up`).
"""

import copy

from part3 import views
from part3.joints import COORDINATE_FRAME, JOINTS
from part3.schema import SCHEMA_ID, ViewError, view_refusal_text

NAME = "part5"
DESCRIPTION = "simon.animation.v1 for Part 5: joints as [x, y, z] lists, hip midpoint at the origin"
SCHEMA = "animation-part5.schema.json"
FORMAT = "simon.animation.v1"
PAGE_LABEL = "a Part 5 animation"  # how the run app names this view in a sentence (schema.view_refusal_text)
T_DECIMALS = 6


def _seconds(t_ms, t0_ms):
    return round((t_ms - t0_ms) / 1000.0, T_DECIMALS)


def _frame(frame, person, t):
    joints = person["joints"]
    return {"index": frame["frame"], "t": t, "interpolated": False,
            "joints": {name: [joints[name]["x"], joints[name]["y"], joints[name]["z"]] for name in JOINTS},
            "conf": {name: joints[name]["conf"] for name in JOINTS}}


def _frames(skeleton):
    t0, written, last = skeleton["frames"][0]["t_ms"], [], None
    for frame in skeleton["frames"]:
        if not frame["people"]:
            continue
        t = _seconds(frame["t_ms"], t0)
        if last is not None and t <= last:
            detail = f"frame {frame['frame']}: times must strictly increase (Part 5 rejects a clip whose times do not)"
            raise ViewError(f"--view {NAME}", detail, view_refusal_text(PAGE_LABEL, detail))
        written.append(_frame(frame, frame["people"][0], t))
        last = t
    return written


def _bone_list(skeleton):
    lengths = skeleton["bone_lengths_m"]
    return [{"name": bone["name"], "parent": bone["from"], "child": bone["to"], "length_m": lengths[bone["name"]]}
            for bone in skeleton["bones"]]


def render(skeleton, **opts):
    views.reject_options(opts, NAME)
    frames = _frames(skeleton)
    clip = skeleton["frames"]
    head = {"format": FORMAT, "producer": "part3", "view": NAME}
    if "resample" in skeleton:
        head["fps"] = skeleton["resample"]["fps"]
    return {**head, "duration_s": _seconds(clip[-1]["t_ms"], clip[0]["t_ms"]), "frame_count": len(frames),
            "coordinate_frame": dict(COORDINATE_FRAME), "joints": list(JOINTS), "bones": _bone_list(skeleton),
            "body": copy.deepcopy(skeleton["body"]), "person": copy.deepcopy(skeleton["person"]),
            "mirror": dict(skeleton["mirror"]),
            "source": {"schema": SCHEMA_ID, "sha256": skeleton["input"]["sha256"]},
            "frames_skipped": len(clip) - len(frames), "frames": frames}
