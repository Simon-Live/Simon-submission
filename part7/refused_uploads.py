"""Refused uploads kept for diagnosis (TICKET-196): the last few, bounded in count and size.

A refusal used to delete the folder and log nothing, so an intermittent "not a video" left no evidence.
`keep` moves the refused folder to `<state>/uploads-refused/<id>/`; the oldest go first past 20 folders or 50 MB.
"""
from __future__ import annotations

import logging
from pathlib import Path
import shutil
import time

from part7 import applog, config

KEEP_COUNT = 20
KEEP_BYTES = 50 * 1024 * 1024
DIR_NAME = "uploads-refused"


def _size(folder: Path) -> int:
    total = 0
    for p in folder.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except FileNotFoundError:  # removed while we count
            continue
    return total


def _mtime(folder: Path) -> float | None:
    try:
        return folder.stat().st_mtime
    except FileNotFoundError:  # a folder that vanished between the listing and the stat
        return None


def _prune(root: Path) -> None:
    listed = ((p, _mtime(p)) for p in root.iterdir() if p.is_dir())
    folders = [p for p, m in sorted(((p, m) for p, m in listed if m is not None), key=lambda item: (item[1], item[0].name))]
    sizes = {p: _size(p) for p in folders}
    while folders and (len(folders) > KEEP_COUNT or sum(sizes[p] for p in folders) > KEEP_BYTES):
        shutil.rmtree(folders.pop(0), ignore_errors=True)


def keep(folder: Path, state: Path) -> Path | None:
    """Move `folder` into the refused store and prune it; None when it could not be kept (it is then removed)."""
    root = state / DIR_NAME
    try:
        root.mkdir(parents=True, exist_ok=True)
        target = root / folder.name
        shutil.move(str(folder), str(target))
        _prune(root)
        return target
    except OSError as exc:
        applog.log(f"refused upload not kept: {applog.cause(exc)}", level=logging.WARNING)
        shutil.rmtree(folder, ignore_errors=True)
        return None


def sweep(state: Path, now: float | None = None) -> int:
    """Remove refused uploads older than `RETENTION_DAYS` (the same cutoff as the uploads); returns how many went.

    A refused upload is not linked to an account, so it is deleted by age only and never shown (recorder.md).
    """
    root = state / DIR_NAME
    if not root.is_dir():
        return 0
    cutoff = (now if now is not None else time.time()) - config.RETENTION_DAYS * 86400
    gone = 0
    for folder in list(root.iterdir()):
        mtime = _mtime(folder)
        if mtime is not None and mtime < cutoff:
            shutil.rmtree(folder, ignore_errors=True)
            gone += 1
    return gone
