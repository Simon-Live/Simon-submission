"""Download my data: the builder of `simon.export.v1` (docs/specs/export-data.md, TICKET-236).

One JSON document with everything Simon keeps about one signed-in person. Read only: it calls the same readers the
app uses (`IdentityStore`, `profile`, `history_store.entries/takes/consent`) and writes nothing, so a delete that
already ran is reflected. Each store is one *exporter* in `EXPORTERS`; a store added later joins the file with one
`register(...)` line (see the bottom of this module), and `COVERED_TABLES` makes a test fail until a new identity
table is either exported or listed as left out on purpose. The JSON file lists video, never embeds it; the ZIP
download (`write_zip`, `GET api/me/export.zip`, LEG-M3) holds the same JSON plus the files themselves (`media_files`,
data-integrity D2): each take's clip, the raw upload still held, its 3D joint positions (`pose3d.json`) and per-take
data (`work/follower/*.json`; a trainer take's skeleton, animation and key frames), each kept history copy, the video,
data and label notes of each movement the person recorded, the outputs of each group take they made (S-R3), and the
files of each model they imported or generated.
The JSON holds the job record of each take (`job_records`: consent answers and age band included) and the boards the
person made or has a score on (`boards`, with their own entries only).

Never in the file: another person's data, a share token, a session id or hash, the pepper, a spend line, a private
take's analysis. `build` ends with a check that no other account's id or email is in the text; if one is, it raises
`ExportError` and the route answers no file at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable
import zipfile

from part7 import challenges, devices, history_store, modal_creds, labels, model_only, model_store, my_reference, notes, profile, reference_approval, share, shown_score, source_credit, upload_owner

FORMAT = "simon.export.v1"
MAX_BYTES = 32 * 1024 * 1024  # measured: about 300 takes come to under 3 MB (docs/specs/export-data.md)
ZIP_MAX_BYTES = 4 << 30  # the files of one ZIP download, before it is refused
ZIP_TMP_KEEP_S = 3600  # a ZIP left behind by a crashed download is removed by the next download after an hour
ZIP_PREFIX = ".export-"
ENTRY_FILES = ("manifest.json", "video.mp4", "keyframes.json", "skeleton.json", "animation.json", "thumbnail.jpg")
MODEL_FILES = ("model.glb", "character.json")  # the model the person imported or generated (model_store.py)
FEEDBACK_ROLE = "follower"  # work/follower/*.json is the analysis and its views: left out for a private take
ANOTHER_ACCOUNT = "(another account)"  # an id of someone else in the person's own record, as the file shows it
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


def _others_out(ctx: Ctx, value: Any) -> Any:
    """`value` with every account id but the person's own replaced: a record of theirs can name a teacher or a
    reference's maker, and the file never names another account."""
    if isinstance(value, dict):
        return {k: _others_out(ctx, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_others_out(ctx, v) for v in value]
    if isinstance(value, str):
        return _USER_ID_RE.sub(lambda m: m.group(0) if m.group(0) == ctx.user_id else ANOTHER_ACCOUNT, value)
    return value


def _job_records(ctx: Ctx) -> list[dict[str, Any]]:
    """The job record of each take, people job and group take the person made (consent answers, age band, trim,
    labels, the result summary)."""
    out = []
    ids = [t["job_id"] for t in ctx.store.takes_of(ctx.user_id)] + list(upload_owner.jobs_of(ctx.state, ctx.user_id))
    for job_id in ids:  # with the people jobs and group takes, which have no takes row (DI-N1)
        job = history_store.read_json(ctx.jobs / job_id / "job.json")
        if isinstance(job, dict):
            out.append(_others_out(ctx, job))
    return out


def _boards(ctx: Ctx) -> list[dict[str, Any]]:
    """Every board the person made or has a score on: what the board says and only their own entries on it. On a board
    someone else made, the maker's name is left out."""
    mine = {t["job_id"] for t in ctx.store.takes_of(ctx.user_id)}
    out = []
    for doc in challenges.involving(ctx.state, ctx.user_id, mine):
        entries = [e for e in doc.get("entries") or [] if isinstance(e, dict)]
        made = doc.get("owner") == ctx.user_id
        board = {k: v for k, v in doc.items() if k not in ("entries", *challenges.PRIVATE_DOC_FIELDS) and (made or k != "creator_name")}
        invites = [{"email": i.get("email"), "added_at": i.get("added_at"), "joined": bool(i.get("joined_at"))} for i in doc.get("invites") or []] if made else []
        out.append({**board, "made_by_me": made, "visibility": doc.get("visibility", "public"), "invites": invites,
                    "movement": ctx.movement(doc.get("entry_id")), "entry_count": len(entries),
                    "my_entries": [challenges.public_entry(e) for e in [*entries, *(doc.get("superseded") or [])] if isinstance(e, dict) and challenges.is_of(e, ctx.user_id, mine)]})
    return out


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
register("modal", modal_creds.export_rows)  # TICKET-367: "modal credentials: set", never a value
register("notes", notes.export_rows)  # TICKET-237: author line from attribution.py, never the user id
register("job_records", _job_records)  # data-integrity D2: the record of each take, consent answers included
register("boards", _boards)  # data-integrity D2: the boards the person made, their own entries only
# TICKET-232 (attribution) adds no store of its own: its author line is read where a note or entry shows one.


# ----- build ----------------------------------------------------------------------------------------
def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if str(k).lower() not in FORBIDDEN_KEYS}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _invited_by_me(doc: dict[str, Any]) -> set[str]:
    """The addresses the person typed on their own boards. They are the person's data, so one of them may also be an account's."""
    return {str(i.get("email")).lower() for b in doc.get("boards") or [] if isinstance(b, dict) and b.get("made_by_me")
            for i in b.get("invites") or [] if isinstance(i, dict) and i.get("email")}


def _check_no_one_else(ctx: Ctx, text: str, typed: frozenset[str] | set[str] = frozenset()) -> None:
    """Raise if the text holds another account's id, or the email of another account that the person did not type themselves."""
    own = ctx.store.user(ctx.user_id) or {}
    for found in set(_USER_ID_RE.findall(text)) - {ctx.user_id}:
        if ctx.store._one("SELECT 1 FROM users WHERE user_id = ?", (found,)) is not None:
            raise ExportError("another account's id is in the export")
    own_email = str(own.get("email", "")).lower()
    for found in {m.lower() for m in _EMAIL_RE.findall(text)} - {own_email} - set(typed):
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
    _check_no_one_else(ctx, text, _invited_by_me(doc))
    data = text.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise ExportError("the export is too large")
    return data


def filename(now: datetime | None = None, suffix: str = "json") -> str:
    return f"simon-my-data-{(now or datetime.now(timezone.utc)).strftime('%Y-%m-%d')}.{suffix}"


def _plain(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _upload_files(ctx: Ctx, job: Any) -> list[Path]:
    """The raw upload a take came from, while Simon still holds it (`uploads/<id>/upload.*`)."""
    from part7 import delete_routes  # one reader of the upload id, also for an older trainer job (data-integrity D1)

    upload_id = delete_routes.upload_of(job) if isinstance(job, dict) else None
    folder = ctx.state / "uploads" / upload_id if upload_id else None
    if folder is None or folder.is_symlink() or not folder.is_dir():
        return []
    return [path for path in sorted(folder.glob("upload.*")) if _plain(path)]


def _take_files(ctx: Ctx, job_id: str) -> list[tuple[str, Path]]:
    """One take's files: clip, raw upload, the 3D joint positions of each role, the trainer's skeleton, animation and
    key frames, and the follower's analysis files (not of a private take: private mode keeps no feedback)."""
    folder, base = ctx.jobs / job_id, f"takes/{job_id}"
    job = history_store.read_json(folder / "job.json")
    private = isinstance(job, dict) and history_store.is_private(job)
    out = [(f"{base}/video.mp4", folder / "work" / "video.mp4")]
    out += [(f"{base}/{path.name}", path) for path in _upload_files(ctx, job)]
    for role in ("follower", "trainer"):
        work = folder / "work" / role
        prefix = base if role == FEEDBACK_ROLE else f"{base}/{role}"
        out.append((f"{prefix}/pose3d.json", work / "part2" / "pose3d.json"))
        if work.is_dir() and not (private and role == FEEDBACK_ROLE):
            out += [(f"{prefix}/{path.name}", path) for path in sorted(work.glob("*.json"))]
    return [(name, path) for name, path in out if _plain(path)]


def _group_files(folder: Path, base: str) -> list[tuple[str, Path]]:
    """A group take's own outputs, for the account that made it (`_people_owner`, S-R3): the 3D joint positions of
    everyone chosen (`pose3d.json`), the trainer chain's skeleton, animation and key frames, and each person's analysis
    and replay. The people in the class are in the recording this account made and owns; nobody else's account
    data is (export-data.md "Group takes"). The clip is the people job's, listed there once."""
    work = folder / "work"
    out = [(f"{base}/pose3d.json", work / "part2" / "pose3d.json")]
    trainer = work / "trainer"
    out += [(f"{base}/trainer/{p.name}", p) for p in sorted(trainer.glob("*.json"))] if trainer.is_dir() else []
    people = work / "person"
    for person in sorted(people.iterdir()) if people.is_dir() else []:
        if person.is_dir() and not person.is_symlink():
            out += [(f"{base}/person/{person.name}/{name}", person / name) for name in ("analysis.json", "replay.json")]
    return out


def _people_files(ctx: Ctx) -> list[tuple[str, Path]]:
    """The people jobs the person made (DI-N1): the cut clip, the picture of each person, the tracks, and the raw
    upload; then every other upload still bound to the account."""
    out: list[tuple[str, Path]] = []
    for job_id, kind in upload_owner.jobs_of(ctx.state, ctx.user_id).items():
        if kind == "group":
            out += _group_files(ctx.jobs / job_id, f"group/{job_id}")
            continue
        if kind != "people":
            continue
        folder, base = ctx.jobs / job_id, f"people/{job_id}"
        out += [(f"{base}/{name}", folder / "work" / name) for name in ("clip.mp4", "tracks.json")]
        pictures = folder / "people"
        out += [(f"{base}/pictures/{p.name}", p) for p in sorted(pictures.glob("*.jpg"))] if pictures.is_dir() else []
        out += [(f"{base}/{p.name}", p) for p in _upload_files(ctx, history_store.read_json(folder / "job.json"))]
    listed = {path for _, path in out}
    for upload_id in upload_owner.uploads_of(ctx.state / "uploads", ctx.user_id):
        out += [(f"uploads/{upload_id}/{p.name}", p) for p in _upload_files(ctx, {"upload_id": upload_id}) if p not in listed]
    return [(name, path) for name, path in out if _plain(path)]


def media_files(ctx: Ctx, entry_ids: list[str] | None = None) -> list[tuple[str, Path]]:
    """`(name in the ZIP, file)` of every file Simon holds for the person: each take's files (`_take_files`), kept
    history copies, the files and label notes of the movements they recorded (`entry_ids`, default the identity
    store's), and the files of their models."""
    out: list[tuple[str, Path]] = []
    for take in ctx.store.takes_of(ctx.user_id):
        out += _take_files(ctx, take["job_id"])
    taken = {path for _, path in out}  # an upload a take already lists is not listed twice
    out += [(name, path) for name, path in _people_files(ctx) if path not in taken]
    for job_id, row in _kept_rows(ctx).items():
        base = f"history/{job_id}"
        if row.get("clip") is not None and _plain(row["clip"]):
            out.append((f"{base}/{history_store.CLIP_NAME}", row["clip"]))
        if not row.get("private") and _plain(row["analysis"]):
            out.append((f"{base}/{history_store.ANALYSIS_NAME}", row["analysis"]))
    catalog = Path(ctx.child.catalog_dir) if ctx.child is not None else None
    ids = entry_ids if entry_ids is not None else [e["entry_id"] for e in ctx.store.entries_of(ctx.user_id)]
    for entry_id in ids if catalog is not None else []:
        if not labels.ENTRY_ID_RE.match(entry_id):
            continue
        for name in ENTRY_FILES:
            path = catalog / entry_id / name
            if _plain(path):
                out.append((f"movements/{entry_id}/{name}", path))
        notes_file = ctx.state / "labels" / f"{entry_id}.json"  # the labels and notes the trainer gave the movement
        if _plain(notes_file):
            out.append((f"movements/{entry_id}/labels.json", notes_file))
    for rec in model_store.owned(ctx.state, f"u:{ctx.user_id}"):
        model_id = str(rec.get("id") or "")
        for name in MODEL_FILES if model_store.ID_RE.match(model_id) else ():
            path = model_store.root(ctx.state) / model_id / name
            if _plain(path):
                out.append((f"models/{model_id}/{name}", path))
    return out


def sweep_zips(folder: Path, now: float | None = None) -> int:
    """Remove ZIP files a download left behind (a crash between write and send) after ZIP_TMP_KEEP_S."""
    cutoff, gone = (time.time() if now is None else now) - ZIP_TMP_KEEP_S, 0
    for path in folder.glob(f"{ZIP_PREFIX}*") if folder.is_dir() else []:
        try:
            if path.stat().st_mtime <= cutoff:
                path.unlink()
                gone += 1
        except OSError:
            continue
    return gone


def write_zip(ctx: Ctx, target: Path, now: datetime | None = None, entry_ids: list[str] | None = None) -> int:
    """Write the ZIP download to `target` (the JSON file plus `media_files`); returns its size. `ExportError` when it
    cannot be built safely or the files exceed ZIP_MAX_BYTES; `target` is then removed."""
    data = build(ctx, now)
    files = media_files(ctx, entry_ids)
    total = sum(path.stat().st_size for _, path in files)
    if total > ZIP_MAX_BYTES:
        raise ExportError("the files are too large for one download")
    try:
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as out:
            out.writestr(filename(now), data)
            for name, path in files:
                out.write(path, name, compress_type=zipfile.ZIP_STORED if name.endswith(".mp4") else zipfile.ZIP_DEFLATED)
        os.chmod(target, 0o600)
        return target.stat().st_size
    except (OSError, zipfile.BadZipFile) as exc:
        target.unlink(missing_ok=True)
        raise ExportError(f"zip: {type(exc).__name__}") from exc
register("my_references", my_reference.export_rows)  # ADR-0019: which take is my reference per movement; no movement data
register("reference_approvals", reference_approval.export_rows)  # ADR-0019: approvals a teacher made or a student received; no movement data
