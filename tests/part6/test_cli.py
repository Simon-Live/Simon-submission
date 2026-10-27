"""python3 -m part6: serve, validate and reset commands."""
import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from part6 import __main__ as cli
from part6 import catalog

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "fixtures" / "output" / "catalog"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_serve_defaults_follow_the_spec():
    args = cli._parser().parse_args(["serve"])
    assert (args.host, args.port, args.catalog) == ("127.0.0.1", 8726, None)
    args = cli._parser().parse_args(["serve", "--host", "0.0.0.0", "--port", "9", "--catalog", "x"])
    assert (args.host, args.port, args.catalog) == ("0.0.0.0", 9, "x")


def test_a_command_is_required():
    with pytest.raises(SystemExit):
        cli._parser().parse_args([])


def test_validate_prints_failures_on_stderr_and_exits_one(tmp_path, capsys):
    shutil.copytree(CATALOG / "squat", tmp_path / "squat")
    (tmp_path / "squat" / "animation.json").write_text("{}")
    assert cli.main(["validate", str(tmp_path)]) == 1
    out = capsys.readouterr()
    assert "squat: animation.json:" in out.err
    assert json.loads(out.out) == {"entries": 1, "invalid": 1}


def test_validate_exits_one_for_a_missing_or_empty_folder(tmp_path, capsys):
    assert cli.main(["validate", str(tmp_path / "nope")]) == 1
    assert "is not a folder" in capsys.readouterr().err
    assert cli.main(["validate", str(tmp_path)]) == 1
    assert "no entry folder" in capsys.readouterr().err


def test_reset_prints_counts_on_stdout_and_exits_zero(tmp_path, capsys):
    root = tmp_path / "cat"
    assert cli.main(["reset", "--catalog", str(root)]) == 0
    assert json.loads(capsys.readouterr().out) == {"removed": 0, "restored": 6}
    assert len(list(root.iterdir())) == 6


def test_reset_uses_the_environment_root_without_the_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMON6_CATALOG_DIR", str(tmp_path / "from-env"))
    assert cli.main(["reset"]) == 0
    assert len(list((tmp_path / "from-env").iterdir())) == 6
    capsys.readouterr()


def test_root_resolution_order(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMON6_CATALOG_DIR", str(tmp_path / "env"))
    assert catalog.resolve_root(str(tmp_path / "flag")) == tmp_path / "flag"
    assert catalog.resolve_root() == tmp_path / "env"
    monkeypatch.delenv("SIMON6_CATALOG_DIR")
    default = catalog.resolve_root()
    assert str(default).endswith(".local/state/simon-part-6/catalog")
    assert default.is_absolute() and "~" not in str(default)


def start(tmp_path, catalog_dir):
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "part6", "serve", "--host", "127.0.0.1", "--port", str(port),
         "--catalog", str(catalog_dir)], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as r:
                return proc, port, json.load(r)
        except OSError:
            time.sleep(0.1)
    proc.kill()
    raise AssertionError("server did not start")


def tree(root):
    return {p.relative_to(root): p.read_bytes() for p in Path(root).rglob("*") if p.is_file()}


def test_serve_seeds_answers_and_exits_promptly_on_sigterm(tmp_path):
    before = tree(CATALOG)
    proc, port, health = start(tmp_path, tmp_path / "fresh")
    try:
        assert health == {"ok": True, "entries": 6}
        # an idle keep-alive connection must not delay the exit
        idle = socket.create_connection(("127.0.0.1", port))
        idle.sendall(b"GET /api/health HTTP/1.1\r\nHost: x\r\n\r\n")
        idle.recv(4096)
        began = time.monotonic()
        proc.terminate()
        code = proc.wait(timeout=5)
        elapsed = time.monotonic() - began
        idle.close()
    finally:
        if proc.poll() is None:
            proc.kill()
    out, err = proc.stdout.read(), proc.stderr.read().decode()
    assert code == 0 and elapsed < 2
    assert out == b"" and "GET /api/health" in err and "seeded 6 entries" in err
    assert tree(CATALOG) == before


def test_a_server_restart_keeps_the_entries(tmp_path):
    proc, port, _ = start(tmp_path, tmp_path / "keep")
    try:
        body = json.dumps({"name": "Keep me", "category": "dance", "duration_ms": 1500}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/entries", data=body, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 201
    finally:
        proc.terminate()
        proc.wait(5)
    proc, port, health = start(tmp_path, tmp_path / "keep")
    try:
        assert health["entries"] == 7
    finally:
        proc.terminate()
        proc.wait(5)


# the shipped fixture catalog is never a writable root (review R5)

def fixture_roots(tmp_path):
    link = tmp_path / "link-to-fixtures"
    link.symlink_to(CATALOG, target_is_directory=True)
    return [str(CATALOG), str(CATALOG / "squat"), str(CATALOG / "no-such-entry"),
            str(CATALOG / ".." / "catalog"), str(link), str(link / "squat")]


def test_serve_refuses_a_root_in_the_shipped_fixtures(tmp_path, capsys):
    before = tree(CATALOG)
    for root in fixture_roots(tmp_path):
        assert cli.main(["serve", "--port", "0", "--catalog", root]) == 2
        err = capsys.readouterr().err
        assert "shipped fixture catalog" in err and "--catalog" in err
    assert tree(CATALOG) == before and not (CATALOG / "no-such-entry").exists()


def test_reset_refuses_a_root_in_the_shipped_fixtures(tmp_path, capsys):
    before = tree(CATALOG)
    for root in fixture_roots(tmp_path):
        assert cli.main(["reset", "--catalog", root]) == 2
        captured = capsys.readouterr()
        assert captured.out == "" and "shipped fixture catalog" in captured.err
    assert tree(CATALOG) == before


def test_the_environment_root_is_checked_too(monkeypatch, capsys):
    monkeypatch.setenv("SIMON6_CATALOG_DIR", str(CATALOG))
    assert cli.main(["reset"]) == 2 and "shipped fixture catalog" in capsys.readouterr().err


def test_serve_exits_non_zero_from_a_real_process(tmp_path):
    done = subprocess.run([sys.executable, "-m", "part6", "serve", "--port", "0",
                           "--catalog", str(CATALOG)], cwd=ROOT, capture_output=True, timeout=20)
    assert done.returncode == 2 and b"shipped fixture catalog" in done.stderr


def test_other_roots_and_validate_are_still_allowed(tmp_path, capsys):
    assert cli.main(["reset", "--catalog", str(tmp_path / "ok")]) == 0
    assert cli.main(["validate", str(CATALOG)]) == 0
    capsys.readouterr()
