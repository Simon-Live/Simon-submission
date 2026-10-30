"""Warm worker: models loaded once, `run` and `track` served over a Unix socket (CONTRACT.md, "Warm worker").

    part2 serve-worker --socket PATH [--backend gpu|cpu]     # serves until SIGTERM / Ctrl-C
    part2 run --worker PATH ...                              # client: uses the worker when it is up, else in-process

Protocol: newline-delimited JSON over an AF_UNIX stream socket, one request per connection.
  request  {"argv": ["run", "--mode", "single", ...], "cwd": "/abs/dir", "env": {"PART2_PROGRESS": "1"}}
  stream   {"stream": "stdout"|"stderr", "data": "text"}   zero or more, in order, as the CLI prints
  final    {"exit": 0}
Requests run one at a time (the next connection waits in the listen queue); the GPU is shared with other
jobs, so a worker is never run concurrently with itself. The served argv is the CLI's own argv, so outputs are
what `part2 <argv>` writes. Spec: docs/specs/warm-worker.md.
"""
import contextlib
import json
import os
import socket
import sys
from pathlib import Path

ENV_PREFIX = "PART2_"  # the only environment a request may set
SERVED = ("run", "track")


def strip_worker(argv: list[str]) -> tuple[list[str], str | None]:
    """(argv without --worker, the socket path or None)."""
    out, path, i = [], None, 0
    while i < len(argv):
        a = argv[i]
        if a == "--worker" and i + 1 < len(argv):
            path, i = argv[i + 1], i + 2
        elif a.startswith("--worker="):
            path, i = a.split("=", 1)[1], i + 1
        else:
            out.append(a)
            i += 1
    return out, path


def forward(path: str, argv: list[str], out=None, err=None) -> int | None:
    """Run argv on the worker at `path`, copying its output to out/err; its exit code. None when no worker is
    listening there (the caller runs in-process). A connection lost mid-request is exit 1, never a re-run."""
    out, err = out or sys.stdout, err or sys.stderr
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(path)
    except (FileNotFoundError, ConnectionRefusedError, NotADirectoryError, PermissionError):
        s.close()
        return None
    env = {k: v for k, v in os.environ.items() if k.startswith(ENV_PREFIX)}
    with s, s.makefile("rw", encoding="utf-8") as f:
        f.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "env": env}) + "\n")
        f.flush()
        for line in f:
            msg = json.loads(line)
            if "exit" in msg:
                return int(msg["exit"])
            (out if msg["stream"] == "stdout" else err).write(msg["data"])
            (out if msg["stream"] == "stdout" else err).flush()
    print("part2: the worker closed the connection before finishing; not re-run in-process", file=err)
    return 1


class _Stream:
    """A text sink that sends each write to the client as a stream message."""

    def __init__(self, f, name):
        self.f, self.name = f, name

    def write(self, data):
        if data:
            self.f.write(json.dumps({"stream": self.name, "data": data}) + "\n")
            self.f.flush()
        return len(data)

    def flush(self):
        pass


def handle(f, main) -> None:
    """Serve one request read from file object f (also the reply channel)."""
    req = json.loads(f.readline())
    argv = list(req["argv"])
    if not argv or argv[0] not in SERVED:
        code = _refuse(f, f"the worker serves {' and '.join(SERVED)}, not {argv[:1]}")
    else:
        env = {k: str(v) for k, v in req.get("env", {}).items() if k.startswith(ENV_PREFIX)}
        saved, cwd = {k: os.environ.get(k) for k in env}, os.getcwd()
        try:
            os.chdir(req["cwd"])
            os.environ.update(env)
            with contextlib.redirect_stdout(_Stream(f, "stdout")), contextlib.redirect_stderr(_Stream(f, "stderr")):
                try:
                    code = main(argv)
                except SystemExit as e:  # argparse errors
                    code = e.code if isinstance(e.code, int) else 2
                except Exception as e:  # a request must not kill the worker
                    print(f"part2: {type(e).__name__}: {e}", file=sys.stderr)
                    code = 1
        finally:
            os.chdir(cwd)
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    f.write(json.dumps({"exit": code if isinstance(code, int) else 1}) + "\n")
    f.flush()


def _refuse(f, why) -> int:
    f.write(json.dumps({"stream": "stderr", "data": f"part2: {why}\n"}) + "\n")
    return 2


def keep_warm(name: str, preload: bool = True):
    """Make backends.get(name) return one instance for the life of this process, with its models loaded.
    (Patched here, not in part2.backends, so the scored outputs' code stamps stay fresh.)"""
    from part2 import backends

    inst, real = backends.get(name), backends.get
    if preload and hasattr(inst, "load"):
        inst.load()
    backends.get = lambda n: inst if n == name else real(n)
    return inst


def serve(path: str, backend: str | None = None, preload: bool = True, ready=None) -> None:
    """Load the backend once, listen on `path` and serve requests one at a time until interrupted."""
    from part2 import backends, cli

    name = backends.resolve(backend)
    keep_warm(name, preload)
    p = Path(path)
    if p.exists():
        p.unlink()  # a stale socket from a dead worker; a live one would have answered forward()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(p))
    p.chmod(0o600)
    srv.listen(8)
    print(f"part2 worker ({name}) listening on {p}", flush=True)
    if ready:
        ready()
    try:
        while True:
            conn, _ = srv.accept()
            with conn, conn.makefile("rw", encoding="utf-8") as f:
                try:
                    handle(f, cli.main)
                except (BrokenPipeError, ConnectionResetError, json.JSONDecodeError, KeyError):
                    pass  # the client went away or sent junk; the worker stays up
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
        p.unlink(missing_ok=True)
