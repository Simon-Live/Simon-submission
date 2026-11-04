"""The second opinion's guardrail and its document check (TICKET-045, docs/specs/second-opinion.md AC-SO-02 to 04).

`supported(clip)` lists the body parts the follower clip shows: a part (a `template.GROUPS` name) is shown on a side
when one of its joints there is usable in at least half the frames (`clip.mask`, which already hides what the camera
does not see). `read_answer` parses the model's JSON and keeps only the verdicts and observations that pass
`text_problem`: one line of at most 140 characters, no control character, no link, a body part the clip shows (the
`template.GROUPS` words and the `EXTRA_PARTS` words, such as "back" and "shins"), times inside the clip, no other
number (`template.NUMBER`, and `QUANTITY` words such as "twice" and "half" as an amount), no praise and none of
`BANNED`. "back" is the trunk only as a noun, and "face" after a body-part noun is a verb that names no head. Each
dropped item is listed with its reason. On a take with a declared body mask, `masked_parts` lists the body parts it
leaves not scored, and a note that names one is dropped too (N3 of the 1.14.0 recheck, TICKET-084), by its words and
a bare side word ("the left lifts"): a paraphrase with no listed word passes (TICKET-098).

`read_history_answer` is the same guard for the history opinion (TICKET-072, docs/specs/history-opinion.md): an
observation is kept only when it cites one fault of one take of the series (take, second, measure, side and body
part), and its sentence passes `text_problem` with no time allowed and only the cited fault's body part and side.

`check_answer` and `measured_facts` guard Ask this take (TICKET-081, docs/specs/ask-this-take.md "The validator",
ADR-0022): every number in an answer must be a number of a successful tool result of the same exchange, within its
rounding, and the answer must pass `shown_problem` (`unsafe_problem` and the praise test); otherwise `measured_facts`
writes the answer from the tool results, so each of its numbers is one of theirs.
"""
import re
import unicodedata

from ..io import JOINTS
from ..mask import mask_of_names
from ..measures import ALL_SPECS, SIDES
from ..phrasing.lang import EN, check_translated, json_object
from ..phrasing.template import GROUP_RX, NAMES, NUMBER, SIDE_WORDS, TIME, praise, without_face_verbs
from .prompt import MAX_NOTE, MAX_OBSERVATIONS, _number   # `_number`: None for nan, inf and an integer too big

LABEL = "model_opinion"
STATUSES = ("ok", "fallback", "skipped")
MIN_SHOWN = 0.5   # share of frames a joint must be usable in for its body part to count as shown
# Words this product never uses in what a student reads (positioning: a teacher's recording students are checked
# against, not a health product).
BANNED = re.compile(r"\b(?:coach\w*|rehab\w*|medic\w*|injur\w*|pain\w*|therap\w*|diagnos\w*|physio\w*|"
                    r"clinic\w*|doctor\w*|patient\w*|health\w*)\b", re.I)
# A count said in words that `template.NUMBER` (digits, units, number words) does not hold. "half" is a count ("by
# half", "half as much", "half a beat") but not when it names a stretch of the take ("the second half", "the first
# half of the clip", "the lower half"): the word before it is then a position.
QUANTITY = re.compile(r"\b(?:twice|thrice|doubl(?:e|ed)|tripl(?:e|ed)|halves|dozens?)\b|"
                      r"(?<!first )(?<!second )(?<!last )(?<!final )(?<!other )(?<!latter )(?<!upper )(?<!lower )"
                      r"(?<!top )(?<!bottom )(?<!front )(?<!back )\bhalf\b")
# A link or a domain: a note is about the take and sends nobody anywhere.
_LINK = re.compile(r"\b[a-z][a-z0-9+.\-]*://|\bwww\.|\bmailto:|\b[a-z0-9\-]+(?:\.[a-z0-9\-]+)*\.(?:com|net|org|io|ai|app|"
                   r"dev|co|me|ly|info|biz|edu|gov|xyz|site|online|link|top|club|shop|store|tv|cc|uk|us|de|fr|ru|cn|"
                   r"tk)\b")
# Body words a free note uses that `template.GROUPS` leaves out (a fault line never needs them), each with the group
# whose joints the clip must show. "back" counts as the trunk when it is the noun ("the back rounds"), not a direction
# ("steps back", "shifts to the back", "back and forth") and not the far one of a pair ("the back foot", "the back hip",
# "the back side"): those name the part after it, or nothing.
_BACK = (r"(?:^|(?<!to )(?<!toward )(?<!towards )\bthe\s+|\b(?:your|his|her|upper|lower|mid|middle)\s+)back\b"
         r"(?!\s+(?:and\s+forth|foot|feet|leg|legs|knee|knees|ankle|ankles|toe|toes|hip|hips|shoulder|shoulders|"
         r"wrist|wrists|side|sides|arm|arms|hand|hands|elbow|elbows|heel|heels|of|to|toward|towards|into|up|down)\b)")
# The list is words, so a paraphrase with none of them passes (TICKET-098, AC-SO-04): "lower body" and "lower limbs"
# are the thigh group (every leg part), the kneecap and the tibia the knee.
EXTRA_PARTS = (
    ("trunk", re.compile(_BACK + r"|\b(?:ribs?|ribcage|abs|abdomen|belly|stomach|lats?)\b")),
    ("hip", re.compile(r"\b(?:waist|waistline|glutes?|buttocks?|butt|pelvic|sacrum|tailbone|coccyx|"
                       r"sit(?:ting)? bones?)\b")),
    ("thigh", re.compile(r"\b(?:quads?|quadriceps|hamstrings?|groin|lower[\s-]+body|"
                         r"lower[\s-]+(?:limbs?|extremities)|laps?|femur|femurs|femora)\b")),
    ("knee", re.compile(r"\b(?:kneecaps?|patellae?|patellas?|tibiae?|tibias?|fibulae?|fibulas?)\b")),
    ("foot", re.compile(r"\b(?:shins?|calf|calves|lower legs?|insteps?|soles?|footwork)\b")),
    ("head", re.compile(r"\b(?:eyes?|eyebrows?|ears?|mouth|jaw|forehead|cheeks?|gaze)\b")),
    ("hand", re.compile(r"\b(?:fingers?|thumbs?|palms?|knuckles?)\b")),
    ("arm", re.compile(r"\b(?:biceps?|triceps?)\b")),
    ("shoulder", re.compile(r"\b(?:collarbones?|scapulae?|trapezius|deltoids?)\b")),
)
BODY_PARTS = (*GROUP_RX.items(), *EXTRA_PARTS)
_SIDED = {"shoulder": ("shoulder",), "arm": ("elbow", "wrist"), "elbow": ("elbow",), "hand": ("wrist",),
          "hip": ("hip",), "thigh": ("hip", "knee"), "knee": ("knee",), "foot": ("ankle",)}
_HEAD = ("nose", "left_eye", "right_eye", "left_ear", "right_ear")
_DIRECTION = re.compile(r"\b(?:to|toward|towards)\s+(?:the\s+)?$")   # "to the left": a direction, not a part's side


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


def masked_parts(block):
    """`{group: sides}` of the body parts a declared body mask (`body_mask`, ADR-0023) leaves not scored: a side of a
    `template.GROUPS` part when the mask (`mask.mask_of_names`) drops every measure that names it (`template.NAMES`: the
    measures of that side and the side-less ones), as `BodyMask.not_scored_chains` reads a chain. A seated take's legs,
    knees, feet and hips; a masked arm's arm, elbow and hand, but not its shoulder, which `shoulder_tilt` still scores.
    Empty with no block. N3 of the 1.14.0 recheck (TICKET-084): the second opinion refuses a note that names one."""
    if not isinstance(block, dict):
        return {}
    dropped = mask_of_names(block["declared"], block["source"]).measures
    out = {}
    for side in SIDES:
        for group in GROUP_RX:
            named = {name for measure, groups in NAMES.items() if group in groups
                     for name in (f"{side}_{measure}", measure) if name in ALL_SPECS}
            if named and named <= dropped:
                out.setdefault(group, set()).add(side)
    return out


def _not_scored(parts, masked):
    """The reason the lower-case sentence `parts` names a body part `masked` (`masked_parts`) leaves not scored: a
    mention with a masked side among the three words before it, or with no side word there (it speaks of every side);
    else a bare side word (`_bare_side`). None when it names none. Three words, so "left and right knees" is read as
    both sides; a direction word there ("drifts right, the left hand") can refuse a note it need not, never let one
    through."""
    for group, rx in BODY_PARTS:
        off = masked.get(group)
        for found in (rx.finditer(parts) if off else ()):
            said = set(SIDE_WORDS.findall(" ".join(re.findall(r"\w+", parts[:found.start()])[-3:])))
            if not said or said & off:
                return f"names a body part not scored in this take ({group})"
    return _bare_side(parts, masked)


def _bare_side(parts, masked):
    """The reason `parts` has a side word that no body-part noun takes ("the left lifts", "your left side stays
    quiet") and means a part `masked` leaves not scored: its side is not scored on any part (`_SIDED`), or a part named
    earlier in the sentence is not scored on that side (the noun the word leaves out, "the right foot stays while the
    left lifts"). "To the left", "towards the right" are a direction and are left to the note's other words. Lexical,
    like `_not_scored`: a paraphrase with no listed word passes."""
    mentions = [(found.start(), group) for group, rx in BODY_PARTS for found in rx.finditer(parts)]
    for found in SIDE_WORDS.finditer(parts):
        side, bound = found.group(), any(
            at >= found.end() and len(re.findall(r"\w+", parts[found.end():at])) < 3 for at, _ in mentions)
        if bound or _DIRECTION.search(parts[:found.start()]):
            continue
        if all(side in masked.get(group, ()) for group in _SIDED):
            return f"names a side not scored in this take ({side})"
        for at, group in sorted(mentions):
            if at < found.start() and side in masked.get(group, ()):
                return f"names a body part not scored in this take ({group})"
    return None


def unsafe_problem(text):
    """The reason `text` may not be shown in any language (a control character, a link, a word this product does not
    use), else None. A translated line is held to it too; the word list is English, so it catches a banned word that
    was left in the line untranslated."""
    if any(unicodedata.category(c) in ("Cc", "Cf") for c in text):
        return "has a control character"
    lowered = text.lower()
    if _LINK.search(lowered):
        return "has a link"
    if BANNED.search(lowered):
        return "uses a word this product does not use"
    return None


def text_problem(text, duration_s, shows, masked=None):
    """None when `text` may be shown, else the short reason it may not. `masked` (`masked_parts`) is what a declared
    body mask leaves not scored; a body part named there is refused even when the clip shows it."""
    if not isinstance(text, str) or not text.strip():
        return "empty"
    if "\n" in text or "\r" in text:
        return "more than one line"
    if len(text) > MAX_NOTE:
        return "too long"
    unsafe = unsafe_problem(text)   # CR and LF were refused above
    if unsafe:
        return unsafe
    lowered = text.lower()
    if praise(lowered):
        return "adds praise"
    times = [float(t) for t in TIME.findall(lowered)]
    if any(not 0 <= t <= duration_s for t in times):
        return "names a time outside the clip"
    untimed = TIME.sub(" ", lowered)
    if NUMBER.search(untimed) or QUANTITY.search(untimed):
        return "adds a number"
    sides = set(SIDE_WORDS.findall(lowered))
    parts = without_face_verbs(lowered)   # "the feet face out" names no head
    not_scored = _not_scored(parts, masked) if masked else None
    if not_scored:
        return not_scored
    for group, rx in BODY_PARTS:
        if not rx.search(parts):
            continue
        shown = shows.get(group, set())
        if not shown:
            return f"names a body part the clip does not show ({group})"
        if "any" not in shown and len(sides) == 1 and not sides <= shown:
            return f"names a side the clip does not show ({next(iter(sides))} {group})"
    return None


def _verdicts(items, n_faults, duration_s, shows, rejected, masked):
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
            problem = text_problem(note, duration_s, shows, masked)
        if problem:
            rejected.append({"kind": "verdict", "index": i, "reason": problem})
            continue
        seen.add(index)
        kept.append({"fault_index": index, "agrees": agrees, "note": note.strip()})
    return sorted(kept, key=lambda v: v["fault_index"])


def _observations(items, duration_s, shows, rejected, masked):
    kept = []
    for i, item in enumerate(items if isinstance(items, list) else []):
        item = item if isinstance(item, dict) else {}
        at_s, text = item.get("at_s"), item.get("text")
        at = _number(at_s)   # a bool, a string, nan, inf or an integer too large for a float is None
        if at is None or not 0 <= at <= duration_s:
            problem = "time outside the clip"
        elif len(kept) >= MAX_OBSERVATIONS:
            problem = f"more than {MAX_OBSERVATIONS} observations"
        else:
            problem = text_problem(text, duration_s, shows, masked)
        if problem:
            rejected.append({"kind": "observation", "index": i, "reason": problem})
            continue
        kept.append({"at_s": round(at, 1), "text": text.strip(), "label": LABEL})
    return kept


def read_answer(text, n_faults, duration_s, shows, masked=None):
    """`{verdicts, observations, rejected}` from the model's answer; ValueError when it is not a JSON object. A note
    that names a body part `masked` (`masked_parts`) leaves not scored is rejected (N3 of the 1.14.0 recheck)."""
    doc = json_object(text)
    rejected = []
    verdicts = _verdicts(doc.get("verdicts"), n_faults, duration_s, shows, rejected, masked)
    observations = _observations(doc.get("observations"), duration_s, shows, rejected, masked)
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


# ---- the history opinion's guard (TICKET-072, docs/specs/history-opinion.md AC-HO-04 to AC-HO-06, AC-HO-09) --------
NO_TIME = -1.0   # `text_problem` refuses every time in a sentence checked against a duration below 0
# The body-part groups (`template.GROUPS`) a sentence may name for a fault whose measure `template.NAMES` does not list.
PART_GROUPS = {"arms": ("arm", "elbow", "hand", "shoulder"), "legs": ("thigh", "knee", "hip", "foot"),
               "torso": ("trunk", "shoulder", "hip"), "head": ("head",), "feet": ("foot",)}
CITED = ("measure", "side", "body_part")


def _worded(problem):
    """`text_problem`'s reason, said for a fault of a series and not for a clip."""
    return problem.replace("names a time outside the clip", "names a time").replace(
        "the clip does not show", "the cited fault does not name")


def _cited_shows(fault):
    """The `shows` of `text_problem` for a sentence about `fault`: the groups its measure names, on its side."""
    groups = NAMES.get(fault["measure"]) or PART_GROUPS.get(fault["body_part"], ())
    sides = {fault["side"]} if fault["side"] in ("left", "right") else {"any"}
    return {group: set(sides) for group in groups}


def _seconds(value):
    """`value` rounded to 0.1 s when it is a finite number (not a bool), else None; an integer too large for a float is
    not a number here (`math.isfinite` would raise OverflowError on it)."""
    number = _number(value)
    return None if number is None else round(number, 1)


def _cited_fault(item, series):
    """`(fault row, None)` when `item` cites one fault of one take of `series`, else `(None, reason)`; the first
    citation value that is not in the input names the reason."""
    if not isinstance(item, dict):
        return None, "not an object"
    rows = series.faults.get(item["take"]) if isinstance(item.get("take"), str) else None
    if rows is None:
        return None, "take not in the input"
    at_s = _seconds(item.get("at_s"))
    if at_s is None or not any(row.get("at_s") == at_s for row in rows):
        return None, "second not in the input"
    for key, reason in zip(CITED, ("measure not in the input", "side not in the input", "body part not in the input")):
        if not (isinstance(item.get(key), str) and any(row.get(key) == item[key] for row in rows)):
            return None, reason
    for row in rows:
        if row.get("at_s") == at_s and all(row[key] == item[key] for key in CITED):
            return row, None
    return None, "values are not one fault of that take"


# "The earlier takes" is false of the first take of a series and "the later takes" of the last (a series of one take is
# both): the order is the one the caller gave, so the guard knows which take has nothing before or after it. Only a claim
# about another take is refused: "in your next take" (TICKET-076 R9) is advice about the take the follower makes next,
# true of the last one too, so a possessive before "next take" lets it through; "the next take" stays a claim. The
# possessive excuses "next take" only: "your later takes" and "your following takes" are claims about other takes (R2).
_EARLIER = re.compile(r"\b(?:earlier|previous|prior)\s+takes?\b")
_LATER = re.compile(r"\b(?:later|following)\s+takes?\b|"
                    r"(?<!\byour )(?<!\btheir )(?<!\bhis )(?<!\bher )\bnext\s+takes?\b")


def _order_problem(text, take_id, series):
    """The reason `text` may not be shown for `take_id`: it speaks of earlier takes though this is the first take of
    `series`, or of later takes though it is the last (advice about "your next take" is not a claim); else None."""
    lowered = text.lower()
    if take_id == series.takes[0]["take"] and _EARLIER.search(lowered):
        return "speaks of earlier takes but the cited take is the first"
    if take_id == series.takes[-1]["take"] and _LATER.search(lowered):
        return "speaks of later takes but the cited take is the last"
    return None


def _sentence(item, fault, series, language):
    """`(fields, None, fell_back)` with `text`, `lang` (and `text_en` for a translation) for the observation, or
    `(None, reason, False)`. The English `text` always goes through `text_problem` and `_order_problem`; for another
    language the `line` must pass `check_translated` too (which runs `unsafe_problem`), else the observation keeps its
    English text (`fell_back`)."""
    english = item.get("text")
    problem = text_problem(english, NO_TIME, _cited_shows(fault)) or _order_problem(english, item["take"], series)
    if problem:
        return None, _worded(problem), False
    english = english.strip()
    if language == EN:
        return {"text": english, "lang": EN}, None, False
    line = item.get("line")
    line = line.strip() if isinstance(line, str) else None
    if line is not None and check_translated({}, line, False) is None:
        return {"text": line, "lang": language, "text_en": english}, None, False
    return {"text": english, "lang": EN}, None, True


def _history_observation(item, series, language):
    """`(observation, None, fell_back)` for a grounded item, else `(None, reason, False)`. Every value in the
    observation but the sentence is copied from the cited fault, never from the model."""
    fault, reason = _cited_fault(item, series)
    if fault is None:
        return None, reason, False
    fields, reason, fell_back = _sentence(item, fault, series, language)
    if fields is None:
        return None, reason, False
    evidence = {key: fault[key] for key in ("direction", "magnitude_deg") if key in fault}
    return ({"take_id": item["take"], "at_s": fault["at_s"], **{key: fault[key] for key in CITED}, **fields,
             "evidence": evidence, "label": LABEL}, None, fell_back)


def read_history_answer(text, series, language, limit):
    """`{observations, dropped, translation_fallbacks}` from the model's answer on `series`: at most `limit` grounded
    observations in the model's order, and a count of what was dropped by reason. ValueError when the answer is not a
    JSON object holding an `observations` list."""
    items = json_object(text).get("observations")
    if not isinstance(items, list):
        raise ValueError("no observations list")
    kept, reasons, fallbacks, seen = [], {}, 0, set()
    for item in items:
        obs, reason, fell_back = _history_observation(item, series, language)
        if obs is not None:
            cite = (obs["take_id"], obs["at_s"], *(obs[key] for key in CITED))
            if cite in seen:
                reason = "second observation for the same fault"
            elif len(kept) >= limit:
                reason = f"more than {limit} observations"
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        seen.add(cite)
        kept.append(obs)
        fallbacks += fell_back
    return {"observations": kept, "dropped": {"count": sum(reasons.values()), "reasons": reasons},
            "translation_fallbacks": fallbacks}


# ---- Ask this take's validator (TICKET-081, docs/specs/ask-this-take.md "The validator", ADR-0022) ------------------
# The number words `template.NUMBER` counts as a number in a student line ("one" is not one of them: "the left one").
NUMBER_WORDS = {"zero": 0, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
                "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
                "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000}
_DIGITS = re.compile(r"\d+(?:\.\d+)?")
_NUMBER_WORD = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b")
MAX_ANSWER_CHARS = 1200
NUMBER_NOT_FOUND = "a number in the answer is not in any tool result"
NO_ANSWER = "no answer"
# R2 of the 1.14.0 review: an answer may not count in words, since no tool returns a count so written. `QUANTITY` is the
# second opinion's list (twice, half as an amount, dozens); `COUNT_WORDS` adds what no student line needed: an ordinal or
# a fraction past "second" ("the fifth rep", "a third", "a quarter") and the plural of a number word ("hundreds of
# frames"). "first" and "second" are left out: "at first", "a second".
COUNT_WORDS = re.compile(r"\b(?:third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|"
                         r"(?:thir|four|fif|six|seven|eigh|nine)teenth|(?:twen|thir|for|fif|six|seven|eigh|nine)tieth|"
                         r"hundredth|thousandth|thirds|fourths|fifths|quarters?|tens|hundreds|thousands|millions?)\b")
COUNT_IN_WORDS = "a count in words is not in any tool result"


def answer_numbers(text):
    """`[(as written, value, decimals)]` of the numbers in `text`, in reading order: its digit runs (`12`, `9.8`) and
    its number words. A sign is not part of a number: "9.8 degrees less" reads a tool's -9.8."""
    found = [(m.start(), m.group(), float(m.group()), len(m.group().partition(".")[2])) for m in _DIGITS.finditer(text)]
    found += [(m.start(), m.group(1), float(NUMBER_WORDS[m.group(1)]), 0)
              for m in _NUMBER_WORD.finditer(text.lower())]
    return [item[1:] for item in sorted(found)]


def shown_problem(text):
    """The reason the model's `text` may not be shown to a follower in Ask this take: `unsafe_problem` (a control
    character such as a bidi override, a link, a word this product does not use) or praise; else None. The answer and
    every string of a tool call's arguments are held to it (R1 of the 1.14.0 review)."""
    return unsafe_problem(text) or praise(text.lower())


def result_numbers(tool_calls):
    """The absolute values of every number in the results of the successful calls of `tool_calls` (`ok` true), the
    numbers inside their text included. An error result holds no measurement, so its numbers count for nothing: the
    model cannot launder a number through a refused call (R1 of the 1.14.0 review)."""
    out = []

    def walk(value):
        if isinstance(value, str):
            out.extend(abs(v) for _, v, _ in answer_numbers(value))
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif _number(value) is not None:   # a bool, None, nan or an integer too large for a float is not a number
            out.append(abs(_number(value)))

    for call in tool_calls:
        if call.get("ok") is True:
            walk(call.get("result"))
    return out


def _found(value, decimals, known):
    """True when a number of `known` rounds to `value` at `decimals` places (half a unit of the last place each way)."""
    slack = 0.5 * 10 ** -decimals + 1e-9
    return any(abs(v - value) <= slack for v in known)


def check_answer(text, tool_calls):
    """`(answer, problem, not_found)` for the model's `text`: the answer with its runs of blanks and line breaks joined
    to one space, the reason it may not be shown (None when it may) and the numbers no tool result of `tool_calls`
    holds, as written. The numbers are checked before the count words, so an answer with both lists its numbers."""
    answer = " ".join(text.split()) if isinstance(text, str) else ""
    if not answer:
        return answer, NO_ANSWER, []
    if len(answer) > MAX_ANSWER_CHARS:
        return answer, "answer too long", []
    problem = shown_problem(answer)
    if problem:
        return answer, problem, []
    known = result_numbers(tool_calls)
    missing = [written for written, value, decimals in answer_numbers(answer) if not _found(value, decimals, known)]
    if missing:
        return answer, NUMBER_NOT_FOUND, missing
    lowered = answer.lower()
    return answer, COUNT_IN_WORDS if QUANTITY.search(lowered) or COUNT_WORDS.search(lowered) else None, []


def _say(value):
    """A tool's number as the measured facts write it: its own digits, no trailing zero, no sign."""
    return ("%.6f" % abs(value)).rstrip("0").rstrip(".")


def _capitalised(text):
    return text[:1].upper() + text[1:]


def _named(row):
    """`left knee bend` for a measure row of `get_joint_angle` or `compare_with_teacher`."""
    return f"{row['side']} {row['means']}" if row["side"] in ("left", "right") else row["means"]


def _fault_facts(result):
    count = result["count"]
    if not count:
        return ["The measurement found no difference from the example."]
    lines = [f"The measurement found {count} difference{'s' if count != 1 else ''} from the example."]
    for fault in result["faults"]:
        words = fault.get("text_timed") or fault.get("text") or f"{fault.get('side', '')} {fault.get('measure', '')}"
        size = _number(fault.get("magnitude_deg"))
        how = f": {_say(size)} degrees {fault.get('direction')} than the example" if size is not None \
            and fault.get("direction") in ("more", "less") else ""
        lines.append(f"{_capitalised(words.strip())}{how}.")
    return lines


def _angle_facts(result):
    span = f"from {_say(result['t0'])} s to {_say(result['t1'])} s"
    return [f"{_capitalised(_named(row))} {span}: from {_say(row['min'])} to {_say(row['max'])} degrees, "
            f"{_say(row['mean'])} on average." if row["min"] is not None
            else f"{_capitalised(_named(row))} could not be measured {span}." for row in result["measures"]]


def _compare_facts(result):
    lines = []
    for row in result["measures"]:
        if row["take_deg"] is None or row["example_deg"] is None:
            continue
        diff = row["difference_deg"]
        how = "the same as the example" if not diff else f"{_say(diff)} degrees {'more' if diff > 0 else 'less'}"
        lines.append(f"At {_say(result['take_t_s'])} s, {_named(row)}: {_say(row['take_deg'])} degrees in the take and "
                     f"{_say(row['example_deg'])} in the example at {_say(result['example_t_s'])} s, {how}.")
    return lines


FACTS = {"get_faults": _fault_facts, "get_joint_angle": _angle_facts, "compare_with_teacher": _compare_facts}
# R13 of the 1.14.0 review: the facts are held to `answer.maxLength` of contracts/ask.schema.json. A take with many faults
# and seven range and compare calls could pass it, so whole sentences are kept in order while they fit, then FACTS_CUT.
MAX_FACTS_CHARS = 4000
FACTS_CUT = "The rest of the measured facts are in the tool calls."


def _held(lines, limit=MAX_FACTS_CHARS):
    """`lines` joined by one space when that fits `limit`; else the longest run of whole lines from the first that fits
    with FACTS_CUT after it."""
    text = " ".join(lines)
    if len(text) <= limit:
        return text
    kept, size = [], len(FACTS_CUT)
    for line in lines:
        if size + len(line) + 1 > limit:
            break
        kept.append(line)
        size += len(line) + 1
    return " ".join([*kept, FACTS_CUT])


def measured_facts(tool_calls):
    """The answer Part 5 writes from the results of `tool_calls` (each fact once, in call order), or None when no
    result holds a fact (only UI actions or errors). Every number in it is a number of a result, and it is at most
    MAX_FACTS_CHARS long, cut between whole sentences (`_held`)."""
    lines = []
    for call in tool_calls:
        if call["ok"] and call["name"] in FACTS:
            lines += FACTS[call["name"]](call["result"])
    return _held(list(dict.fromkeys(lines))) or None
