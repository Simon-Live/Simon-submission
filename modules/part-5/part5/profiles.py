"""Analysis profiles: how picky a take is judged (docs/specs/profiles.md, ADR-0016).

    load(path) -> the validated part5/profiles.json        (ProfileError names the file and the field)
    names(), default(), require(name)                      the profile names, in file order
    kind_of(measure) -> "range" | "position"               the tolerance group of a measure
    effective_rules(rules, name) -> rules'                 the rules a profile detects with
    tempo_of(rules), tempo_points(ratio, weight, cap)      the profile's tempo block and its dance charge
    file_sha256(path)                                      information for `make check-5`

A profile is tolerances per cue kind (optionally per measure) and a tempo block. Every number only loosens
(a multiplier is at least 1, an addition at least 0), `fitness` is the identity and is never changed, and the
values are set by hand: nothing here was tuned on a seed. Nothing in this module reads another Part.
"""
# ADR-0016: profiles live in their own file, so rules.json and both freeze hashes never change.
import copy
import hashlib
import json
import math
import re
from pathlib import Path

from . import cues
from .detect import generic
from .persistence import DEFAULT_MIN_RUN_FRAMES
from .measures import FOOT_MEASURES

PROFILES_PATH = Path(__file__).with_name("profiles.json")
VERSION = "simon.profiles.v1"
IDENTITY = "fitness"
KINDS = ("range", "position")
TEMPO_CUE_KEYS = ("speed_up", "slow_down")
# The foot measures (ADR-0015) by their side-less names, the ones `rules["measures"]` and `cues.CUES` use.
FOOT_GENERIC = tuple(dict.fromkeys(generic(name)[0] for name in FOOT_MEASURES))
NAME = re.compile(r"[a-z][a-z0-9_]*")
DASHES = re.compile(f"[{chr(0x2013)}{chr(0x2014)}]| - ")   # an en dash, an em dash or a spaced hyphen, as in the cue tests
IDENTITY_TOLERANCE = {"threshold_multiplier": 1.0, "min_fraction_multiplier": 1.0, "min_run_frames_add": 0}
IDENTITY_TEMPO = {"cues": {}, "weight": 0.0, "cap": 0.0}


class ProfileError(ValueError):
    """A profiles file that breaks the rules, an unknown profile, or rules a profile cannot be applied to."""


def _fail(where, field, message):
    raise ProfileError(f"{where}: {field}: {message}")


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


# --- reading and validating the file ---
def load(path=PROFILES_PATH):
    """The validated profiles document, or a `ProfileError` naming the file and the field that broke."""
    path = Path(path)
    try:
        doc = json.loads(path.read_text())
    except OSError as e:
        raise ProfileError(f"{path.name}: cannot be read ({e.strerror or e})") from e
    except ValueError as e:
        raise ProfileError(f"{path.name}: not JSON ({e})") from e
    _check_document(doc, path.name)
    return doc


def _check_keys(obj, where, field, allowed, required=()):
    if not isinstance(obj, dict):
        _fail(where, field, "must be an object")
    extra = sorted(set(obj) - set(allowed))
    if extra:
        _fail(where, field, f"unknown keys {extra}")
    missing = [k for k in required if k not in obj]
    if missing:
        _fail(where, field, f"missing keys {missing}")


def _check_document(doc, where):
    _check_keys(doc, where, "(file)", ("_comment", "version", "default", "profiles"), ("version", "default", "profiles"))
    if doc["version"] != VERSION:
        _fail(where, "version", f"must be {VERSION!r}, got {doc['version']!r}")
    profiles = doc["profiles"]
    if not isinstance(profiles, dict) or IDENTITY not in profiles:
        _fail(where, "profiles", f"must be an object that has a {IDENTITY!r} entry")
    if doc["default"] != IDENTITY:
        _fail(where, "default", f"must be {IDENTITY!r} (a request that names no profile is fitness), got {doc['default']!r}")
    for name, profile in profiles.items():
        if not NAME.fullmatch(name):
            _fail(where, f"profiles.{name}", "a profile name is lower case words (a-z, 0-9, _), starting with a letter")
        _check_profile(profile, where, f"profiles.{name}")
    _check_identity(profiles[IDENTITY], where, f"profiles.{IDENTITY}")


def _check_profile(profile, where, field):
    _check_keys(profile, where, field, ("kinds", "measures", "tempo"), ("kinds", "measures", "tempo"))
    kinds = profile["kinds"]
    _check_keys(kinds, where, f"{field}.kinds", KINDS, KINDS)
    for kind in KINDS:
        _check_tolerance(kinds[kind], where, f"{field}.kinds.{kind}", complete=True)
    measures = profile["measures"]
    if not isinstance(measures, dict):
        _fail(where, f"{field}.measures", "must be an object")
    for measure, tolerance in measures.items():
        try:
            kind_of(measure)
        except ProfileError:
            _fail(where, f"{field}.measures.{measure}", "not a measure with a cue (part5/cues.py)")
        _check_tolerance(tolerance, where, f"{field}.measures.{measure}", complete=False)
    _check_tempo(profile["tempo"], where, f"{field}.tempo")


def _check_tolerance(tolerance, where, field, complete):
    keys = tuple(IDENTITY_TOLERANCE)
    _check_keys(tolerance, where, field, keys, keys if complete else ())
    for key in ("threshold_multiplier", "min_fraction_multiplier"):
        if key in tolerance and not (_is_number(tolerance[key]) and tolerance[key] >= 1):
            _fail(where, f"{field}.{key}", f"must be a number of at least 1 (a profile only loosens), got {tolerance[key]!r}")
    add = tolerance.get("min_run_frames_add", 0)
    if not (_is_int(add) and add >= 0):
        _fail(where, f"{field}.min_run_frames_add", f"must be an integer of at least 0, got {add!r}")


def _check_tempo(tempo, where, field):
    _check_keys(tempo, where, field, tuple(IDENTITY_TEMPO), tuple(IDENTITY_TEMPO))
    replaced = tempo["cues"]
    _check_keys(replaced, where, f"{field}.cues", TEMPO_CUE_KEYS)
    for key, cue in replaced.items():
        if not (isinstance(cue, str) and 1 <= len(cue.split()) <= cues.MAX_WORDS and cue[0].isupper()
                and not cue.endswith(".") and not DASHES.search(cue)):
            _fail(where, f"{field}.cues.{key}",
                  f"must be a capitalised cue of 1 to {cues.MAX_WORDS} words with no dash, got {cue!r}")
    for key in ("weight", "cap"):
        if not (_is_number(tempo[key]) and tempo[key] >= 0):
            _fail(where, f"{field}.{key}", f"must be a number of at least 0, got {tempo[key]!r}")


def _check_identity(profile, where, field):
    """fitness is the identity: `effective_rules` returns the rules untouched for it, so the file may not say otherwise."""
    tolerances = [profile["kinds"][k] for k in KINDS]
    if any(t != IDENTITY_TOLERANCE for t in tolerances) or profile["measures"] or profile["tempo"] != IDENTITY_TEMPO:
        _fail(where, field, "must be the identity: every multiplier 1, every addition 0, no measures, "
                            "no tempo cue and a tempo weight and cap of 0")


# --- the names ---
def names(doc=None):
    """The profile names in file order."""
    return list((load() if doc is None else doc)["profiles"])


def default(doc=None):
    return (load() if doc is None else doc)["default"]


def require(name, doc=None):
    """`name` if it is a profile, else a `ProfileError` whose message is the sentence the API answers with."""
    known = names(doc)
    if not isinstance(name, str) or name not in known:
        raise ProfileError(f"profile: must be one of {known}")
    return name


def kind_of(measure):
    """`range` (how far a joint bends or a limb lifts) or `position` (where a body part sits), from the cue table."""
    if measure in cues.CUES:
        return cues.CUES[measure][0]
    raise ProfileError(f"no cue kind for measure {measure!r}")


# --- applying a profile ---
def effective_rules(rules, name=None, doc=None):
    """The rules a profile detects with. `rules` itself, the same object, for `fitness` or no name.

    Otherwise a new dict: every measure's config relaxed by the profile's tolerance for its kind (a per-measure
    entry replaces the kind's key by key), and a `profile` key `{name, baseline, tempo}` where `baseline` holds the
    unrelaxed config of each measure, which detection uses to judge what explains what (docs/specs/profiles.md).
    The input is not changed."""
    if name is None:
        return rules
    doc = load() if doc is None else doc
    if require(name, doc) == IDENTITY:
        return rules
    if "profile" in rules:
        raise ProfileError(f"profile {name}: the rules already carry profile {rules['profile'].get('name')!r}")
    profile = doc["profiles"][name]
    out = copy.deepcopy(rules)
    out["measures"], baseline = {}, {}
    # ADR-0015: a foot measure has no default threshold, so rules that lack its entry do not report it, and a profile
    # must not switch it on from `default` (it would report a fault fitness does not).
    named = [*rules.get("measures", {}), *(m for m in cues.CUES if m not in FOOT_GENERIC)]
    for measure in dict.fromkeys(named):
        tolerance = {**profile["kinds"][kind_of(measure)], **profile["measures"].get(measure, {})}
        base = {**rules["default"], **rules.get("measures", {}).get(measure, {})}
        baseline[measure] = copy.deepcopy(base)
        out["measures"][measure] = _relax(base, tolerance, name, measure)
    out["profile"] = {"name": name, "baseline": baseline, "tempo": copy.deepcopy(profile["tempo"])}
    return out


def fitness_rules(rules):
    """The `fitness` rules that effective `rules` were made from: `rules` itself when they carry no profile, else a
    copy that has each measure's baseline config and no `profile` key, so `detect` on it finds what `fitness` finds.
    Repetition mode uses it to judge a profile's take-level faults against fitness's own (`repwise.compare`)."""
    profile = rules.get("profile")
    if profile is None:
        return rules
    out = {key: value for key, value in rules.items() if key != "profile"}
    out["measures"] = copy.deepcopy(profile["baseline"])
    return out


def sides_of(side):
    """The sides a fault reports: `both` is left and right, anything else is itself."""
    return {"left", "right"} if side == "both" else {side}


def covered_by(key, fitness_keys):
    """Is a profile fault `key` = (measure, side, direction) covered by the fitness faults' keys of the same take? For
    every side it reports there is a fitness key with the same measure and direction that reports that side (a fault
    fitness reports on both sides may be reported on one by a profile). The loosen-only invariant, docs/specs/profiles.md."""
    measure, side, direction = key
    return all(any(m == measure and d == direction and s in sides_of(fs) for m, fs, d in fitness_keys)
               for s in sides_of(side))


def _relax(base, tolerance, name, measure):
    """`base` (one measure's full config) with the tolerance applied: a higher threshold, a larger share of the
    clip and a longer run to count, never less."""
    if "threshold_deg" not in base:
        raise ProfileError(f"profile {name}: {measure} has no threshold_deg in the rules")
    out = dict(base)
    out["threshold_deg"] = round(base["threshold_deg"] * tolerance["threshold_multiplier"], 6)
    share = tolerance["min_fraction_multiplier"]
    if "min_fraction" in base:
        out["min_fraction"] = round(base["min_fraction"] * share, 6)
        if out["min_fraction"] > 1:
            raise ProfileError(f"profile {name}: {measure} min_fraction {base['min_fraction']} times {share} is over 1")
    if base.get("min_frames"):
        out["min_frames"] = math.ceil(round(base["min_frames"] * share, 6))
    out["min_run_frames"] = base.get("min_run_frames", DEFAULT_MIN_RUN_FRAMES) + tolerance["min_run_frames_add"]
    return out


# --- tempo ---
def tempo_of(rules):
    """The profile's `{cues, weight, cap}` from effective rules, or the identity block for plain rules."""
    return copy.deepcopy((rules.get("profile") or {}).get("tempo", IDENTITY_TEMPO))


def tempo_points(ratio, weight, cap):
    """Score points a window's tempo costs under a profile that charges it: `weight` per 1.0 of ratio outside the
    cue band (below TEMPO_FAST or above TEMPO_SLOW), at most `cap`; 0 when the ratio is unmeasured."""
    if ratio is None or not math.isfinite(ratio):
        return 0.0
    outside = max(0.0, cues.TEMPO_FAST - ratio, ratio - cues.TEMPO_SLOW)
    return min(float(cap), weight * outside)


def file_sha256(path=PROFILES_PATH):
    """sha256 of the file's bytes: what `make check-5` prints as `profiles_sha256`, for information only."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
