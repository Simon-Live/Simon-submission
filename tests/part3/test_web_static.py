"""Static checks of the web pages (docs/specs/run-app.md AC-NFR-04 and the run page wiring; docs/specs/compare-mode.md
AC-M05, AC-M10, AC-NFR-M2 for the compare page and the new run options).

No browser: the files are read as text. The browser drive lives in staging/verify.mjs.
"""

import json
import math
import pathlib
import re
import shutil
import subprocess

import pytest

from part3 import compare, metrics, runapi, server, standard

ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
HTML_FILES = ["app.html", "index.html", "compare.html"]
JS_FILES = ["app.js", "viewer.js", "scene.js", "compare.js", "controls.js"]
PAGE_SCRIPTS = ["app.js", "compare.js", "controls.js"]  # the Run page, the Compare page and the module they share
CSS_FILES = ["app.css", "viewer.css", "compare.css"]

ATTR_URL = re.compile(r"""\b(?:src|href|action)\s*=\s*["']([^"']*)["']""")
IMPORTMAP = re.compile(r"""<script\s+type=["']importmap["']\s*>(.*?)</script>""", re.S)
HTML_ID = re.compile(r"""\bid=["']([^"']+)["']""")
HTML_REF = re.compile(r"""\b(?:for|aria-labelledby|aria-describedby|aria-controls)=["']([^"']+)["']""")
# A string literal on one line whose text is a path from the host root or a network address.
JS_ABSOLUTE = re.compile(r"""(["'`])(/[A-Za-z0-9_.\-][^"'`\n]*|//[^"'`\n]*|[A-Za-z][A-Za-z0-9+.\-]*://[^"'`\n]*)\1""")
JS_FETCH = re.compile(r"""\bfetch\(\s*(["'`])([^"'`\n]*)""")
JS_IMPORT = re.compile(r"""(?:\bimport\s+(?:[^"'`;]*?\sfrom\s+)?|\bimport\()\s*["']([^"']+)["']""")
BYID_CALL = re.compile(r"""\bbyId\(\s*(.)""")
BYID_LITERAL = re.compile(r"""\b(?:byId|getElementById)\(\s*"([^"]+)"\s*\)""")


def read(name):
    return (WEB / name).read_text(encoding="utf-8")


def is_relative(url):
    """True for a URL that resolves under the page's own directory (no leading slash, no scheme)."""
    if url.startswith("//") or url.startswith("/"):
        return False
    return not re.match(r"[A-Za-z][A-Za-z0-9+.\-]*:", url)


def absolute_urls_in_html(text):
    return [u for u in ATTR_URL.findall(text) if not is_relative(u)]


def absolute_urls_in_js(text):
    found = [m.group(2) for m in JS_ABSOLUTE.finditer(text)]
    found += [m.group(2) for m in JS_FETCH.finditer(text) if m.group(2) and not is_relative(m.group(2))]
    return found


def import_map(text):
    match = IMPORTMAP.search(text)
    assert match, "no import map"
    return json.loads(match.group(1))


@pytest.mark.parametrize("name", HTML_FILES)
def test_html_has_no_absolute_url(name):
    assert absolute_urls_in_html(read(name)) == []


@pytest.mark.parametrize("name", JS_FILES)
def test_js_has_no_absolute_url(name):
    assert absolute_urls_in_js(read(name)) == []


@pytest.mark.parametrize("name", JS_FILES)
def test_js_import_specifiers_are_relative_or_mapped(name):
    for spec in JS_IMPORT.findall(read(name)):
        assert spec == "three" or spec.startswith("./") or spec.startswith("../"), spec


def test_scanners_catch_absolute_urls():
    # Negative control: the scanners above must flag what they exist to flag.
    assert absolute_urls_in_js('fetch("/api/run")') != []
    assert absolute_urls_in_js("const u = `/api/run?x=1`;") != []
    assert absolute_urls_in_js("const u = 'https://example.com/a';") != []
    assert absolute_urls_in_js('fetch("api/run")') == []
    assert absolute_urls_in_html('<a href="/agreement">x</a>') != []
    assert absolute_urls_in_html('<script src="http://x/y.js"></script>') != []
    assert absolute_urls_in_html('<a href="agreement">x</a><link href="./viewer.css">') == []


def test_import_maps_are_relative_and_the_same():
    app, index, comparing = (import_map(read(name)) for name in ("app.html", "index.html", "compare.html"))
    assert app == index == comparing
    assert app["imports"]["three"] == "./vendor/three/three.module.js"
    for url in app["imports"].values():
        assert url.startswith("./") and is_relative(url)


def test_app_html_loads_its_own_files_as_a_module():
    html = read("app.html")
    assert '<script type="module" src="app.js"></script>' in html
    assert '<link rel="stylesheet" href="app.css">' in html
    assert 'href="agreement"' in html


@pytest.mark.parametrize("name", CSS_FILES)
def test_css_has_no_url_to_anywhere(name):
    assert "url(" not in read(name) and "@import" not in read(name)


def test_index_links_back_to_the_run_page():
    assert re.search(r'<a [^>]*href="\./"[^>]*>Run the pipeline</a>', read("index.html"))


@pytest.mark.parametrize("name", ["app.js", "controls.js"])
def test_every_byid_call_in_app_js_and_controls_js_is_a_literal(name):
    # A computed id cannot be checked against app.html, so every lookup spells its id out.
    bad = [m.group(0) for m in BYID_CALL.finditer(read(name)) if m.group(1) != '"']
    assert bad == []


def test_every_id_app_js_looks_up_exists_in_app_html():
    # The Run page's own lookups and those of the shared module it imports.
    ids = set(HTML_ID.findall(read("app.html")))
    wanted = set(BYID_LITERAL.findall(read("app.js"))) | set(BYID_LITERAL.findall(read("controls.js")))
    assert wanted, "app.js looks up no ids"
    assert sorted(wanted - ids) == []


def test_app_html_ids_are_unique_and_references_resolve():
    html = read("app.html")
    ids = HTML_ID.findall(html)
    assert len(ids) == len(set(ids))
    refs = {part for value in HTML_REF.findall(html) for part in value.split()}
    assert sorted(refs - set(ids)) == []


def test_app_html_has_one_status_and_one_alert_region():
    # <output> carries an implicit status role, which would make the status landmark ambiguous.
    html = read("app.html")
    assert html.count('role="status"') == 1
    assert html.count('role="alert"') == 1
    assert "<output" not in html


LANDMARKS = [
    "Input", "Mirror", "Your own file", "pose3d.json file", "Auto", "On", "Off", "Run", "Front", "Side", "Top",
    "Reset", "Play", "Frame", "Download skeleton.json", "Four-take agreement",
]
GETTER_HOOKS = ["ready", "runs", "lastRun", "frame", "frameCount", "playing"]
METHOD_HOOKS = ["camera", "target"]


@pytest.mark.parametrize("name", LANDMARKS)
def test_landmark_name_is_in_the_run_page(name):
    # The verify suite finds controls by role and accessible name; the name must be spelled out in the page files.
    html, script = read("app.html"), read("app.js") + read("controls.js")
    assert f">{name}<" in html or f'"{name}"' in script, name


def test_run_pipeline_link_is_on_the_agreement_view():
    assert ">Run the pipeline<" in read("index.html")


def test_window_app_hooks_are_read_only_getters_and_functions():
    script = read("app.js")
    block = script[script.index("window.app = Object.freeze({"):]
    block = block[:block.index("\n});")]
    for name in GETTER_HOOKS:
        assert f"get {name}()" in block, name
    for name in METHOD_HOOKS:
        assert f"{name}: (" in block, name
    assert "set " not in block


@pytest.mark.parametrize("name", PAGE_SCRIPTS)
def test_page_scripts_render_server_text_with_textcontent_only(name):
    script = read(name)
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert banned not in script, banned
    assert "textContent" in script


def test_run_page_copy_has_no_em_or_en_dash():
    for name in ("app.html", "app.js"):
        text = read(name)
        assert "\u2014" not in text and "\u2013" not in text, name


# ---- AC-M05, AC-M10, AC-NFR-M2: the compare page and the run options -----------------------------

SELECT = re.compile(r"""<select\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</select>""", re.S)
OPTION_VALUE = re.compile(r'<option\b[^>]*\bvalue="([^"]*)"')
INLINE_SCRIPT = re.compile(r"""<script\b(?![^>]*\bsrc\s*=)([^>]*)>""", re.I)
EVENT_ATTRIBUTE = re.compile(r"""\son[a-z]+\s*=""", re.I)
CONST = r"""\bconst\s+{name}\s*=\s*([^;]+);"""


def options_of(html, select_id):
    for found, inner in SELECT.findall(html):
        if found == select_id:
            return OPTION_VALUE.findall(inner)
    raise AssertionError(f"no select #{select_id}")


def number_in(script, name):
    """The value of `const NAME = <number or product of numbers>;` in a script."""
    match = re.search(CONST.format(name=name), script)
    assert match, name
    expr = match.group(1).strip()
    assert re.fullmatch(r"[0-9.]+(?: \* [0-9.]+)*", expr), expr
    return math.prod(float(factor) for factor in expr.split("*"))


@pytest.mark.parametrize("name", ["app.html", "compare.html"])
def test_the_four_option_selectors_are_labelled_and_offer_the_servers_values(name):
    html = read(name)
    assert options_of(html, "body-select") == list(runapi.BODIES)
    assert options_of(html, "view-select") == list(runapi.VIEWS)
    assert options_of(html, "fps-select") == ["", *map(str, runapi.FPS_VALUES)]
    for control, label in (("body-select", "Body"), ("height-input", "Height"), ("view-select", "View"),
                           ("fps-select", "Frame rate")):
        assert re.search(rf'<label for="{control}">{label}</label>', html), (name, label)
    height = re.search(r'<input[^>]*id="height-input"[^>]*>', html).group(0)
    assert 'type="number"' in height and 'min="0.5"' in height and 'max="2.5"' in height


def test_the_run_page_names_the_profile_and_shows_the_bone_lengths():
    html, script = read("app.html"), read("app.js")
    assert 'id="m-profile"' in html and ">Bone lengths<" in html and 'id="m-thigh"' in html
    assert "m-profile" in script and "bone_lengths_m" in script


def test_the_run_page_sends_the_options_and_downloads_the_views_file():
    script, shared = read("app.js"), read("controls.js")  # the request is built in the shared module
    for field in ("body=", "stature=", "view=", "fps="):
        assert field in shared, field
    assert "output_text" in shared and "output_name" in shared
    assert "downloadFile(state.result.text, state.result.name)" in script and "link.download = name;" in shared
    assert "2 MB" not in script and "2 MB" not in read("app.html") and "16 MB" in read("app.html")


def test_the_pages_show_the_servers_own_words_and_name_no_command_line_flag():
    """Review B1 and residual 11: an error the server refuses a run with (too_long among them) reaches the visitor as
    the server's message, and nothing a visitor reads names the `--input-fps` flag the page does not have."""
    shared = read("controls.js")
    assert "message: error.message" in shared and "showAlert" in shared  # the server's message is the one shown
    assert "too_long" not in shared  # no page-side copy of a server text to drift from it
    for name in (*HTML_FILES, *JS_FILES):
        assert "--input-fps" not in read(name), name
    assert "--input-fps" not in runapi.ERRORS["too_long"][1] and runapi.ERRORS["too_long"][0] == 400


def test_the_pages_know_the_servers_upload_cap():
    # One definition, in the module both pages import.
    assert number_in(read("controls.js"), "MAX_UPLOAD_BYTES") == server.MAX_BODY == 16 * 1024 * 1024
    for name in ("app.js", "compare.js"):
        assert "MAX_UPLOAD_BYTES" not in read(name), name


def test_compare_js_constants_equal_the_servers():
    script = read("compare.js")
    assert number_in(script, "MAX_COMPARE_FRAMES") == compare.MAX_FRAMES
    assert number_in(script, "MIN_ROWS") == compare.MIN_INPUTS and number_in(script, "MAX_ROWS") == compare.MAX_INPUTS
    assert number_in(script, "LIMIT_DEG") == metrics.AGREEMENT_MAX_DEG
    assert number_in(read("controls.js"), "NAME_LIMIT") == runapi.MAX_NAME == compare.MAX_LABEL
    assert len(re.search(r"OVERLAY_COLORS = \[([^\]]*)\]", read("scene.js")).group(1).split(",")) == compare.MAX_INPUTS


def test_compare_html_loads_its_own_files_as_a_module():
    html = read("compare.html")
    assert '<script type="module" src="compare.js"></script>' in html
    assert '<link rel="stylesheet" href="app.css">' in html and '<link rel="stylesheet" href="compare.css">' in html
    assert 'href="./"' in html and 'href="agreement"' in html


def test_the_run_page_links_to_the_compare_page():
    assert re.search(r'<a [^>]*href="compare"[^>]*>Compare takes</a>', read("app.html"))


def test_every_byid_call_in_compare_js_is_a_literal_and_exists_in_compare_html():
    script, html = read("compare.js"), read("compare.html")
    assert [m.group(0) for m in BYID_CALL.finditer(script) if m.group(1) != '"'] == []
    wanted = set(BYID_LITERAL.findall(script)) | set(BYID_LITERAL.findall(read("controls.js")))
    assert wanted
    assert sorted(wanted - set(HTML_ID.findall(html))) == []


def test_compare_html_ids_are_unique_and_references_resolve():
    html = read("compare.html")
    ids = HTML_ID.findall(html)
    assert len(ids) == len(set(ids))
    assert sorted({part for value in HTML_REF.findall(html) for part in value.split()} - set(ids)) == []


def test_compare_html_has_one_status_and_one_alert_region():
    html = read("compare.html")
    assert html.count('role="status"') == 1 and html.count('role="alert"') == 1 and "<output" not in html


COMPARE_LANDMARKS = ["Compare", "Add input", "Body", "Height", "View", "Frame rate", "Reset", "Front", "Side", "Top",
                     "Play", "Frame", "Show or hide an input", "Inputs", "Agreement", "Joint-angle agreement, p95",
                     "Result", "Run the pipeline", "Four-take agreement"]


@pytest.mark.parametrize("name", COMPARE_LANDMARKS)
def test_landmark_name_is_in_the_compare_page(name):
    assert f">{name}<" in read("compare.html") or f'"{name}"' in read("compare.js") + read("controls.js"), name


def test_the_per_input_controls_are_real_labelled_elements():
    script = read("compare.js")
    for pattern in ('type: "checkbox"', 'el("label"', 'setAttribute("aria-label", `Remove input ${k}`)',
                    'setAttribute("aria-label", `Source for input ${k}`)', 'setAttribute("aria-label", `Mirror for input ${k}`)',
                    'setAttribute("aria-label", `pose3d.json file for input ${k}`)',
                    'setAttribute("aria-label", `Download input ${k + 1}`)', 'type: "file"'):
        assert pattern in script, pattern
    assert "tabindex" not in script.lower()
    assert read("compare.html").lower().count("tabindex") == 1  # only the scrolling tables box, tested below


def test_the_compare_tables_have_captions_and_column_and_row_headers():
    html, script = read("compare.html"), read("compare.js")
    assert html.count("<caption>") == 2 and html.count("<table") == 2
    assert html.count('<th scope="col">') >= 9
    assert script.count("scope = \"row\"") == 2


def test_the_compare_overlay_has_a_legend_and_play_controls():
    html = read("compare.html")
    assert 'id="legend"' in html and 'id="frame-slider"' in html and 'id="btn-play"' in html
    assert "maps" in read("compare.js") and "sampleOutput" in read("compare.js")
    assert "class Overlay" in read("scene.js") and "OVERLAY_COLORS" in read("scene.js")


def test_compare_js_window_app_hooks_are_read_only():
    script = read("compare.js")
    block = script[script.index("window.app = Object.freeze({"):]
    block = block[:block.index("\n});")]
    for name in GETTER_HOOKS:
        assert f"get {name}()" in block, name
    for name in METHOD_HOOKS:
        assert f"{name}: (" in block, name
    assert "set " not in block


@pytest.mark.parametrize("name", ["app.html", "index.html", "compare.html"])
def test_a_page_is_content_security_policy_compatible(name):
    """The server allows 'self' scripts and the hash of each inline script: only the import map may be inline,
    and no element carries an event handler or a javascript: URL."""
    html = read(name)
    kinds = [attrs for attrs in INLINE_SCRIPT.findall(html)]
    assert all('type="importmap"' in attrs for attrs in kinds), kinds
    assert EVENT_ATTRIBUTE.search(html) is None and "javascript:" not in html.lower()


@pytest.mark.parametrize("name", ["compare.html", "compare.js", "compare.css", "app.css", "scene.js", "controls.js"])
def test_page_copy_has_no_em_or_en_dash(name):
    text = read(name)
    assert "\u2014" not in text and "\u2013" not in text, name


def test_the_server_csp_for_the_compare_page_covers_exactly_its_inline_scripts():
    html = read("compare.html")
    inline = [block for attrs, block in re.findall(r"<script\b((?![^>]*\bsrc\s*=)[^>]*)>(.*?)</script>", html, re.S)]
    assert len(inline) == 1
    csp = server.csp_for(WEB / "compare.html")
    assert csp.count("'sha256-") == 1


# ---- web/controls.js: the module the Run and Compare pages share (docs/specs/compare-mode.md) ----

EXPORTED_HELPERS = ["byId", "el", "bind", "say", "NA", "isNum", "percent", "plural", "shortName", "failure", "call",
                    "runAnswer", "sendRun", "loadSamples", "readOptions", "heightError", "inputError", "badge",
                    "showAlert", "downloadFile", "showNoWebgl", "ensureStage", "markView", "createPlayer", "framingScale",
                    "framedView", "reframePanel"]
PLAYER_FUNCTIONS = ["updatePlayButton", "setFrame", "play", "pause", "toggle", "step", "advance", "startLoop"]


def defines(script, name):
    """True when the script declares `name` as a function or constant (a loop variable of that name does not count)."""
    return re.search(rf"^\s*(?:export\s+)?(?:async\s+)?(?:function|const|class)\s+{name}\b", script, re.M) is not None


@pytest.mark.parametrize("page", ["app.js", "compare.js"])
def test_a_page_imports_the_shared_module_by_a_relative_url(page):
    assert re.search(r'\bfrom "\./controls\.js"', read(page))
    assert [spec for spec in JS_IMPORT.findall(read(page)) if spec.endswith("controls.js")] == ["./controls.js"]


def test_controls_js_is_a_leaf_module_with_no_script_of_its_own():
    # It imports nothing, so loading it adds no address beyond 'self'; no page lists it in a <script> tag either, so
    # the CSP hashes cover exactly the import maps as before.
    script = read("controls.js")
    assert JS_IMPORT.findall(script) == []
    assert "createElement(\"script\")" not in script and "<script" not in script
    for name in ("app.html", "compare.html", "index.html"):
        assert "controls.js" not in read(name), name


@pytest.mark.parametrize("name", EXPORTED_HELPERS)
def test_a_shared_helper_is_exported_by_controls_js_and_defined_by_no_page(name):
    assert re.search(rf"\bexport (?:async )?(?:function|const) {name}\b", read("controls.js")), name
    for page in ("app.js", "compare.js"):
        assert not defines(read(page), name), (page, name)


@pytest.mark.parametrize("name", PLAYER_FUNCTIONS)
def test_the_player_lives_in_controls_js_only(name):
    assert defines(read("controls.js"), name), name
    for page in ("app.js", "compare.js"):
        assert not defines(read(page), name), (page, name)


def test_every_name_a_page_imports_from_controls_js_is_exported_and_used():
    exported = set(re.findall(r"\bexport (?:async )?(?:function|const) (\w+)", read("controls.js")))
    for page in ("app.js", "compare.js"):
        script = read(page)
        block = re.search(r"import \{([^}]*)\} from \"\./controls\.js\"", script).group(1)
        names = [part.strip() for part in block.split(",") if part.strip()]
        assert names and set(names) <= exported, (page, sorted(set(names) - exported))
        rest = script.replace(block, "")
        for imported in names:
            assert re.search(rf"\b{imported}\b", rest), (page, imported)


def test_the_api_run_request_is_built_once_with_the_four_options():
    # One builder for both pages: flip, then body, stature, view and fps, the same query whichever page sends it.
    shared = read("controls.js")
    assert shared.count("api/run?") == 2  # the sample form and the upload form
    for field in ("flip=", "body=", "stature=", "view=", "fps="):
        assert shared.count(field) == 1, field
    for page in ("app.js", "compare.js"):
        assert "api/run?" not in read(page), page


# --- TICKET-021 polish --------------------------------------------------------------------------

@pytest.mark.parametrize("page", HTML_FILES)
def test_every_page_links_the_app_icon_by_a_relative_url(page):
    assert re.search(r"""<link rel="icon" href="icon.svg" type="image/svg\+xml">""", read(page)), page
    assert "data:," not in read(page), page


def test_the_app_icon_is_a_small_svg_the_server_serves():
    icon = read("icon.svg")
    assert icon.lstrip().startswith("<svg") and "</svg>" in icon and len(icon) < 2000
    assert ".svg" in server.STATIC_TYPES and "<script" not in icon and "href=" not in icon


def test_a_pressed_view_button_is_styled_so_a_sighted_user_sees_it():
    rule = re.search(r"""button\[aria-pressed="true"\](?:[^{]*)\{([^}]*)\}""", read("app.css"))
    assert rule and "background" in rule.group(1)
    # hovering a pressed button keeps it looking pressed (the hover rule would otherwise win)
    assert 'button[aria-pressed="true"]:hover:not(:disabled)' in read("app.css")


@pytest.mark.parametrize("page", HTML_FILES)
def test_page_copy_names_no_side_because_the_panels_stack_on_a_phone(page):
    text = re.sub(r"<[^>]+>", " ", read(page))
    for phrase in ("Left:", "Right:", "side by side", "on the left", "on the right"):
        assert phrase not in text, (page, phrase)


@pytest.mark.parametrize("page", HTML_FILES)
def test_play_states_its_action_by_its_label_and_carries_no_aria_pressed(page):
    play = re.search(r"""<button[^>]*id="btn-play"[^>]*>""", read(page)).group(0)
    assert "aria-pressed" not in play, page
    for script in ("controls.js", "viewer.js"):
        text = read(script)
        assert '"Pause" : "Play"' in text and 'setAttribute("aria-pressed", String(state.playing))' not in text
        assert 'setAttribute("aria-pressed", String(this.playing))' not in text


def test_the_output_panel_title_holds_for_every_body_profile():
    # The Body switch can pick Measured, Part 4 rig or a Height, so the output panel is "one fixed body", never "standard".
    for page, text in (("app.html", read("app.html")), ("app.js", read("app.js"))):
        assert "Output skeleton.json, one fixed body" in text, page
        assert "one standard body" not in text, page


# ---- review N1: the copy about limb lengths is true for every Body, including Measured from the clip ----------

DEMO_MD = ROOT / "staging" / "DEMO.md"  # local only: staging/ is never published, so the published tree skips these checks
DENIALS = ("not the person's own", "not the person\u2019s own", "that body's and not")


@pytest.mark.parametrize("name", HTML_FILES + PAGE_SCRIPTS)
def test_no_page_says_the_output_limb_lengths_are_not_the_persons_own(name):
    text = " ".join(read(name).split())
    for denial in DENIALS:
        assert denial not in text, (name, denial)


def demo_notes():
    """The staging demo notes, or a skip in a tree without them (the published one)."""
    if not DEMO_MD.exists():
        pytest.skip("staging/DEMO.md is local only; the published tree has no staging/")
    return DEMO_MD.read_text(encoding="utf-8")


def test_no_line_of_the_demo_notes_says_the_output_limb_lengths_are_not_the_persons_own():
    lines = demo_notes().splitlines()
    assert any("limb lengths" in line for line in lines)  # must-hit control: the sentence under test is there
    for line in lines:
        for denial in DENIALS:
            assert denial not in line, (line, denial)


def test_the_denial_scan_catches_the_old_sentence():
    old = "so its limb lengths are that body's and not the person's own."
    assert any(denial in old for denial in DENIALS)


def test_the_footnotes_say_what_measured_uses_and_that_a_height_scales_the_body():
    run_note = " ".join(re.search(r'<p class="footnote">(.*?)</p>', read("app.html"), re.S).group(1).split())
    compare_note = " ".join(re.search(r'<p class="footnote">(.*?)</p>', read("compare.html"), re.S).group(1).split())
    assert ("rebuilt on the Body you chose, with the same limb lengths in every frame and the feet on the grid. "
            "Measured from the clip uses this clip's own median lengths, left and right averaged, "
            "and a Height scales whichever Body you chose.") in run_note
    assert ("Each output is rebuilt on the Body you chose, with the same limb lengths in every frame. "
            "Measured from the clip uses each input's own median lengths, left and right averaged, "
            "and a Height scales whichever Body you chose.") in compare_note


def test_the_demo_notes_say_what_measured_uses():
    notes = " ".join(demo_notes().split())
    assert ("Measured from the clip uses the clip's own median lengths, left and right averaged, "
            "and a Height scales whichever Body you chose.") in notes


# ---- review residual 7: the Body height card note names this run's body, not a claim across runs ----------------

CROSS_RUN_CLAIM = "every output uses this one body"


def test_the_body_height_card_note_names_this_runs_body():
    assert "this run's body: ${profile}" in read("app.js")
    assert 'id="m-height-sub"></p>' in read("app.html")  # filled by app.js on every run; no copy of its own


def test_no_page_file_says_every_output_uses_one_body():
    # The wording read as a claim across runs; with Measured, Part 4 rig and a Height each run has its own body.
    files = [path for path in sorted(WEB.rglob("*")) if path.is_file() and "vendor" not in path.relative_to(WEB).parts
             and path.suffix in {".html", ".js", ".css", ".json", ".svg"}]
    assert {"app.html", "app.js", "compare.html", "controls.js"} <= {path.name for path in files}  # must-hit control
    for path in files:
        assert CROSS_RUN_CLAIM not in " ".join(path.read_text(encoding="utf-8").split()), path.name


def test_the_compare_page_claims_no_single_body_across_its_inputs():
    # With Measured every input is rebuilt on its own body, so "one body" or "one fixed body" would be false there.
    text = " ".join(read("compare.html").split())
    for claim in ("one body", "one fixed body", "one standard body"):
        assert claim not in text, claim


# ---- the output camera of the Run page is framed for the body's height (TICKET-032) -----------------------

def test_the_output_camera_is_framed_for_the_body_height_in_the_run_page_code():
    controls, script = read("controls.js"), read("app.js")
    assert number_in(controls, "FRAMING_STATURE_M") == standard.stature_m() == 1.7  # the body the views are framed for
    assert re.search(r"\bexport function framingScale\(statureM\)", controls)
    assert "framingScale(data.metrics.stature_m)" in script  # the height the run answered with
    # Every output camera move goes through the shared framedView (scaled by state.framing); none uses the bare target.
    assert script.count("framedView(viewOffset(output, \"reset\"), OVERLAP_TARGET, state.framing)") == 1
    assert script.count("framedView(viewOffset(output.panel, name), OVERLAP_TARGET, state.framing)") == 1
    assert "output.place(viewOffset(output" not in script and "flyTo(viewOffset(output.panel" not in script
    assert "reframePanel(state, state.stage && state.stage.output.panel, framingScale(data.metrics.stature_m));" in script
    assert "framingScale" not in read("scene.js") and "framingScale" not in read("viewer.js")  # the agreement view is as before


def test_the_framing_covers_the_servers_height_range_inside_the_panel_zoom_limit():
    # The farthest output camera (the three-quarter view on a narrow panel, at the tallest Height) stays under maxDistance.
    scene, script = read("scene.js"), read("app.js")
    reset = [float(v) for v in re.search(r"reset: new THREE\.Vector3\(([-0-9., ]+)\)", scene).group(1).split(",")]
    output = re.search(r'label: "Output skeleton\.json, one fixed body", minDistance: [0-9.]+, maxDistance: ([0-9.]+)', script)
    narrow = 1.3  # viewOffset(): a tall narrow panel needs more distance
    assert math.hypot(*reset) * narrow * (runapi.STATURE_RANGE[1] / 1.7) < float(output.group(1))


FRAMING_CASES = [1.7, 1.85, 2.5, 1.55, 0.5, None, float("nan"), float("inf"), "2"]


def framing_scales():
    """framingScale of FRAMING_CASES as computed by web/controls.js itself under node, or a skip without node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed; the static checks above still cover the function")
    cases = json.dumps(FRAMING_CASES)  # Python writes NaN and Infinity, which are JavaScript literals too
    program = f"import {{ framingScale }} from {json.dumps((WEB / 'controls.js').as_uri())};\n" \
              f"console.log(JSON.stringify({cases}.map(framingScale)));"
    done = subprocess.run([node, "--input-type=module", "-e", program], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(done.stdout)


def test_framing_scale_keeps_the_standard_view_and_grows_with_a_taller_body():
    scales = framing_scales()
    assert scales[0] == 1  # 1.70 m: the view as before
    assert scales[1] == pytest.approx(1.85 / 1.7) and scales[2] == pytest.approx(2.5 / 1.7)
    assert scales[3:] == [1] * (len(FRAMING_CASES) - 3)  # a shorter body, the smallest Height, and anything not a number
    assert scales[1] < scales[2]


# ---- the overlay camera of the Compare page is framed for the tallest input (TICKET-032 batch review residual 5) --------

def imported_from_controls(page):
    block = re.search(r"import \{([^}]*)\} from \"\./controls\.js\"", read(page)).group(1)
    return [part.strip() for part in block.split(",") if part.strip()]


def test_the_compare_page_frames_its_overlay_camera_by_framing_scale():
    script = read("compare.js")
    assert {"framingScale", "framedView", "reframePanel"} <= set(imported_from_controls("compare.js"))
    assert "framingScale(run.metrics.stature_m)" in script  # the height each input's run answered with
    assert re.search(r"const tallest = Math\.max\(\.\.\.runs\.map\(", script)  # the tallest input sets the framing
    assert "reframePanel(state, state.stage && state.stage.panel, tallest);" in script
    # Every overlay camera move goes through framedView (scaled by state.framing); none uses the bare target.
    assert script.count("framedView(viewOffset(state.stage.panel, name), OVERLAP_TARGET, state.framing)") == 1
    assert re.search(r"state\.stage\.panel\.flyTo\(view\.offset, view\.target\)", script)
    assert "flyTo(viewOffset(" not in script and "OVERLAP_TARGET)" not in script


def test_one_helper_in_controls_js_frames_the_camera_of_both_pages():
    controls, app, compare = read("controls.js"), read("app.js"), read("compare.js")
    # The two functions live in controls.js, exported once each ...
    for name in ("framedView", "reframePanel"):
        assert len(re.findall(rf"\bexport function {name}\(", controls)) == 1, name
    assert re.search(r"offset: offset\.clone\(\)\.multiplyScalar\(scale\)", controls)
    assert re.search(r"const ratio = scale / state\.framing;", controls)
    assert re.search(r"if \(!panel \|\| ratio === 1\) return;", controls)  # no stage, or the same framing: camera as it is
    # ... both pages import and call them ...
    for page, script in (("app.js", app), ("compare.js", compare)):
        assert {"framedView", "reframePanel"} <= set(imported_from_controls(page)), page
        assert len(re.findall(r"\breframePanel\(state, ", script)) == 1, page
        assert "framedView(" in script, page
    # ... and neither keeps a copy of the logic behind them.
    for page, script in (("app.js", app), ("compare.js", compare)):
        for name in ("framedView", "reframePanel", "outputView", "overlayView", "frameOutput", "frameOverlay"):
            assert not defines(script, name), (page, name)
        assert "multiplyScalar" not in script, page
        assert "panel.tween = null" not in script, page
        assert "/ state.framing" not in script, page


def test_only_the_compare_and_run_pages_know_the_framing_the_agreement_view_is_as_before():
    for name in ("scene.js", "viewer.js", "index.html"):
        assert "framingScale" not in read(name), name
        assert "framing" not in read(name).lower(), name
    controls = read("controls.js")
    assert len(re.findall(r"\bexport function framingScale\b", controls)) == 1  # one definition, shared


def test_the_overlay_zoom_limit_holds_the_farthest_compare_camera_at_the_tallest_height():
    scene = read("scene.js")
    reset = [float(v) for v in re.search(r"reset: new THREE\.Vector3\(([-0-9., ]+)\)", scene).group(1).split(",")]
    overlay = re.search(r"class Overlay \{.*?new Panel\(stage, \{[^}]*maxDistance: ([0-9.]+)", scene, re.S)
    narrow = 1.3  # viewOffset(): a tall narrow panel needs more distance
    assert math.hypot(*reset) * narrow * (runapi.STATURE_RANGE[1] / 1.7) < float(overlay.group(1))


FAKE_VECTOR = """
class Vec {
  constructor(x, y, z) { this.x = x; this.y = y; this.z = z; }
  clone() { return new Vec(this.x, this.y, this.z); }
  multiplyScalar(k) { this.x *= k; this.y *= k; this.z *= k; return this; }
  sub(v) { this.x -= v.x; this.y -= v.y; this.z -= v.z; return this; }
  toArray() { return [this.x, this.y, this.z]; }
}
"""


def run_framing_helpers(body):
    """Runs `body` (JavaScript) with the real framedView and reframePanel of web/controls.js and fake vectors; the
    last console.log is parsed as JSON. Skipped without node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed; the static checks above still cover the helpers")
    program = f"import {{ framedView, reframePanel }} from {json.dumps((WEB / 'controls.js').as_uri())};\n{FAKE_VECTOR}\n{body}"
    done = subprocess.run([node, "--input-type=module", "-e", program], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_framed_view_scales_the_offset_and_the_target_and_leaves_its_arguments_alone():
    out = run_framing_helpers("""
      const offset = new Vec(1.7, 0.8, 2.3), target = new Vec(0, 0.75, 0);
      const same = framedView(offset, target, 1), far = framedView(offset, target, 2.5 / 1.7);
      console.log(JSON.stringify({ same: [same.offset.toArray(), same.target.toArray()],
        far: [far.offset.toArray(), far.target.toArray()], args: [offset.toArray(), target.toArray()] }));""")
    assert out["same"] == [[1.7, 0.8, 2.3], [0, 0.75, 0]]  # scale 1 is the view as before
    assert out["far"][0] == pytest.approx([1.7 * 2.5 / 1.7, 0.8 * 2.5 / 1.7, 2.3 * 2.5 / 1.7])
    assert out["far"][1] == pytest.approx([0, 0.75 * 2.5 / 1.7, 0])
    assert out["args"] == [[1.7, 0.8, 2.3], [0, 0.75, 0]]


def test_reframe_panel_moves_the_live_camera_by_the_ratio_and_keeps_the_visitors_view():
    out = run_framing_helpers("""
      const panel = { tween: "flying", camera: { position: new Vec(-1.4, 2.6, 1.2) }, controls: { target: new Vec(0, 0.75, 0) }, placed: 0,
        place(offset, target) { this.placed += 1; this.controls.target = target; this.camera.position = target.clone(); this.offset = offset; } };
      const state = { framing: 1 };
      reframePanel(state, panel, 1);   // the same framing: nothing moves
      const idle = { framing: state.framing, placed: panel.placed, tween: panel.tween };
      reframePanel(state, null, 2);    // no 3D stage: only the framing is kept
      const headless = { framing: state.framing, placed: panel.placed };
      state.framing = 1;
      reframePanel(state, panel, 2);   // a body twice as tall: out by 2
      const moved = { framing: state.framing, placed: panel.placed, tween: panel.tween, offset: panel.offset.toArray(),
        target: panel.controls.target.toArray() };
      console.log(JSON.stringify({ idle, headless, moved }));""")
    assert out["idle"] == {"framing": 1, "placed": 0, "tween": "flying"}
    assert out["headless"] == {"framing": 2, "placed": 0}
    assert out["moved"]["framing"] == 2 and out["moved"]["placed"] == 1 and out["moved"]["tween"] is None
    assert out["moved"]["offset"] == pytest.approx([2 * (-1.4), 2 * (2.6 - 0.75), 2 * 1.2])  # camera minus target, doubled
    assert out["moved"]["target"] == pytest.approx([0, 1.5, 0])


COMPARE_STATURES = [[1.7, 1.7], [1.7, 1.85], [2.5, 1.7, 1.85], [1.55, 1.6], [None, 1.7], [1.85, None], [None, None]]


def compare_framings():
    """The expression compare.js frames its overlay camera by (`tallest`), evaluated by node on COMPARE_STATURES with the real
    framingScale, or a skip without node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed; the static checks above still cover the page")
    expression = re.search(r"const tallest = (Math\.max\(.*?\));", read("compare.js")).group(1)
    assert re.fullmatch(r"Math\.max\(\.\.\.runs\.map\(\(run\) => framingScale\(run\.metrics\.stature_m\)\)\)", expression)
    runs = json.dumps([[{"metrics": {"stature_m": s}} for s in group] for group in COMPARE_STATURES])
    program = f"import {{ framingScale }} from {json.dumps((WEB / 'controls.js').as_uri())};\n" \
              f"console.log(JSON.stringify({runs}.map((runs) => {expression})));"
    done = subprocess.run([node, "--input-type=module", "-e", program], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(done.stdout)


def test_the_compare_framing_is_one_at_the_default_height_and_follows_the_tallest_input():
    scales = compare_framings()
    assert scales[0] == 1  # two inputs at 1.70 m: the overlay view as before
    assert scales[1] == pytest.approx(1.85 / 1.7) and scales[2] == pytest.approx(2.5 / 1.7)  # the tallest decides
    # Shorter bodies, and a height that is not a number, add nothing.
    assert scales[3:] == [1, 1, pytest.approx(1.85 / 1.7), 1]


# ---- review R9: the sideways-scrolling tables box can be reached from the keyboard -------------------

def test_the_scrolling_tables_box_is_a_focusable_labelled_region():
    box = re.search(r'<div\b[^>]*\bclass="tables"[^>]*>', read("compare.html")).group(0)
    assert 'tabindex="0"' in box and 'role="region"' in box and 'aria-label="Result tables"' in box
    assert re.search(r"\.tables\s*\{[^}]*overflow-x:\s*auto", read("compare.css"))  # the box that scrolls is this one
    assert re.search(r"(?<![\w-]):focus-visible\s*\{[^}]*outline:", read("app.css"))  # a focused box shows an outline


def test_the_tables_box_change_keeps_the_page_csp_compatible_and_its_urls_relative():
    html = read("compare.html")
    assert absolute_urls_in_html(html) == [] and EVENT_ATTRIBUTE.search(html) is None
    assert html.lower().count("tabindex") == 1 and "tabindex" not in read("compare.js").lower()


# ---- the Compare result's source note names what the server applied (docs/specs/compare-mode.md AC-M05) ---------

# (options, note): the options a run echoed, or the raw field text of readOptions(), and the note they must give.
NOTE_CASES = [
    # What the server echoes: numbers, null for a blank Height and the Source frame rate.
    ({"body": "measured", "stature": 1.85, "view": "native", "fps": 30},
     "Body: measured, height 1.85 m. View: native. Frame rate: 30 per second."),
    ({"body": "part4-rig", "stature": 2.5, "view": "part5", "fps": 60},
     "Body: part4-rig, height 2.5 m. View: part5. Frame rate: 60 per second."),
    ({"body": "simon-standard", "stature": None, "view": "native", "fps": None},
     "Body: simon-standard, height the body's own. View: native. Frame rate: source."),  # the defaults: as before
    # The page's own field text (readOptions): a number in a string is still named, a blank one reads as the default.
    ({"body": "measured", "stature": "1.85", "view": "native", "fps": "30"},
     "Body: measured, height 1.85 m. View: native. Frame rate: 30 per second."),
    ({"body": "simon-standard", "stature": "", "view": "native", "fps": ""},
     "Body: simon-standard, height the body's own. View: native. Frame rate: source."),
    ({"body": "simon-standard", "stature": "  ", "view": "part4", "fps": "abc"},
     "Body: simon-standard, height the body's own. View: part4. Frame rate: source."),
    # An answer without the echo is not a crash.
    (None, "Body: n/a, height the body's own. View: n/a. Frame rate: source."),
]


def compare_notes():
    """The note compare.js builds for each of NOTE_CASES: its own `applied`, `named` and `sourceNote` (the text between
    `const applied` and `function fillCards`) run by node with the real isNum and NA of web/controls.js, or a skip."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed; the static checks above still cover the page")
    script = read("compare.js")
    start, end = script.index("const applied = "), script.index("function fillCards(")
    cases = json.dumps([options for options, _ in NOTE_CASES])
    program = f"import {{ NA, isNum }} from {json.dumps((WEB / 'controls.js').as_uri())};\n{script[start:end]}\n" \
              f"console.log(JSON.stringify({cases}.map(sourceNote)));"
    done = subprocess.run([node, "--input-type=module", "-e", program], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(done.stdout)


def test_the_compare_note_names_the_height_and_frame_rate_the_server_applied_and_reads_as_before_by_default():
    assert compare_notes() == [note for _, note in NOTE_CASES]


def test_the_compare_note_is_built_from_the_options_the_runs_echoed_not_from_the_field_text():
    script = read("compare.js")
    # Each kept run carries the options the server echoed, and the cards read the first run's (all runs got the same).
    assert re.search(r"function keepRun\(.*?\boptions: data\.options\b", script, re.S)
    assert 'byId("source-note").textContent = sourceNote(result.inputs[0].options);' in script
    # fillCards and showResult no longer take the page's readOptions() strings; the note builder never reads them.
    assert "function fillCards(result) {" in script and "function showResult(runs, compared) {" in script
    assert "fillCards(result);" in script and "showResult(runs, compared);" in script
    note = script[script.index("function sourceNote("):script.index("function fillCards(")]
    assert "readOptions" not in note and "options.stature" not in script.replace("heightError(options.stature)", "")
    assert "options.fps" not in script
    # The page still reads the field text to send it, and only for that.
    assert script.count("readOptions()") == 1 and "runAll(inputs, options)" in script


def test_the_server_echoes_the_height_and_frame_rate_as_numbers_the_note_names():
    options, bad = runapi.parse_options("body=measured&stature=1.85&view=native&fps=30")
    assert bad is None and options == {"body": "measured", "stature": 1.85, "view": "native", "fps": 30}
    status, body = runapi.handle("take-1", "auto", "", b"", options)
    assert status == 200 and body["options"] == options and body["metrics"]["stature_m"] == 1.85
    defaults, _ = runapi.parse_options("")
    assert defaults == {"body": "simon-standard", "stature": None, "view": "native", "fps": None}
