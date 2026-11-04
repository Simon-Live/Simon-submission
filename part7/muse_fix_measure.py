"""Re-measure a returned image with SAM 3D Body (docs/specs/muse-fix.md, TICKET-280).

`measure(image_path)` on the operator's Modal workspace (serverless mode, prod) sends the one image through the route a take uses
(`serverless_route.command`, `part2 run --mode single --input <image>`: Part 2 reads a single image as a one-frame video) and
reads `pose3d.json` back; no model loads on this host. Otherwise it runs `python -m part2 run --mode single` on a folder holding the one image, under `gpu_lock`,
with Part 2's GPU venv (the way `avatar_jobs` runs Part 2), and returns the first person's pose3d joints of that
image, or None when Part 2 found nobody or did not run. Part 2 is a black box (ADR-0002): only its CLI and its
`pose3d.json` are used. The caller can pass any function with this signature in place of `measure`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from typing import Any

from part7 import avatar_jobs, byok_route, compute_mode, config, gpu_lock, modules, serverless_route

MIN_FREE_MIB = 8192
LOCK_TIMEOUT_S = 900.0
RUN_TIMEOUT_S = 600.0
PROBE_TIMEOUT_S = 45.0
_SECRET_ENV = re.compile(r"KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL", re.IGNORECASE)


class CheckFailed(Exception):
    """The picture was not looked at (Modal busy, stopped, a token or a failed call): no answer about the pose, a retry waits."""


def available() -> bool:
    """A check can run: on Modal in serverless mode, else Part 2 and its GPU venv are here. Never on this host under BYOK-only
    (nofallback D1): then `measure` answers None and `muse_fix.run` sends nothing."""
    if compute_mode.serverless():
        return True
    if byok_route.host_models_refused():
        return False
    return (config.part_dir(2) / "part2" / "cli.py").is_file() and (config.part2_gpu_venv_path() / "bin" / "python").is_file()


def reachable() -> bool:
    """Whether the check can run now, read before any paid call (R14). On this host's own GPU: True, `available` already said so.
    On Modal: one lookup of Simon's app and its deploy stamp through the launcher's `--check-deploy` (metadata only, no GPU container
    starts, so no cold start and no GPU cost). A stopped workspace, a refused token, a missing app, another release or an answer that
    does not come within PROBE_TIMEOUT_S all read False: unknown counts as no, since a paid picture nobody can check is the loss."""
    if not compute_mode.serverless():
        return True
    try:
        argv = [sys.executable, "-I", str(serverless_route.CLIENT), "--serverless", "--secrets-dir", str(config.keys_dir()),
                "--check-deploy", "--part2-sha", modules.load().sha("2")]
        done = subprocess.run(argv, cwd=config.REPO_ROOT, env=avatar_jobs._environment(config.REPO_ROOT), capture_output=True,
                              stdin=subprocess.DEVNULL, timeout=PROBE_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired, modules.ModuleError):
        return False
    return done.returncode == 0


def read_joints(out_dir: Path) -> dict[str, Any] | None:
    """The joints of the first person of the first frame of `pose3d.json` in `out_dir`, else None."""
    try:
        doc = json.loads((out_dir / "pose3d.json").read_text(encoding="utf-8"))
        people = doc["frames"][0]["people"]
        joints = people[0]["joints"] if people else None
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None
    return joints if isinstance(joints, dict) and joints else None


def _run(argv: list[str], cwd: Path, env: dict[str, str]) -> int | None:
    """Run Part 2 in its own session; on the timeout kill the group this call started (and nothing else)."""
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        return proc.wait(timeout=RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        proc.wait()
        return None


def _on_modal(src: Path) -> dict[str, Any] | None:
    """The joints of the picture from one Part 2 call on Modal. Part 2's own "nobody found" (exit 4) is None; any other
    failed call raises CheckFailed, since it says nothing about the picture."""
    work = Path(tempfile.mkdtemp(prefix="muse-fix-measure-"))
    try:
        image = work / ("candidate" + src.suffix.lower())
        shutil.copyfile(src, image)
        sub = ["run", "--mode", "single", "--input", str(image), "--out", str(work / "out"), "--fps", "1", "--backend", "gpu"]
        try:
            argv = serverless_route.command(sub, modules.load().sha("2"), work)
            done = subprocess.run(argv, cwd=config.REPO_ROOT, env=avatar_jobs._environment(config.REPO_ROOT), capture_output=True,
                                  stdin=subprocess.DEVNULL, timeout=serverless_route.timeout_s(RUN_TIMEOUT_S), check=False)
        except (OSError, subprocess.TimeoutExpired, modules.ModuleError) as exc:
            raise CheckFailed(type(exc).__name__) from None
        serverless_route.note_exit(done.returncode)
        if done.returncode == 0:
            return read_joints(work / "out")
        if done.returncode == 4:
            return None
        raise CheckFailed(f"exit {done.returncode}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def measure(image_path: Path | str) -> dict[str, Any] | None:
    if compute_mode.serverless():
        return _on_modal(Path(image_path))
    if not available():
        return None
    part2, py = config.part_dir(2), config.part2_gpu_venv_path() / "bin" / "python"
    env = {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}
    env["PYTHONPATH"] = str(part2)
    src = Path(image_path)
    work = Path(tempfile.mkdtemp(prefix="muse-fix-measure-"))
    try:
        (work / "in").mkdir()
        shutil.copyfile(src, work / "in" / ("000000" + src.suffix.lower()))
        argv = [str(py), "-m", "part2", "run", "--input", str(work / "in"), "--out", str(work / "out"), "--mode", "single",
                "--backend", "gpu", "--fps", "1"]
        try:
            with gpu_lock.acquire(min_free_mib=MIN_FREE_MIB, timeout_s=LOCK_TIMEOUT_S, hold_flock=False):
                code = _run(argv, part2, env)
        except (TimeoutError, OSError):
            return None
        return read_joints(work / "out") if code == 0 else None
    finally:
        shutil.rmtree(work, ignore_errors=True)
