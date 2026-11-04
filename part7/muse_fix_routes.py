"""HTTP routes of 'You, doing it right' (docs/specs/muse-fix-ui.md, TICKET-280); `server.py` calls `handle`.

- `GET api/jobs/<id>/muse-fix`: `{eligible, consent, running, card, can_draw, image, referee}` for the card on the result page.
- `POST api/jobs/<id>/muse-fix` with `{"what": "image" | "referee"}`: starts `muse_fix.run` or the blind referee in a
  background thread (the re-measure waits up to 15 minutes on the GPU lock) and answers 202; the page polls the GET.
- `GET api/jobs/<id>/muse-fix/image`: the kept picture, from `work/muse-fix/`, owner-only.

Owner-only: 401 without a session, 404 for another user's job, an unknown id or anything but a finished follow take.
Consent is the owner's video consent (`history_store.consent`); without it POST answers 403 and nothing is read, sent or
written, and the GET carries no card. Private and rehab takes are never eligible (409 on POST, no card on GET).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from part7 import applog, history_store, jobs, muse_fix, muse_fix_inputs, muse_fix_measure, muse_prod
from part7.auth_routes import MSG_CSRF, MSG_SIGN_IN

MSG_GONE = "This take was not found."
MSG_CONSENT = "Allow Meta's AI models to see your video in your settings first. Nothing was sent."
MSG_TRAINER = "The trainer of this movement has not agreed to send their recording to Meta, so this is not available. Nothing was sent."
MSG_BODY = "Send what as image or referee."
MSG_INELIGIBLE = "This take cannot be used for this."
MSG_NEEDS_PICTURE = "Make the picture first."
MSG_NO_FAULT = "Simon draws elbows, knees, shoulders and hips, and this take has no fault there to draw. Nothing was sent."
_running: set[str] = set()
_guard = threading.Lock()


def active(job_id: str) -> bool:
    """True while a picture or referee run writes into the job's folder (the delete path waits for it)."""
    with _guard:
        return job_id in _running


def _user(h: Any) -> str | None:
    auth = history_store.optional_module("part7.auth")
    user = auth.current_user(h) if auth is not None else None
    return user if isinstance(user, str) and history_store.USER_ID_RE.match(user) else None


def _same_origin(h: Any) -> bool:
    auth = history_store.optional_module("part7.auth")
    return bool(auth is not None and auth.origin_ok(h))


def eligible(job: dict[str, Any]) -> bool:
    """A finished follow take that is neither private nor a rehab take (a group take has another kind)."""
    return job.get("kind") == "follow" and job.get("status") == "done" and not history_store.is_private(job) and job.get("mode") != "rehab"


def _trials(job_dir: Path) -> list[dict[str, Any]]:
    """This take's referee trials, as the page may show them: whether the model picked the corrected render. No seed, no key."""
    rows = muse_fix._read(muse_fix.folder(job_dir) / muse_fix.REFEREE_FILE)
    return [{"picked_corrected": r.get("picked_corrected"), "model": r.get("model")} for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _state(h: Any, job_id: str, user: str, job: dict[str, Any]) -> dict[str, Any]:
    job_dir = h.app.queue.job_dir(job_id)
    consent = history_store.consent(h.app.state, user)["video"]
    ok = (eligible(job) and muse_prod.status("muse_fix", user, h.app.state) is None  # muse-prod.md: no card that fails
          and muse_prod.trainer_video_allowed(h.app.state, str(job.get("entry_id") or "")))
    shown = consent and ok
    live = shown and muse_fix.DRAW_ENABLED  # switched off: an older picture is not shown either
    card = muse_fix.latest_card(job_dir) if live else None
    trials = _trials(job_dir) if live else []
    why = muse_fix.blocker()  # the switch, or a picture nobody can check: no button, and the true reason
    return {"eligible": ok, "consent": consent, "running": active(job_id), "card": card, "no_check": bool(shown and why),
            "no_check_reason": why if shown else None,
            "can_draw": bool(shown and not why and not (card and card.get("status") == "shown") and muse_fix.can_offer(job_dir)),
            "image": f"api/jobs/{job_id}/muse-fix/image" if card and card.get("status") == "shown" else None,
            "referee": {"mine": trials[-1] if trials else None, "summary": muse_fix.report(job_dir.parent)["referee"]}
            if shown and card and card.get("status") == "shown" else None}


def _work(job_id: str, fn: Any, job_dir: Path | None) -> None:
    try:
        fn()
    except Exception as exc:  # a worker fault must not leave the job marked busy or take the server down
        applog.log(f"muse-fix: {job_id} failed: {applog.cause(exc)}", level=logging.WARNING)
        if job_dir is not None:  # a picture press always ends in a record, so the card never goes quiet
            muse_fix.not_drawn(job_dir, "failed", "the worker stopped")
    finally:
        with _guard:
            _running.discard(job_id)


def _start(job_id: str, fn: Any, job_dir: Path | None = None) -> bool:
    with _guard:
        if job_id in _running:
            return False
        _running.add(job_id)
    threading.Thread(target=_work, args=(job_id, fn, job_dir), daemon=True, name=f"muse-fix-{job_id}").start()
    return True


def _post(h: Any, job_id: str, user: str, job: dict[str, Any]) -> None:
    raw = str(h.headers.get("Content-Length") or "")
    doc = h._body_json() if raw.isascii() and raw.isdigit() and 0 < len(raw) <= 4 and 0 < int(raw) <= 1024 else None
    what = doc.get("what") if isinstance(doc, dict) else None
    if what not in ("image", "referee"):
        return h._error(400, MSG_BODY)
    if not history_store.consent(h.app.state, user)["video"]:
        return h._error(403, MSG_CONSENT, code="consent_needed")
    if not eligible(job):
        return h._error(409, MSG_INELIGIBLE)
    job_dir, state, entry = h.app.queue.job_dir(job_id), h.app.state, str(job.get("entry_id") or "")
    if not muse_prod.trainer_video_allowed(state, entry):  # muse-prod.md AC-MP11: the picture is measured against the trainer's body
        return h._error(403, MSG_TRAINER, code="trainer_no_tick")
    if what == "image" and not muse_fix.can_offer(job_dir):  # before the admission: nothing was asked of Meta, so no limit is touched
        return h._error(409, MSG_NO_FAULT, code="no_fault_to_draw")
    why = muse_fix.blocker() if what == "image" else (muse_fix.SWITCHED_OFF if not muse_fix.DRAW_ENABLED else None)  # R14b B4: the switch covers both asks
    if why is None and what == "image" and not muse_fix_measure.reachable():  # R1: Modal stopped, so nothing is paid and nothing is recorded
        why = muse_fix.NO_ROUTE
    if why is not None:
        return h._error(409, why, code="no_check")
    closed = muse_prod.admit("muse_fix", user, state)
    if closed is not None:
        return h._error(closed.status, closed.message, code=closed.code)
    if what == "image":
        _start(job_id, lambda: muse_fix.run(job_dir, consent=muse_prod.video_allowed(state, user, entry), state=state, probe=False), job_dir)
    else:
        card = muse_fix.latest_card(job_dir)
        if not card or card.get("status") != "shown":
            return h._error(409, MSG_NEEDS_PICTURE)

        def trial() -> None:
            images = muse_fix_inputs.referee_images(job_dir.parent, job_dir)
            muse_fix.referee(job_dir, *images, consent=muse_prod.video_allowed(state, user, entry), state=state)

        _start(job_id, trial)
    h._send(202, b'{"running": true}', "application/json; charset=utf-8", {"Retry-After": "3"})


def _image(h: Any, job_id: str, user: str, job: dict[str, Any]) -> None:
    card = (muse_fix.latest_card(h.app.queue.job_dir(job_id))
            if muse_fix.DRAW_ENABLED and eligible(job) and history_store.consent(h.app.state, user)["video"] else None)
    path = muse_fix.folder(h.app.queue.job_dir(job_id)) / str(card["image"]) if card and card.get("status") == "shown" else None
    if path is None or path.is_symlink() or not path.is_file():
        return h._error(404, MSG_GONE)
    kind = "image/png" if path.suffix == ".png" else "image/jpeg"
    h._send(200, path.read_bytes(), kind, {"Cache-Control": "private, no-store"})


def handle(h: Any, method: str, route: str) -> bool:
    """Answer the routes above; False for any other route."""
    parts = route.split("/")
    if not (len(parts) in (3, 4) and parts[0] == "jobs" and parts[2] == "muse-fix" and (len(parts) == 3 or parts[3] == "image")):
        return False
    user = _user(h)
    if user is None:
        h._error(401, MSG_SIGN_IN)
        return True
    job = h.app.queue.get(parts[1]) if jobs.JOB_ID_RE.match(parts[1]) else None
    if job is None or job.get("kind") != "follow" or job.get("status") != "done" or history_store.owner_of(h.app.state, parts[1]) != user:
        h._error(404, MSG_GONE)
    elif method in ("GET", "HEAD") and len(parts) == 4:
        _image(h, parts[1], user, job)
    elif method in ("GET", "HEAD"):
        h._json(200, _state(h, parts[1], user, job))
    elif method == "POST" and len(parts) == 3 and not _same_origin(h):
        h._error(403, MSG_CSRF, code="forbidden_origin")
    elif method == "POST" and len(parts) == 3:
        _post(h, parts[1], user, job)
    else:
        h._error(405, "Method not allowed.")
    return True

