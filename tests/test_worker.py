"""Warm worker protocol (part2.worker): forwarding, streaming, exit codes, fallback, survival of bad clients and
bad requests, socket ownership. Spec: docs/specs/warm-worker.md. No model, no GPU: the served main is a fake."""
import io
import json
import os
import socket
import stat
import struct
import sys
import threading
import time

import pytest

from part2 import backends, cli, frames, worker

STOP = ["track", "--stop-the-test-worker"]
TURN = {"keepalive": True}  # the first line of every reply: the worker has taken the request (AC-W17)
real_main = cli.main  # the real entry point, kept before `start_worker` puts its stand-in on cli.main


def _serve_once(path, main):
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(path))
    srv.listen(1)

    def run():
        conn, _ = srv.accept()
        with conn, conn.makefile("rw", encoding="utf-8") as f:
            worker.handle(f, main)
        srv.close()

    t = threading.Thread(target=run)
    t.start()
    return t


def _request(argv=("run",), cwd=None, env=None) -> str:
    return json.dumps({"argv": list(argv), "cwd": cwd or os.getcwd(), "env": env or {}}) + "\n"


def _raw(path, line: str) -> list[dict]:
    """Send one raw request line, read the replies to the end of the connection."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(str(path))
        s.sendall(line.encode())
        with s.makefile("r", encoding="utf-8") as f:
            return [json.loads(x) for x in f]


def _exit_and_stderr(msgs) -> tuple[int, str]:
    return msgs[-1]["exit"], "".join(m["data"] for m in msgs if m.get("stream") == "stderr")


@pytest.fixture
def start_worker(tmp_path, monkeypatch):
    """start(main, name, preload) runs the real worker.serve in a thread on a temp socket (`main` in place of the
    CLI) and returns the socket path. Each worker is stopped at teardown through a request. By default the models
    are stubbed out (keep_warm does nothing); preload=True or False runs the real keep_warm with that preload."""
    started = []

    def start(main, name="w.sock", preload=None):
        path = tmp_path / name
        if preload is None:
            monkeypatch.setattr(worker, "keep_warm", lambda *a, **k: None)

        def fake_main(argv):
            if argv == STOP:
                raise KeyboardInterrupt
            return main(argv)

        monkeypatch.setattr(cli, "main", fake_main)
        ready, failed = threading.Event(), []

        def run():
            try:
                worker.serve(str(path), "cpu", preload=bool(preload), ready=ready.set)
            except BaseException as e:  # reported by the assert below
                failed.append(e)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        assert ready.wait(10), f"the worker did not start: {failed}"
        started.append((path, t))
        return path

    yield start
    for path, t in started:
        # a test that already stopped its worker leaves the thread finishing after it removed the socket
        if t.is_alive() and path.exists():
            _raw(path, _request(STOP))
        t.join(10)
        assert not t.is_alive()


def test_strip_worker_both_forms():
    assert worker.strip_worker(["run", "--worker", "/s", "--mode", "single"]) == (["run", "--mode", "single"], "/s")
    assert worker.strip_worker(["track", "--worker=/s", "--input", "a"]) == (["track", "--input", "a"], "/s")
    assert worker.strip_worker(["run"]) == (["run"], None)


def test_forward_streams_output_and_exit_code(tmp_path, monkeypatch):
    seen = {}

    def main(argv):
        seen["argv"], seen["cwd"], seen["env"] = argv, os.getcwd(), os.environ.get("PART2_PROGRESS")
        print("progress pose 0 3")
        print("oops", file=sys.stderr)
        return 3

    sock = tmp_path / "w.sock"
    monkeypatch.setenv("PART2_PROGRESS", "1")
    t = _serve_once(sock, main)
    out, err = io.StringIO(), io.StringIO()
    code = worker.forward(str(sock), ["run", "--mode", "single"], out, err)
    t.join()
    assert code == 3
    assert out.getvalue() == "progress pose 0 3\n" and err.getvalue() == "oops\n"
    assert seen == {"argv": ["run", "--mode", "single"], "cwd": os.getcwd(), "env": "1"}


def test_request_env_is_applied_during_the_job_and_restored_after(tmp_path, monkeypatch):
    monkeypatch.setenv("PART2_PROGRESS", "before")
    during = {}
    t = _serve_once(tmp_path / "w.sock", lambda argv: during.update(v=os.environ.get("PART2_PROGRESS")) or 0)
    msgs = _raw(tmp_path / "w.sock", _request(["track"], env={"PART2_PROGRESS": "request"}))
    t.join()
    assert msgs == [TURN, {"exit": 0}]
    assert during["v"] == "request" and os.environ["PART2_PROGRESS"] == "before"


def test_request_env_replaces_the_workers_own_part2_variables(tmp_path, monkeypatch):
    """AC-W05: the job sees the client's PART2_* environment, not the worker's; the worker's own is back after."""
    monkeypatch.setenv("PART2_ONLY_WORKER", "w")
    monkeypatch.delenv("PART2_ONLY_REQUEST", raising=False)
    during = {}

    def main(argv):
        during.update(worker=os.environ.get("PART2_ONLY_WORKER"), request=os.environ.get("PART2_ONLY_REQUEST"))
        return 0

    t = _serve_once(tmp_path / "w.sock", main)
    _raw(tmp_path / "w.sock", _request(["run"], env={"PART2_ONLY_REQUEST": "r"}))
    t.join()
    assert during == {"worker": None, "request": "r"}
    assert os.environ["PART2_ONLY_WORKER"] == "w" and "PART2_ONLY_REQUEST" not in os.environ


def test_only_part2_environment_crosses_the_socket(tmp_path, monkeypatch):
    """AC-W05: X_TEST has no PART2_ prefix, so it is absent inside main even though the request carries it."""
    monkeypatch.delenv("X_TEST", raising=False)
    during = {}
    t = _serve_once(tmp_path / "w.sock",
                    lambda argv: during.update(x=os.environ.get("X_TEST"), p=os.environ.get("PART2_A")) or 0)
    _raw(tmp_path / "w.sock", _request(["run"], env={"X_TEST": "1", "PART2_A": "1"}))
    t.join()
    assert during == {"x": None, "p": "1"}
    assert "X_TEST" not in os.environ


def test_job_runs_in_the_request_cwd_and_the_worker_cwd_is_restored(tmp_path):
    """AC-W01: relative paths in argv resolve against the client's cwd, not the worker's."""
    (tmp_path / "client").mkdir()
    during, before = {}, os.getcwd()
    t = _serve_once(tmp_path / "w.sock", lambda argv: during.update(cwd=os.getcwd()) or 0)
    _raw(tmp_path / "w.sock", _request(["run"], cwd=str(tmp_path / "client")))
    t.join()
    assert during["cwd"] == str(tmp_path / "client") and os.getcwd() == before


def test_refuses_other_commands(tmp_path):
    t = _serve_once(tmp_path / "w.sock", lambda argv: 0)
    err = io.StringIO()
    assert worker.forward(str(tmp_path / "w.sock"), ["check"], io.StringIO(), err) == 2
    t.join()
    assert "serves run and track" in err.getvalue()


@pytest.mark.parametrize("option", ["--worker", "--worker=/x", "--work", "--wor", "--wo", "--workx"])
def test_refuses_an_argv_that_still_carries_the_worker_option(tmp_path, option):
    """A client that did not strip --worker (or an abbreviation) would make the worker forward to itself."""
    called = []
    t = _serve_once(tmp_path / "w.sock", lambda argv: called.append(argv) or 0)
    code, err = _exit_and_stderr(_raw(tmp_path / "w.sock", _request(["run", option, "/x"])))
    t.join()
    assert code == 2 and "--worker" in err and called == []


def test_exception_in_job_is_exit_1_not_a_dead_worker(tmp_path):
    def main(argv):
        raise RuntimeError("boom")

    t = _serve_once(tmp_path / "w.sock", main)
    err = io.StringIO()
    assert worker.forward(str(tmp_path / "w.sock"), ["run"], io.StringIO(), err) == 1
    t.join()
    assert "boom" in err.getvalue()
    assert err.getvalue().count("\n") == 1  # one line for the client


def test_job_traceback_is_printed_on_the_workers_stderr(tmp_path, capsys):
    def main(argv):
        raise RuntimeError("kaboom")

    t = _serve_once(tmp_path / "w.sock", main)
    err = io.StringIO()
    worker.forward(str(tmp_path / "w.sock"), ["run"], io.StringIO(), err)
    t.join()
    log = capsys.readouterr().err
    assert "Traceback" in log and "RuntimeError: kaboom" in log
    assert "Traceback" not in err.getvalue()


@pytest.fixture(params=["missing", "refused", "permission denied", "parent is a file", "path too long"])
def no_worker_path(request, tmp_path):
    """A --worker path where no worker can be reached, one fixture value for each way connect() fails (AC-W03)."""
    kind = request.param
    if kind == "missing":
        yield str(tmp_path / "absent.sock")
    elif kind == "refused":  # the socket file of a worker that was killed: it exists and nobody listens
        stale = tmp_path / "stale.sock"
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(stale))
        s.close()
        assert stale.exists()
        yield str(stale)
    elif kind == "permission denied":  # a live worker's socket in a directory this user may not enter
        if os.geteuid() == 0:
            pytest.skip("root passes every permission check")
        locked = tmp_path / "locked"
        locked.mkdir()
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(locked / "w.sock"))
        srv.listen(1)
        locked.chmod(0)
        yield str(locked / "w.sock")
        locked.chmod(0o700)  # so that pytest can remove it
        srv.close()
    elif kind == "parent is a file":
        (tmp_path / "plain").write_text("not a directory")
        yield str(tmp_path / "plain" / "w.sock")
    else:  # a Unix socket path holds at most 107 bytes: connect() raises OSError "AF_UNIX path too long"
        yield "/" + "a" * 200 + "/w.sock"


def test_no_worker_returns_none(no_worker_path):
    out, err = io.StringIO(), io.StringIO()
    assert worker.forward(no_worker_path, ["run"], out, err) is None
    assert out.getvalue() == "" and err.getvalue() == ""  # the caller says "no worker", forward stays quiet


def test_keep_warm_returns_one_instance(monkeypatch):
    real = backends.get
    monkeypatch.setattr(backends, "get", real)  # restored after the test
    first = worker.keep_warm("cpu", preload=False)
    assert backends.get("cpu") is first
    assert backends.get("gpu") is not first


@pytest.mark.parametrize("preload", [True, False])
def test_with_preload_the_model_loads_once_across_two_requests(start_worker, monkeypatch, preload):
    """AC-W06: a counting stand-in for the gpu backend (its load() builds the model once and is idempotent, its
    estimate() calls load(), as part2.backends.gpu_sam3db does) behind the real keep_warm and the real serve.
    With preload the model is built before the first request and neither request builds another."""
    made, loads, models = [], [], []

    class Counting:
        name = "cpu"

        def __init__(self):
            made.append(self)
            self.model = None

        def load(self):
            if self.model is None:
                loads.append(1)
                self.model = object()
            return self.model

        def estimate(self):
            return self.load()

    monkeypatch.setattr(backends, "get", lambda name: Counting())  # restored by monkeypatch after keep_warm swaps it
    sock = start_worker(lambda argv: models.append(backends.get("cpu").estimate()) or 0, preload=preload)
    assert (len(made), len(loads)) == (1, 1 if preload else 0)  # preload: loaded at start, before any request
    for _ in range(2):
        assert worker.forward(str(sock), ["run"], io.StringIO(), io.StringIO()) == 0
    assert (len(made), len(loads)) == (1, 1)  # one instance, one model build for both requests
    assert len(models) == 2 and models[0] is models[1] is made[0].model


# ---- AC-W03: a lost connection is exit 1, never a re-run -------------------------------------------------

def _stub_server(path, reply: bytes, reset=False):
    """A server that sends `reply` and closes. It reads the request first, except when reset=True: it then leaves
    the request unread, which makes the close a reset (ConnectionResetError in the client)."""
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(path))
    srv.listen(1)

    def run():
        conn, _ = srv.accept()
        with conn:
            if reset:
                conn.recv(1, socket.MSG_PEEK)  # wait for the request without reading it
            else:
                conn.makefile("r").readline()
            conn.sendall(reply)
        srv.close()

    t = threading.Thread(target=run)
    t.start()
    return t


STREAM_LINE = b'{"stream": "stdout", "data": "half way\\n"}\n'
KEEPALIVE_LINE = b'{"keepalive": true}\n'


def test_connection_lost_after_a_stream_line_is_exit_1_and_not_none(tmp_path):
    t = _stub_server(tmp_path / "w.sock", STREAM_LINE)
    out, err = io.StringIO(), io.StringIO()
    code = worker.forward(str(tmp_path / "w.sock"), ["run"], out, err)
    t.join()
    assert code == 1  # not None: None is the caller's cue to run in-process
    assert out.getvalue() == "half way\n" and "not re-run in-process" in err.getvalue()


def test_connection_lost_is_not_rerun_in_process_by_the_cli(tmp_path, monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(frames, "ingest", lambda *a, **k: ran.append(a) or [])  # the in-process job's first step
    t = _stub_server(tmp_path / "w.sock", STREAM_LINE)
    code = cli.main(["run", "--mode", "single", "--input", "x.mp4", "--out", str(tmp_path / "o"), "--backend", "cpu",
                     "--worker", str(tmp_path / "w.sock")])
    t.join()
    assert code == 1 and ran == []
    assert "no worker at" not in capsys.readouterr().err


@pytest.mark.parametrize("reply", [b'{"stream": "stdout", "da', b'{"stream": "stdout", "data": "x"}\n{"exit"'])
def test_a_line_cut_short_is_exit_1_not_a_traceback(tmp_path, reply):
    t = _stub_server(tmp_path / "w.sock", reply)
    err = io.StringIO()
    assert worker.forward(str(tmp_path / "w.sock"), ["run"], io.StringIO(), err) == 1
    t.join()
    assert "not re-run in-process" in err.getvalue()


def test_a_reset_connection_is_exit_1_not_a_traceback(tmp_path):
    t = _stub_server(tmp_path / "w.sock", STREAM_LINE, reset=True)
    err = io.StringIO()
    assert worker.forward(str(tmp_path / "w.sock"), ["run"], io.StringIO(), err) == 1
    t.join()
    assert "not re-run in-process" in err.getvalue()


@pytest.mark.parametrize("value", ["x", None, 1.5, True, [3], {"code": 0}], ids=repr)
def test_an_exit_code_that_is_not_an_integer_is_exit_1_with_one_line(tmp_path, value):
    """AC-W13: int("x") used to raise out of the client; a bool is not an exit code either."""
    t = _stub_server(tmp_path / "w.sock", (json.dumps({"exit": value}) + "\n").encode())
    err = io.StringIO()
    assert worker.forward(str(tmp_path / "w.sock"), ["run"], io.StringIO(), err) == 1
    t.join()
    line = err.getvalue()
    assert line.startswith("part2: ") and "not an integer" in line and line.count("\n") == 1


@pytest.mark.parametrize("value", [0, 1, 2, 7])
def test_an_integer_exit_code_is_returned_as_it_is(tmp_path, value):
    t = _stub_server(tmp_path / "w.sock", (json.dumps({"exit": value}) + "\n").encode())
    err = io.StringIO()
    assert worker.forward(str(tmp_path / "w.sock"), ["run"], io.StringIO(), err) == value
    t.join()
    assert err.getvalue() == ""


BAD_MESSAGES = {
    "data an int": {"stream": "stdout", "data": 5},
    "data null": {"stream": "stderr", "data": None},
    "data a list": {"stream": "stdout", "data": ["x"]},
    "data missing": {"stream": "stdout"},
    "stream unknown": {"stream": "other", "data": "x"},
    "stream a list": {"stream": ["stdout"], "data": "x"},
    "no known kind": {"hello": 1},
    "empty object": {},
}


@pytest.mark.parametrize("msg", BAD_MESSAGES.values(), ids=BAD_MESSAGES.keys())
def test_a_stream_message_that_is_not_well_formed_is_a_lost_connection_not_a_traceback(tmp_path, msg):
    """AC-W16: `{"stream": "stdout", "data": 5}` used to raise TypeError out of the client. Text that came before it
    is shown; the message is the existing one and the job is not re-run."""
    t = _stub_server(tmp_path / "w.sock", STREAM_LINE + (json.dumps(msg) + "\n").encode() + b'{"exit": 0}\n')
    out, err = io.StringIO(), io.StringIO()
    assert worker.forward(str(tmp_path / "w.sock"), ["run"], out, err) == 1
    t.join()
    assert out.getvalue() == "half way\n" and err.getvalue() == worker.LOST + "\n"


def test_a_keepalive_message_prints_nothing_and_is_not_an_error(tmp_path):
    reply = b'{"keepalive": true}\n' + STREAM_LINE + b'{"keepalive": true}\n{"exit": 4}\n'
    t = _stub_server(tmp_path / "w.sock", reply)
    out, err = io.StringIO(), io.StringIO()
    assert worker.forward(str(tmp_path / "w.sock"), ["run"], out, err) == 4
    t.join()
    assert out.getvalue() == "half way\n" and err.getvalue() == ""


# ---- AC-W12: a silent worker ends the wait, never a re-run ---------------------------------------------

def _silent_server(path, then=b"", hold: threading.Event | None = None):
    """A server that reads the request, sends `then`, and keeps the connection open and quiet until `hold` is set."""
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(path))
    srv.listen(1)
    hold = hold or threading.Event()

    def run():
        conn, _ = srv.accept()
        with conn:
            conn.makefile("r").readline()
            if then:
                conn.sendall(then)
            hold.wait(10)
        srv.close()

    t = threading.Thread(target=run)
    t.start()
    return t, hold


def test_the_idle_timeout_is_a_few_keepalive_periods_so_it_catches_only_a_hung_worker():
    """AC-W12/AC-W14: the worker beats every KEEPALIVE_S, so a healthy job is never quiet for longer; the limit is
    at least three beats (one late beat does not cut a job off) and at most five minutes (a hung worker is noticed)."""
    assert worker.KEEPALIVE_S > 0
    assert 3 * worker.KEEPALIVE_S <= worker.CLIENT_IDLE_TIMEOUT_S <= 300


@pytest.mark.parametrize("then, shown", [(KEEPALIVE_LINE, ""), (STREAM_LINE, "half way\n")], ids=["after a keepalive", "after a stream line"])
def test_a_worker_that_goes_quiet_is_exit_1_naming_the_timeout(tmp_path, monkeypatch, then, shown):
    monkeypatch.setattr(worker, "CLIENT_IDLE_TIMEOUT_S", 0.3)
    t, hold = _silent_server(tmp_path / "w.sock", then)
    out, err = io.StringIO(), io.StringIO()
    started = time.monotonic()
    code = worker.forward(str(tmp_path / "w.sock"), ["run"], out, err)
    waited = time.monotonic() - started
    hold.set()
    t.join()
    assert code == 1 and out.getvalue() == shown  # not None: the caller must not re-run the job
    assert err.getvalue() == "part2: the worker sent nothing for 0.3 s; connection dropped, not re-run in-process\n"
    assert 0.25 < waited < 5


def test_the_limit_is_idle_time_not_total_time(tmp_path, monkeypatch):
    """Each line from the worker restarts the wait: a job that talks every 0.1 s runs past a 0.3 s limit."""
    monkeypatch.setattr(worker, "CLIENT_IDLE_TIMEOUT_S", 0.3)

    def main(argv):
        for i in range(8):
            print("progress pose", i, 8, flush=True)
            time.sleep(0.1)
        return 0

    t = _serve_once(tmp_path / "w.sock", main)
    out = io.StringIO()
    started = time.monotonic()
    assert worker.forward(str(tmp_path / "w.sock"), ["run"], out, io.StringIO()) == 0
    t.join()
    assert time.monotonic() - started > 0.6 and out.getvalue().count("progress pose") == 8


def test_a_timed_out_cli_is_not_rerun_in_process(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(worker, "CLIENT_IDLE_TIMEOUT_S", 0.2)
    ran = []
    monkeypatch.setattr(frames, "ingest", lambda *a, **k: ran.append(a) or [])  # the in-process job's first step
    t, hold = _silent_server(tmp_path / "w.sock", KEEPALIVE_LINE)  # the worker took the request, then went quiet
    code = cli.main(["run", "--mode", "single", "--input", "x.mp4", "--out", str(tmp_path / "o"), "--backend", "cpu",
                     "--worker", str(tmp_path / "w.sock")])
    hold.set()
    t.join()
    err = capsys.readouterr().err
    assert code == 1 and ran == [] and "sent nothing for 0.2 s" in err and "no worker at" not in err


# The queue wait (a request behind another job) is tested in tests/test_worker_keepalive.py.

# ---- CLI wiring -----------------------------------------------------------------------------------

def test_cli_without_a_worker_says_so_and_runs_in_process(tmp_path, capsys, no_worker_path):
    """Every way of finding no worker (AC-W03), including a path too long for a socket that used to escape main as an
    OSError, ends in the in-process job and the one stderr line."""
    code = cli.main(["run", "--mode", "single", "--input", str(tmp_path / "missing.mp4"), "--out", str(tmp_path / "o"),
                     "--backend", "cpu", "--worker", no_worker_path])
    err = capsys.readouterr().err
    assert f"no worker at {no_worker_path}" in err
    assert code == 1 and "missing.mp4" in err  # the in-process job's own exit code and message


def test_cli_with_a_worker_returns_its_exit_code(tmp_path, start_worker, capsys):
    """R1: `real_main`, not `cli.main` (which start_worker has replaced by the worker's stand-in), is the client. The
    job's exit code 7 is one the CLI never returns itself, and `served` shows the job ran in the worker without
    --worker. tests/test_worker_cli_integration.py covers the exit code 2 of a real job; this is the code of any job."""
    served = []
    sock = start_worker(lambda argv: served.append(argv) or print("served", argv[0]) or 7)
    capsys.readouterr()  # the worker's own "listening on" line
    code = real_main(["track", "--input", "x", "--out", "y", "--worker", str(sock)])
    assert code == 7 and served == [["track", "--input", "x", "--out", "y"]]
    assert capsys.readouterr().out == "served track\n"  # the worker's stdout reached this process


# ---- B1: nothing a client does ends the worker -----------------------------------------------------

def test_a_client_that_leaves_mid_job_does_not_stop_the_worker(tmp_path, start_worker, capsys):
    started, proceed = threading.Event(), threading.Event()

    def main(argv):
        if argv == ["run", "slow"]:
            started.set()
            proceed.wait(10)
            for _ in range(200):  # the client is gone: a write fails and ends the job
                print("x" * 1000)
        else:
            print("served", argv)
        return 0

    sock = start_worker(main)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as gone:
        gone.connect(str(sock))
        gone.sendall(_request(["run", "slow"]).encode())
        assert started.wait(10)
    proceed.set()  # the client has closed its end
    out = io.StringIO()
    assert worker.forward(str(sock), ["run", "next"], out, io.StringIO()) == 0
    assert out.getvalue() == "served ['run', 'next']\n"
    assert "BrokenPipeError" in capsys.readouterr().err  # logged on the worker's stderr


MALFORMED = {
    "not json": "{nope\n",
    "a number": "1\n",
    "a list": "[1]\n",
    "argv not a list": json.dumps({"argv": "run", "cwd": "/", "env": {}}) + "\n",
    "argv holds a number": json.dumps({"argv": ["run", 3], "cwd": "/", "env": {}}) + "\n",
    "cwd missing from disk": json.dumps({"argv": ["run"], "cwd": "/no/such/dir", "env": {}}) + "\n",
    "cwd relative": json.dumps({"argv": ["run"], "cwd": ".", "env": {}}) + "\n",
    "cwd not a string": json.dumps({"argv": ["run"], "cwd": 5, "env": {}}) + "\n",
    "env null": json.dumps({"argv": ["run"], "cwd": "/", "env": None}) + "\n",
    "env value not a string": json.dumps({"argv": ["run"], "cwd": "/", "env": {"PART2_A": 1}}) + "\n",
}


@pytest.mark.parametrize("line", MALFORMED.values(), ids=MALFORMED.keys())
def test_a_malformed_request_gets_exit_2_and_the_worker_serves_the_next(start_worker, line):
    called = []
    sock = start_worker(lambda argv: called.append(argv) or print("ok") or 0)
    code, err = _exit_and_stderr(_raw(sock, line))
    assert code == 2 and err.startswith("part2: ") and err.count("\n") == 1
    assert called == []
    out = io.StringIO()
    assert worker.forward(str(sock), ["run"], out, io.StringIO()) == 0
    assert out.getvalue() == "ok\n"


def test_a_probe_that_connects_and_leaves_is_ignored(start_worker, capsys):
    sock = start_worker(lambda argv: 0)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(str(sock))
    assert worker.forward(str(sock), ["run"], io.StringIO(), io.StringIO()) == 0
    assert "Traceback" not in capsys.readouterr().err


# ---- AC-W04: one request at a time ---------------------------------------------------------------

def test_the_second_job_starts_only_after_the_first_has_finished(start_worker):
    events, first_running, release = [], threading.Event(), threading.Event()

    def main(argv):
        events.append(f"start {argv[1]}")
        if argv[1] == "1":
            first_running.set()
            release.wait(10)
        events.append(f"end {argv[1]}")
        return int(argv[1])

    sock = start_worker(main)
    codes = {}

    def client(n):
        codes[n] = worker.forward(str(sock), ["run", str(n)], io.StringIO(), io.StringIO())

    t1 = threading.Thread(target=client, args=(1,))
    t1.start()
    assert first_running.wait(10)
    t2 = threading.Thread(target=client, args=(2,))
    t2.start()
    t2.join(0.5)  # the second client is connected and waiting
    assert t2.is_alive() and events == ["start 1"]
    release.set()
    t1.join(10)
    t2.join(10)
    assert events == ["start 1", "end 1", "start 2", "end 2"]
    assert codes == {1: 1, 2: 2}


# ---- R1: the socket path --------------------------------------------------------------------------

def test_serve_refuses_a_path_that_is_not_a_socket(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "keep_warm", lambda *a, **k: pytest.fail("models must not load"))
    p = tmp_path / "precious.txt"
    p.write_text("keep me")
    with pytest.raises(worker.WorkerError, match="not a socket"):
        worker.serve(str(p), "cpu")
    assert p.read_text() == "keep me"


def _path_of_length(tmp_path, n):
    """A socket path of exactly n bytes in tmp_path."""
    return tmp_path / ("a" * (n - len(f"{tmp_path}/")))


def test_the_unix_path_limit_is_what_bind_does_on_this_host(tmp_path):
    """worker.UNIX_PATH_MAX is written down as a number; bind itself says whether it is right."""
    ok, too_long = _path_of_length(tmp_path, worker.UNIX_PATH_MAX), _path_of_length(tmp_path, worker.UNIX_PATH_MAX + 1)
    for path, fits in ((ok, True), (too_long, False)):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            if fits:
                s.bind(str(path))
            else:
                with pytest.raises(OSError, match="too long"):
                    s.bind(str(path))
    assert worker.check_socket_path(ok) is True  # the socket just made is stale: the check lets a path of this size by
    with pytest.raises(worker.WorkerError, match="holds at most"):
        worker.check_socket_path(too_long)


def test_serve_refuses_a_path_too_long_for_a_unix_socket_before_loading_any_model(tmp_path, monkeypatch):
    """N5: bind would refuse it after the model load; the refusal comes first, as one line naming the path."""
    monkeypatch.setattr(worker, "keep_warm", lambda *a, **k: pytest.fail("models must not load"))
    path = _path_of_length(tmp_path, worker.UNIX_PATH_MAX + 1)
    with pytest.raises(worker.WorkerError) as e:
        worker.serve(str(path), "cpu")
    assert str(path) in str(e.value) and f"is {worker.UNIX_PATH_MAX + 1} bytes" in str(e.value)
    assert "\n" not in str(e.value)


def test_serve_refuses_a_directory_that_cannot_hold_the_socket_before_loading_any_model(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "keep_warm", lambda *a, **k: pytest.fail("models must not load"))
    (tmp_path / "plain").write_text("a file, not a directory")
    for path in (tmp_path / "missing" / "w.sock", tmp_path / "plain" / "w.sock"):
        with pytest.raises(worker.WorkerError, match="not an existing directory"):
            worker.serve(str(path), "cpu")
    if os.geteuid() != 0:  # root passes every permission check
        locked = tmp_path / "locked"
        locked.mkdir()
        locked.chmod(0o500)
        try:
            with pytest.raises(worker.WorkerError, match="no permission"):
                worker.serve(str(locked / "w.sock"), "cpu")
        finally:
            locked.chmod(0o700)


def test_serve_refuses_a_stale_socket_in_a_directory_it_cannot_write_to(tmp_path, monkeypatch):
    """Replacing a stale socket means unlinking it, which needs the directory: said before the model load too."""
    if os.geteuid() == 0:
        pytest.skip("root passes every permission check")
    monkeypatch.setattr(worker, "keep_warm", lambda *a, **k: pytest.fail("models must not load"))
    stale = tmp_path / "w.sock"
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(stale))
    s.close()
    tmp_path.chmod(0o500)
    try:
        with pytest.raises(worker.WorkerError, match="no permission"):
            worker.serve(str(stale), "cpu")
    finally:
        tmp_path.chmod(0o700)
    assert stale.exists()


def test_serve_refuses_a_symlink_to_a_socket(tmp_path, start_worker):
    sock = start_worker(lambda argv: 0)
    link = tmp_path / "link.sock"
    link.symlink_to(sock)
    with pytest.raises(worker.WorkerError, match="not a socket"):
        worker.serve(str(link), "cpu")
    assert link.is_symlink() and stat.S_ISSOCK(sock.lstat().st_mode)


def test_serve_refuses_a_live_worker_and_leaves_it_running(tmp_path, start_worker):
    sock = start_worker(lambda argv: print("still here") or 0)
    with pytest.raises(worker.WorkerError, match="already listening"):
        worker.serve(str(sock), "cpu")
    out = io.StringIO()
    assert worker.forward(str(sock), ["run"], out, io.StringIO()) == 0
    assert out.getvalue() == "still here\n"


def test_serve_replaces_a_stale_socket(tmp_path, start_worker):
    stale = tmp_path / "w.sock"
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(stale))
    s.close()  # the file stays, nobody listens: a worker that was killed
    assert stale.exists() and worker.check_socket_path(stale) is True
    sock = start_worker(lambda argv: 0)
    assert sock == stale and worker.forward(str(sock), ["run"], io.StringIO(), io.StringIO()) == 0


def test_serve_removes_its_socket_when_it_stops(tmp_path, start_worker):
    sock = start_worker(lambda argv: 0)
    assert stat.S_IMODE(sock.stat().st_mode) == 0o600
    _raw(sock, _request(STOP))
    for _ in range(100):
        if not sock.exists():
            break
        threading.Event().wait(0.05)
    assert not sock.exists()


def test_remove_own_leaves_a_socket_that_another_worker_made(tmp_path):
    p = tmp_path / "w.sock"
    first = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    first.bind(str(p))
    mine = worker._identity(p)
    p.unlink()
    second = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)  # a later worker took the path
    second.bind(str(p))
    worker.remove_own(p, mine)
    assert p.exists()
    worker.remove_own(p, worker._identity(p))
    assert not p.exists()
    first.close()
    second.close()


# ---- R5: whose socket ----------------------------------------------------------------------------

def _peer_cred(monkeypatch, uid):
    real = socket.socket.getsockopt

    def getsockopt(self, level, opt, *rest):
        if opt == getattr(socket, "SO_PEERCRED", None):
            return struct.pack("3i", 1, uid, 0)
        return real(self, level, opt, *rest)

    monkeypatch.setattr(socket.socket, "getsockopt", getsockopt)


def test_a_socket_owned_by_another_user_is_exit_1_and_nothing_is_sent(tmp_path, monkeypatch):
    called = []
    t = _serve_once(tmp_path / "w.sock", lambda argv: called.append(argv) or 0)
    _peer_cred(monkeypatch, os.getuid() + 1)
    err = io.StringIO()
    assert worker.forward(str(tmp_path / "w.sock"), ["run"], io.StringIO(), err) == 1
    t.join()
    assert "belongs to another user" in err.getvalue() and called == []


def test_a_socket_of_my_own_uid_is_used(tmp_path, monkeypatch):
    t = _serve_once(tmp_path / "w.sock", lambda argv: 4)
    _peer_cred(monkeypatch, os.getuid())
    assert worker.forward(str(tmp_path / "w.sock"), ["run"], io.StringIO(), io.StringIO()) == 4
    t.join()


def test_without_so_peercred_the_owner_check_is_skipped(tmp_path, monkeypatch):
    monkeypatch.delattr(socket, "SO_PEERCRED", raising=False)
    t = _serve_once(tmp_path / "w.sock", lambda argv: 5)
    assert worker.forward(str(tmp_path / "w.sock"), ["run"], io.StringIO(), io.StringIO()) == 5
    t.join()
