"""The `part4` view: the native skeleton plus Part 4's rig, rotations and keyframes (TICKET-025).

Spec: docs/specs/integration-contract.md "Views" and "Part 4 rig and rotations". Part 4 reads
`skeleton.json` with `format: simon.skeleton.v1`, `rest_offsets_m` and `keyframes[]` carrying
`local_rotations`, and rejects a key whose forward kinematics misses its `joints` by over 1 mm. So each
key's `joints` are the forward kinematics of its (rounded) rotations, and the distance of those joints
to the native pose is reported in `rig.fit` instead of being hidden.
"""

import copy

import numpy as np

from part3 import config as config_file
from part3 import keyframes as kf
from part3 import rig
from part3.joints import COORDINATE_FRAME, JOINTS
from part3.schema import LongWayError, ViewError, view_refusal_text

NAME = "part4"
DESCRIPTION = ("simon.skeleton.v1 for Part 4: the native skeleton plus rest offsets, 30 fps key ticks "
               "and one fitted local rotation per rig joint at each key")
SCHEMA = "skeleton-part4.schema.json"

FORMAT = "simon.skeleton.v1"
KEYFRAMES_FORMAT = "simon.keyframes.v1"
PAGE_LABEL = "Part 4 keys"  # how the run app names this view in a sentence (schema.view_refusal_text)
VIRTUAL_JOINTS = ["pelvis", "neck"]
DECIMALS = 6
GAP_PAGE_TEXT = "Every key falls where the person is missing from the clip, so there is no key pose to write."
GAP_REASON = "the input frame nearest the key has no person (the person is missing there)"


def render(skeleton, keyframes=None, keyframes_person=None, max_frames=None, keyframes_densify=None,
           densify_flag=None, env=None, config=None, **_):
    """A new dict: the native `skeleton` unchanged plus the Part 4 fields.

    `keyframes` is a file path (Part 1 or Part 4 keyframes), `"every:<n>"` or a parsed keyframes dict;
    `keyframes_person` picks the Part 1 person; `max_frames` caps the timeline's ticks (None: the cap
    of `resample.MAX_FRAMES`). `keyframes_densify` (the API channel), `densify_flag` (the command-line channel), `env` and
    `config` feed `keyframes.resolve_densify` (`every:<n>` or `off`); they apply to a keyframes file only and are ignored for `every:<n>`
    (`env` None: `os.environ`; `config` None discovers a file, False reads none). Raises ViewError when `keyframes` is missing; ContractError when it is
    unreadable, of an unknown kind or leaves no key inside the clip; FrameCapError when the timeline would
    be longer than the cap; LongWayError (a ViewError) when Part 4 would reject the keys (a joint turning
    the long way between two of them).
    """
    if keyframes is None:
        raise ViewError("--view part4", "needs --keyframes <keyframes.json> or every:<n>",
                        view_refusal_text(PAGE_LABEL), colon=False)
    frames = skeleton["frames"]
    t0_ms, t_last_ms = frames[0]["t_ms"], frames[-1]["t_ms"]
    timeline = kf.load(keyframes, t0_ms, t_last_ms, person=keyframes_person, max_frames=max_frames)
    named_ticks = {index for index, _ in timeline.keys}
    timeline = _densified(timeline, keyframes, (densify_flag, keyframes_densify), env, config)
    offsets = _written_offsets(skeleton["bone_lengths_m"])
    holders = [(f["t_ms"], f) for f in frames if f["people"]]
    keys, residual, previous, kept = [], [], None, []
    every = [(f["t_ms"], f) for f in frames]
    for index, name in timeline.keys:
        t_ms = kf.tick_time_ms(t0_ms, index)
        if not _nearest(every, t_ms)["people"]:
            timeline.dropped.append({"name": name, "t_ms": round(t_ms, 3), "reason": GAP_REASON})
            continue
        key, distances = _key(index, name, _nearest(holders, t_ms), offsets, previous)
        previous = key["local_rotations"]
        keys.append(key)
        residual.append(distances)
        kept.append((index, name))
    if not keys:
        raise ViewError("--keyframes", "every key falls where the person is missing from the clip",
                        GAP_PAGE_TEXT)
    if timeline.densify:  # a filler dropped for a missing person is not an added key
        timeline.densify["added"] = sum(1 for index, _ in kept if index not in named_ticks)
    _check_long_way(keys)
    out = copy.deepcopy(skeleton)
    out.update({
        "format": FORMAT,
        "fps": kf.FPS,
        "coordinate_frame": dict(COORDINATE_FRAME),
        "root_joint": rig.ROOT_JOINT,
        "virtual_joints": list(VIRTUAL_JOINTS),
        "rest_offsets_m": offsets,
        "timeline": _timeline_block(timeline),
        "rig": {"convention": rig.CONVENTION, "fit": _fit_block(kept, residual)},
        "keyframes": keys,
    })
    return out


def _densified(timeline, keyframes, channels, env, config):
    """`timeline` densified when a channel asks for it and the source is a keyframes file, else as given.

    A dropped filler (nobody at its tick) is counted out of `added` after the keys are built."""
    if kf.is_every(keyframes):
        return timeline
    flag, api = channels
    n, selected_by = kf.resolve_densify(flag=flag, api=api, env=env, config=config_file.load(config, env))
    return timeline if n is None else kf.densify(timeline, n, selected_by)


def keyframes_doc(rendered):
    """The `simon.keyframes.v1` companion of a part4 render: the file Part 4 reads beside `skeleton.json`."""
    timeline = rendered["timeline"]
    return {
        "format": KEYFRAMES_FORMAT,
        "producer": "part3",
        "fps": timeline["fps"],
        "duration_s": timeline["duration_s"],
        "frame_count": timeline["frame_count"],
        "keyframes": [{"index": k["index"], "t": k["t"], "name": k["name"]} for k in rendered["keyframes"]],
    }


def _check_long_way(keys):
    """Raise LongWayError for the earliest key step Part 4 would reject (spec "Self-check", review B2)."""
    steps = rig.long_way(keys)
    if steps:
        step = min(steps, key=lambda s: s["from_index"])
        raise LongWayError("--view part4", f"Part 4 would reject this clip: {step['joint']} turns {step['deg']} "
                                           f"degrees between keys {step['from_index']} and {step['to_index']} "
                                           f"(Part 4 allows {rig.MAX_ROTVEC_STEP_DEG:g}); {rig.LONG_WAY_FIX}",
                           joint=step["joint"], degrees=step["deg"], from_index=step["from_index"],
                           to_index=step["to_index"], limit_deg=rig.MAX_ROTVEC_STEP_DEG)


def _round(values):
    """A list of floats rounded to the output decimals, -0.0 written as 0.0."""
    return (np.round(np.asarray(values, dtype=float), DECIMALS) + 0.0).tolist()


def _written_offsets(bone_lengths_m):
    """The rest offsets as written to the file (rounded); the fit and the forward pass use these exact numbers."""
    offsets = rig.rest_offsets(bone_lengths_m)
    return {j: {"parent": e["parent"], "offset": _round(e["offset"])} for j, e in offsets.items()}


def _nearest(holders, t_ms):
    """The frame holding the person nearest in time to `t_ms`; ties go to the earlier frame."""
    gaps = np.abs(np.array([t for t, _ in holders]) - t_ms)
    return holders[int(np.flatnonzero(gaps <= gaps.min() + 1e-9)[0])][1]


def _key(index, name, frame, offsets, previous=None):
    """(key entry, per-joint distance in metres of the key's FK joints to the native pose).
    `previous` is the previous key's local rotations, for rig.fit's twist continuity."""
    person = frame["people"][0]["joints"]
    native = {j: [person[j]["x"], person[j]["y"], person[j]["z"]] for j in JOINTS}
    rotations, _, _ = rig.fit(native, offsets, previous)
    rotations = {j: _round(q) for j, q in rotations.items()}
    posed = {j: _round(p) for j, p in rig.forward(rotations, offsets).items()}
    distances = rig.residuals(posed, native)
    return {
        "index": index,
        "t": round(index / kf.FPS, DECIMALS),
        "name": name,
        "source_frame": frame["frame"],
        "source_t_ms": frame["t_ms"],
        "joints": posed,
        "conf": {j: person[j]["conf"] for j in JOINTS},
        "local_rotations": rotations,
    }, distances


def _timeline_block(timeline):
    return {"fps": timeline.fps, "duration_s": timeline.duration_s, "frame_count": timeline.frame_count,
            "t0_ms": timeline.t0_ms, "source_kind": timeline.source_kind, "person": timeline.person,
            "dropped": copy.deepcopy(timeline.dropped),
            **({"densify": dict(timeline.densify)} if timeline.densify else {})}


def _fit_block(keys, residual):
    """max_m, mean_m, worst_joint and worst_index (the key tick) of the distance to the native pose."""
    table = np.array([[d[j] for j in JOINTS] for d in residual])
    key, joint = np.unravel_index(int(np.argmax(table)), table.shape)
    return {"max_m": round(float(table.max()), DECIMALS), "mean_m": round(float(table.mean()), DECIMALS),
            "worst_joint": JOINTS[joint], "worst_index": keys[key][0]}
