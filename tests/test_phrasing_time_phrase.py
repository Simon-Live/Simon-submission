"""A translated fault line keeps no English time phrase (TICKET-052, docs/specs/second-opinion.md AC-LA-02).

The model is mocked; no socket is opened and no key is read. The recorded lines are the two live runs of 2026-10-31
and 2026-11-01, kept in `tests/fixtures/phrasing/recorded-es-lines.json` (an extract of `progress/`, which is
workspace-only) and read as data, never sent anywhere.
"""
import json
from pathlib import Path

import pytest

from part5 import phrasing
from part5.phrasing import lang, prompt, template
from test_phrasing import clean_env, no_network  # noqa: F401
from test_phrasing_lang import pair
from test_phrasing_muse_spark import Client, live  # noqa: F401
from test_phrasing_timed import RIGHT_FOOT

ROOT = Path(__file__).resolve().parent.parent
REASON = "translated line keeps an English time phrase"
ENGLISH = "Your right foot drifts too far to the right at 1.9 s."
SPANISH_AT = "At 1.9 s, tu pie derecho se va demasiado a la derecha."

# A correct time phrase of RIGHT_FOOT (right foot too far right at 1.9 s) in each listed language, in the several ways
# the language says it. None of these may be refused: the words before the number (a, a las, a los, en, bei, um, aos,
# as, rond, om, vid, w ...) are the ones the English set must leave out.
PHRASES = {
    "es": ("Tu pie derecho se va demasiado a la derecha a los 1,9 s.",
           "A las 1,9 s tu pie derecho se va demasiado a la derecha.",
           "A 1,9 s, tu pie derecho se va demasiado a la derecha.",
           "Alrededor de 1,9 s tu pie derecho se va demasiado a la derecha.",
           "En 1,9 s tu pie derecho se va demasiado a la derecha.",
           "Hacia los 1.9 s tu pie derecho se va demasiado a la derecha.",
           "Cerca de 1,9 s tu pie derecho se va demasiado a la derecha.",
           "Tras 1,9 s tu pie derecho se va demasiado a la derecha.",
           "Antes de 1,9 s tu pie derecho se va demasiado a la derecha."),
    "fr": ("À 1,9 s, ton pied droit part trop à droite.",
           "Vers 1,9 s, ton pied droit part trop à droite.",
           "Autour de 1,9 s, ton pied droit part trop à droite.",
           "Environ 1.9 s, ton pied droit part trop à droite.",
           "Après 1,9 s, ton pied droit part trop à droite.",
           "Avant 1,9 s, ton pied droit part trop à droite.",
           "Ton pied droit part trop à droite à 1.9 s."),
    "de": ("Bei 1,9 s geht dein rechter Fuß zu weit nach rechts.",
           "Um 1,9 s geht dein rechter Fuß zu weit nach rechts.",
           "Nach 1,9 s geht dein rechter Fuß zu weit nach rechts.",
           "Vor 1,9 s geht dein rechter Fuß zu weit nach rechts.",
           "Gegen 1,9 s geht dein rechter Fuß zu weit nach rechts.",
           "Etwa bei 1,9 s geht dein rechter Fuß zu weit nach rechts.",
           "Ungefähr um 1.9 s geht dein rechter Fuß zu weit nach rechts."),
    "it": ("A 1,9 s il tuo piede destro va troppo a destra.",
           "Intorno a 1,9 s il tuo piede destro va troppo a destra.",
           "Attorno a 1,9 s il tuo piede destro va troppo a destra.",
           "Verso 1,9 s il tuo piede destro va troppo a destra.",
           "Dopo 1,9 s il tuo piede destro va troppo a destra.",
           "Prima di 1,9 s il tuo piede destro va troppo a destra.",
           "Il tuo piede destro va troppo a destra a 1.9 s."),
    "pt": ("Aos 1,9 s o seu pé direito vai longe demais à direita.",
           "Às 1,9 s o seu pé direito vai longe demais à direita.",
           "Por volta de 1,9 s o seu pé direito vai longe demais à direita.",
           "Em 1,9 s o seu pé direito vai longe demais à direita.",
           "A 1,9 s o seu pé direito vai longe demais à direita.",
           "Perto de 1.9 s o seu pé direito vai longe demais à direita.",
           "Após 1,9 s o seu pé direito vai longe demais à direita.",
           "Antes de 1,9 s o seu pé direito vai longe demais à direita."),
    "nl": ("Om 1,9 s gaat je rechtervoet te ver naar rechts.",
           "Rond 1,9 s gaat je rechtervoet te ver naar rechts.",
           "Bij 1,9 s gaat je rechtervoet te ver naar rechts.",
           "Omstreeks 1.9 s gaat je rechtervoet te ver naar rechts.",
           "Na 1,9 s gaat je rechtervoet te ver naar rechts.",
           "Voor 1,9 s gaat je rechtervoet te ver naar rechts.",
           "Ongeveer bij 1,9 s gaat je rechtervoet te ver naar rechts."),
    "sv": ("Vid 1,9 s går din högra fot för långt åt höger.",
           "Omkring 1,9 s går din högra fot för långt åt höger.",
           "Runt 1.9 s går din högra fot för långt åt höger.",
           "Cirka 1,9 s går din högra fot för långt åt höger.",
           "Efter 1,9 s går din högra fot för långt åt höger.",
           "Före 1,9 s går din högra fot för långt åt höger."),
    "pl": ("W 1,9 s twoja prawa stopa ucieka za daleko w prawo.",
           "Około 1,9 s twoja prawa stopa ucieka za daleko w prawo.",
           "Przy 1,9 s twoja prawa stopa ucieka za daleko w prawo.",
           "Po 1,9 s twoja prawa stopa ucieka za daleko w prawo.",
           "Przed 1.9 s twoja prawa stopa ucieka za daleko w prawo.",
           "Na 1,9 s twoja prawa stopa ucieka za daleko w prawo."),
    "tr": ("1,9 s'de sağ ayağın çok fazla sağa kayıyor.",
           "Yaklaşık 1,9 s'de sağ ayağın çok fazla sağa kayıyor.",
           "1.9 s civarında sağ ayağın çok fazla sağa kayıyor.",
           "Sağ ayağın 1,9 s'de çok fazla sağa kayıyor."),
    "id": ("Pada 1,9 s, kaki kananmu terlalu jauh ke kanan.",
           "Sekitar 1,9 s, kaki kananmu terlalu jauh ke kanan.",
           "Di 1,9 s kaki kananmu terlalu jauh ke kanan.",
           "Setelah 1,9 s, kaki kananmu terlalu jauh ke kanan.",
           "Sebelum 1.9 s, kaki kananmu terlalu jauh ke kanan.",
           "Kira-kira 1,9 s, kaki kananmu terlalu jauh ke kanan."),
    "vi": ("Lúc 1,9 s, chân phải của bạn lệch quá xa sang phải.",
           "Vào lúc 1,9 s, chân phải của bạn lệch quá xa sang phải.",
           "Khoảng 1,9 s, chân phải của bạn lệch quá xa sang phải.",
           "Tại 1.9 s, chân phải của bạn lệch quá xa sang phải.",
           "Sau 1,9 s, chân phải của bạn lệch quá xa sang phải.",
           "Trước 1,9 s, chân phải của bạn lệch quá xa sang phải.",
           "Gần 1,9 s, chân phải của bạn lệch quá xa sang phải."),
    # the languages in other scripts, the same way
    "ru": ("На 1,9 с твоя правая стопа уходит слишком далеко вправо.",
           "Около 1,9 с твоя правая стопа уходит слишком далеко вправо.",
           "После 1.9 с твоя правая стопа уходит слишком далеко вправо."),
    "ar": ("عند 1.9 ث تنحرف قدمك اليمنى كثيرا نحو اليمين.",
           "حوالي 1.9 ث تنحرف قدمك اليمنى كثيرا نحو اليمين.",
           "بعد 1.9 ث تنحرف قدمك اليمنى كثيرا نحو اليمين."),
    "hi": ("1.9 s पर आपका दायां पैर बहुत ज्यादा दाईं ओर जा रहा है।",
           "लगभग 1.9 s पर आपका दायां पैर बहुत ज्यादा दाईं ओर जा रहा है।"),
    "ja": ("1.9秒で右足が右に出すぎています。", "約1.9秒の時点で右足が右に出すぎています。"),
    "ko": ("1.9초에 오른발이 오른쪽으로 너무 많이 벗어납니다.", "약 1.9초에 오른발이 오른쪽으로 너무 많이 벗어납니다."),
    "zh": ("在1.9秒时，右脚向右偏得太远。", "大约1.9秒时，右脚向右偏得太远。"),
}
CORRECT = [(code, line) for code, lines in PHRASES.items() for line in lines]


def check(line, timed=True):
    return lang.check_translated(RIGHT_FOOT, line, timed)


# ---- the word set and the time phrases of the listed languages -------------------------------------------------------
def test_the_english_set_is_the_nine_words_of_the_ruling_and_leaves_out_the_small_words():
    assert lang.ENGLISH_TIME_WORDS == ("at", "around", "about", "by", "near", "after", "before", "approximately",
                                       "roughly")
    assert {"in", "a", "en", "um", "om", "on", "to", "bei", "vers"} & set(lang.ENGLISH_TIME_WORDS) == set()


def test_every_listed_language_has_pinned_time_phrases():
    assert set(PHRASES) == set(lang.LANGUAGES) - {lang.EN}


@pytest.mark.parametrize("code,line", CORRECT)
def test_a_correct_time_phrase_in_a_listed_language_passes(code, line):
    assert check(line) is None


# ---- what is refused -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("word", lang.ENGLISH_TIME_WORDS)
@pytest.mark.parametrize("cased", [str.lower, str.capitalize, str.upper, str.swapcase])
def test_each_english_time_word_before_the_time_is_refused_in_any_letter_case(word, cased):
    assert check(f"{cased(word)} 1,9 s tu pie derecho se va demasiado a la derecha.") == REASON
    assert check(f"Tu pie derecho se va demasiado a la derecha, {cased(word)} 1.9 s.") == REASON


@pytest.mark.parametrize("line", [
    SPANISH_AT,
    "At 1,9 s, tu pie derecho se va demasiado a la derecha.",
    "At 1.9, tu pie derecho se va demasiado a la derecha.",              # without "s"
    "At 1,9, tu pie derecho se va demasiado a la derecha.",
    "At 1.9s, tu pie derecho se va demasiado a la derecha.",             # "s" glued to the number
    "At  1.9 s, tu pie derecho se va demasiado a la derecha.",
    "At\t1.9 s, tu pie derecho se va demasiado a la derecha.",
    "At\N{NO-BREAK SPACE}1.9 s, tu pie derecho se va demasiado a la derecha.",
    "A\N{ZERO WIDTH SPACE}t 1.9 s, tu pie derecho se va demasiado a la derecha.",    # hidden inside the word
    "At\N{ZERO WIDTH SPACE}1.9 s, tu pie derecho se va demasiado a la derecha.",     # the only separator
    "Tu pie derecho se va demasiado a la derecha, around 1.9 s.",
    "Approximately 1.9 s, tu pie derecho se va demasiado a la derecha.",
    "At 1.9 s, 右足が右に出すぎています。",                                              # another script
    "At 1.9 s, ton pied droit part trop à droite.",
])
def test_an_english_time_phrase_in_a_translated_line_is_refused(line):
    assert check(line) == REASON


def test_other_reasons_come_first_and_an_untimed_line_is_not_read_for_a_time():
    assert check("At 2.4 s, tu pie derecho se va demasiado a la derecha.") == "translated line has the wrong time"
    assert check("At 1.9 s, tu pie derecho, a las 1,9 s.") == "translated line does not say the time once"
    assert check("Great job, " + SPANISH_AT) == "translated line adds praise"
    assert check("At 1.9 s, tu pie derecho\nse va a la derecha.") == "translated line has more than one line"
    assert check("At the start, tu pie derecho se va demasiado a la derecha.", timed=False) is None
    assert check("At 1.9 s, tu pie derecho se va a la derecha.", timed=False) == "translated line adds a number"


@pytest.mark.parametrize("line", [
    "Tu pie derecho se va demasiado a la derecha at the end, a los 1,9 s.",   # English elsewhere: ASM-014's job
    "Tu pie derecho se va demasiado a la derecha, combat 1,9 s.",             # "at" inside a word
    "Tu pie derecho se va demasiado a la derecha, nearby 1,9 s.",             # "by" ends a longer word
    "Tu pie derecho se va demasiado a la derecha, át 1,9 s.",                 # an accented word is not "at"
    "At the start, tu pie derecho se va demasiado a la derecha a los 1,9 s.",
])
def test_only_a_whole_english_word_directly_before_the_time_is_refused(line):
    assert check(line) is None


# ---- the registry: the line falls back to the English template -------------------------------------------------------
def test_ac_la_02_a_line_with_an_english_time_phrase_falls_back_to_the_english_template(live):  # noqa: F811
    lines, record = phrasing.phrase([RIGHT_FOOT], "muse-spark", client=Client(pair(line=SPANISH_AT)), lang="es")
    assert lines == [RIGHT_FOOT["text_timed"]]
    assert record["lang"] == "es"
    assert record["faults"][0] == {"backend": "template", "model": None, "fallback_reason": f"muse-spark: {REASON}",
                                   "lang": "en", "text": RIGHT_FOOT["text_timed"]}


@pytest.mark.parametrize("code,line", [
    ("fr", "Around 1.9 s, ton pied droit part trop à droite."),
    ("de", "About 1,9 s geht dein rechter Fuß zu weit nach rechts."),
    ("pt", "By 1,9 s o seu pé direito vai longe demais à direita."),
    ("ja", "Near 1.9 s 右足が右に出すぎています。"),
])
def test_ac_la_02_an_english_time_phrase_in_the_other_listed_languages_falls_back(live, code, line):  # noqa: F811
    lines, record = phrasing.phrase([RIGHT_FOOT], "muse-spark", client=Client(pair(line=line)), lang=code)
    assert lines == [RIGHT_FOOT["text_timed"]] and record["lang"] == code and record["faults"][0]["lang"] == "en"
    assert record["faults"][0]["fallback_reason"] == f"muse-spark: {REASON}"


def test_ac_la_02_a_correct_pair_in_each_latin_script_language_is_kept(live):  # noqa: F811
    for code in ("es", "fr", "de", "it", "pt", "nl", "sv", "pl", "tr", "id", "vi"):
        line = PHRASES[code][0]
        lines, record = phrasing.phrase([RIGHT_FOOT], "muse-spark", client=Client(pair(line=line)), lang=code)
        entry = record["faults"][0]
        assert lines == [line] and entry["lang"] == code and entry["fallback_reason"] is None


# ---- the recorded lines ----------------------------------------------------------------------------------------------
# The two live documents are workspace-only (`progress/` is not published), so the tests read the lines and the
# measured faults from a committed extract of them. `source` names the document each came from.
FIXTURE = ROOT / "tests" / "fixtures" / "phrasing" / "recorded-es-lines.json"
# (document, fault index) of the recorded lines that open with the English "At 0.0 s": the only two that change verdict
ENGLISH_AT = {("second-opinion-live-20261031.json", 0), ("second-opinion-live-20261101.json", 0)}


def documents():
    """{name of the live document: its extract} from the fixture: `source`, the measured `faults` (without
    `coaching`) and the `phrasing` record (`lang`, and `lang` and `text` per fault)."""
    return {Path(doc["source"]).name: doc for doc in json.loads(FIXTURE.read_text())["documents"]}


def recorded_lines(doc):
    """[(fault, translated line)] of a recorded analysis whose phrasing is in a language other than English."""
    assert doc["phrasing"]["lang"] == "es"
    entries = doc["phrasing"]["faults"]
    assert [e["lang"] for e in entries] == ["es"] * len(doc["faults"])
    return [(fault, entry["text"]) for fault, entry in zip(doc["faults"], entries)]


def twin(fault):
    """An English twin that passes the word test: the fault's own template words."""
    text = fault["text_timed"]
    assert template.line_problem(fault, text, timed=True) is None
    return text[0].upper() + text[1:] + "."


def test_the_two_recorded_at_lines_are_refused_and_fall_back_with_lang_en(live):  # noqa: F811
    assert sorted(documents()) == sorted({name for name, _ in ENGLISH_AT})
    for doc in documents().values():
        fault, line = recorded_lines(doc)[0]
        assert line.startswith("At 0.0 s, tus codos")
        lines, record = phrasing.phrase([fault], "muse-spark", client=Client(pair(twin(fault), line)), lang="es")
        assert lines == [fault["text_timed"]]
        assert record["lang"] == "es"
        assert record["faults"][0] == {"backend": "template", "model": None, "lang": "en",
                                       "fallback_reason": f"muse-spark: {REASON}", "text": fault["text_timed"]}


def test_the_other_recorded_spanish_lines_still_pass(live):  # noqa: F811
    kept = 0
    for name, doc in documents().items():
        for index, (fault, line) in enumerate(recorded_lines(doc)):
            if (name, index) in ENGLISH_AT:
                continue
            lines, record = phrasing.phrase([fault], "muse-spark", client=Client(pair(twin(fault), line)), lang="es")
            assert lines == [line] and record["faults"][0]["lang"] == "es", (name, index, line)
            assert record["faults"][0]["fallback_reason"] is None
            kept += 1
    assert kept == 8


def test_every_recorded_translated_line_keeps_its_verdict_except_the_two_at_lines():
    """The lines recorded as translated (the extract of the two live runs, and the goldens of `fixtures/output/`,
    which hold English only) all passed `check_translated` before TICKET-052; now exactly the two "At 0.0 s" lines
    do not."""
    docs = dict(documents())
    for path in sorted((ROOT / "fixtures" / "output").glob("*.json")):
        golden = json.loads(path.read_text())
        record = golden.get("phrasing") if isinstance(golden, dict) else None
        if isinstance(record, dict) and record.get("lang", "en") != "en":
            docs[path.name] = golden
    verdicts = {}
    for name, doc in docs.items():
        for index, (fault, line) in enumerate(recorded_lines(doc)):
            verdicts[(name, index)] = lang.check_translated(fault, line, fault.get("at_s") is not None)
    assert len(verdicts) == 10
    assert {key for key, verdict in verdicts.items() if verdict} == ENGLISH_AT
    assert {verdict for verdict in verdicts.values() if verdict} == {REASON}


def test_the_fixture_holds_only_the_faults_and_the_lines_of_its_sources():
    for name, doc in documents().items():
        assert name.startswith("second-opinion-live-") and doc["source"] == f"progress/{name}"
        assert set(doc) == {"source", "faults", "phrasing"}
        assert set(doc["phrasing"]) == {"lang", "faults"}
        assert all(set(entry) == {"lang", "text"} for entry in doc["phrasing"]["faults"])
        assert all("coaching" not in fault for fault in doc["faults"])


@pytest.mark.parametrize("name", sorted(documents()))
def test_the_fixture_matches_the_progress_document_it_was_extracted_from(name):
    doc = documents()[name]
    source = ROOT / doc["source"]
    if not source.is_file():   # `progress/` is workspace-only: absent from a published tree, so only this check skips
        pytest.skip(f"{doc['source']} is not in this tree")
    recorded = json.loads(source.read_text())
    assert doc["faults"] == [{k: v for k, v in fault.items() if k != "coaching"} for fault in recorded["faults"]]
    entries = recorded["phrasing"]["faults"]
    assert doc["phrasing"] == {"lang": recorded["phrasing"]["lang"],
                               "faults": [{"lang": e["lang"], "text": e["text"]} for e in entries]}
    assert [f["coaching"] for f in recorded["faults"]] == [e["text"] for e in doc["phrasing"]["faults"]]


# ---- the prompt: shape 0 without its English example -----------------------------------------------------------------
def test_the_first_sentence_shape_drops_its_english_example_when_the_reply_is_not_english():
    assert "At 1.9 s," in prompt.system_timed(0) and prompt.SHAPES[0] in prompt.system_timed(0)
    assert prompt.system_timed(0, "en") == prompt.system_timed(0)
    for code in lang.LANGUAGES:
        if code == lang.EN:
            continue
        system = prompt.system_timed(0, code)
        assert prompt.SHAPE_TIME_FIRST_OTHER in system and prompt.SHAPES[0] not in system
        assert "At 1.9 s" not in system and "At " not in prompt.SHAPE_TIME_FIRST_OTHER


def test_only_the_first_shape_changes_with_the_language():
    assert prompt.shape_for(0, "es") == prompt.SHAPE_TIME_FIRST_OTHER
    assert prompt.shape_for(6, "es") == prompt.SHAPE_TIME_FIRST_OTHER   # the first shape comes round again at 6
    for index in (1, 2, 3, 4, 5, 7):
        assert prompt.shape_for(index, "es") == prompt.shape_for(index) != prompt.SHAPE_TIME_FIRST_OTHER
    assert [prompt.shape_for(i) for i in range(8)][0] == prompt.SHAPES[0]


def test_a_request_in_spanish_carries_no_english_example_in_its_first_shape(live):  # noqa: F811
    client = Client(pair())
    phrasing.phrase([RIGHT_FOOT], "muse-spark", client=client, lang="es")
    system = client.requests[0]["body"]["messages"][0]["content"]
    assert prompt.SHAPE_TIME_FIRST_OTHER in system and "like: At 1.9 s" not in system
