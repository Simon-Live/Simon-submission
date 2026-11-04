"""HTTP routes of share links (docs/specs/share.md): `POST api/shares`, `GET api/me/shares`,
`DELETE api/me/shares/<token_hash>` (owner only, 401 signed out, 404 for another person's) and the public
`GET api/shared/<token>` (+ `/clip.mp4`). `server.py` calls `handle(h, method, route)` with `route` below `api/`.

The viewer answers one generic 404 for a bad or unknown token, and a plain 410 line for a token this server signed whose
link expired or was stopped; it carries nothing but the snapshot.

No share link of any kind for someone under 18 (privacy PM-B1, TICKET-233): the create and the preview answer 403 when
the caller's account is marked 13 to 17, or owns a take or movement that is, or the take itself carries that answer
(`trainer_publish.minor_refused`); marking an account ends its live links (identity `mark_minor`).
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from part7 import (applog, attribution, auth, history_report, history_store, identity as ident, jobs, labels, model_only, progress_sheet,
                   result_media, share, shown_score, source_routes, trainer_publish)
from part7.auth_routes import MSG_CSRF, MSG_SIGN_IN, _post_body, _reply

MSG_GONE = "This link is not available."
MSG_EXPIRED = "This link has expired."
MSG_REVOKED = "This link was stopped by the person who shared it."
MSG_NO_ITEM = "There is nothing here to share."
MSG_NO_REPORT = "Make a comparison of your takes first, then share it."
MSG_NO_SHEET = "There are no measured sessions to share yet."
MSG_NO_CLIP = "This take has no kept clip to share."
MSG_CONFIRM = "Confirm what the link will show."
MSG_BAD = "The request is not valid."
MSG_RATE = "Too many tries. Wait a little, then try again."
MSG_MINOR = "Share links are off for anyone under 18."
VIEW_HEADERS = {"X-Robots-Tag": "noindex", "Referrer-Policy": "no-referrer"}
VIEW_PER_IP = (60, 600)
FAULTS_MAX = 5
TICKS = ("score", "faults")
_VIEW_LIMIT: dict[int, auth.Limiter] = {}


def _limiter(app: Any) -> auth.Limiter:
    return _VIEW_LIMIT.setdefault(id(app), auth.Limiter(*VIEW_PER_IP))


def _gone(h: Any) -> None:
    _reply(h, 404, {"ok": False, "error": MSG_GONE, "message": MSG_GONE}, VIEW_HEADERS)


def _ended(h: Any, why: str) -> None:
    message = MSG_EXPIRED if why == "expired" else MSG_REVOKED
    _reply(h, 410, {"ok": False, "error": message, "message": message, "ended": why}, VIEW_HEADERS)


def _fail(h: Any, status: int, message: str) -> None:
    _reply(h, status, {"ok": False, "error": message, "message": message})


def _day(value: Any) -> str | None:
    return value[:10] if isinstance(value, str) and len(value) >= 10 else None


def _author(db: ident.IdentityStore, owner: str, show_name: bool) -> str | None:
    """The owner's public name when they opted in for this share and their profile has one (never an email)."""
    if not show_name:
        return None
    try:
        profile = importlib.import_module("part7.profile")
        name = profile.public_identity(db, owner).get("name")
    except Exception:  # no profile module yet, or a store fault: the share simply carries no name
        return None
    return name if isinstance(name, str) and name else None


def _attribution(h: Any, store: ident.IdentityStore, owner: str, show_name: bool, kind: str, ref: str) -> dict[str, Any]:
    """The snapshot's author line (docs/specs/attribution.md): the name only when the share chose it and the profile allows it."""
    job = h.app.queue.get(ref) if kind == "take_result" else None
    entry_id = (job or {}).get("entry_id") if kind == "take_result" else ref
    try:
        line = attribution.author_line(store, attribution.take_subject(store, ref if job else None, entry_id, owner))
    except Exception:  # a lookup fault leaves the line nameless, never the share broken
        return {"kind": "take", "author": None, "trainer_credit": None, "mine": False}
    if not show_name:
        line["author"] = None
    return {"kind": "take", **line, "mine": False}


def _entry_of_job(state: Any, owner: str, job_id: str) -> str | None:
    for entry in history_store.entries(state, owner):
        if any(t["job_id"] == job_id for t in history_store.takes(state, owner, entry)):
            return entry
    return None


def _take_snapshot(h: Any, owner: str, job_id: Any, want_clip: bool) -> tuple[dict[str, Any], bool]:
    """The take result as it is now; 404 `None` when it is not the caller's. Returns (snapshot, clip kept)."""
    if not isinstance(job_id, str) or not jobs.JOB_ID_RE.match(job_id) or ident.owner_of_job(h.app.state, job_id) != owner:
        raise LookupError(MSG_NO_ITEM)
    job = h.app.queue.get(job_id)
    analysis = history_store.read_json(h.app.queue.job_dir(job_id) / "work" / "follower" / "analysis.json")
    score = analysis.get("score") if isinstance(analysis, dict) else None
    if not job or not isinstance(score, dict) or not isinstance(score.get("value"), (int, float)):
        raise LookupError(MSG_NO_ITEM)
    faults = [f["text"] for f in analysis.get("faults", []) if isinstance(f, dict) and isinstance(f.get("text"), str)][:FAULTS_MAX]
    clip = False
    if want_clip and model_only.kept(job) and not model_only.view_only(job):  # a model-only take never carries a clip: the tick is ignored, not an error
        entry = _entry_of_job(h.app.state, owner, job_id)
        take = next((t for t in history_store.takes(h.app.state, owner, entry) if t["job_id"] == job_id), None) if entry else None
        clip = bool(take and take["clip"] and not take["private"])
        if not clip:
            raise ValueError(MSG_NO_CLIP)
    return {"title": labels.entry_name(h.app.child, job.get("entry_id", h.app.state) or ""), "score": score["value"], "grade": score.get("grade"),
            "result": _result_block(analysis, job), "faults": faults, "on": _day(job.get("finished_at") or job.get("created_at"))}, clip


_SCORE_KEYS = ("value", "grade", "uncapped", "capped_by", "fault_cap", "basis")
_CREDIT_KEYS = ("version", "percent", "grade", "grades", "points", "max_points", "tolerance", "bands", "points_per_measure_second")


def _display(doc: Any) -> dict[str, str] | None:
    """The owner's saved score unit and level (web/score-display.js), only known values; anything else is left out."""
    if not isinstance(doc, dict):
        return None
    out = {k: doc[k] for k, ok in (("mode", ("points", "percent")), ("level", ("easy", "normal", "hard"))) if doc.get(k) in ok}
    return out or None


def _pick(doc: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: doc[k] for k in keys if isinstance(doc, dict) and k in doc}


def _result_block(analysis: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    """What the result screen draws its score, cap and warning from (docs/specs/share.md, "Score and cap"), so the
    viewer runs the result's own code on it: the score with its cap fields and credit (no per-window detail), the
    warnings, the quality and match blocks the caps read, Part 7's light level and the practice mode. Nothing else."""
    raw = analysis["score"]
    score = _pick(raw, _SCORE_KEYS)
    if isinstance(raw.get("credit"), dict):
        score["credit"] = _pick(raw["credit"], _CREDIT_KEYS)
    quality = analysis.get("quality")
    out: dict[str, Any] = {
        "score": score,
        "warnings": [_pick(w, ("code", "text", "tip", "cause")) for w in analysis.get("warnings") or [] if isinstance(w, dict)],
        "mode": job.get("mode") if isinstance(job.get("mode"), str) else None,
    }
    if isinstance(quality, dict):
        out["quality"] = {**_pick(quality, ("level", "score_cap", "reasons")),
                          "issues": [_pick(i, ("code", "impact", "text", "tip")) for i in quality.get("issues") or [] if isinstance(i, dict)]}
    if isinstance(analysis.get("match"), dict):
        out["match"] = _pick(analysis["match"], ("quality",))
    if isinstance(analysis.get("status"), dict):
        out["status"] = _pick(analysis["status"], ("code", "text"))
    light = (job.get("result") or {}).get("light") if isinstance(job.get("result"), dict) else None
    if isinstance(light, dict) and isinstance(light.get("level"), str):
        out["light"] = {"level": light["level"]}
    return out


def _ticked(snap: dict[str, Any], ticks: dict[str, bool]) -> dict[str, Any]:
    """The snapshot with only the parts the owner ticked: an unticked part is never stored, so it cannot reach a viewer."""
    kept = {k: v for k, v in snap.items() if not ((k in ("score", "grade", "result") and not ticks["score"]) or (k == "faults" and not ticks["faults"]))}
    return {**kept, "include": dict(ticks)}


def _report_snapshot(h: Any, owner: str, entry: Any) -> dict[str, Any]:
    if not isinstance(entry, str) or not labels.ENTRY_ID_RE.match(entry) or not history_store.takes(h.app.state, owner, entry):
        raise LookupError(MSG_NO_ITEM)
    runner = history_report.runner_for(h.app.state, h.app.child.catalog_dir)
    _, key, _ = runner.plan(owner, entry)
    doc = history_report.cached(h.app.state, owner, entry, key)
    if doc is None:
        raise LookupError(MSG_NO_REPORT)
    summary = doc.get("summary") if isinstance(doc.get("summary"), dict) else {}
    trends = [t["text"] for t in doc.get("trends", []) if isinstance(t, dict) and isinstance(t.get("text"), str)]
    return {"title": labels.entry_name(h.app.child, entry, h.app.state), "summary": summary.get("text"), "trends": trends, "takes": _report_rows(doc)}


def _report_rows(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The report's takes for a viewer: number, day, score, grade, and the shown score (one-letter.md) when the report
    has it (a report cached before the block has none; the viewer then shows score and grade)."""
    return [{"take": t.get("take"), "on": _day(t.get("at")), "score": t.get("score"), "grade": t.get("grade"),
             **({"shown": _pick(t["shown"], shown_score.PUBLIC_KEYS)} if isinstance(t.get("shown"), dict) else {})}
            for t in doc.get("takes", []) if isinstance(t, dict)]


def _sheet_snapshot(h: Any, owner: str, entry: Any) -> dict[str, Any]:
    """TICKET-283: the progress sheet as it is now, without the entry id or any job id, and with no video."""
    if not isinstance(entry, str) or not labels.ENTRY_ID_RE.match(entry):
        raise LookupError(MSG_NO_ITEM)
    sheet = progress_sheet.build(h.app.state, owner, entry, labels.entry_name(h.app.child, entry, h.app.state))
    if sheet is None:
        raise LookupError(MSG_NO_SHEET)
    return progress_sheet.public(sheet)


def _prepare(h: Any, owner: str, doc: dict[str, Any]) -> tuple[dict[str, Any], bool] | None:
    """The snapshot a share would hold (and whether its clip is kept), or None after the error answer has been sent.
    The one builder for both the real share and the owner's preview, so the preview shows what a viewer will get."""
    kind = doc.get("kind")
    show_name, show_clip = doc.get("show_name") is True, doc.get("show_clip") is True
    ticks = {k: doc.get(f"include_{k}", True) for k in TICKS}  # score and faults are on unless the person unticked them
    ref = doc.get("item_ref")
    job = h.app.queue.get(ref) if kind == "take_result" and isinstance(ref, str) and jobs.JOB_ID_RE.match(ref) else None
    if kind not in share.OFFERED_KINDS:
        _fail(h, 400, share.MSG_KIND)
    elif not all(isinstance(v, bool) for v in ticks.values()):
        _fail(h, 400, MSG_BAD)
    elif trainer_publish.minor_refused(h, owner, job):  # PM-B1: every kind, before anything is read or built
        _fail(h, 403, MSG_MINOR)
    else:
        try:
            if kind == "take_result":
                snap, clip = _take_snapshot(h, owner, doc.get("item_ref"), show_clip)
                snap = _ticked(snap, ticks)
                display = _display(doc.get("score_display"))
                if display and "result" in snap:  # the owner's points or % choice, so the link shows the result's unit
                    snap["result"]["display"] = display
            elif kind == "progress_sheet":
                snap, clip = _sheet_snapshot(h, owner, doc.get("item_ref")), False
            else:
                snap, clip = _report_snapshot(h, owner, doc.get("item_ref")), False
            store = auth.identity(h.app)
            snap["author"] = _author(store, owner, show_name)
            snap["attribution"] = _attribution(h, store, owner, show_name, kind, doc["item_ref"])
            snap["clip"] = clip
            return snap, clip
        except LookupError as exc:
            _fail(h, 404, str(exc))
        except ValueError as exc:
            _fail(h, 400, str(exc))
    return None


def _create(h: Any, owner: str) -> None:
    doc = _post_body(h)
    if doc is None:
        return
    if doc.get("confirm") is not True:
        return _fail(h, 400, MSG_CONFIRM)
    made = _prepare(h, owner, doc)
    if made is None:
        return
    snap, clip = made
    store = auth.identity(h.app)
    try:
        token = share.create_share(store, owner, doc["kind"], doc["item_ref"], doc.get("show_name") is True, clip, doc.get("days", 7), snapshot=snap)
    except share.ShareError as exc:
        return _fail(h, exc.status, str(exc))
    applog.log("share: created", level=logging.INFO)  # the token, the name and the text are never logged
    _reply(h, 201, {"token": token, "id": share.token_hash(token), "path": f"#/shared/{token}",
                    "expires_utc": share.resolve(store, token)["expires_utc"]})  # `id` lets the maker delete it (TICKET-283)


def _preview(h: Any, owner: str) -> None:
    """`POST api/shares/preview`: the snapshot the same body would make, nothing stored. The clip is a flag, never a URL."""
    doc = _post_body(h)
    made = _prepare(h, owner, doc) if doc is not None else None
    if made is not None:
        _reply(h, 200, {**made[0], "kind": doc["kind"], "clip": None, "clip_included": made[1]})


def _owner_routes(h: Any, method: str, parts: list[str]) -> None:
    owner = auth.current_user(h)
    if owner is None:
        return _fail(h, 401, MSG_SIGN_IN)
    store = auth.identity(h.app)
    if method == "GET" and len(parts) == 2:
        return _reply(h, 200, {"shares": share.list_for_owner(store, owner)})
    if method == "DELETE" and len(parts) == 2:  # "Revoke all": every share of this owner, effective on the next request
        if not auth.origin_ok(h):
            return _fail(h, 403, MSG_CSRF)
        return _reply(h, 200, {"revoked": share.revoke_all(store, owner)})
    if method == "DELETE" and len(parts) == 3:
        if not auth.origin_ok(h):
            return _fail(h, 403, MSG_CSRF)
        if not share.revoke(store, owner, parts[2]):
            return _fail(h, 404, MSG_NO_ITEM)
        return _reply(h, 200, {"revoked": True})
    _fail(h, 405, "Method not allowed.")


def _viewer(h: Any, method: str, parts: list[str]) -> None:
    if method not in ("GET", "HEAD"):
        return _fail(h, 405, "Method not allowed.")
    if not _limiter(h.app).hit(auth.client_key(h)):
        return _reply(h, 429, {"ok": False, "error": MSG_RATE, "message": MSG_RATE}, VIEW_HEADERS)
    if not ident.db_path(h.app.state).is_file():
        return _gone(h)
    store = auth.identity(h.app)
    token = parts[1]
    if len(parts) == 3:
        return _clip(h, store, token) if parts[2] == "clip.mp4" else _gone(h)
    snap = share.resolve(store, token)
    if snap is None:
        why = share.ended(store, token)
        return _ended(h, why) if why else _gone(h)
    if snap.get("clip"):
        snap["clip"] = f"api/shared/{token}/clip.mp4"
    else:
        snap["clip"] = None
    snap["source"] = source_routes.for_share(h, store, token)  # TICKET-322: title, creator, licence and link of the take, or None
    _reply(h, 200, snap, VIEW_HEADERS)


def _clip(h: Any, store: ident.IdentityStore, token: str) -> None:
    grant = share.clip_grant(store, token)
    entry = _entry_of_job(h.app.state, *grant) if grant else None
    take = next((t for t in history_store.takes(h.app.state, grant[0], entry) if t["job_id"] == grant[1]), None) if entry else None
    if take is None or take["clip"] is None or take["private"]:
        return _gone(h)
    result_media.serve_file(h, take["clip"])


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `route` (below `api/`) when it is a share route; False when it is not."""
    parts = route.split("/")
    if parts[0] == "shared" and len(parts) in (2, 3):
        _viewer(h, method, parts)
        return True
    if parts == ["shares"]:
        if method != "POST":
            _fail(h, 405, "Method not allowed.")
        elif (owner := auth.current_user(h)) is None:
            _fail(h, 401, MSG_SIGN_IN)
        else:
            _create(h, owner)
        return True
    if parts == ["shares", "preview"]:
        if method != "POST":
            _fail(h, 405, "Method not allowed.")
        elif (owner := auth.current_user(h)) is None:
            _fail(h, 401, MSG_SIGN_IN)
        else:
            _preview(h, owner)
        return True
    if parts[:2] == ["me", "shares"] and len(parts) in (2, 3):
        _owner_routes(h, method, parts)
        return True
    return False
