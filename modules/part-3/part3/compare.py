"""Compare mode (spec compare-mode.md AC-M04): the agreement of 2 to 6 runs of the same movement.

`handle(body_bytes)` takes the request body of `POST api/compare`, `{"inputs": [{"label", "angles"}, ...]}`, where
`angles` is the joint-angle series a run returned (`part3.angles.joint_angles`: one row of 9 angles per frame, a
number or null). It aligns the series with the phase alignment `make check-3` uses (`metrics.dtw_samples`: every
input is warped onto input 0, the reference) and measures the spread across inputs with `metrics.spread_stats`.
The overall figure is that function on all inputs, so four takes give the number `make check-3` prints. A pair is
the same function on the two inputs' aligned samples, so every figure is read off the one shared timeline that
the page draws; a pair with the reference is exactly `spread_stats(dtw_samples([a, b]))`.

Pure: no HTTP, no files. The server calls it under its run slot and timeout.
"""

import json
import math

import numpy as np

from part3 import metrics
from part3.angles import N_ANGLES
from part3.runapi import error
from part3.schema import is_number

MIN_INPUTS = 2
MAX_INPUTS = 6
TOO_LARGE = "This compare request is over 16 MB."  # the 413 text of api/compare; the server's cap is 16 MiB
# The spec names 20,000 frames. The DTW of `part3.align` keeps a matrix of frames x frames, so 20,000 frames would
# need gigabytes and minutes; 3,000 frames (about 100 s at 30 fps) takes about 0.7 s and 220 MiB per input.
MAX_FRAMES = 3000
MAX_LABEL = 80
MAX_ANGLE = 1000.0  # degrees; a joint angle is 0 to 180, the bound only keeps sums finite
P95_DECIMALS = 3  # as `make check-3` prints it
MAP_DECIMALS = 3


class Refused(Exception):
    """The request is refused; `failure` is the (status, body) answer."""

    def __init__(self, failure):
        super().__init__(failure[1]["error"]["message"])
        self.failure = failure


def _refuse(code, message):
    raise Refused(error(code, reason=message))


def _row(k, i, row):
    if not (isinstance(row, list) and len(row) == N_ANGLES):
        _refuse("compare_shape", f"Input {k}: frame {i + 1} must be a list of {N_ANGLES} angles.")
    out = []
    for value in row:
        if value is None:
            out.append(math.nan)
        elif is_number(value) and math.isfinite(value) and abs(value) <= MAX_ANGLE:
            out.append(float(value))
        else:
            _refuse("compare_shape",
                    f"Input {k}: frame {i + 1} holds an angle that is not a number from -1000 to 1000 or null.")
    return out


def _series(k, entry):
    """The (n, 9) angle array of input number `k` (counted from 1), with NaN where the series holds null."""
    if not isinstance(entry, dict):
        _refuse("compare_shape", f"Input {k}: must be an object with a label and angles.")
    label, angles = entry.get("label"), entry.get("angles")
    if not isinstance(label, str):
        _refuse("compare_shape", f"Input {k}: label must be text.")
    if len(label) > MAX_LABEL:
        _refuse("compare_size", f"Input {k}: the label is over {MAX_LABEL} characters.")
    if not isinstance(angles, list):
        _refuse("compare_shape", f"Input {k}: angles must be a list of frames.")
    if not angles:
        _refuse("compare_shape", f"Input {k}: angles has no frames.")
    if len(angles) > MAX_FRAMES:
        _refuse("compare_size", f"Input {k}: more than {MAX_FRAMES} frames. Compare handles up to {MAX_FRAMES}.")
    return np.array([_row(k, i, row) for i, row in enumerate(angles)], dtype=float)


def _parse(raw):
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        doc = None
    if not (isinstance(doc, dict) and isinstance(doc.get("inputs"), list)):
        _refuse("compare_shape", 'The compare request must be a JSON object with an "inputs" list.')
    if not MIN_INPUTS <= len(doc["inputs"]) <= MAX_INPUTS:
        _refuse("compare_count", f"Compare needs {MIN_INPUTS} to {MAX_INPUTS} inputs.")
    return [_series(k, entry) for k, entry in enumerate(doc["inputs"], start=1)]


def _p95(samples):
    """(p95 in degrees or None, pass) of the spread across `samples`, as the done-check measures it."""
    stats = metrics.spread_stats(samples)
    if stats is None:
        return None, False
    p95 = round(stats["p95"], P95_DECIMALS) + 0.0
    return p95, stats["p95"] <= metrics.AGREEMENT_MAX_DEG


def _agreement(series):
    samples, maps = metrics.dtw_samples(series)
    p95, ok = _p95(samples)
    pairs = []
    for a in range(len(series)):
        for b in range(a + 1, len(series)):
            pair_p95, pair_ok = _p95([samples[a], samples[b]])
            pairs.append({"a": a, "b": b, "p95_deg": pair_p95, "pass": pair_ok})
    return ({"p95_deg": p95, "pass": ok, "per_pair": pairs},
            {"reference": 0, "maps": [np.round(m, MAP_DECIMALS).tolist() for m in maps]})


def handle(body):
    """(HTTP status, JSON dict) for POST api/compare with the raw request `body`."""
    try:
        series = _parse(body)
    except Refused as refused:
        return refused.failure
    agreement, alignment = _agreement(series)
    return 200, {"ok": True, "agreement": agreement, "alignment": alignment}
