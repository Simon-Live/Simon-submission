"""TICKET-181 AC-7 to AC-13: the history citation guard, one test group per rule (docs/specs/history-meta.md).

Facts come from two REAL cleared takes of body-squat-19b06562 (staging jobs cc7cd5469055 and 5277380db1e1, trimmed
copies in fixtures/history/real_analyses.json). Take 1 (score 100) has no fault; take 2 (score 77) leans forward at
0.9 s. The model answer below is HAND-WRITTEN TEST FIXTURE text, not model output: one valid claim and one violation
per rule.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from part7 import history_guard

REAL = json.loads((Path(__file__).parent / "fixtures" / "history" / "real_analyses.json").read_text())


def build_facts() -> dict[str, Any]:
    """A C-FACTS table from the real analyses, oldest take first (a test helper; the server builds the real one)."""
    takes = []
    for n, row in enumerate(sorted(REAL["takes"], key=lambda r: r["created_at"]), start=1):
        analysis = row["analysis"]
        faults = [{"measure": f["measure"], "side": f["side"], "at_s": f["at_s"], "span": f["follower_t_s"],
                   "text_timed": f["text_timed"], "cue": f["cue"]} for f in analysis["faults"]]
        cues = sorted({m["cue"] for w in analysis["score"]["timeline"] for m in w["misses"] if m.get("cue")})
        takes.append({"take": n, "at": row["created_at"], "score": analysis["score"]["value"],
                      "grade": analysis["score"]["grade"], "duration_s": row["duration_ms"] / 1000.0,
                      "faults": faults, "cues": cues})
    return {"entry_id": "body-squat-19b06562", "takes": takes, "best": 1, "latest": 2,
            "measures": [{"measure": "trunk_lean_forward", "side": "center", "present_in": [2], "status": "new",
                          "first": 2, "last": 2}]}


NARRATION = {"format": "simon.narration.v1", "cues": [  # hand-written fixture, same shape as narration.json
    {"index": 0, "start_s": 0.4, "end_s": 2.0, "text": "Chest up and push your knees out"},
    {"index": 1, "start_s": 4.0, "end_s": 5.5, "text": "Slow on the way down"}]}

FACTS = build_facts()

VALID_TREND = {"kind": "new", "measure": "trunk_lean_forward", "side": "center",
               "text": "The forward lean at 0.9 s in take 2 was not in take 1.",
               "cites": [{"take": 1, "at_s": None}, {"take": 2, "at_s": 0.9}]}
VALID_FOCUS = {"measure": "trunk_lean_forward", "side": "center", "cue": "Keep your chest up",
               "text": "Work on the forward lean at 0.9 s in take 2.", "cites": [{"take": 2, "at_s": 0.9}]}
VALID_LINK = {"cue_index": 0, "text": 'The teacher said "Chest up and push your knees out" in take 2.',
              "cites": [{"take": 2, "at_s": None}]}
VALID_OBS = {"take": 2, "at_s": 4.0, "text": "The hips shift to one side near the bottom."}

# HAND-WRITTEN TEST FIXTURE: valid items first, then one violation per rule.
ANSWER: dict[str, Any] = {
    "summary": {"text": "Your score went from 100 in take 1 to 77 in take 2.",
                "cites": [{"take": 1, "at_s": None}, {"take": 2, "at_s": None}]},
    "trends": [
        VALID_TREND,
        {**VALID_TREND, "cites": [{"take": 7, "at_s": None}]},                          # rule 1: take not in input
        {**VALID_TREND, "cites": [{"take": 2, "at_s": 6.0}]},                           # rule 2: not where measured
        {**VALID_TREND, "kind": "fixed"},                                               # rule 3: status is new
        {**VALID_TREND, "text": "The lean reached 31 degrees at 0.9 s in take 2."},     # rule 4: uncited number
        {**VALID_TREND, "text": "A great start at 0.9 s in take 2."},                   # rule 6: praise
    ],
    "focus": VALID_FOCUS,
    "teacher_link": VALID_LINK,
    "observations": [
        VALID_OBS,
        {"take": 2, "at_s": 99.0, "text": "The stance is wide."},                       # rule 1: outside the take
        {"take": 2, "at_s": 5.0, "text": "A twinge of pain shows at the knee."},       # rule 6: banned word
        {"take": 2, "at_s": 6.0, "text": "x" * 161},                                    # rule 6: too long
    ],
}


def run(answer: Any, **kw: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return history_guard.check(answer, kw.get("facts", FACTS), kw.get("narration", NARRATION), kw.get("words"))


def variant(**changes: Any) -> dict[str, Any]:
    """The valid summary, focus and teacher link with no trends or observations, then `changes` on top."""
    out = copy.deepcopy(ANSWER)
    out.update(trends=[], observations=[])
    out.update(changes)
    return out


def rules_of(rejected: list[dict[str, Any]], prefix: str) -> list[Any]:
    return [r["rule"] for r in rejected if r["item"].startswith(prefix)]


def test_real_facts_are_what_the_fixture_claims():
    assert [t["score"] for t in FACTS["takes"]] == [100, 77]
    assert FACTS["takes"][1]["faults"][0]["span"] == [0.9, 3.2]
    assert FACTS["takes"][1]["cues"] == ["Keep your chest up"]


def test_fixture_answer_keeps_valid_and_rejects_each_violation():
    kept, rejected = run(ANSWER)
    assert kept["summary"]["source"] == "model"
    assert [t["text"] for t in kept["trends"]] == [VALID_TREND["text"]]
    assert kept["focus"]["cue"] == "Keep your chest up" and kept["teacher_link"]["cue_index"] == 0
    assert [o["text"] for o in kept["observations"]] == [VALID_OBS["text"]]
    assert kept["observations"][0]["label"] == "model_opinion"
    assert rules_of(rejected, "trends") == [1, 2, 3, 4, 6]
    assert rules_of(rejected, "observations") == [1, 6, 6]


def test_rule_1_every_item_is_cited_inside_the_input():
    _, rejected = run(ANSWER)
    assert rules_of(rejected, "trends")[0] == 1
    assert rules_of(rejected, "observations")[0] == 1
    cases = [
        [], None, "take 1", [{"take": 2, "at_s": float("nan")}], [{"take": 2, "at_s": float("inf")}],
        [{"take": 2, "at_s": -0.1}], [{"take": 2, "at_s": 10.0}], [{"take": True, "at_s": None}],
        [{"take": 2, "at_s": "0.9"}], [{}], [{"take": 1, "at_s": 9.97}],
    ]
    for cites in cases:
        _, rejected = run(variant(trends=[{**VALID_TREND, "cites": cites}]))
        assert rules_of(rejected, "trends") == [1], cites
    kept, _ = run(variant(trends=[{**VALID_TREND, "cites": [{"take": 2, "at_s": 9.9}]}]))
    assert kept["trends"] == []  # 9.9 s is inside the take but not where the fault was measured: rule 2
    kept, rejected = run(variant(observations=[{"take": 2, "text": "no time"}, "not an object"]))
    assert rules_of(rejected, "observations") == [1, 1] and kept["observations"] == []


def test_rule_2_a_fault_time_must_be_where_it_was_measured():
    kept, rejected = run(ANSWER)
    assert rules_of(rejected, "trends")[1] == 2
    for at_s, ok in [(0.9, True), (3.2, True), (2.0, True), (4.2, False), (4.3, False), (0.0, True), (5.0, False)]:
        trend = {**VALID_TREND, "text": f"The lean at {at_s} s in take 2.", "cites": [{"take": 2, "at_s": at_s}]}
        kept, rejected = run(variant(trends=[trend]))
        assert bool(kept["trends"]) is ok, at_s
        assert ok or rejected[0]["rule"] == 2
    other_side = {**VALID_TREND, "side": "left"}
    kept, rejected = run(variant(trends=[other_side]))
    assert kept["trends"] == [] and rejected[0]["rule"] == 2
    focus_bad = {**VALID_FOCUS, "cites": [{"take": 2, "at_s": 8.0}], "text": "The lean at 8.0 s in take 2."}
    kept, rejected = run(variant(focus=focus_bad))
    assert kept["focus"] is None and rules_of(rejected, "focus") == [2]


def test_rule_3_kind_agrees_with_the_fact_table():
    _, rejected = run(ANSWER)
    assert rules_of(rejected, "trends")[2] == 3
    for kind in ("improved", "persistent", "fixed", "bogus"):
        kept, rejected = run(variant(trends=[{**VALID_TREND, "kind": kind}]))
        assert kept["trends"] == [] and rejected[0]["rule"] == 3
    unknown = {**VALID_TREND, "measure": "knee_in"}
    kept, rejected = run(variant(trends=[unknown]))
    assert kept["trends"] == [] and rejected[0]["rule"] in (2, 3)
    facts = copy.deepcopy(FACTS)
    facts["measures"][0]["status"] = "fixed"
    kept, _ = run(variant(trends=[{**VALID_TREND, "kind": "fixed"}]), facts=facts)
    assert len(kept["trends"]) == 1


def test_rule_4_only_cited_times_and_cited_scores_are_numbers():
    _, rejected = run(ANSWER)
    assert rules_of(rejected, "trends")[3] == 4
    ok = ["Down from 100 to 77 across takes 1 and 2.", "The lean at 0.90 s in take 2.", "Take 2 scored 77."]
    for text in ok:
        trend = {**VALID_TREND, "text": text, "cites": [{"take": 1, "at_s": None}, {"take": 2, "at_s": 0.9}]}
        kept, rejected = run(variant(trends=[trend]))
        assert len(kept["trends"]) == 1, (text, rejected)
    bad = ["It happened 3 times in take 2.", "The lean at 1.5 s in take 2.", "Take 3 had it too.",
           "Down from 100 to 78 in take 2.", "Scored 77 in take 2 at 0.9 s, up 23 points."]
    for text in bad:
        trend = {**VALID_TREND, "text": text, "cites": [{"take": 1, "at_s": None}, {"take": 2, "at_s": 0.9}]}
        kept, rejected = run(variant(trends=[trend]))
        assert kept["trends"] == [] and rejected[0]["rule"] == 4, text
    only_take_two = {**VALID_TREND, "text": "Take 1 scored 100.", "cites": [{"take": 2, "at_s": 0.9}]}
    kept, rejected = run(variant(trends=[only_take_two]))
    assert kept["trends"] == [] and rejected[0]["rule"] == 4  # take 1 and its score are not cited


def test_rule_5_cue_and_teacher_quote_are_verbatim():
    kept, rejected = run(ANSWER)
    assert kept["focus"] and kept["teacher_link"] and not rules_of(rejected, "focus")
    for cue in ("Keep your chest up!", "keep your chest up", "Chest up", ""):
        kept, rejected = run(variant(focus={**VALID_FOCUS, "cue": cue}))
        assert kept["focus"] is None and rejected[0]["rule"] == 5, cue
    facts = copy.deepcopy(FACTS)
    facts["takes"][0]["cues"] = ["Slow down to match the trainer"]  # an older take's cue is not the latest take's
    kept, rejected = run(variant(focus={**VALID_FOCUS, "cue": "Slow down to match the trainer"}), facts=facts)
    assert kept["focus"] is None and rejected[0]["rule"] == 5
    for text in ('The teacher said "Chest up, push knees out" in take 2.', "The teacher said chest up in take 2.",
                 'The teacher said "Slow on the way down" in take 2.'):
        kept, rejected = run(variant(teacher_link={**VALID_LINK, "text": text}))
        assert kept["teacher_link"] is None and rejected[0]["rule"] == 5, text
    kept, rejected = run(variant(teacher_link={**VALID_LINK, "cue_index": 9}))
    assert kept["teacher_link"] is None and rejected[0]["rule"] == 5
    kept, rejected = run(ANSWER, narration=None)
    assert kept["teacher_link"] is None
    assert [r["rule"] for r in rejected if r["item"] == "teacher_link"] == [5]
    praise_in_quote = {"index": 0, "text": "Good, chest up"}
    kept, _ = run(variant(teacher_link={**VALID_LINK, "text": 'The teacher said "Good, chest up" in take 2.'}),
                  narration={"cues": [praise_in_quote]})
    assert kept["teacher_link"] is not None  # the teacher's own words are not the model's praise


def test_rule_6_banned_words_praise_and_one_short_line():
    _, rejected = run(ANSWER)
    assert rules_of(rejected, "trends")[4] == 6
    assert rules_of(rejected, "observations")[1:] == [6, 6]
    banned = ["A coach would fix it", "Coaching helps", "Medical advice", "an injury risk", "some pain", "rehab work",
              "therapy tip", "a diagnosis", "good for your health"]
    for text in banned:
        kept, rejected = run(variant(observations=[{**VALID_OBS, "text": text}]))
        assert kept["observations"] == [] and rejected[0]["rule"] == 6, text
    for text in ("Nice work", "That was excellent", "Well done on this one", "Great depth", "Perfect"):
        kept, rejected = run(variant(observations=[{**VALID_OBS, "text": text}]))
        assert kept["observations"] == [] and rejected[0]["rule"] == 6, text
    for text in ("two\nlines", "x" * 161, "", "   ", None, 5):
        kept, rejected = run(variant(observations=[{**VALID_OBS, "text": text}]))
        assert kept["observations"] == [] and rejected[0]["rule"] == 6, repr(text)
    kept, _ = run(variant(observations=[{**VALID_OBS, "text": "y" * 160}, {**VALID_OBS, "text": "Paint on the wall."}]))
    assert len(kept["observations"]) == 2  # 160 characters is allowed; "pain" does not match "paint"
    words = {"banned": ["wobbl*"], "praise": ["splendid"]}
    kept, _ = run(variant(observations=[{**VALID_OBS, "text": "A wobbly knee"}, {**VALID_OBS, "text": "Splendid"},
                                       {**VALID_OBS, "text": "A good stance"}]), words=words)
    assert [o["text"] for o in kept["observations"]] == ["A good stance"]  # the words file replaces the lists


def test_rule_6_also_covers_the_summary():
    kept, rejected = run(variant(summary={**ANSWER["summary"], "text": "Great, 100 then 77 in takes 1 and 2."}))
    assert kept["summary"]["source"] == "fact_table" and rejected[0]["rule"] == 6


def test_rule_7_a_dropped_summary_is_the_fact_table_summary():
    kept, rejected = run(ANSWER)
    assert kept["summary"]["source"] == "model"
    bad = variant(summary={"text": "Your score fell by 23 points.", "cites": [{"take": 1}, {"take": 2}]})
    kept, rejected = run(bad)
    assert kept["summary"] == {"text": "Your score went from 100 to 77 across 2 takes.",
                               "cites": [{"take": 1}, {"take": 2}], "source": "fact_table"}
    assert rejected[0]["item"] == "summary" and rejected[0]["rule"] == 4
    answer = variant()
    del answer["summary"]
    kept, rejected = run(answer)
    assert kept["summary"]["source"] == "fact_table" and rejected[0]["rule"] == 7
    one = {**FACTS, "takes": FACTS["takes"][:1]}
    assert history_guard.fact_summary(one)["text"] == "You have one take so far, scored 100."
    assert history_guard.fact_summary({"takes": []})["text"] == "There are no scored takes yet."


def test_answer_text_and_limits():
    kept, rejected = run(json.dumps(ANSWER))
    assert kept["summary"]["source"] == "model" and len(kept["trends"]) == 1
    kept, _ = run("Here is the JSON:\n" + json.dumps(ANSWER) + "\nDone.")
    assert len(kept["trends"]) == 1  # the JSON-parse fallback for a model that wraps its answer
    for junk in ("not json", "", None, 5, "[1]"):
        kept, rejected = run(junk)
        assert kept["summary"]["source"] == "fact_table" and kept["trends"] == [] and kept["focus"] is None
        assert rejected[0]["item"] == "answer"
    trends = [{**VALID_TREND, "text": f"Lean {chr(97 + i)} in take 2."} for i in range(7)]
    kept, rejected = run(variant(trends=trends))
    assert len(kept["trends"]) == 5 and [r["reason"] for r in rejected] == ["more than 5 items"] * 2
    # the words file may ship with only one list: the other falls back to the defaults
    kept, _ = run(variant(observations=[{**VALID_OBS, "text": "Great knee"}]), words={"banned": ["wobbl*"]})
    assert kept["observations"] == []
    # an unknown extra key is not passed through
    kept, _ = run(variant(trends=[{**VALID_TREND, "extra": "x"}]))
    assert "extra" not in kept["trends"][0]


def test_rule_6_phrases_hyphens_zero_width_prefix_and_whole_word():
    words = {"banned": ["injur*", "pain"], "praise": ["well done", "keep it up", "nice work"]}
    zw = chr(0x200B)
    praise = ["Well-done on take 2", "well   done here", "Keep-it-up", f"Nice w{zw}ork on take 2", f"We{chr(0xFEFF)}ll done"]
    for text in praise:
        kept, rejected = run(variant(observations=[{**VALID_OBS, "text": text}]), words=words)
        assert kept["observations"] == [] and rejected[0]["rule"] == 6, text
    for text in ("An injured knee", "Injury", f"Some pa{chr(0x2060)}in"):
        kept, rejected = run(variant(observations=[{**VALID_OBS, "text": text}]), words=words)
        assert kept["observations"] == [] and rejected[0]["rule"] == 6, text
    for text in ("Paint on the wall", "Well then, done", "A nicework"):
        kept, _ = run(variant(observations=[{**VALID_OBS, "text": text}]), words=words)
        assert len(kept["observations"]) == 1, text


@pytest.fixture(autouse=True)
def _own_default_words(monkeypatch):
    """The rules are tested on the guard's own defaults; the pinned Part 5 file has its own test below."""
    monkeypatch.setattr(history_guard, "WORDS_FILE", "contracts/absent-student-words.json")


def test_the_pinned_part_5_word_file_loads_when_the_clone_has_it(monkeypatch):
    from part7 import config
    monkeypatch.setattr(history_guard, "WORDS_FILE", "contracts/student-words.json")
    if not (config.part_dir(5) / "contracts" / "student-words.json").is_file():
        pytest.skip("the pinned Part 5 clone has no contracts/student-words.json")
    words = history_guard.load_words()
    assert words is not history_guard.DEFAULT_WORDS and len(words["banned"]) == 12 and len(words["praise"]) == 23
    assert "pain*" in words["banned"] and words["ignored"]


def test_rule_6_words_file_is_loaded_from_the_part_clone_else_defaults(tmp_path, monkeypatch):
    from part7 import config
    monkeypatch.setattr(history_guard, "WORDS_FILE", "contracts/student-words.json")
    clone = tmp_path / "part-5" / "contracts"
    clone.mkdir(parents=True)
    (clone / "student-words.json").write_text(json.dumps(
        {"format": "simon.student-words.v1", "banned": ["wobbl*"], "praise": ["fine form"], "match": "word"}))
    monkeypatch.setattr(config, "part_dir", lambda part: tmp_path / f"part-{part}")
    assert history_guard.load_words()["praise"] == ["fine form"]
    kept, _ = run(variant(observations=[{**VALID_OBS, "text": "Fine-form here"}, {**VALID_OBS, "text": "A wobbly knee"},
                                       {**VALID_OBS, "text": "Great knee"}]))
    assert [o["text"] for o in kept["observations"]] == ["Great knee"]  # the file's lists replace the defaults
    monkeypatch.setattr(config, "part_dir", lambda part: tmp_path / "absent")
    assert history_guard.load_words() == history_guard.DEFAULT_WORDS
    (tmp_path / "bad.json").write_text("{")
    assert history_guard.load_words(tmp_path / "bad.json") == history_guard.DEFAULT_WORDS


def test_words_file_in_part_5_shape_is_used_as_given_with_its_ignored_characters(tmp_path):
    stems = ["coach*", "rehab*", "medic*", "injur*", "pain*", "therap*", "diagnos*", "physio*", "clinic*", "doctor*", "patient*", "health*"]
    path = tmp_path / "student-words.json"
    path.write_text(json.dumps({
        "format": "simon.student-words.v1", "version": "1", "description": "d", "match": "word-prefix", "banned": stems,
        "praise": ["well done", "keep it up"], "applies_to": ["x"], "ignored_characters": ["U+00AD", "~"],
        "sources": ["s"], "lists_sha256": "0" * 64}))
    words = history_guard.load_words(path)
    assert words["banned"] == stems and words["praise"] == ["well done", "keep it up"]
    for text in ("Paint on the wall", "A coa\u00adch voice", "co~ach", "Physiology"):  # stems as given; ignored characters removed
        kept, _ = run(variant(observations=[{**VALID_OBS, "text": text}]), words=words)
        assert kept["observations"] == [], text
    kept, _ = run(variant(observations=[{**VALID_OBS, "text": "Great knee"}]), words=words)
    assert len(kept["observations"]) == 1  # the file's praise list replaces the defaults
    kept, _ = run(variant(observations=[{**VALID_OBS, "text": "Paint on the wall"}]))
    assert len(kept["observations"]) == 1  # our own defaults keep the whole word "pain" only
