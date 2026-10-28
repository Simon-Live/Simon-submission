"""Contract tests: the published schemas, the committed fixtures, and the loader.

Run with `make test`. Standard library only. When the `jsonschema` package is
installed, every verdict is also checked against it, so the small validator in
`simon_anim.contract` cannot drift from JSON Schema draft 2020-12.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from simon_anim import contract  # noqa: E402
from simon_anim.check import fixture_files  # noqa: E402
from simon_anim.interpolate import build_animation  # noqa: E402

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
        skeleton = copy.deepcopy(self.skeleton)
        skeleton["keyframes"][1]["local_rotations"]["left_knee"] = [1.0, 0.0, 0.0, -0.05]
        skeleton["keyframes"][2]["local_rotations"]["left_knee"] = [-1.0, 0.0, 0.0, -0.05]
        self.assertEqual(contract.validate(skeleton, _published("skeleton")), [])
        with self.assertRaisesRegex(ValueError, "left_knee takes the long way between frames"):
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
            "extra frame field": _set(["frames", 0, "conf"], 1.0),
            "missing joint": _drop(["frames", 3, "joints", "left_ankle"]),
            "interpolated as text": _set(["frames", 1, "interpolated"], "true"),
            "fps 60": _set(["fps"], 60),
            "another format": _set(["format"], "simon.animation/1"),
            "no movement field": _drop(["movement"]),
        }
        for name, apply in breaks.items():
            with self.subTest(name):
                doc = copy.deepcopy(self.animation)
                apply(doc)
                self.assertNotEqual(contract.validate(doc, _published("animation")), [])
                if jsonschema is not None:
                    self.assertFalse(jsonschema.Draft202012Validator(_published("animation")).is_valid(doc))


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


if __name__ == "__main__":
    unittest.main()
