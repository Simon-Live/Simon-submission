"""Configuration constants and state directory helpers for Simon Part 7."""

from __future__ import annotations

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
DEFAULT_PART1_TIMEOUT_S = 90.0


def _env_number(name: str, default: float, minimum: float) -> float:
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value >= minimum else default


def gpu_workers() -> int:
    """Job worker threads (`SIMON7_GPU_WORKERS`, default 2)."""
    return int(_env_number("SIMON7_GPU_WORKERS", DEFAULT_GPU_WORKERS, 1))


def part1_timeout_s() -> float:
    """Seconds the trainer chain waits for Part 1 (`SIMON7_PART1_TIMEOUT_S`, default 90)."""
    return _env_number("SIMON7_PART1_TIMEOUT_S", DEFAULT_PART1_TIMEOUT_S, 1)


TIMEOUTS = {
    "1": 900,
    "2": 1200,
    "3": 180,
    "4": 180,
    "5": 180,
    "6": 60,
    "doctor": 60,
}

PART_REPOS: dict[str, str] = {
    "1": "https://github.com/moalborati/simon-part-1-keyframes.git",
    "2": "https://github.com/moalborati/simon-part-2-images-to-3d.git",
    "3": "https://github.com/moalborati/simon-part-3-skeleton-consistency.git",
    "4": "https://github.com/moalborati/simon-part-4-animate-keyframes.git",
    "5": "https://github.com/moalborati/simon-part-5-fault-analysis.git",
    "6": "https://github.com/moalborati/simon-part-6-recording-catalog.git",
}

# Optional local checkouts of Parts 2, 3, 5 and 6 (`~/simon-part-<n>`): `part7 pin --update` reads the last
# STATUS line of each one that exists into parts.lock.json; a missing checkout records "upstream main".
PART_WORKSPACES: dict[str, Path] = {p: Path.home() / f"simon-part-{p}" for p in ("2", "3", "5", "6")}


def state_root(state: str | Path | None = None) -> Path:
    """Return the root state directory (`~/.local/state/simon-part-7/` by default)."""
    if state is not None:
        return Path(state).expanduser().resolve()
    env_val = os.environ.get("SIMON7_STATE_DIR")
    if env_val:
        return Path(env_val).expanduser().resolve()
    return (Path.home() / ".local" / "state" / "simon-part-7").resolve()


def parts_dir(state: str | Path | None = None) -> Path:
    """Return the directory holding materialized part clones (`<state>/parts`)."""
    return state_root(state) / "parts"


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


def lock_path() -> Path:
    """Return the path to `parts.lock.json`."""
    env_val = os.environ.get("SIMON7_LOCK_PATH")
    if env_val:
        return Path(env_val).expanduser().resolve()
    return REPO_ROOT / "parts.lock.json"


def manifest_path() -> Path:
    """Return the path to `videos/manifest.json`."""
    env_val = os.environ.get("SIMON7_VIDEOS_MANIFEST")
    if env_val:
        return Path(env_val).expanduser().resolve()
    return REPO_ROOT / "videos" / "manifest.json"


def keys_dir() -> Path:
    """Return the directory holding operator key files."""
    env_val = os.environ.get("SIMON7_KEYS_DIR")
    if env_val:
        return Path(env_val).expanduser().resolve()
    return (Path.home() / ".config" / "firm" / "operator-keys").resolve()


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
