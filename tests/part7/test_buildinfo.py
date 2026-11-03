"""Build stamp: buildinfo module, api/version and api/health (app.md AC-A13, AC-A14, AC-A16)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import re
import subprocess

import pytest

from part7 import buildinfo

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 30, 16, 50, 7, tzinfo=timezone.utc)
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_COMMITTER_DATE": "2026-10-30T18:00:00+02:00", "GIT_AUTHOR_DATE": "2026-10-30T18:00:00+02:00",
        "PATH": os.environ["PATH"], "HOME": str(tmp_path),
    }
    for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "x"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, env=env)
    out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    return root, out.stdout.strip()


PARTS = {"1": "a" * 9, "2": "b" * 9}


@needs_git
def test_git_present(tmp_path: Path) -> None:
    root, sha = _repo(tmp_path)
    doc = buildinfo.collect(root, NOW, PARTS, env="local")
    assert doc == {
        "sha": sha, "short": sha[:9], "committed_at": "2026-10-30T16:00:00Z", "subject": "x",
        "started_at": "2026-10-30T16:50:07Z", "parts": {"1": "a" * 9, "2": "b" * 9}, "environment": "local",
    }


@needs_git
def test_not_a_git_checkout_gives_unknown(tmp_path: Path) -> None:
    # tmp_path sits outside any repository, so git finds no checkout here.
    doc = buildinfo.collect(tmp_path, NOW, PARTS)
    assert doc["sha"] == doc["short"] == doc["committed_at"] == doc["subject"] == "unknown"
    assert doc["started_at"] == "2026-10-30T16:50:07Z" and doc["parts"] == {"1": "a" * 9, "2": "b" * 9}


def test_git_binary_missing_gives_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr(buildinfo.subprocess, "run", boom)
    doc = buildinfo.collect(tmp_path, NOW, PARTS)
    assert doc["short"] == "unknown" and doc["committed_at"] == "unknown"


@needs_git
def test_parts_default_to_the_modules_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, sha = _repo(tmp_path)
    monkeypatch.setattr(buildinfo.modules, "short_map", lambda: {"3": "c" * 9})
    assert buildinfo.collect(root, NOW)["parts"] == {"3": "c" * 9}


def test_modules_failure_gives_no_parts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> None:
        raise OSError("no modules")

    monkeypatch.setattr(buildinfo.modules, "short_map", boom)
    assert buildinfo.collect(tmp_path, NOW)["parts"] == {}


def test_version_route_and_health_carry_the_build(api) -> None:  # type: ignore[no-untyped-def]
    api.app.build = {
        "sha": "s" * 40, "short": "s" * 9, "committed_at": "2026-10-30T16:00:00Z",
        "started_at": "2026-10-30T16:50:07Z", "parts": {"1": "a" * 9},
    }
    status, _, data = api.request("GET", "api/version")
    assert status == 200 and json.loads(data) == api.app.build
    health = json.loads(api.request("GET", "api/health")[2])
    assert health["build"] == api.app.build and health["ok"] is True and "pins" in health


def test_build_app_fills_the_build(api) -> None:  # type: ignore[no-untyped-def]
    assert set(api.app.build) == {"sha", "short", "committed_at", "subject", "started_at", "parts", "environment"}
    assert api.app.build["started_at"].endswith("Z")


def test_build_line_is_in_the_header_and_web_unit_tests_pass():
    index = (ROOT / "web/index.html").read_text(encoding="utf-8")
    header = index.split("<header", 1)[1].split("</header>", 1)[0]
    assert re.search(r'<div id="build"[^>]*hidden', header) and "<footer" not in header  # TICKET-326: the footer is below main
    assert "mountBuildStamp" in (ROOT / "web/app.js").read_text(encoding="utf-8")
    for name in ("build.js", "styles.css"):
        text = (ROOT / "web" / name).read_text(encoding="utf-8")
        assert "—" not in text and "–" not in text, name
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, "--test", str(ROOT / "tests/part7/build.unit.test.mjs"),
                        str(ROOT / "tests/part7/build.dom.test.mjs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
