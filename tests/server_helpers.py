"""Shared helpers and fixtures of the server tests (test_server.py, test_server_run.py, test_server_pages.py).

A small synthetic repo served from tmp_path, a server on a free port with a fake capability probe, HTTP helpers, a
fake nvidia-smi and a tree snapshot. Each test module imports the fixtures it uses by name (pytest finds them in the
module), and imports `isolated_jobs` so its autouse setup applies there too.
"""
import contextlib
import http.client
import json
import socket
import tempfile
import threading
from pathlib import Path

import pytest

from part2 import jobs, runapi, server
from part2.joints import CANONICAL
from test_runapi import ALL_UP

ROOT = Path(__file__).resolve().parent.parent
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


# ---- helpers -----------------------------------------------------------------------------------------

def write_output(d: Path, ids=(0,), n=3, step=200.0, provenance=None, tracks=False):
    d.mkdir(parents=True)
    joints = {name: {"x": 0.01 * k, "y": 0.1 * k, "z": 0.0, "conf": 1.0} for k, name in enumerate(CANONICAL)}
    frames = [{"frame": f, "t_ms": f * step, "people": [{"id": i, "joints": joints} for i in ids]} for f in range(n)]
    (d / "pose3d.json").write_text(json.dumps({"frames": frames, **({"provenance": provenance} if provenance else {})}))
    eye = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    (d / "camera.json").write_text(json.dumps({"K": eye, "image_size": [1280, 720], "frames": [
        {"frame": f, "people": [{"id": i, "R": eye, "t": [0, 0, 3]} for i in ids]} for f in range(n)]}))
    if tracks:
        (d / "tracks.json").write_text(json.dumps({"frames": [
            {"frame": f, "people": [{"id": i, "bbox": [0, 0, 1, 1], "confidence": 1.0} for i in ids]} for f in range(n)]}))


def write_frames(d: Path, n=3, step=200.0, name=lambda f: f"{f:06d}.jpg"):
    d.mkdir(parents=True)
    for f in range(n):
        (d / name(f)).write_bytes(JPEG + str(f).encode())
    (d / "frames.json").write_text(json.dumps({"source": "/somewhere/clip.mp4", "frames": [
        {"frame": f, "t_ms": f * step, "file": name(f)} for f in range(n)]}))


@pytest.fixture
def repo(tmp_path):
    """A small repo root: pages, three outputs (class with matching pictures), a scored output, contracts."""
    root = tmp_path / "repo"
    web = root / "web"
    web.mkdir(parents=True)
    for name in ("index.html", "contract.html"):
        (web / name).write_text(f"<!doctype html><title>{name}</title>")
    (web / "browse.js").write_text("// browse")
    (web / "viewer.js").write_text("// viewer")
    (web / "style.css").write_text("body{}")
    (web / "icon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (web / "unlisted.html").write_text("NOT-IN-THE-TABLE")
    out = root / "fixtures" / "output"
    write_output(out / "single", n=4, step=100.0)
    write_output(out / "class", ids=(0, 1, 2), tracks=True)
    write_output(out / "scored" / "cpu-single", n=4, step=100.0, provenance={"backend": "cpu", "tracker": None})
    write_frames(root / "fixtures" / "input" / "class" / "frames")
    write_frames(root / "fixtures" / "input" / "single" / "frames", n=4, step=100.0)
    (root / "contracts" / "consumers").mkdir(parents=True)
    (root / "contracts" / "pose3d.schema.json").write_text('{"title": "pose3d"}')
    (root / "contracts" / "consumers" / "part3.json").write_text('{"title": "part3"}')
    (root / "contracts" / "notes.txt").write_text("not json")
    (root / "CONTRACT.md").write_text("# Contract\n\nText.\n")
    (root / "private.txt").write_text("PRIVATE-DATA")
    (tmp_path / "secret.txt").write_text("TOP-SECRET")
    return root


@pytest.fixture(autouse=True)
def isolated_jobs(tmp_path_factory, monkeypatch):
    """Job dirs and the GPU lock in temp dirs; no nvidia-smi (health says gpu null) unless a test fakes one."""
    monkeypatch.setenv("PART2_JOBS_DIR", str(tmp_path_factory.mktemp("jobs")))
    monkeypatch.setenv("PART2_GPU_LOCK", str(tmp_path_factory.mktemp("lock") / "gpu.lock"))
    monkeypatch.setenv("PART2_NVIDIA_SMI", str(tmp_path_factory.mktemp("nosmi") / "nvidia-smi"))
    monkeypatch.setenv("PYTHONPATH", str(ROOT))


FAST = jobs.Settings(gpu_poll_s=0.05, poll_s=0.05, kill_grace_s=2.0, gpu_wait_s=0.5)


@contextlib.contextmanager
def running(root: Path, base: str = "/", probe=None, **kw):
    """A server on a free port with its own temp job dir and a fake capability probe (all available)."""
    with tempfile.TemporaryDirectory() as jobs_dir:
        caps = runapi.Capabilities(probe=probe or (lambda: ALL_UP))
        srv = server.make_server("127.0.0.1", 0, base, root, jobs_dir=kw.pop("jobs_dir", Path(jobs_dir)),
                                 caps=caps, settings=kw.pop("settings", FAST), **kw)
        thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        try:
            yield srv.server_address[1]
        finally:
            srv.shutdown()
            srv.server_close()
            thread.join(5)


@pytest.fixture
def port(repo):
    with running(repo) as p:
        yield p


def fetch(port, path, method="GET", body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        r = conn.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
    finally:
        conn.close()


def get_json(port, path):
    status, headers, body = fetch(port, path)
    return status, json.loads(body)


def fake_smi(tmp_path: Path, monkeypatch, line: str = "20480, 32768") -> None:
    script = tmp_path / "nvidia-smi"
    script.write_text(f"#!/bin/sh\necho '{line}'\n")
    script.chmod(0o755)
    monkeypatch.setenv("PART2_NVIDIA_SMI", str(script))


def raw_exchange(port, request: bytes) -> tuple:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(request)
        data = b""
        try:
            while chunk := s.recv(4096):
                data += chunk
        except ConnectionResetError:  # the server closes with part of an oversize request unread: TCP resets after the reply
            pass
    head, _, body = data.partition(b"\r\n\r\n")
    return head.decode(), body


def snapshot(root: Path):
    return {p.relative_to(root).as_posix(): (p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*") if p.is_file()}


@pytest.fixture(scope="module")
def real_port():
    with running(ROOT) as p:
        yield p
