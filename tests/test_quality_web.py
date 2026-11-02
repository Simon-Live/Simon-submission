"""TICKET-079, AC-Q13: the line under the score on the Compare page, run in Node (`web/joints.js` has no DOM).

The page shows one line when `quality.level` is `degraded` or `major` and nothing for `ok` or a document without the block
(not assessed). The words say what was measured and name no cause (docs/specs/quality.md, Deviations), and they are held to
the writer's bans: no dash, no first person, no praise, one sentence."""
import json
import re
from pathlib import Path

import pytest

from test_web_logic import JOINTS_URL, node_major, run_node

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(node_major() < 22, reason="needs Node 22 or later to import the page's modules")
SCRIPT = f"""
import {{ QUALITY_NOTES, qualityNote }} from {json.dumps(JOINTS_URL)};
console.log(JSON.stringify({{ notes: QUALITY_NOTES, lines: payload.map((a) => qualityNote(a)) }}));
"""


def lines_for(*analyses):
    return run_node(SCRIPT, list(analyses))


def test_a_degraded_and_a_major_take_each_get_their_own_line_and_nothing_else_does():
    out = lines_for({"quality": {"level": "degraded"}}, {"quality": {"level": "major"}}, {"quality": {"level": "ok"}}, {},
                    {"quality": None}, {"quality": {}}, {"quality": {"level": "worse"}}, {"quality": {"level": 3}},
                    {"quality": {"level": "constructor"}}, {"quality": {"level": "__proto__"}})
    assert out["lines"][0] == out["notes"]["degraded"] and out["lines"][1] == out["notes"]["major"]
    assert out["lines"][0] != out["lines"][1]
    assert out["lines"][2:] == [None] * 8, "ok, no block, no level, an unknown level and a prototype key show nothing"


def test_the_two_lines_say_what_was_seen_and_name_no_cause():
    notes = lines_for({})["notes"]
    assert set(notes) == {"degraded", "major"}
    assert "treat the result with care" in notes["degraded"] and "do not rely on the result" in notes["major"]
    for text in notes.values():
        assert "hard to see" in text
        assert not re.search(r"light|dark|occlu|lens|camera angle", text, re.I), "a cause Part 5 cannot measure"


def test_the_lines_keep_to_the_writers_bans():
    for text in lines_for({})["notes"].values():
        assert not any(dash in text for dash in (chr(0x2014), chr(0x2013), " " + "-" + " ")), "a dash"
        assert not re.search(r"\b(I|we|my|our)\b", text), "first person"
        assert not re.search(r"great|well done|excellent|perfect|amazing", text, re.I), "praise"
        assert text.endswith(".") and text.count(".") == 1, "one sentence"
        assert len(text.split()) <= 16


def test_the_page_has_the_line_in_its_markup_between_the_score_note_and_the_mode_note():
    html = (ROOT / "web/index.html").read_text()
    order = [html.index(f'id="{name}"') for name in ("score", "score-note", "quality-note", "profile-note", "warning-panel")]
    assert order == sorted(order)
    assert re.search(r'<p id="quality-note"[^>]*data-testid="quality-note"[^>]* hidden></p>', html)


def test_the_page_script_shows_and_hides_the_line_from_the_helper_after_the_score():
    app = (ROOT / "web/app.js").read_text()
    assert "qualityNote" in app.split("} from \"./joints.js\"")[0]
    assert app.index("showScore(analysis.score);") < app.index("showQualityNote(analysis);") < app.index("showProfileNote(analysis);")
    assert "el.qualityNote.hidden = note === null;" in app


STATUS_SCRIPT = f"""
import {{ NO_FAULTS_SENTENCE, NO_FAULTS_UNSEEN_SENTENCE, QUALITY_NOTES, resultSentence }} from {json.dumps(JOINTS_URL)};
console.log(JSON.stringify({{ plain: NO_FAULTS_SENTENCE, unseen: NO_FAULTS_UNSEEN_SENTENCE, major: QUALITY_NOTES.major,
  lines: payload.map((a) => resultSentence(a)) }}));
"""
WARNING = {"code": "low_match", "text": "This take does not closely match the example."}
FAULT = {"measure": "foot_out", "text": "left foot too far out"}


def test_a_major_take_with_no_fault_does_not_say_it_follows_the_example():
    """TICKET-088 (the 1.13.0 web validator, uc-analyse-take): beside "do not rely on the result", the status line said "This
    take follows the example". On a major take with no fault and no warning it now says the take was not seen well enough to
    say so; every other status line is as it was."""
    out = run_node(STATUS_SCRIPT, [
        {"faults": [], "quality": {"level": "major"}},
        {"faults": [], "quality": {"level": "degraded"}}, {"faults": [], "quality": {"level": "ok"}}, {"faults": []},
        {"faults": [], "quality": {"level": "worse"}},
        {"faults": [], "warnings": [WARNING], "quality": {"level": "major"}},
        {"faults": [FAULT], "quality": {"level": "major"}}, {"faults": [FAULT, FAULT], "quality": {"level": "major"}},
    ])
    assert out["lines"] == [out["unseen"], out["plain"], out["plain"], out["plain"], out["plain"],
                            "No faults are listed. Read the warning first.", "1 fault found.", "2 faults found."]
    assert out["plain"] == "No faults found. This take follows the example."
    assert "This take follows the example" not in out["unseen"] and out["unseen"].startswith("No faults found, but")


PREVIEW_URL = (ROOT / "web/preview.js").as_uri()
PREVIEW_SCRIPT = f"""
globalThis.document = {{ createElement: (tag) => ({{ tag, className: "", textContent: "", dataset: {{}}, children: [],
  setAttribute() {{}}, append(...c) {{ this.children.push(...c); }}, replaceChildren(...c) {{ this.children = c; }} }}) }};
const {{ renderPreview, FIELDS_READ }} = await import({json.dumps(PREVIEW_URL)});
const {{ NO_FAULTS_SENTENCE, NO_FAULTS_UNSEEN_SENTENCE, resultSentence }} = await import({json.dumps(JOINTS_URL)});
const phone = (analysis) => {{
  const screen = document.createElement("div"), fields = document.createElement("div");
  renderPreview(screen, fields, analysis);
  return screen.children.filter((n) => n.className === "phone-meta").map((n) => n.textContent);
}};
console.log(JSON.stringify({{ plain: NO_FAULTS_SENTENCE, unseen: NO_FAULTS_UNSEEN_SENTENCE, fields: FIELDS_READ,
  lines: payload.map((a) => phone(a)), status: payload.map((a) => resultSentence(a)) }}));
"""


CARD_FAULT = {**FAULT, "body_part": "feet", "magnitude_deg": 10.0, "direction": "more", "joints": ["left_ankle"],
              "follower_frames": [3, 9]}


def test_the_phone_preview_says_what_the_status_line_says_for_a_take_with_no_fault():
    """TICKET-088: the preview did not read `quality`, so a major take with no fault and no warning still read "This take
    follows the example" there, beside the Compare tab's "not seen well enough to say it follows the example". The preview now
    shows the status line's own sentence (`resultSentence`, not a second copy of the words); with a warning it keeps its own
    "No faults are listed.", and a take with faults has no such line."""
    major, degraded, ok = ({"faults": [], "quality": {"level": level}} for level in ("major", "degraded", "ok"))
    out = run_node(PREVIEW_SCRIPT, [
        major, degraded, ok, {"faults": []}, {"faults": [], "quality": {"level": "worse"}},
        {"faults": [], "warnings": [WARNING], "quality": {"level": "major"}},
        {"faults": [CARD_FAULT], "quality": {"level": "major"}},
    ])
    plain, unseen = out["plain"], out["unseen"]
    assert out["lines"][0] == [unseen] and out["lines"][0] == [out["status"][0]]
    assert out["lines"][1:5] == [[plain]] * 4 and out["status"][1:5] == [plain] * 4
    assert out["lines"][5] == ["No faults are listed."], "a warning keeps the preview's own line"
    assert plain not in out["lines"][0] and "This take follows the example" not in unseen
    assert not any(line in (plain, unseen) for line in out["lines"][6]), "a take with a fault has no no-fault line"
    assert ["Whether the take was seen well enough", "quality.level"] in out["fields"]


def test_the_preview_holds_no_copy_of_the_status_line_words():
    code = (ROOT / "web/preview.js").read_text()
    assert "follows the example" not in code and "not seen well enough" not in code and "NO_FAULTS_SENTENCE" not in code
    assert "resultSentence" in code.split("} from \"./joints.js\"")[0]


def test_the_major_status_line_keeps_to_the_writers_bans_and_does_not_repeat_the_quality_note():
    out = run_node(STATUS_SCRIPT, [])
    text = out["unseen"]
    assert not any(dash in text for dash in (chr(0x2014), chr(0x2013), " " + "-" + " ")), "a dash"
    assert not re.search(r"\b(I|we|my|our)\b", text) and text.endswith(".") and text.count(".") == 1
    assert not re.search(r"light|dark|occlu|lens|camera", text, re.I), "a cause Part 5 cannot measure"
    assert "hard to see" not in text and text != out["major"]


HEADING_SCRIPT = f"""
import {{ HEADING_NOTE, QUALITY_NOTES, qualityNote }} from {json.dumps(JOINTS_URL)};
console.log(JSON.stringify({{ angle: HEADING_NOTE, notes: QUALITY_NOTES, lines: payload.map((a) => qualityNote(a)) }}));
"""


def reason(code):
    return {"code": code, "words": "w", "value": 1.0, "threshold": 1.0}


def test_a_take_whose_only_reason_is_the_heading_gets_the_angle_line_and_mixed_reasons_keep_the_generic_one():
    """TICKET-086: a degraded take whose only reason is heading_offset was told its joints were hard to see, which is not what
    was measured. It now reads the camera-angle line; beside any other reason the line of its level stays, and a take
    without reasons (or with no list) keeps the line of its level."""
    heading, jitter, unseen = reason("heading_offset"), reason("position_jitter"), reason("joints_unseen")
    out = run_node(HEADING_SCRIPT, [
        {"quality": {"level": "degraded", "reasons": [heading]}},
        {"quality": {"level": "major", "reasons": [heading]}},   # not written since TICKET-086 (degraded only); read the same way
        {"quality": {"level": "degraded", "reasons": [jitter, heading]}},
        {"quality": {"level": "major", "reasons": [unseen, jitter, heading]}},
        {"quality": {"level": "degraded", "reasons": [jitter]}},
        {"quality": {"level": "degraded", "reasons": []}}, {"quality": {"level": "degraded"}},
        {"quality": {"level": "degraded", "reasons": "heading_offset"}}, {"quality": {"level": "degraded", "reasons": [None]}},
        {"quality": {"level": "ok", "reasons": [heading]}}, {"quality": {"level": "worse", "reasons": [heading]}},
    ])
    angle, degraded, major = out["angle"], out["notes"]["degraded"], out["notes"]["major"]
    assert out["lines"] == [angle, angle, degraded, major, degraded, degraded, degraded, degraded, degraded, None, None]


def test_the_angle_line_keeps_to_the_writers_bans_and_names_the_angle_not_the_joints():
    angle = run_node(HEADING_SCRIPT, [])["angle"]
    assert angle == "Filmed from a different angle than the example, so treat the score as rough."
    assert not any(dash in angle for dash in (chr(0x2014), chr(0x2013), " " + "-" + " ")), "a dash"
    assert not re.search(r"\b(I|we|my|our)\b", angle) and angle.endswith(".") and angle.count(".") == 1
    assert not re.search(r"great|well done|excellent|perfect|amazing|light|dark|occlu|lens", angle, re.I)
    assert "angle" in angle and "hard to see" not in angle and len(angle.split()) <= 16
