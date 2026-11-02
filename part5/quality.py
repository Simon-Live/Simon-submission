"""How well the camera saw the follower's take: the `quality` block of `analysis.json` (ADR-0021, docs/specs/quality.md).

    shown_joints(*confs)                     the joints the example itself sees (its conf, `--expected-visibility`), ADR-0011's path
    read_signals(clip, shown)                the five raw readings of a follower file, and the joint that is worst for three
    assess(readings, warning_codes)          the `simon.quality.v1` block: level, reasons, signals, score_cap
    load_thresholds()                        the limits in `part5/quality.json`

Everything is read from what Part 5 already reads in the follower's file, before smoothing: the joint `conf` and Part 2's 0.3
unseen mark (ADR-0011), null joints and filled frames, the measures ADR-0011 hides, and the frame-to-frame jitter of the
positions as `feet.jitter` measures it (ADR-0015 Amendment 4). A reading that cannot be made is `None`, never 0.

A follower is not held to a body part the example does not show: `unseen_joint_share` counts only the joints the example sees in
at least half of its frames. An example whose visibility is unknown (no `conf` anywhere) counts every joint; the follower's own
set is never borrowed for it (docs/specs/quality.md, "The example's visibility").

The block is reported only. It sets no cap, no grade and no gate; `score_cap` says 59 (`score.WARNING_CAP`) when the level is
`major` and Part 7 applies it. The limits are in `part5/quality.json`, not in `part5/rules.json`, so `rules_sha256`, the detection
hash and the score `params_sha256` do not move. `low_match` is not a reason: a take of another movement is not a take the camera
saw badly. The words name what was measured and never a cause (no part gives Part 5 a light reading).

The vocabulary (codes, levels, the cap) and the validator are in `part5.output`, like every other block of the document.
"""
import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from .feet import jitter
from .io import JOINTS
from .measures import MEASURES
from .output import QUALITY_CAP, QUALITY_SIGNALS, QUALITY_VERSION, QUALITY_WARNING_CODES
from .visibility import seen_mask, usable_from_conf

THRESHOLDS_PATH = Path(__file__).with_name("quality.json")
THRESHOLDS_FORMAT = "simon.part5.quality-thresholds.v1"
OK, DEGRADED, MAJOR = "ok", "degraded", "major"
SHARE_DECIMALS, MM_DECIMALS = 4, 1
# A frame with at most this many of the 17 joints usable is lost, as a filled (`interpolated`) frame is.
LOST_FRAME_JOINTS = len(JOINTS) // 2
# The example shows a joint when it sees it (strict: a joint at 0.3 is never seen) in at least this share of its frames.
SHOWN_SHARE = 0.5
# The signal behind each reason that reads one, in the order the reasons are listed (after the warning reasons).
SIGNAL_REASONS = (("joints_unseen", "unseen_joint_share"), ("joints_missing", "missing_joint_share"),
                  ("frames_missing", "missing_frame_share"), ("measures_hidden", "hidden_measure_share"),
                  ("position_jitter", "position_jitter_mm"))
# What each warning reason says; they repeat a warning the take already carries, so they carry no number.
WARNING_WORDS = {
    "not_enough_visible": "Too little of the body was in view to compare this take with the example.",
    "moving_part_out_of_frame": "The part of the body the example moves was mostly out of frame.",
    "no_usable_measures": "Too few joints could be read to measure this take.",
}


class QualityError(ValueError):
    """`part5/quality.json` is missing, unreadable or breaks its own format; the message says where."""


@dataclass(frozen=True)
class Readings:
    """The five signals (`None` where a reading cannot be made) and, for the three that can name one, the worst joint."""
    signals: dict
    worst: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------------------------- the limits
@lru_cache(maxsize=None)
def load_thresholds(path=THRESHOLDS_PATH):
    """`{signal: (degraded, major)}` from the thresholds file; a `QualityError` naming the file when it breaks its format."""
    def fail(why):
        raise QualityError(f"{path}: {why}")

    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise QualityError(f"{path}: cannot read JSON ({e})") from e
    if not isinstance(doc, dict) or doc.get("format") != THRESHOLDS_FORMAT:
        fail(f"format must be {THRESHOLDS_FORMAT!r}")
    signals = doc.get("signals")
    if not isinstance(signals, dict) or set(signals) != set(QUALITY_SIGNALS):
        fail(f"signals must list exactly {list(QUALITY_SIGNALS)}")
    limits = {}
    for name in QUALITY_SIGNALS:
        pair = signals[name]
        low, high = (pair.get("degraded"), pair.get("major")) if isinstance(pair, dict) else (None, None)
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in (low, high)) or low >= high:
            fail(f"signals.{name} must have numbers 0 < degraded < major, got {pair!r}")
        limits[name] = (float(low), float(high))
    return limits


# ---------------------------------------------------------------------------------------------- the example's visibility
def shown_joints(*confs):
    """(17,) bool: the joints the example itself sees, in at least `SHOWN_SHARE` of its frames in every conf given (its own
    `conf` and the one of `--expected-visibility`; None is a conf that is not known). Read the way ADR-0011 reads an example,
    strict, so a joint at the 0.3 unseen mark is never shown. With no conf known the example's visibility is unknown and every joint
    counts: this fails closed, and the follower's own set is never borrowed."""
    shown = np.ones(len(JOINTS), bool)
    for conf in confs:
        if conf is not None:
            shown &= seen_mask(conf, strict=True).mean(axis=0) >= SHOWN_SHARE
    return shown


# ---------------------------------------------------------------------------------------------- the signals
def _share(flags):
    """The share of True in a boolean array, to `SHARE_DECIMALS`."""
    return round(float(np.mean(flags)), SHARE_DECIMALS)


def _worst(per_joint):
    """The joint with the largest reading, or None when every reading is zero or missing."""
    values = np.nan_to_num(np.asarray(per_joint, float), nan=-1.0)
    top = int(np.argmax(values))
    return JOINTS[top] if values[top] > 0 else None


def _unseen(clip, shown):
    """Readings at Part 2's 0.3 unseen mark, counted as ADR-0011 counts them (`visibility.seen_mask`), of the joints the example
    shows only; None without `conf` and when the example shows no joint."""
    if clip.conf is None or not shown.any():
        return None, None
    unseen = ~seen_mask(clip.conf)
    return _share(unseen[:, shown]), _worst(np.where(shown, unseen.mean(axis=0), 0.0))


def _missing(clip):
    """Readings that are null or have `conf` below 0.3 (the clip's mask), and the joint that lost most of them."""
    lost = ~clip.mask
    return _share(lost), _worst(lost.mean(axis=0))


def _lost_frames(clip):
    """Frames flagged `interpolated` (filled, not observed) or with at most half the joints usable."""
    return _share(clip.interpolated | (clip.mask.sum(axis=1) <= LOST_FRAME_JOINTS))


def _hidden_measures(clip):
    """The share of the full-body measures the follower's own `conf` makes unusable under ADR-0011; None without `conf`."""
    usable = usable_from_conf(clip.conf)
    if usable is None:
        return None
    return round(sum(m not in usable for m in MEASURES) / len(MEASURES), SHARE_DECIMALS)


def _joint_jitter_mm(series):
    """One joint's jitter: `feet.jitter` (the median absolute change between consecutive frames) of the step series on each axis,
    so a steady movement is not jitter, the three axes joined as a norm, in millimetres. NaN when an axis has too little."""
    steps = np.diff(series, axis=0)
    axes = [jitter(steps[:, k]) for k in range(steps.shape[1])]
    return math.nan if any(math.isnan(a) for a in axes) else 1000.0 * math.hypot(*axes)


def _jitter(clip):
    """The median over the joints of their jitter in millimetres per frame, and the shakiest joint; None when no joint has
    enough frames. Positions the clip does not trust (null, `conf` below 0.3) are left out, as `feet.py` leaves out a foot point."""
    seen = np.where(clip.mask[:, :, None], clip.positions, np.nan)   # ADR-0021: feet.jitter, the steadiness test of ADR-0015, per joint
    per_joint = np.array([_joint_jitter_mm(seen[:, j]) for j in range(len(JOINTS))])
    if not np.isfinite(per_joint).any():
        return None, None
    return round(float(np.nanmedian(per_joint)), MM_DECIMALS), _worst(per_joint)


def read_signals(clip, shown=None):
    """The `Readings` of a follower `io.Clip`, as the file was loaded (before smoothing). `shown` is `shown_joints(...)` of the
    example, the joints `unseen_joint_share` counts; None counts every joint."""
    shown = np.ones(len(JOINTS), bool) if shown is None else np.asarray(shown, bool)
    unseen, unseen_joint = _unseen(clip, shown)
    missing, missing_joint = _missing(clip)
    shake, shake_joint = _jitter(clip)
    signals = {"unseen_joint_share": unseen, "missing_joint_share": missing, "missing_frame_share": _lost_frames(clip),
               "hidden_measure_share": _hidden_measures(clip), "position_jitter_mm": shake}
    worst = {"unseen_joint_share": unseen_joint, "missing_joint_share": missing_joint, "position_jitter_mm": shake_joint}
    return Readings(signals, {name: joint for name, joint in worst.items() if joint})


# ---------------------------------------------------------------------------------------------- the words
def _percent(share):
    return f"{share * 100:.0f} percent"


def _joint_name(joint):
    return joint.replace("_", " ")


def _near(code, value, joint):
    """The sentence for a reason that reads a signal: the numbers and the joint, never a cause."""
    where = f", most often the {_joint_name(joint)}" if joint else ""
    if code == "joints_unseen":
        return f"{_percent(value)} of the joint readings were outside the picture{where}."
    if code == "joints_missing":
        return f"{_percent(value)} of the joint readings were missing{where}."
    if code == "frames_missing":
        return f"{_percent(value)} of the frames were filled in or had too few joints to use."
    if code == "measures_hidden":
        return (f"{round(value * len(MEASURES))} of {len(MEASURES)} measures were left out because their joints "
                "were not seen in enough of the take.")
    where = f", most at the {_joint_name(joint)}" if joint else ""
    return f"Joint positions shook by about {value:.0f} mm from one frame to the next{where}."


# ---------------------------------------------------------------------------------------------- the block
def _reached(value, limits):
    """(level, limit) of the highest limit `value` is at or above, or None when it is below both or not measured."""
    if value is None:
        return None
    degraded, major = limits
    if value >= major:
        return MAJOR, major
    return (DEGRADED, degraded) if value >= degraded else None


def _signal_reasons(readings, thresholds):
    """[(level, reason)] for every signal at or above a limit, in the order of `SIGNAL_REASONS`."""
    out = []
    for code, name in SIGNAL_REASONS:
        value = readings.signals.get(name)
        hit = _reached(value, thresholds[name])
        if hit is None:
            continue
        level, limit = hit
        joint = readings.worst.get(name)
        reason = {"code": code, "words": _near(code, value, joint), "value": value, "threshold": limit}
        out.append((level, dict(reason, joint=joint) if joint else reason))
    return out


def _warning_reasons(warning_codes):
    """[(major, reason)] for each visibility warning the take carries; `low_match` and `no_person` are not reasons."""
    return [(MAJOR, {"code": code, "words": WARNING_WORDS[code], "value": None, "threshold": None})
            for code in QUALITY_WARNING_CODES if code in warning_codes]


def assess(readings, warning_codes=(), thresholds=None):
    """The `simon.quality.v1` block for a take: its `Readings` and the codes of the warnings it carries. The level is the worst
    reason (`ok` with none); `score_cap` is 59 when it is `major`, else None. Reported only: nothing here changes a score."""
    thresholds = load_thresholds() if thresholds is None else thresholds
    # ADR-0021: reported only. Nothing below touches a score, a grade or a warning; the cap is a number for Part 7 to apply.
    found = _warning_reasons(set(warning_codes)) + _signal_reasons(readings, thresholds)
    level = MAJOR if any(l == MAJOR for l, _ in found) else DEGRADED if found else OK
    return {"version": QUALITY_VERSION, "level": level, "reasons": [reason for _, reason in found],
            "signals": dict(readings.signals), "score_cap": QUALITY_CAP if level == MAJOR else None}


def of_clip(clip, warning_codes=(), shown=None):
    """The block for a follower `io.Clip` and the warning codes of its take (none for the clip alone); `shown` as `read_signals`."""
    return assess(read_signals(clip, shown), warning_codes)
