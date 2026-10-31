"""Warm worker: the keepalive that lets a short idle timeout coexist with a long quiet job (AC-W12, AC-W14), a queued
request whose client has left (AC-W15), and the wait for a turn behind other jobs (AC-W17). Spec:
docs/specs/warm-worker.md. Constants are patched small."""
import io
import json
import socket
import sys
import threading
import time

from test_worker import (  # noqa: F401  (start_worker is a fixture)
    TURN, _raw, _request, _serve_once, _silent_server, start_worker)

from part2 import cli, frames, worker

KEEPALIVE = TURN


# ---- AC-W14: the worker sends a keepalive while a job runs ------------------------------------------

def test_a_quiet_job_is_kept_alive_on_the_wire_and_the_exit_is_last(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "KEEPALIVE_S", 0.05)
    t = _serve_once(tmp_path / "w.sock", lambda argv: time.sleep(0.5) or 6)
    msgs = _raw(tmp_path / "w.sock", _request(["run"]))
    t.join()
    assert msgs[-1] == {"exit": 6}
    assert 4 <= msgs[:-1].count(KEEPALIVE) == len(msgs) - 1  # only keepalives came before it, about one per 0.05 s


def _beat_threads():
    return [x for x in threading.enumerate() if x.name == "part2-keepalive"]


def test_the_keepalive_thread_ends_with_the_job(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "KEEPALIVE_S", 0.05)
    t = _serve_once(tmp_path / "w.sock", lambda argv: time.sleep(0.2) or 0)
    _raw(tmp_path / "w.sock", _request(["run"]))
    t.join()
    assert _beat_threads() == []


def test_the_keepalive_thread_ends_quietly_when_the_client_has_left(start_worker, monkeypatch, capsys):
    """A failed beat ends the thread; it prints no traceback of its own (threading's hook would: "Exception in
    thread"), and the worker serves the next request."""
    monkeypatch.setattr(worker, "KEEPALIVE_S", 0.02)
    started, proceed = threading.Event(), threading.Event()

    def main(argv):
        if argv == ["run", "slow"]:
            started.set()
            proceed.wait(10)
        return 0

    sock = start_worker(main)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(str(sock))
        s.sendall(_request(["run", "slow"]).encode())
        assert started.wait(10)
    time.sleep(0.2)  # several beats go to a closed peer
    proceed.set()
    assert worker.forward(str(sock), ["run", "next"], io.StringIO(), io.StringIO()) == 0
    assert "Exception in thread" not in capsys.readouterr().err and _beat_threads() == []


class _SlowFile:
    """The reply file of one connection, with a write that lingers: a second writer that gets in between a write and
    its flush is an interleaving. `overlaps` counts them."""

    def __init__(self, request: str):
        self.request, self.lines, self.open_write, self.overlaps = request, [], False, 0

    def readline(self):
        return self.request

    def write(self, text):
        if self.open_write:
            self.overlaps += 1
        self.open_write = True
        time.sleep(0.002)
        self.lines.append(text)

    def flush(self):
        self.open_write = False


def test_keepalives_and_job_output_never_interleave_on_the_socket(monkeypatch):
    """AC-W14: the beat and the stream writer share one lock, so a line is written whole before the next begins."""
    monkeypatch.setattr(worker, "KEEPALIVE_S", 0.001)

    def main(argv):
        for i in range(30):
            print("line", i)
        return 0

    f = _SlowFile(_request(["run"]))
    worker.handle(f, main)
    assert f.overlaps == 0
    msgs = [json.loads(x) for x in f.lines]  # every write is one whole JSON line
    assert msgs[-1] == {"exit": 0}
    assert "".join(m["data"] for m in msgs if "stream" in m) == "".join(f"line {i}\n" for i in range(30))
    assert KEEPALIVE in msgs  # the beat did run, so the test was about something


# ---- AC-W12: what the client does with the keepalive ----------------------------------------------------

def test_a_long_silent_job_keeps_the_client_waiting_and_ends_with_its_real_exit_code(tmp_path, monkeypatch):
    """The job prints nothing for 1.2 s, four times the client's 0.3 s limit; the keepalive keeps the wait alive."""
    monkeypatch.setattr(worker, "KEEPALIVE_S", 0.05)
    monkeypatch.setattr(worker, "CLIENT_IDLE_TIMEOUT_S", 0.3)
    t = _serve_once(tmp_path / "w.sock", lambda argv: time.sleep(1.2) or 5)
    out, err = io.StringIO(), io.StringIO()
    started = time.monotonic()
    assert worker.forward(str(tmp_path / "w.sock"), ["run"], out, err) == 5
    t.join()
    assert time.monotonic() - started > 1.1
    assert out.getvalue() == "" and err.getvalue() == ""  # the keepalive prints nothing


def test_a_worker_that_stops_sending_times_the_client_out_with_exit_1_and_no_rerun(tmp_path, monkeypatch, capsys):
    """Keepalives for a while, then silence: the wait runs out 0.3 s after the last one, and the CLI does not run the
    job itself (`frames.ingest` is its first step)."""
    monkeypatch.setattr(worker, "CLIENT_IDLE_TIMEOUT_S", 0.3)
    ran = []
    monkeypatch.setattr(frames, "ingest", lambda *a, **k: ran.append(a) or [])
    beats = (json.dumps(KEEPALIVE) + "\n").encode() * 3
    t, hold = _silent_server(tmp_path / "w.sock", beats)
    started = time.monotonic()
    code = cli.main(["run", "--mode", "single", "--input", "x.mp4", "--out", str(tmp_path / "o"), "--backend", "cpu",
                     "--worker", str(tmp_path / "w.sock")])
    waited = time.monotonic() - started
    hold.set()
    t.join()
    err = capsys.readouterr().err
    assert code == 1 and ran == [] and "sent nothing for 0.3 s" in err and "no worker at" not in err
    assert 0.25 < waited < 5


def test_beats_that_come_slower_than_the_limit_do_not_save_the_client(start_worker, monkeypatch):
    """The limit counts from the last line: a keepalive every 0.4 s against a 0.15 s limit is no activity."""
    monkeypatch.setattr(worker, "KEEPALIVE_S", 0.4)
    monkeypatch.setattr(worker, "CLIENT_IDLE_TIMEOUT_S", 0.15)
    sock = start_worker(lambda argv: time.sleep(0.6) or 0)
    err = io.StringIO()
    assert worker.forward(str(sock), ["run"], io.StringIO(), err) == 1
    assert "sent nothing for 0.15 s" in err.getvalue()


# ---- AC-W15: a request whose client has left is not run -----------------------------------------------

def _wait_for_log(capsys, text, seconds=10) -> str:
    seen, deadline = "", time.monotonic() + seconds
    while text not in seen and time.monotonic() < deadline:
        time.sleep(0.02)
        seen += capsys.readouterr().err
    return seen


def test_a_queued_client_that_leaves_before_its_turn_gets_no_job_and_the_next_is_served(start_worker, capsys):
    started, proceed, ran = threading.Event(), threading.Event(), []

    def main(argv):
        ran.append(argv)
        if argv == ["run", "slow"]:
            started.set()
            proceed.wait(10)
        sys.stdout.write(f"served {argv[1]}\n")
        return 0

    sock = start_worker(main)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as first:  # the job ahead
        first.connect(str(sock))
        first.sendall(_request(["run", "slow"]).encode())
        assert started.wait(10)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as gone:  # asks, queues, leaves
            gone.connect(str(sock))
            gone.sendall(_request(["run", "gone"]).encode())
        proceed.set()
        with first.makefile("r", encoding="utf-8") as f:  # to its end: this client does not leave early
            assert [json.loads(x) for x in f] == [TURN, {"stream": "stdout", "data": "served slow\n"}, {"exit": 0}]
    out = io.StringIO()
    assert worker.forward(str(sock), ["run", "next"], out, io.StringIO()) == 0
    assert out.getvalue() == "served next\n"
    assert ran == [["run", "slow"], ["run", "next"]]  # the spy never saw "gone"
    log = _wait_for_log(capsys, "client left before its turn")
    assert "client left before its turn; request not run" in log and "Traceback" not in log


def test_a_client_that_only_closed_its_sending_side_is_still_served(start_worker):
    """shutdown(SHUT_WR) after the request is the usual way for a client to say "that was all"; it still reads."""
    sock = start_worker(lambda argv: sys.stdout.write("hello\n") and 3)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(str(sock))
        s.sendall(_request(["run"]).encode())
        s.shutdown(socket.SHUT_WR)
        with s.makefile("r", encoding="utf-8") as f:
            assert [json.loads(x) for x in f] == [TURN, {"stream": "stdout", "data": "hello\n"}, {"exit": 3}]


def test_a_client_that_leaves_without_a_request_is_ignored_in_silence(start_worker, capsys):
    sock = start_worker(lambda argv: 0)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(str(sock))
    assert worker.forward(str(sock), ["run"], io.StringIO(), io.StringIO()) == 0
    assert "left before its turn" not in capsys.readouterr().err


def test_a_client_that_is_there_is_not_mistaken_for_one_that_left():
    a, b = socket.socketpair()
    try:
        assert worker._client_gone(a) is False
        b.close()
        assert worker._client_gone(a) is True
    finally:
        a.close()


# ---- AC-W17: the wait for a turn behind other jobs ---------------------------------------------------------

def _worker_with_a_slow_job(start_worker):
    """(socket, started, proceed, ran): a worker whose job `run slow` holds until `proceed`, and whose job `run
    queued` ends with exit code 9; `ran` lists the argv it served."""
    started, proceed, ran = threading.Event(), threading.Event(), []

    def main(argv):
        ran.append(argv)
        if argv == ["run", "slow"]:
            started.set()
            proceed.wait(10)
        sys.stdout.write(f"served {argv[1]}\n")
        return 9 if argv[1] == "queued" else 0

    return start_worker(main), started, proceed, ran


def _ask_and_listen(sock, argv) -> socket.socket:
    """A client that sends its request and then only listens; the caller closes it."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(str(sock))
    s.sendall(_request(argv).encode())
    return s


def test_a_client_queued_behind_a_job_longer_than_the_idle_limit_is_served_with_its_real_exit_code(
        start_worker, monkeypatch):
    monkeypatch.setattr(worker, "CLIENT_IDLE_TIMEOUT_S", 0.3)
    monkeypatch.setattr(worker, "CLIENT_QUEUE_WAIT_S", 20)
    sock, started, proceed, ran = _worker_with_a_slow_job(start_worker)
    out, err, result = io.StringIO(), io.StringIO(), []
    with _ask_and_listen(sock, ["run", "slow"]) as first:
        assert started.wait(10)
        client = threading.Thread(target=lambda: result.append(worker.forward(str(sock), ["run", "queued"], out, err)))
        client.start()
        time.sleep(1.0)  # more than three idle limits, with the job ahead still running
        assert client.is_alive() and result == []
        proceed.set()
        client.join(10)
        assert not client.is_alive()
    assert result == [9] and out.getvalue() == "served queued\n" and err.getvalue() == ""
    assert ran == [["run", "slow"], ["run", "queued"]]


def test_a_client_whose_queue_wait_runs_out_exits_1_and_its_request_is_skipped_in_its_turn(
        start_worker, monkeypatch, capsys):
    """The queued client reports through its own `err`: the job ahead runs with sys.stderr redirected in this very
    process, so a message printed on sys.stderr would go to that job's client."""
    monkeypatch.setattr(worker, "CLIENT_QUEUE_WAIT_S", 0.3)
    monkeypatch.setattr(worker, "CLIENT_IDLE_TIMEOUT_S", 10)
    sock, started, proceed, ran = _worker_with_a_slow_job(start_worker)
    out, err = io.StringIO(), io.StringIO()
    with _ask_and_listen(sock, ["run", "slow"]) as first:
        assert started.wait(10)
        began = time.monotonic()
        code = worker.forward(str(sock), ["run", "queued"], out, err)
        waited = time.monotonic() - began
        proceed.set()
        with first.makefile("r", encoding="utf-8") as f:  # the job ahead ends as it should
            assert [json.loads(x) for x in f][-1] == {"exit": 0}
    assert code == 1 and out.getvalue() == "" and 0.25 < waited < 5  # 1, not None: the caller must not re-run it
    assert err.getvalue() == "part2: waited 0.3 s for a turn at the worker; connection dropped, not re-run in-process\n"
    monkeypatch.setattr(worker, "CLIENT_QUEUE_WAIT_S", 10)
    assert worker.forward(str(sock), ["run", "after"], io.StringIO(), io.StringIO()) == 0
    assert ran == [["run", "slow"], ["run", "after"]]  # the request that gave up was skipped in its turn
    assert "client left before its turn" in _wait_for_log(capsys, "client left before its turn")


def test_a_cli_whose_wait_for_a_turn_runs_out_is_exit_1_and_not_rerun_in_process(tmp_path, monkeypatch, capsys):
    """A worker that never takes the request: the wait ends at the queue limit, not at the shorter idle limit."""
    monkeypatch.setattr(worker, "CLIENT_QUEUE_WAIT_S", 0.5)
    monkeypatch.setattr(worker, "CLIENT_IDLE_TIMEOUT_S", 0.1)
    ran = []
    monkeypatch.setattr(frames, "ingest", lambda *a, **k: ran.append(a) or [])  # the in-process job's first step
    t, hold = _silent_server(tmp_path / "w.sock")
    began = time.monotonic()
    code = cli.main(["run", "--mode", "single", "--input", "x.mp4", "--out", str(tmp_path / "o"), "--backend", "cpu",
                     "--worker", str(tmp_path / "w.sock")])
    waited = time.monotonic() - began
    hold.set()
    t.join()
    err = capsys.readouterr().err
    assert code == 1 and ran == [] and 0.4 < waited < 5
    assert "waited 0.5 s for a turn at the worker; connection dropped, not re-run in-process" in err
    assert "no worker at" not in err and "sent nothing" not in err


def test_the_first_line_after_taking_a_connection_arrives_while_the_job_has_not_finished(start_worker):
    """The job waits for the client to have read its first line, so that line cannot be the timer's beat (30 s) or the
    exit: it is sent when the worker takes the request."""
    got_first = threading.Event()
    sock = start_worker(lambda argv: 0 if got_first.wait(10) else 1)
    with _ask_and_listen(sock, ["run"]) as s, s.makefile("r", encoding="utf-8") as f:
        first = json.loads(f.readline())
        got_first.set()
        rest = [json.loads(x) for x in f]
    assert first == TURN and rest == [{"exit": 0}]


class _OrderFile:
    """The reply file of one connection that records what is written; `fail` makes every write raise."""

    def __init__(self, events, fail=False):
        self.events, self.fail = events, fail

    def readline(self):
        return _request(["run"])

    def write(self, text):
        if self.fail:
            raise BrokenPipeError(32, "Broken pipe")
        self.events.append(json.loads(text))

    def flush(self):
        pass


def test_the_turn_is_announced_before_the_request_runs():
    events = []
    worker.handle(_OrderFile(events), lambda argv: events.append("job") or 0)
    assert events == [TURN, "job", {"exit": 0}]


def test_a_client_that_leaves_before_the_turn_is_announced_gets_no_job_and_no_traceback(capsys):
    ran = []
    worker.handle(_OrderFile([], fail=True), lambda argv: ran.append(argv) or 0)
    err = capsys.readouterr().err
    assert ran == [] and "client left before its turn; request not run" in err and "Traceback" not in err


def test_the_queue_wait_covers_a_full_listen_queue_of_typical_jobs_and_is_still_bounded():
    """The listen queue is 8 deep; a typical job is about 150 s (141.5 s measured); a wait beyond four hours would
    leave a client waiting on a worker that never takes its request."""
    assert 8 * 150 <= worker.CLIENT_QUEUE_WAIT_S <= 4 * 3600
    assert worker.CLIENT_QUEUE_WAIT_S > worker.CLIENT_IDLE_TIMEOUT_S
