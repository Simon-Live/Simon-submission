"""Which build is running: git commit, commit time, server start and the checked-out part modules (staging.md "Build stamp").

Read once at server start. Never raises: no git, no checkout or no module gives "unknown" fields.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess
from typing import Any

from part7 import config, modules

SHORT = 9
UNKNOWN = "unknown"
GIT_TIMEOUT_S = 5


def _git(root: Path, *args: str) -> str | None:
    try:
        run = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=GIT_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = run.stdout.strip()
    return out if run.returncode == 0 and out else None


def _parts() -> dict[str, str]:
    try:
        return modules.short_map()
    except Exception:
        return {}


def environment() -> str:
    """`staging` on the staging server (SIMON7_STAGING=1 or its state folder), else `local` (version-footer.md, Data)."""
    try:
        return "staging" if config.is_staging_server() else "local"
    except Exception:
        return "local"


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect(root: Path, now: datetime | None = None, parts: dict[str, str] | None = None,
            env: str | None = None) -> dict[str, Any]:
    marked = modules.firm_sha(root)  # a prod release tree has no .git, only .firm-sha
    sha = marked or _git(root, "rev-parse", "HEAD")
    committed = _git(root, "log", "-1", "--format=%cI", "HEAD") if sha and not marked else None
    subject = _git(root, "log", "-1", "--format=%s", "HEAD") if sha and not marked else None
    if committed:
        try:
            committed = _utc(datetime.fromisoformat(committed))
        except ValueError:
            committed = None
    return {
        "sha": sha or UNKNOWN,
        "short": sha[:SHORT] if sha else UNKNOWN,
        "committed_at": committed or UNKNOWN,
        "subject": subject or UNKNOWN,
        "started_at": _utc(now or datetime.now(timezone.utc)),
        "parts": parts if parts is not None else _parts(),
        "environment": env or environment(),  # TICKET-326: the footer names it
    }


def unknown() -> dict[str, Any]:
    return {"sha": UNKNOWN, "short": UNKNOWN, "committed_at": UNKNOWN, "subject": UNKNOWN,
            "started_at": UNKNOWN, "parts": {}, "environment": environment()}
