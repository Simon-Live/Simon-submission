"""The replay payload for the web viewer: both skeletons, matched frame for frame.

`build_replay(result)` takes a `pipeline.PipelineResult` and returns plain JSON data. The
timeline runs on the expected clip's frames. At expected frame `i` the follower shows its own
file's frame `exp_to_fol[i]`, so the viewer never needs the resampled clock the alignment used.

`simon.replay.v1` (contracts/replay.schema.json, ADR-0009) is that payload plus `format`,
`schema_version`, `expected_t`, `follower_t` and `coordinate_frame`; `write_replay` writes it.
"""
import json
from pathlib import Path

import numpy as np

from .io import JOINTS
from .pipeline import clip_fps

DECIMALS = 4
FORMAT = "simon.replay.v1"
SCHEMA_VERSION = "1.0.0"
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


def build_replay(result):
    """`{fps, expected, follower, exp_to_fol, joints, bones}` for one `PipelineResult`.

    `expected` and `follower` hold the normalised clips on their own frames. `exp_to_fol[i]` is the
    follower file's frame shown at expected frame `i`: the alignment's choice, mapped back from the
    resampled follower frames to the file's own.
    """
    if result.alignment is None:
        raise ValueError("a replay needs the alignment, and this analysis has none")
    exp_to_fol = np.asarray(result.to_original)[np.asarray(result.alignment.exp_to_fol)]
    return {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "fps": float(clip_fps(result.expected)),
        "expected": frames_json(result.expected.positions),
        "follower": frames_json(result.follower.positions),
        "exp_to_fol": [int(i) for i in exp_to_fol],
        "joints": list(JOINTS),
        "bones": [list(b) for b in BONES],
        "expected_t": [round(float(x), 6) for x in result.expected.t],
        "follower_t": [round(float(x), 6) for x in result.follower.t],
        "coordinate_frame": dict(COORDINATE_FRAME),
    }


def write_replay(path, result):
    """Write `build_replay(result)` to `path` (parents made); returns the payload. OSError propagates."""
    payload = build_replay(result)
    text = json.dumps(payload, allow_nan=False) + "\n"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text)
    return payload
