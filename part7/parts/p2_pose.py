"""Part 2 adapter: video to `pose3d.json` and downstream doctor (TICKET-010)."""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from part7 import applog, byok_route, config, gpu_lock, job_gpu, keys, p2_worker, modules, quota, runner, warm_wait
from part7 import failcause  # whether a failed run looked and found nobody
from part7 import licence_gates  # licence-gates.md: which tracker prod may run
from part7 import prod_mode
from part7 import serverless_route  # serverless-compute.md: the operator's Modal workspace
from part7.parts import p1_keyframes, p2_host, probe

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
TRACK_FPS_SINGLE_ENV = "SIMON7_P2_TRACK_FPS_SINGLE"  # TICKET-198: people tracking rate of a "Just me" take
TRACK_FPS_GROUP_ENV = "SIMON7_P2_TRACK_FPS_GROUP"  # ... and of a group take (also a request without a mode)
TRACK_FPS_SINGLE, TRACK_FPS_GROUP = 3, 3  # group went to 3 as well (moalborati/simon#62, 2026-11-01)
FALLBACK_TRACK_FPS = 10  # a take that finds no participant at its low rate is tracked once more at this rate


def track_fps_for(mode: str | None) -> tuple[int, str]:
    """`(fps, mode)` of the people step: `SIMON7_P2_TRACK_FPS`, when set, overrides both; else the single or group rate.

    Any `mode` but "single" is group, the safe default for an old client. Read at call time, so an operator edit
    of the env takes effect with the next job; a bad value is logged and the default used.
    """
    kind = "single" if mode == "single" else "group"
    if os.environ.get(TRACK_FPS_ENV, "").strip():
        return (_env_fps(TRACK_FPS_ENV, FPS), kind)
    if kind == "single":
        return (_env_fps(TRACK_FPS_SINGLE_ENV, TRACK_FPS_SINGLE), kind)
    return (_env_fps(TRACK_FPS_GROUP_ENV, TRACK_FPS_GROUP), kind)


TRACKER_ENV = "SIMON7_P2_TRACKER"  # a Part 2 tracker name (local-sam31, local-open, bytetrack, api-sam31) in place of "auto"
# Kept from the client team's 91cbe07 (serverless route). Part 7 main has no `remote()` yet, so nothing reads these
# three until that route is ported; they are here so that merge loses nothing of theirs.
RETRIED = ("api-sam31",)  # a failure is retried once with LOCAL_TRACKER by name
REMOTE_RETRIED = ("api-sam31", "local-sam31")  # on the serverless route a failed local-sam31 also goes to LOCAL_TRACKER
REMOTE_ENV = "SIMON7_PART2_REMOTE"  # "modal": run Part 2 on Modal instead of the local GPU (deploy/serverless/)
# "on": a Part 2 call that fails on its route runs once more on the other one (local GPU <-> Modal), so either is the
# other's failsafe (team, 2026-11-02). Off by default; the first route is still chosen by REMOTE_ENV.
FALLBACK_ENV = "SIMON7_PART2_FALLBACK"
FALLBACK_LOG = ".fallback.log"   # the second route's log sits beside the first: part2.log -> part2.fallback.log
MODAL_REQ = "modal==1.6.3"  # docs/specs/byok-prod.md: the version whose spawn and Volume reads were checked
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
# TICKET-320: what stopping an idle loaded tracker gives back before its load was measured (`_tracker_gives_back`;
# WSL2's nvidia-smi reports [N/A] per process, so no pid is read). part7.log measured about 4038 MiB twice (2026-11-01 13:48:58Z, 2026-11-02 17:18:15Z); the figure is
# kept low on purpose: an estimate too low only makes the take wait for the warm tracker, one too high stops it in vain.
TRACK_RESIDENT_MIB = 4000


COLD_WAIT_ENV = "SIMON7_P2_COLD_SAM31_WAIT_S"  # longest the cold repeat waits for that memory before local-open instead
COLD_WAIT_DEFAULT_S = 60.0


TRACK_WAIT_ENV = "SIMON7_P2_TRACK_GPU_WAIT_S"  # longest an "auto" track waits for local-sam31's GPU admission (TICKET-191)
TRACK_WAIT_DEFAULT_S = 90.0
# local-open (a small detector, no SAM) needs far less than local-sam31's 12 GiB admission; there is no measurement
# of its peak, so this is a modest documented floor (TICKET-193). Its wait is bounded by TRACK_WAIT_ENV again.
LOCAL_OPEN_MIN_FREE_MIB = 4096


def track_gpu_wait_s() -> float:
    """Seconds an "auto" track waits for GPU admission before it goes to api-sam31 or local-open (default 90)."""
    return applog.env_float(TRACK_WAIT_ENV, TRACK_WAIT_DEFAULT_S)


def cold_min_free_mib() -> int:
    """Free GPU memory (MiB) the cold repeat of a warm call waits for: `COLD_MIN_FREE_ENV`, else the 26 GiB peak."""
    raw = os.environ.get(COLD_MIN_FREE_ENV, "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else COLD_SAM31_MIN_FREE_MIB


def _command(backend: str, sub: list[str], clone: Path) -> tuple[list[str], dict[str, str] | None]:
    """The Part 2 argv for `sub` (a subcommand and its flags) and the env it needs."""
    gpu_py = config.part2_gpu_venv_path() / "bin" / "python"
    if backend == "gpu" and not byok_route.host_models_refused() and gpu_py.exists():
        return ([str(gpu_py), "-m", "part2", *sub], {"PYTHONPATH": str(clone)})
    return ([*p2_host.base(), *sub], None)  # prod: the prepared CPU venv, never `uv run` in the release tree (D3)


def has_worker(lk: modules.Modules, clone: Path) -> bool:
    """True when the pinned `part2 run` offers `--worker` (a warm model process, `part2 serve-worker`)."""
    base = _command("cpu", [], clone)[0]
    return probe.has_flag(2, [*base, "run"], clone, "--worker", lk)


def has_mesh(lk: modules.Modules, clone: Path) -> bool:
    """True when the pinned `part2 run` offers `--mesh` (SAM 3D Body mesh files, TICKET-143); cached per clone."""
    base = _command("cpu", [], clone)[0]
    return probe.has_flag(2, [*base, "run"], clone, "--mesh", lk)


def offers_in_source(clone: Path, flag: str) -> bool:
    """True when the pinned Part 2's own CLI declares `flag` (`add_argument("--mesh"`), read from its source: the
    serverless route runs Part 2 on Modal, so nothing is run locally to ask it."""
    try:
        text = (Path(clone) / "part2" / "cli.py").read_text(encoding="utf-8")
    except OSError:
        return False
    return f'add_argument("{flag}"' in text or f"add_argument('{flag}'" in text


def has_mesh_stream(lk: modules.Modules, clone: Path) -> bool:
    """True when the pinned `part2 run` offers `--mesh-stream` (mesh3d.stream/ while SAM 3D Body runs, TICKET-284)."""
    base = _command("cpu", [], clone)[0]
    return probe.has_flag(2, [*base, "run"], clone, "--mesh-stream", lk)


def drop_mesh(out_dir: Path) -> bool:
    """Remove `mesh3d.json` and `mesh3d.bin` from Part 2's folder (a malformed pair is treated as no mesh)."""
    gone = False
    for name in MESH_FILES:
        with contextlib.suppress(OSError):
            (out_dir / name).unlink()
            gone = True
    return gone


WARM_WORKERS_ENV = "SIMON7_P2_WARM_WORKERS"  # explicit: any value but 0, off, no, false or empty starts ONE worker
WARM_OFF = ("", "0", "off", "no", "false")


def warm_workers_decision(state: Path | str | None = None) -> tuple[int, str]:
    """How many warm 3D workers (`part2 serve-worker`) this server starts, and why (GPU guard, TICKET-099).

    An explicit SIMON7_P2_WARM_WORKERS wins (`explicit`: 0 for 0, off, no, false or empty, else 1). Unset, only the
    staging server starts one (`staging`: SIMON7_STAGING=1 or the staging state folder); every other server, a lane
    or dev one, starts none (`dev default off`): each worker holds 5 to 11 GB of the shared GPU.
    """
    if byok_route.host_models_refused():  # nofallback D2: no model is resident on this machine, whatever the env says
        return 0, "byok" if byok_route.byok_only() else "serverless"
    raw = os.environ.get(WARM_WORKERS_ENV)
    if raw is not None:
        return (0 if raw.strip().lower() in WARM_OFF else 1), "explicit"
    if config.is_staging_server(state):
        return 1, "staging"
    return 0, "dev default off"


def warm_workers_note(state: Path | str | None = None) -> str:
    """The one startup line: `p2 warm workers: N (staging|dev default off|explicit)`."""
    count, why = warm_workers_decision(state)
    return f"p2 warm workers: {count} ({why})"


def warm_worker_enabled(state: Path | str | None = None) -> bool:
    """True when this server starts the warm worker (`warm_workers_decision`)."""
    return warm_workers_decision(state)[0] > 0


def track_worker_enabled() -> bool:
    """True when SIMON7_P2_TRACK_WORKER asks for Part 2's warm track worker (1, on, yes or true; unset is off).
    Never under BYOK-only (prod, nofallback D2) or in serverless mode."""
    if byok_route.host_models_refused():
        return False
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
    if not licence_gates.warm_tracker_allowed():  # LIC-H2: the warm worker serves local SAM 3.1, off in prod while unread
        applog.log("p2_tracker: not started; local SAM 3.1 is off in prod until its weights licence is read")
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
        measure_free=gpu_lock.free_gpu_memory_mib,  # TICKET-320: its resident size, for `_cold_fits`
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
    if not warm_worker_enabled(state):
        return False
    lk = lock or modules.load()
    clone = lk.path("2")
    if backend != "gpu" or not has_worker(lk, clone):
        return False
    argv, env = _command(backend, ["serve-worker"], clone)
    pool = p2_worker.Pool(Path(state), 1, lambda sock: [*argv, "--socket", str(sock)], cwd=clone, env=env)
    p2_worker.start_pool(pool)
    return True


def remote() -> str | None:
    """`modal` when SIMON7_PART2_REMOTE asks for the serverless route (deploy/serverless/README.md), else None."""
    return "modal" if os.environ.get(REMOTE_ENV, "").strip().lower() == "modal" else None


# TICKET-364 (AC-H12): a take's "Run on" choice, set for the job's thread by `run_on.bind`; it overrides REMOTE_ENV for
# the first route of every Part 2 call of that job. None (no choice) keeps the env route.
_JOB_ROUTE: contextvars.ContextVar[str | None] = contextvars.ContextVar("p2_job_route", default=None)


def job_route() -> str | None:
    """The current job's chosen first route (`modal` or `local`), or None when the job made no choice."""
    return _JOB_ROUTE.get()


@contextlib.contextmanager
def job_route_set(route: str | None) -> Iterator[None]:
    """Within the block, Part 2 calls on this thread try `route` first (None: the env route)."""
    token = _JOB_ROUTE.set(route)
    try:
        yield
    finally:
        _JOB_ROUTE.reset(token)


# TICKET-367 (AC-H16): the job owner's own Modal credentials, set by `run_on.bind` at execution time for that job's thread
# only. They reach one Part 2 subprocess through `runner.run(env_extra=...)`; os.environ is never touched. The second
# variable is a one-item list the job reads after its calls: whether Modal refused those credentials.
_JOB_MODAL_ENV: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar("p2_job_modal_env", default=None)
_JOB_MODAL_REFUSED: contextvars.ContextVar[list[bool] | None] = contextvars.ContextVar("p2_job_modal_refused", default=None)
# go-live BYOK N1: the gate each own-route process starts through (runner.run `gate`), which reads the token again
# under the owner's lock and registers the process before Remove can run.
_JOB_MODAL_GATE: contextvars.ContextVar[Any] = contextvars.ContextVar("p2_job_modal_gate", default=None)
CREDS_REFUSED_EXIT = byok_route.CREDS_REFUSED_EXIT  # deploy/serverless/p2_client.py: Modal refused the credentials


@contextlib.contextmanager
def job_modal_env_set(env: dict[str, str] | None, gate: Any = None) -> Iterator[list[bool]]:
    """Within the block, the Modal route of this thread runs with `env` (the user's tokens), each process started
    through `gate` (runner.Gate) when given; yields the refused flag."""
    refused: list[bool] = [False]
    token, token_r, token_g = _JOB_MODAL_ENV.set(env), _JOB_MODAL_REFUSED.set(refused), _JOB_MODAL_GATE.set(gate)
    try:
        yield refused
    finally:
        _JOB_MODAL_ENV.reset(token)
        _JOB_MODAL_REFUSED.reset(token_r)
        _JOB_MODAL_GATE.reset(token_g)


def job_modal_env() -> dict[str, str] | None:
    """The current job's own Modal env (`job_modal_env_set`), for another call on the owner's account (captions)."""
    return _JOB_MODAL_ENV.get()


def job_modal_gate() -> Any:
    """The current job's launch gate (`job_modal_env_set`), or None."""
    return _JOB_MODAL_GATE.get()


def first_route(route: str | None = None) -> str:
    """The route a Part 2 call tries first: `route`, else the job's choice, else SIMON7_PART2_REMOTE, else local. In
    serverless mode always Modal: never on the host (serverless-compute.md AC-SC1)."""
    if serverless_route.enabled():
        return "modal"
    return route or job_route() or ("modal" if remote() else "local")


def fallback() -> bool:
    """Whether a failed Part 2 call repeats on the other route (SIMON7_PART2_FALLBACK=on)."""
    return os.environ.get(FALLBACK_ENV, "").strip().lower() in ("on", "1", "true", "yes")


def _remote_command(sub: list[str], lk: modules.Modules) -> list[str]:
    """`part2 <sub>` run on Modal through deploy/serverless/p2_client.py, at the commit `modules/part-2` is at."""
    client = config.REPO_ROOT / "deploy" / "serverless" / "p2_client.py"
    sha = lk.sha("2")
    return ["uv", "run", "--no-project", "--with", MODAL_REQ, "python", str(client), "--sha", sha, "--", *sub]


MSG_TOKEN_REFUSED = "Modal refused the owner's token earlier in this job; it is not sent to Modal again"


def _execute(
    sub: list[str], backend: str, work_p: Path, log_name: str, lk: modules.Modules, clone: Path,
    acquire_lock: bool, gpu_lock_kwargs: dict[str, Any] | None, route: str | None = None,
) -> runner.Step:
    """Part 2 `sub` on the chosen route (`route`, else the job's "Run on" choice, else Modal with
    SIMON7_PART2_REMOTE=modal, else the local GPU); with SIMON7_PART2_FALLBACK=on a failure there runs the same call
    once on the other route, logged beside the first."""
    first = first_route(route)
    if (why := byok_route.refusal(first, _JOB_MODAL_ENV.get())) is not None:  # BYOK-C2: never here, never the server's Modal
        return byok_route.refused_step(lk.sha12("2"), clone, work_p / "steps" / log_name, why)
    own = first == "modal" and _JOB_MODAL_ENV.get() is not None  # TICKET-367: a failure on the user's own Modal runs here
    flag = _JOB_MODAL_REFUSED.get()
    if own and flag is not None and flag[0]:  # byok-ui D2: Modal refused this token already; it is not sent again
        step = byok_route.refused_step(lk.sha12("2"), clone, work_p / "steps" / log_name, MSG_TOKEN_REFUSED)
        step["exit"] = CREDS_REFUSED_EXIT
    else:
        step = _on_route(first, sub, backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs)
    if own and step["exit"] == CREDS_REFUSED_EXIT and flag is not None:
        flag[0] = True
    if step["exit"] == 0 or not byok_route.may_fall_back(own, step["exit"], fallback()):  # R1, BYOK-H1
        return step
    other = "local" if first == "modal" else "modal"
    applog.anomaly("p2_route_fallback", f"Part 2 failed on the {first} route; the same call runs on the {other} route",
                   job_dir=work_p, exit=step["exit"], route=first, to=other, sub=sub[0])
    again = _on_route(other, sub, backend, work_p, log_name.removesuffix(".log") + FALLBACK_LOG, lk, clone, acquire_lock,
                      gpu_lock_kwargs)
    again["route"] = other
    return again


def _on_route(
    route: str, sub: list[str], backend: str, work_p: Path, log_name: str, lk: modules.Modules, clone: Path,
    acquire_lock: bool, gpu_lock_kwargs: dict[str, Any] | None,
) -> runner.Step:
    if route == "modal" and serverless_route.enabled():
        return _on_operator_modal(sub, work_p, log_name, lk, clone)
    if route == "modal":  # serverless route: no local GPU, no warm worker, no GPU lock; the runner still logs and times it
        own = _JOB_MODAL_ENV.get() is not None  # BYOK-C1: the own route never unpickles a result (byok_route)
        low = quota.disk_refusal(work_p) if own else None  # security audit R7: the result is written here
        if low:
            applog.log(f"part2: own Modal run not started ({low})", level=logging.WARNING)
            return _skipped_step(lk, clone, log_name, work_p)
        return runner.run(
            2, byok_route.command(sub, lk.sha("2")) if own else _remote_command(sub, lk), cwd=clone, timeout_s=config.TIMEOUTS["2"],
            log_path=work_p / "steps" / log_name, lock=lk, env_extra=_JOB_MODAL_ENV.get(),  # TICKET-367: this subprocess only
            gate=_JOB_MODAL_GATE.get() if own else None,  # go-live BYOK N1: the token read again as the client starts
        )
    # TICKET-101: only `run` (the 3D step) may use the warm worker, and it is leased AFTER the GPU admission, so a
    # long flock wait never parks the worker as busy. An idle worker already holds the model in GPU memory, so its
    # admission needs only a turn (min_free_mib=0); otherwise the memory check applies. A worker that is busy after
    # admission is waited for a few seconds, then skipped: the run goes in-process as before.
    if backend == "gpu" and sub[0] == "track" and _tracker_arg(sub) == LOCAL_SAM31 and p2_worker.track_state() != "off":
        return _execute_warm_track(sub, backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs)
    if not (backend == "gpu" and sub[0] == "run" and has_worker(lk, clone)):
        return _attempt(sub, backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs)
    warm_admit, warm = p2_worker.state() == "idle", warm_wait.WarmWait(work_p)  # the wait's bound runs from here
    with _admission(backend, acquire_lock, work_p, warm_admit, {"wait_since": warm.since, **(gpu_lock_kwargs or {})}):
        with p2_worker.lease() as sock:
            missed = sock is None and warm_admit and p2_worker.state() in ("busy", "starting")
            if not missed:
                _report_worker(work_p, sock)
                step = _launch(sub, sock, work_p, log_name, lk, clone, backend)
    if missed:  # TICKET-320: admitted for the warm worker alone (no memory floor), so never a cold run without a wait
        sock, step = _wait_warm_run(sub, backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs, warm)
    if sock is not None and step["exit"] != 0 and _worker_lost(work_p / "steps" / log_name):
        applog.anomaly("p2_worker_unhealthy", "the worker dropped the request; the run repeats in-process",
                       job_dir=work_p, exit=step["exit"])
        job_gpu.worker(work_p, job_gpu.COLD, job_gpu.COLD_FAILED)
        return _attempt(sub, backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs)
    return step


def _on_operator_modal(sub: list[str], work_p: Path, log_name: str, lk: modules.Modules, clone: Path) -> runner.Step:
    """One Part 2 call on the operator's workspace (serverless-compute.md): no fallback, the media through a Volume, the
    job page told while Modal has not started it."""
    low = quota.disk_refusal(work_p)
    if low:
        applog.log(f"part2: Modal run not started ({low})", level=logging.WARNING)
        return _skipped_step(lk, clone, log_name, work_p)
    with serverless_route.watching(work_p):
        step = runner.run(2, serverless_route.command(sub, lk.sha("2"), work_p), cwd=clone,
                          timeout_s=serverless_route.timeout_s(config.TIMEOUTS["2"]),
                          log_path=work_p / "steps" / log_name, lock=lk)
    serverless_route.note_exit(step["exit"])
    return step


def _report_worker(work_p: Path, sock: Path | None) -> None:
    """TICKET-289: the job record says whether the 3D step got the warm worker or runs the slower per-call path.
    No pool (`off`: dev, or the worker is not enabled) is not a fallback and reports nothing."""
    pool = p2_worker.state()
    if sock is not None:
        job_gpu.worker(work_p, job_gpu.WARM)
    elif pool != "off":
        job_gpu.worker(work_p, job_gpu.COLD, job_gpu.COLD_BUSY if pool == "busy" else job_gpu.COLD_RESTARTING)


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
    A busy worker is waited for up to the warm wait's bound (TICKET-320; one call at a time; going cold beside a loaded worker could
    run out of GPU memory). No worker (down, starting, restarting) runs per-call. A timed-out call or exit 1 logs
    `ANOMALY p2_tracker_unhealthy` and repeats per-call in a fresh out folder. A timed-out worker is still running
    the call and holds Part 2's GPU lock (its spec: a disconnecting client does not stop the call), so the lease
    stops it (its process group) and the repeat waits for the lock to be free. Every per-call repeat of
    local-sam31 first stops the warm worker (`_cold_attempt`): it restarts at the next lease.
    TICKET-320: while the warm tracker holds a model, an admission that times out goes on waiting for it
    (`_warm_track_call`), and a missed lease waits for it when the cold call cannot fit beside the resident workers
    (`_wait_warm_track`); either wait ends at `warm_wait.max_s()` from the start of the take's GPU wait.
    """
    warm = warm_wait.WarmWait(work_p)
    step = _warm_track_call(sub, backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs, warm)
    if step is None and p2_worker.track_holds_model() and _cold_fits(cold_min_free_mib(), gpu_lock_kwargs) is False:
        step = _wait_warm_track(sub, backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs, warm)
    if step is None:
        return _cold_attempt(sub, backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs, warm)
    if step["exit"] == 1 or step.get("timed_out"):
        applog.anomaly("p2_tracker_unhealthy", "the warm track call failed or timed out; the call repeats per-call",
                       job_dir=work_p, exit=step["exit"])
        # The worker may still be writing to the first out dir (a timed-out call keeps running), so the repeat gets its own.
        sub, fresh = _fresh_out(sub)
        retry = _cold_attempt(sub, backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs)
        retry["out_dir"] = str(fresh)
        return retry
    return step


def _warm_track_once(
    sub: list[str], backend: str, work_p: Path, log_name: str, lk: modules.Modules, clone: Path,
    acquire_lock: bool, gpu_lock_kwargs: dict[str, Any] | None, warm: warm_wait.WarmWait,
    lease_wait_s: float | None = None,
) -> runner.Step | None:
    """One admission, then the warm tracker's lease (waiting up to `lease_wait_s`, default the call timeout) and the
    call; None when no worker was lent. A lease after a warm wait ends that wait (`warm.got`)."""
    wait_s = config.TIMEOUTS["2"] if lease_wait_s is None else lease_wait_s
    with _admission(backend, acquire_lock, work_p, False, gpu_lock_kwargs, min_free_mib=TRACK_MIN_FREE_MIB):
        with p2_worker.track_lease(wait_s) as sock:
            if sock is not None:
                warm.got()
            step = _launch(sub, sock, work_p, log_name, lk, clone, backend) if sock is not None else None
            if step is not None and step.get("timed_out") and sock is not None:
                p2_worker.track_mark_restart(sock)
    return step


def _warm_track_call(
    sub: list[str], backend: str, work_p: Path, log_name: str, lk: modules.Modules, clone: Path,
    acquire_lock: bool, gpu_lock_kwargs: dict[str, Any] | None, warm: warm_wait.WarmWait,
) -> runner.Step | None:
    """`_warm_track_once`; TICKET-320: when its admission times out while the warm tracker holds a model, the take
    is admitted again with what is left of `warm`'s bound and the same wait start on its record; at the bound it
    gives up (logged) and the TimeoutError goes to `track`, which routes as before. No warm tracker: as before."""
    first = {"wait_since": warm.since, **(gpu_lock_kwargs or {})}  # one wait start on the record for both admissions
    try:
        return _warm_track_once(sub, backend, work_p, log_name, lk, clone, acquire_lock, first, warm,
                                lease_wait_s=max(0.0, warm.left()))
    except TimeoutError:
        if not (p2_worker.track_holds_model() and warm.left() > 0):
            raise
    warm.shown = True  # the admission's own watcher keeps the record's reason (another take or other GPU work)
    try:
        return _warm_track_once(sub, backend, work_p, log_name, lk, clone, acquire_lock,
                                warm_wait.admission_kw(warm, gpu_lock_kwargs), warm, lease_wait_s=max(0.0, warm.left()))
    except TimeoutError:
        warm.gave_up(f"no GPU turn within {warm_wait.max_s():g} s")
        raise
    except BaseException:
        warm.end()
        raise


def _wait_warm_track(
    sub: list[str], backend: str, work_p: Path, log_name: str, lk: modules.Modules, clone: Path,
    acquire_lock: bool, gpu_lock_kwargs: dict[str, Any] | None, warm: warm_wait.WarmWait,
) -> runner.Step | None:
    """TICKET-320: the lease missed (another take holds the warm tracker, or it starts) and a cold call cannot fit
    beside the resident workers (staging da5275f0c143, 2026-11-02 17:19Z): wait for the tracker (`warm_wait.wait_for`).
    None at the bound or when the tracker stops holding a model; the caller then goes cold (`_cold_attempt`)."""
    def attempt(kw: dict[str, Any]) -> runner.Step | None:
        return _warm_track_once(sub, backend, work_p, log_name, lk, clone, acquire_lock, kw, warm,
                                lease_wait_s=max(0.0, warm.left()))

    return warm_wait.wait_for(warm, gpu_lock_kwargs, p2_worker.track_holds_model, p2_worker.track_wait_ready, attempt)


def _free_mib(gpu_lock_kwargs: dict[str, Any] | None) -> int | None:
    """Free GPU memory now, read as the admission reads it (the caller's `memory_fn`, else nvidia-smi)."""
    read = (gpu_lock_kwargs or {}).get("memory_fn") or gpu_lock.free_gpu_memory_mib
    return read()


def _cold_fits(need: int, gpu_lock_kwargs: dict[str, Any] | None) -> bool | None:
    """TICKET-320: whether a cold call needing `need` MiB fits beside the other resident workers once the warm tracker
    is stopped: free memory now plus what an idle loaded tracker gives back (`_tracker_gives_back`; a leased or
    starting one gives back nothing certain). None when free memory cannot be read: the caller goes on as before."""
    free = _free_mib(gpu_lock_kwargs)
    if free is None:
        return None
    return free + (_tracker_gives_back() if p2_worker.track_state() == "idle" else 0) >= need


def _tracker_gives_back() -> int:
    """MiB stopping the idle tracker gives back: its size measured at load (`p2_worker.track_resident_mib`), else
    `TRACK_RESIDENT_MIB`. WSL2's nvidia-smi reports no per-process memory, so no pid is read."""
    measured = p2_worker.track_resident_mib()
    return measured if measured is not None else TRACK_RESIDENT_MIB


def _wait_warm_run(
    sub: list[str], backend: str, work_p: Path, log_name: str, lk: modules.Modules, clone: Path,
    acquire_lock: bool, gpu_lock_kwargs: dict[str, Any] | None, warm: warm_wait.WarmWait,
) -> tuple[Path | None, runner.Step]:
    """TICKET-320: the 3D step was admitted for the idle warm worker (no memory floor) and another take leased it first.
    Wait for it (`warm_wait.wait_for`, bounded from the start of the step's GPU wait), admitted on its turn again once
    nobody leases it. At the bound, or when the worker stops, the run goes in-process on the usual memory floor."""
    def attempt(kw: dict[str, Any]) -> tuple[Path, runner.Step] | None:
        with _admission(backend, acquire_lock, work_p, True, kw):
            with p2_worker.lease() as sock:
                if sock is None:
                    return None
                warm.got()
                _report_worker(work_p, sock)
                return sock, _launch(sub, sock, work_p, log_name, lk, clone, backend)

    got = warm_wait.wait_for(warm, gpu_lock_kwargs, p2_worker.holds_model, p2_worker.wait_ready, attempt)
    if got is not None:
        return got
    warm.gave_up("the warm worker stopped" if not p2_worker.holds_model() else
                 f"no warm worker within {warm_wait.max_s():g} s")
    job_gpu.worker(work_p, job_gpu.COLD, job_gpu.COLD_BUSY)
    return None, _attempt(sub, backend, work_p, log_name, lk, clone, acquire_lock, gpu_lock_kwargs)


def cold_wait_s() -> float:
    """Seconds the cold repeat waits for `cold_min_free_mib` after the tracker stopped (`COLD_WAIT_ENV`, default 60)."""
    return applog.env_float(COLD_WAIT_ENV, COLD_WAIT_DEFAULT_S)


def _skipped_step(lk: modules.Modules, clone: Path, log_name: str, work_p: Path) -> runner.Step:
    """A failed step for a run that was never started (cold local-sam31 skipped); same keys as `runner.run`."""
    return runner.Step(part=2, commit=lk.sha12("2"), argv=[], cwd=str(clone), exit=1, timed_out=False, duration_s=0.0,
                       log=str(work_p / "steps" / log_name), skipped=True)


def _cold_attempt(
    sub: list[str], backend: str, work_p: Path, log_name: str, lk: modules.Modules, clone: Path,
    acquire_lock: bool, gpu_lock_kwargs: dict[str, Any] | None, warm: warm_wait.WarmWait | None = None,
) -> runner.Step:
    """The per-call `part2 track` that follows a warm one: the warm worker is stopped first when it holds a model,
    then the call is admitted on `COLD_SAM31_MIN_FREE_MIB` (a cold run peaks near 26 GiB; TICKET-129).
    TICKET-320: a warm tracker is never stopped for a cold call that cannot fit beside the other resident workers
    (`_cold_fits`): cold local-sam31 is skipped and `track` goes on to local-open. `warm` is the take's warm wait,
    which ends here (logged) when it was shown."""
    need = cold_min_free_mib()
    if p2_worker.track_holds_model() and _cold_fits(need, gpu_lock_kwargs) is False:
        if warm is not None:
            warm.gave_up(f"no warm tracker within {warm_wait.max_s():g} s; cold local-sam31 cannot fit, local-open")
        applog.anomaly("p2_cold_sam31_skipped", "the cold call cannot fit beside the resident workers; the warm "
                       "tracker stays", job_dir=work_p, free_mib=_free_mib(gpu_lock_kwargs), need_mib=need)
        return _skipped_step(lk, clone, log_name, work_p)
    if warm is not None:
        warm.gave_up("the warm tracker stopped; cold local-sam31")
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
    # The serverless route asks for the mesh too (the Person model needs it; team, 3 Nov): it reads the flag from
    # the pin's source instead of running Part 2 locally, and the Modal call returns the whole out folder. No
    # --mesh-stream there: the stream's partial files only reach the page from a local run.
    remote_route = first_route() == "modal"
    if "--refine" not in sub and (offers_in_source(clone, "--mesh") if remote_route else has_mesh(lk, clone)):
        sub += ["--mesh"]
        if not remote_route and has_mesh_stream(lk, clone):  # TICKET-284: the pending page draws the body while the model runs
            sub += ["--mesh-stream"]
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
    fps: int | None = None,
) -> tuple[runner.Step, Path]:
    """Run `part2 track` (frames and `tracks.json`, no 3D) when the pin has it (see `capabilities`).

    `tracker="auto"` asks for `--tracker api-sam31` while the Meta budget allows (see `api_tracker_allowed`) and
    runs Part 2's default order if that run fails; a name forces it, None leaves Part 2's default order.
    A named attempt writes its own log (`_tracker_log`); when the fallback runs, its step carries the failed
    attempt under `first_try`.
    The api-sam31 run skips Part 7's GPU admission; the default-order run (it may load local SAM) keeps it.
    `fps` is the tracking rate (TICKET-198; default `TRACK_FPS`); every route below gets the same one: the warm
    worker, the per-call run, api-sam31 and the local-open GPU-busy routing.
    """
    lk = lock or modules.load()
    clone = lk.path("2")
    work_p = Path(work)
    out_dir = work_p / "part2_track"
    out_dir.mkdir(parents=True, exist_ok=True)
    sub = ["track", "--input", str(Path(video).resolve()), "--out", str(out_dir.resolve()), "--fps", str(fps or TRACK_FPS)]
    if tracker == "auto" and os.environ.get(TRACKER_ENV, "").strip():
        tracker = os.environ[TRACKER_ENV].strip()  # e.g. local-open: the free tracker on the same GPU, no Meta API
    auto_local = False
    if tracker == "auto" and p2_worker.track_state() != "off":
        tracker = LOCAL_SAM31  # the warm tracker is running: use it rather than the paid API (TICKET-117)
        auto_local = True
    if tracker == "auto":
        tracker = API_TRACKER if api_tracker_allowed(lk, clone, state) else None
    tracker = licence_gates.tracker(tracker)  # LIC-H2: prod never loads local SAM 3.1 (api-sam31, then local-open by name)
    if tracker:
        # TICKET-067: at the pin a named tracker never falls back (`trackers.select`) and api-sam31 loads no torch and
        # no local model: it uploads a video to the Meta API, so it needs no GPU admission (parts-harness.md "GPU").
        admit = acquire_lock and tracker != API_TRACKER
        began = time.monotonic()
        try:
            named = _execute(
                [*sub, "--tracker", tracker], backend, work_p, _tracker_log(tracker), lk, clone, admit,
                {**(gpu_lock_kwargs or {}), "timeout_s": track_gpu_wait_s()} if auto_local else gpu_lock_kwargs,
            )
        except TimeoutError:
            if not auto_local:
                raise
            # TICKET-191: no GPU admission for local-sam31 in time (other apps hold the card): never park the people
            # step for the 30 minute default; api-sam31 needs no local GPU, else the free local-open.
            tracker = API_TRACKER if api_tracker_allowed(lk, clone, state) else LOCAL_TRACKER
            applog.anomaly("p2_track_gpu_busy", job_dir=work_p, waited_s=round(max(track_gpu_wait_s(), time.monotonic() - began), 1),
                           free_mib=gpu_lock.free_gpu_memory_mib(), routed=tracker)
            try:
                named = _execute(
                    [*sub, "--tracker", tracker], backend, work_p, _tracker_log(tracker), lk, clone,
                    acquire_lock and tracker != API_TRACKER,
                    {"min_free_mib": LOCAL_OPEN_MIN_FREE_MIB, "timeout_s": track_gpu_wait_s(), **(gpu_lock_kwargs or {})}
                    if tracker == LOCAL_TRACKER else gpu_lock_kwargs,
                )
            except TimeoutError:
                applog.anomaly("p2_track_gpu_busy_final", job_dir=work_p, waited_s=round(time.monotonic() - began, 1),
                               free_mib=gpu_lock.free_gpu_memory_mib(),
                               detail="no GPU admission for local-sam31 or local-open; the job fails with a busy message")
                raise TimeoutError("the GPU is busy, try again in a few minutes") from None
        named_dir = Path(named.get("out_dir") or out_dir)
        if named["exit"] == 0 and (named_dir / "tracks.json").is_file():
            return (named, named_dir / "tracks.json")
        if failcause.part2_found_nobody(named):  # it looked and found nobody: a second tracker would spend again on the same clip
            return (named, named_dir / "tracks.json")
        if licence_gates.meta_barred():  # AC-SC5: Part 2's default order holds api-sam31, so nothing runs without a name
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
    if config.part1_spend_capped(p1_keyframes.total_spend_usd(state)):
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


def frame_times(
    video: Path | str, work: Path | str, fps: float, lock: modules.Modules | None = None
) -> list[float] | None:
    """Seconds of the frames `part2 run --fps <fps>` samples from `video`, from `part2 frame-times` (TICKET-203).

    None when the pinned Part 2 lacks the command (`part2 frame-times --help` fails) or the call fails; the caller
    then uses Part 7's copy of the rule (`track_resample.sample_times`)."""
    lk = lock or modules.load()
    clone = lk.path("2")
    if not Path(clone).is_dir():  # TICKET-328: nothing to run in; said once, never a silent switch
        applog.log(f"part 2 frame-times: no Part 2 checkout at {Path(clone).name}, using Part 7's rule", job_dir=work,
                   level=logging.WARNING)  # a deploy fault on staging; expected only in tests and CI
        return None
    if prod_mode.is_prod():  # this command runs ffprobe outside `ffsafe`; Part 7's rule reads the timestamps through it
        return None
    base = [*_command("cpu", [], clone)[0]]
    if not probe.help_text(2, [*base, "frame-times"], clone, lk):
        return None
    out = Path(work) / "frame_times.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    argv = [*base, "frame-times", "--input", str(Path(video).resolve()), "--fps", str(fps), "--out", str(out.resolve())]
    step = runner.run(2, argv, cwd=clone, timeout_s=probe.HELP_TIMEOUT_S, lock=lk, log_path=Path(work) / "steps" / "part2_frame_times.log")
    if step["exit"] != 0:
        return None
    try:
        return [float(f["t_ms"]) / 1000.0 for f in json.loads(out.read_text(encoding="utf-8"))["frames"]]
    except (OSError, ValueError, KeyError, TypeError):
        return None


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
        [*p2_host.base(("uv", "run", "python", "-m", "part2")), "doctor", str(Path(pose3d_path).resolve()), "--for",
         "part3"],
        cwd=clone,
        timeout_s=config.TIMEOUTS["doctor"],
        log_path=work_p / "steps" / "part2_doctor.log",
        lock=lk,
    )


def warmup_step(state: Path | str, lk: modules.Modules, sock: Path, backend: str = "gpu") -> tuple[runner.Step | None, str]:
    """TICKET-260: one 1-frame `part2 run` through the warm worker on `sock`, so the first take skips the first-run cost.

    The input is the first frame of Part 2's own single-person fixture, copied to `<state>/p2-warmup/in/`. Returns the
    step (None and a reason when the fixture is missing). The caller holds the lease and the GPU admission.
    """
    clone = lk.path("2")
    frame = clone / "fixtures" / "input" / "single" / "frames" / "000000.jpg"
    if not frame.is_file():
        return (None, "Part 2's single-person fixture frame is missing")
    work = Path(state) / "p2-warmup"
    src, out = work / "in", work / "out"
    src.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(frame, src / frame.name)
    sub = ["run", "--mode", "single", "--input", str(src.resolve()), "--out", str(out.resolve()), "--fps", str(FPS),
           "--backend", backend]
    if has_mesh(lk, clone):
        sub += ["--mesh"]
    return (_launch(sub, sock, work, "warmup.log", lk, clone, backend), "")
