"""A signed-in user's own Modal credentials (TICKET-367, parts-harness.md AC-H16, docs/specs/byok-prod.md).

One file per user, `<state>/credentials/<user_id>.json`, mode 0600 in a 0700 folder, written atomically. The file
holds `{v: 3, gen, box}`: `box` is the pair under AES-256-GCM (`byok_crypto`, BYOK-M4), the owner's id and `gen` bound
as associated data, so a file copied to another user's name does not open. `gen` is a random id per save that a
check result names (R4); it is not a secret.

Idle expiry (BYOK-H2): the file's mtime is its last use. `env_for` (a job about to run) sets it; a pair unused for
`IDLE_TTL_S` is deleted the next time anything reads it and by the sweeper (`sweep`, `start_sweeper`, start-up
included). Deleting overwrites the file with zeros first, then leaves a tombstone `<user_id>.tomb.json` that says
why (`expired`, `invalid`) and holds no value. Every read and write of one user's files holds that user's flock;
the sweeper removes the lock with the user's last tombstone (lifecycle R3).

Never in the identity database, a job record, a log line, an error message or an exception text: callers get the
values only from `env_for`, which builds the env of one Modal client subprocess. Everything else sees `hint`.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
from typing import Any, Callable, Iterator

from part7 import applog, byok_crypto, own_clients

DIR = "credentials"
# Modal's own tokens are `ak-` and `as-` followed by letters and digits (`modal token new`). The exact length is not
# documented. ASM-367-1: the operator fallback, 8 to 128 of [A-Za-z0-9_-] after the prefix.
TOKEN_ID_RE = re.compile(r"^ak-[A-Za-z0-9_-]{8,128}$")
TOKEN_SECRET_RE = re.compile(r"^as-[A-Za-z0-9_-]{8,128}$")
USER_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MSG_KEY_DOWN = ("This server cannot read saved Modal tokens right now. That is a fault on the server, not your "
                "token, and your token is kept. Try again later.")
# go-live BYOK N4: Save with the server's key unusable names the same fault as the card and the check
MSG_KEY_DOWN_SAVE = ("This server cannot save Modal tokens right now. That is a fault on the server, not your token. "
                     "Try again later.")
MSG_SHAPE = "Those do not look like Modal tokens. The ID starts with ak- and the secret with as-."
ENV_ID, ENV_SECRET = "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"
FORMAT = 3  # 1 and 2 (f18fc24e plaintext, 159ec5d0 HMAC) existed only in tests: dropped on read, not migrated
IDLE_TTL_S = 86400  # BYOK-H2 and the prod contract: at most 24 h unused; api/health reports it (run_on.health_fields)
SWEEP_S = 900.0
TMP_MAX_AGE_S = 300.0  # a temp file older than this belongs to a write that died
TOMB_KEEP_S = 7 * 86400
CHECK, TOMB, LOCK = ".check.json", ".tomb.json", ".lock"
EXPIRED, INVALID = "expired", "invalid"
Clock = Callable[[], float]
CLOCK: Clock = time.time  # tests replace it


def _path(state: Path | str, user_id: str) -> Path | None:
    """The user's file, or None for an id that could not be a safe file name (never a path outside the folder)."""
    if not isinstance(user_id, str) or not USER_RE.match(user_id):
        return None
    return Path(state) / DIR / f"{user_id}.json"


def side(path: Path, suffix: str) -> Path:
    """`<user_id><suffix>` beside the credentials file (the check result, the tombstone, the lock)."""
    return path.with_name(path.stem + suffix)


def valid(token_id: object, token_secret: object) -> bool:
    """Whether both values have the Modal token shape. Says nothing about which one failed (no echo of a value)."""
    return (isinstance(token_id, str) and isinstance(token_secret, str)
            and bool(TOKEN_ID_RE.match(token_id)) and bool(TOKEN_SECRET_RE.match(token_secret)))


def write_private(path: Path, doc: dict[str, Any]) -> None:
    """`doc` as JSON at `path`, atomically: a 0600 temp file in the same 0700 folder, fsynced, then renamed. The temp
    file never outlives a failed write (R5)."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)  # mkstemp creates it 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _wipe(path: Path) -> bool:
    """Overwrite `path` with zeros, then delete it; True when it was there."""
    try:
        size = path.stat().st_size
        with path.open("r+b") as fh:
            fh.write(b"\0" * size)
            fh.flush()
            os.fsync(fh.fileno())
    except FileNotFoundError:
        return False
    path.unlink(missing_ok=True)
    return True


@contextlib.contextmanager
def _locked(path: Path) -> Iterator[None]:
    """This user's flock (`<user_id>.lock`): every read and write of their files holds it."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(side(path, LOCK), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _ad(user_id: str, gen: str) -> bytes:
    return f"simon7-byok:v{FORMAT}:{user_id}:{gen}".encode("utf-8")


def _drop(path: Path, reason: str, now: float) -> None:
    """Delete the pair and its check result, and leave a tombstone that says why (holder of the lock only)."""
    _wipe(path)
    side(path, CHECK).unlink(missing_ok=True)
    write_private(side(path, TOMB), {"reason": reason, "at": int(now)})
    applog.log(f"byok: modal credentials of {path.stem} deleted ({reason})", level=logging.INFO)


def _expired(path: Path, now: float) -> bool:
    return now - path.stat().st_mtime > IDLE_TTL_S


def _read(state: Path | str, path: Path, touch: bool, now: float) -> tuple[str, str, str] | None:
    """`(token_id, token_secret, gen)` under the lock, or None. Expired or unreadable pairs are deleted here."""
    if not path.is_file():
        return None
    if _expired(path, now):
        _drop(path, EXPIRED, now)
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = None
    if not isinstance(doc, dict) or doc.get("v") != FORMAT or not isinstance(doc.get("gen"), str):
        _drop(path, INVALID, now)  # includes the f18fc24e and 159ec5d0 formats
        return None
    try:
        key = byok_crypto.load_key(state)
    except (OSError, byok_crypto.ByokKeyError) as exc:  # not the user's fault: keep the file, use nothing
        applog.log(f"byok: the key file is not usable ({type(exc).__name__})", level=logging.WARNING)
        return None
    plain = byok_crypto.open_(key, doc.get("box"), _ad(path.stem, doc["gen"]))
    try:
        pair = json.loads(plain.decode("utf-8")) if plain is not None else None
    except (UnicodeDecodeError, ValueError):
        pair = None
    if not isinstance(pair, dict) or not valid(pair.get("token_id"), pair.get("token_secret")):
        _drop(path, INVALID, now)
        return None
    if touch:
        os.utime(path, (now, now))
    return (pair["token_id"], pair["token_secret"], doc["gen"])


def _get(state: Path | str | None, user_id: str | None, touch: bool = False) -> tuple[str, str, str] | None:
    path = _path(state, user_id) if state is not None and user_id else None
    if path is None or not path.is_file():  # no lock file is made for a person who never saved a token
        return None
    with _locked(path):
        return _read(state, path, touch, CLOCK())  # type: ignore[arg-type]


def save(state: Path | str, user_id: str, token_id: str, token_secret: str) -> bool:
    """Store the pair encrypted (0600 file, 0700 folder); False for a bad shape or user id, nothing written then.
    Raises byok_crypto.ByokKeyError when the key file is not usable."""
    path = _path(state, user_id)
    if path is None or not valid(token_id, token_secret):
        return False
    key = byok_crypto.load_key(state)
    gen = secrets.token_hex(8)
    box = byok_crypto.seal(key, json.dumps({"token_id": token_id, "token_secret": token_secret}).encode("utf-8"),
                           _ad(user_id, gen))
    with _locked(path):
        write_private(path, {"v": FORMAT, "gen": gen, "box": box})
        side(path, CHECK).unlink(missing_ok=True)  # a new token has not been checked yet
        side(path, TOMB).unlink(missing_ok=True)
    return True


def is_set(state: Path | str | None, user_id: str | None) -> bool:
    return _get(state, user_id) is not None


def key_unavailable(state: Path | str | None, user_id: str | None) -> bool:
    """The user has a stored pair, and this server's key cannot open anything now (missing after first use, wrong
    mode, wrong length): the server's fault, not theirs (lifecycle R2). The record is kept."""
    path = _path(state, user_id) if state is not None and user_id else None
    if path is None or not path.is_file():
        return False
    try:
        byok_crypto.load_key(state)  # type: ignore[arg-type]
    except (OSError, byok_crypto.ByokKeyError):
        return True
    return False


def generation(state: Path | str | None, user_id: str | None) -> str | None:
    """The id of the stored save (a check result names it), or None."""
    got = _get(state, user_id)
    return got[2] if got else None


def tombstone(state: Path | str | None, user_id: str | None) -> str | None:
    """Why the last pair was deleted by this build (`expired`, `invalid`), or None."""
    path = _path(state, user_id) if state is not None and user_id else None
    try:
        doc = json.loads(side(path, TOMB).read_text(encoding="utf-8")) if path is not None else None
    except (OSError, ValueError):
        return None
    return doc.get("reason") if isinstance(doc, dict) and doc.get("reason") in (EXPIRED, INVALID) else None


def hint(state: Path | str, user_id: str | None) -> dict[str, object]:
    """`{"set", "token_id_hint": "ak-…<last 4>" | None, "expired"}`: the only view of the pair outside `env_for`."""
    got = _get(state, user_id)
    return {"set": got is not None, "token_id_hint": f"ak-…{got[0][-4:]}" if got else None,
            "expired": got is None and tombstone(state, user_id) == EXPIRED}


def token_key(state: Path | str | None, user_id: str | None) -> str | None:
    """A hash of the stored token ID, the same for every account that saves that token (byok R3: the check limit
    counts per token as well as per user), or None. Never the ID itself; a view, so the idle clock is not reset."""
    got = _get(state, user_id)
    return hashlib.sha256(f"simon7-modal-token:{got[0]}".encode("utf-8")).hexdigest()[:32] if got else None


def env_for(state: Path | str | None, user_id: str | None) -> dict[str, str] | None:
    """The env of one Modal client subprocess on the user's account, read now (so Remove applies at once). This is
    the one use that counts as use: it resets the idle clock."""
    got = _get(state, user_id, touch=True)
    return {ENV_ID: got[0], ENV_SECRET: got[1]} if got else None


@contextlib.contextmanager
def launch_gate(state: Path | str | None, user_id: str | None) -> Iterator[tuple[dict[str, str] | None, Callable[[int], Path | None]]]:
    """`runner.run(gate=...)` for one own-route Modal client: under the user's lock, the env read now (None once the
    pair is gone: nothing starts) and `started(pid)`, which registers the launcher before the lock is let go. With
    `remove` holding the same lock from the wipe to the stop, a client either starts before the wipe and is stopped,
    or reads no token (go-live BYOK N1)."""
    path = _path(state, user_id) if state is not None and user_id else None
    if path is None or not path.is_file():
        yield None, lambda pid: None
        return
    with _locked(path):
        got = _read(state, path, True, CLOCK())  # type: ignore[arg-type]
        env = {ENV_ID: got[0], ENV_SECRET: got[1]} if got else None
        yield env, lambda pid: own_clients.register(state, user_id, pid)  # type: ignore[arg-type]


def remove(state: Path | str, user_id: str) -> bool:
    """Delete everything of the user's under the folder (Remove and delete-account); True when a pair was there.
    Under the user's lock: the pair goes first, then every client holding it is stopped (BYOK-M6), so no queued take
    reads it in between and starts a client nothing stops (go-live BYOK N1)."""
    path = _path(state, user_id)
    if path is None or not path.parent.is_dir():
        return False
    with _locked(path):
        had = _wipe(path)
        own_clients.stop_owner(state, user_id)  # every launcher started before the wipe is registered by now
        for suffix in (CHECK, TOMB):
            side(path, suffix).unlink(missing_ok=True)
        side(path, LOCK).unlink(missing_ok=True)
    return had


def _sweep_one(state: Path | str, path: Path, now: float) -> bool:
    with _locked(path):
        if path.is_file() and _expired(path, now):
            _drop(path, EXPIRED, now)
            return True
    return False


def _drop_lock(path: Path) -> None:
    """The user's lock file once nothing of theirs is left (lifecycle R3): removed under the lock itself, as `remove`
    does, and only while no pair and no tombstone exist."""
    if not USER_RE.match(path.stem) or not side(path, LOCK).is_file():
        return
    with _locked(path):
        if not path.is_file() and not side(path, TOMB).is_file():
            side(path, LOCK).unlink(missing_ok=True)


def sweep(state: Path | str, now: float | None = None) -> dict[str, int]:
    """Delete expired pairs, temp files of dead writes, orphaned check results, old tombstones and the lock of a
    user whose tombstone goes (nothing of theirs is left then)."""
    folder, now = Path(state) / DIR, CLOCK() if now is None else now
    done = {"expired": 0, "tmp": 0, "orphans": 0}
    if not folder.is_dir():
        return done
    for item in sorted(folder.iterdir()):
        name = item.name
        try:
            age = now - item.stat().st_mtime
        except FileNotFoundError:
            continue
        if name.startswith(".tmp-"):
            if age > TMP_MAX_AGE_S:
                item.unlink(missing_ok=True)
                done["tmp"] += 1
        elif name.endswith(CHECK):
            if not item.with_name(name.removesuffix(CHECK) + ".json").is_file():
                item.unlink(missing_ok=True)
                done["orphans"] += 1
        elif name.endswith(TOMB):
            if age > TOMB_KEEP_S:
                item.unlink(missing_ok=True)
                _drop_lock(item.with_name(name.removesuffix(TOMB) + ".json"))
        elif name.endswith(".json") and USER_RE.match(item.stem):
            done["expired"] += _sweep_one(state, item, now)
    return done


_SWEEPERS: dict[str, threading.Event] = {}
_SWEEPERS_LOCK = threading.Lock()


def start_sweeper(state: Path | str, interval_s: float = SWEEP_S) -> threading.Event:
    """Sweep now (start-up), then every `interval_s` on a daemon thread; one per state dir. Set the event to stop."""
    key = str(Path(state).resolve())
    with _SWEEPERS_LOCK:
        if key in _SWEEPERS and not _SWEEPERS[key].is_set():
            return _SWEEPERS[key]
        stop = _SWEEPERS[key] = threading.Event()
    sweep(state)

    def loop() -> None:
        while not stop.wait(interval_s):
            try:
                sweep(state)
            except Exception as exc:  # the next round tries again; the type only
                applog.log(f"byok: sweep failed ({type(exc).__name__})", level=logging.WARNING)

    threading.Thread(target=loop, name="byok-sweeper", daemon=True).start()
    return stop


def export_rows(ctx: object) -> dict[str, str]:
    """Download my data: whether credentials are stored, never a value."""
    return {"modal credentials": "set" if is_set(ctx.state, ctx.user_id) else "not set"}  # type: ignore[attr-defined]
