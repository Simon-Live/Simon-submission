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

import pytest

from part2 import backends, cli, frames, worker

STOP = ["track", "--stop-the-test-worker"]


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
    """start(main, name) runs the real worker.serve in a thread on a temp socket (models stubbed out, `main` in
    place of the CLI) and returns the socket path. Each worker is stopped at teardown through a request."""
    started = []

    def start(main, name="w.sock"):
        path = tmp_path / name
        monkeypatch.setattr(worker, "keep_warm", lambda *a, **k: None)

        def fake_main(argv):
            if argv == STOP:
                raise KeyboardInterrupt
            return main(argv)

        monkeypatch.setattr(cli, "main", fake_main)
        ready, failed = threading.Event(), []

        def run():
            try:
                worker.serve(str(path), "cpu", ready=ready.set)
            except BaseException as e:  # reported by the assert below
                failed.append(e)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        assert ready.wait(10), f"the worker did not start: {failed}"
        started.append((path, t))
        return path

    yield start
    for path, t in started:
        if t.is_alive():
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
    assert msgs == [{"exit": 0}]
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


def test_no_worker_returns_none(tmp_path):
    assert worker.forward(str(tmp_path / "absent.sock"), ["run"]) is None


def test_keep_warm_returns_one_instance(monkeypatch):
    real = backends.get
    monkeypatch.setattr(backends, "get", real)  # restored after the test
    first = worker.keep_warm("cpu", preload=False)
    assert backends.get("cpu") is first
    assert backends.get("gpu") is not first


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


# ---- CLI wiring -----------------------------------------------------------------------------------

def test_cli_without_a_worker_says_so_and_runs_in_process(tmp_path, capsys):
    code = cli.main(["run", "--mode", "single", "--input", str(tmp_path / "missing.mp4"), "--out", str(tmp_path / "o"),
                     "--backend", "cpu", "--worker", str(tmp_path / "absent.sock")])
    err = capsys.readouterr().err
    assert f"no worker at {tmp_path / 'absent.sock'}" in err
    assert code == 1 and "missing.mp4" in err  # the in-process job's own exit code and message


def test_cli_with_a_worker_returns_its_exit_code(tmp_path, start_worker):
    sock = start_worker(lambda argv: print("served", argv[0]) or 7)
    assert cli.main(["track", "--input", "x", "--out", "y", "--worker", str(sock)]) == 7


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
