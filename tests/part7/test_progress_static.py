"""Static checks on the progress indicators (operator 2026-10-30): exports, test ids, aria, copy rules."""

from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"


def src(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def test_progress_exports_and_aria():
    s = src("progress.js")
    for name in ("createProgress", "showLoading", "hideLoading", "estimateText"):
        assert f"export function {name}(" in s, name
    for needle in ('role: "progressbar"', 'role: "status"', '"aria-live": "polite"', "aria-valuenow", "aria-valuemin", "aria-valuemax"):
        assert needle in s, needle
    for tid in ("progress-bar", "progress-text", "progress-elapsed"):
        assert f'"{tid}"' in s, tid


def test_screens_use_the_component():
    assert '"upload-progress"' in src("take-flow.js") and "onProgress" in src("take-flow.js")
    assert "XMLHttpRequest" in src("api.js") and "upload.onprogress" in src("api.js")
    assert '"people-progress"' in src("people.js")
    assert 'testid: "progress"' in src("job.js") and "group-progress" in src("job.js")
    for n in ("watch.js", "follow.js", "app.js", "trim.js"):
        assert "showLoading" in src(n), n


def test_people_continue_is_hidden_while_looking_and_explained_when_disabled():
    s = src("people.js")
    assert 'text: "Continue", hidden: true' in s
    assert "people-continue-reason" in s


def test_no_em_dash_in_progress_files():
    for n in ("progress.js", "progress.css", "people.js", "job.js", "take-flow.js", "api.js"):
        assert "—" not in src(n) and "–" not in src(n), n
