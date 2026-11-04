"""Release 16, AC-R16-1c: the served /privacy row for "You, doing it right" tells what the app does with the draw switch.

While `muse_fix.DRAW_ENABLED` is False the row says nothing is sent; once it is True the row must describe the frame that goes
to Meta, so switching draw on fails this test until the page is rewritten (docs/specs/result-release-16.md).
"""
from __future__ import annotations

import re

from part7 import legal_pages, muse_fix


def _row(page: str) -> str:
    rows = re.findall(r"<tr>.*?</tr>", page, flags=re.S)
    hit = [r for r in rows if "You, doing it right" in r]
    assert len(hit) == 1, "the privacy page has exactly one row for the feature"
    return re.sub(r"<[^>]+>", " ", hit[0])


def test_served_privacy_row_matches_the_draw_switch() -> None:
    page = (legal_pages.render("privacy") or b"").decode("utf-8")
    assert page, "the privacy page renders"
    row = _row(page)
    if muse_fix.DRAW_ENABLED:
        assert "guide drawn" in row and "Muse Image" in row, "draw is on: the row must say what frame goes to Meta"
    else:
        assert "nothing at present" in row and "switched off" in row
        assert "guide drawn" not in row and "Muse Image" not in row, "draw is off: no frame goes, so the row names none"
    assert "Needs lawyer review" not in page and "[TODO" not in page and "{{" not in page, "legal drafts rule: no placeholder, no banner"
