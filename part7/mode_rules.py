"""Scoring rules per practice mode, derived from the pinned Part 5's own `rules.json` at run time.

ADR-0008 (operator directive of 2026-10-31): dance and rehab loosen Part 5's fault thresholds and
soften the score slope. Fitness is the unchanged standard rule set. Nothing here is a copy of Part 5's
numbers: each variant is the pinned file with the factors below applied, so a Part 5 retune flows through.

Every factor only loosens (threshold factors >= 1, run lengths up, slope factor <= 1). Measures that are a
cause in `explained_by` or `explained_by_opposite` are never loosened, so a mode cannot surface an effect whose
cause it dropped. As a safety net `p5_analyse` runs the standard rules first and keeps the mode result only when it
reports no fault (measure, side) the standard run does not.
The body stays the one standard body for everyone (ADR-0008 option 3): that is the fairness of the score.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

from part7 import modes

RULES_RELPATH = Path("part5") / "rules.json"
PROFILE_SOURCE = "part7-rules"
NOTE_ADDS_FAULT = "Mode rules would add a fault the standard rules do not; standard rules used"
NOTE_RUN_FAILED = "Scoring rules for {mode} could not be applied to this take; standard rules used"
NOTE_UNAVAILABLE = "Scoring rules for {mode} unavailable in this Part 5; standard rules used"

# Position measures a dance moves on purpose (style), so a wider band is fair.
DANCE_STYLE = ("forearm_out", "thigh_out", "foot_out", "knee_valgus", "trunk_lean_forward", "trunk_lean_side",
               "shoulder_tilt", "head_forward")
# Range-of-motion measures: a rehab client works inside a limited range, so they loosen less.
REHAB_RANGE = ("elbow_flexion", "knee_flexion", "upper_arm_out", "upper_arm_forward", "thigh_forward")

# mode -> default: factor for the default threshold and every measure not named in `threshold`;
# threshold: per-measure factors; min_run: factor on min_run_frames; slope: factor on score.slope.
FACTORS: dict[str, dict[str, Any]] = {
    "dance": {"default": 1.0, "threshold": {m: 1.5 for m in DANCE_STYLE}, "min_run": 1.0, "slope": 0.9},
    "rehab": {"default": 1.6, "threshold": {m: 1.25 for m in REHAB_RANGE}, "min_run": 1.5, "slope": 0.8},
}

# One row per knob: (mode, knob, factor, reason). Mirrored in docs/adr/ADR-0008 and practice-and-modes.md.
TABLE = (
    ("dance", "forearm_out, thigh_out, foot_out, knee_valgus, trunk_lean_forward, trunk_lean_side, "
              "shoulder_tilt, head_forward thresholds (causes excepted)", "x1.5", "style and flourish move these on purpose"),
    ("all", "causes in explained_by and explained_by_opposite (at this pin foot_out, knee_valgus, upper_arm_out, "
            "trunk_lean_forward): threshold and min_run_frames", "x1.0",
     "loosening a cause drops its fault and would surface the effect it explained"),
    ("dance", "every other threshold, min_run_frames", "x1.0", "form that defines the move stays strict"),
    ("dance", "score slope", "x0.9", "a miss costs a little less per degree over the threshold"),
    ("rehab", "elbow_flexion, knee_flexion, upper_arm_out, upper_arm_forward, thigh_forward thresholds (causes excepted)", "x1.25",
     "range of motion is the point of the exercise, so it loosens least"),
    ("rehab", "every other threshold, default included (causes excepted)", "x1.6", "gentle, unhurried movement needs a wide band"),
    ("rehab", "min_run_frames (causes excepted)", "x1.5, rounded up", "a brief wobble is not a fault"),
    ("rehab", "score slope", "x0.8", "a miss costs less per degree over the threshold"),
    ("fitness", "everything", "x1.0", "Part 5's standard rules, untouched"),
)


def load_base(clone: Path | str) -> dict[str, Any]:
    """The pinned Part 5's own rules, read from its clone."""
    return json.loads((Path(clone) / RULES_RELPATH).read_text(encoding="utf-8"))


def _loosen(value: float, factor: float) -> float:
    # rounded up at 3 places, so a factor >= 1 can never give a tighter number
    return math.ceil(float(value) * factor * 1000 - 1e-9) / 1000


def causes_of(rules: dict[str, Any]) -> set[str]:
    """Measures that explain another in `explained_by` or `explained_by_opposite`.

    Loosening a cause could drop its fault and so stop explaining the effect, which would then be reported.
    Causes keep the standard threshold; only effects and independent measures loosen.
    """
    out: set[str] = set()
    for key in ("explained_by", "explained_by_opposite"):
        for names in (rules.get(key) or {}).values():
            if isinstance(names, list):
                out.update(n for n in names if isinstance(n, str))
    return out


def derive(rules: dict[str, Any], mode: str | None) -> dict[str, Any]:
    """A deep copy of `rules` with `mode`'s factors applied; fitness (and None) returns an equal copy."""
    out = copy.deepcopy(rules)
    cfg = FACTORS.get(mode) if mode in modes.MODES else None
    if cfg is None:
        return out
    default = out.get("default") or {}
    measures = out.setdefault("measures", {})
    base_threshold = default.get("threshold_deg")
    base_run = default.get("min_run_frames")
    causes = causes_of(rules)
    if base_threshold is not None and cfg["default"] != 1.0:
        default["threshold_deg"] = _loosen(base_threshold, cfg["default"])
    for name in sorted(set(measures) | set(cfg["threshold"]) | causes):
        factor = cfg["threshold"].get(name, cfg["default"])
        entry = measures.get(name, {})
        source = entry.get("threshold_deg", base_threshold)
        if name in causes:
            # a cause keeps its standard threshold and run length, pinned explicitly because the default moves
            if source is not None:
                measures.setdefault(name, {})["threshold_deg"] = source
            run = entry.get("min_run_frames", base_run)
            if run is not None:
                measures.setdefault(name, {})["min_run_frames"] = run
            continue
        if factor != 1.0 and source is not None:
            measures.setdefault(name, {})["threshold_deg"] = _loosen(source, factor)
        if "min_run_frames" in entry:
            entry["min_run_frames"] = math.ceil(entry["min_run_frames"] * cfg["min_run"])
    if "min_run_frames" in default:
        default["min_run_frames"] = math.ceil(default["min_run_frames"] * cfg["min_run"])
    score = out.get("score")
    if isinstance(score, dict) and isinstance(score.get("slope"), (int, float)):
        score["slope"] = round(score["slope"] * cfg["slope"], 3)
    return out


def write_variant(clone: Path | str, mode: str, path: Path | str) -> Path:
    """Derive `mode`'s rules from the clone's `rules.json` and write them to `path`."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(derive(load_base(clone), mode), indent=2) + "\n", encoding="utf-8")
    return target
