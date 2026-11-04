"""serverless-compute.md AC-SC2 to AC-SC4, AC-SC7, AC-SC10, AC-SC16, AC-SC19: the real p2_client.py in its real child process
against a fake Modal (tests/part7/fake_modal). No network, no account."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import time
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "deploy" / "serverless" / "p2_client.py"
FAKE = Path(__file__).resolve().parent / "fake_modal"
SECRET = "as-CanaryTokenSecret0123456789"
TOKEN_ID = "ak-CanaryTokenId0123456789"
SHA = "a" * 40


class Rig:
    def __init__(self, base: Path) -> None:
        self.root, self.secrets, self.ledger = base / "workspace", base / "secrets", base / "ledger"
        self.base = base
        for folder in (self.root, self.secrets, self.ledger):
            folder.mkdir()
        for name, value in (("MODAL_TOKEN_ID", TOKEN_ID), ("MODAL_TOKEN_SECRET", SECRET)):
            (self.secrets / name).write_text(value)
            (self.secrets / name).chmod(0o600)
        tool = base / "fake-python"
        tool.mkdir()
        shutil.copy(FAKE / "python", tool / "python")
        (tool / "python").chmod(0o755)
        (tool / "root").write_text(str(self.root))
        (tool / "fake-dir").write_text(str(FAKE))
        self.python = tool / "python"
        self.clip = base / "clip.mp4"
        self.clip.write_bytes(b"VIDEO-BYTES-OF-A-PERSON")

    def env(self) -> dict[str, str]:
        return {"PATH": os.environ["PATH"], "HOME": str(self.base), "SIMON7_MODAL_PYTHON": str(self.python)}

    def mode(self, name: str) -> None:
        (self.root / "mode").write_text(name)

    def client(self, *args: str, secrets: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-I", str(CLIENT), "--serverless", "--secrets-dir", str(secrets or self.secrets),
                               *args], env=self.env(), capture_output=True, text=True, timeout=60, check=False)

    def run_take(self, *flags: str) -> subprocess.CompletedProcess[str]:
        return self.client("--ledger", str(self.ledger), "--job", "job1", *flags, "--sha", SHA, "--", "run", "--input",
                           str(self.clip), "--out", str(self.base / "out"))

    def calls(self) -> list[dict]:
        path = self.root / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def store(self) -> list[Path]:
        folder = self.root / "volumes" / "simon-part2-store"
        return [p for p in folder.iterdir()] if folder.exists() else []


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def test_a_take_runs_through_the_volume_and_leaves_nothing_at_modal(rig: Rig) -> None:
    done = rig.run_take()
    assert done.returncode == 0, done.stdout + done.stderr
    assert (rig.base / "out" / "result.txt").read_text() == "fake"
    assert rig.store() == [], "AC-SC4: the object is gone when the job ends"
    assert list(rig.ledger.iterdir()) == [], "the ledger entry goes once Modal confirmed"


def test_the_call_carries_a_key_and_never_the_video(rig: Rig) -> None:
    rig.run_take()
    call = rig.calls()[0]
    assert len(call["key"]) == 32 and call["inputs"] == ["input.mp4"], "the media waits in the Volume"
    assert "VIDEO-BYTES" not in json.dumps(call), "AC-SC3: no media in the call's arguments"
    assert not any(str(rig.base) in arg for arg in call["argv"]), "no local path reaches Modal"


def test_the_token_is_read_only_by_the_process_that_calls_modal(rig: Rig) -> None:
    done = rig.run_take()
    assert rig.calls()[0]["had_token"], "the child read the files"
    assert SECRET not in done.stdout + done.stderr and TOKEN_ID not in done.stdout + done.stderr


def test_the_launcher_starts_the_child_with_no_token_in_env_or_argv(rig: Rig, tmp_path: Path) -> None:
    shim = rig.python.parent / "python"
    record = tmp_path / "seen.txt"
    shim.write_text(f'#!/bin/sh\n{{ env; printf "%s\\n" "$@"; }} > "{record}"\nexit 0\n')
    assert rig.run_take().returncode == 0
    seen = record.read_text()
    assert "MODAL_TOKEN" not in seen and SECRET not in seen and TOKEN_ID not in seen
    assert str(rig.secrets) in seen, "a folder's path is all the child gets"


@pytest.mark.parametrize("mode_bits", [0o640, 0o604])
def test_a_token_file_open_to_others_stops_the_job(rig: Rig, mode_bits: int) -> None:
    (rig.secrets / "MODAL_TOKEN_SECRET").chmod(mode_bits)
    assert stat.S_IMODE((rig.secrets / "MODAL_TOKEN_SECRET").stat().st_mode) == mode_bits
    done = rig.run_take()
    assert done.returncode == 80 and rig.calls() == []


def test_a_missing_token_file_stops_the_job(rig: Rig) -> None:
    (rig.secrets / "MODAL_TOKEN_ID").unlink()
    assert rig.run_take().returncode == 80 and rig.calls() == []


def test_over_a_limit_is_busy_and_cleans_up(rig: Rig) -> None:
    rig.mode("over-limit")
    done = rig.run_take()
    assert done.returncode == 79 and "over a limit" in done.stdout
    assert rig.store() == [] and list(rig.ledger.iterdir()) == []


def test_never_starting_is_busy_shows_the_wait_cancels_and_cleans_up(rig: Rig) -> None:
    rig.mode("never-starts")
    status = rig.base / "status.json"
    done = rig.run_take("--queue-wait", "0", "--status", str(status))
    assert done.returncode == 79
    assert (rig.root / "cancelled").exists(), "the queued call is cancelled, so it cannot run later on a removed key"
    assert rig.store() == [], "no video stays behind a call that never ran"


def test_a_token_modal_refuses_is_a_plain_stop_and_never_prints_the_exception(rig: Rig) -> None:
    rig.mode("refused")
    done = rig.run_take()
    assert done.returncode == 80, "HARDENING 4a: the provider refusing is a stop, with no retry here"
    assert "ak-must-not-be-printed" not in done.stdout + done.stderr
    assert rig.calls() == []


def _wait_for(check, seconds: float = 20.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.05)
    return bool(check())


def test_sigterm_cancels_the_call_and_removes_the_object_and_its_ledger_entry(rig: Rig) -> None:  # AC-SC4
    rig.mode("never-starts")
    proc = subprocess.Popen([sys.executable, "-I", str(CLIENT), "--serverless", "--secrets-dir", str(rig.secrets),
                             "--ledger", str(rig.ledger), "--job", "job1", "--sha", SHA, "--", "run", "--input",
                             str(rig.clip), "--out", str(rig.base / "out")],
                            env=rig.env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert _wait_for(lambda: rig.calls() and list(rig.ledger.iterdir())), "the call never started"
        assert rig.store() != [], "negative: the object is there before the signal"
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=30) != 0
    finally:
        proc.kill()
    assert (rig.root / "cancelled").exists(), "the queued call is cancelled, so it cannot run on a removed key"
    assert rig.store() == [] and list(rig.ledger.iterdir()) == [], "nothing stays at Modal after a stop"


def _transcribe(rig: Rig, *flags: str) -> subprocess.CompletedProcess[str]:
    wav = rig.base / "voice.wav"
    if not wav.exists():
        wav.write_bytes(b"RIFF-VOICE-OF-A-TRAINER")
    return rig.client("--ledger", str(rig.ledger), "--job", "job1", *flags, "--transcribe", "--input", str(wav),
                      "--out", str(rig.base / "captions"))


def test_captions_go_through_the_volume_with_a_key_only(rig: Rig) -> None:  # AC-SC15
    done = _transcribe(rig)
    assert done.returncode == 0, done.stdout + done.stderr
    call = rig.calls()[0]
    assert set(call) == {"key", "asr", "inputs"} and len(call["key"]) == 32 and call["inputs"] == ["audio.wav"]
    assert "RIFF-VOICE" not in json.dumps(call), "no sound in the call's arguments"
    assert json.loads((rig.base / "captions" / "transcript.json").read_text())["transcript"] == "lift your arms"
    assert rig.store() == [] and list(rig.ledger.iterdir()) == [], "nothing of the voice stays at Modal"
    assert SECRET not in done.stdout + done.stderr
    assert "modal: captions call " in done.stdout, "the call to look up at Modal when captions hang"


@pytest.mark.parametrize("mode", ["asr-failed", "asr-bad"])
def test_failed_captions_write_nothing_and_leave_nothing_at_modal(rig: Rig, mode: str) -> None:  # AC-SC15
    rig.mode(mode)
    assert _transcribe(rig).returncode != 0
    assert not (rig.base / "captions" / "transcript.json").exists(), "no captions means no transcript file"
    assert rig.store() == [] and list(rig.ledger.iterdir()) == []


def test_captions_over_the_length_cap_never_reach_modal(rig: Rig) -> None:  # AC-SC15
    with (rig.base / "voice.wav").open("wb") as fh:
        fh.truncate(40 * 2**20 + 1)
    assert _transcribe(rig).returncode != 0
    assert rig.calls() == [] and rig.store() == []


def test_sigterm_during_captions_cancels_and_leaves_nothing(rig: Rig) -> None:  # AC-SC15
    rig.mode("never-starts")
    proc = subprocess.Popen([sys.executable, "-I", str(CLIENT), "--serverless", "--secrets-dir", str(rig.secrets), "--ledger",
                             str(rig.ledger), "--job", "job1", "--transcribe", "--input", str(rig.clip), "--out",
                             str(rig.base / "captions")], env=rig.env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert _wait_for(lambda: rig.calls()), "the call never started"
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=30) != 0
    finally:
        proc.kill()
    assert (rig.root / "cancelled").exists() and rig.store() == [] and list(rig.ledger.iterdir()) == []


def test_the_measured_line_holds_numbers_only(rig: Rig) -> None:
    done = rig.run_take()
    line = next(x for x in done.stdout.splitlines() if x.startswith("modal: measured "))
    doc = json.loads(line.removeprefix("modal: measured "))
    assert doc["container_up_s"] == 40.5 and doc["gpu_s"] == 90.0 and doc["peak_ram_mib"] == 9000
    assert "note" not in doc and "spawn_to_start_s" in doc


def test_a_tracker_other_than_local_open_is_refused_before_any_upload(rig: Rig) -> None:
    done = rig.client("--sha", SHA, "--", "track", "--input", str(rig.clip), "--out", str(rig.base / "o"),
                      "--tracker", "api-sam31")
    assert done.returncode == 1 and rig.calls() == [] and rig.store() == []


def test_a_listed_key_is_deleted_by_the_sweep_route(rig: Rig) -> None:
    key = "b" * 32
    (rig.root / "volumes" / "simon-part2-store" / key).mkdir(parents=True)
    (rig.ledger / f"{key}.json").write_text(json.dumps({"job": "job1", "at": 0, "due": True}))
    assert rig.client("--ledger", str(rig.ledger), "--delete").returncode == 0
    assert rig.store() == [] and list(rig.ledger.iterdir()) == []


# ----- AC-SC16: the deployed app's version ---------------------------------------------------------------------------
def _version(part2: str) -> str:
    import hashlib

    return f"{part2}:{hashlib.sha256((ROOT / 'deploy/serverless/part2_app.py').read_bytes()).hexdigest()[:16]}"


def _image3d_version(part2: str) -> str:
    import hashlib

    digest = lambda name: hashlib.sha256((ROOT / "deploy/serverless" / name).read_bytes()).hexdigest()[:16]  # noqa: E731
    return f"{part2}:{digest('image3d_app.py')}:{digest('part2_app.py')}"


def _stamp(rig: Rig, version: str) -> None:
    folder = rig.root / "volumes" / "simon-part2-store"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "deploy.json").write_text(json.dumps({"version": version}))
    (folder / "deploy-image3d.json").write_text(json.dumps({"version": _image3d_version(version.split(":")[0])}))
    (folder / "deploy-converter.json").write_text(json.dumps({"version": _converter_version()}))


def _converter_version() -> str:
    import hashlib

    digest = hashlib.sha256((ROOT / "deploy/serverless/convert_app.py").read_bytes())
    digest.update((ROOT / "tools/model-converter/convert.py").read_bytes())  # baked into the image: a change must show
    return digest.hexdigest()[:16]


@pytest.mark.parametrize("case", ["no-stamp", "stale", "garbled"])
def test_the_deploy_check_asks_for_the_converter_and_fails_closed(rig: Rig, case: str) -> None:
    _stamp(rig, _version(SHA))
    stamp = rig.root / "volumes" / "simon-part2-store" / "deploy-converter.json"
    assert rig.client("--check-deploy", "--part2-sha", SHA, "--need-converter").returncode == 0
    if case == "no-stamp":
        stamp.unlink()
    else:
        stamp.write_text("[not json" if case == "garbled" else json.dumps({"version": "an-older-image"}))
    done = rig.client("--check-deploy", "--part2-sha", SHA, "--need-converter")
    assert done.returncode == 81 and "deploy/serverless/deploy.sh" in done.stdout
    assert rig.client("--check-deploy", "--part2-sha", SHA).returncode == 0, "the flag asks, as --need-image3d does"


def test_up_sh_asks_for_the_converter_at_this_version(rig: Rig) -> None:
    _stamp(rig, _version(SHA))
    (rig.root / "volumes" / "simon-part2-store" / "deploy-converter.json").unlink()
    done = _up_check(rig)
    assert done.returncode == 1 and "converter" in done.stderr


def test_up_sh_passes_every_whole_number_setting_of_compute_conf() -> None:
    """The list in `build_env`, run by bash on the real compute.conf: a name left out never reaches the app."""
    source = (ROOT / "prod/up.sh").read_text(encoding="utf-8")
    start = source.index("  for name in SIMON7_SERVERLESS_MAX_CONCURRENT")
    loop = source[start:source.index("\n  done\n", start) + 8]
    script = f'set -u\nHERE={ROOT / "prod"}\nAPP_ENV=()\nname=""; value=""\n{loop}\nprintf "%s\\n" "${{APP_ENV[@]}}"\n'
    passed = subprocess.run(["bash", "-c", script], env={"PATH": os.environ["PATH"]}, capture_output=True, text=True, check=True).stdout
    assert "SIMON7_PART1_TIMEOUT_S=305" in passed.splitlines()
    conf = {line.split("=")[0] for line in (ROOT / "prod/compute.conf").read_text().splitlines() if line and not line.startswith("#")}
    assert conf - {line.split("=")[0] for line in passed.splitlines()} == {"SIMON7_MUSE_PROD"}, "SIMON7_MUSE_PROD has its own path"


def test_the_deploy_check_passes_at_this_releases_version(rig: Rig) -> None:
    _stamp(rig, _version(SHA))
    done = rig.client("--check-deploy", "--part2-sha", SHA)
    assert done.returncode == 0, done.stdout


@pytest.mark.parametrize("case", ["no-app", "no-volume", "no-stamp", "other-part2", "garbled"])
def test_the_deploy_check_fails_closed_and_names_the_command(rig: Rig, case: str) -> None:
    folder = rig.root / "volumes" / "simon-part2-store"
    if case == "no-app":
        _stamp(rig, _version(SHA))
        rig.mode("no-app")
    elif case == "no-stamp":
        folder.mkdir(parents=True)
    elif case == "other-part2":
        _stamp(rig, _version("b" * 40))
    elif case == "garbled":
        _stamp(rig, "x")
        (folder / "deploy.json").write_text("[not json")
    done = rig.client("--check-deploy", "--part2-sha", SHA)
    assert done.returncode == 81, done.stdout + done.stderr
    assert "deploy/serverless/deploy.sh" in done.stdout


def test_the_deploy_check_with_a_refused_token_is_a_stop(rig: Rig) -> None:
    rig.mode("refused")
    assert rig.client("--check-deploy", "--part2-sha", SHA).returncode == 80


def _wrapper_env(rig: Rig) -> dict[str, str]:
    return {"PATH": os.environ["PATH"], "HOME": str(rig.base), "SIMON7_MODAL_PYTHON": str(rig.python)}


def _checkout(base: Path) -> Path:
    """A copy of what the two scripts need, with modules/part-2 as a real git commit."""
    tree = base / "tree"
    (tree / "deploy/serverless").mkdir(parents=True)
    for name in ("p2_client.py", "part2_app.py", "image3d_app.py", "convert_app.py", "real_take.sh", "deploy.sh", "deploy_converter.sh",
                 "modal-requirements.txt"):
        shutil.copy(ROOT / "deploy/serverless" / name, tree / "deploy/serverless" / name)
    (tree / "prod").mkdir()
    shutil.copy(ROOT / "prod/compute.conf", tree / "prod/compute.conf")
    part2 = tree / "modules/part-2"
    part2.mkdir(parents=True)
    git = ["git", "-C", str(part2), "-c", "user.name=t", "-c", "user.email=t@example.test"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    return tree


def test_real_take_measures_a_cold_and_a_warm_call_with_no_server(rig: Rig) -> None:
    """AC-SC19: what the operator runs before the site is public, here against the fake."""
    tree = _checkout(rig.base)
    head = subprocess.run(["git", "-C", str(tree / "modules/part-2"), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    source = (tree / "deploy/serverless/part2_app.py").read_bytes()
    import hashlib

    _stamp(rig, f"{head}:{hashlib.sha256(source).hexdigest()[:16]}")
    out = rig.base / "measured"
    done = subprocess.run(["bash", str(tree / "deploy/serverless/real_take.sh"), "--secrets-dir", str(rig.secrets), "--clip",
                           str(rig.clip), "--out", str(out)], env=_wrapper_env(rig), capture_output=True, text=True,
                          timeout=120, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    lines = (out / "measurements.txt").read_text()
    for label in ("check exit=0", "track-1 exit=0", "pose-1 exit=0", "track-2 exit=0", "pose-2 exit=0"):
        assert label in lines
    assert "gpu_s" in lines and SECRET not in lines
    assert [c["argv"][0] for c in rig.calls()] == ["track", "run", "track", "run"]
    assert "local-open" in rig.calls()[0]["argv"]
    assert sorted(p.name for p in rig.store()) == ["deploy-converter.json", "deploy-image3d.json", "deploy.json"], "no take remains at Modal"
    every = "".join(p.read_text(errors="replace") for p in out.rglob("*") if p.is_file())
    assert SECRET not in every and TOKEN_ID not in every


def test_real_take_uses_the_frame_rates_of_a_prod_take() -> None:
    from part7.parts import p2_pose

    source = (ROOT / "deploy/serverless/real_take.sh").read_text()
    assert f"FPS={p2_pose.FPS} TRACK_FPS={p2_pose.TRACK_FPS_SINGLE} " in source


def test_real_take_refuses_inside_an_app_environment(rig: Rig) -> None:
    done = subprocess.run(["bash", str(ROOT / "deploy/serverless/real_take.sh"), "--secrets-dir", str(rig.secrets), "--clip",
                           str(rig.clip), "--out", str(rig.base / "o")], env={**_wrapper_env(rig), "FIRM_ENV": "prod"},
                          capture_output=True, text=True, timeout=30, check=False)
    assert done.returncode == 2 and "not from a stack" in done.stderr


def test_deploy_sh_stamps_only_after_a_deploy_that_worked_and_keeps_tokens_out_of_argv(rig: Rig) -> None:
    tree = _checkout(rig.base)
    tools = rig.base / "tools"
    tools.mkdir()
    log = rig.base / "uv.log"
    (tools / "uv").write_text(f'#!/bin/sh\necho "ARGV $*" >> "{log}"\necho "ENV ${{MODAL_TOKEN_SECRET:+set}} max=$SIMON7_SERVERLESS_MAX_CONCURRENT" >> "{log}"\n'
                              'case "$*" in *"modal deploy"*) exit ${FAKE_DEPLOY_EXIT:-0};; esac\nexit 0\n')
    (tools / "uv").chmod(0o755)
    env = {"PATH": f"{tools}:{os.environ['PATH']}", "HOME": str(rig.base)}
    script = str(tree / "deploy/serverless/deploy.sh")
    done = subprocess.run(["bash", script, "--secrets-dir", str(rig.secrets)], env=env, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    seen = log.read_text()
    assert seen.index("modal deploy") < seen.index("--stamp-deploy")
    assert seen.index("modal deploy deploy/serverless/convert_app.py") < seen.index("--stamp-deploy --converter")
    cap = next(line.split("=")[1] for line in (tree / "prod/compute.conf").read_text().splitlines() if line.startswith("SIMON7_SERVERLESS_MAX_CONCURRENT="))
    assert f"ENV set max={cap}" in seen and SECRET not in seen and SECRET not in done.stdout + done.stderr
    log.unlink()
    failed = subprocess.run(["bash", script], env={**env, "FAKE_DEPLOY_EXIT": "3"}, capture_output=True, text=True, check=False)
    assert failed.returncode == 3 and "--stamp-deploy" not in log.read_text(), "a failed deploy stamps nothing"


# ----- AC-SC16 in prod/up.sh: the function itself, run by bash, with the real client on the fake Modal ---------------------
def _up_check(rig: Rig, compute: str = "serverless", sha: str = "tree1") -> subprocess.CompletedProcess[str]:
    source = (ROOT / "prod/up.sh").read_text(encoding="utf-8")
    start = source.index("check_modal_app() {")
    body = source[start:source.index("\n}\n", start) + 3]
    tree, state = rig.base / "up-root", rig.base / "up-state"
    (tree / "modules/part-2").mkdir(parents=True, exist_ok=True)
    (tree / "modules/part-2/.firm-sha").write_text(SHA + "\n")
    (tree / "deploy").mkdir(exist_ok=True)
    if not (tree / "deploy/serverless").exists():
        (tree / "deploy/serverless").symlink_to(ROOT / "deploy/serverless")
    for folder in ("run", "logs"):
        (state / folder).mkdir(parents=True, exist_ok=True)
    script = f"""set -euo pipefail
ROOT={tree}; STATE={state}; APP_PY={sys.executable}; PROD_COMPUTE={compute}; PROD_SECRETS_DIR={rig.secrets}
tree_sha() {{ echo {sha}; }}
die() {{ echo "up: $*" >&2; exit 1; }}
build_env() {{ APP_ENV=("PATH=$PATH" "HOME={rig.base}" "SIMON7_MODAL_PYTHON={rig.python}"); }}
{body}
check_modal_app
"""
    return subprocess.run(["bash", "-c", script], env={"PATH": os.environ["PATH"]}, capture_output=True, text=True, timeout=60,
                          check=False)


def test_up_refuses_a_release_whose_app_is_not_deployed_and_names_the_command(rig: Rig) -> None:
    done = _up_check(rig)
    assert done.returncode == 1 and "deploy/serverless/deploy.sh" in done.stderr
    assert "nothing was started or stopped" in done.stderr and SECRET not in done.stderr


def test_up_refuses_another_version_and_passes_the_right_one(rig: Rig) -> None:
    _stamp(rig, _version("b" * 40))
    assert _up_check(rig).returncode == 1
    _stamp(rig, _version(SHA))
    assert _up_check(rig).returncode == 0, "the right version starts"


def test_a_checked_release_restarts_with_modal_down_and_another_does_not(rig: Rig) -> None:
    _stamp(rig, _version(SHA))
    assert _up_check(rig).returncode == 0
    rig.mode("refused")
    assert _up_check(rig).returncode == 0, "a restart does not depend on Modal"
    assert _up_check(rig, sha="tree2").returncode == 1, "a new release does"


def test_up_does_not_ask_modal_under_byok(rig: Rig) -> None:
    rig.mode("refused")
    assert _up_check(rig, compute="byok").returncode == 0


def test_an_empty_result_file_is_waited_for_not_read_as_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first real take: a background commit of the Volume showed result.json empty, and the client gave up on a good call."""
    monkeypatch.syspath_prepend(str(CLIENT.parent))
    import p2_client

    answers = [FileNotFoundError(), b"", b'{"exit": 0}']

    class Vol:
        def read_file(self, path: str):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            yield answer

    clock = iter(range(100))
    raw = p2_client._wait_result(Vol(), "k", lambda _s: None, lambda: float(next(clock)), 50.0)
    assert raw == b'{"exit": 0}' and not answers


# ----- AC-SC20: a picture takes the road a take takes -------------------------------------------------------------------
def _picture(rig: Rig) -> Path:
    path = rig.base / "image-1.jpg"
    path.write_bytes(b"\xff\xd8\xffPHOTO-BYTES")
    return path


def test_a_photo_goes_up_as_a_file_and_never_in_the_call(rig: Rig) -> None:
    done = rig.client("--ledger", str(rig.ledger), "--job", "m1", "--sha", SHA, "--", "avatar", "--out", str(rig.base / "out"),
                      str(_picture(rig)))
    assert done.returncode == 0, done.stdout + done.stderr
    call = rig.calls()[0]
    assert call["inputs"] == ["image-1.jpg"] and call["argv"] == ["avatar", "--out", "{out}", "{in}/image-1.jpg"]
    assert "PHOTO-BYTES" not in json.dumps(call) and rig.store() == [] and list(rig.ledger.iterdir()) == []


def test_a_picture_of_a_character_goes_to_its_own_app(rig: Rig) -> None:
    done = rig.client("--sha", SHA, "--", "image3d", "--out", str(rig.base / "out"), str(_picture(rig)))
    assert done.returncode == 0, done.stdout + done.stderr
    assert rig.calls()[0]["app"] == "simon-image3d" and rig.calls()[0]["argv"][0] == "image3d"
    assert rig.run_take().returncode == 0 and rig.calls()[-1]["app"] == "simon-part2"


def test_the_deploy_check_refuses_a_release_whose_picture_app_is_missing(rig: Rig) -> None:
    _stamp(rig, _version(SHA))
    (rig.root / "volumes" / "simon-part2-store" / "deploy-image3d.json").unlink()
    assert rig.client("--check-deploy", "--part2-sha", SHA, "--need-image3d").returncode == 81
    assert rig.client("--check-deploy", "--part2-sha", SHA).returncode == 0, "a release that offers no pictures does not need it"


# ----- AC-SC21: reading a finished take back. In process, so the pauses are recorded instead of slept -----------------
BLOCK_403 = f"Request failed with status 403 Forbidden: {SECRET}"
BLOCK_503 = f"Service temporarily unavailable: {SECRET}"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Reads:
    """The real client and the fake Modal in this process, against `rig`'s workspace."""

    def __init__(self, rig: Rig) -> None:
        self.rig, self.pauses = rig, []
        self.client = _load("p2_client_reads", CLIENT)
        self.modal = _load("fake_modal_reads", FAKE / "modal" / "__init__.py")

    def fault(self, file: str, times: int | None, error: str = "ExecutionError", text: str = BLOCK_403, partial: bool = False) -> None:
        doc = {"file": file, "times": times, "error": error, "text": text, "partial": partial}
        (self.rig.root / "read-fault.json").write_text(json.dumps(doc), encoding="utf-8")

    def take(self) -> int:
        sub = ["run", "--input", str(self.rig.clip), "--out", str(self.rig.base / "out")]
        return self.client._guarded_server(self.modal, lambda: self.client.run_server(
            self.modal, SHA, sub, self.rig.ledger, "job1", sleep=self.pauses.append))

    def read_pauses(self) -> int:
        return self.pauses.count(self.client.READ_PAUSE_S)

    def read_count(self, name: str) -> int:
        return (self.rig.root / "reads.log").read_text(encoding="utf-8").splitlines().count(name)


@pytest.fixture
def reads(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> Reads:
    monkeypatch.setenv("FAKE_MODAL_ROOT", str(rig.root))
    return Reads(rig)


def _kept_the_take(reads: Reads, code: int) -> None:
    assert code == 0
    assert (reads.rig.base / "out" / "result.txt").read_text() == "fake"
    assert reads.rig.store() == [] and list(reads.rig.ledger.iterdir()) == []
    assert len(reads.rig.calls()) == 1, "a read is tried again, the call never"


@pytest.mark.parametrize("file", ["started.json", "result.json", "metrics.json", "log.txt", "result.txt"])
@pytest.mark.parametrize(("error", "text", "word"), [("ExecutionError", BLOCK_403, "http_403"),
                                                      ("ServiceError", BLOCK_503, "block_503")])
def test_one_failed_read_is_tried_again_and_the_take_is_kept(reads: Reads, capsys: pytest.CaptureFixture[str], file: str, error: str,
                                                             text: str, word: str) -> None:
    """Jobs eb5d1ea0c5df and 4bf1668f6e90 finished on the GPU and failed on the read back."""
    reads.fault(file, 1, error, text)
    _kept_the_take(reads, reads.take())
    shown = capsys.readouterr().out
    assert f"reading {file} failed ({word}), trying again" in shown and SECRET not in shown
    assert reads.read_pauses() == 1 and reads.read_count(file) == 2


def test_a_retry_after_part_of_a_file_starts_the_file_again(reads: Reads) -> None:
    reads.fault("result.txt", 1, partial=True)
    _kept_the_take(reads, reads.take())
    assert reads.read_pauses() == 1, "the file holds `fake`, not `fafake`"


@pytest.mark.parametrize("file", ["metrics.json", "log.txt"])
def test_a_diagnostic_file_that_keeps_failing_never_costs_the_take(reads: Reads, capsys: pytest.CaptureFixture[str], file: str) -> None:
    reads.fault(file, None)
    _kept_the_take(reads, reads.take())
    shown = capsys.readouterr().out
    assert f"modal: {file} is not available (http_403)" in shown and SECRET not in shown
    assert "modal: measured" in shown and "modal: part2 exited 0" in shown
    assert reads.read_pauses() == reads.client.READ_TRIES - 1


def test_a_result_file_that_keeps_failing_ends_the_take_and_keeps_none_of_it(reads: Reads, capsys: pytest.CaptureFixture[str]) -> None:
    reads.fault("result.txt", None, partial=True)
    assert reads.take() == 80
    shown = capsys.readouterr().out
    assert "the remote Part 2 call failed (ExecutionError: http_403, last read result.txt)" in shown
    assert SECRET not in shown and "Forbidden" not in shown
    assert not (reads.rig.base / "out" / "result.txt").exists()
    assert reads.rig.store() == [] and len(reads.rig.calls()) == 1


def test_a_result_json_that_keeps_failing_ends_the_take_and_its_call(reads: Reads, capsys: pytest.CaptureFixture[str]) -> None:
    reads.fault("result.json", None, "ServiceError", BLOCK_503)
    assert reads.take() == 80
    shown = capsys.readouterr().out
    assert "the remote Part 2 call failed (ServiceError: block_503, last read result.json)" in shown and SECRET not in shown
    assert (reads.rig.root / "cancelled").exists() and reads.rig.store() == [] and len(reads.rig.calls()) == 1


def test_a_missing_file_and_a_refusal_are_not_tried_again(reads: Reads) -> None:
    vol = reads.modal.Volume.from_name("simon-part2-store", create_if_missing=True, version=2)
    with pytest.raises(FileNotFoundError):
        reads.client.read_head(vol, "nokey/absent.json", 100, reads.pauses.append)
    assert reads.pauses == [] and reads.read_count("absent.json") == 1
    (vol.base / "here.json").write_text("{}")
    reads.fault("here.json", None, "AuthError", "refused")
    with pytest.raises(reads.modal.exception.AuthError):
        reads.client.read_head(vol, "here.json", 100, reads.pauses.append)
    assert reads.pauses == [] and reads.read_count("here.json") == 1


@pytest.mark.parametrize(("text", "word"), [("Request failed with status 403 Forbidden: x", "http_403"),
                                            ("Get from url failed with status 500: x", "http_500"),
                                            ("Service temporarily unavailable: x", "block_503"),
                                            ("Block download corrupted: expected sha256 a, got b", "block_digest"),
                                            ("Block response is longer than the expected 9 bytes", "block_too_long"),
                                            ("the tool ended with exit status 127", "other"),
                                            (SECRET, "other")])
def test_a_failure_is_named_by_a_fixed_word(reads: Reads, text: str, word: str) -> None:
    assert reads.client.failure_class(RuntimeError(text)) == word
