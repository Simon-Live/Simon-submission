#!/usr/bin/env python3
"""Focused contract tests for schemas + tools/measures.py (stdlib unittest).

Run: python3 -m unittest discover -s tests -v
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import measures  # noqa: E402


def load(rel):
    return json.loads((ROOT / rel).read_text())


class SchemaV020Tests(unittest.TestCase):
    def test_version_bumped(self):
        schema = load("schemas/movement.schema.json")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "0.2.0")
        for name in ("pushup", "arm_phrase"):
            self.assertEqual(load(f"fixtures/{name}.movement.json")["schema_version"], "0.2.0")

    def test_labels_can_store_beats_ratings_and_sync_semantics(self):
        schema = load("schemas/labels.schema.json")
        props = schema["properties"]
        self.assertIn("beats_ms", props)
        self.assertIn("downbeats_ms", props)
        self.assertIn("clip-local", schema["properties"]["sync"]["description"])
        rep_props = props["reps"]["items"]["properties"]
        self.assertIn("human_rating", rep_props)

    def test_movement_can_reference_audio(self):
        schema = load("schemas/movement.schema.json")
        self.assertIn("audio", schema["properties"])
        arm = load("fixtures/arm_phrase.movement.json")
        self.assertIn("audio", arm)


class PoseSimilarityTests(unittest.TestCase):
    def test_reference_mode_fault_pass_scores_worse_than_clean(self):
        for name in ("pushup", "arm_phrase"):
            pkg = load(f"fixtures/{name}.movement.json")
            rule = next(r for r in pkg["rules"] if r["measure"]["type"] == "pose_similarity")
            scores = measures.pose_similarity_per_rep(pkg, rule)
            self.assertAlmostEqual(scores[1], 0.0, places=5)
            self.assertGreater(scores[2], scores[1])
            fired = measures.pose_similarity_fires_per_rep(pkg, rule)
            self.assertEqual(fired[1], False)
            self.assertEqual(fired[2], True)

    def test_mirror_of_asymmetric_count5_is_detectably_different(self):
        pkg = load("fixtures/arm_phrase.movement.json")
        rule = next(r for r in pkg["rules"] if r["measure"]["type"] == "pose_similarity")
        seg = next(p for p in pkg["phases"] if p["rep"] == 1 and p["name"] == "count_5")
        frame = pkg["reference_motion"]["frames"][seg["keyframe_frame"]]["joints"]
        mirrored = measures.mirror_joints(frame)
        same = measures.pose_similarity(frame, frame, rule["measure"]["joints"])
        diff = measures.pose_similarity(mirrored, frame, rule["measure"]["joints"])
        self.assertAlmostEqual(same, 0.0, places=5)
        self.assertGreater(diff, 20.0)

    def test_anterior_check_passes_fixtures_and_rejects_swapped_face(self):
        for name in ("pushup", "arm_phrase"):
            pkg = load(f"fixtures/{name}.movement.json")
            for f in pkg["reference_motion"]["frames"]:
                self.assertTrue(measures.anterior_ok(f["joints"]))
        pkg = load("fixtures/arm_phrase.movement.json")
        joints = pkg["reference_motion"]["frames"][0]["joints"]
        swapped = dict(joints)
        nose = dict(joints["nose"]); nose["z"] = -abs(nose["z"]) - 0.05
        swapped["nose"] = nose
        self.assertFalse(measures.anterior_ok(swapped))


if __name__ == "__main__":
    unittest.main()
