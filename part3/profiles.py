"""Body profiles: which fixed set of 18 bone lengths every frame is rebuilt on (spec
integration-contract.md "Body profiles").

`resolve` picks the profile and the stature from the channels (flag, environment, config file, API
parameter, default); `lengths_for` turns the pick into a `Body` with the numbers. The numbers of the
named profiles are typed in here as data with their source beside them; nothing reads another part
at run time.
"""

import dataclasses
import json
import math
import os
import pathlib

from part3 import config as config_file
from part3 import io, standard
from part3.joints import BONE_NAMES
from part3.schema import ContractError

NAMES = ("simon-standard", "part4-rig", "measured")
SELECTED_BY = ("flag", "env", "config", "api", "default")
FILE_PREFIX = "file:"
PROFILE_SCHEMA = "simon.body_profile/1"
BONE_RANGE_M = (0.005, 1.5)
STATURE_RANGE_M = (0.5, 2.5)
EQUAL_PAIRS = (("left_pelvis", "right_pelvis"), ("left_clavicle", "right_clavicle"))

STANDARD_SOURCE = "part3/standard_body.json"
MEASURED_SOURCE = "measured: median input bone lengths of this clip"
PART4_SOURCE = ("moalborati/simon-part-4-animate-keyframes 9f4c073: README 'The body and the coordinate frame'; "
                "fixtures/input/exercise/skeleton.json bone_lengths_m")
PART4_STATURE_M = 1.70
PART4_LENGTHS_M = {
    "left_pelvis": 0.125, "right_pelvis": 0.125,
    "left_thigh": 0.4165, "right_thigh": 0.4165,
    "left_shank": 0.4182, "right_shank": 0.4182,
    "spine": 0.4896,
    "left_clavicle": 0.1979, "right_clavicle": 0.1979,
    "left_upper_arm": 0.3162, "right_upper_arm": 0.3162,
    "left_forearm": 0.2482, "right_forearm": 0.2482,
    "head": 0.1907,
    "left_eye_link": 0.0618, "right_eye_link": 0.0618,
    "left_ear_link": 0.0774, "right_ear_link": 0.0774,
}
UNKNOWN = 'unknown body profile "{}"; choose simon-standard, part4-rig, measured or file:<path>'


@dataclasses.dataclass(frozen=True)
class Selection:
    """The profile chosen and which channel chose it (`selected_by`: flag, env, config, api, default)."""

    name: str
    selected_by: str
    spec: str
    stature: float | None = None
    stature_selected_by: str | None = None
    config_dir: pathlib.Path | None = None


@dataclasses.dataclass(frozen=True)
class Body:
    """A profile with its numbers: `bone_lengths_m` is rounded and already scaled by `scale`."""

    name: str
    stature_m: float
    scale: float
    bone_lengths_m: dict
    source: str
    sources: list
    symmetrized: bool
    selected_by: str
    stature_selected_by: str | None = None

    def block(self):
        """The top-level `body` block of a skeleton (`stature_selected_by` only when a stature was asked for)."""
        block = {"profile": self.name, "selected_by": self.selected_by, "stature_m": self.stature_m,
                 "scale": self.scale, "source": self.source, "symmetrized": self.symmetrized}
        if self.stature_selected_by is not None:
            block["stature_selected_by"] = self.stature_selected_by
        return block


@dataclasses.dataclass(frozen=True)
class _Base:
    stature_m: float
    lengths: dict
    source: str
    sources: list
    symmetrized: bool = False


# --- selection ----------------------------------------------------------------------------------

def _pick(candidates):
    """(value, channel kind, label) of the first candidate that is set, else (None, "default", None)."""
    for value, kind, label in candidates:
        if value is not None:
            return value, kind, label
    return None, "default", None


def _env_value(env, key):
    value = env.get(key)
    return value if value else None


def _profile_name(spec, channel):
    if isinstance(spec, str) and (spec in NAMES or (spec.startswith(FILE_PREFIX) and spec[len(FILE_PREFIX):])):
        return spec if spec in NAMES else "file"
    raise ContractError(channel, UNKNOWN.format(spec))


def parse_stature(value, channel):
    """`value` (a number or numeric text) as a float in 0.5 to 2.5 m, else ContractError naming `channel`."""
    low, high = STATURE_RANGE_M
    try:
        number = float(value) if not isinstance(value, bool) else math.nan
    except (TypeError, ValueError):
        number = math.nan
    if not low <= number <= high:
        raise ContractError(channel, f"stature must be {low} to {high} m (got {value})")
    return number


def resolve(flag=None, api=None, stature_flag=None, stature_api=None, env=None, config=None):
    """The `Selection` for the channels, first set wins: flag, environment, config file, API, default.

    Body: `--body`, `PART3_BODY`, config `[body] profile`, API `body=`, `simon-standard`. Stature:
    `--stature`, `PART3_STATURE`, config `[body] stature`, API `stature=`, none. `env` None means
    `os.environ`; `config` None discovers `PART3_CONFIG` then `./part3.toml`, False reads no file, a
    path names the file. Raises ContractError naming the channel for an unknown profile, a stature
    out of range or a bad config file.
    """
    env = os.environ if env is None else env
    cfg = config_file.load(config, env)
    label = cfg.label if cfg else ""
    spec, kind, channel = _pick([
        (flag, "flag", "--body"), (_env_value(env, "PART3_BODY"), "env", "PART3_BODY"),
        (cfg.profile if cfg else None, "config", f"{label} body.profile"), (api, "api", "body=")])
    name = _profile_name(spec, channel) if spec is not None else "simon-standard"
    stature, stature_kind, stature_channel = _pick([
        (stature_flag, "flag", "--stature"), (_env_value(env, "PART3_STATURE"), "env", "PART3_STATURE"),
        (cfg.stature if cfg else None, "config", f"{label} body.stature"), (stature_api, "api", "stature=")])
    return Selection(name, kind, spec if spec is not None else name,
                     parse_stature(stature, stature_channel) if stature is not None else None,
                     stature_kind if stature is not None else None,
                     cfg.dir if cfg and kind == "config" else None)


# --- numbers ------------------------------------------------------------------------------------

def _chain(lengths):
    """Leg and trunk chain in metres: thigh and shank (both sides averaged) plus the spine."""
    legs = sum(lengths[f"{side}_{bone}"] for side in ("left", "right") for bone in ("thigh", "shank"))
    return legs / 2.0 + lengths["spine"]


def estimate_stature(lengths):
    """The standard stature scaled by the leg and trunk chain of `lengths` over the standard body's."""
    return standard.stature_m() * _chain(lengths) / _chain(standard.bone_lengths())


def symmetrize(lengths):
    """Copy of `lengths` with every left/right pair replaced by its mean."""
    out = dict(lengths)
    for name in BONE_NAMES:
        if name.startswith("left_"):
            twin = "right_" + name[len("left_"):]
            out[name] = out[twin] = (lengths[name] + lengths[twin]) / 2.0
    return out


def _number_problem(value, low, high, unit):
    """Why `value` is not a finite number in [low, high], or None when it is."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "expected a number"
    try:
        inside = low <= value <= high and math.isfinite(value)
    except OverflowError:
        inside = False
    return None if inside else f"{value} is not between {low} and {high} {unit}"


def rule_problem(lengths, stature_m):
    """(field, reason) of the first profile rule the 18 lengths and the stature break, or None."""
    problem = _number_problem(stature_m, *STATURE_RANGE_M, "m")
    if problem:
        return "stature_m", problem
    if not isinstance(lengths, dict):
        return "bone_lengths_m", "expected an object with the 18 bones"
    for name in lengths:
        if name not in BONE_NAMES:
            return f"bone_lengths_m.{name}", "unknown bone"
    for name in BONE_NAMES:
        if name not in lengths:
            return f"bone_lengths_m.{name}", "missing"
        problem = _number_problem(lengths[name], *BONE_RANGE_M, "m")
        if problem:
            return f"bone_lengths_m.{name}", problem
    for left, right in EQUAL_PAIRS:
        if lengths[left] != lengths[right]:
            return (f"bone_lengths_m.{right}",
                    f"must equal {left} ({lengths[left]}), or the hip and shoulder midpoints move")
    return None


def check_rules(lengths, stature_m, where):
    """Raise ContractError(`where`, "<field>: <reason>") unless the lengths and stature meet the rules."""
    found = rule_problem(lengths, stature_m)
    if found:
        raise ContractError(where, f"{found[0]}: {found[1]}")


# --- profile sources ----------------------------------------------------------------------------

def _read_file(selection):
    """(document, label) of a `file:` profile; relative paths follow the config file that named it."""
    raw = selection.spec[len(FILE_PREFIX):]
    where = f"body {FILE_PREFIX}{raw}"
    path = pathlib.Path(raw)
    if not path.is_absolute() and selection.config_dir is not None:
        path = selection.config_dir / path
    try:
        return json.loads(path.read_text(encoding="utf-8")), where
    except OSError as error:
        raise ContractError(where, f"cannot read ({error.strerror or error})") from error
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise ContractError(where, f"not valid JSON ({error})") from error


def _text_field(doc, key, where):
    value = doc.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(where, f"{key}: expected a non-empty string")
    return value.strip()


def _file_base(selection):
    doc, where = _read_file(selection)
    if not isinstance(doc, dict):
        raise ContractError(where, "expected an object")
    if doc.get("schema") != PROFILE_SCHEMA:
        raise ContractError(where, f'schema: expected "{PROFILE_SCHEMA}"')
    name, source = _text_field(doc, "name", where), _text_field(doc, "source", where)
    check_rules(doc.get("bone_lengths_m"), doc.get("stature_m"), where)
    source = f"{source} ({FILE_PREFIX}{selection.spec[len(FILE_PREFIX):]})"
    return _Base(float(doc["stature_m"]), dict(doc["bone_lengths_m"]), source, [source]), f"{FILE_PREFIX}{name}"


def _measured_base(measured_lengths):
    where = "body measured"
    if not isinstance(measured_lengths, dict) or list(measured_lengths) != list(BONE_NAMES):
        raise ContractError(where, "needs the measured lengths of the 18 bones")
    lengths = {name: io.round_clean(value, io.OUTPUT_DECIMALS)
               for name, value in symmetrize(measured_lengths).items()}
    stature = io.round_clean(estimate_stature(lengths), io.OUTPUT_DECIMALS)
    check_rules(lengths, stature, where)
    return _Base(stature, lengths, MEASURED_SOURCE, [MEASURED_SOURCE], True)


def _base(selection, measured_lengths):
    """(_Base, profile name for the output) of a selection."""
    if selection.name == "measured":
        return _measured_base(measured_lengths), "measured"
    if selection.name == "part4-rig":
        return _Base(PART4_STATURE_M, dict(PART4_LENGTHS_M), PART4_SOURCE, [PART4_SOURCE]), "part4-rig"
    if selection.name == "file":
        return _file_base(selection)
    return _Base(standard.stature_m(), standard.bone_lengths(), STANDARD_SOURCE, standard.sources()), \
        "simon-standard"


def lengths_for(selection, measured_lengths=None):
    """The `Body` of `selection`; `measured_lengths` ({bone: m}, 18 bones) is read only by `measured`.

    `--stature` scales every length by `stature / profile stature`; the lengths are rounded to 4
    decimals after scaling. Raises ContractError naming the profile and the field for a bad `file:`
    profile or an unusable measured body.
    """
    base, name = _base(selection, measured_lengths)
    stature = selection.stature
    scale = 1.0 if stature is None else stature / base.stature_m
    return Body(name, base.stature_m if stature is None else stature, scale, _scaled(base, scale),
                base.source, list(base.sources), base.symmetrized, selection.selected_by,
                selection.stature_selected_by)


def _scaled(base, scale):
    return {bone: io.round_clean(base.lengths[bone] * scale, io.OUTPUT_DECIMALS) for bone in BONE_NAMES}


# --- the `body` block of a skeleton file ----------------------------------------------------------

def _block_fail(p, field, message):
    raise ContractError(f"{p}.body.{field}", message)


def _check_block_fields(block, doc, p):
    if not isinstance(block.get("profile"), str) or not block["profile"]:
        _block_fail(p, "profile", "expected a profile name")
    if block.get("selected_by") not in SELECTED_BY:
        _block_fail(p, "selected_by", f"expected one of {', '.join(SELECTED_BY)}")
    if "stature_selected_by" in block and block["stature_selected_by"] not in SELECTED_BY[:-1]:
        _block_fail(p, "stature_selected_by", f"expected one of {', '.join(SELECTED_BY[:-1])}")
    scale = block.get("scale")
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not 0 < scale < math.inf:
        _block_fail(p, "scale", "expected a positive number")
    if block.get("stature_m") != doc["standard"]["stature_m"]:
        raise ContractError(f"{p}.standard.stature_m", "must equal body.stature_m")
    if not isinstance(block.get("source"), str) or not block["source"]:
        _block_fail(p, "source", "expected a source text")
    if not isinstance(block.get("symmetrized"), bool):
        _block_fail(p, "symmetrized", "expected true or false")


def _check_block_numbers(block, doc, p):
    """A named profile's numbers must be the profile's at `scale`; a `file:` profile only meets the rules."""
    name = block["profile"]
    if name.startswith(FILE_PREFIX):
        return
    if name not in NAMES:
        _block_fail(p, "profile", f"expected one of {', '.join(NAMES)} or file:<name>")
    selection = Selection(name, "default", name)
    base, _ = _base(selection, doc["person"]["measured_bone_lengths_m"])
    if _scaled(base, block["scale"]) != doc["bone_lengths_m"]:
        raise ContractError(f"{p}.bone_lengths_m", f"must be the {name} lengths times body.scale")
    if abs(base.stature_m * block["scale"] - block["stature_m"]) > 1e-9 or block["symmetrized"] != base.symmetrized:
        _block_fail(p, "stature_m", f"does not match the {name} profile at this scale")
    if doc["standard"]["sources"] != base.sources or block["source"] != base.source:
        _block_fail(p, "source", f"does not match the {name} profile")


def validate_block(doc, p="skeleton"):
    """Raise ContractError unless the `body` block of a skeleton `doc` is consistent with its numbers.

    `doc` already has valid `standard`, `bone_lengths_m` and `person` blocks. Every profile meets the
    rules of `check_rules`; a named profile also gives exactly its own numbers at the recorded scale.
    """
    block = doc.get("body")
    if not isinstance(block, dict):
        raise ContractError(f"{p}.body", "expected an object")
    _check_block_fields(block, doc, p)
    found = rule_problem(doc["bone_lengths_m"], block["stature_m"])
    if found:
        raise ContractError(f"{p}.{found[0]}", found[1])
    _check_block_numbers(block, doc, p)
