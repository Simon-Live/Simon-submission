"""`python3 -m part6 doctor <entry folder or file>`: what would fail, in plain words (AC-C05).

A folder is checked as a catalog entry: the manifest against contract v1, each named file through
`part6.formats`, hashes against provenance, thumbnail and video present, and what the player would
do. A single file is checked as one shared file. Output is one line per file, then one JSON line
`{entry, ok, plays, problems}`. Exit 0 when valid and playable, 1 when not, 2 for a missing path.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from . import contract, formats, schema_check, validate


def _decode(raw, name):
    """(parsed JSON, None) or (None, "<name>: is not valid JSON"), parsed as the importer does."""
    try:
        return validate.parse_json(raw), None
    except validate.NotJson:
        return None, f"{name}: is not valid JSON"


def _part_text(part):
    return f", part {part}" if part is not None else ""


def _plain(name):
    return isinstance(name, str) and validate.FILE_RE.match(name) is not None


def _root_key(message):
    """The first path segment of a "path: reason" message ("$" for the whole document)."""
    return message.split(":", 1)[0].split(".")[0].split("[")[0]


def _manifest_problems(manifest, folder_name):
    """Problems from the validator, then those of the schema about paths the validator did not name."""
    problems = [f"manifest.json: {m}" for m in validate.check_manifest(manifest, folder_name)]
    named = {_root_key(m.split(": ", 1)[1]) for m in problems}
    for message in schema_check.errors(manifest, contract.schema("manifest")):
        key = _root_key(message)
        # "$" is a rule over several fields (a skeleton or an animation); the validator said it already.
        if key not in named and not (key == "$" and problems):
            problems.append(f"manifest.json: {message}")
    return problems


def _hash_problems(name, raw, claim):
    if not isinstance(claim, dict):
        return []
    if claim.get("sha256") != hashlib.sha256(raw).hexdigest():
        return [f"{name}: sha256 differs from provenance"]
    if claim.get("bytes") != len(raw):
        return [f"{name}: size differs from provenance"]
    return []


class _Report:
    """The lines and problems of one diagnosis: one line per file, one `fail` line per problem."""

    def __init__(self):
        self.problems, self.lines = [], []

    def file(self, ok_text, problems):
        if problems:
            self.problems += problems
            self.lines += [f"fail {p}" for p in problems]
        else:
            self.lines.append(f"ok {ok_text}")


def _read_data_file(folder, kind, name, claim):
    """(normalized or None, reading error or None, hash problems) for a named JSON file."""
    path = folder / name
    if not path.is_file():
        return None, f"{name}: file is missing", []
    raw = path.read_bytes()
    data, bad = _decode(raw, name)
    if bad:
        return None, bad, []
    try:
        return formats.read(kind, data, name), None, _hash_problems(name, raw, claim)
    except formats.FormatError as exc:
        return None, str(exc), []


def _check_data_file(folder, kind, name, claim, report):
    """Check one file and add its line. Returns (normalized or None, reading error or None)."""
    normal, error, bad_hash = _read_data_file(folder, kind, name, claim)
    if error:
        report.file(None, [error])
        return None, error
    if isinstance(claim, dict) and "part" in claim:
        part = claim["part"] if claim["part"] is not None else "unknown"
    else:
        part = formats.PRODUCER.get(normal["format"])    # no provenance: the usual producer
    report.file(f"{name}: {normal['format']} ({normal['detected_by']}){_part_text(part)}", bad_hash)
    return normal, None


def _check_support_file(folder, name, label, claim, report):
    """Thumbnail or video: present, not empty, and its hash when provenance has one."""
    path = folder / name
    if not path.is_file():
        return report.file(None, [f"{name}: file is missing"])
    raw = path.read_bytes()
    if not raw:
        return report.file(None, [f"{name}: file is empty"])
    part = (claim.get("part") or "unknown") if isinstance(claim, dict) else None
    report.file(f"{name}: {label}{_part_text(part)}", _hash_problems(name, raw, claim))


def _plays(read, errors):
    """What the player would do, from the files that read and the messages of those that did not."""
    animation, skeleton = read.get("animation"), read.get("skeleton")
    try:
        formats.playable(animation, skeleton)
    except formats.FormatError as exc:
        reason = next((errors[k] for k in ("animation", "skeleton") if k in errors), str(exc))
        return f"cannot play: {reason}"
    if animation is not None:
        return "plays animation"
    if "animation" in errors:
        return "plays skeleton (animation unreadable)"
    return "plays skeleton (no animation)"


def _result(entry, report, plays):
    ok = not report.problems and plays.startswith("plays")
    return {"entry": entry, "ok": ok, "plays": plays, "problems": report.problems,
            "lines": report.lines}


def _refused(entry, message, plays):
    report = _Report()
    report.file(None, [message])
    return _result(entry, report, plays)


def _diagnose_folder(folder):
    folder_name = folder.resolve().name
    try:
        raw = (folder / "manifest.json").read_bytes()
    except OSError:
        return _refused(folder_name, "manifest.json: file is missing",
                        "cannot play: manifest.json is missing")
    manifest, bad = _decode(raw, "manifest.json")
    if bad:
        return _refused(folder_name, bad, "cannot play: manifest.json is not valid JSON")
    report = _Report()
    report.file("manifest.json: manifest v1", _manifest_problems(manifest, folder_name))
    if not isinstance(manifest, dict):
        return _result(folder_name, report, "cannot play: manifest.json is not an object")
    entry = manifest["id"] if isinstance(manifest.get("id"), str) else folder_name
    provenance = manifest.get("provenance")
    claims = provenance if isinstance(provenance, dict) else {}
    read, errors = {}, {}
    for kind in formats.KINDS:
        if _plain(manifest.get(kind)):
            normal, error = _check_data_file(folder, kind, manifest[kind], claims.get(kind), report)
            if normal is not None:
                read[kind] = normal
            else:
                errors[kind] = error
    if _plain(manifest.get("thumbnail")):
        _check_support_file(folder, manifest["thumbnail"], "thumbnail", None, report)
    if _plain(manifest.get("video_uri")):
        _check_support_file(folder, manifest["video_uri"], "video (file)", claims.get("video"), report)
    return _result(entry, report, _plays(read, errors))


def _diagnose_file(path):
    name = path.name
    base = {"entry": name, "ok": False, "plays": None, "problems": [], "lines": [],
            "kind": None, "format": None}
    data, bad = _decode(path.read_bytes(), name)
    if bad:
        return dict(base, problems=[bad], lines=[f"fail {bad}"])
    try:
        kind = formats.detect_kind(data, name)
        normal = formats.read(kind, data, name)
    except formats.FormatError as exc:
        return dict(base, problems=[str(exc)], lines=[f"fail {exc}"])
    part = formats.PRODUCER.get(normal["format"])
    plays = {"animation": "plays animation", "skeleton": "plays skeleton (no animation)"}.get(kind)
    line = f"ok {name}: {kind}, {normal['format']} ({normal['detected_by']}){_part_text(part)}"
    return dict(base, ok=True, plays=plays, lines=[line], kind=kind, format=normal["format"])


def diagnose(path):
    """{"entry", "ok", "plays", "problems", "lines"} for an entry folder or a single file.

    A single file also carries "kind" and "format". Raises FileNotFoundError for a missing path.
    """
    target = Path(path)
    if target.is_dir():
        return _diagnose_folder(target)
    if target.is_file():
        return _diagnose_file(target)
    raise FileNotFoundError(str(path))


def run(path, out=sys.stdout):
    """Print the lines, then the JSON line. Exit code 0 ok, 1 not ok, 2 missing path."""
    try:
        result = diagnose(path)
    except FileNotFoundError:
        print(f"doctor: {path} is not a folder or a file", file=sys.stderr)
        return 2
    for line in result["lines"]:
        out.write(line + "\n")
    out.write(json.dumps({k: result[k] for k in ("entry", "ok", "plays", "problems")}) + "\n")
    return 0 if result["ok"] else 1
