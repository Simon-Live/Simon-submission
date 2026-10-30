"""Live phrasing review (TICKET-037, AC-P07): `python -m part5.phrasing.review [--n 20] [--out FILE]`.

Analyses the real stock takes and Part 3's kit takes (fixtures only, offline), gives each fault its
time, direction and timed template words (J-1, J-2), asks Muse Spark for the line and runs the timed
validator. Prints one JSON object per line sample plus the fallback rate. It makes real calls, so
it is opt-in: it needs the key file (running it is the live opt-in) and is never part
of `make test` or `make check-5`. The key is never printed.

The time and direction here are derived from the spec rules (`docs/specs/journey-followup.md`, J-1
and J-2) on top of `part5.pipeline.run`, so the review does not depend on the output module.
"""
import argparse
import json
import math
import sys
from pathlib import Path

from .. import phrasing
from ..pipeline import run
from . import muse_spark

ROOT = Path(__file__).resolve().parents[2]
STOCK_EXPECTED = "fixtures/input/eval/real/pexels-5034562/skeleton.json"
STOCK_FOLLOWERS = ("pexels-5034577", "pexels-8837221")
KIT_EXPECTED = "fixtures/input/expected/part3-squat/animation.json"
KIT_DIR = "fixtures/input/contract/part3/followers"
SYNTHETIC_EXPECTED = "fixtures/input/expected/exercise/animation.json"
SYNTHETIC_DIR = "fixtures/input/followers/exercise"
OUT_MEASURES = ("foot_out", "thigh_out", "upper_arm_out", "forearm_out")
WORD = {"foot_out": "foot", "thigh_out": "knee", "upper_arm_out": "arm", "forearm_out": "hand"}
FLIP = {"left": "right", "right": "left"}


def lateral_of(fault):
    """The subject's own left or right for a fault, J-2 table; None when the measure has no sideways word."""
    measure, side, direction = fault["measure"], fault["side"], fault["direction"]
    if side in ("left", "right"):
        if measure in OUT_MEASURES:
            return side if direction == "more" else FLIP[side]
        if measure == "knee_valgus":
            return FLIP[side] if direction == "more" else side
    if measure == "trunk_lean_side":
        return "left" if direction == "more" else "right"
    return None


def at_s_of(fault, follower_t):
    """The follower file's own time at the fault's first frame, rounded half up to 0.1 s."""
    return math.floor(float(follower_t[fault["follower_frames"][0]]) * 10 + 0.5) / 10


def timed_words(fault, lateral, at_s):
    """The J-2 vocabulary: the timed template line (the review's stand-in for `text_timed`)."""
    measure, side = fault["measure"], fault["side"]
    if measure in WORD and lateral and side in ("left", "right"):
        words = f"{side} {WORD[measure]} too far {lateral}"
    elif measure in ("thigh_forward", "upper_arm_forward") and fault["direction"] == "less":
        words = {"thigh_forward": "thigh", "upper_arm_forward": "arm"}[measure]
        words = f"{side} {words} too low" if side in ("left", "right") else f"{words}s too low"
    else:
        words = fault["text"]
    return f"{words} at {at_s:.1f} s"


def timed_faults():
    """Every fault of every fixture take, as (take id, timed fault dict)."""
    pairs = [(f, STOCK_EXPECTED, f"fixtures/input/eval/real/{f}/skeleton.json") for f in STOCK_FOLLOWERS]
    kit = sorted((ROOT / KIT_DIR).glob("*/skeleton.json"))
    pairs += [(p.parent.name, KIT_EXPECTED, str(p.relative_to(ROOT))) for p in kit]
    # The stock and kit takes hold fewer than 20 faults: the synthetic good-light takes with a
    # single labelled fault fill the rest and are marked "synthetic" in the sample.
    synthetic = sorted((ROOT / SYNTHETIC_DIR).glob("exercise_*_good_0[2-7]_*/skeleton.json"))
    pairs += [(p.parent.name, SYNTHETIC_EXPECTED, str(p.relative_to(ROOT))) for p in synthetic]
    out = []
    for take, expected, follower in pairs:
        result = run(str(ROOT / expected), str(ROOT / follower))
        for fault in result.analysis["faults"]:
            lateral = lateral_of(fault)
            at_s = at_s_of(fault, result.follower.t)
            out.append((take, {**fault, "at_s": at_s, "lateral": lateral,
                               "text_timed": timed_words(fault, lateral, at_s)}))
    return out


def pick(faults, n):
    """`n` faults, spread over the measures first, then in order."""
    by_measure = {}
    for item in faults:
        by_measure.setdefault(item[1]["measure"], []).append(item)
    picked = []
    while len(picked) < n and any(by_measure.values()):
        for items in by_measure.values():
            if items and len(picked) < n:
                picked.append(items.pop(0))
    return picked


def sample(take, fault):
    result = phrasing.phrase_fault(fault, timeout_s=10, live=True)
    keys = ("measure", "side", "direction", "lateral", "at_s", "magnitude_deg", "threshold_deg", "text_timed")
    source = "synthetic" if take.startswith("exercise_") else "stock" if take.startswith("pexels") else "kit"
    return {"take": take, "source": source, "fault": {k: fault[k] for k in keys}, **result}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m part5.phrasing.review", description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--out", help="also write the samples here as JSON")
    args = ap.parse_args(argv)
    reason = muse_spark.unavailable(live=True)  # running the review is the opt-in
    if reason:
        print(f"review: {reason}", file=sys.stderr)
        return 1
    samples = [sample(take, fault) for take, fault in pick(timed_faults(), args.n)]
    fell_back = sum(s["backend"] != muse_spark.NAME for s in samples)
    for s in samples:
        print(json.dumps(s, sort_keys=True))
    print(f"review: {len(samples)} lines, {fell_back} fell back ({fell_back / max(len(samples), 1):.0%})")
    if args.out:
        Path(args.out).write_text(json.dumps(samples, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
