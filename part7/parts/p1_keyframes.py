"""Part 1 adapter: key frame detection and run-wide spend cap (TICKET-010)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Any

from part7 import config, keys, pins, runner


def _extract_spend(data: Any) -> float:
    if isinstance(data, (int, float)):
        return float(data)
    if isinstance(data, dict):
        for field in ("usd", "total_usd", "total", "spend_usd"):
            val = data.get(field)
            if isinstance(val, (int, float)):
                return float(val)
        entries = data.get("entries")
        if isinstance(entries, list):
            return sum(
                float(item.get("usd", 0.0))
                for item in entries
                if isinstance(item, dict) and isinstance(item.get("usd"), (int, float))
            )
    if isinstance(data, list):
        return sum(
            float(item.get("usd", item.get("cost_usd", 0.0)))
            for item in data
            if isinstance(item, dict)
            and isinstance(item.get("usd", item.get("cost_usd", 0.0)), (int, float))
        )
    return 0.0


def total_spend_usd(state: Path | str | None = None) -> float:
    """Sum `.meta-spend.json` across all pinned `1@*` clones under `parts_dir` (AC-H10)."""
    pdir = config.parts_dir(state)
    if not pdir.is_dir():
        return 0.0
    total = 0.0
    for clone in sorted(pdir.glob("1@*")):
        ledger = clone / ".meta-spend.json"
        if not ledger.is_file():
            continue
        try:
            data = json.loads(ledger.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        total += _extract_spend(data)
    return round(total, 6)


def run(
    video: Path | str,
    work: Path | str,
    lock: pins.Lock | None = None,
    state: Path | str | None = None,
    keys_dir: Path | str | None = None,
    timeout_s: float | None = None,
) -> tuple[runner.Step | None, Path | None, str | None]:
    """Run Part 1 on `video` if under the $5 cap and `MODEL_API_KEY` is present (`timeout_s` caps the call)."""
    if total_spend_usd(state) >= config.PART1_RUN_SPEND_CAP_USD:
        return (None, None, "spend cap")

    if not keys.has_key("MODEL_API_KEY", keys_dir=keys_dir):
        return (None, None, "key frames from Part 3, Part 1 unavailable")

    lk = lock or pins.load()
    clone = lk.path("1", state=state)
    video_p = Path(video)
    work_p = Path(work)
    work_p.mkdir(parents=True, exist_ok=True)

    sha12 = hashlib.sha256(video_p.read_bytes()).hexdigest()[:12]
    stem = f"p7-{sha12}"
    inbox_rel = f"inbox/{stem}.mp4"
    inbox_copy = clone / inbox_rel
    inbox_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(video_p, inbox_copy)

    venv_py = clone / ".venv" / "bin" / "python"
    py_exe = str(venv_py) if venv_py.exists() else sys.executable
    log_path = work_p / "steps" / "part1.log"

    # Call -m keyframe_finder.from_video on the single clip, never make keyframes, because inbox/*.mp4 in a GIT_LFS_SKIP_SMUDGE=1 clone are LFS pointer files.
    step: runner.Step | None = None
    try:
        with keys.part1_dotenv(clone, keys_dir=keys_dir) as has_env:
            if not has_env:
                return (None, None, "key frames from Part 3, Part 1 unavailable")
            step = runner.run(
                1,
                [py_exe, "-m", "keyframe_finder.from_video", inbox_rel],
                cwd=clone,
                timeout_s=timeout_s if timeout_s is not None else config.TIMEOUTS["1"],
                log_path=log_path,
                lock=lk,
            )
    finally:
        inbox_copy.unlink(missing_ok=True)

    out_kf = clone / "out" / stem / "keyframes.json"
    if step is not None and step["exit"] == 0 and out_kf.is_file():
        dst = work_p / "keyframes.json"
        shutil.copyfile(out_kf, dst)
        return (step, dst, None)

    exit_code = step["exit"] if step is not None else "none"
    return (step, None, f"key frames from Part 3, Part 1 exited {exit_code}")


def doctor(
    keyframes_path: Path | str,
    work: Path | str,
    lock: pins.Lock | None = None,
    state: Path | str | None = None,
) -> runner.Step:
    """Validate a Part 1 `keyframes.json` using Part 6's `doctor` command."""
    lk = lock or pins.load()
    clone6 = lk.path("6", state=state)
    work_p = Path(work)
    return runner.run(
        6,
        ["python3", "-m", "part6", "doctor", str(Path(keyframes_path).resolve())],
        cwd=clone6,
        timeout_s=config.TIMEOUTS["doctor"],
        log_path=work_p / "steps" / "part1_doctor.log",
        lock=lk,
    )
