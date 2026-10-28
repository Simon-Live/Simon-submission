"""keyframes.json contract checks. These do not call the API."""

import copy
import json
import unittest

from keyframe_finder import from_video
from keyframe_finder.from_video_test import _run, _tracks
from keyframe_finder.label import label_document
from keyframe_finder.schema import FORMAT, SCHEMA_PATH, frame_ms, load_schema, validate

EXAMPLE = SCHEMA_PATH.parent / "keyframes.example.json"


def _built():
    tracks = _tracks()
    frames = len(tracks[7])
    spark = json.dumps(
        {"sections": [{"movement": "squat", "start_s": 0, "end_s": frames / 8.0, "phase_names": ["start", "bottom", "top"]}]}
    )
    return json.loads(json.dumps(from_video.build_document(_run(frames), tracks, spark)))


def _keyframes(document):
    for person in document["people"]:
        for rep in person["repetitions"]:
            yield from rep["keyframes"]


class ContractTest(unittest.TestCase):
    def test_schema_names_the_same_format(self):
        schema = load_schema()
        self.assertEqual(schema["properties"]["format"]["const"], FORMAT)
        self.assertEqual(schema["x-simon-version"], FORMAT)

    def test_example_is_valid(self):
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(validate(example), [])

    def test_built_document_is_valid_and_carries_the_format(self):
        document = _built()
        self.assertEqual(validate(document), [])
        self.assertEqual(next(iter(document)), "format")
        self.assertEqual(document["format"], FORMAT)
        for key in ("video", "fps", "analysis_fps", "spark_names", "quality", "people"):
            self.assertIn(key, document)
        self.assertGreater(len(list(_keyframes(document))), 0)

    def test_frame_is_t_ms_on_the_video_clock(self):
        document = _built()
        for keyframe in _keyframes(document):
            self.assertEqual(keyframe["frame"], int(round(keyframe["t_ms"] / 1000.0 * document["fps"])))

    def test_keyframes_of_a_repetition_run_forward_in_time(self):
        document = _built()
        for person in document["people"]:
            for rep in person["repetitions"]:
                times = [keyframe["t_ms"] for keyframe in rep["keyframes"]]
                self.assertEqual(times, sorted(times))

    def test_t_ms_steps_on_the_analysis_clock(self):
        document = _built()
        steps = {frame_ms(index, document["analysis_fps"]) for index in range(1000)}
        for keyframe in _keyframes(document):
            self.assertIn(keyframe["t_ms"], steps)

    def test_broken_documents_name_the_field(self):
        good = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        cases = [
            (lambda doc: doc.pop("format"), "keyframes.json: missing format"),
            (lambda doc: doc.update(format="simon.keyframes.v1"), "keyframes.json.format: must be"),
            (lambda doc: doc.update(fps=0), "keyframes.json.fps: must be above 0"),
            (
                lambda doc: doc["people"][0]["repetitions"][0]["keyframes"][1].pop("t_ms"),
                "keyframes.json.people[0].repetitions[0].keyframes[1]: missing t_ms",
            ),
            (
                lambda doc: doc["people"][0]["repetitions"][0]["keyframes"][0].update(frame=-1),
                "keyframes.json.people[0].repetitions[0].keyframes[0].frame: must be at least 0",
            ),
            (lambda doc: doc["people"][0].update(id="0"), "keyframes.json.people[0].id: expected integer"),
        ]
        for change, message in cases:
            broken = copy.deepcopy(good)
            change(broken)
            errors = validate(broken)
            self.assertTrue(any(error.startswith(message) for error in errors), (message, errors))

    def test_extra_keys_are_allowed(self):
        document = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        document["note"] = "kept"
        document["people"][0]["repetitions"][0]["keyframes"][0]["reviewed"] = True
        self.assertEqual(validate(document), [])


class LabelTest(unittest.TestCase):
    def test_saved_label_carries_the_format_and_is_valid(self):
        draft = _built()
        payload = {
            "video": draft["video"],
            "fps": draft["fps"],
            "analysis_fps": draft["analysis_fps"],
            "people": draft["people"],
        }
        document = label_document("clip", payload)
        self.assertEqual(document["format"], FORMAT)
        self.assertEqual(document["video"], "inbox/clip.mp4")
        self.assertEqual(validate(document), [])

    def test_label_without_fps_is_refused(self):
        with self.assertRaisesRegex(ValueError, "fps"):
            label_document("clip", {"people": []})


if __name__ == "__main__":
    unittest.main()
