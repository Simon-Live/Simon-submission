"""part2/gpu_guard.py: free memory through a fake nvidia-smi and the host GPU lock (docs/specs/run-app.md, Jobs).

No GPU is needed: nvidia-smi is a small script named by PART2_NVIDIA_SMI, and the lock file lives in tmp_path.
The lock itself is part2.trackers.gpu_lock (unchanged); gpu_guard wraps it and adds a non-blocking try.
"""
import subprocess
import sys
import time
from pathlib import Path

import pytest

from part2 import gpu_guard, trackers


@pytest.fixture(autouse=True)
def lock_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("PART2_GPU_LOCK", str(tmp_path / "gpu.lock"))
    return tmp_path / "gpu.lock"


def fake_smi(tmp_path: Path, monkeypatch, output: str = "", code: int = 0) -> Path:
    script = tmp_path / "nvidia-smi"
    script.write_text(f"#!/bin/sh\nprintf '{output}'\nexit {code}\n")
    script.chmod(0o755)
    monkeypatch.setenv("PART2_NVIDIA_SMI", str(script))
    return script


# ---- free memory ------------------------------------------------------------------------------------

def test_parse_smi_reads_the_first_gpu_in_gib():
    assert gpu_guard.parse_smi("27951, 32607\n") == {"free_gib": 27.3, "total_gib": 31.84}
    assert gpu_guard.parse_smi("\n4096, 8192\n20480, 32768\n") == {"free_gib": 4.0, "total_gib": 8.0}


@pytest.mark.parametrize("text", ["", "\n", "N/A, N/A", "12", "a, b", "-5, 100", "100, 0"])
def test_parse_smi_refuses_anything_but_two_numbers(text):
    assert gpu_guard.parse_smi(text) is None


def test_query_and_free_gib_through_a_fake_nvidia_smi(tmp_path, monkeypatch):
    script = fake_smi(tmp_path, monkeypatch, "4096, 32768\\n")
    assert gpu_guard.query() == {"free_gib": 4.0, "total_gib": 32.0}
    assert gpu_guard.free_gib() == 4.0
    assert gpu_guard.smi_command() == [str(script), *gpu_guard.SMI_ARGS]


def test_a_failing_or_missing_nvidia_smi_is_none(tmp_path, monkeypatch):
    fake_smi(tmp_path, monkeypatch, "NVIDIA-SMI has failed", code=9)
    assert gpu_guard.query() is None and gpu_guard.free_gib() is None
    monkeypatch.setenv("PART2_NVIDIA_SMI", str(tmp_path / "absent"))
    assert gpu_guard.query() is None
    monkeypatch.delenv("PART2_NVIDIA_SMI")
    monkeypatch.setattr(gpu_guard.shutil, "which", lambda name: None)
    assert gpu_guard.smi_command() is None and gpu_guard.free_gib() is None


def test_the_query_is_the_documented_one():
    assert "--query-gpu=memory.free,memory.total" in gpu_guard.SMI_ARGS
    assert "--format=csv,noheader,nounits" in gpu_guard.SMI_ARGS
    assert gpu_guard.MIN_FREE_GIB == 12.0


# ---- the lock --------------------------------------------------------------------------------------------

def test_the_lock_file_is_the_trackers_one(lock_in_tmp, monkeypatch):
    assert gpu_guard.lock_path() == lock_in_tmp
    monkeypatch.delenv("PART2_GPU_LOCK")
    assert gpu_guard.lock_path() == Path(trackers.GPU_LOCK_DEFAULT).expanduser()


def test_try_lock_is_exclusive_until_released(lock_in_tmp):
    first = gpu_guard.try_lock()
    assert first is not None and lock_in_tmp.exists()
    assert gpu_guard.try_lock() is None
    gpu_guard.release(first)
    again = gpu_guard.try_lock()
    assert again is not None
    gpu_guard.release(again)
    gpu_guard.release(again)          # releasing twice is harmless
    gpu_guard.release(None)


def test_gpu_lock_is_the_trackers_lock_and_waits_then_raises_gpu_busy():
    held = gpu_guard.try_lock()
    try:
        t0 = time.monotonic()
        with pytest.raises(trackers.GpuBusy, match="^another GPU job is running$"):
            with gpu_guard.gpu_lock(wait_s=0.2, poll_s=0.05):
                pass
        assert time.monotonic() - t0 >= 0.2
    finally:
        gpu_guard.release(held)
    with gpu_guard.gpu_lock(wait_s=0.1):
        assert gpu_guard.try_lock() is None          # held inside the block, seen by try_lock
    probe = gpu_guard.try_lock()
    assert probe is not None                         # released after it
    gpu_guard.release(probe)
    with trackers.gpu_lock(wait_s=0.1):
        assert gpu_guard.try_lock() is None          # the trackers' own lock is the same lock


def test_gpu_lock_defaults_to_the_trackers_wait(monkeypatch):
    seen = {}
    monkeypatch.setattr(trackers, "gpu_lock", lambda wait_s, poll_s: seen.update(wait_s=wait_s, poll_s=poll_s) or "cm")
    assert gpu_guard.gpu_lock() == "cm" and seen == {"wait_s": trackers.GPU_LOCK_WAIT_S, "poll_s": 1.0}
    gpu_guard.gpu_lock(wait_s=5, poll_s=0.5)
    assert seen == {"wait_s": 5, "poll_s": 0.5}


def test_importing_gpu_guard_does_not_import_the_trackers():
    code = "import sys, part2.gpu_guard; print('part2.trackers' in sys.modules)"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30,
                          cwd=Path(__file__).resolve().parent.parent)
    assert done.stdout.strip() == "False", done.stderr
