"""Scorer tests. These do not call the API."""

import unittest

from keyframe_finder.evaluate import score_document


def _key(name, t_ms):
    return {"name": name, "frame": 0, "t_ms": t_ms}


def _doc(reps):
    return {"people": [{"id": 1, "repetitions": reps}]}


class ScoreTest(unittest.TestCase):
    def test_exact_times_pass(self):
        reps = [{"rep": 1, "keyframes": [_key("start", 0), _key("bottom", 1000)]}]
        scored = score_document(_doc(reps), _doc(reps))
        self.assertTrue(scored["pass"])
        self.assertTrue(scored["reps_exact"])
        self.assertEqual(scored["keyframes_hit"], 2)

    def test_boundary_of_three_tenths_passes(self):
        label = _doc([{"rep": 1, "keyframes": [_key("bottom", 1000)]}])
        predicted = _doc([{"rep": 1, "keyframes": [_key("bottom", 1300)]}])
        scored = score_document(label, predicted)
        self.assertTrue(scored["pass"])
        self.assertEqual(scored["max_abs_error_ms"], 300)

    def test_late_keyframe_misses(self):
        label = _doc([{"rep": 1, "keyframes": [_key("bottom", 1000)]}])
        predicted = _doc([{"rep": 1, "keyframes": [_key("bottom", 1400)]}])
        scored = score_document(label, predicted)
        self.assertFalse(scored["pass"])
        self.assertEqual(scored["keyframes_hit"], 0)

    def test_extra_repetition_fails_the_count(self):
        label = _doc([{"rep": 1, "keyframes": [_key("bottom", 1000)]}])
        predicted = _doc(
            [
                {"rep": 1, "keyframes": [_key("bottom", 1000)]},
                {"rep": 2, "keyframes": [_key("bottom", 2000)]},
            ]
        )
        scored = score_document(label, predicted)
        self.assertFalse(scored["reps_exact"])
        self.assertFalse(scored["pass"])

    def test_renamed_pose_still_hits_on_time(self):
        label = _doc([{"rep": 1, "keyframes": [_key("bottom", 1000)]}])
        predicted = _doc([{"rep": 1, "keyframes": [_key("squat_bottom", 1000)]}])
        scored = score_document(label, predicted)
        self.assertTrue(scored["pass"])
        self.assertEqual(scored["name_mismatches"], 1)


if __name__ == "__main__":
    unittest.main()
