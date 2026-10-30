"""Trainer chain end to end with the import, densify argv, fallbacks and harness changes (processor.md, parts-harness.md)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
from typing import Any

import pytest

from part7 import chain, gpu_lock, keys, runner, setup_parts
from part7.parts import p1_keyframes, p2_pose, p3_skeleton, p4_animate, p5_analyse, p6_catalog, probe
from support import make_lock


def step(part: int, exit_code: int = 0, stdout: str = "", timed_out: bool = False) -> runner.Step:
    return runner.Step(part=part, commit="x", argv=["stub"], cwd="/tmp", exit=exit_code, timed_out=timed_out,
                       duration_s=0.01, log="", stdout=stdout)


@pytest.fixture()
def seams(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Fake every part adapter of the chain; tests flip entries to inject failures."""
    seen: dict[str, Any] = {"import": [], "p1": step(1), "p4": 0, "doctor6": 0, "import_exit": 0, "people": True}

    def p1_run(video: Path, work: Path, **kw: Any) -> tuple[Any, Path | None, str | None]:
        if seen["p1"]["exit"] != 0:
            return (seen["p1"], None, f"key frames from Part 3, Part 1 exited {seen['p1']['exit']}")
        kf = Path(work) / "keyframes.json"
        kf.write_text(json.dumps({"people": [{"id": 0}] if seen["people"] else []}))
        return (step(1), kf, None)

    def p2_run(video: Path, work: Path, **kw: Any) -> tuple[Any, Path]:
        pose = Path(work) / "part2" / "pose3d.json"
        pose.parent.mkdir(parents=True, exist_ok=True)
        pose.write_text("{}")
        return (step(2), pose)

    def p3_part4(pose: Path, kf: Any, work: Path, **kw: Any) -> tuple[list[Any], Path, Path, None]:
        seen["kf_arg"] = str(kf)
        skel, kfv1 = Path(work) / "skeleton.json", Path(work) / "keyframes.v1.json"
        skel.write_text("{}")
        kfv1.write_text("{}")
        return ([step(3)], skel, kfv1, None)

    def p4_run(skel: Path, kfv1: Path, work: Path, **kw: Any) -> tuple[Any, Path]:
        out = Path(work) / "part4" / "animation.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("{}")
        return (step(4, seen["p4"]), out)

    def import_entry(catalog: Path, folder: Path, name: str, category: str, parts: dict[str, int], work: Path, **kw: Any):
        seen["import"].append({"folder": sorted(p.name for p in Path(folder).iterdir()), "name": name,
                               "category": category, "parts": parts})
        if seen["import_exit"]:
            return (step(6, seen["import_exit"]), None)
        return (step(6), {"id": "lateral-raise-smoke", "files_source": "import"})

    monkeypatch.setattr(p1_keyframes, "run", p1_run)
    monkeypatch.setattr(p1_keyframes, "doctor", lambda *a, **k: step(6))
    monkeypatch.setattr(p2_pose, "run", p2_run)
    monkeypatch.setattr(p2_pose, "doctor", lambda *a, **k: step(2))
    monkeypatch.setattr(p3_skeleton, "part4", p3_part4)
    monkeypatch.setattr(p3_skeleton, "doctor", lambda *a, **k: step(3))
    monkeypatch.setattr(p4_animate, "validate", lambda *a, **k: step(4))
    monkeypatch.setattr(p4_animate, "run", p4_run)
    monkeypatch.setattr(p5_analyse, "doctor", lambda *a, **k: step(5))
    monkeypatch.setattr(p6_catalog, "import_entry", import_entry)
    monkeypatch.setattr(p6_catalog, "doctor", lambda *a, **k: step(6, seen["doctor6"]))
    return seen


def run_trainer(tmp_path: Path, stages: list[str] | None = None) -> dict[str, Any]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    video = tmp_path / "video.mp4"
    video.write_bytes(b"mp4")
    return chain.trainer(video, tmp_path / "w", report=(stages.append if stages is not None else None),
                         lock=make_lock(), catalog=tmp_path / "cat", name="Lateral raise", category="exercise")


def test_trainer_ends_with_import_carrying_video_and_provenance(tmp_path: Path, seams: dict[str, Any]) -> None:
    stages: list[str] = []
    res = run_trainer(tmp_path, stages)
    assert res["ok"] and res["entry_id"] == "lateral-raise-smoke"
    assert stages == ["keyframes", "pose", "skeleton", "animation", "catalog"]
    call = seams["import"][0]
    assert call["folder"] == ["animation.json", "keyframes.json", "skeleton.json", "video.mp4"]
    assert call["parts"] == {"keyframes": 1, "skeleton": 3, "animation": 4}
    assert (call["name"], call["category"]) == ("Lateral raise", "exercise")
    assert Path(seams["kf_arg"]).name == "keyframes.json"


def test_part1_failure_and_empty_people_take_the_part3_fallback(tmp_path: Path, seams: dict[str, Any]) -> None:
    seams["p1"] = step(1, 3)
    res = run_trainer(tmp_path)
    assert res["ok"] and seams["kf_arg"] == "every:10" and seams["import"][0]["parts"]["keyframes"] == 3
    assert "Part 1 exited 3" in res["note"]
    seams["p1"], seams["people"], seams["import"] = step(1), False, []
    res = run_trainer(tmp_path / "second")
    assert seams["kf_arg"] == "every:10" and seams["import"][0]["parts"]["keyframes"] == 3
    assert "no person" in res["note"]


def test_part4_exit_1_maps_to_failed_animation(tmp_path: Path, seams: dict[str, Any]) -> None:
    seams["p4"] = 1
    res = run_trainer(tmp_path)
    assert res["ok"] is False and res["error"] == "failed:animation: the animation step failed"
    assert seams["import"] == []


@pytest.mark.parametrize("field,value", [("import_exit", 1), ("doctor6", 1)])
def test_import_or_doctor_failure_is_failed_catalog(tmp_path: Path, seams: dict[str, Any], field: str, value: int) -> None:
    seams[field] = value
    res = run_trainer(tmp_path)
    assert res["error"] == "failed:catalog: the catalog did not accept the entry"


def test_failure_reasons_carry_no_path_or_host(tmp_path: Path, seams: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def busy(*a: Any, **k: Any) -> Any:
        raise TimeoutError("GPU busy at /home/x/gpu.lock on box.example.com")

    monkeypatch.setattr(p2_pose, "run", busy)
    res = run_trainer(tmp_path)
    assert res["error"] == "failed:pose: the GPU is busy, try again later"
    monkeypatch.setattr(p2_pose, "run", lambda v, w, **k: (step(2, None, timed_out=True), Path(w) / "none.json"))
    assert run_trainer(tmp_path / "t2")["error"] == "failed:pose: the 3D step took too long"
    monkeypatch.setattr(p2_pose, "doctor", lambda *a, **k: step(2, 1))
    monkeypatch.setattr(p2_pose, "run", lambda v, w, **k: (step(2), _touch(Path(w) / "p.json")))
    err = run_trainer(tmp_path / "t3")["error"]
    assert err == "failed:pose: pose3d.json was rejected by part 2" and "/" not in err.split(": ", 1)[1]


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}")
    return path


# ----- Part 3 argv: densify present after the re-pin, absent before it (AC-R5) --------------------
def _capture_runner(monkeypatch: pytest.MonkeyPatch, outputs: list[runner.Step]) -> list[list[str]]:
    argvs: list[list[str]] = []

    def fake(part: Any, argv: list[str], **kw: Any) -> runner.Step:
        argvs.append(list(argv))
        return outputs[min(len(argvs), len(outputs)) - 1]

    monkeypatch.setattr(runner, "run", fake)
    return argvs


def _p3(tmp_path: Path, kf: Any) -> tuple[list[Any], Path, Path, str | None]:
    state = tmp_path / "state"
    lk = make_lock()
    lk.path("3", state=state).mkdir(parents=True)
    pose = tmp_path / "pose3d.json"
    pose.write_text("{}")
    return p3_skeleton.part4(pose, kf, tmp_path / "w", lock=lk, state=state)


def test_densify_argv_present_when_part3_offers_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probe.clear_cache()
    monkeypatch.setattr(probe, "has_flag", lambda *a, **k: True)
    argvs = _capture_runner(monkeypatch, [step(3)])
    kf = tmp_path / "keyframes.json"
    kf.write_text("{}")
    _p3(tmp_path, kf)
    argv = argvs[0]
    assert argv[argv.index("--keyframes-densify") + 1] == "every:10"
    assert argv[argv.index("--body") + 1] == "simon-standard" and argv[argv.index("--view") + 1] == "part4"
    assert argv[argv.index("--keyframes") + 1] == str(kf.resolve())


def test_densify_argv_absent_before_the_repin_with_a_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "has_flag", lambda *a, **k: False)
    argvs = _capture_runner(monkeypatch, [step(3)])
    kf = tmp_path / "keyframes.json"
    kf.write_text("{}")
    _, _, _, note = _p3(tmp_path, kf)
    assert "--keyframes-densify" not in argvs[0] and argvs[0][argvs[0].index("--keyframes") + 1] == "every:10"
    assert "no densify" in note


def test_part3_180_degree_refusal_retries_once_with_every_5(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "has_flag", lambda *a, **k: False)
    argvs = _capture_runner(monkeypatch, [step(3, 2, "left_elbow turns over 180 degrees; add keys between them"), step(3)])
    steps, _, _, note = _p3(tmp_path, "every:10")
    assert len(argvs) == 2 and argvs[1][argvs[1].index("--keyframes") + 1] == "every:5" and "every:5" in note
    assert steps[-1]["exit"] == 0


def test_probe_reads_help_once_per_clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probe.clear_cache()
    argvs = _capture_runner(monkeypatch, [step(3, 0, "usage: --keyframes-densify DENSIFY")])
    assert probe.has_flag(3, ["py", "-m", "part3", "run"], tmp_path, "--keyframes-densify")
    assert probe.has_flag(3, ["py", "-m", "part3", "run"], tmp_path, "--keyframes-densify")
    assert not probe.has_flag(3, ["py", "-m", "part3", "run"], tmp_path, "--nope")
    assert len(argvs) == 2 and argvs[0][-1] == "--help"
    probe.clear_cache()


def test_part2_and_follower_argv_follow_the_journey(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    argvs = _capture_runner(monkeypatch, [step(2)])
    state, lk = tmp_path / "s", make_lock()
    lk.path("2", state=state).mkdir(parents=True)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    p2_pose.run(video, tmp_path / "w", backend="cpu", lock=lk, state=state)
    assert argvs[0][argvs[0].index("--fps") + 1] == "10" and argvs[0][argvs[0].index("--backend") + 1] == "cpu"
    argvs.clear()
    lk.path("3", state=state).mkdir(parents=True)
    p3_skeleton.part5(tmp_path / "p.json", tmp_path / "w", lock=lk, state=state)
    a = argvs[0]
    assert a[a.index("--view") + 1] == "part5" and a[a.index("--fps") + 1] == "30" and a[a.index("--body") + 1] == "simon-standard"


@pytest.mark.parametrize("flags,phrasing,expect_phrasing,expect_replay,expect_notes", [
    ("--replay --live muse-spark", "live", ["--phrasing", "muse-spark", "--live"], True, 0),
    ("--phrasing", "live", ["--phrasing", "template"], False, 2),
    ("--replay", "template", ["--phrasing", "template"], True, 0),
])
def test_part5_argv_follows_the_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flags: str, phrasing: str,
                                    expect_phrasing: list[str], expect_replay: bool, expect_notes: int) -> None:
    probe.clear_cache()
    argvs = _capture_runner(monkeypatch, [step(5, 0, flags)])
    state, lk = tmp_path / "s", make_lock()
    lk.path("5", state=state).mkdir(parents=True)
    _, _, _, notes = p5_analyse.run(tmp_path / "e.json", tmp_path / "f.json", tmp_path / "w", lock=lk, state=state,
                                    phrasing=phrasing)
    run_argv = argvs[-1]
    assert run_argv[run_argv.index("--phrasing"):][:len(expect_phrasing)] == expect_phrasing
    assert ("--replay" in run_argv) is expect_replay and len(notes) == expect_notes
    probe.clear_cache()


# ----- runner, gpu lock, keys, setup-parts changes ----------------------------------------------------
def test_runner_writes_the_log_while_the_command_runs(tmp_path: Path) -> None:
    log = tmp_path / "x.log"
    code = "import time,sys; print('first', flush=True); time.sleep(1.5); print('second')"
    holder: dict[str, Any] = {}
    import threading

    t = threading.Thread(target=lambda: holder.update(step=runner.run("x", [sys.executable, "-c", code], cwd=tmp_path, log_path=log)))
    t.start()
    deadline, seen = time.monotonic() + 1.4, False
    while time.monotonic() < deadline and not seen:
        seen = log.exists() and "first" in log.read_text() and "second" not in log.read_text()
        time.sleep(0.05)
    t.join()
    assert seen and holder["step"]["exit"] == 0 and "second" in log.read_text()


def test_runner_redacts_a_key_in_the_live_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kd = tmp_path / "keys"
    kd.mkdir()
    (kd / "MODEL_API_KEY").write_text("sk-abcdef-123456")
    monkeypatch.setenv("SIMON7_KEYS_DIR", str(kd))
    log = tmp_path / "k.log"
    st = runner.run("x", [sys.executable, "-c", "print('token sk-abcdef-123456 end')"], cwd=tmp_path, log_path=log)
    assert "sk-abcdef" not in log.read_text() and "<redacted>" in log.read_text() and "sk-abcdef" not in st["stdout"]


def test_redactor_snapshot_matches_redact(tmp_path: Path) -> None:
    (tmp_path / "A").write_text("topsecret-value")
    assert keys.redactor(tmp_path)("x topsecret-value y") == keys.redact("x topsecret-value y", keys_dir=tmp_path) == "x <redacted> y"


def test_gpu_lock_with_zero_free_memory_requirement_skips_the_wait(tmp_path: Path) -> None:
    calls = []
    with gpu_lock.acquire(lock_path=tmp_path / "l", min_free_mib=0, memory_fn=lambda: calls.append(1) or 0):
        pass
    assert calls == []


def test_setup_parts_checks_part6_contract_version(state_dir: Path) -> None:
    assert setup_parts._contract_version_is_1('{"contract_version": 1}')
    assert not setup_parts._contract_version_is_1('{"contract_version": 2}')
    assert not setup_parts._contract_version_is_1("contract_version: 1")


def test_gpu_lock_can_release_the_file_lock_for_part2_which_takes_it_itself(tmp_path: Path) -> None:
    import fcntl
    import os

    path = tmp_path / "l"
    with gpu_lock.acquire(lock_path=path, min_free_mib=0, hold_flock=False):
        fd = os.open(str(path), os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises BlockingIOError if Part 7 still held it
        os.close(fd)
    with gpu_lock.acquire(lock_path=path, min_free_mib=0):
        fd = os.open(str(path), os.O_RDWR)
        with pytest.raises(BlockingIOError):
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.close(fd)
