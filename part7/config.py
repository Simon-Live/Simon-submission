"""Configuration constants and state directory helpers for Simon Part 7."""

from __future__ import annotations

import logging
import os
from pathlib import Path

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
MAX_UPLOAD_BYTES = 95_000_000
RECORDER_BPS = 2_500_000
QUEUE_LIMIT = 8
RETENTION_DAYS = 7
VISITOR_TRAINER_PER_DAY = 3
VISITOR_GPU_PER_DAY = 10
PART6_MIN_DURATION_MS = 1000
PART6_MAX_DURATION_MS = 120000

DAILY_TRAINER_JOBS_LIMIT = 10
DAILY_GPU_JOBS_LIMIT = 40
PART1_RUN_SPEND_CAP_USD = 5.0

DEFAULT_GPU_WORKERS = 2
DEFAULT_PART1_TIMEOUT_S = 150.0
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


def gpu_workers() -> int:
    """Job worker threads (`SIMON7_GPU_WORKERS`, default 2)."""
    return int(_env_number("SIMON7_GPU_WORKERS", DEFAULT_GPU_WORKERS, 1))


def cleanup_every_s() -> float:
    """Seconds between retention sweeps of the job folders (`SIMON7_CLEANUP_EVERY_S`, default 600)."""
    return _env_number("SIMON7_CLEANUP_EVERY_S", 600.0, 1)


DEFAULT_DRAIN_MAX_S = 600.0


def drain_max_s() -> float:
    """Seconds a stopping server waits for running jobs (`SIMON7_DRAIN_MAX_S`, default 600)."""
    return _env_number("SIMON7_DRAIN_MAX_S", DEFAULT_DRAIN_MAX_S, 0)


def part1_timeout_s() -> float:
    """Seconds the trainer chain waits for Part 1 (`SIMON7_PART1_TIMEOUT_S`, default 150)."""
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
    """Return the directory holding the part submodules (`<repo>/modules`, or `SIMON7_MODULES_DIR`)."""
    env_val = os.environ.get("SIMON7_MODULES_DIR")
    if env_val:
        return Path(env_val).expanduser().resolve()
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
