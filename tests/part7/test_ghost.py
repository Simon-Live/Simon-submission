"""The trainer's 2D ghost route (docs/specs/follow-ghost.md, TICKET-264)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from part7 import ghost
from part7.skeleton2d import JOINTS


def _anim(frames: int = 3, fps: int = 30) -> dict[str, Any]:
    out = []
    for i in range(frames):
        joints = {n: [0.0, 0.0, 0.0] for n in JOINTS}
        joints["nose"] = [0.1, 0.8 + 0.01 * i, 0.0]
        joints["left_ankle"] = [0.2, -0.8, 0.0]
        joints["right_ankle"] = [-0.2, -0.8, 0.0]
        out.append({"index": i, "t": i / fps, "joints": joints})
    return {"format": "simon.animation.v1", "fps": fps, "joints": list(JOINTS), "frames": out}


def _skeleton() -> dict[str, Any]:
    joints = {n: {"x": 0.0, "y": 0.0, "z": 0.0, "conf": 1.0} for n in JOINTS}
    joints["nose"] = {"x": 0.0, "y": 1.0, "z": 0.0, "conf": 1.0}
    joints["left_wrist"] = {"x": 0.3, "y": 0.5, "z": 0.0, "conf": 0.0}  # unseen: not drawn
    return {"format": "simon.skeleton.v1", "frames": [{"frame": 0, "t_ms": 500.0, "people": [{"id": 0, "joints": joints}]}]}


class Child:
    def __init__(self, manifest: dict[str, Any] | None, files: dict[str, Any]) -> None:
        self.manifest, self.files = manifest, files

    def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        return self.manifest

    def get_entry_file(self, entry_id: str, name: str) -> bytes | None:
        doc = self.files.get(name)
        return None if doc is None else (doc if isinstance(doc, bytes) else json.dumps(doc).encode())


class H:
    def __init__(self, child: Child) -> None:
        self.app = SimpleNamespace(child=child)
        self.sent: list[tuple[int, Any]] = []

    def _json(self, status: int, body: Any) -> None:
        self.sent.append((status, body))

    def _error(self, status: int, msg: str) -> None:
        self.sent.append((status, {"error": msg}))


def test_build_scales_the_body_height_to_one_in_the_camera_view() -> None:
    doc = ghost.build(_anim())
    assert doc is not None and doc["format"] == "simon.skeleton2d.v1" and doc["box"] == "body" and doc["mirrored"] is False
    assert doc["joints"] == list(JOINTS) and len(doc["frames"]) == 3
    assert [f["t"] for f in doc["frames"]] == [0.0, 0.033, 0.067]
    first = doc["frames"][0]["pts"]
    nose, left_ankle, right_ankle = first[0], first[JOINTS.index("left_ankle")], first[JOINTS.index("right_ankle")]
    # the subject's left is on the image's right (a trainer facing the camera); feet at the bottom
    assert left_ankle[0] > 0.5 > right_ankle[0]
    assert left_ankle[1] == 1.0 and nose[1] < 0.1


def test_build_reads_a_part3_skeleton_and_drops_unseen_joints() -> None:
    doc = ghost.build(_skeleton())
    assert doc is not None and doc["frames"][0]["t"] == 0.5
    assert doc["frames"][0]["pts"][JOINTS.index("left_wrist")] is None


def test_build_refuses_documents_with_no_height() -> None:
    assert ghost.build(None) is None
    assert ghost.build({"frames": []}) is None
    flat = {"frames": [{"t": 0, "joints": {n: [0, 0, 0] for n in JOINTS}}]}
    assert ghost.build(flat) is None


def test_route_answers_the_animation_first() -> None:
    h = H(Child({"id": "squat", "animation": "animation.json", "skeleton": "skeleton.json"},
                {"animation.json": _anim(), "skeleton.json": _skeleton()}))
    assert ghost.handle(h, "GET", "ghost/squat.json") is True
    status, body = h.sent[0]
    assert status == 200 and body["source"] == "animation" and body["available"] is True and body["entry_id"] == "squat" and len(body["frames"]) == 3


def test_route_falls_back_to_the_skeleton_when_the_animation_is_unreadable() -> None:
    h = H(Child({"id": "squat", "animation": "animation.json", "skeleton": "skeleton.json"},
                {"animation.json": b"not json", "skeleton.json": _skeleton()}))
    ghost.handle(h, "GET", "ghost/squat.json")
    assert h.sent[0][0] == 200 and h.sent[0][1]["source"] == "skeleton"


def test_route_404s_and_ignores_other_routes() -> None:
    h = H(Child(None, {}))
    assert ghost.handle(h, "GET", "ghost/squat.json") is True
    assert h.sent == [(404, {"error": ghost.MSG_ENTRY})]
    h2 = H(Child({"id": "squat"}, {}))
    ghost.handle(h2, "GET", "ghost/squat.json")
    assert h2.sent == [(200, {"available": False, "entry_id": "squat", "reason": ghost.MSG_NONE})]  # no console 404
    h3 = H(Child({"id": "squat"}, {}))
    assert ghost.handle(h3, "GET", "ghost/../etc.json") is False
    assert ghost.handle(h3, "POST", "ghost/squat.json") is False
    assert ghost.handle(h3, "GET", "ghosts/squat.json") is False
    assert h3.sent == []


# ----- through the running app (part7/server.py) -----------------------------------------------------------------
def test_app_route_answers_the_ghost_and_the_no_ghost_case(api: Any) -> None:
    from test_ghost import _anim as anim  # same module: the fixture animation

    api.app.child.files = {**api.app.child.files, "animation.json": json.dumps(anim()).encode()}
    status, doc = api.json("GET", "api/ghost/lateral-raise.json")
    assert status == 200 and doc["available"] is True and doc["format"] == "simon.skeleton2d.v1" and len(doc["frames"]) == 3
    status, doc = api.json("GET", "api/ghost/empty.json")
    assert status == 200 and doc == {"available": False, "entry_id": "empty", "reason": ghost.MSG_NONE}
    status, doc = api.json("GET", "api/ghost/not-there.json")
    assert status == 404
