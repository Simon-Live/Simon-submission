"""Warm worker: models loaded once, `run` and `track` served over a Unix socket (CONTRACT.md, "Warm worker").

    part2 serve-worker --socket PATH [--backend gpu|cpu|cpu-sam3db]   # serves until Ctrl-C
    part2 run --worker PATH ...                                       # client: uses the worker when it is up, else in-process

Protocol: newline-delimited JSON over an AF_UNIX stream socket, one request per connection.
  request  {"argv": ["run", "--mode", "single", ...], "cwd": "/abs/dir", "env": {"PART2_PROGRESS": "1"}}
  stream   {"stream": "stdout"|"stderr", "data": "text"}   zero or more, in order, as the CLI prints
  alive    {"keepalive": true}                              at once when the worker takes the request, then every
                                                            KEEPALIVE_S while the job runs; nothing to print
  final    {"exit": 0}
Requests run one at a time (the next connection waits in the listen queue); the GPU is shared with other
jobs, so a worker is never run concurrently with itself. The served argv is the CLI's own argv, so outputs are
what `part2 <argv>` writes. Nothing a client does ends the worker. A client waits for its turn up to
CLIENT_QUEUE_WAIT_S (its first line is the keepalive the worker sends when it takes the request), then gives up after
CLIENT_IDLE_TIMEOUT_S without a line; either way it exits 1 and never re-runs the job in-process. A queued request
whose client has left by its turn is not run. Spec: docs/specs/warm-worker.md.
"""
import contextlib
import json
import os
import reprlib
import select
import socket
import stat
import struct
import sys
import threading
import traceback
from pathlib import Path

ENV_PREFIX = "PART2_"  # the only environment a request may set
SERVED = ("run", "track")
# While a job runs, the worker sends {"keepalive": true} this often (seconds), whatever the job prints: a 3D stage
# can be silent for many minutes. warm-worker.md, AC-W14.
KEEPALIVE_S = 30
# The client's idle limit: seconds without a line from the worker (a keepalive counts) before it drops the
# connection, once the worker has taken its request. Four keepalive periods, so that one late beat does not cut a
# healthy job off while a hung or vanished worker is noticed within two minutes. warm-worker.md, AC-W12.
CLIENT_IDLE_TIMEOUT_S = 120
# The client's wait for its turn: seconds before the worker's first line (it sends a keepalive the moment it takes
# the request). The worker serves one request at a time, so a request in the listen queue (8 deep) hears nothing while
# the jobs ahead run. One hour clears eight typical jobs (141.5 s each, TICKET-041 class smoke) and two class jobs of
# five people (about 1800 s each, an estimate), and still ends the wait on a worker that is alive but never takes
# the request. warm-worker.md, AC-W17.
CLIENT_QUEUE_WAIT_S = 3600
UNIX_PATH_MAX = 107  # bytes of a Unix socket path on Linux (sun_path is 108 with its NUL); bind and connect refuse more
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
    listening there: any OSError on connect (no such socket, connection refused, permission denied, a path too
    long for a Unix socket) is "no worker", and the caller runs in-process. A connection lost mid-request, a message
    that is not well formed, no turn at the worker within CLIENT_QUEUE_WAIT_S, a worker silent for
    CLIENT_IDLE_TIMEOUT_S once it has taken the request, a reply with an exit code that is not an integer, or a
    socket that another user owns, is exit 1, never a re-run."""
    out, err = out or sys.stdout, err or sys.stderr
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(path)  # blocking: with the 8-deep queue full, the connect waits for a place in it
    except OSError:
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
    """Send the request on connected socket s and relay the reply; the job's exit code, or 1 when the worker is lost,
    never takes the request within CLIENT_QUEUE_WAIT_S, goes quiet for CLIENT_IDLE_TIMEOUT_S or answers with an exit
    code that is not an integer."""
    s.settimeout(CLIENT_QUEUE_WAIT_S)  # until the worker's first line: waiting for a turn behind other jobs
    return _exchange(s, argv, out, err)


def _exchange(s, argv, out, err) -> int:
    """Send the request and relay the reply. Two waits, both ending in exit 1 (_gave_up): the socket's timeout is
    CLIENT_QUEUE_WAIT_S until the worker's first line and CLIENT_IDLE_TIMEOUT_S between lines after it."""
    heard = False  # the worker's first line, a keepalive at once, says that this request's turn has come
    try:
        if not _send_request(s, argv):
            return _lost(err)
        with s.makefile("r", encoding="utf-8") as f:
            while (msg := _read(f)) is not None:
                if not heard:
                    heard = True
                    s.settimeout(CLIENT_IDLE_TIMEOUT_S)  # from here every read waits at most this long
                if "exit" in msg:
                    return _exit_code(msg["exit"], err)
                if "keepalive" in msg:
                    continue  # a sign of life: reading it restarted the idle wait, and there is nothing to print
                if not _relay(msg, out, err):
                    break
    except TimeoutError:
        return _gave_up(heard, err)
    return _lost(err)


def _send_request(s, argv) -> bool:
    """Send the request; False when the connection is already broken. A send that waits past the socket's timeout
    raises TimeoutError."""
    request = {"argv": argv, "cwd": os.getcwd(), "env": _part2_only(os.environ)}
    try:
        s.sendall((json.dumps(request) + "\n").encode("utf-8"))
    except TimeoutError:
        raise
    except OSError:
        return False
    return True


def _gave_up(heard: bool, err) -> int:
    """Exit 1 for a wait that ran out, with the line that names which one: the turn (nothing heard yet) or the idle
    limit (the worker had taken the request)."""
    if heard:
        print(f"part2: the worker sent nothing for {CLIENT_IDLE_TIMEOUT_S:g} s; connection dropped, "
              "not re-run in-process", file=err)
    else:
        print(f"part2: waited {CLIENT_QUEUE_WAIT_S:g} s for a turn at the worker; connection dropped, "
              "not re-run in-process", file=err)
    return 1


def _relay(msg: dict, out, err) -> bool:
    """Print a stream message on out (stdout) or err (stderr); False when msg is not one: any other `stream`, or
    `data` that is not a string. The caller treats that like a lost connection."""
    stream, data = msg.get("stream"), msg.get("data")
    if stream not in ("stdout", "stderr") or not isinstance(data, str):
        return False
    sink = out if stream == "stdout" else err
    sink.write(data)
    sink.flush()
    return True


def _read(f) -> dict | None:
    """The next message from the worker; None when the connection ended, broke or sent a half line. A read that
    waits past the socket's timeout raises TimeoutError (the caller reports which wait ran out)."""
    try:
        msg = json.loads(f.readline() or "null")
    except TimeoutError:
        raise
    except (OSError, ValueError):  # reset by a dying worker; a line cut short
        return None
    return msg if isinstance(msg, dict) else None


def _exit_code(value, err) -> int:
    """The worker's exit code; exit 1 with one line when it is not an integer (a bool is not one)."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    print(f"part2: the worker sent an exit code that is not an integer ({reprlib.repr(value)}); "
          "treated as exit 1", file=err)
    return 1


def _lost(err) -> int:
    print(LOST, file=err)
    return 1


# ---- serving one request ---------------------------------------------------------------------------------

class _Channel:
    """The reply side of one connection. A message is one JSON line, written and flushed whole under a lock, so the
    job's output, the keepalives and the final exit never interleave, whichever thread sends them."""

    def __init__(self, f):
        self.f, self.lock = f, threading.Lock()

    def send(self, msg: dict) -> None:
        line = json.dumps(msg) + "\n"
        with self.lock:
            self.f.write(line)
            self.f.flush()


class _Stream:
    """A text sink that sends each write to the client as a stream message."""

    def __init__(self, chan, name):
        self.chan, self.name = chan, name

    def write(self, data):
        if data:
            self.chan.send({"stream": self.name, "data": data})
        return len(data)

    def flush(self):
        pass


def handle(f, main, conn=None) -> None:
    """Serve one request read from file object f (also the reply channel); conn is the connected socket behind f,
    when the caller has it. A request that is not well formed gets exit 2 and a one-line reason; the job's own
    failures are exit 1; neither stops the worker. A client that has left (conn fully closed) before the job starts
    gets nothing: the request is not run, so a client that timed out in the queue costs the worker no job. A client
    that is there gets a keepalive at once, before anything runs: its first line, which ends its wait for a turn."""
    line = f.readline()
    if not line.strip():
        return  # a liveness probe, or a client that left without asking
    chan = _Channel(f)
    if (conn is not None and _client_gone(conn)) or not _announce_turn(chan):
        print(f"part2 worker: the client left before its turn; request not run: {reprlib.repr(line.strip())}",
              file=sys.stderr)
        return
    req, why = _parse_request(line)
    why = why or _unserved(req["argv"])
    code = _refuse(chan, why) if why else _run_job(chan, main, req)
    chan.send({"exit": code if isinstance(code, int) else 1})


def _announce_turn(chan) -> bool:
    """Send the keepalive that tells the client its turn has come; False when it cannot be sent (the client left)."""
    try:
        chan.send({"keepalive": True})
    except (OSError, ValueError):
        return False
    return True


def _client_gone(conn) -> bool:
    """True when the peer of connected socket conn has closed it. A peer that only closed its sending side after the
    request (shutdown(SHUT_WR), "that was all") still reads the reply and is not gone: Linux reports POLLHUP only for
    a full close, which is why this polls and does not peek for an end of stream. Where the OS says nothing, False."""
    gone = select.POLLHUP | select.POLLERR
    poller = select.poll()
    poller.register(conn.fileno(), gone)
    return any(events & gone for _fd, events in poller.poll(0))


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


def _refuse(chan, why) -> int:
    chan.send({"stream": "stderr", "data": f"part2: {why}\n"})
    return 2


@contextlib.contextmanager
def _keepalive(chan):
    """While the block runs, a timer thread sends {"keepalive": true} every KEEPALIVE_S seconds (through the
    channel's lock) so that the client can tell a long quiet stage from a worker that is gone. It ends with the
    block, or at once when a send fails: a client that left is noticed by the job's next write, as before."""
    stop = threading.Event()

    def beat():
        while not stop.wait(KEEPALIVE_S):
            try:
                chan.send({"keepalive": True})
            except (OSError, ValueError):  # the client left, or its file is closed
                return

    thread = threading.Thread(target=beat, name="part2-keepalive", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


def _run_job(chan, main, req: dict) -> int:
    """Run main(argv) in the request's cwd and PART2_* environment, its output streamed to the client; its exit code."""
    env = _part2_only(req.get("env", {}))
    log = sys.stderr  # the worker's own, before the redirect
    with _job_context(req["cwd"], env), contextlib.redirect_stdout(_Stream(chan, "stdout")), \
            contextlib.redirect_stderr(_Stream(chan, "stderr")), _keepalive(chan):
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
    prev_cwd, saved = os.getcwd(), _part2_only(os.environ)
    try:
        _set_part2_environ(env)
        os.chdir(cwd)
        yield
    finally:
        os.chdir(prev_cwd)
        _set_part2_environ(saved)


def _part2_only(env) -> dict:
    """The PART2_* entries of the mapping env: the only environment that crosses the socket or is set for a job."""
    return {k: v for k, v in env.items() if k.startswith(ENV_PREFIX)}


def _set_part2_environ(env: dict) -> None:
    for k in _part2_only(os.environ):
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
    p is not a socket, a worker answers there, that cannot be told, or a socket could not be made there anyway: the
    path is longer than UNIX_PATH_MAX bytes, or its directory is missing, not a directory or not writable. All of
    it is known before any model loads."""
    size = len(os.fsencode(p))
    if size > UNIX_PATH_MAX:
        raise WorkerError(f"the socket path {p} is {size} bytes; a Unix socket path holds at most {UNIX_PATH_MAX}")
    parent = p.parent
    if not os.path.isdir(parent):
        raise WorkerError(f"cannot make the socket {p}: {parent} is not an existing directory")
    stale = _stale_socket(p)  # before the permission check: a live worker is the more useful thing to say
    if not os.access(parent, os.W_OK | os.X_OK):
        raise WorkerError(f"cannot make the socket {p}: no permission to create files in {parent}")
    return stale


def _stale_socket(p: Path) -> bool:
    """True when a stale socket of a dead worker sits at p, False when p is free; WorkerError when p is not a
    socket, a worker answers there, or that cannot be told."""
    try:
        mode = os.lstat(p).st_mode  # lstat: a symlink is not a socket
    except FileNotFoundError:
        return False
    except OSError as e:
        raise WorkerError(f"cannot look at {p}: {e}") from e
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
            handle(f, main, conn)
    except Exception:
        traceback.print_exc()


def serve(path: str, backend: str | None = None, preload: bool = True, ready=None) -> None:
    """Load the backend once, listen on `path` and serve requests one at a time until interrupted. WorkerError
    (before any model loads) when `path` is not a socket, a worker is already listening there, or no socket can be
    made there (see check_socket_path)."""
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
