"""Compare only what the camera sees (ADR-0011).

Part 2 writes `conf` 1.0 for a joint inside the image and exactly 0.3 for one the model placed
outside it (Part 2 CONTRACT, `joints.<name>.conf`). A seated or close-up selfie therefore carries
invented legs, and a comparison that counts them measures the estimator, not the person.

- A joint is unseen in a frame when its `conf` is the sentinel `UNSEEN_CONF` (0.3), Part 2's mark for a joint
  the model placed outside the image, and so is its left/right counterpart's (a side view marks only its far side). Any other conf is seen; a conf below 0.3 is a missing joint, which
  `io` already masks to NaN, so it keeps its earlier handling and nothing changes for those takes.
- A measure is usable in a clip when every joint it needs is visible in at least `MIN_VISIBLE_SHARE`
  of the clip's frames.
- A clip with no `conf` anywhere has unknown visibility and takes the other clip's usable set.
- The take is compared on the measures usable in both clips; fewer than `MIN_USABLE_MEASURES` refuses it
  as `not_enough_visible`.
A pair whose full-body measures are all usable (conf 1.0 or none) is compared exactly as before.
"""
import json
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from .align import ALIGN_MEASURES
from .guard import NOT_ENOUGH_VISIBLE  # noqa: F401  (the status code, re-exported)
from .io import JOINTS, InputError
from .measures import MEASURE_JOINTS, MEASURES, VIEW_MEASURES, compute, compute_view
from .reps import robust_range

ALL_JOINTS = {**MEASURE_JOINTS, **VIEW_MEASURES}   # every measure, with the joints it reads
UNSEEN_CONF = 0.3
UNSEEN_TOLERANCE = 1e-6
MIN_VISIBLE_SHARE = 0.8
MIN_USABLE_MEASURES = 3
# A measure "moves" in the expected clip when its robust range (p95 minus p5) is above this. Above the
# 15 degrees reps.py needs for repetitions and above every sway of a still head and shoulders (<= 9 degrees in
# the salute trainer); seed 5's expected clips and the documented real trainers move their main measures 40+.
MOVING_RANGE_DEG = 20.0
RULE = (f"a measure is used when all its joints are seen (conf is not the 0.3 unseen mark) in at least "
        f"{MIN_VISIBLE_SHARE:.0%} of the clip's frames; the take is compared on the measures usable in both clips")
NOT_ENOUGH_TEXT = ("Not enough of the body is in frame to compare this take with the example. "
                   "Step back or move the camera so more of the body, the same parts the example shows, is in frame.")


def _mirror(name):
    other = {"left": "right", "right": "left"}.get(name.split("_")[0])
    return JOINTS.index(other + name[name.index("_"):]) if other else None


MIRROR = [_mirror(n) for n in JOINTS]   # index of the left/right counterpart, None for the nose


def seen_mask(conf, strict=False):
    """(F, 17) True where a joint is seen. A joint is unseen when its conf is the 0.3 sentinel and so is its
    left/right counterpart's: a frame that crops both knees has lost the legs, whereas the far side of a side
    view is also marked 0.3 yet its mirror is seen, and that limb has always been compared (ADR-0011)."""
    marked = np.abs(np.asarray(conf, float) - UNSEEN_CONF) <= UNSEEN_TOLERANCE
    if strict:   # every 0.3 joint is unseen, side views included (what the example itself shows)
        return ~marked
    both = marked.copy()
    for j, m in enumerate(MIRROR):
        if m is not None:
            both[:, j] = marked[:, j] & marked[:, m]
    return ~both


def usable_from_conf(conf, strict=False):
    """Names of the measures usable given `conf` (F, 17), or None when visibility is unknown."""
    if conf is None:
        return None
    share = seen_mask(conf, strict).mean(axis=0)
    seen = {name for j, name in enumerate(JOINTS) if share[j] >= MIN_VISIBLE_SHARE}
    return {m for m, joints in ALL_JOINTS.items() if all(j in seen for j in joints)}


def clip_usable(clip):
    return usable_from_conf(clip.conf)


def _conf_of_doc(doc, source):
    """(F, 17) conf from a Part 2 `pose3d.json` / `skeleton.json` (frames[].people[0].joints.<j>.conf)
    or from a `simon.animation.v1` / `simon.skeleton.v1` document with per-frame `conf`."""
    frames = (doc.get("frames") or doc.get("keyframes")) if isinstance(doc, dict) else None
    if not isinstance(frames, list) or not frames:
        raise InputError(f"{source}: expected-visibility file has no frames")
    rows, seen = [], False
    for fr in frames:
        if not isinstance(fr, dict):
            raise InputError(f"{source}: expected-visibility frame is not an object")
        if isinstance(fr.get("people"), list):
            people = fr["people"]
            joints = people[0].get("joints", {}) if people and isinstance(people[0], dict) else {}
            conf = {k: v.get("conf", 1.0) for k, v in joints.items() if isinstance(v, dict)}
        else:
            conf = fr.get("conf", {})
        seen = seen or bool(conf)
        rows.append([float(conf.get(j, 1.0)) for j in JOINTS])
    return np.array(rows) if seen else None


def load_conf(path):
    """(F, 17) conf of the trainer's own skeleton (`--expected-visibility`), or None when it carries no `conf`."""
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise InputError(f"{path}: cannot read JSON ({e})") from e
    return _conf_of_doc(doc, str(path))


def load_visibility(path):
    """The usable measure set of `load_conf(path)`, or None when the file carries no `conf`."""
    return usable_from_conf(load_conf(path))


@dataclass
class Visibility:
    usable: list          # measure names (full-body, then view), in definition order
    excluded: list

    @property
    def full(self):
        """Every full-body measure is usable: the pair is compared as it always was (view measures unused)."""
        return not any(m in MEASURES for m in self.excluded)

    @property
    def align_usable(self):
        """Measures timing may be taken from, or None for the unchanged full-body choice."""
        return None if self.full else [m for m in self.usable if m in ALIGN_MEASURES or m in VIEW_MEASURES]

    @property
    def enough(self):
        return self.full or (len(self.usable) >= MIN_USABLE_MEASURES and bool(self.align_usable))

    def diagnostics(self, moving=None):
        out = {"usable_measures": len(self.usable), "excluded": list(self.excluded), "rule": RULE}
        return {**out, **moving} if moving else out


def resolve(*usable_sets):
    """Intersect the known usable sets (None = unknown, skipped) into a `Visibility`."""
    keep = set(ALL_JOINTS)
    for u in usable_sets:
        if u is not None:
            keep &= u
    return Visibility([m for m in ALL_JOINTS if m in keep], [m for m in ALL_JOINTS if m not in keep])


def hide_unseen(clip, vis):
    """The clip with every joint a frame does not see (conf is the 0.3 unseen mark) set to NaN, so a
    usable measure is never computed from an invented joint. Unchanged for a full-body pair or a clip with no conf."""
    if vis.full or clip.conf is None:
        return clip
    seen = seen_mask(clip.conf)
    pos = np.where(seen[:, :, None], clip.positions, np.nan)
    return replace(clip, positions=pos, mask=clip.mask & seen)


def measures_of(positions, vis):
    """The measure series a comparison uses: `compute` unchanged for a full-body pair; otherwise the
    unusable ones set to NaN and the usable head-and-shoulder view measures added."""
    m = compute(positions)
    if vis is None or vis.full:
        return m
    m = {n: (np.full_like(np.asarray(v, float), np.nan) if n in vis.excluded else v) for n, v in m.items()}
    view = compute_view(positions)
    return {**m, **{n: v for n, v in view.items() if n in vis.usable}}


def moving_check(exp_positions, vis, expected_confs):
    """The measures that move in the expected clip and which of them the pair can use (ADR-0011).

    Only measures the example itself shows count as moving (`expected_confs`: its own conf and the
    `--expected-visibility` conf, each None when unknown; strict, so a 0.3 joint is never shown), so the example's invented legs do not."""
    candidates = set(ALL_JOINTS)
    for conf in expected_confs:
        if conf is not None:
            candidates &= usable_from_conf(conf, strict=True)
    series = {**compute(exp_positions), **compute_view(exp_positions)}
    moving = [m for m in ALL_JOINTS if m in candidates and robust_range(series[m]) > MOVING_RANGE_DEG]
    return {"moving_measures": moving, "moving_usable": [m for m in moving if m in vis.usable]}


def _region(joints):
    """('arm'|'leg', side) pairs for the elbow, wrist, hip, knee and ankle joints in `joints`."""
    out = set()
    for j in joints:
        side, _, base = j.partition("_")
        if base in ("elbow", "wrist"):
            out.add(("arm", side))
        elif base in ("hip", "knee", "ankle"):
            out.add(("leg", side))
    return out


def _names(kind, sides):
    if len(sides) == 2:
        return f"{kind}s", True
    return f"{sides[0]} {kind}", False


def moving_text(moving):
    """Plain words naming the body part the example moves, from the joints of its moving measures."""
    regions = _region({j for m in moving for j in ALL_JOINTS[m]})
    names, plural = [], False
    for kind in ("arm", "leg"):
        sides = sorted(s for k, s in regions if k == kind)
        if sides:
            name, many = _names(kind, sides)
            names.append(name)
            plural = plural or many
    if not names:
        names, plural = ["head and shoulders"], True
    part = " and ".join(names)
    nouns = " and ".join(n.split()[-1] for n in names)
    if len(names) > 1:
        plural = True
    verb, pron = ("are", "they") if plural else ("is", "it")
    keep = "stay" if plural else "stays"
    return (f"Your {part} {verb} mostly out of frame, so {pron} can't be compared. "
            f"Step back so your whole {nouns} {keep} in view, then record again.")
