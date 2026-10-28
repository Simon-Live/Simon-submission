"""Place keyframes from how a person's silhouette changes.

SAM's box only moves when an outer edge moves. A limb can travel inside that
rectangle while the box stays put. The silhouette grid catches that. A change
smaller than the error margin is the same pose: outline wobble, not a new move.
"""

import numpy as np

from keyframe_finder.schema import frame_ms

# Outline wobble, and a box that only shivers, stay under this.
ERROR_RATIO = 0.18
# A repetition must reach this share of the biggest move that person makes.
OWN_MOVE_RATIO = 0.50
# Moving this far across the frame counts as much as a completely different shape.
STEP_FRACTION = 0.12
# A pose has to sit still this long before it counts as settled.
MIN_HOLD_S = 0.50
SHAPE = 48


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


def _holds(count, fps, usable, dist):
    min_span = max(2, int(round(MIN_HOLD_S * float(fps))))
    max_gap = max(1, int(round(MIN_HOLD_S * float(fps))))
    holds = []
    index = 0
    while index < count:
        if not usable(index):
            index += 1
            continue
        last = index
        cursor = index
        while cursor + 1 < count:
            nxt = cursor + 1
            while nxt < count and not usable(nxt):
                nxt += 1
            if nxt >= count or nxt - last > max_gap:
                break
            if dist(nxt, index) >= ERROR_RATIO:
                break
            last = nxt
            cursor = nxt
        if last - index + 1 >= min_span:
            holds.append((index, last))
        index = last + 1
    return holds


def _farthest(count, start, stop, reference, usable, dist):
    """Frame that differs most from the reference.

    Once the score is maxed, the mark is the middle of that stretch, so a held
    extreme wins over the first frame that left the old pose.
    """
    scored = []
    stop = min(stop, count - 1)
    for frame in range(max(0, start), stop + 1):
        if not usable(frame):
            continue
        scored.append((frame, dist(frame, reference)))
    if not scored:
        return start, -1.0
    best = max(distance for _, distance in scored)
    peak = [frame for frame, distance in scored if distance >= best - 0.02]
    return peak[len(peak) // 2], best


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


def _motion_span(masks, centers):
    present = [index for index in range(len(masks)) if _usable(masks, centers, index)]
    if len(present) < 4:
        return 0.0
    step = max(1, len(present) // 40)
    sample = present[::step]
    span = 0.0
    for left in sample:
        for right in sample:
            if right <= left:
                continue
            span = max(span, _pose_distance(masks, centers, left, right))
    return span


def _move_threshold(span):
    """Cut off wobble, but keep a small move when it is this person's biggest one."""
    if span < ERROR_RATIO:
        return None
    return max(ERROR_RATIO, OWN_MOVE_RATIO * span)


def _drift_marks(count, usable, dist, threshold):
    present = [index for index in range(count) if usable(index)]
    if not present:
        return []
    marks = [present[0]]
    anchor = present[0]
    for frame in present[1:]:
        if dist(frame, anchor) >= threshold:
            marks.append(frame)
            anchor = frame
    return marks


def _hold_bounds(holds):
    bounds = []
    for previous, nxt in zip(holds, holds[1:]):
        bounds.append(previous[1])
        bounds.append(nxt[0])
    return sorted(set(bounds))


def _bounds_from_pairs(count, pairs, usable, dist, threshold):
    bounds = []
    for start, end in pairs:
        if end <= start or not usable(start):
            continue
        middle, distance = _farthest(count, start, end, start, usable, dist)
        if distance < threshold:
            continue
        bounds.append((start, middle, end))
    return bounds


def find_motion_bounds(masks, fps, centers=None):
    """Start, extreme, and end frames for each real move, on the whole clip.

    The move has to be a large share of the biggest change this person makes.
    A step across the frame counts even when the body shape stays the same.
    """
    masks, centers = _prepare(masks, centers, fps)
    count = len(masks)
    usable = lambda frame: _usable(masks, centers, frame)
    dist = lambda left, right: _pose_distance(masks, centers, left, right)
    threshold = _move_threshold(_motion_span(masks, centers))
    if threshold is None:
        return []
    holds = _holds(count, fps, usable, dist)
    if len(holds) >= 2:
        pairs = list(zip(_hold_bounds(holds), _hold_bounds(holds)[1:]))
        found = _bounds_from_pairs(count, pairs, usable, dist, threshold)
        if found:
            return found
    marks = _drift_marks(count, usable, dist, threshold)
    return _bounds_from_pairs(count, list(zip(marks, marks[1:])), usable, dist, threshold)


def frames_for_bounds(masks, fps, names, start, middle, end, centers=None):
    """Lay 3 or 5 pose names onto a move that was already found."""
    if len(names) not in (3, 5):
        raise ValueError("keyframe_names must list 3 or 5 phases in time order")
    masks, centers = _prepare(masks, centers, fps)
    usable = lambda frame: _usable(masks, centers, frame)
    dist = lambda left, right: _pose_distance(masks, centers, left, right)
    return _phase_frames(len(masks), names, start, middle, end, usable, dist)


def find_mask_repetitions(masks, fps, names, centers=None):
    """One repetition runs from one pose to the next settled pose.

    The start mark is the pose being left. The middle mark is the frame that
    differs most. The end mark is where the shape settles. Five names add the
    halfway points on the way out and the way back.
    """
    if len(names) not in (3, 5):
        raise ValueError("keyframe_names must list 3 or 5 phases in time order")
    repetitions = []
    for start, middle, end in find_motion_bounds(masks, fps, centers):
        frames = frames_for_bounds(masks, fps, names, start, middle, end, centers)
        repetitions.append(_pack(names, frames, fps, len(repetitions) + 1))
    return repetitions
