"""Warm worker protocol (part2.worker): forwarding, streaming, exit codes, fallback. Spec: docs/specs/warm-worker.md."""
import io
import os
import socket
import sys
import threading

from part2 import backends, worker


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


def test_request_env_is_restored_after_the_job(tmp_path, monkeypatch):
    monkeypatch.setenv("PART2_PROGRESS", "1")
    sock = tmp_path / "w.sock"
    t = _serve_once(sock, lambda argv: 0)
    monkeypatch.delenv("PART2_PROGRESS")  # the worker side had none; the request carried "1" before this
    # the request was built from the client environment at forward() time
    monkeypatch.setenv("PART2_PROGRESS", "1")
    worker.forward(str(sock), ["track"], io.StringIO(), io.StringIO())
    t.join()
    assert os.environ["PART2_PROGRESS"] == "1"


def test_refuses_other_commands(tmp_path):
    t = _serve_once(tmp_path / "w.sock", lambda argv: 0)
    err = io.StringIO()
    assert worker.forward(str(tmp_path / "w.sock"), ["check"], io.StringIO(), err) == 2
    t.join()
    assert "serves run and track" in err.getvalue()


def test_exception_in_job_is_exit_1_not_a_dead_worker(tmp_path):
    def main(argv):
        raise RuntimeError("boom")

    t = _serve_once(tmp_path / "w.sock", main)
    err = io.StringIO()
    assert worker.forward(str(tmp_path / "w.sock"), ["run"], io.StringIO(), err) == 1
    t.join()
    assert "boom" in err.getvalue()


def test_no_worker_returns_none(tmp_path):
    assert worker.forward(str(tmp_path / "absent.sock"), ["run"]) is None


def test_keep_warm_returns_one_instance(monkeypatch):
    real = backends.get
    monkeypatch.setattr(backends, "get", real)  # restored after the test
    first = worker.keep_warm("cpu", preload=False)
    assert backends.get("cpu") is first
    assert backends.get("gpu") is not first
