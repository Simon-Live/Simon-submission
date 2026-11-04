"""Persistence: does a deviation hold long enough, in a rep of the example, to be a fault (ADR-0017).

Split out of `detect.py` (pre-freeze review R1, docs/specs/rep-persistence.md Files). Deliberate faults are held
through a good part of the movement, possibly in several stretches; noise comes in short runs. For one measure, side and
direction, `judge` takes the frames past the threshold and says which runs persist:

- a run counts from `min_run_frames` (its own length: a run is never cut at a rep boundary) and belongs to the rep that
  holds most of its frames (the earlier rep on a tie);
- a rep persists when the counted runs that belong to it sum to what it needs (`needed`): an explicit `min_frames`,
  else `min_fraction` of the rep floored by the measure's floor;
- the floor is a duration, written as frames at `reference_fps` (32 frames at 30 is 1.07 s), and a frame count at the
  example's own rate (`floor_frames`). It never asks for more than `floor_share` of the rep, so a rep shorter than the
  floor (a short rep, or a slow frame rate) can still persist (pre-freeze review B1). `reference_fps` and `floor_share`
  are `rules.json` `default` keys (residual 5), so they are inside `detection_sha256` with the floors;
- the floor splits by measure class (recheck N2, stakeholder-proxy): the foot measures (`measures.FOOT_MEASURES`) read
  `min_frames_floor`, every body measure reads `min_frames_floor_body`, both of the same form;
- without spans, or with one, the clip is one rep and this is the rule the whole clip has always had.
"""
from dataclasses import dataclass

DEFAULT_MIN_RUN_FRAMES = 4
FOOT_FLOOR_KEY = "min_frames_floor"         # the floor of the foot measures
BODY_FLOOR_KEY = "min_frames_floor_body"    # the floor of every other measure
FLOOR_KEYS = (FOOT_FLOOR_KEY, BODY_FLOOR_KEY)


@dataclass
class Persistence:
    """What persistence made of the frames past a threshold (`judge`).

    `kept` is the runs that persist: the counted runs of every rep whose counted frames reach what it needs. A clip
    without reps is one rep. `counted_frames` and `needed_frames` are those of the rep that came closest to persisting,
    `span` that rep's frames, so the pair says how far a dropped candidate fell short and `longest` names the run in it."""
    runs: list              # every run past the threshold, inclusive frames
    counted: list           # those of at least min_run_frames
    kept: list              # the counted runs of the reps that persist; [] when none does
    counted_frames: int
    needed_frames: int
    min_run: int
    span: tuple             # the inclusive frames of the rep that came closest to persisting

    def longest(self):
        """The run a candidate points at: the longest of the runs that persist (the earliest on a tie) or, when none
        does, the longest run inside the rep that came closest (by its frames in that rep), which is the rep the
        counted and needed frames describe."""
        if self.kept:
            return max(self.kept, key=lambda r: r[1] - r[0])
        a, b = self.span
        return max((r for r in self.runs if r[0] <= b and r[1] >= a), key=lambda r: min(r[1], b) - max(r[0], a))


def runs_of(flags):
    """Maximal runs of True in `flags` as inclusive (start, end) frame pairs."""
    out, start = [], None
    for i, f in enumerate(list(flags) + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append((start, i - 1))
            start = None
    return out


def floor_frames(cfg, length, fps=None, foot=False):
    """The floor of a measure (`foot`: a foot measure's `min_frames_floor`, else `min_frames_floor_body`) as a count of
    frames of a rep of `length` frames at `fps` (None: the reference rate, so the key is a count of frames): the duration
    it names in the example's own frame rate, at most `floor_share` of the rep. Both constants are `cfg`'s."""
    reference = cfg["reference_fps"]
    return min(int(round(cfg[FOOT_FLOOR_KEY if foot else BODY_FLOOR_KEY] * (fps or reference) / reference)),
               int(round(cfg["floor_share"] * length)))


def needed(cfg, length, fps=None, foot=False):
    """The frames a fault must hold in a rep of `length` frames: an explicit `min_frames` (a count of frames), else
    `min_fraction` of the rep, floored by `floor_frames` (and by 1 frame, so a config with no floor still needs one)."""
    return cfg.get("min_frames") or max(1, floor_frames(cfg, length, fps, foot), int(round(cfg["min_fraction"] * length)))


def owner(run, spans):
    """The index of the rep that holds most of `run` (the earlier one on a tie)."""
    share = [max(0, min(run[1], b) - max(run[0], a) + 1) for a, b in spans]
    return share.index(max(share))


def judge(flags, cfg, n, spans=None, fps=None, foot=False):
    """The `Persistence` of the frames past a threshold in a clip of `n` frames, judged rep by rep (ADR-0017). `spans`
    is the clip's reps as disjoint inclusive frame spans (`reps.Segmentation.partition`); `fps` is the example's frame
    rate, which turns the floor into frames; `foot` says the measure is a foot measure (its floor is the foot floor). A
    deviation that fills most of one rep is a fault even when the take has many reps and the deviation is a small share
    of all of it."""
    min_run = cfg.get("min_run_frames", DEFAULT_MIN_RUN_FRAMES)
    runs = runs_of(flags)
    counted = [(s, e) for s, e in runs if e - s + 1 >= min_run]
    spans = spans or ((0, n - 1),)
    owners = [owner(run, spans) for run in counted] if len(spans) > 1 else [0] * len(counted)
    kept, best = [], None
    for j, (a, b) in enumerate(spans):
        mine = [run for run, who in zip(counted, owners) if who == j]
        frames, need = sum(e - s + 1 for s, e in mine), needed(cfg, b - a + 1, fps, foot)
        if frames and frames >= need:
            kept += mine
        longest = max((min(e, b) - max(s, a) + 1 for s, e in runs), default=0)   # the closest rep when none counted
        closeness = (frames / need, longest)
        if best is None or closeness > best[0]:
            best = closeness, frames, need, (a, b)
    return Persistence(runs, counted, kept, best[1], best[2], min_run, best[3])
