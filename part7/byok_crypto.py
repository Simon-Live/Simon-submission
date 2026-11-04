"""Encryption at rest for a user's own Modal credentials (docs/specs/byok-prod.md, BYOK-M4).

AES-256-GCM (`cryptography` AESGCM, pinned in pyproject.toml; ASM-367-2). A box is base64 of
`version byte || 96-bit random nonce || ciphertext and 128-bit tag`. The version byte is also part of the associated
data, so it cannot be swapped; the caller adds the owner (`modal_creds` passes the user id and the save's id), so a
box copied to another user does not open. A box of any other version is not opened: the f18fc24e plaintext and the
159ec5d0 HMAC format were never written outside tests and are dropped, not migrated.

The master key is a file named by SIMON7_BYOK_KEY_FILE; in prod without it, `$PROD_SECRETS_DIR/simon7-byok.key`;
elsewhere `<state parent>/.simon7-byok.key`. It is never inside the state dir (a state backup alone cannot decrypt),
created 0600 with 32 random bytes (hex) on first use, and refused when another user can read it.

Created once (prod verify lifecycle R1): a key that loads leaves the marker `<state>/.byok-key-made` (a fact, no
value; outside the credentials folder, which holds users' files only). With the marker, or with any stored record, a missing key file is an error (ByokKeyError), never a new
key: a new key would make every stored record unreadable, and reading them would delete them. `prod_check` refuses
the start then (`missing_problem`).
"""

from __future__ import annotations

import base64
import binascii
import os
from pathlib import Path
import secrets
import stat
from typing import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from part7 import prod_mode

KEY_ENV = "SIMON7_BYOK_KEY_FILE"
PROD_DIR_ENV = "PROD_SECRETS_DIR"
KEY_NAME = "simon7-byok.key"
KEY_BYTES = 32  # AES-256
NONCE_BYTES = 12  # 96 bits, random per write
VERSION = 1


class ByokKeyError(RuntimeError):
    """The key file is inside the state dir, readable by others, or not 32 bytes."""


MARKER = ".byok-key-made"  # in <state>: a key existed for this state once
MSG_MISSING = "the BYOK key file is missing, and this server had one; restore it from the secrets backup"


def key_path(state: Path | str, env: Mapping[str, str] | None = None) -> Path:
    """Where the master key lives for `state` (see the module text); `env` defaults to the process env."""
    source = os.environ if env is None else env
    named = source.get(KEY_ENV, "").strip()
    if named:
        return Path(named)
    prod_dir = source.get(PROD_DIR_ENV, "").strip()
    active = prod_mode.is_prod() if env is None else source.get("FIRM_ENV", "") == "prod"
    if active and prod_dir:
        return Path(prod_dir) / KEY_NAME
    return Path(state).resolve().parent / f".{KEY_NAME}"


def _folder(state: Path | str) -> Path:
    return Path(state) / "credentials"  # modal_creds.DIR (it imports this module, not the other way)


def had_key(state: Path | str) -> bool:
    """A key was made or loaded for this state before, or a record exists that only that key opens."""
    folder = _folder(state)
    if (Path(state) / MARKER).is_file():
        return True
    try:
        return any(p.suffix == ".json" and not p.name.startswith(".") and not p.name.endswith((".tomb.json", ".check.json"))
                   for p in folder.iterdir())
    except OSError:
        return False


def _mark(state: Path | str) -> None:
    marker = Path(state) / MARKER
    if marker.is_file():
        return
    marker.parent.mkdir(parents=True, exist_ok=True)
    os.close(os.open(marker, os.O_WRONLY | os.O_CREAT, 0o600))


def missing_problem(state: Path | str, env: Mapping[str, str] | None = None) -> str | None:
    """MSG_MISSING when the key file is gone from a state that had one (prod_check, lifecycle R1), else None."""
    return MSG_MISSING if had_key(state) and not key_path(state, env).is_file() else None


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
    except ValueError:
        return False
    return True


def load_key(state: Path | str) -> bytes:
    """The 32-byte master key, created on first use only (see the module text). ByokKeyError when it is missing
    after first use, when it sits in the state dir, others may read it,
    or it does not hold exactly 32 bytes (64 hex digits)."""
    path = key_path(state)
    if _inside(path, Path(state)):
        raise ByokKeyError("the BYOK key file must be outside the state dir")
    if not path.is_file():
        if had_key(state):  # R1: never a new key over records the old one sealed
            raise ByokKeyError(MSG_MISSING)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:  # another thread made it first: read theirs
            pass
        else:
            with os.fdopen(fd, "wb") as fh:
                fh.write(secrets.token_bytes(KEY_BYTES).hex().encode("ascii"))
                fh.flush()
                os.fsync(fh.fileno())
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ByokKeyError("the BYOK key file is readable by other users (chmod 600)")
    try:
        key = bytes.fromhex(path.read_bytes().strip().decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        raise ByokKeyError("the BYOK key file must hold 64 hex digits") from None
    if len(key) != KEY_BYTES:
        raise ByokKeyError("the BYOK key file must hold 64 hex digits")
    _mark(state)
    return key


def _ad(ad: bytes) -> bytes:
    return bytes([VERSION]) + ad


def seal(key: bytes, plaintext: bytes, ad: bytes) -> str:
    """`plaintext` encrypted with a fresh random nonce and bound to `ad` (the owner): base64 text."""
    nonce = secrets.token_bytes(NONCE_BYTES)
    ct = AESGCM(key).encrypt(nonce, plaintext, _ad(ad))
    return base64.b64encode(bytes([VERSION]) + nonce + ct).decode("ascii")


def open_(key: bytes, box: object, ad: bytes) -> bytes | None:
    """The plaintext of `box`, or None when it is malformed, another version, for another owner, under another key,
    or tampered with."""
    if not isinstance(box, str):
        return None
    try:
        raw = base64.b64decode(box, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) < 1 + NONCE_BYTES + 16 or raw[0] != VERSION:
        return None
    try:
        return AESGCM(key).decrypt(raw[1:1 + NONCE_BYTES], raw[1 + NONCE_BYTES:], _ad(ad))
    except (InvalidTag, ValueError):
        return None
