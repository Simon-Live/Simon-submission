"""A result file served to its owner names no server path (prod run on release 8, finding 4)."""

from __future__ import annotations

import json

from part7 import result_paths


def test_absolute_paths_go_and_everything_else_stays() -> None:
    doc = {"expected": {"path": "/srv/firm-prod/state/jobs/a/work/expected.json", "fps": 10},
           "follower": {"path": "/home/x/jobs/a/work/follower/follower.json"},
           "score": {"value": 71.5, "grade": "B"}, "unit": "/", "ratio": "3/4", "note": "see / here",
           "files": ["/tmp/a/b", "kept.json"], "nested": [{"log": "/srv/a/b.log", "name": "n"}]}
    out = json.loads(result_paths.strip(json.dumps(doc).encode()))
    assert out == {"expected": {"fps": 10}, "follower": {}, "score": {"value": 71.5, "grade": "B"}, "unit": "/", "ratio": "3/4",
                   "note": "see / here", "files": ["kept.json"], "nested": [{"name": "n"}]}
    assert b"/srv/" not in result_paths.strip(json.dumps(doc).encode()), "negative: no server path in the answer"


def test_a_file_that_is_not_json_stays_as_it_is() -> None:
    assert result_paths.strip(b"not json") == b"not json"
