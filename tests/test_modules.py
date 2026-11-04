"""Parts as git submodules tracking main (ADR-0007): `parts-status`, remote checks, module paths."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

import pytest

from part7 import modules, parts_gate

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


def test_check_remote_exits_0_when_a_pin_is_ahead_of_main(
    fake_parts: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """TICKET-380: a pin on a part's fix branch is not stale, and the JSON says it is ahead."""
    clone = fake_parts["1"].parents[1] / "modules" / "part-1"
    _git(clone, "commit", "-q", "--allow-empty", "-m", "fix branch")
    _git(clone, "push", "-q", "origin", "HEAD:refs/heads/fix-380")
    assert modules.cli_parts_status(check_remote=True) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["1"]["ahead"] is True and doc["1"]["remote_sha"] != doc["1"]["sha"] and "ahead" not in doc["2"]


def test_check_remote_exits_0_when_the_fix_branch_moved_past_the_pin(
    fake_parts: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """The branch head is not in the checkout yet: it is fetched, and it holds the pin."""
    clone = fake_parts["1"].parents[1] / "modules" / "part-1"
    _git(clone, "commit", "-q", "--allow-empty", "-m", "fix branch")
    _git(clone, "push", "-q", "origin", "HEAD:refs/heads/fix-380")
    _git(fake_parts["1"], "checkout", "-q", "fix-380")
    _commit(fake_parts["1"], "more on the fix branch")
    _git(fake_parts["1"], "checkout", "-q", "main")
    assert modules.cli_parts_status(check_remote=True) == 0
    assert json.loads(capsys.readouterr().out)["1"]["ahead"] is True


def test_check_remote_exits_3_when_main_was_rewound_below_the_pin(
    fake_parts: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """R6: the pin holds the rewound main, but no remote branch holds the pin, so this is no fix-branch pin."""
    remote = fake_parts["1"]
    old = _git(remote, "rev-parse", "HEAD")
    _commit(remote, "later reverted by a rewind")
    clone = remote.parents[1] / "modules" / "part-1"
    _git(clone, "pull", "-q", "origin", "main")
    _git(remote, "reset", "-q", "--hard", old)
    assert modules.cli_parts_status(check_remote=True) == modules.EXIT_STALE
    out = capsys.readouterr()
    assert "ahead" not in json.loads(out.out)["1"] and "part 1 differs from its remote main" in out.err


def test_check_remote_exits_3_when_the_pin_is_only_local(
    fake_parts: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    clone = fake_parts["1"].parents[1] / "modules" / "part-1"
    _git(clone, "commit", "-q", "--allow-empty", "-m", "never pushed")
    assert modules.cli_parts_status(check_remote=True) == modules.EXIT_STALE
    assert "ahead" not in json.loads(capsys.readouterr().out)["1"]


def test_check_remote_exits_3_when_a_pin_and_main_have_diverged(
    fake_parts: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    clone = fake_parts["1"].parents[1] / "modules" / "part-1"
    _git(clone, "commit", "-q", "--allow-empty", "-m", "fix branch")
    _commit(fake_parts["1"], "main moved past the pin's base")
    _git(clone, "fetch", "-q", "origin")
    assert modules.cli_parts_status(check_remote=True) == modules.EXIT_STALE
    assert "ahead" not in json.loads(capsys.readouterr().out)["1"]


def test_check_remote_exits_3_and_names_the_part_when_behind(
    fake_parts: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    new = _commit(fake_parts["4"], "second 4")
    assert modules.cli_parts_status(check_remote=True) == modules.EXIT_STALE == 3
    out = capsys.readouterr()
    assert json.loads(out.out)["4"]["remote_sha"] == new
    assert "part 4 differs from its remote main" in out.err and "part 1" not in out.err


def _fail_git(monkeypatch: pytest.MonkeyPatch, *words: str) -> None:
    """The git calls naming every one of `words` fail as a dropped network does; everything else really runs."""
    real = subprocess.run

    def run(cmd: Any, *args: Any, **kwargs: Any) -> Any:
        if all(word in cmd for word in words):
            return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="fatal: unable to access")
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(modules.subprocess, "run", run)


def _pin_on_a_branch_past_the_checkout(fake_parts: dict[str, Path]) -> None:
    clone = fake_parts["1"].parents[1] / "modules" / "part-1"
    _git(clone, "commit", "-q", "--allow-empty", "-m", "fix branch")
    _git(clone, "push", "-q", "origin", "HEAD:refs/heads/fix-380")
    _git(fake_parts["1"], "checkout", "-q", "fix-380")
    _commit(fake_parts["1"], "more on the fix branch")
    _git(fake_parts["1"], "checkout", "-q", "main")


@pytest.mark.parametrize("words", [("ls-remote", "--heads"), ("fetch",)])
def test_a_failed_branch_lookup_is_unknown_not_a_moved_main(
    fake_parts: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, words: tuple[str, ...]
) -> None:
    """R5: main was read, the branch lookup then failed. Nothing says the pin is on no branch, so exit 4 and no restart."""
    _pin_on_a_branch_past_the_checkout(fake_parts)
    _fail_git(monkeypatch, *words)
    assert modules.cli_parts_status(check_remote=True) == modules.EXIT_UNREACHABLE
    out = capsys.readouterr()
    doc = json.loads(out.out)
    assert "ahead" not in doc["1"] and doc["1"]["remote_sha"] is None
    assert "part 1: checkout or remote unreadable" in out.err and "differs from its remote main" not in out.err


def test_a_failed_branch_lookup_is_not_a_gate_candidate(fake_parts: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate reads the same status: an unknown part is not checked and adopted as a moved main."""
    _pin_on_a_branch_past_the_checkout(fake_parts)
    _fail_git(monkeypatch, "fetch")
    assert "1" not in parts_gate.candidates(modules.status(check_remote=True))


def test_a_pin_no_branch_holds_is_still_stale_when_every_lookup_answers(
    fake_parts: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """The negative of the two above: an answered lookup stays exit 3, with an empty fetch reading as success."""
    clone = fake_parts["1"].parents[1] / "modules" / "part-1"
    _git(clone, "commit", "-q", "--allow-empty", "-m", "local only")
    _git(fake_parts["1"], "checkout", "-q", "-b", "other")
    _commit(fake_parts["1"], "a branch the checkout lacks")
    _git(fake_parts["1"], "checkout", "-q", "main")
    assert modules.cli_parts_status(check_remote=True) == modules.EXIT_STALE
    assert json.loads(capsys.readouterr().out)["1"]["remote_sha"] is not None


def test_check_remote_exits_4_when_a_remote_is_unreadable(
    fake_parts: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _git(fake_parts["2"], "branch", "-m", "main", "trunk")
    assert modules.cli_parts_status(check_remote=True) == modules.EXIT_UNREACHABLE
    assert "part 2: checkout or remote unreadable" in capsys.readouterr().err


def test_exit_4_still_names_a_part_whose_remote_main_moved(fake_parts: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    """R-c: part 2 unreadable and part 4 moved: the exit is 4, and stderr names both so the moved one is not hidden."""
    _git(fake_parts["2"], "branch", "-m", "main", "trunk")
    _commit(fake_parts["4"], "main moved")
    assert modules.cli_parts_status(check_remote=True) == modules.EXIT_UNREACHABLE
    err = capsys.readouterr().err
    assert "part 2: checkout or remote unreadable" in err and "part 4 differs from its remote main" in err
    assert "part 2 differs" not in err


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


def test_head_sha_reads_the_checkout_fresh_each_call(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    first = _commit(repo, "one")
    assert modules.head_sha(repo) == first and len(first) == 40
    second = _commit(repo, "two")
    assert modules.head_sha(repo) == second != first  # not cached: a pin that moved is seen at once


def test_head_sha_is_none_when_the_path_is_not_a_checkout_or_is_missing(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert modules.head_sha(plain) is None
    assert modules.head_sha(tmp_path / "missing") is None


def test_head_sha_is_none_for_an_unborn_branch(tmp_path: Path) -> None:
    repo = tmp_path / "empty"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    assert modules.head_sha(repo) is None
