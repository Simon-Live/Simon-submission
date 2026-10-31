"""Warm worker: models loaded once, `run` and `track` served over a Unix socket (CONTRACT.md, "Warm worker").

    part2 serve-worker --socket PATH [--backend gpu|cpu]     # serves until Ctrl-C
    part2 run --worker PATH ...                              # client: uses the worker when it is up, else in-process

Protocol: newline-delimited JSON over an AF_UNIX stream socket, one request per connection.
  request  {"argv": ["run", "--mode", "single", ...], "cwd": "/abs/dir", "env": {"PART2_PROGRESS": "1"}}
  stream   {"stream": "stdout"|"stderr", "data": "text"}   zero or more, in order, as the CLI prints
  final    {"exit": 0}
Requests run one at a time (the next connection waits in the listen queue); the GPU is shared with other
jobs, so a worker is never run concurrently with itself. The served argv is the CLI's own argv, so outputs are
what `part2 <argv>` writes. Nothing a client does ends the worker. Spec: docs/specs/warm-worker.md.
"""
import contextlib
import json
import os
import socket
import stat
import struct
import sys
import traceback
from pathlib import Path

ENV_PREFIX = "PART2_"  # the only environment a request may set
SERVED = ("run", "track")
LOST = "part2: the worker closed the connection before finishing; not re-run in-process"
_CRED = "3i"  # struct ucred: pid, uid, gid (SO_PEERCRED)


class WorkerError(OSError):
    """serve() cannot take its socket path; str() is the one-line, user-facing reason."""


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


# ---- client -------------------------------------------------------------------------------------------

def forward(path: str, argv: list[str], out=None, err=None) -> int | None:
    """Run argv on the worker at `path`, copying its output to out/err; its exit code. None when no worker is
    listening there (the caller runs in-process). A connection lost mid-request, or a socket that another
    user owns, is exit 1, never a re-run."""
    out, err = out or sys.stdout, err or sys.stderr
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(path)
    except (FileNotFoundError, ConnectionRefusedError, NotADirectoryError, PermissionError):
        s.close()
        return None
    with s:
        uid = _peer_uid(s)
        if uid is not None and uid != os.getuid():
            print(f"part2: the socket {path} belongs to another user (uid {uid}); not used", file=err)
            return 1
        return _converse(s, argv, out, err)


def _peer_uid(s) -> int | None:
    """The uid of the process that listens on connected socket s (SO_PEERCRED, Linux); None where the OS cannot say."""
    opt = getattr(socket, "SO_PEERCRED", None)
    if opt is None:
        return None
    _pid, uid, _gid = struct.unpack(_CRED, s.getsockopt(socket.SOL_SOCKET, opt, struct.calcsize(_CRED)))
    return uid


def _converse(s, argv, out, err) -> int:
    """Send the request on connected socket s and relay the reply; the job's exit code, or 1 when the worker is lost."""
    env = {k: v for k, v in os.environ.items() if k.startswith(ENV_PREFIX)}
    try:
        s.sendall((json.dumps({"argv": argv, "cwd": os.getcwd(), "env": env}) + "\n").encode("utf-8"))
    except OSError:
        return _lost(err)
    with s.makefile("r", encoding="utf-8") as f:
        while (msg := _read(f)) is not None:
            if "exit" in msg:
                return int(msg["exit"])
            sink = out if msg.get("stream") == "stdout" else err
            sink.write(msg.get("data", ""))
            sink.flush()
    return _lost(err)


def _read(f) -> dict | None:
    """The next message from the worker; None when the connection ended, broke or sent a half line."""
    try:
        msg = json.loads(f.readline() or "null")
    except (OSError, ValueError):  # reset by a dying worker; a line cut short
        return None
    return msg if isinstance(msg, dict) else None


def _lost(err) -> int:
    print(LOST, file=err)
    return 1


# ---- serving one request ---------------------------------------------------------------------------------

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
    """Serve one request read from file object f (also the reply channel). A request that is not well formed gets
    exit 2 and a one-line reason; the job's own failures are exit 1; neither stops the worker."""
    line = f.readline()
    if not line.strip():
        return  # a liveness probe, or a client that left without asking
    req, why = _parse_request(line)
    why = why or _unserved(req["argv"])
    code = _refuse(f, why) if why else _run_job(f, main, req)
    f.write(json.dumps({"exit": code if isinstance(code, int) else 1}) + "\n")
    f.flush()


def _parse_request(line: str) -> tuple[dict | None, str | None]:
    """(request, None), or (None, why it is not well formed)."""
    try:
        req = json.loads(line)
    except ValueError:
        return None, "the request is not JSON"
    if not isinstance(req, dict):
        return None, "the request must be a JSON object"
    argv, cwd, env = req.get("argv"), req.get("cwd"), req.get("env", {})
    if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        return None, "argv must be a list of strings"
    if not (isinstance(cwd, str) and os.path.isabs(cwd) and os.path.isdir(cwd) and os.access(cwd, os.X_OK)):
        return None, f"cwd must be an existing absolute directory, not {cwd!r}"
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        return None, "env must map strings to strings"
    return req, None


def _unserved(argv: list[str]) -> str | None:
    """Why the worker will not run argv, or None."""
    if not argv or argv[0] not in SERVED:
        return f"the worker serves {' and '.join(SERVED)}, not {argv[:1]}"
    if any(_is_worker_option(a) for a in argv):
        return "argv must not carry --worker (the client strips it; the worker would forward to itself)"
    return None


def _is_worker_option(arg: str) -> bool:
    """--worker, or an abbreviation argparse would resolve to it."""
    name = arg.split("=", 1)[0]
    return name.startswith("--work") or (len(name) > 2 and "--worker".startswith(name))


def _refuse(f, why) -> int:
    f.write(json.dumps({"stream": "stderr", "data": f"part2: {why}\n"}) + "\n")
    return 2


def _run_job(f, main, req: dict) -> int:
    """Run main(argv) in the request's cwd and PART2_* environment, its output streamed to f; its exit code."""
    env = {k: v for k, v in req.get("env", {}).items() if k.startswith(ENV_PREFIX)}
    log = sys.stderr  # the worker's own, before the redirect
    with _job_context(req["cwd"], env), contextlib.redirect_stdout(_Stream(f, "stdout")), \
            contextlib.redirect_stderr(_Stream(f, "stderr")):
        try:
            return main(req["argv"])
        except SystemExit as e:  # argparse errors
            return e.code if isinstance(e.code, int) else 2
        except Exception as e:  # a request must not kill the worker
            traceback.print_exc(file=log)  # the client gets one line; the worker keeps the traceback
            with contextlib.suppress(OSError):  # the client may be gone
                print(f"part2: {type(e).__name__}: {e}", file=sys.stderr)
            return 1


@contextlib.contextmanager
def _job_context(cwd: str, env: dict):
    """The request's cwd and PART2_* environment for the duration of the job: the worker's own PART2_* variables
    are hidden, and everything is put back afterwards."""
    prev_cwd, saved = os.getcwd(), _part2_environ()
    try:
        _set_part2_environ(env)
        os.chdir(cwd)
        yield
    finally:
        os.chdir(prev_cwd)
        _set_part2_environ(saved)


def _part2_environ() -> dict:
    return {k: v for k, v in os.environ.items() if k.startswith(ENV_PREFIX)}


def _set_part2_environ(env: dict) -> None:
    for k in _part2_environ():
        del os.environ[k]
    os.environ.update(env)


# ---- serving ------------------------------------------------------------------------------------------

def keep_warm(name: str, preload: bool = True):
    """Make backends.get(name) return one instance for the life of this process, with its models loaded.
    (Patched here, not in part2.backends, so the scored outputs' code stamps stay fresh.)"""
    from part2 import backends

    inst, real = backends.get(name), backends.get
    if preload and hasattr(inst, "load"):
        inst.load()
    backends.get = lambda n: inst if n == name else real(n)
    return inst


def check_socket_path(p: Path) -> bool:
    """True when a stale socket of a dead worker sits at p (to be replaced), False when p is free. WorkerError when
    p is not a socket, a worker answers there, or that cannot be told."""
    try:
        mode = os.lstat(p).st_mode  # lstat: a symlink is not a socket
    except FileNotFoundError:
        return False
    if not stat.S_ISSOCK(mode):
        raise WorkerError(f"{p} exists and is not a socket; not replacing it")
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.connect(str(p))
    except ConnectionRefusedError:
        return True
    except FileNotFoundError:
        return False
    except OSError as e:
        raise WorkerError(f"cannot tell whether a worker listens on {p}: {e}") from e
    finally:
        probe.close()
    raise WorkerError(f"a worker is already listening on {p}")


def _listen(p: Path):
    """(listening socket at p, the identity of the socket file made); a stale socket at p is replaced."""
    if check_socket_path(p):
        p.unlink()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        srv.bind(str(p))
        p.chmod(0o600)
        srv.listen(8)
    except BaseException:
        srv.close()
        raise
    return srv, _identity(p)


def _identity(p: Path) -> tuple[int, int] | None:
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return None
    return st.st_dev, st.st_ino


def remove_own(p: Path, identity) -> None:
    """Remove the socket file at p only when it is the one this process made."""
    if identity is not None and _identity(p) == identity:
        p.unlink(missing_ok=True)


def _serve_conn(conn, main) -> None:
    """One connection, start to finish. Nothing a client does may end the worker: a client that left mid-job, a
    malformed request or a bug is logged with its traceback on the worker's stderr and the loop goes on."""
    try:
        with conn, conn.makefile("rw", encoding="utf-8") as f:
            handle(f, main)
    except Exception:
        traceback.print_exc()


def serve(path: str, backend: str | None = None, preload: bool = True, ready=None) -> None:
    """Load the backend once, listen on `path` and serve requests one at a time until interrupted. WorkerError
    (before any model loads) when `path` is not a socket or a worker is already listening there."""
    from part2 import backends, cli

    p = Path(path)
    name = backends.resolve(backend)
    check_socket_path(p)
    keep_warm(name, preload)
    srv, identity = _listen(p)
    print(f"part2 worker ({name}) listening on {p}", flush=True)
    if ready:
        ready()
    try:
        while True:
            conn, _ = srv.accept()
            _serve_conn(conn, cli.main)
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
        remove_own(p, identity)
