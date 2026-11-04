"""B5: a Part 1 run of a build that passes no `.env` lock (an older release) still keeps its key. It runs with its cwd in the
copy, and the sweeps, the start clear and the tree reclaim leave a directory a live process works in
(docs/specs/parts-harness.md AC-H5c). The child is a real process with no lock; no network."""

from __future__ import annotations

import errno
import os
from pathlib import Path
import subprocess
from typing import Iterator

import pytest

from part7 import keys
from part7.parts import p1_keyframes


@pytest.fixture()
def run_in(tmp_path: Path) -> Iterator[list[subprocess.Popen[bytes]]]:
    """Real children with a working directory of the test's choice, in a session of their own as Part 1 is."""
    started: list[subprocess.Popen[bytes]] = []
    yield started
    for proc in started:
        proc.kill()
        proc.wait(timeout=30)


def _child(started: list[subprocess.Popen[bytes]], cwd: Path) -> subprocess.Popen[bytes]:
    proc = subprocess.Popen(["sleep", "120"], cwd=cwd, start_new_session=True)
    started.append(proc)
    return proc


def _key_file(copy: Path) -> Path:
    copy.mkdir(parents=True, exist_ok=True)
    env = copy / ".env"
    env.write_text("MODEL_API_KEY=fake-not-a-key-000000\n", encoding="utf-8")
    env.chmod(0o600)
    return env


def test_the_sweep_keeps_the_key_under_a_run_with_no_lock_until_it_exits(tmp_path: Path, run_in: list[subprocess.Popen[bytes]]) -> None:
    copy = tmp_path / "clone"
    env = _key_file(copy)
    child = _child(run_in, copy)
    keys.drop_part1_env(copy)
    assert env.is_file(), "the sweep removed the key under a live run that holds no lock"
    child.kill()
    child.wait(timeout=30)
    keys.drop_part1_env(copy)
    assert not env.exists()


def test_a_run_below_the_directory_keeps_it_too(tmp_path: Path, run_in: list[subprocess.Popen[bytes]]) -> None:
    """Part 1 and its tools may work in `out/` or `inbox/` of the copy."""
    copy = tmp_path / "clone"
    env = _key_file(copy)
    (copy / "out").mkdir()
    _child(run_in, copy / "out")
    keys.drop_part1_env(copy)
    assert env.is_file()


def test_prod_sweep_keeps_the_key_under_a_run_with_no_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                         run_in: list[subprocess.Popen[bytes]]) -> None:
    """The prod path: `p1_keyframes.sweep` over every copy under `part1/`, old pins included."""
    monkeypatch.setenv("FIRM_ENV", "prod")
    copy = tmp_path / "part1" / "abcdef012345"
    env = _key_file(copy)
    child = _child(run_in, copy)
    p1_keyframes.sweep(tmp_path)
    assert env.is_file(), "prod's sweep removed the key under a live run that holds no lock"
    child.kill()
    child.wait(timeout=30)
    p1_keyframes.sweep(tmp_path)
    assert not env.exists()


def test_a_proc_that_cannot_be_listed_keeps_the_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                    caplog: pytest.LogCaptureFixture) -> None:
    copy = tmp_path / "clone"
    env = _key_file(copy)
    real = os.listdir

    def listdir(path: object = ".") -> list[str]:
        if path == "/proc":
            raise PermissionError(errno.EACCES, "no /proc")
        return real(path)  # type: ignore[arg-type]

    monkeypatch.setattr(keys.os, "listdir", listdir)
    with caplog.at_level("WARNING", logger="part7"):
        keys.drop_part1_env(copy)
    assert env.is_file() and "/proc cannot be read" in caplog.text


def test_a_kept_key_is_logged_with_the_process(tmp_path: Path, run_in: list[subprocess.Popen[bytes]], caplog: pytest.LogCaptureFixture) -> None:
    copy = tmp_path / "clone"
    _key_file(copy)
    child = _child(run_in, copy)
    with caplog.at_level("WARNING", logger="part7"):
        keys.drop_part1_env(copy)
    assert f"process {child.pid} works inside it" in caplog.text


def test_a_process_elsewhere_does_not_keep_the_key(tmp_path: Path, run_in: list[subprocess.Popen[bytes]]) -> None:
    """The negative: a live process in a sibling directory, or one named like it, holds nothing."""
    copy = tmp_path / "clone"
    env = _key_file(copy)
    (tmp_path / "clone2").mkdir()
    _child(run_in, tmp_path / "clone2")
    keys.drop_part1_env(copy)
    assert not env.exists()


def test_a_call_that_finds_the_tree_gone_is_unavailable_not_a_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R26: a reclaim removed the tree while this call waited on the lock; Part 1 reads as unavailable, so the chain falls back."""
    kdir = tmp_path / "keys"
    kdir.mkdir()
    (kdir / "MODEL_API_KEY").write_text("fake-not-a-key-000000\n", encoding="utf-8")

    def gone(*a: object, **k: object) -> None:
        raise FileNotFoundError(errno.ENOENT, "tree removed")

    monkeypatch.setattr(keys, "_write_part1_env", gone)
    with keys.part1_dotenv(tmp_path / "clone", keys_dir=kdir) as active:
        assert active is False


def test_this_processs_own_cwd_in_the_copy_keeps_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A server whose cwd happens to be the copy is not a Part 1 run: the sweep may still clear."""
    copy = tmp_path / "clone"
    env = _key_file(copy)
    monkeypatch.chdir(copy)
    assert keys.process_inside(copy) is None
    keys.drop_part1_env(copy)
    assert not env.exists()


def test_a_listing_without_this_process_is_unreadable_not_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R5: an empty or hidden /proc lists no one, not even us; that must keep the key, not read as "no run here"."""
    copy = tmp_path / "clone"
    env = _key_file(copy)
    monkeypatch.setattr(keys.os, "listdir", lambda path=".": [])
    assert keys.process_inside(copy) == keys.PROC_UNREADABLE
    keys.drop_part1_env(copy)
    assert env.is_file()
