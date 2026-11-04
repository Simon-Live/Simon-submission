"""TICKET-055: the phone's gravity as the true up (part2/gravity.py, docs/specs/gravity-up.md).

The fixture is the standing body of test_canonical.py seen by a camera pitched and rolled by known angles. Part 2's
canonical frame assumes a level camera, so its y is the camera's up; the written `up` must be the body's own vertical,
recovered here independently by fitting the known body to the canonical joints.
"""
import json

import numpy as np
import pytest

from part2 import cli, gravity
from part2.body3d import project
from part2.canonical import convert, write_docs
from part2.joints import CANONICAL
from part2.schema import ContractError, validate_pose3d
from test_canonical import BODY, K, _yaw


def rot_x(deg):
    a = np.radians(deg)
    return np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])


def rot_z(deg):
    a = np.radians(deg)
    return np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])


def tilted_body3d(pitch, roll=0.0, yaws=(0, 30, 60), ids=(0,), t=(0.1, 0.3, 4.0)):
    """body3d of the standing BODY turned by `yaws`, seen by a camera pitched about its x and rolled about its z."""
    tilt = rot_z(roll) @ rot_x(pitch)
    can = np.array([BODY[j] for j in CANONICAL])
    frames = []
    for i, deg in enumerate(yaws):
        people = []
        for k, pid in enumerate(ids):
            cam = (can @ _yaw(deg).T + np.array(t) + np.array([0.9 * k, 0, 0])) @ tilt.T
            uv = project(cam, K)
            people.append({"id": pid, "bbox": [0, 0, 1, 1], "kp3d_cam": {j: p.tolist() for j, p in zip(CANONICAL, cam)},
                           "kp2d": {j: q.tolist() for j, q in zip(CANONICAL, uv)}})
        frames.append({"frame": i, "t_ms": i * 33.3, "people": people})
    up_camera = tilt @ np.array([0.0, -1.0, 0.0])
    return {"camera_frame": "opencv", "K": K, "image_size": [1280, 720], "frames": frames}, up_camera


def gravity_doc(up_vec, **over):
    doc = {"schema": "simon.gravity/1", "frame": "opencv", "up": list(up_vec), "t_ms": [0, 2000],
           "samples": 120, "source": "devicemotion"}
    doc.update(over)
    return doc


def body_vertical_in(joints):
    """The BODY's own +y expressed in these canonical joints (Kabsch fit of BODY onto them)."""
    A = np.array([BODY[j] for j in CANONICAL], float)
    B = np.array([[joints[j][k] for k in "xyz"] for j in CANONICAL], float)
    A0, B0 = A - A.mean(0), B - B.mean(0)
    U, _, Vt = np.linalg.svd(A0.T @ B0)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1, 1, d]) @ U.T
    return R @ np.array([0.0, 1.0, 0.0])


def write_run(tmp_path, body3d):
    pose3d, camera = convert(body3d)
    write_docs(tmp_path, pose3d, camera)
    return tmp_path


@pytest.mark.parametrize("pitch,roll", [(0.0, 0.0), (20.0, 0.0), (-35.0, 0.0), (15.0, 10.0), (0.0, -25.0)])
def test_known_tilt_round_trips_into_each_persons_canonical_up(tmp_path, pitch, roll):
    body3d, up_cam = tilted_body3d(pitch, roll)
    out = write_run(tmp_path, body3d)
    assert gravity.apply(out, gravity.parse(gravity_doc(up_cam))) == [out / "pose3d.json"]
    doc = json.loads((out / "pose3d.json").read_text())
    validate_pose3d(doc)
    block = doc["gravity"]
    assert block["camera_frame"] == "opencv" and block["samples"] == 120 and block["source"] == "devicemotion"
    expected_tilt = np.degrees(np.arccos(np.cos(np.radians(pitch)) * np.cos(np.radians(roll))))
    assert block["tilt_deg"] == pytest.approx(expected_tilt, abs=1e-3)
    for frame in doc["frames"]:
        for person in frame["people"]:
            truth = body_vertical_in(person["joints"])
            np.testing.assert_allclose(person["up"], truth, atol=2e-4)
            assert person["up"][1] == pytest.approx(np.cos(np.radians(expected_tilt)), abs=2e-4)


def test_level_camera_up_is_the_canonical_y(tmp_path):
    body3d, up_cam = tilted_body3d(0.0)
    out = write_run(tmp_path, body3d)
    gravity.apply(out, gravity.parse(gravity_doc(up_cam)))
    doc = json.loads((out / "pose3d.json").read_text())
    assert doc["gravity"]["tilt_deg"] == 0.0
    assert all(p["up"] == [0.0, 1.0, 0.0] for f in doc["frames"] for p in f["people"])


def test_without_gravity_nothing_is_touched(tmp_path):
    out = write_run(tmp_path, tilted_body3d(20.0)[0])
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    assert gravity.apply(out, None) == []
    assert gravity.load(None) is None
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before


def test_every_person_stream_gets_its_own_up(tmp_path):
    body3d, up_cam = tilted_body3d(25.0, ids=(3, "b"))
    pose3d, camera = convert(body3d)
    write_docs(tmp_path, pose3d, camera)
    for pid in (3, "b"):
        person_doc = {"frames": [{"frame": f["frame"], "t_ms": f["t_ms"], "people": [p for p in f["people"] if p["id"] == pid]}
                                 for f in pose3d["frames"]]}
        (tmp_path / f"pose3d_person_{pid}.json").write_text(json.dumps(person_doc))
    written = gravity.apply(tmp_path, gravity.parse(gravity_doc(up_cam)), people=[3, "b"])
    assert [p.name for p in written] == ["pose3d.json", "pose3d_person_3.json", "pose3d_person_b.json"]
    for path in written:
        doc = json.loads(path.read_text())
        for frame in doc["frames"]:
            for person in frame["people"]:
                np.testing.assert_allclose(person["up"], body_vertical_in(person["joints"]), atol=2e-4)


def test_unnormalised_input_is_made_unit_length():
    g = gravity.parse(gravity_doc([0.0, -9.81, 0.0]))
    assert g["up_camera"] == [0.0, -1.0, 0.0]


@pytest.mark.parametrize("bad,where", [
    ({"schema": "simon.gravity/2"}, "gravity.schema"),
    ({"frame": "device"}, "gravity.frame"),
    ({"up": [0, 1]}, "gravity.up"),
    ({"up": [0, float("nan"), 0]}, "gravity.up"),
    ({"up": [0, 0, 0]}, "gravity.up"),
    ({"up": [0, True, 0]}, "gravity.up"),
    ({"t_ms": [500, 100]}, "gravity.t_ms"),
    ({"t_ms": [-1, 100]}, "gravity.t_ms"),
    ({"samples": 0}, "gravity.samples"),
    ({"samples": 2.5}, "gravity.samples"),
    ({"source": ""}, "gravity.source"),
    ({"source": "x" * 65}, "gravity.source"),
])
def test_invalid_documents_are_refused(bad, where):
    with pytest.raises(ContractError) as e:
        gravity.parse(gravity_doc([0, -1, 0], **bad))
    assert e.value.path == where


def test_unreadable_file_is_refused(tmp_path):
    (tmp_path / "g.json").write_text("{not json")
    with pytest.raises(ContractError):
        gravity.load(tmp_path / "g.json")
    with pytest.raises(ContractError):
        gravity.load(tmp_path / "missing.json")


def test_run_refuses_a_bad_gravity_file_before_any_work(tmp_path, capsys):
    bad = tmp_path / "g.json"
    bad.write_text(json.dumps({"schema": "simon.gravity/1"}))
    code = cli.main(["run", "--mode", "single", "--backend", "cpu", "--input", str(tmp_path / "no-video.mp4"),
                     "--out", str(tmp_path / "out"), "--gravity", str(bad)])
    assert code == 2
    assert "gravity.frame" in capsys.readouterr().err
    assert not (tmp_path / "out" / "frames").exists()


def test_missing_camera_rotation_is_a_contract_error(tmp_path):
    body3d, up_cam = tilted_body3d(10.0)
    pose3d, camera = convert(body3d)
    camera["frames"][1]["people"] = []
    write_docs(tmp_path, pose3d, camera)
    with pytest.raises(ContractError):
        gravity.apply(tmp_path, gravity.parse(gravity_doc(up_cam)))


@pytest.mark.parametrize("mutate,where", [
    (lambda d: d["gravity"].update(camera_frame="device"), "pose3d.gravity.camera_frame"),
    (lambda d: d["gravity"].update(up_camera=[0, -1]), "pose3d.gravity.up_camera"),
    (lambda d: d["gravity"].update(tilt_deg=181), "pose3d.gravity.tilt_deg"),
    (lambda d: d["gravity"].update(samples=0), "pose3d.gravity.samples"),
    (lambda d: d["frames"][0]["people"][0].update(up=[0, 1]), "pose3d.frames[0].people[0].up"),
])
def test_validator_checks_the_new_keys(tmp_path, mutate, where):
    body3d, up_cam = tilted_body3d(10.0)
    out = write_run(tmp_path, body3d)
    gravity.apply(out, gravity.parse(gravity_doc(up_cam)))
    doc = json.loads((out / "pose3d.json").read_text())
    mutate(doc)
    with pytest.raises(ContractError) as e:
        validate_pose3d(doc)
    assert e.value.path == where


def test_written_file_passes_the_json_schema_and_the_part3_doctor(tmp_path):
    from part2 import contract
    body3d, up_cam = tilted_body3d(30.0)
    out = write_run(tmp_path, body3d)
    gravity.apply(out, gravity.parse(gravity_doc(up_cam)))
    doc = json.loads((out / "pose3d.json").read_text())
    contract.validate(doc, "pose3d")
    assert cli.main(["doctor", str(out / "pose3d.json"), "--for", "part3"]) == 0


def test_a_source_with_a_newline_is_refused_before_anything_is_written(tmp_path):
    body3d, up_cam = tilted_body3d(10.0)
    out = write_run(tmp_path, body3d)
    before = (out / "pose3d.json").read_bytes()
    with pytest.raises(ContractError):
        gravity.apply(out, gravity.parse(gravity_doc(up_cam, source="a\nb")))
    assert (out / "pose3d.json").read_bytes() == before


def test_a_failing_person_file_leaves_pose3d_json_unwritten(tmp_path):
    body3d, up_cam = tilted_body3d(10.0, ids=(3,))
    pose3d, camera = convert(body3d)
    write_docs(tmp_path, pose3d, camera)
    (tmp_path / "pose3d_person_9.json").write_text(json.dumps({"frames": [{"frame": 0, "t_ms": 0, "people": [
        {**pose3d["frames"][0]["people"][0], "id": 9}]}]}))
    before = (tmp_path / "pose3d.json").read_bytes()
    with pytest.raises(ContractError):
        gravity.apply(tmp_path, gravity.parse(gravity_doc(up_cam)), people=[9])
    assert (tmp_path / "pose3d.json").read_bytes() == before


def test_only_the_named_person_files_are_written(tmp_path):
    body3d, up_cam = tilted_body3d(10.0, ids=(3, 4))
    pose3d, camera = convert(body3d)
    write_docs(tmp_path, pose3d, camera)
    for pid in (3, 4):
        doc = {"frames": [{"frame": f["frame"], "t_ms": f["t_ms"], "people": [p for p in f["people"] if p["id"] == pid]}
                          for f in pose3d["frames"]]}
        (tmp_path / f"pose3d_person_{pid}.json").write_text(json.dumps(doc))
    untouched = (tmp_path / "pose3d_person_4.json").read_bytes()
    written = gravity.apply(tmp_path, gravity.parse(gravity_doc(up_cam)), people=[3])
    assert [p.name for p in written] == ["pose3d.json", "pose3d_person_3.json"]
    assert (tmp_path / "pose3d_person_4.json").read_bytes() == untouched


def test_integer_and_string_ids_that_print_alike_are_two_people(tmp_path):
    body3d, up_cam = tilted_body3d(10.0, ids=(3,))
    pose3d, camera = convert(body3d)
    for f in pose3d["frames"]:
        f["people"][0]["id"] = "3"  # camera.json still has the integer 3
    write_docs(tmp_path, pose3d, camera)
    with pytest.raises(ContractError):
        gravity.apply(tmp_path, gravity.parse(gravity_doc(up_cam)))


@pytest.mark.parametrize("mutate,where", [
    (lambda d: d["gravity"].update(up_camera=[0, -2, 0]), "pose3d.gravity.up_camera"),
    (lambda d: d["gravity"].update(t_ms=[500, 100]), "pose3d.gravity.t_ms"),
    (lambda d: d["gravity"].update(t_ms=[-5, 100]), "pose3d.gravity.t_ms"),
    (lambda d: d["gravity"].update(tilt_deg=90.0), "pose3d.gravity.tilt_deg"),
])
def test_validator_checks_the_gravity_values_agree(tmp_path, mutate, where):
    body3d, up_cam = tilted_body3d(10.0)
    out = write_run(tmp_path, body3d)
    gravity.apply(out, gravity.parse(gravity_doc(up_cam)))
    doc = json.loads((out / "pose3d.json").read_text())
    mutate(doc)
    with pytest.raises(ContractError) as e:
        validate_pose3d(doc)
    assert e.value.path == where


def test_check_clip_refuses_a_window_past_the_last_frame_and_allows_slack():
    recs = [{"frame": 0, "t_ms": 0}, {"frame": 1, "t_ms": 5000}]
    gravity.check_clip(gravity.parse(gravity_doc([0, -1, 0], t_ms=[0, 5900])), recs)
    gravity.check_clip(None, recs)
    with pytest.raises(ContractError) as e:
        gravity.check_clip(gravity.parse(gravity_doc([0, -1, 0], t_ms=[0, 6100])), recs)
    assert e.value.path == "gravity.t_ms"
