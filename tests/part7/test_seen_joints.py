"""TICKET-376: a joint Part 2 marked unseen (conf 0.3) is not drawn on the result: not in the 2D overlay and not in
the 3D replay's stick figure. Fixture shaped like take 69842f939ab0: ankles 0.3 in every frame, a knee 0.3 in some."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from part7 import models_used, replay
from part7.skeleton2d import JOINTS

K = [[434.0, 0.0, 320.0], [0.0, 434.0, 240.0], [0.0, 0.0, 1.0]]
ROT = [[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]]
FRAMES = 4
BODY = {"nose": (0, 0.6, 0), "left_hip": (0.1, 0, 0), "right_hip": (-0.1, 0, 0), "left_knee": (0.1, -0.4, 0),
        "right_knee": (-0.1, -0.4, 0), "left_ankle": (0.1, -0.8, 0), "right_ankle": (-0.1, -0.8, 0)}
IDX = {n: i for i, n in enumerate(JOINTS)}


def _conf(name: str, frame: int) -> float:
    if name in ("left_ankle", "right_ankle"):
        return 0.3
    return 0.3 if name == "left_knee" and frame in (1, 2) else 1.0


def put_follower(job: Path) -> Path:
    part2 = job / "work" / "follower" / "part2"
    part2.mkdir(parents=True)
    pose = {"frames": [{"frame": i, "t_ms": i * 100.0, "people": [{"id": 0, "joints": {
        n: {"x": BODY.get(n, (0, 0.3, 0))[0], "y": BODY.get(n, (0, 0.3, 0))[1], "z": BODY.get(n, (0, 0.3, 0))[2],
            "conf": _conf(n, i)} for n in JOINTS}}]} for i in range(FRAMES)]}
    cam = {"K": K, "image_size": [640, 480],
           "frames": [{"frame": i, "people": [{"id": 0, "R": ROT, "t": [0.0, 0.0, 2.0]}]} for i in range(FRAMES)]}
    (part2 / "pose3d.json").write_text(json.dumps(pose), encoding="utf-8")
    (part2 / "camera.json").write_text(json.dumps(cam), encoding="utf-8")
    return part2


class H:
    def __init__(self, root: Path) -> None:
        self.app = SimpleNamespace(queue=SimpleNamespace(job_dir=lambda j: root / j))
        self.sent: list[tuple[int, Any]] = []

    def _json(self, status: int, body: Any) -> None:
        self.sent.append((status, body))

    def _error(self, status: int, msg: str) -> None:
        self.sent.append((status, {"error": msg}))


def test_the_overlay_route_leaves_unseen_joints_null_and_keeps_the_hips(tmp_path: Path) -> None:
    job = tmp_path / "69842f939ab0"
    put_follower(job)
    (job / "job.json").write_text(json.dumps({"kind": "follow", "status": "done"}), encoding="utf-8")
    h = H(tmp_path)
    assert models_used.handle(h, "GET", "results/69842f939ab0/skeleton2d.json")
    status, doc = h.sent[0]
    assert status == 200
    for i, frame in enumerate(doc["frames"]):
        pts = frame["pts"]
        assert pts[IDX["left_ankle"]] is None and pts[IDX["right_ankle"]] is None
        assert (pts[IDX["left_knee"]] is None) == (i in (1, 2))
        assert pts[IDX["right_knee"]] is not None
        assert pts[IDX["left_hip"]] is not None and pts[IDX["right_hip"]] is not None


def _replay_doc() -> dict[str, Any]:
    pose = [[0.0, 0.0, 0.0] for _ in JOINTS]
    return {"joints": list(JOINTS), "fps": 10.0, "follower": [pose] * FRAMES,
            "follower_t": [i * 0.1 for i in range(FRAMES)]}


def test_replay_names_the_follower_joints_unseen_per_frame(tmp_path: Path) -> None:
    part2 = put_follower(tmp_path / "j")
    out = replay.follower_unseen(_replay_doc(), part2, None)
    ankles = [IDX["left_ankle"], IDX["right_ankle"]]
    assert out is not None and len(out) == FRAMES
    assert out[0] == sorted(ankles)
    assert out[1] == sorted(ankles + [IDX["left_knee"]])
    assert IDX["left_hip"] not in out[1] and IDX["right_hip"] not in out[1]


def test_replay_bytes_gain_the_field_and_a_missing_part2_leaves_them_alone(tmp_path: Path) -> None:
    part2 = put_follower(tmp_path / "j")
    raw = json.dumps(_replay_doc()).encode()
    doc = json.loads(replay.with_follower_unseen(raw, part2, None))
    assert len(doc["follower_unseen"]) == FRAMES
    assert replay.with_follower_unseen(raw, tmp_path / "none", None) == raw


def test_the_overlay_route_is_gone_for_a_running_job_a_single_job_and_no_job_file(tmp_path: Path) -> None:
    for name, record in (("a" * 12, {"kind": "follow", "status": "running"}), ("b" * 12, {"kind": "single", "status": "done"}),
                         ("c" * 12, None)):
        put_follower(tmp_path / name)
        if record is not None:
            (tmp_path / name / "job.json").write_text(json.dumps(record), encoding="utf-8")
        h = H(tmp_path)
        assert models_used.handle(h, "GET", f"results/{name}/skeleton2d.json")
        assert h.sent[0][0] == 404, name


def test_a_frame_without_the_chosen_person_marks_nothing_and_a_late_first_stamp_still_maps(tmp_path: Path) -> None:
    part2 = put_follower(tmp_path / "j")
    pose = json.loads((part2 / "pose3d.json").read_text(encoding="utf-8"))
    for f in pose["frames"]:
        f["t_ms"] += 500.0  # the clip's first pose stamp is not 0
    pose["frames"][2]["people"][0]["id"] = 7  # person 0 is absent from frame 2
    (part2 / "pose3d.json").write_text(json.dumps(pose), encoding="utf-8")
    doc = _replay_doc()
    doc["follower_t"] = [0.5 + i * 0.1 for i in range(FRAMES)]
    out = replay.follower_unseen(doc, part2, "0")
    assert out is not None
    assert out[1] == sorted([IDX["left_ankle"], IDX["right_ankle"], IDX["left_knee"]])
    assert out[2] == []
    assert out[0] == sorted([IDX["left_ankle"], IDX["right_ankle"]])
