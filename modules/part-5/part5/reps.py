"""Repetition segmentation: cut a clip into the cycles of its main movement (ADR-0010).

A real exercise clip holds several repetitions, and a trainer's reps are not the follower's reps
(three at 3.5 s against eight at 1.3 s). Aligning whole clips fails on the repetition count, so the
pipeline compares one repetition at a time. `segment` finds the cut points of a clip from its own
measures:

1. pick the measure with the largest robust range (p95 minus p5), or the one a reference clip used
   (`prefer`) when the clip moves it enough;
2. fill gaps, smooth with a moving average of `SMOOTH_S`;
3. find the turning points with a zigzag filter: a turn counts when the signal has moved at least
   `MIN_PROMINENCE` of the range away from the last extreme (so noise and half-movements are not rep
   boundaries);
4. cut at the dips or at the peaks, whichever gives more cycles (a tie goes to the dips: a rep
   starts and ends in the rest pose), at the first frame of the extreme. Cuts closer than `MIN_REP_S`
   apart are one cut. Cutting in the middle of a rest, or at the start of the stretch near the extreme,
   was tried on the real lateral raises and made the reps disagree on phase (ADR-0010).

A clip with fewer than `MIN_CYCLES` cycles is one segment, the whole clip, so a single-rep clip is
analysed exactly as it always was. The constants were fixed from seed 5 and the documented real takes
(docs/thresholds.md "Repetitions"); the held-out seeds were not looked at.
"""
from dataclasses import dataclass

import numpy as np

from .measures import MEASURES

MIN_PROMINENCE = 0.35   # a turn needs this share of the range between it and the last extreme
MIN_REP_S = 0.6         # no repetition is shorter than this
SMOOTH_S = 0.25         # moving-average window, seconds
MIN_RANGE_DEG = 15.0    # a measure that moves less than this has no repetitions
MIN_CYCLES = 2          # fewer cycles than this: the clip is one segment
PREFER_SHARE = 0.5      # a preferred measure is used when its range is this share of the best one
DIP, PEAK = "dip", "peak"


@dataclass(frozen=True)
class Segmentation:
    """`spans` are inclusive `(start, end)` frames; a boundary frame is shared by two neighbours."""
    spans: tuple
    measure: str | None
    bound: str | None
    range_deg: float

    @property
    def reps(self):
        return len(self.spans)

    def partition(self, n_frames):
        """Disjoint inclusive `(start, end)` spans that tile frames 0..n_frames-1, one per rep (ADR-0017).

        A rep runs from its first frame to the frame before the next rep's first, the first rep from frame 0 and the
        last to the end of the clip: the lead-in before the first cut and the tail after the last belong to the
        nearest rep, so every frame is in exactly one rep. A clip of one segment is one span, the whole clip. The
        spans of `spans` share their boundary frame; these do not."""
        if self.reps < 2:
            return ((0, n_frames - 1),)
        starts = [0] + [a for a, _ in self.spans[1:]]
        return tuple((a, b) for a, b in zip(starts, [s - 1 for s in starts[1:]] + [n_frames - 1]))


def _filled(x):
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    if not ok.any():
        return None
    t = np.arange(len(x))
    return np.interp(t, t[ok], x[ok])


def _smooth(x, fps):
    k = max(3, int(round(SMOOTH_S * fps)) | 1)
    pad = k // 2
    padded = np.pad(x, pad, mode="edge")
    return np.convolve(padded, np.ones(k) / k, mode="valid")


def robust_range(x):
    """p95 minus p5 of the finite values (0 when there are none)."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return float(np.percentile(x, 95) - np.percentile(x, 5)) if len(x) else 0.0


def turning_points(s, threshold):
    """The `(frame, kind)` extremes of `s` that stand out by `threshold` from the previous extreme, in
    order and alternating. The last extreme is kept when the signal ends on it."""
    out, hi, lo = [], 0, 0
    state = None   # "up": looking for a peak after a dip; "down": looking for a dip after a peak
    for i in range(1, len(s)):
        if state is None:
            hi = i if s[i] > s[hi] else hi
            lo = i if s[i] < s[lo] else lo
            if s[i] - s[lo] >= threshold:
                out.append((lo, DIP)); state, hi = "up", i
            elif s[hi] - s[i] >= threshold:
                out.append((hi, PEAK)); state, lo = "down", i
        elif state == "up":
            hi = i if s[i] > s[hi] else hi
            if s[hi] - s[i] >= threshold:
                out.append((hi, PEAK)); state, lo = "down", i
        else:
            lo = i if s[i] < s[lo] else lo
            if s[i] - s[lo] >= threshold:
                out.append((lo, DIP)); state, hi = "up", i
    if state == "up":
        out.append((hi, PEAK))
    elif state == "down":
        out.append((lo, DIP))
    return out


def _cuts(points, kind, min_gap):
    """Frames of the `kind` extremes, dropping any closer than `min_gap` to the one before."""
    cuts = []
    for frame, k in points:
        if k == kind and (not cuts or frame - cuts[-1] >= min_gap):
            cuts.append(frame)
    return cuts


def _pick(measures, prefer):
    """The measure to cut on and its filled series: `prefer` when it moves enough, else the largest."""
    ranges = {n: robust_range(measures[n]) for n in MEASURES if n in measures}
    best = max(ranges, key=lambda n: ranges[n]) if ranges else None   # the first on a tie
    if best is None or ranges[best] < MIN_RANGE_DEG:
        return None, 0.0
    name = prefer if prefer in ranges and ranges[prefer] >= PREFER_SHARE * ranges[best] else best
    return name, ranges[name]


def whole(n_frames, measure=None, rng=0.0):
    return Segmentation(((0, n_frames - 1),), measure, None, rng)


def segment(measures, fps, prefer=None):
    """The repetitions of a clip as a `Segmentation` (`prefer` is `(measure, bound)` from a reference
    clip). One whole-clip segment when the clip has fewer than `MIN_CYCLES` cycles."""
    n = len(next(iter(measures.values())))
    name, rng = _pick(measures, prefer[0] if prefer else None)
    series = None if name is None else _filled(measures[name])
    if series is None or n < 3:
        return whole(n)
    points = turning_points(_smooth(series, fps), MIN_PROMINENCE * rng)
    gap = max(1, int(round(MIN_REP_S * fps)))
    options = {k: _cuts(points, k, gap) for k in (DIP, PEAK)}
    if prefer and name == prefer[0] and len(options[prefer[1]]) > MIN_CYCLES - 1:
        bound = prefer[1]
    else:
        bound = DIP if len(options[DIP]) >= len(options[PEAK]) else PEAK
    cuts = options[bound]
    if len(cuts) - 1 < MIN_CYCLES:
        return whole(n, name, rng)
    return Segmentation(tuple((a, b) for a, b in zip(cuts, cuts[1:])), name, bound, rng)
