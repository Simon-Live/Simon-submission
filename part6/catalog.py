"""Catalog storage: one folder per entry under a root (docs/specs/shared-files.md section 4).

The importer (part6/importer.py) builds entries and writes them through `write_shared_entry`.
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

from .validate import FILE_RE, ID_RE, check_manifest, entry_folders, read_json

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_CATALOG = REPO_ROOT / "fixtures" / "output" / "catalog"
DEFAULT_ROOT = Path("~/.local/state/simon-part-6/catalog")
SLUG_MAX = 40
DEFAULT_MAX_RECORDINGS = 30    # visitor recordings kept; 0 = no cap, only when passed (AC-015)
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


def list_entries(root, q="", category=None, source=None):
    """Manifests sorted by name; q terms must all occur in the name (case-insensitive);
    `category` and `source` (a `files_source` value) keep only exact matches when given."""
    terms = q.casefold().split()
    entries = []
    for folder in entry_folders(root):
        manifest = read_manifest(root, folder.name)
        if manifest is None:
            continue
        name = manifest["name"].casefold()
        if (all(t in name for t in terms) and category in (None, manifest["category"])
                and source in (None, manifest["files_source"])):
            entries.append(manifest)
    return sorted(entries, key=lambda m: (m["name"].casefold(), m["name"], m["id"]))


def served_names(manifest):
    """The files an entry serves: those it names (a kind that is null is not served) and the
    thumbnail, plus `video_uri` when it is a plain file name."""
    names = {manifest.get(field) for field in ("keyframes", "skeleton", "animation", "thumbnail",
                                               "video_uri")}
    return {n for n in names if isinstance(n, str) and FILE_RE.match(n)}


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


def write_shared_entry(root, entry_id, manifest, files):
    """Write an entry made of `manifest` and `files` ({name: str or bytes}), atomically."""
    return write_entry(root, entry_id, {"manifest.json": json.dumps(manifest, indent=2) + "\n",
                                        **files})


def _copy_entry(source, root):
    """Copy one fixture folder into root, replacing any folder of that name."""
    entry_id = source.name
    tmp, final = Path(root) / f".tmp-{entry_id}", Path(root) / entry_id
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(source, tmp)
    if final.exists():
        shutil.rmtree(final)
    os.rename(tmp, final)


def holds_entry(root):
    """True when root has any non-dot folder or link with an id-shaped name (an entry of any
    kind, a broken link included); False for a missing or empty root."""
    try:
        names = [p for p in Path(root).iterdir() if is_valid_id(p.name)]
    except FileNotFoundError:
        return False
    return any(p.is_dir() or p.is_symlink() for p in names)


def seed(root, source=None):
    """Copy every fixture entry into a root that is missing or holds no entry; returns the count.

    A root that holds any entry (fixture, visitor entry, import) is never seeded
    (docs/specs/catalog-contract.md AC-C13a); `reset` is what brings the fixtures back."""
    guard_root(root)
    source = Path(source) if source else FIXTURE_CATALOG
    Path(root).mkdir(parents=True, exist_ok=True)
    if holds_entry(root):
        return 0
    folders = [p for p in entry_folders(source)
               if is_valid_id(p.name) and not os.path.lexists(Path(root) / p.name)]
    for folder in folders:
        _copy_entry(folder, root)
    if folders:
        log(f"seeded {len(folders)} entries into {root}: {', '.join(p.name for p in folders)}")
    return len(folders)


RESET_SOURCES = ("mock", "import", "processor")    # everything but the fixtures (AC-C12)


def _is_resettable(folder):
    try:
        return read_json(folder / "manifest.json").get("files_source") in RESET_SOURCES
    except (ValueError, AttributeError):
        return False


def reset(root, source=None):
    """Delete mock, import and processor entries and dot folders, recopy every fixture entry;
    returns {"removed", "restored"}."""
    guard_root(root)
    root, source = Path(root), Path(source) if source else FIXTURE_CATALOG
    root.mkdir(parents=True, exist_ok=True)
    dot = [p for p in root.iterdir() if p.is_dir() and p.name.startswith(".")]
    doomed = [p for p in dot + [p for p in entry_folders(root) if _is_resettable(p)]
              if not p.is_symlink()]
    for folder in doomed:
        shutil.rmtree(folder)
    folders = [p for p in entry_folders(source) if is_valid_id(p.name)]
    for folder in folders:
        _copy_entry(folder, root)
    return {"removed": len(doomed), "restored": len(folders)}


def remove_entry(root, entry_id):
    """Delete one entry folder. The id pattern is checked, a symlink is refused, and the folder
    is renamed to a dot folder (never listed) before it is deleted."""
    if not is_valid_id(entry_id):
        raise ValueError(f"invalid id: {entry_id!r}")
    folder = Path(root) / entry_id
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError(f"{entry_id} is not an entry folder")
    doomed = Path(root) / f".evict-{entry_id}"
    shutil.rmtree(doomed, ignore_errors=True)
    os.rename(folder, doomed)
    try:
        shutil.rmtree(doomed)
    except OSError as exc:
        log(f"left {doomed.name} behind: {exc}")    # unlisted; `reset` removes dot folders


def is_visitor(manifest):
    """True for an entry made over HTTP (`visitor` true) and for a Phase 1 recording (no
    `visitor` field, `files_source` mock). Fixtures and CLI imports never count (AC-C12)."""
    if manifest["files_source"] == "fixture":
        return False
    if "visitor" in manifest:
        return manifest["visitor"] is True
    return manifest["files_source"] == "mock"


def visitor_entries(root):
    """Manifests of the visitor entries (`is_visitor`), oldest first. A symlinked folder is not
    counted: remove_entry refuses it, so it would hold a cap slot forever."""
    visitors = [m for m in list_entries(root)
                if is_visitor(m) and not (Path(root) / m["id"]).is_symlink()]
    return sorted(visitors, key=lambda m: (m["created_at"], m["id"]))


def enforce_cap(root, cap, keep_id):
    """Remove the oldest visitor entries until at most `cap` remain; 0 means no cap.
    Fixtures and CLI imports are not counted, `keep_id` is never removed, and a failed removal is logged and
    skipped (the next oldest goes instead). Returns the removed ids."""
    removed = []
    if cap <= 0:
        return removed
    visitors = visitor_entries(root)
    excess = len(visitors) - cap
    for manifest in visitors:
        if excess <= 0:
            break
        if manifest["id"] == keep_id:
            continue
        try:
            remove_entry(root, manifest["id"])
        except (OSError, ValueError) as exc:
            log(f"could not evict {manifest['id']}: {exc}")
            continue
        log(f"evicted {manifest['id']} (cap {cap})")
        removed.append(manifest["id"])
        excess -= 1
    return removed


def slugify(name):
    """Lowercase ASCII letters and digits, other runs become -, at most 40 characters."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:SLUG_MAX].strip("-")
    return slug or "movement"


def new_id(name):
    return f"{slugify(name)}-{secrets.token_hex(4)}"


def utc_now():
    return datetime.now(timezone.utc)


def compact_json(data):
    """The stored form of a parsed shared file: compact JSON and a final newline. NaN and
    infinity are refused (ValueError), because a browser cannot parse them."""
    return json.dumps(data, separators=(",", ":"), allow_nan=False) + "\n"


def build_manifest(entry_id, name, category, duration_ms, files_source, description, created_at,
                   *, kinds=("keyframes", "skeleton", "animation"), video_uri=None,
                   provenance=None, visitor=None):
    """A manifest v1 (AC-C01). `kinds` are the shared files the entry holds, stored under their
    fixed names; the others are null. `provenance` and `visitor` are left out when None."""
    manifest = {"id": entry_id, "name": name, "video_uri": video_uri}
    for kind in ("keyframes", "skeleton", "animation"):
        manifest[kind] = f"{kind}.json" if kind in kinds else None
    manifest.update(created_at=created_at, schema_version=1, category=category,
                    description=description, thumbnail="thumbnail.svg", duration_ms=duration_ms,
                    files_source=files_source)
    if provenance is not None:
        manifest["provenance"] = provenance
    if visitor is not None:
        manifest["visitor"] = visitor
    return manifest
