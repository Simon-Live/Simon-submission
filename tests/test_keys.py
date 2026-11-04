"""Tests for `part7.keys` (TICKET-009, AC-H4, AC-H5, AC-008)."""

from __future__ import annotations

from pathlib import Path
import stat
import subprocess
import sys
import threading
import time

import pytest

from part7 import keys


def test_read_has_and_redact_keys(tmp_path: Path) -> None:
    """AC-H4: Any key value read through `keys.py` or present in `keys_dir` is redacted."""
    kdir = tmp_path / "keys"
    kdir.mkdir()
    secret = "fake-meta-secret-99887766"
    (kdir / "MODEL_API_KEY").write_text(secret + "\n", encoding="utf-8")
    (kdir / "SHORT").write_text("abc\n", encoding="utf-8")

    assert keys.has_key("MODEL_API_KEY", keys_dir=kdir) is True
    assert keys.has_key("HF_TOKEN", keys_dir=kdir) is False
    assert keys.read_key("MODEL_API_KEY", keys_dir=kdir) == secret

    raw_log = f"Authorization: Bearer {secret}\nDone."
    redacted = keys.redact(raw_log, keys_dir=kdir)
    assert secret not in redacted
    assert "Authorization: Bearer <redacted>" in redacted
    assert "abc" in keys.redact("abc", keys_dir=kdir)


def test_part1_dotenv_lifecycle_and_stale_removal(tmp_path: Path) -> None:
    """AC-H5: Part 1 `.env` is absent before and after, mode 0600 during, and removes stale `.env` first."""
    clone_dir = tmp_path / "part1_clone"
    clone_dir.mkdir()
    env_path = clone_dir / ".env"
    env_path.write_text("MODEL_API_KEY=stale-leftover-key\n", encoding="utf-8")

    kdir = tmp_path / "keys"
    kdir.mkdir()

    # When MODEL_API_KEY is missing, stale .env is still removed and yields False
    with keys.part1_dotenv(clone_dir, keys_dir=kdir) as active:
        assert active is False
        assert not env_path.exists()
    assert not env_path.exists()

    # Now provide MODEL_API_KEY and verify mode 0600 during stub command execution
    secret = "meta-live-test-key-1234567890"
    (kdir / "MODEL_API_KEY").write_text(secret, encoding="utf-8")
    env_path.write_text("MODEL_API_KEY=stale-again\n", encoding="utf-8")

    with keys.part1_dotenv(clone_dir, keys_dir=kdir) as active:
        assert active is True
        assert env_path.is_file()
        mode = stat.S_IMODE(env_path.stat().st_mode)
        assert mode == 0o600
        # Verify via a stub child process that .env is readable with mode 0600 during the call
        res = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os, pathlib, stat; p = pathlib.Path('.env'); "
                "print(oct(stat.S_IMODE(p.stat().st_mode)), p.exists())",
            ],
            cwd=clone_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "0o600 True" in res.stdout

    assert not env_path.exists()


def test_part1_dotenv_removes_env_on_exception(tmp_path: Path) -> None:
    """AC-H5: `.env` is removed even when the body inside `part1_dotenv` raises."""
    clone_dir = tmp_path / "part1_clone"
    clone_dir.mkdir()
    kdir = tmp_path / "keys"
    kdir.mkdir()
    (kdir / "MODEL_API_KEY").write_text("secret-key-for-exception-test", encoding="utf-8")

    with pytest.raises(RuntimeError, match="boom"):
        with keys.part1_dotenv(clone_dir, keys_dir=kdir) as active:
            assert active is True
            assert (clone_dir / ".env").exists()
            raise RuntimeError("boom")

    assert not (clone_dir / ".env").exists()


FAKE_KEY = "fake-not-a-key-000000"
# A second process holding the key on `argv[1]` with keys in `argv[2]`: it says `in`, then waits for stdin or a kill.
HOLDER = """import sys
from part7 import keys
with keys.part1_dotenv(sys.argv[1], keys_dir=sys.argv[2]) as active:
    print("in" if active else "no key", flush=True)
    sys.stdin.readline()
"""


@pytest.fixture()
def clone_and_keys(tmp_path: Path) -> tuple[Path, Path]:
    clone_dir, kdir = tmp_path / "part1_clone", tmp_path / "keys"
    clone_dir.mkdir()
    kdir.mkdir()
    (kdir / "MODEL_API_KEY").write_text(FAKE_KEY, encoding="utf-8")
    return clone_dir, kdir


def _holder(clone_dir: Path, kdir: Path) -> subprocess.Popen[str]:
    proc = subprocess.Popen([sys.executable, "-c", HOLDER, str(clone_dir), str(kdir)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, cwd=Path(__file__).resolve().parents[1])
    assert proc.stdout is not None and proc.stdout.readline().strip() == "in"
    return proc


def test_part1_dotenv_first_holder_out_leaves_the_key_for_the_second(clone_and_keys: tuple[Path, Path]) -> None:
    """AC-H5b, TICKET-388: what Part 1's `api_key()` reads survives another run ending; the last one out removes it."""
    clone_dir, kdir = clone_and_keys
    env_path = clone_dir / ".env"
    first, second = keys.part1_dotenv(clone_dir, keys_dir=kdir), keys.part1_dotenv(clone_dir, keys_dir=kdir)
    assert first.__enter__() is True and second.__enter__() is True
    first.__exit__(None, None, None)
    assert env_path.read_text(encoding="utf-8") == f"MODEL_API_KEY={FAKE_KEY}\n"
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
    second.__exit__(None, None, None)
    assert not env_path.exists()


def test_part1_dotenv_a_holder_that_starts_keeps_the_key_of_one_already_inside(clone_and_keys: tuple[Path, Path]) -> None:
    clone_dir, kdir = clone_and_keys
    with keys.part1_dotenv(clone_dir, keys_dir=kdir):
        before = (clone_dir / ".env").read_text(encoding="utf-8")
        with keys.part1_dotenv(clone_dir, keys_dir=kdir):
            assert (clone_dir / ".env").read_text(encoding="utf-8") == before
        assert (clone_dir / ".env").read_text(encoding="utf-8") == before
    assert sorted(p.name for p in clone_dir.iterdir()) == []  # no lock file, no temp file left in Part 1's tree


def test_part1_dotenv_a_call_without_a_key_leaves_a_holder_alone(clone_and_keys: tuple[Path, Path], tmp_path: Path) -> None:
    clone_dir, kdir = clone_and_keys
    empty = tmp_path / "no-keys"
    empty.mkdir()
    with keys.part1_dotenv(clone_dir, keys_dir=kdir):
        with keys.part1_dotenv(clone_dir, keys_dir=empty) as active:
            assert active is False and (clone_dir / ".env").exists()
    assert not (clone_dir / ".env").exists()


def test_part1_dotenv_overlap_across_processes(clone_and_keys: tuple[Path, Path]) -> None:
    """The server and another process on one clone: the lock is the kernel's, not this process's."""
    clone_dir, kdir = clone_and_keys
    other = _holder(clone_dir, kdir)
    with keys.part1_dotenv(clone_dir, keys_dir=kdir):
        pass
    assert (clone_dir / ".env").exists()
    other.communicate("out\n", timeout=30)
    assert other.returncode == 0 and not (clone_dir / ".env").exists()


def test_part1_dotenv_a_killed_holder_blocks_nothing(clone_and_keys: tuple[Path, Path]) -> None:
    """AC-H5: a server killed inside the call leaves a stale `.env` and no lock; the next call replaces and removes it."""
    clone_dir, kdir = clone_and_keys
    dead = _holder(clone_dir, kdir)
    dead.kill()
    dead.communicate(timeout=30)
    assert (clone_dir / ".env").exists()
    with keys.part1_dotenv(clone_dir, keys_dir=kdir) as active:
        assert active is True
    assert not (clone_dir / ".env").exists()


def test_part1_dotenv_the_part_process_does_not_keep_the_lock(clone_and_keys: tuple[Path, Path]) -> None:
    """A child started inside the call without `pass_fds` (a stray) inherits no lock, so the holder's exit still removes. A Part 1
    run gets the descriptor on purpose (`part1_holder_fds`, tests/part7/test_serve_part1_env.py)."""
    clone_dir, kdir = clone_and_keys
    with keys.part1_dotenv(clone_dir, keys_dir=kdir):
        child = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.readline()"], stdin=subprocess.PIPE, text=True)
    try:
        assert not (clone_dir / ".env").exists()
    finally:
        child.communicate("out\n", timeout=30)


def test_part1_dotenv_many_overlapping_holders_always_see_the_key(clone_and_keys: tuple[Path, Path]) -> None:
    clone_dir, kdir = clone_and_keys
    env_path = clone_dir / ".env"
    gaps: list[str] = []

    def take() -> None:
        for _ in range(40):
            with keys.part1_dotenv(clone_dir, keys_dir=kdir):
                if not env_path.is_file() or FAKE_KEY not in env_path.read_text(encoding="utf-8"):
                    gaps.append("key missing inside a holder")

    threads = [threading.Thread(target=take) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not gaps and not any(t.is_alive() for t in threads) and sorted(p.name for p in clone_dir.iterdir()) == []


def _leftover(clone_dir: Path, name: str, body: str = "MODEL_API_KEY=x\n", mode: int = 0o600) -> Path:
    path = clone_dir / name
    path.write_text(body, encoding="utf-8")
    path.chmod(mode)
    return path


@pytest.mark.parametrize("body", ["MODEL_API_KEY=x\n", "MODEL_API", ""])
def test_the_start_sweep_removes_a_killed_writer_leftovers(clone_and_keys: tuple[Path, Path], body: str) -> None:
    """R1 and R2: SIGKILL leaves `.env` with nothing to remove it, and a temp file `git add -A` could stage."""
    clone_dir, _kdir = clone_and_keys
    env, temp = _leftover(clone_dir, ".env"), _leftover(clone_dir, ".env.p7-a1b2_c3d", body)
    keys.drop_part1_env(clone_dir)
    assert not env.exists() and not temp.exists()


WRITER = """import os, sys, time
from pathlib import Path
from part7 import keys
def stall(src, dst):
    Path(sys.argv[2]).write_text("x")
    time.sleep(60)
os.replace = stall
keys._write_part1_env(Path(sys.argv[1]), "fake-not-a-key-000000")
"""


def test_a_real_writer_killed_before_its_replace_leaves_a_file_the_sweep_removes(clone_and_keys: tuple[Path, Path], tmp_path: Path) -> None:
    """R17: the file is named by the real writer, so a prefix the sweep does not know turns this red."""
    clone_dir, _kdir = clone_and_keys
    mark = tmp_path / "stalled"
    proc = subprocess.Popen([sys.executable, "-c", WRITER, str(clone_dir), str(mark)], cwd=Path(__file__).resolve().parents[1])
    try:
        deadline = time.monotonic() + 60
        while not mark.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert mark.exists()
        proc.kill()
        proc.wait(timeout=30)
    finally:
        proc.kill()
    left = [p for p in clone_dir.iterdir() if p.name.startswith(".env.")]
    assert len(left) == 1 and left[0].read_text(encoding="utf-8").startswith("MODEL_API_KEY=")
    keys.drop_part1_env(clone_dir)
    assert not any(clone_dir.iterdir())


def test_the_sweep_still_clears_an_old_style_temp_file_that_holds_the_key(clone_and_keys: tuple[Path, Path]) -> None:
    """Transition: files named `.env.<8 characters>` by the release before the prefix go, when they hold the key line."""
    clone_dir, _kdir = clone_and_keys
    old = _leftover(clone_dir, ".env.a1b2c3d4", "MODEL_API_KEY=x\n")
    keys.drop_part1_env(clone_dir)
    assert not old.exists()


def test_the_sweep_leaves_files_a_person_or_a_repo_owns(clone_and_keys: tuple[Path, Path]) -> None:
    """Only what `mkstemp` wrote is touched: not a tracked example, nor a name, mode or content that is not ours."""
    clone_dir, _kdir = clone_and_keys
    kept = [
        _leftover(clone_dir, ".env.example"),  # not 8 characters
        _leftover(clone_dir, ".env.template", "KEY=\n", 0o644),  # 8 characters, a checkout's mode
        _leftover(clone_dir, ".env.template2"),
        _leftover(clone_dir, ".env.personal"),  # 8 letters, mode 600, a key line: nothing mkstemp's name rule needs to take
        _leftover(clone_dir, ".env.original"),
        _leftover(clone_dir, ".env.sample_1", ""),  # an old-style name with no key line: nothing to leak
        _leftover(clone_dir, ".env.p7-a1b2c3d4", "MODEL_API_KEY=x\n", 0o644),  # our prefix, not mkstemp's mode
        _leftover(clone_dir, ".env.a1b2c3d4", "MODEL_API_KEY=x\n", 0o644),  # the mode is not mkstemp's
        _leftover(clone_dir, ".env.e5f6g7h8", "OTHER=1\n"),  # the content is not what we write
        _leftover(clone_dir, "env.a1b2c3d4"),
    ]
    target = _leftover(clone_dir, "target", "MODEL_API_KEY=x\n")
    link = clone_dir / ".env.linklink"
    link.symlink_to(target)
    keys.drop_part1_env(clone_dir)
    assert all(path.exists() for path in kept) and link.is_symlink() and target.exists()


def test_the_sweep_leaves_a_running_holder_alone(clone_and_keys: tuple[Path, Path]) -> None:
    """A holder may be writing its temp file: nothing goes while any holder is inside."""
    clone_dir, kdir = clone_and_keys
    with keys.part1_dotenv(clone_dir, keys_dir=kdir):
        temp = _leftover(clone_dir, ".env.p7-a1b2c3d4")
        keys.drop_part1_env(clone_dir)
        assert (clone_dir / ".env").is_file() and temp.exists()
    assert not (clone_dir / ".env").exists() and not temp.exists()


def test_the_sweep_after_a_killed_holder_clears_both(clone_and_keys: tuple[Path, Path]) -> None:
    """The real SIGKILL: the kernel drops the lock, the files stay until the next server start sweeps them."""
    clone_dir, kdir = clone_and_keys
    holder = _holder(clone_dir, kdir)
    temp = _leftover(clone_dir, ".env.p7-a1b2c3d4")
    holder.kill()
    holder.communicate(timeout=30)
    assert (clone_dir / ".env").is_file()
    keys.drop_part1_env(clone_dir)
    assert not (clone_dir / ".env").exists() and not temp.exists()


def test_the_sweep_of_a_missing_tree_does_nothing(tmp_path: Path) -> None:
    keys.drop_part1_env(tmp_path / "no-such-clone")


def test_keys_dir_never_falls_back_to_a_shared_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                         caplog: pytest.LogCaptureFixture) -> None:
    from part7 import config

    monkeypatch.delenv("SIMON7_KEYS_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(config, "_KEYS_LOGGED", False)
    own, other = tmp_path / ".config/simon/keys", tmp_path / ".config/firm/operator-keys"
    other.mkdir(parents=True)
    (other / "MODEL_API_KEY").write_text("secret-value-123\n", encoding="utf-8")
    with caplog.at_level("INFO", logger="part7"):
        assert config.keys_dir() == own.resolve(), "a firm-internal directory is never used"
        assert config.keys_dir() == own.resolve()
    assert [r.getMessage() for r in caplog.records].count(
        f"keys: no keys directory is set (SIMON7_KEYS_DIR) and {own.resolve()} does not exist") == 1
    assert "secret-value-123" not in caplog.text
    own.mkdir(parents=True)
    assert config.keys_dir() == own.resolve()
    monkeypatch.setenv("SIMON7_KEYS_DIR", str(tmp_path / "x"))
    assert config.keys_dir() == (tmp_path / "x").resolve()


def test_a_part1_run_given_the_descriptor_keeps_the_lock_after_the_holder_is_gone(clone_and_keys: tuple[Path, Path]) -> None:
    """The other half of the test above: with `pass_fds=part1_holder_fds()` the child holds the lock itself, so an exclusive try
    on the copy stays refused after the holder left and the key stays; once the child exits the lock and the key go."""
    import fcntl
    import os
    clone_dir, kdir = clone_and_keys
    with keys.part1_dotenv(clone_dir, keys_dir=kdir):
        child = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.readline()"], stdin=subprocess.PIPE, text=True,
                                 pass_fds=keys.part1_holder_fds(), cwd=tmp_elsewhere())
    try:
        fd = os.open(clone_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
        assert (clone_dir / ".env").is_file()
    finally:
        child.communicate("out\n", timeout=30)
    keys.drop_part1_env(clone_dir)
    assert not (clone_dir / ".env").exists()


def tmp_elsewhere() -> str:
    """A working directory outside any copy, so only the descriptor can keep the key in the test above."""
    return "/"
