import copy
import json
from pathlib import Path

import numpy as np
import pytest

from part5.io import JOINTS, InputError, load_clip, parse_clip

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = ROOT / "fixtures/input/expected/exercise/animation.json"
FOLLOWERS = ROOT / "fixtures/input/followers"


@pytest.fixture(scope="module")
def doc():
    return json.loads(EXPECTED.read_text())


def test_expected_fixtures_load():
    for s, n in [("exercise", 91), ("dance", 121)]:
        clip = load_clip(ROOT / f"fixtures/input/expected/{s}/animation.json")
        assert clip.positions.shape == (n, 17, 3)
        assert clip.mask.all()
        assert clip.fps == 30


def test_every_follower_fixture_loads():
    labels = json.loads((FOLLOWERS / "labels.json").read_text())
    for take in labels["takes"]:
        clip = load_clip(ROOT / take["follower"])
        assert clip.n_frames == take["frame_count"]


def test_keyframe_skeleton_format(doc):
    sk = {"format": "simon.skeleton.v1", "joints": JOINTS,
          "keyframes": [{"index": f["index"], "t": f["t"], "joints": f["joints"]} for f in doc["frames"][::10]]}
    clip = parse_clip(sk)
    assert clip.n_frames == 10


def test_missing_and_low_conf_joints_are_masked(doc):
    d = copy.deepcopy(doc)
    d["frames"][3]["joints"].pop("left_wrist")
    d["frames"][4]["conf"] = {"right_knee": 0.1}
    clip = parse_clip(d)
    assert not clip.mask[3, JOINTS.index("left_wrist")]
    assert np.isnan(clip.positions[3, JOINTS.index("left_wrist")]).all()
    assert not clip.mask[4, JOINTS.index("right_knee")]
    assert clip.mask.sum() == clip.mask.size - 2


@pytest.mark.parametrize("edit, msg", [
    (lambda d: d.update(format="nope"), "format must be"),
    (lambda d: d.update(joints=JOINTS[::-1]), "canonical 17"),
    (lambda d: d["coordinate_frame"].update(y="world_down"), "coordinate_frame.y"),
    (lambda d: d.update(frames=[]), "non-empty"),
    (lambda d: d["frames"][2]["joints"].update(nose=[0, 1]), "joints.nose"),
    (lambda d: d["frames"][2]["joints"].update(toe=[0, 0, 0]), "unknown names"),
    (lambda d: d["frames"][5].update(t=0.0), "strictly increase"),
    (lambda d: [f["joints"].update(left_hip=[0.5, 0.0, 0.0]) for f in d["frames"]], "hip midpoint"),
])
def test_malformed_inputs_fail_clearly(doc, edit, msg):
    d = copy.deepcopy(doc)
    edit(d)
    with pytest.raises(InputError, match=msg):
        parse_clip(d, source="bad.json")


def test_unreadable_file(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{not json")
    with pytest.raises(InputError, match="cannot read JSON"):
        load_clip(p)
