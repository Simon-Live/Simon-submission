"""The second opinion's guardrail and its document check (TICKET-045, docs/specs/second-opinion.md AC-SO-02 to 04).

`supported(clip)` lists the body parts the follower clip shows: a part (a `template.GROUPS` name) is shown on a side
when one of its joints there is usable in at least half the frames (`clip.mask`, which already hides what the camera
does not see). `read_answer` parses the model's JSON and keeps only the verdicts and observations that pass
`text_problem`: one line of at most 140 characters, no control character, no link, a body part the clip shows (the
`template.GROUPS` words and the `EXTRA_PARTS` words, such as "back" and "shins"), times inside the clip, no other
number (`template.NUMBER`, and `QUANTITY` words such as "twice"), no praise and none of `BANNED`. Each dropped item
is listed with its reason.
"""
import math
import re
import unicodedata

from ..io import JOINTS
from ..phrasing.lang import json_object
from ..phrasing.template import GROUP_RX, NUMBER, SIDE_WORDS, TIME, praise
from .prompt import MAX_NOTE, MAX_OBSERVATIONS

LABEL = "model_opinion"
STATUSES = ("ok", "fallback", "skipped")
MIN_SHOWN = 0.5   # share of frames a joint must be usable in for its body part to count as shown
# Words this product never uses in what a student reads (positioning: a teacher's recording students are checked
# against, not a health product).
BANNED = re.compile(r"\b(?:coach\w*|rehab\w*|medic\w*|injur\w*|pain\w*|therap\w*|diagnos\w*|physio\w*|"
                    r"clinic\w*|doctor\w*|patient\w*|health\w*)\b", re.I)
# A count said in words that `template.NUMBER` (digits, units, number words) does not hold.
QUANTITY = re.compile(r"\b(?:twice|thrice|doubl(?:e|ed)|tripl(?:e|ed)|half|halves|dozens?)\b")
# A link or a domain: a note is about the take and sends nobody anywhere.
_LINK = re.compile(r"\b[a-z][a-z0-9+.\-]*://|\bwww\.|\bmailto:|\b[a-z0-9\-]+(?:\.[a-z0-9\-]+)*\.(?:com|net|org|io|ai|app|"
                   r"dev|co|me|ly|info|biz|edu|gov|xyz|site|online|link|top|club|shop|store|tv|cc|uk|us|de|fr|ru|cn|"
                   r"tk)\b")
# Body words a free note uses that `template.GROUPS` leaves out (a fault line never needs them), each with the group
# whose joints the clip must show. "back" counts as the trunk when it is the noun ("the back rounds"), not a direction
# ("steps back", "the back foot").
_BACK = (r"(?:^|\b(?:the|your|his|her|upper|lower|mid|middle)\s+)back\b(?!\s+(?:foot|feet|leg|legs|knee|knees|arm|"
         r"arms|hand|hands|elbow|elbows|heel|heels|of|to|toward|towards|into|up|down)\b)")
EXTRA_PARTS = (
    ("trunk", re.compile(_BACK + r"|\b(?:ribs?|ribcage|abs|abdomen|belly|stomach|lats?)\b")),
    ("hip", re.compile(r"\b(?:waist|waistline|glutes?|buttocks?|butt)\b")),
    ("thigh", re.compile(r"\b(?:quads?|quadriceps|hamstrings?|groin)\b")),
    ("foot", re.compile(r"\b(?:shins?|calf|calves|lower legs?|insteps?|soles?)\b")),
    ("head", re.compile(r"\b(?:eyes?|eyebrows?|ears?|mouth|jaw|forehead|cheeks?|gaze)\b")),
    ("hand", re.compile(r"\b(?:fingers?|thumbs?|palms?|knuckles?)\b")),
    ("arm", re.compile(r"\b(?:biceps?|triceps?)\b")),
    ("shoulder", re.compile(r"\b(?:collarbones?|scapulae?|trapezius|deltoids?)\b")),
)
BODY_PARTS = (*GROUP_RX.items(), *EXTRA_PARTS)
_SIDED = {"shoulder": ("shoulder",), "arm": ("elbow", "wrist"), "elbow": ("elbow",), "hand": ("wrist",),
          "hip": ("hip",), "thigh": ("hip", "knee"), "knee": ("knee",), "foot": ("ankle",)}
_HEAD = ("nose", "left_eye", "right_eye", "left_ear", "right_ear")


def supported(clip):
    """`{group: set of sides}` the clip shows; `"any"` for the head and trunk, which no side word narrows."""
    mask = getattr(clip, "mask", None)
    if mask is None or not len(mask):
        return {}
    shown = {name: float(mask[:, j].mean()) >= MIN_SHOWN for j, name in enumerate(JOINTS)}
    out = {}
    for group, parts in _SIDED.items():
        sides = {s for s in ("left", "right") if any(shown[f"{s}_{p}"] for p in parts)}
        if sides:
            out[group] = sides
    if any(shown[j] for j in _HEAD):
        out["head"] = {"any"}
    if all(shown[f"{s}_{p}"] for s in ("left", "right") for p in ("shoulder", "hip")):
        out["trunk"] = {"any"}
    return out


def text_problem(text, duration_s, shows):
    """None when `text` may be shown, else the short reason it may not."""
    if not isinstance(text, str) or not text.strip():
        return "empty"
    if "\n" in text or "\r" in text:
        return "more than one line"
    if len(text) > MAX_NOTE:
        return "too long"
    if any(unicodedata.category(c) in ("Cc", "Cf") for c in text):   # CR and LF were refused above
        return "has a control character"
    lowered = text.lower()
    if _LINK.search(lowered):
        return "has a link"
    if BANNED.search(lowered):
        return "uses a word this product does not use"
    if praise(lowered):
        return "adds praise"
    times = [float(t) for t in TIME.findall(lowered)]
    if any(not 0 <= t <= duration_s for t in times):
        return "names a time outside the clip"
    untimed = TIME.sub(" ", lowered)
    if NUMBER.search(untimed) or QUANTITY.search(untimed):
        return "adds a number"
    sides = set(SIDE_WORDS.findall(lowered))
    for group, rx in BODY_PARTS:
        if not rx.search(lowered):
            continue
        shown = shows.get(group, set())
        if not shown:
            return f"names a body part the clip does not show ({group})"
        if "any" not in shown and len(sides) == 1 and not sides <= shown:
            return f"names a side the clip does not show ({next(iter(sides))} {group})"
    return None


def _verdicts(items, n_faults, duration_s, shows, rejected):
    kept, seen = [], set()
    for i, item in enumerate(items if isinstance(items, list) else []):
        item = item if isinstance(item, dict) else {}
        index, agrees, note = item.get("fault_index"), item.get("agrees"), item.get("note")
        if not (isinstance(index, int) and not isinstance(index, bool) and 0 <= index < n_faults):
            problem = "names no fault of this take"
        elif index in seen:
            problem = "second verdict for the same fault"
        elif not isinstance(agrees, bool):
            problem = "agrees is not true or false"
        else:
            problem = text_problem(note, duration_s, shows)
        if problem:
            rejected.append({"kind": "verdict", "index": i, "reason": problem})
            continue
        seen.add(index)
        kept.append({"fault_index": index, "agrees": agrees, "note": note.strip()})
    return sorted(kept, key=lambda v: v["fault_index"])


def _observations(items, duration_s, shows, rejected):
    kept = []
    for i, item in enumerate(items if isinstance(items, list) else []):
        item = item if isinstance(item, dict) else {}
        at_s, text = item.get("at_s"), item.get("text")
        number = isinstance(at_s, (int, float)) and not isinstance(at_s, bool) and math.isfinite(at_s)
        if not number or not 0 <= at_s <= duration_s:
            problem = "time outside the clip"
        elif len(kept) >= MAX_OBSERVATIONS:
            problem = f"more than {MAX_OBSERVATIONS} observations"
        else:
            problem = text_problem(text, duration_s, shows)
        if problem:
            rejected.append({"kind": "observation", "index": i, "reason": problem})
            continue
        kept.append({"at_s": round(float(at_s), 1), "text": text.strip(), "label": LABEL})
    return kept


def read_answer(text, n_faults, duration_s, shows):
    """`{verdicts, observations, rejected}` from the model's answer; ValueError when it is not a JSON object."""
    doc = json_object(text)
    rejected = []
    verdicts = _verdicts(doc.get("verdicts"), n_faults, duration_s, shows, rejected)
    observations = _observations(doc.get("observations"), duration_s, shows, rejected)
    return {"verdicts": verdicts, "observations": observations, "rejected": rejected}


def validate_block(block, n_faults, fail):
    """The document check of `second_opinion` (contract C1), called by `output.validate_analysis`."""
    where = "second_opinion"
    if not isinstance(block, dict) or block.get("status") not in STATUSES:
        fail(f"{where} must be an object with status one of {list(STATUSES)}")
    for key in ("reason", "model"):
        if block.get(key) is not None and not isinstance(block[key], str):
            fail(f"{where}.{key} must be a string or null")
    if not isinstance(block.get("backend"), str):
        fail(f"{where}.backend must be a string")
    verdicts, observations = block.get("verdicts"), block.get("observations")
    if not isinstance(verdicts, list) or not isinstance(observations, list) or len(observations) > MAX_OBSERVATIONS:
        fail(f"{where} must carry verdicts and observations lists (at most {MAX_OBSERVATIONS} observations)")
    indices = [v.get("fault_index") if isinstance(v, dict) else None for v in verdicts]
    for v, index in zip(verdicts, indices):
        ok = (isinstance(index, int) and not isinstance(index, bool) and 0 <= index < n_faults
              and isinstance(v.get("agrees"), bool) and isinstance(v.get("note"), str) and len(v["note"]) <= MAX_NOTE)
        if not ok:
            fail(f"{where}.verdicts[] must be {{fault_index < {n_faults}, agrees, note of at most {MAX_NOTE}}}")
    if len(set(indices)) != len(indices):
        fail(f"{where}.verdicts has two verdicts for one fault")
    for o in observations:
        ok = (isinstance(o, dict) and isinstance(o.get("at_s"), (int, float)) and not isinstance(o["at_s"], bool)
              and o["at_s"] >= 0 and isinstance(o.get("text"), str) and len(o["text"]) <= MAX_NOTE
              and o.get("label") == LABEL)
        if not ok:
            fail(f"{where}.observations[] must be {{at_s, text of at most {MAX_NOTE}, label {LABEL!r}}}")
