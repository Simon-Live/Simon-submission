"""Short imperative coaching cues for faults, misses and tempo (ADR-0014).

    cue_for(measure, direction, side) -> (cue, cue_kind)
    tempo_cue(ratio, overrides=None) -> cue or None     (overrides: a profile's tempo cues, ADR-0016)

A cue says what to do, in at most MAX_WORDS words: "Bend your knees more", "Raise your left arm higher".
It is template text from the fault's `measure`, `direction` and `side` only, so the same fault always gets
the same cue; no phrasing backend rewrites it (the AI line is `coaching`, ADR-0005).

`direction` is the sign of follower minus example (`more` positive, `less` negative), so every cue moves
the follower toward the example. Sides are the subject's own left and right, as in `part5.words`.

`cue_kind`: `range` when the fix is how far a joint bends or a limb lifts, `position` when it is where a body
part is placed or how it is aligned, `tempo` for speed. Foot rotation and the ankle roll are cues only when the
pair has foot points (ADR-0015: Part 2's heel and toe points, read from its pose3d.json); the 17 COCO joints end at
the ankle, so without them nothing measures a foot (ADR-0014).
"""
MAX_WORDS = 6
KINDS = ("position", "range", "tempo")

# Tempo (ADR-0014): ratio = follower time / example time for the same stretch of movement.
TEMPO_FAST, TEMPO_SLOW = 0.85, 1.15
SLOW_DOWN = "Slow down to match the trainer"
SPEED_UP = "Speed up to match the trainer"
# Tempo cues that reassure and ask for nothing (ADR-0016 Amendment 2, AC-PROF-07): `rehab` replaces SPEED_UP with the
# first. "What to work on first" lists actions (`part5.insights`), so a tempo cue in this set stays in `tempo.cue` and
# is no item. A profile that replaces a tempo cue with an action keeps its item, whatever the action says.
REASSURANCE_CUES = frozenset({"Slower is fine"})

# measure -> kind, {direction: (one side with {side}, both sides)}; centre measures have one string per direction.
CUES = {
    "elbow_flexion": ("range", {"more": ("Straighten your {side} arm more", "Straighten your arms more"),
                                "less": ("Bend your {side} elbow more", "Bend your elbows more")}),
    "knee_flexion": ("range", {"more": ("Straighten your {side} knee more", "Straighten your knees more"),
                               "less": ("Bend your {side} knee more", "Bend your knees more")}),
    "upper_arm_out": ("range", {"more": ("Keep your {side} arm closer in", "Keep your elbows closer in"),
                                "less": ("Raise your {side} arm higher", "Raise your arms higher")}),
    "upper_arm_forward": ("range", {"more": ("Keep your {side} arm lower", "Keep your arms lower"),
                                    "less": ("Raise your {side} arm forward more", "Raise your arms forward more")}),
    "thigh_forward": ("range", {"more": ("Keep your {side} knee lower", "Keep your thighs lower"),
                                "less": ("Lift your {side} knee higher", "Raise your thighs higher")}),
    "forearm_out": ("position", {"more": ("Bring your {side} hand in", "Bring your hands in"),
                                 "less": ("Move your {side} hand out", "Move your hands out wider")}),
    "thigh_out": ("position", {"more": ("Bring your {side} knee in", "Bring your knees closer together"),
                               "less": ("Push your {side} knee out", "Push your knees apart")}),
    "foot_out": ("position", {"more": ("Step your {side} foot in", "Bring your feet closer together"),
                              "less": ("Step your {side} foot out", "Widen your stance")}),
    "knee_valgus": ("position", {"more": ("Push your {side} knee out", "Push your knees out"),
                                 "less": ("Let your {side} knee come in", "Let your knees come in")}),
    # ADR-0015: `more` toe-out is the follower's foot turned out further than the example, so the cue turns it in.
    "foot_rotation": ("position", {"more": ("Turn your {side} foot in", "Turn your feet in"),
                                   "less": ("Turn your {side} foot out", "Turn your feet out")}),
    # ADR-0015 Amendment 1: `more` is the foot on its outer edge (the ankle rolling out), `less` the inner edge down.
    "ankle_inversion": ("position", {"more": ("Keep your {side} ankle straight", "Keep your ankles straight"),
                                     "less": ("Stop your {side} ankle rolling in", "Stop your ankles rolling in")}),
    "trunk_lean_forward": ("position", {"more": "Keep your chest up", "less": "Lean forward more"}),
    "trunk_lean_side": ("position", {"more": "Lean less to your left", "less": "Lean less to your right"}),
    "shoulder_tilt": ("position", {"more": "Lower your left shoulder", "less": "Lower your right shoulder"}),
    "head_forward": ("position", {"more": "Pull your head back", "less": "Bring your head forward"}),
}


def cue_for(measure, direction, side):
    """`(cue, cue_kind)` for a fault; ValueError for a measure, direction or side the vocabulary lacks."""
    if measure not in CUES:
        raise ValueError(f"no cue for measure {measure!r}")
    kind, by_direction = CUES[measure]
    if direction not in by_direction:
        raise ValueError(f"direction must be 'more' or 'less', got {direction!r}")
    entry = by_direction[direction]
    if isinstance(entry, str):
        if side != "center":
            raise ValueError(f"{measure} is a centre measure, got side {side!r}")
        return entry, kind
    one, both = entry
    if side == "both":
        return both, kind
    if side not in ("left", "right"):
        raise ValueError(f"{measure} needs side left/right/both, got {side!r}")
    return one.format(side=side), kind


def tempo_cue(ratio, overrides=None):
    """The tempo cue for a follower/example time ratio, or None when it is within 15% or unmeasured.

    `overrides` is a profile's `tempo.cues` (ADR-0016): `{"speed_up": ..., "slow_down": ...}` replaces that cue's
    words only; the ratio that earns the cue does not change."""
    overrides = overrides or {}
    if ratio is None:
        return None
    if ratio < TEMPO_FAST:
        return overrides.get("slow_down", SLOW_DOWN)
    if ratio > TEMPO_SLOW:
        return overrides.get("speed_up", SPEED_UP)
    return None


def tempo_block(ratio, overrides=None):
    """A window's `tempo`: `{ratio, cue}` (ratio rounded to 0.01, both null when unmeasured)."""
    r = None if ratio is None else round(float(ratio), 2)
    return {"ratio": r, "cue": tempo_cue(r, overrides)}
