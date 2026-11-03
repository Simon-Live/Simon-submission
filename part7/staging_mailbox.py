"""The staging test mailbox (docs/specs/identity.md "Staging mailbox", TICKET-176).

On staging there is no mail account, so sign-in messages land here and a tester reads their own code and link on
`#/outbox`. Anyone who knows an address can read the messages sent to it: accepted for staging, which only carries
synthetic accounts, and never enabled anywhere else (`mail.select_transport` picks it only on the app's own origin
with `SIMON7_MAIL_TRANSPORT=outbox`). Messages live 30 minutes, the newest 50 are kept, and a listing needs the exact
address. No log line here holds an address, a code or a link.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
from typing import Any

TTL_S = 30 * 60
KEEP = 50
_LOCK = threading.Lock()


def _file(state: Path | str) -> Path:
    return Path(state) / "mailbox" / "messages.json"


def _load(path: Path, now: float) -> list[dict[str, Any]]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("at"), (int, float)) and now - r["at"] < TTL_S] if isinstance(rows, list) else []


def _save(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(rows, out)
    os.replace(tmp, path)


def add(state: Path | str, to: str, code: str, link: str, now: float | None = None) -> None:
    """Keep one message; expired ones go, and only the newest `KEEP` stay."""
    stamp = time.time() if now is None else now
    path = _file(state)
    with _LOCK:
        rows = _load(path, stamp)
        rows.append({"to": to.strip().lower(), "at": stamp, "code": code, "link": link})
        _save(path, rows[-KEEP:])


def messages_for(state: Path | str, email: str, now: float | None = None) -> list[dict[str, Any]]:
    """Messages sent to exactly `email` in the last 30 minutes, newest first. An empty address lists nothing."""
    wanted = (email or "").strip().lower()
    if not wanted:
        return []
    stamp = time.time() if now is None else now
    with _LOCK:
        rows = _load(_file(state), stamp)
    mine = [r for r in rows if r.get("to") == wanted]
    return [{"to": r["to"], "at": datetime.fromtimestamp(r["at"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "code": r["code"], "link": r["link"]} for r in reversed(mine)]


def purge(state: Path | str, email: str) -> int:
    """Delete the messages to `email` (Delete my data); returns how many."""
    path, wanted = _file(state), (email or "").strip().lower()
    with _LOCK:
        rows = _load(path, time.time())
        kept = [r for r in rows if r.get("to") != wanted]
        if len(kept) != len(rows) and path.parent.is_dir():
            _save(path, kept)
    return len(rows) - len(kept)
