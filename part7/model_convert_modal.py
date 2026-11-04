"""The Modal route of model conversion (docs/specs/model-convert.md "On Modal").

    available(spool)                  the app is deployed, as last checked, and the stop file is absent
    start(spool, model_dir, src, fmt) run `deploy/serverless/convert_client.py` in a thread, then `model_convert._finish`
    stop(job_id)                      end a running client (the drain ran out of time)
    refresh(spool)                    ask Modal again whether the app is deployed, in the background

Whatever the client brings back was written next to a stranger's file in a Blender process, so it is checked as
`tools/model-converter/supervisor.py` checks a container's output, by the same functions.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

from part7 import applog, config, model_convert, quota

CLIENT = config.REPO_ROOT / "deploy" / "serverless" / "convert_client.py"
READY_FILE = "modal-ready.json"
RECHECK_S = 3600.0  # how old a yes to "is the app deployed" may get before it is asked again
RECHECK_NO_S = 60.0  # and how old a no: after a redeploy or a Modal recovery uploads work again within a minute
CHECK_TIMEOUT_S = 60.0
CALL_TIMEOUT_S = 860.0  # convert_client.py WAIT_S, plus the upload
TIMEOUT_EXIT = 78  # = convert_client.py TIMEOUT_EXIT
SLOTS = threading.BoundedSemaphore(2)  # conversions at once; the rest wait as `queued`
FAILED_NOW = "Simon cannot convert files right now. Upload a GLB or VRM, or try again later."
INPUT_NAMES = {"fbx": "input.fbx", "blend": "input.blend", "gltf-zip": "input.zip"}

_lock = threading.Lock()
_checking = False
_procs: dict[str, subprocess.Popen] = {}


def _load_supervisor() -> Any:
    """tools/model-converter/supervisor.py by path: its checks of what a jail printed, its caps and its messages."""
    path = config.REPO_ROOT / "tools" / "model-converter" / "supervisor.py"
    spec = importlib.util.spec_from_file_location("simon7_converter_supervisor", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


supervisor = _load_supervisor()


def _command(*args: str) -> list[str]:
    return [sys.executable, "-I", str(CLIENT), "--secrets-dir", str(config.keys_dir()), *args]


# ---------------------------------------------------------------- is it there
def _read(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _write(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    os.replace(tmp, path)


def _check(spool: Path) -> None:
    global _checking
    try:
        done = subprocess.run(_command("--check"), capture_output=True, timeout=CHECK_TIMEOUT_S, check=False, stdin=subprocess.DEVNULL)
        ok = done.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    _write(spool / READY_FILE, {"ok": ok, "ts": time.time()})
    if not ok:
        applog.log("model convert: the Modal converter app is not usable; FBX, Blender and glTF zip uploads are refused")
    with _lock:
        _checking = False


def refresh(spool: Path) -> None:
    """Ask once, in the background: a request never waits for Modal."""
    global _checking
    with _lock:
        if _checking:
            return
        _checking = True
    threading.Thread(target=_check, args=(spool,), name="model-convert-check", daemon=True).start()


def available(spool: Path) -> bool:
    if (spool.parent / quota.STOP_FILE).exists():
        return False
    doc = _read(spool / READY_FILE)
    ts = doc.get("ts")
    if not isinstance(ts, (int, float)) or abs(time.time() - ts) > (RECHECK_S if doc.get("ok") is True else RECHECK_NO_S):
        refresh(spool)
    return doc.get("ok") is True


# ---------------------------------------------------------------- one conversion
def start(spool: Path, model_dir: Path, src: Path, fmt: str) -> None:
    threading.Thread(target=_work, args=(spool, model_dir, src, fmt), name=f"model-convert-{model_dir.name[:8]}", daemon=True).start()


def stop(job_id: str) -> None:
    with _lock:
        proc = _procs.get(job_id)
    if proc is not None:
        proc.terminate()


def _call(job_id: str, argv: list[str]) -> int | None:
    """The client's exit code, or None when it ran out of time."""
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with _lock:
        _procs[job_id] = proc
    try:
        return proc.wait(CALL_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        return None
    finally:
        with _lock:
            _procs.pop(job_id, None)


def outcome_of(folder: Path, code: int | None) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """(result for `model_convert._finish`, the checked outcome, the attempts) from what the client brought back."""
    if code is None or code == TIMEOUT_EXIT:
        return {"ok": False, "reason": "timeout", "message": supervisor.TIMEOUT_MESSAGE}, {}, []
    doc = _read(folder / "result.json") if code == 0 else {}
    if not doc:
        return {"ok": False, "reason": "stopped", "message": FAILED_NOW}, {}, []
    outcome = supervisor.clean_outcome(doc.get("outcome"))
    raw = doc.get("attempts")
    attempts = [{"reader": "fbx2gltf" if a.get("reader") == "fbx2gltf" else "blender", "image": str(a.get("reader"))[:40], "ok": not a.get("reason"), "reason": str(a.get("reason") or "")[:40]}
                for a in raw[:supervisor.caps.MAX_ATTEMPTS] if isinstance(a, dict)] if isinstance(raw, list) else []
    reason = doc.get("reason")
    if reason == "too-big":
        return {"ok": False, "reason": reason, "message": supervisor.TOO_BIG_MESSAGE}, outcome, attempts
    if reason == "timeout":
        return {"ok": False, "reason": reason, "message": supervisor.TIMEOUT_MESSAGE}, outcome, attempts
    glb = folder / "model.glb"
    if reason or glb.is_symlink() or not glb.is_file() or glb.stat().st_size == 0:
        return {"ok": False, "reason": "failed", "message": supervisor.failure_message(outcome)}, outcome, attempts
    return {"ok": True, "reason": "", "message": ""}, outcome, attempts


def _work(spool: Path, model_dir: Path, src: Path, fmt: str) -> None:
    job_id = model_dir.name
    began = time.monotonic()
    with SLOTS, tempfile.TemporaryDirectory(prefix="convert-", dir=model_dir, ignore_cleanup_errors=True) as tmp:
        if model_convert._status_of(model_dir) != "queued":
            return
        model_convert.set_status(model_dir, "converting")
        folder = Path(tmp)
        code: int | None = 1
        try:
            code = _call(job_id, _command("--input", str(src), "--name", INPUT_NAMES[fmt], "--out", str(folder)))
        except OSError as exc:
            applog.log(f"model convert {job_id}: the client did not start ({type(exc).__name__})")
        result, outcome, attempts = outcome_of(folder, code)
        if model_convert._status_of(model_dir) != "converting":  # the drain ran out of time and settled it
            return
        if result["ok"]:
            dest = model_dir / "out"
            dest.mkdir(exist_ok=True)
            shutil.move(str(folder / "model.glb"), dest / "model.glb")
        log = folder / "log.txt"
        if log.is_file() and not log.is_symlink():
            shutil.copyfile(log, model_dir / "convert.log")
        reader = next((a["reader"] for a in reversed(attempts) if a["ok"]), None)
        model_convert._write_json(model_dir / "convert.json", {
            "ok": result["ok"], "reader": reader, "mode": outcome.get("mode"), "code": outcome.get("code"),
            "steps": outcome.get("steps") or [], "attempts": attempts})
        model_convert._finish(spool, {"id": job_id, **result, "seconds": round(time.monotonic() - began, 1)})
