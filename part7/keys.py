"""Key file lookup, redaction, and temporary Part 1 `.env` management (TICKET-009)."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Callable, Iterator

from part7 import config

KEY_NAMES: tuple[str, ...] = (
    "MODEL_API_KEY",
    "HF_TOKEN",
    "BASETEN_API_KEY",
    "MUSE_SPARK_API_KEY",
    "SIMON7_SMTP_URL",
    "SIMON7_SMTP_HOST",
    "SIMON7_SMTP_USER",
    "SIMON7_SMTP_PASSWORD",
    "SIMON7_MAIL_API_KEY",
    "SIMON7_AUTH_PEPPER",
)

_SECRETS: set[str] = set()


def read_key(name: str, keys_dir: Path | str | None = None) -> str | None:
    """Read a key file from `keys_dir` (or `config.keys_dir()`) and register it for redaction."""
    kdir = Path(keys_dir) if keys_dir is not None else config.keys_dir()
    kpath = kdir / name
    if not kpath.is_file():
        return None
    try:
        value = kpath.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not value:
        return None
    if len(value) >= 4:
        _SECRETS.add(value)
    return value


def has_key(name: str, keys_dir: Path | str | None = None) -> bool:
    """Return True when the named key file exists and is non-empty."""
    return bool(read_key(name, keys_dir=keys_dir))


def _known_secrets(keys_dir: Path | str | None = None) -> set[str]:
    """Every key value in `keys_dir` plus every value read through `read_key` (4 characters or more)."""
    secrets: set[str] = set(_SECRETS)
    kdir = Path(keys_dir) if keys_dir is not None else config.keys_dir()
    if kdir.is_dir():
        try:
            for item in kdir.iterdir():
                if not item.is_file():
                    continue
                try:
                    val = item.read_text(encoding="utf-8", errors="replace").strip()
                except OSError:
                    continue
                if len(val) >= 4:
                    secrets.add(val)
                    _SECRETS.add(val)
        except OSError:
            pass
    return secrets


def redactor(keys_dir: Path | str | None = None) -> Callable[[str], str]:
    """Return a `redact` function over one snapshot of the key values (cheap to call per line)."""
    ordered = sorted(_known_secrets(keys_dir), key=len, reverse=True)

    def _redact(text: str) -> str:
        out = text
        for secret in ordered:
            if secret in out:
                out = out.replace(secret, "<redacted>")
        return out

    return _redact


def redact(text: str, keys_dir: Path | str | None = None) -> str:
    """Replace any present key values in `text` with `<redacted>` (AC-H4, AC-008)."""
    if not text:
        return text
    return redactor(keys_dir)(text)


@contextlib.contextmanager
def part1_dotenv(
    clone_dir: Path | str,
    keys_dir: Path | str | None = None,
) -> Iterator[bool]:
    """Write `<clone_dir>/.env` with mode 0600 only for the duration of a Part 1 call (AC-H5)."""
    cdir = Path(clone_dir)
    env_path = cdir / ".env"
    env_path.unlink(missing_ok=True)
    key_val = read_key("MODEL_API_KEY", keys_dir=keys_dir)
    if not key_val:
        yield False
        return
    cdir.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(env_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, f"MODEL_API_KEY={key_val}\n".encode("utf-8"))
        finally:
            os.close(fd)
        os.chmod(env_path, 0o600)
        yield True
    finally:
        env_path.unlink(missing_ok=True)
