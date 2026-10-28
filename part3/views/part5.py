"""View `part5`: the `simon.animation.v1` shape Part 5 reads (its `docs/schemas.md`).

Only frames that hold the person are written, each with `interpolated: false`. `t` is seconds from
the first input frame; `index` is the input `frame` (the grid index when the skeleton was resampled).
`frame_count` is the number of frames written, `frames_skipped` the input frames left out, and
`duration_s` spans the whole clip. `fps` is always written (`output_fps`): the `--fps` rate when the skeleton
was resampled, otherwise the input clock's rate, 1000 over the median step between consecutive input `t_ms`
(3 decimals), and 30 for a clip with no positive step. It is the clip's nominal clock; each frame's `t` stays
the time of record when steps are not uniform. `y` is `world_up` because Part 3's body up is its estimate of world
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
FPS_DECIMALS = 3
FALLBACK_FPS = 30  # a clip with no positive step between frames (one frame): Part 4's and Part 6's play rate


def _seconds(t_ms, t0_ms):
    return round((t_ms - t0_ms) / 1000.0, T_DECIMALS)


def output_fps(skeleton):
    """The output clock's rate, a number above 0: the resample rate, else 1000 / median input step, else 30."""
    if "resample" in skeleton:
        return skeleton["resample"]["fps"]
    times = [frame["t_ms"] for frame in skeleton["frames"]]
    steps = sorted(b - a for a, b in zip(times, times[1:]) if b > a)
    if not steps:
        return FALLBACK_FPS
    middle = len(steps) // 2
    step = steps[middle] if len(steps) % 2 else (steps[middle - 1] + steps[middle]) / 2
    rate = 1000.0 / step
    rounded = round(rate, FPS_DECIMALS)
    return rounded if rounded > 0 else rate


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
    head = {"format": FORMAT, "producer": "part3", "view": NAME, "fps": output_fps(skeleton)}
    return {**head, "duration_s": _seconds(clip[-1]["t_ms"], clip[0]["t_ms"]), "frame_count": len(frames),
            "coordinate_frame": dict(COORDINATE_FRAME), "joints": list(JOINTS), "bones": _bone_list(skeleton),
            "body": copy.deepcopy(skeleton["body"]), "person": copy.deepcopy(skeleton["person"]),
            "mirror": dict(skeleton["mirror"]),
            "source": {"schema": SCHEMA_ID, "sha256": skeleton["input"]["sha256"]},
            "frames_skipped": len(clip) - len(frames), "frames": frames}
