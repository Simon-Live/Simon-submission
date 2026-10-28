"""Format adapters for keyframes, skeleton and animation files (docs/specs/formats.md).

Parts 1, 3 and 4 write these three files in more than one shape. One small reader per file kind
turns any known shape into one normalized form; the catalog, the doctor and the thumbnail only ever
see that form. Detection is by version field first, then by shape. A file no reader accepts raises
`FormatError` whose message names the file and the field in plain words, identical to the one
`web/formats.js` raises (both are held to `fixtures/conformance/formats/cases.json`).

Everything here is pure: no I/O, no clock, no randomness, inputs are never changed. A frame index
is always `floor(x + 0.5)`, never `round()`, so the Python and JavaScript readers agree.
"""
from __future__ import annotations

import math

KINDS = ("keyframes", "skeleton", "animation")
FORMATS = {"animation": ("simon.animation/1", "simon.animation.v1"),
           "skeleton": ("simon.skeleton/1", "simon.skeleton.v1"),
           "keyframes": ("simon.keyframes/part1", "simon.keyframes.v1")}
PRODUCER = {"simon.animation/1": 6, "simon.animation.v1": 4, "simon.skeleton/1": 3,
            "simon.skeleton.v1": 4, "simon.keyframes/part1": 1, "simon.keyframes.v1": 4}
PLAY_FPS = 30
MAX_TIME_S = 7200  # two hours: no time a reader derives may be above this (E16)
JOINTS = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
    "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle",
)

PRODUCER_VALUES = {f"part{n}": n for n in range(1, 8)}


def declared_producer(data):
    """The part a file names in its own top-level `producer` ("part1" to "part7"; Part 3 writes
    "part3" in its views and keyframes), else None. A declared producer is read, never guessed
    (docs/specs/catalog-contract.md AC-C05, AC-C06)."""
    value = data.get("producer") if isinstance(data, dict) else None
    return PRODUCER_VALUES.get(value) if isinstance(value, str) else None


A1, AV1 = FORMATS["animation"]
S1, SV1 = FORMATS["skeleton"]
K1, KV1 = FORMATS["keyframes"]
_ID_KIND = {fid: kind for kind, ids in FORMATS.items() for fid in ids}
_NAME_KINDS = (("keyframe", "keyframes"), ("skeleton", "skeleton"), ("animation", "animation"))
_SHOWN_MAX = 60  # an E2 value longer than this is cut to its first 57 characters plus "..."
_EPS = 1e-6  # absorbs Part 3's three-decimal t_ms rounding (AC-F07)
_DEFAULT_FILE = {kind: f"{kind}.json" for kind in KINDS}


class FormatError(ValueError):
    """A file no reader accepts. `str(error)` is the plain-words message; `code` is its id (E1..E16)."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def _num(v):
    """A finite JSON number (booleans are not numbers)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        return math.isfinite(v)
    except OverflowError:
        return False


def _as_float(v):
    """float(v), with an integer too large for a float read as infinity, as JavaScript reads it."""
    try:
        return float(v)
    except OverflowError:
        return math.inf if v > 0 else -math.inf


def _frame_index(t, fps):
    """floor(t * fps + 0.5); a product that is not finite is passed through, never an OverflowError."""
    x = _as_float(t) * _as_float(fps) + 0.5
    return math.floor(x) if math.isfinite(x) else x


def mark_frame(t, fps):
    """The frame of a mark at `t` seconds on a clock of `fps`: floor(t * fps + 0.5)."""
    return _frame_index(t, fps)


# ---- detection ---------------------------------------------------------------------------------

def _by_version(kind, data, file):
    """The known id named by `format`, else by `schema`, or None (AC-F02).

    A string field decides: a known id of this kind is used, another kind's id is E3, anything
    else is E2 even when the other field is known. An unknown version is never read by a guess.
    """
    for field in ("format", "schema"):
        v = data.get(field)
        if not isinstance(v, str):
            continue
        other = _ID_KIND.get(v)
        if other is None:
            ids = ", ".join(FORMATS[kind])
            shown = v if len(v) <= _SHOWN_MAX else v[:_SHOWN_MAX - 3] + "..."
            raise FormatError(
                f'{file}: {field} "{shown}" is not a version Part 6 reads (it reads {ids})', "E2")
        if other != kind:
            raise FormatError(f"{file}: holds {v}, which belongs in {other}.json, not {kind}.json", "E3")
        return v
    return None


def _out_of_range(file, where):
    return FormatError(f"{file}: {where}: time must be from 0 to two hours", "E16")


def _in_limit(t, file, where):
    """`t` seconds, or E16 unless it is from 0 to two hours (this bounds a held skeleton's frames)."""
    if not 0 <= t <= MAX_TIME_S:
        raise _out_of_range(file, where)
    return t


def _start(kind, data, file):
    """Common start of every reader: the file name, E1, then the version field."""
    file = file or _DEFAULT_FILE[kind]
    if not isinstance(data, dict):
        raise FormatError(f"{file}: is not a JSON object", "E1")
    return file, _by_version(kind, data, file)


def _no_reader(kind, file):
    return FormatError(
        f"{file}: has no format or schema field and its shape matches no {kind} reader", "E4")


def _is_key_list(v):
    """A `keyframes` list whose items carry `joints` (skeleton key poses)."""
    return isinstance(v, list) and bool(v) and isinstance(v[0], dict) and "joints" in v[0]


def detect_kind(data, file_name):
    """The kind of an imported file: version id, then file name, then shape (AC-F03)."""
    name = file_name if isinstance(file_name, str) and file_name else "file"
    if not isinstance(data, dict):
        raise FormatError(f"{name}: is not a JSON object", "E1")
    for field in ("format", "schema"):
        v = data.get(field)
        if isinstance(v, str) and v in _ID_KIND:
            return _ID_KIND[v]
    low = name.lower()
    for needle, kind in _NAME_KINDS:
        if needle in low:
            return kind
    if "frames" in data:
        return "animation" if "fps" in data else "skeleton"
    if _is_key_list(data.get("keyframes")):
        return "skeleton"
    if "people" in data or "keyframes" in data:
        return "keyframes"
    raise FormatError(f"{name}: has no format or schema field and its shape matches no reader", "E4")


# ---- joints and persons --------------------------------------------------------------------------

def _vec(v):
    """[x, y, z] from `{x, y, z, ...}` or `[x, y, z, ...]`, else None."""
    if isinstance(v, (list, tuple)):
        parts = v[:3] if len(v) >= 3 else None
    elif isinstance(v, dict):
        parts = (v.get("x"), v.get("y"), v.get("z"))
    else:
        parts = None
    if parts is None or not all(_num(p) for p in parts):
        return None
    return [float(p) for p in parts]


def _joints(src, file, where):
    """The 17 joints of `src` as {name: [x, y, z]}; E7 for a missing one, E8 for a bad one."""
    if not isinstance(src, dict):
        src = {}
    out = {}
    for name in JOINTS:
        if name not in src:
            raise FormatError(f"{file}: {where}.joints.{name}: missing", "E7")
        vec = _vec(src[name])
        if vec is None:
            raise FormatError(f"{file}: {where}.joints.{name}: needs three finite numbers", "E8")
        out[name] = vec
    return out


def _pick_person(people):
    """Index of the person with id 0, else 0; None when the list is empty or not a list."""
    if not isinstance(people, list) or not people:
        return None
    for i, p in enumerate(people):
        if isinstance(p, dict) and _num(p.get("id")) and p["id"] == 0:
            return i
    return 0


def _person_joints(people, p, file, where):
    person = people[p] if isinstance(people[p], dict) else {}
    return _joints(person.get("joints"), file, f"{where}.people[{p}]")


def _obj(v):
    return v if isinstance(v, dict) else {}


# ---- animation -----------------------------------------------------------------------------------

def _animation_shape(data, file):
    frames = data.get("frames")
    if "fps" in data and isinstance(frames, list) and frames and isinstance(frames[0], dict):
        if "people" in frames[0]:
            return A1
        if "joints" in frames[0]:
            return AV1
    raise _no_reader("animation", file)


def _a1_frame(fr, i, fps, file):
    where = f"frames[{i}]"
    t = _in_limit(fr["t_ms"] / 1000 if _num(fr.get("t_ms")) else i / fps, file, where)
    p = _pick_person(fr.get("people"))
    if p is None:
        raise FormatError(f"{file}: {where}: has no person", "E9")
    return t, _person_joints(fr["people"], p, file, where)


def _v1_frame(fr, i, fps, file):
    if _num(fr.get("t")):
        t = fr["t"]
    elif _num(fr.get("index")):
        t = fr["index"] / fps
    else:
        t = i / fps
    where = f"frames[{i}]"
    return _in_limit(t, file, where), _joints(fr.get("joints"), file, where)


def read_animation(data, file="animation.json"):
    """Normalized animation: {kind, format, detected_by, source_kind, fps, frames, held}."""
    file, fid = _start("animation", data, file)
    by = "version"
    if fid is None:
        fid, by = _animation_shape(data, file), "shape"
    fps = data.get("fps")
    if not _num(fps) or fps <= 0:
        raise FormatError(f"{file}: fps: must be a number above 0", "E5")
    frames = data.get("frames")
    if not isinstance(frames, list) or not frames:
        raise FormatError(f"{file}: frames: must be a non-empty list", "E6")
    read_frame = _a1_frame if fid == A1 else _v1_frame
    out, prev = [], None
    for i, fr in enumerate(frames):
        fr = _obj(fr)
        t, joints = read_frame(fr, i, fps, file)
        if prev is not None and not t > prev:
            raise FormatError(f"{file}: frames[{i}]: time must be later than the frame before", "E10")
        out.append({"t": t, "interpolated": fr.get("interpolated") is True, "joints": joints})
        prev = t
    return {"kind": "animation", "format": fid, "detected_by": by, "source_kind": "animation",
            "fps": float(fps), "frames": out, "held": False}


# ---- skeleton ------------------------------------------------------------------------------------

def _key_block(data):
    """(path prefix, key list) of the skeleton key poses, or None.

    A top-level `keyframes` list whose items carry `joints`, else the first top-level object field
    in sorted key order (plain string sort, so both readers agree) whose `format` is
    simon.skeleton.v1 and which holds such a list (Part 3 `--view part4`).
    """
    if _is_key_list(data.get("keyframes")):
        return "keyframes", data["keyframes"]
    for field in sorted(data):
        val = data[field]
        if isinstance(val, dict) and val.get("format") == SV1 and _is_key_list(val.get("keyframes")):
            return f"{field}.keyframes", val["keyframes"]
    return None


def _skeleton_shape(data, file):
    frames = data.get("frames")
    if ("fps" not in data and isinstance(frames, list) and frames
            and isinstance(frames[0], dict) and "people" in frames[0]):
        return S1
    if _is_key_list(data.get("keyframes")):
        return SV1
    raise _no_reader("skeleton", file)


def _skeleton_frames(data, file):
    frames = data.get("frames")
    if not isinstance(frames, list) or not frames:
        return None
    out = []
    for i, fr in enumerate(frames):
        fr = _obj(fr)
        if _num(fr.get("t_ms")):
            t = fr["t_ms"] / 1000
        elif _num(fr.get("t")):
            t = fr["t"]
        else:
            raise FormatError(f"{file}: frames[{i}]: needs t_ms or t", "E11")
        _in_limit(t, file, f"frames[{i}]")
        p = _pick_person(fr.get("people"))
        joints = None if p is None else _person_joints(fr["people"], p, file, f"frames[{i}]")
        out.append({"t": t, "joints": joints})
    return out


def _skeleton_keys(block, file):
    if block is None:
        return None
    prefix, items = block
    out = []
    for i, item in enumerate(items):
        item, where = _obj(item), f"{prefix}[{i}]"
        if _num(item.get("t")):
            t = item["t"]
        elif _num(item.get("index")):
            t = item["index"] / PLAY_FPS
        else:
            raise FormatError(f"{file}: {where}: needs t or index", "E11")
        _in_limit(t, file, where)
        name = item.get("name") if "name" in item else ""
        if not isinstance(name, str):
            raise FormatError(f"{file}: {where}.name: must be a string", "E15")
        out.append({"t": t, "name": name, "joints": _joints(item.get("joints"), file, where)})
    return out


def read_skeleton(data, file="skeleton.json"):
    """Normalized skeleton: {kind, format, detected_by, frames, keys}."""
    file, fid = _start("skeleton", data, file)
    by = "version"
    if fid is None:
        fid, by = _skeleton_shape(data, file), "shape"
    frames = _skeleton_frames(data, file)
    keys = _skeleton_keys(_key_block(data), file)
    if not any(f["joints"] is not None for f in frames or ()) and not keys:
        raise FormatError(f"{file}: no frame has a person and there are no key poses", "E9s")
    return {"kind": "skeleton", "format": fid, "detected_by": by, "frames": frames, "keys": keys}


def animation_from_skeleton(skeleton):
    """A skeleton played as its own animation: 30 fps, each pose held, never blended (AC-F07)."""
    frames = skeleton.get("frames") or []
    samples = [f for f in frames if f["joints"] is not None] or list(skeleton.get("keys") or [])
    if not samples:
        raise FormatError("skeleton.json: no frame has a person and there are no key poses", "E9s")
    samples = sorted(samples, key=lambda s: s["t"])
    count = max(1, _frame_index(samples[-1]["t"], PLAY_FPS) + 1)
    exact = {_frame_index(s["t"], PLAY_FPS) for s in samples}
    out, j = [], 0
    for k in range(count):
        limit = k / PLAY_FPS + _EPS
        while j + 1 < len(samples) and samples[j + 1]["t"] <= limit:
            j += 1
        out.append({"t": k / PLAY_FPS, "interpolated": k not in exact, "joints": samples[j]["joints"]})
    return {"kind": "animation", "format": skeleton["format"], "detected_by": skeleton["detected_by"],
            "source_kind": "skeleton", "fps": PLAY_FPS, "frames": out, "held": True}


def playable(animation=None, skeleton=None):
    """The animation when there is one, else the skeleton played as an animation (E12 for neither)."""
    if animation is not None:
        return animation
    if skeleton is not None:
        return animation_from_skeleton(skeleton)
    raise FormatError("nothing to play: add an animation.json or a skeleton.json", "E12")


# ---- keyframes -----------------------------------------------------------------------------------

def _keyframes_shape(data, file):
    if isinstance(data.get("people"), list):
        return K1
    if isinstance(data.get("keyframes"), list) and not _is_key_list(data["keyframes"]):
        return KV1
    raise _no_reader("keyframes", file)


def _clock_fps(data, file):
    """`fps` as a float, None when the file has none; E5 when it is there and not above 0."""
    fps = data.get("fps")
    if fps is None:
        return None
    if not _num(fps) or fps <= 0:
        raise FormatError(f"{file}: fps: must be a number above 0", "E5")
    return float(fps)


def _mark_name(item, file, where):
    name = item.get("name")
    if not isinstance(name, str):
        raise FormatError(f"{file}: {where}.name: must be a string", "E15")
    return name


def _part1_time(item, fps, file, where):
    tms, frame = item.get("t_ms"), item.get("frame")
    if _num(tms) and tms >= 0:
        return _in_limit(tms / 1000, file, where)
    if fps is not None and _num(frame):
        return _in_limit(frame / fps, file, where)
    if _num(tms):  # a negative t_ms with no frame clock to fall back on
        raise _out_of_range(file, where)
    raise FormatError(f"{file}: {where}: needs t_ms, or frame with fps", "E14")


def _part1_marks(data, fps, file):
    people = data.get("people")
    if not isinstance(people, list):
        raise FormatError(f"{file}: people: must be a list", "E13")
    p = _pick_person(people)
    if p is None:
        return []
    person, base = _obj(people[p]), f"people[{p}]"
    reps = person.get("repetitions")
    if not isinstance(reps, list):
        raise FormatError(f"{file}: {base}.repetitions: must be a list", "E13")
    pid = person["id"] if _num(person.get("id")) else p
    marks = []
    for r, rep in enumerate(reps):
        rep, rbase = _obj(rep), f"{base}.repetitions[{r}]"
        items = rep.get("keyframes")
        if not isinstance(items, list):
            raise FormatError(f"{file}: {rbase}.keyframes: must be a list", "E13")
        number = rep["rep"] if _num(rep.get("rep")) else r + 1
        for k, item in enumerate(items):
            item, where = _obj(item), f"{rbase}.keyframes[{k}]"
            name = _mark_name(item, file, where)
            marks.append({"name": name, "t": _part1_time(item, fps, file, where),
                          "rep": number, "person": pid})
    return marks


def _v1_time(item, fps, file, where):
    t, index = item.get("t"), item.get("index")
    if _num(t):
        return _in_limit(t, file, where)
    if fps is not None and _num(index):
        return _in_limit(index / fps, file, where)
    raise FormatError(f"{file}: {where}: needs t, or index with fps", "E14")


def _v1_marks(data, fps, file):
    items = data.get("keyframes")
    if not isinstance(items, list):
        raise FormatError(f"{file}: keyframes: must be a list", "E13")
    marks = []
    for k, item in enumerate(items):
        item, where = _obj(item), f"keyframes[{k}]"
        name = _mark_name(item, file, where)
        marks.append({"name": name, "t": _v1_time(item, fps, file, where), "rep": None, "person": None})
    return marks


def read_keyframes(data, file="keyframes.json"):
    """Normalized key frames: {kind, format, detected_by, clock_fps, marks}, marks sorted by t."""
    file, fid = _start("keyframes", data, file)
    by = "version"
    if fid is None:
        fid, by = _keyframes_shape(data, file), "shape"
    fps = _clock_fps(data, file)
    marks = (_part1_marks if fid == K1 else _v1_marks)(data, fps, file)
    marks.sort(key=lambda m: m["t"])
    return {"kind": "keyframes", "format": fid, "detected_by": by, "clock_fps": fps, "marks": marks}


# ---- dispatch and summary --------------------------------------------------------------------

_READERS = {"keyframes": read_keyframes, "skeleton": read_skeleton, "animation": read_animation}


def read(kind, data, file=None):
    """The reader of `kind` applied to `data`; `file` defaults to `<kind>.json`."""
    if kind not in _READERS:
        raise FormatError(f"{kind}: is not a file kind Part 6 reads (it reads {', '.join(KINDS)})")
    return _READERS[kind](data, file or _DEFAULT_FILE[kind])


def _summary_animation(n):
    frames = n["frames"]
    return {"kind": "animation", "format": n["format"], "detected_by": n["detected_by"],
            "source_kind": n["source_kind"], "fps": n["fps"], "frame_count": len(frames),
            "duration_s": frames[-1]["t"],
            "interpolated_count": sum(1 for f in frames if f["interpolated"]),
            "held": n["held"], "nose_first": list(frames[0]["joints"]["nose"]),
            "left_ankle_mid": list(frames[len(frames) // 2]["joints"]["left_ankle"]),
            "right_wrist_last": list(frames[-1]["joints"]["right_wrist"])}


def _summary_skeleton(n):
    frames, keys = n["frames"] or [], n["keys"] or []
    return {"kind": "skeleton", "format": n["format"], "detected_by": n["detected_by"],
            "frame_count": len(frames), "present_count": sum(1 for f in frames if f["joints"] is not None),
            "key_count": len(keys), "key_names": [k["name"] for k in keys]}


def _summary_keyframes(n):
    marks = n["marks"]
    return {"kind": "keyframes", "format": n["format"], "detected_by": n["detected_by"],
            "clock_fps": n["clock_fps"], "mark_count": len(marks),
            "marks": [[m["name"], m["t"]] for m in marks],
            "frames_at_30": [mark_frame(m["t"], PLAY_FPS) for m in marks]}


def summary(normalized):
    """The comparable digest of a normalized result (AC-F10); one definition for both runners."""
    kind = normalized["kind"]
    if kind == "animation":
        return _summary_animation(normalized)
    if kind == "skeleton":
        return _summary_skeleton(normalized)
    return _summary_keyframes(normalized)
