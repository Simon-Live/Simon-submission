"""A warm SAM 3.1 tracker process (TICKET-117), run as a script so its folder holds nothing else on `sys.path`.

`serve` runs in Part 2's gpu-cu128 venv with Part 2 on PYTHONPATH (cwd is the Part 2 clone). It loads facebook/sam3.1
once, then serves `part2 track ... --tracker local-sam31` calls over a unix socket, each run in this process by
Part 2's own CLI (`part2.cli.main`), so frames, tracks.json and its provenance are what Part 2 writes. Part 2 runs
SAM 3.1 in a child per call (its bfloat16 autocast must not reach SAM 3D Body); here the predictor stays loaded in
this process, which tracks and never runs the 3D model (that stays in Part 2's `serve-worker`, another process).
Ported from the client team's deploy/serverless/sam31_warm.py (53e3d6e, 6100157).

`call` runs in Part 7's venv (stdlib only): it sends one request, copies the call's log to its own stdout as the log
grows and exits with the call's exit code, so `runner.run` records it as an ordinary step. When the worker cannot be
reached or drops the request it prints `LOST` (the text Part 7 looks for) and exits 1.

Protocol: one JSON line per connection, {"argv": ["track", ...], "log": path}; the reply is {"exit": int}.
All calls run on the thread that built the model: SAM 3.1 enters torch.autocast(cuda, bfloat16) when built and never
leaves it, and autocast is per thread (another thread meets the model in float32: "mat1 and mat2 must have the same
dtype, but got BFloat16 and Float").
"""
from __future__ import annotations

import contextlib
import importlib
import json
import os
import socket
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

LOST = "the tracker worker closed the connection"
ALLOWED = "track"  # the only Part 2 subcommand this process serves
POLL_S = 0.2


def load() -> None:
    """Build the predictor from the cached checkpoint and point Part 2's local-sam31 at it."""
    # ADR-0002 amendment (docs/adr/ADR-0002-black-box-by-process-and-pins.md "Amendment: the warm tracker bridge"): this file is the
    # one allowlisted place that reaches Part 2 internals (local_sam31 and its run_in_child hook). The bridge is off on
    # every host by default and on staging, and goes when Part 2 ships a documented warm track entry.
    ls = importlib.import_module("part2.trackers.local_sam31")
    call_with_key = importlib.import_module("part2.trackers").call_with_key

    with ls.quiet_http_logs():
        ckpt = Path(call_with_key("local-sam31", ls.KEY, ls.hf_download))  # the token stays inside Part 2
    predictor = ls.build_predictor(ckpt)

    def warm_run(checkpoint, frames_dir, frame_records):  # replaces the per-call child process
        return {int(k): v for k, v in ls.text_prompt_track(predictor, frames_dir, frame_records).items()}

    ls.run_in_child = warm_run
    with contextlib.suppress(Exception):  # the resident figure is a log line, never a failure
        import torch

        print(f"track worker resident: torch allocated {torch.cuda.memory_allocated() // 2**20} MiB, "
              f"reserved {torch.cuda.memory_reserved() // 2**20} MiB", flush=True)


def run_request(req: dict, main) -> int:
    """Run `main(argv)` with its output in `req["log"]`; the exit code Part 2 returns (1 on any failure)."""
    argv = req.get("argv")
    if not (isinstance(argv, list) and argv and argv[0] == ALLOWED and all(isinstance(a, str) for a in argv)):
        return 2
    code = 1
    with open(req["log"], "w", buffering=1, encoding="utf-8") as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            try:
                code = int(main(argv) or 0)
            except SystemExit as e:  # argparse and Part 2's own exits
                code = e.code if isinstance(e.code, int) else 1
            except Exception:  # noqa: BLE001 (reported in the call's log, like a failed child)
                traceback.print_exc()
                code = 1
    return code


def _client_gone(conn: socket.socket) -> bool:
    """True when the peer closed its end (a non-blocking peek reads EOF); a live client has nothing more to send."""
    try:
        return conn.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT) == b""
    except BlockingIOError:
        return False
    except OSError:
        return True


def handle(conn: socket.socket, main) -> None:
    with conn, conn.makefile("rwb") as f:
        line = f.readline()
        if not line.strip():  # a health probe connects and closes
            return
        if _client_gone(conn):  # a timed-out client left while this request waited its turn: do not run it (TICKET-125)
            return
        try:
            code = run_request(json.loads(line), main)
        except (ValueError, KeyError, OSError, AttributeError):
            code = 2
        f.write((json.dumps({"exit": code}) + "\n").encode())
        f.flush()


def serve(sock_path: str, main=None, loader=load) -> None:
    loader()
    if main is None:
        main = importlib.import_module("part2.cli").main
    with contextlib.suppress(FileNotFoundError):
        os.unlink(sock_path)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(4)
    print(f"sam31 warm tracker listening on {sock_path}", flush=True)
    while True:
        conn, _ = srv.accept()
        try:
            handle(conn, main)  # on this thread, the one that built the model
        except OSError:
            continue  # a client that left mid-call does not stop the worker


def call(sock_path: str, argv: list[str], out=None) -> int:
    """Send `argv` to the worker; echo its log to `out` (default stdout) while it runs; return the exit code."""
    out = out or sys.stdout
    log = Path(tempfile.mkdtemp(prefix="s7trk-")) / "call.log"
    log.touch()
    done = threading.Event()
    pump = threading.Thread(target=_pump, args=(log, out, done), daemon=True)
    pump.start()
    code = -1
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(sock_path)
            with s.makefile("rwb") as f:
                f.write((json.dumps({"argv": argv, "log": str(log)}) + "\n").encode())
                f.flush()
                reply = f.readline()
        if reply.strip():
            code = int(json.loads(reply)["exit"])
    except (OSError, ValueError, KeyError):
        code = -1
    finally:
        done.set()
        pump.join(timeout=5)
        with contextlib.suppress(OSError):
            log.unlink()
            log.parent.rmdir()
    if code == -1:
        print(LOST, file=out, flush=True)
        return 1
    return code


def _pump(log: Path, out, done: threading.Event) -> None:
    pos = 0
    while True:
        finished = done.is_set()
        with contextlib.suppress(OSError), open(log, encoding="utf-8", errors="replace") as f:
            f.seek(pos)
            chunk = f.read()
            pos = f.tell()
            if chunk:
                out.write(chunk)
                out.flush()
        if finished:
            return
        time.sleep(POLL_S)


def main_cli(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[0] == "serve" and argv[1] == "--socket":
        serve(argv[2])
        return 0
    if len(argv) >= 4 and argv[0] == "call" and argv[1] == "--socket" and argv[3] == "--":
        return call(argv[2], argv[4:])
    print("usage: track_worker.py serve --socket S | call --socket S -- <part2 argv>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main_cli(sys.argv[1:]))
