"""Tests for `part7.pins` (TICKET-003, AC-H1, AC-H2, AC-H11)."""

from __future__ import annotations

import subprocess
from pathlib import Path
import pytest

from part7 import pins


def _make_git_repo(base: Path, name: str, content: str = "v1") -> tuple[str, str]:
    repo_dir = base / name
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True)
    (repo_dir / "README.md").write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-q", "-m", f"init {content}"], cwd=repo_dir, check=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return str(repo_dir), sha


def _commit_update(repo_dir: str, content: str) -> str:
    p = Path(repo_dir)
    (p / "README.md").write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=p, check=True)
    subprocess.run(["git", "commit", "-q", "-m", f"update {content}"], cwd=p, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=p,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_pin_writes_six_records_and_update_single_part(tmp_path: Path, state_dir: Path) -> None:
    """AC-H1: `part7 pin` writes six records with 40-char shas; `--update 2` changes only Part 2."""
    repos_root = tmp_path / "repos"
    repo_urls: dict[str, str] = {}
    initial_shas: dict[str, str] = {}
    for n in ("1", "2", "3", "4", "5", "6"):
        url, sha = _make_git_repo(repos_root, f"part-{n}", content=f"part {n} v1")
        repo_urls[n] = url
        initial_shas[n] = sha

    ws_root = tmp_path / "workspaces"
    (ws_root / "p2").mkdir(parents=True)
    (ws_root / "p2" / "STATUS.md").write_text("# Status\nSTATUS: DONE\n", encoding="utf-8")
    (ws_root / "p5").mkdir(parents=True)
    (ws_root / "p5" / "STATUS.md").write_text("# Status\nIn progress\n", encoding="utf-8")
    workspaces = {"2": ws_root / "p2", "5": ws_root / "p5"}

    lock_file = tmp_path / "parts.lock.json"
    lock = pins.pin(
        update=None,
        materialize=False,
        lock_file=lock_file,
        state=state_dir,
        repo_urls=repo_urls,
        workspaces=workspaces,
    )

    assert lock_file.is_file()
    for n in ("1", "2", "3", "4", "5", "6"):
        assert len(lock.sha(n)) == 40
        assert lock.sha(n) == initial_shas[n]
        assert lock.sha12(n) == initial_shas[n][:12]

    assert lock.part_info("2")["status"] == "STATUS: DONE"
    assert lock.part_info("2")["repin_due"] is False
    assert lock.part_info("5")["status"] == "In progress"
    assert lock.part_info("5")["repin_due"] is True

    # Advance both Part 1 and Part 2 upstream, but only `--update 2`
    _commit_update(repo_urls["1"], "part 1 v2")
    new_sha2 = _commit_update(repo_urls["2"], "part 2 v2")

    lock2 = pins.pin(
        update=["2"],
        materialize=False,
        lock_file=lock_file,
        state=state_dir,
        repo_urls=repo_urls,
        workspaces=workspaces,
    )
    assert lock2.sha("2") == new_sha2
    assert lock2.sha("1") == initial_shas["1"]
    for n in ("3", "4", "5", "6"):
        assert lock2.sha(n) == initial_shas[n]


def test_pin_unreachable_upstream_exits_3(tmp_path: Path, state_dir: Path) -> None:
    """AC-H1 Error Case: unreachable upstream raises PinError with exit_code=3."""
    bad_repo = str(tmp_path / "does-not-exist.git")
    repo_urls = {str(n): bad_repo for n in range(1, 7)}
    lock_file = tmp_path / "parts.lock.json"

    with pytest.raises(pins.PinError) as exc_info:
        pins.pin(lock_file=lock_file, state=state_dir, repo_urls=repo_urls)
    assert exc_info.value.exit_code == 3
    assert f"pin: {bad_repo} unreachable" in str(exc_info.value)


def test_materialize_clones_and_detects_sha_mismatch(tmp_path: Path, state_dir: Path) -> None:
    """AC-H2: `--materialize` clones each missing pin; a clone at the wrong sha is an error naming it."""
    repos_root = tmp_path / "repos"
    repo_urls: dict[str, str] = {}
    shas: dict[str, str] = {}
    for n in ("1", "2", "3", "4", "5", "6"):
        url, sha = _make_git_repo(repos_root, f"part-{n}", content=f"part {n} v1")
        repo_urls[n] = url
        shas[n] = sha

    lock_file = tmp_path / "parts.lock.json"
    lock = pins.pin(
        materialize=True,
        lock_file=lock_file,
        state=state_dir,
        repo_urls=repo_urls,
    )

    for n in ("1", "2", "3", "4", "5", "6"):
        cdir = lock.path(n, state=state_dir)
        assert (cdir / ".git").exists()
        head = subprocess.run(
            ["git", "-C", str(cdir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert head == shas[n]

    # Move clone 3 to a different commit and verify materialize raises PinError (exit 1)
    cdir3 = lock.path("3", state=state_dir)
    (cdir3 / "README.md").write_text("tampered", encoding="utf-8")
    subprocess.run(["git", "-C", str(cdir3), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(cdir3), "commit", "-q", "-m", "tamper"], check=True)
    wrong_sha = subprocess.run(
        ["git", "-C", str(cdir3), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    with pytest.raises(pins.PinError) as exc_info:
        pins.pin(
            materialize=True,
            lock_file=lock_file,
            state=state_dir,
            repo_urls=repo_urls,
        )
    assert exc_info.value.exit_code == 1
    assert f"part 3: clone at {wrong_sha} but the lock says {shas['3']}" in str(exc_info.value)


def test_probe_part2_backend_detection(tmp_path: Path) -> None:
    """AC-H11: stub `part2 run --help` without `--backend` records `entry_point: missing` and `repin_due: true`."""
    rec_missing: dict[str, object] = {}
    res_missing = pins.probe_part2(
        tmp_path,
        runner=lambda cmd, cwd: (0, "usage: part2 run [--mode MODE] [--input INPUT]\n"),
        record=rec_missing,
    )
    assert res_missing == {"entry_point": "missing", "repin_due": True}
    assert rec_missing["entry_point"] == "missing"
    assert rec_missing["repin_due"] is True

    rec_ok: dict[str, object] = {}
    res_ok = pins.probe_part2(
        tmp_path,
        runner=lambda cmd, cwd: (0, "usage: part2 run [--mode MODE] [--backend {gpu,cpu}]\n"),
        record=rec_ok,
    )
    assert res_ok == {"entry_point": "backend", "repin_due": False}
    assert rec_ok["entry_point"] == "backend"
    assert rec_ok["repin_due"] is False
