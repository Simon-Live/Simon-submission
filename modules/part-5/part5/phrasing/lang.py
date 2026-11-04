"""The follower's language for fault lines (TICKET-046, docs/specs/second-opinion.md, ASM-014).

`resolve(tag)` maps a BCP 47 tag to a listed language (its primary subtag); anything else is English, and the tag
asked for is kept so the document can say so. For a language other than English a model is asked for one JSON
answer holding the English line and the translated line (`reply_instruction`, `read_pair`). The English line goes
through the existing word test (`template.line_problem`); the translated line through `check_translated`, which
holds what can be checked in any language: one line, no control character, link or banned word
(`opinion.guard.unsafe_problem`, N2 of the 1.14.0 recheck), the fault's time said once, no other number, no English
time phrase before it (TICKET-052) and no praise.
`json_object` is the one reader of a model's JSON answer (this module and `opinion.guard`).

Cues and reasons (TICKET-080, docs/specs/language-cues.md): `check_cue` holds one translated cue or reason to the same
kind of test, for any listed language: one line, a length limit, no control character, link or banned word
(`opinion.guard.unsafe_problem`), no praise, no number a cue should not have (a reason keeps exactly the numbers of its English
text), no English time phrase, written in the script of the language and not a copy of the English. `NATIVE_REVIEWED` lists
the languages a native reader has checked; none yet.
"""
import json
import re
import unicodedata

from ..cues import ROLE_CUE
from . import template

EN = "en"
# The languages Part 5 asks Muse Spark to write in, by primary subtag. A language left out falls back to English.
LANGUAGES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese",
    "nl": "Dutch", "sv": "Swedish", "pl": "Polish", "tr": "Turkish", "ru": "Russian", "ar": "Arabic",
    "hi": "Hindi", "id": "Indonesian", "vi": "Vietnamese", "ja": "Japanese", "ko": "Korean", "zh": "Chinese",
}
# The languages a native reader has checked (TICKET-080, ASM-015). A language is added here only when a person signs it;
# `phrasing.native_review` is true for these and false for every other language but English.
NATIVE_REVIEWED = frozenset()
# The scripts of the listed languages that do not write Latin letters, by the first word of a letter's Unicode name.
SCRIPTS = {"ar": ("ARABIC",), "hi": ("DEVANAGARI",), "ru": ("CYRILLIC",), "ja": ("HIRAGANA", "KATAKANA", "CJK"),
           "ko": ("HANGUL", "CJK"), "zh": ("CJK",)}
MAX_CUE_CHARS, MAX_CUE_WORDS = 60, 10   # a cue is at most 6 English words; another language needs more room
MIN_SCRIPT_SHARE = 0.5   # share of a text's letters that must be in the language's script
_WORD = re.compile(r"[^\W\d_]{3,}")
TAG = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*$")
MAX_REQUESTED = 35     # characters kept of the tag asked for: BCP 47's practical maximum
MAX_TRANSLATED = 200   # characters; a translation runs longer than the 160 an English line may take
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
# The English words that open a time phrase ("At 1.9 s", "Around 1.9 s"). The model copies its English twin's phrase
# into the translated line, so a line that has one directly before the time number is English there and falls back to
# the template line (TICKET-052, ASM-014). Whole words, any letter case. The set leaves out every word a listed
# language writes in that place (in, a, en, um, om, bei, vers, aos, rond and the like); the test file
# tests/test_phrasing_time_phrase.py pins a correct time phrase in each listed language. Only this position is
# checked; other English words in a line rest on ASM-014 and the native-speaker read.
ENGLISH_TIME_WORDS = ("at", "around", "about", "by", "near", "after", "before", "approximately", "roughly")
_ENGLISH_TIME = re.compile(r"(?<!\w)(?:" + "|".join(ENGLISH_TIME_WORDS) + r")\s+\d+(?:[.,]\d+)?", re.I)
# Praise in the other Latin-script languages a line is written in, by language, as the plain words (lower case, no
# accents: `_praised` reads the line the same way). English praise (`template.PRAISE_PHRASES`) is checked in every
# language, since a translated line often keeps an English phrase. A language left out here (the ones in other scripts)
# is checked for the English phrases only.
PRAISE = {
    "es": ("buen trabajo", "buen esfuerzo", "buen intento", "bien hecho", "excelente trabajo", "felicidades",
           "felicitaciones", "enhorabuena"),
    "fr": ("bon travail", "beau travail", "excellent travail", "bon effort", "bel effort", "bien joue", "bien fait",
           "felicitations"),
    "de": ("gut gemacht", "gute arbeit", "super gemacht", "toll gemacht", "guter versuch", "gluckwunsch"),
    "it": ("ottimo lavoro", "buon lavoro", "bel lavoro", "ben fatto", "complimenti", "buon tentativo", "bravo",
           "brava", "bravi"),
    "pt": ("bom trabalho", "otimo trabalho", "excelente trabalho", "bem feito", "parabens", "boa tentativa",
           "bom esforco"),
    "nl": ("goed gedaan", "goed werk", "goed zo", "gefeliciteerd"),
    "sv": ("bra jobbat", "bra gjort", "bra jobb", "grattis"),
    "pl": ("dobra robota", "swietna robota", "gratulacje", "brawo"),
    "tr": ("aferin", "tebrikler"),
    "id": ("kerja bagus",),
}
_PRAISE = re.compile(r"\b(?:" + "|".join(r"[\s\-]+".join(map(re.escape, p.split()))
                                         for phrases in PRAISE.values() for p in phrases) + r")\b")


def _clean(tag):
    """`tag` as text without control or format characters (a tab, a zero-width space), stripped."""
    return "".join(c for c in str(tag) if unicodedata.category(c)[0] != "C").strip()


def resolve(tag):
    """(language, requested): `language` is a key of LANGUAGES; `requested` is the tag when it differs from it
    (a region tag such as `es-MX`, an unlisted or malformed tag), else None, kept to MAX_REQUESTED characters. None,
    "" or a tag of nothing but white space and control characters means English with no tag asked for."""
    text = _clean("" if tag is None else tag)
    if not text:
        return EN, None
    primary = text.split("-")[0].lower() if TAG.match(text) else None
    language = primary if primary in LANGUAGES else EN
    return language, (None if text == language else text[:MAX_REQUESTED])


def name(language):
    return LANGUAGES[language]


def reply_instruction(language):
    """The reply rule of a prompt: the sentence alone in English, a JSON pair for any other language."""
    if language == EN:
        return "Reply with only the sentence."
    lang = name(language)
    return (f"Reply with only a JSON object {{\"en\": \"<the sentence in English>\", \"line\": \"<the same sentence "
            f"in {lang}>\"}}. The English sentence follows every rule below. The {lang} sentence says exactly the "
            f"same thing, follows the same rules with every word in {lang} (the sentence shape too), and writes "
            "the time with the same Western digits as the English one.")


def json_object(text):
    """The JSON object in a model's answer (from the first `{` to the last `}`); ValueError when there is none."""
    start, end = text.find("{"), text.rfind("}")
    if not 0 <= start < end:
        raise ValueError("no JSON object")
    doc = json.loads(text[start:end + 1])
    if not isinstance(doc, dict):
        raise ValueError("not an object")
    return doc


def read_pair(text):
    """(english, translated) from a model's JSON answer; ValueError("unreadable answer") when it is not one."""
    try:
        doc = json_object(text)
    except ValueError:
        raise ValueError("unreadable answer") from None
    pair = (doc.get("en"), doc.get("line"))
    if not all(isinstance(p, str) and p.strip() for p in pair):
        raise ValueError("unreadable answer")
    return tuple(p.strip().strip("\"'`").strip() for p in pair)


def _unhidden(text, format_as):
    """`text` with each format character (zero-width and the like) read as `format_as`."""
    return "".join(format_as if unicodedata.category(c) == "Cf" else c for c in text)


def _folded(text, format_as):
    """`text` lower case, without accents, each format character (zero-width and the like) read as `format_as`."""
    plain = (c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c))
    return _unhidden(plain, format_as)


def _praised(line):
    """True when `line` holds a praise phrase: an English one (`template.praise`) or one of `PRAISE`."""
    return bool(template.praise(line)) or any(_PRAISE.search(_folded(line, as_)) for as_ in ("", " "))


def _english_time(line):
    """True when an English time word (`ENGLISH_TIME_WORDS`) stands directly before a number in `line`. Accents are
    kept (an accented word of a listed language is never read as an English one); a format character is read both
    ways, as `_praised` does."""
    return any(_ENGLISH_TIME.search(_unhidden(line, as_)) for as_ in ("", " "))


def _unsafe(text):
    """`opinion.guard.unsafe_problem(text)`, imported at the call: opinion.guard imports this module."""
    from ..opinion.guard import unsafe_problem
    return unsafe_problem(text)


def check_translated(fault, line, timed):
    """None when the translated `line` holds what a line in any language must, else the short reason. A line that
    passes the checks of TICKET-046 and TICKET-052 (`_translated_problem`, whose reasons stand) is then held to
    `opinion.guard.unsafe_problem` (no control character, a bidi override such as U+202E included, no link, none of the
    words this product does not use), as a translated cue is: N2 of the 1.14.0 recheck (TICKET-080), since the page
    shows the line with `dir=auto`."""
    problem = _translated_problem(fault, line, timed)
    if problem:
        return problem
    unsafe = _unsafe(line)
    return f"translated line {unsafe}" if unsafe else None


def _translated_problem(fault, line, timed):
    """The reason `line` is not one line saying the fault's time once (when `timed`), with no other number, no English
    time phrase and no praise; None when it is."""
    if "\n" in line or "\r" in line:
        return "translated line has more than one line"
    if not line or len(line) > MAX_TRANSLATED:
        return "translated line is empty or too long"
    if _praised(line):
        return "translated line adds praise"
    numbers = _NUMBER.findall(line)
    if not timed:
        return "translated line adds a number" if numbers else None
    if len(numbers) != 1:
        return "translated line does not say the time once"
    if round(float(numbers[0].replace(",", ".")), 1) != round(float(fault["at_s"]), 1):
        return "translated line has the wrong time"
    return "translated line keeps an English time phrase" if _english_time(line) else None


def native_review(language):
    """True when a native reader has checked `language` (`NATIVE_REVIEWED`); False for every other language."""
    return language in NATIVE_REVIEWED


def _numbers(text):
    """The numbers of `text` as floats, sorted, a comma or a point as the decimal separator ("1,9" is 1.9)."""
    return sorted(float(n.replace(",", ".")) for n in _NUMBER.findall(text))


def _script_share(text, prefixes):
    """The share of the letters of `text` whose Unicode name starts with one of `prefixes`; 0 when it has no letter."""
    letters = [c for c in text if c.isalpha()]
    inside = sum(unicodedata.name(c, "").startswith(prefixes) for c in letters)
    return inside / len(letters) if letters else 0.0


def _in_language(source, text, language):
    """True when `text` reads as written in `language` and not as the English `source`: a language with its own script
    has at least half its letters in it; a Latin-script language is not a copy of the English and does not share half or
    more (and at least two) of its words of three letters or more with it."""
    if language in SCRIPTS:
        return _script_share(text, tuple(SCRIPTS[language])) >= MIN_SCRIPT_SHARE
    if text.strip().casefold() == source.strip().casefold():
        return False
    source_words = set(_WORD.findall(source.casefold()))
    shared = source_words & set(_WORD.findall(text.casefold()))
    return not (len(shared) >= 2 and 2 * len(shared) >= len(source_words))


def read_items(text, count):
    """`{id: text}` from a model's answer to the batched cue request, for the ids below `count` it holds a text for
    (the first text of an id wins); ValueError("unreadable answer") when it is not a JSON object with an `items` list."""
    try:
        listed = json_object(text).get("items")
    except ValueError:
        raise ValueError("unreadable answer") from None
    if not isinstance(listed, list):
        raise ValueError("unreadable answer")
    found = {}
    for entry in listed:
        number, said = (entry.get("id"), entry.get("text")) if isinstance(entry, dict) else (None, None)
        if isinstance(number, int) and not isinstance(number, bool) and 0 <= number < count \
                and isinstance(said, str) and number not in found:
            found[number] = said.strip().strip("\"'`").strip()
    return found


def check_cue(role, source, text, language):
    """None when `text`, a model's translation of the English cue or reason `source` into `language`, holds what any
    language must, else the short reason (docs/specs/language-cues.md). `role` is `cues.ROLE_CUE` or `cues.ROLE_REASON`.
    A translation is held to `opinion.guard.unsafe_problem` (no control character, a bidi override included, no link,
    none of the words this product does not use), as the history opinion's translations are (R7 of the 1.14.0 review)."""
    if "\n" in text or "\r" in text:
        return "translation has more than one line"
    cue = role == ROLE_CUE
    if not text.strip() or len(text) > (MAX_CUE_CHARS if cue else MAX_TRANSLATED) \
            or (cue and len(text.split()) > MAX_CUE_WORDS):
        return "translation is empty or too long"
    unsafe = _unsafe(text)
    if unsafe:
        return f"translation {unsafe}"
    if _praised(text):
        return "translation adds praise"
    if cue and any(c.isdigit() for c in text):
        return "translation adds a number"
    if not cue and _numbers(text) != _numbers(source):
        return "translation changes the numbers"
    if _english_time(text):
        return "translation keeps an English time phrase"
    return None if _in_language(source, text, language) else "translation is not in the language asked"
