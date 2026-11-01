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
        p.write_text('{"frames": [{"frame": 0, "people": [{"id": 0}]}]}', encoding="utf-8")
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
        p.write_text('{"frames": [{"frame": 0, "people": [{"id": 0}]}]}', encoding="utf-8")
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
        p.write_text('{"frames": [{"frame": 0, "people": []}]}', encoding="utf-8")
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
    assert doc["warnings"][0]["reason"] == "No person was found in this video"
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


def _p3_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def p3(pose: Path, w: Path, **kw: Any) -> tuple[runner.Step, Path]:
        f = Path(w) / "follower.json"
        f.write_text("{}", encoding="utf-8")
        return (_ok_step(3), f)

    monkeypatch.setattr(p3_skeleton, "part5", p3)
    monkeypatch.setattr(p3_skeleton, "doctor", lambda *a, **kw: _ok_step(3, "p3-doc"))
    monkeypatch.setattr(p5_analyse, "doctor", lambda *a, **kw: _ok_step(5, "p5-doc"))


def _follow(tmp_path: Path, state_dir: Path, video: Path, expected: Path) -> dict[str, Any]:
    return chain.follower(video, expected, tmp_path / "w", lock=_dummy_lock(state_dir), state=state_dir)


def test_follower_part3_reporting_nothing_measurable_is_an_analysis(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Part 3 exit 2 with its documented empty result ("no person in any frame") is the take's fact."""
    video, expected = _follower_inputs(tmp_path, monkeypatch)
    out = "part3: pose3d.frames: no person in any frame"
    monkeypatch.setattr(p3_skeleton, "part5", lambda *a, **kw: (_fail_step(3, 2, out), tmp_path / "none.json"))
    res = _follow(tmp_path, state_dir, video, expected)
    assert res["ok"] is True and res["status"] == "ok"
    doc = json.loads(Path(res["files"]["analysis"]).read_text(encoding="utf-8"))
    assert [w["code"] for w in doc["warnings"]] == ["no_usable_measures"]
    assert doc["score"]["value"] == 0 and doc["score"]["grade"] == "F"


@pytest.mark.parametrize("exit_code,out", [(1, "Traceback: ValueError boom"), (2, "part3: --person: no such id"),
                                           (137, "Killed")])
def test_follower_part3_crash_is_a_failed_job(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, exit_code: int, out: str
) -> None:
    video, expected = _follower_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(p3_skeleton, "part5", lambda *a, **kw: (_fail_step(3, exit_code, out), tmp_path / "n.json"))
    res = _follow(tmp_path, state_dir, video, expected)
    assert res["ok"] is False and res["stage"] == "skeleton" and res["status"] == "failed"
    assert "No person" not in res["error"]


def test_follower_part5_failure_is_a_failed_job(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video, expected = _follower_inputs(tmp_path, monkeypatch)
    _p3_ok(tmp_path, monkeypatch)
    monkeypatch.setattr(
        p5_analyse, "run", lambda *a, **kw: (_fail_step(5, 1, "part5 analyse: boom"), tmp_path / "w" / "a.json", "failed", [])
    )
    res = _follow(tmp_path, state_dir, video, expected)
    assert res["ok"] is False and res["stage"] == "analyse"
    assert res["error"].endswith("The analysis step failed: boom.")


def test_follower_part5_not_enough_visible_stays_an_analysis(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Part 5 exit 0 with a `not_enough_visible` warning is Part 5's own analysis, passed through unchanged."""
    video, expected = _follower_inputs(tmp_path, monkeypatch)
    _p3_ok(tmp_path, monkeypatch)

    def p5(exp: Path, fol: Path, w: Path, **kw: Any) -> tuple[runner.Step, Path, str, list[str]]:
        out = Path(w) / "analysis.json"
        out.write_text(json.dumps({"status": {"code": "ok"}, "warnings": [{"code": "not_enough_visible"}]}),
                       encoding="utf-8")
        return (_ok_step(5), out, "ok", [])

    monkeypatch.setattr(p5_analyse, "run", p5)
    res = _follow(tmp_path, state_dir, video, expected)
    assert res["ok"] is True and res["files"]["analysis"].endswith("analysis.json")
    assert json.loads(Path(res["files"]["analysis"]).read_text())["warnings"][0]["code"] == "not_enough_visible"


def test_follower_part2_exit_1_with_no_person_message_is_no_person(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video, expected = _follower_inputs(tmp_path, monkeypatch)
    msg = "part2: no person found in 40 frames"
    monkeypatch.setattr(p2_pose, "run", lambda *a, **kw: (_fail_step(2, 1, msg), tmp_path / "w" / "none.json"))
    res = _follow(tmp_path, state_dir, video, expected)
    assert res["ok"] is True and res["status"] == "ok"
    doc = json.loads(Path(res["files"]["analysis"]).read_text(encoding="utf-8"))
    assert [w["code"] for w in doc["warnings"]] == ["no_person"]
    assert doc["status"]["code"] == "ok" and doc["score"]["value"] == 0 and doc["score"]["grade"] == "F"


@pytest.mark.parametrize("code,msg", [
    (4, "part2: anything the new exit code prints"),  # Part 2 TICKET-047: exit 4 is "no person"
    (4, ""),
    (1, "part2: no person found to track"),  # the multi-mode message
])
def test_follower_part2_no_person_by_exit_4_or_multi_mode_message(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, code: int, msg: str
) -> None:
    video, expected = _follower_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(p2_pose, "run", lambda *a, **kw: (_fail_step(2, code, msg), tmp_path / "w" / "none.json"))
    res = _follow(tmp_path, state_dir, video, expected)
    assert res["ok"] is True
    doc = json.loads(Path(res["files"]["analysis"]).read_text(encoding="utf-8"))
    assert [w["code"] for w in doc["warnings"]] == ["no_person"]


def test_part2_exit_4_after_a_timeout_is_not_a_finding() -> None:
    from part7 import failcause
    step = _fail_step(2, 4, "")
    step["timed_out"] = True
    assert failcause.part2_found_nobody(step) is False
    assert failcause.part2_found_nobody(_fail_step(2, 2, "part2: no person found")) is False


CUDA = "part2: the gpu backend needs CUDA and the gpu-cu128 profile (make setup-gpu)"


def test_follower_part2_without_cuda_is_a_failed_job_with_that_cause(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TICKET-103: a Mac with no NVIDIA GPU. Part 2 exit 1 in 0.3 s is the machine's, not the take's."""
    video, expected = _follower_inputs(tmp_path, monkeypatch)
    log = tmp_path / "part2.log"
    log.write_text("starting\n" + CUDA + "\n", encoding="utf-8")
    step = _fail_step(2, 1, CUDA)
    step["log"] = str(log)
    monkeypatch.setattr(p2_pose, "run", lambda *a, **kw: (step, tmp_path / "w" / "none.json"))
    res = _follow(tmp_path, state_dir, video, expected)
    assert res["ok"] is False and res["stage"] == "pose" and res["cause"] == "no_cuda"
    assert res["error"] == (
        "failed:pose: The 3D step could not run on this server: the GPU backend is not available (no CUDA)."
    )
    assert "/" not in res["error"].split(": ", 2)[-1]


@pytest.mark.parametrize("out,cause,words", [
    ("torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 2 GiB", "out_of_memory", "ran out of memory"),
    ("bash: ffmpeg: command not found", "missing_tool", "a tool it needs is missing"),
    ("part2: something odd at /home/x/secret/dir/file.py", "failed", "The 3D step failed: something odd at"),
])
def test_follower_part2_failure_causes_are_named_and_sanitised(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, out: str, cause: str, words: str
) -> None:
    video, expected = _follower_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(p2_pose, "run", lambda *a, **kw: (_fail_step(2, 1, out), tmp_path / "w" / "none.json"))
    res = _follow(tmp_path, state_dir, video, expected)
    assert res["ok"] is False and res["cause"] == cause and words in res["error"]
    assert "/home" not in res["error"] and "Traceback" not in res["error"]


def test_follower_part2_timeout_is_a_failed_job(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video, expected = _follower_inputs(tmp_path, monkeypatch)
    step = _fail_step(2, 124, "part2: no person found in 3 frames")  # even a stale line: a timeout is not a finding
    step["timed_out"] = True
    monkeypatch.setattr(p2_pose, "run", lambda *a, **kw: (step, tmp_path / "w" / "none.json"))
    res = _follow(tmp_path, state_dir, video, expected)
    assert res["ok"] is False and res["cause"] == "timeout" and "took too long" in res["error"]


def test_follower_part2_file_rejected_by_doctor_with_people_is_a_failed_job(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video, expected = _follower_inputs(tmp_path, monkeypatch)

    def p2(v: Path, w: Path, **kw: Any) -> tuple[runner.Step, Path]:
        p = Path(w) / "part2" / "pose3d.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"frames": [{"frame": 0, "people": [{"id": 0}]}]}', encoding="utf-8")
        return (_ok_step(2), p)

    monkeypatch.setattr(p2_pose, "run", p2)
    monkeypatch.setattr(p2_pose, "doctor", lambda *a, **kw: _fail_step(2, 1, "bad"))
    res = _follow(tmp_path, state_dir, video, expected)
    assert res["ok"] is False and res["stage"] == "pose"


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


def test_infrastructure_failure_writes_no_analysis_and_so_shows_no_video_tips(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TICKET-103: video quality tips live in the own analysis; a failed job has none, so none are shown."""
    video, expected = _follower_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(p2_pose, "run", lambda *a, **kw: (_fail_step(2, 1, CUDA), tmp_path / "w" / "none.json"))
    res = _follow(tmp_path, state_dir, video, expected)
    assert res["ok"] is False and res["files"] == {} and not (tmp_path / "w" / "analysis.json").exists()
