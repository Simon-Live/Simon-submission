import json
import shutil
import subprocess

import pytest
from test_canonical import _body3d

from part2 import demo, frames
from part2.canonical import convert
from part2.joints import BONES, CANONICAL


@pytest.fixture
def run_dir(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(3):
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=1280x720", "-frames:v", "1",
                        str(src / f"{i}.jpg")], check=True)
    run = tmp_path / "run"
    frames.ingest(src, run / "frames", fps=10)
    pose3d, camera = convert(_body3d([0, 30, 60]))
    for f in pose3d["frames"]:
        f["t_ms"] = f["frame"] * 100.0
    (run / "pose3d.json").write_text(json.dumps(pose3d))
    (run / "camera.json").write_text(json.dumps(camera))
    return run


needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def test_bones_use_canonical_joints():
    assert all(a in CANONICAL and b in CANONICAL for a, b in BONES) and len(BONES) == 16


@needs_ffmpeg
def test_viewer_embeds_sequence(run_dir):
    html = demo.viewer(run_dir).read_text()
    data = json.loads(html.split("const D = ", 1)[1].split(";\n", 1)[0])
    assert data["id"] == 0 and len(data["frames"]) == 3 and len(data["frames"][0]["joints"]) == 17
    assert data["frames"][0]["file"] == "frames/000000.jpg"


def test_viewer_embed_inlines_frames(run_dir, tmp_path):
    out = demo.viewer(run_dir, out=tmp_path / "v.html", embed=True)  # away from run_dir/frames
    data = json.loads(out.read_text().split("const D = ", 1)[1].split(";\n", 1)[0])
    assert all(f["file"].startswith("data:image/jpeg;base64,") for f in data["frames"])


@needs_ffmpeg
def test_overlay_writes_video_with_all_frames(run_dir):
    out = demo.overlay(run_dir)
    n = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                        "stream=nb_read_frames", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout
    assert int(n.strip()) == 3


def test_colors_stable_per_id():
    assert demo.color_for(3) == demo.color_for("3") != demo.color_for(4)


def test_string_id_colors_are_stable():
    assert demo.color_for("person_a") == demo.COLORS[__import__("zlib").crc32(b"person_a") % len(demo.COLORS)]


@needs_ffmpeg
def test_viewer_unknown_id_is_an_error(run_dir):
    with pytest.raises(ValueError, match="available ids"):
        demo.viewer(run_dir, person_id="7")
