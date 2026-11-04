"""Search, filter, sort and page the catalog list (docs/specs/catalog-search.md, TICKET-440). Pure: no HTTP, no disk.

`parse(query)` turns the query string into a `Query` or raises `SearchError` (one plain line, HTTP 400). `run(rows,
query)` filters, counts the facets, sorts and cuts one page. A row is built by `row(entry, ...)` from a Part 6 manifest
and what Part 7 knows beside it (labels, credit, owner, takes, boards). Matching never builds a pattern from input:
the text is folded, split into terms and each term is a plain substring test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Any, Iterable
from urllib.parse import parse_qsl
import unicodedata

TYPES = ("exercise", "dance", "rehab")
SORTS = ("relevance", "newest", "popular", "title", "duration")
DURATIONS = ("short", "medium", "long")
UNKNOWN = "unknown"  # a movement with no duration_ms: in no bucket, listed last by the duration sort
HAS = ("video", "model", "board")
PER_PAGES = (12, 24, 48)
PER_PAGE_DEFAULT = 24
SHORT_MS, LONG_MS = 15_000, 45_000  # short under 15 s, long over 45 s, medium between (both ends in)
Q_MAX, TERMS_MAX, TERM_MAX = 100, 8, 64
TAGS_MAX = 8
PAGE_MAX = 100_000
TAG_FACETS = 20  # the tags offered as facets: the most used
KNOWN = {"q", "type", "sort", "tag", "duration", "has", "mine", "page", "per_page", "profile", "level", "_"}
TAG_RE = re.compile(r"^[a-z0-9-]{1,24}$")

MSG_ONCE = "Send each option once."
MSG_Q = f"Search text is at most {Q_MAX} characters."
MSG_LEVEL = "This catalog has no level to filter by."
MSG_REHAB = "Rehab is not offered here."


class SearchError(ValueError):
    """The query is not acceptable; `str(exc)` is the one plain line shown (HTTP 400)."""


@dataclass(frozen=True)
class Query:
    terms: tuple[str, ...] = ()
    types: frozenset[str] = frozenset()
    tags: frozenset[str] = frozenset()
    durations: frozenset[str] = frozenset()
    has: frozenset[str] = frozenset()
    mine: bool = False
    sort: str = "newest"
    page: int = 1
    per_page: int = PER_PAGE_DEFAULT
    submission: bool | None = None


@dataclass
class Row:
    """One catalog movement as the search sees it."""

    entry: dict[str, Any]
    types: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    duration: str = UNKNOWN
    has: frozenset[str] = frozenset()
    mine: bool = False
    takes: int = 0
    title: str = ""
    credit: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def fold(text: Any) -> str:
    """Case-insensitive, accent-insensitive form of `text` (NFKC, then casefold)."""
    return unicodedata.normalize("NFKC", str(text or "")).casefold()


def _single(pairs: list[tuple[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in pairs:
        if key in out:
            raise SearchError(MSG_ONCE)
        out[key] = value
    return out


def _words(raw: str | None, allowed: Iterable[str], label: str) -> frozenset[str]:
    if not raw:
        return frozenset()
    found = [w.strip().lower() for w in raw.split(",") if w.strip()]
    bad = [w for w in found if w not in allowed]
    if bad:
        raise SearchError(f"Unknown {label}: {bad[0][:24]}. Use {', '.join(allowed)}.")
    return frozenset(found)


def _int(raw: str | None, default: int, label: str, high: int) -> int:
    if raw is None or raw == "":
        return default
    if not raw.isascii() or not raw.isdigit() or len(raw) > len(str(high)) or not 1 <= int(raw) <= high:  # length first: int() refuses a very long string
        raise SearchError(f"{label} must be a whole number from 1 to {high}.")
    return int(raw)


def terms_of(text: str) -> tuple[str, ...]:
    """The search terms of `text`: folded, split on spaces, at most `TERMS_MAX` of up to `TERM_MAX` characters."""
    found = [t for t in fold(text).split() if t]
    if len(found) > TERMS_MAX or any(len(t) > TERM_MAX for t in found):
        raise SearchError(f"Search for at most {TERMS_MAX} words of {TERM_MAX} characters each.")
    return tuple(dict.fromkeys(found))


def parse(query: str, rehab_on: bool = True) -> Query:
    """The `Query` of a query string. `rehab_on` False refuses `type=rehab` (the prod `rehab` switch is off)."""
    try:
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=False, max_num_fields=40)
    except ValueError as exc:
        raise SearchError("The options could not be read.") from exc
    given = _single(pairs)
    if "level" in given:
        raise SearchError(MSG_LEVEL)
    unknown = [k for k in given if k not in KNOWN]
    if unknown:
        raise SearchError(f"Unknown option: {unknown[0][:24]}.")
    text = given.get("q", "")
    if len(text) > Q_MAX:
        raise SearchError(MSG_Q)
    terms = terms_of(text)
    types = _words(given.get("type"), TYPES, "type")
    if "rehab" in types and not rehab_on:
        raise SearchError(MSG_REHAB)
    tags = frozenset(t.strip().lower() for t in (given.get("tag") or "").split(",") if t.strip())
    if len(tags) > TAGS_MAX or any(not TAG_RE.match(t) for t in tags):
        raise SearchError("A tag is letters, digits and hyphens, up to 24 characters; give up to 8.")
    sort = (given.get("sort") or ("relevance" if terms else "newest")).strip().lower()
    if sort not in SORTS:
        raise SearchError(f"Unknown sort: {sort[:24]}. Use {', '.join(SORTS)}.")
    mine = given.get("mine", "")
    if mine not in ("", "0", "1"):
        raise SearchError("mine is 1 or left out.")
    profile = given.get("profile", "")
    if profile not in ("", "default", "submission"):
        raise SearchError("profile is default or submission.")
    per_page = _int(given.get("per_page"), PER_PAGE_DEFAULT, "per_page", max(PER_PAGES))
    if per_page not in PER_PAGES:
        raise SearchError(f"per_page is {', '.join(str(p) for p in PER_PAGES)}.")
    return Query(
        terms=terms, types=types, tags=tags, durations=_words(given.get("duration"), DURATIONS, "duration"),
        has=_words(given.get("has"), HAS, "has"), mine=mine == "1", sort=sort,
        page=_int(given.get("page"), 1, "page", PAGE_MAX), per_page=per_page,
        submission=None if not profile else profile == "submission",
    )


def bucket(duration_ms: Any) -> str:
    """short, medium, long or `UNKNOWN` for a movement's `duration_ms`."""
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, (int, float)) or duration_ms <= 0:
        return UNKNOWN
    return "short" if duration_ms < SHORT_MS else "long" if duration_ms > LONG_MS else "medium"


def row(entry: dict[str, Any], *, tags: Iterable[str] = (), credit: str = "", rehab_on: bool = True, mine: bool = False,
        takes: int = 0, board: bool = False) -> Row:
    """The search row of one manifest. Type: the category (exercise or dance) plus `rehab` for the rehab tag while
    the switch is on (web/model/kind.js `entryInKind`); a movement with neither has no type."""
    tag_list = tuple(dict.fromkeys(str(t).lower() for t in tags))
    kinds = [entry["category"]] if entry.get("category") in ("exercise", "dance") else []
    if rehab_on and "rehab" in tag_list:
        kinds.append("rehab")
    has = {k for k, on in (("video", bool(entry.get("video_uri"))), ("model", bool(entry.get("animation"))), ("board", board)) if on}
    title = str(entry.get("name") or entry.get("id") or "")
    return Row(entry=entry, types=tuple(kinds), tags=tag_list, duration=bucket(entry.get("duration_ms")), has=frozenset(has),
               mine=mine, takes=takes, title=fold(title), credit=fold(credit))


def relevance(r: Row, terms: tuple[str, ...]) -> int | None:
    """None when a term is in none of the title, credit and tags; else a score (higher is closer)."""
    if not terms:
        return 0
    score = 0
    tags = [fold(t) for t in r.tags]
    words = re.split(r"[^\w]+", r.title)
    for term in terms:
        here = 0
        if term in r.title:
            here += 4 if any(w.startswith(term) for w in words) else 2
        if any(term == t for t in tags):
            here += 3
        elif any(term in t for t in tags):
            here += 1
        if term in r.credit:
            here += 1
        if not here:
            return None
        score += here
    return score + (5 if " ".join(terms) in r.title else 0)


def _ok(r: Row, q: Query, skip: str, scores: dict[str, int]) -> bool:
    """True when `r` passes every filter of `q` except the one named `skip` (the facet being counted)."""
    if r.entry["id"] not in scores:
        return False
    if skip != "type" and q.types and not q.types.intersection(r.types):
        return False
    if skip != "duration" and q.durations and r.duration not in q.durations:
        return False
    if skip != "has" and not q.has <= r.has:
        return False
    if skip != "tag" and not q.tags <= set(r.tags):
        return False
    return not (q.mine and not r.mine)


def facets(rows: list[Row], q: Query, scores: dict[str, int]) -> dict[str, Any]:
    """Counts per value of each facet, with every filter applied except the facet's own."""
    out: dict[str, Any] = {"type": {t: 0 for t in TYPES}, "duration": {d: 0 for d in (*DURATIONS, UNKNOWN)},
                           "has": {h: 0 for h in HAS}}
    tag_counts: dict[str, int] = {}
    for r in rows:
        if _ok(r, q, "type", scores):
            for t in r.types:
                out["type"][t] += 1
        if _ok(r, q, "duration", scores):
            out["duration"][r.duration] += 1
        if _ok(r, q, "has", scores):
            for h in r.has:
                out["has"][h] += 1
        if _ok(r, q, "tag", scores):
            for t in r.tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1
    top = sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TAG_FACETS]
    out["tag"] = dict(top)
    return out


def _order(sort: str, scores: dict[str, int]) -> Any:
    """The sort key. Every key ends in (title, id), unique per movement, so a page never repeats or skips a card."""
    def last(r: Row) -> tuple[str, str]:
        return (r.title, str(r.entry["id"]))

    if sort == "relevance":
        return lambda r: (-scores[r.entry["id"]], *last(r))
    if sort == "popular":
        return lambda r: (-r.takes, str(r.entry.get("created_at") or "") == "", _neg(r.entry.get("created_at")), *last(r))
    if sort == "title":
        return last
    if sort == "duration":  # shortest first, unknown last
        return lambda r: (r.duration == UNKNOWN, float(r.entry.get("duration_ms") or 0), *last(r))
    return lambda r: (str(r.entry.get("created_at") or "") == "", _neg(r.entry.get("created_at")), *last(r))  # newest


def _neg(stamp: Any) -> tuple[int, ...]:
    """A descending key for an ISO stamp string (a missing one sorts after the dated, through the flag before it)."""
    return (*(-ord(c) for c in str(stamp or "")), 1)


def run(rows: list[Row], q: Query) -> dict[str, Any]:
    """The reply body for `q` over `rows` (no `ok` key): the page of cards, totals and facets."""
    scores = {}
    for r in rows:
        found = relevance(r, q.terms)
        if found is not None:
            scores[r.entry["id"]] = found
    counts = facets(rows, q, scores)
    kept = [r for r in rows if _ok(r, q, "", scores)]
    kept.sort(key=_order(q.sort, scores))
    total = len(kept)
    pages = math.ceil(total / q.per_page)
    start = (q.page - 1) * q.per_page
    cards = [card(r) for r in kept[start:start + q.per_page]]
    return {"entries": cards, "total": total, "page": q.page, "per_page": q.per_page, "pages": pages, "sort": q.sort,
            "facets": counts}


def card(r: Row) -> dict[str, Any]:
    """The Part 6 card plus the computed fields: `types`, `tags`, `has`, `duration_bucket`, `takes`, `mine`."""
    return {**r.entry, "types": list(r.types), "tags": list(r.tags), "has": sorted(r.has),
            "duration_bucket": r.duration, "takes": r.takes, "mine": r.mine}
