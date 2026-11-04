"""AC-C21 (docs/specs/integration-contract.md, TICKET-075): a Part 4 animation.json that carries the optional
`unseen_joints` and `frames[].conf` Part 4 added at 7036622 is accepted by `doctor` and by `analyse`.

The documents are built from the committed Part 4 fixture with the two fields added, so the test needs no copy of Part 4's
code and moves with `make contracts-sync`."""
import json
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from part5 import cli
from part5.io import JOINTS, load_clip

ROOT = Path(__file__).resolve().parent.parent
PART4_CLIP = ROOT / "fixtures/input/contract/part4/exercise/animation.json"
PART4_SCHEMA = ROOT / "contracts/part4/animation.schema.json"
FOLLOWER = ROOT / "fixtures/input/followers/exercise/exercise_front_good_08_arms_wider-both+elbow_bent-right/skeleton.json"
KEY_CONF, FILLED_CONF, UNSEEN_CONF = 0.9, 0.7, 0.1   # seen joints stay above 0.3; an unseen one is at or below it


def part4_clip_with_conf(unseen=()):
    """The committed Part 4 clip with `unseen_joints` (canonical order) and a `conf` on every frame, as Part 4 7036622
    writes them: a key frame carries its key's values, a filled frame the lower of its neighbours."""
    doc = json.loads(PART4_CLIP.read_text())
    doc["unseen_joints"] = [j for j in JOINTS if j in unseen]
    for frame in doc["frames"]:
        seen = FILLED_CONF if frame["interpolated"] else KEY_CONF
        frame["conf"] = {j: UNSEEN_CONF if j in unseen else seen for j in JOINTS}
    return doc


def written(tmp_path, doc, name="animation.json"):
    path = tmp_path / name
    path.write_text(json.dumps(doc))
    return path


def doctor(path, capsys, *args):
    code = cli.main(["doctor", str(path), "--for", "part5", "--json", *args])
    return code, json.loads(capsys.readouterr().out)


CASES = {"none unseen": (), "one unseen": ("left_wrist",), "both wrists and an ear": ("left_wrist", "right_wrist", "left_ear")}


@pytest.fixture(params=sorted(CASES), ids=sorted(CASES))
def unseen(request):
    return CASES[request.param]


def test_the_built_document_has_the_shape_part4_now_publishes(unseen):
    doc = part4_clip_with_conf(unseen)
    jsonschema.Draft202012Validator(json.loads(PART4_SCHEMA.read_text())).validate(doc)
    assert doc["unseen_joints"] == [j for j in JOINTS if j in unseen]
    assert any(f["interpolated"] for f in doc["frames"]) and not all(f["interpolated"] for f in doc["frames"])


def test_doctor_accepts_a_part4_animation_with_unseen_joints_and_conf(tmp_path, capsys, unseen):
    code, report = doctor(written(tmp_path, part4_clip_with_conf(unseen)), capsys)
    assert code == 0 and report["verdict"] == "accepted" and report["problems"] == []
    assert report["kind"] == "animation" and report["version"] == "simon.animation.v1"


def test_the_loader_reads_the_conf_and_masks_the_unseen_joints(tmp_path, unseen):
    clip = load_clip(written(tmp_path, part4_clip_with_conf(unseen)))
    assert clip.conf is not None and clip.conf.shape == (clip.n_frames, len(JOINTS))
    for name in JOINTS:
        j = JOINTS.index(name)
        assert clip.mask[:, j].any() != (name in unseen)          # an unseen joint is used in no frame, the rest are
        assert np.allclose(clip.conf[:, j], UNSEEN_CONF if name in unseen else [
            FILLED_CONF if f else KEY_CONF for f in clip.interpolated])


def analyse(expected, follower, tmp_path):
    out = tmp_path / "analysis.json"
    code = cli.main(["analyse", "--expected", str(expected), "--follower", str(follower), "--out", str(out)])
    return code, json.loads(out.read_text())


def test_analyse_accepts_a_part4_animation_with_the_new_fields_as_the_expected_clip(tmp_path, unseen):
    expected = written(tmp_path, part4_clip_with_conf(unseen), "expected.json")
    code, doc = analyse(expected, FOLLOWER, tmp_path)
    assert code == 0 and doc["status"]["code"] == "ok"
    assert doc["expected"]["path"] == str(expected)


def test_analyse_accepts_a_part4_animation_with_the_new_fields_as_the_follower(tmp_path, unseen):
    follower = written(tmp_path, part4_clip_with_conf(unseen), "follower.json")
    code, doc = analyse(PART4_CLIP, follower, tmp_path)
    assert code == 0 and doc["status"]["code"] == "ok"
    assert doc["follower"]["path"] == str(follower)


def test_the_new_fields_change_nothing_while_every_joint_is_seen(tmp_path):
    """With every joint above 0.3 the take is analysed as the same clip without the two fields."""
    plain = analyse(PART4_CLIP, FOLLOWER, tmp_path)[1]
    with_fields = analyse(written(tmp_path, part4_clip_with_conf(), "expected.json"), FOLLOWER, tmp_path)[1]
    assert with_fields["faults"] == plain["faults"] and with_fields["score"] == plain["score"]


def test_a_conf_outside_zero_to_one_is_still_rejected_with_the_frame_named(tmp_path, capsys):
    doc = part4_clip_with_conf()
    doc["frames"][3]["conf"]["left_knee"] = 1.5
    code, report = doctor(written(tmp_path, doc), capsys)
    assert code == 1 and report["verdict"] == "rejected"
    assert [p["path"] for p in report["problems"]] == ["frames[3].conf.left_knee"]
