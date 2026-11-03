"""Per-build module trees (TICKET-329; docs/specs/staging.md "Per-build module trees").

A server build never shares a checked-out `modules/part-N` with another build. A new set of pins gets its own tree,
`<state>/module-trees/t-<id>/part-N`, one `git worktree add --detach` of each part's base clone at the pin, with the
per-part setup run inside it. The serving build's tree is never touched. `current` (a symlink swapped by rename) names
the tree of the serving build; `next` names a built tree waiting for its server. Trees whose server is gone are removed
with `git worktree remove`, never by deleting a path.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable, Iterator

from part7 import config, modules, parts_adopt, setup_parts

ROOT_NAME = "module-trees"
CURRENT = "current"
NEXT = "next"
OWNER = "owner"  # "<pid> <port>" of the server running on the tree, written by staging/server-lib.sh
READY = "ready"
PROMOTED = ".promoted"  # "current": the tree was once `current`; with no owner file it is UNKNOWN, never GONE (AC-329-10)
WAS_CURRENT = "current"
SETUP_LOGS = ".setup-logs"  # per-part setup step logs of the tree, beside its part-N folders
UNOWNED_GRACE_S = 3600.0
MIN_FREE_MB = 5120  # a build refuses below this much free space (SIMON7_TREE_MIN_FREE_MB); Part 3's pip venv is a full copy
LOCK = ".lock"


@contextlib.contextmanager
def _locked(state: Path | str | None = None) -> Iterator[None]:
    """One writer at a time in module-trees/ (build, promote, reclaim), across processes (TICKET-329 R10)."""
    root = trees_root(state)
    root.mkdir(parents=True, exist_ok=True)
    with open(root / LOCK, "a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def trees_root(state: Path | str | None = None) -> Path:
    return config.state_root(state) / ROOT_NAME


def base_dir() -> Path:
    """The shared clones every tree is a worktree of: `SIMON7_BASE_MODULES_DIR`, else `SIMON7_MODULES_DIR`, else
    `<repo>/modules`. Never a tree: inside a server `SIMON7_MODULES_DIR` is its own tree, and a value under
    `module-trees/` is ignored (R7), so a process that inherits a server's environment cannot take a tree for the base."""
    for name in ("SIMON7_BASE_MODULES_DIR", "SIMON7_MODULES_DIR"):
        env_val = os.environ.get(name)
        if env_val:
            path = Path(env_val).expanduser().resolve()
            if ROOT_NAME not in path.parts:
                return path
    return config.REPO_ROOT / "modules"


def pointer_target(state: Path | str | None = None) -> Path | None:
    link = trees_root(state) / CURRENT
    return link.resolve() if link.is_symlink() and link.resolve().is_dir() else None


def next_tree(state: Path | str | None = None) -> Path | None:
    try:
        name = (trees_root(state) / NEXT).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    tree = trees_root(state) / name
    return tree if name and (tree / READY).is_file() else None


def serving_dir(state: Path | str | None = None) -> Path:
    return pointer_target(state) or base_dir()


def start_dir(state: Path | str | None = None) -> Path:
    """Where a server about to start reads its modules: the built `next` tree, else the serving one."""
    return next_tree(state) or serving_dir(state)


def _heads(mods: Path) -> dict[str, str]:
    heads: dict[str, str] = {}
    for part in (str(n) for n in range(1, 7)):
        sha = parts_adopt._git(mods / f"part-{part}", "rev-parse", "HEAD").stdout.strip()
        if sha:
            heads[part] = sha
    return heads


def tree_id(shas: dict[str, str]) -> str:
    """Hash of the shas plus a nonce: a rebuilt set of shas is a new path, so it can never land on a tree a draining
    build still runs on and a stale setup stamp (keyed by path) can never match it (B1, B2)."""
    text = "".join(f"{p}={s}\n" for p, s in sorted(shas.items()))
    return "t-" + hashlib.sha256(text.encode()).hexdigest()[:12] + "-" + os.urandom(3).hex()


def _drop_setup_stamp(part_dir: Path, state: Path | str | None = None) -> None:
    """The setup marker of a checkout that is going away (B2): a marker must not outlive the venv it vouches for. The
    marker lives under `state` (R-h), the state folder the tree belongs to."""
    sha = parts_adopt._git(part_dir, "rev-parse", "HEAD").stdout.strip()
    if sha:
        setup_parts._stamp(part_dir.name.removeprefix("part-"), sha[: modules.SHORT_RUN], state, part_dir).unlink(missing_ok=True)


def _remove_tree(base: Path, tree: Path, state: Path | str | None = None) -> bool:
    """Remove every part worktree of `tree` with `git worktree remove`, then the empty folder. True when it is gone."""
    for part in sorted(tree.glob("part-*")):
        _drop_setup_stamp(part, state)
        parts_adopt._git(base / part.name, "worktree", "remove", "--force", str(part))  # no blanket prune (R12)
    for name in (OWNER, READY, PROMOTED):
        (tree / name).unlink(missing_ok=True)
    try:
        tree.rmdir()
    except OSError:
        return False
    return True


def _setup_tree(tree: Path) -> int:
    """The per-part setup `parts_adopt` ran in place, run inside `tree` (venvs live inside each part checkout)."""
    cmd = os.environ.get("SIMON7_TREE_SETUP_CMD")
    if cmd and os.environ.get("SIMON7_STAGING_STUB") == "1":  # test seam, honoured only by the staging stub
        return subprocess.run(["bash", "-c", cmd], cwd=tree, env={**os.environ, "SIMON7_MODULES_DIR": str(tree)}).returncode
    before = os.environ.get("SIMON7_MODULES_DIR")
    os.environ["SIMON7_MODULES_DIR"] = str(tree)
    try:
        only = tuple(sorted(p.name.removeprefix("part-") for p in tree.glob("part-*")))
        # The step logs stay with the tree: a `next` build must not overwrite the serving tree's, nor another build's.
        return setup_parts.cli_setup_parts(only=only, log_dir=tree / SETUP_LOGS) if only else 0
    finally:
        if before is None:
            os.environ.pop("SIMON7_MODULES_DIR", None)
        else:
            os.environ["SIMON7_MODULES_DIR"] = before


def free_mb(path: Path) -> int:
    stat = os.statvfs(path)
    return stat.f_bavail * stat.f_frsize // (1024 * 1024)


def build(wanted: dict[str, str], state: Path | str | None = None,
          setup: Callable[[Path], int] = _setup_tree) -> tuple[str, str | None]:
    """Build the tree for the shas of `start_dir()` (a built `next`, else the serving tree) overlaid with `wanted`, so a
    built but unserved pin set is carried on and never overwritten (B3). `(outcome, error)`: unchanged | built | failed.
    Every path this run creates is new (nonce), so a failure removes only what it made (B1)."""
    with _locked(state):
        root = trees_root(state)
        baseline_dir = start_dir(state)
        shas = {**_heads(baseline_dir), **wanted}
        if shas == _heads(baseline_dir):
            return ("built" if baseline_dir != serving_dir(state) else "unchanged"), None
        _reclaim_locked(state)  # old and half-built trees go first: they are the disk this build may need
        floor = int(os.environ.get("SIMON7_TREE_MIN_FREE_MB", MIN_FREE_MB))
        if free_mb(root) < floor:
            return "failed", (f"only {free_mb(root)} MB free under {root}; a new module tree needs at least {floor} MB "
                              "(Part 3's pip venv is a full copy). Free space or lower SIMON7_TREE_MIN_FREE_MB.")
        return _build_new(wanted_shas=shas, state=state, setup=setup)


def _build_new(wanted_shas: dict[str, str], state: Path | str | None, setup: Callable[[Path], int]) -> tuple[str, str | None]:
    base, root = base_dir(), trees_root(state)
    tree = root / tree_id(wanted_shas)
    tree.mkdir(parents=True, exist_ok=False)
    for part, sha in sorted(wanted_shas.items()):
        module = base / f"part-{part}"
        if not (module / ".git").exists():
            _remove_tree(base, tree, state)
            return "failed", f"part {part}: no module checkout"
        if parts_adopt._git(module, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
            parts_adopt._git(module, "fetch", "-q", "origin")
        made = parts_adopt._git(module, "worktree", "add", "--detach", str(tree / f"part-{part}"), sha)
        if made.returncode != 0:
            _remove_tree(base, tree, state)
            return "failed", f"part {part}: {made.stderr.strip() or 'git worktree add failed'}"
    if setup(tree) != 0:
        _remove_tree(base, tree, state)
        return "failed", "part setup failed in the new tree"
    # No PROMOTED here (B1): a `next` that is replaced before it is ever served must stay reclaimable.
    (tree / READY).write_text("ready\n", encoding="utf-8")
    tmp = root / (NEXT + ".tmp")
    tmp.write_text(tree.name + "\n", encoding="utf-8")
    os.replace(tmp, root / NEXT)
    return "built", None


class ExpectMismatch(ValueError):
    """`promote --expect DIR`: DIR is not the tree the pointer would move to; nothing was changed (AC-329-12)."""


def _check_expect(expect: Path | str, tree: Path | None, state: Path | str | None) -> None:
    """The dir the new server started on must be the `next` tree, or, with nothing waiting, what already serves."""
    want = Path(expect).expanduser().resolve()
    if tree is not None:
        if want != tree.resolve():
            raise ExpectMismatch(f"the server started on {want}, but `next` is {tree.resolve()}; `current` not moved")
        return
    current = pointer_target(state)
    if want != (current or want) or (current is None and ROOT_NAME in want.parts):
        raise ExpectMismatch(f"the server started on {want}, which is neither `next` (none) nor `current` ({current})")


def promote(state: Path | str | None = None, expect: Path | str | None = None) -> bool:
    """Point `current` at the `next` tree (a symlink swapped by rename) and clear `next`. False when nothing waits.
    With `expect` (the dir the new server started on, R2 of recheck 3) a mismatch raises ExpectMismatch and changes
    nothing, so `current` never names a tree the server is not on."""
    with _locked(state):
        tree = next_tree(state)
        if expect is not None:
            _check_expect(expect, tree, state)
        if tree is None:
            return False
        root = trees_root(state)
        (tree / PROMOTED).write_text(WAS_CURRENT + "\n", encoding="utf-8")
        tmp = root / (CURRENT + ".tmp")
        tmp.unlink(missing_ok=True)
        tmp.symlink_to(tree)
        os.replace(tmp, root / CURRENT)
        (root / NEXT).unlink(missing_ok=True)
        return True


def proc_start_ticks(pid: int) -> str:
    """Field 22 of /proc/<pid>/stat (start time in clock ticks); "" when the process is not readable."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return ""
    fields = stat.rsplit(")", 1)[-1].split()
    return fields[19] if len(fields) > 19 else ""


ALIVE, UNKNOWN, GONE = "alive", "unknown", "gone"


def _resolve_arg(arg: str, pid: int) -> Path | None:
    """`--state` as the process sees it: a relative path against its working directory. None when it cannot be resolved."""
    try:
        path = Path(arg)
        if not path.is_absolute():
            path = Path(os.readlink(f"/proc/{pid}/cwd")) / path
        return path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None


def server_state(tree: Path, state: Path | str | None = None) -> str:
    """Is the server named in `tree/owner` still this checkout's? `gone` only on a positive sign: a dead pid, another
    start time, another exact `--port`, another program, or a different state folder. Anything that cannot be read or
    resolved (no `--state`, an unresolvable one, an unreadable owner or cmdline) is `unknown` and the tree is kept."""
    try:
        fields = (tree / OWNER).read_text(encoding="utf-8").split()
        pid, port = int(fields[0]), fields[1]
    except FileNotFoundError:
        # No server recorded: a tree that was once `current` may still have one (the owner write can fail), so keep it.
        return UNKNOWN if was_current(tree) else GONE
    except (OSError, ValueError, IndexError):
        return UNKNOWN
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace").split("\0")
    except (FileNotFoundError, ProcessLookupError):
        return GONE
    except OSError:
        return UNKNOWN
    if len(fields) > 2 and fields[2] != proc_start_ticks(pid):
        return GONE
    pairs = dict(zip(argv, argv[1:]))
    if not any(a == "--port" and b == port for a, b in zip(argv, argv[1:])):
        return GONE
    if "simon7-staging-stub" in argv:
        return ALIVE
    if not ("serve" in argv and "part7" in argv):
        return GONE
    given = pairs.get("--state")
    if given is None:
        return UNKNOWN
    theirs, ours = _resolve_arg(given, pid), _resolve_arg(str(config.state_root(state)), pid)
    if theirs is None or ours is None:
        return UNKNOWN
    return ALIVE if theirs == ours else GONE


def was_current(tree: Path) -> bool:
    """The tree was once `current` (written by promote() only, B1). A `.promoted` reading "next", left by builds before
    the fix, is a never-served `next`, so it does not count."""
    try:
        return (tree / PROMOTED).read_text(encoding="utf-8").strip() == WAS_CURRENT
    except OSError:
        return False


def _server_alive(tree: Path, state: Path | str | None = None) -> bool:
    """True unless the owner is positively not this checkout's server (keep on unknown)."""
    return server_state(tree, state) != GONE


def _env_modules_dir(pid: int) -> str | None:
    """SIMON7_MODULES_DIR of a process, parsed from its environ; no other variable is kept, nothing is logged."""
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return None
    for item in raw.split(b"\0"):
        if item.startswith(b"SIMON7_MODULES_DIR="):
            return item.split(b"=", 1)[1].decode(errors="replace")
    return None


def _serve_paths(pid: int, state: Path | str | None) -> list[Path]:
    """The module paths (environ SIMON7_MODULES_DIR, cwd) of `pid` when it is a `part7 serve` for our state, else []."""
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace").split("\0")
    except OSError:
        return []
    if "simon7-staging-stub" not in argv:
        if not ("serve" in argv and "part7" in argv):
            return []
        given = dict(zip(argv, argv[1:])).get("--state")
        theirs = _resolve_arg(given, pid) if given is not None else None
        if theirs is None or theirs != _resolve_arg(str(config.state_root(state)), pid):
            return []
    paths: list[Path] = []
    for raw in (_env_modules_dir(pid), _readlink(f"/proc/{pid}/cwd")):
        if raw:
            try:
                paths.append(Path(raw).resolve())
            except (OSError, RuntimeError):
                continue
    return paths


def _readlink(path: str) -> str | None:
    try:
        return os.readlink(path)
    except OSError:
        return None


def _trees_in_use(root: Path, state: Path | str | None) -> set[Path]:
    """Trees a live `part7 serve` of this state runs on (its SIMON7_MODULES_DIR or cwd is the tree or inside it), found
    by scanning /proc once. Whatever a tree's owner file says (or lacks). Unreadable entries are skipped."""
    used: set[Path] = set()
    trees = [t.resolve() for t in root.glob("t-*")]
    try:
        pids = [int(n) for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return used
    for pid in pids:
        for path in _serve_paths(pid, state):
            used.update(t for t in trees if path == t or t in path.parents)
    return used


def reclaim(state: Path | str | None = None) -> tuple[list[str], list[str]]:
    """Remove the trees nothing serves from or waits for. Never removed: the `current` and `next` trees, a tree a live
    `part7 serve` of this state runs on (found by scanning /proc for its SIMON7_MODULES_DIR or cwd, whatever the owner
    file says), a tree with a live or unknown owner, a tree that was once `current` and has no owner file (the owner
    write can fail, so it is unknown), and a built (`ready`), never-current, unowned tree younger than the grace. A tree
    with no `ready` marker is a killed build's half tree: under the lock no build runs, so it goes with no grace (R-a).
    A built `next` that a later build replaced before it was served is never-current, so it goes too (B1).
    `(removed, failed)` tree names."""
    if not trees_root(state).is_dir():
        return [], []
    with _locked(state):
        return _reclaim_locked(state)


def _reclaim_locked(state: Path | str | None) -> tuple[list[str], list[str]]:
    root, base = trees_root(state), base_dir()
    grace = float(os.environ.get("SIMON7_TREE_GRACE_S", UNOWNED_GRACE_S))
    gone: list[str] = []
    failed: list[str] = []
    keep = {pointer_target(state), next_tree(state)} | _trees_in_use(root, state)
    for tree in sorted(root.glob("t-*")):
        if tree.resolve() in keep or _server_alive(tree, state):
            continue
        # The lock is held: every build is finished, so a tree with no `ready` marker is a killed build's (R-a).
        if (tree / READY).is_file() and not (tree / OWNER).exists() and time.time() - tree.stat().st_mtime < grace:
            continue
        (gone if _remove_tree(base, tree, state) else failed).append(tree.name)
    return gone, failed


def _forward_only(wanted: dict[str, str], state: Path | str | None = None) -> dict[str, str]:
    """A validated sha is adopted only when it is ahead of the serving checkout, as `parts-adopt --validated` did."""
    serving = start_dir(state)
    heads = _heads(serving)
    kept: dict[str, str] = {}
    for part, sha in wanted.items():
        cur = heads.get(part)
        if cur and parts_adopt._git(serving / f"part-{part}", "merge-base", "--is-ancestor", cur, sha).returncode != 0:
            print(f"parts-tree: part {part}: {sha[:12]} is not ahead of {cur[:12]}; skipped", file=sys.stderr)
            continue
        kept[part] = sha
    return kept


def cli_parts_tree(action: str, pins: bool = False, validated: bool = False, expect: str | None = None) -> int:
    """`part7 parts-tree build --pins|--validated | promote --expect DIR | reclaim | path`."""
    if action in ("path", "serving", "base"):  # the one place the shell asks, so it cannot drift from Python (R13)
        print({"path": start_dir, "serving": serving_dir, "base": base_dir}[action]())
        return 0
    try:
        if action == "promote":
            if not expect:  # AC-329-12: the caller names the dir its server started on; no caller promotes blind
                print("parts-tree promote: --expect DIR is required (the modules dir the new server started on)", file=sys.stderr)
                return 2
            print("promoted" if promote(expect=expect) else "nothing waiting")
            return 0
        if action == "reclaim":
            gone, failed = reclaim()
            print("reclaimed: " + (", ".join(gone) or "none"))
            if failed:
                print("parts-tree: could not remove " + ", ".join(failed), file=sys.stderr)
            return 1 if failed else 0
    except ExpectMismatch as exc:
        print(f"parts-tree promote: refused: {exc}", file=sys.stderr)
        return 3
    except OSError as exc:
        print(f"parts-tree {action}: {exc}", file=sys.stderr)
        return 1
    if validated:
        wanted, err = parts_adopt.validated_shas(parts_adopt.parts_gate.gate_dir())
    else:
        wanted, err = parts_adopt.changed_pins(config.REPO_ROOT, config.state_root() / parts_adopt.PINS_FILE)
    if err:
        print(f"parts-tree: {err}", file=sys.stderr)
        return 1
    if validated:
        wanted = _forward_only(wanted)
    outcome, failure = build(wanted)
    if failure:
        print(f"parts-tree: {failure}", file=sys.stderr)
        return 1
    if pins:
        parts_adopt.record_pins(config.REPO_ROOT, config.state_root() / parts_adopt.PINS_FILE)
    print(f"parts-tree: {outcome}")
    return 0
