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
import unicodedata
from typing import Any, Callable, Iterator
from urllib.parse import urlsplit

from part7 import prod_mode, shown_score

Keep = Callable[[dict[str, Any]], bool]  # which stored entries a public view may show (TICKET-327, ADR-0019)

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
STALE_DAYS = 90  # a friend or crew board with no activity for this long is deleted when a new one is made
PRIVATE_FIELDS = ("job_id", "pid", "private", "own_reference", "compute_owner", "shown_before", "owner", "poster")  # on disk only (TICKET-327: the post-time privacy facts; `owner`: the account that posted, for Delete my data and the under-18 mark)
PRIVATE_DOC_FIELDS = ("visitor", "owner", "superseded", "invites", "reports")  # on a challenge, on disk only: the hashed visitor key, the account that made it, replaced scores, the invite list and the reports
FORMER_MEMBER = "A former member"  # the maker's name once the account is gone and others are still on the board
REPORT_REASONS = ("name", "title", "score", "other")  # a report holds one of these and nothing the reporter typed
VISITOR_KEEP_DAYS = 3  # the sweep drops the hashed visitor key after 3 days (D11)
_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f  \ud800-\udfff]")
_CACHE: dict[str, dict[str, tuple[tuple[int, int, int], dict[str, Any] | None]]] = {}  # folder -> file -> (stat key, doc)

MSG_NAME = "Use your own name, 1 to 24 characters, with no @. A board shows names, never email addresses."
MSG_NAME_CHARS = "Use letters, numbers and ordinary symbols. Hidden and direction-changing characters are not allowed."
MSG_NAME_RESERVED = "That name is kept for Simon. Choose your own."
MSG_TITLE = "Give the challenge a title of 1 to 60 characters, with no @."
MSG_KIND = "A challenge is for a friend or a crew."
MSG_ENTRY = "This movement id is not valid."
MSG_SPONSOR = "A sponsor needs a name, a tagline, an https link, a prize and an https link to the official rules."
MSG_SPONSOR_ENDS = "A sponsored challenge needs an end date."
MSG_REPORT = "Choose a reason to report."
MSG_SPONSOR_OWN_COMPUTE = "This board is a prize board, so a take scored on your own compute cannot join it."
MSG_SPONSOR_SIGN_IN = "Sign in to join a prize board."
MSG_SPONSOR_ONE = "You already have a result on this prize board."
MSG_SPONSOR_CREW = "A prize board takes one result for each account, so a crew cannot join it. Each person joins with their own take."
MSG_ENDS = "The end time must be a date and time in the future."
MSG_ENDED = "This challenge has ended."
MSG_DUPLICATE = "This result is already on the board."
MSG_BETTER_HELD = "Your best score on this board is already higher. Only your best counts."
MSG_OTHER_NAME = "This result is already on a board under another name."
MSG_VISIBILITY = "Choose Public, or People I choose while signed in."
MSG_PRIZES_OFF = "Prize challenges are turned off on this server."


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


_FILLERS = "⠀ㅤᅟᅠﾠ͏"  # blank-looking letters and marks that are not format characters
_STAFF_WORDS = frozenset({"official", "staff", "support", "admin", "administrator", "moderator", "mod", "operator", "team", "verified", "system"})
_SCRIPTS = ("LATIN", "CYRILLIC", "GREEK")


def _hidden(text: str) -> bool:
    """True when `text` holds a format character (zero width, soft hyphen, direction marks and overrides), a private-use or
    unassigned one, a blank-looking filler, or nothing visible at all."""
    if any(unicodedata.category(c) in ("Cf", "Co", "Cn", "Cs", "Zl", "Zp") or c in _FILLERS for c in text):
        return True
    return not any(not unicodedata.category(c).startswith(("Z", "C")) for c in text)


def clean_text(value: Any, maximum: int, message: str) -> str:
    """`value` trimmed, 1 to `maximum` characters and no control or format characters; else `ChallengeError(message)`."""
    if not isinstance(value, str):
        raise ChallengeError(message)
    text = " ".join(value.split())
    if not 1 <= len(text) <= maximum or _CONTROL.search(text):
        raise ChallengeError(message)
    if _hidden(text):
        raise ChallengeError(MSG_NAME_CHARS)
    return text


def has_at(text: Any) -> bool:
    """True when `text` holds an @ in any spelling (NFKC folds the full-width one): a name that looks like an address."""
    return isinstance(text, str) and "@" in unicodedata.normalize("NFKC", text)


def masked(text: Any, replacement: str = "Hidden name") -> Any:
    """What a board shows for a stored name or title: `replacement` when it holds an @ (boards made before names with an
    @ were refused; a typed address must not stay public), else the text itself."""
    return replacement if has_at(text) else text


def _tokens(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(c if c.isalnum() else " " for c in folded).split()


def _mixed_script(text: str) -> bool:
    """True when one word mixes Latin with Cyrillic or Greek letters: a look-alike spelling of another name."""
    for word in unicodedata.normalize("NFKC", text).split():
        seen = {unicodedata.name(c, "").split(" ")[0] for c in word if c.isalpha()} & set(_SCRIPTS)
        if len(seen) > 1:
            return True
    return False


def reserved(text: str) -> bool:
    """True for the name Simon, a name that pairs Simon with a staff-like word, a staff-like word alone, and a look-alike spelling."""
    words = _tokens(text)
    staff = [w for w in words if w in _STAFF_WORDS]
    return bool(words) and (words == ["simon"] or bool(staff and ("simon" in words or len(words) == len(staff))) or _mixed_script(text))


def clean_name(value: Any, reserved_ok: bool = False) -> str:
    """A name of 1 to NAME_MAX visible characters, with no @; the name Simon and staff-like ones are refused unless `reserved_ok` (the operator)."""
    if has_at(value):
        raise ChallengeError(MSG_NAME)
    text = clean_text(value, NAME_MAX, MSG_NAME)
    if not reserved_ok and reserved(text):
        raise ChallengeError(MSG_NAME_RESERVED)
    return text


def clean_sponsor(raw: Any) -> dict[str, str]:
    """`{name, tagline, url, prize, rules_url}` validated; both links must be https with a host."""
    if not isinstance(raw, dict):
        raise ChallengeError(MSG_SPONSOR)
    out = {
        "name": clean_text(raw.get("name"), SPONSOR_NAME_MAX, MSG_SPONSOR),
        "tagline": clean_text(raw.get("tagline"), SPONSOR_TAGLINE_MAX, MSG_SPONSOR),
        "prize": clean_text(raw.get("prize"), SPONSOR_PRIZE_MAX, MSG_SPONSOR),
    }
    out["url"] = _https(raw.get("url"), "The sponsor link must start with https://.")
    out["rules_url"] = _https(raw.get("rules_url"), "The link to the official rules must start with https://.")
    return out


def _https(url: Any, message: str) -> str:
    parts = urlsplit(url) if isinstance(url, str) and len(url) <= URL_MAX and url == url.strip() else None
    if parts is None or parts.scheme != "https" or not parts.hostname or _CONTROL.search(url) or " " in url:
        raise ChallengeError(message)
    return url


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
    """Entries by the shown measure (one-letter.md L3: the credit percent shown, else the capped score; a stored entry
    without it by its score), highest first; a tie goes to the earlier post (then the name, so the order is stable)."""
    key = lambda e: (not shown_score.on_credit_scale(e), shown_score.is_partial(e), -float(shown_score.rank_of(e) or 0), str(e.get("created_at") or ""), str(e.get("name") or ""))  # noqa: E731
    return [{**e, "rank": i + 1} for i, e in enumerate(sorted(entries, key=key))]


def rescale(state: Path, read: Callable[[dict[str, Any]], tuple[Any, Any, Any] | None], apply: bool = True) -> dict[str, int]:
    """Bring every stored entry to the board's rules (S7, S8) from its own job, with no new run. `read(entry)` returns
    `(analysis, light, owner)`, or None when the job is gone. `score`, `grade` and the old `shown` stay (the old `shown` as
    `shown_before`); an entry gets its account as `owner`; where one account holds several rows the best stays and the rest
    move to the board's private `superseded` list, not deleted. An entry already at `BOARD_VERSION` keeps its numbers.
    Returns `{changed, kept, missing, superseded}`."""
    out = {"changed": 0, "kept": 0, "missing": 0, "superseded": 0}
    with _locked(state):
        for doc in _docs(state):
            entries, touched = [], False
            for e in doc["entries"]:
                have = e.get("shown") if isinstance(e.get("shown"), dict) else {}
                current = have.get("board_v") == shown_score.BOARD_VERSION
                got = None if current and "owner" in e else read(e)
                if got is None and not current:
                    out["missing"] += 1
                    entries.append(e)
                    continue
                new = e
                if got is not None:
                    holder = got[2] if isinstance(got[2], str) and e.get("pid") is None else None
                    shown = have if current else shown_score.for_board(got[0], got[1])
                    if shown is None:
                        out["missing"] += 1
                        entries.append(e)
                        continue
                    before = {} if current or "shown_before" in e or not have else {"shown_before": have}
                    new = {**e, "shown": shown, **before, **({"owner": holder} if holder else {})}
                out["kept" if current else "changed"] += 1
                touched = touched or new != e
                entries.append(new)
            best: dict[str, dict[str, Any]] = {}
            for e in entries:
                who = e.get("owner")
                if who and (who not in best or _strength(e) > _strength(best[who])):
                    best[who] = e
            drop = [e for e in entries if e.get("owner") and best[e["owner"]] is not e]
            if drop:
                entries = [e for e in entries if not any(e is d for d in drop)]
                doc = {**doc, "superseded": [*doc.get("superseded", []), *drop]}
                out["superseded"] += len(drop)
                touched = True
            if touched and apply:
                _write(state, {**doc, "entries": entries})
    return out


def public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """An entry without the fields that name the entrant's job. An entry with the board's one number (`shown.board_v`) has
    `score` and `grade` that say the same thing as `shown` (the percent and its letter), not Part 5's 0 to 100 pair, which
    stays on disk (S9)."""
    out = {k: v for k, v in entry.items() if k not in PRIVATE_FIELDS}
    out["name"] = masked(out.get("name"))
    s = entry.get("shown")
    if isinstance(s, dict) and s.get("board_v") and isinstance(s.get("measure"), (int, float)) and isinstance(s.get("letter"), str):
        out.update(score=s["measure"], grade=s["letter"])
    return out


def prize_boards_on() -> bool:
    """#415 and LEG-M7: sponsored boards carry a prize and have no official rules, so prod turns them off."""
    return prod_mode.policy("prize_boards")


def ranks_owner_compute() -> bool:
    """#415 and BYOK-H3: a score made on the owner's own compute (`compute_owner` on its job) stays off ranked boards
    unless the `byok_ranked` switch is on."""
    return prod_mode.policy("byok_ranked")


def shown(doc: dict[str, Any] | None) -> bool:
    """False for a sponsored board while prize boards are off: it is neither listed nor answered."""
    return doc is not None and (doc.get("kind") != "sponsored" or prize_boards_on())


def _kept(doc: dict[str, Any], keep: Keep | None) -> list[dict[str, Any]]:
    owner_ok = ranks_owner_compute()
    return [e for e in doc["entries"] if (keep is None or keep(e)) and (owner_ok or e.get("compute_owner") is not True)]


def _public_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """The board's own fields for any viewer: no entries, no private fields, no @ in the shown name or title."""
    out = {k: v for k, v in doc.items() if k not in ("entries", *PRIVATE_DOC_FIELDS)}
    out["creator_name"], out["title"] = masked(out.get("creator_name")), masked(out.get("title"), "Challenge")
    out.setdefault("visibility", "public")  # a board stored before visibility existed is public
    return out


def view(doc: dict[str, Any], now: datetime | None = None, keep: Keep | None = None) -> dict[str, Any]:
    """The public form of a challenge: ranked entries (no job id, no pid) and the `ended` flag. `keep` leaves out the
    entries that stay with their owner (challenge_routes passes `takes_on.board_keep`)."""
    rows = ranked([public_entry(e) for e in _kept(doc, keep)])
    return {**_public_doc(doc), "ended": ended(doc, now), "entries": rows}


def summary(doc: dict[str, Any], now: datetime | None = None, keep: Keep | None = None) -> dict[str, Any]:
    """A list row: the challenge without its entries, plus the count and the leader (of the entries `keep` shows)."""
    board = ranked(_kept(doc, keep))
    top = next((e for e in board if not shown_score.is_capped(e)), None)   # one-letter.md L6: a capped take never heads a list
    lead = {"name": masked(top["name"]), "score": public_entry(top)["score"], **({"shown": top["shown"]} if top.get("shown") else {})} if top else None
    return {**_public_doc(doc), "ended": ended(doc, now), "entry_count": len(board), "leader": lead}


def _activity(doc: dict[str, Any]) -> datetime | None:
    """The latest sign of life of a board: its start, its end and its newest entry."""
    times = [parse_time(doc.get("created_at")), parse_time(doc.get("ends_at"))]
    times += [parse_time(e.get("created_at")) for e in doc["entries"] if isinstance(e, dict)]
    known = [t for t in times if t is not None]
    return max(known) if known else None


def _prune(state: Path, now: datetime | None = None) -> int:
    """Delete friend and crew boards idle for `STALE_DAYS`; sponsored boards stay. Call with the lock held."""
    cutoff, gone = (now or _now()) - timedelta(days=STALE_DAYS), 0
    for doc in _docs(state):
        last = _activity(doc)
        if doc.get("kind") in PUBLIC_KINDS and last is not None and last < cutoff:
            (_dir(state) / f"{doc['id']}.json").unlink(missing_ok=True)
            gone += 1
    return gone


def _report_unkeyed(row: Any, cutoff: datetime) -> Any:
    """A stored report without its visitor key once it is older than `cutoff`; its reason and time stay."""
    if not isinstance(row, dict) or "visitor" not in row:
        return row
    at = parse_time(row.get("at"))
    return row if at is not None and at >= cutoff else {k: v for k, v in row.items() if k != "visitor"}


def sweep(state: Path, now: datetime | None = None) -> dict[str, int]:
    """The periodic sweep (`server._sweep`, data-integrity D10): idle friend and crew boards go (`_prune`), and the
    hashed visitor key leaves boards made, and reports made, more than VISITOR_KEEP_DAYS ago. `{pruned, unkeyed}`."""
    moment = now or _now()
    cutoff = moment - timedelta(days=VISITOR_KEEP_DAYS)
    unkeyed = 0
    with _locked(state):
        pruned = _prune(state, moment)
        for doc in _docs(state):
            made = parse_time(doc.get("created_at"))
            after = {k: v for k, v in doc.items() if k != "visitor" or (made is not None and made >= cutoff)}
            if isinstance(doc.get("reports"), list):
                after["reports"] = [_report_unkeyed(r, cutoff) for r in doc["reports"]]
            if after != doc:
                _write(state, after)
                unkeyed += 1
    return {"pruned": pruned, "unkeyed": unkeyed}


def made_by(state: Path, user_id: str) -> list[dict[str, Any]]:
    """The boards the account `user_id` made, as stored (Download my data reads them, export_data.py)."""
    return [doc for doc in _docs(state) if user_id and doc.get("owner") == user_id]


def is_of(entry: dict[str, Any], user_id: str | None, job_ids: Any = ()) -> bool:
    """True when a stored entry is the account's: its `owner`, its `poster` (a crew's row, posted by that account) or one of its take ids."""
    return (bool(user_id) and user_id in (entry.get("owner"), entry.get("poster"))) or entry.get("job_id") in job_ids


def holds_row(doc: dict[str, Any], user_id: str | None, job_ids: Any = ()) -> bool:
    """True when the board holds a row, shown or replaced, of this account or of one of these take ids."""
    rows = [*doc.get("entries", []), *[e for e in doc.get("superseded") or [] if isinstance(e, dict)]]
    return any(is_of(e, user_id, job_ids) for e in rows)


def _without(doc: dict[str, Any], gone: Any) -> dict[str, Any]:
    """`doc` with the entries `gone(entry)` names off the board and off its private `superseded` list (a replaced score is still that person's)."""
    out = {**doc, "entries": [e for e in doc["entries"] if not gone(e)]}
    if "superseded" in doc:
        out["superseded"] = [e for e in doc["superseded"] if not (isinstance(e, dict) and gone(e))]
    return out


def _changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return len(before["entries"]) != len(after["entries"]) or len(before.get("superseded") or []) != len(after.get("superseded") or [])


def involving(state: Path, user_id: str, job_ids: Any = ()) -> list[dict[str, Any]]:
    """The boards the account made or has an entry on, as stored (Download my data): an entry is the account's by its
    `owner` or by a job id of its takes (entries posted before `owner` was kept)."""
    jobs = {j for j in job_ids if isinstance(j, str)}
    rows = lambda doc: [*doc["entries"], *[e for e in doc.get("superseded") or [] if isinstance(e, dict)]]  # noqa: E731
    return [doc for doc in _docs(state) if user_id and (doc.get("owner") == user_id or any(is_of(e, user_id, jobs) for e in rows(doc)))]


def remove_account(state: Path, user_id: str, job_ids: Any = ()) -> dict[str, int]:
    """Take the account `user_id` off every board (Delete my data, data-integrity D7; the under-18 mark, privacy PM-B2).

    Its entries go from every board: those stamped with its `owner`, and those from `job_ids` (its takes, for entries
    posted before `owner` was kept). A board it made with nobody else on it is deleted; one others are on stays, with the
    maker's name and visitor key replaced (FORMER_MEMBER). Boards made signed out carry no owner and stay.
    Returns `{entries, removed, anonymised}`."""
    out = {"entries": 0, "removed": 0, "anonymised": 0}
    if not user_id:
        return out
    jobs = {j for j in job_ids if isinstance(j, str)}
    with _locked(state):
        for doc in _docs(state):
            if not ID_RE.match(str(doc.get("id") or "")):
                continue
            changed = _without(doc, lambda e: is_of(e, user_id, jobs))  # noqa: B023  # called here, in this pass
            keep = changed["entries"]
            made = doc.get("owner") == user_id
            if not made and not _changed(doc, changed):
                continue
            out["entries"] += len(doc["entries"]) - len(keep)
            if made and not keep:
                (_dir(state) / f"{doc['id']}.json").unlink(missing_ok=True)
                out["removed"] += 1
                continue
            if made:
                changed = {k: v for k, v in changed.items() if k not in ("owner", "visitor")}
                changed["creator_name"] = FORMER_MEMBER
                out["anonymised"] += 1
            _write(state, changed)
    return out


def remove_score(state: Path, challenge_id: str, name: str) -> int:
    """Operator: take every entry under `name` (case-insensitive) off one board; returns how many went. 404 for a missing board."""
    with _locked(state):
        doc = get(state, challenge_id)
        if doc is None:
            raise ChallengeError("This challenge was not found.", 404)
        after = _without(doc, lambda e: str(e.get("name") or "").casefold() == str(name).casefold())
        gone = len(doc["entries"]) - len(after["entries"])
        if _changed(doc, after):
            _write(state, after)
    return gone


def remove_board(state: Path, challenge_id: str) -> None:
    """Operator: delete one board and its entries. 404 for a missing board."""
    with _locked(state):
        if get(state, challenge_id) is None:
            raise ChallengeError("This challenge was not found.", 404)
        (_dir(state) / f"{challenge_id}.json").unlink(missing_ok=True)


def report(state: Path, challenge_id: str, reason: Any, visitor: str) -> tuple[int, bool]:
    """Record that `visitor` (the hashed key) reported the board for `reason` (one of REPORT_REASONS, never free text).
    Returns `(reports on the board, first)`, `first` true only for the report that made the count 1; the same visitor and reason twice counts once. 404 for a missing board."""
    if reason not in REPORT_REASONS:
        raise ChallengeError(MSG_REPORT)
    with _locked(state):
        doc = get(state, challenge_id)
        if doc is None or not shown(doc):
            raise ChallengeError("This challenge was not found.", 404)
        rows = list(doc.get("reports") or [])
        new = not any(r.get("visitor") == visitor and r.get("reason") == reason for r in rows)
        if new:
            rows.append({"reason": reason, "visitor": visitor, "at": stamp(_now())})
            _write(state, {**doc, "reports": rows})
    return len(rows), new and len(rows) == 1


def _strength(e: dict[str, Any]) -> tuple[bool, bool, float]:
    """How a board orders two entries of one account (the sort key of `ranked`, without the post time): bigger is better."""
    return (shown_score.on_credit_scale(e), not shown_score.is_partial(e), float(shown_score.rank_of(e) or 0))


def _one_per_account(existing: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`existing` without the entries a better `new` one of the same account replaces (S8); ChallengeError (409) when the
    account already holds a score at least as good. Entries with no `owner` (signed out, or a crew) are never merged."""
    kept = list(existing)
    for e in new:
        who = e.get("owner")
        held = [h for h in kept if who and h.get("owner") == who and (h.get("job_id"), h.get("pid")) != (e.get("job_id"), e.get("pid"))]
        if held and _strength(e) <= max(_strength(h) for h in held):
            raise ChallengeError(MSG_BETTER_HELD, 409)
        kept = [h for h in kept if h not in held]
    return kept


def _admit(state: Path, challenge_id: str, existing: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`new` entries stamped, or ChallengeError (409): duplicate, or a job already on another board under another name.

    With no accounts the job id is the entrant's private key, so one result can sit on several boards only under
    one name. Call with the lock held.
    """
    keys = [(e["job_id"], e.get("pid")) for e in new]
    have = {(e.get("job_id"), e.get("pid")) for e in existing}
    if len(set(keys)) != len(keys) or have & set(keys):
        raise ChallengeError(MSG_DUPLICATE, 409)
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
    visitor: str | None = None, owner: str | None = None, visibility: str = "public",
    invites: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate and store a new challenge, with its first `entries` (already verified) in the same write.

    `sponsor` and the kind `sponsored` need `allow_sponsored` (the operator CLI). Nothing is stored when anything fails.
    `visitor` is the hashed visitor key (quota.visitor_key).
    `owner` is the signed-in account that makes it, kept on disk only.
    """
    if not isinstance(entry_id, str) or not ENTRY_ID_RE.match(entry_id):
        raise ChallengeError(MSG_ENTRY)
    if kind not in (KINDS if allow_sponsored else PUBLIC_KINDS):
        raise ChallengeError(MSG_KIND)
    if kind == "sponsored" and not prize_boards_on():
        raise ChallengeError(MSG_PRIZES_OFF, 403)
    if (kind == "sponsored") != (sponsor is not None):
        raise ChallengeError(MSG_SPONSOR)
    if kind == "sponsored" and ends_at is None:
        raise ChallengeError(MSG_SPONSOR_ENDS)  # no prize board without rules and an end (the rules link is checked by clean_sponsor)
    end = None
    if ends_at is not None:
        moment = parse_time(ends_at)
        if moment is None or moment <= _now():
            raise ChallengeError(MSG_ENDS)
        end = stamp(moment)
    if has_at(title):
        raise ChallengeError(MSG_TITLE)
    doc = {
        "id": new_id(), "entry_id": entry_id, "title": clean_text(title, TITLE_MAX, MSG_TITLE),
        "kind": kind, "created_at": stamp(_now()), "ends_at": end,
        "creator_name": clean_name(creator_name, reserved_ok=allow_sponsored), "sponsor": clean_sponsor(sponsor) if sponsor is not None else None,
        "entries": [],
    }
    if visibility not in ("public", "invited") or (visibility == "invited" and (kind not in PUBLIC_KINDS or not owner)):
        raise ChallengeError(MSG_VISIBILITY)  # people-I-choose needs a signed-in maker and a friend or crew board
    doc["visibility"], doc["invites"] = visibility, list(invites or [])  # challenge_visibility.py; a file without them is public
    if visitor and kind in PUBLIC_KINDS:
        doc["visitor"] = visitor
    if owner:
        doc["owner"] = owner  # the signed-in maker: Delete my data anonymises or removes the board (`remove_account`)
    with _locked(state):
        if kind in PUBLIC_KINDS:
            _prune(state)  # idle boards go by age; no count of boards or of one visitor's boards refuses a new one (operator 2026-11-04)
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
        if doc.get("kind") == "sponsored":
            _admit_prize(doc, entries)  # a prize board refuses a second result of an account; it never replaces the first
        kept = _one_per_account(doc["entries"], entries)
        doc["entries"] = [*kept, *_admit(state, challenge_id, kept, entries)]
        _write(state, doc)
    return doc


def _admit_prize(doc: dict[str, Any], new: list[dict[str, Any]]) -> None:
    """A prize board takes one result per account and none scored on the entrant's own compute (LEG-M7: no invented rules)."""
    accounts = [e.get("owner") for e in new] + [e.get("owner") for e in doc["entries"]]
    if any(e.get("pid") is not None for e in new):  # a crew's people share the poster's account, so they would be many results of one
        raise ChallengeError(MSG_SPONSOR_CREW, 409)
    if any(e.get("compute_owner") is True for e in new):
        raise ChallengeError(MSG_SPONSOR_OWN_COMPUTE, 409)
    if not all(e.get("owner") for e in new):
        raise ChallengeError(MSG_SPONSOR_SIGN_IN, 403)
    if len({a for a in accounts if a}) != len([a for a in accounts if a]):
        raise ChallengeError(MSG_SPONSOR_ONE, 409)


def remove_job(state: Path, job_id: str) -> int:
    """Take every board entry made from `job_id` off its board (a deleted take leaves no score behind); returns how many."""
    removed = 0
    with _locked(state):
        for doc in _docs(state):
            after = _without(doc, lambda e: e.get("job_id") == job_id)
            if _changed(doc, after):
                removed += len(doc["entries"]) - len(after["entries"])
                _write(state, after)
    return removed


def remove_scores(state: Path, challenge_id: str, *, owner: str | None, job_ids: tuple[str, ...] = ()) -> int:
    """Take the caller's own scores off one board (TICKET-431): the entries of account `owner`, and the entries made from
    `job_ids` (unowned takes a browser names). ChallengeError 404 for an unknown board; returns how many went."""
    with _locked(state):
        doc = get(state, challenge_id)
        if doc is None:
            raise ChallengeError("This challenge was not found.", 404)
        after = _without(doc, lambda e: is_of(e, owner, job_ids))
        gone = len(doc["entries"]) - len(after["entries"])
        if _changed(doc, after):
            _write(state, after)
    return gone


def delete(state: Path, challenge_id: str) -> bool:
    """Delete one board and its scores (its maker's call); False when it was not there."""
    if not ID_RE.match(str(challenge_id)):
        return False
    with _locked(state):
        path = _dir(state) / f"{challenge_id}.json"
        found = path.is_file()
        path.unlink(missing_ok=True)
    return found


def remove_entry(state: Path, entry_id: str) -> int:
    """Delete every board on the movement `entry_id`, sponsored ones too: the trainer's deletion beats a challenge
    that uses the movement (docs/specs/prod-data.md, LEG-C1). Returns how many boards went."""
    removed = 0
    with _locked(state):
        for doc in _docs(state):
            if doc.get("entry_id") == entry_id and ID_RE.match(str(doc.get("id") or "")):
                (_dir(state) / f"{doc['id']}.json").unlink(missing_ok=True)
                removed += 1
    return removed


def docs(state: Path) -> list[dict[str, Any]]:
    """Every stored board, read-only, for callers that decide who may see it (challenge_visibility.can_view)."""
    return _docs(state)


def update(state: Path, challenge_id: str, change: Callable[[dict[str, Any]], Any]) -> tuple[dict[str, Any], Any]:
    """Read, `change(doc)` in place and write one board under the lock; `(doc, change's answer)`. 404 when it is gone."""
    with _locked(state):
        doc = get(state, challenge_id)
        if doc is None:
            raise ChallengeError("This challenge was not found.", 404)
        answer = change(doc)
        _write(state, doc)
    return doc, answer


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
    state: Path, *, entry_id: str | None = None, kind: str | None = None, keep: Keep | None = None,
    allow: Callable[[dict[str, Any]], bool] | None = None,
) -> list[dict[str, Any]]:
    """Summaries, newest first, optionally of one movement and one kind. Unchanged files are not read again.
    `allow` is asked with the stored board (challenge_visibility.can_view); a board it refuses is left out."""
    out = [
        summary(doc, keep=keep) for doc in _docs(state)
        if shown(doc) and (allow is None or allow(doc)) and (entry_id is None or doc.get("entry_id") == entry_id) and (kind is None or doc.get("kind") == kind)
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
