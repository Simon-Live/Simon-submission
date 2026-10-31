"""Tests for `part7.chain` (TICKET-014, 021, AC-H7, AC-H8, AC-H10)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pytest

from part7 import chain, modules, runner
from support import stub_modules
from part7.parts import (
    p1_keyframes,
    p2_pose,
    p3_skeleton,
    p4_animate,
    p5_analyse,
)


def _dummy_lock(state: Path) -> modules.Modules:
    lk = stub_modules(state / "modules")
    return lk


def _ok_step(part: int, cmd: str = "stub") -> runner.Step:
    return runner.Step(
        part=part,
        commit=str(part) * 12,
        argv=[cmd],
        cwd="/tmp",
        exit=0,
        timed_out=False,
        duration_s=0.01,
        log="",
        stdout="",
    )


def _fail_step(part: int, exit_code: int = 1, stdout: str = "error") -> runner.Step:
    return runner.Step(
        part=part,
        commit=str(part) * 12,
        argv=["stub"],
        cwd="/tmp",
        exit=exit_code,
        timed_out=False,
        duration_s=0.01,
        log=stdout,
        stdout=stdout,
    )


def test_trainer_chain_full_success_and_stages(
    tmp_path: Path,
    state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lk = _dummy_lock(state_dir)
    video = tmp_path / "trainer.mp4"
    video.write_bytes(b"video")

    def fake_p1_run(v: Path, w: Path, **kw: Any) -> tuple[runner.Step, Path, None]:
        kf = Path(w) / "keyframes.json"
        kf.parent.mkdir(parents=True, exist_ok=True)
        kf.write_text('{"format": "simon.keyframes/part1"}', encoding="utf-8")
        return (_ok_step(1, "p1"), kf, None)

    def fake_p2_run(v: Path, w: Path, **kw: Any) -> tuple[runner.Step, Path]:
        p = Path(w) / "part2" / "pose3d.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"frames": []}', encoding="utf-8")
        return (_ok_step(2, "p2"), p)

    def fake_p3_part4(pose: Path, kf: Any, w: Path, **kw: Any) -> tuple[list[runner.Step], Path, Path, None]:
        sk = Path(w) / "skeleton.json"
        kfv1 = Path(w) / "keyframes.v1.json"
        sk.write_text('{"format": "simon.skeleton.v1"}', encoding="utf-8")
        kfv1.write_text('{"format": "simon.keyframes.v1"}', encoding="utf-8")
        return ([_ok_step(3, "p3-part4")], sk, kfv1, None)

    def fake_p4_run(sk: Path, kfv1: Path, w: Path, **kw: Any) -> tuple[runner.Step, Path]:
        anim = Path(w) / "part4" / "animation.json"
        anim.parent.mkdir(parents=True, exist_ok=True)
        anim.write_text('{"format": "simon.animation.v1"}', encoding="utf-8")
        return (_ok_step(4, "p4-animate"), anim)

    monkeypatch.setattr(p1_keyframes, "run", fake_p1_run)
    monkeypatch.setattr(p1_keyframes, "doctor", lambda *a, **kw: _ok_step(6, "p6-doc-kf"))
    monkeypatch.setattr(p2_pose, "run", fake_p2_run)
    monkeypatch.setattr(p2_pose, "doctor", lambda *a, **kw: _ok_step(2, "p2-doc"))
    monkeypatch.setattr(p3_skeleton, "part4", fake_p3_part4)
    monkeypatch.setattr(p3_skeleton, "doctor", lambda *a, **kw: _ok_step(3, "p3-doc"))
    monkeypatch.setattr(p4_animate, "validate", lambda kind, *a, **kw: _ok_step(4, f"p4-val-{kind}"))
    monkeypatch.setattr(p4_animate, "run", fake_p4_run)
    monkeypatch.setattr(p5_analyse, "doctor", lambda *a, **kw: _ok_step(5, "p5-doc"))

    stages: list[str] = []
    res = chain.trainer(
        video,
        tmp_path / "work",
        report=stages.append,
        lock=lk,
        state=state_dir,
    )
    assert res["ok"] is True
    assert res["parts"] == {"keyframes": 1, "skeleton": 3, "animation": 4}
    assert stages == ["keyframes", "pose", "skeleton", "animation"]
    assert Path(res["files"]["animation"]).is_file()


def test_trainer_chain_part1_fallback_to_part3_every10(
    tmp_path: Path,
    state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-H8: Part 1 failure takes the `every:10` fallback and records `parts.keyframes: 3` and note."""
    lk = _dummy_lock(state_dir)
    video = tmp_path / "trainer.mp4"
    video.write_bytes(b"video")

    monkeypatch.setattr(
        p1_keyframes,
        "run",
        lambda *a, **kw: (_fail_step(1, 3), None, "key frames from Part 3, Part 1 exited 3"),
    )

    def fake_p2_run(v: Path, w: Path, **kw: Any) -> tuple[runner.Step, Path]:
        p = Path(w) / "part2" / "pose3d.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"frames": []}', encoding="utf-8")
        return (_ok_step(2, "p2"), p)

    seen_kf_arg: list[str] = []

    def fake_p3_part4(pose: Path, kf: Any, w: Path, **kw: Any) -> tuple[list[runner.Step], Path, Path, str]:
        seen_kf_arg.append(str(kf))
        sk = Path(w) / "skeleton.json"
        kfv1 = Path(w) / "keyframes.v1.json"
        sk.write_text('{"format": "simon.skeleton.v1"}', encoding="utf-8")
        kfv1.write_text('{"format": "simon.keyframes.v1"}', encoding="utf-8")
        return ([_ok_step(3, "p3-part4")], sk, kfv1, "retried Part 3 with every:5")

    def fake_p4_run(sk: Path, kfv1: Path, w: Path, **kw: Any) -> tuple[runner.Step, Path]:
        anim = Path(w) / "part4" / "animation.json"
        anim.parent.mkdir(parents=True, exist_ok=True)
        anim.write_text('{"format": "simon.animation.v1"}', encoding="utf-8")
        return (_ok_step(4, "p4-animate"), anim)

    monkeypatch.setattr(p2_pose, "run", fake_p2_run)
    monkeypatch.setattr(p2_pose, "doctor", lambda *a, **kw: _ok_step(2, "p2-doc"))
    monkeypatch.setattr(p3_skeleton, "part4", fake_p3_part4)
    monkeypatch.setattr(p3_skeleton, "doctor", lambda *a, **kw: _ok_step(3, "p3-doc"))
    monkeypatch.setattr(p4_animate, "validate", lambda *a, **kw: _ok_step(4, "p4-val"))
    monkeypatch.setattr(p4_animate, "run", fake_p4_run)
    monkeypatch.setattr(p5_analyse, "doctor", lambda *a, **kw: _ok_step(5, "p5-doc"))

    res = chain.trainer(video, tmp_path / "work", lock=lk, state=state_dir)
    assert res["ok"] is True
    assert seen_kf_arg == ["every:10"]
    assert res["parts"]["keyframes"] == 3
    assert "key frames from Part 3, Part 1 exited 3" in res["note"]
    assert "retried Part 3 with every:5" in res["note"]


def test_chain_stops_at_first_failing_doctor_and_names_it(
    tmp_path: Path,
    state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-H7: `make chain` stops at the first failing step or doctor and names it; exit 1."""
    lk = _dummy_lock(state_dir)
    video = tmp_path / "follower.mp4"
    video.write_bytes(b"video")
    expected = tmp_path / "animation.json"
    expected.write_text("{}", encoding="utf-8")

    def fake_p2_run(v: Path, w: Path, **kw: Any) -> tuple[runner.Step, Path]:
        p = Path(w) / "part2" / "pose3d.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
        return (_ok_step(2, "p2"), p)

    p3_called = False

    def fake_p3_part5(*a: Any, **kw: Any) -> tuple[runner.Step, Path]:
        nonlocal p3_called
        p3_called = True
        return (_ok_step(3), tmp_path / "follower.json")

    monkeypatch.setattr(p2_pose, "run", fake_p2_run)
    monkeypatch.setattr(p2_pose, "doctor", lambda *a, **kw: _fail_step(2, 1, "rejected"))
    monkeypatch.setattr(p3_skeleton, "part5", fake_p3_part5)

    # AC-H7 still holds for the trainer chain; a follower take is never refused, it is analysed as an F
    res = chain.follower(video, expected, tmp_path / "work_f", lock=lk, state=state_dir)
    assert res["ok"] is True and res["status"] == "ok"
    doc = json.loads(Path(res["files"]["analysis"]).read_text(encoding="utf-8"))
    assert doc["status"]["code"] == "ok"
    assert [w["code"] for w in doc["warnings"]] == ["no_person"]
    assert doc["warnings"][0]["reason"] == "pose3d.json was rejected by part 2"
    assert doc["score"]["value"] == 0 and doc["score"]["grade"] == "F" and doc["faults"] == []
    assert "analysed by Part 7 alone" in res["note"]
    assert p3_called is False


def _follower_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    video = tmp_path / "follower.mp4"
    video.write_bytes(b"video")
    expected = tmp_path / "animation.json"
    expected.write_text("{}", encoding="utf-8")

    def fake_p2_run(v: Path, w: Path, **kw: Any) -> tuple[runner.Step, Path]:
        p = Path(w) / "part2" / "pose3d.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
        return (_ok_step(2, "p2"), p)

    monkeypatch.setattr(p2_pose, "run", fake_p2_run)
    monkeypatch.setattr(p2_pose, "doctor", lambda *a, **kw: _ok_step(2, "p2-doc"))
    return video, expected


def test_follower_part3_failure_is_an_analysis_with_no_usable_measures(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video, expected = _follower_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(p3_skeleton, "part5", lambda *a, **kw: (_fail_step(3), tmp_path / "none.json"))
    res = chain.follower(video, expected, tmp_path / "w", lock=_dummy_lock(state_dir), state=state_dir)
    assert res["ok"] is True
    doc = json.loads(Path(res["files"]["analysis"]).read_text(encoding="utf-8"))
    assert [w["code"] for w in doc["warnings"]] == ["no_usable_measures"]
    assert doc["score"]["grade"] == "F"


def test_follower_part5_failure_is_an_analysis_with_no_usable_measures(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video, expected = _follower_inputs(tmp_path, monkeypatch)

    def p3(pose: Path, w: Path, **kw: Any) -> tuple[runner.Step, Path]:
        f = Path(w) / "follower.json"
        f.write_text("{}", encoding="utf-8")
        return (_ok_step(3), f)

    monkeypatch.setattr(p3_skeleton, "part5", p3)
    monkeypatch.setattr(p3_skeleton, "doctor", lambda *a, **kw: _ok_step(3, "p3-doc"))
    monkeypatch.setattr(p5_analyse, "doctor", lambda *a, **kw: _ok_step(5, "p5-doc"))
    monkeypatch.setattr(
        p5_analyse, "run", lambda *a, **kw: (_fail_step(5, 1), tmp_path / "w" / "analysis.json", "failed", [])
    )
    res = chain.follower(video, expected, tmp_path / "w", lock=_dummy_lock(state_dir), state=state_dir)
    assert res["ok"] is True
    doc = json.loads(Path(res["files"]["analysis"]).read_text(encoding="utf-8"))
    assert [w["code"] for w in doc["warnings"]] == ["no_usable_measures"]


def test_follower_infrastructure_failures_stay_failed(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video, expected = _follower_inputs(tmp_path, monkeypatch)

    def busy(*a: Any, **kw: Any) -> Any:
        raise TimeoutError

    monkeypatch.setattr(p2_pose, "run", busy)
    res = chain.follower(video, expected, tmp_path / "w", lock=_dummy_lock(state_dir), state=state_dir)
    assert res["ok"] is False and res["stage"] == "pose"
    assert "busy" in res["error"]


def test_follower_chain_accepts_part5_exit_0_and_exit_3(
    tmp_path: Path,
    state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lk = _dummy_lock(state_dir)
    video = tmp_path / "follower.mp4"
    video.write_bytes(b"video")
    expected = tmp_path / "animation.json"
    expected.write_text("{}", encoding="utf-8")

    def fake_p2_run(v: Path, w: Path, **kw: Any) -> tuple[runner.Step, Path]:
        p = Path(w) / "part2" / "pose3d.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
        return (_ok_step(2, "p2"), p)

    def fake_p3_part5(pose: Path, w: Path, **kw: Any) -> tuple[runner.Step, Path]:
        f = Path(w) / "follower.json"
        f.write_text("{}", encoding="utf-8")
        return (_ok_step(3, "p3-part5"), f)

    def fake_p5_run(exp: Path, fol: Path, w: Path, **kw: Any) -> tuple[runner.Step, Path, str, list[str]]:
        out = Path(w) / "analysis.json"
        out.write_text(
            json.dumps({"format": "simon.analysis.v1", "status": {"code": "different_movement"}, "faults": []}),
            encoding="utf-8",
        )
        s = _ok_step(5, "p5-analyse")
        s["exit"] = 3
        return (s, out, "different_movement", [])

    monkeypatch.setattr(p2_pose, "run", fake_p2_run)
    monkeypatch.setattr(p2_pose, "doctor", lambda *a, **kw: _ok_step(2, "p2-doc"))
    monkeypatch.setattr(p3_skeleton, "part5", fake_p3_part5)
    monkeypatch.setattr(p3_skeleton, "doctor", lambda *a, **kw: _ok_step(3, "p3-doc"))
    monkeypatch.setattr(p5_analyse, "doctor", lambda *a, **kw: _ok_step(5, "p5-doc"))
    monkeypatch.setattr(p5_analyse, "run", fake_p5_run)

    stages: list[str] = []
    res = chain.follower(
        video,
        expected,
        tmp_path / "work_refused",
        report=stages.append,
        lock=lk,
        state=state_dir,
    )
    assert res["ok"] is True
    assert res["status"] == "different_movement"
    assert stages == ["pose", "skeleton", "analyse"]
