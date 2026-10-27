"""Shared fixtures. The repo root goes first on sys.path so `part6` is the real package.

There is deliberately no __init__.py in this folder: a test package named part6 would shadow it.
Tests never touch ~/.local/state/simon-part-6: every catalog is a tmp_path and servers bind
port 0.
"""
import http.client
import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if sys.path[0] != str(ROOT):
    sys.path.insert(0, str(ROOT))

from part6 import catalog, server  # noqa: E402

FIXTURES = ROOT / "fixtures" / "output" / "catalog"


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """No test can reach the default catalog root or inherit a base path."""
    monkeypatch.setenv("SIMON6_CATALOG_DIR", str(tmp_path / "env-catalog"))
    monkeypatch.delenv("SIMON6_BASE_PATH", raising=False)


@pytest.fixture
def seeded(tmp_path):
    """A catalog root seeded from the shipped fixtures."""
    root = tmp_path / "catalog"
    catalog.seed(root)
    return root


class Client:
    """A tiny HTTP client; every call opens a connection so requests never share state."""

    def __init__(self, port, prefix=""):
        self.port, self.prefix = port, prefix

    def request(self, method, path, body=None, headers=None, prefix=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            full = (self.prefix if prefix is None else prefix) + path
            conn.request(method, full, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
        finally:
            conn.close()

    def get(self, path, headers=None, **kw):
        return self.request("GET", path, headers=headers, **kw)

    def get_json(self, path, **kw):
        status, headers, body = self.get(path, **kw)
        return status, json.loads(body)

    def post(self, obj, path="/api/entries", **kw):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        return self.request("POST", path, body=body, headers={"Content-Type": "application/json"},
                            **kw)

    def post_json(self, obj, **kw):
        status, headers, body = self.post(obj, **kw)
        return status, json.loads(body)


class Running:
    def __init__(self, root, web_root, base_path=None):
        self.srv = server.make_server(root, port=0, base_path=base_path, web_root=web_root)
        self.thread = threading.Thread(target=self.srv.serve_forever,
                                       kwargs={"poll_interval": 0.005}, daemon=True)
        self.thread.start()
        self.port = self.srv.server_address[1]
        self.client = Client(self.port)

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(5)


@pytest.fixture
def start_server(tmp_path):
    """start_server(root, base_path=None, web_root=None) -> Running; stopped at teardown."""
    running = []
    web = tmp_path / "web"
    web.mkdir(exist_ok=True)
    (web / "index.html").write_text("<!doctype html><title>t</title>")

    def start(root, base_path=None, web_root=None):
        item = Running(root, web_root or web, base_path)
        running.append(item)
        return item

    yield start
    for item in running:
        item.stop()


@pytest.fixture
def app(seeded, start_server):
    """A running server over a seeded catalog."""
    return start_server(seeded)


@pytest.fixture
def post_valid():
    """post_valid(client, name=..., category=..., duration_ms=...) -> the new entry's manifest."""
    def post(client, name="Test move", category="dance", duration_ms=2000):
        status, manifest = client.post_json({"name": name, "category": category,
                                             "duration_ms": duration_ms})
        assert status == 201, manifest
        return manifest
    return post
