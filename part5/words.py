"""Plain-words line for each fault, from its measure, direction, side and size.

Template text only (README: no frontier model). Sides are the subject's own left/right.
A per-side phrase has a {side} slot; "both" uses the plural phrase without a side.
"""

# measure → direction → (one side, both sides). Centre measures have one phrase per direction.
# Slots: {side}; {q} = "slightly " / "" / "much "; {nq} = "not quite" / "not" / "nowhere near"
# (for "not … enough" phrases, where "slightly"/"much" would read wrong).
PHRASES = {
    "elbow_flexion": {"more": ("{side} elbow bent {q}more than the example", "elbows bent {q}more than the example"),
                      "less": ("{side} elbow {q}straighter than the example", "elbows {q}straighter than the example")},
    "knee_flexion": {"more": ("{side} knee bent {q}more than the example", "knees bent {q}more than the example"),
                     "less": ("{side} knee {nq} bent enough", "knees {nq} bent enough")},
    "upper_arm_out": {"more": ("{side} arm {q}too far out", "elbows {q}wider than the example"),
                      "less": ("{side} arm {q}too close to the body", "arms {q}too close to the body")},
    "upper_arm_forward": {"more": ("{side} arm raised {q}too far forward", "arms raised {q}too far forward"),
                          "less": ("{side} arm {nq} raised far enough forward", "arms {nq} raised far enough forward")},
    "forearm_out": {"more": ("{side} hand {q}too far out", "hands {q}too far out"),
                    "less": ("{side} hand {q}too close in", "hands {q}too close in")},
    "thigh_out": {"more": ("{side} knee {q}too far out", "knees {q}too far apart"),
                  "less": ("{side} knee {q}too far in", "knees {q}too close together")},
    "thigh_forward": {"more": ("{side} thigh raised {q}too high", "thighs raised {q}too high"),
                      "less": ("{side} thigh {nq} raised enough", "thighs {nq} raised enough")},
    "foot_out": {"more": ("{side} foot {q}too far out", "feet {q}too far apart"),
                 "less": ("{side} foot {q}too far in", "feet {q}too close together")},
    # Centre measures are phrased relative to the example: detection only knows
    # follower − expected, so "leaning to the right" would be wrong when the example leans left.
    "trunk_lean_forward": {"more": "leaning forward {q}more than the example",
                           "less": "{q}more upright than the example, lean forward more"},
    "trunk_lean_side": {"more": "leaning {q}further to the left than the example",
                        "less": "leaning {q}further to the right than the example"},
    "shoulder_tilt": {"more": "left shoulder {q}higher than in the example",
                      "less": "right shoulder {q}higher than in the example"},
    "head_forward": {"more": "head {q}further forward than the example",
                     "less": "head {q}further back than the example"},
}

# Size qualifier from |magnitude| / threshold: just past the threshold reads "slightly".
SLIGHT_BELOW, MUCH_FROM = 1.5, 3.0


QUALIFIERS = {"slight": ("slightly ", "not quite"), "plain": ("", "not"), "much": ("much ", "nowhere near")}


def band(magnitude_deg, threshold_deg):
    r = abs(magnitude_deg) / threshold_deg if threshold_deg else 0
    if r < SLIGHT_BELOW:
        return "slight"
    if r >= MUCH_FROM:
        return "much"
    return "plain"


def phrase(measure, direction, side, size="plain"):
    entry = PHRASES[measure][direction]
    q, nq = QUALIFIERS[size]
    if isinstance(entry, str):
        if side != "center":
            raise ValueError(f"{measure} is a centre measure, got side {side!r}")
        return entry.format(q=q, nq=nq)
    one, both = entry
    if side == "both":
        return both.format(q=q, nq=nq)
    if side not in ("left", "right"):
        raise ValueError(f"{measure} needs side left/right/both, got {side!r}")
    return one.format(side=side, q=q, nq=nq)


def describe(fault, qualify=True):
    """`fault` has measure, direction, side, magnitude_deg, threshold_deg (a detect.Fault)."""
    size = band(fault.magnitude_deg, fault.threshold_deg) if qualify else "plain"
    return phrase(fault.measure, fault.direction, fault.side, size)
