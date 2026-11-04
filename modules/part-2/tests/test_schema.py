"""part2/schema.py: the validators, ContractError, the finite-number walk and the JSON writer."""
import copy
import json

import pytest
from test_canonical import _body3d

from part2 import schema
from part2.canonical import convert
from part2.schema import ContractError, validate_pose3d, validate_tracks

NAN, INF = float("nan"), float("inf")


def _pose():
    return convert(_body3d([0, 10]))[0]


def _tracks():
    person = {"id": 3, "bbox": [1.0, 2.0, 3.0, 4.0], "mask_rle": {"size": [4, 5], "counts": "abc"}, "confidence": 0.5}
    return {"frames": [{"frame": 0, "people": [person]}, {"frame": 2, "people": []}]}


def test_contract_error_is_a_value_error_with_path_and_message():
    with pytest.raises(ContractError) as e:
        validate_pose3d({"frames": [{"frame": 0, "people": []}]})
    assert isinstance(e.value, ValueError)
    assert (e.value.path, e.value.msg) == ("pose3d.frames[0].t_ms", "expected a finite number")
    assert str(e.value) == "pose3d.frames[0].t_ms: expected a finite number"


@pytest.mark.parametrize("mutate, path", [
    (lambda d: d.pop("frames"), "pose3d.frames"),
    (lambda d: d["frames"][0].update(frame=True), "pose3d.frames[0].frame"),
    (lambda d: d["frames"][0].update(frame="0"), "pose3d.frames[0].frame"),
    (lambda d: d["frames"][0].update(people={}), "pose3d.frames[0].people"),
    (lambda d: d["frames"][0]["people"][0].update(id=1.5), "pose3d.frames[0].people[0].id"),
    (lambda d: d["frames"][0]["people"][0].pop("joints"), "pose3d.frames[0].people[0].joints"),
    (lambda d: d["frames"][0]["people"][0]["joints"].pop("nose"), "pose3d.frames[0].people[0].joints"),
    (lambda d: d["frames"][0]["people"][0]["joints"]["nose"].pop("z"), "joints.nose.z"),
    (lambda d: d["frames"][0]["people"][0]["joints"]["nose"].update(conf=-0.1), "joints.nose.conf"),
    (lambda d: d["frames"][1].update(frame=0), "pose3d.frames[].frame"),
])
def test_validate_pose3d_rules_name_the_path(mutate, path):
    doc = copy.deepcopy(_pose())
    mutate(doc)
    with pytest.raises(ContractError) as e:
        validate_pose3d(doc)
    assert path in str(e.value)


def test_validate_pose3d_accepts_string_ids_and_empty_frames():
    doc = _pose()
    doc["frames"][0]["people"][0]["id"] = "a"
    doc["frames"][1]["people"] = []
    validate_pose3d(doc)
    validate_pose3d({"frames": []})


@pytest.mark.parametrize("key, value, ok", [
    ("mirrored", True, True), ("mirrored", False, True), ("mirrored", "yes", False), ("mirrored", 1, False),
    ("fps", 30, True), ("fps", 0, False), ("fps", -5, False), ("fps", NAN, False), ("fps", INF, False), ("fps", "30", False),
    ("t0_pts_ms", 0, True), ("t0_pts_ms", 2500.5, True), ("t0_pts_ms", NAN, False), ("t0_pts_ms", None, False),
    ("provenance", {}, True), ("provenance", [], False), ("extra", "anything", True),
])
def test_validate_pose3d_optional_top_level_keys(key, value, ok):
    doc = {**_pose(), key: value}
    if ok:
        validate_pose3d(doc)
    else:
        with pytest.raises(ContractError, match=f"pose3d.{key}"):
            validate_pose3d(doc)


@pytest.mark.parametrize("key, value, ok", [
    ("t0_pts_ms", 12.5, True), ("t0_pts_ms", INF, False), ("provenance", {"tracker": "x"}, True), ("provenance", "x", False)])
def test_validate_tracks_optional_top_level_keys(key, value, ok):
    doc = {**_tracks(), key: value}
    if ok:
        validate_tracks(doc)
    else:
        with pytest.raises(ContractError, match=f"tracks.{key}"):
            validate_tracks(doc)


@pytest.mark.parametrize("mutate, path", [
    (lambda d: d["frames"][0]["people"][0].pop("bbox"), "people[0].bbox"),
    (lambda d: d["frames"][0]["people"][0].update(bbox=[1, 2, 3]), "people[0].bbox"),
    (lambda d: d["frames"][0]["people"][0].update(bbox=[1, 2, -3, 4]), "people[0].bbox"),
    (lambda d: d["frames"][0]["people"][0].update(bbox=[1, 2, 3, NAN]), "people[0].bbox"),
    (lambda d: d["frames"][0]["people"][0].update(bbox=[1, 2, INF, 4]), "people[0].bbox"),
    (lambda d: d["frames"][0]["people"][0]["mask_rle"].update(size=[0, 5]), "people[0].mask_rle"),
    (lambda d: d["frames"][0]["people"][0]["mask_rle"].update(counts=""), "people[0].mask_rle"),
    (lambda d: d["frames"][0]["people"][0].update(confidence=NAN), "people[0].confidence"),
    (lambda d: d["frames"][0]["people"][0].update(confidence=1.2), "people[0].confidence"),
    (lambda d: d["frames"][0]["people"].append(copy.deepcopy(d["frames"][0]["people"][0])), "duplicate ids"),
    (lambda d: d["frames"][1].update(frame=0), "tracks.frames[].frame"),
])
def test_validate_tracks_rules_name_the_path(mutate, path):
    doc = _tracks()
    mutate(doc)
    with pytest.raises(ContractError) as e:
        validate_tracks(doc)
    assert path in str(e.value)


def test_optional_top_reads_the_doc_and_extras_override_it():
    doc = {"frames": [], "mirrored": False, "t0_pts_ms": 5, "other": 1}
    assert schema.optional_top(doc) == {"mirrored": False, "t0_pts_ms": 5}
    got = schema.optional_top(doc, {"mirrored": True, "provenance": {"a": 1}, "t0_pts_ms": None, "frames": ["no"], "x": 1})
    assert got == {"mirrored": True, "t0_pts_ms": 5, "provenance": {"a": 1}}


def test_check_finite_names_the_path_of_the_first_bad_number():
    schema.check_finite({"a": [1, 2.5, {"b": True, "c": None}], "d": "x"}, "doc")
    with pytest.raises(ContractError) as e:
        schema.check_finite({"a": [1, {"b": [0, INF]}]}, "doc")
    assert (e.value.path, e.value.msg) == ("doc.a[1].b[1]", "NaN or infinity is not allowed")
    with pytest.raises(ContractError, match=r"doc\.n: number too large for a double"):
        schema.check_finite({"n": 10 ** 400}, "doc")


@pytest.mark.parametrize("value, ok", [(1, True), (1.5, True), (0, True), (True, False), (None, False), ("1", False),
                                       (NAN, False), (INF, False), (-INF, False), (10 ** 400, False), (10 ** 20, True)])
def test_is_number(value, ok):
    assert schema.is_number(value) is ok


def test_write_json_writes_compact_json_and_returns_the_path(tmp_path):
    path = schema.write_json(tmp_path / "a.json", {"x": [1, 2.5]})
    assert path == tmp_path / "a.json" and path.read_text() == '{"x": [1, 2.5]}'
    assert json.loads(schema.write_json(tmp_path / "b.json", {"x": 1}, indent=1).read_text()) == {"x": 1}


@pytest.mark.parametrize("bad", [NAN, INF, -INF])
def test_write_json_refuses_nan_and_infinity_before_touching_the_file(tmp_path, bad):
    target = tmp_path / "pose3d.json"
    target.write_text("old")
    with pytest.raises(ContractError, match=r"pose3d\.json\.frames\[1\]: NaN or infinity"):
        schema.write_json(target, {"frames": [0, bad]})
    assert target.read_text() == "old"
