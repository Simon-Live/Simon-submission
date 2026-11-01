"""The trainer's unseen joints from Part 3's skeleton (trainer_visibility.py, compare-view.md, TICKET-116)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from part7 import jobs, trainer_visibility
from part7.skeleton2d import JOINTS
from support import Api

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "input"
LEGS = [JOINTS.index(n) for n in ("left_knee", "right_knee", "left_ankle", "right_ankle")]


def test_seated_sample_marks_knees_and_ankles_in_every_frame() -> None:
    doc = trainer_visibility.build(FIX / "expected_skeleton_seated.json")
    assert doc is not None and doc["schema"] == "simon.trainer_visibility.v1" and doc["joints"] == list(JOINTS)
    assert len(doc["t"]) == len(doc["unseen"]) == 8 and doc["t"][:2] == [0.0, 0.1]
    assert all(u == sorted(LEGS) for u in doc["unseen"])  # the hips are 1.0 in the sample, as in the issue's take


def test_standing_sample_has_no_unseen_joint() -> None:
    doc = trainer_visibility.build(FIX / "expected_skeleton_standing.json")
    assert doc is not None and all(u == [] for u in doc["unseen"])


def test_committed_browser_fixtures_match_the_builder() -> None:
    for name in ("seated", "standing"):
        built = trainer_visibility.build(FIX / f"expected_skeleton_{name}.json")
        assert json.loads((FIX / f"trainer-visibility-{name}.json").read_text(encoding="utf-8")) == built


def test_threshold_is_the_unseen_mark_not_any_low_value(tmp_path: Path) -> None:
    def frame(conf: Any) -> dict[str, Any]:
        return {"t_ms": 0, "people": [{"id": 0, "joints": {"left_knee": {"x": 0, "y": 0, "z": 0, "conf": conf}}}]}

    path = tmp_path / "s.json"
    for conf, expect in ((0.3, [13]), (0.0, [13]), (0.31, []), (0.9, []), (1.0, []), ("0.3", []), (None, []), (True, [])):
        path.write_text(json.dumps({"fps": 30, "frames": [frame(conf)]}), encoding="utf-8")
        assert trainer_visibility.build(path)["unseen"] == [expect], conf


def test_missing_time_falls_back_to_fps_and_bad_files_give_none(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    people = [{"id": 0, "joints": {}}]
    path.write_text(json.dumps({"fps": 10, "frames": [{"people": people}, {"people": people}, "x", {"people": []}]}), encoding="utf-8")
    assert trainer_visibility.build(path)["t"] == [0.0, 0.1]
    for text in ("{", "[]", '{"frames": []}', '{"frames": [1]}'):
        path.write_text(text, encoding="utf-8")
        assert trainer_visibility.build(path) is None
    assert trainer_visibility.build(tmp_path / "missing.json") is None


def test_route_serves_done_follow_jobs_with_a_skeleton_only(api: Api) -> None:
    def fill(src: str | None):
        def run(ctx: jobs.JobContext) -> dict[str, Any]:
            if src:
                (ctx.dir / "work").mkdir(exist_ok=True)
                (ctx.dir / "work" / "expected_skeleton.json").write_bytes((FIX / src).read_bytes())
            return {"result": {}}
        return run

    def done(kind: str, src: str | None) -> str:
        rec = api.app.queue.submit(kind, fill(src))
        assert api.app.queue.wait(rec["id"], 10)["status"] == "done"
        return rec["id"]

    seated = done("follow", "expected_skeleton_seated.json")
    status, doc = api.json("GET", f"api/results/{seated}/trainer-visibility.json")
    assert status == 200 and doc["unseen"][0] == sorted(LEGS)
    assert api.json("GET", f"api/results/{done('follow', None)}/trainer-visibility.json")[0] == 404
    assert api.json("GET", f"api/results/{done('trainer', 'expected_skeleton_seated.json')}/trainer-visibility.json")[0] == 404
    assert api.json("GET", "api/results/NOTANID/trainer-visibility.json")[0] == 404
