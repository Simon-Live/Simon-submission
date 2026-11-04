"""The replay payload for the web viewer: both skeletons, matched frame for frame.

`build_replay(result)` takes a `pipeline.PipelineResult` and returns plain JSON data. The
timeline runs on the expected clip's frames. At expected frame `i` the follower shows its own
file's frame `exp_to_fol[i]`, so the viewer never needs the resampled clock the alignment used.

`simon.replay.v1` (contracts/replay.schema.json, ADR-0009) is that payload plus `format`,
`schema_version`, `expected_t`, `follower_t` and `coordinate_frame`; `write_replay` writes it.
From 1.1.0 (TICKET-085) it also says where the alignment path ends (`aligned_until`): the alignment is open-ended
(part5/align.py), so the follower frames after the last one `exp_to_fol` reaches were never compared or scored.

Ask this take reads a replay back in `part5/ask/tools.py` (`Take` and the agent's five tools), which was the second half of
this module until the 1.14.0 round moved it (TICKET-081).
"""
import json
from pathlib import Path

import numpy as np

from .io import JOINTS
from .pipeline import clip_fps

DECIMALS = 4
FORMAT = "simon.replay.v1"
SCHEMA_VERSION = "1.1.0"   # 1.1.0 (TICKET-085): aligned_until_s and aligned_until_expected_frame
COORDINATE_FRAME = {"origin": "hip_midpoint", "x": "subject_left", "y": "world_up", "z": "anterior",
                    "unit": "metres"}

# Joint-name pairs the viewer draws as bones. The torso sides stand in for the spine, which has
# no joint of its own among the 17, and the nose to each shoulder stands in for the neck.
BONE_NAMES = [
    ("nose", "left_eye"), ("nose", "right_eye"), ("left_eye", "left_ear"), ("right_eye", "right_ear"),
    ("nose", "left_shoulder"), ("nose", "right_shoulder"),
    ("left_shoulder", "right_shoulder"), ("left_hip", "right_hip"),
    ("left_shoulder", "left_hip"), ("right_shoulder", "right_hip"),
    ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
    ("left_hip", "left_knee"), ("left_knee", "left_ankle"),
    ("right_hip", "right_knee"), ("right_knee", "right_ankle"),
]
BONES = [[JOINTS.index(a), JOINTS.index(b)] for a, b in BONE_NAMES]


def frames_json(positions):
    """(F, 17, 3) positions as nested lists, 4 decimals; a joint with a NaN coordinate is `None`."""
    arr = np.round(np.asarray(positions, dtype=float), DECIMALS) + 0.0  # + 0.0 turns -0.0 into 0.0
    usable = np.isfinite(arr).all(axis=2)
    return [[arr[f, j].tolist() if usable[f, j] else None for j in range(arr.shape[1])]
            for f in range(arr.shape[0])]


def aligned_until(exp_to_fol, follower_t):
    """Where the alignment path ends (TICKET-085), reported only: `aligned_until_s`, the follower time of the last
    follower frame `exp_to_fol` reaches, and `aligned_until_expected_frame`, the last expected frame shown with it.
    Follower frames after `aligned_until_s` were never compared: a reader that maps follower frames back to expected
    ones would pair each with that expected frame, and should leave them out instead."""
    last = max(exp_to_fol)
    expected_frame = max(i for i, f in enumerate(exp_to_fol) if f == last)
    return {"aligned_until_s": round(float(follower_t[last]), 6), "aligned_until_expected_frame": int(expected_frame)}


def build_replay(result):
    """`{fps, expected, follower, exp_to_fol, joints, bones}` for one `PipelineResult`.

    `expected` and `follower` hold the normalised clips on their own frames. `exp_to_fol[i]` is the
    follower file's frame shown at expected frame `i`: the alignment's choice, mapped back from the
    resampled follower frames to the file's own.
    """
    if result.alignment is None:
        raise ValueError("a replay needs the alignment, and this analysis has none")
    if result.reps:
        return _rep_replay(result)
    exp_to_fol = [int(i) for i in np.asarray(result.to_original)[np.asarray(result.alignment.exp_to_fol)]]
    return {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "fps": float(clip_fps(result.expected)),
        "expected": frames_json(result.expected.positions),
        "follower": frames_json(result.follower.positions),
        "exp_to_fol": exp_to_fol,
        "joints": list(JOINTS),
        "bones": [list(b) for b in BONES],
        "expected_t": [round(float(x), 6) for x in result.expected.t],
        "follower_t": [round(float(x), 6) for x in result.follower.t],
        "coordinate_frame": dict(COORDINATE_FRAME),
        **aligned_until(exp_to_fol, result.follower.t),
    }


def _follower_frames(rep):
    """The follower file's frame shown at each reference frame of one rep; a rep that could not be aligned
    plays straight through its resampled frames."""
    idx = np.arange(len(rep.to_original)) if rep.alignment is None else np.asarray(rep.alignment.exp_to_fol)
    return [int(rep.to_original[j]) for j in idx]


def _rep_replay(result):
    """The replay of a take compared rep by rep (ADR-0010): each follower rep's expected reference (ADR-0017: the
    expected rep it was compared with, so the references differ in length when the example's reps do) one after the
    other, and the whole follower take played against them. `reps` lists, per follower rep, the
    expected frames it is shown against (frames of this tiled list, not of the expected file), the follower
    file's frames and whether the guard passed it. `expected_t` starts at the first reference's own time in the
    expected file."""
    reps = result.reps
    refs = [r.expected for r in reps]
    sizes = [ref.n_frames for ref in refs]
    ends = np.cumsum(sizes)
    fps = float(clip_fps(refs[0]))
    exp_to_fol = [f for r in reps for f in _follower_frames(r)]
    # The first copy of the reference carries the example file's own times; each further copy follows one rep
    # (and one frame step) later, so the list still strictly increases.
    expected_t, start = [], float(refs[0].t[0])
    for ref in refs:
        expected_t += [round(start + float(t - ref.t[0]), 6) for t in ref.t]
        start += float(ref.t[-1] - ref.t[0]) + 1.0 / fps
    return {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "fps": fps,
        "expected": frames_json(np.concatenate([ref.positions for ref in refs])),
        "follower": frames_json(result.follower.positions),
        "exp_to_fol": exp_to_fol,
        "joints": list(JOINTS),
        "bones": [list(b) for b in BONES],
        "expected_t": expected_t,
        "follower_t": [round(float(x), 6) for x in result.follower.t],
        "coordinate_frame": dict(COORDINATE_FRAME),
        "reps": [{"expected_frames": [int(e - n), int(e - 1)], "follower_frames": list(r.span), "ok": bool(r.ok)}
                 for r, n, e in zip(reps, sizes, ends)],
        **aligned_until(exp_to_fol, result.follower.t),
    }


def write_replay(path, result):
    """Write `build_replay(result)` to `path` (parents made); returns the payload. OSError propagates."""
    payload = build_replay(result)
    text = json.dumps(payload, allow_nan=False) + "\n"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text)
    return payload
