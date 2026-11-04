"""A legal route in the app (web/legal.js, web/model/legal-server.js) reads the server's page: part7/legal_pages.py renders
the real docs/legal/ file and the app's parser, run in node, keeps every word. A made-up address, never the real one."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from part7 import legal_pages

ROOT = Path(__file__).resolve().parents[2]
ADDRESS = "1 Made Up Way, Nowhere"
PARSE = (
    "import { parseLegalHtml } from %s;"
    "let s = ''; for await (const c of process.stdin) s += c;"
    "process.stdout.write(JSON.stringify(parseLegalHtml(s, process.argv[1])));"
)


def _parse(html: bytes, key: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available")
    code = PARSE % json.dumps((ROOT / "web/model/legal-server.js").as_uri())
    done = subprocess.run([node, "--input-type=module", "-e", code, key], input=html, capture_output=True, check=True, timeout=60)
    return json.loads(done.stdout)


def test_the_dmca_route_draws_the_server_text_with_the_configured_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(legal_pages, "postal_address", lambda: ADDRESS)
    page = _parse(legal_pages.render("dmca"), "dmca")
    assert page["title"] == legal_pages.TITLES["dmca"]
    text = json.dumps(page, ensure_ascii=False)
    assert ADDRESS in text
    assert legal_pages.ADDRESS_TOKEN not in text and "{{" not in text  # negative: no raw token


@pytest.mark.parametrize("key", list(legal_pages.PAGES))
def test_every_legal_page_keeps_every_heading(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(legal_pages, "postal_address", lambda: ADDRESS)
    body = legal_pages.render(key)
    assert body is not None, key
    page = _parse(body, key)
    drawn = [s["heading"] for s in page["sections"] if s["heading"]]
    main = body.decode().split("<main", 1)[1]
    assert len(drawn) == main.count("<h2>") + main.count("<h3>"), key
    assert page["updated"].startswith("Last updated"), key


def test_a_missing_address_gives_no_page_so_the_app_shows_its_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(legal_pages, "postal_address", lambda: None)
    assert legal_pages.render("dmca") is None  # the route answers 404; web/legal.js then says the page did not load
