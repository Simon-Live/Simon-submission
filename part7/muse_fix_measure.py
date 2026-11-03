"""Re-measure a returned image with SAM 3D Body (docs/specs/muse-fix.md, TICKET-280).

`measure(image_path)` runs `python -m part2 run --mode single` on a folder holding the one image, under `gpu_lock`,
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
import tempfile
from typing import Any

from part7 import config, gpu_lock

MIN_FREE_MIB = 8192
LOCK_TIMEOUT_S = 900.0
RUN_TIMEOUT_S = 600.0
_SECRET_ENV = re.compile(r"KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL", re.IGNORECASE)


def available() -> bool:
    return (config.part_dir(2) / "part2" / "cli.py").is_file() and (config.part2_gpu_venv_path() / "bin" / "python").is_file()


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


def measure(image_path: Path | str) -> dict[str, Any] | None:
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
