"""Writes tests/part7/skin-weights-vector.json: the shared test vector of the person skin's weights (docs/specs/person-skin.md
AC-PS18). Synthetic, no person's data: 400 vertices scattered around a standing skeleton over five frames with the arms
down, out, up and one forward, so arm and torso costs come close. The expected bones and weights are part7.take_rig's;
web/skin/motion-weights.js must give the same bits (tests/part7/person-skin.unit.test.mjs) and so must Python
(tests/part7/test_person_skin.py). Run from the repo root: python3 tests/part7/skin_weights_vector.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from part7 import take_rig  # noqa: E402

OUT = ROOT / "tests/part7/skin-weights-vector.json"
UNIT = 0.0001
STAND = {"nose": (0, 0.666, 0.097), "left_eye": (0.031, 0.71, 0.068), "right_eye": (-0.031, 0.71, 0.068),
         "left_ear": (0.064, 0.7, 0), "right_ear": (-0.064, 0.7, 0), "left_shoulder": (0.18, 0.5, 0),
         "right_shoulder": (-0.18, 0.5, 0), "left_elbow": (0.2, 0.22, 0), "right_elbow": (-0.2, 0.22, 0),
         "left_wrist": (0.2, -0.04, 0), "right_wrist": (-0.2, -0.04, 0), "left_hip": (0.09, 0, 0), "right_hip": (-0.09, 0, 0),
         "left_knee": (0.09, -0.42, 0), "right_knee": (-0.09, -0.42, 0), "left_ankle": (0.09, -0.84, 0),
         "right_ankle": (-0.09, -0.84, 0)}
ARMS = [  # (left elbow, left wrist); the right arm mirrors it
    ((0.2, 0.22, 0), (0.2, -0.04, 0)), ((0.46, 0.5, 0), (0.72, 0.5, 0)), ((0.2, 0.78, 0), (0.2, 1.04, 0)),
    ((0.18, 0.5, 0.28), (0.18, 0.5, 0.54)), ((0.3, 0.27, 0.1), (0.36, 0.03, 0.15))]


def lcg(seed: int):
    while True:
        seed = (seed * 1103515245 + 12345) % 2**31
        yield seed / 2**31


def main() -> None:
    rnd = lcg(7)
    rest = [(-0.35 + 0.7 * next(rnd), -0.95 + 1.8 * next(rnd), -0.15 + 0.3 * next(rnd)) for _ in range(400)]
    frames = []
    for (el, wr) in ARMS:
        joints = {**STAND, "left_elbow": el, "left_wrist": wr, "right_elbow": (-el[0], el[1], el[2]), "right_wrist": (-wr[0], wr[1], wr[2])}
        # a vertex nearer the arm at rest moves with the left or right arm (rigidly by the forearm's shift), the rest stay
        moved = []
        for (x, y, z) in rest:
            s = 1 if x >= 0 else -1
            if abs(x) > 0.16 and -0.1 < y < 0.55:
                dx, dy, dz = wr[0] * s - STAND["left_wrist"][0] * s, wr[1] - STAND["left_wrist"][1], wr[2] - STAND["left_wrist"][2]
                moved.append((x + dx, y + dy, z + dz))
            else:
                moved.append((x, y, z))
        frames.append({"block": [round(v / UNIT) for p in moved for v in p], "joints": {n: list(joints[n]) for n in take_rig.COCO}})
    doc = {"unit_m": UNIT, "vertex_count": len(rest), "frames": frames}
    bones, weights = take_rig.motion_weights(inputs(doc))
    doc["expected"] = {"bones": list(take_rig.NAMES), "bone": [b for pair in bones for b in pair], "weight": [w for pair in weights for w in pair]}
    OUT.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


def inputs(doc: dict) -> list[tuple[list[take_rig.Vec], dict[str, take_rig.Vec]]]:
    """The vector's frames as take_rig.motion_weights takes them: int16 times unit_m in doubles, joints derived."""
    u, n = doc["unit_m"], doc["vertex_count"]
    out = []
    for f in doc["frames"]:
        b = f["block"]
        out.append(([(b[3 * i] * u, b[3 * i + 1] * u, b[3 * i + 2] * u) for i in range(n)],
                    take_rig.derive({k: tuple(v) for k, v in f["joints"].items()})))
    return out


if __name__ == "__main__":
    main()
