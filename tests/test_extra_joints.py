"""TICKET-043 foot points: pose3d.json's optional per-person `extra_joints` (docs/specs/integration-contract.md
AC-C12 to AC-C15). SAM 3D Body, RTMPose and the 2D model are faked here; no GPU, no weights."""
import json

import numpy as np
import pytest
from test_canonical import BODY, K, _yaw
from test_cpu_rtm import Fake2D, _frames
from test_refine import T, Ctx, camera_joints, kp_for

from part2 import body3d, canonical, contract, doctor, output_steps, provenance, refine
from part2.backends import cpu_rtm
from part2.joints import CANONICAL, EXTRA, MHR70, MHR70_EXTRA
from part2.lifters import project
from part2.multi3d import write_pose_streams
from part2.refine import focal, kp2d_fit, temporal
from part2.schema import ContractError, validate_pose3d

# The six foot points of test_canonical.BODY in the canonical frame (x subject's left, y up, z anterior), metres.
FEET = {"left_big_toe": [0.12, -0.95, 0.15], "left_small_toe": [0.17, -0.95, 0.11],
        "left_heel": [0.1, -0.97, -0.08], "right_big_toe": [-0.12, -0.95, 0.15],
        "right_small_toe": [-0.17, -0.95, 0.11], "right_heel": [-0.1, -0.97, -0.08]}
FILLER = 9.0  # every other MHR70 row: a foot point read from a wrong row would land metres away


def sam_output(deg=30.0, t=(0.1, 0.3, 4.0), feet=None) -> dict:
    """A fake SAM 3D Body output for one person: 70 MHR keypoints relative to pred_cam_t (the 17 joints and six foot
    points `feet`, FEET by default, at their MHR70 rows, FILLER elsewhere), 2D the projection of the camera-space points."""
    rows = np.full((70, 3), FILLER)
    for name, i in {**MHR70, **MHR70_EXTRA}.items():
        rows[i] = (BODY | (feet or FEET))[name]
    rel = rows @ _yaw(deg).T
    uv = body3d.project(rel + np.asarray(t), K)
    return {"pred_keypoints_3d": rel, "pred_cam_t": np.asarray(t, float), "pred_keypoints_2d": uv,
            "bbox": np.array([500.0, 100.0, 800.0, 700.0])}


def gpu_body3d(yaws, t=(0.1, 0.3, 4.0), prov=None) -> dict:
    """A body3d document as the gpu backend writes it, one person per frame through body3d._person."""
    frames = [{"frame": i, "t_ms": i * 200.0, "people": [body3d._person(0, sam_output(d, t), np.array(K))]}
              for i, d in enumerate(yaws)]
    doc = {"model": "sam-3d-body-dinov3", "camera_frame": "opencv", "K": K, "image_size": [1280, 720], "frames": frames}
    return {**doc, "provenance": prov} if prov else doc


def gpu_block():
    return provenance.block("gpu", None, None, [], [], commit="c" * 40)


def xyz(point) -> list:
    return [point[k] for k in "xyz"]


# --- AC-C12: the gpu backend writes the six points through the joints' canonical transform -----------------------

def test_the_gpu_person_carries_the_six_foot_points_from_mhr70_rows_15_to_20():
    o = sam_output()
    p = body3d._person(0, o, np.array(K))
    cam = o["pred_keypoints_3d"] + o["pred_cam_t"]
    assert list(p["extra_kp3d_cam"]) == EXTRA == list(p["extra_kp2d"])
    for name, row in MHR70_EXTRA.items():
        np.testing.assert_allclose(p["extra_kp3d_cam"][name], cam[row], atol=1e-4)
        np.testing.assert_allclose(p["extra_kp2d"][name], o["pred_keypoints_2d"][row], atol=1e-2)
    assert p["kp3d_cam"] == {j: np.round(cam[MHR70[j]], 4).tolist() for j in CANONICAL}  # the 17 joints unchanged
    assert p["reproj_self_px"] < 0.01  # still the 17 joints' own gap


@pytest.mark.parametrize("deg", [0, 90, -90, 180, 35])
def test_the_feet_are_canonicalised_with_the_joints_from_any_view(deg):
    pose3d, _ = canonical.convert(gpu_body3d([deg], prov=gpu_block()))
    person = pose3d["frames"][0]["people"][0]
    assert list(person["joints"]) == CANONICAL and list(person["extra_joints"]) == EXTRA
    np.testing.assert_allclose([xyz(person["extra_joints"][n]) for n in EXTRA], [FEET[n] for n in EXTRA], atol=1e-3)
    np.testing.assert_allclose([xyz(person["joints"][j]) for j in CANONICAL], [BODY[j] for j in CANONICAL], atol=1e-3)
    assert all(p["conf"] == 1.0 for p in person["extra_joints"].values())
    assert pose3d["provenance"]["extra_joints"] == EXTRA  # AC-C14
    provenance.validate(pose3d["provenance"])
    contract.validate(pose3d, "pose3d")
    contract.validate_part3(pose3d)  # AC-C13: Part 3's consumer schema allows the new person key


def test_feet_outside_the_image_are_written_with_the_low_confidence_of_any_outside_joint():
    pose3d, _ = canonical.convert(gpu_body3d([0], t=(0.1, 1.2, 2.0)))  # the subject's lower legs below the image
    person = pose3d["frames"][0]["people"][0]
    assert {p["conf"] for p in person["extra_joints"].values()} == {canonical.OUTSIDE_CONF}
    assert person["joints"]["left_ankle"]["conf"] == canonical.OUTSIDE_CONF and person["joints"]["nose"]["conf"] == 1.0
    np.testing.assert_allclose(xyz(person["extra_joints"]["left_heel"]), FEET["left_heel"], atol=1e-3)


def test_a_body3d_person_without_foot_points_writes_no_extra_joints_and_no_provenance_line():
    doc = gpu_body3d([0, 10], prov=gpu_block())
    for f in doc["frames"]:
        for p in f["people"]:
            del p["extra_kp3d_cam"], p["extra_kp2d"]
    pose3d, _ = canonical.convert(doc)
    assert all("extra_joints" not in p for f in pose3d["frames"] for p in f["people"])
    assert "extra_joints" not in pose3d["provenance"]


# --- AC-C12: the cpu backend (RTMPose-x, 17 points) writes none -----------------------------------------------------

def test_the_cpu_backend_writes_no_extra_joints_and_its_provenance_names_none(tmp_path):
    backend = cpu_rtm.Backend("fixed-bones")
    doc = backend.estimate(_frames(tmp_path, 4), tmp_path / "body3d.json", model2d=Fake2D(4))
    keys = {"id", "bbox", "kp3d_cam", "kp2d", "reproj_self_px"}
    assert all(set(p) == keys for f in doc["frames"] for p in f["people"])
    pose_path, _ = canonical.write(tmp_path / "body3d.json", tmp_path,
                                   extras=output_steps.pose_extras({}, False, backend))
    pose3d = json.loads(pose_path.read_text())
    assert all("extra_joints" not in p for f in pose3d["frames"] for p in f["people"])
    assert pose3d["provenance"]["backend"] == "cpu" and "extra_joints" not in pose3d["provenance"]


# --- the refine rungs and smoothing keep the feet with the refined ankles ----------------------------------------

def feet_cam(deg=30.0, shift=(0.0, 0.0, 0.0)) -> np.ndarray:
    return np.array([FEET[n] for n in EXTRA]) @ _yaw(deg).T + T + np.asarray(shift)


def footed(X, F, pid=0) -> dict:
    """A body3d person (test_refine's shape) with joints X and foot points F, both camera space."""
    return {"id": pid, "bbox": [500.0, 100.0, 300.0, 600.0], "reproj_self_px": 0.0,
            "kp3d_cam": {j: x.tolist() for j, x in zip(CANONICAL, X)},
            "kp2d": {j: x.tolist() for j, x in zip(CANONICAL, project(X, K))},
            "extra_kp3d_cam": {n: x.tolist() for n, x in zip(EXTRA, F)},
            "extra_kp2d": {n: x.tolist() for n, x in zip(EXTRA, project(F, K))}}


def doc_with_feet(pairs) -> dict:
    return {"model": "test", "camera_frame": "opencv", "K": K, "image_size": [1280, 720],
            "frames": [{"frame": i, "t_ms": i * 200.0, "people": [footed(X, F)]} for i, (X, F) in enumerate(pairs)]}


def assert_feet_follow_ankles(before: dict, after: dict, atol=2e-4):
    """Every foot point moved by exactly its own ankle's displacement; extra_kp2d is the new points' projection."""
    for name in EXTRA:
        ankle = name.split("_")[0] + "_ankle"
        moved = np.subtract(after["extra_kp3d_cam"][name], before["extra_kp3d_cam"][name])
        np.testing.assert_allclose(moved, np.subtract(after["kp3d_cam"][ankle], before["kp3d_cam"][ankle]), atol=atol)
    F = np.array([after["extra_kp3d_cam"][n] for n in EXTRA])
    np.testing.assert_allclose([after["extra_kp2d"][n] for n in EXTRA], project(F, K), atol=0.01)


def test_kp2d_fit_moves_each_foot_point_with_its_own_ankle():
    doc = doc_with_feet([(camera_joints(30), feet_cam(30))])
    target = project(camera_joints(30, shift=(0.04, -0.02, 0.0)), K)
    out = kp2d_fit.apply(doc, Ctx(kp_for(doc, {0: target})))
    before, after = doc["frames"][0]["people"][0], out["frames"][0]["people"][0]
    left = np.subtract(after["kp3d_cam"]["left_ankle"], before["kp3d_cam"]["left_ankle"])
    assert np.linalg.norm(left) > 0.005  # the fit did move the ankle
    assert_feet_follow_ankles(before, after)


def test_both_rungs_write_a_person_through_the_one_shared_with_joints():
    assert kp2d_fit.with_joints is refine.with_joints is temporal.with_joints  # R4: one function, not two copies
    person = footed(camera_joints(30), feet_cam(30))
    moved = camera_joints(30, shift=(0.0123456, -0.0234567, 0.0345678))
    out = refine.with_joints(person, moved, K)
    X = np.round(moved, 4)
    assert out["kp3d_cam"] == {j: x.tolist() for j, x in zip(CANONICAL, X)}
    assert out["kp2d"] == {j: x.tolist() for j, x in zip(CANONICAL, np.round(project(X, K), 2))}
    assert out["reproj_self_px"] == 0.0 and out["id"] == person["id"] and out["bbox"] == person["bbox"]
    assert_feet_follow_ankles(person, out)
    plain = {k: v for k, v in person.items() if not k.startswith("extra_")}
    bare = refine.with_joints(plain, moved, K)
    assert set(bare) == set(plain) and bare["kp3d_cam"] == out["kp3d_cam"]  # no foot points in, none out


def test_kp2d_fit_leaves_a_person_without_feet_without_them():
    doc = doc_with_feet([(camera_joints(30), feet_cam(30))])
    for key in ("extra_kp3d_cam", "extra_kp2d"):
        del doc["frames"][0]["people"][0][key]
    out = kp2d_fit.apply(doc, Ctx(kp_for(doc, {0: project(camera_joints(30, shift=(0.04, 0, 0)), K)})))
    assert "extra_kp3d_cam" not in out["frames"][0]["people"][0]


def test_temporal_moves_each_foot_point_with_its_own_smoothed_ankle():
    rng = np.random.default_rng(1)
    pairs = []
    for i in range(6):
        jitter = rng.normal(0, 0.01, 3)
        pairs.append((camera_joints(30, shift=(0.02 * i, 0, 0)) + rng.normal(0, 0.01, (17, 3)), feet_cam(30) + jitter))
    doc = doc_with_feet(pairs)
    out = temporal.apply(doc)
    for f0, f1 in zip(doc["frames"], out["frames"]):
        assert_feet_follow_ankles(f0["people"][0], f1["people"][0])


def test_one_euro_smoothing_moves_each_foot_point_with_its_own_ankle():
    rng = np.random.default_rng(2)
    doc = doc_with_feet([(camera_joints(30) + rng.normal(0, 0.01, (17, 3)), feet_cam(30)) for _ in range(5)])
    smoothed = canonical.smooth_tracks(doc["frames"])
    for f0, f1 in zip(doc["frames"], smoothed):
        p0, p1 = f0["people"][0], f1["people"][0]
        for name in EXTRA:
            ankle = name.split("_")[0] + "_ankle"
            np.testing.assert_allclose(np.subtract(p1["extra_kp3d_cam"][name], p1["kp3d_cam"][ankle]),
                                       np.subtract(p0["extra_kp3d_cam"][name], p0["kp3d_cam"][ankle]), atol=1e-9)
        assert p1["extra_kp2d"] == p0["extra_kp2d"]  # 2D left as measured, as for the joints


def test_focal_takes_the_feet_of_the_chosen_run(tmp_path, monkeypatch):
    def estimate(frames_dir, out_path, boxes=None, estimator=None):  # each run's feet name the focal it ran at
        Kc = estimator.fov_estimator.get_cam_intrinsics(None).tolist()
        F = feet_cam(20) + [Kc[0][0] / 1e6, 0, 0]
        return {**doc_with_feet([(camera_joints(20), F)] * 2), "K": Kc}

    class Sam:
        def load(self):
            return object()

    monkeypatch.setattr(body3d, "estimate", estimate)
    doc = doc_with_feet([(camera_joints(20), feet_cam(20))] * 2)
    kp = kp_for(doc, {i: project(camera_joints(20), focal.scaled_K(K, 1.2)) for i in range(2)})
    out = focal.apply(doc, refine.Context(tmp_path, keypoints=kp, backend=Sam(), work_dir=tmp_path),
                      {"SCALES": (0.85, 1.0, 1.2)})
    assert out["focal_fit"]["scale"] == 1.2
    heel = out["frames"][0]["people"][0]["extra_kp3d_cam"]["left_heel"][0]
    assert heel == pytest.approx(feet_cam(20)[EXTRA.index("left_heel")][0] + 1200.0 / 1e6)


# --- AC-C13: the schema and the validators -----------------------------------------------------------------------

def _pose3d(**kw) -> dict:
    return canonical.convert(gpu_body3d([0, 10], **kw))[0]


def test_the_schema_accepts_files_with_and_without_extra_joints_and_part3_still_does():
    with_feet = _pose3d(prov=gpu_block())
    without = json.loads(json.dumps(with_feet))
    for f in without["frames"]:
        for p in f["people"]:
            del p["extra_joints"]
    for doc in (with_feet, without):
        contract.validate(doc, "pose3d")
        validate_pose3d(doc)
        contract.validate_part3(doc)


def test_any_subset_of_the_six_names_is_valid():
    doc = _pose3d()
    first = doc["frames"][0]["people"][0]
    first["extra_joints"] = {"left_heel": first["extra_joints"]["left_heel"]}
    doc["frames"][1]["people"][0]["extra_joints"] = {}
    contract.validate(doc, "pose3d")
    validate_pose3d(doc)


@pytest.mark.parametrize("mutate, where", [
    (lambda e: e.update(left_toe=dict(e["left_heel"])), "extra_joints"),          # an unknown name
    (lambda e: e.update(left_heel=None), "extra_joints.left_heel"),                 # null, as in joints: never
    (lambda e: e["right_heel"].update(conf=1.5), "extra_joints.right_heel.conf"),   # conf outside [0, 1]
    (lambda e: e["left_big_toe"].pop("z"), "extra_joints.left_big_toe.z"),          # a missing coordinate
    (lambda e: e["left_big_toe"].update(x="0.1"), "extra_joints.left_big_toe.x"),   # not a number
    (lambda e: e["left_big_toe"].update(x=float("nan")), "extra_joints.left_big_toe.x"),     # NaN
    (lambda e: e["right_small_toe"].update(z=float("inf")), "extra_joints.right_small_toe.z"),  # infinity
    (lambda e: e["left_heel"].update(y=float("-inf")), "extra_joints.left_heel.y"),         # minus infinity
    (lambda e: e["right_heel"].update(conf=float("nan")), "extra_joints.right_heel.conf"),   # NaN conf
])
def test_the_validators_reject_a_broken_extra_joints_object_and_name_the_path(mutate, where):
    doc = _pose3d()
    mutate(doc["frames"][0]["people"][0]["extra_joints"])
    for check in (lambda d: contract.validate(d, "pose3d"), validate_pose3d):
        with pytest.raises(ContractError) as e:
            check(doc)
        assert e.value.path.startswith(f"pose3d.frames[0].people[0].{where}")


def test_extra_joints_must_be_an_object():
    doc = _pose3d()
    doc["frames"][0]["people"][0]["extra_joints"] = [1, 2]
    with pytest.raises(ContractError, match="extra_joints"):
        contract.validate(doc, "pose3d")
    with pytest.raises(ContractError, match="extra_joints"):
        validate_pose3d(doc)


def test_the_schema_adds_extra_joints_as_optional_with_no_version_change():
    s = contract.own_schema("pose3d")
    assert s["x-simon-version"] == "part2.pose3d/2026-10-28"
    ex = s["$defs"]["extra_joints"]
    assert ex["additionalProperties"] is False and "required" not in ex and list(ex["properties"]) == EXTRA
    assert s["$defs"]["person"]["required"] == ["id", "joints"]
    j = s["$defs"]["joints"]
    assert j["additionalProperties"] is False and set(j["properties"]) == set(CANONICAL)


# --- AC-C14: provenance names what the file holds ------------------------------------------------------------------

def test_provenance_extra_joints_accepts_the_six_names_and_rejects_any_other_string():
    item = contract.own_schema("pose3d")["$defs"]["provenance"]["properties"]["extra_joints"]["items"]
    assert item == {"type": "string", "pattern": "^(left|right)_(big_toe|small_toe|heel)$"}
    doc = _pose3d(prov=gpu_block())
    assert doc["provenance"]["extra_joints"] == EXTRA
    contract.validate(doc, "pose3d")
    for bad in ("left_toe", "middle_heel", "left_ankle", "LEFT_HEEL", "left_heel ", "heel", "", "left_big_toe_2", "a left_heel"):
        doc["provenance"]["extra_joints"] = [*EXTRA[:2], bad]
        with pytest.raises(ContractError) as e:
            contract.validate(doc, "pose3d")
        assert e.value.path == "pose3d.provenance.extra_joints[2]"
    doc["provenance"]["extra_joints"] = [EXTRA[0], 3]  # still a string
    with pytest.raises(ContractError, match=r"provenance\.extra_joints\[1\]: expected string"):
        contract.validate(doc, "pose3d")
    doc["provenance"]["extra_joints"] = []  # a list may be empty: the key is simply absent in a file written without feet
    contract.validate(doc, "pose3d")


def test_a_provenance_block_copied_from_a_file_with_feet_loses_the_line_when_this_file_has_none():
    doc = {"frames": [{"frame": 0, "t_ms": 0.0, "people": []}], "provenance": {**gpu_block(), "extra_joints": EXTRA}}
    assert "extra_joints" not in canonical.with_extra_provenance(doc)["provenance"]
    assert canonical.with_extra_provenance({"frames": []}) == {"frames": []}  # no block: nothing added


def test_each_per_person_file_names_only_the_feet_of_its_own_person(tmp_path):
    doc = gpu_body3d([0, 30])
    for f in doc["frames"]:  # a second person without feet, 1.5 m to the side
        p0 = f["people"][0]
        f["people"].append({"id": 7, "bbox": [10, 10, 5, 5], "reproj_self_px": 0.0,
                            "kp3d_cam": {j: (np.array(v) + [1.5, 0, 0]).tolist() for j, v in p0["kp3d_cam"].items()},
                            "kp2d": {j: [v[0] + 50, v[1]] for j, v in p0["kp2d"].items()}})
    write_pose_streams(doc, tmp_path, extras={"provenance": gpu_block()})
    read = {f.name: json.loads(f.read_text()) for f in tmp_path.glob("pose3d*.json")}
    assert read["pose3d.json"]["provenance"]["extra_joints"] == EXTRA
    assert read["pose3d_person_0.json"]["provenance"]["extra_joints"] == EXTRA
    assert "extra_joints" not in read["pose3d_person_7.json"]["provenance"]
    for d in read.values():
        contract.validate(d, "pose3d")


def test_two_people_with_different_feet_keep_their_own_values_in_every_file(tmp_path):
    feet_7 = {n: [p[0], p[1] + 0.01, p[2] * 1.4] for n, p in FEET.items()}  # longer feet, a hand's width apart
    doc = gpu_body3d([0, 30])  # person 0: FEET
    for f, deg in zip(doc["frames"], (60, 100)):  # person 7: feet_7 and no right heel, other yaw, 1.4 m to the side
        p7 = body3d._person(7, sam_output(deg, t=(1.5, 0.3, 4.5), feet=feet_7), np.array(K))
        del p7["extra_kp3d_cam"]["right_heel"], p7["extra_kp2d"]["right_heel"]
        f["people"].append(p7)
    write_pose_streams(doc, tmp_path, extras={"provenance": gpu_block()})
    read = {f.name: json.loads(f.read_text()) for f in tmp_path.glob("pose3d*.json")}
    assert sorted(read) == ["pose3d.json", "pose3d_person_0.json", "pose3d_person_7.json"]
    want = {0: FEET, 7: {n: v for n, v in feet_7.items() if n != "right_heel"}}
    for name, ids in (("pose3d.json", (0, 7)), ("pose3d_person_0.json", (0,)), ("pose3d_person_7.json", (7,))):
        frames = read[name]["frames"]
        assert len(frames) == 2 and [[p["id"] for p in f["people"]] for f in frames] == [list(ids)] * 2
        for f in frames:
            for p in f["people"]:
                assert list(p["extra_joints"]) == [n for n in EXTRA if n in want[p["id"]]]
                np.testing.assert_allclose([xyz(q) for q in p["extra_joints"].values()],
                                           [want[p["id"]][n] for n in p["extra_joints"]], atol=1e-3)
        contract.validate(read[name], "pose3d")
    for pid, name in ((0, "pose3d_person_0.json"), (7, "pose3d_person_7.json")):  # a per-person file is the combined one's person
        combined = [p for f in read["pose3d.json"]["frames"] for p in f["people"] if p["id"] == pid]
        assert combined == [p for f in read[name]["frames"] for p in f["people"]]
    first = read["pose3d.json"]["frames"][0]["people"]
    assert first[0]["extra_joints"]["left_heel"] != first[1]["extra_joints"]["left_heel"]  # not one person's feet twice
    assert first[0]["extra_joints"]["left_big_toe"]["z"] == pytest.approx(0.15, abs=1e-3)
    assert first[1]["extra_joints"]["left_big_toe"]["z"] == pytest.approx(0.21, abs=1e-3)
    prov = {name: d["provenance"]["extra_joints"] for name, d in read.items()}
    assert prov == {"pose3d.json": EXTRA, "pose3d_person_0.json": EXTRA,
                    "pose3d_person_7.json": [n for n in EXTRA if n != "right_heel"]}


# --- AC-C15: doctor mentions the feet and keeps every verdict ----------------------------------------------------

def test_doctor_names_the_extra_joints_and_keeps_every_verdict(tmp_path):
    with_feet = _pose3d(prov=gpu_block())
    without = json.loads(json.dumps(with_feet))
    for f in without["frames"]:
        for p in f["people"]:
            del p["extra_joints"]
    a, b = tmp_path / "feet.json", tmp_path / "plain.json"
    a.write_text(json.dumps(with_feet))
    b.write_text(json.dumps(without))
    ra, rb = doctor.diagnose(a), doctor.diagnose(b)
    assert ra["findings"] == rb["findings"] and ra["exit"] == rb["exit"] == 0 and ra["schema_error"] is None
    for consumer in ("part3", "part5", "part6"):
        assert doctor.diagnose(a, consumer)["exit"] == doctor.diagnose(b, consumer)["exit"]
    assert ra["extra_joints"] == {"names": EXTRA, "person_frames": 2, "of": 2} and rb["extra_joints"] is None
    line = f"extra joints: {', '.join(EXTRA)} on 2 of 2 person-frames (optional extra_joints beside the 17 joints)"
    assert line in doctor.render(ra) and not any(x.startswith("extra joints") for x in doctor.render(rb))


def test_doctor_counts_the_person_frames_that_carry_feet(tmp_path, capsys):
    doc = _pose3d()
    doc["frames"][1]["people"][0]["extra_joints"] = {}
    path = tmp_path / "pose3d.json"
    path.write_text(json.dumps(doc))
    assert doctor.command(path, "part3", as_json=True) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["extra_joints"] == {"names": EXTRA, "person_frames": 1, "of": 2}
