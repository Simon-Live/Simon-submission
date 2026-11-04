import json
from pathlib import Path

from part2.canonical import project_pose3d
from part2.schema import validate_pose3d

OUT = Path(__file__).resolve().parent.parent / "fixtures" / "output"


def test_single_fixture_is_valid_and_projects():
    pose3d = json.loads((OUT / "single" / "pose3d.json").read_text())
    camera = json.loads((OUT / "single" / "camera.json").read_text())
    validate_pose3d(pose3d)
    uv = project_pose3d(pose3d, camera)
    assert len(uv) == sum(len(f["people"]) for f in pose3d["frames"]) > 0
    w, h = camera["image_size"]
    nose = [p["nose"] for p in uv.values()]
    assert all(0 <= u < w and 0 <= v < h for u, v in nose)
