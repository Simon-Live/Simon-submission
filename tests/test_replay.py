"""part5.replay.build_replay: both skeletons and the frame match, ready for the viewer."""
import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest

from part5.io import JOINTS
from part5.pipeline import run
from part5.replay import BONES, build_replay, frames_json

ROOT = Path(__file__).resolve().parent.parent
LABELS = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
LABEL = next(t for t in LABELS["takes"] if t["set"] == "exercise" and t["angle"] == "front"
             and t["lighting"] == "good" and [f["type"] for f in t["faults"]] == ["foot_out"])
EXPECTED = ROOT / LABEL["expected"]
TAKE = ROOT / LABEL["follower"]


def with_doc(mutate):
    """The take's JSON after `mutate(doc)`, as an in-memory follower ref."""
    doc = json.loads(TAKE.read_text())
    mutate(doc)
    return {"path": "follower.upload", "doc": doc}


@pytest.fixture(scope="module")
def result():
    return run(str(EXPECTED), str(TAKE))


def test_payload_has_the_documented_keys_and_17_joints_per_frame(result):
    replay = build_replay(result)
    assert set(replay) == {"format", "schema_version", "fps", "expected", "follower", "exp_to_fol", "joints", "bones",
                           "expected_t", "follower_t", "coordinate_frame"}
    assert replay["fps"] == 30.0
    assert replay["joints"] == JOINTS
    assert len(replay["expected"]) == result.expected.n_frames
    assert len(replay["follower"]) == result.follower.n_frames
    assert all(len(frame) == 17 for frame in replay["expected"] + replay["follower"])
    assert all(len(joint) == 3 for joint in replay["expected"][0])


def test_bones_are_index_pairs_of_distinct_joints(result):
    bones = build_replay(result)["bones"]
    assert bones == [list(b) for b in BONES]
    assert all(0 <= a < 17 and 0 <= b < 17 and a != b for a, b in bones)


def test_exp_to_fol_is_the_alignment_mapped_to_original_follower_frames(result):
    replay = build_replay(result)
    assert replay["exp_to_fol"] == result.to_original[result.alignment.exp_to_fol].tolist()
    assert len(replay["exp_to_fol"]) == len(replay["expected"])
    assert 0 <= min(replay["exp_to_fol"]) and max(replay["exp_to_fol"]) < len(replay["follower"])
    assert np.all(np.diff(replay["exp_to_fol"]) >= 0)


def test_the_follower_is_the_files_own_frames_when_its_clock_differs():
    """Keeping every second frame halves the follower's rate: the replay must index that file."""
    slow = with_doc(lambda d: d.update(frames=d["frames"][::2]))
    res = run(str(EXPECTED), slow)
    replay = build_replay(res)
    assert len(replay["follower"]) == res.follower.n_frames == len(slow["doc"]["frames"])
    assert len(res.follower_positions) > len(replay["follower"])
    assert max(replay["exp_to_fol"]) < len(replay["follower"])
    assert replay["fps"] == 30.0


def test_a_missing_joint_is_null_and_the_payload_is_strict_json():
    def drop_wrist(doc):
        for frame in doc["frames"][10:14]:
            frame["joints"]["left_wrist"] = None

    replay = build_replay(run(str(EXPECTED), with_doc(drop_wrist)))
    wrist = JOINTS.index("left_wrist")
    assert all(replay["follower"][i][wrist] is None for i in range(10, 14))
    assert replay["follower"][5][wrist] is not None
    assert replay["follower"][11][JOINTS.index("left_knee")] is not None
    json.dumps(replay, allow_nan=False)


def test_coordinates_are_rounded_to_four_decimals(result):
    replay = build_replay(result)
    values = [c for frame in replay["expected"] + replay["follower"] for joint in frame for c in joint]
    assert values and all(round(v, 4) == v for v in values)


def test_negative_zero_is_written_as_zero():
    frames = frames_json(np.full((1, 17, 3), -0.00001))
    assert "-0.0" not in json.dumps(frames)


def test_a_joint_with_one_nan_coordinate_is_null():
    positions = np.zeros((1, 17, 3))
    positions[0, 4, 1] = np.nan
    assert frames_json(positions)[0][4] is None


def test_without_an_alignment_there_is_nothing_to_replay(result):
    with pytest.raises(ValueError, match="alignment"):
        build_replay(dataclasses.replace(result, alignment=None))
