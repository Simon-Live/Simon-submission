"""Challenges: a movement, a title, and a board of scores people posted (docs/specs/challenges.md).

One JSON file per challenge in `<state>/challenges/<id>.json`, written atomically (unique temp file, `os.replace`).
The files are not pruned with the jobs: every entry keeps its own copy of the score, grade and strongest section, so
the board outlives the 7-day job retention. Every change takes one `flock` on `<state>/challenges/.lock`, so the
server's threads and the operator CLI never lose each other's update. The module trusts nothing from a browser;
`challenge_routes.py` reads the scores. An entry's `job_id` and `pid` stay on disk (duplicate checks) and are never
part of a public view: with no accounts, the job id is the entrant's private key.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
from typing import Any, Iterator
from urllib.parse import urlsplit

ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,32}$")
ENTRY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
KINDS = ("friend", "crew", "sponsored")
PUBLIC_KINDS = ("friend", "crew")
NAME_MAX = 24
TITLE_MAX = 60
SPONSOR_NAME_MAX = 60
SPONSOR_TAGLINE_MAX = 120
SPONSOR_PRIZE_MAX = 160
URL_MAX = 300
MAX_ENTRIES = 200  # entries on one board
MAX_BOARDS = 500  # friend and crew boards the web can hold; sponsored boards are the operator's and not counted
STALE_DAYS = 90  # a friend or crew board with no activity for this long is deleted when a new one is made
PRIVATE_FIELDS = ("job_id", "pid")  # on disk only
PRIVATE_DOC_FIELDS = ("visitor",)  # on a challenge, on disk only: the hashed key of the visitor who made it
BOARDS_PER_VISITOR_DAY = 10  # friend and crew boards one visitor may make per UTC day
_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f  \ud800-\udfff]")
_CACHE: dict[str, dict[str, tuple[tuple[int, int, int], dict[str, Any] | None]]] = {}  # folder -> file -> (stat key, doc)

MSG_NAME = "Use a name of 1 to 24 characters."
MSG_TITLE = "Give the challenge a title of 1 to 60 characters."
MSG_KIND = "A challenge is for a friend or a crew."
MSG_ENTRY = "This movement id is not valid."
MSG_SPONSOR = "A sponsor needs a name, a tagline, an https link and a prize."
MSG_ENDS = "The end time must be a date and time in the future."
MSG_ENDED = "This challenge has ended."
MSG_DUPLICATE = "This result is already on the board."
MSG_FULL = "This board is full."
MSG_OTHER_NAME = "This result is already on a board under another name."
MSG_VISITOR_BOARDS = "You have made today's challenges. Try again tomorrow."
MSG_BOARDS = "There are too many challenges right now. Try again later."


class ChallengeError(ValueError):
    """The request is not acceptable; `status` is the HTTP answer and the message is plain words."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value: Any) -> datetime | None:
    """An ISO 8601 time as an aware UTC datetime, or None when it is not one."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


def clean_text(value: Any, maximum: int, message: str) -> str:
    """`value` trimmed, 1 to `maximum` characters and no control characters; else `ChallengeError(message)`."""
    if not isinstance(value, str):
        raise ChallengeError(message)
    text = " ".join(value.split())
    if not 1 <= len(text) <= maximum or _CONTROL.search(text):
        raise ChallengeError(message)
    return text


def clean_name(value: Any) -> str:
    return clean_text(value, NAME_MAX, MSG_NAME)


def clean_sponsor(raw: Any) -> dict[str, str]:
    """`{name, tagline, url, prize}` validated; the link must be https with a host."""
    if not isinstance(raw, dict):
        raise ChallengeError(MSG_SPONSOR)
    out = {
        "name": clean_text(raw.get("name"), SPONSOR_NAME_MAX, MSG_SPONSOR),
        "tagline": clean_text(raw.get("tagline"), SPONSOR_TAGLINE_MAX, MSG_SPONSOR),
        "prize": clean_text(raw.get("prize"), SPONSOR_PRIZE_MAX, MSG_SPONSOR),
    }
    url = raw.get("url")
    parts = urlsplit(url) if isinstance(url, str) and len(url) <= URL_MAX and url == url.strip() else None
    if parts is None or parts.scheme != "https" or not parts.hostname or _CONTROL.search(url) or " " in url:
        raise ChallengeError("The sponsor link must start with https://.")
    out["url"] = url
    return out


def new_id() -> str:
    """A random board id that never starts with `-`, so the operator CLI (`challenge close ID`) cannot read it as a flag (TICKET-095)."""
    while True:
        value = secrets.token_urlsafe(8)
        if not value.startswith("-"):
            return value


def _dir(state: Path) -> Path:
    return Path(state) / "challenges"


@contextmanager
def _locked(state: Path) -> Iterator[None]:
    """One writer at a time across threads and processes: `flock` on the folder's lock file."""
    folder = _dir(state)
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / ".lock", "a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _write(state: Path, doc: dict[str, Any]) -> None:
    folder = _dir(state)
    folder.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=folder, prefix=f".{doc['id']}.", suffix=".tmp")  # a name no other writer shares
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(json.dumps(doc))
        os.replace(name, folder / f"{doc['id']}.json")
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def _read(path: Path, challenge_id: str) -> dict[str, Any] | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ok = isinstance(doc, dict) and doc.get("id") == challenge_id and isinstance(doc.get("entries"), list)
    return doc if ok else None


def get(state: Path, challenge_id: str) -> dict[str, Any] | None:
    """The stored challenge (a fresh copy), or None when it is missing or unreadable."""
    if not isinstance(challenge_id, str) or not ID_RE.match(challenge_id):
        return None
    return _read(_dir(state) / f"{challenge_id}.json", challenge_id)


def _docs(state: Path) -> list[dict[str, Any]]:
    """Every readable challenge, read-only. A file is parsed again only when its inode, mtime or size changed."""
    folder = _dir(state)
    old: dict[str, Any] = _CACHE.get(str(folder), {})
    fresh: dict[str, Any] = {}
    out = []
    for path in folder.glob("*.json") if folder.is_dir() else []:
        try:
            info = path.stat()
        except OSError:
            continue
        key = (info.st_ino, info.st_mtime_ns, info.st_size)
        hit = old.get(path.name)
        doc = hit[1] if hit and hit[0] == key else _read(path, path.stem)
        fresh[path.name] = (key, doc)
        if doc:
            out.append(doc)
    _CACHE[str(folder)] = fresh
    return out


def ended(doc: dict[str, Any], now: datetime | None = None) -> bool:
    end = parse_time(doc.get("ends_at"))
    return end is not None and end <= (now or _now())


def ranked(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Entries by score, highest first; a tie goes to the earlier post (then the name, so the order is stable)."""
    key = lambda e: (-float(e.get("score") or 0), str(e.get("created_at") or ""), str(e.get("name") or ""))  # noqa: E731
    return [{**e, "rank": i + 1} for i, e in enumerate(sorted(entries, key=key))]


def public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """An entry without the fields that name the entrant's job."""
    return {k: v for k, v in entry.items() if k not in PRIVATE_FIELDS}


def view(doc: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """The public form of a challenge: ranked entries (no job id, no pid) and the `ended` flag."""
    rows = ranked([public_entry(e) for e in doc["entries"]])
    return {**{k: v for k, v in doc.items() if k not in ("entries", *PRIVATE_DOC_FIELDS)}, "ended": ended(doc, now), "entries": rows}


def summary(doc: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """A list row: the challenge without its entries, plus the count and the leader."""
    board = ranked(doc["entries"])
    lead = {"name": board[0]["name"], "score": board[0]["score"]} if board else None
    return {**{k: v for k, v in doc.items() if k not in ("entries", *PRIVATE_DOC_FIELDS)}, "ended": ended(doc, now), "entry_count": len(board), "leader": lead}


def _activity(doc: dict[str, Any]) -> datetime | None:
    """The latest sign of life of a board: its start, its end and its newest entry."""
    times = [parse_time(doc.get("created_at")), parse_time(doc.get("ends_at"))]
    times += [parse_time(e.get("created_at")) for e in doc["entries"] if isinstance(e, dict)]
    known = [t for t in times if t is not None]
    return max(known) if known else None


def _prune(state: Path) -> int:
    """Delete friend and crew boards idle for `STALE_DAYS`; sponsored boards stay. Call with the lock held."""
    cutoff, gone = _now() - timedelta(days=STALE_DAYS), 0
    for doc in _docs(state):
        last = _activity(doc)
        if doc.get("kind") in PUBLIC_KINDS and last is not None and last < cutoff:
            (_dir(state) / f"{doc['id']}.json").unlink(missing_ok=True)
            gone += 1
    return gone


def _admit(state: Path, challenge_id: str, existing: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`new` entries stamped, or ChallengeError (409): duplicate, full, or a job already on another board under another name.

    With no accounts the job id is the entrant's private key, so one result can sit on several boards only under
    one name. Call with the lock held.
    """
    keys = [(e["job_id"], e.get("pid")) for e in new]
    have = {(e.get("job_id"), e.get("pid")) for e in existing}
    if len(set(keys)) != len(keys) or have & set(keys):
        raise ChallengeError(MSG_DUPLICATE, 409)
    if len(existing) + len(new) > MAX_ENTRIES:
        raise ChallengeError(MSG_FULL, 409)
    owners: dict[Any, str] = {}
    for other in _docs(state):
        if other["id"] != challenge_id:
            for e in other["entries"]:
                owners.setdefault((e.get("job_id"), e.get("pid")), str(e.get("name") or "").casefold())
    for key, e in zip(keys, new):
        if owners.get(key, e["name"].casefold()) != e["name"].casefold():
            raise ChallengeError(MSG_OTHER_NAME, 409)
    return [{**e, "created_at": stamp(_now())} for e in new]


def create(
    state: Path, *, entry_id: Any, title: Any, creator_name: Any, kind: Any, sponsor: Any = None,
    ends_at: Any = None, allow_sponsored: bool = False, entries: list[dict[str, Any]] | None = None,
    visitor: str | None = None,
) -> dict[str, Any]:
    """Validate and store a new challenge, with its first `entries` (already verified) in the same write.

    `sponsor` and the kind `sponsored` need `allow_sponsored` (the operator CLI). Nothing is stored when anything fails.
    `visitor` is the hashed visitor key (quota.visitor_key): one key makes at most BOARDS_PER_VISITOR_DAY public boards a day (429).
    """
    if not isinstance(entry_id, str) or not ENTRY_ID_RE.match(entry_id):
        raise ChallengeError(MSG_ENTRY)
    if kind not in (KINDS if allow_sponsored else PUBLIC_KINDS):
        raise ChallengeError(MSG_KIND)
    if (kind == "sponsored") != (sponsor is not None):
        raise ChallengeError(MSG_SPONSOR)
    end = None
    if ends_at is not None:
        moment = parse_time(ends_at)
        if moment is None or moment <= _now():
            raise ChallengeError(MSG_ENDS)
        end = stamp(moment)
    doc = {
        "id": new_id(), "entry_id": entry_id, "title": clean_text(title, TITLE_MAX, MSG_TITLE),
        "kind": kind, "created_at": stamp(_now()), "ends_at": end,
        "creator_name": clean_name(creator_name), "sponsor": clean_sponsor(sponsor) if sponsor is not None else None,
        "entries": [],
    }
    if visitor and kind in PUBLIC_KINDS:
        doc["visitor"] = visitor
    with _locked(state):
        if kind in PUBLIC_KINDS:
            _prune(state)
            if sum(1 for d in _docs(state) if d.get("kind") in PUBLIC_KINDS) >= MAX_BOARDS:
                raise ChallengeError(MSG_BOARDS, 409)
            today = doc["created_at"][:10]
            made = sum(1 for d in _docs(state) if visitor and d.get("visitor") == visitor and str(d.get("created_at"))[:10] == today)
            if visitor and made >= BOARDS_PER_VISITOR_DAY:
                raise ChallengeError(MSG_VISITOR_BOARDS, 429)
        doc["entries"] = _admit(state, doc["id"], [], entries or [])
        _write(state, doc)
    return doc


def add_entries(state: Path, challenge_id: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Append already-verified `entries` (all or none). Raises 404, 409 (ended, duplicate, other name, full)."""
    with _locked(state):
        doc = get(state, challenge_id)
        if doc is None:
            raise ChallengeError("This challenge was not found.", 404)
        if ended(doc):
            raise ChallengeError(MSG_ENDED, 409)
        doc["entries"].extend(_admit(state, challenge_id, doc["entries"], entries))
        _write(state, doc)
    return doc


def remove_job(state: Path, job_id: str) -> int:
    """Take every board entry made from `job_id` off its board (a deleted take leaves no score behind); returns how many."""
    removed = 0
    with _locked(state):
        for doc in _docs(state):
            keep = [e for e in doc["entries"] if e.get("job_id") != job_id]
            if len(keep) != len(doc["entries"]):
                removed += len(doc["entries"]) - len(keep)
                _write(state, {**doc, "entries": keep})
    return removed


def close(state: Path, challenge_id: str) -> dict[str, Any]:
    """End a challenge now (operator); its board stays readable."""
    with _locked(state):
        doc = get(state, challenge_id)
        if doc is None:
            raise ChallengeError("This challenge was not found.", 404)
        if not ended(doc):
            doc["ends_at"] = stamp(_now() - timedelta(seconds=1))
            _write(state, doc)
    return doc


def list_all(
    state: Path, *, entry_id: str | None = None, kind: str | None = None
) -> list[dict[str, Any]]:
    """Summaries, newest first, optionally of one movement and one kind. Unchanged files are not read again."""
    out = [
        summary(doc) for doc in _docs(state)
        if (entry_id is None or doc.get("entry_id") == entry_id) and (kind is None or doc.get("kind") == kind)
    ]
    return sorted(out, key=lambda d: (d["created_at"], d["id"]), reverse=True)


# ----- the strongest section of a result ---------------------------------------------------------------
def window_label(window: dict[str, Any], index: int, basis: Any) -> str:
    """The label web/timeline.js `windowLabel` gives a window: "Rep 3" or "4.9 s to 9.8 s"."""
    if basis == "reps":
        return f"Rep {index + 1}"
    a, b = window["t_s"]
    return f"{float(a):.1f} s to {float(b):.1f} s"


def strongest_section(score: dict[str, Any]) -> dict[str, Any] | None:
    """The best compared window of `score.timeline` (ties go to the earliest), or None without a timeline."""
    best: tuple[float, float, int] | None = None
    timeline = score.get("timeline") if isinstance(score, dict) else None
    for i, w in enumerate(timeline if isinstance(timeline, list) else []):
        if not isinstance(w, dict) or w.get("compared") is False:
            continue
        t, value = w.get("t_s"), w.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if not (isinstance(t, list) and len(t) == 2 and all(isinstance(x, (int, float)) for x in t)):
            continue
        if best is None or value > best[0] or (value == best[0] and t[0] < best[1]):
            best = (float(value), float(t[0]), i)
    if best is None:
        return None
    w = timeline[best[2]]
    return {"label": window_label(w, best[2], score.get("basis")), "value": w["value"], "t_s": [w["t_s"][0], w["t_s"][1]]}
