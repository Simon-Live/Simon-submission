"""Queue for rigged-model jobs made from photos or an unrigged mesh (docs/specs/avatar-jobs.md).

`model_import` writes the upload into `<state>/models/<id>/in/` and calls `submit_images` or `submit_autorig`. One
worker thread runs the jobs one at a time on the GPU: it takes `gpu_lock`, runs `python -m part2 avatar` or
`autorig` with Part 2's GPU venv, checks the output and hands `model.glb` to `model_import.finalize`, which checks the
GLB, maps the bones and writes `character.json`. The inputs (photos of a person) are removed on every end.
A job is `avatar-job.json` plus `status.json` on disk, so `fail_stuck` can settle jobs a restart left behind.
A stopping server drains (`begin_drain`, `running`, `cut_off`): it starts no queued job and waits for the running one
(TICKET-306); `status.json` names the server process that runs a job (`run_by`), so a restart settles only the jobs of
a server that is gone.
"""

from __future__ import annotations

import collections
import json
import logging
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import time
from typing import Any, Callable

from part7 import config, gpu_lock, import_timings, keys, model_store, p2_worker

log = logging.getLogger("part7")

from part7 import image3d_jobs  # noqa: E402  (the picture kind; a separate line so it merges beside other import edits)

MAX_IMAGES = 4
MAX_QUEUE = 8
# SAM 3D Body peaks at 10.32 GiB (10568 MiB, Part 2 TICKET-011); the floor adds about 0.7 GiB of margin.
MIN_FREE_MIB = 11264  # the GPU must have this much free before Part 2 starts
MIN_FREE_MIB_IMAGE3D = image3d_jobs.MIN_FREE_MIB  # a picture of a character or object needs its own, higher floor
CARD_POLL_S = 2.0  # how often a job waiting for the graphics card looks again
LOCK_TIMEOUT_S = 1800.0
TIMEOUT_S = {"image": 900.0, "autorig": 1800.0}
BUSY_RETRIES = 20  # exit 4 (another process took the card between our check and Part 2's own lock) is tried again this many times
RETRY_WAIT_S = 10.0
JOB_FILE = "avatar-job.json"
STATUS_FILE = "status.json"
# the stages of making a model, as the status shows them; step 1 is the upload and the last is ready (both the browser's)
STEP_INDEX = {"waiting": 2, "making": 3, "skeleton": 3, "checking": 4}
STEP_COUNT = 5
# The check after Part 2 takes well under a poll of the browser, so the "checking" step would pass unseen. The step stays
# at least this long (the check runs inside it), so the bar shows a step that did happen. Tests set it to 0.
CHECK_HOLD_S = 1.5
AVATAR_SCHEMA = "simon.avatar.v1"
DEFAULT_ATTRIBUTION = "SAM License; MHR Apache-2.0 notice"
MESSAGE_MAX = 200

MSG_NOT_SET_UP = "Model generation is not set up on this server."
MSG_BAD_IMAGES = "The pictures could not be used."
MSG_BAD_MESH = "The mesh could not be used."
MSG_NO_PERSON = {"image": "We could not find a person in the picture.", "autorig": "We could not find a body in the mesh."}
MSG_GPU_BUSY = "The graphics card is busy. Try again in a few minutes."
MSG_FAILED = "The model could not be made."
MSG_UNUSABLE = "The model came back unusable."
MSG_UNCHECKED = "The model could not be checked."
MSG_TIMEOUT = "The model took too long. Try again."
STUCK_MESSAGE = "The server restarted while this model was being made. Try again."
MSG_QUEUE_FULL = "Too many models are being made right now. Try again in a few minutes."

_SUBCOMMAND = {"image": "avatar", "autorig": "autorig"}
_TIMING_STAGE = {"image": "avatar", "autorig": "autorig", "image3d": "image3d"}  # TICKET-363
_SECRET_ENV = re.compile(r"KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


class AvatarError(Exception):
    """The request cannot be queued; `message` is plain words."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class QueueFull(AvatarError):
    """Eight jobs already wait or run."""


# --- status and job files -------------------------------------------------------------------------------------


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: Path, doc: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _step_fields(step: str | None) -> dict[str, Any]:
    return {"step": step, "step_index": STEP_INDEX[step], "step_count": STEP_COUNT} if step else {}


def _set_status(model_dir: Path, status: str, error: str | None = None, missing: list[str] | None = None,
                step: str | None = None) -> bool:
    """Update `status`, `error` and `missing` in status.json and keep the other fields. False when the folder is gone.
    A new status drops the waiting reason and place (`_note_waiting` writes them while the model stays queued) and
    sets the step: `waiting` for a queued model, else `step` (none for ready or failed)."""
    if not model_dir.is_dir():
        return False
    doc = _read_json(model_dir / STATUS_FILE) or {
        "id": model_dir.name, "owner": None, "created_at": _now(), "bytes": 0,
    }
    doc.update({"status": status, "error": error, "missing": missing})
    if status in ("queued", "converting"):
        doc[model_store.RUN_BY] = model_store.owner_stamp()  # TICKET-306: this server makes the model
    doc.pop("waiting", None)
    doc.pop("position", None)
    for key in ("step", "step_index", "step_count"):
        doc.pop(key, None)
    doc.update(_step_fields("waiting" if status == "queued" and step is None else step))
    try:
        _write_json(model_dir / STATUS_FILE, doc)
    except OSError:
        return False
    return True


def _note_waiting(model_dir: Path, text: str, position: int) -> None:
    """Tell the owner why a queued model has not started and where it stands. Written only when it changed."""
    doc = _read_json(model_dir / STATUS_FILE)
    if not doc or doc.get("status") != "queued" or (doc.get("waiting"), doc.get("position")) == (text, position):
        return
    doc.update({"waiting": text, "position": position})
    try:
        _write_json(model_dir / STATUS_FILE, doc)
    except OSError:
        pass  # the reason is a convenience; the job still waits


def _mark_step(model_dir: Path, step: str) -> None:
    """Move a converting model to a later step (Part 2 is done and the result is being checked)."""
    doc = _read_json(model_dir / STATUS_FILE)
    if doc and doc.get("status") == "converting":
        doc.update(_step_fields(step))
        try:
            _write_json(model_dir / STATUS_FILE, doc)
        except OSError:
            pass


def _place(position: int) -> str:
    return "Your model is next." if position <= 1 else f"Your model is number {position} in line."


def _refresh_positions() -> None:
    """Every model still in the queue learns its place. Called with `_cond` held."""
    ahead = 1 if _running else 0
    for i, model_dir in enumerate(_queue):
        position = ahead + i + 1
        _note_waiting(model_dir, ("Waiting in line for the models before yours. " if position > 1 else "") + _place(position), position)


def _clean(text: str) -> str:
    """One plain line: no control characters, no dashes the writer rules ban, no secrets, bounded length."""
    line = _CONTROL.sub(" ", keys.redact(text))
    line = re.sub(r"\s+[-\u2013\u2014]+\s+", ", ", line).replace("\u2014", ", ").replace("\u2013", "-")
    return " ".join(line.split())[:MESSAGE_MAX]


def _alive(model_dir: Path) -> bool:
    """The model still exists: its status file does (Part 2 may recreate `out/` under a deleted folder)."""
    return (model_dir / STATUS_FILE).is_file()


def _drop(model_dir: Path) -> None:
    """The owner deleted the model while it was made: remove what this job left behind, and the folder if empty."""
    _cleanup(model_dir)
    for name in (JOB_FILE, "avatar.log", "avatar.err"):
        (model_dir / name).unlink(missing_ok=True)
    try:
        model_dir.rmdir()
    except OSError:
        pass


def _remove_dir(path: Path) -> None:
    if path.is_symlink():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


# --- availability ---------------------------------------------------------------------------------------------

_MODULE = {"image": "avatar.py", "autorig": "autorig.py"}
image3d_jobs.extend(_SUBCOMMAND, _MODULE, TIMEOUT_S, MSG_NO_PERSON)  # the picture of a character or object kind


# The remote route (SIMON7_PART2_REMOTE=modal, through the judges' relay when SIMON_PART2_RELAY is set) runs `avatar`
# and `autorig` on Part 2's Modal image (SAM 3D Body and MHR are in it); `image3d` needs SAM 3D Objects' own venv, which
# that image does not have, so it stays local-GPU only.
REMOTE_KINDS = ("image", "autorig")


def _remote() -> bool:
    """True when Part 2 runs on Modal rather than this machine's GPU."""
    from part7.parts import p2_pose  # here: p2_pose imports much of part7
    return p2_pose.remote() is not None


def available(kind: str = "image") -> bool:
    """True when this checkout of Part 2 has the `avatar` (image) or `autorig` command and its GPU venv exists, or
    Part 2 runs on Modal and the kind runs there."""
    part2, py = config.part_dir(2), config.part2_gpu_venv_path() / "bin" / "python"
    if kind == image3d_jobs.KIND:
        return image3d_jobs.available(part2, py)
    has_module = kind in _MODULE and (part2 / "part2" / _MODULE[kind]).is_file()
    return has_module and (py.is_file() or (kind in REMOTE_KINDS and _remote()))


# --- submit ---------------------------------------------------------------------------------------------------


def _check_inputs(model_dir: Path, paths: list[Path], low: int, high: int, what: str) -> list[Path]:
    if not low <= len(paths) <= high:
        raise AvatarError(f"Send {what}.")
    in_dir = (model_dir / "in").resolve()
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_symlink() or not p.is_file() or p.resolve().parent != in_dir:
            raise AvatarError("A file could not be read.")
        out.append(p)
    return out


def _submit(kind: str, model_dir: Path | str, files: list[Path], owner: Any) -> None:
    """Queue one job. While this server drains it is written to disk only, so the next server runs it (TICKET-306)."""
    model_dir = Path(model_dir)
    names = [p.name for p in files]
    with _cond:
        if len(_queue) + (1 if _running else 0) >= MAX_QUEUE:
            raise QueueFull(MSG_QUEUE_FULL)
        _write_json(model_dir / JOB_FILE, {"kind": kind, "inputs": names, "owner": owner})
        _set_status(model_dir, "queued")
        status = _read_json(model_dir / STATUS_FILE) or {}
        if owner is not None and status.get("owner") is None:
            status["owner"] = owner
            _write_json(model_dir / STATUS_FILE, status)
        if _draining:
            return
        _queue.append(model_dir)
        _refresh_positions()
        _start_worker()


def submit_images(model_dir: Path | str, paths: list[Path | str], owner: Any) -> None:
    """Queue a model from 1 to 4 photos already saved under `model_dir/in/`."""
    files = _check_inputs(Path(model_dir), [Path(p) for p in paths], 1, MAX_IMAGES, "one to four pictures")
    _submit("image", model_dir, files, owner)


def submit_image3d(model_dir: Path | str, paths: list[Path | str], owner: Any) -> None:
    """Queue a rigged, textured model of a character or object from one picture already saved under `model_dir/in/`."""
    files = _check_inputs(Path(model_dir), [Path(p) for p in paths], 1, 1, "one picture")
    _submit(image3d_jobs.KIND, model_dir, files, owner)


def submit_autorig(model_dir: Path | str, mesh_path: Path | str, owner: Any) -> None:
    """Queue a rig for one unrigged mesh already saved under `model_dir/in/`."""
    files = _check_inputs(Path(model_dir), [Path(mesh_path)], 1, 1, "one mesh")
    _submit("autorig", model_dir, files, owner)


# --- worker ---------------------------------------------------------------------------------------------------

_cond = threading.Condition()
_queue: collections.deque[Path] = collections.deque()
_running = False
_thread: threading.Thread | None = None
_draining = False  # TICKET-306: a stopping server starts no queued job; they stay queued on disk for the next server
_current: Path | None = None  # the job the worker runs now
_proc: subprocess.Popen[bytes] | None = None  # its Part 2 process, killed when a drain cuts the job off
_cut: set[str] = set()  # jobs a drain cut off: the worker writes nothing more for them


def _start_worker() -> None:
    """Called with `_cond` held."""
    global _thread
    if _thread is None:
        _thread = threading.Thread(target=_work, name="avatar-jobs", daemon=True)
        _thread.start()


def wait_idle(timeout_s: float = 60.0) -> bool:
    """True once nothing waits or runs; False when `timeout_s` passes first."""
    deadline = time.monotonic() + timeout_s
    with _cond:
        while _queue or _running:
            left = deadline - time.monotonic()
            if left <= 0:
                return False
            _cond.wait(min(left, 0.2))
    return True


def _work() -> None:
    global _running, _thread, _current
    while True:
        with _cond:
            _current = None
            if not _queue or _draining:
                _running = False
                _thread = None
                _cond.notify_all()
                return
            model_dir = _queue.popleft()
            _running = True
            _current = model_dir
            _refresh_positions()
        try:
            _run_job(model_dir)
        except Exception:  # the worker must outlive any one job
            log.exception("avatar job %s crashed", model_dir.name)
            _set_status(model_dir, "failed", MSG_FAILED)
            _cleanup(model_dir)


def _cleanup(model_dir: Path) -> None:
    _remove_dir(model_dir / "in")
    _remove_dir(model_dir / "out")
    _remove_dir(model_dir / "tmp")


def _fail(model_dir: Path, message: str, missing: list[str] | None = None) -> None:
    _set_status(model_dir, "failed", message, missing)
    _cleanup(model_dir)


def _environment(part2: Path, scratch: Path | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}
    env["PYTHONPATH"] = str(part2)
    if scratch is not None:
        env["TMPDIR"] = str(scratch)
    return env


def _scratch(model_dir: Path, kind: str) -> Path | None:
    """A picture job's temp folder lives in its model folder, so a run that is killed leaves nothing in /tmp: Part 2's
    image3d makes `image3d-*` folders there, and a delete or a failed job removes this one with the model (TICKET-318)."""
    if kind != image3d_jobs.KIND:
        return None
    path = model_dir / "tmp"
    path.mkdir(exist_ok=True)
    return path


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        proc.kill()


def _run_part2(argv: list[str], cwd: Path, env: dict[str, str], model_dir: Path, timeout_s: float) -> int | None:
    """Run Part 2 in its own session. Exit code, or None after the timeout killed the group this call started."""
    global _proc
    with open(model_dir / "avatar.log", "ab") as out, open(model_dir / "avatar.err", "wb") as err:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                start_new_session=True)
        with _cond:
            _proc = proc
        try:
            return proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            proc.wait()
            return None
        finally:
            with _cond:
                _proc = None


def _stderr_line(model_dir: Path) -> str:
    try:
        lines = (model_dir / "avatar.err").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return _clean(next((ln for ln in reversed(lines) if ln.strip()), ""))


MSG_FREEING = "Freeing the graphics card for your model."
FREEING_S = 60.0  # after idle warm workers were released, low memory is put down to them for this long


def _why_busy() -> str:
    """The plain reason the graphics card is not free, from who holds its lock and which warm workers are busy."""
    holder = gpu_lock.lock_holder(config.gpu_lock_path()) or ""
    if "owner=staging" in holder or "busy" in (p2_worker.track_state(), p2_worker.state()):
        return "a take is being analysed"
    if holder:
        return "another job is using it"
    return "other programs are using its memory"


def _holder_is_own_worker() -> bool:
    """The GPU lock is held by one of this server's own warm workers (one being stopped), not by another job."""
    found = re.match(r"pid (\d+)", gpu_lock.lock_holder(config.gpu_lock_path()) or "")
    return bool(found) and p2_worker.own_warm_worker(int(found.group(1)))


def _waiting_text(released_at: float | None) -> str:
    """What a model waiting for the card tells its owner. While this server's own idle warm workers are being stopped
    for it (and no other job holds gpu_lock) that is what it says; "another job is using it" only for another job's
    lock (staging 2026-11-02: an image3d job said another job while staging freed its own workers)."""
    recent = released_at is not None and time.monotonic() - released_at < FREEING_S
    holder = gpu_lock.lock_holder(config.gpu_lock_path())
    if "busy" not in (p2_worker.track_state(), p2_worker.state()) \
            and ((holder is None and recent) or (holder is not None and _holder_is_own_worker())):
        return f"{MSG_FREEING} {_place(1)}"
    return f"Waiting for the graphics card: {_why_busy()}. {_place(1)}"


def min_free_mib(kind: str) -> int:
    """The free GPU memory a job of this kind waits for before Part 2 starts (image3d needs about twice a photo's)."""
    return MIN_FREE_MIB_IMAGE3D if kind == image3d_jobs.KIND else MIN_FREE_MIB


def _wait_for_card(model_dir: Path, kind: str = "image") -> bool:
    """Wait until the card has room for Part 2 and nobody holds its lock; False after LOCK_TIMEOUT_S.

    The reason and place go to the owner while this waits. An idle warm worker is asked to give its memory back once
    (a leased one is never touched, so a running take keeps its model); an image3d job asks before it looks at all,
    since its floor leaves no room for a warm worker.
    """
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    floor = min_free_mib(kind)
    released = kind == image3d_jobs.KIND
    released_at = None  # when idle warm workers were last asked to give their memory back (None: none were)
    if released and p2_worker.release_idle_workers():
        released_at = time.monotonic()
    while True:
        free = gpu_lock.free_gpu_memory_mib()
        roomy = free is None or free >= floor
        if roomy and gpu_lock.wait_free(timeout_s=0.0):
            return True
        if not roomy and not released:
            released = True
            if p2_worker.release_idle_workers():
                released_at = time.monotonic()
            continue
        _note_waiting(model_dir, _waiting_text(released_at), 1)
        if time.monotonic() >= deadline or not _alive(model_dir) or _draining:
            return False
        time.sleep(CARD_POLL_S)


def _attempt(model_dir: Path, kind: str, files: list[Path], part2: Path, py: Path) -> tuple[int | None, bool]:
    """One Part 2 run under the GPU lock. (exit code or None on timeout, lock timed out)."""
    out_dir = model_dir / "out"
    _remove_dir(out_dir)
    if kind in REMOTE_KINDS and _remote() and not py.is_file():   # no GPU here: Part 2 on Modal (deploy/judges/)
        from part7 import modules
        from part7.parts import p2_pose
        argv = p2_pose._remote_command([_SUBCOMMAND[kind], "--out", str(out_dir), *map(str, files)], modules.load())
        if not _set_status(model_dir, "converting", step="skeleton" if kind == "autorig" else "making"):
            return 4, True
        began = import_timings.start()
        code = _run_part2(argv, part2, _environment(part2, _scratch(model_dir, kind)), model_dir, TIMEOUT_S[kind])
        if code == 0:
            import_timings.done(model_dir, _TIMING_STAGE.get(kind, "avatar"), began)
        return code, False
    argv = [str(py), "-m", "part2", _SUBCOMMAND[kind], "--out", str(out_dir), *map(str, files)]
    if not _wait_for_card(model_dir, kind):
        return 4, True
    try:
        with gpu_lock.acquire(min_free_mib=min_free_mib(kind), timeout_s=LOCK_TIMEOUT_S, hold_flock=False,
                              priority=gpu_lock.LOW):  # GPU guard: an avatar build yields to a staging take
            made = "skeleton" if kind == "autorig" else "making"  # the skeleton for a mesh, else the model from pictures
            if not _set_status(model_dir, "converting", step=made):  # the status turns to working only when Part 2 starts
                return 4, True
            began = import_timings.start()  # TICKET-363: Part 2's run only, the wait for the card left out
            code = _run_part2(argv, part2, _environment(part2, _scratch(model_dir, kind)), model_dir, TIMEOUT_S[kind])
            if code == 0:
                import_timings.done(model_dir, _TIMING_STAGE.get(kind, "avatar"), began)
            return code, False
    except TimeoutError:
        return 4, True


def _exit_message(kind: str, code: int, model_dir: Path) -> str:
    picture = image3d_jobs.exit_message(kind, code, _stderr_line(model_dir))
    if picture:
        return picture
    if code == 2:
        return _stderr_line(model_dir) or (MSG_BAD_IMAGES if kind == "image" else MSG_BAD_MESH)
    if code == 3:
        return MSG_NO_PERSON[kind]
    if code == 4:
        return MSG_GPU_BUSY
    return MSG_FAILED


def _read_output(model_dir: Path, kind: str) -> tuple[Path, dict[str, Any]] | None:
    glb = model_dir / "out" / "model.glb"
    doc = _read_json(model_dir / "out" / "avatar.json")
    try:
        ok = glb.is_file() and not glb.is_symlink() and glb.stat().st_size > 0
    except OSError:
        ok = False
    if not ok or doc is None or doc.get("schema") != AVATAR_SCHEMA or doc.get("kind") != kind:
        return None
    return glb, doc


def _finalize_fn() -> Callable[[Path, Path, dict[str, Any]], Any]:
    from part7 import model_import  # late: the importer module imports this one

    return model_import.finalize


def _licence_text(doc: dict[str, Any]) -> str:
    text = doc.get("licence")
    return _clean(text) if isinstance(text, str) and text.strip() else DEFAULT_ATTRIBUTION


def _finalize(model_dir: Path, kind: str, glb: Path, doc: dict[str, Any]) -> None:
    doc = image3d_jobs.with_licence(kind, doc)
    extra = {
        "kind": "generated", "source_kind": kind, "preset": "simon-avatar", "avatar": doc,
        "licence": {"id": "own-work", "attribution": _licence_text(doc), "shareable": False},
    }
    try:
        manifest = _finalize_fn()(model_dir, glb, extra)
    except Exception as exc:
        log.warning("avatar job %s: finalize refused: %s", model_dir.name, type(exc).__name__)
        message = getattr(exc, "message", None)
        missing = getattr(exc, "missing", None)
        _fail(model_dir, _clean(message) if isinstance(message, str) and message.strip() else MSG_UNCHECKED,
              list(missing) if isinstance(missing, (list, tuple)) else None)
        return
    if manifest is None:  # the importer refused the model and has already written failed with its reason
        _cleanup(model_dir)
        return
    state = _read_json(model_dir / STATUS_FILE) or {}
    if state.get("status") != "ready":
        _set_status(model_dir, "ready")
    _cleanup(model_dir)


def _grey_fallback(model_dir: Path, kind: str) -> bool:
    """A person photo sent with the look option whose rig failed (image3d exit 3) is queued again as the grey body job.

    The model remembers it (`look_fallback`), so `model_import` tells the person in plain words. False for any other job."""
    meta = model_store.read_meta(model_dir)
    job = _read_json(model_dir / JOB_FILE)
    if kind != image3d_jobs.KIND or not meta.get("look") or job is None:
        return False
    model_store.write_meta(model_dir, {**meta, "look_fallback": True})
    _write_json(model_dir / JOB_FILE, {**job, "kind": "image"})
    return _set_status(model_dir, "queued")


def _run_job(model_dir: Path) -> None:
    job = _read_json(model_dir / JOB_FILE)
    state = _read_json(model_dir / STATUS_FILE)
    if job is None or state is None or state.get("status") != "queued":
        return  # deleted, or settled by someone else, while it waited
    kind = job.get("kind") if job.get("kind") in _SUBCOMMAND else "image"
    files = [model_dir / "in" / str(n) for n in job.get("inputs", [])]
    part2, py = config.part_dir(2), config.part2_gpu_venv_path() / "bin" / "python"
    if not part2.is_dir() or not py.is_file():
        _fail(model_dir, MSG_NOT_SET_UP)
        return
    code: int | None = 4
    for attempt in range(BUSY_RETRIES + 1):
        if not _alive(model_dir):
            return _drop(model_dir)
        code, lock_timed_out = _attempt(model_dir, kind, files, part2, py)
        if code != 4 or lock_timed_out:
            break
        if attempt < BUSY_RETRIES:
            _set_status(model_dir, "queued")
            _note_waiting(model_dir, "The graphics card was busy. Trying again in a moment.", 1)
            time.sleep(RETRY_WAIT_S)
    if model_dir.name in _cut or _left_for_next_server(model_dir):
        return
    if not _alive(model_dir):
        return _drop(model_dir)
    if code is None:
        _fail(model_dir, MSG_TIMEOUT)
    elif code == 3 and _grey_fallback(model_dir, kind):
        return _run_job(model_dir)  # TICKET-318: no figure fitted the clothed photo; the plain grey body is made instead
    elif code != 0:
        _fail(model_dir, _exit_message(kind, code, model_dir))
    else:
        found = _read_output(model_dir, kind)
        _mark_step(model_dir, "checking")
        time.sleep(CHECK_HOLD_S)
        if found is None:
            _fail(model_dir, MSG_UNUSABLE)
        else:
            _finalize(model_dir, kind, *found)


# --- restart --------------------------------------------------------------------------------------------------


def _left_for_next_server(model_dir: Path) -> bool:
    """A drain began before Part 2 started: the job stays queued on disk, with its inputs, for the next server."""
    state = _read_json(model_dir / STATUS_FILE) or {}
    return _draining and state.get("status") == "queued"


def begin_drain() -> None:
    """TICKET-306: this server is stopping. No queued job starts here any more (each stays queued on disk, for the next
    server to run); a new one is only written to disk."""
    global _draining
    with _cond:
        _draining = True
        _queue.clear()
        _cond.notify_all()


def running() -> list[tuple[str, str]]:
    """(model id, kind) of the job the worker runs now, for the drain to wait on."""
    with _cond:
        model_dir = _current if _running else None
    if model_dir is None:
        return []
    kind = (_read_json(model_dir / JOB_FILE) or {}).get("kind")
    return [(model_dir.name, str(kind if kind in _SUBCOMMAND else "image"))]


def cut_off() -> list[tuple[str, str]]:
    """The drain ran out of time: the running job is failed with STUCK_MESSAGE and its Part 2 group is killed."""
    found = running()
    with _cond:
        proc, model_dir = _proc, _current
        _cut.update(model_id for model_id, _ in found)
    if proc is not None:
        _kill_group(proc)
    if model_dir is not None and found and model_dir.name == found[0][0] \
            and (_read_json(model_dir / STATUS_FILE) or {}).get("status") in ("queued", "converting") \
            and _set_status(model_dir, "failed", STUCK_MESSAGE):
        _cleanup(model_dir)
    return found


def _requeue(model_dir: Path) -> bool:
    """A queued job whose server is gone runs here when its inputs are still on disk; False when they are not."""
    job = _read_json(model_dir / JOB_FILE) or {}
    kind = job.get("kind")
    if kind not in _SUBCOMMAND:
        return False
    inputs = [model_dir / "in" / str(n) for n in job.get("inputs") or []]
    try:
        files = _check_inputs(model_dir, inputs, 1, MAX_IMAGES, "the pictures again")
        _submit(kind, model_dir, files, job.get("owner"))
    except (AvatarError, OSError):
        return False
    log.info("avatar job %s: queued again here, the server that queued it is gone", model_dir.name)
    return True


def fail_stuck(models_root: Path | str) -> list[str]:
    """After a restart: settle the avatar jobs left `queued` or `converting` by a server process that is gone.

    A queued one runs again here when its inputs are still on disk; the rest become `failed` (STUCK_MESSAGE). A job
    whose server still runs (`run_by`, the old server draining in a restart with no gap) is left alone. Returns the
    ids failed."""
    root = Path(models_root)
    changed: list[str] = []
    if not root.is_dir():
        return changed
    for entry in sorted(root.iterdir()):
        if entry.is_symlink() or not (entry / JOB_FILE).is_file():
            continue
        state = _read_json(entry / STATUS_FILE)
        if not state or state.get("status") not in ("queued", "converting") or model_store.owner_alive(state):
            continue
        if state.get("status") == "queued" and _requeue(entry):
            continue
        if _set_status(entry, "failed", STUCK_MESSAGE):
            _cleanup(entry)
            changed.append(entry.name)
    return changed
