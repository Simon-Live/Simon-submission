"""Fault lines in the follower's language (docs/specs/second-opinion.md AC-LA-01 to AC-LA-04, TICKET-046, ASM-014).

The model is mocked; no socket is opened.
"""
import json

import pytest

from part5 import cli, phrasing
from part5.phrasing import lang, prompt, template
from part5.phrasing.local_llm import messages
from test_api import EXPECTED_PATH, FOOT_PATH, analyse, error_of, samples
from test_phrasing import clean_env, no_network  # noqa: F401
from test_phrasing_muse_spark import Client, live, reply  # noqa: F401
from test_phrasing_timed import RIGHT_FOOT, timed

ENGLISH = "Your right foot drifts too far to the right at 1.9 s."
SPANISH = "Tu pie derecho se va demasiado a la derecha a los 1,9 s."


def pair(english=ENGLISH, line=SPANISH):
    return reply(json.dumps({"en": english, "line": line}, ensure_ascii=False))


# ---- AC-LA-01: the tag ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("tag,expected", [
    (None, ("en", None)), ("", ("en", None)), ("en", ("en", None)), ("es", ("es", None)),
    ("es-MX", ("es", "es-MX")), ("pt-BR", ("pt", "pt-BR")), ("ES", ("es", "ES")), ("xx", ("en", "xx")),
    ("klingon", ("en", "klingon")), ("12", ("en", "12")), ("es_MX", ("en", "es_MX")),
])
def test_ac_la_01_a_tag_resolves_to_a_listed_language_or_english(tag, expected):
    assert lang.resolve(tag) == expected


def test_ac_la_01_an_unlisted_tag_is_kept_as_requested_and_english_is_written(live):  # noqa: F811
    lines, record = phrasing.phrase([RIGHT_FOOT], "muse-spark", client=Client(reply(ENGLISH)), lang="tlh")
    assert record["lang"] == "en" and record["lang_requested"] == "tlh"
    assert lines == [ENGLISH] and record["faults"][0]["lang"] == "en"


# ---- AC-LA-02: the pair --------------------------------------------------------------------------------------------
def test_ac_la_02_a_spanish_pair_shows_the_spanish_line(live):  # noqa: F811
    client = Client(pair())
    lines, record = phrasing.phrase([RIGHT_FOOT], "muse-spark", client=client, lang="es")
    assert lines == [SPANISH]
    assert record["lang"] == "es" and "lang_requested" not in record
    assert record["faults"][0] == {"backend": "muse-spark", "model": "meta-models/muse-spark-open-1026",
                                   "fallback_reason": None, "lang": "es", "text": SPANISH}
    system = client.requests[0]["body"]["messages"][0]["content"]
    assert "Spanish" in system and '"line"' in system and "Reply with only the sentence." not in system


@pytest.mark.parametrize("answer,reason", [
    (pair(english="Your left foot drifts too far to the right at 1.9 s."), "muse-spark: wrong side"),
    (pair(english="Your right foot drifts too far right at 1.9 s, nice effort."), "muse-spark: adds praise"),
    (pair(line="Tu pie derecho se va demasiado a la derecha."), "muse-spark: translated line does not say the time once"),
    (pair(line="Tu pie derecho se va 8 grados a la derecha a los 1,9 s."),
     "muse-spark: translated line does not say the time once"),
    (pair(line="Tu pie derecho se va demasiado a la derecha a los 2,4 s."), "muse-spark: translated line has the wrong time"),
    (pair(line="Tu pie derecho\nse va a la derecha a los 1,9 s."), "muse-spark: translated line has more than one line"),
    (reply("Tu pie derecho se va demasiado a la derecha a los 1,9 s."), "muse-spark: unreadable answer"),
    (reply('{"en": "Your right foot drifts too far right at 1.9 s."}'), "muse-spark: unreadable answer"),
])
def test_ac_la_02_a_pair_that_breaks_a_rule_falls_back_to_the_english_template(live, answer, reason):  # noqa: F811
    lines, record = phrasing.phrase([RIGHT_FOOT], "muse-spark", client=Client(answer), lang="es")
    assert lines == [RIGHT_FOOT["text_timed"]]
    entry = record["faults"][0]
    assert entry["backend"] == "template" and entry["lang"] == "en" and entry["fallback_reason"] == reason
    assert "Tu pie" not in json.dumps(record["faults"][0]["fallback_reason"])


def test_ac_la_02_the_translated_check_reads_comma_decimals_and_untimed_lines():
    assert lang.check_translated(RIGHT_FOOT, SPANISH, timed=True) is None
    assert lang.check_translated(RIGHT_FOOT, "pied droit trop à droite à 1.9 s", timed=True) is None
    assert lang.check_translated(RIGHT_FOOT, "x" * 201, timed=True) == "translated line is empty or too long"
    assert lang.check_translated(RIGHT_FOOT, "pie derecho demasiado afuera", timed=False) is None
    assert lang.check_translated(RIGHT_FOOT, "pie derecho a 2 s", timed=False) == "translated line adds a number"


def test_ac_la_02_an_untimed_fault_asks_for_the_pair_too():
    fault = dict(RIGHT_FOOT)
    fault.pop("at_s")
    system = messages(fault, language="fr")[0]["content"]
    assert "French" in system and '"en"' in system
    assert messages(fault)[0]["content"].endswith(".") and "French" not in messages(fault)[0]["content"]


def test_every_word_of_the_translated_line_is_asked_for_in_that_language():
    system = prompt.system_timed(0, "de")
    assert "every word in German (the sentence shape too)" in system


# ---- AC-LA-03 and AC-LA-04: fallbacks and the record ------------------------------------------------------------
def test_ac_la_03_the_template_backend_says_it_writes_english():
    lines, record = phrasing.phrase([RIGHT_FOOT], "template", lang="es")
    assert lines == [RIGHT_FOOT["text_timed"]] and record["lang"] == "es"
    assert record["faults"][0]["lang"] == "en" and record["faults"][0]["fallback_reason"] == phrasing.ENGLISH_ONLY


def test_ac_la_03_english_keeps_the_record_without_a_reason():
    lines, record = phrasing.phrase([RIGHT_FOOT], "template")
    assert record["lang"] == "en" and record["faults"][0]["fallback_reason"] is None
    assert record["faults"][0]["text"] == lines[0]


def test_ac_la_04_the_cli_writes_the_language_and_each_line_once(tmp_path, capsys):
    out = tmp_path / "a.json"
    assert cli.main(["analyse", "--expected", str(EXPECTED_PATH), "--follower", str(FOOT_PATH), "--out", str(out),
                     "--lang", "pt-BR"]) == 0
    doc = json.loads(out.read_text())
    assert doc["schema_version"] == "1.12.0"
    assert doc["phrasing"]["lang"] == "pt" and doc["phrasing"]["lang_requested"] == "pt-BR"
    assert [e["text"] for e in doc["phrasing"]["faults"]] == [f["coaching"] for f in doc["faults"]]
    assert "second_opinion" not in doc   # no clip given: the document has no block


def test_ac_la_01_the_api_takes_lang_and_refuses_a_non_string():
    status, _, body = analyse(*samples(), lang="es")
    assert status == 200 and body["analysis"]["phrasing"]["lang"] == "es"
    assert error_of(analyse(*samples(), lang=["es"]))[:2] == (400, "lang")


def test_the_spanish_live_line_of_2026_10_31_passes_both_checks():
    """The live line recorded in the lane evidence (pexels-8837221, fault 3) passes the twin and the translated check."""
    fault = timed("upper_arm_forward", "left", "less", None, at_s=1.1, text_timed="left arm too low at 1.1 s")
    assert template.line_problem(fault, "Around 1.1 s, your left arm is too low.", timed=True) is None
    assert lang.check_translated(fault, "Alrededor de 1.1 s tu brazo izquierdo está demasiado bajo.", timed=True) is None


# ---- the review of the rubric integration: B3, B4, R11, R14, R15 -----------------------------------------------------
@pytest.mark.parametrize("line", [
    "Buen trabajo, great job, tu pie derecho se va demasiado a la derecha a los 1,9 s.",
    "Buen trabajo: tu pie derecho se va demasiado a la derecha a los 1,9 s.",
    "Tu pie derecho se va demasiado a la derecha a los 1,9 s, bien hecho.",
    "Bravo, ton pied droit part trop a droite a 1.9 s.",
    "Félicitations ! Votre pied droit part trop à droite à 1.9 s.",
    "Gut gemacht, dein rechter Fuß geht bei 1,9 s zu weit nach rechts.",
    "Ótimo trabalho, seu pé direito vai longe demais à direita aos 1,9 s.",
    "Buen​trabajo, tu pie derecho se va a la derecha a los 1,9 s.",
    "Buen-trabajo, tu pie derecho se va a la derecha a los 1,9 s.",
    "Tu pie derecho se va a la derecha a los 1,9 s, nice effort.",
])
def test_review_b3_a_translated_line_with_praise_is_refused(line):
    assert lang.check_translated(RIGHT_FOOT, line, timed=True) == "translated line adds praise"
    assert lang.check_translated(RIGHT_FOOT, line, timed=False) == "translated line adds praise"


@pytest.mark.parametrize("line", [
    SPANISH,
    "Tu pie derecho se va demasiado bien a la derecha a los 1,9 s.",   # "bien" next to nothing praising
    "Tu pie derecho sigue el trabajo del profesor a los 1,9 s.",       # "trabajo" alone is not praise
    "Ton pied droit part trop loin à droite à 1.9 s.",
])
def test_review_b3_a_translated_line_without_praise_still_passes(line):
    assert lang.check_translated(RIGHT_FOOT, line, timed=True) is None


def test_review_b3_a_praised_pair_makes_the_registry_fall_back_to_the_english_template(live):  # noqa: F811
    answer = pair(line="Buen trabajo, tu pie derecho se va demasiado a la derecha a los 1,9 s.")
    lines, record = phrasing.phrase([RIGHT_FOOT], "muse-spark", client=Client(answer), lang="es")
    assert lines == [RIGHT_FOOT["text_timed"]]
    entry = record["faults"][0]
    assert (entry["backend"], entry["lang"]) == ("template", "en")
    assert entry["fallback_reason"] == "muse-spark: translated line adds praise"


@pytest.mark.parametrize("tag", ["  ", "\t", " \t\n ", "​", "\x00", "      "])
def test_review_b4_a_tag_of_white_space_is_english_with_no_tag_asked_for(tag):
    assert lang.resolve(tag) == ("en", None)


def test_review_b4_the_cli_takes_a_blank_lang_as_english(tmp_path):
    for tag in ("  ", "\t"):
        out = tmp_path / "a.json"
        assert cli.main(["analyse", "--expected", str(EXPECTED_PATH), "--follower", str(FOOT_PATH), "--out", str(out),
                         "--lang", tag]) == 0
        record = json.loads(out.read_text())["phrasing"]
        assert record["lang"] == "en" and "lang_requested" not in record


def test_review_b4_the_api_takes_a_blank_lang_as_english():
    for tag in ("  ", "\t", " ​ "):
        status, _, body = analyse(*samples(), lang=tag)
        assert status == 200
        record = body["analysis"]["phrasing"]
        assert record["lang"] == "en" and "lang_requested" not in record


def test_review_r11_the_tag_asked_for_is_cleaned_and_capped():
    assert lang.resolve("es\x00-MX") == ("es", "es-MX")
    assert lang.resolve("​es-MX\n") == ("es", "es-MX")
    long_tag = "es-" + "-".join(["abcdefgh"] * 40)   # well formed, 363 characters
    language, asked = lang.resolve(long_tag)
    assert language == "es" and asked == long_tag[:lang.MAX_REQUESTED] and len(asked) == 35
    language, asked = lang.resolve("tlh-" + "\x07" * 3 + "y" * 100)   # malformed: English, what was asked kept capped
    assert language == "en" and asked == ("tlh-" + "y" * 100)[:35]


def test_review_r11_a_long_tag_reaches_the_document_capped(tmp_path):
    out = tmp_path / "a.json"
    long_tag = "pt-" + "-".join(["abcdefgh"] * 40)
    assert cli.main(["analyse", "--expected", str(EXPECTED_PATH), "--follower", str(FOOT_PATH), "--out", str(out),
                     "--lang", long_tag]) == 0
    record = json.loads(out.read_text())["phrasing"]
    assert record["lang"] == "pt" and record["lang_requested"] == long_tag[:35]


@pytest.mark.parametrize("text,doc", [
    ('{"a": 1}', {"a": 1}), ('Sure! {"a": {"b": 2}} Done.', {"a": {"b": 2}}), ('```json\n{"en": "x"}\n```', {"en": "x"}),
])
def test_review_r14_one_reader_for_a_models_json_object(text, doc):
    assert lang.json_object(text) == doc


@pytest.mark.parametrize("text", ["no object here", "[1, 2]", "}{", '{"a": ', "{not json}", "", "{}}{"])
def test_review_r14_a_text_without_a_json_object_is_a_value_error(text):
    with pytest.raises(ValueError):
        lang.json_object(text)


def test_review_r14_the_guard_and_the_pair_reader_use_that_one_reader():
    from part5.opinion import guard
    assert guard.json_object is lang.json_object
    assert lang.read_pair(' {"en": " Right foot. ", "line": "\'Pie derecho.\'"} ') == ("Right foot.", "Pie derecho.")
    for text in ("not json", "[1]", '{"en": "x"}', '{"en": "x", "line": " "}'):
        with pytest.raises(ValueError, match="unreadable answer"):
            lang.read_pair(text)


def test_review_r15_the_names_the_guard_uses_are_public():
    assert template.GROUP_RX and template.TIME.pattern and callable(template.praise)
    assert not any(hasattr(template, old) for old in ("_GROUP_RX", "_TIME", "_praise"))
