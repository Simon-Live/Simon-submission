"""TICKET-187 (L12): publish/overrides.json is disclosure of the firm's own comment, never consent.

The guard (scripts/simon-publish.sh, AC-P28 in tests/publish/test-simon-publish.sh) accepts an override only when
it cites a client reply on moalborati/simon#61. Every committed entry cites the firm's own comment 6554168349, so the
file keeps them under `provisional_disclosure`, a key the guard never reads as a path.
"""
import json
from pathlib import Path

import pytest

FILE = Path(__file__).resolve().parents[2] / "publish" / "overrides.json"
# publish/ is firm-only and not published: the published tree checks nothing here (TICKET-197)
pytestmark = pytest.mark.skipif(not FILE.is_file(), reason="publish/overrides.json is not in the published tree")
OWN_COMMENT = "6554168349"


def test_only_provisional_disclosure_at_the_top_level():
    doc = json.loads(FILE.read_text(encoding="utf-8"))
    assert list(doc) == ["provisional_disclosure"], "a top-level path entry would read as consent"


def test_every_disclosed_entry_cites_the_firms_own_comment():
    doc = json.loads(FILE.read_text(encoding="utf-8"))["provisional_disclosure"]
    entries = {k: v for k, v in doc.items() if k != "_note"}
    assert entries
    for path, shas in entries.items():
        assert all(url.endswith(OWN_COMMENT) for url in shas.values()), path
