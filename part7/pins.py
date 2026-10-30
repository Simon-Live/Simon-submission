"""Pin management and detached clone materialization for Simon Part 7 (TICKET-003)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Callable

from part7 import config

SCHEMA = "part7.parts-lock/1"
PART_IDS = ("1", "2", "3", "4", "5", "6")
TERMINAL_STATUS_PREFIXES = ("STATUS: DONE", "STATUS: DEGRADED", "STATUS: BLOCKED")


class PinError(RuntimeError):
    """Error raised when pinning or materializing a part clone fails."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class Lock:
    """Wrapper around the parsed `parts.lock.json` document."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw

    def part_info(self, part: int | str) -> dict[str, Any]:
        key = str(part)
        parts = self.raw.get("parts", {})
        if key not in parts:
            raise PinError(f"part {key}: missing from parts.lock.json", exit_code=1)
        return parts[key]

    def sha(self, part: int | str) -> str:
        info = self.part_info(part)
        sha = str(info.get("sha", "")).strip()
        if len(sha) != 40:
            raise PinError(f"part {part}: invalid sha {sha!r} in parts.lock.json", exit_code=1)
        return sha

    def sha12(self, part: int | str) -> str:
        return self.sha(part)[:12]

    def path(self, part: int | str, state: Path | str | None = None) -> Path:
        return config.parts_dir(state) / f"{part}@{self.sha12(part)}"

    def pins_short(self) -> dict[str, str]:
        parts = self.raw.get("parts", {})
        return {k: self.sha12(k) for k in PART_IDS if k in parts}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(lock_file: Path | str | None = None) -> Lock:
    """Load `parts.lock.json` and return a `Lock` wrapper."""
    path = Path(lock_file) if lock_file is not None else config.lock_path()
    if not path.is_file():
        raise PinError(f"pin: lock file not found at {path}", exit_code=1)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PinError(f"pin: invalid lock file {path}: {exc}", exit_code=1) from exc
    if not isinstance(data, dict) or not isinstance(data.get("parts"), dict):
        raise PinError(f"pin: malformed lock file {path}", exit_code=1)
    return Lock(data)


def _read_workspace_status(
    part: str,
    workspaces: dict[str, Path] | None = None,
) -> tuple[str, bool]:
    """Read the last status line from a part's workspace STATUS.md (read-only)."""
    ws_map = config.PART_WORKSPACES if workspaces is None else workspaces
    ws = ws_map.get(part)
    if ws is None:
        return "upstream main", False
    status_file = Path(ws) / "STATUS.md"
    if not status_file.is_file():
        return "upstream main", False
    try:
        lines = [
            line.strip()
            for line in status_file.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        ]
    except OSError:
        return "upstream main", False
    if not lines:
        return "running", part in ("2", "5")
    status_lines = [line for line in lines if line.startswith("STATUS:")]
    chosen = status_lines[-1] if status_lines else lines[-1]
    if part in ("2", "5"):
        ended = any(chosen.startswith(prefix) for prefix in TERMINAL_STATUS_PREFIXES)
        return chosen, not ended
    return chosen, False


def _ls_remote_main(repo: str) -> str:
    """Run `git ls-remote <repo> refs/heads/main` and return the 40-char sha."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        res = subprocess.run(
            ["git", "ls-remote", repo, "refs/heads/main"],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PinError(f"pin: {repo} unreachable", exit_code=3) from exc
    if res.returncode != 0 or not res.stdout.strip():
        raise PinError(f"pin: {repo} unreachable", exit_code=3)
    first_token = res.stdout.strip().split()[0]
    if len(first_token) != 40 or any(c not in "0123456789abcdefABCDEF" for c in first_token):
        raise PinError(f"pin: {repo} unreachable", exit_code=3)
    return first_token.lower()


def probe_part2(
    clone_dir: Path | str,
    runner: Callable[..., Any] | list[str] | None = None,
    record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Probe Part 2's CLI at `clone_dir` for `--backend` support (AC-H11)."""
    cdir = Path(clone_dir)
    default_cmd = ["uv", "run", "part2", "run", "--help"]
    stdout = ""
    returncode = 1
    try:
        if callable(runner):
            try:
                out = runner(default_cmd, cdir)
            except TypeError:
                out = runner(cdir)
            if isinstance(out, tuple) and len(out) == 2:
                returncode, stdout = int(out[0]), str(out[1])
            elif isinstance(out, subprocess.CompletedProcess):
                returncode = out.returncode
                stdout = (out.stdout or "") + (out.stderr or "")
            else:
                returncode = 0
                stdout = str(out)
        else:
            cmd = list(runner) if isinstance(runner, (list, tuple)) else default_cmd
            env = os.environ.copy()
            local_bin = str(Path.home() / ".local" / "bin")
            env["PATH"] = f"{local_bin}:{env.get('PATH', '')}"
            res = subprocess.run(
                cmd,
                cwd=cdir,
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
                check=False,
            )
            returncode = res.returncode
            stdout = (res.stdout or "") + (res.stderr or "")
    except (OSError, subprocess.SubprocessError):
        returncode = 1
        stdout = ""

    if returncode == 0 and "--backend" in stdout:
        result: dict[str, Any] = {"entry_point": "backend", "repin_due": False}
    else:
        result = {"entry_point": "missing", "repin_due": True}

    if record is not None:
        record.update(result)
    return result


def _materialize_clone(part: str, repo: str, sha: str, clone_dir: Path) -> None:
    """Materialize or verify a detached clone at `clone_dir`."""
    env = {
        **os.environ,
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    git_marker = clone_dir / ".git"
    if not git_marker.exists():
        clone_dir.parent.mkdir(parents=True, exist_ok=True)
        res_clone = subprocess.run(
            ["git", "clone", "-q", "--no-checkout", repo, str(clone_dir)],
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
            check=False,
        )
        if res_clone.returncode != 0:
            raise PinError(f"pin: {repo} unreachable", exit_code=3)
        res_co = subprocess.run(
            ["git", "-C", str(clone_dir), "checkout", "-q", "--detach", sha],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            check=False,
        )
        if res_co.returncode != 0:
            subprocess.run(
                ["git", "-C", str(clone_dir), "fetch", "-q", "origin", sha],
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
                check=False,
            )
            res_co2 = subprocess.run(
                ["git", "-C", str(clone_dir), "checkout", "-q", "--detach", sha],
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
                check=False,
            )
            if res_co2.returncode != 0:
                raise PinError(
                    f"part {part}: checkout {sha} failed in {clone_dir}",
                    exit_code=1,
                )
        return

    res_rev = subprocess.run(
        ["git", "-C", str(clone_dir), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        check=False,
    )
    actual = res_rev.stdout.strip().lower()
    if res_rev.returncode != 0 or actual != sha.lower():
        raise PinError(
            f"part {part}: clone at {actual or 'unknown'} but the lock says {sha}",
            exit_code=1,
        )


def _write_atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".parts-lock-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def pin(
    update: list[str] | None = None,
    materialize: bool = False,
    lock_file: Path | str | None = None,
    state: Path | str | None = None,
    repo_urls: dict[str, str] | None = None,
    workspaces: dict[str, Path] | None = None,
    probe_runner: Callable[..., Any] | list[str] | None = None,
) -> Lock:
    """Write or update `parts.lock.json` and optionally materialize detached clones."""
    lpath = Path(lock_file) if lock_file is not None else config.lock_path()
    repos = {**config.PART_REPOS, **(repo_urls or {})}
    now = _utc_now()

    existing_doc: dict[str, Any] = {}
    existing_parts: dict[str, dict[str, Any]] = {}
    if lpath.is_file():
        try:
            loaded = json.loads(lpath.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing_doc = loaded
                if isinstance(loaded.get("parts"), dict):
                    existing_parts = {
                        str(k): dict(v)
                        for k, v in loaded["parts"].items()
                        if isinstance(v, dict)
                    }
        except (OSError, json.JSONDecodeError):
            existing_doc = {}
            existing_parts = {}

    if update is None:
        to_update: set[str] = set()
    elif len(update) == 0:
        to_update = set(PART_IDS)
    else:
        to_update = {str(p) for p in update}
        unknown = to_update - set(PART_IDS)
        if unknown:
            raise PinError(f"pin: unknown part(s): {', '.join(sorted(unknown))}", exit_code=2)

    new_parts: dict[str, dict[str, Any]] = {}
    any_updated = False
    for p in PART_IDS:
        repo = repos[p]
        prev = existing_parts.get(p)
        needs_fetch = (
            p in to_update
            or prev is None
            or len(str(prev.get("sha", ""))) != 40
        )
        if needs_fetch:
            sha = _ls_remote_main(repo)
            status, repin_due = _read_workspace_status(p, workspaces=workspaces)
            rec: dict[str, Any] = {
                "repo": repo,
                "sha": sha,
                "pinned_at": now,
                "status": status,
                "repin_due": repin_due,
            }
            if p == "2" and prev and "entry_point" in prev and prev.get("sha") == sha:
                rec["entry_point"] = prev["entry_point"]
            new_parts[p] = rec
            any_updated = True
        else:
            new_parts[p] = dict(prev)

    doc: dict[str, Any] = {
        "schema": SCHEMA,
        "pinned_at": now if (any_updated or "pinned_at" not in existing_doc) else existing_doc["pinned_at"],
        "parts": new_parts,
    }
    lock = Lock(doc)

    if materialize:
        for p in PART_IDS:
            info = lock.part_info(p)
            cdir = lock.path(p, state=state)
            _materialize_clone(p, info["repo"], info["sha"], cdir)
            if p == "2":
                if (
                    probe_runner is not None
                    or (cdir / "pyproject.toml").is_file()
                    or (cdir / "part2").is_dir()
                ):
                    probe_part2(cdir, runner=probe_runner, record=info)

    _write_atomic_json(lpath, doc)
    return lock


def cli_pin(
    update: list[str] | None = None,
    materialize: bool = False,
    lock_file: Path | str | None = None,
    state: Path | str | None = None,
) -> int:
    """CLI entry point for `part7 pin`."""
    try:
        pin(update=update, materialize=materialize, lock_file=lock_file, state=state)
    except PinError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    return 0
