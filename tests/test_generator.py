"""The synthetic follower generator: knee_caving (ADR-0004), the 9-take grid, the dropout variant (#25,
AC-008), --out, determinism and the Makefile target that makes held-out sets."""
import json
import math
import subprocess
import sys
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from part5.io import JOINTS, load_clip
from part5.measures import compute

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


def test_generator_valgus_agrees_with_the_part5_measure_once_it_exists():
    positions = np.array([[f[j] for j in JOINTS] for f in expected_frames()])
    measures = compute(positions)
    if "left_knee_valgus" not in measures:
        pytest.skip("part5.measures has no knee_valgus yet")
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
    """The tuning set is reproducible from the committed expected clips: same bytes, take by take."""
    labels = gen.generate(5, tmp_path)
    committed = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    assert [t["take_id"] for t in labels["takes"]] == [t["take_id"] for t in committed["takes"]]
    for t in committed["takes"]:
        fresh = (tmp_path / t["set"] / t["take_id"] / "skeleton.json").read_bytes()
        assert fresh == (ROOT / t["follower"]).read_bytes(), t["take_id"]
    strip = lambda d: [{k: v for k, v in t.items() if k != "follower"} for t in d["takes"]]  # noqa: E731
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
