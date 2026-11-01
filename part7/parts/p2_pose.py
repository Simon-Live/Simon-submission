"""Part 2 adapter: video to `pose3d.json` and downstream doctor (TICKET-010)."""

from __future__ import annotations

import contextlib
import os
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
TRACK_WORKER_ENV = "SIMON7_P2_TRACK_WORKER"  # "1": Part 2's warm track worker for the people step (staging/env.sh sets 1; "0" turns it off)
TRACK_IDLE_ENV = "SIMON7_P2_TRACK_WORKER_IDLE_S"  # seconds idle before the tracker worker frees its GPU memory; 0: never
TRACK_IDLE_DEFAULT = 0.0  # resident SAM 3.1 is about 5.1 GiB (TICKET-128 measurement), so it stays loaded unless asked
# A warm track call reserves about 26 GiB of GPU memory at its peak while it runs (TICKET-125: empty_cache freed 26.8 GB;
# free memory read 456 MiB during a call) and the loaded worker keeps about 5.1 GiB resident. It is admitted on the
# same threshold as the per-call local-sam31 run.
TRACK_MIN_FREE_MIB = 12288
# A cold local-sam31 run peaks at the same 26 GiB. The cold repeat of a warm call (TICKET-129) is admitted on that
# figure, after the warm worker's resident memory was given back, so it cannot be killed for lack of memory.
COLD_SAM31_MIN_FREE_MIB = 26624
COLD_MIN_FREE_ENV = "SIMON7_P2_COLD_SAM31_MIN_FREE_MIB"  # operator override of that figure (a card where it can never be met)


COLD_WAIT_ENV = "SIMON7_P2_COLD_SAM31_WAIT_S"  # longest the cold repeat waits for that memory before local-open instead
COLD_WAIT_DEFAULT_S = 60.0


def cold_min_free_mib() -> int:
    """Free GPU memory (MiB) the cold repeat of a warm call waits for: `COLD_MIN_FREE_ENV`, else the 26 GiB peak."""
    raw = os.environ.get(COLD_MIN_FREE_ENV, "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else COLD_SAM31_MIN_FREE_MIB


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
    """True when SIMON7_P2_TRACK_WORKER asks for Part 2's warm track worker (1, on, yes or true; unset is off)."""
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
    """Start Part 2's warm track worker pool under `<state>/p2-tracker` when SIMON7_P2_TRACK_WORKER is on (TICKET-128).

    The process is `part2 serve-worker --mode track` in Part 2's GPU venv, started like the 3D worker (same launcher,
    log, pidfile, reaping and drain). At the default idle release of 0 (`SIMON7_P2_TRACK_WORKER_IDLE_S`) it loads at
    boot and stays; above 0 it loads on the first people step and frees its GPU memory after that many seconds without
    a call. It restarts at the next lease when the Part 2 pin changed since it started. False (nothing started) when
    off, not on the GPU backend, the GPU venv is missing or the pin does not offer `track --worker` for local-sam31.
    `p2_worker.stop_track_pool()` stops it.
    """
    gpu_py = config.part2_gpu_venv_path() / "bin" / "python"
    if not track_worker_enabled() or backend != "gpu" or not gpu_py.exists():
        return False
    lk = lock or modules.load()
    clone = lk.path("2")
    if not _offers_warm_track(lk, clone):
        return False
    idle_s = track_idle_s()
    argv, env = _command(backend, ["serve-worker", "--mode", "track"], clone)
    pool = p2_worker.Pool(
        Path(state), 1, lambda sock: [*argv, "--socket", str(sock)], cwd=clone, env=env,
        label="p2_tracker", folder="p2-tracker", on_demand=idle_s > 0, idle_release_s=idle_s, marker=p2_worker.TRACK_MARKER,
        on_started=lambda: applog.log(f"p2_tracker resident: warm SAM 3.1 loaded; {_gpu_used_note()}"),
        version=lambda: modules.head_sha(clone),
    )
    p2_worker.start_track_pool(pool)
    return True


def _offers_warm_track(lk: modules.Modules, clone: Path) -> bool:
    """True when the pinned Part 2 has the warm track worker (a8f91ac): `serve-worker --mode` and a `track` that names
    local-sam31 and takes `--worker`. Older pins have `track --worker` but no `--mode`: no tracker pool then."""
    base = _command("cpu", [], clone)[0]
    if not probe.has_flag(2, [*base, "serve-worker"], clone, "--mode", lk):
        return False
    text = probe.help_text(2, [*base, "track"], clone, lk)
    return "--tracker" in text and LOCAL_SAM31 in text and "--worker" in text


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
    """A `track --tracker local-sam31` call on Part 2's warm track worker (TICKET-128), leased AFTER the GPU admission.

    Locking: the admission (`_admission`, concurrent) waits for free memory and a turn, then RELEASES the host GPU
    lock before the call body, so Part 2's worker takes the same lock itself for each call (CONTRACT.md "GPU lock")
    and cannot deadlock with this process; the 3D `--worker` path works the same way. A loaded worker holds about
    5 GiB but a call grows to about 26 GiB, so admission checks free memory with `TRACK_MIN_FREE_MIB` as a per-call
    run does (TICKET-125). The first call after a release loads the model in the lease.
    Part 2's contract for `track --worker`: exit 1 means run the cold `part2 track` (a model failure, an out-of-memory
    call, a worker that crashed or removed its socket); exit 4 (no person) and exit 2 are answers and pass through.
    A busy worker is waited for up to the call timeout (one call at a time; going cold beside a loaded worker could
    run out of GPU memory). No worker (down, starting, restarting) runs per-call. A timed-out call or exit 1 logs
    `ANOMALY p2_tracker_unhealthy` and repeats per-call in a fresh out folder. A timed-out worker is still running
    the call and holds Part 2's GPU lock (its spec: a disconnecting client does not stop the call), so the lease
    stops it (its process group) and the repeat waits for the lock to be free. Every per-call repeat of
    local-sam31 first stops the warm worker (`_cold_attempt`): it restarts at the next lease.
    """
    with _admission(backend, acquire_lock, work_p, False, gpu_lock_kwargs, min_free_mib=TRACK_MIN_FREE_MIB):
        with p2_worker.track_lease(config.TIMEOUTS["2"]) as sock:
            step = _launch(sub, sock, work_p, log_name, lk, clone, backend) if sock is not None else None
            if step is not None and step.get("timed_out") and sock is not None:
                p2_worker.track_mark_restart(sock)
    if step is None:
        return _cold_attempt(sub, backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs)
    if step["exit"] == 1 or step.get("timed_out"):
        applog.anomaly("p2_tracker_unhealthy", "the warm track call failed or timed out; the call repeats per-call",
                       job_dir=work_p, exit=step["exit"])
        # The worker may still be writing to the first out dir (a timed-out call keeps running), so the repeat gets its own.
        sub, fresh = _fresh_out(sub)
        retry = _cold_attempt(sub, backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs)
        retry["out_dir"] = str(fresh)
        return retry
    return step


def cold_wait_s() -> float:
    """Seconds the cold repeat waits for `cold_min_free_mib` after the tracker stopped (`COLD_WAIT_ENV`, default 60)."""
    return applog.env_float(COLD_WAIT_ENV, COLD_WAIT_DEFAULT_S)


def _skipped_step(lk: modules.Modules, clone: Path, log_name: str, work_p: Path) -> runner.Step:
    """A failed step for a run that was never started (cold local-sam31 skipped); same keys as `runner.run`."""
    return runner.Step(part=2, commit=lk.sha12("2"), argv=[], cwd=str(clone), exit=1, timed_out=False, duration_s=0.0,
                       log=str(work_p / "steps" / log_name), skipped=True)


def _cold_attempt(
    sub: list[str], backend: str, work_p: Path, log_name: str, lk: modules.Modules, clone: Path,
    acquire_lock: bool, gpu_lock_kwargs: dict[str, Any] | None,
) -> runner.Step:
    """The per-call `part2 track` that follows a warm one: the warm worker is stopped first when it holds a model,
    then the call is admitted on `COLD_SAM31_MIN_FREE_MIB` (a cold run peaks near 26 GiB; TICKET-129)."""
    if p2_worker.track_holds_model() and not p2_worker.stop_track_worker(config.TIMEOUTS["2"]):
        applog.anomaly("p2_tracker_unhealthy", "the warm tracker could not be stopped before the per-call run",
                       job_dir=work_p)
    need = cold_min_free_mib()
    try:
        return _attempt(sub, backend, work_p, log_name, lk, clone, acquire_lock,
                        {**(gpu_lock_kwargs or {}), "timeout_s": cold_wait_s()}, min_free_mib=need)
    except TimeoutError:
        # Memory that does not free in time will not free: skip cold local-sam31; `track` goes on to local-open.
        applog.anomaly("p2_cold_sam31_skipped", job_dir=work_p, free_mib=gpu_lock.free_gpu_memory_mib(), need_mib=need)
        return _skipped_step(lk, clone, log_name, work_p)


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


def _worker_lost(log: Path) -> bool:
    try:
        return "the worker closed the connection" in log.read_text(encoding="utf-8", errors="replace")
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
    acquire_lock: bool, gpu_lock_kwargs: dict[str, Any] | None, min_free_mib: int | None = None,
) -> runner.Step:
    with _admission(backend, acquire_lock, work_p, False, gpu_lock_kwargs, min_free_mib=min_free_mib):
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
        retry_sub, retry_dir = sub, out_dir
        if warm_retry:  # the first folders may still be written by a worker that timed out: the free tracker gets its own
            retry_sub, retry_dir = _fresh_out(sub)
        step = _execute([*retry_sub, *retry], backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs)
        step["first_try"] = named  # the job keeps both attempts, each with its own log
        if warm_retry:
            step["out_dir"] = str(retry_dir)
        return (step, retry_dir / "tracks.json")
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
