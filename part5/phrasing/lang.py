"""The follower's language for fault lines (TICKET-046, docs/specs/second-opinion.md, ASM-014).

`resolve(tag)` maps a BCP 47 tag to a listed language (its primary subtag); anything else is English, and the tag
asked for is kept so the document can say so. For a language other than English a model is asked for one JSON
answer holding the English line and the translated line (`reply_instruction`, `read_pair`). The English line goes
through the existing word test (`template.line_problem`); the translated line through `check_translated`, which
holds what can be checked in any language: one line, the fault's time said once, no other number, no English time
phrase before it (TICKET-052) and no praise.
`json_object` is the one reader of a model's JSON answer (this module and `opinion.guard`).
"""
import json
import re
import unicodedata

from . import template

EN = "en"
# The languages Part 5 asks Muse Spark to write in, by primary subtag. A language left out falls back to English.
LANGUAGES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese",
    "nl": "Dutch", "sv": "Swedish", "pl": "Polish", "tr": "Turkish", "ru": "Russian", "ar": "Arabic",
    "hi": "Hindi", "id": "Indonesian", "vi": "Vietnamese", "ja": "Japanese", "ko": "Korean", "zh": "Chinese",
}
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


def check_translated(fault, line, timed):
    """None when the translated `line` holds what a line in any language must, else the short reason."""
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
