"""`--fps <n>`: a uniform time grid over the rebuilt frames (spec integration-contract.md "Resampling").

Output frame `i` sits at `t0 + i * 1000 / n` ms on the input clock. Its two bracketing input frames
`fa` and `fb` give a joint-wise linear blend that is rebuilt on the profile's fixed bone lengths, so
bone lengths stay fixed. A frame whose brackets do not both hold the person is empty: nothing is
blended across a gap. `conf` of a blended joint is the lower of the two brackets; the label groups
repaired are the union of the two brackets'.
"""

import math

import numpy as np

from part3 import bones, io
from part3.joints import GROUP_ORDER, JOINTS
from part3.schema import ContractError, OptionError

FPS_MIN, FPS_MAX = 1, 240
MAX_FRAMES = 100_000  # review B1: the grid grows with the clip's time span, so the upload size bounds nothing
METHOD = "linear blend then fixed-length rebuild"
T_DECIMALS = 3
WEIGHT_DECIMALS = 6
EXACT = 1e-9
HALF_STEP_MS = 0.5 * 10 ** -T_DECIMALS  # input times are written to 3 decimals: a grid point that rounds onto the last one counts


def check_fps(value):
    """`value` (a number or numeric text) as an int when whole else a float in 1 to 240, else ContractError."""
    try:
        number = math.nan if isinstance(value, bool) else float(value)
    except (TypeError, ValueError):
        number = math.nan
    if not FPS_MIN <= number <= FPS_MAX:
        raise ContractError("--fps", f"must be {FPS_MIN} to {FPS_MAX} (got {value})")
    return int(number) if number == int(number) else number


def shown(count):
    """A frame count for a message: the whole number, else three significant digits (a 1e300 ms clip is 3e+298)."""
    return str(count) if count < 10 ** 15 else f"{count:.3g}"


def cap_for(max_frames):
    """The frame limit in force: `max_frames`, else `MAX_FRAMES`."""
    return MAX_FRAMES if max_frames is None else max_frames


def _check_times(times):
    steps = np.flatnonzero(times[1:] <= times[:-1])  # compared, not subtracted: huge t_ms must not overflow
    if len(steps):
        raise ContractError(f"pose3d.frames[{steps[0] + 1}].t_ms", "must increase for --fps")


def grid_count(first_ms, last_ms, fps, max_frames=None):
    """Frames on the `fps` grid from `first_ms` to `last_ms`; OptionError over the cap or for a span that overflows.

    `max_frames` None means `MAX_FRAMES`. Plain floats on purpose: a span past the float range is `inf`
    here and a message, never a numpy warning or an array too large to allocate.
    """
    cap = cap_for(max_frames)
    scaled = (float(last_ms) - float(first_ms) + HALF_STEP_MS) * fps / 1000.0
    if not math.isfinite(scaled):
        raise OptionError(f"--fps {fps}", f"would write more frames than the limit of {cap}: "
                                          "the clip span (first to last t_ms) is not finite")
    count = math.floor(scaled) + 1
    if count > cap:
        raise OptionError(f"--fps {fps}", f"would write {shown(count)} frames; the limit is {cap}")
    return count


def check_grid(times, fps, max_frames=None):
    """The `grid_count` of the input frame times `times` after checking they increase (the cheap early test)."""
    times = np.asarray(times, dtype=float)
    _check_times(times)
    return grid_count(times[0], times[-1], fps, max_frames)


def _brackets(times, grid):
    """(fa, fb, weight) arrays: input positions around each grid time and the share of fb (6 decimals)."""
    clipped = np.clip(grid, times[0], times[-1])
    fa = np.clip(np.searchsorted(times, clipped + EXACT, side="right") - 1, 0, len(times) - 1)
    fb = np.minimum(fa + 1, len(times) - 1)
    span = times[fb] - times[fa]
    weight = np.round(np.divide(clipped - times[fa], span, out=np.zeros_like(clipped), where=span > 0),
                      WEIGHT_DECIMALS)
    whole = weight >= 1.0 - EXACT
    fa = np.where(whole, fb, fa)
    weight = np.where(whole | (weight <= EXACT), 0.0, weight)
    fb = np.where(weight == 0.0, fa, fb)
    return fa, fb, weight


def _union(a, b):
    return [group for group in GROUP_ORDER if group in a or group in b]


def resample(times, frame_ids, indices, coords, conf, repaired, lengths, fps, max_frames=None):
    """The rebuilt person on the `fps` grid.

    `times` are the input frames' t_ms, `frame_ids` their `frame` numbers; `indices`, `coords` (m, 17,
    3), `conf` (m, 17) and `repaired` (m lists) describe the m input frames holding the person, and
    `lengths` is the (18,) array of bone lengths. Returns (slots, coords, conf, repaired) where each
    slot is (frame number, t_ms, row in the returned arrays or None, source block) for every grid
    frame, and the arrays hold the grid frames that hold the person. Raises ContractError before any
    allocation when the grid would hold more than `max_frames` frames (None: `MAX_FRAMES`).
    """
    times = np.asarray(times, dtype=float)
    count = check_grid(times, fps, max_frames)
    grid = np.round(times[0] + np.arange(count) * 1000.0 / fps, T_DECIMALS)
    fa, fb, weight = _brackets(times, grid)
    row_of = {int(i): k for k, i in enumerate(indices)}
    full = np.zeros((len(times), len(JOINTS), 3))
    full[list(row_of)] = coords
    keep = np.array([i for i in range(count) if int(fa[i]) in row_of and int(fb[i]) in row_of], dtype=int)
    w = weight[keep][:, None, None]
    blend = (1.0 - w) * full[fa[keep]] + w * full[fb[keep]]
    rebuilt = io.round_clean(bones.retarget(blend, lengths), io.OUTPUT_DECIMALS)
    rows = {i: k for k, i in enumerate(keep)}
    ka = np.array([row_of[int(fa[i])] for i in keep], dtype=int)
    kb = np.array([row_of[int(fb[i])] for i in keep], dtype=int)
    slots = [(i, float(grid[i]), rows.get(i),
              {"frames": [int(frame_ids[fa[i]]), int(frame_ids[fb[i]])], "weight": float(weight[i])})
             for i in range(count)]
    merged_conf = np.minimum(np.asarray(conf)[ka], np.asarray(conf)[kb]).reshape(-1, len(JOINTS))
    return slots, rebuilt, merged_conf, [_union(repaired[a], repaired[b]) for a, b in zip(ka, kb)]


def block(fps, source_frames):
    """The top-level `resample` block of a skeleton."""
    return {"fps": fps, "source_frames": source_frames, "method": METHOD}
