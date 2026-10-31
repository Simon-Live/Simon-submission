"""Foot points from Part 2's pose3d.json, an optional side input (TICKET-040, docs/specs/foot-keypoints.md).

The 17 COCO joints end at the ankle, so a clip cannot say which way a foot points or whether an ankle rolls. Part 2
publishes six more points per person (`extra_joints`: heel, big toe and small toe of each foot) in the same
`pose3d.json` as the 17, and its contract says Part 3 does not carry them. Part 5 therefore reads them from that
file directly, one per clip (`--expected-feet`, `--follower-feet`), and never touches the clips themselves.

- The four foot measures (`left_foot_rotation`, `right_foot_rotation`, `left_ankle_inversion`,
  `right_ankle_inversion`) are computed per side-file frame, inside the side file's own frame, from its own hips
  and foot points (`measures.compute_feet`). No other joint is read: the knee and ankle are ignored, so a bad value
  there is not an error.
- A point is seen when it is present, finite and its `conf` is at least `FOOT_MIN_CONF`; a measure is NaN in a frame
  where any point it reads is not seen. If the file says `mirrored`, the left and right series are swapped.
- Each clip frame takes the side frame nearest in time (the file's `(t_ms - t0_pts_ms) / 1000` against the clip's own
  `t`, both seconds from the start of the same video) within half the file's median frame step, taken over every
  frame of the file (not only the frames where the person is present), at least `MIN_MATCH_S`; otherwise NaN.
- A measure is usable in a clip when it is a number in at least `MIN_SEEN_SHARE` of the clip's frames, and the pair
  is compared on the measures usable in both (ADR-0011's rule for the body). A file with no `extra_joints`, or a
  pair where only one clip has feet, is not an error: the foot measures are hidden and `diagnostics.feet` says why.
"""
# ADR-0015: foot points enter as a side input; this module is the only reader of Part 2's `extra_joints`.
# ASM-013: synthetic side files in the same shape are a proxy for Part 2's estimated feet.
import math
from dataclasses import dataclass, field, replace

import numpy as np

from .io import InputError, read_json
from .measures import FOOT_MEASURES, SIDES, compute_feet

FOOT_POINTS = ("left_big_toe", "left_small_toe", "left_heel", "right_big_toe", "right_small_toe", "right_heel")
BODY_POINTS = tuple(f"{side}_hip" for side in SIDES)    # the only body joints a foot measure reads
# Provisional (spec open question 4): below it a point is not seen, so Part 2's 0.3 outside-the-image mark is hidden.
FOOT_MIN_CONF = 0.5
MIN_SEEN_SHARE = 0.8    # a foot measure is usable in a clip when it is a number in this share of its frames
MIN_MATCH_S = 0.008     # the least time window a clip frame may take a side frame from: half a 60 fps frame
# A 60 fps clip frame midway between two 30 fps side frames is exactly half a step from both; `t_ms` written to three
# decimals puts it a few hundred nanoseconds over, so the window gets this much slack and the tie still matches.
TIME_SLACK_S = 1e-6
NAN3 = np.full(3, np.nan)
MAX_IDS_SHOWN = 8       # `_ids_present` names this many ids, then counts the rest
MAX_ID_CHARS = 40       # and cuts a longer id to this many characters


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _point(raw, where, source):
    """One `{x, y, z, conf}` as an (x, y, z) array, NaN where the point is not seen (missing, null, not finite or
    `conf` under `FOOT_MIN_CONF`). A point that is not an object, or a coordinate or `conf` that is text, is an
    `InputError`. A point with no `conf` is seen."""
    if raw is None:
        return NAN3
    if not isinstance(raw, dict):
        raise InputError(f"{source}: {where} must be an object {{x, y, z, conf}}, got {type(raw).__name__}")
    xyz = [raw.get(k) for k in "xyz"]
    conf = raw.get("conf", 1.0)
    for name, v in (*zip("xyz", xyz), ("conf", conf)):
        if v is not None and not _is_number(v):
            raise InputError(f"{source}: {where}.{name} must be a number or null, got {v!r}")
    if (conf is None or not math.isfinite(conf) or conf < FOOT_MIN_CONF
            or any(v is None or not math.isfinite(v) for v in xyz)):
        return NAN3
    return np.array(xyz, float)


def _frames(doc, path):
    """`(mirrored, [(where, t seconds, [person objects])])` of a Part 2 pose3d.json, checking its shape: `frames` a
    non-empty list, each frame an object with a numeric `t_ms` and a `people` list of objects, `t0_pts_ms` (default 0)
    a number and `mirrored` (default false) a boolean. `t` is `(t_ms - t0_pts_ms) / 1000`, seconds on the file's own
    clock."""
    frames = doc.get("frames") if isinstance(doc, dict) else None
    if not isinstance(frames, list) or not frames:
        raise InputError(f"{path}: not a Part 2 pose3d.json (frames must be a non-empty list of "
                         "{frame, t_ms, people})")
    t0, mirrored = doc.get("t0_pts_ms", 0.0), doc.get("mirrored", False)
    if not _is_number(t0) or not math.isfinite(t0):
        raise InputError(f"{path}: t0_pts_ms must be a number, got {t0!r}")
    if not isinstance(mirrored, bool):
        raise InputError(f"{path}: mirrored must be true or false, got {mirrored!r}")
    out = []
    for i, fr in enumerate(frames):
        where = f"frames[{i}]"
        if not isinstance(fr, dict):
            raise InputError(f"{path}: {where} must be an object, got {type(fr).__name__}")
        t_ms, people = fr.get("t_ms"), fr.get("people")
        if not _is_number(t_ms) or not math.isfinite(t_ms):
            raise InputError(f"{path}: {where}.t_ms must be a number, got {t_ms!r}")
        if not isinstance(people, list):
            raise InputError(f"{path}: {where}.people must be a list, got {people!r}")
        for j, p in enumerate(people):
            if not isinstance(p, dict):
                raise InputError(f"{path}: {where}.people[{j}] must be an object, got {type(p).__name__}")
        out.append((where, (t_ms - t0) / 1000.0, people))
    return mirrored, out


def _median_step(frames):
    """The median time between consecutive frames of the file, over every frame whether or not the person is in it
    (0.0 for a one-frame file)."""
    times = np.sort(np.array([t for _, t, _ in frames], float))
    return float(np.median(np.diff(times))) if len(times) > 1 else 0.0


def _ids_present(frames):
    """The `people[].id`s in the file as text for an error message, e.g. `[0, 7, 'a']`: the numbers in order, then
    any other id as written (a text id is named too, so the reader sees why `--expected-feet-person 0` skips it).
    A file with many ids lists the first `MAX_IDS_SHOWN` and counts the rest (`[0, 1, ...] and 992 more (1000 in all)`),
    and a long text id is cut to `MAX_ID_CHARS`, so the message stays one short line."""
    numbers, others = set(), set()
    for _, _, people in frames:
        for p in people:
            if "id" not in p:
                continue
            if _is_number(p["id"]):
                numbers.add(p["id"])
            else:
                others.add(repr(p["id"]))
    named = [repr(i) for i in sorted(numbers)] + sorted(others)
    shown = ", ".join(n if len(n) <= MAX_ID_CHARS else n[:MAX_ID_CHARS - 3] + "..." for n in named[:MAX_IDS_SHOWN])
    more = len(named) - MAX_IDS_SHOWN
    return f"[{shown}]" + (f" and {more} more ({len(named)} in all)" if more > 0 else "")


def _carries_points(person):
    extra = person.get("extra_joints")
    return isinstance(extra, dict) and any(name in extra for name in FOOT_POINTS)


def file_summary(doc, source):
    """What a parsed pose3d.json offers as a feet side input, for `part5 doctor`: `{frames, people, with_points,
    mirrored}` (the frame count, the `people[].id`s, the frames where some person carries foot points). Raises
    `InputError` when it is not a Part 2 pose3d.json."""
    mirrored, frames = _frames(doc, source)
    ids = sorted({p["id"] for _, _, people in frames for p in people if _is_number(p.get("id"))})
    with_points = sum(any(_carries_points(p) for p in people) for _, _, people in frames)
    return {"frames": len(frames), "people": ids, "with_points": with_points, "mirrored": mirrored}


def _parse(path, person):
    """(t, points, has_points, mirrored, step) of one person in a Part 2 pose3d.json: `t` seconds on the file's own
    clock, one (n, 3) array per name in BODY_POINTS and FOOT_POINTS, whether any frame carries `extra_joints`, and
    the file's median frame step over all its frames."""
    mirrored, frames = _frames(read_json(path), path)
    times, rows, has_points = [], [], False
    for where, t, people in frames:
        mine = next((p for p in people if _is_number(p.get("id")) and p["id"] == person), None)
        if mine is None:
            continue
        base = f"{where}.people[id {person}]"
        joints, extra = mine.get("joints"), mine.get("extra_joints")
        if not isinstance(joints, dict):
            raise InputError(f"{path}: {base}.joints must be an object")
        if extra is not None and not isinstance(extra, dict):
            raise InputError(f"{path}: {base}.extra_joints must be an object")
        extra = extra or {}
        has_points = has_points or _carries_points(mine)
        rows.append([_point(joints.get(n), f"{base}.joints.{n}", path) for n in BODY_POINTS]
                    + [_point(extra.get(n), f"{base}.extra_joints.{n}", path) for n in FOOT_POINTS])
        times.append(t)
    if not rows:
        raise InputError(f"{path}: person {person} is in no frame (ids present: {_ids_present(frames)})")
    order = np.argsort(times, kind="stable")
    arr = np.array(rows, float)[order]   # (n, 8, 3)
    points = {name: arr[:, k] for k, name in enumerate(BODY_POINTS + FOOT_POINTS)}
    return np.array(times, float)[order], points, has_points, mirrored, _median_step(frames)


def check_file(path):
    """Read the file at `path` the way `load_side` does, for every person it holds, and return its `file_summary`.
    For `make check-5-contract`, which loads each committed feet file. Raises `InputError`."""
    info = file_summary(read_json(path), str(path))
    for person in info["people"]:
        _parse(path, person)
    return info


def _nearest(t_side, t_clip, step):
    """For each clip time the index of the side frame nearest in time, or -1 when none is within half `step`, the
    side file's median frame step over all its frames (at least `MIN_MATCH_S`)."""
    t_clip = np.asarray(t_clip, float)
    n = len(t_side)
    tolerance = max(MIN_MATCH_S, step / 2) + TIME_SLACK_S
    hi = np.clip(np.searchsorted(t_side, t_clip), 0, n - 1)
    lo = np.clip(hi - 1, 0, n - 1)
    best = np.where(np.abs(t_side[hi] - t_clip) < np.abs(t_side[lo] - t_clip), hi, lo)
    return np.where(np.abs(t_side[best] - t_clip) <= tolerance, best, -1)


def _swap_sides(series):
    """The left and right series exchanged: `left_foot_rotation` becomes the file's `right_foot_rotation`."""
    return {name: series[("right_" if name.startswith("left_") else "left_") + name.split("_", 1)[1]]
            for name in series}


@dataclass
class FootSide:
    """One clip's feet: where they came from, how many clip frames matched and the measure series on the clip's
    own frames. `series` is empty when no file was given."""
    label: str                # "expected" or "follower"
    source: str | None        # the side file's path, None when none was given
    person: int
    frames_matched: int = 0
    has_points: bool = False  # some frame of the person carries an `extra_joints` with a foot point
    series: dict = field(default_factory=dict)
    usable: list = field(default_factory=list)

    def entry(self):
        """The `diagnostics.feet.<label>` object."""
        return {"source": self.source, "person": self.person, "frames_matched": self.frames_matched,
                "usable": list(self.usable)}

    def why_not(self):
        """Plain words for why this side gives no foot measure, or None when it gives some."""
        if self.source is None:
            return f"no {self.label} feet file was given"
        if not self.has_points:
            return f"the {self.label} feet file has no extra_joints (no foot points)"
        if not self.usable:
            return f"no foot measure is seen in {MIN_SEEN_SHARE:.0%} of the {self.label} frames"
        return None


def load_side(label, path, person, clip_t):
    """The `FootSide` of the clip whose frame times are `clip_t` (seconds), from the pose3d.json at `path`
    (None for no file). Raises `InputError` for a file that is unreadable or not a Part 2 pose3d.json, a person id
    in no frame, or a file no clip frame matches in time."""
    if path is None:
        return FootSide(label, None, person)
    t_side, points, has_points, mirrored, step = _parse(path, person)
    index = _nearest(t_side, clip_t, step)
    matched = int((index >= 0).sum())
    if not matched:
        raise InputError(f"{path}: no frame of the {label} clip matches a frame of this file in time "
                         f"(file {t_side[0]:.3f} to {t_side[-1]:.3f} s, clip {float(np.min(clip_t)):.3f} to "
                         f"{float(np.max(clip_t)):.3f} s)")
    with np.errstate(invalid="ignore", divide="ignore"):
        raw = compute_feet(points)
    if mirrored:   # Part 3 un-mirrors the body; a mirrored file's left foot is the subject's right
        raw = _swap_sides(raw)
    series = {name: np.where(index >= 0, raw[name][index], np.nan) for name in FOOT_MEASURES}
    usable = [name for name, v in series.items() if np.isfinite(v).mean() >= MIN_SEEN_SHARE]
    return FootSide(label, str(path), person, matched, has_points, series, usable)


@dataclass
class FootPair:
    """The two clips' feet and what the pair is compared on."""
    expected: FootSide
    follower: FootSide
    compared: list
    hidden_reason: str | None

    def diagnostics(self):
        """`diagnostics.feet` (schema 1.6.0)."""
        return {"expected": self.expected.entry(), "follower": self.follower.entry(),
                "compared": list(self.compared), "hidden_reason": self.hidden_reason}

    def hidden(self, why):
        """This pair with no foot measure compared, for `why` (e.g. rep mode, or a take that could not be aligned)."""
        return replace(self, compared=[], hidden_reason=why)


def pair_of(expected, follower):
    """The `FootPair` of two `FootSide`s, or None when neither clip was given a feet file (the pair is then
    analysed and written exactly as before)."""
    if expected.source is None and follower.source is None:
        return None
    compared = [m for m in FOOT_MEASURES if m in expected.usable and m in follower.usable]
    if compared:
        return FootPair(expected, follower, compared, None)
    reasons = [r for r in (expected.why_not(), follower.why_not()) if r]
    return FootPair(expected, follower, [], "; ".join(reasons) or "no foot measure is usable in both clips")
