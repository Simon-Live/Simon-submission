"""Configuration constants and state directory helpers for Simon Part 7."""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path

from part7 import compute_mode, prod_check
from part7.prod_mode import is_prod

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = REPO_ROOT / "web"

DEV_HOST = "127.0.0.1"
DEV_PORT = 8727
STAGING_PORT = 7124
DEFAULT_BASE_PATH = "/"
STAGING_BASE_PATH = "/simon-part-7/"

MAX_UPLOAD_SECONDS = 90  # raw capture; a trim (or no trim) narrows it to MAX_CLIP_SECONDS
MAX_CLIP_SECONDS = 60
MIN_CLIP_SECONDS = 1
# The ONE byte cap of a request body (operator, 2026-11-03). EDGE-413: Cloudflare refuses a body over 100 MB before the
# app sees it and the firm gateway answers 413 from its registry max_body_mb (90, docs/prod/registry-block.yaml), so
# the app's own cap sits under both and the 413 is the app's. The recorder makes about 28 MB per 90 s, so it loses
# nothing. The video upload, model import and the central prod 413 all derive from it.
MAX_UPLOAD_BYTES = 85_000_000
RECORDER_BPS = 2_500_000
QUEUE_LIMIT = 8
RETENTION_DAYS = 7
PART6_MIN_DURATION_MS = 1000
PART6_MAX_DURATION_MS = 120000

DEFAULT_GPU_WORKERS = 2
# 150 s for Part 1's work, then `p1_keyframes.STOP_GRACE_S` for it to delete its upload at Meta (TICKET-388).
DEFAULT_PART1_TIMEOUT_S = 215.0
# TICKET-067: Part 2 `track` sends every frame to a remote tracker, so its time grows with the pixel count
# (412.6 s for 176 frames at 2048x1080, 21.3 s at 608x1080). Every job's clip is scaled to this long side.
DEFAULT_CLIP_MAX_SIDE = 1280
MIN_CLIP_MAX_SIDE = 16


def _env_number(name: str, default: float, minimum: float) -> float:
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value >= minimum else default


def upload_max_bytes() -> int:
    """Largest video upload in bytes (`MAX_UPLOAD_BYTES`, also `api/config` `limits.max_bytes`)."""
    return MAX_UPLOAD_BYTES


def body_cap_bytes() -> int | None:
    """Largest request body of any route in prod (a model import, a proxied Part 6 upload, a form); None outside prod,
    where each route keeps its own cap (each derives from `MAX_UPLOAD_BYTES`)."""
    return MAX_UPLOAD_BYTES if is_prod() else None


def socket_timeout_s() -> float | None:
    """Seconds one socket read or write may block (`SIMON7_SOCKET_TIMEOUT_S`): 60 in prod, off elsewhere unless set (APP-M3)."""
    default = 60.0 if is_prod() else 0.0
    value = _env_number("SIMON7_SOCKET_TIMEOUT_S", default, 0)
    return value or None


def byok_idle_ttl_s() -> int:
    """Seconds a stored BYOK credential may sit unused (`byok_idle_ttl_s` of the health line): the TTL the credential
    store enforces, `modal_creds.IDLE_TTL_S` (one source; the contract caps it at 86400)."""
    from part7 import modal_creds  # here: modal_creds is not needed by the many readers of config

    return modal_creds.IDLE_TTL_S


def disk_floor_bytes() -> int:
    """Free space the state disk must keep after an upload (`SIMON7_DISK_FLOOR_BYTES`, default 5 GB)."""
    return int(_env_number("SIMON7_DISK_FLOOR_BYTES", 5_000_000_000, 0))


def gpu_workers() -> int:
    """Job worker threads (`SIMON7_GPU_WORKERS`, default 2); in serverless mode the configured GPU concurrency."""
    if compute_mode.serverless():
        return serverless_max_concurrent()
    return int(_env_number("SIMON7_GPU_WORKERS", DEFAULT_GPU_WORKERS, 1))


# docs/specs/serverless-compute.md: set in prod/compute.conf.
SERVERLESS_CONCURRENT_ENV = "SIMON7_SERVERLESS_MAX_CONCURRENT"
SERVERLESS_QUEUE_WAIT_ENV = "SIMON7_SERVERLESS_QUEUE_WAIT_S"
DEFAULT_SERVERLESS_CONCURRENT = 4  # also Modal's max_containers (deploy/serverless/part2_app.py reads the same name)
DEFAULT_SERVERLESS_QUEUE_WAIT_S = 900.0


def _count(name: str, default: int) -> int:
    """A whole number from the environment; anything unusable is 0, which refuses (fail closed)."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return int(raw) if raw.isdigit() else 0


def queue_limit() -> float:
    """Jobs the queue holds before it refuses. On Modal a job past the workers waits its turn in memory, however many there
    are (operator: "no limits anywhere ever"); the host's own GPU keeps `QUEUE_LIMIT`."""
    return math.inf if compute_mode.serverless() else QUEUE_LIMIT


def serverless_max_concurrent() -> int:
    return max(1, _count(SERVERLESS_CONCURRENT_ENV, DEFAULT_SERVERLESS_CONCURRENT))


def serverless_image3d() -> bool:
    """A picture of a character or object is offered on Modal (prod/compute.conf, serverless-compute.md AC-SC20)."""
    return os.environ.get("SIMON7_SERVERLESS_IMAGE3D", "").strip() == "1"


def serverless_queue_wait_s() -> float:
    return _env_number(SERVERLESS_QUEUE_WAIT_ENV, DEFAULT_SERVERLESS_QUEUE_WAIT_S, 1)


def cleanup_every_s() -> float:
    """Seconds between retention sweeps of the job folders (`SIMON7_CLEANUP_EVERY_S`, default 600)."""
    return _env_number("SIMON7_CLEANUP_EVERY_S", 600.0, 1)


DEFAULT_DRAIN_MAX_S = 600.0


def drain_max_s() -> float:
    """Seconds a stopping server waits for running jobs (`SIMON7_DRAIN_MAX_S`, default 600)."""
    return _env_number("SIMON7_DRAIN_MAX_S", DEFAULT_DRAIN_MAX_S, 0)


def jobs_after_pid() -> int | None:
    """The previous server a restart started this one beside (`SIMON7_JOBS_AFTER_PID`, set by staging/up.sh): the job
    queue stays a standby until that process has exited (jobs.py, TICKET-240). None when unset or not a pid."""
    value = os.environ.get("SIMON7_JOBS_AFTER_PID", "").strip()
    return int(value) if value.isdigit() and int(value) > 0 else None


def health_part6_stale_s() -> float:
    """Seconds a missed Part 6 probe still counts as healthy (`SIMON7_HEALTH_PART6_STALE_S`, default 120)."""
    return _env_number("SIMON7_HEALTH_PART6_STALE_S", 120.0, 0)


def part1_timeout_s() -> float:
    """Seconds the trainer chain waits for Part 1 (`SIMON7_PART1_TIMEOUT_S`, default 215), its stop included."""
    return _env_number("SIMON7_PART1_TIMEOUT_S", DEFAULT_PART1_TIMEOUT_S, 1)


def clip_max_side() -> int:
    """Long side cap in px of every job's clip (`SIMON7_CLIP_MAX_SIDE`, default 1280; 0 turns the cap off).

    A value that is not a whole number, or one from 1 to `MIN_CLIP_MAX_SIDE - 1`, falls back to the default.
    """
    try:
        value = int(os.environ.get("SIMON7_CLIP_MAX_SIDE", "").strip())
    except ValueError:
        return DEFAULT_CLIP_MAX_SIDE
    return value if value == 0 or value >= MIN_CLIP_MAX_SIDE else DEFAULT_CLIP_MAX_SIDE


TIMEOUTS = {
    "1": 900,
    "2": 1200,
    "3": 180,
    "4": 180,
    "5": 180,
    "6": 60,
    "doctor": 60,
}

def state_root(state: str | Path | None = None) -> Path:
    """Return the root state directory (`~/.local/state/simon-part-7/` by default)."""
    if state is not None:
        return Path(state).expanduser().resolve()
    env_val = os.environ.get("SIMON7_STATE_DIR")
    if env_val:
        return Path(env_val).expanduser().resolve()
    return (Path.home() / ".local" / "state" / "simon-part-7").resolve()


def modules_dir() -> Path:
    """Return the directory holding the part submodules: `SIMON7_MODULES_DIR`, else the tree the serving build runs on
    (`<state>/module-trees/current`, TICKET-329), else `<repo>/modules`."""
    env_val = os.environ.get("SIMON7_MODULES_DIR")
    if env_val:
        return Path(env_val).expanduser().resolve()
    pointer = state_root() / "module-trees" / "current"
    if pointer.is_symlink() and pointer.is_dir():
        return pointer.resolve()
    return REPO_ROOT / "modules"


def part_dir(part: int | str) -> Path:
    """Return the checkout of one part: `<modules dir>/part-<n>`."""
    return modules_dir() / f"part-{part}"


def videos_dir(state: str | Path | None = None) -> Path:
    """Return the directory holding downloaded and trimmed test videos (`<state>/videos`)."""
    return state_root(state) / "videos"


def dev_dir(state: str | Path | None = None) -> Path:
    """Return the local dev server state directory (`<state>/dev`)."""
    return state_root(state) / "dev"


def staging_dir(state: str | Path | None = None) -> Path:
    """Return the staging server state directory (`<state>/staging`)."""
    return state_root(state) / "staging"


STAGING_STATE_DEFAULT = Path.home() / ".local" / "state" / "simon-part-7" / "staging"  # staging/env.sh's SIMON7_STATE_DIR


def staging_state_dir() -> Path:
    """The staging server's state folder: SIMON7_STAGING_STATE_DIR (staging/env.sh exports it), else the default."""
    return Path(os.environ.get("SIMON7_STAGING_STATE_DIR") or STAGING_STATE_DEFAULT).expanduser().resolve()


def is_staging_server(state: str | Path | None = None) -> bool:
    """True for the staging server: SIMON7_STAGING=1, or its state folder is the staging state folder (GPU guard)."""
    if os.environ.get("SIMON7_STAGING", "").strip() == "1":
        return True
    return state_root(state) == staging_state_dir()


def check_dir(state: str | Path | None = None) -> Path:
    """Return the check-7 and chain state directory (`<state>/check`)."""
    return state_root(state) / "check"


def manifest_path() -> Path:
    """Return the path to `videos/manifest.json`."""
    env_val = os.environ.get("SIMON7_VIDEOS_MANIFEST")
    if env_val:
        return Path(env_val).expanduser().resolve()
    return REPO_ROOT / "videos" / "manifest.json"


_KEYS_LOGGED = False


def keys_dir() -> Path:
    """Return the directory holding key files: `SIMON7_KEYS_DIR` when set, else `~/.config/simon/keys`.

    When neither is set nor present, one line says so (the directory is named, never any content).
    """
    global _KEYS_LOGGED
    if is_prod():  # the firm's contract: secrets come from PROD_SECRETS_DIR only, never an operator or home folder
        return prod_check.keys_dir_for_prod()
    env_val = os.environ.get("SIMON7_KEYS_DIR")
    if env_val:
        return Path(env_val).expanduser().resolve()
    own = (Path.home() / ".config" / "simon" / "keys").resolve()
    if not own.exists() and not _KEYS_LOGGED:
        _KEYS_LOGGED = True
        logging.getLogger("part7").info("keys: no keys directory is set (SIMON7_KEYS_DIR) and %s does not exist", own)
    return own


def gpu_lock_path() -> Path:
    """Return the path to Part 2's GPU lock file."""
    env_val = os.environ.get("SIMON7_GPU_LOCK_PATH")
    if env_val:
        return Path(env_val).expanduser().resolve()
    return (Path.home() / ".local" / "state" / "simon-part-2" / "gpu.lock").resolve()


def part2_gpu_venv_path() -> Path:
    """Return the path to Part 2's shared GPU cu128 virtual environment."""
    env_val = os.environ.get("SIMON7_PART2_GPU_VENV")
    if env_val:
        return Path(env_val).expanduser().resolve()
    return (Path.home() / ".local" / "state" / "simon-part-2" / "venvs" / "gpu-cu128").resolve()


def normalize_base_path(base: str | None) -> str:
    """Ensure base path starts and ends with `/`."""
    if not base:
        return "/"
    b = base.strip()
    if not b.startswith("/"):
        b = "/" + b
    if not b.endswith("/"):
        b = b + "/"
    return b


def part1_spend_cap_usd() -> float | None:
    """Part 1's run-wide spend cap in USD: off (None) unless SIMON7_PART1_SPEND_CAP_USD is a positive number.
    Spend is recorded either way."""
    try:
        value = float(os.environ.get("SIMON7_PART1_SPEND_CAP_USD", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def part1_spend_capped(spent: float) -> bool:
    cap = part1_spend_cap_usd()
    return cap is not None and spent >= cap


def staging_route() -> str | None:
    """How the hub exposes this app: `root` (own origin), `prefix` (shared gateway origin) or None when not on staging.

    `STAGING_ROUTE` wins. Without it a base path is read the way the hub sets it: `/` is root, any other path is a
    prefix. ADR-0014: sign-in may be shown only on `root`; in root mode the hub leaves `STAGING_BASE_PATH` empty, so
    "no base path" alone no longer means "local".
    """
    route = os.environ.get("STAGING_ROUTE", "").strip().lower()
    if route in ("root", "prefix", "strip"):
        return route
    base = os.environ.get("STAGING_BASE_PATH", "").strip()
    if not base:
        return None
    return "root" if base == "/" else "prefix"
