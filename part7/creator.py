"""The creator token of a take (docs/specs/prod-data.md "Creator token", LEG-H4, LEG-C1).

The device that submits a follow or trainer take gets `creator_token` once, in the 202 answer of the submit
(`auth.attach_job`). It is `HMAC-SHA256(secret, job_id)`: nothing per take is stored, so the token outlives the job
folder (the 7-day sweep) and still deletes the catalog movement a trainer take made. Only it claims a take for an
account (`POST api/me/claims`); the job id alone (a result link) never does. The secret is
`<state>/creator/secret` (folder 0700, file 0600), made on first use, never logged and never in a job record.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import secrets
import threading

from part7 import jobs

FOLDER, FILE = "creator", "secret"
_LOCK = threading.Lock()


def _secret(state: Path | str) -> bytes:
    folder = Path(state) / FOLDER
    path = folder / FILE
    with _LOCK:
        try:
            return bytes.fromhex(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pass
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        value = secrets.token_hex(32)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:  # another process made it first: use theirs
            return bytes.fromhex(path.read_text(encoding="utf-8").strip())
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(value + "\n")
        return bytes.fromhex(value)


def token_for(state: Path | str, job_id: str) -> str:
    """The creator token of `job_id` (hex); ValueError for a malformed id."""
    if not isinstance(job_id, str) or not jobs.JOB_ID_RE.match(job_id):
        raise ValueError("not a job id")
    return hmac.new(_secret(state), f"creator:{job_id}".encode("utf-8"), hashlib.sha256).hexdigest()


def valid(state: Path | str, job_id: object, token: object) -> bool:
    """True only when `token` is the creator token of `job_id` (constant-time compare)."""
    if not isinstance(job_id, str) or not isinstance(token, str) or not jobs.JOB_ID_RE.match(job_id) or len(token) != 64:
        return False
    return hmac.compare_digest(token_for(state, job_id), token)
