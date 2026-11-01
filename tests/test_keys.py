"""Tests for `part7.keys` (TICKET-009, AC-H4, AC-H5, AC-008)."""

from __future__ import annotations

from pathlib import Path
import stat
import subprocess
import sys
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
