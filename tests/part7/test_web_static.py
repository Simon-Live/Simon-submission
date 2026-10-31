"""Static checks on web/: routes, data-testids, relative URLs, no build step, vendored three."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
OWNED = ["app", "api", "catalog", "watch", "record", "follow", "take-flow", "job", "capture", "countdown", "ui"]

# app.md "Web" table, testids this lane owns (result screen ids belong to the RESULT lane).
TESTIDS = {
    "views/library": ["search", "record"],  # the catalog screen draws through views/library.js (UI redesign)
    "watch": ["trainer-video", "viewer", "watch-frame", "follow"],
    "take-flow": ["name", "category", "save", "analyse", "record-again", "form-error"],
    "capture": ["cam-start", "cam-stop", "upload"],
    "job": ["stage", "retry"],
}


def src(name: str) -> str:
    return (WEB / f"{name}.js").read_text(encoding="utf-8")


def test_files_exist_and_no_build_step():
    for n in OWNED:
        assert (WEB / f"{n}.js").is_file(), n
    assert (WEB / "index.html").is_file() and (WEB / "styles.css").is_file()
    assert not list(WEB.glob("package.json")) and not list(WEB.glob("*.config.*"))
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert '<script type="module" src="app.js">' in index
    assert "node_modules" not in index and "https://" not in index and "http://" not in index


@pytest.mark.parametrize("name,ids", TESTIDS.items())
def test_testids_present(name, ids):
    text = src(name)
    for tid in ids:
        assert f'"data-testid": "{tid}"' in text or f'"{tid}"' in text, f"{name}: {tid}"


def test_entry_row_testid_pattern():
    assert "`entry-${c.id}`" in src("views/library")  # card data from model/library.js


def test_router_has_every_route():
    app = src("app")
    for frag in ["watch\\/", "record$", "follow\\/", "job\\/", "result\\/", "^$/"]:
        assert frag in app, frag
    assert "mountResult" in app and "./result.js" in app
    assert '"fixture"' in app


def test_result_lane_interface_names():
    assert "mountViewer" in src("watch") and "./result.js" in src("watch")
    assert "mountResult" in src("app")


def test_follow_message_origin_checked():
    w = src("watch")
    assert "simon:follow" in w and "event.origin !== origin" in w and "location.origin" in w


def test_urls_are_relative():
    for n in OWNED:
        text = src(n)
        assert not re.search(r"""["'`](https?:)?//""", text), n
        assert not re.search(r"""(fetch|href|src)\s*[=:(]\s*["'`]/[^/]""", text), n
        assert "location.origin" not in text or n == "watch"


def test_capture_follows_spec():
    c = src("capture")
    for frag in ['facingMode: "user"', "audio: false", "videoBitsPerSecond", "recorder_bps", "start(1000)",
                 "video/webm;codecs=vp9", "video/webm", "video/mp4", 'accept: "video/*"',
                 "Camera access is off. Allow it in the browser, or upload a video."]:
        assert frag in c, frag
    assert "scaleX(-1)" in (WEB / "styles.css").read_text(encoding="utf-8")
    assert "scaleX" not in c  # mirrored with CSS only


def test_error_messages_match_spec():
    a = src("api")
    for msg in ["This file is not a video. Pick an MP4 or WebM file.",
                "The video is too long (60 s at most).",
                "The file is too large (95 MB at most).",
                "You have used today's analyses. Try again tomorrow.",
                "The app is busy. Try again in a few minutes.",
                "This movement has no animation to follow."]:
        assert msg in a, msg


def test_no_em_dash_or_en_dash():
    for p in list(WEB.glob("*.js")) + [WEB / "index.html", WEB / "styles.css"]:
        text = p.read_text(encoding="utf-8")
        assert "—" not in text and "–" not in text, p.name


def test_vendored_three_hashes():
    readme = (WEB / "vendor" / "README.md").read_text(encoding="utf-8")
    rows = re.findall(r"\| `(web/vendor/[^`]+)` \| `[^`]+` \| `([0-9a-f]{64})` \|", readme)
    assert len(rows) == 3
    for rel, digest in rows:
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, rel
    assert "0.170.0" in readme
