"""byok-prod.md AC-BY9 and AC-BY10 (prod verify nofallback D1, D2, D3; byok-ui D2, D4): under BYOK-only nothing runs a
model on this host, whatever files exist, and a token Modal refused is not sent again.

The auditor's method: a stand-in Part 2 GPU venv python is planted at a temp HOME's default path
(`$HOME/.local/state/simon-part-2/venvs/gpu-cu128/bin/python`). It appends one line to a marker file whenever it is
started. Outside BYOK-only the app finds it (the control); in prod no path may start it."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from part7 import avatar_jobs as aj, byok_route, model_import, model_reskin, muse_fix_measure, person_check, runner
from part7.parts import p2_host, p2_pose
from support import Api, make_lock

JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 64


@pytest.fixture
def planted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temp HOME holding a stand-in GPU venv, a Part 2 checkout with every module file and the detector weights."""
    home = tmp_path / "home"
    py = home / ".local" / "state" / "simon-part-2" / "venvs" / "gpu-cu128" / "bin" / "python"
    py.parent.mkdir(parents=True)
    marker = tmp_path / "launched.log"
    py.write_text(f'#!/bin/sh\necho "$@" >> "{marker}"\nexit 3\n', encoding="utf-8")
    py.chmod(py.stat().st_mode | stat.S_IEXEC)
    part2 = tmp_path / "modules" / "part-2" / "part2"
    part2.mkdir(parents=True)
    for name in ("avatar.py", "autorig.py", "image3d.py", "cli.py"):
        (part2 / name).write_text("", encoding="utf-8")
    weights = home / ".cache" / "rtmlib" / "hub" / "checkpoints" / person_check.MODEL_NAME
    weights.parent.mkdir(parents=True)
    weights.write_bytes(b"onnx")
    for name in ("SIMON7_PART2_GPU_VENV", "SIMON7_PERSON_DETECTOR_MODEL", "FIRM_ENV", byok_route.PROD_COMPUTE_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SIMON7_MODULES_DIR", str(tmp_path / "modules"))
    monkeypatch.setenv("SIMON7_GPU_LOCK_PATH", str(tmp_path / "gpu.lock"))
    monkeypatch.setattr(aj, "MIN_FREE_MIB", 0)
    monkeypatch.setattr(aj, "MIN_FREE_MIB_IMAGE3D", 0)
    return marker


def go_prod(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FIRM_ENV", "prod")
    monkeypatch.setenv("SIMON7_BYOK", "on")  # serverless-compute.md: paused by default
    monkeypatch.setenv("PROD_SECRETS_DIR", str(tmp_path))


def queued_job(root: Path, kind: str = "image") -> Path:
    model_dir = root / "models" / "m1"
    (model_dir / "in").mkdir(parents=True)
    (model_dir / "in" / "a.jpg").write_bytes(JPEG)
    (model_dir / aj.JOB_FILE).write_text(json.dumps({"kind": kind, "inputs": ["a.jpg"], "owner": None}))
    (model_dir / aj.STATUS_FILE).write_text(json.dumps({"status": "queued", "run_by": {"pid": 1, "start": "x"}}))
    return model_dir


def test_control_outside_byok_the_planted_venv_is_found(planted: Path) -> None:
    """Without this the prod test below would prove nothing: the plant is where the app looks."""
    assert aj.available("image") and aj.available("autorig")
    assert person_check.available() and muse_fix_measure.available()


def test_prod_no_host_model_path_starts_the_planted_venv(planted: Path, tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    go_prod(monkeypatch, tmp_path)
    assert byok_route.host_models_refused()
    for kind in ("image", "autorig", "image3d"):
        assert aj.available(kind) is False, kind
        assert model_import._generator(kind) is None, kind  # model_import answers 415 MSG_NO_GENERATOR
    model_dir = queued_job(tmp_path)
    with pytest.raises(aj.AvatarError, match="not available on this server"):
        aj.submit_images(model_dir, [model_dir / "in" / "a.jpg"], None)
    aj._run_job(model_dir)  # a job left on disk by an older build
    status = json.loads((model_dir / aj.STATUS_FILE).read_text())
    assert status["status"] == "failed" and status["error"] == byok_route.MSG_NO_HOST_MODELS
    again = queued_job(tmp_path / "second")
    assert aj._requeue(again) is False
    assert aj.fail_stuck(tmp_path / "second" / "models") == ["m1"]
    assert person_check.available() is False and person_check.person_like(tmp_path / "x.jpg") is None
    (tmp_path / "x.jpg").write_bytes(JPEG)
    assert muse_fix_measure.measure(tmp_path / "x.jpg") is None
    assert model_reskin.part2_runner(tmp_path / "a.glb", tmp_path / "b.glb") == (model_reskin.NOT_RUN, "")
    assert model_reskin.cli(SimpleNamespace(restore=False, id=None, apply=True, state=str(tmp_path))) == 2
    assert not planted.exists(), "the planted GPU venv was started"


def test_byok_photo_and_mesh_uploads_answer_415_and_start_nothing(planted: Path, api: Api,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(byok_route.PROD_COMPUTE_ENV, "byok")
    head = {"Content-Type": "application/octet-stream", "Origin": f"http://127.0.0.1:{api.port}"}
    for query in ("consent=self", "kind=object&name=Armour"):
        status, _, data = api.request("POST", f"api/models?{query}", JPEG, head)
        assert status == 415 and "not available" in json.loads(data)["error"], query
    assert not planted.exists()


def test_prod_warm_and_track_workers_stay_off_whatever_the_env(planted: Path, tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    go_prod(monkeypatch, tmp_path)
    monkeypatch.setenv(p2_pose.WARM_WORKERS_ENV, "1")
    monkeypatch.setenv(p2_pose.TRACK_WORKER_ENV, "1")
    monkeypatch.setattr(p2_pose.p2_worker, "start_pool", lambda *a, **k: pytest.fail("a warm worker was started"))
    monkeypatch.setattr(p2_pose.p2_worker, "start_track_pool", lambda *a, **k: pytest.fail("a tracker was started"),
                        raising=False)
    assert p2_pose.warm_workers_decision(tmp_path) == (0, "byok")
    assert p2_pose.track_worker_enabled() is False
    assert p2_pose.start_workers(tmp_path, make_lock()) is False
    assert p2_pose._command("gpu", ["run"], tmp_path)[0][0] != str(planted.parent), "never the GPU venv"
    assert not planted.exists()


# ----- D3, byok-ui D4: host Part 2 steps never `uv run` in the release tree in prod --------------------------------
def capture(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    seen: list[list[str]] = []
    real = runner.run

    def spy(part: Any, argv: list[str], *a: Any, **kw: Any) -> runner.Step:
        seen.append([str(x) for x in argv])
        return real(part, argv, *a, **kw)

    monkeypatch.setattr(p2_pose.runner, "run", spy)
    monkeypatch.setattr(p2_pose.probe, "_CACHE", {})
    return seen


def test_outside_prod_host_steps_keep_uv_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIRM_ENV", raising=False)
    assert p2_host.base() == ["uv", "run", "part2"]
    assert p2_host.base(("uv", "run", "python", "-m", "part2"))[:2] == ["uv", "run"]


def test_prod_without_the_host_venv_runs_no_uv_and_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    go_prod(monkeypatch, tmp_path)
    monkeypatch.delenv(p2_host.HOST_PYTHON_ENV, raising=False)
    seen = capture(monkeypatch)
    lk = make_lock()
    clone = lk.path("2")
    clone.mkdir(parents=True, exist_ok=True)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\0")
    step = p2_pose.doctor(tmp_path / "pose3d.json", tmp_path / "w", lock=lk)
    assert step["exit"] == p2_host.NOT_SET_UP_EXIT
    assert p2_pose.frame_times(video, tmp_path / "w", 10.0, lk) is None
    assert p2_pose.capabilities(lk) == {"track": False, "ids": False}
    assert seen and all(argv[0] != "uv" and "uv" not in argv for argv in seen), seen
    assert not (clone / ".venv").exists()


def test_prod_with_the_prepared_venv_runs_it_in_the_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    go_prod(monkeypatch, tmp_path)
    host = tmp_path / "state" / "p2-host-venv" / "bin" / "python"
    host.parent.mkdir(parents=True)
    host.write_text(f'#!/bin/sh\nexec "{sys.executable}" -c "import sys; print(sys.argv)" "$@"\n', encoding="utf-8")
    host.chmod(0o755)
    monkeypatch.setenv(p2_host.HOST_PYTHON_ENV, str(host))
    seen = capture(monkeypatch)
    lk = make_lock()
    lk.path("2").mkdir(parents=True, exist_ok=True)
    assert p2_pose.doctor(tmp_path / "pose3d.json", tmp_path / "w", lock=lk)["exit"] == 0
    assert seen[-1][:3] == [str(host), "-m", "part2"] and seen[-1][3] == "doctor"
    assert p2_pose._command("cpu", ["track", "--help"], lk.path("2"))[0][:3] == [str(host), "-m", "part2"]


# ----- byok-ui D2: a refused token is not sent to Modal again in the same job ---------------------------------------
def test_a_refused_token_is_not_retried_by_the_tracker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    go_prod(monkeypatch, tmp_path)
    own_calls: list[list[str]] = []

    def fake_run(part: Any, argv: list[str], *a: Any, **kw: Any) -> runner.Step:
        own_calls.append(list(argv))
        return runner.Step(exit=byok_route.CREDS_REFUSED_EXIT)

    monkeypatch.setattr(p2_pose.runner, "run", fake_run)
    monkeypatch.setattr(p2_pose.byok_route, "command", lambda sub, sha: ["own-client", *sub])
    monkeypatch.setattr(p2_pose.applog, "anomaly", lambda *a, **k: None)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\0")
    env = {"MODAL_TOKEN_ID": "ak-RefusedToken0001", "MODAL_TOKEN_SECRET": "as-RefusedSecret001"}
    with p2_pose.job_route_set("modal"), p2_pose.job_modal_env_set(env) as refused:
        step, _ = p2_pose.track(video, tmp_path / "w", lock=make_lock(), tracker=p2_pose.API_TRACKER)
    assert refused[0] is True
    assert len(own_calls) == 1, "no second call to Modal"
    assert "--tracker" in own_calls[0] and own_calls[0][own_calls[0].index("--tracker") + 1] == "local-open"
    assert step["exit"] == byok_route.CREDS_REFUSED_EXIT


def test_outside_byok_a_refused_own_token_still_falls_back_here_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R1 stays: the own call is not repeated, the call runs on this machine instead (never the server's account)."""
    for name in ("FIRM_ENV", byok_route.PROD_COMPUTE_ENV):
        monkeypatch.delenv(name, raising=False)
    routes: list[str] = []
    monkeypatch.setattr(p2_pose.runner, "run", lambda part, argv, *a, **k: routes.append("own") or runner.Step(exit=77))
    monkeypatch.setattr(p2_pose.byok_route, "command", lambda sub, sha: ["own-client"])
    monkeypatch.setattr(p2_pose, "_attempt", lambda *a, **k: routes.append("local") or runner.Step(exit=0))
    monkeypatch.setattr(p2_pose.applog, "anomaly", lambda *a, **k: None)
    lk = make_lock()
    with p2_pose.job_route_set("modal"), p2_pose.job_modal_env_set({"MODAL_TOKEN_ID": "x"}):
        for _ in range(2):
            p2_pose._execute(["track"], "gpu", tmp_path, "t.log", lk, tmp_path, False, None)
    assert routes == ["own", "local", "local"]
    assert os.environ.get("MODAL_TOKEN_ID") is None
