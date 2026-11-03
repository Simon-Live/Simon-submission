"""Adopt part shas without a remote lookup (TICKET-192, docs/specs/staging.md "Part updates are checked ...").

Two moves, both to a sha somebody already validated:
- `--validated`: the shas the staging parts gate recorded green in `<state>/parts-gate/last.json`, forward only.
  Never the remote main of this moment (it may have moved again since the gate ran).
- `--pins`: the gitlinks Part 7's own HEAD commits (a release that re-pins Part 4 or 5). The release's tests
  validated those; only a gitlink that changed since the last run is applied, so an adopted upstream sha is not
  rolled back to the pin on every run.
Both then run part setup for the moved parts only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable

from part7 import config, parts_gate

PINS_FILE = "parts-pins.json"
GIT_TIMEOUT_S = 120


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=GIT_TIMEOUT_S, env=env)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(list(args), 124, "", "git timed out")


def head_pins(repo: Path) -> dict[str, str]:
    """`{part: sha}` of the gitlinks committed on `repo` HEAD."""
    out = _git(repo, "ls-tree", "HEAD", "modules/")
    pins: dict[str, str] = {}
    for line in out.stdout.splitlines():
        found = re.match(r"160000 commit ([0-9a-f]{40})\tmodules/part-(\d)$", line)
        if found:
            pins[found.group(2)] = found.group(1)
    return pins


def _has(module: Path, sha: str) -> bool:
    return _git(module, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def _move(module: Path, sha: str, forward_only: bool) -> str | None:
    """Detach `module` at `sha`; an error text, or None when moved or already there."""
    cur = _git(module, "rev-parse", "HEAD").stdout.strip()
    if cur == sha:
        return None
    if not _has(module, sha):
        _git(module, "fetch", "-q", "origin")
        if not _has(module, sha):
            return f"{sha[:12]} is not in the module (fetch did not bring it)"
    if forward_only and cur and _git(module, "merge-base", "--is-ancestor", cur, sha).returncode != 0:
        return f"{sha[:12]} is not ahead of the checked-out {cur[:12]}; not moving backwards"
    moved = _git(module, "checkout", "-q", "--detach", sha)
    return None if moved.returncode == 0 else moved.stderr.strip() or "git checkout failed"


def _setup(moved: list[str]) -> int:
    from part7 import setup_parts

    return setup_parts.cli_setup_parts(only=tuple(moved)) if moved else 0


def _read(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _write(path: Path, doc: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _report(kind: str, moved: list[str], errors: dict[str, str]) -> None:
    print(json.dumps({"adopt": kind, "moved": moved, "errors": errors}))
    for part, err in errors.items():
        print(f"parts-adopt: part {part}: {err}", file=sys.stderr)


def _apply(mods: Path, wanted: dict[str, str], forward_only: bool) -> tuple[list[str], dict[str, str]]:
    moved: list[str] = []
    errors: dict[str, str] = {}
    for part, sha in sorted(wanted.items()):
        module = mods / f"part-{part}"
        if not (module / ".git").exists():
            errors[part] = "no module checkout"
            continue
        before = _git(module, "rev-parse", "HEAD").stdout.strip()
        err = _move(module, sha, forward_only)
        if err:
            errors[part] = err
        elif before != sha:
            moved.append(part)
    return moved, errors


def adopt_validated(mods: Path, gdir: Path, setup: Callable[[list[str]], int] = _setup) -> int:
    """Move each part to the sha the last green gate validated. Exit 1 when there is no green record or a part failed."""
    last = _read(gdir / "last.json")
    shas = last.get("candidate_shas")
    if last.get("outcome") != "green" or not isinstance(shas, dict) or not shas:
        _report("validated", [], {"gate": "last.json holds no green gate result; nothing adopted"})
        return 1
    moved, errors = _apply(mods, {str(k): str(v) for k, v in shas.items()}, forward_only=True)
    rc = setup(moved)
    _report("validated", moved, errors)
    return 1 if errors or rc != 0 else 0


def adopt_pins(repo: Path, mods: Path, state_file: Path, setup: Callable[[list[str]], int] = _setup) -> int:
    """Apply the HEAD gitlinks that changed since the last run. The first run only records them."""
    pins = head_pins(repo)
    seen = _read(state_file)
    if not seen:
        _write(state_file, pins)
        _report("pins", [], {})
        return 0
    changed = {p: s for p, s in pins.items() if seen.get(p) != s}
    moved, errors = _apply(mods, changed, forward_only=False)
    rc = setup(moved)
    if rc == 0:
        _write(state_file, {**seen, **{p: s for p, s in changed.items() if p not in errors}})
    _report("pins", moved, errors)
    return 1 if errors or rc != 0 else 0


def cli_parts_adopt(pins: bool, validated: bool) -> int:
    """`part7 parts-adopt --validated | --pins`."""
    from part7 import module_trees

    if module_trees.pointer_target() is not None:  # TICKET-329 R8: an in-place move would change the serving tree
        print("parts-adopt: refused, the build runs on a module tree (module-trees/current); use `part7 parts-tree build`",
              file=sys.stderr)
        return 1
    mods = config.modules_dir()
    if validated:
        return adopt_validated(mods, parts_gate.gate_dir())
    return adopt_pins(config.REPO_ROOT, mods, config.state_root() / PINS_FILE)


def validated_shas(gdir: Path) -> tuple[dict[str, str], str | None]:
    """`({part: sha}, error)` of the last green gate result, for a per-build tree (TICKET-329); no module is touched."""
    last = _read(gdir / "last.json")
    shas = last.get("candidate_shas")
    if last.get("outcome") != "green" or not isinstance(shas, dict) or not shas:
        return {}, "last.json holds no green gate result; nothing adopted"
    return {str(k): str(v) for k, v in shas.items()}, None


def changed_pins(repo: Path, state_file: Path) -> tuple[dict[str, str], str | None]:
    """The HEAD gitlinks that changed since the last run; the first run only records them (as `adopt_pins`)."""
    pins = head_pins(repo)
    seen = _read(state_file)
    if not seen:
        _write(state_file, pins)
        return {}, None
    return {p: s for p, s in pins.items() if seen.get(p) != s}, None


def record_pins(repo: Path, state_file: Path) -> None:
    """Remember the HEAD gitlinks once their tree is built."""
    _write(state_file, {**_read(state_file), **head_pins(repo)})
