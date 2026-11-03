"""The person skin's weights, computed once on the server and shipped in rest.json (docs/specs/person-skin.md AC-PS18).

The browser's person skin (web/skin/person-skin.js) used to weigh about 2500 vertices over up to 65 frames itself,
synchronously, on every load: 0.2 s on a desktop and seconds on a mid phone. The rule is `take_rig.motion_weights`
(AC-PS17), run here over exactly the frames and joints the rest document names: the rest frame with its 4-decimal
joints, then each `motion` entry. Vertices are read from mesh3d.bin as int16 times `unit_m`, in double precision, as
the browser's fallback (web/skin/motion-weights.js) reads them, so the two agree bit for bit (AC-PS18).

`weights(folder, header, rest_doc, stamp(folder))` answers `{schema, bones, bone, weight}` or None; results are kept per
folder and file stamp (taken before the files are read), and concurrent requests for one take compute it once.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from part7 import take_load, take_rig

SCHEMA = "simon.person-weights.v1"
DECIMALS = 6  # a shipped weight; the second weight of a vertex is 1 minus the first
CACHE_MAX = 16  # takes kept (about 100 KB each)
_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
_lock = threading.Lock()
_inflight: dict[tuple[Any, ...], threading.Lock] = {}  # key -> the lock of the request computing it


def frames_for(header: dict[str, Any], blob: bytes, rest_doc: dict[str, Any]) -> list[tuple[list[take_rig.Vec], dict[str, take_rig.Vec]]] | None:
    """(vertices, derived joints) for the rest frame, then each motion frame other than it; None when a frame is unreadable."""
    n = header.get("vertex_count")
    unit = float((header.get("vertices") or {}).get("unit_m", 0.0001))
    frames = header.get("frames") or []
    names = take_rig.COCO
    picks = [(rest_doc["index"], {k: tuple(v) for k, v in rest_doc["joints"].items()})]
    picks += [(m["index"], {nm: tuple(m["joints"][k]) for k, nm in enumerate(names)})
              for m in rest_doc.get("motion") or [] if m["index"] != rest_doc["index"]]
    out = []
    for index, joints in picks:
        people = frames[index].get("people") if 0 <= index < len(frames) else None
        verts = take_load._verts(blob, int(people[0]["offset"]), n, unit) if people and isinstance(n, int) else None
        if verts is None:
            return None
        out.append((verts, take_rig.derive(joints)))
    return out


def compute(header: dict[str, Any], blob: bytes, rest_doc: dict[str, Any]) -> dict[str, Any] | None:
    """The shipped weights for one person: bone indices in `bones` order, two per vertex, and the first weight of each."""
    frames = frames_for(header, blob, rest_doc)
    if not frames:
        return None
    bones, weights = take_rig.motion_weights(frames)
    return {"schema": SCHEMA, "bones": list(take_rig.NAMES), "bone": [b for pair in bones for b in pair],
            "weight": [round(w0, DECIMALS) for w0, _ in weights]}


def stamp(folder: Path) -> tuple[Any, ...] | None:
    """Size and time of the three files, taken BEFORE they are read, so a file replaced while it is read cannot file
    its weights under the new stamp; None when one is missing."""
    try:
        return tuple((n, st.st_mtime_ns, st.st_size) for n in ("mesh3d.json", "mesh3d.bin", "pose3d.json") for st in [(folder / n).stat()])
    except OSError:
        return None


def weights(folder: Path, header: dict[str, Any], rest_doc: dict[str, Any], taken: tuple[Any, ...] | None) -> dict[str, Any] | None:
    """The weights of the person in `folder` whose files had stamp `taken` before `header` and `rest_doc` were read: from
    the cache when present, else computed once however many requests ask at the same moment (the others wait for it).
    None when the stamp is missing or the bin is missing, a symlink, too large or does not hold the frames."""
    if taken is None:
        return None
    key = (str(folder), taken)
    with _lock:
        if key in _cache:
            return _cache[key]
        gate = _inflight.setdefault(key, threading.Lock())
    try:
        with gate:
            with _lock:
                if key in _cache:  # computed by the request this one waited for
                    return _cache[key]
            doc = _compute_file(folder, header, rest_doc)
            if doc is not None:
                with _lock:
                    while len(_cache) >= CACHE_MAX:
                        _cache.pop(next(iter(_cache)))
                    _cache[key] = doc
            return doc
    finally:
        with _lock:
            if _inflight.get(key) is gate:
                del _inflight[key]


def _compute_file(folder: Path, header: dict[str, Any], rest_doc: dict[str, Any]) -> dict[str, Any] | None:
    bin_path = folder / "mesh3d.bin"
    try:
        if bin_path.is_symlink() or bin_path.stat().st_size > take_load.MAX_BIN_BYTES:
            return None
        return compute(header, bin_path.read_bytes(), rest_doc)
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None
