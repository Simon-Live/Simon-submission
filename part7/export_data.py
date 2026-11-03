"""Download my data: the builder of `simon.export.v1` (docs/specs/export-data.md, TICKET-236).

One JSON document with everything Simon keeps about one signed-in person. Read only: it calls the same readers the
app uses (`IdentityStore`, `profile`, `history_store.entries/takes/consent`) and writes nothing, so a delete that
already ran is reflected. Each store is one *exporter* in `EXPORTERS`; a store added later joins the file with one
`register(...)` line (see the bottom of this module), and `COVERED_TABLES` makes a test fail until a new identity
table is either exported or listed as left out on purpose. Video is listed, never embedded.

Never in the file: another person's data, a share token, a session id or hash, the pepper, a spend line, a private
take's analysis. `build` ends with a check that no other account's id or email is in the text; if one is, it raises
`ExportError` and the route answers no file at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable

from part7 import devices, history_store, labels, model_only, model_store, my_reference, notes, profile, reference_approval, share, shown_score, source_credit

FORMAT = "simon.export.v1"
MAX_BYTES = 32 * 1024 * 1024  # measured: about 300 takes come to under 3 MB (docs/specs/export-data.md)
CLIP_NOTE = "The video is not in this file. The clip stays on your history page while Simon keeps it."
PRIVATE_NOTE = "Private mode take: Simon keeps only the date, so there is no analysis to show."
# Keys that must never reach the file, whatever a store hands back (defence in depth, applied to every section).
FORBIDDEN_KEYS = frozenset({
    "token", "token_hash", "share_token", "sid", "sid_hash", "session_id", "pepper", "secret", "code_mac", "password",
    "api_key", "authorization", "cookie",
})
_USER_ID_RE = re.compile(r"\bu-[0-9a-f]{24}\b")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")

# Identity tables and the section that exports them; None means left out on purpose (no personal data of the account).
COVERED_TABLES: dict[str, str | None] = {
    "users": "account", "takes": "takes", "entries": "entries", "profiles": "profile",
    "sessions": "sessions",  # TICKET-235: a list without ids or hashes
    "shares": "shares",  # TICKET-233: no token or hash in the file
    "note_requests": "notes",  # TICKET-237: both roles, the other side named only by its public author line
    "source_credits": "sources",  # TICKET-322: title, creator, licence and link of the person's own entries and takes
    "challenges": None,  # open sign-in challenges: hashed secrets and an address that may not be an account yet
}


class ExportError(RuntimeError):
    """The file cannot be built safely; the route answers no file."""


@dataclass
class Ctx:
    """What an exporter may read: the state folder, the identity store, the account and the catalog (for names)."""

    state: Path
    store: Any
    user_id: str
    child: Any = None

    @property
    def jobs(self) -> Path:
        return self.state / "jobs"

    def movement(self, entry_id: str | None) -> str | None:
        if not entry_id:
            return None
        return labels.entry_name(self.child, entry_id, self.state) if self.child is not None else entry_id


Exporter = Callable[[Ctx], Any]
EXPORTERS: dict[str, Exporter] = {}


def register(name: str, fn: Exporter) -> None:
    """Add (or replace) the exporter of one section. Order of registration is the order in the file."""
    EXPORTERS[name] = fn


# ----- sections ---------------------------------------------------------------------------------------
def _account(ctx: Ctx) -> dict[str, Any]:
    user = ctx.store.user(ctx.user_id)
    if user is None:
        raise ExportError("the account is gone")
    row = ctx.store._one("SELECT consent_at FROM users WHERE user_id = ?", (ctx.user_id,))
    at = row["consent_at"] if row is not None else None
    video = history_store.consent(ctx.state, ctx.user_id)
    return {
        "email": user["email"], "created": user["created_at"],
        "consent": {
            "retention": {"opted_in": user["retention"]["opted_in"], "version": user["retention"]["consent_version"],
                          "date": datetime.fromtimestamp(at, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if at else None},
            "video": {"opted_in": video["video"], "version": video["version"], "date": video["at"]},
        },
    }


def _profile(ctx: Ctx) -> dict[str, Any]:
    return profile.get_profile(ctx.store, ctx.user_id) or profile.defaults()


def _kept_rows(ctx: Ctx) -> dict[str, dict[str, Any]]:
    """Every kept copy of this user by job id, from `history_store.entries` and `takes`."""
    rows: dict[str, dict[str, Any]] = {}
    for entry_id in history_store.entries(ctx.state, ctx.user_id):
        for row in history_store.takes(ctx.state, ctx.user_id, entry_id):
            rows[row["job_id"]] = row
    return rows


def _job_score(ctx: Ctx, job_id: str) -> tuple[Any, Any, bool, Any]:
    """Score, grade, the private flag and the shown score (one-letter.md) of a take with no kept copy, from its job
    folder (as the Me page reads it)."""
    folder = ctx.jobs / job_id
    job = history_store.read_json(folder / "job.json")
    analysis = history_store.read_json(folder / "work" / "follower" / history_store.ANALYSIS_NAME)
    score = analysis.get("score") if isinstance(analysis, dict) else None
    value = score.get("value") if isinstance(score, dict) else None
    grade = score.get("grade") if isinstance(score, dict) else None
    value = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    shown = shown_score.of_analysis(analysis, history_store.light_of(job) if isinstance(job, dict) else None)
    return value, grade if isinstance(grade, str) else None, bool(isinstance(job, dict) and history_store.is_private(job)), shown


def _takes(ctx: Ctx) -> list[dict[str, Any]]:
    kept, out = _kept_rows(ctx), []
    for take in ctx.store.takes_of(ctx.user_id):
        row = kept.get(take["job_id"])
        score, grade, private, shown = ((row["score"], row["grade"], bool(row["private"]), shown_score.of_take(row)) if row
                                        else _job_score(ctx, take["job_id"]))
        job = history_store.read_json(ctx.jobs / take["job_id"] / "job.json")
        out.append({"video_kept": row.get("video_kept", True) if row else model_only.kept(job), "job_id": take["job_id"], "entry_id": take["entry_id"], "movement": ctx.movement(take["entry_id"]),
                    "kind": take["kind"], "date": take["created_at"], "score": score, "grade": grade, "shown": shown, "private": private})
    return out


def _entries(ctx: Ctx) -> list[dict[str, Any]]:
    return [{"entry_id": e["entry_id"], "movement": ctx.movement(e["entry_id"]), "created": e["created_at"], "only_me": e["only_me"],
             "floor_work": labels.floor_work(ctx.state, e["entry_id"])}
            for e in ctx.store.entries_of(ctx.user_id)]


def _take_doc(row: dict[str, Any]) -> dict[str, Any]:
    if row["private"]:  # listed by date only, as Simon keeps it
        return {"job_id": row["job_id"], "date": row["at"], "private": True, "note": PRIVATE_NOTE}
    folder: Path = row["analysis"].parent
    return {
        "job_id": row["job_id"], "date": row["at"], "private": False,
        "meta": history_store.read_json(folder / history_store.META_NAME),
        "analysis": history_store.read_json(row["analysis"]),
        "clip": {"kept": row["clip"] is not None, "duration_s": row["duration_s"], "note": CLIP_NOTE} if row["clip"] is not None else None,
    }


def _reports(ctx: Ctx, entry_id: str) -> list[Any]:
    folder = history_store.reports_dir(ctx.state, ctx.user_id, entry_id)
    docs = [history_store.read_json(path) for path in sorted(folder.glob("*.json"))] if folder.is_dir() else []
    return [doc for doc in docs if isinstance(doc, dict)]


def _history(ctx: Ctx) -> list[dict[str, Any]]:
    out = []
    for entry_id in history_store.entries(ctx.state, ctx.user_id):
        rows = history_store.takes(ctx.state, ctx.user_id, entry_id)
        out.append({"entry_id": entry_id, "movement": ctx.movement(entry_id), "takes": [_take_doc(r) for r in rows],
                    "reports": _reports(ctx, entry_id)})
    return out


# ----- registry: one line per store. A lane merged later replaces its placeholder with its own reader. ------------
register("account", _account)
register("profile", _profile)
register("sessions", devices.export_rows)  # TICKET-235: no session id or hash
register("takes", _takes)
register("entries", _entries)
register("history", _history)
register("models", lambda ctx: model_store.export_rows(ctx.state, f"u:{ctx.user_id}"))  # imported and generated models, no files
register("shares", share.export_rows)  # TICKET-233: kind, target, include set, dates, state; no token
register("sources", source_credit.export_rows)  # TICKET-322
register("notes", notes.export_rows)  # TICKET-237: author line from attribution.py, never the user id
# TICKET-232 (attribution) adds no store of its own: its author line is read where a note or entry shows one.


# ----- build ----------------------------------------------------------------------------------------
def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if str(k).lower() not in FORBIDDEN_KEYS}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _check_no_one_else(ctx: Ctx, text: str) -> None:
    """Raise if the text holds another account's id or email."""
    own = ctx.store.user(ctx.user_id) or {}
    for found in set(_USER_ID_RE.findall(text)) - {ctx.user_id}:
        if ctx.store._one("SELECT 1 FROM users WHERE user_id = ?", (found,)) is not None:
            raise ExportError("another account's id is in the export")
    own_email = str(own.get("email", "")).lower()
    for found in {m.lower() for m in _EMAIL_RE.findall(text)} - {own_email}:
        if ctx.store._one("SELECT 1 FROM users WHERE email = ?", (found,)) is not None:
            raise ExportError("another account's email is in the export")


def build(ctx: Ctx, now: datetime | None = None) -> bytes:
    """The export as UTF-8 JSON bytes. `ExportError` when it cannot be built safely (nothing is partly returned)."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc: dict[str, Any] = {"format": FORMAT, "generated": stamp,
                           "about": "Everything Simon keeps about you. It shows your email address, so keep the file private."}
    for name, fn in EXPORTERS.items():
        try:
            doc[name] = _scrub(fn(ctx))
        except ExportError:
            raise
        except Exception as exc:  # a reader fault ends in no file, never a half file
            raise ExportError(f"{name}: {type(exc).__name__}") from exc
    text = json.dumps(doc, indent=2, ensure_ascii=False, default=str)
    _check_no_one_else(ctx, text)
    data = text.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise ExportError("the export is too large")
    return data


def filename(now: datetime | None = None) -> str:
    return f"simon-my-data-{(now or datetime.now(timezone.utc)).strftime('%Y-%m-%d')}.json"
register("my_references", my_reference.export_rows)  # ADR-0019: which take is my reference per movement; no movement data
register("reference_approvals", reference_approval.export_rows)  # ADR-0019: approvals a teacher made or a student received; no movement data
