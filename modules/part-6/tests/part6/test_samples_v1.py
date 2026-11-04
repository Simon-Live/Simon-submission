"""TICKET-031: every bundled sample's animation.json is simon.animation.v1, the file Part 5 accepts.

The six synthetic samples used to carry Part 6's own `simon.animation/1` (schema field,
people[].joints.{x,y,z,conf}); Part 5 reads only `simon.animation.v1`. The mock processor's
recordings keep the old shape (a separate ticket).
"""
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from part6 import catalog, formats, motion, processor, server

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "fixtures" / "output" / "catalog"
SAMPLES = ["arm-wave", "forward-lunge", "hip-twist", "jumping-jack", "side-step", "squat"]
ALL_IDS = SAMPLES + ["part4-squat", "part4-step-touch"]


def tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(Path(root).rglob("*"))
            if p.is_file()}


def load(entry, name):
    return json.loads((CATALOG / entry / name).read_text())


def legacy_animation(v1):
    """The `simon.animation/1` file the older release wrote, rebuilt from its v1 twin."""
    return {"schema": "simon.animation/1", "units": processor.UNITS, "frame": processor.FRAME,
            "joints": v1["joints"], "fps": v1["fps"],
            "frames": [{"frame": f["index"], "t_ms": round(f["t"] * 1000, 3),
                        "interpolated": f["interpolated"],
                        "people": [{"id": 0, "joints": {
                            n: dict(zip("xyz", pos), conf=f["conf"][n])
                            for n, pos in f["joints"].items()}}]} for f in v1["frames"]]}


def part5_accepts(data):
    """The rules of Part 5's input-animation.schema.json and part5.io: format const, fps or a
    per-frame t, canonical joints as [x, y, z] or null, strictly increasing t, hip midpoint within
    1 cm of the origin."""
    assert data["format"] == "simon.animation.v1"
    assert data["fps"] > 0 and data["frames"]
    if "joints" in data:
        assert data["joints"] == list(formats.JOINTS)
    last = None
    for frame in data["frames"]:
        assert set(frame["joints"]) <= set(formats.JOINTS)
        for pos in frame["joints"].values():
            assert pos is None or (len(pos) == 3 and all(isinstance(v, (int, float)) for v in pos))
        left, right = frame["joints"]["left_hip"], frame["joints"]["right_hip"]
        assert all(abs((a + b) / 2) <= 0.01 for a, b in zip(left, right))
        assert last is None or frame["t"] > last
        last = frame["t"]
    return True


@pytest.mark.parametrize("entry", ALL_IDS)
def test_animation_is_simon_animation_v1_given_every_bundled_sample(entry):
    assert part5_accepts(load(entry, "animation.json"))
    assert load(entry, "manifest.json")["provenance"]["animation"]["format"] == "simon.animation.v1"


def test_the_v1_file_plays_the_same_poses_as_the_old_one():
    made = processor.generate("squat", 10000, motion.MotionParams(3.0, 3, 0.5))["animation"]
    assert made["schema"] == "simon.animation/1"
    new = processor.animation_v1(made)
    assert part5_accepts(new) and legacy_animation(new) == made
    a, b = formats.read_animation(new), formats.read_animation(made)
    assert a["fps"] == b["fps"] and len(a["frames"]) == len(b["frames"])
    for fa, fb in zip(a["frames"], b["frames"]):
        assert fa["interpolated"] == fb["interpolated"]
        assert fa["t"] == pytest.approx(fb["t"]) and fa["joints"] == fb["joints"]


def stale_copy(tmp_path):
    """A catalog on disk as the older release seeded it: the six samples as simon.animation/1."""
    root = tmp_path / "root"
    for entry in SAMPLES:
        shutil.copytree(CATALOG / entry, root / entry)
        new = load(entry, "animation.json")
        (root / entry / "animation.json").write_text(
            json.dumps(legacy_animation(new), separators=(",", ":")))
        manifest = json.loads((root / entry / "manifest.json").read_text())
        raw = (root / entry / "animation.json").read_bytes()
        manifest["provenance"]["animation"].update(
            format="simon.animation/1", sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        (root / entry / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return root


def test_upgrade_fixtures_replaces_stale_samples_and_keeps_visitor_entries(tmp_path):
    root = stale_copy(tmp_path)
    shutil.copytree(CATALOG / "part4-squat", root / "mine")
    mine = json.loads((root / "mine" / "manifest.json").read_text())
    mine.update(id="mine", files_source="mock")
    (root / "mine" / "manifest.json").write_text(json.dumps(mine))
    edited = root / "squat" / "animation.json"
    edited.write_text(edited.read_text() + " ")
    before_mine = tree(root / "mine")
    assert sorted(catalog.upgrade_fixtures(root)) == sorted(set(SAMPLES) - {"squat"})
    for entry in set(SAMPLES) - {"squat"}:
        assert tree(root / entry) == tree(CATALOG / entry)
    assert edited.read_text().endswith(" ")                    # a changed file is left alone
    assert tree(root / "mine") == before_mine
    assert catalog.upgrade_fixtures(root) == []                # nothing left to do


def test_upgrade_fixtures_leaves_a_visitor_entry_that_reuses_a_sample_id(tmp_path):
    root = stale_copy(tmp_path)
    manifest = json.loads((root / "arm-wave" / "manifest.json").read_text())
    manifest["files_source"] = "mock"
    (root / "arm-wave" / "manifest.json").write_text(json.dumps(manifest))
    before = tree(root / "arm-wave")
    assert "arm-wave" not in catalog.upgrade_fixtures(root)
    assert tree(root / "arm-wave") == before


def test_serve_upgrades_stale_samples_before_serving(tmp_path, monkeypatch):
    root = stale_copy(tmp_path)

    def stop(*args, **kwargs):
        raise SystemExit

    monkeypatch.setattr(server, "make_server", stop)
    with pytest.raises(SystemExit):
        server.serve(root)
    assert tree(root / "arm-wave") == tree(CATALOG / "arm-wave")
