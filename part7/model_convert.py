"""Server side of model conversion (docs/specs/model-convert.md, ADR-0017).

FBX, .blend and gltf-zip uploads are converted by a separate supervisor process (`tools/model-converter/supervisor.py`)
that owns the Docker access. This module never touches Docker. It writes a request into the spool, reads the
result the supervisor leaves, and keeps `status.json` honest.

    available() -> bool                      is a supervisor alive with an image ready
    submit(model_dir, src_path, fmt)         queue one conversion; status.json becomes `queued`
    set_done_handler(fn)                     fn(model_dir, ok, message) runs on every finished conversion
    recover_stuck(state)                     after a restart: settle the conversions of a server that is gone
    running() / cut_off()                    a stopping server waits for its conversions (TICKET-306)

In serverless mode (prod) there is no Docker and no supervisor: `part7/model_convert_modal.py` runs the same converter on
Modal and hands its result to `_finish`, so everything after the converter is one path.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Callable

from part7 import applog, compute_mode, config, import_timings, model_store

SPOOL_DIRNAME = "models-spool"
FORMATS = ("fbx", "blend", "gltf-zip")
HEARTBEAT_MAX_AGE_S = 15.0
MAX_PENDING = 10
POLL_S = 1.0
STAGE = "convert"  # status.json field set here, so recover_stuck leaves other queued work (avatar jobs) alone
UNAVAILABLE_MESSAGE = "This file type needs the converter, which is not installed here."
BUSY_MESSAGE = "The converter is busy. Try again in a few minutes."
RESTART_MESSAGE = "The server restarted while this model was converting. Upload it again."
UNCHECKED_MESSAGE = "The converted model could not be checked."
LOST_MESSAGE = "The converter did not return a model. Upload it again."

DoneHandler = Callable[[Path, bool, str], None]


class ConvertUnavailable(RuntimeError):
    """No supervisor or no image: the caller answers 415 with UNAVAILABLE_MESSAGE."""


class ConvertBusy(RuntimeError):
    """Too many conversions waiting: the caller answers 429 with BUSY_MESSAGE."""


_handler: DoneHandler | None = None
_handlers: dict[str, DoneHandler] = {}
_lock = threading.Lock()
_pollers: dict[Path, threading.Thread] = {}
_started: dict[str, float] = {}  # TICKET-363: import_timings start marks by model id
_active: dict[str, Path] = {}  # TICKET-306: conversions this server submitted that have no result yet


def spool_dir(state: str | Path | None = None) -> Path:
    return config.state_root(state) / SPOOL_DIRNAME


def set_done_handler(fn: DoneHandler | None) -> None:
    """Register the function that checks a converted model (glb_inspect, bone_map) and sets ready or failed."""
    global _handler
    _handler = fn


def available(state: str | Path | None = None) -> bool:
    if os.environ.get("SIMON7_MODEL_CONVERT") == "off":
        return False
    if compute_mode.serverless():
        return _modal().available(spool_dir(state))
    try:
        beat = json.loads((spool_dir(state) / "supervisor.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(beat, dict) or not beat.get("ready"):
        return False
    ts = beat.get("ts")
    return isinstance(ts, (int, float)) and abs(time.time() - ts) <= HEARTBEAT_MAX_AGE_S


def _modal():
    from part7 import model_convert_modal  # here: it imports this module for `_finish`

    return model_convert_modal


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def set_status(model_dir: Path, status: str, error: str | None = None) -> None:
    """Read-modify-write `status.json`, keeping owner and every other field."""
    path = model_dir / "status.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.update({"status": status, "error": error, "stage": STAGE})
    if status in ("queued", "converting"):
        data[model_store.RUN_BY] = model_store.owner_stamp()  # TICKET-306: this server waits for the result
    _write_json(path, data)


def _pending(spool: Path) -> int:
    return sum(len(list((spool / sub).glob("*.json"))) for sub in ("queue", "running"))


def reads_text_fbx(state: str | Path | None = None) -> bool:
    """A text FBX can be read: Blender cannot, FBX2glTF can. In the Modal image, whose version `available` checks; on Docker only when installed."""
    if not available(state):
        return False
    if compute_mode.serverless():
        return True
    try:
        beat = json.loads((spool_dir(state) / "supervisor.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(beat, dict) and "fbx2gltf" in (beat.get("tools") or [])


def submit(model_dir: Path | str, src_path: Path | str, fmt: str, on_done: DoneHandler | None = None,
           state: str | Path | None = None) -> None:
    """Queue one conversion. Raises ConvertUnavailable, ConvertBusy, or ValueError for a bad format or path."""
    model_dir, src = Path(model_dir).resolve(), Path(src_path).resolve()
    if state is None:
        state = model_dir.parent.parent  # <state>/models/<id>: the spool sits beside the models, whatever the server's state is
    if fmt not in FORMATS:
        raise ValueError(f"unsupported format {fmt!r}")
    if src.is_symlink() or not src.is_file() or src.parent != model_dir / "in":
        raise ValueError("the source must be a regular file in the model's in/ folder")
    if not available(state):
        raise ConvertUnavailable(UNAVAILABLE_MESSAGE)
    spool = spool_dir(state)
    for sub in ("queue", "running", "results"):
        (spool / sub).mkdir(parents=True, exist_ok=True)
    modal_route = compute_mode.serverless()
    if not modal_route and _pending(spool) >= MAX_PENDING:  # the local worker's own queue; on Modal each call waits its turn there
        raise ConvertBusy(BUSY_MESSAGE)
    job_id = model_dir.name
    if on_done is not None:
        _handlers[job_id] = on_done
    set_status(model_dir, "queued")
    with _lock:
        _active[job_id] = model_dir
    _started[job_id] = import_timings.start()  # TICKET-363: submit to result, the queue wait included
    if modal_route:
        return _modal().start(spool, model_dir, src, fmt)
    _write_json(spool / "queue" / f"{job_id}.json",
                {"id": job_id, "model_dir": str(model_dir), "src": str(src), "fmt": fmt, "submitted_at": time.time()})
    _ensure_poller(spool)


def _ensure_poller(spool: Path) -> None:
    with _lock:
        thread = _pollers.get(spool)
        if thread is not None and thread.is_alive():
            return
        thread = threading.Thread(target=_poll, args=(spool,), name="model-convert-poll", daemon=True)
        _pollers[spool] = thread
        thread.start()


def _poll(spool: Path) -> None:
    """Handle result files until nothing is queued or running, then stop (submit starts a new poller)."""
    idle_since = time.monotonic()
    while True:
        handled = poll_once(spool)
        if _pending(spool) or handled:
            idle_since = time.monotonic()
        elif time.monotonic() - idle_since > 30:
            return
        time.sleep(POLL_S)


def poll_once(spool: Path) -> int:
    """Handle every result file now present; return how many were handled."""
    count = 0
    for path in sorted((spool / "results").glob("*.json")):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        path.unlink(missing_ok=True)
        if isinstance(result, dict):
            _finish(spool, result)
            count += 1
    return count


def _model_dir(spool: Path, job_id: str) -> Path | None:
    if not (len(job_id) == 32 and all(c in "0123456789abcdef" for c in job_id)):
        return None
    target = spool.parent / "models" / job_id
    return target if target.is_dir() and not target.is_symlink() else None


def _remove(path: Path) -> None:
    if path.is_symlink():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def _finish(spool: Path, result: dict) -> None:
    job_id = str(result.get("id", ""))
    model_dir = _model_dir(spool, job_id)
    handler = _handlers.pop(job_id, None) or _handler
    with _lock:
        _active.pop(job_id, None)
    started = _started.pop(job_id, None)
    if model_dir is None:
        return
    import_timings.done(model_dir, "conversion", started)
    ok, message = bool(result.get("ok")), str(result.get("message") or "")
    produced = model_dir / "out" / "model.glb"
    if ok and (produced.is_symlink() or not produced.is_file()):
        ok, message = False, LOST_MESSAGE
    if ok:
        os.replace(produced, model_dir / "model.glb")
    _remove(model_dir / "out")
    if not ok:
        _remove(model_dir / "in")
        set_status(model_dir, "failed", message or LOST_MESSAGE)
        applog.log(f"model convert failed {job_id}: {result.get('reason')}")
        _call(handler, model_dir, False, message)
        return
    if handler is None:
        set_status(model_dir, "failed", UNCHECKED_MESSAGE)
        return
    if _call(handler, model_dir, True, "") and _status_of(model_dir) in ("ready", "failed"):
        _remove(model_dir / "in")  # a model the handler handed to the rig maker keeps in/: that job reads its mesh there


def _call(handler: DoneHandler | None, model_dir: Path, ok: bool, message: str) -> bool:
    if handler is None:
        return False
    try:
        handler(model_dir, ok, message)
    except Exception as exc:  # the handler is another lane's code; a crash there must not stop the poller
        logging.getLogger("part7").warning("model convert handler failed %s: %s", model_dir.name, exc)
        set_status(model_dir, "failed", UNCHECKED_MESSAGE)
        return False
    return True


def _status_of(model_dir: Path) -> str | None:
    try:
        data = json.loads((model_dir / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get("status") if isinstance(data, dict) else None


def running() -> list[tuple[str, str]]:
    """(model id, "convert") of every conversion this server submitted that is still queued or converting."""
    with _lock:
        active = dict(_active)
    return [(job_id, "convert") for job_id, folder in sorted(active.items())
            if _status_of(folder) in ("queued", "converting")]


def cut_off() -> list[tuple[str, str]]:
    """The drain ran out of time. A conversion still converting fails (RESTART_MESSAGE) and its spool entries go; one
    still queued stays queued in the spool for the next server (`recover_stuck`). Returns the ones failed."""
    cut: list[tuple[str, str]] = []
    with _lock:
        active = dict(_active)
    for job_id, folder in sorted(active.items()):
        if _status_of(folder) != "converting":
            continue
        spool = spool_dir(folder.parent.parent)
        for sub in ("queue", "running", "results"):
            (spool / sub / f"{job_id}.json").unlink(missing_ok=True)
        _remove(folder / "out")
        set_status(folder, "failed", RESTART_MESSAGE)
        if compute_mode.serverless():
            _modal().stop(job_id)
        cut.append((job_id, "convert"))
    return cut


def _requeue(model_dir: Path, spool: Path) -> bool:
    """A queued conversion whose server is gone is polled here when the supervisor still holds its request."""
    if not (spool / "queue" / f"{model_dir.name}.json").is_file():
        return False
    set_status(model_dir, "queued")
    with _lock:
        _active[model_dir.name] = model_dir
    _ensure_poller(spool)
    applog.log(f"model convert {model_dir.name}: queued again here, the server that queued it is gone")
    return True


def recover_stuck(state: str | Path | None = None) -> list[str]:
    """After a restart, settle every conversion still queued or converting whose server process is gone; return the
    ids failed.

    A conversion whose server still runs (`run_by`, the old server draining in a restart with no gap) is left alone
    (TICKET-306). A queued one whose request is still in the spool is polled here (`_requeue`; the done handler
    checks the result). The rest fail: spool requests and results are removed, so the supervisor discards what it
    was doing.
    """
    root = config.state_root(state)
    spool = spool_dir(state)
    failed: list[str] = []
    if compute_mode.serverless():
        _modal().refresh(spool)  # the first upload after a start should not wait for this answer
    for status_path in sorted((root / "models").glob("*/status.json")):
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("stage") != STAGE or data.get("status") not in ("queued", "converting"):
            continue
        if model_store.owner_alive(data):
            continue
        model_dir = status_path.parent
        if data.get("status") == "queued" and _requeue(model_dir, spool):
            continue
        for sub in ("queue", "running", "results"):
            (spool / sub / f"{model_dir.name}.json").unlink(missing_ok=True)
        _remove(model_dir / "out")
        set_status(model_dir, "failed", RESTART_MESSAGE)
        failed.append(model_dir.name)
    return failed
