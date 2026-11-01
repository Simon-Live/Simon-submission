"""Part 2 adapter: video to `pose3d.json` and downstream doctor (TICKET-010)."""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path
from typing import Any

from part7 import applog, config, gpu_lock, keys, p2_worker, modules, runner
from part7.parts import p1_keyframes, probe

API_TRACKER = "api-sam31"
LOCAL_TRACKER = "local-open"  # the free retry after a failed api-sam31 run
RETRY_LOG = "part2_track_retry.log"
MESH_FILES = ("mesh3d.json", "mesh3d.bin")
FPS_ENV = "SIMON7_P2_FPS"  # the rate Part 2 samples a take at, for the people step and the 3D step alike

TRACK_FPS_ENV = "SIMON7_P2_TRACK_FPS"  # the people step may track at a lower rate; the 3D run gets boxes at FPS (#62)

def _env_fps(name: str, default: int) -> int:
    """A positive integer rate from env `name`; a bad value is logged and `default` used (import never fails)."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
        if value > 0:
            return value
    except ValueError:
        pass
    applog.log(f"{name}={raw!r} is not a positive whole number; using {default}")
    return default


FPS = _env_fps(FPS_ENV, 10)  # journey.md "Commands": 10 fps unless the route sets it
TRACK_FPS = _env_fps(TRACK_FPS_ENV, FPS)
TRACKER_ENV = "SIMON7_P2_TRACKER"  # a Part 2 tracker name (local-sam31, local-open, bytetrack, api-sam31) in place of "auto"
# Kept from the client team's 91cbe07 (serverless route). Part 7 main has no `remote()` yet, so nothing reads these
# three until that route is ported; they are here so that merge loses nothing of theirs.
RETRIED = ("api-sam31",)  # a failure is retried once with LOCAL_TRACKER by name
REMOTE_RETRIED = ("api-sam31", "local-sam31")  # on the serverless route a failed local-sam31 also goes to LOCAL_TRACKER
REMOTE_ENV = "SIMON7_PART2_REMOTE"  # "modal": run Part 2 on Modal instead of the local GPU (deploy/serverless/)
MODAL_REQ = "modal>=1.0,<2"
LOCAL_SAM31 = "local-sam31"  # the tracker the warm tracker worker serves (TICKET-117)
TRACK_WORKER_ENV = "SIMON7_P2_TRACK_WORKER"  # "1": keep SAM 3.1 loaded in its own process for the people step (off by default)
TRACK_IDLE_ENV = "SIMON7_P2_TRACK_WORKER_IDLE_S"  # seconds idle before the tracker worker frees its GPU memory; 0: never
TRACK_IDLE_DEFAULT = 0.0  # resident SAM 3.1 is about 3 GB (TICKET-117 measurement), so it stays loaded unless asked
# A warm track call grows to about 22 GB of reserved GPU memory while it runs (TICKET-125: empty_cache freed 26.8 GB;
# free memory read 456 MiB during a call), so it is admitted on the same threshold as the per-call local-sam31 run.
TRACK_MIN_FREE_MIB = 12288
TRACK_LOST = "the tracker worker closed the connection"  # printed by trackwarm/track_worker.py `call`
TRACK_SCRIPT = Path(__file__).resolve().parent.parent / "trackwarm" / "track_worker.py"


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


def has_mesh(lk: modules.Modules, clone: Path) -> bool:
    """True when the pinned `part2 run` offers `--mesh` (SAM 3D Body mesh files, TICKET-143); cached per clone."""
    base = _command("cpu", [], clone)[0]
    return probe.has_flag(2, [*base, "run"], clone, "--mesh", lk)


def drop_mesh(out_dir: Path) -> bool:
    """Remove `mesh3d.json` and `mesh3d.bin` from Part 2's folder (a malformed pair is treated as no mesh)."""
    gone = False
    for name in MESH_FILES:
        with contextlib.suppress(OSError):
            (out_dir / name).unlink()
            gone = True
    return gone


WARM_WORKERS_DEFAULT = "1"  # env SIMON7_P2_WARM_WORKERS: ONE warm `serve-worker` for `part2 run`; "0" turns it off (TICKET-099)


def warm_worker_enabled() -> bool:
    """True when SIMON7_P2_WARM_WORKERS asks for the warm worker (any value but 0, off, no, false or empty)."""
    value = os.environ.get("SIMON7_P2_WARM_WORKERS", WARM_WORKERS_DEFAULT).strip().lower()
    return value not in ("", "0", "off", "no", "false")


def track_worker_enabled() -> bool:
    """True when SIMON7_P2_TRACK_WORKER asks for the warm SAM 3.1 tracker (1, on, yes or true; off by default)."""
    return os.environ.get(TRACK_WORKER_ENV, "").strip().lower() in ("1", "on", "yes", "true")


def track_idle_s() -> float:
    """Seconds without a tracking call before the tracker worker frees its GPU memory; 0 keeps it loaded."""
    try:
        return max(0.0, float(os.environ.get(TRACK_IDLE_ENV, "").strip() or TRACK_IDLE_DEFAULT))
    except ValueError:
        return TRACK_IDLE_DEFAULT


def _gpu_used_note() -> str:
    """`gpu used X of Y MiB` from nvidia-smi for the log line after a worker loads; empty when unreadable."""
    import subprocess

    exe = gpu_lock.nvidia_smi_path()
    if not exe:
        return ""
    try:
        out = subprocess.run([exe, "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5, check=False).stdout.split(",")
        return f"gpu used {int(out[0])} of {int(out[1])} MiB"
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return ""


def start_track_worker(state: Path | str, lock: modules.Modules | None = None, backend: str = "gpu") -> bool:
    """Start the warm SAM 3.1 tracker pool under `<state>/p2-tracker` when SIMON7_P2_TRACK_WORKER is on (TICKET-117).

    The process (`part7/trackwarm/track_worker.py`) runs in Part 2's GPU venv. At the default idle release of 0
    (`SIMON7_P2_TRACK_WORKER_IDLE_S`) it loads at boot and stays; above 0 it loads on the first people step and frees
    its GPU memory after that many seconds without a call. False (nothing started) when off, not on the GPU
    backend, the GPU venv is missing or the pin's `track` does not offer local-sam31. `p2_worker.stop_track_pool()` stops it.
    """
    gpu_py = config.part2_gpu_venv_path() / "bin" / "python"
    if not track_worker_enabled() or backend != "gpu" or not gpu_py.exists():
        return False
    lk = lock or modules.load()
    clone = lk.path("2")
    if not _offers_local_sam31(lk, clone):
        return False
    idle_s = track_idle_s()
    pool = p2_worker.Pool(
        Path(state), 1, lambda sock: [str(gpu_py), str(TRACK_SCRIPT), "serve", "--socket", str(sock)],
        cwd=clone, env={"PYTHONPATH": str(clone)}, label="p2_tracker", folder="p2-tracker", marker=b"track_worker.py",
        on_demand=idle_s > 0, idle_release_s=idle_s,
        on_started=lambda: applog.log(f"p2_tracker resident: warm SAM 3.1 loaded; {_gpu_used_note()}"),
    )
    p2_worker.start_track_pool(pool)
    return True


def _offers_local_sam31(lk: modules.Modules, clone: Path) -> bool:
    text = probe.help_text(2, [*_command("cpu", [], clone)[0], "track"], clone, lk)
    return "--tracker" in text and LOCAL_SAM31 in text


def start_workers(
    state: Path | str, lock: modules.Modules | None = None, backend: str = "gpu"
) -> bool:
    """Start the warm workers: the 3D one (`_start_run_worker`) and, when asked, the SAM 3.1 tracker."""
    run_started = _start_run_worker(state, lock, backend)
    return start_track_worker(state, lock, backend) or run_started


def _start_run_worker(
    state: Path | str, lock: modules.Modules | None = None, backend: str = "gpu"
) -> bool:
    """Start ONE warm Part 2 worker under `<state>/p2-workers` when enabled and the pin has `run --worker`.

    Only `part2 run` uses it (`_execute`); `track` uses the tracker pool. Returns False (and starts nothing) when it is
    off or the pin lacks the flag. Stopped with `p2_worker.stop_pool()`.
    """
    if not warm_worker_enabled():
        return False
    lk = lock or modules.load()
    clone = lk.path("2")
    if backend != "gpu" or not has_worker(lk, clone):
        return False
    argv, env = _command(backend, ["serve-worker"], clone)
    pool = p2_worker.Pool(Path(state), 1, lambda sock: [*argv, "--socket", str(sock)], cwd=clone, env=env)
    p2_worker.start_pool(pool)
    return True


def _execute(
    sub: list[str], backend: str, work_p: Path, log_name: str, lk: modules.Modules, clone: Path,
    acquire_lock: bool, gpu_lock_kwargs: dict[str, Any] | None,
) -> runner.Step:
    # TICKET-101: only `run` (the 3D step) may use the warm worker, and it is leased AFTER the GPU admission, so a
    # long flock wait never parks the worker as busy. An idle worker already holds the model in GPU memory, so its
    # admission needs only a turn (min_free_mib=0); otherwise the memory check applies. A worker that is busy after
    # admission is waited for a few seconds, then skipped: the run goes in-process as before.
    if backend == "gpu" and sub[0] == "track" and _tracker_arg(sub) == LOCAL_SAM31 and p2_worker.track_state() != "off":
        return _execute_warm_track(sub, backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs)
    if not (backend == "gpu" and sub[0] == "run" and has_worker(lk, clone)):
        return _attempt(sub, backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs)
    with _admission(backend, acquire_lock, work_p, p2_worker.state() == "idle", gpu_lock_kwargs):
        with p2_worker.lease() as sock:
            step = _launch(sub, sock, work_p, log_name, lk, clone, backend)
    if sock is not None and step["exit"] != 0 and _worker_lost(work_p / "steps" / log_name):
        applog.anomaly("p2_worker_unhealthy", "the worker dropped the request; the run repeats in-process",
                       job_dir=work_p, exit=step["exit"])
        return _attempt(sub, backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs)
    return step


def _tracker_arg(sub: list[str]) -> str | None:
    return sub[sub.index("--tracker") + 1] if "--tracker" in sub and sub.index("--tracker") + 1 < len(sub) else None


def _execute_warm_track(
    sub: list[str], backend: str, work_p: Path, log_name: str, lk: modules.Modules, clone: Path,
    acquire_lock: bool, gpu_lock_kwargs: dict[str, Any] | None,
) -> runner.Step:
    """A `track --tracker local-sam31` call on the warm tracker (TICKET-117), leased AFTER the GPU admission.

    A loaded worker holds about 5.5 GB but a call grows to about 22 GB, so admission checks free memory with
    `TRACK_MIN_FREE_MIB` exactly as a per-call run does (TICKET-125). The first call after a release loads the model in the lease
    (the cost a per-call run pays anyway). No worker (down, busy past the lease wait, failed to start) or a worker
    that drops the request: the call runs per-call as before, with `ANOMALY p2_tracker_unhealthy` for a drop.
    """
    with _admission(backend, acquire_lock, work_p, False, gpu_lock_kwargs, min_free_mib=TRACK_MIN_FREE_MIB):
        with p2_worker.track_lease() as sock:
            step = _launch_warm_track(sub, sock, work_p, log_name, lk, clone) if sock is not None else None
    if step is None:
        return _attempt(sub, backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs)
    if step["exit"] != 0 and (step.get("timed_out") or _worker_lost(work_p / "steps" / log_name, TRACK_LOST)):
        applog.anomaly("p2_tracker_unhealthy", "the tracker worker dropped or timed out the request; the call repeats per-call",
                       job_dir=work_p, exit=step["exit"])
        # The worker may still be writing to the first out dir (a timed-out call keeps running), so the repeat gets its own.
        sub, fresh = _fresh_out(sub)
        retry = _attempt(sub, backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs)
        retry["out_dir"] = str(fresh)
        return retry
    return step


def _fresh_out(sub: list[str]) -> tuple[list[str], Path]:
    """`sub` with `--out` pointing at a new sibling folder (`<out>_retry`, `_retry2`, ...), which is created."""
    i = sub.index("--out") + 1
    base = Path(sub[i])
    fresh, n = base.with_name(base.name + "_retry"), 1
    while fresh.exists():
        n += 1
        fresh = base.with_name(f"{base.name}_retry{n}")
    fresh.mkdir(parents=True)
    return [*sub[:i], str(fresh), *sub[i + 1:]], fresh


def _launch_warm_track(sub: list[str], sock: Path, work_p: Path, log_name: str, lk: modules.Modules,
                       clone: Path) -> runner.Step:
    argv = [sys.executable, str(TRACK_SCRIPT), "call", "--socket", str(sock), "--", *sub]
    return runner.run(2, argv, cwd=clone, timeout_s=config.TIMEOUTS["2"], log_path=work_p / "steps" / log_name, lock=lk)


def _worker_lost(log: Path, text: str = "the worker closed the connection") -> bool:
    try:
        return text in log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _admission(backend: str, acquire_lock: bool, work_p: Path, warm: bool,
               gpu_lock_kwargs: dict[str, Any] | None, min_free_mib: int | None = None) -> Any:
    floor = 0 if warm else min_free_mib
    kwargs = {"hold_flock": False, "concurrent": True, "job_dir": work_p,
              **({"min_free_mib": floor} if floor is not None else {}),
              **(gpu_lock_kwargs or {})}
    return gpu_lock.acquire(**kwargs) if (backend == "gpu" and acquire_lock) else contextlib.nullcontext()


def _launch(sub: list[str], sock: Path | None, work_p: Path, log_name: str, lk: modules.Modules, clone: Path,
            backend: str) -> runner.Step:
    if sock is not None:
        sub = [*sub, "--worker", str(sock)]
    argv, env_extra = _command(backend, sub, clone)
    return runner.run(
        2, argv, cwd=clone, env_extra=env_extra, timeout_s=config.TIMEOUTS["2"],
        log_path=work_p / "steps" / log_name, lock=lk,
    )


def _attempt(
    sub: list[str], backend: str, work_p: Path, log_name: str, lk: modules.Modules, clone: Path,
    acquire_lock: bool, gpu_lock_kwargs: dict[str, Any] | None,
) -> runner.Step:
    with _admission(backend, acquire_lock, work_p, False, gpu_lock_kwargs):
        return _launch(sub, None, work_p, log_name, lk, clone, backend)


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
    # TICKET-143: ask for the mesh only when the pin offers it. Part 7 never passes --refine (Part 2 exits 2 with both)
    # and leaves --mesh-vertices at Part 2's default (it refuses less than 100). The warm worker gets the flag too:
    # `_launch` forwards the whole `sub`, and a worker started before a deploy is restarted by it (staging.sh up).
    if has_mesh(lk, clone) and "--refine" not in sub:
        sub += ["--mesh"]
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
    sub = ["track", "--input", str(Path(video).resolve()), "--out", str(out_dir.resolve()), "--fps", str(TRACK_FPS)]
    if tracker == "auto" and os.environ.get(TRACKER_ENV, "").strip():
        tracker = os.environ[TRACKER_ENV].strip()  # e.g. local-open: the free tracker on the same GPU, no Meta API
    if tracker == "auto" and p2_worker.track_state() != "off":
        tracker = LOCAL_SAM31  # the warm tracker is running: use it rather than the paid API (TICKET-117)
    if tracker == "auto":
        tracker = API_TRACKER if api_tracker_allowed(lk, clone, state) else None
    if tracker:
        # TICKET-067: at the pin a named tracker never falls back (`trackers.select`) and api-sam31 loads no torch and
        # no local model: it uploads a video to the Meta API, so it needs no GPU admission (parts-harness.md "GPU").
        admit = acquire_lock and tracker != API_TRACKER
        named = _execute(
            [*sub, "--tracker", tracker], backend, work_p, _tracker_log(tracker), lk, clone, admit, gpu_lock_kwargs
        )
        named_dir = Path(named.get("out_dir") or out_dir)
        if named["exit"] == 0 and (named_dir / "tracks.json").is_file():
            return (named, named_dir / "tracks.json")
        # moalborati/simon#61: after a failed api-sam31 run (a refused key) retry with the free local tracker by name; Part 2's
        # default order would try api-sam31 again. Its own log keeps the first error readable. Other trackers keep the default order.
        # With the warm tracker on (TICKET-117) a failed local-sam31 also retries local-open by name.
        warm_retry = tracker == LOCAL_SAM31 and track_worker_enabled()
        retry = ["--tracker", LOCAL_TRACKER] if (tracker in RETRIED or warm_retry) else []
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
