"""Part 3's `frame.up_source` values reach Part 5 through the vendored schemas (TICKET-096, CONTRACT.md "Where the copies
come from"). Part 3 73ed073 adds `input_up_floor_work` (with `frame.floor_work: true`, written under its opt-in
`--floor-work`) to `two_footed_frames` of 9f37c38, and Part 3 72e120f adds `gravity` (with the object `frame.gravity`, and
`frame.gravity_ignored` for a malformed input). A committed Part 3 file is not rewritten here: the view-part4 and native
fixtures are copies, so each value is tried on a copy of them in a temporary tree."""
import json
import shutil
from pathlib import Path

import jsonschema
import pytest

from part5 import cli, contract
from part5.io import InputError, load_clip

ROOT = Path(__file__).resolve().parent.parent
P3 = ROOT / "fixtures/input/contract/part3"
VIEW4 = P3 / "view-part4/skeleton.json"
NATIVE = P3 / "native/skeleton.json"
# The values Part 3 72e120f CONTRACT.md names for `up_source` in the native and `--view part4` skeleton.
UP_SOURCES = ("standing_frames", "two_footed_frames", "input_up_floor_work", "input_up", "all_frames", "gravity")
# A `frame.gravity` as the schema requires it (counts, spread and the body rule's source and angle).
GRAVITY = {"frames_used": 107, "frames_total": 107, "spread_deg": 0.0, "body_rule_source": "standing_frames",
           "body_rule_angle_deg": 4.2}
# (vendored schema, the committed Part 3 file it describes)
PAIRS = [("part3/skeleton-part4.schema.json", VIEW4), ("part3/skeleton.schema.json", NATIVE)]


def validator(name):
    return jsonschema.Draft202012Validator(json.loads((ROOT / "contracts" / name).read_text()))


def with_up_source(path, up_source, **frame):
    doc = json.loads(path.read_text())
    doc["frame"]["up_source"] = up_source
    if up_source == "input_up_floor_work":
        doc["frame"]["floor_work"] = True
    if up_source == "gravity":
        doc["frame"]["gravity"] = dict(GRAVITY)
    doc["frame"].update(frame)
    return doc


def write(root, rel, doc):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))
    return path


@pytest.mark.parametrize("name,path", PAIRS, ids=["view-part4", "native"])
def test_the_vendored_schemas_name_every_up_source_part3_writes(name, path):
    frame = json.loads((ROOT / "contracts" / name).read_text())["properties"]["frame"]["properties"]
    assert set(UP_SOURCES) <= set(frame["up_source"]["enum"])
    assert {"input_up_floor_work", "gravity"} <= set(frame["up_source"]["enum"])
    assert {"floor_work", "gravity", "gravity_ignored"} <= set(frame)


@pytest.mark.parametrize("up_source", UP_SOURCES)
@pytest.mark.parametrize("name,path", PAIRS, ids=["view-part4", "native"])
def test_each_up_source_validates_against_the_vendored_schema(name, path, up_source):
    errors = list(validator(name).iter_errors(with_up_source(path, up_source)))
    assert not errors, [e.message[:120] for e in errors[:3]]


@pytest.mark.parametrize("name,path", PAIRS, ids=["view-part4", "native"])
def test_floor_work_is_true_or_absent_and_an_unlisted_up_source_is_refused(name, path):
    v = validator(name)
    assert not list(v.iter_errors(with_up_source(path, "standing_frames", floor_work=True)))
    assert list(v.iter_errors(with_up_source(path, "input_up_floor_work", floor_work=False)))
    assert list(v.iter_errors(with_up_source(path, "not_an_up_source")))


@pytest.mark.parametrize("name,path", PAIRS, ids=["view-part4", "native"])
def test_gravity_needs_its_counts_and_gravity_ignored_is_a_reason(name, path):
    """72e120f: `frame.gravity` has five required members; a malformed input is named in `frame.gravity_ignored`."""
    v = validator(name)
    assert not list(v.iter_errors(with_up_source(path, "gravity", gravity={**GRAVITY, "warning": "differs by 31 deg",
                                                                              "body_rule_max_deg": 33.0})))
    for key in GRAVITY:
        short = {k: x for k, x in GRAVITY.items() if k != key}
        assert list(v.iter_errors(with_up_source(path, "gravity", gravity=short))), key
    assert not list(v.iter_errors(with_up_source(path, "input_up", gravity_ignored="up is not a unit vector")))
    assert list(v.iter_errors(with_up_source(path, "input_up", gravity_ignored=5)))


NEW_VALUES = ("input_up_floor_work", "gravity")   # the two values added after 9f37c38, one test each below


@pytest.mark.parametrize("up_source", NEW_VALUES)
def test_an_expected_skeleton_with_the_new_up_source_loads_through_part5_io_like_the_committed_one(tmp_path, up_source):
    """Part 5 reads keyframes and fps only: the `frame` block does not change what it loads."""
    got = load_clip(write(tmp_path, "new.json", with_up_source(VIEW4, up_source)))
    plain = load_clip(VIEW4)
    assert got.format == plain.format == "simon.skeleton.v1"
    assert got.n_frames == plain.n_frames and got.fps == plain.fps
    assert (got.positions == plain.positions).all()


@pytest.mark.parametrize("up_source", NEW_VALUES)
def test_a_native_skeleton_with_the_new_up_source_is_still_rejected_with_the_fix_named(tmp_path, up_source):
    with pytest.raises(InputError, match="format must be one of"):
        load_clip(write(tmp_path, "native.json", with_up_source(NATIVE, up_source)))


@pytest.mark.parametrize("up_source", NEW_VALUES)
def test_part5_contract_check_accepts_a_fixture_with_the_new_up_source_in_a_contract_part3_tree(tmp_path, up_source):
    """`part5.contract` (make check-5-contract) classifies a Part 3 file under fixtures/input/contract/part3/ and
    validates it against the vendored schema: the new value must not be a failure there, and the native file must
    still be refused by part5.io as documented."""
    shutil.copytree(ROOT / "contracts", tmp_path / "contracts")
    view4 = write(tmp_path, "fixtures/input/contract/part3/view-part4/skeleton.json", with_up_source(VIEW4, up_source))
    native = write(tmp_path, "fixtures/input/contract/part3/native/skeleton.json", with_up_source(NATIVE, up_source))
    run = contract._Run(tmp_path)
    run.fixture(view4)
    run.fixture(native)
    assert run.failures == []
    assert run.files == 2 and run.loaded == 1 and run.rejected == 1
    assert dict(run.by_schema) == {"part3/skeleton-part4": 1, "input-skeleton": 1, "part3/skeleton": 1}


@pytest.mark.parametrize("up_source", NEW_VALUES)
def test_part5_doctor_accepts_an_expected_skeleton_with_the_new_up_source_and_refuses_the_native_one(
        tmp_path, capsys, up_source):
    view4 = write(tmp_path, "new-view4.json", with_up_source(VIEW4, up_source))
    native = write(tmp_path, "new-native.json", with_up_source(NATIVE, up_source))
    code = cli.main(["doctor", str(view4), "--for", "part5"])
    out = capsys.readouterr().out
    assert code == 0 and "simon.skeleton.v1 (Part 3 --view part4 skeleton.json)" in out
    code = cli.main(["doctor", str(native), "--for", "part5"])
    captured = capsys.readouterr()
    assert code == 1 and "--view part5" in captured.out + captured.err


@pytest.mark.parametrize("up_source", NEW_VALUES)
def test_analyse_gives_the_same_faults_and_score_whatever_the_expected_clips_up_source(tmp_path, up_source):
    """The claim CONTRACT.md makes: `analyse` reads the clip, not `frame.up_source`."""
    follower = P3 / "followers/squat_front_correct/skeleton.json"
    floor = write(tmp_path, "new-view4.json", with_up_source(VIEW4, up_source))
    got = {}
    for name, expected in (("plain", VIEW4), ("floor", floor)):
        out = tmp_path / f"{name}.json"
        assert cli.main(["analyse", "--expected", str(expected), "--follower", str(follower), "--out", str(out)]) == 0
        got[name] = json.loads(out.read_text())
    assert got["floor"]["faults"] == got["plain"]["faults"]
    assert got["floor"]["score"] == got["plain"]["score"]
    assert got["floor"]["diagnostics"] == got["plain"]["diagnostics"]
