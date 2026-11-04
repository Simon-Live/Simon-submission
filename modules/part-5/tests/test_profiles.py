"""docs/specs/profiles.md: the profiles file, its pure functions and the effective rules (ADR-0016).

AC-PROF-01 (the file and the loader), AC-PROF-02 (fitness is the identity, including the baseline of every seed 5
take), AC-PROF-03 (effective rules), AC-PROF-04 (an explained fault stays explained), AC-PROF-05 and 06 (dance and
rehab never report a fault fitness does not, and keep every range fault), AC-PROF-07 (the tempo cue overrides; the rehab
tempo and reassurance tests are in tests/test_profiles_tempo.py) and AC-PROF-08 (the dance tempo charge, the frozen
score params) and AC-PROF-NFR-01. The CLI, API, schema and report parts are in tests/test_profiles_wiring.py. The
`seed5` fixture is in tests/conftest.py."""
import copy
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from part5 import cues, pipeline, profiles, profiles_report, score
from part5.align import Alignment, align
from part5.detect import detect, load_rules
from part5.io import JOINTS, load_clip
from part5.measures import MEASURES, compute
from part5.output import write_analysis
from shipped_score import tempo_items

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_dummy_followers as gen  # noqa: E402  (the generator's fault functions, stdlib only)

RANGE = {"elbow_flexion", "knee_flexion", "upper_arm_out", "upper_arm_forward", "thigh_forward"}
POSITION = {"forearm_out", "thigh_out", "foot_out", "knee_valgus", "trunk_lean_forward", "trunk_lean_side",
            "shoulder_tilt", "head_forward", "foot_rotation", "ankle_inversion"}
DELETE = object()


def shipped():
    return json.loads(profiles.PROFILES_PATH.read_text())


def write(tmp_path, doc):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(doc))
    return path


def edit(path, value):
    """A change to a copy of the shipped document: set `value` at the nested key `path`, or delete it."""
    def change(doc):
        node = doc
        for key in path[:-1]:
            node = node[key]
        if value is DELETE:
            del node[path[-1]]
        else:
            node[path[-1]] = value
    return change


def rename_dance(doc):
    doc["profiles"]["Dance"] = doc["profiles"].pop("dance")


DANCE_POSITION = ["profiles", "dance", "kinds", "position"]
DANCE_TEMPO = ["profiles", "dance", "tempo"]
REHAB_CUES = ["profiles", "rehab", "tempo", "cues"]
FITNESS = ["profiles", "fitness"]
REJECTED = [
    ("no fitness", edit(["profiles", "fitness"], DELETE), "profiles"),
    ("default not a profile", edit(["default"], "yoga"), "default"),
    ("default not fitness", edit(["default"], "dance"), "default"),
    ("wrong version", edit(["version"], "simon.profiles.v2"), "version"),
    ("unknown top level key", edit(["extra"], 1), "unknown keys"),
    ("profile not an object", edit(["profiles", "dance"], 3), "profiles.dance"),
    ("name not lower case", rename_dance, "profiles.Dance"),
    ("typo in a tolerance", edit(DANCE_POSITION + ["threshold_multiplyer"], 1.2), "unknown keys"),
    ("missing kind", edit(["profiles", "dance", "kinds", "range"], DELETE), "missing keys"),
    ("missing tolerance key", edit(DANCE_POSITION + ["min_run_frames_add"], DELETE), "missing keys"),
    ("threshold multiplier below 1", edit(DANCE_POSITION + ["threshold_multiplier"], 0.9), "threshold_multiplier"),
    ("threshold multiplier a string", edit(DANCE_POSITION + ["threshold_multiplier"], "1.2"), "threshold_multiplier"),
    ("threshold multiplier not finite", edit(DANCE_POSITION + ["threshold_multiplier"], float("nan")),
     "threshold_multiplier"),
    ("min_fraction multiplier below 1", edit(DANCE_POSITION + ["min_fraction_multiplier"], 0.5),
     "min_fraction_multiplier"),
    ("run addition negative", edit(DANCE_POSITION + ["min_run_frames_add"], -1), "min_run_frames_add"),
    ("run addition fractional", edit(DANCE_POSITION + ["min_run_frames_add"], 1.5), "min_run_frames_add"),
    ("run addition a bool", edit(DANCE_POSITION + ["min_run_frames_add"], True), "min_run_frames_add"),
    ("unknown tempo cue key", edit(REHAB_CUES + ["speed_down"], "Slower is fine"), "unknown keys"),
    ("tempo cue too long", edit(REHAB_CUES + ["speed_up"], "Slower is really quite fine for you"), "cues.speed_up"),
    ("tempo cue empty", edit(REHAB_CUES + ["speed_up"], ""), "cues.speed_up"),
    ("tempo cue lower case", edit(REHAB_CUES + ["speed_up"], "slower is fine"), "cues.speed_up"),
    ("tempo cue with an em dash", edit(REHAB_CUES + ["speed_up"], f"Slower {chr(0x2014)} fine"), "cues.speed_up"),
    ("tempo cue with an en dash", edit(REHAB_CUES + ["speed_up"], f"Slower {chr(0x2013)} fine"), "cues.speed_up"),
    ("tempo cue with a spaced hyphen", edit(REHAB_CUES + ["speed_up"], "Slower - fine"), "cues.speed_up"),
    ("tempo cue ends with a stop", edit(REHAB_CUES + ["speed_up"], "Slower is fine."), "cues.speed_up"),
    ("tempo cue not text", edit(REHAB_CUES + ["speed_up"], 3), "cues.speed_up"),
    ("negative weight", edit(DANCE_TEMPO + ["weight"], -1), "weight"),
    ("negative cap", edit(DANCE_TEMPO + ["cap"], -1), "cap"),
    ("weight a string", edit(DANCE_TEMPO + ["weight"], "40"), "weight"),
    ("tempo key missing", edit(DANCE_TEMPO + ["cap"], DELETE), "missing keys"),
    ("measure without a cue", edit(["profiles", "rehab", "measures"], {"nose_height": {"threshold_multiplier": 1.2}}),
     "measures.nose_height"),
    ("measure override below 1", edit(["profiles", "rehab", "measures"], {"thigh_out": {"threshold_multiplier": 0.5}}),
     "thigh_out.threshold_multiplier"),
    ("fitness multiplier", edit(FITNESS + ["kinds", "position", "threshold_multiplier"], 1.1), "identity"),
    ("fitness addition", edit(FITNESS + ["kinds", "range", "min_run_frames_add"], 1), "identity"),
    ("fitness weight", edit(FITNESS + ["tempo", "weight"], 1.0), "identity"),
    ("fitness tempo cue", edit(FITNESS + ["tempo", "cues"], {"speed_up": "Hurry up"}), "identity"),
    ("fitness measure entry", edit(FITNESS + ["measures"], {"thigh_out": {}}), "identity"),
]


# --- AC-PROF-01: the file and the loader ---
def test_shipped_file_is_valid():
    doc = profiles.load()
    assert profiles.names(doc) == ["dance", "rehab", "fitness"]
    assert profiles.names() == ["dance", "rehab", "fitness"]
    assert doc["version"] == profiles.VERSION == "simon.profiles.v1"
    assert profiles.default(doc) == profiles.default() == "fitness"
    for name, profile in doc["profiles"].items():
        assert set(profile) == {"kinds", "measures", "tempo"}, name
        assert set(profile["kinds"]) == {"range", "position"}, name


@pytest.mark.parametrize("label, change, field", REJECTED, ids=[r[0] for r in REJECTED])
def test_loader_rejects(tmp_path, label, change, field):
    doc = shipped()
    change(doc)
    path = write(tmp_path, doc)
    with pytest.raises(profiles.ProfileError) as e:
        profiles.load(path)
    assert str(e.value).startswith("profiles.json: ") and field in str(e.value)


def test_loader_names_the_file_when_it_cannot_read_it(tmp_path):
    with pytest.raises(profiles.ProfileError, match="gone.json: cannot be read"):
        profiles.load(tmp_path / "gone.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(profiles.ProfileError, match="bad.json: not JSON"):
        profiles.load(bad)
    bad.write_text("[]")
    with pytest.raises(profiles.ProfileError, match=r"bad.json: \(file\): must be an object"):
        profiles.load(bad)


def test_nothing_in_the_shipped_file_makes_a_profile_stricter():
    for name, profile in shipped()["profiles"].items():
        tolerances = [*profile["kinds"].values(), *profile["measures"].values()]
        assert all(t["threshold_multiplier"] >= 1 and t["min_fraction_multiplier"] >= 1 for t in tolerances), name
        assert all(t["min_run_frames_add"] >= 0 for t in tolerances), name
        assert profile["tempo"]["weight"] >= 0 and profile["tempo"]["cap"] >= 0, name


def test_require_accepts_a_name_and_says_which_names_exist():
    assert [profiles.require(n) for n in ("dance", "rehab", "fitness")] == ["dance", "rehab", "fitness"]
    for bad in ("Rehab", "", "yoga", None, 3, ["dance"]):
        with pytest.raises(profiles.ProfileError) as e:
            profiles.require(bad)
        assert str(e.value) == "profile: must be one of ['dance', 'rehab', 'fitness']"


def test_effective_rules_rejects_a_min_fraction_past_one():
    rules = load_rules()
    rules["default"]["min_fraction"] = 0.9   # dance asks for 1.15 times that on position measures
    with pytest.raises(profiles.ProfileError, match=r"profile dance: .* min_fraction 0.9 times 1.15 is over 1"):
        profiles.effective_rules(rules, "dance")
    assert profiles.effective_rules(rules, "rehab")["default"]["min_fraction"] == 0.9   # rehab leaves the share alone


# --- AC-PROF-02: fitness is the identity ---
def test_fitness_entry_is_all_ones():
    fitness = shipped()["profiles"]["fitness"]
    for kind in ("range", "position"):
        assert fitness["kinds"][kind] == {"threshold_multiplier": 1.0, "min_fraction_multiplier": 1.0,
                                          "min_run_frames_add": 0}
    assert fitness["measures"] == {}
    assert fitness["tempo"] == {"cues": {}, "weight": 0.0, "cap": 0.0}


def test_effective_rules_fitness_returns_the_rules_unchanged():
    rules = load_rules()
    before = copy.deepcopy(rules)
    assert profiles.effective_rules(rules, "fitness") is rules
    assert profiles.effective_rules(rules, None) is rules
    assert profiles.effective_rules(rules) is rules
    assert rules == before and "profile" not in rules


def test_fitness_has_the_identity_tempo_block():
    assert profiles.tempo_of(load_rules()) == {"cues": {}, "weight": 0.0, "cap": 0.0}
    assert profiles.tempo_points(1.6, 0.0, 0.0) == 0.0


# --- AC-PROF-03: effective rules ---
POSITION_THRESHOLDS = {"forearm_out": 17, "thigh_out": 13, "foot_out": 6, "knee_valgus": 9, "trunk_lean_forward": 9,
                       "trunk_lean_side": 9, "shoulder_tilt": 9, "head_forward": 18}
RANGE_THRESHOLDS = {"elbow_flexion": 20, "knee_flexion": 10, "upper_arm_out": 11, "upper_arm_forward": 15,
                    "thigh_forward": 15}


def test_the_rules_hold_the_thresholds_this_spec_works_from():
    measures = load_rules()["measures"]
    for name, threshold in {**POSITION_THRESHOLDS, **RANGE_THRESHOLDS}.items():
        assert measures[name]["threshold_deg"] == threshold, name


@pytest.mark.parametrize("profile, factor, share, run", [("rehab", 1.5, 1.0, 4), ("dance", 1.25, 1.15, 6)])
def test_thresholds_scale_by_kind(profile, factor, share, run):
    rules = load_rules()
    out = profiles.effective_rules(rules, profile)
    for name, threshold in POSITION_THRESHOLDS.items():
        cfg = out["measures"][name]
        assert cfg["threshold_deg"] == pytest.approx(threshold * factor), name
        assert cfg["min_fraction"] == pytest.approx(rules["default"]["min_fraction"] * share), name
        assert cfg["min_run_frames"] == run, name
        assert cfg["min_frames_floor"] == rules["default"]["min_frames_floor"], name
    for name, threshold in RANGE_THRESHOLDS.items():   # range measures are kept: the same config as fitness
        assert out["measures"][name] == {**rules["default"], **rules["measures"][name], "min_run_frames": 4}, name
    assert out["measures"]["thigh_out"]["threshold_deg"] == pytest.approx(19.5 if profile == "rehab" else 16.25)


def test_every_measure_has_a_kind():
    assert {m for m, (kind, _) in cues.CUES.items() if kind == "range"} == RANGE
    assert {m for m, (kind, _) in cues.CUES.items() if kind == "position"} <= POSITION
    rules = load_rules()
    assert set(profiles.FOOT_GENERIC) == {"foot_rotation", "ankle_inversion"}
    for measure in {*rules["measures"], *cues.CUES, *profiles.FOOT_GENERIC}:
        assert profiles.kind_of(measure) in profiles.KINDS, measure
    for measure in profiles.FOOT_GENERIC:   # ADR-0015: both foot measures are position measures, by the cue table alone
        assert measure in cues.CUES and profiles.kind_of(measure) == cues.CUES[measure][0] == "position"
    with pytest.raises(profiles.ProfileError, match="no cue kind for measure 'nose_height'"):
        profiles.kind_of("nose_height")


def test_the_foot_measures_take_the_position_tolerance():
    rules = load_rules()
    rules["measures"] = {**rules["measures"], "foot_rotation": {"threshold_deg": 14.0},
                         "ankle_inversion": {"threshold_deg": 14.0}}
    rehab, dance = profiles.effective_rules(rules, "rehab"), profiles.effective_rules(rules, "dance")
    for measure in profiles.FOOT_GENERIC:
        assert rehab["measures"][measure]["threshold_deg"] == pytest.approx(21.0)
        assert dance["measures"][measure]["threshold_deg"] == pytest.approx(17.5)
        assert dance["measures"][measure]["min_run_frames"] == 6 and rehab["measures"][measure]["min_run_frames"] == 4


def test_measure_override_beats_kind(tmp_path):
    doc = shipped()
    doc["profiles"]["rehab"]["measures"] = {"thigh_out": {"threshold_multiplier": 2.0},
                                            "knee_flexion": {"min_run_frames_add": 3}}
    profiles.load(write(tmp_path, doc))   # a valid file
    rules = load_rules()
    out = profiles.effective_rules(rules, "rehab", doc)
    assert out["measures"]["thigh_out"]["threshold_deg"] == pytest.approx(26.0)   # the override, not the kind's 1.5
    assert out["measures"]["thigh_out"]["min_run_frames"] == 4                    # the kind's other keys stay
    assert out["measures"]["foot_out"]["threshold_deg"] == pytest.approx(9.0)     # other position measures: the kind
    assert out["measures"]["knee_flexion"]["min_run_frames"] == 7                 # a range measure can be overridden
    assert out["measures"]["knee_flexion"]["threshold_deg"] == 10.0


def test_effective_rules_does_not_mutate_or_touch_score():
    rules = load_rules()
    before = copy.deepcopy(rules)
    out = profiles.effective_rules(rules, "dance")
    assert rules == before and out is not rules
    for key in ("default", "guard", "explained_by", "explained_by_opposite", "smooth_frames", "tolerance_frames",
                "score"):
        assert out[key] == rules[key], key
    assert json.dumps(out["score"], sort_keys=True) == json.dumps(rules["score"], sort_keys=True)
    out["guard"]["max_residual"] = 99.0
    out["measures"]["thigh_out"]["threshold_deg"] = 99.0
    assert rules == before   # the effective rules share nothing with the input


def test_effective_rules_records_the_baseline_and_the_tempo_block():
    rules = load_rules()
    out = profiles.effective_rules(rules, "rehab")
    assert out["profile"]["name"] == "rehab"
    for measure, cfg in out["profile"]["baseline"].items():
        assert cfg == {**rules["default"], **rules["measures"].get(measure, {})}, measure
    assert set(out["profile"]["baseline"]) == set(out["measures"]) >= set(rules["measures"])
    assert out["profile"]["tempo"] == shipped()["profiles"]["rehab"]["tempo"]
    assert "profile" not in rules


def test_effective_rules_refuses_a_profile_on_top_of_a_profile_and_an_unknown_one():
    out = profiles.effective_rules(load_rules(), "rehab")
    with pytest.raises(profiles.ProfileError, match="already carry profile 'rehab'"):
        profiles.effective_rules(out, "dance")
    with pytest.raises(profiles.ProfileError, match=r"profile: must be one of \['dance', 'rehab', 'fitness'\]"):
        profiles.effective_rules(load_rules(), "yoga")


def test_min_frames_is_scaled_and_rounded_up_without_float_noise():
    rules = load_rules()
    rules["measures"]["thigh_out"]["min_frames"] = 20   # 20 * 1.15 is 22.999999999999996 in floating point
    rules["measures"]["foot_out"]["min_frames"] = 10    # 11.5 rounds up
    out = profiles.effective_rules(rules, "dance")
    assert out["measures"]["thigh_out"]["min_frames"] == 23 and out["measures"]["foot_out"]["min_frames"] == 12
    assert "min_frames" not in out["measures"]["trunk_lean_forward"]


def test_a_rules_entry_without_a_threshold_is_refused():
    rules = load_rules()
    del rules["default"]["threshold_deg"]
    del rules["measures"]["thigh_out"]["threshold_deg"]
    with pytest.raises(profiles.ProfileError, match="thigh_out has no threshold_deg"):
        profiles.effective_rules(rules, "rehab")


def expected_clip(name):
    return load_clip(ROOT / f"fixtures/input/expected/{name}/animation.json").positions


def with_trunk_lean(positions, degrees, start, end):
    frames = [{j: list(map(float, positions[i, k])) for k, j in enumerate(JOINTS)} for i in range(len(positions))]
    n = len(frames)
    gen.APPLY["trunk_lean"](frames, "center", degrees, [1.0 if start * n <= i <= end * n else 0.0 for i in range(n)])
    return np.array([[f[j] for j in JOINTS] for f in frames])


def trunk_lean_found(exp, fol, rules):
    faults = detect(compute(exp), compute(fol), align(exp, fol), rules)
    return any(f.measure == "trunk_lean_forward" and f.direction == "more" for f in faults)


def test_persistence_relaxation():
    """A lean of 16 degrees clears dance's 11.25 degree threshold, so only how long it lasts decides: held for 40% of
    the clip it is a fault for fitness (38%) and rehab (no change) but not for dance (43.7% and runs of 6 frames);
    held for 50% it is a fault for all three. The loosen-only construction in detect.py comes with the wiring; a lone
    fault has nothing to be explained by, so the plain effective rules show the same here."""
    rules = load_rules()
    dance, rehab = (profiles.effective_rules(rules, p) for p in ("dance", "rehab"))
    exp = expected_clip("dance")
    short, long = with_trunk_lean(exp, 16, 0.1, 0.5), with_trunk_lean(exp, 16, 0.1, 0.6)
    assert trunk_lean_found(exp, short, rules) and trunk_lean_found(exp, short, rehab)
    assert not trunk_lean_found(exp, short, dance)
    assert all(trunk_lean_found(exp, long, r) for r in (rules, rehab, dance))


# --- AC-PROF-07: the tempo cue data (the substitution itself is wiring) ---
def test_rehab_replaces_only_the_speed_up_cue():
    profile_cues = {name: p["tempo"]["cues"] for name, p in shipped()["profiles"].items()}
    assert profile_cues == {"dance": {}, "rehab": {"speed_up": "Slower is fine"}, "fitness": {}}
    assert len("Slower is fine".split()) <= cues.MAX_WORDS
    assert cues.SPEED_UP == "Speed up to match the trainer" and cues.SLOW_DOWN == "Slow down to match the trainer"
    assert "slow_down" not in profile_cues["rehab"]   # a follower faster than the example is still told to slow down


def test_tempo_of_reads_the_effective_rules_and_hands_back_a_copy():
    rules = load_rules()
    assert profiles.tempo_of(rules) == {"cues": {}, "weight": 0.0, "cap": 0.0}
    rehab = profiles.effective_rules(rules, "rehab")
    assert profiles.tempo_of(rehab) == {"cues": {"speed_up": "Slower is fine"}, "weight": 0.0, "cap": 0.0}
    profiles.tempo_of(rehab)["cues"]["speed_up"] = "changed"
    assert profiles.tempo_of(rehab)["cues"]["speed_up"] == "Slower is fine"
    assert profiles.tempo_of(profiles.effective_rules(rules, "dance"))["weight"] == 40.0


# --- AC-PROF-08: the dance tempo charge (the score wiring itself is wiring) ---
@pytest.mark.parametrize("ratio, points", [
    (0.60, 10.0), (0.75, 4.0), (0.85, 0.0), (1.0, 0.0), (1.15, 0.0), (1.25, 4.0), (1.40, 10.0), (1.65, 20.0),
    (2.0, 20.0), (3.0, 20.0), (None, 0.0), (float("nan"), 0.0)])
def test_tempo_points_formula(ratio, points):
    assert profiles.tempo_points(ratio, 40.0, 20.0) == pytest.approx(points)


def test_tempo_points_without_a_weight_cost_nothing_and_a_small_cap_wins():
    assert profiles.tempo_points(2.0, 0.0, 0.0) == 0.0
    assert profiles.tempo_points(2.0, 40.0, 0.0) == 0.0
    assert profiles.tempo_points(1.25, 40.0, 3.0) == 3.0


def test_only_dance_charges_tempo():
    weights = {name: p["tempo"]["weight"] for name, p in shipped()["profiles"].items()}
    assert weights == {"dance": 40.0, "rehab": 0.0, "fitness": 0.0}
    assert shipped()["profiles"]["dance"]["tempo"]["cap"] == 20.0
    assert profiles.tempo_of(profiles.effective_rules(load_rules(), "dance")) == {"cues": {}, "weight": 40.0, "cap": 20.0}


# --- the information hash and determinism ---
def test_file_sha256_is_the_hash_of_the_bytes(tmp_path):
    assert profiles.file_sha256() == hashlib.sha256(profiles.PROFILES_PATH.read_bytes()).hexdigest()
    other = tmp_path / "other.json"
    other.write_text(profiles.PROFILES_PATH.read_text() + "\n")
    assert profiles.file_sha256(other) != profiles.file_sha256()


def test_effective_rules_are_deterministic():
    a, b = (profiles.effective_rules(load_rules(), "dance") for _ in range(2))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_the_profiles_file_is_not_part_of_the_rules():
    rules = load_rules()
    assert "profile" not in rules and "profiles" not in rules


def test_a_foot_measure_the_rules_do_not_list_is_not_switched_on_by_a_profile():
    """ADR-0015: a foot measure has no default threshold. Rules without its entry do not report it, and a profile built
    on them must not start to (it would report a fault fitness does not)."""
    rules = load_rules()
    for measure in profiles.FOOT_GENERIC:
        del rules["measures"][measure]
    for name in ("dance", "rehab"):
        out = profiles.effective_rules(rules, name)
        assert not set(profiles.FOOT_GENERIC) & set(out["measures"]), name
        assert not set(profiles.FOOT_GENERIC) & set(out["profile"]["baseline"]), name


# --- shared runs of the seed 5 set and the Part 3 kit under each profile ---
NAMES = ("fitness", "dance", "rehab")
KIT_DIR = ROOT / "fixtures/input/contract/part3"
KIT_EXPECTED = ROOT / "fixtures/input/expected/part3-squat/animation.json"
TOLERATED = 0.52   # a score value is rounded to a whole number and each component to 0.01


@pytest.fixture(scope="module")
def kit():
    """{take_id: analysis} of Part 3's 15 kit takes against its squat, per profile (faults only, no score)."""
    labels = json.loads((KIT_DIR / "followers/labels.json").read_text())
    follower = {t["take_id"]: str(KIT_DIR / t["follower"]) for t in labels["takes"]}
    return {name: {take_id: pipeline.analyse(str(KIT_EXPECTED), path, profile=name) for take_id, path in follower.items()}
            for name in NAMES}


# --- AC-PROF-02: fitness is the identity ---
def test_fitness_matches_the_prefeature_baseline(seed5):
    runs, labels = seed5
    baseline = json.loads(profiles_report.BASELINE.read_text())
    assert baseline["seed"] == 5 and set(baseline["takes"]) == {t["take_id"] for t in labels["takes"]}
    assert len(baseline["takes"]) == len(labels["takes"]) >= 108
    stale = [take_id for take_id, a in runs["fitness"].items()
             if profiles_report.analysis_digest(a) != baseline["takes"][take_id]]
    assert stale == []


def test_naming_no_profile_is_the_fitness_baseline_too():
    """The path the gate takes (no profile named) hashes to the same values as naming fitness."""
    labels = profiles_report.tuning_labels()
    baseline = json.loads(profiles_report.BASELINE.read_text())["takes"]
    some = {"takes": labels["takes"][::13]}
    assert profiles_report.fitness_digests(some) == {t["take_id"]: baseline[t["take_id"]] for t in some["takes"]}


def test_the_digest_ignores_where_the_repository_lives_and_what_the_feature_added():
    a = {"profile": "rehab", "schema_version": "1.7.0", "expected": {"path": f"{ROOT}/x.json"}, "faults": []}
    b = {"schema_version": "1.6.0", "expected": {"path": "/elsewhere/checkout/x.json"}, "faults": []}
    assert profiles_report.analysis_digest(a, ROOT) == profiles_report.analysis_digest(
        {**b, "expected": {"path": f"{ROOT}/x.json"}}, ROOT)
    assert profiles_report.analysis_digest(a, ROOT) == profiles_report.analysis_digest(
        {"expected": {"path": "x.json"}, "faults": []}, ROOT)
    assert profiles_report.analysis_digest(a, ROOT) != profiles_report.analysis_digest(
        {"expected": {"path": "x.json"}, "faults": [1]}, ROOT)


# --- AC-PROF-04: an explained fault stays explained ---
def synthetic_detect(rules, shifts, n=60):
    """`detect` on measure series that all agree with the example except `shifts` ({name: degrees}), each held over
    frames 10 to 50 (68% of the clip), with the identity alignment."""
    exp_m = {name: np.zeros(n) for name in MEASURES}
    fol_m = {name: np.zeros(n) for name in MEASURES}
    for name, degrees in shifts.items():
        fol_m[name][10:51] = degrees
    ident = np.arange(n)
    alignment = Alignment([(i, i) for i in range(n)], ident, np.linspace(0, 1, n), 0.0, [])
    return detect(exp_m, fol_m, alignment, rules)


def found(faults):
    return {(f.measure, f.side, f.direction) for f in faults}


# (cause, effect): the cause clears fitness's threshold but not dance's or rehab's; the effect clears its own, looser, one.
EXPLAINED = {
    "foot_out explains thigh_out": (("left_foot_out", 7.0), ("left_thigh_out", 25.0)),
    "knee_valgus explains knee_flexion": (("left_knee_valgus", 10.0), ("left_knee_flexion", 15.0)),
    "knee_valgus explains thigh_out, the other way": (("left_knee_valgus", 10.0), ("left_thigh_out", -25.0)),
    "trunk_lean_forward explains thigh_forward": (("trunk_lean_forward", 10.0), ("left_thigh_forward", 25.0)),
    "trunk_lean_forward explains upper_arm_forward": (("trunk_lean_forward", 10.0), ("left_upper_arm_forward", 25.0)),
    "trunk_lean_forward explains head_forward": (("trunk_lean_forward", 10.0), ("head_forward", 35.0)),
}


@pytest.mark.parametrize("case", EXPLAINED)
def test_explained_fault_stays_explained_when_its_cause_is_tolerated(case):
    (cause, cause_deg), (effect, effect_deg) = EXPLAINED[case]
    rules = load_rules()
    shifts = {cause: cause_deg, effect: effect_deg}
    plain = found(synthetic_detect(rules, shifts))
    cause_key = (cause.removeprefix("left_"), "left" if cause.startswith("left_") else "center",
                 "more")
    effect_key = (effect.removeprefix("left_"), "left" if effect.startswith("left_") else "center",
                  "more" if effect_deg > 0 else "less")
    assert plain == {cause_key}, "fitness reports the cause and not the effect it explains"
    for name in ("dance", "rehab"):
        assert found(synthetic_detect(profiles.effective_rules(rules, name), shifts)) == set(), name
    # once the effect is alone, it is a fault in every profile that does not tolerate it (so the pair is the test)
    alone = {effect: effect_deg}
    assert found(synthetic_detect(rules, alone)) == {effect_key}
    assert found(synthetic_detect(profiles.effective_rules(rules, "rehab"), alone)) == {effect_key}


@pytest.mark.parametrize("case", EXPLAINED)
def test_naive_multipliers_would_fail(case):
    """The same cases on rules whose thresholds were multiplied and that carry no baseline do report the effect: the
    construction in detect.py is what keeps a profile loosen-only, and this test would notice if it were dropped."""
    (cause, cause_deg), (effect, effect_deg) = EXPLAINED[case]
    shifts = {cause: cause_deg, effect: effect_deg}
    for name in ("dance", "rehab"):
        naive = {k: v for k, v in profiles.effective_rules(load_rules(), name).items() if k != "profile"}
        reported = found(synthetic_detect(naive, shifts))
        assert reported and all(measure == effect.removeprefix("left_") for measure, _, _ in reported), (case, name)


# --- AC-PROF-05 and AC-PROF-06: dance and rehab only loosen, and keep every range fault ---
def test_covered_handles_both_sides():
    def f(side="left", measure="thigh_out", direction="more"):
        return {"measure": measure, "side": side, "direction": direction}

    covered = profiles_report.covered
    assert covered(f("left"), [f("both")]) and covered(f("right"), [f("both")])
    assert covered(f("both"), [f("both")])
    assert covered(f("both"), [f("left"), f("right")])
    assert not covered(f("both"), [f("left")])
    assert not covered(f("left"), [f("right")])
    assert not covered(f(direction="less"), [f()]) and not covered(f(measure="foot_out"), [f()])
    assert covered(f("center", "trunk_lean_forward"), [f("center", "trunk_lean_forward")])
    assert not covered(f(), [])
    assert profiles_report.uncovered([f("left"), f("both", "foot_out")], [f("both")]) == [f("both", "foot_out")]


def test_covered_by_is_the_same_definition_on_keys():
    key = lambda side="left", measure="thigh_out", direction="more": (measure, side, direction)   # noqa: E731
    covered_by = profiles.covered_by
    assert covered_by(key("left"), [key("both")]) and covered_by(key("right"), [key("both")])
    assert covered_by(key("both"), [key("left"), key("right")]) and not covered_by(key("both"), [key("left")])
    assert not covered_by(key("left"), [key("right")]) and not covered_by(key(), [])
    assert not covered_by(key(direction="less"), [key()]) and not covered_by(key(measure="foot_out"), [key()])
    assert covered_by(key("center", "trunk_lean_forward"), [key("center", "trunk_lean_forward")])
    assert profiles.sides_of("both") == {"left", "right"} and profiles.sides_of("center") == {"center"}


@pytest.mark.parametrize("name", ["dance", "rehab"])
@pytest.mark.parametrize("shifts", [
    {"left_thigh_out": 25.0},                                            # one side
    {"left_thigh_out": 25.0, "right_thigh_out": 25.0},                   # both sides, merged
    {"left_thigh_out": 18.0, "right_thigh_out": 30.0, "left_knee_flexion": -20.0},
    {"left_foot_out": 7.0, "left_thigh_out": 25.0},                      # an explained fault
    {"trunk_lean_forward": 12.0, "head_forward": 35.0},
])
def test_fitness_rules_detect_what_the_plain_rules_detect(name, shifts):
    """`fitness_rules` undoes `effective_rules`: detection on it equals detection on the rules the profile was built from."""
    rules = load_rules()
    effective = profiles.effective_rules(rules, name)
    assert profiles.fitness_rules(effective) is not effective and "profile" not in profiles.fitness_rules(effective)
    assert synthetic_detect(profiles.fitness_rules(effective), shifts) == synthetic_detect(rules, shifts)
    assert "profile" in effective and effective["measures"] != rules["measures"]   # and it did not change the input


def test_fitness_rules_of_plain_rules_are_those_rules():
    rules = load_rules()
    assert profiles.fitness_rules(rules) is rules and profiles.fitness_rules(profiles.effective_rules(rules, "fitness")) is rules


def test_dance_and_rehab_never_report_a_fault_fitness_does_not(seed5, kit):
    runs, _ = seed5
    for label, sets in (("seed 5", runs), ("kit", kit)):
        base = sets["fitness"]
        for name in ("dance", "rehab"):
            for take_id, a in sets[name].items():
                extra = profiles_report.uncovered(a["faults"], base[take_id]["faults"])
                assert extra == [], (label, name, take_id)
                if not base[take_id]["faults"]:
                    assert a["faults"] == [], (label, name, take_id)
    total = {name: sum(len(a["faults"]) for a in runs[name].values()) for name in NAMES}
    assert total["dance"] < total["fitness"] and total["rehab"] < total["fitness"]   # the profiles do loosen something


RANGE_KEYS = ("measure", "side", "direction", "magnitude_deg", "threshold_deg")


def test_range_faults_equal_fitness(seed5, kit):
    runs, _ = seed5

    def ranged(a):
        return sorted(tuple(f[k] for k in RANGE_KEYS) for f in a["faults"] if f["measure"] in RANGE)

    for sets in (runs, kit):
        for name in ("dance", "rehab"):
            for take_id, a in sets[name].items():
                assert ranged(a) == ranged(sets["fitness"][take_id]), (name, take_id)
    assert any(ranged(a) for a in runs["fitness"].values())   # the comparison is not vacuous


# --- AC-PROF-07: rehab says "Slower is fine" ---
def test_cue_overrides():
    rehab = profiles.tempo_of(profiles.effective_rules(load_rules(), "rehab"))["cues"]
    assert cues.tempo_cue(1.3, rehab) == "Slower is fine"
    assert cues.tempo_cue(0.7, rehab) == cues.SLOW_DOWN and cues.tempo_cue(1.0, rehab) is None
    assert cues.tempo_cue(1.3) == cues.SPEED_UP and cues.tempo_cue(1.3, {}) == cues.SPEED_UP
    assert cues.tempo_cue(1.3, {"slow_down": "Easy"}) == cues.SPEED_UP and cues.tempo_cue(0.5, {"slow_down": "Easy"}) == "Easy"
    assert cues.tempo_cue(None, rehab) is None
    assert cues.tempo_block(1.301, rehab) == {"ratio": 1.3, "cue": "Slower is fine"}
    assert cues.tempo_block(1.301) == {"ratio": 1.3, "cue": cues.SPEED_UP}
    assert len("Slower is fine".split()) == 3


# --- AC-PROF-08: dance weights tempo, the score params stay frozen ---
def test_tempo_charge_follows_the_profile_block():
    dance = {"cues": {}, "weight": 40.0, "cap": 20.0}
    none = {"cues": {}, "weight": 0.0, "cap": 0.0}
    assert score.tempo_charge(1.40, dance) == pytest.approx(10.0) and score.tempo_charge(2.0, dance) == 20.0
    assert score.tempo_charge(None, dance) == 0.0 and score.tempo_charge(1.0, dance) == 0.0
    assert score.tempo_charge(1.151, dance) == 0.0   # worked from the ratio the document shows (1.15)
    assert score.tempo_charge(1.40, none) is None and score.tempo_charge(None, none) is None


def windows_of(a):
    return [w for w in a["score"].get("timeline", []) if w["compared"]]


def test_dance_score_adds_up(seed5):
    runs, _ = seed5
    charged = 0
    for take_id, a in runs["dance"].items():
        s = a["score"]
        if "capped_by" in s or not s["value"]:
            continue
        for w in windows_of(a):
            ratio = w["tempo"]["ratio"]
            want = 0.0 if ratio is None else min(20.0, 40.0 * max(0.0, cues.TEMPO_FAST - ratio, ratio - cues.TEMPO_SLOW))
            assert w["components"]["tempo"] == pytest.approx(want, abs=0.006), (take_id, ratio)
            if w["value"]:
                parts = w["components"]
                assert abs(100 - w["value"] - (parts["faults"] + parts["similarity"] + parts["tempo"])) <= TOLERATED
                assert w["grade"] == score.grade(w["value"])
        parts = s["components"]
        before_cap = s.get("uncapped", s)["value"]   # simon.score.v2 (ADR-0018): the value the components add up to
        assert abs(100 - before_cap - (parts["faults"] + parts["similarity"] + parts["tempo"])) <= TOLERATED, take_id
        assert parts["tempo"] == pytest.approx(sum(w["components"]["tempo"] for w in windows_of(a)) / len(windows_of(a)),
                                               abs=0.006)
        charged += parts["tempo"] > 0
    assert charged, "no seed 5 take is charged for tempo under dance"


def test_dance_charge_lowers_the_value_for_the_same_faults(seed5):
    runs, _ = seed5
    lowered = 0
    for take_id, a in runs["dance"].items():
        if a["score"]["components"].get("tempo", 0.0) > 1.0:
            fit = runs["fitness"][take_id]
            same_faults = {(f["measure"], f["side"], f["direction"]) for f in a["faults"]} == \
                          {(f["measure"], f["side"], f["direction"]) for f in fit["faults"]}
            if same_faults and "capped_by" not in a["score"]:
                lowered += a["score"]["value"] < fit["score"]["value"]
    assert lowered


def test_only_dance_has_a_tempo_component(seed5):
    runs, _ = seed5
    for name in NAMES:
        for take_id, a in runs[name].items():
            if a["score"].get("basis") == "reps" or not windows_of(a):
                continue
            inside = [("components" in w and "tempo" in w["components"]) for w in windows_of(a)]
            assert all(inside) == (name == "dance") and any(inside) == (name == "dance"), (name, take_id)
            assert ("tempo" in a["score"]["components"]) == (name == "dance"), (name, take_id)
    for a in runs["dance"].values():   # a take nothing could be compared on has no tempo component (zero block)
        if not windows_of(a):
            assert "tempo" not in a["score"]["components"]


def test_score_params_are_untouched_by_a_profile(seed5):
    runs, _ = seed5
    rules = load_rules()
    want = score.params_sha256(rules["score"])
    assert len({a["score"]["params_sha256"] for name in NAMES for a in runs[name].values()}) == 1
    assert {a["score"]["params_sha256"] for a in runs["dance"].values()} == {want}
    for name in ("dance", "rehab"):
        out = profiles.effective_rules(rules, name)
        assert json.dumps(out["score"], sort_keys=True) == json.dumps(rules["score"], sort_keys=True)
        assert score.params_sha256(out["score"]) == want


def test_tempo_insight_points_for_dance_only(seed5):
    runs, _ = seed5
    seen = {name: 0 for name in NAMES}
    for name in NAMES:
        for take_id, a in runs[name].items():
            for item in tempo_items(a):
                seen[name] += 1
                want = a["score"]["components"]["tempo"] if name == "dance" else None
                assert item["points"] == want, (name, take_id)
    assert all(seen.values())


# --- AC-PROF-NFR-01: determinism ---
def test_profiles_are_deterministic(seed5, tmp_path):
    _, labels = seed5
    take = next(t for t in labels["takes"] if t["faults"])
    for name in ("dance", "rehab"):
        a, b = (profiles_report.analyse_take(take, profile=name) for _ in range(2))
        write_analysis(tmp_path / "a.json", a)
        write_analysis(tmp_path / "b.json", b)
        assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()
        assert a["profile"] == name
