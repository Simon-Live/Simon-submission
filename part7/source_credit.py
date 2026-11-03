"""Source and licence credit of an entry or a take: rules and store (docs/specs/source-credit.md; TICKET-322).

A clip that comes from a dataset or a stock site needs a visible credit: title, creator, licence and a link to the
source. The owner of an entry or a take writes it; every viewer sees it unless the entry is "only me" or the take is
private. Rows live in the `source_credits` table of identity.db (`store` below is the `IdentityStore`). The licence
names are the ones the curated library uses (`part7.videos`), plus the person's own recording and "Other".
"""

from __future__ import annotations

import datetime
import re
import sqlite3
from typing import Any
from urllib.parse import urlsplit, urlunsplit
import unicodedata

import idna

from part7 import videos

KINDS = ("entry", "take")
OWN = "own recording"
OTHER = "Other"
LICENCES = ("CC BY 4.0", videos.PEXELS_LICENCE, videos.PIXABAY_LICENCE, "CC0", OWN, OTHER)
TEXT_MAX, OTHER_MAX, URL_MAX = 120, 80, 500
ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
LABEL_OWN = "Own recording (no licence needed)"
# The official page of each licence that has one (B1): a CC BY credit must link its licence.
LICENCE_URLS = {
    "CC BY 4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC0": "https://creativecommons.org/publicdomain/zero/1.0/",
    videos.PEXELS_LICENCE: "https://www.pexels.com/license/",
    videos.PIXABAY_LICENCE: "https://pixabay.com/service/license-summary/",
}

MSG_BAD = "Send the source as text fields."
MSG_LICENCE = "Choose a licence from the list."
MSG_NEED_LICENCE = "Choose a licence for this source."
MSG_OTHER = "Name the licence in 1 to 80 characters of plain text."
MSG_TEXT = "Use plain text on one line, at most 120 characters, with no hidden characters."
MSG_URL = "Use a web address that starts with https://, has no port number and is at most 500 characters."
MSG_FIELDS = "Give a title, a creator or a web address."

_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_credits (
  kind TEXT NOT NULL CHECK (kind IN ('entry', 'take')), subject_id TEXT NOT NULL, owner_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '', creator TEXT NOT NULL DEFAULT '', licence TEXT NOT NULL, licence_other TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL DEFAULT '', updated_utc TEXT NOT NULL, PRIMARY KEY (kind, subject_id));
CREATE INDEX IF NOT EXISTS source_credits_owner ON source_credits (owner_id);
"""


class SourceError(ValueError):
    """A field the person sent is not acceptable; `str(exc)` is the one plain sentence shown to them (HTTP 400)."""


def migrate(conn: sqlite3.Connection) -> None:
    """Add the `source_credits` table. Additive and idempotent: it changes no existing table, so no backup copy is needed."""
    conn.executescript(_SCHEMA)


def _hidden_char(text: str) -> bool:
    """True when `text` holds a control (Cc) or format (Cf) character: line breaks, bidi overrides, zero-width marks."""
    return any(unicodedata.category(c) in ("Cc", "Cf") for c in text)


def _text(raw: Any, limit: int, message: str = MSG_TEXT) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise SourceError(message)
    text = unicodedata.normalize("NFKC", raw).strip()
    if len(text) > limit or _hidden_char(text):
        raise SourceError(message)
    return text


def _ascii_host(host: str) -> str:
    """The host in ASCII. UTS 46 mapping (the `idna` package) keeps "faß.de" as "xn--fa-hia.de" and folds case and width.
    Raises `idna.IDNAError` (a UnicodeError) for a host that cannot be encoded; the caller refuses the address."""
    return idna.encode(host, uts46=True).decode("ascii")


def clean_url(raw: Any) -> str:
    """The source address, or "" when none. https only: javascript:, data:, http: and every other scheme are refused, as are
    a missing host, a user name or password, spaces, control and format characters, and any port number. The host
    is stored in its ASCII (IDNA) form so what a viewer reads is what the link opens."""
    if raw is None or raw == "":
        return ""
    if not isinstance(raw, str):
        raise SourceError(MSG_URL)
    text = raw.strip()
    if not text or len(text) > URL_MAX or _hidden_char(text) or any(c.isspace() for c in text):
        raise SourceError(MSG_URL)
    try:
        parts = urlsplit(text)
        host, port = parts.hostname, parts.port
        ascii_host = _ascii_host(host) if host else ""
    except (ValueError, UnicodeError) as exc:
        raise SourceError(MSG_URL) from exc
    if parts.scheme.lower() != "https" or not ascii_host or "@" in parts.netloc or "." not in ascii_host or port is not None:
        raise SourceError(MSG_URL)
    return urlunsplit(("https", ascii_host, parts.path, parts.query, parts.fragment))


def clean(doc: Any) -> dict[str, str] | None:
    """The checked fields `{title, creator, licence, licence_other, url}`, or None when every field is empty (that clears
    the source). Raises `SourceError` with one plain sentence."""
    if not isinstance(doc, dict):
        raise SourceError(MSG_BAD)
    title, creator = _text(doc.get("title"), TEXT_MAX), _text(doc.get("creator"), TEXT_MAX)
    licence, url = _text(doc.get("licence"), TEXT_MAX), clean_url(doc.get("url"))
    other = _text(doc.get("licence_other"), OTHER_MAX, MSG_OTHER)
    if not (title or creator or licence or url or other):
        return None
    if not licence:
        raise SourceError(MSG_NEED_LICENCE)
    if licence not in LICENCES:
        raise SourceError(MSG_LICENCE)
    if licence == OTHER and not other:
        raise SourceError(MSG_OTHER)
    if not (title or creator or url):
        raise SourceError(MSG_FIELDS)
    return {"title": title, "creator": creator, "licence": licence, "licence_other": other if licence == OTHER else "", "url": url}


def public(row: Any) -> dict[str, str]:
    """The fields a viewer receives. `licence_label` is the licence as shown ("Other" shows the person's words)."""
    other, licence = row["licence_other"], row["licence"]
    label = other if licence == OTHER and other else LABEL_OWN if licence == OWN else licence
    return {"title": row["title"], "creator": row["creator"], "licence": licence, "licence_other": other,
            "licence_label": label, "licence_url": LICENCE_URLS.get(licence, ""), "url": row["url"]}


def get(store: Any, kind: str, subject_id: str) -> dict[str, str] | None:
    rows = store.fetch("SELECT * FROM source_credits WHERE kind = ? AND subject_id = ?", (kind, subject_id))
    return public(rows[0]) if rows else None


def put(store: Any, kind: str, subject_id: str, owner_id: str, fields: dict[str, str] | None) -> dict[str, str] | None:
    """Store (or, with None, remove) the source of one subject; returns what is now stored."""
    if fields is None:
        store.write("DELETE FROM source_credits WHERE kind = ? AND subject_id = ?", (kind, subject_id))
        return None
    now = datetime.datetime.fromtimestamp(store.clock(), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    store.write("INSERT OR REPLACE INTO source_credits (kind, subject_id, owner_id, title, creator, licence, licence_other, url, updated_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kind, subject_id, owner_id, fields["title"], fields["creator"], fields["licence"], fields["licence_other"],
                 fields["url"], now))
    return get(store, kind, subject_id)


def export_rows(ctx: Any) -> list[dict[str, Any]]:
    """The person's own sources for "Download my data": per entry or take the movement and the fields. No user id."""
    out = []
    takes = {t["job_id"]: t["entry_id"] for t in ctx.store.takes_of(ctx.user_id)}
    for row in ctx.store.fetch("SELECT * FROM source_credits WHERE owner_id = ? ORDER BY kind, updated_utc, subject_id", (ctx.user_id,)):
        entry = row["subject_id"] if row["kind"] == "entry" else takes.get(row["subject_id"])
        out.append({"kind": row["kind"], "id": row["subject_id"], "movement": ctx.movement(entry) if entry else None,
                    **public(row), "updated": row["updated_utc"]})
    return out
