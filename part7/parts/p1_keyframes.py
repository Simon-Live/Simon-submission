"""Part 1 adapter: key frame detection and run-wide spend cap (TICKET-010)."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import shutil
import sys
from typing import Any

from part7 import applog, config, keys, modules, part1_breaker, runner

# Part 1 has no retry around Meta's streamed SAM answer; a stream cut short ends the run with exit 1 (3 staging
# jobs on 2026-10-30, TICKET-064). These names in its output mean the network dropped, not that the clip is bad.
TRANSIENT_MARKERS = ("IncompleteRead", "RemoteDisconnected", "ConnectionResetError", "ProtocolError")
RETRY_MIN_S = 40.0  # retry only when at least this much of Part 1's time budget is left


def transient_failure(step: runner.Step) -> bool:
    """True when Part 1 exited non-zero (not by timeout) because a network stream was cut."""
    return step["exit"] not in (0, None) and not step.get("timed_out") and any(
        marker in step.stdout for marker in TRANSIENT_MARKERS
    )


def _log_open(until: float, work: Path) -> None:
    """`ANOMALY part1_circuit_open` is the text monitors match (TICKET-089)."""
    applog.log(f"ANOMALY part1_circuit_open: part 1 circuit open until {part1_breaker.until_text(until)}",
               applog.job_id_of(work), work, logging.WARNING)


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
    """Part 1's `.meta-spend.json` in its module (AC-H10)."""
    ledger = config.part_dir("1") / ".meta-spend.json"
    if not ledger.is_file():
        return 0.0
    try:
        return round(_extract_spend(json.loads(ledger.read_text(encoding="utf-8"))), 6)
    except (OSError, json.JSONDecodeError):
        return 0.0


def run(
    video: Path | str,
    work: Path | str,
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
    keys_dir: Path | str | None = None,
    timeout_s: float | None = None,
) -> tuple[runner.Step | None, Path | None, str | None]:
    """Run Part 1 on `video` if under the cap (off unless `SIMON7_PART1_SPEND_CAP_USD` is set) and `MODEL_API_KEY` is present (`timeout_s` caps the call)."""
    if config.part1_spend_capped(total_spend_usd(state)):
        return (None, None, "spend cap")

    if not keys.has_key("MODEL_API_KEY", keys_dir=keys_dir):
        return (None, None, "key frames from Part 3, Part 1 unavailable")

    work_p = Path(work)
    breaker = part1_breaker.enabled()
    if breaker:
        allowed, until = part1_breaker.allow(state)
        if not allowed:
            _log_open(until, work_p)
            return (None, None, part1_breaker.pause_note(until))

    lk = lock or modules.load()
    clone = lk.path("1")
    video_p = Path(video)
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
    budget = timeout_s if timeout_s is not None else config.TIMEOUTS["1"]
    argv = [py_exe, "-m", "keyframe_finder.from_video", inbox_rel]
    applog.log(f"Part 1 starts with a {budget:.0f} s budget (a retry after a cut stream needs {RETRY_MIN_S:.0f} s left)",
               applog.job_id_of(work_p), work_p)
    try:
        with keys.part1_dotenv(clone, keys_dir=keys_dir) as has_env:
            if not has_env:
                return (None, None, "key frames from Part 3, Part 1 unavailable")
            step = runner.run(1, argv, cwd=clone, timeout_s=budget, log_path=log_path, lock=lk)
            left = budget - float(step["duration_s"])
            if transient_failure(step) and left < RETRY_MIN_S:
                applog.log(f"Part 1 lost its network stream after {step['duration_s']:.1f} s, no second try: "
                           f"{max(left, 0.0):.1f} s of its {budget:.0f} s budget left (a retry needs "
                           f"{RETRY_MIN_S:.0f} s)", applog.job_id_of(work_p), work_p, logging.WARNING)
            if transient_failure(step) and left >= RETRY_MIN_S:
                if config.part1_spend_capped(total_spend_usd(state)):  # the first try may have spent the rest
                    applog.log("Part 1 lost its network stream and the spend cap is reached, no second try",
                               applog.job_id_of(work_p), work_p, logging.WARNING)
                    return (step, None, "spend cap")
                first = log_path.with_name("part1.try1.log")
                log_path.replace(first)
                applog.log(f"Part 1 lost its network stream after {step['duration_s']:.1f} s, retrying once with "
                           f"{left:.0f} s left of its {budget:.0f} s budget (first try in {first.name})", applog.job_id_of(work_p), work_p,
                           logging.WARNING)
                first_try = {**step, "log": str(first)}
                step = runner.run(1, argv, cwd=clone, timeout_s=left, log_path=log_path, lock=lk)
                step["first_try"] = first_try  # the job record keeps both tries
    finally:
        inbox_copy.unlink(missing_ok=True)

    if breaker and step is not None:
        outcome = "ok" if step["exit"] == 0 else "transient" if step.get("timed_out") or transient_failure(step) else "other"
        opened = part1_breaker.record(outcome, state)
        if opened:
            _log_open(opened, work_p)

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
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
) -> runner.Step:
    """Validate a Part 1 `keyframes.json` using Part 6's `doctor` command."""
    lk = lock or modules.load()
    clone6 = lk.path("6")
    work_p = Path(work)
    return runner.run(
        6,
        ["python3", "-m", "part6", "doctor", str(Path(keyframes_path).resolve())],
        cwd=clone6,
        timeout_s=config.TIMEOUTS["doctor"],
        log_path=work_p / "steps" / "part1_doctor.log",
        lock=lk,
    )
