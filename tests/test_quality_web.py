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
