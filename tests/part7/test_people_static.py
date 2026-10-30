"""Static checks on the people and group web files (people.md): testids, exports, relative URLs, copy rules."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "web"
FILES = ["people.js", "group.js", "group-result.js", "multi-compare.js", "people.css"]
# files other lanes own: this lane must not have changed what they export
TESTIDS = {
    "people.js": ["people", "people-frame", "people-continue", "people-error", "person-${p.id}", "person-trainer-${p.id}", "person-label-${p.id}"],
    "group.js": ["mode-solo", "mode-group"],
    "group-result.js": ["group-board", "group-row-${r.id}", "group-score-${r.id}", "group-grade-${r.id}", "watch-all"],
    "multi-compare.js": ["group-toggle-${u.id}"],
}


def src(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def test_files_exist_and_are_small():
    for n in FILES:
        assert (WEB / n).is_file(), n
        assert len(src(n).splitlines()) < 300, n


@pytest.mark.parametrize("name,ids", TESTIDS.items())
def test_testids(name, ids):
    for i in ids:
        assert f'"{i}"' in src(name) or f"`{i}`" in src(name), (name, i)


def test_exports_for_the_integrator():
    assert re.search(r"export function openPeoplePicker\(root, \{[^}]*peopleJob[^}]*mode", src("people.js"))
    assert "export function mountGroupResult(root, jobId)" in src("group-result.js")
    assert "export function mountModeSwitch(" in src("group.js")
    assert "export async function mountMultiCompare(" in src("multi-compare.js")


def test_urls_are_relative_and_no_build_step():
    for n in FILES:
        text = src(n)
        assert not re.search(r"""["'`]/(api|catalog)/""", text), n
        assert "http://" not in text and "https://" not in text, n


def test_reuses_compare_and_viewer_not_copies():
    text = src("multi-compare.js")
    assert 'from "./compare.js"' in text and 'import("./viewer3d.js")' in text
    assert "THREE" not in text


def test_no_em_dash_or_en_dash():
    for n in FILES:
        assert "\u2014" not in src(n) and "\u2013" not in src(n), n


def test_limits_match_the_spec():
    g = src("group.js")
    assert "GROUP_MAX_FOLLOWERS = 8" in g and "GROUP_MAX_MS = 30000" in g
