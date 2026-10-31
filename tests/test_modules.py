"""Parts as git submodules tracking main (ADR-0007): `parts-status`, remote checks, module paths."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from part7 import modules

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(path: Path, *args: str) -> str:
    env = {**os.environ, **GIT_ENV}
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, check=True, env=env).stdout.strip()


def _commit(repo: Path, note: str) -> str:
    (repo / "note.txt").write_text(note, encoding="utf-8")
    _git(repo, "add", "note.txt")
    _git(repo, "commit", "-q", "-m", note)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def fake_parts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Six fake part remotes on `main`, each cloned to `<tmp>/modules/part-N`."""
    remotes: dict[str, Path] = {}
    (tmp_path / "modules").mkdir()
    for n in modules.PART_IDS:
        remote = tmp_path / "remotes" / f"part-{n}"
        remote.mkdir(parents=True)
        _git(remote, "init", "-q", "-b", "main")
        _commit(remote, f"first {n}")
        _git(tmp_path, "clone", "-q", str(remote), str(tmp_path / "modules" / f"part-{n}"))
        remotes[n] = remote
    monkeypatch.setenv("SIMON7_MODULES_DIR", str(tmp_path / "modules"))
    return remotes


def test_status_shape_without_remote_check(fake_parts: dict[str, Path]) -> None:
    doc = modules.status()
    assert list(doc) == list(modules.PART_IDS)
    one = doc["1"]
    assert set(one) == {"path", "sha", "short", "url", "branch", "remote_sha"}
    assert len(one["sha"]) == 40 and one["short"] == one["sha"][:9]
    assert one["url"] == str(fake_parts["1"]) and one["branch"] == "main" and one["remote_sha"] is None
    assert one["sha"] == _git(fake_parts["1"], "rev-parse", "HEAD")


def test_check_remote_exits_0_when_all_current(fake_parts: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    assert modules.cli_parts_status(check_remote=True) == 0
    doc = json.loads(capsys.readouterr().out)
    assert all(p["remote_sha"] == p["sha"] for p in doc.values())


def test_check_remote_exits_3_and_names_the_part_when_behind(
    fake_parts: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    new = _commit(fake_parts["4"], "second 4")
    assert modules.cli_parts_status(check_remote=True) == modules.EXIT_STALE == 3
    out = capsys.readouterr()
    assert json.loads(out.out)["4"]["remote_sha"] == new
    assert "part 4 is behind" in out.err and "part 1" not in out.err


def test_check_remote_exits_4_when_a_remote_is_unreadable(
    fake_parts: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _git(fake_parts["2"], "branch", "-m", "main", "trunk")
    assert modules.cli_parts_status(check_remote=True) == modules.EXIT_UNREACHABLE
    assert "part 2: checkout or remote unreadable" in capsys.readouterr().err


def test_missing_module_has_null_sha(fake_parts: dict[str, Path], tmp_path: Path) -> None:
    import shutil

    shutil.rmtree(tmp_path / "modules" / "part-5")
    doc = modules.status()
    assert doc["5"]["sha"] is None and doc["5"]["short"] is None
    assert modules.cli_parts_status() == 0


def test_modules_sha_follows_the_checkout_and_caches(fake_parts: dict[str, Path], tmp_path: Path) -> None:
    mods = modules.load()
    first = mods.sha("3")
    assert mods.path("3") == tmp_path / "modules" / "part-3" and first == _git(fake_parts["3"], "rev-parse", "HEAD")
    new = _commit(fake_parts["3"], "second 3")
    _git(mods.path("3"), "pull", "-q")
    assert mods.sha("3") == first  # a snapshot, like the build stamp
    assert modules.load().sha("3") == new and modules.load().sha12("3") == new[:12]
    assert modules.load().shas_short()["3"] == new[:12]


def test_not_a_checkout_raises_module_error(tmp_path: Path) -> None:
    with pytest.raises(modules.ModuleError, match="part 1"):
        modules.Modules(root=tmp_path).sha("1")


def test_short_map_feeds_the_build_stamp(fake_parts: dict[str, Path]) -> None:
    short = modules.short_map()
    assert set(short) == set(modules.PART_IDS)
    assert short["2"] == _git(fake_parts["2"], "rev-parse", "HEAD")[:9]
