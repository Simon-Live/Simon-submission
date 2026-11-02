"""Ask this take: the take and its tools (TICKET-081, docs/specs/ask-this-take.md "The tools", ADR-0022).

`Take` holds one analysis and the replay written with it, and `run_tool` runs the agent's five tools on it (`get_faults`,
`get_joint_angle`, `compare_with_teacher`, `seek`, `spotlight`). The tools read only that take, validate every argument and
return plain JSON data; `seek` and `spotlight` are recorded, never carried out. `strict_json` reads a request or a file so
that what is read can be written back as JSON.

Moved out of `part5/replay.py` unchanged in the 1.14.0 round. It no longer sits beside the pipeline's import, so the shared
finite number check is imported at the top.
"""
import hashlib
import json

import numpy as np

from ..io import JOINTS
from ..measures import MEASURES, SIDES, compute
from ..opinion.guard import shown_problem
from ..opinion.prompt import _number   # the one finite number check (TICKET-076 R13): None for nan, inf and a bool

# ADR-0022: the tools read only the take they are given; the model never reads a file, a take or an address.
UI_TOOLS = ("seek", "spotlight")
# The limbs `spotlight` takes besides a joint name, each with the canonical joints to highlight (as `faults[].joints`).
LIMBS = {f"{side}_{limb}": tuple(f"{side}_{part}" for part in parts) for side in SIDES
         for limb, parts in (("arm", ("shoulder", "elbow", "wrist")), ("leg", ("hip", "knee", "ankle")))}
LIMBS.update(torso=("left_shoulder", "right_shoulder", "left_hip", "right_hip"),
             head=("nose", "left_eye", "right_eye", "left_ear", "right_ear"))
# The fault fields `get_faults` returns, each as the analysis holds it (hub AC-1). The frame lists are left out: the
# model gets the sizes and times a follower reads, not indexes that would widen what its numbers may match.
FAULT_FIELDS = ("measure", "measure_kind", "joint", "joints", "body_part", "side", "direction", "magnitude_deg",
                "peak_deg", "threshold_deg", "unit", "at_s", "follower_t_s", "text", "text_timed", "cue", "lateral",
                "lateral_m")
DEGREES, SECONDS = 1, 2   # decimals of a measured angle and of a frame's time in a tool result
TIME_SLACK = 1e-6         # a time at the take's edge, written to 6 decimals in the replay, is inside it
MAX_ARGUMENTS_CHARS = 2000
ARGUMENTS_NOT_OBJECT = "arguments are not a JSON object"
# R1 of the 1.14.0 review: the arguments ship in `tool_calls` and the stream, which Part 7 may show, so the model's text in
# them is held to the answer's word guard; a call that fails it is not run and its arguments are not recorded.
ARGUMENTS_NOT_SHOWN = "arguments hold text that cannot be shown"
# R3 of the 1.14.0 review: a chain the follower declared not scored (`body_mask`, ADR-0023) carries made-up motion in the
# replay, so no tool reads or highlights it.
JOINT_NOT_SCORED = "that joint is not scored in this take, by the follower's setting; it has no measurement to give"
LIMB_NOT_SCORED = "that limb is not scored in this take, by the follower's setting; it cannot be highlighted"


class ToolError(ValueError):
    """A tool call the take cannot answer; the message is the result's `error`, which the model reads."""


def _positions(frames):
    """(F, 17, 3) floats from replay frames, NaN for a joint written as null."""
    nan = [np.nan] * 3
    return np.array([[point if point is not None else nan for point in frame] for frame in frames], dtype=float)


def _measures_at(joint):
    """[(name, spec)] of the measures read at `joint` (`measures.MEASURES`), in their order."""
    return [(name, spec) for name, spec in MEASURES.items() if spec.joint == joint]


JOINTS_WITH_MEASURES = tuple(j for j in JOINTS if _measures_at(j))


def _deg(value):
    return round(float(value), DEGREES) if np.isfinite(value) else None


def _row(name, spec):
    """The names of one measure as the analysis gives them: `knee_flexion` and `left` for `left_knee_flexion`."""
    generic = name[len(spec.side) + 1:] if spec.side in SIDES else name
    return {"measure": generic, "side": spec.side, "means": spec.description, "unit": "degrees"}


def _names(block, key):
    """The names listed under `key` of a `body_mask` block, as a set; empty when there is no block."""
    listed = block.get(key) if isinstance(block, dict) else None
    return frozenset(n for n in listed if isinstance(n, str)) if isinstance(listed, list) else frozenset()


class Take:
    """One analysed take: its analysis and the replay written with it (both checked first, `agent.ask_take`). The
    measures of both skeletons are computed once, on first use, from the replay's frames. `masked_joints` and
    `not_scored` are the analysis's `body_mask` lists (ADR-0023), empty when the follower declared no mask."""

    def __init__(self, analysis, replay):
        self.analysis, self.replay = analysis, replay
        self.t = np.asarray(replay["follower_t"], dtype=float)
        self.example_t = np.asarray(replay["expected_t"], dtype=float)
        self.exp_to_fol = np.asarray(replay["exp_to_fol"], dtype=int)
        block = analysis.get("body_mask")
        self.masked_joints = _names(block, "masked_joints")
        self.not_scored = _names(block, "not_scored_measures")
        self._series = {}

    def measures_at(self, joint):
        """[(name, spec)] of the scored measures read at `joint`: `_measures_at` without those the mask drops."""
        return [(name, spec) for name, spec in _measures_at(joint) if name not in self.not_scored]

    @property
    def span(self):
        return float(self.t[0]), float(self.t[-1])

    def series(self, skeleton):
        """`{measure name: (F,) degrees}` of the `follower` or the `expected` skeleton."""
        if skeleton not in self._series:
            self._series[skeleton] = compute(_positions(self.replay[skeleton]))
        return self._series[skeleton]

    def nearest(self, t):
        return int(np.argmin(np.abs(self.t - t)))

    def example_frame(self, frame):
        """The example frame the alignment shows with follower `frame`: the middle of those `exp_to_fol` maps to it,
        else the one whose follower frame is nearest (the first of a tie)."""
        matched = np.flatnonzero(self.exp_to_fol == frame)
        if matched.size:
            return int(matched[matched.size // 2])
        return int(np.argmin(np.abs(self.exp_to_fol - frame)))

    def sha256(self):
        """The SHA-256 of the take's tool data: the `get_faults` result and the replay's joints, frames, times and
        alignment, as canonical JSON. Two requests about one take carry the same value."""
        keys = ("joints", "expected", "follower", "expected_t", "follower_t", "exp_to_fol")
        data = {"faults": get_faults(self, {}), "replay": {key: self.replay[key] for key in keys}}
        if self.masked_joints or self.not_scored:   # the tools refuse these; a take with no mask keeps its digest
            data["not_scored"] = {"joints": sorted(self.masked_joints), "measures": sorted(self.not_scored)}
        text = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(text.encode()).hexdigest()


def _only(args, *names):
    """ToolError for an argument the tool does not take. The error names the arguments it takes and never the one it
    was sent: an error result echoes no text of the model's (R1 of the 1.14.0 review)."""
    if set(args) - set(names):
        raise ToolError(f"unknown argument; this tool takes {', '.join(names) or 'no argument'}")


def _time(take, args, key):
    """The seconds in `args[key]`: a finite number (not a bool) inside the take."""
    value = _number(args.get(key))
    if value is None:
        raise ToolError(f"{key} must be a number of seconds")
    start, end = take.span
    if not start - TIME_SLACK <= value <= end + TIME_SLACK:
        raise ToolError(f"{key} must be inside the take, {start:.2f} to {end:.2f} s")
    return value


def _joint(take, args):
    joint = args.get("joint")
    if not isinstance(joint, str) or joint not in take.replay["joints"]:
        raise ToolError(f"joint must be a joint of the take with a measure: {', '.join(JOINTS_WITH_MEASURES)}")
    if joint not in JOINTS_WITH_MEASURES:
        raise ToolError(f"no measure is read at that joint; the joints with one are {', '.join(JOINTS_WITH_MEASURES)}")
    if joint in take.masked_joints or not take.measures_at(joint):
        raise ToolError(JOINT_NOT_SCORED)
    return joint


def get_faults(take, args):
    """The faults as the analysis holds them (`FAULT_FIELDS`, with their index), their count, the take's first and
    last time and the warning codes."""
    _only(args)
    faults = [{"index": i, **{key: f[key] for key in FAULT_FIELDS if key in f}}
              for i, f in enumerate(take.analysis["faults"])]
    warnings = [w["code"] for w in take.analysis.get("warnings") or []
                if isinstance(w, dict) and isinstance(w.get("code"), str)]
    times = take.replay["follower_t"]
    return {"count": len(faults), "faults": faults, "take": {"start_s": times[0], "end_s": times[-1]},
            "warnings": warnings}


def _range_row(name, spec, values, frames, t):
    """One measure over `frames`: min, max and mean in degrees and the times of the min and the max."""
    v = values[frames]
    seen = np.isfinite(v)
    row = {**_row(name, spec), "seen_frames": int(seen.sum())}
    if not seen.any():
        return {**row, "min": None, "max": None, "mean": None, "min_at_s": None, "max_at_s": None}
    kept, at = v[seen], frames[seen]
    low, high = int(np.argmin(kept)), int(np.argmax(kept))
    return {**row, "min": _deg(kept[low]), "max": _deg(kept[high]), "mean": _deg(kept.mean()),
            "min_at_s": round(float(t[at[low]]), SECONDS), "max_at_s": round(float(t[at[high]]), SECONDS)}


def get_joint_angle(take, args):
    """The follower's measures at `joint` over `t0` to `t1` (the nearest frame when none falls inside)."""
    _only(args, "joint", "t0", "t1")
    joint, t0, t1 = _joint(take, args), _time(take, args, "t0"), _time(take, args, "t1")
    if t0 > t1:
        raise ToolError("t0 must not be after t1")
    frames = np.flatnonzero((take.t >= t0 - TIME_SLACK) & (take.t <= t1 + TIME_SLACK))
    if not frames.size:
        frames = np.array([take.nearest(t0)])
    series = take.series("follower")
    return {"joint": joint, "t0": t0, "t1": t1, "frames": int(frames.size),
            "measures": [_range_row(name, spec, series[name], frames, take.t) for name, spec in take.measures_at(joint)]}


def compare_with_teacher(take, args):
    """The follower's measures at `joint` in the frame nearest `t`, against the example's in the frame the alignment
    shows with it; `difference_deg` is the take's minus the example's, the sign of `magnitude_deg`."""
    _only(args, "joint", "t")
    joint, t = _joint(take, args), _time(take, args, "t")
    frame = take.nearest(t)
    example = take.example_frame(frame)
    mine, theirs = take.series("follower"), take.series("expected")
    rows = [{**_row(name, spec), "take_deg": _deg(mine[name][frame]), "example_deg": _deg(theirs[name][example]),
             "difference_deg": _deg(mine[name][frame] - theirs[name][example])}
            for name, spec in take.measures_at(joint)]
    return {"joint": joint, "t": t, "take_t_s": round(float(take.t[frame]), SECONDS),
            "example_t_s": round(float(take.example_t[example]), SECONDS), "measures": rows}


def seek(take, args):
    """A UI action: the player seeks to `t` on the take's clock."""
    _only(args, "t")
    return {"type": "seek", "t": round(_time(take, args, "t"), 3), "limb": None}


def spotlight(take, args):
    """A UI action: the player highlights `limb` (a name of `LIMBS` or a joint of the take) at `t`."""
    _only(args, "limb", "t")
    limb = args.get("limb")
    if isinstance(limb, str) and limb in LIMBS:
        joints = list(LIMBS[limb])
    elif isinstance(limb, str) and limb in take.replay["joints"]:
        joints = [limb]
    else:
        raise ToolError(f"limb must be one of {', '.join(LIMBS)} or a joint of the take")
    if take.masked_joints.intersection(joints):
        raise ToolError(LIMB_NOT_SCORED)
    return {"type": "spotlight", "t": round(_time(take, args, "t"), 3), "limb": limb, "joints": joints}


TOOLS = {"get_faults": get_faults, "get_joint_angle": get_joint_angle, "compare_with_teacher": compare_with_teacher,
         "seek": seek, "spotlight": spotlight}


def _not_finite(text):
    raise ValueError(f"{text} is not a finite number")


def _finite_float(text):
    value = float(text)
    if not np.isfinite(value):   # 1e999 reads as inf, which no JSON document may hold
        raise ValueError(f"{text} is not a finite number")
    return value


def strict_json(text):
    """`text` (str or bytes) parsed as JSON with NaN, Infinity and a number too large for a float refused
    (ValueError), so what Ask this take reads it can write back as JSON."""
    return json.loads(text, parse_constant=_not_finite, parse_float=_finite_float)


def parse_arguments(text):
    """The arguments of a tool call (the model's JSON text) as a dict of finite values; `{}` for empty text."""
    if not isinstance(text, str) or len(text) > MAX_ARGUMENTS_CHARS:
        raise ToolError(ARGUMENTS_NOT_OBJECT)
    if not text.strip():
        return {}
    try:
        args = strict_json(text)
    except (ValueError, RecursionError):
        raise ToolError(ARGUMENTS_NOT_OBJECT) from None
    if not isinstance(args, dict):
        raise ToolError(ARGUMENTS_NOT_OBJECT)
    return args


def strings_of(value):
    """Every string in the JSON value `value`, the keys of its objects included. Walked with a stack, not recursion, so
    arguments nested as deep as the parser allows are read too."""
    found, stack = [], [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            found.append(item)
        elif isinstance(item, dict):
            found += item.keys()
            stack += item.values()
        elif isinstance(item, list):
            stack += item
    return found


def arguments_shown(args):
    """True when every string of `args` passes the answer's word guard (`guard.shown_problem`)."""
    return not any(shown_problem(text) for text in strings_of(args))


def run_tool(take, name, arguments):
    """`(record, action)` for one call of the tool `name` (one of `TOOLS`) with the JSON text `arguments`: the record
    `{name, arguments, ok, result}` and, for a valid `seek` or `spotlight`, its UI action (else None). A bad call is
    `ok: false` with `result: {error}`; it never raises. Arguments that are not one JSON object, or that hold text the
    word guard refuses, are recorded as `{}` and the call is not run."""
    try:
        args = parse_arguments(arguments)
    except ToolError as error:
        return {"name": name, "arguments": {}, "ok": False, "result": {"error": str(error)}}, None
    if not arguments_shown(args):
        return {"name": name, "arguments": {}, "ok": False, "result": {"error": ARGUMENTS_NOT_SHOWN}}, None
    try:
        result = TOOLS[name](take, args)
    except ToolError as error:
        return {"name": name, "arguments": args, "ok": False, "result": {"error": str(error)}}, None
    return {"name": name, "arguments": args, "ok": True, "result": result}, (dict(result) if name in UI_TOOLS else None)
