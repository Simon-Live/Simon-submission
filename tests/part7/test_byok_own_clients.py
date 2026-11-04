"""byok-prod.md AC-BY11 (BYOK-M6, prod verify nofallback D4): an own-route Modal client ends on Remove, at the end of
its server and when its server dies; a reused pid is never signalled. Real processes: the real launcher
(`p2_client.py --own`) starts a stand-in Modal client (`SIMON7_MODAL_PYTHON`) that records its pid and sleeps."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Iterator

import pytest

from part7 import byok_route, config, modal_creds, own_clients

CLIENT = config.REPO_ROOT / "deploy" / "serverless" / "p2_client.py"
TOKENS = {"MODAL_TOKEN_ID": "ak-OwnClientToken001", "MODAL_TOKEN_SECRET": "as-OwnClientSecret01"}


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # a zombie child of this test counts as gone
        return Path(f"/proc/{pid}/stat").read_text().split(") ")[1][0] != "Z"
    except OSError:
        return False


def wait_for(cond, seconds: float = 15.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def stand(tmp_path: Path) -> Iterator[dict]:
    fake = tmp_path / "fake-modal-python"
    childpid = tmp_path / "child.pid"
    fake.write_text(f'#!/bin/sh\necho $$ > "{childpid}"\nexec sleep 60\n', encoding="utf-8")
    fake.chmod(0o755)
    tmpdir = tmp_path / "tmpdir"
    tmpdir.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "TMPDIR": str(tmpdir), "SIMON7_MODAL_PYTHON": str(fake),
           **TOKENS}
    procs: list[subprocess.Popen] = []
    pids: list[int] = []
    yield {"tmp": tmp_path, "env": env, "childpid": childpid, "procs": procs, "pids": pids, "state": tmp_path / "state",
           "tmpdir": tmpdir}
    for pid in [p.pid for p in procs] + pids:  # only processes this test started
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            pass
    for proc in procs:
        proc.wait(timeout=5)
    if childpid.is_file():
        try:
            os.kill(int(childpid.read_text()), signal.SIGKILL)
        except (OSError, ValueError):
            pass


def launch(stand: dict, owner: str = "ann") -> tuple[subprocess.Popen, int]:
    """The launcher as runner.run starts it (own session), registered for `owner`; (process, Modal client pid)."""
    argv = [sys.executable, "-I", str(CLIENT), "--own", "--registry", str(own_clients.registry(stand["state"])),
            "--owner", owner, "--check"]
    proc = subprocess.Popen(argv, env=stand["env"], start_new_session=True, stdout=subprocess.DEVNULL)
    stand["procs"].append(proc)
    entry = own_clients.registry(stand["state"]) / f"{proc.pid}.json"
    assert wait_for(lambda: entry.is_file() and stand["childpid"].is_file() and stand["childpid"].read_text().strip())
    return proc, int(stand["childpid"].read_text())


def test_remove_ends_the_owners_client_only(stand: dict) -> None:
    proc, child = launch(stand)
    entry = json.loads((own_clients.registry(stand["state"]) / f"{proc.pid}.json").read_text())
    assert entry == {"pid": proc.pid, "parent": os.getpid(), "owner": "ann", "start": own_clients.start_time(proc.pid)}
    assert not any(v in json.dumps(entry) for v in TOKENS.values())
    assert own_clients.stop_owner(stand["state"], "bob") == 0 and alive(proc.pid)
    assert own_clients.stop_owner(stand["state"], "ann", grace_s=5) == 1
    proc.wait(timeout=10)
    assert wait_for(lambda: not alive(child)), "the Modal client outlived its launcher"
    assert list(own_clients.registry(stand["state"]).glob("*.json")) == []
    assert list(stand["tmpdir"].iterdir()) == [], "the launcher left its temp HOME"


def test_stop_all_ends_only_the_clients_its_server_started(stand: dict) -> None:
    proc, child = launch(stand)
    assert own_clients.stop_all(stand["state"], parent=os.getpid() + 999999) == 0 and alive(proc.pid)
    assert own_clients.stop_all(stand["state"], parent=os.getpid()) == 1
    proc.wait(timeout=10)
    assert wait_for(lambda: not alive(child))


def test_the_launcher_ends_when_its_server_dies(stand: dict) -> None:
    """A server killed with SIGKILL runs no atexit: the launcher's parent watch ends it and its client."""
    script = (f"import subprocess, sys, time; p = subprocess.Popen({[sys.executable, '-I', str(CLIENT), '--own', '--check']!r}, "
              "start_new_session=True); print(p.pid, flush=True); time.sleep(60)")
    server = subprocess.Popen([sys.executable, "-c", script], env=stand["env"], stdout=subprocess.PIPE, text=True,
                              start_new_session=True)
    stand["procs"].append(server)
    launcher = int(server.stdout.readline())
    stand["pids"].append(launcher)
    assert wait_for(lambda: stand["childpid"].is_file() and stand["childpid"].read_text().strip())
    child = int(stand["childpid"].read_text())
    os.killpg(server.pid, signal.SIGKILL)
    server.wait(timeout=5)
    assert wait_for(lambda: not alive(launcher) and not alive(child), 15), "the client survived its server"


def test_a_reused_pid_is_never_signalled(stand: dict) -> None:
    other = subprocess.Popen(["sleep", "30"], start_new_session=True)
    stand["procs"].append(other)
    folder = own_clients.registry(stand["state"])
    folder.mkdir(parents=True)
    (folder / f"{other.pid}.json").write_text(json.dumps({"pid": other.pid, "owner": "ann", "start": "1"}))
    (folder / "junk.json").write_text("{")
    assert own_clients.stop_all(stand["state"]) == 0
    assert alive(other.pid) and list(folder.glob("*.json")) == []
    real = {"pid": other.pid, "owner": "ann", "start": own_clients.start_time(other.pid)}
    (folder / f"{other.pid}.json").write_text(json.dumps(real))
    assert own_clients.stop_all(stand["state"]) == 0 and alive(other.pid), "not a launcher: its argv is not p2_client.py"


def test_the_cli_down_sh_runs_stops_every_client(stand: dict) -> None:
    proc, child = launch(stand)
    done = subprocess.run([sys.executable, "-E", "-s", "-m", "part7.own_clients", "stop", "--state", str(stand["state"])],
                          cwd=config.REPO_ROOT, capture_output=True, text=True, timeout=30, check=False)
    assert done.returncode == 0 and "stopped: 1" in done.stderr
    proc.wait(timeout=10)
    assert wait_for(lambda: not alive(child))
    assert "own_clients stop --state" in (config.REPO_ROOT / "prod" / "down.sh").read_text(encoding="utf-8")


def test_wiring_job_args_remove_and_start_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert "--registry" not in byok_route.command(["run"], "a" * 40)
    with own_clients.job(tmp_path, "ann"):
        argv = byok_route.command(["run"], "a" * 40)
        asr = byok_route.transcribe_command(tmp_path / "a.wav", tmp_path / "out")
    for got in (argv, asr):
        at = got.index("--registry")
        assert got[at:at + 4] == ["--registry", str(own_clients.registry(tmp_path)), "--owner", "ann"]
    with own_clients.job(tmp_path, "../evil"):
        assert own_clients.launcher_args() == []
    stopped: list[str] = []
    monkeypatch.setattr(modal_creds.own_clients, "stop_owner", lambda state, user: stopped.append(user) or 0)
    monkeypatch.setenv("SIMON7_BYOK_KEY_FILE", str(tmp_path.parent / f"{tmp_path.name}.key"))
    modal_creds.save(tmp_path, "ann", *TOKENS.values())
    assert modal_creds.remove(tmp_path, "ann") and stopped == ["ann"]
    sys.path.insert(0, str(CLIENT.parent))
    try:
        import p2_client
    finally:
        sys.path.remove(str(CLIENT.parent))
    assert p2_client.start_time(os.getpid()) == own_clients.start_time(os.getpid()) is not None
