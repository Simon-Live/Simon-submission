"""No street address in anything Simon sends or shows: sign-in emails, legal pages, the app's page words.

The team, 2026-11-04: a street address appeared on simon.live and in the sign-in emails and must never be sent
anywhere. This test fails if any of these holds one. Each source that exists in this checkout is read; one that does
not (the server's legal pages arrive with the live code) is skipped, not passed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email import policy
import importlib
from pathlib import Path
import re

import pytest

from part7 import mail

ROOT = Path(__file__).resolve().parents[2]

# A house number, one to four words, then a street word: "12 Example Street", "4 Main St", "100 Ocean Ave, Suite 2".
STREET = re.compile(
    r"\b\d{1,6}\s+(?:[A-Z][A-Za-z.'-]*\s+){1,4}"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Way|Court|Ct|Place|Pl|Terrace|Parkway|Pkwy|Highway|Hwy|Square|Sq)\b\.?"
)
# "Suite 12", "Apt 4B", "Unit 7", a US ZIP after a state: also give an address away on their own
EXTRA = re.compile(r"\b(?:Suite|Apt\.?|Apartment|Unit)\s+\w+|\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b")


def addresses(text: str) -> list[str]:
    return [m.group(0) for m in STREET.finditer(text)] + [m.group(0) for m in EXTRA.finditer(text)]


def test_the_patterns_catch_an_address_and_leave_ordinary_text_alone() -> None:
    assert addresses("Write to us at 12 Example Street, Springfield.")
    assert addresses("Simon Live LLC, Suite 4")
    assert addresses("Anytown, NY 10001")
    assert not addresses("Last updated 4 November 2026. Keep 3 takes for 7 days. Part 2 runs on 1 GPU.")
    assert not addresses("the Hamilton product of two quaternions")


def test_the_sign_in_email_has_no_address() -> None:
    msg = mail.build_message("judge@example.com", mail.DEFAULT_FROM, "123456", "https://simon.live/#/signin/x",
                             datetime(2026, 11, 4, tzinfo=timezone.utc))
    for part in msg.walk():
        if part.get_content_maintype() == "text":
            assert addresses(part.get_content()) == [], part.get_content_type()
    assert addresses(msg.as_string(policy=policy.default)) == []


@pytest.mark.parametrize("folder", ["docs/legal", "web/model"])
def test_the_legal_texts_and_page_words_have_no_address(folder: str) -> None:
    base = ROOT / folder
    if not base.is_dir():
        pytest.skip(f"{folder} is not in this checkout")
    found = {}
    for path in sorted(base.rglob("*")):
        if path.suffix in (".md", ".js", ".html", ".txt", ".json") and path.is_file():
            hits = addresses(path.read_text(encoding="utf-8", errors="replace"))
            if hits:
                found[str(path.relative_to(ROOT))] = hits
    assert found == {}


def test_the_server_legal_pages_have_no_address() -> None:
    try:
        pages = importlib.import_module("part7.legal_pages")
    except ImportError:
        pytest.skip("the server's legal pages are not in this checkout yet (they arrive with the live code)")
    render = getattr(pages, "render", None) or getattr(pages, "render_page", None)
    names = getattr(pages, "PAGES", None) or getattr(pages, "PAGE_NAMES", None)
    if render is None or names is None:
        pytest.skip("part7.legal_pages has no render(name) and PAGES this test knows how to call")
    for name in names:
        html = render(name)
        assert addresses(re.sub(r"<[^>]+>", " ", html if isinstance(html, str) else html.decode())) == [], name
