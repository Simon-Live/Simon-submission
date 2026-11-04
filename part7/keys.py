"""Key file lookup, redaction, and temporary Part 1 `.env` management (TICKET-009)."""

from __future__ import annotations

import contextlib
import contextvars
import fcntl
import logging
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Callable, Iterator

from part7 import config
from part7.prod_mode import is_prod, policy

# Operator keys for hosted models (Meta Model API, Hugging Face, Baseten, Muse Spark). `read_key` answers None for them in prod
# and prod_check refuses their files (security audit R1, byok-prod.md), except `MUSE_KEYS` while the `muse` switch is on
# (docs/specs/muse-prod.md, operator decision 2026-11-04).
OPERATOR_MODEL_KEYS: tuple[str, ...] = ("MODEL_API_KEY", "HF_TOKEN", "BASETEN_API_KEY", "MUSE_SPARK_API_KEY")
# The only key files prod reads: the ADR-0025 mail pair, the sign-in pepper and the credential store's key
# (byok_crypto.KEY_NAME) that the app makes itself on first use, and the postal address (legal_pages.ADDRESS_SETTING).
MUSE_KEYS: tuple[str, ...] = ("MODEL_API_KEY", "BASETEN_API_KEY")
PROD_KEYS: tuple[str, ...] = ("SIMON7_SMTP_URL", "SIMON7_MAIL_FROM", "SIMON7_AUTH_PEPPER", "simon7-byok.key",
                              "SIMON7_RESEND_WEBHOOK_SECRET",  # the optional Resend webhook signing secret (mail_webhook.py)
                              "SIMON7_POSTAL_ADDRESS")
# serverless-compute.md AC-SC2: only the process that calls Modal opens these (deploy/serverless/p2_client.py). `read_key`
# and the redactor pass over them, so the server's memory never holds the operator's token.
MODAL_TOKEN_FILES: tuple[str, ...] = ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")
# Every other name the code reads (a test derives the readers from the source): refused as a file in prod.
PROD_REFUSED_KEYS: tuple[str, ...] = (*OPERATOR_MODEL_KEYS, "SIMON7_SMTP_HOST", "SIMON7_SMTP_PORT", "SIMON7_SMTP_USER",
                                      "SIMON7_SMTP_PASSWORD", "SIMON7_MAIL_API_KEY", "SIMON7_MAIL_API_URL")
KEY_NAMES: tuple[str, ...] = (
    *OPERATOR_MODEL_KEYS,
    "SIMON7_SMTP_URL",
    "SIMON7_SMTP_HOST",
    "SIMON7_SMTP_USER",
    "SIMON7_SMTP_PASSWORD",
    "SIMON7_MAIL_API_KEY",
    "SIMON7_AUTH_PEPPER",
    "SIMON7_RESEND_WEBHOOK_SECRET",
)

_SECRETS: set[str] = set()
# What `_write_part1_env` names a temp file: a prefix no checkout tracks, then `mkstemp`'s 8 characters. Files of the earlier
# name `.env.<8 characters>` are still swept (TICKET-497 removes that): only names `mkstemp`'s alphabet and length could make that
# hold a digit or underscore (so `.env.personal` and `.env.original` are never touched; the 5.95% of old names with letters only
# stay for a person to remove, TICKET-388 lists them), mode 600, holding the whole key line.
_ENV_TEMP_PREFIX = ".env.p7-"
_ENV_TEMP_NAME = re.compile(re.escape(_ENV_TEMP_PREFIX) + r"[a-z0-9_]{8}")
_ENV_OLD_TEMP_NAME = re.compile(r"\.env\.(?=[a-z0-9_]*[0-9_])[a-z0-9_]{8}")  # TICKET-497
_ENV_LINE_START = b"MODEL_API_KEY="
_LOG = logging.getLogger("part7")
PROC_UNREADABLE = -1  # `process_inside`: /proc cannot be listed, so a run in the tree cannot be ruled out
_HOLDER_FDS: contextvars.ContextVar[tuple[int, ...]] = contextvars.ContextVar("part1_holder_fds", default=())


def read_key(name: str, keys_dir: Path | str | None = None) -> str | None:
    """Read a key file from `keys_dir` (or `config.keys_dir()`) and register it for redaction."""
    if name in MODAL_TOKEN_FILES:
        return None
    if name in OPERATOR_MODEL_KEYS and is_prod() and not (name in MUSE_KEYS and policy("muse")):  # R1, muse-prod.md
        return None
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
                if not item.is_file() or item.name in MODAL_TOKEN_FILES:
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


def _write_part1_env(clone_dir: Path, key_val: str) -> None:
    """Put the key in `<clone_dir>/.env` by atomic replace (mode 0600), so a Part 1 run reading it never sees a gap."""
    fd, tmp = tempfile.mkstemp(prefix=_ENV_TEMP_PREFIX, dir=clone_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"MODEL_API_KEY={key_val}\n")
        os.replace(tmp, clone_dir / ".env")
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _is_env_temp(path: Path) -> bool:
    """True for what `_write_part1_env` left: a mode 600 regular file named `.env.p7-<8 characters>` holding the key line or
    part of it, or (TICKET-497) an old-style `.env.<8 characters>` name with a digit or underscore holding the whole key
    line. A tracked `.env.example`, a symlink, or a file of another mode or content is none of these. What still matches
    wrongly is a person's own mode 600 file with such an old-style name that starts `MODEL_API_KEY=`: the trees Part 7 serves
    from are built by Part 7, so only a dev checkout can hold one."""
    try:
        info = path.lstat()
        new = bool(_ENV_TEMP_NAME.fullmatch(path.name))
        if not (new or _ENV_OLD_TEMP_NAME.fullmatch(path.name)) or not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            return False
        with path.open("rb") as fh:
            head = fh.read(len(_ENV_LINE_START))
        return _ENV_LINE_START.startswith(head) if new else head == _ENV_LINE_START
    except OSError:
        return False


def process_inside(root: Path) -> int | None:
    """The pid of a live process (not this one) whose working directory is `root` or inside it, else None. A Part 1 run of a
    build that did not pass the `.env` lock (an older release, or a run that outlived a restart) holds no lock, but it runs
    with its cwd in the copy (`runner.run(cwd=clone)`, `p1_keyframes.run`), so this finds it. Same-user processes stay
    visible under prod's `ProtectProc=invisible`, and an exec'd child is dumpable, so its cwd link reads; the non-dumpable app
    itself is hidden and is not a Part 1 run. `PROC_UNREADABLE` when /proc cannot be listed, or lists no entry for this process itself: the answer is then "keep"."""
    try:
        names = os.listdir("/proc")
        target = root.resolve()
    except OSError:
        return PROC_UNREADABLE
    me = os.getpid()
    if str(me) not in names:  # a listing without this very process is not a listing of the host (a hidden or empty /proc)
        return PROC_UNREADABLE
    for name in filter(str.isdigit, names):
        try:
            cwd = Path(os.readlink(f"/proc/{name}/cwd"))
        except OSError:  # gone, another user's, or not dumpable (root-owned): none of those is a run of ours
            continue
        if int(name) != me and (cwd == target or target in cwd.parents):
            return int(name)
    return None


def _kept_by_process(clone_dir: Path) -> bool:
    """True, with a log line, when a live process works inside `clone_dir` (see `process_inside`): its `.env` stays."""
    pid = process_inside(clone_dir)
    if pid is not None:
        why = "/proc cannot be read" if pid == PROC_UNREADABLE else f"process {pid} works inside it"
        _LOG.warning("Part 1 .env kept in %s: %s", clone_dir, why)
    return pid is not None


def _drop_part1_env_if_unheld(clone_dir: Path) -> None:
    """Remove `<clone_dir>/.env` and any temp file a killed writer left, unless a holder of the lock is still alive.
    The exclusive try fails while any process has the shared lock: a `part1_dotenv` holder, or the Part 1 run that
    inherited its descriptor (`part1_holder_fds`), which keeps the lock after the server that started it is dead. A
    holder entering meanwhile waits on the lock and writes the file again afterwards. A holder writes its temp file only
    under that lock, so none here is a live one. A process with its cwd inside `clone_dir` also keeps it: a run of an older
    build holds no lock (B5, prod runs Part 1 with the Muse key)."""
    try:
        probe = os.open(clone_dir, os.O_RDONLY | os.O_DIRECTORY)
    except FileNotFoundError:
        return
    try:
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if _kept_by_process(clone_dir):
            return
        (clone_dir / ".env").unlink(missing_ok=True)
        for leftover in filter(_is_env_temp, clone_dir.glob(".env.*")):
            leftover.unlink(missing_ok=True)
    except BlockingIOError:
        pass
    finally:
        os.close(probe)


def drop_part1_env(clone_dir: Path | str) -> None:
    """Remove `<clone_dir>/.env` and any temp file a killed writer left, unless a live Part 1 call holds it: a killed run cannot
    do this itself, so `part7 serve` calls this at start, at a takeover and with each sweep, and prod's sweep for each copy (AC-H5c)."""
    _drop_part1_env_if_unheld(Path(clone_dir))


def part1_holder_fds() -> tuple[int, ...]:
    """The lock descriptor of the `part1_dotenv` this thread is inside, for `runner.run(pass_fds=...)`: the Part 1 run
    then holds the shared lock itself, so the sweep leaves its `.env` while it lives even if the server is gone (B1)."""
    return _HOLDER_FDS.get()


@contextlib.contextmanager
def part1_dotenv(
    clone_dir: Path | str,
    keys_dir: Path | str | None = None,
) -> Iterator[bool]:
    """Keep `<clone_dir>/.env` (mode 0600) only while a Part 1 call on this clone runs (AC-H5). Part 1 reads the file on
    every API call, so overlapping takes share it and the last one out removes it (AC-H5b, TICKET-388). Each holder keeps
    a shared `flock` on the clone directory: no file to leave behind, and the kernel drops it when every process holding
    the descriptor is gone. The server closes its copy at the end; a run started with `part1_holder_fds` keeps the lock."""
    cdir = Path(clone_dir)
    key_val = read_key("MODEL_API_KEY", keys_dir=keys_dir)
    if not key_val:
        _drop_part1_env_if_unheld(cdir)
        yield False
        return
    cdir.mkdir(parents=True, exist_ok=True)
    holder = os.open(cdir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(holder, fcntl.LOCK_SH)
        try:
            _write_part1_env(cdir, key_val)
        except FileNotFoundError:  # a reclaim removed the tree while this call waited on the lock: Part 1 is unavailable (R26)
            yield False
            return
        token = _HOLDER_FDS.set((holder,))
        try:
            yield True
        finally:
            _HOLDER_FDS.reset(token)
    finally:
        os.close(holder)
        _drop_part1_env_if_unheld(cdir)
