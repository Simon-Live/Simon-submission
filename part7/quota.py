"""GPU job counts, the operator's stop file and the free-disk floor; no usage cap exists (operator: "no limits anywhere ever").

Counters on disk under `<state>/quota/` are for api/health and for reading spend afterwards; they refuse nothing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import threading
from typing import Callable

from part7 import compute_mode, config, keys
from part7.prod_mode import ProdModeError, is_prod

STOPPED_MESSAGE = "Simon has paused new analyses for now. Try again later."
STOP_FILE = "serverless-stop"  # `touch <app state>/serverless-stop` stops new GPU jobs at once, with no release or restart
SIGN_IN_MESSAGE = "Sign in to analyse a take. Simon needs an account for GPU work."  # = serverless_route.MSG_SIGN_IN
KEEP_DAYS = 3  # UTC days a day file (and with it a hashed network address) is kept: today and the two before (D11)


class SignInRequired(Exception):
    """A job on the operator's GPU with nobody signed in (HTTP 429, `SIGN_IN_MESSAGE`)."""


class ComputeStopped(Exception):
    """The operator's stop file stands (HTTP 503, `STOPPED_MESSAGE`)."""


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


_DAY_FILE = re.compile(r"^(?:uploads-)?(\d{4}-\d{2}-\d{2})\.json$")


def prune(folder: Path | str, today: str | None = None) -> int:
    """Delete the day files (`<day>.json`, `uploads-<day>.json`) older than KEEP_DAYS UTC days; the count removed.

    By the date in the name, not by how many files exist: after a quiet week a file from before it still goes (D11).
    The writers call it after each write and the periodic sweep calls it (`server._sweep`), so a server with no traffic
    keeps no hashed address past its days either. A name that is not a day file is left alone."""
    base = Path(folder)
    day = datetime.strptime(today or _today(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    cutoff = (day - timedelta(days=KEEP_DAYS - 1)).strftime("%Y-%m-%d")
    gone = 0
    for path in base.iterdir() if base.is_dir() else []:
        found = _DAY_FILE.match(path.name)
        if found and found.group(1) < cutoff and path.is_file():
            path.unlink(missing_ok=True)
            gone += 1
    return gone


def disk_guard_on() -> bool:
    """The free-disk floor applies in prod and whenever the operator pays for the GPU, elsewhere only with
    SIMON7_DISK_GUARD=on."""
    return is_prod() or compute_mode.serverless() or os.environ.get("SIMON7_DISK_GUARD", "off").strip().lower() == "on"


def client_of(visitor: str) -> str:
    """The unit a limit counts: an IPv4 address as is, an IPv6 address as its /64 (one home or phone network hands a
    client a whole /64, so a per-address count would be a count per new address; APP-M4, security audit R12)."""
    try:
        addr = ipaddress.ip_address(visitor.strip())
    except ValueError:
        return visitor
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


_VISITOR_INFO = b"simon7-visitor-v1"
_VISITOR_KEYS: dict[str, bytes] = {}  # keys derived from a pepper only, one per keys folder
_FALLBACK = secrets.token_bytes(32)  # this process's stand-in while no pepper can be read (never cached as a folder's key)
_VISITOR_LOCK = threading.Lock()


def _derive(seed: bytes) -> bytes:
    prk = hmac.new(b"simon7-visitor-salt", seed, hashlib.sha256).digest()
    return hmac.new(prk, _VISITOR_INFO + b"\x01", hashlib.sha256).digest()


def _made_pepper(folder: str) -> str | None:
    """Make `SIMON7_AUTH_PEPPER` in `folder` as auth._pepper does (0600, never over an existing one); None when it cannot."""
    path = Path(folder) / "SIMON7_AUTH_PEPPER"
    try:
        Path(folder).mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(secrets.token_hex(32) + "\n")
    except FileExistsError:
        pass  # another request or sign-in made it first: read theirs
    except OSError:
        return None
    return keys.read_key("SIMON7_AUTH_PEPPER", folder)


def _visitor_secret() -> bytes:
    """The HMAC key of `visitor_key` (privacy PM-R6), derived from the sign-in pepper in the keys folder (extract then
    expand, info `simon7-visitor-v1`), so the hashed address cannot be reversed by trying every address. Read once per
    keys folder once a pepper is there. With no pepper yet the first call makes it, as sign-in would (the team, #61). When
    it cannot (or with no keys folder) the call uses a key held by this process and is not cached: the next call reads
    the pepper again (review R7)."""
    try:
        folder = str(config.keys_dir())
    except ProdModeError:  # no secrets folder named: the process key below (the start check refuses such a prod)
        folder = ""
    with _VISITOR_LOCK:
        found = _VISITOR_KEYS.get(folder)
        if found is not None:
            return found
        pepper = keys.read_key("SIMON7_AUTH_PEPPER", folder) if folder else None
        if not pepper and folder:
            pepper = _made_pepper(folder)  # made now, as sign-in would, so a visitor's count never changes key
        if not pepper:
            return _derive(_FALLBACK)  # this call only
        found = _VISITOR_KEYS[folder] = _derive(pepper.encode("utf-8"))
        return found


def visitor_key(visitor: str | None) -> str | None:
    """Return a short keyed hash (HMAC-SHA256, `_visitor_secret`) of the visitor's client unit (`client_of`); the
    address itself is never stored. Keys from before PM-R6 (a plain sha256) are not migrated: they live only in the
    day files and on boards, which drop them after KEEP_DAYS (`prune`, challenges VISITOR_KEEP_DAYS)."""
    if not visitor:
        return None
    return hmac.new(_visitor_secret(), client_of(visitor).encode("utf-8"), hashlib.sha256).hexdigest()[:16]


DISK_MESSAGE = "The server is short of disk space right now. Try again later."


def disk_refusal(state: Path | str, need: int = 0, free: Callable[[Path], int] | None = None) -> str | None:
    """A message when writing `need` more bytes under `state` would pass the free-disk floor, else None. Always in prod:
    uploads, the export ZIP and an own-Modal result check it before writing (security audit R7)."""
    if not disk_guard_on():
        return None
    try:
        left = (free or (lambda path: shutil.disk_usage(path).free))(Path(state)) - need
    except OSError:
        return DISK_MESSAGE  # fails closed
    return DISK_MESSAGE if left < config.disk_floor_bytes() else None


def counted_as(user: str | None, visitor: str | None) -> str | None:
    """Who a GPU job runs for: in serverless mode the account (None when signed out, which `reserve` refuses); else the
    visitor's address."""
    if compute_mode.serverless():
        return f"account:{user}" if user else None
    return visitor


class Quota:
    """Counts GPU jobs per UTC day, in total. A trainer job also counts as a GPU job. It refuses only a signed-out job on
    the operator's GPU and any job while the stop file stands."""

    def __init__(self, state: Path | str, *, today: Callable[[], str] = _today) -> None:
        self.stop_file = Path(state) / STOP_FILE
        self.dir = Path(state) / "quota"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.account_needed = compute_mode.serverless()
        self._today = today
        self._lock = threading.Lock()

    def _path(self) -> Path:
        return self.dir / f"{self._today()}.json"

    def _load(self) -> dict:
        """The day's counters; a damaged file reads as a fresh day, since nothing is refused on a count."""
        try:
            doc = json.loads(self._path().read_text(encoding="utf-8"))
            if isinstance(doc, dict) and isinstance(doc.get("gpu", 0), int) and isinstance(doc.get("trainer", 0), int):
                return {"gpu": doc.get("gpu", 0), "trainer": doc.get("trainer", 0)}
        except (OSError, ValueError):
            pass
        return {"gpu": 0, "trainer": 0}

    def _save(self, doc: dict) -> None:
        path = self._path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc), encoding="utf-8")
        tmp.replace(path)
        prune(self.dir, self._today())

    def gpu_jobs_today(self) -> int:
        with self._lock:
            return int(self._load()["gpu"])

    def reserve(self, kind: str, visitor: str | None, gpu_paid: bool = False) -> None:
        """Count one job of `kind` (`trainer` or `follow`), or raise for the stop file or a signed-out person.
        `gpu_paid`: this take's people job already counted its GPU unit (PROD-D3), so only a trainer's own count rises."""
        if self.account_needed and self.stop_file.exists():
            raise ComputeStopped(STOPPED_MESSAGE)
        if self.account_needed and not visitor:
            raise SignInRequired(SIGN_IN_MESSAGE)
        with self._lock:
            doc = self._load()
            self._bump(doc, kind, 1, not gpu_paid)
            self._save(doc)

    def release(self, kind: str, visitor: str | None, gpu_paid: bool = False) -> None:
        """Undo one `reserve` (the job never entered the queue)."""
        with self._lock:
            doc = self._load()
            self._bump(doc, kind, -1, not gpu_paid)
            self._save(doc)

    @staticmethod
    def _bump(doc: dict, kind: str, delta: int, gpu: bool = True) -> None:
        if gpu:
            doc["gpu"] = max(0, doc["gpu"] + delta)
        if kind == "trainer":
            doc["trainer"] = max(0, doc["trainer"] + delta)


UPLOAD_MESSAGE_DISK = "The server cannot take uploads right now. Try again later."
