"""`make outputs REFINE=...` (part2.outputs --refine; docs/specs/check-2.md "One-person ladder"): the rungs run on the
one-person modes' body3d.json, the stamp and pose3d provenance name them. Fake 3D backend and fake 2D model."""
import json

import numpy as np
from test_canonical import BODY, K
from test_outputs import FakeBackend, _use, env  # noqa: F401  (env is a pytest fixture)

from part2 import outputs, refine, stamp
from part2.backends import cpu_rtm
from part2.joints import CANONICAL
from part2.lifters import project


class Fake2D:
    """RTMPose stand-in: every box gets the fake backend's skeleton moved 2 cm to the camera's right."""

    def __init__(self):
        self.calls = 0

    def read(self, path):
        return str(path)

    def keypoints(self, img, xyxy):
        self.calls += 1
        X = np.array([BODY[j] for j in CANONICAL]) * [1, -1, -1] + [0.12, 0.3, 4.0]
        n = len(xyxy)
        return np.stack([project(X, K)] * n), np.full((n, 17), 0.9)


def _fake_2d(monkeypatch):
    model = Fake2D()
    loads = []
    monkeypatch.setattr(refine, "load_2d", lambda names: loads.append(list(names)) or model)
    monkeypatch.setattr(cpu_rtm, "_sha256", lambda path: None)
    return model, loads


def test_refine_runs_on_one_person_modes_and_is_stamped(env, monkeypatch, capsys):  # noqa: F811
    _use(monkeypatch, FakeBackend())
    model, loads = _fake_2d(monkeypatch)
    assert outputs.main(["--modes", "single,coco-single", "--refine", "kp2d_fit"], root=env.root) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["single"]["refine"] == ["kp2d-fit"] and summary["coco-single"]["refine"] == ["kp2d-fit"]
    assert loads == [["kp2d-fit"]] and model.calls == 2 + 2  # one 2D model for both modes; two frames, two photos
    for mode in ("single", "coco-single"):
        doc = stamp.load(env.scored / mode)
        assert doc["refine"] == ["kp2d-fit"] and stamp.check(env.scored / mode, env.root) is None
        assert {"part2/refine/__init__.py", "part2/refine/kp2d_fit.py"} <= set(doc["code_files"])
        assert doc["models"][-1]["name"].startswith("rtmpose-x")
    prov = json.loads((env.scored / "single" / "pose3d.json").read_text())["provenance"]
    assert prov["refine"] == ["kp2d-fit"] and prov["models"][-1]["name"].startswith("rtmpose-x")
    assert any("RTMPose-x" in n for n in prov["licence_notes"])
    work = env.root / outputs.WORK / "single"
    before = json.loads((work / "body3d-unrefined.json").read_text())
    after = json.loads((work / "body3d.json").read_text())
    gap = lambda d: np.mean([np.linalg.norm(np.array(p["kp2d"]["nose"]) - np.array(p["kp2d"]["left_hip"]))  # noqa: E731
                             for f in d["frames"] for p in f["people"]])
    assert before["frames"][0]["people"][0]["kp3d_cam"] != after["frames"][0]["people"][0]["kp3d_cam"]
    assert gap(after) > 0


def test_no_refine_leaves_the_stamp_and_provenance_empty(env, monkeypatch, capsys):  # noqa: F811
    _use(monkeypatch, FakeBackend())
    _, loads = _fake_2d(monkeypatch)
    assert outputs.main(["--modes", "single", "--refine", "none"], root=env.root) == 0
    assert "refine" not in json.loads(capsys.readouterr().out)["single"] and loads == []
    assert stamp.load(env.scored / "single")["refine"] == []
    assert json.loads((env.scored / "single" / "pose3d.json").read_text())["provenance"]["refine"] == []


def test_refine_with_a_class_mode_or_an_unknown_rung_exits_2(env, monkeypatch, capsys):  # noqa: F811
    _use(monkeypatch, FakeBackend())
    assert outputs.main(["--refine", "kp2d-fit"], root=env.root) == 2
    assert "--refine applies to one-person modes only; pass --modes single,coco-single" in capsys.readouterr().err
    assert outputs.main(["--modes", "single", "--refine", "nope"], root=env.root) == 2
    assert 'unknown refine rung "nope"' in capsys.readouterr().err
    assert not env.scored.exists()


def test_the_chosen_rungs_are_the_default_for_single_and_coco_only():  # noqa: F811
    real = {m.name: m.refine for m in outputs.modes_for("gpu") + outputs.modes_for("cpu")}
    assert real["single"] == real["coco-single"] == outputs.CHOSEN_RUNGS == ("focal", "kp2d-fit")
    assert real["cpu-single"] == () and real["class"] == () and real["class-local-open"] == ()


def test_make_outputs_applies_a_mode_default_unless_told_none(env, monkeypatch, capsys):  # noqa: F811
    import dataclasses

    _use(monkeypatch, FakeBackend())
    _, loads = _fake_2d(monkeypatch)
    monkeypatch.setattr(outputs, "MODES", [dataclasses.replace(m, refine=("kp2d-fit",) if m.name == "single" else ())
                                           for m in outputs.MODES])
    assert outputs.main(["--modes", "single"], root=env.root) == 0
    assert json.loads(capsys.readouterr().out)["single"]["refine"] == ["kp2d-fit"]
    assert stamp.load(env.scored / "single")["refine"] == ["kp2d-fit"]
    assert outputs.main(["--modes", "single", "--refine", "none"], root=env.root) == 0
    assert stamp.load(env.scored / "single")["refine"] == []
