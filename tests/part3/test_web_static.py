"""Static checks of the web pages (docs/specs/run-app.md AC-NFR-04 and the run page wiring).

No browser: the files are read as text. The browser drive lives in staging/verify.mjs.
"""

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
HTML_FILES = ["app.html", "index.html"]
JS_FILES = ["app.js", "viewer.js", "scene.js"]

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
    # `data:,` is the empty icon that stops a /favicon.ico request; it names no address.
    return [u for u in ATTR_URL.findall(text) if u != "data:," and not is_relative(u)]


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
    app, index = import_map(read("app.html")), import_map(read("index.html"))
    assert app == index
    assert app["imports"]["three"] == "./vendor/three/three.module.js"
    for url in app["imports"].values():
        assert url.startswith("./") and is_relative(url)


def test_app_html_loads_its_own_files_as_a_module():
    html = read("app.html")
    assert '<script type="module" src="app.js"></script>' in html
    assert '<link rel="stylesheet" href="app.css">' in html
    assert 'href="agreement"' in html


def test_index_links_back_to_the_run_page():
    assert re.search(r'<a [^>]*href="\./"[^>]*>Run the pipeline</a>', read("index.html"))


def test_every_byid_call_in_app_js_is_a_literal():
    # A computed id cannot be checked against app.html, so every lookup spells its id out.
    bad = [m.group(0) for m in BYID_CALL.finditer(read("app.js")) if m.group(1) != '"']
    assert bad == []


def test_every_id_app_js_looks_up_exists_in_app_html():
    ids = set(HTML_ID.findall(read("app.html")))
    wanted = set(BYID_LITERAL.findall(read("app.js")))
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
    html, script = read("app.html"), read("app.js")
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


def test_app_js_renders_server_text_with_textcontent_only():
    script = read("app.js")
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert banned not in script, banned
    assert "textContent" in script


def test_run_page_copy_has_no_em_or_en_dash():
    for name in ("app.html", "app.js"):
        text = read(name)
        assert "—" not in text and "–" not in text, name
