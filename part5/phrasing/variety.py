"""No phrase twice in one result (TICKET-045, docs/specs/second-opinion.md AC-VA-02, AC-VA-03).

The lines of one result are phrased in parallel, so no model call sees the others and a filler ("keep going", "keep
it under your hip") can come back in every line. A *phrase* is a run of three words with at least one word that is
not a fact word of its own line. Fact words are what the measurement says (the fault's template words, its body
part, side, direction, landmarks) and function words; two lines may share those, since two faults can share a side
or a body part. `phrases` lists a line's phrases; `repeats` names the lines that reuse a phrase of an earlier line.
"""
import re

from .template import GROUPS, LANDMARKS, NAMES, RULES

FUNCTION_WORDS = frozenset(
    "a an the your you you're is are was be been it its it's at in on of to and or but as by than then there "
    "this that these those with from for into around about while during when s sec secs second seconds "
    "too far much more less not quite bit little slightly very still just also both each one side looks look "
    "seems appear appears compared".split())
_WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
_GROUP_WORDS = {g: re.compile(rf"^(?:{words})$") for g, words in GROUPS.items()}


def _words(text):
    return _WORD.findall(text.lower().replace("’", "'"))


def _fact(word, fault, own):
    """True when `word` is a fact word for `fault`: function word, own template word, body part or direction."""
    if word in FUNCTION_WORDS or word in own or word.rstrip("s") in own:
        return True
    measure = fault.get("measure")
    groups = set(NAMES.get(measure, ())) | set(LANDMARKS.get(measure, ()))
    if any(_GROUP_WORDS[g].match(word) for g in groups):
        return True
    return any(rx.search(f" {word} ") for rx, _ in RULES.get(measure, ()))


def phrases(line, fault):
    """The three-word runs of `line` that hold a word the measurement does not supply."""
    own = {w for key in ("text", "text_timed", "side", "lateral") for w in _words(str(fault.get(key) or ""))}
    words = _words(line)
    return {tuple(words[i:i + 3]) for i in range(len(words) - 2)
            if not all(_fact(w, fault, own) for w in words[i:i + 3])}


def repeats(lines, faults, replaceable, fallback_lines=None):
    """Indices of the lines in `replaceable` that reuse a phrase of an earlier kept line.

    A line found here is replaced by its fallback (`fallback_lines[i]`, which the next lines are then compared
    against); a line not in `replaceable` (a template line) is always kept as it is.
    """
    seen, found = set(), []
    for i, (line, fault) in enumerate(zip(lines, faults)):
        own = phrases(line, fault)
        if i in replaceable and own & seen:
            found.append(i)
            own = phrases(fallback_lines[i], fault) if fallback_lines else set()
        seen |= own
    return found
