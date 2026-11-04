"""Shared pytest fixtures for Simon Part 7 tests."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import threading
from typing import Iterator

import pytest

sys.path.insert(0, str(Path(__file__).parent / "part7"))  # the helpers of the server tests

from part7 import server  # noqa: E402
from support import Api, FakeChild, ffmpeg_video, make_lock  # noqa: E402
import ci_skips  # noqa: E402
from reclaim_plugin import _reap_session_processes, _reap_test_processes  # noqa: E402,F401  (TICKET-379: autouse, no test leaves a daemon)


def pytest_configure(config: pytest.Config) -> None:
    ci_skips.configure(config)
    # TICKET-349: a process-wide private lock path, so a bare monkeypatch.undo() (which also undoes the per-test setenv
    # below) falls back to this and never to the host's ~/.local/state/simon-part-2/gpu.lock
    private = Path(tempfile.mkdtemp(prefix="simon7-gpu-")) / "gpu.lock"
    os.environ["PART2_GPU_LOCK"] = str(private)
    os.environ["SIMON7_GPU_LOCK_PATH"] = str(private)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    """TICKET-244: tests that need the part checkouts, the GPU host or the staging host skip with a stated reason."""
    ci_skips.setup(item)


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    ci_skips.terminal_summary(terminalreporter)


@pytest.fixture(autouse=True)
def _part1_breaker_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """TICKET-089: the Part 1 circuit breaker writes state; tests that exercise it switch it on with a state dir."""
    monkeypatch.setenv("SIMON7_PART1_BREAKER", "off")


@pytest.fixture(autouse=True)
def _selfheal_clean() -> None:
    """TICKET-204: the self-heal record is process-wide; each test starts with none and no state folder."""
    from part7 import selfheal

    selfheal.configure(None)


@pytest.fixture(autouse=True)
def _private_gpu_lock(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never take the host's shared Part 2 GPU lock: another engagement holding it made fake-runner tests time
    out with "the GPU is busy" (2026-10-31). A test that needs a lock path of its own still sets one."""
    monkeypatch.setenv("SIMON7_GPU_LOCK_PATH", str(tmp_path_factory.mktemp("gpu") / "gpu.lock"))
    # TICKET-349: real Part 2 reads PART2_GPU_LOCK (part2.trackers.GPU_LOCK_ENV); a test that launches it, marked
    # `gpu_host` or not, flocks this temp file and never ~/.local/state/simon-part-2/gpu.lock that live staging takes use
    monkeypatch.setenv("PART2_GPU_LOCK", str(tmp_path_factory.mktemp("p2gpu") / "gpu.lock"))
    monkeypatch.setenv("SIMON7_NARRATION", "off")  # TICKET-146: no test calls the paid transcription API unless it opts in


@pytest.fixture(autouse=True)
def _no_admission_leaks_between_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """`gpu_lock._inside` counts calls past admission in this process. A thread a test left inside its body made the next
    test read `api/health` gpu as {busy: True, holder: part7} (full-suite run of 2026-11-03); each test starts at 0."""
    from part7 import gpu_lock

    monkeypatch.setattr(gpu_lock, "_inside", 0)


@pytest.fixture(autouse=True)
def _fake_free_gpu_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """TICKET-191: tests never read the host card's real free memory (a full card failed fallback tests). The reading
    is `SIMON7_TEST_FREE_MIB` (default 40000); a test of the reader itself calls `free_gpu_memory_mib.__wrapped__`."""
    import functools
    import os

    from part7 import gpu_lock

    @functools.wraps(gpu_lock.free_gpu_memory_mib)
    def fake() -> int | None:
        return int(os.environ.get("SIMON7_TEST_FREE_MIB", "40000"))

    monkeypatch.setattr(gpu_lock, "free_gpu_memory_mib", fake)


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
def _disk_guard_on_in_tests(monkeypatch):
    """The caps are off by default during testing on staging (SIMON7_DISK_GUARD); the tests exercise them on."""
    monkeypatch.setenv("SIMON7_DISK_GUARD", "on")
    monkeypatch.setenv("SIMON7_DISK_FLOOR_BYTES", "0")  # the upload guard's disk floor reads the host's free space; tests do not
