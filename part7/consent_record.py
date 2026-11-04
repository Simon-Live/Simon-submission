"""The consent and age answers a take carries (docs/specs/consent-and-age.md, LEG-C4, LEG-H1, HARDENING section 8).

The browser asks before the first capture or upload (web/consent-gate.js) and sends the answers with every job request
as `consent: {version, items, at}` and `age_band`. This module checks them and gives the job-record fields. Nothing here
is trusted as proof of age or identity: it records what the person answered, with the version of the text they saw.

Prod serves adults only at launch (`PROD_MIN_AGE`, operator decision 3 November 2026): a 13 to 17 answer is refused there as under 13
is, and kept on the account. Outside prod the 13 to 17 rules stay as they are; they still apply wherever `min_age()` is 13.

`required()` is true in prod (FIRM_ENV=prod) and when `SIMON7_CONSENT_GATE=on` (staging QA). When it is true, a job
request without the current version, without every required item, or with the under-13 band is refused.

The account keeps an under 13 answer (privacy PM-R5): `refusal(doc, h)` marks the signed-in account (identity
`mark_under13`) when its request answers under 13, and refuses every later job request of that account, whatever a
clean browser answers. Without `h` only the request is read.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from part7 import applog, prod_mode

# Bump on any change to the consent text in web/model/consent-text.js; the two must name the same version (tested).
VERSION = "2026-11-04.2"  # + the Meta tick is the account's and carries the 18 statement; web/model/consent-text.js: what goes to Meta and Baseten, for how long, and its own tick (muse-prod.md)
# Every item is a separate tick box; all are needed to record or upload (granular, nothing pre-ticked).
ITEMS = ("analysis", "biometric", "processors", "people_in_frame")
META_ADULTS = "meta_adults"  # the person says everyone filmed is 18 or over; Meta Model API Terms 10.1. Part of the Meta tick
META_ITEM = "meta"  # optional: unticked, Simon works and sends no video or frame to Meta on its own (docs/specs/muse-prod.md AC-MP5)
AGE_BANDS = ("adult", "minor", "under13")  # 18 and over, 13 to 17, under 13 (blocked)
MIN_AGE, ADULT_AGE = 13, 18
PROD_MIN_AGE = ADULT_AGE  # set to MIN_AGE to open prod to 13 to 17; the rules for that band stay in the code
UPLOAD_HEADER = "X-Simon-Consent"  # the consent version on POST api/uploads, before any job exists
GATE_ENV = "SIMON7_CONSENT_GATE"
_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z$")

MSG_CONSENT = "Agree to each point of the consent step before you record or upload."
MSG_STALE = "The consent text changed. Read it again and agree before you record or upload."
MSG_AGE = "Answer the age question before you record or upload."
MSG_UNDER13 = "Simon is not available to you."
MSG_STORE = "Simon cannot check your account right now. Try again in a minute."


def required() -> bool:
    """True in prod and when the staging QA switch is on."""
    return prod_mode.is_prod() or os.environ.get(GATE_ENV, "").strip().lower() == "on"


def min_age() -> int:
    """The youngest age this build serves."""
    return PROD_MIN_AGE if prod_mode.is_prod() else MIN_AGE


def _band_refused(band: Any) -> bool:
    return band == "under13" or (band == "minor" and min_age() >= ADULT_AGE)


def age_band(birth_year: int, birth_month: int, today: datetime | None = None) -> str:
    """The band for a birth year and month (1 to 12): the age in whole years, counted to the month. The day is not
    asked, so the birthday month counts as not yet reached (the younger answer protects a child)."""
    now = today or datetime.now(timezone.utc)
    years = now.year - birth_year - (1 if now.month <= birth_month else 0)
    return "under13" if years < MIN_AGE else "minor" if years < ADULT_AGE else "adult"


_ANY: Any = object()  # no request in hand (a plain read of the answers): the account stamp is not compared


def parse(doc: Mapping[str, Any], user: Any = _ANY) -> tuple[dict[str, Any] | None, str | None]:
    """`(record, None)` with the stored form of the answers, `(None, None)` when none were sent, `(None, message)` when
    the answers are malformed, out of date or incomplete."""
    raw, band = doc.get("consent"), doc.get("age_band")
    if raw is None and band is None:
        return None, None
    if band not in AGE_BANDS:
        return None, MSG_AGE
    if not isinstance(raw, dict):
        return None, MSG_CONSENT
    if raw.get("version") != VERSION:
        return None, MSG_STALE
    items = raw.get("items")
    if not isinstance(items, dict) or any(items.get(k) is not True for k in ITEMS):
        return None, MSG_CONSENT
    at = raw.get("at")
    # Every answer belongs to the account that gave it (B2): one stamped for another account, or for nobody while someone is signed in,
    # is refused like a missing one, so B cannot replay A's points. The browser asks the person again (consent-store setAccount).
    if user is not _ANY and (raw.get("account") or "") != (user or ""):
        return None, MSG_CONSENT
    # The Meta tick also needs the 18 statement (B3).
    meta = items.get(META_ITEM) is True and items.get(META_ADULTS) is True
    record = {"version": VERSION, "items": {**{k: True for k in ITEMS}, **({META_ITEM: True, META_ADULTS: True} if meta else {})},
              "at": at if isinstance(at, str) and _STAMP.match(at) else None, "age_band": band}
    return record, None


def meta_allowed(job_fields_doc: Mapping[str, Any]) -> bool:
    """True when a job may send video to Meta on its own: outside a gated build, or with the optional tick on this job's answers."""
    if not required():
        return True
    record = job_fields_doc.get("consent")
    return isinstance(record, dict) and isinstance(record.get("items"), dict) and record["items"].get(META_ITEM) is True and record["items"].get(META_ADULTS) is True


def account_refusal(h: Any, doc: Mapping[str, Any]) -> tuple[int, str] | None:
    """(403, MSG_UNDER13) when the signed-in caller's account keeps an under 13 answer, or this request gives one (then
    kept on the account first, PM-R5); None signed out or otherwise. 503 when the store cannot say (fails closed)."""
    from part7 import auth  # auth imports this module

    user = auth.current_user(h)
    if not user:
        return None
    try:
        store = auth.identity(h.app)
        if doc.get("age_band") == "under13":
            store.mark_under13(user)
            return 403, MSG_UNDER13
        if min_age() >= ADULT_AGE and (doc.get("age_band") == "minor" or store.is_minor(user)):
            store.mark_minor(user)
            return 403, MSG_UNDER13
        return (403, MSG_UNDER13) if store.is_under13(user) else None
    except Exception as exc:  # noqa: BLE001  an unknown answer is not an adult's
        applog.log(f"consent: could not read the age mark of an account ({type(exc).__name__})")
        return 503, MSG_STORE


def _request_user(h: Any) -> Any:
    """The signed-in user of the request (None signed out), or `_ANY` without a request."""
    if h is None:
        return _ANY
    from part7 import auth  # auth imports this module

    return auth.current_user(h)


def refusal(doc: Mapping[str, Any], h: Any = None) -> tuple[int, str] | None:
    """(status, message) when this job request must not start; None when it may. Outside a gated build only malformed
    answers are refused; missing answers are accepted as before. With the request handler `h` the account's kept
    under 13 answer is read and kept too (`account_refusal`, PM-R5)."""
    kept = account_refusal(h, doc) if h is not None else None
    if kept is not None:
        return kept
    record, problem = parse(doc, _request_user(h))
    if problem is not None:
        return (403, MSG_UNDER13) if _band_refused(doc.get("age_band")) else (400, problem)
    if record is None:
        return (400, MSG_CONSENT) if required() else None
    return (403, MSG_UNDER13) if _band_refused(record["age_band"]) else None


def job_fields(doc: Mapping[str, Any], user: Any = _ANY) -> dict[str, Any]:
    """The job-record fields: `{"consent": record}` (version and answers kept with the take), or `{}` when none. `user` is the
    signed-in account of the request: the Meta tick is kept only when it was made for that account."""
    record, problem = parse(doc, user)
    ok = record is not None and problem is None and record["age_band"] != "under13"
    return {"consent": record} if ok else {}


def upload_refusal(headers: Mapping[str, str] | Any) -> tuple[int, str] | None:
    """(status, message) for POST api/uploads in a gated build when the consent header does not name VERSION."""
    if not required():
        return None
    value = (headers.get(UPLOAD_HEADER) or "").strip() if headers is not None else ""
    if value == VERSION:
        return None
    return 400, (MSG_STALE if value else MSG_CONSENT)


def is_minor(job: Mapping[str, Any] | None) -> bool:
    """True when the take's consent says 13 to 17 (or under 13, which never gets this far): no public content, no name."""
    consent = (job or {}).get("consent")
    return isinstance(consent, dict) and consent.get("age_band") in ("minor", "under13")
