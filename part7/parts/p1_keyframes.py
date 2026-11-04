"""Part 1 adapter: key frame detection and run-wide spend cap (TICKET-010)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any
import uuid

from part7 import applog, config, ffsafe, keys, media, modules, muse_prod, part1_breaker, prod_mode, runner

# Part 1 tries a cut upload or SAM stream again itself (`SAM_TRIES = 2`, TICKET-380), so Part 7 starts it once and one
# Part 1 run costs at most 2 SAM calls; a take cut off at restart drains can reach 3 runs (`jobs.CUT_REQUEUE_MAX`). As the
# exception that ended the run, these names mean the network dropped, not that the clip is bad. `StreamCut` is what Part 1
# raises when every try was cut; a stream closed without `response.completed` carries no other name.
TRANSIENT_MARKERS = ("StreamCut", "IncompleteRead", "RemoteDisconnected", "ConnectionResetError", "ProtocolError")
CUT_NOTE = "key frames from Part 3, Part 1 lost its network stream"
# The line opens with the exception's name, module path allowed. A cut Part 1 survived prints its own line earlier in
# the same output, and an unrelated error's message may quote a marker: neither is the cause of the exit.
_CUT_EXCEPTION = re.compile(r"(?:[\w.]+\.)?(?:" + "|".join(TRANSIENT_MARKERS) + r")\b")
# Part 1 skips a second SAM try that this time could not cover. The runner's SIGTERM comes `_stop_times(budget)[0]` after
# the process starts; the margin leaves the run time to end by itself, before any signal.
DEADLINE_ENV = "SIMON_P1_DEADLINE"
DEADLINE_BEFORE_KILL_S = 5.0
# SIGTERM to SIGKILL (TICKET-388). Part 1's handler ends the run so its `finally` deletes the upload at Meta, and
# `delete_file` waits up to 60 s for a slow answer; 5 s more lets it print its line and exit. The grace is taken out of the
# budget, so SIGKILL never comes later than the budget, and it never takes more than half a short budget.
STOP_GRACE_S = 65.0
# A stop that did not come from our own timeout (`timed_out` is set then): a restart or the host's memory guard. It says
# nothing about Meta's network, so it is not a cut and does not touch the breaker.
_SIGTERM_EXITS = (143, -15)
_NO_TIME_LEFT = "giving up (no time left for another try)"
LEFTOVER_AGE_S = config.TIMEOUTS["1"] + 600.0  # older than any live Part 1 run can be
_RETRIED_CUT = re.compile(r"\s*(SAM 3\.1 stream (?:cut|closed) after \d+ frames.*?|upload cut \(\w+\)); trying again\s*$")
# Part 1's own lines about a clip at Meta, as of 29b018b. `delete_file failed` ends in `: <reason>`.
_FILE_LINE = re.compile(r"\s*((uploaded|delete_file ok|delete_file failed) file_id=(\S+?)(?:: .*)?)\s*$")


def _final_line(step: runner.Step) -> str:
    """Part 1's last output line: on a crash, the exception that ended the run."""
    lines = step.stdout.strip().splitlines()
    return lines[-1].strip() if lines else ""


def transient_failure(step: runner.Step) -> bool:
    """True when Part 1 exited non-zero (not by timeout or SIGTERM) and the exception that ended it is a cut network stream."""
    return step["exit"] not in (0, None, *_SIGTERM_EXITS) and not step.get("timed_out") and bool(_CUT_EXCEPTION.match(_final_line(step)))


def _stopped_from_outside(step: runner.Step) -> bool:
    """SIGTERM from anyone but the runner's own timeout, which reports `timed_out` and `exit` None."""
    return step["exit"] in _SIGTERM_EXITS and not step.get("timed_out")


def _cut_line(step: runner.Step) -> str:
    """The exception that ended the run: `StreamCut` says how many frames arrived, which shows where streams die."""
    return _final_line(step)[:200] or "no detail"


def _stop_times(budget: float) -> tuple[float, float]:
    """`(seconds to SIGTERM, seconds from there to SIGKILL)`; together they are exactly `budget`."""
    grace = min(STOP_GRACE_S, budget / 2)
    return (budget - grace, grace)


def _deadline_env(term_after_s: float) -> dict[str, str]:
    """`SIMON_P1_DEADLINE` in whole Unix seconds, read just before the process starts so it is earlier than SIGTERM."""
    return {DEADLINE_ENV: str(int(time.time() + term_after_s - DEADLINE_BEFORE_KILL_S))}


def _run_dir(source: Path, state: Path | str | None) -> Path:
    """Where Part 1 runs. Part 1 writes `.env`, `inbox/` and `out/` beside its code, and prod's release tree is read-only, so prod
    runs from one copy of the code per pin in the app state (docs/specs/muse-prod.md AC-MP7); the key sits there, and `sweep` clears it
    at start and with each retention sweep. Elsewhere, the clone itself."""
    if not prod_mode.is_prod():
        return source
    sha_file = source / ".firm-sha"
    pin = sha_file.read_text(encoding="utf-8").strip()[:12] if sha_file.is_file() else "unpinned"
    target = config.state_root(state) / "part1" / pin
    if not (target / "keyframe_finder").is_dir():
        scratch = target.with_name(f"{pin}.{os.getpid()}.tmp")
        shutil.copytree(source, scratch, ignore=shutil.ignore_patterns(".venv", ".git", "inbox", "out", "fixtures"), dirs_exist_ok=True)
        try:
            scratch.rename(target)
        except OSError:  # another job made it first
            shutil.rmtree(scratch, ignore_errors=True)
    return target


def _clear_run(clone: Path, stem: str) -> None:
    """Prod only: what Part 1 leaves of one clip beside its code, the clip itself and its tracks, goes as the run ends (AC-MP9)."""
    if not prod_mode.is_prod():
        return
    shutil.rmtree(clone / "out" / stem, ignore_errors=True)
    for left in (clone / "out" / "work").glob(f"{stem}*"):
        left.unlink(missing_ok=True)


def _take_output(step: runner.Step | None, clone: Path, stem: str, work: Path) -> Path | None:
    """Copy the key frames into the job, then clear the run. Called from the `finally`, so a run that raised is cleared too."""
    out_kf, kept = clone / "out" / stem / "keyframes.json", None
    if step is not None and step["exit"] == 0 and out_kf.is_file():
        kept = work / "keyframes.json"
        shutil.copyfile(out_kf, kept)
    _clear_run(clone, stem)
    return kept


def _old(path: Path, now: float) -> bool:
    try:
        return now - path.stat().st_mtime > LEFTOVER_AGE_S
    except OSError:
        return False


def sweep(state: Path | str | None = None, now: float | None = None) -> int:
    """Prod only, with the periodic sweep: what a killed run could not clear (AC-MP9), once no live run can still be using it.
    A `.env` goes unless a live run holds it, so a key on disk does not wait for the next take. Returns the items removed."""
    if not prod_mode.is_prod():
        return 0
    moment, removed = time.time() if now is None else now, 0
    for copy in (config.state_root(state) / "part1").glob("*"):
        if not copy.is_dir():
            continue
        keys.drop_part1_env(copy)
        for folder in (copy / "out" / "work", copy / "out", copy / "inbox"):
            for item in list(folder.glob("*")) if folder.is_dir() else []:
                if item.name == "work" or not _old(item, moment):
                    continue
                shutil.rmtree(item, ignore_errors=True) if item.is_dir() else item.unlink(missing_ok=True)
                removed += 1
    return removed


def _safe_input(video: Path, work: Path) -> Path:
    """In prod Part 1's own ffmpeg, which has the network, reads only a copy Part 7 re-encoded inside `ffsafe`, without its sound."""
    if not prod_mode.is_prod() or video.name == "person.mp4":  # the crop to a person is already that copy (crop.crop_video)
        return video
    copy = work / "part1-input.mp4"
    res = ffsafe.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                      "-pix_fmt", "yuv420p", "-an", *media.FRAME_CAP_ARGS, str(copy)], timeout=120, text=True)
    if res.returncode != 0 or not copy.is_file():
        raise RuntimeError("the copy for Part 1 could not be made")
    return copy


def _cut_cost(step: runner.Step) -> str:
    """What the cut run spent on trying: a run stopped by the deadline did not get its second try."""
    no_time = any(line.rstrip().endswith(_NO_TIME_LEFT) for line in step.stdout.splitlines())
    return "no time left for another try" if no_time else "its own retry included"


def _log_retried_cuts(step: runner.Step, work: Path) -> None:
    """One `part7.log` line per cut Part 1 tried again, with its frame count, whatever the run went on to do (R8)."""
    for line in step.stdout.splitlines():
        match = _RETRIED_CUT.match(line)
        if match:
            applog.log(f"Part 1 tried again after a cut: {match.group(1)}", applog.job_id_of(work), work)


def _log_clip_lines(step: runner.Step, work: Path) -> None:
    """One `part7.log` line per upload and delete Part 1 printed, so a clip left at Meta is found per job with
    `grep delete_file` (TICKET-388). An upload with no delete line means the run was killed before it could say."""
    job = applog.job_id_of(work)
    open_ids: list[str] = []
    for line in step.stdout.splitlines():
        match = _FILE_LINE.match(line)
        if not match:
            continue
        text, kind, file_id = match.groups()
        applog.log(f"Part 1 {text}", job, work, logging.WARNING if kind == "delete_file failed" else logging.INFO)
        if kind == "uploaded":
            open_ids.append(file_id)
        elif file_id in open_ids:
            open_ids.remove(file_id)
    for file_id in open_ids:
        applog.log(f"Part 1 delete_file missing file_id={file_id}: the run ended with no delete line, "
                   "the clip may still be at Meta", job, work, logging.WARNING)


def _log_stop(step: runner.Step, work: Path) -> None:
    """How a run the budget stopped ended: exit 143 is Part 1's handler, -9 is SIGKILL at the end of the grace."""
    if step.get("stop_exit") is not None:
        applog.log(f"Part 1 stopped at {applog.secs(step['timeout_s'])} s: exit {step['stop_exit']} after "
                   f"{step['duration_s']:.1f} s", applog.job_id_of(work), work)


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

    if not keys.has_key("MODEL_API_KEY", keys_dir=keys_dir) or muse_prod.gate(state) is not None:  # the stop file reaches a queued job too
        return (None, None, "key frames from Part 3, Part 1 unavailable")

    work_p = Path(work)
    breaker = part1_breaker.enabled()
    if breaker:
        allowed, until = part1_breaker.allow(state)
        if not allowed:
            _log_open(until, work_p)
            return (None, None, part1_breaker.pause_note(until))

    lk = lock or modules.load()
    source = lk.path("1")
    clone = _run_dir(source, state)
    work_p.mkdir(parents=True, exist_ok=True)
    try:
        video_p = _safe_input(Path(video), work_p)
    except (RuntimeError, OSError) as exc:
        applog.log(f"Part 1 not started: {applog.cause(exc)}", applog.job_id_of(work_p), work_p, logging.WARNING)
        return (None, None, "key frames from Part 3, Part 1 unavailable")

    sha12 = hashlib.sha256(video_p.read_bytes()).hexdigest()[:12]
    # In prod each run has its own name: `_clear_run` must not take the output of another take of the same clip.
    stem = f"p7-{sha12}-{uuid.uuid4().hex[:8]}" if prod_mode.is_prod() else f"p7-{sha12}"
    inbox_rel = f"inbox/{stem}.mp4"
    inbox_copy = clone / inbox_rel
    inbox_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(video_p, inbox_copy)

    venv_py = source / ".venv" / "bin" / "python"
    py_exe = str(venv_py) if venv_py.exists() else sys.executable
    log_path = work_p / "steps" / "part1.log"

    # Call -m keyframe_finder.from_video on the single clip, never make keyframes, because inbox/*.mp4 in a GIT_LFS_SKIP_SMUDGE=1 clone are LFS pointer files.
    step: runner.Step | None = None
    kept: Path | None = None
    budget = timeout_s if timeout_s is not None else config.TIMEOUTS["1"]
    term_after_s, grace_s = _stop_times(budget)
    argv = [py_exe, "-m", "keyframe_finder.from_video", inbox_rel]
    applog.log(f"Part 1 starts with a {budget:.0f} s budget", applog.job_id_of(work_p), work_p)
    try:
        with keys.part1_dotenv(clone, keys_dir=keys_dir) as has_env:
            if not has_env:
                return (None, None, "key frames from Part 3, Part 1 unavailable")
            step = runner.run(1, argv, cwd=clone, env_extra=_deadline_env(term_after_s), timeout_s=term_after_s,
                              kill_grace_s=grace_s, log_path=log_path, lock=lk, pass_fds=keys.part1_holder_fds())
            _log_retried_cuts(step, work_p)
            _log_clip_lines(step, work_p)
            _log_stop(step, work_p)
            if transient_failure(step):
                applog.log(f"Part 1 lost its network stream after {step['duration_s']:.1f} s, {_cut_cost(step)}: "
                           f"{_cut_line(step)}", applog.job_id_of(work_p), work_p, logging.WARNING)
    finally:
        inbox_copy.unlink(missing_ok=True)
        kept = _take_output(step, clone, stem, work_p)

    if breaker and step is not None and not _stopped_from_outside(step):
        outcome = "ok" if step["exit"] == 0 else "transient" if step.get("timed_out") or transient_failure(step) else "other"
        opened = part1_breaker.record(outcome, state)
        if opened:
            _log_open(opened, work_p)

    if kept is not None:
        return (step, kept, None)

    if step is not None and transient_failure(step):
        return (step, None, CUT_NOTE)
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
