"""The "Check my credentials" call (TICKET-367, parts-harness.md AC-H16, docs/specs/byok-prod.md): the smallest Modal
call that proves a user's own token works and that Simon's Part 2 app is deployed in that workspace
(`modal.App.lookup`, no GPU, no deploy).

It runs in a background thread, never the request thread, as one subprocess with a 30 s timeout, started through
`modal_creds.launch_gate` and registered with `own_clients` like every own-route client, so Remove stops it (S-R2):
`deploy/serverless/p2_client.py --own --check` under `python -I`, the same launcher a take uses, so the Modal client
gets a fresh env (the two token variables, PATH, an empty HOME). Its output is discarded, never read, so a token it
might echo cannot reach a log; only its exit code is mapped to one of the fixed reasons below. The result
`{checked_at, ok, reason, gen}` is stored beside the credentials, 0600. `gen` names the save it checked: a result for
a token since replaced is never stored or shown (R4).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from typing import Any, Callable

from part7 import applog, byok_route, modal_creds, own_clients

APP_NAME = "simon-part2"  # deploy/serverless/part2_app.py APP_NAME (a test keeps the two equal)
TIMEOUT_S = 30.0
OK, REJECTED, NO_APP = "ok", "token rejected", "Simon's app is not in this Modal workspace (run the command shown)"
TIMED_OUT, FAILED = "timed out", "check failed"
REASONS = (OK, REJECTED, NO_APP, TIMED_OUT, FAILED)
EXIT_REJECTED, EXIT_NO_APP = byok_route.CREDS_REFUSED_EXIT, 2  # p2_client.py CREDS_REFUSED_EXIT, NOT_DEPLOYED_EXIT
# What the launcher needs to find uv, and the Modal venv prod/up.sh installed (the same interpreter takes use; R8).
PASS_ENV = ("PATH", "HOME", "UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR", "SIMON7_MODAL_PYTHON")
_BUSY: set[str] = set()
_LOCK = threading.Lock()
Runner = Callable[..., Any]
_spawn = subprocess.Popen  # the launcher's process (tests replace it)


def argv() -> list[str]:
    return byok_route.check_command()


def env_of(tokens: dict[str, str]) -> dict[str, str]:
    """The launcher's env, built fresh: the user's tokens and PASS_ENV only (the launcher narrows it again)."""
    base = {k: os.environ[k] for k in PASS_ENV if k in os.environ}
    return {**base, modal_creds.ENV_ID: tokens[modal_creds.ENV_ID], modal_creds.ENV_SECRET: tokens[modal_creds.ENV_SECRET]}


def reason_of(code: int | None) -> str:
    return {0: OK, EXIT_REJECTED: REJECTED, EXIT_NO_APP: NO_APP}.get(code, FAILED) if code is not None else TIMED_OUT


def _result_path(state: Path | str, user_id: str) -> Path | None:
    path = modal_creds._path(state, user_id)
    return modal_creds.side(path, modal_creds.CHECK) if path is not None else None


def result(state: Path | str, user_id: str | None) -> dict[str, Any] | None:
    """The stored `{checked_at, ok, reason}` of the token stored now, or None. Only a known reason is returned."""
    path = _result_path(state, user_id) if user_id else None
    try:
        doc = json.loads(path.read_text(encoding="utf-8")) if path is not None and path.is_file() else None
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("reason") not in REASONS:
        return None
    if doc.get("gen") != modal_creds.generation(state, user_id):  # R4: a check of a token since replaced
        return None
    return {"checked_at": doc.get("checked_at"), "ok": doc["reason"] == OK, "reason": doc["reason"]}


def _store(state: Path | str, user_id: str, reason: str, gen: str) -> None:
    path = _result_path(state, user_id)
    if path is None:
        return
    doc = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ok": reason == OK, "reason": reason,
           "gen": gen}
    modal_creds.write_private(path, doc)  # R5: no temp file outlives a failed write


def _command() -> list[str]:
    """The check's launcher argv; inside `own_clients.job` it also registers itself, as a take's launcher does."""
    cmd = argv()
    at = cmd.index("--own") + 1
    return [*cmd[:at], *own_clients.launcher_args(), *cmd[at:]]


def _call(state: Path | str, user_id: str, run: Runner | None) -> str:
    """One launcher through `modal_creds.launch_gate` (S-R2): the tokens read under the user's lock, the process
    started and registered (`own_clients.register`) before it is let go, so Remove either finds and stops it or the
    gate gives no tokens and nothing starts. An injected `run` (tests) gets the same env, called after the lock."""
    with own_clients.job(state, user_id):
        cmd = _command()
    proc, entry = None, None
    with modal_creds.launch_gate(state, user_id) as (tokens, started):
        if tokens is None:
            return FAILED
        env = env_of(tokens)
        if run is None:
            proc = _spawn(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          start_new_session=True)
            entry = started(proc.pid)
    if proc is None:
        done = run(cmd, env=env, timeout=TIMEOUT_S, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,  # type: ignore[misc]
                   stderr=subprocess.DEVNULL, check=False)
        return reason_of(int(done.returncode))
    try:
        return reason_of(proc.wait(timeout=TIMEOUT_S))
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        return TIMED_OUT
    finally:
        if entry is not None:
            entry.unlink(missing_ok=True)  # the launcher removes its own file too


def run_check(state: Path | str, user_id: str, run: Runner | None = None) -> str:
    """One check, on the calling (background) thread; stores and returns the reason. Output is never captured."""
    gen = modal_creds.generation(state, user_id)  # read before the tokens: a save in between makes the two differ
    if gen is None:
        return FAILED
    try:
        reason = _call(state, user_id, run)
    except subprocess.TimeoutExpired:
        reason = TIMED_OUT
    except Exception as exc:  # the type only: an exception text could quote the env
        applog.log(f"modal check: could not run ({type(exc).__name__})", level=logging.WARNING)
        reason = FAILED
    if modal_creds.generation(state, user_id) == gen:  # removed or replaced meanwhile: leave no result behind (R4)
        _store(state, user_id, reason, gen)
    applog.log(f"modal check for {user_id}: {reason}", level=logging.INFO)
    return reason


def start(state: Path | str, user_id: str, run: Runner | None = None) -> bool:
    """Start one check in a background thread; False when one is already running for this user."""
    with _LOCK:
        if user_id in _BUSY:
            return False
        _BUSY.add(user_id)

    def work() -> None:
        try:
            run_check(state, user_id, run)
        finally:
            with _LOCK:
                _BUSY.discard(user_id)

    threading.Thread(target=work, name=f"modal-check-{user_id[:8]}", daemon=True).start()
    return True
