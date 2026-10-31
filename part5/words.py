"""Plain-words line for each fault, from its measure, direction, side and size.

Template text only (README: no frontier model). Sides are the subject's own left/right.
A per-side phrase has a {side} slot; "both" uses the plural phrase without a side.
"""
from .lateral import lateral_for

# measure → direction → (one side, both sides). Centre measures have one phrase per direction.
# Slots: {side}; {q} = "slightly " / "" / "much "; {nq} = "not quite" / "not" / "nowhere near"
# (for "not … enough" phrases, where "slightly"/"much" would read wrong); {aq} = " slightly" / ""
# / " a lot" (for phrases that end on a verb, where "much caving in" would read wrong).
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
    "knee_valgus": {"more": ("{side} knee caving in{aq}", "knees caving in{aq}"),
                    "less": ("{side} knee pushed out{aq}", "knees pushed out{aq}")},
    # ADR-0015: the foot measures. The ankle words say which way it rolls, not inversion or eversion: `more` is the
    # foot on its outer edge (the ankle rolling out), `less` the inner edge down (the arch collapsing, the ankle
    # caving in; ADR-0015 Amendment 1).
    "foot_rotation": {"more": ("{side} foot turned out {q}more than the example", "feet turned out {q}more than the example"),
                      "less": ("{side} foot {nq} turned out enough", "feet {nq} turned out enough")},
    "ankle_inversion": {"more": ("{side} ankle rolling out{aq}", "ankles rolling out{aq}"),
                        "less": ("{side} ankle rolling in{aq}", "ankles rolling in{aq}")},
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


QUALIFIERS = {"slight": ("slightly ", "not quite", " slightly"), "plain": ("", "not", ""),
              "much": ("much ", "nowhere near", " a lot")}


def band(magnitude_deg, threshold_deg):
    r = abs(magnitude_deg) / threshold_deg if threshold_deg else 0
    if r < SLIGHT_BELOW:
        return "slight"
    if r >= MUCH_FROM:
        return "much"
    return "plain"


def phrase(measure, direction, side, size="plain"):
    entry = PHRASES[measure][direction]
    q, nq, aq = QUALIFIERS[size]
    if isinstance(entry, str):
        if side != "center":
            raise ValueError(f"{measure} is a centre measure, got side {side!r}")
        return entry.format(q=q, nq=nq, aq=aq)
    one, both = entry
    if side == "both":
        return both.format(q=q, nq=nq, aq=aq)
    if side not in ("left", "right"):
        raise ValueError(f"{measure} needs side left/right/both, got {side!r}")
    return one.format(side=side, q=q, nq=nq, aq=aq)


def describe(fault, qualify=True):
    """`fault` has measure, direction, side, magnitude_deg, threshold_deg (a detect.Fault)."""
    size = band(fault.magnitude_deg, fault.threshold_deg) if qualify else "plain"
    return phrase(fault.measure, fault.direction, fault.side, size)


# Timed vocabulary (ADR-0009): measure → body noun for "{side} <noun> too far <lateral>".
LATERAL_NOUNS = {"foot_out": "foot", "thigh_out": "knee", "upper_arm_out": "arm", "forearm_out": "hand"}
# measure → (one side, both sides) for "too low"; only the direction "less". A thigh is not here: "thigh too
# low" reads as squatting too deep on a squat, the opposite of the fault, so `thigh_forward` keeps its
# "not raised enough" words in the timed line (R9). An arm held too low is just that.
LOW_PHRASES = {"upper_arm_forward": ("{side} arm {q}too low", "arms {q}too low")}


def describe_timed(fault, qualify=True):
    """The timed words for a `detect.Fault`: "too far right" and, for an arm, "too low" where `describe`
    says "out" or "not raised far enough". Everything else is the plain line, thigh_forward included
    ("right thigh not raised enough"; size: "not quite", "not", "nowhere near", as in `describe`)."""
    size = band(fault.magnitude_deg, fault.threshold_deg) if qualify else "plain"
    q = QUALIFIERS[size][0]
    lateral = lateral_for(fault.measure, fault.direction, fault.side)
    if fault.measure in LATERAL_NOUNS and lateral:
        return f"{fault.side} {LATERAL_NOUNS[fault.measure]} {q}too far {lateral}"
    if fault.measure in LOW_PHRASES and fault.direction == "less" and fault.side in ("left", "right", "both"):
        one, both = LOW_PHRASES[fault.measure]
        return (both if fault.side == "both" else one).format(side=fault.side, q=q)
    return phrase(fault.measure, fault.direction, fault.side, size)
