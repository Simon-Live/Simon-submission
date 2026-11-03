"""A warm SAM 3.1 tracker for the Modal container (deploy/serverless/README.md, "Warm SAM 3.1").

Runs in Part 2's gpu-cu128 venv with Part 2 on PYTHONPATH. It loads SAM 3.1 (the gated facebook/sam3.1
checkpoint the image baked in) once, then serves `part2 track ... --tracker local-sam31` calls over a unix socket,
each run in this process by Part 2's own CLI (`part2.cli.main`), so frames, tracks.json and its provenance are
exactly what Part 2 writes. The one change: Part 2 runs SAM 3.1 in a fresh child process per call (its
bfloat16 autocast must not reach SAM 3D Body); here the predictor stays loaded in this process, which runs
tracking only (3D runs in Part 2's own serve-worker, a separate process).

Protocol: one JSON line per connection, {"argv": [...], "log": path}; the reply is one JSON line {"exit": int}.
The call's output goes to `log` (the Modal method streams it back as it grows).
"""
from __future__ import annotations

import contextlib
import json
import os
import socket
import sys
import traceback
from pathlib import Path

SOCKET = sys.argv[1] if len(sys.argv) > 1 else "/tmp/sam31-warm.sock"


def load():
    """Build the predictor from the cached checkpoint and point Part 2's local-sam31 at it."""
    from part2.trackers import local_sam31 as ls

    with ls.quiet_http_logs():
        ckpt = Path(ls.hf_download(os.environ["HF_TOKEN"]))  # baked into the image: a cache hit, no download
    predictor = ls.build_predictor(ckpt)

    def warm_run(checkpoint, frames_dir, frame_records):  # replaces the per-call child process
        return {int(k): v for k, v in ls.text_prompt_track(predictor, frames_dir, frame_records).items()}

    ls.run_in_child = warm_run


def handle(conn: socket.socket) -> None:
    from part2.cli import main

    with conn, conn.makefile("rwb") as f:
        req = json.loads(f.readline())
        code = 1
        with open(req["log"], "w", buffering=1, encoding="utf-8") as log:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                try:
                    code = int(main(req["argv"]) or 0)
                except SystemExit as e:  # argparse and Part 2's own exits
                    code = e.code if isinstance(e.code, int) else 1
                except Exception:  # noqa: BLE001 (reported in the call's log, like a failed child)
                    traceback.print_exc()
                    code = 1
        f.write((json.dumps({"exit": code}) + "\n").encode())
        f.flush()


def serve() -> None:
    load()
    with contextlib.suppress(FileNotFoundError):
        os.unlink(SOCKET)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCKET)
    srv.listen(4)
    print(f"sam31 warm tracker listening on {SOCKET}", flush=True)
    # Calls run one at a time on this thread: SAM 3.1 enters torch.autocast(cuda, bfloat16) when it is built and
    # never leaves it, and autocast is per thread, so a call on another thread meets the model in float32
    # ("mat1 and mat2 must have the same dtype, but got BFloat16 and Float").
    while True:
        conn, _ = srv.accept()
        handle(conn)


if __name__ == "__main__":
    serve()
