"""Shared pytest fixtures for Simon Part 7 tests."""

from __future__ import annotations

from pathlib import Path
import sys
import threading
from typing import Iterator

import pytest

sys.path.insert(0, str(Path(__file__).parent / "part7"))  # the helpers of the server tests

from part7 import server  # noqa: E402
from support import Api, FakeChild, ffmpeg_video, make_lock  # noqa: E402


@pytest.fixture(autouse=True)
def _part1_breaker_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """TICKET-089: the Part 1 circuit breaker writes state; tests that exercise it switch it on with a state dir."""
    monkeypatch.setenv("SIMON7_PART1_BREAKER", "off")


@pytest.fixture()
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide an isolated temporary state root for tests."""
    s = tmp_path / "state"
    s.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SIMON7_STATE_DIR", str(s))
    return s


@pytest.fixture(scope="session")
def tiny_mp4(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return ffmpeg_video(tmp_path_factory.mktemp("vid") / "tiny.mp4", 2)


@pytest.fixture(scope="session")
def long_mp4(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return ffmpeg_video(tmp_path_factory.mktemp("vid") / "long.mp4", 61)


@pytest.fixture()
def api(tmp_path: Path, state_dir: Path) -> Iterator[Api]:
    child = FakeChild(tmp_path / "catalog")
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<h1>Simon</h1>", encoding="utf-8")
    (web / "app.js").write_text("export {}", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    app = server.build_app(state_dir, "/simon-part-7/", child=child, lock=make_lock(), web_dir=web, phrasing="template")
    http = server.make_server(app)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    yield Api(app, http)
    http.shutdown()
    http.server_close()
    app.queue.close()
    child.close()


@pytest.fixture(autouse=True)
def _limits_on_in_tests(monkeypatch):
    """The caps are off by default during testing on staging (SIMON7_LIMITS); the tests exercise them on."""
    monkeypatch.setenv("SIMON7_LIMITS", "on")
