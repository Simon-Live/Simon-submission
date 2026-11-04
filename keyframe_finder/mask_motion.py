"""Place keyframes from how a person's silhouette changes.

SAM's box only moves when an outer edge moves. A limb can travel inside that
rectangle while the box stays put. The silhouette grid catches that. A change
smaller than the error margin is the same pose: outline wobble, not a new move.

Each person's frames are reduced to one movement signal: the direction in which
their silhouette changes most over the clip. 0 is the pose they start in, 1 is
the far pose. A repetition leaves the start pose, reaches the far pose, and
comes back.
"""

import numpy as np

from keyframe_finder.schema import frame_ms

# Outline wobble, and a box that only shivers, stay under this.
ERROR_RATIO = 0.18
# Moving this far across the frame counts as much as a completely different shape.
STEP_FRACTION = 0.12
# Once a steady drift is taken out, position that varies less than this share of the frame is standing still.
STILL_FRACTION = 0.02
# A pose has to sit still this long before it counts as settled.
MIN_HOLD_S = 0.50
SHAPE = 48
# The silhouette is compared on a coarser grid, so a ragged edge is not a move.
CELL = 4
# A repetition goes past REACH on the way out and back under RETURN.
# The gap between them keeps a wobble at the halfway mark from counting twice.
REACH = 0.60
RETURN = 0.40
# A pose is settled while it stays within this share of the full move.
SETTLE = 0.10
# Signal range, ignoring the most extreme 2% at each end.
RANGE_PERCENTILE = 2.0


def silhouette(raster, height, width):
    """Resize a decoded mask into a fixed grid. Position in the frame is ignored.

    The grid is the person's shape, so the same pose in a new spot still matches,
    and a pose change inside a fixed box does not.
    """
    if height <= 0 or width <= 0:
        return None
    flat = np.frombuffer(raster, dtype=np.uint8)
    if flat.size != height * width:
        return None
    image = flat.reshape(height, width) > 0
    if not image.any():
        return None
    grid = np.zeros((SHAPE, SHAPE), dtype=bool)
    rows, cols = np.nonzero(image)
    gy = np.minimum(rows * SHAPE // height, SHAPE - 1)
    gx = np.minimum(cols * SHAPE // width, SHAPE - 1)
    grid[gy, gx] = True
    return grid


def keep_aspect(grid, box_width, box_height):
    """Put the silhouette back in its box's proportions, feet on the bottom row.

    The stored grid is stretched to a square, so a person bent over and the same
    person standing can fill it alike. Their box width against height still differs.
    """
    if grid is None or box_width <= 0 or box_height <= 0:
        return None
    aspect = float(box_width) / float(box_height)
    if aspect <= 1.0:
        rows, cols = SHAPE, max(1, int(round(SHAPE * aspect)))
    else:
        rows, cols = max(1, int(round(SHAPE / aspect))), SHAPE
    row_index = np.minimum(np.arange(rows) * SHAPE // rows, SHAPE - 1)
    col_index = np.minimum(np.arange(cols) * SHAPE // cols, SHAPE - 1)
    placed = np.zeros((SHAPE, SHAPE), dtype=bool)
    left = (SHAPE - cols) // 2
    placed[SHAPE - rows :, left : left + cols] = np.asarray(grid, dtype=bool)[np.ix_(row_index, col_index)]
    return placed


def mask_distance(left, right):
    """Share of the two silhouettes that does not overlap. 0 is the same shape."""
    if left is None or right is None:
        return 1.0
    union = int(np.count_nonzero(np.logical_or(left, right)))
    if union == 0:
        return 0.0
    changed = int(np.count_nonzero(left != right))
    return changed / union


def _pose_distance(masks, centers, left, right):
    """How much the pose changed. A real step counts even when the shape matches."""
    shape = 0.0
    if masks[left] is not None and masks[right] is not None:
        shape = mask_distance(masks[left], masks[right])
    moved = 0.0
    if centers is not None and centers[left] is not None and centers[right] is not None:
        dx = centers[left][0] - centers[right][0]
        dy = centers[left][1] - centers[right][1]
        moved = min(1.0, ((dx * dx) + (dy * dy)) ** 0.5 / STEP_FRACTION)
    return max(shape, moved)


def _usable(masks, centers, frame):
    if masks[frame] is not None:
        return True
    return centers is not None and centers[frame] is not None


def _closest(count, start, stop, reference, target, usable, dist):
    best = start
    best_error = None
    stop = min(stop, count - 1)
    for frame in range(max(0, start), stop + 1):
        if not usable(frame):
            continue
        error = abs(dist(frame, reference) - target)
        if best_error is None or error < best_error:
            best = frame
            best_error = error
    return best


def _increasing(frames, last):
    ordered = []
    for frame in frames:
        if ordered and frame <= ordered[-1]:
            frame = ordered[-1] + 1
        ordered.append(frame)
    for index in range(len(ordered) - 2, -1, -1):
        if ordered[index] >= ordered[index + 1]:
            ordered[index] = ordered[index + 1] - 1
    if ordered:
        ordered[0] = max(0, ordered[0])
        ordered[-1] = min(last, ordered[-1])
    return ordered


def _phase_frames(count, names, start, middle, end, usable, dist):
    start, middle, end = sorted((int(start), int(middle), int(end)))
    if len(names) == 3:
        chosen = [start, middle, end]
    else:
        peak = dist(middle, start)
        half = peak / 2.0
        chosen = [
            start,
            _closest(count, start, middle, start, half, usable, dist),
            middle,
            _closest(count, middle, end, start, half, usable, dist),
            end,
        ]
    return _increasing(chosen, count - 1)


def _pack(names, frames, fps, rep_number):
    return {
        "rep": rep_number,
        "keyframes": [
            {"name": name, "frame": int(frame), "t_ms": frame_ms(frame, fps)}
            for name, frame in zip(names, frames)
        ],
    }


def _smooth(masks, fps):
    """Average the silhouette over the hold window so outline wobble is not a move."""
    win = _window(fps)
    blank = np.zeros((SHAPE, SHAPE), dtype=np.float32)
    stack = np.stack(
        [blank if mask is None else np.asarray(mask, dtype=np.float32) for mask in masks]
    )
    pad = win // 2
    padded = np.pad(stack, ((pad, pad), (0, 0), (0, 0)), mode="edge")
    total = np.zeros_like(stack)
    for offset in range(win):
        total += padded[offset : offset + len(masks)]
    average = total / win
    smoothed = []
    for index, mask in enumerate(masks):
        if mask is None:
            smoothed.append(None)
        else:
            smoothed.append(average[index] >= 0.5)
    return smoothed


def _window(fps):
    win = int(round(MIN_HOLD_S * float(fps)))
    if win % 2 == 0:
        win += 1
    return max(3, win)


def _smooth_centers(centers, fps):
    if centers is None:
        return None
    win = _window(fps)
    half = win // 2
    smoothed = []
    for index, center in enumerate(centers):
        if center is None:
            smoothed.append(None)
            continue
        xs = []
        ys = []
        stop = min(len(centers), index + half + 1)
        for cursor in range(max(0, index - half), stop):
            if centers[cursor] is None:
                continue
            xs.append(centers[cursor][0])
            ys.append(centers[cursor][1])
        if not xs:
            smoothed.append(None)
        else:
            smoothed.append((float(np.mean(xs)), float(np.mean(ys))))
    return smoothed


def _prepare(masks, centers, fps):
    return _smooth(masks, fps), _smooth_centers(centers, fps)


def _fill_columns(rows):
    """Carry each feature across frames that lack it."""
    index = np.arange(rows.shape[0])
    for column in range(rows.shape[1]):
        good = ~np.isnan(rows[:, column])
        if not good.any():
            rows[:, column] = 0.0
        elif not good.all():
            rows[:, column] = np.interp(index, index[good], rows[good, column])
    return rows


def _features(masks, centers, present):
    """One row per frame: the coarse silhouette, then the position in the frame."""
    side = SHAPE // CELL
    shape = np.full((len(present), side * side), np.nan)
    for row, frame in enumerate(present):
        if masks[frame] is not None:
            coarse = np.asarray(masks[frame], dtype=np.float64).reshape(side, CELL, side, CELL)
            shape[row] = coarse.mean(axis=(1, 3)).ravel()
    shape = _fill_columns(shape)
    if centers is None:
        return shape
    place = np.full((len(present), 2), np.nan)
    for row, frame in enumerate(present):
        if centers[frame] is not None:
            place[row] = centers[frame]
    place = _drift_removed(_fill_columns(place), present)
    size = float(np.median(np.linalg.norm(shape, axis=1)))
    weight = (size if size > 0 else 1.0) / STEP_FRACTION
    return np.hstack([shape, place * weight])


def _drift_removed(place, present):
    """The position without its straight-line trend over the clip.

    A trainer who drifts sideways while doing knee lifts moved 18% of the frame one way (TICKET-380). Weighed as a
    step, that drift was the person's biggest change, the signal followed it, and no repetition was found. A step
    out and back has no trend, so it is kept as it was; only a steady drift is taken out.
    """
    if place.shape[0] < 3:
        return place
    t = np.asarray(present, dtype=np.float64)
    t = t - t.mean()
    spread = float(np.dot(t, t))
    if spread <= 0:
        return place
    slope = (t @ (place - place.mean(axis=0))) / spread
    left = place - np.outer(t, slope)
    if float(np.max(np.abs(left - left.mean(axis=0)))) < STILL_FRACTION:
        return np.broadcast_to(left.mean(axis=0), left.shape).copy()   # only drift and rounding were left
    return left


def _movement_signal(masks, centers, present, fps):
    """0 at the starting pose, 1 at the far pose, along the person's biggest change."""
    rows = _features(masks, centers, present)
    rows = rows - rows.mean(axis=0)
    if not np.any(rows):
        return None
    _, _, axes = np.linalg.svd(rows, full_matrices=False)
    signal = rows @ axes[0]
    low = float(np.percentile(signal, RANGE_PERCENTILE))
    high = float(np.percentile(signal, 100.0 - RANGE_PERCENTILE))
    if high - low <= 1e-9:
        return None
    signal = np.clip((signal - low) / (high - low), 0.0, 1.0)
    head = max(_window(fps), len(signal) // 5)
    if float(np.median(signal[:head])) > 0.5:
        signal = 1.0 - signal
    return signal


def _excursions(signal):
    """Stretches that go past REACH and later fall back under RETURN.

    The last one has no return when the clip ends on the far pose.
    """
    found = []
    began = None
    been_low = False
    for index, value in enumerate(signal):
        if began is None:
            if value <= RETURN:
                been_low = True
            elif value >= REACH and been_low:
                began = index
        elif value <= RETURN:
            found.append((began, index))
            began = None
    if began is not None:
        found.append((began, None))
    return found


def _peak_middle(signal, start, stop):
    """Middle of the stretch spent at the far pose."""
    peak = start + int(np.argmax(signal[start:stop]))
    level = float(signal[peak]) - SETTLE
    first = peak
    while first > start and signal[first - 1] >= level:
        first -= 1
    last = peak
    while last + 1 < stop and signal[last + 1] >= level:
        last += 1
    return (first + last) // 2, first, last


def _rep_bounds(signal, fps):
    """Start, far, and end positions in the signal for each repetition."""
    outs = _excursions(signal)
    bounds = []
    hold = max(2, int(round(MIN_HOLD_S * float(fps))))
    for number, (began, back) in enumerate(outs):
        before = outs[number - 1][1] if number else 0
        floor = float(np.min(signal[before : began + 1]))
        start = began
        while start > before and signal[start] > floor + SETTLE:
            start -= 1
        if back is None:
            middle, first, last = _peak_middle(signal, began, len(signal))
            if last - first + 1 < hold or last != len(signal) - 1:
                continue
            bounds.append((start, middle, len(signal) - 1))
            continue
        after = outs[number + 1][0] if number + 1 < len(outs) else len(signal)
        floor = float(np.min(signal[back:after]))
        end = back
        while end + 1 < after and signal[end] > floor + SETTLE:
            end += 1
        middle, _, _ = _peak_middle(signal, began, back)
        bounds.append((start, middle, end))
    return bounds


def find_motion_bounds(masks, fps, centers=None):
    """Start, far, and end frames for each repetition, on the whole clip.

    The start is where the person leaves the pose they began in. The far frame
    is the middle of the time spent at the other extreme. The end is where they
    are back. A repetition cut off by the end of the clip still counts once the
    far pose has been held. The far pose has to differ from the start pose by
    more than outline wobble.
    """
    masks, centers = _prepare(masks, centers, fps)
    present = [frame for frame in range(len(masks)) if _usable(masks, centers, frame)]
    if len(present) < 4:
        return []
    signal = _movement_signal(masks, centers, present, fps)
    if signal is None:
        return []
    low = present[int(np.argmin(signal))]
    high = present[int(np.argmax(signal))]
    if _pose_distance(masks, centers, low, high) < ERROR_RATIO:
        return []
    return [
        (present[start], present[middle], present[end])
        for start, middle, end in _rep_bounds(signal, fps)
    ]


def frames_for_bounds(masks, fps, names, start, middle, end, centers=None):
    """Lay 3 or 5 pose names onto a move that was already found."""
    if len(names) not in (3, 5):
        raise ValueError("keyframe_names must list 3 or 5 phases in time order")
    masks, centers = _prepare(masks, centers, fps)
    usable = lambda frame: _usable(masks, centers, frame)
    dist = lambda left, right: _pose_distance(masks, centers, left, right)
    return _phase_frames(len(masks), names, start, middle, end, usable, dist)


def find_mask_repetitions(masks, fps, names, centers=None):
    """One repetition leaves the start pose, reaches the far pose, and comes back.

    The start mark is where the start pose is left. The middle mark is the middle
    of the time at the far pose. The end mark is where the start pose is reached
    again. Five names add the halfway points on the way out and the way back.
    """
    if len(names) not in (3, 5):
        raise ValueError("keyframe_names must list 3 or 5 phases in time order")
    repetitions = []
    for start, middle, end in find_motion_bounds(masks, fps, centers):
        frames = frames_for_bounds(masks, fps, names, start, middle, end, centers)
        repetitions.append(_pack(names, frames, fps, len(repetitions) + 1))
    return repetitions
