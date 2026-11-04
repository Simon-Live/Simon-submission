"""Turn a person's vertical motion into per-rep key frames.

The movement spec names the phases and says whether the middle phase is the
body's lowest or highest point. Times come from the video, not from the spec.
"""

import numpy as np

from keyframe_finder.schema import frame_ms

# A half-depth bounce is a hesitation, not another repetition.
MIN_HEIGHT_RATIO = 0.50
MIN_PROMINENCE_RATIO = 0.40
# Plateau edges sit where the pose has left the held extreme.
PLATEAU_RATIO = 0.08


def _odd_window(fps):
    win = int(round(float(fps) / 8.0))
    if win % 2 == 0:
        win += 1
    return max(3, win)


def smooth(series, win):
    series = np.asarray(series, dtype=np.float64)
    if win < 3:
        return series.copy()
    pad = win // 2
    padded = np.pad(series, pad, mode="edge")
    kernel = np.ones(win, dtype=np.float64) / win
    return np.convolve(padded, kernel, mode="valid")


def orient(series, extremum):
    series = np.asarray(series, dtype=np.float64)
    if extremum == "max_centroid_y":
        return series
    if extremum == "min_centroid_y":
        return -series
    raise ValueError(f"unknown extremum {extremum!r}")


def local_maxima(series):
    peaks = []
    for index in range(1, len(series) - 1):
        if series[index] >= series[index - 1] and series[index] > series[index + 1]:
            peaks.append(index)
    return peaks


def prominence(series, index):
    left = series[index]
    cursor = index
    while cursor > 0:
        cursor -= 1
        if series[cursor] > series[index]:
            break
        if series[cursor] < left:
            left = series[cursor]
    right = series[index]
    cursor = index
    last = len(series) - 1
    while cursor < last:
        cursor += 1
        if series[cursor] > series[index]:
            break
        if series[cursor] < right:
            right = series[cursor]
    return float(series[index] - max(left, right))


def select_peaks(series, fps):
    low = float(np.min(series))
    high = float(np.max(series))
    span = high - low
    if span <= 1e-6:
        return []
    min_height = low + MIN_HEIGHT_RATIO * span
    min_prominence = MIN_PROMINENCE_RATIO * span
    min_distance = max(3, int(round(0.45 * float(fps))))
    ranked = []
    for index in local_maxima(series):
        if series[index] < min_height:
            continue
        score = prominence(series, index)
        if score < min_prominence:
            continue
        ranked.append((score, index))
    ranked.sort(reverse=True)
    kept = []
    for _, index in ranked:
        if all(abs(index - other) >= min_distance for other in kept):
            kept.append(index)
    kept.sort()
    return kept


def snap(series, seed, radius, mode):
    start = max(0, seed - radius)
    stop = min(len(series) - 1, seed + radius)
    segment = series[start : stop + 1]
    offset = int(np.argmax(segment) if mode == "max" else np.argmin(segment))
    return start + offset


def plateau_center(series, seed, mode, tolerance):
    level = float(series[seed])
    start = stop = seed
    last = len(series) - 1
    if mode == "max":
        while start > 0 and series[start - 1] >= level - tolerance:
            start -= 1
        while stop < last and series[stop + 1] >= level - tolerance:
            stop += 1
    else:
        while start > 0 and series[start - 1] <= level + tolerance:
            start -= 1
        while stop < last and series[stop + 1] <= level + tolerance:
            stop += 1
    return (start + stop) // 2


def adjacent_valley(series, peak, direction, tolerance):
    cursor = peak
    best = float(series[peak])
    best_at = peak
    last = len(series) - 1
    while True:
        nxt = cursor + direction
        if nxt < 0 or nxt > last:
            break
        if series[nxt] > best + tolerance and series[nxt] > series[cursor]:
            break
        cursor = nxt
        if series[cursor] < best:
            best = float(series[cursor])
            best_at = cursor
    return plateau_center(series, best_at, "min", tolerance)


def steepest_frame(series, start, stop, sign):
    start = int(start)
    stop = int(stop)
    if stop < start:
        start, stop = stop, start
    if stop <= start:
        return start
    slopes = np.diff(series[start : stop + 1])
    offset = int(np.argmax(slopes) if sign > 0 else np.argmin(slopes))
    return start + offset + 1


def find_repetitions(series, fps, names, extremum):
    if len(names) not in (3, 5):
        raise ValueError("keyframe_names must list 3 or 5 phases in time order")
    work = smooth(orient(series, extremum), _odd_window(fps))
    span = float(np.max(work) - np.min(work))
    tolerance = PLATEAU_RATIO * span
    radius = max(3, int(round(0.6 * float(fps))))
    repetitions = []
    for rep_number, peak in enumerate(select_peaks(work, fps), start=1):
        bottom = plateau_center(work, snap(work, peak, radius, "max"), "max", tolerance)
        start = adjacent_valley(work, bottom, -1, tolerance)
        end = adjacent_valley(work, bottom, 1, tolerance)
        if len(names) == 3:
            frames = [start, bottom, end]
        else:
            frames = [
                start,
                steepest_frame(work, start + 1, bottom - 1, 1),
                bottom,
                steepest_frame(work, bottom + 1, end - 1, -1),
                end,
            ]
        repetitions.append(
            {
                "rep": rep_number,
                "keyframes": [
                    {"name": name, "frame": int(frame), "t_ms": frame_ms(frame, fps)}
                    for name, frame in zip(names, frames)
                ],
            }
        )
    return repetitions
