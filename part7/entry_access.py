"""Who owns a trainer-made catalog movement and whether it is published (docs/specs/prod-data.md, APP-H4, LEG-C1).

One JSON file per movement, `<state>/entry-access/<entry_id>.json`:
`{entry_id, trainer_job, owner, published, created_at, age_band, nobody_under_18}`. `age_band` is the age answer of
the upload that made the movement ("adult", "minor", or "" when none was sent), read from the trainer job record when
the row learns its job id, so it outlives the 7-day job sweep. A "minor" row is never published (LEG-H1, private-default
D1), nor a row of an account marked 13 to 17 on its identity row (privacy PM-R2), nor, where the consent step is
required, a row whose answer cannot be read (PM-R3, fails closed). `nobody_under_18` is the uploader's statement that
nobody in the video is under 18 (privacy PM-B3): with the `trainer_public` switch off a row is published only with it.
`owner` is the signed-in user id, or "" for a movement made signed out. The row outlives the trainer job (swept after
7 days), so the movement can still be found, deleted
with the take's creator token (creator.py) and removed with its owner's account.

`published` is decided once, when Part 6 saves the movement: `open_by_default()` (on outside prod)
or the uploader's explicit opt-in for this upload. An unpublished movement is listed and served to its owner only:
the signed-in owner, or a request that carries the take's creator token in `X-Creator-Token`. A movement with no
row is shown only when it is a shipped sample (its manifest says `files_source: "fixture"`, Part 6 `seed` and
`reset`): every movement a take makes has its held-back row written before Part 6 is asked to save it
(`Link.reserve`), so a movement without a row is not yet decided, or was made before this store, and stays hidden
(re-verification W-N1, fails closed).

`evicted` (go-live-readiness.md "Evict", HARDENING 8.7, register LEG-H6) is the operator's takedown mark, set only by
`evict` (`python -m part7 evict`): the movement leaves public view at once, its owner may not publish it again
(`publish_refused`, `release`), and every evict and reinstate is appended to `<state>/evictions.jsonl`. The owner
still sees it (to export or delete it); `reinstate` clears the mark and puts back the published state it had.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Callable

from part7 import applog, consent_record, creator, identity, job_lookup, labels, prod_mode

FOLDER = "entry-access"
EVICTIONS = "evictions.jsonl"  # the operator's record of every evict and reinstate, one JSON line each
REASON_MAX = 500
HEADER = "X-Creator-Token"
SAMPLE_SOURCE = "fixture"  # Part 6's mark on the samples it ships (catalog.seed, reset)
UNDONE = ".undone"  # `<entry_id>.undone`: the save of this id was undone, so a folder that appears is an orphan
STATEMENT = "nobody_under_18"  # privacy PM-B3: the uploader said nobody in the video is under 18
_LOCK = threading.Lock()


def _path(state: Path | str, entry_id: str) -> Path | None:
    if not isinstance(entry_id, str) or not labels.ENTRY_ID_RE.match(entry_id):
        return None
    return Path(state) / FOLDER / f"{entry_id}.json"


def get(state: Path | str, entry_id: Any) -> dict[str, Any] | None:
    path = _path(state, entry_id)
    try:
        doc = json.loads(path.read_text(encoding="utf-8")) if path is not None else None
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _write(state: Path | str, doc: dict[str, Any]) -> None:
    folder = Path(state) / FOLDER
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=folder, prefix=f".{doc['entry_id']}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(json.dumps(doc))
        os.replace(name, folder / f"{doc['entry_id']}.json")
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def open_by_default() -> bool:
    """True when a movement is public with nothing asked: outside prod only. In prod the `trainer_public` switch sets the
    web's default tick (web/trainer-publish.js), never the server's: a movement is public only on the person's own
    `public` and `nobody_under_18` answers, so what they saw is what is saved, and a row already private stays private."""
    return not prod_mode.is_prod()


GPC_PRIVATE = "gpc"  # the publish choice of a request with Global Privacy Control and no opt-in (trainer_publish.choice)


def published_default(opt_in: Any) -> bool:
    """Whether a new trainer movement is public: the uploader's explicit `True`; private for `GPC_PRIVATE`
    (go-live-readiness.md "GPC"); else the `trainer_public` switch (on outside prod, off in prod)."""
    if opt_in is True:
        return True
    return opt_in != GPC_PRIVATE and open_by_default()


def job_band(state: Path | str, job_id: Any) -> str:
    """The age answer a job record carries: "adult", "minor", or "" (no answer, or no readable record). The queue keeps
    its records in `<state>/jobs/<id>/job.json` (jobs.JobQueue)."""
    if not isinstance(job_id, str) or not job_id or "/" in job_id or job_id.startswith("."):
        return ""
    doc = job_lookup.read_json(Path(state) / "jobs" / job_id / "job.json")
    consent = doc.get("consent") if isinstance(doc, dict) else None
    band = consent.get("age_band") if isinstance(consent, dict) else None
    return "minor" if band in ("minor", "under13") else "adult" if band == "adult" else ""


def band_of(state: Path | str, row: dict[str, Any] | None) -> str:
    """The age answer of the upload that made a movement: the row's own, else its trainer job's, else ""."""
    found = (row or {}).get("age_band")
    if found in ("adult", "minor"):
        return found
    return job_band(state, (row or {}).get("trainer_job"))


def owner_is_minor(state: Path | str, user_id: str) -> bool:
    """True when any movement `user_id` owns was made with a 13 to 17 answer: that account never publishes."""
    return bool(user_id) and any(r.get("owner") == user_id and band_of(state, r) == "minor" for r in rows(state))


def _owner_minor(state: Path | str, owner: Any) -> bool:
    """`owner_is_minor`, or the account's own 13 to 17 mark on its identity row (PM-R2; True when it is unreadable)."""
    return bool(owner) and (identity.account_minor(state, str(owner)) or owner_is_minor(state, str(owner)))


def _unknown(band: str) -> bool:
    """PM-R3: where the consent step is required, an unreadable age answer is not an adult's (fails closed)."""
    return band == "" and consent_record.required()


def _held(state: Path | str, row: dict[str, Any]) -> bool:
    """True when the row may not be published: a 13 to 17 or unknown answer, or a minor owner (D1, PM-R2, PM-R3)."""
    band = band_of(state, row)
    return band == "minor" or _unknown(band) or _owner_minor(state, row.get("owner"))


def record(state: Path | str, entry_id: str, *, trainer_job: str = "", owner: str = "", published: bool,
           age_band: str = "", nobody_under_18: bool = False) -> None:
    """Write the row of a new movement. A second call fills in a missing trainer job, owner, age answer or statement,
    nothing else. A movement of a 13 to 17 answer, of an account that gave one, or (where the consent step is required)
    of an unknown answer, is written unpublished (private-default D1, PM-R2, PM-R3), and so, with the `trainer_public`
    switch off, is one without the PM-B3 statement."""
    if _path(state, entry_id) is None:
        return
    forget_undone(state, entry_id)  # a new save of the id: the folder that may appear is not the undone one
    with _LOCK:
        found = get(state, entry_id)
        if found is not None:
            found["trainer_job"] = found.get("trainer_job") or trainer_job
            found["owner"] = found.get("owner") or owner
            found["age_band"] = found.get("age_band") or age_band or job_band(state, found["trainer_job"])
            found[STATEMENT] = found.get(STATEMENT) is True or nobody_under_18 is True
            if found["age_band"] == "minor":
                found["published"] = False
            _write(state, found)
            return
        row = {"entry_id": entry_id, "trainer_job": trainer_job, "owner": owner, "created_at": time.time(),
               "age_band": age_band or job_band(state, trainer_job), STATEMENT: nobody_under_18 is True}
        stated = open_by_default() or row[STATEMENT]  # PM-B3, as `release`
        _write(state, {**row, "published": bool(published) and stated and not _held(state, row)})


def publish_refused(state: Path | str, entry_id: str, user_id: str, owner_minor: bool | None = None) -> bool:
    """True when the owner may not make this movement public: it was made with a 13 to 17 answer, the owner's account
    made one, or (where the consent step is required) its age answer can no longer be read. Making a movement private
    is never refused. `owner_minor` is the account rule when the caller already read it (one read per request, R3)."""
    row = get(state, entry_id)
    if row is not None and row.get("evicted"):  # the operator took it down (LEG-H6): only a reinstate puts it back
        return True
    band = band_of(state, row)
    if band == "minor" or (owner_is_minor(state, user_id) if owner_minor is None else owner_minor):
        return True
    return band == "" and consent_record.required()  # fails closed: an unknown answer is not an adult's


def set_published(state: Path | str, entry_id: str, value: bool, nobody_under_18: bool = False) -> bool:
    """The owner's switch: set `published`; a publish with the PM-B3 statement records it on the row."""
    with _LOCK:
        found = get(state, entry_id)
        if found is None or (value and found.get("evicted")):  # an evicted movement goes public only by reinstate
            return False
        found["published"] = bool(value)
        if value and nobody_under_18 is True:
            found[STATEMENT] = True
        _write(state, found)
        return True


def unpublish_owner(state: Path | str, user_id: str) -> int:
    """Make every movement `user_id` owns private (identity `mark_minor`, PM-R2); returns how many changed."""
    changed = 0
    with _LOCK:
        for row in rows(state):
            if user_id and row.get("owner") == user_id and row.get("published") is not False:
                _write(state, {**row, "published": False})
                changed += 1
    return changed


def drop(state: Path | str, entry_id: str) -> None:
    path = _path(state, entry_id)
    if path is not None:
        path.unlink(missing_ok=True)


def rows(state: Path | str) -> list[dict[str, Any]]:
    folder = Path(state) / FOLDER
    out = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        doc = get(state, path.stem)
        if doc is not None:
            out.append(doc)
    return out


def owned_by(state: Path | str, user_id: str) -> list[str]:
    """The movement ids whose row names `user_id` as owner."""
    return [r["entry_id"] for r in rows(state) if user_id and r.get("owner") == user_id]


def holds_key(state: Path | str, row: dict[str, Any] | None, token: Any) -> bool:
    """True when `token` is the creator token of the trainer job that made the movement."""
    job = (row or {}).get("trainer_job")
    try:
        return bool(job) and creator.valid(state, job, token)
    except OSError as exc:  # the secret cannot be read: nobody holds the key (fails closed)
        applog.log(f"entry access: creator secret unreadable: {applog.cause(exc)}")
        return False


def shipped_sample(catalog: Path | str | None, entry_id: str) -> bool:
    """True when `<catalog>/<entry_id>/manifest.json` marks the movement as one of the samples Part 6 ships."""
    if catalog is None or not isinstance(entry_id, str) or not labels.ENTRY_ID_RE.match(entry_id):
        return False
    doc = job_lookup.read_json(Path(catalog) / entry_id / "manifest.json")
    return isinstance(doc, dict) and doc.get("files_source") == SAMPLE_SOURCE


def _mark_path(state: Path | str, entry_id: str) -> Path | None:
    row = _path(state, entry_id)
    return row.with_suffix(UNDONE) if row is not None else None


def forget_undone(state: Path | str, entry_id: str) -> None:
    mark = _mark_path(state, entry_id)
    if mark is not None:
        mark.unlink(missing_ok=True)


def orphans(state: Path | str, catalog: Path | str | None, now: float, window_s: float) -> list[str]:
    """The catalog folders of an undone save (PM-R10), untouched for over `window_s`: a save that finished after
    `Link.reserve`'s undo is hidden (W-N1), and the retention sweep removes it past the save window. The undo's mark is
    the only evidence: a folder with no row may be a movement made before this store, which stays hidden and is never
    removed here. A row file, even an unreadable one, keeps its folder and ends the mark. A mark whose save never came
    goes past the window."""
    folder = Path(state) / FOLDER
    out = []
    for mark in sorted(folder.glob(f"*{UNDONE}")) if catalog is not None and folder.is_dir() else []:
        entry_id = mark.name[: -len(UNDONE)]
        made = Path(catalog) / entry_id
        row = _path(state, entry_id)
        try:
            if row is None or os.path.lexists(row):
                mark.unlink(missing_ok=True)
            elif not made.is_dir() or made.is_symlink():
                if now - mark.stat().st_mtime > window_s:
                    mark.unlink(missing_ok=True)
            elif not shipped_sample(catalog, entry_id) and now - made.stat().st_mtime > window_s:
                out.append(entry_id)
        except OSError:
            continue
    return out


def _account_minor(state: Path | str, owner: str, minors: dict[str, bool] | None) -> bool:
    """`identity.account_minor`, read once per owner into `minors` when the caller keeps one (review R5)."""
    if minors is None:
        return identity.account_minor(state, owner)
    if owner not in minors:
        minors[owner] = identity.account_minor(state, owner)
    return minors[owner]


def visible(state: Path | str, entry_id: str, user_id: str | None, token: Any, catalog: Path | str | None = None,
            minors: dict[str, bool] | None = None) -> bool:
    """False for a movement without a row unless it is a shipped sample in `catalog` (W-N1), and for an unpublished
    movement, one made with a 13 to 17 or under 13 answer, or one whose owner's account is marked 13 to 17 (PM-R2),
    unless the caller is its owner (session) or holds its creator token. `minors` is the request's cache of the account
    mark per owner: a listing reads the identity store once per owner, not once per movement (review R5)."""
    row = get(state, entry_id)
    if row is None:
        return shipped_sample(catalog, entry_id)  # W-N1: no row is not yet decided, never "public"
    owner = row.get("owner")  # PM-R2: the account's own mark (one read; `mark_minor` already unpublished its rows)
    marked = bool(owner) and _account_minor(state, str(owner), minors)
    if row.get("published") is not False and band_of(state, row) != "minor" and not marked and not row.get("evicted"):
        return True  # go-live R5: a movement of a 13 to 17 or under 13 answer is never shown, whatever `published` says
    if user_id and row.get("owner") == user_id:
        return True
    return holds_key(state, row, token)


def _note(state: Path | str, doc: dict[str, Any]) -> None:
    path = Path(state) / EVICTIONS
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as out:
        out.write(json.dumps(doc, sort_keys=True) + "\n")


def evict(state: Path | str, entry_id: str, reason: str, clock: Callable[[], float] = time.time) -> dict[str, Any]:
    """Take `entry_id` out of public view (a takedown) and record it; the row after the change. A movement without a
    row (a shipped sample) gets one. Raises ValueError for a bad id or an empty reason."""
    text = " ".join(str(reason or "").split())[:REASON_MAX]
    if _path(state, entry_id) is None or not text:
        raise ValueError("evict needs a valid movement id and a reason")
    now = clock()
    with _LOCK:
        found = get(state, entry_id) or {"entry_id": entry_id, "trainer_job": "", "owner": "", "published": True,
                                          "created_at": now, "age_band": ""}
        if not found.get("evicted"):
            found["evicted"] = {"at": now, "reason": text, "was_published": found.get("published") is not False}
        found["published"] = False
        _write(state, found)
        _note(state, {"action": "evict", "entry_id": entry_id, "at": now, "reason": text})
    return found


def reinstate(state: Path | str, entry_id: str, reason: str, clock: Callable[[], float] = time.time) -> dict[str, Any] | None:
    """Clear the takedown mark of `entry_id` (a counter notice) and put back the published state it had, by `release`'s
    rule (never a held row, nor, with `trainer_public` off, one without the PM-B3 statement; review R6); the row, or
    None when it was not evicted. Raises ValueError for a bad id or an empty reason."""
    text = " ".join(str(reason or "").split())[:REASON_MAX]
    if _path(state, entry_id) is None or not text:
        raise ValueError("reinstate needs a valid movement id and a reason")
    now = clock()
    with _LOCK:
        found = get(state, entry_id)
        if found is None or not found.get("evicted"):
            return None
        mark = found.pop("evicted")
        stated = open_by_default() or found.get(STATEMENT) is True  # PM-B3, as `release` (review R6)
        found["published"] = bool(isinstance(mark, dict) and mark.get("was_published")) and stated and not _held(state, found)
        _write(state, found)
        _note(state, {"action": "reinstate", "entry_id": entry_id, "at": now, "reason": text})
    return found


def evictions(state: Path | str) -> list[dict[str, Any]]:
    """Every line of the evictions record, oldest first (a line that does not parse is skipped)."""
    path = Path(state) / EVICTIONS
    out = []
    for row in path.read_text(encoding="utf-8").splitlines() if path.is_file() else []:
        try:
            doc = json.loads(row)
        except ValueError:
            continue
        if isinstance(doc, dict):
            out.append(doc)
    return out


def release(state: Path | str, entry_id: str, owner: str) -> bool:
    """Publish a movement whose row was written held back (`Link(deferred=True)`), by the rule `record` applies to a
    new row: never one of a 13 to 17 or (consent required) unknown answer, of an account that gave a 13 to 17 one, nor,
    with the `trainer_public` switch off, one without the PM-B3 statement. True when it is published now."""
    with _LOCK:
        found = get(state, entry_id)
        if found is None or found.get("evicted") or _held(state, {**found, "owner": found.get("owner") or owner}):
            return False
        if not open_by_default() and found.get(STATEMENT) is not True:
            return False
        found["published"] = True
        _write(state, found)
        return True


class Link:
    """The pending row of a trainer submit: the request knows the owner and the opt-in, the queue the job id.

    `auth.on_entry` makes it before the job exists and `auth.attach_job` gives it the job id. The chain calls `reserve`
    with the id it asks Part 6 for before Part 6 saves anything, which writes the row held back (W-N1); Part 6's save
    (`saved`) and the job id complete it. With `deferred` (a trainer or group job, whose captions or silent video come
    after the save) the row stays unpublished until `ready`, then is published as asked (go-live R4, a11y B3). Each
    write after `ready` publishes by `release`'s rules, so a `ready` that came before the row was complete is not lost
    (review S-R5); nothing is published before the job id is known, since the upload's age answer is read from it."""

    def __init__(self, state: Path | str, owner: str, published: bool, deferred: bool = False) -> None:
        self.state, self.owner, self.published, self.deferred = state, owner, published, deferred
        # PM-B3: with the switch off `published` is True only through `trainer_publish.opt_in`, which needs the
        # statement `nobody_under_18: true`; with it on every movement is public and nothing was stated
        self.stated = bool(published) and not open_by_default()
        self.job_id, self.entry_id = "", ""
        self._ready = False
        self._lock = threading.Lock()

    def _write(self) -> None:
        now = self.published and bool(self.job_id) and (self._ready or not self.deferred)  # no job id: band unknown
        record(self.state, self.entry_id, trainer_job=self.job_id, owner=self.owner, published=now,
               nobody_under_18=self.stated)
        if now:  # a row written held back by `reserve` is published here; minor bands are refused (`release`)
            release(self.state, self.entry_id, self.owner)

    def reserve(self, entry_id: str) -> Callable[[], None]:
        """Write the held-back row of `entry_id` before Part 6 saves it; returns the undo for a save that did not
        happen. Raises OSError when the row cannot be written, or when a row of `entry_id` already names another job
        or owner (app-surface R5: a new movement never lands on another movement's row; the chain does not save)."""
        with self._lock:
            found = get(self.state, entry_id)
            if found is not None and (found.get("trainer_job") != self.job_id or found.get("owner") != self.owner):
                raise OSError(f"the access row of {entry_id} belongs to another movement")
            self.entry_id = entry_id
            record(self.state, entry_id, trainer_job=self.job_id, owner=self.owner, published=False,
                   nobody_under_18=self.stated)
            if get(self.state, entry_id) is None:
                raise OSError(f"no access row for {entry_id}")

        def undo() -> None:
            with self._lock:
                if self.entry_id == entry_id:
                    self.entry_id = ""
                row = get(self.state, entry_id)  # only this link's own row: never another take's (review residual 2)
                if row is not None and row.get("trainer_job") == self.job_id and row.get("owner") == self.owner:
                    drop(self.state, entry_id)
                    mark = _mark_path(self.state, entry_id)
                    if mark is not None:
                        mark.touch()  # the only evidence `orphans` accepts

        return undo

    def ready(self) -> None:
        """The movement may be shown as asked: publish a held-back row when the upload opted in."""
        with self._lock:
            self._ready = True
            if self.deferred and self.published and self.entry_id and self.job_id:  # else `job` publishes it
                release(self.state, self.entry_id, self.owner)

    def job(self, job_id: str) -> None:
        with self._lock:
            self.job_id = job_id
            if self.entry_id:
                self._write()

    def saved(self, entry_id: str) -> None:
        with self._lock:
            self.entry_id = entry_id
            self._write()
