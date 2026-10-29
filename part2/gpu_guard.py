"""GPU guard: free GPU memory through nvidia-smi, and the host's one-GPU-job lock for the web app's worker.

Spec: docs/specs/run-app.md (Jobs), docs/specs/tracker-registry.md (GPU lock held), ADR-0007.

    q = gpu_guard.query()             # {"free_gib", "total_gib"} of GPU 0, or None without nvidia-smi
    gib = gpu_guard.free_gib()        # free GiB of GPU 0, or None
    with gpu_guard.gpu_lock(wait_s=600):   # part2.trackers.gpu_lock: waits, then raises trackers.GpuBusy
        ...
    f = gpu_guard.try_lock()          # the same lock without waiting: the open file, or None when it is held
    gpu_guard.release(f)

The lock is the flock of part2.trackers (PART2_GPU_LOCK, default ~/.local/state/simon-part-2/gpu.lock), shared by
`make outputs`, the SAM trackers and the job worker. part2.trackers is imported inside the functions only, so
importing this module stays light.
"""
from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
from pathlib import Path

MIN_FREE_GIB = 12.0
SMI_ENV = "PART2_NVIDIA_SMI"          # path of the nvidia-smi to run (tests point it at a fake)
SMI_ARGS = ("--query-gpu=memory.free,memory.total", "--format=csv,noheader,nounits")
SMI_TIMEOUT_S = 10


# ---- free memory ------------------------------------------------------------------------------------

def smi_command() -> list[str] | None:
    exe = os.environ.get(SMI_ENV) or shutil.which("nvidia-smi")
    return [exe, *SMI_ARGS] if exe else None


def parse_smi(text: str) -> dict | None:
    """The first GPU's line "<free MiB>, <total MiB>" as GiB; None when it is not two numbers."""
    line = next((ln for ln in text.splitlines() if ln.strip()), "")
    try:
        free, total = (float(p) for p in line.split(",")[:2])
    except ValueError:
        return None
    if free < 0 or total <= 0:
        return None
    return {"free_gib": round(free / 1024, 2), "total_gib": round(total / 1024, 2)}


def query() -> dict | None:
    """Free and total memory of GPU 0 in GiB, or None when nvidia-smi is absent or fails."""
    cmd = smi_command()
    if cmd is None:
        return None
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=SMI_TIMEOUT_S, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_smi(out)


def free_gib() -> float | None:
    q = query()
    return None if q is None else q["free_gib"]


# ---- the lock ----------------------------------------------------------------------------------------

def lock_path() -> Path:
    from part2 import trackers

    return Path(os.environ.get(trackers.GPU_LOCK_ENV) or trackers.GPU_LOCK_DEFAULT).expanduser()


def gpu_lock(wait_s: float | None = None, poll_s: float = 1.0):
    """part2.trackers.gpu_lock (a context manager): one GPU inference at a time on this host."""
    from part2 import trackers

    return trackers.gpu_lock(trackers.GPU_LOCK_WAIT_S if wait_s is None else wait_s, poll_s)


def try_lock(path: Path | None = None):
    """Take the lock without waiting: the open lock file (keep it to hold the lock), or None if it is held."""
    path = Path(path or lock_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    f = path.open("a")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return None
    return f


def release(f) -> None:
    """Drop a lock taken by try_lock."""
    if f is None or f.closed:
        return
    try:
        fcntl.flock(f, fcntl.LOCK_UN)
    finally:
        f.close()
