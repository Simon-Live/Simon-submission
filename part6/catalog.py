"""Catalog storage: one folder per entry under a root (docs/specs/shared-files.md section 4).

Entries are read from disk on every call. A folder with a missing or invalid manifest is skipped
and logged to stderr. The id pattern is checked before any path is built from an id. Writes go
to `<root>/.tmp-<id>/` and are renamed into place, so a crash never leaves a half entry in the
listing (dot folders are never listed). The shipped fixtures are only ever read.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import processor, thumbnail
from .validate import FILE_RE, ID_RE, check_manifest, entry_folders, read_json

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_CATALOG = REPO_ROOT / "fixtures" / "output" / "catalog"
DEFAULT_ROOT = Path("~/.local/state/simon-part-6/catalog")
SLUG_MAX = 40
ID_RETRIES = 8


def log(message):
    print(f"part6: {message}", file=sys.stderr, flush=True)


def resolve_root(arg=None):
    """--catalog, else SIMON6_CATALOG_DIR, else ~/.local/state/simon-part-6/catalog."""
    chosen = arg or os.environ.get("SIMON6_CATALOG_DIR") or DEFAULT_ROOT
    return Path(chosen).expanduser()


def is_valid_id(entry_id):
    return isinstance(entry_id, str) and ID_RE.match(entry_id) is not None


class RootError(ValueError):
    """The catalog root is not somewhere the app may write."""


def guard_root(root):
    """Raise RootError when root is the shipped fixture catalog or inside it."""
    shipped = FIXTURE_CATALOG.resolve()
    resolved = Path(root).expanduser().resolve()
    if resolved == shipped or shipped in resolved.parents:
        raise RootError(f"{root} is the shipped fixture catalog or inside it; "
                        "pass another --catalog folder")


def read_manifest(root, entry_id):
    """The entry's manifest, or None. An unknown id is silent; a folder whose manifest is
    missing or invalid is logged as skipped."""
    if not is_valid_id(entry_id):
        return None
    folder = Path(root) / entry_id
    if not folder.is_dir():
        return None
    try:
        manifest = read_json(folder / "manifest.json")
    except ValueError as exc:
        log(f"skipping {entry_id}: manifest.json: {exc}")
        return None
    problems = check_manifest(manifest, entry_id)
    if problems:
        log(f"skipping {entry_id}: manifest.json: {problems[0]}")
        return None
    return manifest


def list_entries(root, q="", category=None):
    """Manifests sorted by name; q terms must all occur in the name (case-insensitive)."""
    terms = q.casefold().split()
    entries = []
    for folder in entry_folders(root):
        manifest = read_manifest(root, folder.name)
        if manifest is None:
            continue
        name = manifest["name"].casefold()
        if all(t in name for t in terms) and category in (None, manifest["category"]):
            entries.append(manifest)
    return sorted(entries, key=lambda m: (m["name"].casefold(), m["name"], m["id"]))


def served_names(manifest):
    """The files an entry serves: the four it names, and `video_uri` when it is a plain file name."""
    names = {manifest["keyframes"], manifest["skeleton"], manifest["animation"],
             manifest["thumbnail"]}
    video = manifest.get("video_uri")
    if isinstance(video, str) and FILE_RE.match(video):
        names.add(video)
    return names


def entry_file(root, entry_id, name):
    """Path of a file the entry's manifest names, or None (anything else is not served)."""
    manifest = read_manifest(root, entry_id)
    if manifest is None or not isinstance(name, str) or name not in served_names(manifest):
        return None
    path = Path(root) / entry_id / name
    return path if path.is_file() and not path.is_symlink() else None


def write_entry(root, entry_id, files):
    """Write `files` ({name: str or bytes}) as a new entry folder, atomically."""
    if not is_valid_id(entry_id):
        raise ValueError(f"invalid id: {entry_id!r}")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    final, tmp = root / entry_id, root / f".tmp-{entry_id}"
    if final.exists():
        raise FileExistsError(entry_id)
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    try:
        for name, content in files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            (tmp / name).write_bytes(data)
        os.rename(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return final


def _copy_entry(source, root):
    """Copy one fixture folder into root, replacing any folder of that name."""
    entry_id = source.name
    tmp, final = Path(root) / f".tmp-{entry_id}", Path(root) / entry_id
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(source, tmp)
    if final.exists():
        shutil.rmtree(final)
    os.rename(tmp, final)


def seed(root, source=None):
    """Copy every fixture entry into root when it has no entry folder; returns the count."""
    guard_root(root)
    source = Path(source) if source else FIXTURE_CATALOG
    if entry_folders(root):
        return 0
    Path(root).mkdir(parents=True, exist_ok=True)
    folders = [p for p in entry_folders(source) if is_valid_id(p.name)]
    for folder in folders:
        _copy_entry(folder, root)
    if folders:
        log(f"seeded {len(folders)} entries into {root}")
    return len(folders)


def _says_mock(folder):
    try:
        return read_json(folder / "manifest.json").get("files_source") == "mock"
    except (ValueError, AttributeError):
        return False


def reset(root, source=None):
    """Delete mock entries and dot folders, recopy every fixture entry; {"removed", "restored"}."""
    guard_root(root)
    root, source = Path(root), Path(source) if source else FIXTURE_CATALOG
    root.mkdir(parents=True, exist_ok=True)
    dot = [p for p in root.iterdir() if p.is_dir() and p.name.startswith(".")]
    doomed = [p for p in dot + [p for p in entry_folders(root) if _says_mock(p)]
              if not p.is_symlink()]
    for folder in doomed:
        shutil.rmtree(folder)
    folders = [p for p in entry_folders(source) if is_valid_id(p.name)]
    for folder in folders:
        _copy_entry(folder, root)
    return {"removed": len(doomed), "restored": len(folders)}


def slugify(name):
    """Lowercase ASCII letters and digits, other runs become -, at most 40 characters."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:SLUG_MAX].strip("-")
    return slug or "movement"


def new_id(name):
    return f"{slugify(name)}-{secrets.token_hex(4)}"


def utc_now():
    return datetime.now(timezone.utc)


def build_manifest(entry_id, name, category, duration_ms, files_source, description, created_at):
    return {"id": entry_id, "name": name, "video_uri": None,
            "keyframes": "keyframes.json", "skeleton": "skeleton.json",
            "animation": "animation.json", "created_at": created_at,
            "schema_version": 1, "category": category, "description": description,
            "thumbnail": "thumbnail.svg", "duration_ms": duration_ms,
            "files_source": files_source}


def entry_files(manifest, shared):
    """The files of an entry folder: manifest, the shared files and the thumbnail."""
    def compact(data):
        return json.dumps(data, separators=(",", ":")) + "\n"
    return {"manifest.json": json.dumps(manifest, indent=2) + "\n",
            manifest["keyframes"]: compact(shared["keyframes"]),
            manifest["skeleton"]: compact(shared["skeleton"]),
            manifest["animation"]: compact(shared["animation"]),
            manifest["thumbnail"]: thumbnail.svg(shared["animation"])}


def create_mock_entry(root, name, category, duration_ms):
    """Process a mock recording and store it as a new entry; returns its manifest."""
    for _ in range(ID_RETRIES):
        entry_id = new_id(name)
        if (Path(root) / entry_id).exists():
            continue
        now = utc_now()
        recording = {"id": entry_id, "name": name, "category": category,
                     "duration_ms": duration_ms, "video_path": None}
        manifest = build_manifest(
            entry_id, name, category, duration_ms, "mock",
            f"Mock recording from {now:%Y-%m-%d}. Capture and processing are mocked.",
            f"{now:%Y-%m-%dT%H:%M:%SZ}")
        try:
            write_entry(root, entry_id, entry_files(manifest, processor.process(recording)))
        except FileExistsError:
            continue
        return manifest
    raise RuntimeError("could not allocate an entry id")
