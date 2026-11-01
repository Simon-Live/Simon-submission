"""`--mesh` goes to `part2 run` only when the pin offers it; Part 2 soft misses are not failures (TICKET-143)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from part7 import chain, failcause, runner
from part7.parts import p2_pose, probe
from support import make_lock

MISS = "part2: --mesh found no mesh vertices; no mesh3d pair written"


def step(code: int = 0, out: str = "") -> runner.Step:
    return runner.Step(part=2, commit="x", argv=["stub"], cwd="/tmp", exit=code, timed_out=False,
                       duration_s=0.01, log="", stdout=out)


def argv_of(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, help_text: str, **kw: Any) -> list[str]:
    probe.clear_cache()
    seen: list[list[str]] = []

    def fake(part: Any, argv: list[str], **k: Any) -> runner.Step:
        seen.append(list(argv))
        return step(0, help_text) if argv[-1] == "--help" else step()

    monkeypatch.setattr(runner, "run", fake)
    lk = make_lock()
    lk.path("2").mkdir(parents=True, exist_ok=True)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    p2_pose.run(video, tmp_path / "w", backend="cpu", lock=lk, state=tmp_path / "s", **kw)
    probe.clear_cache()
    return [a for a in seen if a[-1] != "--help"][0]


def test_mesh_is_passed_when_the_pin_offers_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    argv = argv_of(tmp_path, monkeypatch, "usage: run [--mesh] [--mesh-vertices N]")
    assert argv.count("--mesh") == 1 and "--mesh-vertices" not in argv and "--refine" not in argv


def test_mesh_is_not_passed_when_the_pin_lacks_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert "--mesh" not in argv_of(tmp_path, monkeypatch, "usage: run [--ids IDS] [--mesh-x]")


def test_mesh_rides_the_warm_worker_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    argv = argv_of(tmp_path, monkeypatch, "usage: run --mesh --worker SOCK")
    assert "--mesh" in argv  # `_launch` appends `--worker <sock>` to this same sub list


def test_soft_miss_needs_exit_1_the_message_and_a_pose(tmp_path: Path) -> None:
    pose = tmp_path / "pose3d.json"
    assert not failcause.mesh_soft_miss(step(1, MISS), pose)  # no pose3d.json: a real failure
    pose.write_text("{}")
    assert failcause.mesh_soft_miss(step(1, MISS), pose)
    assert not failcause.mesh_soft_miss(step(1, "part2: boom"), pose)
    assert not failcause.mesh_soft_miss(step(2, MISS), pose)


def _run_pose(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, p2: runner.Step, doctors: list[Any]) -> chain._Run:
    pose = tmp_path / "w" / "part2" / "pose3d.json"
    pose.parent.mkdir(parents=True)
    pose.write_text('{"frames": [{"people": [{}]}]}')
    (pose.parent / "mesh3d.json").write_text("{bad")
    (pose.parent / "mesh3d.bin").write_bytes(b"x")
    monkeypatch.setattr(p2_pose, "run", lambda *a, **k: (p2, pose))
    codes = iter(doctors)
    monkeypatch.setattr(p2_pose, "doctor", lambda *a, **k: step(*(lambda c: c if isinstance(c, tuple) else (c,))(next(codes))))
    run = chain._Run(tmp_path / "v.mp4", None, {})
    chain._pose_run(run, tmp_path / "v.mp4", tmp_path / "w", "cpu", make_lock(), None, None, None)
    return run


def test_soft_miss_is_a_success_with_a_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run_pose(tmp_path, monkeypatch, step(1, MISS), [0])
    assert "no 3D mesh for this take" in run.notes and run.steps[0]["exit"] == 0


def test_malformed_mesh_fails_the_doctor_once_then_is_dropped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run_pose(tmp_path, monkeypatch, step(0), [(1, "part2 doctor: mesh3d.bin is shorter than mesh3d.json says"), 0])
    folder = tmp_path / "w" / "part2"
    assert not (folder / "mesh3d.json").exists() and not (folder / "mesh3d.bin").exists()
    assert "no 3D mesh for this take" in run.notes


def test_doctor_failure_without_a_mesh_still_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pose = tmp_path / "w" / "part2" / "pose3d.json"
    pose.parent.mkdir(parents=True)
    pose.write_text('{"frames": [{"people": [{}]}]}')
    monkeypatch.setattr(p2_pose, "run", lambda *a, **k: (step(0), pose))
    monkeypatch.setattr(p2_pose, "doctor", lambda *a, **k: step(1))
    with pytest.raises(chain._Stop):
        chain._pose_run(chain._Run(tmp_path / "v.mp4", None, {}), tmp_path / "v.mp4", tmp_path / "w", "cpu",
                        make_lock(), None, None, None)


def test_doctor_failure_not_about_the_mesh_fails_directly_and_keeps_the_mesh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    pose = tmp_path / "w" / "part2" / "pose3d.json"
    pose.parent.mkdir(parents=True)
    pose.write_text('{"frames": [{"people": [{}]}]}')
    (pose.parent / "mesh3d.json").write_text("{}")
    (pose.parent / "mesh3d.bin").write_bytes(b"x")
    monkeypatch.setattr(p2_pose, "run", lambda *a, **k: (step(0), pose))
    monkeypatch.setattr(p2_pose, "doctor", lambda *a, **k: (calls.append(1), step(1, "part2 doctor: frame 3 has no keypoints"))[1])
    with pytest.raises(chain._Stop):
        chain._pose_run(chain._Run(tmp_path / "v.mp4", None, {}), tmp_path / "v.mp4", tmp_path / "w", "cpu",
                        make_lock(), None, None, None)
    assert len(calls) == 1, "the doctor is not run again"
    assert (pose.parent / "mesh3d.json").exists(), "negative: the mesh pair is not dropped for an unrelated failure"
