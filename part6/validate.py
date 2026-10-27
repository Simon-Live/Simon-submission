"""Validators for the shared files (docs/specs/shared-files.md sections 1 to 4) and the create body.

Each `check_*` returns a list of short messages, empty when valid, capped at MAX_ERRORS so a
broken 300-frame file does not print 300 lines. `check_catalog` backs `python3 -m part6 validate`.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import datetime
from itertools import islice
from pathlib import Path

from .motion import CATEGORIES, JOINTS

MAX_ERRORS = 10
# \Z, not $: "$" would also accept a trailing newline.
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}\Z")
FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\Z")
FILES_SOURCES = ("fixture", "mock", "pipeline")
NAME_MAX = 80
DURATION_MIN_MS, DURATION_MAX_MS = 1000, 120000


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


def _manifest_errors(data, folder_name):
    if not isinstance(data, dict):
        yield "manifest: not an object"
        return
    eid = data.get("id")
    if not (isinstance(eid, str) and ID_RE.match(eid)):
        yield "id: does not match ^[a-z0-9][a-z0-9-]{0,62}$"
    elif folder_name is not None and eid != folder_name:
        yield "id: differs from the folder name"
    if not (isinstance(data.get("name"), str) and data["name"].strip()):
        yield "name: not a non-empty string"
    if data.get("video_uri") is not None and not isinstance(data["video_uri"], str):
        yield "video_uri: must be null or a string"
    for field in ("keyframes", "skeleton", "animation", "thumbnail"):
        value = data.get(field)
        if not (isinstance(value, str) and FILE_RE.match(value)):
            yield f"{field}: not a plain file name"
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
        yield "files_source: must be fixture, mock or pipeline"


def check_keyframes(data):
    return _capped(_keyframes_errors(data))


def check_skeleton(data):
    return _capped(_skeleton_errors(data))


def check_animation(data):
    return _capped(_animation_errors(data))


def check_manifest(data, folder_name=None):
    return _capped(_manifest_errors(data, folder_name))


def read_json(path):
    """Parsed JSON of a file, or raises ValueError with a short reason."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError("file is missing") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unreadable JSON: {exc}") from None


def check_entry(folder):
    """Every error of one entry folder: manifest, then the files it names."""
    folder = Path(folder)
    try:
        manifest = read_json(folder / "manifest.json")
    except ValueError as exc:
        return [f"manifest.json: {exc}"]
    errors = [f"manifest.json: {m}" for m in check_manifest(manifest, folder.name)]
    if errors:
        return errors
    checks = (("keyframes", check_keyframes), ("skeleton", check_skeleton),
              ("animation", check_animation))
    for field, check in checks:
        errors += _file_errors(folder, manifest[field], check)
    thumb = folder / manifest["thumbnail"]
    if not thumb.is_file() or thumb.stat().st_size == 0:
        errors.append(f"{manifest['thumbnail']}: file is missing or empty")
    return errors


def _file_errors(folder, name, check):
    try:
        data = read_json(folder / name)
    except ValueError as exc:
        return [f"{name}: {exc}"]
    return [f"{name}: {m}" for m in check(data)]


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
