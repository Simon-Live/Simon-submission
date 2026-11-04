"""Import: put shared files made by other parts into catalog entries (docs/specs/catalog-contract.md).

`import_files` takes the bytes of dropped files (CLI folder, CLI files or HTTP body), finds each
file's kind, reads it through `part6/formats.py` and writes one entry with `files_source`
"import". It is two steps, `prepare_import` (all the slow work, no write) and `commit_import` (the
write), so a server can hold its save lock for the write only. `store_processed` stores the parsed
files a processor returned. Both build on `add_entry`, which also backs `fixtures/make_catalog.py`
and the conformance kit.

Safety: no name from a request ever builds a path. Files are stored under the fixed names
`keyframes.json`, `skeleton.json`, `animation.json`, `thumbnail.svg`, `manifest.json` and
`video.webm` or `video.mp4`; a dropped file's own name is kept only as
`provenance.<kind>.original_name`. Writes are atomic (`catalog.write_entry`).
"""
from __future__ import annotations

import hashlib
import math
import unicodedata
from pathlib import Path
from typing import NamedTuple

from . import catalog, formats, thumbnail
from .motion import CATEGORIES
from .validate import FILES_SOURCES, NotJson, clean_name, parse_json

MAX_FILES = 4
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_VIDEO_BYTES = 16 * 1024 * 1024
TEXT_MAX = {"description": 1000, "source": 200}
LABEL_MAX = 120
WEBM_MAGIC = b"\x1a\x45\xdf\xa3"
# A name with one of these endings was meant as a video, so a failed magic check says so.
VIDEO_SUFFIXES = (".webm", ".mp4", ".m4v", ".mov", ".mkv", ".avi", ".ogv", ".3gp", ".mpg",
                  ".mpeg", ".wmv", ".flv")
KIND_WORDS = {"keyframes": "key frames", "skeleton": "skeleton", "animation": "animation",
              "video": "video"}
ID_HINT = ("id: use 1 to 63 lowercase letters, digits or dashes, starting with a letter or "
           "digit")
PART_HINT = "use a whole number from 1 to 7, or null"
PARTS_HINT = "parts: use an object of file kind to part number (1 to 7, or null)"


class ImportProblem(ValueError):
    """The files cannot become an entry; the message is the plain-words reason."""


class Shared(NamedTuple):
    """One shared JSON file, read: its stored bytes, normalized form and provenance extras."""
    kind: str
    data: bytes
    normalized: dict
    part: int | None
    source: str | None
    original_name: str | None


class Video(NamedTuple):
    data: bytes
    ext: str
    part: int | None
    source: str | None
    original_name: str | None


# reading

def video_ext(data):
    """"webm" for a WebM (EBML header), "mp4" for an MP4 (`ftyp` at byte 4), else None."""
    if data[:4] == WEBM_MAGIC:
        return "webm"
    return "mp4" if data[4:8] == b"ftyp" else None


def file_label(name):
    """A dropped file's name as shown in messages: last path part, no control characters."""
    if not isinstance(name, str):
        return "file"
    label = "".join(c for c in name.replace("\\", "/").rsplit("/", 1)[-1]
                    if unicodedata.category(c) != "Cc").strip()
    return label[:LABEL_MAX] or "file"


def _parse(data, file):
    try:
        return parse_json(data)
    except NotJson:
        raise ImportProblem(f"{file}: is not valid JSON") from None


def read_shared(kind, *, data=None, parsed=None, file=None, part=None, source=None,
                original_name=None):
    """Read one shared file through its reader. Give `data` (bytes, kept as is) or `parsed`
    (stored as compact JSON); raises ImportProblem with the reader's E-message."""
    file = file or f"{kind}.json"
    if parsed is None:
        parsed = _parse(data, file)
    try:
        normalized = formats.read(kind, parsed, file)
    except formats.FormatError as exc:
        raise ImportProblem(str(exc)) from None
    if data is None:
        try:
            data = catalog.compact_json(parsed).encode("utf-8")
        except (TypeError, ValueError):
            raise ImportProblem(f"{file}: is not valid JSON") from None
    return Shared(kind, data, normalized, part, source, original_name)


def _detect_kind(parsed, file):
    try:
        return formats.detect_kind(parsed, file)
    except formats.FormatError as exc:
        raise ImportProblem(str(exc)) from None


def _classify(item):
    """(kind, label, data, parsed or video extension) of one dropped file; raises ImportProblem.
    Sizes are checked before anything is parsed."""
    if not (isinstance(item, dict) and isinstance(item.get("name"), str)
            and isinstance(item.get("data"), (bytes, bytearray))):
        raise ImportProblem("files")
    label, data = file_label(item["name"]), bytes(item["data"])
    ext = video_ext(data)
    video_named = label.lower().endswith(VIDEO_SUFFIXES)
    if len(data) > (MAX_VIDEO_BYTES if ext or video_named else MAX_JSON_BYTES):
        raise ImportProblem(f"{label}: file too large")
    if ext:
        return "video", label, data, ext
    if video_named:
        raise ImportProblem(f"{label}: not a WebM or MP4 video")
    parsed = _parse(data, label)
    return _detect_kind(parsed, label), label, data, parsed


def part_for(part, kind, parsed=None):
    """The part recorded for one file (AC-C06): `part` is None, a whole number for every file, or
    {kind or "*": number}. A number named for the kind wins, then "*" or the plain number, then the
    producer the file declares itself (`formats.declared_producer`), else None (not known)."""
    if isinstance(part, dict):
        chosen = part.get(kind, part.get("*"))
    else:
        chosen = part
    return chosen if chosen is not None else formats.declared_producer(parsed)


def load_items(items, part=None, source=None):
    """{kind: Shared or Video} for the dropped files, at most one per kind. A second file of a
    kind is refused before its content is read. `part` as in `part_for`."""
    if not isinstance(items, (list, tuple)) or not items:
        raise ImportProblem("files")
    if len(items) > MAX_FILES:
        raise ImportProblem("too many files")
    loaded = {}
    for item in items:
        kind, label, data, detail = _classify(item)
        if kind in loaded:
            raise ImportProblem(f"two {kind} files")
        if kind == "video":
            loaded[kind] = Video(data, detail, part_for(part, kind), source, label)
        else:
            loaded[kind] = read_shared(kind, data=data, parsed=detail, file=label,
                                       part=part_for(part, kind, detail), source=source,
                                       original_name=label)
    return loaded


# the request fields

def _clean_text(value, field):
    if value is None:
        return None
    text = " ".join(value.split()) if isinstance(value, str) else None
    if text is None or len(text) > TEXT_MAX[field] or any(
            unicodedata.category(c) == "Cc" for c in text):
        raise ImportProblem(field)
    return text or None


PART_KEYS = formats.KINDS + ("video", "*")


def _clean_part(part):
    """None, a whole number from 1 to 7, or {kind or "*": that number}; raises ImportProblem."""
    if isinstance(part, dict):
        if not part or any(key not in PART_KEYS for key in part):
            raise ImportProblem("part")
        return {key: _clean_part(value) for key, value in part.items()}
    if part is not None and not (isinstance(part, int) and not isinstance(part, bool)
                                 and 1 <= part <= 7):
        raise ImportProblem("part")
    return part


def _clean_name_and_category(name, category):
    clean = clean_name(name)
    if clean is None:
        raise ImportProblem("name")
    if category not in CATEGORIES:
        raise ImportProblem("category")
    return clean


def _default_description(loaded, now):
    words = ", ".join(word for kind, word in KIND_WORDS.items() if kind in loaded)
    return f"Imported on {now:%Y-%m-%d}. Files: {words}."


# building and writing

def _provenance(shared, video):
    """Provenance per file. `part` is the part given with the file (`--part`, the producer the
    file declares, or the part a processor declares), else None (not known): the format alone
    never names a producer (AC-C06, AC-C09)."""
    out = {}
    for kind in formats.KINDS:
        if kind in shared:
            entry = shared[kind]
            fmt = entry.normalized["format"]
            record = {"part": entry.part, "format": fmt, "detected_by": entry.normalized["detected_by"]}
            out[kind] = _with_hash(record, entry)
    if video:
        out["video"] = _with_hash({"part": video.part, "format": None, "detected_by": "file"},
                                  video)
    return out


def _with_hash(record, entry):
    record["sha256"] = hashlib.sha256(entry.data).hexdigest()
    record["bytes"] = len(entry.data)
    for field in ("source", "original_name"):
        if getattr(entry, field):
            record[field] = getattr(entry, field)
    return record


def duration_ms_of(animation):
    """Whole milliseconds of a normalized animation: floor(last t * 1000 + 0.5), at least 1."""
    return max(1, math.floor(animation["frames"][-1]["t"] * 1000 + 0.5))


class Prepared(NamedTuple):
    """A new entry made ready to write: its manifest without an id (and without `visitor`) and
    every file's bytes. Building it reads nothing from the catalog, so a server does it outside
    its save lock."""
    manifest: dict
    files: dict


def prepare_entry(*, name, category, files_source, description, created_at, shared, video=None,
                  duration_ms=None):
    """Make the manifest and files of one entry from read files.

    `shared` is {kind: Shared}, `video` a Video or None. The thumbnail comes from what plays
    (`formats.playable`); `duration_ms` is that animation's unless given. Raises ImportProblem (E12 when nothing plays)."""
    try:
        play = formats.playable(shared["animation"].normalized if "animation" in shared else None,
                                shared["skeleton"].normalized if "skeleton" in shared else None)
    except formats.FormatError as exc:
        raise ImportProblem(str(exc)) from None
    manifest = catalog.build_manifest(
        None, name, category, duration_ms or duration_ms_of(play), files_source,
        description, created_at, kinds=tuple(shared),
        video_uri=f"video.{video.ext}" if video else None,
        provenance=_provenance(shared, video))
    files = {manifest[kind]: shared[kind].data for kind in shared}
    files[manifest["thumbnail"]] = thumbnail.svg(play)
    if video:
        files[manifest["video_uri"]] = video.data
    return Prepared(manifest, files)


def write_prepared(root, entry_id, prepared, visitor=None):
    """Write a prepared entry as `entry_id` and return its manifest. `visitor` is left out of the
    manifest when None. Raises FileExistsError when the id is taken. Does not check the root;
    callers that take requests call `catalog.guard_root` first."""
    manifest = dict(prepared.manifest, id=entry_id)
    if visitor is not None:
        manifest["visitor"] = visitor
    catalog.write_shared_entry(root, entry_id, manifest, prepared.files)
    return manifest


def add_entry(root, *, entry_id, name, category, files_source, description, created_at,
              shared, video=None, duration_ms=None, visitor=None):
    """Write one entry from read files and return its manifest (`prepare_entry`, then
    `write_prepared`). Raises ImportProblem or FileExistsError."""
    prepared = prepare_entry(
        name=name, category=category, files_source=files_source, description=description,
        created_at=created_at, shared=shared, video=video, duration_ms=duration_ms)
    return write_prepared(root, entry_id, prepared, visitor)


def _check_id(entry_id):
    if entry_id is not None and not catalog.is_valid_id(entry_id):
        raise ImportProblem(ID_HINT)


def _free_ids(name, entry_id):
    """The ids to try, in order: the one asked for, else new ones made from the name."""
    if entry_id is not None:
        yield entry_id
        return
    for _ in range(catalog.ID_RETRIES):
        yield catalog.new_id(name)


def _write_with_id(root, name, entry_id, build):
    """`build(id)` with the asked-for id or a fresh one; a taken id is refused or retried."""
    for candidate in _free_ids(name, entry_id):
        if (Path(root) / candidate).exists():
            if entry_id is not None:
                raise ImportProblem(f"id: {entry_id} is already in the catalog")
            continue
        try:
            return build(candidate)
        except FileExistsError:
            if entry_id is not None:
                raise ImportProblem(f"id: {entry_id} is already in the catalog") from None
    raise RuntimeError("could not allocate an entry id")


def prepare_import(name, category, items, *, entry_id=None, description=None, source=None,
                   part=None, created_at=None):
    """Check and read dropped files and make them ready to write: a `Prepared`. This is all the
    slow work of an import (parsing, the readers, hashes, the thumbnail) and writes nothing.
    `entry_id` is only checked here. Raises ImportProblem."""
    name = _clean_name_and_category(name, category)
    _check_id(entry_id)
    description, source, part = (_clean_text(description, "description"),
                                _clean_text(source, "source"), _clean_part(part))
    loaded = load_items(items, part, source)
    shared = {k: v for k, v in loaded.items() if k != "video"}
    now = catalog.utc_now()
    stamp = created_at or f"{now:%Y-%m-%dT%H:%M:%SZ}"
    return prepare_entry(
        name=name, category=category, files_source="import", created_at=stamp, shared=shared,
        description=description or _default_description(loaded, now), video=loaded.get("video"))


def commit_import(root, prepared, *, entry_id=None, visitor=False):
    """Write a `Prepared` import as a new entry and return its manifest: the asked-for id, else a
    fresh one made from the name. Only this step needs a lock. Raises ImportProblem when the id
    is taken."""
    catalog.guard_root(root)
    return _write_with_id(root, prepared.manifest["name"], entry_id,
                          lambda candidate: write_prepared(root, candidate, prepared, bool(visitor)))


def import_files(root, name, category, items, *, entry_id=None, description=None, source=None,
                 part=None, visitor=False, created_at=None):
    """Import dropped files as one new entry; returns its manifest.

    `items` is [{"name": str, "data": bytes}]: at most MAX_FILES, one per kind, kinds found by
    `formats.detect_kind`, each JSON file read through its reader, a video only when it is a
    WebM or MP4. Raises ImportProblem; nothing is written then. `prepare_import` followed by
    `commit_import`."""
    catalog.guard_root(root)
    prepared = prepare_import(name, category, items, entry_id=entry_id, description=description,
                              source=source, part=part, created_at=created_at)
    return commit_import(root, prepared, entry_id=entry_id, visitor=visitor)


def _declared_parts(parts, files):
    """{kind: part or None} from a processor's optional `parts`: a dict of kind to a whole number
    from 1 to 7 or None. Kinds it did not return are ignored. Raises ImportProblem."""
    if parts is None:
        return {}
    if not isinstance(parts, dict):
        raise ImportProblem(PARTS_HINT)
    out = {}
    for kind in formats.KINDS:
        if files.get(kind) is not None and parts.get(kind) is not None:
            try:
                out[kind] = _clean_part(parts[kind])
            except ImportProblem:
                raise ImportProblem(f"parts.{kind}: {PART_HINT}") from None
    return out


def store_processed(root, recording, files, *, files_source, description, visitor=True,
                    created_at=None, parts=None):
    """Store the parsed files a processor returned as the entry `recording["id"]`.

    `files` is {"keyframes"?, "skeleton"?, "animation"?} of parsed JSON, stored as compact JSON.
    `parts` is the processor's optional {kind: part} (AC-C09): provenance records each file's
    format and the part declared for it, else null. Raises ImportProblem (the reader's E-message,
    a bad `parts`, or E12) or FileExistsError."""
    catalog.guard_root(root)
    if files_source not in FILES_SOURCES:
        raise ValueError(f"files_source must be one of {', '.join(FILES_SOURCES)}")
    entry_id = recording.get("id")
    if entry_id is None:
        raise ImportProblem(ID_HINT)
    _check_id(entry_id)
    name = _clean_name_and_category(recording.get("name"), recording.get("category"))
    declared = _declared_parts(parts, files)
    shared = {kind: read_shared(kind, parsed=files[kind], part=declared.get(kind))
              for kind in formats.KINDS if files.get(kind) is not None}
    stamp = created_at or f"{catalog.utc_now():%Y-%m-%dT%H:%M:%SZ}"
    duration = recording.get("duration_ms")
    ok = isinstance(duration, int) and not isinstance(duration, bool) and duration > 0
    return add_entry(root, entry_id=entry_id, name=name, category=recording["category"],
                     files_source=files_source, description=description, created_at=stamp,
                     shared=shared, duration_ms=duration if ok else None, visitor=bool(visitor))
