"""Keyframes input for the part4 view (spec integration-contract.md "Keyframes input", TICKET-025).

Three sources become one timeline on Part 4's 30 fps clock: Part 1's `keyframes.json` (key times in ms on
the video clock), Part 4's `simon.keyframes.v1` (ticks as given) and `every:<n>` (a key every n ticks).
"""

import dataclasses
import math
import os
import pathlib
import re

from part3 import io
from part3.resample import cap_for, shown
from part3.schema import ContractError, FrameCapError, describe, is_finite, is_int

FPS = 30
EVERY_PREFIX = "every:"
EVERY_MIN, EVERY_MAX = 1, 300
PART4_FORMAT = "simon.keyframes.v1"
DENSIFY_ENV = "PART3_KEYFRAMES_DENSIFY"
DENSIFY_OFF = "off"
_EVERY = re.compile(r"every:([0-9]+)")
_EPS = 1e-9  # keeps a last frame that lands exactly on a tick from rounding down to the tick before


@dataclasses.dataclass
class Timeline:
    """The key ticks of a clip: `keys` is [(index, name)] strictly increasing in index.

    `dropped` lists every source key that was not used: {name, t_ms, reason}. `source_kind` is
    "part1", "part4" or "every"; `person` is the Part 1 person id used (else None); `t0_ms` is the
    clock value of tick 0.
    """
    fps: int
    frame_count: int
    duration_s: float
    keys: list
    dropped: list
    source_kind: str
    person: object
    t0_ms: float = 0.0
    densify: object = None  # {"every", "selected_by", "added"} once `densify` ran, else None


def frame_count(t0_ms, t_last_ms, max_frames=None):
    """Ticks in the clip: floor((t_last - t0) * 30 / 1000 + 1e-9) + 1 (at least 1).

    Raises FrameCapError when the clip would have more than `max_frames` ticks (None: `resample.MAX_FRAMES`)
    or its span is not finite: the timeline is built tick by tick, so its length must be bounded (review B1).
    """
    cap = cap_for(max_frames)
    scaled = max(float(t_last_ms) - float(t0_ms), 0.0) * FPS / 1000.0 + _EPS
    if not math.isfinite(scaled):
        raise FrameCapError("--keyframes", f"the {FPS} fps timeline would have more ticks than the limit of "
                                           f"{cap}: the clip span (first to last t_ms) is not finite", timeline=True)
    count = math.floor(scaled) + 1
    if count > cap:
        raise FrameCapError("--keyframes", f"the {FPS} fps timeline would have {shown(count)} ticks; "
                                           f"the limit is {cap}", timeline=True)
    return count


def tick_time_ms(t0_ms, index):
    """Clock value in ms of tick `index`."""
    return float(t0_ms) + index * 1000.0 / FPS


def _ms(value):
    """A millisecond count for a message: up to 3 decimals, no trailing zeros."""
    return f"{value:.3f}".rstrip("0").rstrip(".")


# --- reading -----------------------------------------------------------------------------------

def read(source):
    """A keyframes document `load` accepts: a parsed dict as is, `every:<n>` checked, or a file parsed.

    Raises ContractError naming the file or the option for an unreadable file, invalid JSON or a bad `n`.
    """
    if isinstance(source, dict):
        return source
    if is_every(source):
        every_n(source)
        return source
    if isinstance(source, (str, pathlib.Path)):
        return _read_file(source)
    raise ContractError("keyframes", "expected a file path, every:<n> or a parsed keyframes object")


def is_every(source):
    return isinstance(source, str) and source.startswith(EVERY_PREFIX)


def _read_file(path):
    try:
        doc, _ = io.read_json(path)
    except OSError as error:
        raise ContractError(str(path), f"cannot read ({error.strerror or error})") from error
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise ContractError(str(path), f"not valid JSON ({error})") from error
    return doc


def every_n(spec):
    """The integer n of an `every:<n>` spec; ContractError unless it is a whole number from 1 to 300."""
    match = _EVERY.fullmatch(spec)
    if match is None or not EVERY_MIN <= int(match.group(1)) <= EVERY_MAX:
        raise ContractError(f"--keyframes {spec}", f"n must be a whole number from {EVERY_MIN} to {EVERY_MAX}")
    return int(match.group(1))


def _n_of(spec, label, prefix=""):
    """The n of an `every:<n>` text, else ContractError(label, prefix + message)."""
    match = _EVERY.fullmatch(spec) if isinstance(spec, str) else None
    if match is None or not EVERY_MIN <= int(match.group(1)) <= EVERY_MAX:
        raise ContractError(label, f"{prefix}n must be a whole number from {EVERY_MIN} to {EVERY_MAX}")
    return int(match.group(1))


# --- densifying (spec journey-followup.md "Densify rule", TICKET-036) --------------------------

def _parse_densify(value, label, prefix=""):
    """n for `every:<n>`, DENSIFY_OFF for `off`; ContractError(label, prefix + message) otherwise."""
    if value == DENSIFY_OFF:
        return DENSIFY_OFF
    if isinstance(value, str) and value.startswith(EVERY_PREFIX):
        return _n_of(value, label, prefix)
    raise ContractError(label, f"{prefix}expected {EVERY_PREFIX}<n> or {DENSIFY_OFF}")


def resolve_densify(flag=None, api=None, env=None, config=None):
    """(n, selected_by) of the densify setting, first set wins: flag, environment, config file, API, default.

    `flag` and `api` are `every:<n>` or `off` (API: also a whole number n); `env` None means `os.environ`;
    `config` is a `part3.config.Config` or None. `off` on a channel stops the lookup: (None, None).
    Raises ContractError naming the channel for a bad value.
    """
    env = os.environ if env is None else env
    text = env.get(DENSIFY_ENV) or None
    cfg_value = getattr(config, "densify", None)
    label = getattr(config, "label", "")
    for value, kind, name, prefix in (
            (flag, "flag", f"--keyframes-densify {flag}", ""), (text, "env", DENSIFY_ENV, ""),
            (cfg_value, "config", label, "keyframes.densify: "), (api, "api", "keyframes_densify=", "")):
        if value is None:
            continue
        n = _parse_densify(value, name, prefix)
        return (None, None) if n == DENSIFY_OFF else (n, kind)
    return None, None


def densify(timeline, n, selected_by):
    """A new Timeline: the named keys kept and a filler `key_<index>` every `n` ticks between the anchors.

    Anchors are tick 0, the surviving named keys and the last tick; fillers restart at each anchor and stay
    strictly below the next one. `timeline.densify` records n, the channel and the fillers written.
    """
    named = dict(timeline.keys)
    anchors = sorted({0, timeline.frame_count - 1, *named})
    ticks = set(anchors)
    for low, high in zip(anchors, anchors[1:]):
        ticks.update(range(low + n, high, n))
    keys = [(index, named.get(index, f"key_{index}")) for index in sorted(ticks)]
    return dataclasses.replace(timeline, keys=keys, dropped=[dict(d) for d in timeline.dropped],
                               densify={"every": n, "selected_by": selected_by, "added": len(keys) - len(named)})


# --- loading -----------------------------------------------------------------------------------

def load(source, t0_ms, t_last_ms, person=None, label=None, max_frames=None):
    """The Timeline of `source` (path, `every:<n>`, or a parsed Part 1 / Part 4 dict) for a clip.

    `t0_ms` and `t_last_ms` are the clock values of the first and last input frame. `person` picks the
    Part 1 person (an id as int or str; the first listed when None). `label` names the source in
    messages (the path when `source` is one). `max_frames` caps the ticks (None: `resample.MAX_FRAMES`).
    Raises ContractError when the source cannot be read, is neither a Part 1 nor a Part 4 file, names a
    person it lacks, has an entry of `people` that is not an object, leaves no key inside the clip or
    spans more ticks than the cap.
    """
    label = label or (str(source) if isinstance(source, (str, pathlib.Path)) else "keyframes")
    doc = read(source)
    count = frame_count(t0_ms, t_last_ms, max_frames)
    base = dict(fps=FPS, frame_count=count, duration_s=round((count - 1) / FPS, 6), t0_ms=float(t0_ms))
    if is_every(source):
        return Timeline(keys=_every_keys(every_n(source), count), dropped=[], source_kind="every",
                        person=None, **base)
    kind = _kind(doc, label)
    if kind == "part1":
        chosen, items = _part1_items(doc, person, label, t0_ms)
    else:
        chosen, items = None, _part4_items(doc, label, t0_ms)
    keys, dropped = _assign(items, count, t0_ms)
    if not keys:
        raise ContractError(label, f"no keyframe falls inside the clip ({_ms(t0_ms)} to {_ms(t_last_ms)} ms)")
    return Timeline(keys=keys, dropped=dropped, source_kind=kind, person=chosen, **base)


def _kind(doc, label):
    if isinstance(doc, dict):
        if isinstance(doc.get("people"), list):
            return "part1"
        if doc.get("format") == PART4_FORMAT or isinstance(doc.get("keyframes"), list):
            return "part4"
    raise ContractError(label, "not a Part 1 or Part 4 keyframes file")


def _every_keys(n, count):
    ticks = list(range(0, count, n))
    if ticks[-1] != count - 1:
        ticks.append(count - 1)
    return [(index, f"key_{index}") for index in ticks]


def _assign(items, count, t0_ms):
    """Keys as (index, name) and dropped entries from `items` [(index, name, t_ms)] in time order."""
    taken, dropped = {}, []
    for index, name, t_ms in items:
        reason = None
        if index < 0:
            reason = f"before the clip start (tick 0 is {_ms(t0_ms)} ms)"
        elif index > count - 1:
            reason = f"after the clip end (last tick {count - 1} is {_ms(tick_time_ms(t0_ms, count - 1))} ms)"
        elif index in taken:
            reason = f"tick {index} already holds the key {taken[index]!r}"
        if reason:
            dropped.append({"name": name, "t_ms": round(t_ms, 3), "reason": reason})
        else:
            taken[index] = name
    return sorted(taken.items()), dropped


# --- Part 1 ------------------------------------------------------------------------------------

def _part1_items(doc, person, label, t0_ms):
    """(chosen person id, [(index, name, t_ms)] of every repetition's keys in time order)."""
    people = doc["people"]
    _check_people(people, label)
    if not people:
        return None, []
    p = _pick_person(people, person, label)
    chosen = people[p]
    items = []
    for r, rep in enumerate(_list(chosen.get("repetitions"))):
        for k, key in enumerate(_list(rep.get("keyframes") if isinstance(rep, dict) else None)):
            path = f"{label}.people[{p}].repetitions[{r}].keyframes[{k}]"
            items.append((_key_time(key, doc.get("fps"), path), _name(key)))
    items.sort(key=lambda item: item[0])
    return chosen.get("id"), [(_tick(t_ms, t0_ms), name, t_ms) for t_ms, name in items]


def _check_people(people, label):
    """ContractError naming `people[k]` for the first entry that is not an object (never read as 'no keys')."""
    for k, entry in enumerate(people):
        if not isinstance(entry, dict):
            raise ContractError(f"{label}.people[{k}]", f"expected an object (got {describe(entry)})")


def _list(value):
    return value if isinstance(value, list) else []


def _pick_person(people, person, label):
    """Position in `people` of the requested id (as int or str), else of the first listed."""
    if person is None:
        return 0
    for k, entry in enumerate(people):
        if str(entry.get("id")) == str(person):
            return k
    ids = ", ".join(str(e.get("id")) for e in people[:20])
    raise ContractError(f"--keyframes-person {person}", f"not in {label} (ids: {ids})")


def _key_time(key, fps, path):
    """A Part 1 key's time in ms: its `t_ms`, else `frame` over the file's `fps`."""
    if isinstance(key, dict):
        t_ms = key.get("t_ms")
        if is_finite(t_ms):
            return float(t_ms)
        if is_finite(key.get("frame")) and is_finite(fps) and fps > 0:
            return key["frame"] * 1000.0 / fps
    raise ContractError(f"{path}.t_ms", "missing (expected a number of milliseconds on the video clock)")


def _name(key):
    name = key.get("name") if isinstance(key, dict) else None
    return name if isinstance(name, str) and name else "key"


def _tick(t_ms, t0_ms):
    """The 30 fps tick of a clock time: (t - t0) * 30 / 1000 rounded half up."""
    return math.floor((t_ms - t0_ms) * FPS / 1000.0 + 0.5)


# --- Part 4 ------------------------------------------------------------------------------------

def _part4_items(doc, label, t0_ms):
    """[(index, name, t_ms)] in file order; the file's `fps` must be 30 and each `index` a whole number."""
    if doc.get("fps") != FPS or isinstance(doc.get("fps"), bool):
        raise ContractError(f"{label}.fps", f"must be {FPS} (got {doc.get('fps')!r})")
    keys = doc.get("keyframes")
    if not isinstance(keys, list):
        raise ContractError(f"{label}.keyframes", "expected a list")
    items = []
    for k, key in enumerate(keys):
        index = key.get("index") if isinstance(key, dict) else None
        if not is_int(index):
            raise ContractError(f"{label}.keyframes[{k}].index", "expected a whole number")
        items.append((index, _name(key), tick_time_ms(t0_ms, index)))
    return items
