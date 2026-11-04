"""The staging parts gate (TICKET-189; docs/specs/staging.md "Part updates are checked before staging adopts them")."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

from part7 import config, parts_gate
from part7.parts_gate import Deps

OLD, NEW, NEW2 = "a" * 40, "b" * 40, "c" * 40


def status(moved: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    moved = moved or {}
    return {n: {"sha": OLD, "remote_sha": moved.get(n, OLD)} for n in "123456"}


class Recorder:
    """Fake steps: records each call, fails the step named in `fail`."""

    def __init__(self, fail: str | None = None) -> None:
        self.fail, self.calls, self.notices, self.prepared, self.removed = fail, [], [], [], []

    def deps(self, moved: dict[str, str], mem: int | None = 20000) -> Deps:
        def run_step(argv: list[str], cwd: Path, env: dict[str, str], timeout_s: float, log: Path) -> int:
            name = next(n for n in ("setup-parts", "doctor-parts", "pytest") if n in argv)
            self.calls.append((name, argv, env))
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(f"{name}\n")
            return 1 if (self.fail and self.fail in name) else 0

        def prepare(repo: Path, wt: Path, cand: dict[str, Any], mods: Path) -> dict[str, str]:
            self.prepared.append(sorted(cand))
            return {}

        return Deps(status=lambda: status(moved), mem_mb=lambda: mem, prepare=prepare,
                    remove=lambda *a: self.removed.append(a[1]), run_step=run_step, sweep=lambda *a: None,
                    notify=lambda subject, body: self.notices.append(subject))


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    monkeypatch.setenv("SIMON7_STATE_DIR", str(state))
    return state


def test_nothing_moved_is_unchanged_and_runs_nothing(_env: Path) -> None:
    rec = Recorder()
    res = parts_gate.gate(deps=rec.deps({}))
    assert res.outcome == "unchanged" and res.exit_code() == 0 and rec.calls == []


def test_green_runs_setup_for_moved_parts_doctor_and_the_smoke_tests(_env: Path) -> None:
    rec = Recorder()
    res = parts_gate.gate(deps=rec.deps({"3": NEW, "5": NEW2}))
    assert res.outcome == "green" and res.exit_code() == 0
    assert [c[0] for c in rec.calls] == ["setup-parts", "doctor-parts", "pytest"]
    assert rec.calls[0][1][-2:] == ["--only", "3,5"]
    assert rec.calls[2][1][-len(parts_gate.SMOKE_TESTS):] == parts_gate.SMOKE_TESTS
    assert rec.calls[0][2]["SIMON7_STATE_DIR"] != str(_env), "the steps use a throwaway state dir"
    assert "SIMON7_MODULES_DIR" in rec.calls[0][2] and len(rec.removed) == 1
    assert json.loads((_env / "parts-gate" / "last.json").read_text())["outcome"] == "green"
    assert rec.notices == []


def test_red_records_last_json_logs_the_anomaly_and_notifies_once_per_sha(
    _env: Path, caplog: pytest.LogCaptureFixture
) -> None:
    rec = Recorder(fail="doctor")
    with caplog.at_level(logging.WARNING, logger=parts_gate.applog.LOGGER.name):
        res = parts_gate.gate(deps=rec.deps({"2": NEW}))
    assert res.outcome == "red" and res.exit_code() == 1 and res.failed_step == "doctor-parts"
    assert [c[0] for c in rec.calls] == ["setup-parts", "doctor-parts"], "the tests do not run after a red step"
    doc = json.loads((_env / "parts-gate" / "last.json").read_text())
    assert doc["outcome"] == "red" and doc["failed_step"] == "doctor-parts"
    assert doc["candidate_shas"] == {"2": NEW} and doc["log_dir"].endswith(Path(doc["log_dir"]).name)
    assert Path(doc["steps"][-1]["log"]).is_file() and doc["finished_at"]
    assert f"ANOMALY parts_gate_red part=2 sha={NEW} step=doctor-parts" in caplog.text
    assert len(rec.notices) == 1 and NEW[:12] in rec.notices[0]
    again = parts_gate.gate(deps=rec.deps({"2": NEW}))  # same sha: not rerun, not announced again
    assert again.outcome == "red" and len(rec.calls) == 2 and len(rec.notices) == 1
    forced = parts_gate.gate(deps=rec.deps({"2": NEW}), force=True)
    assert forced.outcome == "red" and len(rec.calls) == 4 and len(rec.notices) == 1, "same sha, same notice"
    parts_gate.gate(deps=rec.deps({"2": NEW2}))  # a new candidate sha is announced
    assert len(rec.notices) == 2


def test_a_red_gate_leaves_the_served_module_shas_alone(_env: Path) -> None:
    """The gate itself never moves a module: only `make parts` after exit 0 does (staging/parts-gate-run.sh)."""
    rec = Recorder(fail="pytest")
    res = parts_gate.gate(deps=rec.deps({"1": NEW}))
    assert res.outcome == "red" and res.failed_step == "tests" and res.exit_code() == 1


def test_the_lock_keeps_two_gates_from_running_at_once(_env: Path) -> None:
    gdir = parts_gate.gate_dir()
    gdir.mkdir(parents=True)
    with open(gdir / "gate.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rec = Recorder()
        res = parts_gate.gate(deps=rec.deps({"1": NEW}))
    assert res.outcome == "skipped" and res.exit_code() == 3 and rec.calls == []
    assert parts_gate.gate(deps=rec.deps({"1": NEW})).outcome == "green", "released lock lets the next gate run"


def test_low_memory_skips_logs_and_retries_next_tick(_env: Path, caplog: pytest.LogCaptureFixture) -> None:
    rec = Recorder()
    with caplog.at_level(logging.WARNING, logger=parts_gate.applog.LOGGER.name):
        res = parts_gate.gate(deps=rec.deps({"4": NEW}, mem=500))
    assert res.outcome == "skipped" and res.exit_code() == 3 and "memory" in res.reason
    assert rec.calls == [] and not (_env / "parts-gate" / "last.json").exists()
    assert "ANOMALY parts_gate_skipped" in caplog.text
    assert parts_gate.gate(deps=rec.deps({"4": NEW}, mem=20000)).outcome == "green"


def test_a_worktree_failure_is_red_at_the_worktree_step(_env: Path) -> None:
    rec = Recorder()
    deps = rec.deps({"1": NEW})

    def boom(*_a: Any) -> dict[str, str]:
        raise RuntimeError("part 1: fetch failed: offline")

    deps.prepare = boom
    res = parts_gate.gate(deps=deps)
    assert res.outcome == "red" and res.failed_step == "worktree" and rec.calls == [] and len(rec.removed) == 1


def test_candidates_skip_a_pin_ahead_of_main() -> None:
    st = {"1": {"sha": "a" * 40, "remote_sha": "b" * 40, "ahead": True}, "2": {"sha": "c" * 40, "remote_sha": "d" * 40}}
    assert list(parts_gate.candidates(st)) == ["2"]


def test_candidates_ignore_unknown_shas() -> None:
    st = status({"1": NEW})
    st["2"]["remote_sha"] = None
    st["3"]["sha"] = None
    assert list(parts_gate.candidates(st)) == ["1"]


def git(cwd: Path, *args: str) -> str:
    out = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_prepare_worktree_places_the_candidate_and_links_the_served_modules(tmp_path: Path) -> None:
    upstream = tmp_path / "up"
    upstream.mkdir()
    git(upstream, "init", "-q", "-b", "main")
    (upstream / "f.txt").write_text("one\n")
    git(upstream, "add", ".")
    git(upstream, "commit", "-q", "-m", "one")
    repo = tmp_path / "repo"
    (repo / "modules").mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    (repo / "README").write_text("x\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "root")
    for n in "123456":
        git(tmp_path, "clone", "-q", str(upstream), str(repo / "modules" / f"part-{n}"))
    old = git(upstream, "rev-parse", "HEAD")
    (upstream / "f.txt").write_text("two\n")
    git(upstream, "commit", "-q", "-am", "two")
    new = git(upstream, "rev-parse", "HEAD")
    wt = tmp_path / "wt"
    cand = {"2": {"old": old, "new": new}}
    resolved = parts_gate.prepare_worktree(repo, wt, cand, repo / "modules")
    assert resolved == {"2": new}
    assert (wt / "modules" / "part-2" / "f.txt").read_text() == "two\n"
    assert (wt / "modules" / "part-1").is_symlink()
    assert (repo / "modules" / "part-2" / "f.txt").read_text() == "one\n", "the served module is not moved"
    parts_gate.remove_worktree(repo, wt, cand, repo / "modules")
    assert not wt.exists()
    assert git(repo / "modules" / "part-2", "rev-parse", "HEAD") == old


def test_notify_uses_the_override_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "n.txt"
    monkeypatch.setenv("SIMON7_PARTS_GATE_NOTIFY_CMD", f"bash -c 'echo \"$0|$1\" > {out}'")
    parts_gate.notify("subject line", "body")
    assert out.read_text().strip() == "subject line|body"


def test_smoke_tests_exist_and_the_make_target_names_them() -> None:
    for rel in parts_gate.SMOKE_TESTS:
        assert (config.REPO_ROOT / rel).is_file(), rel
    assert "parts-smoke:" in (config.REPO_ROOT / "Makefile").read_text()


KILLED_GATE = textwrap.dedent("""
    import sys
    from pathlib import Path
    from part7 import parts_gate
    from part7.parts_gate import Deps
    pidfile = Path(sys.argv[1])

    def run_step(argv, cwd, env, timeout_s, log):
        # The real step runner: its own process group, a grandchild that would outlive a plain kill of the gate.
        return parts_gate.run_step(["bash", "-c", "sleep 300 & echo $! > " + str(pidfile) + "; wait"], cwd, env, 600, log)

    def prepare(repo, wt, cand, mods):
        wt.mkdir(parents=True)
        return {}

    deps = Deps(status=lambda: {n: {"sha": "a" * 40, "remote_sha": "b" * 40 if n == "2" else "a" * 40} for n in "123456"},
                mem_mb=lambda: 20000, prepare=prepare, remove=lambda *a: Path(sys.argv[2]).write_text("removed"),
                run_step=run_step, notify=lambda *a: None, sweep=lambda *a: None)
    sys.exit(parts_gate.gate(deps=deps).exit_code())
""")


def test_a_gate_killed_at_the_timeout_stops_its_steps_cleans_up_and_records_a_timeout(
    _env: Path, tmp_path: Path
) -> None:
    pidfile, removed = tmp_path / "sleep.pid", tmp_path / "removed"
    env = {**os.environ, "SIMON7_STATE_DIR": str(_env)}
    proc = subprocess.Popen([sys.executable, "-c", KILLED_GATE, str(pidfile), str(removed)], env=env)
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text().strip():
            break
        time.sleep(0.1)
    sleeper = int(pidfile.read_text())
    os.kill(proc.pid, signal.SIGTERM)  # what `timeout` sends at the helper limit
    assert proc.wait(timeout=30) == 124
    time.sleep(0.3)
    assert not Path(f"/proc/{sleeper}").exists(), "the step's own children were stopped, not orphaned"
    assert removed.read_text() == "removed"
    doc = json.loads((_env / "parts-gate" / "last.json").read_text())
    assert doc["outcome"] == "red" and doc["failed_step"] == "timeout"


def test_a_timeout_is_retried_on_the_same_shas_unlike_a_red(_env: Path) -> None:
    rec = Recorder()
    gdir = parts_gate.gate_dir()
    gdir.mkdir(parents=True)
    (gdir / "last.json").write_text(json.dumps({"outcome": "red", "failed_step": "timeout", "candidate_shas": {"2": NEW}}))
    assert parts_gate.gate(deps=rec.deps({"2": NEW})).outcome == "green"


def git(cwd: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin", "HOME": str(cwd)}
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout.strip()


def test_the_next_gate_sweeps_leftover_worktrees_under_its_own_work_dir_only(_env: Path, tmp_path: Path) -> None:
    repo, other = tmp_path / "repo", tmp_path / "elsewhere"
    mods = tmp_path / "mods"
    for d in (repo, mods / "part-2"):
        d.mkdir(parents=True)
        git(d, "init", "-q", "-b", "main")
        (d / "f").write_text("x")
        git(d, "add", "f")
        git(d, "commit", "-q", "-m", "c")
    gdir = parts_gate.gate_dir()
    leftover = gdir / "work" / "20260101T000000Z"
    git(repo, "worktree", "add", "--detach", str(leftover))
    git(mods / "part-2", "worktree", "add", "--detach", str(leftover / "modules-part-2"))
    git(mods / "part-2", "worktree", "add", "--detach", str(other))
    (gdir / "work" / "20260101T000000Z-state").mkdir()
    parts_gate.sweep_stale(repo, mods, gdir)
    assert list((gdir / "work").iterdir()) == []
    assert "elsewhere" in git(mods / "part-2", "worktree", "list"), "a worktree outside the gate's work dir is not touched"
    assert other.is_dir() and str(leftover) not in git(repo, "worktree", "list")
