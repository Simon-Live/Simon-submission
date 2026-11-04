"""deploy/judges/run.sh and the catalog: each start heals our four movements and leaves a judge's recordings alone.

Runs the real script in a throwaway copy of the layout it needs, with `curl`, `make` and `uv` stubbed on PATH, so no
relay is called and no server starts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

from part7 import entry_access

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = sorted(p for p in (ROOT / "deploy" / "judges" / "catalog").iterdir() if p.is_dir())


def _stub(folder: Path, name: str, body: str) -> None:
    path = folder / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _run(tmp_path: Path, state: Path, entries: list[Path] | None = None) -> subprocess.CompletedProcess:
    repo = tmp_path / "repo"
    judges = repo / "deploy" / "judges"
    judges.mkdir(parents=True, exist_ok=True)
    (repo / "modules" / "part-1").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "deploy" / "judges" / "run.sh", judges / "run.sh")
    (judges / "signin_codes.py").write_text("", encoding="utf-8")
    samples = repo / "modules" / "part-6" / "fixtures" / "output" / "catalog" / "sample-one"
    samples.mkdir(parents=True, exist_ok=True)
    for entry in entries if entries is not None else SHIPPED:
        shutil.copytree(entry, judges / "catalog" / entry.name, dirs_exist_ok=True)
    stubs = tmp_path / "stubs"
    stubs.mkdir(exist_ok=True)
    _stub(stubs, "curl", """printf '{"open":true}'""")
    _stub(stubs, "make", "exit 0")
    _stub(stubs, "uv", "exit 0")
    env = {**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}", "HOME": str(tmp_path / "home"),
           "SIMON7_STATE_DIR": str(state), "SIMON_PORT": "0"}
    return subprocess.run(["bash", str(judges / "run.sh")], env=env, capture_output=True, text=True, timeout=60)


def _manifest(folder: Path) -> dict:
    return json.loads((folder / "manifest.json").read_text(encoding="utf-8"))


def test_a_stale_copy_of_ours_is_healed_and_its_extra_files_stay(tmp_path):
    state = tmp_path / "state"
    catalog = state / "dev" / "catalog"
    shipped = SHIPPED[0]
    stale = catalog / shipped.name
    shutil.copytree(shipped, stale)
    doc = _manifest(stale)
    doc["files_source"] = "import"  # what an older run.sh left behind
    (stale / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    (stale / "video.mp4").write_bytes(b"old bytes")
    (stale / "narration.json").write_text("{}", encoding="utf-8")  # a file we do not ship
    assert not entry_access.shipped_sample(catalog, shipped.name)

    done = _run(tmp_path, state)

    assert done.returncode == 0, done.stderr
    assert entry_access.shipped_sample(catalog, shipped.name)
    assert (stale / "manifest.json").read_bytes() == (shipped / "manifest.json").read_bytes()
    assert (stale / "video.mp4").read_bytes() == (shipped / "video.mp4").read_bytes()
    assert (stale / "narration.json").read_text(encoding="utf-8") == "{}"
    assert sorted(p.name for p in catalog.iterdir() if p.is_dir()) == [p.name for p in SHIPPED]
    assert not (stale / shipped.name).exists()  # the folder's contents went in, not a folder inside it


def test_a_judges_own_recording_is_untouched(tmp_path):
    state = tmp_path / "state"
    catalog = state / "dev" / "catalog"
    mine = catalog / "my-recording-abc12345"
    mine.mkdir(parents=True)
    (mine / "manifest.json").write_text('{"files_source": "import"}', encoding="utf-8")
    (mine / "video.mp4").write_bytes(b"a judge's own video")
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in mine.iterdir()}

    done = _run(tmp_path, state)

    assert done.returncode == 0, done.stderr
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in mine.iterdir()} == before
    for shipped in SHIPPED:  # the four arrive beside it
        assert entry_access.shipped_sample(catalog, shipped.name)


def test_an_empty_catalog_gets_our_four_as_real_videos(tmp_path):
    state = tmp_path / "state"
    catalog = state / "dev" / "catalog"

    done = _run(tmp_path, state)

    assert done.returncode == 0, done.stderr
    for shipped in SHIPPED:
        assert entry_access.shipped_sample(catalog, shipped.name)
        head = (catalog / shipped.name / "video.mp4").read_bytes()[:12]
        assert head[4:8] == b"ftyp"  # an MP4, not a Git LFS pointer


def test_the_four_are_marked_as_samples_in_the_repo():
    assert len(SHIPPED) == 4
    assert all(_manifest(p)["files_source"] == entry_access.SAMPLE_SOURCE for p in SHIPPED)
