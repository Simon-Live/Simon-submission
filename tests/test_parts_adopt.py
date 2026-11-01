"""parts-adopt: the gate's validated shas and the HEAD pins, not the remote main of the moment (TICKET-192)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from part7 import parts_adopt


def git(cwd: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin", "HOME": str(cwd)}
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout.strip()


def commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", name)
    return git(repo, "rev-parse", "HEAD")


class World:
    """A remote part repo with three commits and a module clone sitting at the first."""

    def __init__(self, tmp: Path) -> None:
        self.remote = tmp / "remote"
        self.remote.mkdir()
        git(self.remote, "init", "-q", "-b", "main")
        self.c1 = commit(self.remote, "one")
        self.c2 = commit(self.remote, "two")
        self.mods = tmp / "modules"
        self.mods.mkdir()
        self.module = self.mods / "part-3"
        git(tmp, "clone", "-q", str(self.remote), str(self.module))
        git(self.module, "checkout", "-q", "--detach", self.c1)
        self.gdir = tmp / "gate"
        self.gdir.mkdir()
        self.moved_setup: list[list[str]] = []

    def setup(self, moved: list[str]) -> int:
        self.moved_setup.append(moved)
        return 0

    def green(self, sha: str) -> None:
        (self.gdir / "last.json").write_text(json.dumps({"outcome": "green", "candidate_shas": {"3": sha}}))

    def head(self) -> str:
        return git(self.module, "rev-parse", "HEAD")


def test_validated_adoption_takes_the_gated_sha_even_when_the_remote_moved_again(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.green(w.c2)
    c3 = commit(w.remote, "three")  # the part pushed again after the gate validated c2
    assert parts_adopt.adopt_validated(w.mods, w.gdir, w.setup) == 0
    assert w.head() == w.c2 != c3
    assert w.moved_setup == [["3"]]


def test_validated_adoption_never_moves_backwards_or_on_a_non_green_record(tmp_path: Path) -> None:
    w = World(tmp_path)
    git(w.module, "fetch", "-q", "origin")
    git(w.module, "checkout", "-q", "--detach", w.c2)
    w.green(w.c1)  # a stale green record older than the served module
    assert parts_adopt.adopt_validated(w.mods, w.gdir, w.setup) == 1
    assert w.head() == w.c2
    (w.gdir / "last.json").write_text(json.dumps({"outcome": "red", "candidate_shas": {"3": w.c1}}))
    assert parts_adopt.adopt_validated(w.mods, w.gdir, w.setup) == 1
    assert w.head() == w.c2


def test_validated_adoption_is_idempotent_and_runs_no_setup_when_nothing_moves(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.green(w.c1)
    assert parts_adopt.adopt_validated(w.mods, w.gdir, w.setup) == 0
    assert w.moved_setup == [[]]


def make_superproject(tmp: Path, pin: str) -> Path:
    repo = tmp / "p7"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, "readme")
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{pin},modules/part-3")
    git(repo, "commit", "-q", "-m", "pin")
    return repo


def repin(repo: Path, pin: str) -> None:
    git(repo, "update-index", "--cacheinfo", f"160000,{pin},modules/part-3")
    git(repo, "commit", "-q", "-m", "repin")


def test_pins_are_recorded_first_then_a_changed_pin_is_adopted_inline(tmp_path: Path) -> None:
    w = World(tmp_path)
    repo = make_superproject(tmp_path, w.c1)
    state = tmp_path / "pins.json"
    assert parts_adopt.head_pins(repo) == {"3": w.c1}
    assert parts_adopt.adopt_pins(repo, w.mods, state, w.setup) == 0  # first run: record only
    assert json.loads(state.read_text()) == {"3": w.c1} and w.moved_setup == []
    repin(repo, w.c2)
    assert parts_adopt.adopt_pins(repo, w.mods, state, w.setup) == 0
    assert w.head() == w.c2 and w.moved_setup == [["3"]]
    assert json.loads(state.read_text()) == {"3": w.c2}


def test_an_adopted_upstream_sha_is_not_rolled_back_to_an_unchanged_pin(tmp_path: Path) -> None:
    w = World(tmp_path)
    repo = make_superproject(tmp_path, w.c1)
    state = tmp_path / "pins.json"
    assert parts_adopt.adopt_pins(repo, w.mods, state, w.setup) == 0
    w.green(w.c2)
    assert parts_adopt.adopt_validated(w.mods, w.gdir, w.setup) == 0  # the gate moved the module beyond the pin
    assert parts_adopt.adopt_pins(repo, w.mods, state, w.setup) == 0
    assert w.head() == w.c2


def test_a_pin_missing_from_the_module_is_an_error_and_is_retried(tmp_path: Path) -> None:
    w = World(tmp_path)
    repo = make_superproject(tmp_path, w.c1)
    state = tmp_path / "pins.json"
    assert parts_adopt.adopt_pins(repo, w.mods, state, w.setup) == 0
    repin(repo, "d" * 40)
    assert parts_adopt.adopt_pins(repo, w.mods, state, w.setup) == 1
    assert w.head() == w.c1 and json.loads(state.read_text()) == {"3": w.c1}
