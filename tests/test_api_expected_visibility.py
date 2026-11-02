"""TICKET-087: POST api/analyse takes the trainer's own visibility (`expected_visibility`), with the effect of
`part5 analyse --expected-visibility`, under the upload limits; a document Part 5 cannot read is a 400 naming the field.

The real lateral raise (fixtures/input/real/lateral-raise): its trainer is a Part 4 animation with no `conf`, and the follower
pexels-40297504 was filmed from the waist up (its knees and ankles at Part 2's 0.3 unseen mark). The trainer's own Part 2 file is
not committed, so the test writes one in the shape Part 2 writes (frames[].people[0].joints.<joint>.conf) for a trainer filmed from
the waist up too."""
import copy
import json
from pathlib import Path

import pytest

from part5 import api, cli
from part5.io import JOINTS

ROOT = Path(__file__).resolve().parent.parent
RAISE = ROOT / "fixtures/input/real/lateral-raise"
TRAINER = json.loads((RAISE / "pexels-5319084/animation.json").read_text())
FOLLOWER = json.loads((RAISE / "pexels-40297504/animation.json").read_text())
LEGS = ("left_knee", "right_knee", "left_ankle", "right_ankle")
LABELS = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
SAMPLE = next(t["take_id"] for t in LABELS["takes"] if t["take_id"].startswith("exercise_front_good_00"))


def waist_up_pose3d(n_frames):
    """A trainer's Part 2 pose3d (conf only): its legs at the unseen mark in every frame, every other joint seen."""
    joints = {j: {"conf": 0.3 if j in LEGS else 1.0} for j in JOINTS}
    return {"frames": [{"people": [{"id": 0, "joints": copy.deepcopy(joints)}]} for _ in range(n_frames)]}


def post(payload):
    status, _, out = api.handle("POST", "/api/analyse", json.dumps(payload).encode(), base_path="/")
    return status, json.loads(out)


def raise_request(**extra):
    return {"expected": {"upload": TRAINER}, "follower": {"upload": FOLLOWER}, **extra}


@pytest.fixture(scope="module")
def visibility():
    return waist_up_pose3d(len(TRAINER["frames"]))


@pytest.fixture(scope="module")
def without(visibility):
    status, body = post(raise_request())
    assert status == 200
    return body["analysis"]


@pytest.fixture(scope="module")
def with_field(visibility):
    status, body = post(raise_request(expected_visibility=visibility))
    assert status == 200
    return body["analysis"]


def codes(analysis):
    return [r["code"] for r in analysis["quality"]["reasons"]]


def test_without_the_field_a_waist_up_follower_reads_major_on_legs_the_trainer_never_showed(without):
    q = without["quality"]
    assert q["level"] == "major" and q["score_cap"] == 59 and codes(without)[0] == "joints_unseen"
    assert q["signals"]["unseen_joint_share"] == round(4 / 17, 4)


def test_with_the_field_the_legs_are_excused_and_only_the_follower_s_own_hidden_measures_count(with_field):
    """The joints_unseen reason goes and the take is no longer major. It reads degraded, not ok: hidden_measure_share reads the
    follower's own conf (10 of 22 measures need its legs), which the trainer's visibility does not excuse (docs/specs/quality.md)."""
    q = with_field["quality"]
    assert q["signals"]["unseen_joint_share"] == 0.0 and "joints_unseen" not in codes(with_field)
    assert q["level"] == "degraded" and q["score_cap"] is None and codes(with_field) == ["measures_hidden"]
    assert q["signals"]["hidden_measure_share"] == round(10 / 22, 4)


def test_the_field_has_the_effect_of_the_flag(with_field, visibility, tmp_path):
    files = {}
    for name, doc in (("trainer", TRAINER), ("follower", FOLLOWER), ("visibility", visibility)):
        files[name] = tmp_path / f"{name}.json"
        files[name].write_text(json.dumps(doc))
    out = tmp_path / "analysis.json"
    assert cli.main(["analyse", "--expected", str(files["trainer"]), "--follower", str(files["follower"]),
                     "--expected-visibility", str(files["visibility"]), "--out", str(out)]) == 0
    flag = json.loads(out.read_text())
    for key in ("quality", "faults", "score", "warnings", "insights"):
        assert flag.get(key) == with_field.get(key), key
    assert flag["diagnostics"]["visibility"] == with_field["diagnostics"]["visibility"]


def test_null_is_the_same_as_leaving_the_field_out():
    request = {"expected": {"sample": "exercise"}, "follower": {"sample": SAMPLE}}
    assert post(request) == post(dict(request, expected_visibility=None))


@pytest.mark.parametrize("value,message", [
    ("{not json", "expected_visibility: not JSON"),
    ([1, 2], "expected_visibility: give the trainer's own skeleton or pose3d document"),
    ({"frames": []}, "expected_visibility: expected-visibility file has no frames"),
    ({"frames": [{"conf": {"left_knee": "seen"}}]}, "expected_visibility: expected-visibility conf must be a number"),
])
def test_a_document_part5_cannot_read_is_a_400_naming_the_field(value, message):
    status, body = post({"expected": {"sample": "exercise"}, "follower": {"sample": SAMPLE}, "expected_visibility": value})
    assert status == 400 and body["error"]["field"] == "expected_visibility" and body["error"]["message"].startswith(message)


def test_a_document_over_the_upload_limit_is_a_413_naming_the_field(monkeypatch, visibility):
    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 1024)
    status, body = post({"expected": {"sample": "exercise"}, "follower": {"sample": SAMPLE}, "expected_visibility": visibility})
    assert status == 413 and body["error"]["field"] == "expected_visibility"
