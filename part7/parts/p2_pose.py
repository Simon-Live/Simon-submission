"""Part 2 adapter: video to `pose3d.json` and downstream doctor (TICKET-010)."""

from __future__ import annotations

import os
import contextlib
from pathlib import Path
from typing import Any, Callable

from part7 import config, gpu_lock, keys, p2_worker, modules, runner
from part7.parts import p1_keyframes, probe

API_TRACKER = "api-sam31"
LOCAL_TRACKER = "local-open"  # the free retry after a failed api-sam31 run
RETRY_LOG = "part2_track_retry.log"
FPS = 10  # journey.md "Commands": Part 2 samples the take at 10 fps


def _command(backend: str, sub: list[str], clone: Path) -> tuple[list[str], dict[str, str] | None]:
    """The Part 2 argv for `sub` (a subcommand and its flags) and the env it needs."""
    gpu_py = config.part2_gpu_venv_path() / "bin" / "python"
    if backend == "gpu" and gpu_py.exists():
        return ([str(gpu_py), "-m", "part2", *sub], {"PYTHONPATH": str(clone)})
    return (["uv", "run", "part2", *sub], None)


def has_worker(lk: modules.Modules, clone: Path) -> bool:
    """True when the pinned `part2 run` offers `--worker` (a warm model process, `part2 serve-worker`)."""
    base = _command("cpu", [], clone)[0]
    return probe.has_flag(2, [*base, "run"], clone, "--worker", lk)


def start_workers(
    slots: int, state: Path | str, lock: modules.Modules | None = None, backend: str = "gpu"
) -> bool:
    """Start one warm Part 2 worker per job slot under `<state>/p2-workers` when the pin has `run --worker`.

    Returns False (and starts nothing) when it does not. Stopped with `p2_worker.stop_pool()`.
    """
    # Off by default (2026-10-30): on staging the warm workers stalled the follow-side tracking requests;
    # set SIMON7_P2_WARM_WORKERS=1 to try them again once they are proven on real jobs.
    if os.environ.get("SIMON7_P2_WARM_WORKERS", "0") != "1":
        return False
    lk = lock or modules.load()
    clone = lk.path("2")
    if backend != "gpu" or slots < 1 or not has_worker(lk, clone):
        return False
    argv, env = _command(backend, ["serve-worker"], clone)
    pool = p2_worker.Pool(
        Path(state), slots, lambda sock: [*argv, "--socket", str(sock)], cwd=clone, env=env
    )
    p2_worker.start_pool(pool)
    return True


def _execute(
    sub: list[str], backend: str, work_p: Path, log_name: str, lk: modules.Modules, clone: Path,
    acquire_lock: bool, gpu_lock_kwargs: dict[str, Any] | None,
) -> runner.Step:
    # a warm worker already holds the model in GPU memory, so its job needs no free memory, only an admission turn
    lend = p2_worker.lease() if (backend == "gpu" and sub[0] == "run" and has_worker(lk, clone)) else contextlib.nullcontext()
    with lend as sock:
        if sock is not None:
            sub = [*sub, "--worker", str(sock)]
        argv, env_extra = _command(backend, sub, clone)
        kwargs = {"hold_flock": False, "concurrent": True, "job_dir": work_p, **({"min_free_mib": 0} if sock else {}),
                  **(gpu_lock_kwargs or {})}
        ctx = gpu_lock.acquire(**kwargs) if (backend == "gpu" and acquire_lock) else contextlib.nullcontext()
        with ctx:
            return runner.run(
                2, argv, cwd=clone, env_extra=env_extra, timeout_s=config.TIMEOUTS["2"],
                log_path=work_p / "steps" / log_name, lock=lk,
            )


def run(
    video: Path | str,
    work: Path | str,
    backend: str = "gpu",
    lock: modules.Modules | None = None,
    acquire_lock: bool = True,
    state: Path | str | None = None,
    gpu_lock_kwargs: dict[str, Any] | None = None,
    multi: bool = False,
    tracks: Path | str | None = None,
    ids: list[str] | None = None,
) -> tuple[runner.Step, Path]:
    """Run Part 2 3D pose estimation on `video`: one person by default.

    `multi` runs `--mode multi` (everyone, also writes `tracks.json`); `tracks` and `ids` add
    `--tracks <file> --ids <id,id>` (people.md "Part 2 follow-up": no re-tracking, 3D for those ids only).
    """
    lk = lock or modules.load()

    clone = lk.path("2")
    work_p = Path(work)
    out_dir = work_p / "part2"
    out_dir.mkdir(parents=True, exist_ok=True)
    sub = [
        "run", "--mode", "multi" if (multi or tracks or ids) else "single", "--input", str(Path(video).resolve()),
        "--out", str(out_dir.resolve()), "--fps", str(FPS), "--backend", backend,
    ]
    if tracks:
        sub += ["--tracks", str(Path(tracks).resolve())]
    if ids:
        sub += ["--ids", ",".join(str(i) for i in ids)]
    step = _execute(sub, backend, work_p, "part2.log", lk, clone, acquire_lock, gpu_lock_kwargs)
    return (step, out_dir / "pose3d.json")


def track(
    video: Path | str,
    work: Path | str,
    backend: str = "gpu",
    lock: modules.Modules | None = None,
    acquire_lock: bool = True,
    state: Path | str | None = None,
    gpu_lock_kwargs: dict[str, Any] | None = None,
    tracker: str | None = "auto",
) -> tuple[runner.Step, Path]:
    """Run `part2 track` (frames and `tracks.json`, no 3D) when the pin has it (see `capabilities`).

    `tracker="auto"` asks for `--tracker api-sam31` while the Meta budget allows (see `api_tracker_allowed`) and
    runs Part 2's default order if that run fails; a name forces it, None leaves Part 2's default order.
    A named attempt writes its own log (`_tracker_log`); when the fallback runs, its step carries the failed
    attempt under `first_try`.
    The api-sam31 run skips Part 7's GPU admission; the default-order run (it may load local SAM) keeps it.
    """
    lk = lock or modules.load()
    clone = lk.path("2")
    work_p = Path(work)
    out_dir = work_p / "part2_track"
    out_dir.mkdir(parents=True, exist_ok=True)
    sub = ["track", "--input", str(Path(video).resolve()), "--out", str(out_dir.resolve()), "--fps", str(FPS)]
    if tracker == "auto":
        tracker = API_TRACKER if api_tracker_allowed(lk, clone, state) else None
    if tracker:
        # TICKET-067: at the pin a named tracker never falls back (`trackers.select`) and api-sam31 loads no torch and
        # no local model: it uploads a video to the Meta API, so it needs no GPU admission (parts-harness.md "GPU").
        admit = acquire_lock and tracker != API_TRACKER
        named = _execute(
            [*sub, "--tracker", tracker], backend, work_p, _tracker_log(tracker), lk, clone, admit, gpu_lock_kwargs
        )
        if named["exit"] == 0 and (out_dir / "tracks.json").is_file():
            return (named, out_dir / "tracks.json")
        # moalborati/simon#61: after a failed api-sam31 run (a refused key) retry with the free local tracker by name; Part 2's
        # default order would try api-sam31 again. Its own log keeps the first error readable. Other trackers keep the default order.
        retry = ["--tracker", LOCAL_TRACKER] if tracker == API_TRACKER else []
        log_name = RETRY_LOG if retry else "part2_track.log"
        step = _execute([*sub, *retry], backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs)
        step["first_try"] = named  # the job keeps both attempts, each with its own log
        return (step, out_dir / "tracks.json")
    step = _execute(sub, backend, work_p, "part2_track.log", lk, clone, acquire_lock, gpu_lock_kwargs)
    return (step, out_dir / "tracks.json")


def _tracker_log(tracker: str) -> str:
    """The step log of a named tracker attempt: `part2_track.api.log` for api-sam31, else `part2_track.<name>.log`."""
    return "part2_track.api.log" if tracker == API_TRACKER else f"part2_track.{tracker}.log"


def api_tracker_allowed(lk: modules.Modules, clone: Path, state: Path | str | None = None) -> bool:
    """True when the pin's `track` offers `--tracker` with `api-sam31`, the key file exists and Part 1's spend cap holds."""
    if not keys.has_key("MODEL_API_KEY"):
        return False
    if p1_keyframes.total_spend_usd(state) >= config.PART1_RUN_SPEND_CAP_USD:
        return False
    text = probe.help_text(2, [*_command("cpu", [], clone)[0], "track"], clone, lk)
    return "--tracker" in text and API_TRACKER in text


def capabilities(lock: modules.Modules | None = None, state: Path | str | None = None) -> dict[str, bool]:
    """What the pinned Part 2 offers for people choice: `track` and `ids` (run `--tracks --ids`)."""
    lk = lock or modules.load()
    clone = lk.path("2")
    base = [*_command("cpu", [], clone)[0]]
    track_ok = bool(probe.help_text(2, [*base, "track"], clone, lk))
    return {
        "track": track_ok,
        "ids": probe.has_flag(2, [*base, "run"], clone, "--ids", lk),
    }


def doctor(
    pose3d_path: Path | str,
    work: Path | str,
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
) -> runner.Step:
    """Run Part 2's `doctor <pose3d.json> --for part3` check."""
    lk = lock or modules.load()
    clone = lk.path("2")
    work_p = Path(work)
    return runner.run(
        2,
        [
            "uv",
            "run",
            "python",
            "-m",
            "part2",
            "doctor",
            str(Path(pose3d_path).resolve()),
            "--for",
            "part3",
        ],
        cwd=clone,
        timeout_s=config.TIMEOUTS["doctor"],
        log_path=work_p / "steps" / "part2_doctor.log",
        lock=lk,
    )
