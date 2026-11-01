"""Contract tests: the published schemas, the committed fixtures, and the loader.

Run with `make test`. Standard library only. When the `jsonschema` package is
installed, every verdict is also checked against it, so the small validator in
`simon_anim.contract` cannot drift from JSON Schema draft 2020-12.
"""

from __future__ import annotations

import copy
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from simon_anim import contract  # noqa: E402
from simon_anim.check import fixture_files  # noqa: E402
from simon_anim.interpolate import build_animation  # noqa: E402
from simon_anim.math3d import (  # noqa: E402
    as_quat,
    direction_angle_deg,
    quat_align_hemisphere,
    quat_from_axis_angle,
    quat_normalize,
    quat_to_rotvec,
    v_add,
    v_cross,
    v_dot,
    v_norm,
    v_normalize,
    v_scale,
    v_sub,
)
from simon_anim.skeleton import ROTATED_JOINTS, forward_kinematics, rest_offsets_from_skeleton  # noqa: E402

try:  # optional second witness
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _published(kind: str) -> dict:
    return _load(ROOT / "contracts" / contract.FILES[kind])


def _drop(path: list):
    def apply(doc: dict) -> None:
        node = doc
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]

    return apply


def _set(path: list, value):
    def apply(doc: dict) -> None:
        node = doc
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return apply


def _about(axis, degrees: float) -> tuple:
    return quat_from_axis_angle(axis, math.radians(degrees))


def _arc(a, b) -> tuple:
    """Shortest rotation taking unit vector a onto unit vector b (not antiparallel)."""
    c = v_cross(a, b)
    return quat_normalize((c[0], c[1], c[2], 1.0 + v_dot(a, b)))


def _old_rule_steps(quats: list) -> list[float]:
    """Steps in degrees as f1693dc measured them: rotation vectors kept in 0 to 180 degrees."""
    previous = (0.0, 0.0, 0.0, 1.0)
    vectors = []
    for quat in quats:
        previous = quat_align_hemisphere(as_quat(quat), previous)
        vectors.append(quat_to_rotvec(previous))
    return [math.degrees(v_norm(v_sub(b, a))) for a, b in zip(vectors, vectors[1:])]


def _clip_with(skeleton: dict, joint: str, quats: list) -> dict:
    """Every key of `skeleton` at its first key's pose, except `joint`, which takes `quats` in turn.

    Key positions are the forward kinematics of the new rotations, as Part 3 writes them.
    """
    offsets = rest_offsets_from_skeleton(skeleton)
    first = skeleton["keyframes"][0]["local_rotations"]
    clip = copy.deepcopy(skeleton)
    for key, quat in zip(clip["keyframes"], quats):
        rotations = {name: list(first[name]) for name in ROTATED_JOINTS}
        rotations[joint] = list(quat)
        key["local_rotations"] = rotations
        key["joints"] = {name: list(p) for name, p in forward_kinematics(rotations, offsets).items()}
    return clip


# Each case breaks one rule a schema states. The loader must refuse every one.
KEYFRAMES_BREAKS = {
    "no format": _drop(["format"]),
    "another format": _set(["format"], "simon.keyframes.v2"),
    "fps 60": _set(["fps"], 60),
    "fps as text": _set(["fps"], "30"),
    "no fps": _drop(["fps"]),
    "no duration": _drop(["duration_s"]),
    "no frame_count": _drop(["frame_count"]),
    "frame_count 0": _set(["frame_count"], 0),
    "no keyframes": _drop(["keyframes"]),
    "empty keyframes": _set(["keyframes"], []),
    "key without index": _drop(["keyframes", 0, "index"]),
    "fractional index": _set(["keyframes", 1, "index"], 10.5),
    "negative index": _set(["keyframes", 0, "index"], -1),
    "key without t": _drop(["keyframes", 0, "t"]),
    "t as text": _set(["keyframes", 0, "t"], "0.0"),
}
SKELETON_BREAKS = {
    "no format": _drop(["format"]),
    "another format": _set(["format"], "simon.skeleton/1"),
    "fps 25": _set(["fps"], 25),
    "joints out of order": _set(["joints"], list(reversed(contract.CANONICAL_JOINTS))),
    "no rest_offsets_m": _drop(["rest_offsets_m"]),
    "rest offset missing a joint": _drop(["rest_offsets_m", "left_knee"]),
    "wrong parent": _set(["rest_offsets_m", "left_knee", "parent"], "pelvis"),
    "two-number offset": _set(["rest_offsets_m", "left_knee", "offset"], [0.0, -0.4]),
    "no keyframes": _drop(["keyframes"]),
    "empty keyframes": _set(["keyframes"], []),
    "missing rotation": _drop(["keyframes", 1, "local_rotations", "left_knee"]),
    "three-number rotation": _set(["keyframes", 1, "local_rotations", "left_knee"], [0.0, 0.0, 1.0]),
    "missing joint position": _drop(["keyframes", 0, "joints", "nose"]),
    "two-number position": _set(["keyframes", 0, "joints", "nose"], [0.0, 0.6]),
    "key without local_rotations": _drop(["keyframes", 0, "local_rotations"]),
}
# Each case passes the schema but breaks a rule listed under x-rules. The loader refuses these too.
LOADER_ONLY_BREAKS = {
    "key time off by a millisecond": ("keyframes", _set(["keyframes", 1, "t"], 10 / 30 + 0.001)),
    "repeated key": ("both", _set(["keyframes", 1, "index"], 0)),
    "frame_count off the duration": ("keyframes", _set(["frame_count"], 90)),
    "zero quaternion": ("skeleton", _set(["keyframes", 1, "local_rotations", "left_knee"], [0.0, 0.0, 0.0, 0.0])),
    "zero-length offset": ("skeleton", _set(["rest_offsets_m", "left_knee", "offset"], [0.0, 0.0, 0.0])),
}


class SchemaFilesTest(unittest.TestCase):
    def test_committed_files_match_the_generator(self):
        self.assertEqual(contract.stale_files(), [])

    def test_schemas_are_valid_draft_2020_12(self):
        if jsonschema is None:
            self.skipTest("jsonschema not installed")
        for kind in contract.FILES:
            jsonschema.Draft202012Validator.check_schema(_published(kind))

    def test_validator_refuses_unknown_keywords(self):
        with self.assertRaises(contract.SchemaError):
            contract.validate("x", {"pattern": "^x$"})

    def test_every_schema_names_its_version_field(self):
        for kind in contract.FILES:
            schema = _published(kind)
            self.assertEqual(schema["x-version-field"], "format")
            self.assertEqual(schema["properties"]["format"]["const"], schema["x-simon-version"])


class FixturesConformTest(unittest.TestCase):
    def test_every_committed_fixture_meets_its_schema(self):
        pairs = fixture_files()
        self.assertGreaterEqual(len(pairs), 15)
        for kind, path in pairs:
            with self.subTest(path=str(path.relative_to(ROOT))):
                doc = _load(path)
                self.assertEqual(contract.validate(doc, _published(kind)), [])
                if jsonschema is not None:
                    jsonschema.validate(doc, _published(kind), cls=jsonschema.Draft202012Validator)

    def test_fresh_output_meets_the_animation_schema(self):
        base = ROOT / "fixtures" / "input" / "exercise"
        animation = build_animation(_load(base / "skeleton.json"), _load(base / "keyframes.json"))
        self.assertEqual(contract.validate(json.loads(json.dumps(animation)), _published("animation")), [])

    def test_every_shipped_animation_names_part4_as_producer(self):
        outputs = sorted((ROOT / "fixtures" / "output").glob("*/animation.json"))
        self.assertGreaterEqual(len(outputs), 5)
        for path in outputs:
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertEqual(_load(path)["producer"], "part4")
        self.assertEqual(_published("animation")["properties"]["producer"]["const"], "part4")
        self.assertIn("producer", _published("animation")["required"])


class LoaderRejectsWhatSchemaRejectsTest(unittest.TestCase):
    def setUp(self):
        base = ROOT / "fixtures" / "input" / "exercise"
        self.keyframes = _load(base / "keyframes.json")
        self.skeleton = _load(base / "skeleton.json")

    def _assert_schema_rejects(self, doc: dict, kind: str) -> None:
        self.assertNotEqual(contract.validate(doc, _published(kind)), [])
        if jsonschema is not None:
            self.assertFalse(jsonschema.Draft202012Validator(_published(kind)).is_valid(doc))

    def test_keyframes_breaks(self):
        for name, apply in KEYFRAMES_BREAKS.items():
            with self.subTest(name):
                doc = copy.deepcopy(self.keyframes)
                apply(doc)
                self._assert_schema_rejects(doc, "keyframes")
                with self.assertRaisesRegex(ValueError, "keyframes.json"):
                    build_animation(self.skeleton, doc)

    def test_skeleton_breaks(self):
        for name, apply in SKELETON_BREAKS.items():
            with self.subTest(name):
                doc = copy.deepcopy(self.skeleton)
                apply(doc)
                self._assert_schema_rejects(doc, "skeleton")
                with self.assertRaisesRegex(ValueError, "skeleton.json"):
                    build_animation(doc, self.keyframes)

    def test_rules_beyond_the_schema_are_still_refused(self):
        for name, (target, apply) in LOADER_ONLY_BREAKS.items():
            with self.subTest(name):
                keyframes = copy.deepcopy(self.keyframes)
                skeleton = copy.deepcopy(self.skeleton)
                if target in ("keyframes", "both"):
                    apply(keyframes)
                if target in ("skeleton", "both"):
                    apply(skeleton)
                self.assertEqual(contract.validate(keyframes, _published("keyframes")), [])
                self.assertEqual(contract.validate(skeleton, _published("skeleton")), [])
                with self.assertRaises(ValueError):
                    build_animation(skeleton, keyframes)

    def test_long_way_round_names_joint_and_keys(self):
        # 170 degrees about x, then 170 degrees about z: a near half turn inside one gap.
        skeleton = copy.deepcopy(self.skeleton)
        skeleton["keyframes"][1]["local_rotations"]["left_hip"] = list(_about((1.0, 0.0, 0.0), 170.0))
        for key in skeleton["keyframes"][2:]:
            key["local_rotations"]["left_hip"] = list(_about((0.0, 0.0, 1.0), 170.0))
        self.assertEqual(contract.validate(skeleton, _published("skeleton")), [])
        with self.assertRaisesRegex(ValueError, "left_hip takes the long way between frames 10 and 20"):
            build_animation(skeleton, self.keyframes)

    def test_optional_fields_part3_adds_are_accepted(self):
        skeleton = copy.deepcopy(self.skeleton)
        skeleton["fps"] = 30
        skeleton["producer_note"] = "extra keys are ignored"
        self.assertEqual(contract.validate(skeleton, _published("skeleton")), [])
        build_animation(skeleton, self.keyframes)


class AnimationSchemaIsClosedTest(unittest.TestCase):
    def setUp(self):
        self.animation = _load(ROOT / "fixtures" / "output" / "exercise" / "animation.json")

    def test_breaks(self):
        breaks = {
            "extra top-level field": _set(["extra"], 1),
            "extra frame field": _set(["frames", 0, "confidence"], 1.0),
            "conf that is not a map": _set(["frames", 0, "conf"], 1.0),
            "missing joint": _drop(["frames", 3, "joints", "left_ankle"]),
            "interpolated as text": _set(["frames", 1, "interpolated"], "true"),
            "fps 60": _set(["fps"], 60),
            "another format": _set(["format"], "simon.animation/1"),
            "no movement field": _drop(["movement"]),
            "no producer": _drop(["producer"]),
            "another producer": _set(["producer"], "part5"),
        }
        for name, apply in breaks.items():
            with self.subTest(name):
                doc = copy.deepcopy(self.animation)
                apply(doc)
                self.assertNotEqual(contract.validate(doc, _published("animation")), [])
                if jsonschema is not None:
                    self.assertFalse(jsonschema.Draft202012Validator(_published("animation")).is_valid(doc))


class ShortestArcTest(unittest.TestCase):
    """Key pairs the 180 degree rule of f1693dc refused although the body barely moved (A-P4-07, A-P4-08)."""

    FOLD_DEG = 160.0
    SWINGS_DEG = (0.0, 80.0, 160.0, 80.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    def setUp(self):
        base = ROOT / "fixtures" / "input" / "exercise"
        self.keyframes = _load(base / "keyframes.json")
        self.skeleton = _load(base / "skeleton.json")
        offsets = rest_offsets_from_skeleton(self.skeleton)
        self.upper = v_normalize(offsets["left_elbow"][1])
        self.rest_forearm = v_normalize(offsets["left_wrist"][1])
        self.p1 = v_normalize(v_cross(self.upper, (0.0, 0.0, 1.0)))
        self.p2 = v_cross(self.upper, self.p1)

    def _forearm(self, swing_deg: float) -> tuple:
        """Forearm direction in the upper arm's frame: folded FOLD_DEG back, bend plane turned swing_deg."""
        fold, swing = math.radians(self.FOLD_DEG), math.radians(swing_deg)
        bend = v_add(v_scale(self.p1, math.cos(swing)), v_scale(self.p2, math.sin(swing)))
        return v_add(v_scale(self.upper, math.cos(fold)), v_scale(bend, math.sin(fold)))

    def test_a_folded_elbow_swung_about_the_upper_arm_is_animated(self):
        # Part 3's seated side stretch: the forearm folded 160 degrees, its bend plane swinging
        # 80 degrees per gap. The elbow's own swing changes axis, the forearm moves about 25 degrees.
        quats = [_arc(self.rest_forearm, self._forearm(s)) for s in self.SWINGS_DEG]
        self.assertGreater(max(_old_rule_steps(quats)), 180.0)
        clip = _clip_with(self.skeleton, "left_elbow", quats)
        animation = build_animation(clip, self.keyframes)
        offsets = rest_offsets_from_skeleton(clip)
        first = clip["keyframes"][0]["local_rotations"]
        key_t = [float(k["t"]) for k in self.keyframes["keyframes"]]
        worst = 0.0
        for frame in animation["frames"]:
            t = frame["t"]
            i = min(sum(1 for kt in key_t if kt <= t) - 1, len(key_t) - 2)
            u = min(1.0, (t - key_t[i]) / (key_t[i + 1] - key_t[i]))
            swing = self.SWINGS_DEG[i] + u * (self.SWINGS_DEG[i + 1] - self.SWINGS_DEG[i])
            truth_rot = {name: first[name] for name in ROTATED_JOINTS}
            truth_rot["left_elbow"] = _arc(self.rest_forearm, self._forearm(swing))
            truth = forward_kinematics(truth_rot, offsets)
            got = frame["joints"]
            worst = max(worst, direction_angle_deg(
                v_sub(got["left_wrist"], got["left_elbow"]), v_sub(truth["left_wrist"], truth["left_elbow"])))
            if not frame["interpolated"]:
                self.assertLess(v_norm(v_sub(got["left_wrist"], truth["left_wrist"])), 1e-6)
        self.assertLess(worst, 8.0)

    def test_a_joint_turning_through_180_degrees_is_animated_the_short_way(self):
        # The hip lifts the thigh overhead and just past it (175 to 185 degrees), then back down.
        angles = (0.0, 90.0, 150.0, 175.0, 185.0, 175.0, 150.0, 90.0, 30.0, 0.0)
        quats = [_about((1.0, 0.0, 0.0), a) for a in angles]
        self.assertGreater(max(_old_rule_steps(quats)), 180.0)
        clip = _clip_with(self.skeleton, "left_hip", quats)
        animation = build_animation(clip, self.keyframes)
        rest = v_sub(animation["frames"][0]["joints"]["left_knee"], animation["frames"][0]["joints"]["left_hip"])
        for frame in animation["frames"][30:41]:
            thigh = v_sub(frame["joints"]["left_knee"], frame["joints"]["left_hip"])
            self.assertGreater(direction_angle_deg(thigh, rest), 170.0, f"frame {frame['index']}")

    def test_the_twist_taken_out_moves_no_joint_at_the_keys(self):
        twisted = [list(_about(self.rest_forearm, 30.0 * i)) for i in range(10)]
        self.assertGreater(max(_old_rule_steps(twisted)), 180.0)
        plain = _clip_with(self.skeleton, "left_elbow", [(0.0, 0.0, 0.0, 1.0)] * 10)
        clip = _clip_with(self.skeleton, "left_elbow", twisted)
        a = build_animation(clip, self.keyframes)
        b = build_animation(plain, self.keyframes)
        for fa, fb in zip(a["frames"], b["frames"]):
            for name in contract.CANONICAL_JOINTS:
                self.assertLess(v_norm(v_sub(fa["joints"][name], fb["joints"][name])), 1e-6)


class Part3ViewEndToEndTest(unittest.TestCase):
    def test_part3_view_rebuilds_the_shipped_clip(self):
        base = ROOT / "fixtures" / "input" / "part3-squat"
        keyframes = _load(base / "keyframes.json")
        skeleton = _load(base / "skeleton.json")
        self.assertNotIn("movement", keyframes)
        animation = build_animation(skeleton, keyframes, set_name="part3-squat")
        shipped = _load(ROOT / "fixtures" / "output" / "part3-squat" / "animation.json")
        self.assertEqual(animation["set"], "part3-squat")
        self.assertIsNone(animation["movement"])
        self.assertEqual(animation["frame_count"], len(shipped["frames"]))
        keys = {int(frame["index"]) for frame in keyframes["keyframes"]}
        self.assertEqual({f["index"] for f in shipped["frames"] if not f["interpolated"]}, keys)


UNSEEN = ("left_knee", "right_knee", "left_ankle", "right_ankle")


class VisibilityTest(unittest.TestCase):
    """Part 3's conf 0.3 (joint never seen) reaches animation.json as optional frames[].conf and unseen_joints."""

    def setUp(self):
        base = ROOT / "fixtures" / "input" / "exercise"
        self.keyframes = _load(base / "keyframes.json")
        self.plain = _load(base / "skeleton.json")
        self.skeleton = copy.deepcopy(self.plain)
        for key in self.skeleton["keyframes"]:
            key["conf"] = {name: (0.3 if name in UNSEEN else 1.0) for name in contract.CANONICAL_JOINTS}
        self.keys = [int(k["index"]) for k in self.skeleton["keyframes"]]

    def _build(self, skeleton):
        return json.loads(json.dumps(build_animation(skeleton, self.keyframes, set_name="exercise")))

    def test_unseen_knees_and_ankles_are_not_silently_dropped(self):
        animation = self._build(self.skeleton)
        self.assertEqual(animation["unseen_joints"], list(UNSEEN))
        for frame in animation["frames"]:
            for name in contract.CANONICAL_JOINTS:
                self.assertEqual(frame["conf"][name], 0.3 if name in UNSEEN else 1.0)

    def test_filled_frames_take_the_minimum_of_the_two_neighbouring_keys(self):
        skeleton = copy.deepcopy(self.skeleton)
        skeleton["keyframes"][2]["conf"]["left_wrist"] = 0.3  # one key unseen
        skeleton["keyframes"][3]["conf"]["left_wrist"] = 0.8
        skeleton["keyframes"][3]["conf"]["nose"] = 0.6
        animation = self._build(skeleton)
        k2, k3 = self.keys[2], self.keys[3]
        by_index = {f["index"]: f for f in animation["frames"]}
        self.assertEqual(by_index[k2]["conf"]["left_wrist"], 0.3)
        self.assertEqual(by_index[k3]["conf"]["left_wrist"], 0.8)
        for index in range(k2 + 1, k3):
            self.assertTrue(by_index[index]["interpolated"])
            self.assertEqual(by_index[index]["conf"]["left_wrist"], 0.3)
            self.assertEqual(by_index[index]["conf"]["nose"], 0.6)
        self.assertNotIn("left_wrist", animation["unseen_joints"])

    def test_frames_outside_the_keys_hold_the_nearest_key(self):
        skeleton = copy.deepcopy(self.skeleton)
        skeleton["keyframes"][0]["conf"]["nose"] = 0.5
        skeleton["keyframes"][-1]["conf"]["nose"] = 0.7
        animation = self._build(skeleton)
        self.assertEqual(animation["frames"][0]["conf"]["nose"], 0.5)
        self.assertEqual(animation["frames"][-1]["conf"]["nose"], 0.7)

    def test_a_joint_unseen_at_some_keys_only_is_not_listed(self):
        skeleton = copy.deepcopy(self.skeleton)
        skeleton["keyframes"][4]["conf"]["left_knee"] = 1.0
        self.assertEqual(self._build(skeleton)["unseen_joints"], ["right_knee", "left_ankle", "right_ankle"])

    def test_conf_on_the_joint_object_is_read_when_there_is_no_conf_map(self):
        skeleton = copy.deepcopy(self.plain)
        for key in skeleton["keyframes"]:
            key["joints"]["left_ankle"]["conf"] = 0.3
        animation = self._build(skeleton)
        self.assertEqual(animation["unseen_joints"], ["left_ankle"])
        self.assertEqual(animation["frames"][5]["conf"]["left_ankle"], 0.3)
        self.assertEqual(animation["frames"][5]["conf"]["nose"], 1.0)

    def test_output_is_valid_animation_v1_and_part5_can_read_its_conf(self):
        animation = self._build(self.skeleton)
        self.assertEqual(contract.validate(animation, _published("animation")), [])
        if jsonschema is not None:
            jsonschema.validate(animation, _published("animation"), cls=jsonschema.Draft202012Validator)
        # Part 5 (part5/io.py parse_clip): conf is a joint -> number in 0..1 map on a frame; extra top-level keys are allowed.
        for frame in animation["frames"]:
            self.assertEqual(set(frame["conf"]), set(animation["joints"]))
            self.assertTrue(all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in frame["conf"].values()))

    def test_positions_do_not_depend_on_conf(self):
        with_conf = self._build(self.skeleton)
        without = self._build(self.plain)
        for a, b in zip(with_conf["frames"], without["frames"]):
            self.assertEqual(a["joints"], b["joints"])
            self.assertEqual(a["interpolated"], b["interpolated"])

    def test_full_confidence_everywhere_is_the_same_as_no_conf(self):
        skeleton = copy.deepcopy(self.plain)  # synthetic fixtures carry {x, y, z, conf: 1.0}
        self.assertEqual(skeleton["keyframes"][0]["joints"]["nose"]["conf"], 1.0)
        for key in skeleton["keyframes"]:
            key["conf"] = {name: 1.0 for name in contract.CANONICAL_JOINTS}
        animation = self._build(skeleton)
        self.assertEqual(animation, self._build(self.plain))
        self.assertNotIn("unseen_joints", animation)

    def test_input_without_conf_writes_no_conf_fields(self):
        for key in self.plain["keyframes"]:
            key["joints"] = {n: [p["x"], p["y"], p["z"]] for n, p in key["joints"].items()}
        animation = self._build(self.plain)
        self.assertNotIn("unseen_joints", animation)
        self.assertTrue(all("conf" not in frame for frame in animation["frames"]))
        self.assertEqual(contract.validate(animation, _published("animation")), [])

    def test_a_conf_outside_0_to_1_is_refused(self):
        for bad in (1.5, -0.1, "high"):
            with self.subTest(bad=bad):
                skeleton = copy.deepcopy(self.skeleton)
                skeleton["keyframes"][1]["conf"]["nose"] = bad
                with self.assertRaisesRegex(ValueError, "skeleton.json"):
                    build_animation(skeleton, self.keyframes)

    def test_animation_schema_rejects_malformed_visibility(self):
        animation = self._build(self.skeleton)
        breaks = {
            "conf above 1": _set(["frames", 2, "conf", "nose"], 1.5),
            "conf missing a joint": _drop(["frames", 2, "conf", "nose"]),
            "unknown joint in conf": _set(["frames", 2, "conf", "tail"], 1.0),
            "unseen_joints with a stranger": _set(["unseen_joints"], ["tail"]),
        }
        for name, apply in breaks.items():
            with self.subTest(name):
                doc = copy.deepcopy(animation)
                apply(doc)
                self.assertNotEqual(contract.validate(doc, _published("animation")), [])
                if jsonschema is not None:
                    self.assertFalse(jsonschema.Draft202012Validator(_published("animation")).is_valid(doc))

    def test_shipped_part3_clip_marks_the_ankle_part3_never_saw(self):
        shipped = _load(ROOT / "fixtures" / "output" / "part3-squat" / "animation.json")
        self.assertEqual(shipped["unseen_joints"], ["right_ankle"])
        self.assertEqual(shipped["frames"][0]["conf"]["right_ankle"], 0.3)
        self.assertEqual(shipped["frames"][0]["conf"]["left_ankle"], 1.0)


if __name__ == "__main__":
    unittest.main()
