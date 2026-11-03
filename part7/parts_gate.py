"""Check a moved part in a throwaway worktree before staging adopts it (TICKET-189, docs/specs/staging.md).

`gate()` compares each module's checked-out sha with its remote `main`. For the parts that moved it builds a
throwaway worktree of this checkout, puts each candidate sha in it, and runs part setup (moved parts only),
`doctor-parts` and the fast contract subset of the Part 7 tests. Green: the caller goes on to `make parts`.
Red or skipped: the served modules stay as they are; `<state>/parts-gate/last.json` says why.

Ported from the intent of the parked reconcile lane (d3069fe, TICKET-063): lock, throwaway worktree, memory
skip, last.json on red. check-7 is not run here (minutes to hours); the publish runs it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable

from part7 import applog, config, modules, runner, selfheal

SCHEMA = "part7.parts-gate/1"
EXIT_GREEN, EXIT_RED, EXIT_SKIPPED, EXIT_TIMEOUT = 0, 1, 3, 124
KILL_GRACE_S = 5.0
MIN_MEM_MB = 6144
STEP_TIMEOUTS = {"setup-parts": 900.0, "doctor-parts": 180.0, "tests": 300.0}
# The part contracts: module access, setup, doctor, the per-part adapters, the chain and the runner.
SMOKE_TESTS = [
    "tests/test_modules.py", "tests/test_setup_parts.py", "tests/test_parts.py", "tests/test_black_box.py",
    "tests/test_chain.py", "tests/test_runner.py", "tests/part7/test_trainer_chain_and_harness.py",
    "tests/part7/test_processor_summary.py",
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gate_dir(state: Path | str | None = None) -> Path:
    return config.state_root(state) / "parts-gate"


def mem_available_mb() -> int | None:
    """MemAvailable of the host in MiB, None when /proc/meminfo is unreadable."""
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=300, env=env)


def candidates(status: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    """`{part: {old, new}}` for each part whose remote main differs from the checked-out sha (both known)."""
    out: dict[str, dict[str, str]] = {}
    for part, info in status.items():
        if info.get("sha") and info.get("remote_sha") and info["sha"] != info["remote_sha"]:
            out[part] = {"old": info["sha"], "new": info["remote_sha"]}
    return out


def prepare_worktree(repo: Path, wt: Path, cand: dict[str, dict[str, str]], mods: Path, branch: str = "main") -> dict[str, str]:
    """Throwaway worktree of `repo` HEAD; moved parts are worktrees of their candidate sha, the others link to the served
    module (already set up). Returns the sha each candidate resolved to after the fetch. Raises RuntimeError."""
    added = _git(["worktree", "add", "--detach", str(wt), "HEAD"], repo)
    if added.returncode != 0:
        raise RuntimeError(f"worktree: {added.stderr.strip()}")
    resolved: dict[str, str] = {}
    (wt / "modules").mkdir(exist_ok=True)
    for part in modules.PART_IDS:
        target = wt / "modules" / f"part-{part}"
        if target.is_dir() and not target.is_symlink():
            target.rmdir()  # the empty gitlink directory of the worktree
        live = mods / f"part-{part}"
        if part not in cand:
            target.symlink_to(live)
            continue
        fetched = _git(["fetch", "-q", "origin", branch], live)
        if fetched.returncode != 0:
            raise RuntimeError(f"part {part}: fetch failed: {fetched.stderr.strip()}")
        sha = _git(["rev-parse", "FETCH_HEAD"], live).stdout.strip()
        placed = _git(["worktree", "add", "--detach", str(target), sha], live)
        if placed.returncode != 0:
            raise RuntimeError(f"part {part}: worktree at {sha[:12]}: {placed.stderr.strip()}")
        resolved[part] = sha
    return resolved


def remove_worktree(repo: Path, wt: Path, cand: dict[str, dict[str, str]], mods: Path) -> None:
    """Drop the throwaway worktrees (the candidates first); forward-only, nothing else is touched."""
    for part in cand:
        _git(["worktree", "remove", "--force", str(wt / "modules" / f"part-{part}")], mods / f"part-{part}")
        _git(["worktree", "prune"], mods / f"part-{part}")
    _git(["worktree", "remove", "--force", str(wt)], repo)
    _git(["worktree", "prune"], repo)


class GateInterrupted(Exception):
    """The gate got SIGTERM (the helper's timeout) or SIGINT."""


def _children_of(pid: int) -> list[int]:
    out = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8")
            if int(stat.rsplit(")", 1)[1].split()[1]) == pid:
                out.append(int(entry.name))
        except (OSError, ValueError, IndexError):
            continue
    return out


def _tree(pid: int) -> list[int]:
    found = []
    for child in _children_of(pid):
        found.append(child)
        found.extend(_tree(child))
    return found


def kill_children(grace_s: float = KILL_GRACE_S) -> None:
    """Stop every step still running under this process: each step is its own process group, so signal the group
    and the descendants, then KILL what survives the grace."""
    pids = _tree(os.getpid())
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in pids:
            for send in (os.killpg, os.kill):
                try:
                    send(pid, sig)
                except OSError:
                    pass
        if sig == signal.SIGTERM:
            deadline = time.monotonic() + grace_s
            while time.monotonic() < deadline and any(Path(f"/proc/{p}").exists() for p in pids):
                time.sleep(0.1)


def _raise_interrupted(signum: int, _frame: Any) -> None:
    raise GateInterrupted(f"signal {signum}")


def sweep_stale(repo: Path, mods: Path, gdir: Path) -> None:
    """Remove what a gate killed before its cleanup left behind. Only paths under `<gate dir>/work` are touched:
    their registered worktrees first (through git), then the leftover directories."""
    work = (gdir / "work").resolve()
    if not work.is_dir():
        return
    for part in modules.PART_IDS:
        live = mods / f"part-{part}"
        if not (live / ".git").exists():
            continue
        listing = _git(["worktree", "list", "--porcelain"], live).stdout.splitlines()
        for line in listing:
            if line.startswith("worktree ") and Path(line[9:]).resolve().is_relative_to(work):
                _git(["worktree", "remove", "--force", line[9:]], live)
        _git(["worktree", "prune"], live)
    for line in _git(["worktree", "list", "--porcelain"], repo).stdout.splitlines():
        if line.startswith("worktree ") and Path(line[9:]).resolve().is_relative_to(work) and Path(line[9:]).resolve() != work:
            _git(["worktree", "remove", "--force", line[9:]], repo)
    _git(["worktree", "prune"], repo)
    for child in work.iterdir():
        if child.is_symlink():
            child.unlink()
        elif child.resolve().parent == work:
            shutil.rmtree(child, ignore_errors=True)


def run_step(argv: list[str], cwd: Path, env: dict[str, str], timeout_s: float, log: Path) -> int:
    """One validation step in its own process group, output to `log`; 124 on timeout."""
    step = runner.run("7", argv, cwd=cwd, env_extra=env, timeout_s=timeout_s, log_path=log, lock=None)
    return 124 if step["exit"] is None else int(step["exit"])


def notify(subject: str, body: str) -> None:
    """One IECB message to the hub (`scripts/comms.sh send`), or `SIMON7_PARTS_GATE_NOTIFY_CMD subject body`; failures are logged only."""
    override = os.environ.get("SIMON7_PARTS_GATE_NOTIFY_CMD")
    if override:
        argv = [*shlex.split(override), subject, body]
    else:
        shim = config.REPO_ROOT / "scripts" / "comms.sh"
        if not shim.is_file():
            return
        argv = [str(shim), "send", "--to", "firm", "--topic", "parts-gate-red", "--priority", "normal",
                "--subject", subject, "--body", body]
    try:
        subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False, cwd=config.REPO_ROOT)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"parts-gate: notice not sent: {exc}", file=sys.stderr)


@dataclass
class Deps:
    """What the gate reaches outside itself with; tests replace these."""

    status: Callable[[], dict[str, dict[str, Any]]] = lambda: modules.status(check_remote=True)
    mem_mb: Callable[[], int | None] = mem_available_mb
    prepare: Callable[..., dict[str, str]] = prepare_worktree
    remove: Callable[..., None] = remove_worktree
    run_step: Callable[..., int] = run_step
    notify: Callable[[str, str], None] = notify
    sweep: Callable[..., None] = sweep_stale


@dataclass
class Result:
    outcome: str  # green | red | skipped | unchanged
    reason: str = ""
    parts: dict[str, dict[str, str]] = field(default_factory=dict)
    failed_step: str | None = None
    log_dir: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)

    def exit_code(self) -> int:
        if self.failed_step == "timeout":
            return EXIT_TIMEOUT
        return {"red": EXIT_RED, "skipped": EXIT_SKIPPED}.get(self.outcome, EXIT_GREEN)


def _write_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _shas(parts: dict[str, dict[str, str]]) -> dict[str, str]:
    return {n: v["new"] for n, v in sorted(parts.items())}


def _run_steps(deps: Deps, wt: Path, state_dir: Path, cand: dict[str, dict[str, str]], log_dir: Path,
               res: Result) -> bool:
    env = {"SIMON7_MODULES_DIR": str(wt / "modules"), "SIMON7_STATE_DIR": str(state_dir)}
    py = ["uv", "run", "python", "-m", "part7"]
    plan = [("setup-parts", py + ["setup-parts", "--only", ",".join(sorted(cand))]),
            ("doctor-parts", py + ["doctor-parts"]),
            ("tests", ["uv", "run", "pytest", "-q", "-x", *SMOKE_TESTS])]
    for name, argv in plan:
        log = log_dir / f"{name}.log"
        code = deps.run_step(argv, wt, env, STEP_TIMEOUTS[name], log)
        res.steps.append({"step": name, "exit": code, "log": str(log)})
        if code != 0:
            res.failed_step, res.reason = name, f"{name} exited {code}"
            return False
    return True


def _red(gdir: Path, res: Result, started: str, deps: Deps) -> None:
    """Keep the served modules: record last.json, one ANOMALY line per part, one notice per candidate sha."""
    doc = _read_json(gdir / "last.json")
    notified = [s for s in doc.get("notified", []) if isinstance(s, str)]
    fresh = []
    for part, sha in _shas(res.parts).items():
        applog.anomaly("parts_gate_red", part=part, sha=sha, step=res.failed_step, log=res.log_dir)
        if sha not in notified:
            fresh.append((part, sha))
    for part, sha in fresh:
        deps.notify(f"simon-part-7: part {part} {sha[:12]} failed the staging parts gate",
                    f"Staging keeps serving the current modules. Failing step: {res.failed_step}. Log: {res.log_dir}. "
                    f"Record: {gdir / 'last.json'}.")
        notified.append(sha)
    _write_json(gdir / "last.json", {
        "schema": SCHEMA, "started_at": started, "finished_at": _now(), "outcome": "red", "parts": res.parts,
        "candidate_shas": _shas(res.parts), "failed_step": res.failed_step, "reason": res.reason,
        "log_dir": res.log_dir, "steps": res.steps, "notified": notified})


def _validate(deps: Deps, repo: Path, mods: Path, gdir: Path, cand: dict[str, dict[str, str]]) -> Result:
    tag = _now().replace(":", "").replace("-", "")
    wt, state_dir, log_dir = gdir / "work" / tag, gdir / "work" / f"{tag}-state", gdir / "logs" / tag
    log_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    res = Result("red", parts=cand, log_dir=str(log_dir))
    wt.parent.mkdir(parents=True, exist_ok=True)
    try:
        try:
            resolved = deps.prepare(repo, wt, cand, mods)
        except RuntimeError as exc:
            res.failed_step, res.reason = "worktree", str(exc)
            return res
        for part, sha in resolved.items():
            cand[part]["new"] = sha
        if _run_steps(deps, wt, state_dir, cand, log_dir, res):
            res.outcome = "green"
    except GateInterrupted:
        kill_children()
        res.failed_step, res.reason = "timeout", "the gate was killed at its time limit; running steps were stopped"
    finally:
        deps.remove(repo, wt, cand, mods)
    return res


class _term_guard:
    """SIGTERM and SIGINT raise GateInterrupted while the steps run (main thread only)."""

    def __enter__(self) -> None:
        self.old: dict[int, Any] = {}
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                self.old[sig] = signal.signal(sig, _raise_interrupted)

    def __exit__(self, *_exc: object) -> None:
        for sig, handler in self.old.items():
            signal.signal(sig, handler)


def gate(state: Path | str | None = None, repo: Path | None = None, deps: Deps | None = None,
         force: bool = False) -> Result:
    """One pass. Never raises for an expected condition; the Result says what happened (exit 0 green or nothing
    moved, 1 red, 3 skipped)."""
    deps = deps or Deps()
    repo = repo or config.REPO_ROOT
    gdir = gate_dir(state)
    gdir.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(str(gdir / "gate.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return Result("skipped", reason="another parts gate holds the lock")
        deps.sweep(repo, config.modules_dir(), gdir)
        cand = candidates(deps.status())
        if not cand:
            return Result("unchanged", reason="no part main moved")
        last = _read_json(gdir / "last.json")
        if (not force and last.get("outcome") == "red" and last.get("failed_step") != "timeout"
                and last.get("candidate_shas") == _shas(cand)):
            return Result("red", reason="these shas already failed (see last.json); use --force", parts=cand,
                          failed_step=last.get("failed_step"), log_dir=last.get("log_dir"))
        mem = deps.mem_mb()
        floor = int(os.environ.get("SIMON7_PARTS_GATE_MIN_MEM_MB", MIN_MEM_MB))
        if mem is not None and mem < floor:
            res = Result("skipped", reason=f"host memory low ({mem} MB available, need {floor})", parts=cand)
            applog.anomaly("parts_gate_skipped", reason=res.reason, parts=",".join(sorted(cand)))
            return res
        started = _now()
        with _term_guard():
            res = _validate(deps, repo, config.modules_dir(), gdir, cand)
        if res.outcome == "red":
            _red(gdir, res, started, deps)
        else:
            _write_json(gdir / "last.json", {"schema": SCHEMA, "started_at": started, "finished_at": _now(),
                                             "outcome": "green", "parts": res.parts, "candidate_shas": _shas(res.parts),
                                             "log_dir": res.log_dir, "steps": res.steps, "notified": []})
        return res
    finally:
        os.close(lock_fd)


def cli_parts_gate(force: bool = False) -> int:
    """`part7 parts-gate [--force]`: one JSON line; exit 0 green or nothing moved, 1 red, 3 skipped."""
    applog.setup(config.state_root())
    selfheal.configure(config.state_root())
    try:
        res = gate(force=force)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"parts-gate: {exc}", file=sys.stderr)
        return 2
    if res.outcome in ("green", "unchanged"):
        selfheal.record("parts_gate")  # ran clean; red and skipped already marked it through their ANOMALY lines
    print(json.dumps({"outcome": res.outcome, "reason": res.reason, "parts": _shas(res.parts),
                      "failed_step": res.failed_step, "log_dir": res.log_dir}))
    return res.exit_code()
