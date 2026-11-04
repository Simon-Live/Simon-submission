"""Parts 1 to 6 under `modules/part-N` (ADR-0007, ADR-0008).

Part 7 calls each part's own code and entry points from that directory and keeps no copy of part logic. In this repo
the parts are ordinary folders, merged with their history (the hackathon submission is one repo, ADR-0008), and
`modules/PINS.json` names the commit of each part's own repo they came from. A module tree that is a git checkout of
its own (a staging build's `SIMON7_MODULES_DIR`) is read with `git rev-parse HEAD`, as before.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from part7 import config

PART_IDS = ("1", "2", "3", "4", "5", "6")
SHORT = 9
SHORT_RUN = 12
GIT_TIMEOUT_S = 60
EXIT_STALE = 3
EXIT_UNREACHABLE = 4


class ModuleError(RuntimeError):
    """A part module is missing or is not a git checkout."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _git(cwd: Path, *args: str) -> str | None:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        run = subprocess.run(
            ["git", "-C", str(cwd), *args], capture_output=True, text=True,
            timeout=GIT_TIMEOUT_S, env=env, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = run.stdout.strip()
    return out if run.returncode == 0 and out else None


def firm_sha(path: Path) -> str | None:
    """The commit a prod release tree was made from: the 40 hex characters in `<path>/.firm-sha` (no .git there)."""
    try:
        found = (Path(path) / ".firm-sha").read_text(encoding="utf-8").strip().lower()
    except OSError:
        return None
    return found if _is_sha(found) else None


def tree_sha(path: Path) -> str | None:
    """The commit of the tree at `path`: its `.firm-sha` when present (a prod release), else `git rev-parse HEAD`."""
    found = firm_sha(path)
    if found:
        return found
    git = _git(path, "rev-parse", "HEAD")
    return git.lower() if _is_sha(git) else None


def head_sha(path: Path) -> str | None:
    """The commit of the checkout at `path`, read fresh each call (None when unreadable)."""
    return tree_sha(path)


def _pins() -> dict[str, dict[str, str]]:
    """`modules/PINS.json` parts: `{part: {sha, from}}`, or {} when absent or unreadable."""
    try:
        doc = json.loads((config.REPO_ROOT / "modules" / "PINS.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    parts = doc.get("parts") if isinstance(doc, dict) else None
    return parts if isinstance(parts, dict) else {}


def _own_checkout(path: Path) -> bool:
    """Whether `path` is a git checkout of its own (a submodule or clone), not a folder of this repo."""
    return (path / ".git").exists()


def _is_sha(text: str | None) -> bool:
    return text is not None and len(text) == 40 and all(c in "0123456789abcdef" for c in text.lower())


class Modules:
    """The checked-out part modules: where each one lives and which commit it is at.

    `shas` overrides the lookup (tests). Otherwise each sha is `rev-parse HEAD` of the module,
    read once and kept for the life of this object (a snapshot, like a build stamp).
    """

    def __init__(self, root: Path | str | None = None, shas: dict[str, str] | None = None) -> None:
        self.root = Path(root) if root is not None else None
        self._shas = {str(k): v for k, v in (shas or {}).items()}

    def path(self, part: int | str) -> Path:
        key = str(part)
        if self.root is not None:
            return self.root / f"part-{key}"
        return config.part_dir(key)

    def sha(self, part: int | str) -> str:
        key = str(part)
        if key not in self._shas:
            path = self.path(key)
            found = _git(path, "rev-parse", "HEAD") if _own_checkout(path) else (_pins().get(key) or {}).get("sha")
            if not _is_sha(found) or not path.is_dir():
                raise ModuleError(f"part {key}: no checkout at {self.path(key)} (run make parts)")
            self._shas[key] = str(found).lower()
        return self._shas[key]

    def sha12(self, part: int | str) -> str:
        return self.sha(part)[:SHORT_RUN]

    def shas_short(self) -> dict[str, str]:
        """`{part: 12-char sha}` for every part whose module is a checkout."""
        out: dict[str, str] = {}
        for key in PART_IDS:
            try:
                out[key] = self.sha12(key)
            except ModuleError:
                continue
        return out


def load(root: Path | str | None = None) -> Modules:
    """The modules of this checkout (`modules/part-N`, or `SIMON7_MODULES_DIR`)."""
    return Modules(root=root)


def _declared(key: str) -> tuple[str | None, str]:
    """`(url, branch)` from `.gitmodules` for a part, else from `modules/PINS.json` (the repo it came from)."""
    if not (config.REPO_ROOT / ".gitmodules").is_file():
        return (_pins().get(key) or {}).get("from"), "main"
    name = f"submodule.modules/part-{key}"
    url = _git(config.REPO_ROOT, "config", "--file", ".gitmodules", f"{name}.url")
    branch = _git(config.REPO_ROOT, "config", "--file", ".gitmodules", f"{name}.branch")
    return url, branch or "main"


def ls_remote(url: str, branch: str = "main") -> str | None:
    """The 40-char sha of `refs/heads/<branch>` at `url`, or None when unreachable."""
    out = _git(config.REPO_ROOT, "ls-remote", url, f"refs/heads/{branch}")
    first = out.split()[0].lower() if out else None
    return first if _is_sha(first) else None


def _git_ok(cwd: Path, *args: str) -> bool:
    """True when the command exits 0; for one with no output on success, which `_git` cannot tell from a failure."""
    try:
        return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, timeout=GIT_TIMEOUT_S,
                              env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _on_a_remote_branch(path: Path, sha: str, url: str | None) -> bool | None:
    """True when a branch at `url` holds `sha`, False when none does, None when a lookup failed and nobody can say. Heads
    the checkout lacks are fetched only if no head it has holds it."""

    def holds(heads: list[str]) -> bool:
        return any(_git(path, "merge-base", sha, head) == sha for head in heads)

    listed = _git(path, "ls-remote", "--heads", url) if url else None
    if listed is None:  # main was read a moment ago, so a remote with no heads is a failed lookup
        return None
    heads = [line.split()[0] for line in listed.splitlines()]
    known = [head for head in heads if _git(path, "cat-file", "-t", head)]
    if holds(known):
        return True
    missing = [head for head in heads if head not in known]
    if missing and not _git_ok(path, "fetch", "-q", "--no-tags", str(url), *missing):
        return None
    return holds(missing)


def _ahead_of(path: Path, sha: str | None, remote: str | None, url: str | None) -> bool | None:
    """True when the checkout holds the remote main and more, and a remote branch holds that too: a pin on a part's fix
    branch (TICKET-380). An object the checkout lacks (a main that really moved) reads as not ahead, and so does a main
    rewound below the pin, since then no remote branch has the pin. None when the branch lookup failed."""
    if not sha or not remote or sha == remote or _git(path, "merge-base", remote, sha) != remote:
        return False
    return _on_a_remote_branch(path, sha, url)


def status(check_remote: bool = False, root: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """`{part: {path, sha, short, url, branch, remote_sha}}`; remote_sha is null unless asked for."""
    mods = load(root)
    doc: dict[str, dict[str, Any]] = {}
    for key in PART_IDS:
        path = mods.path(key)
        declared_url, branch = _declared(key)
        try:
            sha: str | None = mods.sha(key)
        except ModuleError:
            sha = None
        url = (_git(path, "remote", "get-url", "origin") if _own_checkout(path) else None) or declared_url
        remote = ls_remote(url, branch) if (check_remote and url) else None
        try:
            shown = str(path.relative_to(config.REPO_ROOT))
        except ValueError:
            shown = str(path)
        doc[key] = {"path": shown, "sha": sha, "short": sha[:SHORT] if sha else None,
                    "url": url, "branch": branch, "remote_sha": remote}
        ahead = _ahead_of(path, sha, remote, url)
        if ahead is None:  # unknown: an unread remote (exit 4, and the gate skips it), never a moved main (exit 3)
            doc[key]["remote_sha"] = None
        elif ahead:
            doc[key]["ahead"] = True
    return doc


def short_map(root: Path | str | None = None) -> dict[str, str]:
    """`{part: 9-char sha}` for the build stamp."""
    return {k: p["short"] for k, p in status(root=root).items() if p["short"]}


def cli_parts_status(check_remote: bool = False, root: Path | str | None = None) -> int:
    """`part7 parts-status [--check-remote]`: JSON on stdout; exit 3 when a remote main moved, 4 when unreadable."""
    doc = status(check_remote=check_remote, root=root)
    print(json.dumps(doc, indent=2))
    if not check_remote:
        return 0
    # a part folder of this repo (ADR-0008) is the version modules/PINS.json names; it does not follow a remote main
    in_repo = {k for k in doc if not _own_checkout(load(root).path(k))}
    doc = {k: p for k, p in doc.items() if k not in in_repo}
    unread = [k for k, p in doc.items() if p["sha"] is None or p["remote_sha"] is None]
    for key in unread:
        print(f"parts-status: part {key}: checkout or remote unreadable", file=sys.stderr)
    stale = [k for k, p in doc.items() if k not in unread and p["remote_sha"] != p["sha"] and not p.get("ahead")]
    for key in stale:
        print(f"parts-status: part {key} differs from its remote main", file=sys.stderr)  # named even when exit 4 wins
    if unread:
        return EXIT_UNREACHABLE
    return EXIT_STALE if stale else 0
