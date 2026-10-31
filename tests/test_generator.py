"""The synthetic follower generator: knee_caving (ADR-0004), the 9-take grid, the dropout variant (#25,
AC-008), --out, determinism and the Makefile target that makes held-out sets; and --feet (TICKET-040, ASM-013):
planted feet written as Part 2 pose3d side files, the four foot-fault takes per cell, and the proof that no base
take changes."""
import json
import math
import subprocess
import sys
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from part5.io import JOINTS, load_clip
from part5.measures import _ankle_inversion, _foot_rotation, compute

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_dummy_followers as gen  # noqa: E402  (stdlib only, so it imports without the project)

FAULT_TYPES = ["arms_wider", "foot_out", "knees_shallow", "elbow_bent", "trunk_lean", "knee_caving"]


def expected_frames(name="exercise"):
    doc = json.loads((ROOT / f"fixtures/input/expected/{name}/animation.json").read_text())
    return [{j: list(fr["joints"][j]) for j in doc["joints"]} for fr in doc["frames"]]


def deepest(frames, side="left"):
    return max(frames, key=lambda f: gen.measure(f, "knee_flexion", side))


def valgus_reference(f, side):
    """The master spec formula, written with numpy so it is independent of the generator's helpers."""
    h, k, a = (np.array(f[f"{side}_{j}"]) for j in ("hip", "knee", "ankle"))
    inward = -np.array([1.0, 0, 0] if side == "left" else [-1.0, 0, 0])
    axis = (a - h) / np.linalg.norm(a - h)
    off = (k - h) - axis * np.dot(k - h, axis)
    return math.degrees(math.atan2(np.dot(off, inward), np.linalg.norm(k - h)))


@pytest.fixture(scope="module")
def seed5(tmp_path_factory):
    out = tmp_path_factory.mktemp("seed5")
    return out, gen.generate(5, out)


@pytest.fixture(scope="module")
def seed5_dropout(tmp_path_factory):
    out = tmp_path_factory.mktemp("seed5-dropout")
    return out, gen.generate(5, out, dropout_variant=True)


# --- knee_caving ---
def test_knee_valgus_helper_follows_the_master_spec_formula():
    for name in ("exercise", "dance"):
        for f in expected_frames(name)[::10]:
            for side in ("left", "right"):
                assert gen.knee_valgus(f, side) == pytest.approx(valgus_reference(f, side), abs=1e-9)


def test_generator_valgus_agrees_with_the_part5_measure():
    positions = np.array([[f[j] for j in JOINTS] for f in expected_frames()])
    measures = compute(positions)
    frames = expected_frames()
    for side in ("left", "right"):
        want = [gen.knee_valgus(f, side) for f in frames]
        assert np.allclose(measures[f"{side}_knee_valgus"], want, atol=1e-6)


@pytest.mark.parametrize("side", ["left", "right"])
def test_cave_knee_reaches_the_target_inward_and_keeps_bone_lengths(side):
    f = deepest(expected_frames(), side)
    before = {j: list(p) for j, p in f.items()}
    thigh, shank = (gen.norm(gen.sub(f[f"{side}_{a}"], f[f"{side}_{b}"])) for a, b in (("knee", "hip"), ("ankle", "knee")))
    gen.cave_knee(f, side, 20.0)
    assert gen.knee_valgus(f, side) == pytest.approx(20.0, abs=1e-6)
    assert gen.norm(gen.sub(f[f"{side}_knee"], f[f"{side}_hip"])) == pytest.approx(thigh)
    assert gen.norm(gen.sub(f[f"{side}_ankle"], f[f"{side}_knee"])) == pytest.approx(shank)
    assert f[f"{side}_hip"] == before[f"{side}_hip"] and f[f"{side}_ankle"] == before[f"{side}_ankle"]
    moved = f[f"{side}_knee"][0] - before[f"{side}_knee"][0]
    assert (moved < 0) if side == "left" else (moved > 0)  # toward the midline


def test_cave_knee_does_nothing_on_a_straight_leg():
    frames = expected_frames()
    straight = frames[0]
    assert gen.measure(straight, "knee_flexion", "left") < 1.0
    before = list(straight["left_knee"])
    gen.cave_knee(straight, "left", 20.0)
    assert straight["left_knee"] == pytest.approx(before, abs=1e-3)  # nothing to rotate


def test_fault_knee_caving_follows_the_envelope():
    frames = expected_frames()
    n = len(frames)
    w = [0.0] * 10 + [0.5] * 10 + [1.0] * (n - 20)
    gen.fault_knee_caving(frames, "right", 20.0, w)
    assert gen.knee_valgus(frames[3], "right") == pytest.approx(0.0, abs=0.5)
    assert gen.knee_valgus(frames[len(frames) // 2], "right") == pytest.approx(20.0, abs=0.5)
    assert gen.APPLY["knee_caving"] is gen.fault_knee_caving


def test_knee_caving_labels_hold_the_measured_change(seed5):
    out, labels = seed5
    caving = [(t, f) for t in labels["takes"] for f in t["faults"] if f["type"] == "knee_caving"]
    assert len(caving) == 12  # one per cell, both sets
    for take, f in caving:
        assert (f["measure"], f["body_part"], f["direction"]) == ("knee_valgus", "legs", "more")
        assert f["side"] in ("left", "right") and f["joints"] == [f"{f['side']}_knee"]
        assert f["text"] == f"{f['side']} knee caving in"
        assert 0 < f["magnitude_deg"] <= f["peak_deg"] <= 26
        if take["set"] == "exercise":  # the squat bends enough to reach the 15 to 25 degree size
            assert 14.5 <= f["magnitude_deg"] <= 25.5


# --- the grid ---
def test_nine_takes_per_cell_and_108_per_seed(seed5):
    out, labels = seed5
    takes = labels["takes"]
    assert len(takes) == 108 == 2 * 3 * 2 * 9
    cells = {}
    for t in takes:
        cells.setdefault((t["set"], t["angle"], t["lighting"]), []).append(t)
    assert len(cells) == 12
    for cell in cells.values():
        assert len(cell) == 9 and sum(t["correct"] for t in cell) == 2
        singles = [t for t in cell if len(t["faults"]) == 1]
        assert sorted(t["faults"][0]["type"] for t in singles) == sorted(FAULT_TYPES)
        assert sum(len(t["faults"]) == 2 for t in cell) == 1
    assert sum(len(t["faults"]) for t in takes) == 96
    assert len({t["take_id"] for t in takes}) == 108


def test_every_label_carries_variant_and_label_source(seed5):
    out, labels = seed5
    assert labels["seed"] == 5 and labels["label_source"] == "synthetic"
    assert {(t["variant"], t["label_source"]) for t in labels["takes"]} == {("clean", "synthetic")}
    on_disk = json.loads((out / "labels.json").read_text())
    assert on_disk["seed"] == 5 and on_disk["takes"][0]["variant"] == "clean"


def test_double_fault_takes_never_pair_knee_caving(seed5):
    out, labels = seed5
    for t in labels["takes"]:
        if len(t["faults"]) == 2:
            assert "knee_caving" not in {f["type"] for f in t["faults"]}


def test_labels_validate_against_the_labels_schema(seed5_dropout):
    out, labels = seed5_dropout
    schema = json.loads((ROOT / "contracts/labels.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(labels)


# --- determinism, --out and the CLI ---
def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(Path(root).rglob("*")) if p.is_file()}


def test_same_seed_gives_byte_identical_output(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    gen.main(["--seed", "5", "--out", str(a), "--dropout-variant"])
    gen.main(["--seed", "5", "--out", str(b), "--dropout-variant"])
    ta, tb = tree(a), tree(b)
    assert ta.keys() == tb.keys() and len(ta) == 108 + 72 + 1
    # labels.json names the take files by absolute path outside the repo; everything else is the same bytes
    assert all(ta[k].replace(str(a.resolve()).encode(), b"X") == tb[k].replace(str(b.resolve()).encode(), b"X")
               for k in ta)


def test_a_different_seed_gives_different_takes(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    gen.generate(5, a, sets=["exercise"], angles=["front"], lights=["good"])
    gen.generate(6, b, sets=["exercise"], angles=["front"], lights=["good"])
    assert tree(a) != tree(b)
    assert json.loads((b / "labels.json").read_text())["seed"] == 6


def test_the_committed_seed_5_set_is_what_the_generator_writes(tmp_path):
    """The tuning set is reproducible from the committed expected clips: same bytes, take by take, feet included."""
    labels = gen.generate(5, tmp_path, feet=True, expected_feet_dir=tmp_path / "expected-feet")
    committed = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    assert [t["take_id"] for t in labels["takes"]] == [t["take_id"] for t in committed["takes"]]
    for t in committed["takes"]:
        for name, path in (("skeleton.json", t["follower"]), ("feet.json", t["follower_feet"])):
            assert (tmp_path / t["set"] / t["take_id"] / name).read_bytes() == (ROOT / path).read_bytes(), t["take_id"]
    for set_name in gen.SETS:
        fresh = (tmp_path / "expected-feet" / set_name / "feet.json").read_bytes()
        assert fresh == (ROOT / "fixtures/input/expected-feet" / set_name / "feet.json").read_bytes()
    paths = ("follower", "follower_feet", "expected_feet")
    strip = lambda d: [{k: v for k, v in t.items() if k not in paths} for t in d["takes"]]  # noqa: E731
    assert strip(labels) == strip(committed)


def test_out_defaults_to_the_tuning_set_and_expected_to_the_repo():
    assert gen.OUT == ROOT / "fixtures" / "input" / "followers"
    assert gen.EXPECTED == ROOT / "fixtures" / "input" / "expected"
    assert gen.rel(ROOT / "fixtures/input/followers") == "fixtures/input/followers"


def test_out_writes_where_asked_and_leaves_other_files(tmp_path):
    (tmp_path / "README.md").write_text("kept")
    gen.main(["--seed", "7", "--out", str(tmp_path)])
    assert (tmp_path / "README.md").read_text() == "kept"
    assert json.loads((tmp_path / "labels.json").read_text())["seed"] == 7
    assert len(list((tmp_path / "exercise").iterdir())) == 54


def test_a_rerun_replaces_the_previous_set(tmp_path):
    gen.generate(5, tmp_path, dropout_variant=True)
    labels = gen.generate(6, tmp_path)
    assert not list(tmp_path.rglob("*_dropout"))
    assert len(list((tmp_path / "exercise").iterdir())) == 54 == len([t for t in labels["takes"] if t["set"] == "exercise"])


# --- the dropout variant (AC-008) ---
def test_dropout_copies_exist_for_side_and_45_takes_only(seed5_dropout):
    out, labels = seed5_dropout
    dropped = [t for t in labels["takes"] if t["variant"] == "dropout"]
    clean = {t["take_id"]: t for t in labels["takes"] if t["variant"] == "clean"}
    assert len(clean) == 108 and len(dropped) == 2 * 2 * 2 * 9
    assert {t["angle"] for t in dropped} == {"45", "side"}
    for t in dropped:
        assert t["take_id"].endswith("_dropout") and t["label_source"] == "synthetic"
        source = clean[t["take_id"].removesuffix("_dropout")]
        assert t["faults"] == source["faults"] and t["correct"] == source["correct"]
        assert t["angle"] == source["angle"] and t["lighting"] == source["lighting"]
        assert (out / t["set"] / t["take_id"] / "skeleton.json").is_file()


def test_clean_takes_are_the_same_bytes_with_or_without_the_flag(tmp_path):
    a, b = tmp_path / "plain", tmp_path / "flag"
    gen.generate(5, a, sets=["dance"], angles=["side"], lights=["low"])
    gen.generate(5, b, sets=["dance"], angles=["side"], lights=["low"], dropout_variant=True)
    ta, tb = tree(a), tree(b)
    skeletons = {k: v for k, v in ta.items() if k.endswith("skeleton.json")}
    assert skeletons and all(tb[k] == v for k, v in skeletons.items())
    assert len([k for k in tb if k.endswith("_dropout/skeleton.json")]) == 9


def load_json(path):
    return json.loads(Path(path).read_text())


def test_dropout_takes_carry_conf_and_far_side_bursts(seed5_dropout):
    out, labels = seed5_dropout
    take = next(t for t in labels["takes"] if t["variant"] == "dropout" and t["angle"] == "side"
                and t["lighting"] == "low")
    doc = follower(take)
    far = {j for j in JOINTS if j.startswith("right_")}
    nulls = {(i, j) for i, fr in enumerate(doc["frames"]) for j, p in fr["joints"].items() if p is None}
    lows = {(i, j) for i, fr in enumerate(doc["frames"]) for j, c in fr["conf"].items() if c < 0.3}
    assert nulls and lows >= nulls  # a lost joint has conf below the cutoff too
    assert {j for _, j in lows} <= {"right_elbow", "right_wrist", "right_knee", "right_ankle"} <= far
    assert not [1 for _, j in lows if "hip" in j]  # the hip midpoint stays at the origin
    for fr in doc["frames"]:
        assert set(fr["conf"]) == set(JOINTS) and all(0 <= c <= 1 for c in fr["conf"].values())
    for b in take["dropouts"]:
        s, e = b["follower_frames"]
        assert 3 <= e - s + 1 <= 8 and b["mode"] in ("null", "low_conf")
    assert 2 <= len(take["dropouts"]) <= 4


def mean_conf(doc, joint_prefix):
    vals = [c for fr in doc["frames"] for j, c in fr["conf"].items() if j.startswith(joint_prefix) and c >= 0.3]
    return sum(vals) / len(vals)


def follower(take):
    path = Path(take["follower"])
    return load_json(path if path.is_absolute() else ROOT / path)


def test_conf_is_lower_on_the_far_side_and_in_low_light(seed5_dropout):
    out, labels = seed5_dropout
    pick = lambda angle, light: next(t for t in labels["takes"] if t["variant"] == "dropout"  # noqa: E731
                                     and t["set"] == "exercise" and t["angle"] == angle and t["lighting"] == light)
    side_good, side_low, deg45_good = (follower(pick(a, l)) for a, l in (("side", "good"), ("side", "low"), ("45", "good")))
    assert mean_conf(side_good, "right_") < mean_conf(side_good, "left_") - 0.1  # far side from the camera
    assert mean_conf(side_low, "left_") < mean_conf(side_good, "left_") - 0.1  # low light
    assert mean_conf(side_good, "right_") < mean_conf(deg45_good, "right_")  # the farther the camera yaw, the lower


def test_dropout_takes_load_through_part5_io_with_masked_joints(seed5_dropout):
    """AC-008: masked joints come through part5.io (null joints and conf below 0.3 are unusable)."""
    out, labels = seed5_dropout
    take = next(t for t in labels["takes"] if t["variant"] == "dropout" and t["angle"] == "45")
    path = Path(take["follower"])
    path = path if path.is_absolute() else ROOT / path
    clip = load_clip(path)
    doc = load_json(path)
    schema = json.loads((ROOT / "contracts/input-animation.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(doc)
    j = {name: i for i, name in enumerate(JOINTS)}
    burst = take["dropouts"][0]
    frame = burst["follower_frames"][0]
    assert not clip.mask[frame, j[burst["joint"]]]
    if burst["mode"] == "null":
        assert np.isnan(clip.positions[frame, j[burst["joint"]]]).all()
    assert clip.mask.mean() < 1.0 and clip.mask[:, j["left_knee"]].all()


# --- planted feet (TICKET-040, ASM-013, docs/specs/foot-keypoints.md) ---
FOOT_TYPES = {"foot_turned_out": ("foot_rotation", "more"), "foot_turned_in": ("foot_rotation", "less"),
              "ankle_rolled_in": ("ankle_inversion", "more"), "ankle_rolled_out": ("ankle_inversion", "less")}
FOOT_KEYS = ("expected_feet", "follower_feet")
# The template's big toe sits 0.035 m inside the foot axis, 0.24 m ahead of the heel: the heel to big toe vector
# points atan(0.035 / 0.24) toward the midline of a foot whose axis is turned out by the planted toe-out.
BIG_TOE_OFFSET_DEG = math.degrees(math.atan2(0.035, 0.24))


@pytest.fixture(scope="module")
def seed5_feet(tmp_path_factory):
    out = tmp_path_factory.mktemp("seed5-feet")
    return out, gen.generate(5, out, feet=True, expected_feet_dir=out / "expected-feet")


@pytest.fixture(scope="module")
def seed5_feet_dropout(tmp_path_factory):
    out = tmp_path_factory.mktemp("seed5-feet-dropout")
    return out, gen.generate(5, out, dropout_variant=True, feet=True, expected_feet_dir=out / "expected-feet")


def side_arrays(doc):
    """(joints (F, 17, 3), feet (F, 6, 3), joint conf (F, 17), foot conf (F, 6)) of a pose3d.json shaped side file."""
    people = [fr["people"][0] for fr in doc["frames"]]
    pts = lambda key, names: np.array([[[p[key][n][c] for c in "xyz"] for n in names] for p in people])  # noqa: E731
    conf = lambda key, names: np.array([[p[key][n]["conf"] for n in names] for p in people])  # noqa: E731
    return (pts("joints", JOINTS), pts("extra_joints", gen.FOOT_JOINTS),
            conf("joints", JOINTS), conf("extra_joints", gen.FOOT_JOINTS))


def foot_measures(doc):
    """{(measure, side): series} read off a side file with the Part 5 geometry helpers."""
    j, f, _, _ = side_arrays(doc)
    at = lambda name: j[:, JOINTS.index(name)]  # noqa: E731
    foot = lambda name: f[:, gen.FOOT_JOINTS.index(name)]  # noqa: E731
    out = {}
    for s in ("left", "right"):
        out["foot_rotation", s] = _foot_rotation(at("left_hip"), at("right_hip"), foot(f"{s}_heel"), foot(f"{s}_big_toe"), s)
        out["ankle_inversion", s] = _ankle_inversion(foot(f"{s}_heel"), foot(f"{s}_big_toe"), foot(f"{s}_small_toe"), s)
    return out


def test_feet_change_no_base_take_and_only_add_to_the_labels(tmp_path):
    """The 17-joint data of every base take and every earlier label key are the same bytes with or without --feet."""
    cell = dict(sets=["exercise"], angles=["45"], lights=["good"], dropout_variant=True)
    a, b = tmp_path / "plain", tmp_path / "feet"
    plain = gen.generate(5, a, **cell)
    with_feet = gen.generate(5, b, feet=True, expected_feet_dir=tmp_path / "ef", **cell)
    ta, tb = tree(a), tree(b)
    skeletons = {k: v for k, v in ta.items() if k.endswith("skeleton.json")}
    assert len(skeletons) == 18 and all(tb[k] == v for k, v in skeletons.items())
    keep = lambda t: {k: v for k, v in t.items() if k not in (*FOOT_KEYS, "follower", "expected")}  # noqa: E731
    for variant in ("clean", "dropout"):
        before = [t for t in plain["takes"] if t["variant"] == variant]
        after = [t for t in with_feet["takes"] if t["variant"] == variant]
        assert len(before) == 9 and len(after) == 13                  # the four foot takes are appended, never inserted
        assert [keep(t) for t in after[:9]] == [keep(t) for t in before]
        assert all(t["faults"][0]["type"] in FOOT_TYPES for t in after[9:])


def test_foot_takes_and_their_streams_do_not_depend_on_the_other_takes(tmp_path, seed5_feet):
    """A take's feet come from a stream keyed by its id: generating one cell gives the same feet.json as the full set."""
    out, labels = seed5_feet
    gen.generate(5, tmp_path, sets=["exercise"], angles=["front"], lights=["good"], feet=True,
                 expected_feet_dir=tmp_path / "ef")
    for take_id in ("exercise_front_good_03_foot_out-right", "exercise_front_good_10_foot_turned_in-left"):
        assert (tmp_path / "exercise" / take_id / "feet.json").read_bytes() == \
               (out / "exercise" / take_id / "feet.json").read_bytes()
        assert (tmp_path / "exercise" / take_id / "skeleton.json").read_bytes() == \
               (out / "exercise" / take_id / "skeleton.json").read_bytes()


def test_the_feet_grid_adds_four_takes_to_every_cell(seed5_feet):
    out, labels = seed5_feet
    takes = labels["takes"]
    assert len(takes) == 156 == 108 + 12 * 4
    assert [t["take_id"] for t in takes[:108]] == [t["take_id"] for t in gen.generate(5, out / "plain")["takes"]]
    cells = {}
    for t in takes[108:]:
        cells.setdefault((t["set"], t["angle"], t["lighting"]), []).append(t)
    assert len(cells) == 12
    for cell in cells.values():
        assert sorted(t["faults"][0]["type"] for t in cell) == sorted(FOOT_TYPES)
        assert [t["take_id"].split("_")[3] for t in cell] == ["09", "10", "11", "12"]
        assert all(len(t["faults"]) == 1 and not t["correct"] for t in cell)
    assert len({t["take_id"] for t in takes}) == 156
    assert sum(t["correct"] for t in takes) == 24 and sum(len(t["faults"]) for t in takes) == 96 + 48


def test_a_foot_fault_label_names_the_measure_the_side_and_the_size(seed5_feet):
    out, labels = seed5_feet
    for t in labels["takes"][108:]:
        (f,) = t["faults"]
        measure, direction = FOOT_TYPES[f["type"]]
        assert (f["measure"], f["direction"], f["body_part"]) == (measure, direction, "feet")
        sides = ["left", "right"] if f["side"] == "both" else [f["side"]]
        assert f["side"] in ("left", "right", "both") and f["joints"] == [f"{s}_ankle" for s in sides]
        assert 15 <= f["magnitude_deg"] == f["peak_deg"] <= 25
        s, e = f["follower_frames"]
        assert 0 <= s < e < t["frame_count"] and f["expected_frames"][0] < f["expected_frames"][1]
        assert f["text"].startswith(("left ", "right ", "feet ", "ankles ")) and f["text"].islower()
        assert t["variant"] == "clean" and t["label_source"] == "synthetic"


def test_every_take_names_its_two_side_files(seed5_feet):
    out, labels = seed5_feet
    for t in labels["takes"]:
        assert t["expected_feet"].endswith(f"expected-feet/{t['set']}/feet.json")
        assert Path(t["expected_feet"]).is_file() and Path(t["follower_feet"]).is_file()
        assert Path(t["follower_feet"]).parent == Path(t["follower"]).parent
        keys = list(t)
        assert keys.index("expected_feet") < keys.index("follower_feet") < keys.index("expected")  # additive in the file


def test_foot_fault_labels_validate_against_the_labels_schema_once_it_knows_them(seed5_feet):
    schema = json.loads((ROOT / "contracts/labels.schema.json").read_text())
    if "foot_turned_out" not in json.dumps(schema):
        pytest.skip("contracts/labels.schema.json does not list the foot fault types yet (TICKET-040 core lane)")
    jsonschema.Draft202012Validator(schema).validate(seed5_feet[1])


def test_a_side_file_is_part2s_pose3d_shape_holding_the_takes_own_joints(seed5_feet):
    out, labels = seed5_feet
    take = labels["takes"][3]
    skeleton, doc = load_json(take["follower"]), load_json(take["follower_feet"])
    assert set(doc) == {"frames", "t0_pts_ms", "provenance"} and doc["t0_pts_ms"] == 0.0
    assert doc["provenance"]["source"] == "synthetic" and doc["provenance"]["seed"] == 5
    assert doc["provenance"]["generator"] == "scripts/make_dummy_followers.py"
    assert len(doc["frames"]) == skeleton["frame_count"]
    for i, (fr, sk) in enumerate(zip(doc["frames"], skeleton["frames"])):
        assert fr["frame"] == i and fr["t_ms"] == pytest.approx(sk["t"] * 1000, abs=5e-4)
        (person,) = fr["people"]
        assert person["id"] == 0 and list(person["joints"]) == JOINTS and list(person["extra_joints"]) == gen.FOOT_JOINTS
        assert all(set(p) == {"x", "y", "z", "conf"} and p["conf"] == 1.0
                   for p in [*person["joints"].values(), *person["extra_joints"].values()])
        assert [person["joints"][j][c] for j in JOINTS for c in "xyz"] == [v for j in JOINTS for v in sk["joints"][j]]
    joints, feet, *_ = side_arrays(doc)
    assert np.allclose((joints[:, JOINTS.index("left_hip")] + joints[:, JOINTS.index("right_hip")]) / 2, 0, atol=1e-3)
    assert np.isfinite(feet).all()


def test_expected_feet_are_planted_flat_under_the_ankles_at_a_fixed_toe_out(seed5_feet):
    out, labels = seed5_feet
    doc = load_json(out / "expected-feet" / "exercise" / "feet.json")
    joints, feet, *_ = side_arrays(doc)
    ankle = lambda s: joints[:, JOINTS.index(f"{s}_ankle")]  # noqa: E731
    foot = lambda s, n: feet[:, gen.FOOT_JOINTS.index(f"{s}_{n}")]  # noqa: E731
    for s in ("left", "right"):
        for n in ("heel", "big_toe", "small_toe"):
            assert np.allclose(foot(s, n)[:, 1], ankle(s)[:, 1] - 0.08, atol=3e-4)   # flat, 0.08 m below the ankle
        ahead = np.linalg.norm((foot(s, "big_toe") - foot(s, "heel"))[:, [0, 2]], axis=1)
        assert np.allclose(ahead, math.hypot(0.24, 0.035), atol=3e-4)                 # 0.17 + 0.07 ahead, 0.035 across
        assert np.allclose(foot(s, "heel")[:, 2], ankle(s)[:, 2] - 0.07 * math.cos(math.radians(7)), atol=3e-4)
    for (measure, s), series in foot_measures(doc).items():
        if measure == "foot_rotation":   # hips on the x axis here, so the pelvis faces +z: 7 degrees out, less the offset
            assert np.allclose(series, gen.EXPECTED_TOE_OUT_DEG - BIG_TOE_OFFSET_DEG, atol=0.1), s
    assert doc["provenance"]["source"] == "synthetic" and doc["provenance"]["seed"] is None
    assert all(c == 1.0 for c in side_arrays(doc)[3].ravel())


def plain_take_feet(faults):
    """Planted feet and labels for the exercise clip with no noise, the fault window at full strength mid-clip."""
    frames = expected_frames()
    n = len(frames)
    plan = {"rng": gen.random.Random("feet-test"), "faults": faults}
    feet, labels = gen.plant_take_feet(frames, [float(i) for i in range(n)], 1.0, n, plan)
    return frames, feet, labels


def read_foot(frames, feet, i, side, kind):
    """The measure `kind` (yaw: foot_rotation, roll: ankle_inversion) of one foot in frame i, in degrees."""
    f = frames[i]
    p = {n.removeprefix(f"{side}_"): np.array(v) for n, v in feet[i].items() if n.startswith(side)}
    a = lambda name: np.array(f[name])  # noqa: E731
    if kind == "yaw":
        return float(_foot_rotation(a("left_hip"), a("right_hip"), p["heel"], p["big_toe"], side))
    return float(_ankle_inversion(p["heel"], p["big_toe"], p["small_toe"], side))


@pytest.mark.parametrize("ftype, side", [("foot_turned_out", "left"), ("foot_turned_in", "right"),
                                         ("foot_turned_out", "both"), ("ankle_rolled_in", "left"),
                                         ("ankle_rolled_out", "right"), ("ankle_rolled_in", "both")])
def test_a_foot_fault_moves_its_measure_by_exactly_the_label_size_and_nothing_else(ftype, side):
    frames, base, _ = plain_take_feet([])
    faulted, (label,) = plain_take_feet([(ftype, side)])[1:]
    spec = gen.FOOT_FAULTS[ftype]
    start, end = label["_window"]
    mid = (start + end) // 2   # the ramps are 6 frames, so the middle of the window is at full strength
    hit = ["left", "right"] if side == "both" else [side]
    for s in ("left", "right"):
        change = read_foot(frames, faulted, mid, s, spec["kind"]) - read_foot(frames, base, mid, s, spec["kind"])
        want = spec["sign"] * label["magnitude_deg"] if s in hit else 0.0   # a foot that is not named is untouched
        assert change == pytest.approx(want, abs=1e-6)
        assert read_foot(frames, faulted, 0, s, spec["kind"]) == pytest.approx(read_foot(frames, base, 0, s, spec["kind"]), abs=1e-9)
    assert 15 <= label["magnitude_deg"] <= 25 and label["measure"] == spec["measure"]


def test_foot_takes_carry_the_fault_in_their_side_file(seed5_feet):
    """The fault shows in the measure series: inside its window a turned foot sits about its size from where it is outside."""
    out, labels = seed5_feet
    shifts = []
    for t in labels["takes"][108:]:
        (f,) = t["faults"]
        if t["lighting"] != "good" or t["angle"] != "front" or f["measure"] != "foot_rotation":
            continue
        series = foot_measures(load_json(t["follower_feet"]))
        s0, e0 = f["follower_frames"]
        for side in (["left", "right"] if f["side"] == "both" else [f["side"]]):
            v = series[f["measure"], side]
            outside = np.concatenate([v[:s0 - 4], v[e0 + 4:]])
            sign = 1.0 if f["direction"] == "more" else -1.0
            shifts.append(sign * (np.nanmedian(v[s0 + 8:e0 - 8]) - np.nanmedian(outside)) / f["magnitude_deg"])
    assert len(shifts) >= 4 and np.median(shifts) == pytest.approx(1.0, abs=0.35) and min(shifts) > 0.3


def test_the_far_foot_is_noisier_than_the_near_one(seed5_feet):
    """The foot points carry the take's camera noise with the far side multiplied, like the 17 joints."""
    out, labels = seed5_feet
    spread = {}
    for t in labels["takes"][:108]:
        if t["correct"] and t["angle"] == "side" and t["lighting"] == "good":
            j, f, *_ = side_arrays(load_json(t["follower_feet"]))
            for s in ("left", "right"):
                heel = f[:, gen.FOOT_JOINTS.index(f"{s}_heel")] - j[:, JOINTS.index(f"{s}_ankle")]
                spread.setdefault(s, []).append(float(np.std(heel, axis=0).sum()))
    assert np.mean(spread["right"]) > np.mean(spread["left"])


def test_feet_output_is_deterministic_with_dropout_copies(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    gen.main(["--seed", "5", "--out", str(a), "--dropout-variant", "--feet", "--expected-feet-dir", str(a / "ef")])
    gen.main(["--seed", "5", "--out", str(b), "--dropout-variant", "--feet", "--expected-feet-dir", str(b / "ef")])
    ta, tb = tree(a), tree(b)
    assert ta.keys() == tb.keys() and sum(k.endswith("/feet.json") for k in ta) == 156 + 104 + 2   # every take, every copy, both expected sets
    assert all(ta[k].replace(str(a.resolve()).encode(), b"X") == tb[k].replace(str(b.resolve()).encode(), b"X")
               for k in ta)


def test_a_dropout_copy_masks_a_foot_where_it_masks_the_ankle(seed5_feet_dropout):
    out, labels = seed5_feet_dropout
    copies = [t for t in labels["takes"] if t["variant"] == "dropout"]
    assert len(copies) == 104 and all(Path(t["follower_feet"]).parent == Path(t["follower"]).parent for t in copies)
    masked = 0
    for t in copies:
        sk, doc = load_json(t["follower"]), load_json(t["follower_feet"])
        joints, feet, jconf, fconf = side_arrays(doc)
        assert np.isfinite(joints).all() and np.isfinite(feet).all()                  # Part 2 never writes a null
        assert np.allclose(jconf, [[fr["conf"][j] for j in JOINTS] for fr in sk["frames"]])
        for s in ("left", "right"):
            ankle = jconf[:, JOINTS.index(f"{s}_ankle")]
            foot = fconf[:, [gen.FOOT_JOINTS.index(f"{s}_{n}") for n in ("big_toe", "small_toe", "heel")]]
            lost = ankle < 0.3
            assert np.array_equal(foot < 0.3, np.repeat(lost[:, None], 3, axis=1))   # masked in the ankle's frames only
            assert np.all(foot[~lost] == 1.0) and np.allclose(foot[lost], ankle[lost][:, None])
            masked += int(lost.any())
    assert masked > 0                      # at least one copy loses an ankle, so the test is not vacuous
    clean = next(t for t in labels["takes"] if t["take_id"] == copies[0]["take_id"].removesuffix("_dropout"))
    assert side_arrays(load_json(clean["follower_feet"]))[3].min() == 1.0   # a clean take is never masked


# --- make heldout-data (never run with a real seed here) ---
def make(*args):
    return subprocess.run(["make", *args], cwd=ROOT, capture_output=True, text=True)


HELDOUT_LABELS = ROOT / "fixtures/input/heldout/labels.json"


def heldout_state():
    """The committed held-out labels (or None): a refused or dry make must leave them as they are."""
    return HELDOUT_LABELS.read_bytes() if HELDOUT_LABELS.exists() else None


def test_heldout_data_refuses_without_a_seed():
    before = heldout_state()
    r = make("heldout-data")
    assert r.returncode == 2 and "SEED is required" in r.stderr and "make heldout-data SEED=29" in r.stderr
    assert heldout_state() == before


@pytest.mark.parametrize("seed", ["5", "7", "30"])
def test_heldout_data_refuses_a_seed_that_is_not_a_held_out_seed(seed):
    before = heldout_state()
    r = make("heldout-data", f"SEED={seed}")
    assert r.returncode == 2 and "not a held-out seed" in r.stderr
    assert heldout_state() == before


@pytest.mark.parametrize("seed", ["29", "31", "37"])
def test_heldout_data_dry_run_names_the_generator_command(seed):
    before = heldout_state()
    r = make("-n", "heldout-data", f"SEED={seed}")  # -n prints the recipe and runs nothing
    assert r.returncode == 0
    assert f"python3 scripts/make_dummy_followers.py --seed {seed} --out fixtures/input/heldout --dropout-variant" in r.stdout
    assert heldout_state() == before


@pytest.mark.parametrize("seed, feet", [("29", False), ("31", False), ("37", True)])
def test_heldout_data_passes_feet_only_for_the_seeds_scored_with_them(seed, feet):
    """Seeds 29 and 31 were scored without feet and regenerate without (AC-FOOT-11); seed 37 is the first with."""
    r = make("-n", "heldout-data", f"SEED={seed}")
    assert r.returncode == 0 and (" --feet" in r.stdout) is feet


def test_dummy_data_writes_the_seed_5_set_with_feet():
    r = make("-n", "dummy-data")
    assert r.returncode == 0 and "python3 scripts/make_dummy_followers.py --feet" in r.stdout
