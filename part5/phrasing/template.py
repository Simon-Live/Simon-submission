"""The `template` backend, and the word test every other backend's line must pass (ADR-0005).

`lines` returns each fault's `text` (the plain-words template line from `part5.words`). It is the
default, the only backend in tests and `check-5`, and the fallback for any fault another backend
cannot phrase.

`line_problem` is the word test for a line from a language model. Per fault it must name the same
body part and side, carry the direction's meaning, add no number and add no other body part (a
proxy for "no fault the record does not hold"). It is deliberately strict and word based: a line
it cannot place falls back to the template, which is always safe. The template's own lines pass it
(tested), so the two vocabularies cannot drift apart.
"""
import re

NAME = "template"
MAX_CHARS = 160


def lines(faults):
    """Each fault's template text, in fault order."""
    return [f["text"] for f in faults]


# ---- body parts -------------------------------------------------------------------------------
GROUPS = {
    "head": r"heads?|necks?|chins?|nose|face",
    "shoulder": r"shoulders?",
    "arm": r"arms?",
    "elbow": r"elbows?",
    "hand": r"hands?|forearms?|wrists?|fists?",
    "trunk": r"trunk|torso|spine|chest|upper body|core",
    "hip": r"hips?|pelvis",
    "thigh": r"thighs?|legs?",
    "knee": r"knees?",
    "foot": r"foot|feet|ankles?|toes?|heels?",
}
# Groups a line may name for each measure; at least one must appear.
NAMES = {
    "elbow_flexion": ("elbow", "arm"),
    "knee_flexion": ("knee", "thigh"),
    "upper_arm_out": ("arm", "elbow", "shoulder"),
    "upper_arm_forward": ("arm", "elbow", "shoulder"),
    "forearm_out": ("hand", "arm"),
    "thigh_out": ("knee", "thigh", "hip"),
    "thigh_forward": ("thigh", "knee", "hip"),
    "foot_out": ("foot", "thigh"),
    "knee_valgus": ("knee", "thigh"),
    "trunk_lean_forward": ("trunk",),
    "trunk_lean_side": ("trunk",),
    "shoulder_tilt": ("shoulder",),
    "head_forward": ("head",),
}
# The trunk is often named by what it does, so a lean word counts as naming it.
TRUNK_CUES = r"lean\w*|upright|tilt\w*|slump\w*|hunch\w*|stoop\w*|posture|sway\w*"
# For these measures the words "left" and "right" carry the direction, so the side test steps aside.
SIDE_IS_DIRECTION = ("trunk_lean_side", "shoulder_tilt")


def _w(words):
    return rf"\b(?:{words})\b"


def _neg(words):
    """`words` under a negation, "not quite bent" or "bent less", consuming the rest of the clause."""
    before = rf"\b(?:not|isn't|aren't|never|barely|hardly|less|nowhere near)\b(?:\W+\w+){{0,3}}?\W+(?:{words})\b"
    after = rf"\b(?:{words})\b(?:\W+\w+){{0,2}}?\W+(?:less|not enough|too little)\b"
    return rf"(?:{before}|{after})[^,.;]*"


# ---- direction --------------------------------------------------------------------------------
# Rules run in order on the lower-cased line; each match is removed so later rules do not count it
# again. A line passes when every surviving hit has the fault's direction.
_OUT = r"out|outward\w*|wide\w*|apart|away|bow\w*|flar\w*|splay\w*|spread\w*"
_IN = (r"far in|inward\w*|close\w*|together|narrow\w*|tuck\w*|knock\w*|squeez\w*|pinned|hugg\w*|"
       r"against|in toward")
_UP = r"rais\w*|lift\w*|high\w*|up|forward|ahead|elevat\w*|swing\w*"
_DOWN = r"low\w*|hang\w*|drop\w*|behind|short|back"
_BENT = r"bent|bend\w*|flex\w*|curl\w*|fold\w*|deep\w*|sink\w*|tight\w*"
_STRAIGHT = r"straight\w*|extend\w*|locked|stiff|open|shallow"
_CAVE = r"cav\w*|collaps\w*|buckl\w*|knock\w*|inward\w*|far in|pinch\w*|squeez\w*|tuck\w*|fall\w* in|drift\w* in"
_KNEE_OUT = r"out|outward\w*|wide\w*|apart|bow\w*|splay\w*|flar\w*"
_LEAN = r"lean\w*|forward|ahead|hunch\w*|slump\w*|stoop\w*|bent over|round\w*|tilt\w*"
_UPRIGHT = r"upright|straighter|taller|tall|back\w*|behind|arch\w*|vertical"
_HEAD_FWD = r"forward|ahead|jut\w*|pok\w*|crane\w*|protrud\w*|out in front"
_HEAD_BACK = r"back|behind|retract\w*|tuck\w*"

OUT_IN = [(_neg(_OUT), "less"), (_w(_IN), "less"), (_w(_OUT), "more")]
RULES = {
    "upper_arm_out": OUT_IN, "forearm_out": OUT_IN, "thigh_out": OUT_IN, "foot_out": OUT_IN,
    "upper_arm_forward": [(_neg(_UP), "less"), (_w(_DOWN), "less"), (_w(_UP), "more")],
    "thigh_forward": [(_neg(_UP), "less"), (_w(_DOWN), "less"), (_w(_UP), "more")],
    "elbow_flexion": [(_neg(_BENT), "less"), (_w(_STRAIGHT), "less"), (_w(_BENT), "more")],
    "knee_flexion": [(_neg(_BENT), "less"), (_w(_STRAIGHT), "less"), (_w(_BENT), "more")],
    "knee_valgus": [(_neg(_CAVE), "less"), (_w(_KNEE_OUT), "less"), (_w(_CAVE), "more")],
    "trunk_lean_forward": [(r"\b(?:lean|bend|tilt) (?:forward|ahead) (?:a bit |a little )?(?:more|further)\b", "less"),
                           (_neg(_LEAN), "less"), (_w(_UPRIGHT), "less"), (_w(_LEAN), "more")],
    "trunk_lean_side": [(r"\bleft\b", "more"), (r"\bright\b", "less")],
    "shoulder_tilt": [(r"\bleft\b", "more"), (r"\bright\b", "less")],
    "head_forward": [(_neg(_HEAD_FWD), "less"), (_w(_HEAD_BACK), "less"), (_w(_HEAD_FWD), "more")],
}
RULES = {m: [(re.compile(p), d) for p, d in rules] for m, rules in RULES.items()}

NUMBER = re.compile(
    r"\d|%|°|\b(?:degrees?|percent|inch(?:es)?|cm|mm|centimet\w+|millimet\w+|met(?:re|er)s?|"
    r"zero|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    r"hundred|thousand)\b")
SIDE_WORDS = re.compile(r"\b(left|right)\b")
_GROUP_RX = {g: re.compile(_w(words)) for g, words in GROUPS.items()}
_TRUNK_CUES = re.compile(_w(TRUNK_CUES))


def _shape(fault, text):
    if not text:
        return "empty line"
    if "\n" in text or "\r" in text:
        return "more than one line"
    if len(text) > MAX_CHARS:
        return "line too long"
    return None


def _numbers(fault, text):
    return "adds a number" if NUMBER.search(text) else None


def _side(fault, text):
    if fault["measure"] in SIDE_IS_DIRECTION:
        return None
    named = set(SIDE_WORDS.findall(text))
    side = fault["side"]
    if side in ("left", "right"):
        return None if named == {side} else "wrong side"
    if side == "both":
        return None if len(named) != 1 else "wrong side"
    return None if not named else "wrong side"


def _body(fault, text):
    allowed = NAMES.get(fault["measure"])
    if allowed is None:
        return f"no word test for measure {fault['measure']!r}"
    found = {g for g, rx in _GROUP_RX.items() if rx.search(text)}
    if not (found & set(allowed)) and not (allowed == ("trunk",) and _TRUNK_CUES.search(text)):
        return "does not name the body part"
    extra = sorted(found - set(allowed))
    return f"adds another body part ({extra[0]})" if extra else None


def _direction(fault, text):
    hits = set()
    for rx, direction in RULES[fault["measure"]]:
        text, count = rx.subn(" ", text)
        if count:
            hits.add(direction)
    if not hits:
        return "does not say how it differs"
    if len(hits) > 1:
        return "contradicts itself on the direction"
    return None if hits == {fault["direction"]} else "wrong direction"


def line_problem(fault, line):
    """None when `line` fairly phrases the measured `fault`, else the short reason it does not."""
    text = line.strip().lower().replace("’", "'")
    for check in (_shape, _numbers, _side, _body, _direction):
        problem = check(fault, text)
        if problem:
            return problem
    return None
