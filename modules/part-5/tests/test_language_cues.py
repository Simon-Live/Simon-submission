"""The cues and reasons of an analysis in the follower's language (docs/specs/language-cues.md AC-LC-01 to AC-LC-10,
TICKET-080, ASM-015).

The model is a scripted client; no socket is opened, no key is read and no usage ledger but a temporary one is written.
"""
import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from part5 import cli, contract, doctor, phrasing
from part5.cues import ROLE_CUE, ROLE_REASON, CueField, cue_fields
from part5.output import OutputError, validate_analysis
from part5.phrasing import lang, local_llm, muse_spark, prompt
from part5.pipeline import run
from part5.score_report import score_block
from test_phrasing import clean_env, no_network  # noqa: F401
from test_phrasing_muse_spark import SENTINEL, Client, http_error, ledger_lines, live, reply  # noqa: F401
from test_web_logic import JOINTS_URL, node_major, run_node

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "contracts/analysis.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)
EXPECTED = str(ROOT / "fixtures/input/expected/exercise/animation.json")
TAKE = ROOT / "fixtures/input/followers/exercise/exercise_front_good_03_foot_out-right"   # the ticket's seed 5 Take 03
FEET = {"expected_feet": str(ROOT / "fixtures/input/expected-feet/exercise/feet.json"),
        "follower_feet": str(TAKE / "feet.json")}
CUE_EN, WHY_EN = "Step your right foot in", "Right foot too far right at 1.9 s"
GOOD = {"es": ("Acerca tu pie derecho", "Pie derecho demasiado a la derecha a 1,9 s"),
        "ar": ("قرّب قدمك اليمنى إلى الداخل", "القدم اليمنى بعيدة جدًا إلى اليمين عند 1.9 ث"),
        "hi": ("अपना दाहिना पैर अंदर लाएं", "दाहिना पैर बहुत ज़्यादा दाईं ओर 1.9 से.")}
PATHS = ["faults[0].cue", "score.timeline[0].misses[0].cue", "insights[0].cue", "insights[0].why"]
FAULT_PAIR = {"en": "Your right foot drifts too far to the right at 1.9 s.",
              "line": "Tu pie derecho se va demasiado a la derecha a los 1,9 s."}


def take_run(**options):
    return run(EXPECTED, str(TAKE / "skeleton.json"), score=score_block, **FEET, **options).analysis


@pytest.fixture(scope="module")
def english():
    """Seed 5 Take 03 (`exercise_front_good_03_foot_out-right`) with its feet files, the template and no language."""
    return take_run()


@pytest.fixture(scope="module")
def spanish_template():
    """The same take asked for in Spanish with the template: nothing is written in Spanish."""
    return take_run(lang="es")


def items(*texts):
    """A scripted model answer to the batched cue request: the texts with the ids 0, 1, ..."""
    return reply(json.dumps({"items": [{"id": n, "text": t} for n, t in enumerate(texts)]}, ensure_ascii=False))


def cued(doc, client, language="es", backend="muse-spark", **options):
    """`doc` (a copy) after `phrase_cues`: the record of the cues."""
    out = copy.deepcopy(doc)
    out["phrasing"]["lang"] = language
    return phrasing.phrase_cues(out, backend, client=client, live=True, lang=language, **options)


def entry_of(doc, path):
    return next(e for e in doc["phrasing"]["cues"] if e["path"] == path)


# ---- AC-LC-01: which strings are English today, and what the collector lists -------------------------------------------
def test_ac_lc_01_every_cue_and_reason_of_a_spanish_template_analysis_is_english(english, spanish_template):
    """The strings of the take the ticket names stay English whatever the language asked for (the template writes English)."""
    assert spanish_template["phrasing"]["lang"] == "es"
    assert [f.path for f in cue_fields(spanish_template)] == PATHS
    assert [f.text for f in cue_fields(spanish_template)] == [CUE_EN, CUE_EN, CUE_EN, WHY_EN]
    assert [f.role for f in cue_fields(spanish_template)] == [ROLE_CUE, ROLE_CUE, ROLE_CUE, ROLE_REASON]
    assert cue_fields(spanish_template) == cue_fields(english)


def test_ac_lc_01_the_collector_lists_misses_tempo_and_insights_in_document_order():
    doc = {"faults": [{"cue": "Bend your knees more"}, {"cue": None}, {"cue": "Raise your arms higher"}],
           "score": {"timeline": [{"misses": [{"cue": "Bend your knees more"}, {"text": "no cue"}],
                                   "tempo": {"ratio": 0.7, "cue": "Slow down to match the trainer"}},
                                  {"misses": [], "tempo": {"ratio": 1.0, "cue": None}},
                                  {"misses": [{"cue": "Raise your arms higher"}]},
                                  "not a window"],
                     "tempo": {"ratio": 0.7, "cue": "Slow down to match the trainer"}},
           "insights": [{"cue": "Bend your knees more", "why": "Left knee not bent enough (3 of 8 reps)"},
                        {"cue": "Slow down to match the trainer", "why": "You took 70% of the trainer's time"}]}
    assert cue_fields(doc) == [
        CueField("faults[0].cue", ROLE_CUE, "Bend your knees more"),
        CueField("faults[2].cue", ROLE_CUE, "Raise your arms higher"),
        CueField("score.timeline[0].misses[0].cue", ROLE_CUE, "Bend your knees more"),
        CueField("score.timeline[0].tempo.cue", ROLE_CUE, "Slow down to match the trainer"),
        CueField("score.timeline[2].misses[0].cue", ROLE_CUE, "Raise your arms higher"),
        CueField("score.tempo.cue", ROLE_CUE, "Slow down to match the trainer"),
        CueField("insights[0].cue", ROLE_CUE, "Bend your knees more"),
        CueField("insights[0].why", ROLE_REASON, "Left knee not bent enough (3 of 8 reps)"),
        CueField("insights[1].cue", ROLE_CUE, "Slow down to match the trainer"),
        CueField("insights[1].why", ROLE_REASON, "You took 70% of the trainer's time"),
    ]
    assert cue_fields({}) == [] and cue_fields({"faults": "x", "score": None, "insights": [None]}) == []


# ---- AC-LC-02: one batched call, written by the model, with provenance ------------------------------------------------
@pytest.mark.parametrize("tag", ["es", "ar", "hi"])
def test_ac_lc_02_one_batched_call_writes_every_cue_and_names_the_model(english, live, tag):  # noqa: F811
    client = Client(items(*GOOD[tag]))
    doc = cued(english, client, tag)
    assert len(client.requests) == 1 and len(ledger_lines(live)) == 1
    entries = doc["phrasing"]["cues"]
    assert [e["path"] for e in entries] == PATHS
    assert [e["text"] for e in entries] == [GOOD[tag][0]] * 3 + [GOOD[tag][1]]
    for e in entries:
        assert e["lang"] == tag and e["backend"] == "muse-spark" and e["fallback_reason"] is None
        assert e["model"] == "meta-models/muse-spark-open-1026"
    assert doc["phrasing"]["native_review"] is False
    assert validate_analysis(doc) is doc and list(VALIDATOR.iter_errors(doc)) == []


def test_ac_lc_02_the_request_carries_each_distinct_english_text_once_and_nothing_about_the_person(english, live):  # noqa: F811
    client = Client(items(*GOOD["ar"]))
    cued(english, client, "ar")
    request = client.requests[0]
    system, user = request["body"]["messages"][0]["content"], request["body"]["messages"][1]["content"]
    assert "into Arabic" in system and "Hindi" not in system and request["body"]["max_tokens"] == muse_spark.BATCH_MAX_TOKENS
    assert json.loads(user) == [{"id": 0, "kind": "cue", "text": CUE_EN}, {"id": 1, "kind": "reason", "text": WHY_EN}]
    assert "fixtures" not in user and "foot_out" not in user and SENTINEL not in json.dumps(request["body"])
    assert request["headers"]["Authorization"] == f"Bearer {SENTINEL}" and request["timeout_s"] == phrasing.CUES_TIMEOUT_S
    assert request["body"]["reasoning_effort"] == "low"


def test_ac_lc_02_a_cue_shared_by_several_paths_is_asked_once_and_the_same_cue_and_reason_are_kept_apart(live):  # noqa: F811
    doc = {"faults": [{"cue": "Bend your knees more"}, {"cue": "Bend your knees more"}], "phrasing": {"lang": "es"},
           "insights": [{"cue": "Bend your knees more", "why": "Bend your knees more"}]}
    client = Client(items("Dobla más las rodillas", "Dobla más las rodillas"))
    out = phrasing.phrase_cues(doc, "muse-spark", client=client, live=True, lang="es")
    asked = json.loads(client.requests[0]["body"]["messages"][1]["content"])
    assert [a["kind"] for a in asked] == ["cue", "reason"] and len(asked) == 2   # the same words as a cue and as a reason
    assert [e["text"] for e in out["phrasing"]["cues"]] == ["Dobla más las rodillas"] * 4


def test_ac_lc_02_the_key_and_the_models_text_stay_out_of_the_document_and_the_ledger(english, live):  # noqa: F811
    doc = cued(english, Client(items("Acerca tu pie derecho 5", GOOD["es"][1])))
    assert SENTINEL not in json.dumps(doc) and SENTINEL not in live["ledger"].read_text()
    assert set(ledger_lines(live)[0]) == {"time", "model", "http_status", "prompt_tokens", "completion_tokens",
                                          "reasoning_tokens"}
    assert "Acerca" not in json.dumps([e["fallback_reason"] for e in doc["phrasing"]["cues"]])


def test_ac_lc_02_the_local_model_writes_them_too_and_is_named(english, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ollama")
    monkeypatch.setenv("PART5_OLLAMA_MODEL", "tiny-coach")
    client = Client(items(*GOOD["es"]))
    doc = cued(english, client, backend="local-llm")
    assert {e["backend"] for e in doc["phrasing"]["cues"]} == {"local-llm"}
    assert {e["model"] for e in doc["phrasing"]["cues"]} == {"tiny-coach"}
    assert client.requests[0]["url"] == local_llm.URL and "Authorization" not in client.requests[0]["headers"]
    assert client.requests[0]["body"]["max_tokens"] >= local_llm.BATCH_MAX_TOKENS


def test_ac_lc_02_the_product_path_asks_for_the_fault_line_and_then_the_cues(live):  # noqa: F811
    """`pipeline.run` with a language: the fault line first, then one batched call once the insights are final."""
    client = Client(reply(json.dumps(FAULT_PAIR, ensure_ascii=False)), items(*GOOD["es"]))
    doc = take_run(phrasing="muse-spark", phrasing_client=client, live=True, lang="es")
    assert len(client.requests) == 2 and len(ledger_lines(live)) == 2
    assert doc["faults"][0]["coaching"] == FAULT_PAIR["line"] and doc["phrasing"]["faults"][0]["lang"] == "es"
    assert [e["path"] for e in doc["phrasing"]["cues"]] == PATHS
    assert {e["backend"] for e in doc["phrasing"]["cues"]} == {"muse-spark"}
    assert doc["phrasing"]["native_review"] is False and doc["schema_version"] == "1.14.0"
    assert list(VALIDATOR.iter_errors(doc)) == []


# ---- AC-LC-03: a bad item falls back alone, and says why ---------------------------------------------------------------
BAD_CUES = [
    ("Acerca tu pie 5", "translation adds a number"),
    ("Acerca tu pie ٣", "translation adds a number"),
    ("Acerca\ntu pie", "translation has more than one line"),
    ("", "translation is empty or too long"),
    ("Acerca tu pie derecho hacia adentro con mucho cuidado ahora mismo", "translation is empty or too long"),
    ("Acerca tu pie derecho hacia adentro un poco más de lo que lo haces ahora", "translation is empty or too long"),
    ("Buen trabajo, acerca tu pie", "translation adds praise"),
    ("Great job, acerca tu pie", "translation adds praise"),
    ("Step your right foot in", "translation is not in the language asked"),
    ("step YOUR right foot in!", "translation is not in the language asked"),
    ("Step your pie derecho", "translation is not in the language asked"),
]


@pytest.mark.parametrize("text,reason", BAD_CUES)
def test_ac_lc_03_a_bad_spanish_cue_is_refused_with_its_reason(text, reason):
    assert lang.check_cue(ROLE_CUE, CUE_EN, text, "es") == reason


BAD_REASONS = [
    ("Pie derecho demasiado a la derecha", "translation changes the numbers"),
    ("Pie derecho demasiado a la derecha a 2,4 s", "translation changes the numbers"),
    ("Pie derecho a 1,9 s y a 1,9 s", "translation changes the numbers"),
    ("Pie derecho a 1,9 s (3 veces)", "translation changes the numbers"),
    ("Pie derecho at 1,9 s", "translation keeps an English time phrase"),
    ("Pie derecho around 1.9 s", "translation keeps an English time phrase"),
    ("Pie derecho a 1,9 s, bien hecho", "translation adds praise"),
    ("Right foot too far right at 1.9 s", "translation keeps an English time phrase"),
    ("Right foot too far right, 1.9 s", "translation is not in the language asked"),
    ("x" * 201, "translation is empty or too long"),
    ("Pie derecho demasiado a la derecha a 1,9 s " + "y " * 100, "translation is empty or too long"),
]


@pytest.mark.parametrize("text,reason", BAD_REASONS)
def test_ac_lc_03_a_bad_spanish_reason_is_refused_with_its_reason(text, reason):
    assert lang.check_cue(ROLE_REASON, WHY_EN, text, "es") == reason


def test_ac_lc_03_a_good_text_passes_in_each_listed_script_and_a_comma_decimal_is_the_same_number():
    for tag, (cue, why) in GOOD.items():
        assert lang.check_cue(ROLE_CUE, CUE_EN, cue, tag) is None and lang.check_cue(ROLE_REASON, WHY_EN, why, tag) is None
    assert lang.check_cue(ROLE_REASON, WHY_EN, "Pie derecho a 1,90 s", "es") is None
    assert lang.check_cue(ROLE_REASON, "Left knee not bent enough (3 of 8 reps)",
                          "Rodilla izquierda poco flexionada (3 de 8 repeticiones)", "es") is None
    assert lang.check_cue(ROLE_REASON, "Your reps took 1.3 times the trainer's time",
                          "Tus repeticiones duraron 1,3 veces el tiempo del entrenador", "es") is None


@pytest.mark.parametrize("tag,text", [("ar", "Step your right foot in"), ("hi", "Acerca tu pie derecho"),
                                      ("ru", "Step your right foot in"), ("ja", "Step your right foot"),
                                      ("ar", "اضغط 1 foot in right now ok")])
def test_ac_lc_03_a_language_with_its_own_script_needs_most_of_its_letters_in_it(tag, text):
    assert lang.check_cue(ROLE_CUE, CUE_EN, text, tag) in ("translation is not in the language asked",
                                                          "translation adds a number")


def test_ac_lc_03_the_same_checks_run_for_every_listed_language():
    for tag in lang.LANGUAGES:
        if tag != lang.EN:
            assert lang.check_cue(ROLE_CUE, CUE_EN, "Step your right foot in", tag) == \
                "translation is not in the language asked", tag


UNSAFE = [   # R7 of the 1.14.0 review: what the history opinion's translations already refuse (`guard.unsafe_problem`)
    (ROLE_CUE, "Visita www.salud.com ahora mismo", "es", "translation has a link"),             # the review's probe
    (ROLE_CUE, "Gira el pie‮ derecho dentro", "es", "translation has a control character"),  # a bidi override
    (ROLE_CUE, "قرّب قدمك‮ اليمنى", "ar", "translation has a control character"),
    (ROLE_CUE, "قرّب قدمك‫ اليمنى", "ar", "translation has a control character"),             # an embedding
    (ROLE_CUE, "अपना⁦ पैर अंदर", "hi", "translation has a control character"),                  # an isolate
    (ROLE_CUE, "Acerca​ tu pie derecho", "es", "translation has a control character"),     # a zero-width space
    (ROLE_CUE, "Acerca\ttu pie derecho", "es", "translation has a control character"),
    (ROLE_CUE, "Pregunta a tu coach ahora", "es", "translation uses a word this product does not use"),
    (ROLE_CUE, "Evita la pain ahora", "es", "translation uses a word this product does not use"),
    (ROLE_REASON, "Pie derecho hacia fuera a 1,9 s, ve a http://x.io", "es", "translation has a link"),
    (ROLE_REASON, "القدم اليمنى عند 1.9 ث www.x.com", "ar", "translation has a link"),
]


@pytest.mark.parametrize("role,text,tag,reason", UNSAFE)
def test_r7_a_translation_with_a_link_a_control_character_or_a_banned_word_is_refused(role, text, tag, reason):
    assert lang.check_cue(role, CUE_EN if role == ROLE_CUE else WHY_EN, text, tag) == reason


def test_r7_the_recorded_translations_pass_the_word_guard():
    for tag in ("es", "ar", "hi"):
        doc = json.loads((ROOT / f"fixtures/output/lang/analysis.{tag}.json").read_text())
        fields = {f.path: f for f in cue_fields(doc)}
        for entry in doc["phrasing"]["cues"]:
            field = fields[entry["path"]]
            assert lang.check_cue(field.role, field.text, entry["text"], tag) is None, (tag, entry["path"])


def test_r7_a_link_keeps_the_english_text_with_its_reason(english, live):  # noqa: F811
    doc = cued(english, Client(items("Visita www.salud.com ahora", GOOD["es"][1])))
    assert entry_of(doc, "faults[0].cue") == {"path": "faults[0].cue", "text": CUE_EN, "lang": "en", "backend": "template",
                                              "model": None, "fallback_reason": "muse-spark: translation has a link"}
    assert entry_of(doc, "insights[0].why")["text"] == GOOD["es"][1]


def test_ac_lc_03_a_bad_item_keeps_its_english_text_and_the_others_keep_theirs(english, live):  # noqa: F811
    doc = cued(english, Client(items("Acerca tu pie 5", GOOD["es"][1])))
    bad = [entry_of(doc, p) for p in ("faults[0].cue", "score.timeline[0].misses[0].cue", "insights[0].cue")]
    for e in bad:
        assert e == {"path": e["path"], "text": CUE_EN, "lang": "en", "backend": "template", "model": None,
                     "fallback_reason": "muse-spark: translation adds a number"}
    good = entry_of(doc, "insights[0].why")
    assert good["text"] == GOOD["es"][1] and good["lang"] == "es" and good["backend"] == "muse-spark"
    assert validate_analysis(doc) is doc


def test_ac_lc_03_a_missing_item_and_an_unusable_id_are_refused_not_guessed(english, live):  # noqa: F811
    answer = reply(json.dumps({"items": [{"id": 0, "text": GOOD["es"][0]}, {"id": 7, "text": "x"}, {"id": True, "text": "y"},
                                         {"text": "no id"}, "text", {"id": 1}]}))
    doc = cued(english, Client(answer))
    assert entry_of(doc, "insights[0].cue")["backend"] == "muse-spark"
    why = entry_of(doc, "insights[0].why")
    assert why["backend"] == "template" and why["fallback_reason"] == "muse-spark: no translation returned"


@pytest.mark.parametrize("answer,reason", [
    (items(*GOOD["es"]), None),
    (reply("Aquí tienes: " + json.dumps({"items": [{"id": 0, "text": GOOD["es"][0]}, {"id": 1, "text": GOOD["es"][1]}]})),
     None),
    (reply("Acerca tu pie derecho"), "muse-spark: unreadable answer"),
    (reply('{"items": "no"}'), "muse-spark: unreadable answer"),
    (reply('{"cues": []}'), "muse-spark: unreadable answer"),
    (reply('{"items": [{"id": 0, '), "muse-spark: unreadable answer"),
    (reply("[1, 2]"), "muse-spark: unreadable answer"),
    (http_error(500), "muse-spark: HTTP 500"),
    (TimeoutError("slow"), "muse-spark: timeout after 20 s"),
    (reply(""), "muse-spark: empty content"),
])
def test_ac_lc_03_a_failed_call_or_an_answer_that_is_not_the_json_asked_for_keeps_every_text_in_english(
        english, live, answer, reason):  # noqa: F811
    doc = cued(english, Client(answer))
    entries = doc["phrasing"]["cues"]
    assert [e["path"] for e in entries] == PATHS
    if reason is None:
        assert {e["backend"] for e in entries} == {"muse-spark"}
        return
    assert {e["backend"] for e in entries} == {"template"} and {e["lang"] for e in entries} == {"en"}
    assert {e["fallback_reason"] for e in entries} == {reason} and {e["model"] for e in entries} == {None}
    assert [e["text"] for e in entries] == [CUE_EN] * 3 + [WHY_EN]
    assert validate_analysis(doc) is doc


def test_ac_lc_03_a_rate_limited_call_says_so_plainly(english, live, monkeypatch):  # noqa: F811
    monkeypatch.setenv("PART5_MUSE_PER_MINUTE", "0")
    client = Client()
    doc = cued(english, client)
    assert client.requests == [] and {e["fallback_reason"] for e in doc["phrasing"]["cues"]} == {"rate limited"}


# ---- AC-LC-04: no model, no call ------------------------------------------------------------------------------------
def test_ac_lc_04_the_template_makes_no_call_and_says_it_writes_english(spanish_template):
    entries = spanish_template["phrasing"]["cues"]
    assert [e["path"] for e in entries] == PATHS
    for e in entries:
        assert e["lang"] == "en" and e["backend"] == "template" and e["model"] is None
        assert e["fallback_reason"] == "template lines are English only"
    assert spanish_template["phrasing"]["native_review"] is False
    assert validate_analysis(spanish_template) is spanish_template


@pytest.mark.parametrize("live_on,key,reason", [(True, False, "no key"), (False, True, "live calls are off")])
def test_ac_lc_04_no_key_or_live_off_makes_no_call_and_keeps_english(english, tmp_path, monkeypatch, live_on, key, reason):
    if key:
        (tmp_path / "key").write_text("k\n")
        monkeypatch.setenv("PART5_BASETEN_KEY_FILE", str(tmp_path / "key"))
    client = Client()
    out = copy.deepcopy(english)
    phrasing.phrase_cues(out, "muse-spark", client=client, live=live_on, lang="ar")
    assert client.requests == []
    assert {e["backend"] for e in out["phrasing"]["cues"]} == {"template"}
    assert all(e["fallback_reason"].startswith(reason) for e in out["phrasing"]["cues"])


def test_ac_lc_04_a_take_with_nothing_to_write_makes_no_call(live):  # noqa: F811
    doc = {"faults": [], "phrasing": {"lang": "es"}}
    client = Client()
    assert phrasing.phrase_cues(doc, "muse-spark", client=client, live=True, lang="es")["phrasing"]["cues"] == []
    assert client.requests == []


def test_ac_lc_04_an_unknown_backend_is_refused():
    with pytest.raises(ValueError, match="unknown phrasing backend"):
        phrasing.phrase_cues({"phrasing": {}}, "nope", lang="es")


# ---- AC-LC-05: the marker ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("tag", ["es", "ar", "hi", "fr", "es-MX"])
def test_ac_lc_05_every_listed_language_but_english_is_marked_not_reviewed(english, tag):
    out = copy.deepcopy(english)
    phrasing.phrase_cues(out, "template", lang=tag)
    assert out["phrasing"]["native_review"] is False and lang.NATIVE_REVIEWED == frozenset()


@pytest.mark.parametrize("tag", [None, "", "en", "en-GB", "tlh", "xx", "klingon"])
def test_ac_lc_05_english_and_an_unlisted_tag_have_neither_key(english, tag):
    out = copy.deepcopy(english)
    assert phrasing.phrase_cues(out, "template", lang=tag) is out
    assert out == english and "cues" not in out["phrasing"] and "native_review" not in out["phrasing"]


def test_ac_lc_05_a_language_a_native_reader_signed_is_true(english, monkeypatch):
    monkeypatch.setattr(lang, "NATIVE_REVIEWED", frozenset({"es"}))
    spanish, arabic = copy.deepcopy(english), copy.deepcopy(english)
    assert phrasing.phrase_cues(spanish, "template", lang="es")["phrasing"]["native_review"] is True
    assert phrasing.phrase_cues(arabic, "template", lang="ar")["phrasing"]["native_review"] is False
    assert validate_analysis(spanish) is spanish


# ---- AC-LC-06: additive, English unchanged ----------------------------------------------------------------------------
def test_ac_lc_06_an_english_request_is_what_it_was_and_the_pipeline_adds_nothing(english):
    assert english["schema_version"] == "1.14.0" and "cues" not in english["phrasing"]
    again = take_run(lang="en")
    assert json.dumps(again, sort_keys=True) == json.dumps(english, sort_keys=True)
    committed = json.loads((ROOT / "fixtures/output/analysis.example.json").read_text())
    assert committed["schema_version"] == "1.14.0" and "cues" not in committed["phrasing"]


def test_ac_lc_06_nothing_but_the_phrasing_record_changes_for_a_language(english, live):  # noqa: F811
    doc = cued(english, Client(items(*GOOD["es"])))
    before, after = copy.deepcopy(english), copy.deepcopy(doc)
    for d in (before, after):
        d["phrasing"].pop("cues", None), d["phrasing"].pop("native_review", None), d["phrasing"].pop("lang")
    assert before == after   # the English cues, why, coaching, score and insights are what they were


def test_ac_lc_06_the_original_cue_fields_stay_english_in_a_language_document(live):  # noqa: F811
    client = Client(reply(json.dumps(FAULT_PAIR, ensure_ascii=False)), items(*GOOD["hi"]))
    doc = take_run(phrasing="muse-spark", phrasing_client=client, live=True, lang="hi")
    assert doc["faults"][0]["cue"] == CUE_EN and doc["insights"][0]["cue"] == CUE_EN and doc["insights"][0]["why"] == WHY_EN
    assert doc["score"]["timeline"][0]["misses"][0]["cue"] == CUE_EN
    assert entry_of(doc, "insights[0].cue")["text"] == GOOD["hi"][0]


def test_ac_lc_06_the_document_check_refuses_an_entry_that_does_not_belong(english):
    good = {"path": "faults[0].cue", "text": CUE_EN, "lang": "en", "backend": "template", "model": None,
            "fallback_reason": "no key"}

    def with_cues(*cues, **record):
        doc = copy.deepcopy(english)
        doc["phrasing"].update(cues=list(cues), **record)
        return doc

    assert validate_analysis(with_cues(good)) and validate_analysis(with_cues()) and validate_analysis(
        with_cues(good, native_review=False))
    for entry, what in [({**good, "path": "faults[3].cue"}, "must name a cue or reason"),
                        ({**good, "path": "status.text"}, "must name a cue or reason"),
                        ({**good, "path": 7}, "must name a cue or reason"),
                        ({**good, "text": ""}, "text must be a non-empty string"),
                        ({**good, "lang": None}, "lang must be a non-empty string"),
                        ({**good, "backend": ""}, "backend must be a non-empty string"),
                        ({**good, "backend": "made-up"}, "backend must be one of ['local-llm', 'muse-spark', 'template']"),
                        ({**good, "backend": "Template"}, "backend must be one of"),
                        ({**good, "model": 3}, "model must be a string or null"),
                        ({**good, "fallback_reason": 3}, "fallback_reason must be a string or null"),
                        ({**good, "text": "Acerca tu pie"}, "must equal faults[0].cue when the template wrote it"),
                        ("not an object", "must be an object")]:
        with pytest.raises(OutputError, match=re.escape(what)):
            validate_analysis(with_cues(entry))
    for bad in ("no", 1, None):
        with pytest.raises(OutputError, match="native_review must be true or false"):
            validate_analysis(with_cues(good, native_review=bad))
    doc = copy.deepcopy(english)
    doc["phrasing"]["cues"] = {"path": "x"}
    with pytest.raises(OutputError, match="phrasing.cues must be a list"):
        validate_analysis(doc)


def test_r10_the_document_check_and_the_schema_know_the_same_backends():
    """R10 of the 1.14.0 review: `validate_cues` took `"backend": "made-up"`; only the schema's enum refused it."""
    enum = SCHEMA["properties"]["phrasing"]["properties"]["cues"]["items"]["properties"]["backend"]["enum"]
    assert sorted(enum) == sorted(phrasing.BACKENDS)


def test_ac_lc_06_the_schema_validates_the_record_and_an_older_document_still_validates(english, live):  # noqa: F811
    doc = cued(english, Client(items(*GOOD["ar"])))
    assert list(VALIDATOR.iter_errors(doc)) == []
    broken = copy.deepcopy(doc)
    del broken["phrasing"]["cues"][0]["model"]
    broken["phrasing"]["native_review"] = "false"
    messages = " ".join(e.message for e in VALIDATOR.iter_errors(broken))
    assert "'model' is a required property" in messages and "is not of type 'boolean'" in messages
    old = copy.deepcopy(english)
    old["schema_version"] = "1.13.0"
    assert list(VALIDATOR.iter_errors(old)) == [] and SCHEMA["version"] == "1.14.0"


def test_ac_lc_06_a_pipeline_document_for_every_listed_language_validates(english):
    for tag in ("es", "ar", "hi"):
        doc = copy.deepcopy(english)
        phrasing.phrase_cues(doc, "template", lang=tag)
        assert list(VALIDATOR.iter_errors(doc)) == [] and validate_analysis(doc) is doc


# ---- AC-LC-07: the doctor -----------------------------------------------------------------------------------------------
def doctor_out(doc, tmp_path, capsys):
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(doc))
    code = cli.main(["doctor", str(path), "--for", "part7"])
    return code, capsys.readouterr().out


def test_ac_lc_07_the_doctor_notes_who_wrote_the_cues_and_that_no_native_reader_has_checked_them(
        english, live, tmp_path, capsys):  # noqa: F811
    doc = cued(english, Client(items("Acerca tu pie 5", GOOD["es"][1])))
    code, out = doctor_out(doc, tmp_path, capsys)
    assert code == 0 and "accepted for part7" in out
    notes = [line for line in out.splitlines() if "cues in es" in line]
    assert len(notes) == 1
    assert "1 of 4 written by meta-models/muse-spark-open-1026, 3 kept in English" in notes[0]
    assert "muse-spark: translation adds a number" in notes[0]
    assert "no native reader has checked them (phrasing.native_review is false)" in notes[0]


def test_ac_lc_07_the_doctor_says_so_for_a_reviewed_language_an_empty_record_and_an_english_document(
        english, tmp_path, capsys, monkeypatch):
    reviewed = cued(english, Client(), "es", backend="template")
    monkeypatch.setattr(lang, "NATIVE_REVIEWED", frozenset({"es"}))
    reviewed["phrasing"]["native_review"] = True
    _, out = doctor_out(reviewed, tmp_path, capsys)
    assert "0 of 4 written by the model, 4 kept in English (the first reason: template lines are English only)" in out
    assert "a native reader has checked them" in out
    report = SimpleNamespace(notes=[])   # what the doctor fills
    doctor._cue_language_notes(report, {"phrasing": {"lang": "ar", "cues": []}})
    assert report.notes == ["phrasing.cues is empty: the take has no cue or reason to write in ar"]
    _, plain = doctor_out(english, tmp_path, capsys)
    assert "cues in" not in plain


# ---- the reader of the model's answer ---------------------------------------------------------------------------------
def test_the_reader_keeps_the_first_text_of_an_id_and_strips_quotes():
    answer = json.dumps({"items": [{"id": 1, "text": "  'uno' "}, {"id": 1, "text": "dos"}, {"id": 0, "text": "cero"},
                                   {"id": 2, "text": "fuera"}, {"id": -1, "text": "menos"}, {"id": 0, "text": 5}]})
    assert lang.read_items(answer, 2) == {0: "cero", 1: "uno"}
    for bad in ("", "no json", '{"items": 3}', "[]", '{"items": [}'):
        with pytest.raises(ValueError, match="unreadable answer"):
            lang.read_items(bad, 2)


def test_the_prompt_names_the_language_and_the_rules_and_keeps_non_latin_text_as_it_is():
    chat = prompt.cue_messages([("cue", "Bend your knees more"), ("reason", "Left knee not bent enough (3 of 8 reps)")], "hi")
    assert chat[0]["role"] == "system" and "into Hindi" in chat[0]["content"]
    for rule in ("no praise", "Keep each one as the English has it", "Western digits", "with no digit"):
        assert rule in chat[0]["content"]
    assert json.loads(chat[1]["content"])[1] == {"id": 1, "kind": "reason", "text": "Left knee not bent enough (3 of 8 reps)"}
    arabic = prompt.cue_messages([("cue", "قرّب قدمك")], "ar")[1]["content"]
    assert "قرّب قدمك" in arabic   # not escaped to \uXXXX: a model reads the text as it is


# ---- AC-LC-08: the viewer ---------------------------------------------------------------------------------------------
needs_node = pytest.mark.skipif(node_major() < 22, reason="needs Node 22 or later to import the page's modules")
PHRASING_AR = {"cues": [{"path": "insights[1].cue", "text": "قرّب قدمك", "lang": "ar"},
                        {"path": "insights[1].why", "text": "القدم اليمنى عند 1.9 ث", "lang": "ar"},
                        {"path": "insights[0].cue", "text": "", "lang": "ar"}], "native_review": False}


@needs_node
def test_ac_lc_08_the_page_shows_the_translated_cue_and_reason_at_their_paths_and_the_english_elsewhere():
    analysis = {"insights": [{"cue": "Raise your arms higher", "why": "Arms low"},
                             {"cue": CUE_EN, "why": WHY_EN}, {"cue": "Lean forward more"}, {"why": "no cue"}],
                "phrasing": PHRASING_AR}
    script = f"""import {{ insightItems, cueText, nativeReviewNote }} from {json.dumps(JOINTS_URL)};
console.log(JSON.stringify([insightItems(payload), cueText(payload, "insights[9].cue", "kept"),
  cueText({{}}, "insights[0].cue", "English"), nativeReviewNote(payload), nativeReviewNote({{}}),
  nativeReviewNote({{ phrasing: {{ native_review: true }} }}), nativeReviewNote({{ phrasing: {{}} }})]));"""
    shown, kept, bare, note, none_, reviewed, absent = run_node(script, analysis)
    assert shown == [{"cue": "Raise your arms higher", "why": "Arms low"},   # an empty text keeps the English
                     {"cue": "قرّب قدمك", "why": "القدم اليمنى عند 1.9 ث"},
                     {"cue": "Lean forward more", "why": ""}]
    assert kept == "kept" and bare == "English"
    assert note == "Not reviewed by a native reader." and none_ is None and reviewed is None and absent is None


@needs_node
def test_ac_lc_08_text_from_phrasing_has_dir_auto_and_the_pages_own_words_do_not():
    preview = (ROOT / "web/preview.js").as_uri()
    script = f"""const made = [];
globalThis.document = {{ createElement(tag) {{ const node = {{ tag, attrs: {{}}, className: "", textContent: "",
  setAttribute(k, v) {{ this.attrs[k] = v; }} }}; made.push(node); return node; }} }};
const {{ make, phrased }} = await import({json.dumps(preview)});
const plain = make("p", "phone-meta", "Shows on: knee");
const arabic = phrased("p", "phone-coach", "قدمك اليمنى بعيدة جدًا عند 1.9 ث");
console.log(JSON.stringify([plain.attrs, arabic.attrs, arabic.textContent, arabic.tag, arabic.className]));"""
    plain, arabic, text, tag, name = run_node(script, None)
    assert plain == {} and arabic == {"dir": "auto"} and text.endswith("1.9 ث") and tag == "p" and name == "phone-coach"


def test_ac_lc_08_every_place_the_page_shows_a_models_text_goes_through_phrased():
    app, preview = (ROOT / "web/app.js").read_text(), (ROOT / "web/preview.js").read_text()
    assert 'phrased("span", "fault-text"' in app and 'phrased("li", "insight")' in app
    assert 'phrased("p", "phone-coach"' in preview and "nativeReviewNote(analysis)" in app
    assert 'make("span", "fault-text"' not in app and 'make("li", "insight")' not in app
    assert "text-align: start" in (ROOT / "web/style.css").read_text()


# ---- AC-LC-09: the recorded live outputs -----------------------------------------------------------------------------
RECORDED = sorted((ROOT / "fixtures/output/lang").glob("analysis.*.json"))


def test_ac_lc_09_the_recorded_outputs_are_the_three_languages_the_ticket_names():
    assert [p.name for p in RECORDED] == ["analysis.ar.json", "analysis.es.json", "analysis.hi.json"]
    assert (ROOT / "fixtures/output/lang/PROVENANCE.md").is_file()


@pytest.mark.parametrize("path", RECORDED, ids=lambda p: p.name)
def test_ac_lc_09_a_recorded_output_validates_names_the_model_and_is_marked_not_reviewed(path):
    doc = json.loads(path.read_text())
    tag = path.name.split(".")[1]
    assert validate_analysis(doc) is doc and list(VALIDATOR.iter_errors(doc)) == []
    assert doc["phrasing"]["lang"] == tag and doc["phrasing"]["selected_by"] == "live"
    assert doc["phrasing"]["native_review"] is False and doc["schema_version"] == "1.14.0"
    entries = doc["phrasing"]["cues"]
    assert [e["path"] for e in entries] == [f.path for f in cue_fields(doc)] and entries
    for e in entries:   # the model, or the English text with the reason; never a template taken for a translation
        if e["backend"] == "muse-spark":
            assert e["model"] == "meta-models/muse-spark-open-1026" and e["lang"] == tag and e["fallback_reason"] is None
        else:
            assert e["backend"] == "template" and e["lang"] == "en" and e["fallback_reason"] and e["model"] is None
    assert "Authorization" not in path.read_text() and "Bearer" not in path.read_text()


def test_ac_lc_09_the_recorded_files_are_validated_by_the_contract_check_and_not_rebuilt():
    run_ = contract._Run(ROOT)
    for path in RECORDED:
        run_.fixture(path)
    assert run_.failures == [] and run_.rebuilt == [] and run_.loaded == len(RECORDED) and run_.files == len(RECORDED)
