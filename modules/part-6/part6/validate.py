"""Validators for catalog entries (docs/specs/catalog-contract.md AC-C01) and the create body.

Each `check_*` returns a list of short messages, empty when valid, capped at MAX_ERRORS so a
broken 300-frame file does not print 300 lines. `check_catalog` backs `python3 -m part6 validate`.

`check_entry` reads the files an entry names through `part6/formats.py`, so any known format
passes. `check_keyframes`, `check_skeleton` and `check_animation` are the strict checks of Part 6's
own shapes (`simon.keyframes/part1`, `simon.skeleton/1`, `simon.animation/1`); they stay for the
files Part 6 writes itself (docs/specs/formats.md AC-F12).
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import datetime
from itertools import islice
from pathlib import Path

from . import formats
from .motion import CATEGORIES, JOINTS

MAX_ERRORS = 10
# \Z, not $: "$" would also accept a trailing newline.
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}\Z")
FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\Z")
FILES_SOURCES = ("fixture", "mock", "import", "processor")
PROVENANCE_KINDS = (*formats.KINDS, "video")
DETECTED_BY = ("version", "shape")
SHA256_RE = re.compile(r"^[0-9a-f]{64}\Z")
NAME_MAX = 80
DURATION_MIN_MS, DURATION_MAX_MS = 1000, 120000


class NotJson(ValueError):
    """Bytes that are not strict JSON; the message is "is not valid JSON"."""


# The longest integer text that always fits a double (1.797e308 has 309 digits).
SAFE_INT_CHARS = 308


def _no_constant(name):
    raise ValueError(f"{name} is not JSON")


def parse_float(text):
    """A JSON number with a fraction or exponent as a float; ValueError when it does not fit a
    double (`1e400` reads as infinity, which a browser also cannot hold)."""
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"{text[:20]} does not fit a number")
    return value


def parse_int(text):
    """A JSON integer. One too long to be sure it fits a double (this also covers more digits than
    Python's own limit, which would raise) is read as a float, so it is refused when not finite."""
    return parse_float(text) if len(text) > SAFE_INT_CHARS else int(text)


def parse_json(raw):
    """Parsed JSON of bytes (UTF-8, an optional byte order mark) or text, parsed as strictly as a
    browser: `NaN`, `Infinity` and `-Infinity` are refused, and so is a number that does not fit
    a double (`1e400`, `-1e400`, an integer of 400 digits). The one parser for every file and
    request body Part 6 reads (docs/specs/formats.md "Error Cases"). Raises NotJson for anything
    that is not JSON, including text nested too deep to parse."""
    try:
        text = raw.decode("utf-8-sig") if isinstance(raw, (bytes, bytearray)) else raw
        return json.loads(text, parse_constant=_no_constant, parse_float=parse_float,
                          parse_int=parse_int)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise NotJson("is not valid JSON") from None


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _capped(gen):
    return list(islice(gen, MAX_ERRORS))


def _keyframes_errors(data):
    if not isinstance(data, dict):
        yield "keyframes: not an object"
        return
    if "fps" in data and not (is_number(data["fps"]) and data["fps"] > 0):
        yield "fps: not a positive number"
    people = data.get("people")
    if not isinstance(people, list):
        yield "people: not a list"
        return
    for pi, person in enumerate(people):
        reps = person.get("repetitions") if isinstance(person, dict) else None
        if not isinstance(reps, list):
            yield f"people[{pi}].repetitions: not a list"
            continue
        for ri, rep in enumerate(reps):
            marks = rep.get("keyframes") if isinstance(rep, dict) else None
            if not isinstance(marks, list):
                yield f"people[{pi}].repetitions[{ri}].keyframes: not a list"
                continue
            for ki, mark in enumerate(marks):
                where = f"people[{pi}].repetitions[{ri}].keyframes[{ki}]"
                if not isinstance(mark, dict) or not isinstance(mark.get("name"), str):
                    yield f"{where}.name: not a string"
                elif not (is_number(mark.get("t_ms")) and mark["t_ms"] >= 0):
                    yield f"{where}.t_ms: not a non-negative number"


def _joint_errors(person, where):
    joints = person.get("joints") if isinstance(person, dict) else None
    if not isinstance(joints, dict):
        yield f"{where}.joints: not an object"
        return
    for name in JOINTS:
        j = joints.get(name)
        if not isinstance(j, dict):
            yield f"{where}.joints.{name}: missing"
        elif not all(is_number(j.get(k)) for k in "xyz"):
            yield f"{where}.joints.{name}: x, y, z must be finite numbers"


def _skeleton_errors(data):
    if not isinstance(data, dict):
        yield "skeleton: not an object"
        return
    if data.get("schema") != "simon.skeleton/1":
        yield "schema: must be simon.skeleton/1"
    lengths = data.get("bone_lengths_m")
    if not isinstance(lengths, dict) or not all(is_number(v) and v > 0 for v in lengths.values()):
        yield "bone_lengths_m: must be an object of positive numbers"
    frames = data.get("frames")
    if not isinstance(frames, list) or not frames:
        yield "frames: must be a non-empty list"
        return
    present = False
    for i, frame in enumerate(frames):
        if not isinstance(frame, dict):
            yield f"frames[{i}]: not an object"
            continue
        people = frame.get("people")
        if not is_number(frame.get("t_ms")):
            yield f"frames[{i}].t_ms: not a number"
        elif not isinstance(people, list) or len(people) > 1:
            yield f"frames[{i}].people: must be a list of 0 or 1 entries"
        elif people:
            present = True
            yield from _joint_errors(people[0], f"frames[{i}].people[0]")
    if not present:
        yield "frames: no frame has a person"


def _animation_errors(data):
    if not isinstance(data, dict):
        yield "animation: not an object"
        return
    if "schema" in data and data["schema"] != "simon.animation/1":
        yield "schema: must be simon.animation/1"
    if not (is_number(data.get("fps")) and data["fps"] > 0):
        yield "fps: not a positive number"
    frames = data.get("frames")
    if not isinstance(frames, list) or not frames:
        yield "frames: must be a non-empty list"
        return
    last_t = None
    for i, frame in enumerate(frames):
        if not isinstance(frame, dict):
            yield f"frames[{i}]: not an object"
            continue
        if frame.get("frame") != i or not is_int(frame.get("frame")):
            yield f"frames[{i}].frame: must equal its index"
        t = frame.get("t_ms")
        if not is_number(t) or (last_t is not None and t <= last_t):
            yield f"frames[{i}].t_ms: must be a number above the previous frame"
        else:
            last_t = t
        if not isinstance(frame.get("interpolated"), bool):
            yield f"frames[{i}].interpolated: not a boolean"
        people = frame.get("people")
        if not isinstance(people, list) or not people:
            yield f"frames[{i}].people: must hold a first person"
        else:
            yield from _joint_errors(people[0], f"frames[{i}].people[0]")


def _utc_stamp(value):
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return False
    return True


def _plain_name(value):
    return isinstance(value, str) and FILE_RE.match(value) is not None


def _provenance_file_errors(kind, entry, where):
    if not isinstance(entry, dict):
        yield f"{where}: not an object"
        return
    part = entry.get("part")
    if not (part is None and "part" in entry) and not (is_int(part) and 1 <= part <= 7):
        yield f"{where}.part: must be a whole number from 1 to 7, or null"
    fmt, how = entry.get("format"), entry.get("detected_by")
    if kind == "video":
        if fmt is not None:
            yield f"{where}.format: must be null for a video"
        if how != "file":
            yield f"{where}.detected_by: must be file for a video"
    else:
        if fmt not in formats.FORMATS[kind]:
            yield f"{where}.format: must be one of {', '.join(formats.FORMATS[kind])}"
        if how not in DETECTED_BY:
            yield f"{where}.detected_by: must be version or shape"
    if not (isinstance(entry.get("sha256"), str) and SHA256_RE.match(entry["sha256"])):
        yield f"{where}.sha256: must be 64 lowercase hex characters"
    if not (is_int(entry.get("bytes")) and entry["bytes"] >= 0):
        yield f"{where}.bytes: must be a whole number of 0 or more"
    for optional in ("source", "original_name"):
        if optional in entry and not isinstance(entry[optional], str):
            yield f"{where}.{optional}: must be a string"


def _provenance_errors(data):
    if not isinstance(data, dict):
        yield "provenance: must be an object"
        return
    # A key this version does not know is ignored, never a reason to hide the entry (AC-C01).
    for kind in PROVENANCE_KINDS:
        if kind in data:
            yield from _provenance_file_errors(kind, data[kind], f"provenance.{kind}")


def _manifest_errors(data, folder_name):
    if not isinstance(data, dict):
        yield "manifest: not an object"
        return
    eid = data.get("id")
    if not (isinstance(eid, str) and ID_RE.match(eid)):
        yield "id: does not match ^[a-z0-9][a-z0-9-]{0,62}$"
    elif folder_name is not None and eid != folder_name:
        yield "id: differs from the folder name"
    name = data.get("name")
    if not (isinstance(name, str) and 1 <= len(name) <= NAME_MAX and name == name.strip()):
        yield "name: must be 1 to 80 characters with no space at either end"
    for field in ("video_uri", *formats.KINDS):
        if field not in data:
            yield f"{field}: is required"
        elif data[field] is not None and not _plain_name(data[field]):
            yield f"{field}: must be null or a plain file name"
    if data.get("skeleton") is None and data.get("animation") is None:
        yield "skeleton, animation: at least one must name a file"
    if not _plain_name(data.get("thumbnail")):
        yield "thumbnail: not a plain file name"
    if not _utc_stamp(data.get("created_at")):
        yield "created_at: not YYYY-MM-DDTHH:MM:SSZ"
    if data.get("schema_version") != 1 or not is_int(data.get("schema_version")):
        yield "schema_version: must be 1"
    if data.get("category") not in CATEGORIES:
        yield "category: must be exercise or dance"
    if not isinstance(data.get("description"), str):
        yield "description: not a string"
    if not (is_int(data.get("duration_ms")) and data["duration_ms"] > 0):
        yield "duration_ms: not a positive integer"
    if data.get("files_source") not in FILES_SOURCES:
        yield f"files_source: must be {', '.join(FILES_SOURCES[:-1])} or {FILES_SOURCES[-1]}"
    if "provenance" in data:
        yield from _provenance_errors(data["provenance"])
    if "visitor" in data and not isinstance(data["visitor"], bool):
        yield "visitor: must be true or false"


def check_keyframes(data):
    return _capped(_keyframes_errors(data))


def check_skeleton(data):
    return _capped(_skeleton_errors(data))


def check_animation(data):
    return _capped(_animation_errors(data))


def check_manifest(data, folder_name=None):
    return _capped(_manifest_errors(data, folder_name))


def read_json(path):
    """Parsed JSON of a file (see `parse_json`), or raises ValueError with a short reason:
    "file is missing", "is not valid JSON" or the operating system's words."""
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        raise ValueError("file is missing") from None
    except OSError as exc:
        raise ValueError(f"unreadable: {exc.strerror or exc}") from None
    return parse_json(raw)


def check_entry(folder):
    """Every error of one entry folder: manifest, then the files it names read through
    `part6/formats.py` (any known format passes), the video and the thumbnail."""
    folder = Path(folder)
    try:
        manifest = read_json(folder / "manifest.json")
    except ValueError as exc:
        return [f"manifest.json: {exc}"]
    errors = [f"manifest.json: {m}" for m in check_manifest(manifest, folder.name)]
    if errors:
        return errors
    for kind in formats.KINDS:
        if manifest[kind] is not None:
            errors += _file_errors(folder, kind, manifest[kind])
    video = manifest.get("video_uri")
    if video is not None and not (folder / video).is_file():
        errors.append(f"{video}: file is missing")
    thumb = folder / manifest["thumbnail"]
    if not thumb.is_file() or thumb.stat().st_size == 0:
        errors.append(f"{manifest['thumbnail']}: file is missing or empty")
    return errors


def _file_errors(folder, kind, name):
    try:
        data = read_json(folder / name)
    except ValueError as exc:
        return [f"{name}: {exc}"]
    try:
        formats.read(kind, data, name)
    except formats.FormatError as exc:
        return [str(exc)]
    return []


def entry_folders(root):
    """Non-dot subfolders of root in name order; [] when root is missing."""
    try:
        return sorted(p for p in Path(root).iterdir() if p.is_dir() and not p.name.startswith("."))
    except FileNotFoundError:
        return []


def check_catalog(root):
    """{entry id: errors} for every invalid entry folder under root; {} when all are valid."""
    problems = {}
    for folder in entry_folders(root):
        errors = check_entry(folder) if ID_RE.match(folder.name) else ["folder name is not an id"]
        if errors:
            problems[folder.name] = errors
    return problems


def clean_name(raw):
    """The stored name, or None: trimmed, inner whitespace collapsed, 1 to 80 characters."""
    if not isinstance(raw, str) or any(unicodedata.category(c) == "Cc" for c in raw):
        return None
    name = " ".join(raw.split())
    return name if 1 <= len(name) <= NAME_MAX else None


def clean_create_request(obj):
    """(fields, None) for a valid create body, else (None, name of the first bad field)."""
    name = clean_name(obj.get("name"))
    if name is None:
        return None, "name"
    if obj.get("category") not in CATEGORIES:
        return None, "category"
    duration = obj.get("duration_ms")
    if not is_int(duration) or not DURATION_MIN_MS <= duration <= DURATION_MAX_MS:
        return None, "duration_ms"
    return {"name": name, "category": obj["category"], "duration_ms": duration}, None
