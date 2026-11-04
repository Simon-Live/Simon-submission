"""The wording the page preselects and the hint under the select, run in Node (docs/specs/viewer.md AC-V19, ADR-0008).

`web/joints.js` has no DOM, so Node imports `defaultWording` and `wordingHint` directly and is handed the real
`api/samples` answer of a server in each state: live mode with a key file, live mode without one, and not live.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from part5 import api

ROOT = Path(__file__).resolve().parent.parent
JOINTS_URL = (ROOT / "web/joints.js").as_uri()
NODE = shutil.which("node")


def node_major():
    if not NODE:
        return 0
    return int(subprocess.run([NODE, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")[0])


pytestmark = pytest.mark.skipif(node_major() < 22, reason="needs Node 22 or later to import the page's modules")

# The page's own calls, in the order app.js makes them: the preselected wording is `defaultWording(samples)`, and the
# hint is `wordingHint(<the select's value>, <offered>, <that default>)` at load and again after every pick.
SCRIPT = f"""
import {{ defaultWording, wordingHint }} from {json.dumps(JOINTS_URL)};
const input = JSON.parse(await new Promise((r) => {{ let s = ''; process.stdin.setEncoding('utf8');
  process.stdin.on('data', (c) => {{ s += c; }}); process.stdin.on('end', () => r(s)); }}));
const out = input.map(([samples, picked]) => {{
  const chosen = defaultWording(samples);
  const offered = samples.phrasing ?? ['template'];
  return {{ chosen, hint: wordingHint(chosen, offered, chosen),
           picked_hint: picked == null ? null : wordingHint(picked, offered, chosen) }};
}});
console.log(JSON.stringify(out));
"""


def run_page(pairs):
    done = subprocess.run([NODE, "--no-warnings", "--input-type=module", "-e", SCRIPT], input=json.dumps(pairs),
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def page_choice(*listings):
    """[{chosen, hint}] the page makes from each `api/samples` answer in `listings`."""
    return run_page([[listing, None] for listing in listings])


def page_hint_after_pick(samples, picked):
    """The hint the page shows once the visitor has picked `picked` on a server whose `api/samples` answer is `samples`."""
    return run_page([[samples, picked]])[0]["picked_hint"]


def listing():
    status, _, out = api.handle("GET", "/api/samples", b"", base_path="/")
    assert status == 200
    return json.loads(out)


@pytest.fixture
def key_file(monkeypatch, tmp_path):
    key = tmp_path / "BASETEN_API_KEY"
    key.write_text("not-a-real-key\n")   # only has to exist: nothing reads it
    monkeypatch.setenv("PART5_BASETEN_KEY_FILE", str(key))


def test_a_server_in_live_mode_with_a_key_starts_the_page_on_muse_spark(key_file, monkeypatch):
    monkeypatch.setenv("META_LIVE", "1")
    (made,) = page_choice(listing())
    assert made["chosen"] == "muse-spark"
    assert made["hint"].startswith("Muse Spark is preselected because this server uses it")
    assert "template wording is always available" in made["hint"]


def test_a_server_in_live_mode_without_a_key_starts_the_page_on_the_template(monkeypatch):
    monkeypatch.setenv("META_LIVE", "1")
    (made,) = page_choice(listing())
    assert made["chosen"] == "template"
    assert made["hint"] == "Template is preselected because it is the only wording this server can run."


def test_a_server_that_is_not_live_starts_the_page_on_the_template_even_with_a_key_file(key_file):
    (made,) = page_choice(listing())
    assert made["chosen"] == "template" and "muse-spark" not in listing()["phrasing"]


def test_the_page_follows_the_named_default_and_not_the_order_or_the_last_wording_offered():
    base = {"phrasing": ["template", "muse-spark"]}
    named_template, named_model = page_choice({**base, "phrasing_default": "template"},
                                              {**base, "phrasing_default": "muse-spark"})
    assert named_template["chosen"] == "template"      # offered, but not the default: never preselected
    assert named_model["chosen"] == "muse-spark"
    assert "Muse Spark can also be chosen" in named_template["hint"]


def test_a_default_that_is_not_offered_or_missing_is_the_template():
    unoffered, missing, older = page_choice({"phrasing": ["template"], "phrasing_default": "muse-spark"},
                                            {"phrasing": ["template", "muse-spark"]}, {})
    assert (unoffered["chosen"], missing["chosen"], older["chosen"]) == ("template", "template", "template")


LIVE = {"phrasing": ["template", "muse-spark"], "phrasing_default": "muse-spark"}
PLAIN = {"phrasing": ["template", "muse-spark"], "phrasing_default": "template"}


def test_the_hint_follows_the_pick_when_the_visitor_leaves_the_servers_default():
    """AC-V19: after the pick the hint no longer says the default is preselected."""
    assert page_hint_after_pick(LIVE, "template") == "Template wording chosen. This server's default is Muse Spark."
    assert page_hint_after_pick(PLAIN, "muse-spark") == "Muse Spark wording chosen. This server's default is Template."
    for samples, picked in ((LIVE, "template"), (PLAIN, "muse-spark")):
        assert "preselected" not in page_hint_after_pick(samples, picked)


def test_picking_the_default_again_brings_the_preselected_sentence_back():
    for samples in (LIVE, PLAIN):
        (made,) = page_choice(samples)
        assert page_hint_after_pick(samples, made["chosen"]) == made["hint"]
        assert "is preselected because" in made["hint"]


def test_the_hint_after_a_pick_names_the_effective_default_not_an_unoffered_one():
    """A named default the server does not offer is replaced by the template, so that is the default the hint names."""
    unoffered = {"phrasing": ["template", "local-llm"], "phrasing_default": "muse-spark"}
    assert page_hint_after_pick(unoffered, "local-llm") == "Local language model wording chosen. This server's default is Template."


def test_no_hint_has_an_em_dash_an_en_dash_or_a_spaced_hyphen():
    hints = [made["hint"] for made in page_choice(
        {"phrasing": ["template"], "phrasing_default": "template"},
        {"phrasing": ["template", "local-llm", "muse-spark"], "phrasing_default": "template"},
        {"phrasing": ["template", "muse-spark"], "phrasing_default": "muse-spark"})]
    hints += [page_hint_after_pick(LIVE, "template"), page_hint_after_pick(PLAIN, "muse-spark")]
    assert "Local language model and Muse Spark can also be chosen" in hints[1]
    banned = (chr(0x2014), chr(0x2013), " - ")   # em dash, en dash, spaced hyphen
    assert not [h for h in hints if any(mark in h for mark in banned)]
