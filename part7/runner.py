"""Subprocess runner with process-group timeout and secret redaction (TICKET-009)."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from typing import Any, Callable, TextIO

from part7 import config, keys, pins


MAX_CAPTURED_CHARS = 8_000_000
KILL_GRACE_S = 10.0


class Step(dict):
    """Step execution record supporting both mapping and attribute access."""

    def __init__(self, *args: Any, stdout: str = "", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        super().__setattr__("_stdout", stdout)

    @property
    def stdout(self) -> str:
        return str(super().__getattribute__("_stdout"))

    @property
    def output(self) -> str:
        return str(super().__getattribute__("_stdout"))

    def get(self, key: Any, default: Any = None) -> Any:
        if key in ("stdout", "output") and key not in self:
            return self.stdout
        return super().get(key, default)

    def __getitem__(self, key: Any) -> Any:
        if key in ("stdout", "output") and key not in self:
            return self.stdout
        return super().__getitem__(key)

    def __getattr__(self, name: str) -> Any:
        if name in ("stdout", "output"):
            return self.stdout
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_stdout":
            super().__setattr__(name, value)
        else:
            self[name] = value


def _resolve_commit(part: int | str, lock: pins.Lock | None = None) -> str:
    lk = lock
    if lk is None:
        try:
            lk = pins.load()
        except Exception:
            return "unknown"
    try:
        return lk.sha12(part)
    except Exception:
        return "unknown"


def _pump(
    stream: TextIO,
    sink: TextIO | None,
    redact: Callable[[str], str],
    chunks: list[str],
) -> None:
    """Copy `stream` line by line, redacted, to the log sink and to the in-memory capture."""
    captured = 0
    for line in iter(stream.readline, ""):
        clean = redact(line)
        if sink is not None:
            sink.write(clean)
            sink.flush()
        if captured < MAX_CAPTURED_CHARS:
            chunks.append(clean)
            captured += len(clean)


def _kill_group(proc: subprocess.Popen[str], sig: int) -> None:
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def run(
    part: int | str,
    argv: list[str],
    cwd: Path | str,
    env_extra: dict[str, str] | None = None,
    timeout_s: float = 180.0,
    log_path: Path | str | None = None,
    lock: pins.Lock | None = None,
    kill_grace_s: float = KILL_GRACE_S,
) -> Step:
    """Run a part command in its own process group with timeout and log redaction.

    The log is written while the command runs (line by line, redacted), so a long Part 2 call can be
    followed by reading it. On timeout the group gets SIGTERM, `kill_grace_s` later SIGKILL.
    """
    env = os.environ.copy()
    if Path(cwd).resolve() != config.REPO_ROOT.resolve():
        env.pop("VIRTUAL_ENV", None)
    local_bin = str(Path.home() / ".local" / "bin")
    cur_path = env.get("PATH", "")
    env["PATH"] = f"{local_bin}:{cur_path}" if cur_path else local_bin
    if env_extra:
        for k, v in env_extra.items():
            env[str(k)] = str(v)

    cmd = [str(a) for a in argv]
    cwd_str = str(cwd)
    commit = _resolve_commit(part, lock=lock)
    redact = keys.redactor()

    sink: TextIO | None = None
    if log_path is not None:
        lpath = Path(log_path)
        lpath.parent.mkdir(parents=True, exist_ok=True)
        sink = lpath.open("w", encoding="utf-8")

    chunks: list[str] = []
    timed_out = False
    exit_code: int | None
    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd_str,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            text=True,
            errors="replace",
        )
        assert proc.stdout is not None
        pump = threading.Thread(target=_pump, args=(proc.stdout, sink, redact, chunks), daemon=True)
        pump.start()
        try:
            exit_code = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = None
            _kill_group(proc, signal.SIGTERM)
            try:
                proc.wait(timeout=kill_grace_s)
            except subprocess.TimeoutExpired:
                _kill_group(proc, signal.SIGKILL)
                proc.wait()
        pump.join(timeout=5.0)
        if timed_out:
            note = f"\npart {part} timed out after {timeout_s} s\n"
            chunks.append(note)
            if sink is not None:
                sink.write(note)
    finally:
        if sink is not None:
            sink.close()

    duration_s = round(time.monotonic() - start, 4)
    out = "".join(chunks)
    part_val: int | str = int(part) if str(part).isdigit() else str(part)
    return Step(
        part=part_val,
        commit=commit,
        argv=cmd,
        cwd=cwd_str,
        exit=exit_code,
        timed_out=timed_out,
        duration_s=duration_s,
        log=str(lpath) if log_path is not None else out,
        stdout=out,
    )
