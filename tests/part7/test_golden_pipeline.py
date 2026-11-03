"""GPU-free golden pipeline, replay and badges (docs/specs/golden-replay.md, TICKET-263).

AC-1a: Parts 3 to 5 and the compare, on the CPU, from stored Part 2 poses, equal `expected.json` exactly.
AC-3: `part7 replay <job>` exits 0 on equality and 1 naming the first differing field.
AC-4: fixtures hold derived numbers only; badges come from the run's JUnit.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from typing import Any

import pytest

from part7 import cli, config, golden, golden_badges, modules

FIX = golden.FIXTURE_DIR
PARTS_HINT = "run `uv run python -m part7 setup-parts --only 3,4,5,6`"


def _parts_ready() -> bool:
    return ((config.part_dir("3") / ".venv" / "bin" / "python").is_file()
            and (config.part_dir("4") / "src").is_dir() and (config.part_dir("5") / "pyproject.toml").is_file())


needs_parts = pytest.mark.skipif(
    not _parts_ready() and not os.environ.get("SIMON7_GOLDEN_REQUIRED"),
    reason=f"Parts 3 to 6 are not set up here: {PARTS_HINT}",
)


@pytest.fixture(autouse=True)
def _no_part2_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Integrator rule: nothing here starts a Part 2 worker or holds the GPU; the golden pipeline is CPU-only."""
    monkeypatch.setenv("SIMON7_P2_WARM_WORKERS", "0")


def test_golden_module_never_touches_part2() -> None:
    src = (config.REPO_ROOT / "part7" / "golden.py").read_text(encoding="utf-8")
    assert "p2_pose" not in src and "p2_worker" not in src


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One real pipeline run: the summaries, plus the work folder for the replay job."""
    assert _parts_ready(), f"Parts 3 to 6 are required (SIMON7_GOLDEN_REQUIRED set): {PARTS_HINT}"
    work = tmp_path_factory.mktemp("golden")
    lock = modules.load()
    animation = golden.trainer_cpu(FIX / golden.TRAINER / golden.POSE_FILE, work / "trainer", lock)
    clip = golden.TAKES[0]
    follower, analysis = golden.follower_cpu(FIX / clip / golden.POSE_FILE, animation, work / clip, lock)
    full = golden.run_golden(FIX, work / "all", lock)
    return {"full": full, "animation": animation, "follower": follower, "analysis": analysis, "clip": clip}


def _job(tmp: Path, run: dict[str, Any]) -> Path:
    """A job folder shaped like the app's: work/expected.json and work/follower/{part2/pose3d.json, outputs}."""
    job = tmp / "job1"
    fdir = job / "work" / "follower"
    (fdir / "part2").mkdir(parents=True)
    shutil.copyfile(run["animation"], job / "work" / "expected.json")
    shutil.copyfile(FIX / run["clip"] / golden.POSE_FILE, fdir / "part2" / golden.POSE_FILE)
    shutil.copyfile(run["follower"], fdir / "follower.json")
    shutil.copyfile(run["analysis"], fdir / "analysis.json")
    return job


# --------------------------------------------------------------------------- AC-1a


@needs_parts
def test_golden_pipeline_equals_expected(run: dict[str, Any]) -> None:
    expected = json.loads((FIX / golden.EXPECTED_FILE).read_text(encoding="utf-8"))
    for clip, take in run["full"]["takes"].items():
        print(f"golden {clip}: status={take['status']} score={take['score']} faults="
              f"{[(f['measure'], f['side'], f['at_s']) for f in take['faults']]}")
    assert run["full"]["takes"] == expected["takes"]
    assert run["full"]["trainer"] == expected["trainer"]


def test_expected_is_not_trivial() -> None:
    takes = json.loads((FIX / golden.EXPECTED_FILE).read_text(encoding="utf-8"))["takes"]
    assert set(takes) == set(golden.TAKES)
    followers = [takes[c] for c in golden.TAKES[:2]]
    assert all(isinstance(t["score"], int) and t["score"] > 0 and t["faults"] for t in followers)
    assert all("at_s" in f for t in followers for f in t["faults"])


# --------------------------------------------------------------------------- AC-3


@needs_parts
def test_replay_positive_exits_zero(run: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["replay", str(_job(tmp_path, run))]) == 0
    assert "reproduces" in capsys.readouterr().out


@needs_parts
def test_replay_by_job_id_under_state(run: dict[str, Any], tmp_path: Path) -> None:
    job = _job(tmp_path, run)
    jobs = tmp_path / "state" / "jobs"
    jobs.mkdir(parents=True)
    job.rename(jobs / "abc123")
    assert cli.main(["replay", "abc123", "--state", str(tmp_path / "state")]) == 0


@needs_parts
def test_replay_negative_names_the_analysis_field(run: dict[str, Any], tmp_path: Path,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    job = _job(tmp_path, run)
    path = job / "work" / "follower" / "analysis.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["score"]["value"] = doc["score"]["value"] + 1
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert cli.main(["replay", str(job)]) == 1
    assert "analysis.json differs at score.value" in capsys.readouterr().err


@needs_parts
def test_replay_negative_names_the_follower_field(run: dict[str, Any], tmp_path: Path,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    job = _job(tmp_path, run)
    path = job / "work" / "follower" / "follower.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    key = next(k for k, v in doc.items() if isinstance(v, (int, float)) and not isinstance(v, bool))
    doc[key] = doc[key] + 1
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert cli.main(["replay", str(job)]) == 1
    assert f"follower.json differs at {key}" in capsys.readouterr().err


def test_replay_missing_input_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "job" / "work").mkdir(parents=True)
    assert cli.main(["replay", str(tmp_path / "job")]) == 2
    assert "lacks" in capsys.readouterr().err


def test_first_difference_cases() -> None:
    assert golden.first_difference({"a": 1}, {"a": 1}) is None
    assert golden.first_difference({"a": {"b": [1, 2]}}, {"a": {"b": [1, 3]}}) == "a.b[1]"
    assert golden.first_difference({"a": 1, "b": 2}, {"a": 1}) == "b"
    assert golden.first_difference({"a": 1}, {"a": 1, "z": 0}) == "z"
    assert golden.first_difference([1], [1, 2]) == "[1]"
    assert golden.first_difference({"a": 1}, {"a": 1.0}) == "a"  # 1 versus 1.0 is a byte difference
    assert golden.first_difference({"a": True}, {"a": 1}) == "a"


# --------------------------------------------------------------------------- AC-4


def test_fixtures_hold_derived_numbers_only() -> None:
    names = sorted(p.relative_to(FIX).as_posix() for p in FIX.rglob("*") if p.is_file())
    expected = sorted([golden.EXPECTED_FILE, *(f"{c}/{golden.POSE_FILE}" for c in (golden.TRAINER, *golden.TAKES))])
    assert names == expected
    for pose in FIX.glob(f"*/{golden.POSE_FILE}"):
        text = pose.read_text(encoding="utf-8")
        assert "/home/" not in text and ".mp4" not in text and ".jpg" not in text


def test_fixture_clips_are_licensed_pexels_clips() -> None:
    for clip in (golden.TRAINER, *golden.TAKES):
        assert "Pexels License" in (config.REPO_ROOT / "videos" / clip / "SOURCE.md").read_text(encoding="utf-8")


def test_fixtures_are_on_the_publish_allowlist() -> None:
    lines = (config.REPO_ROOT / ".simon-publish").read_text(encoding="utf-8").splitlines()
    assert "tests/part7/**" in lines


JUNIT = """<?xml version="1.0"?><testsuites>
<testsuite name="a" tests="5" failures="1" errors="0" skipped="1"/>
<testsuite name="b" tests="3" failures="0" errors="1" skipped="0"/></testsuites>"""
COBERTURA = '<coverage line-rate="0.8312" branch-rate="0"></coverage>'


def test_badges_from_junit_and_coverage(tmp_path: Path) -> None:
    (tmp_path / "junit.xml").write_text(JUNIT, encoding="utf-8")
    (tmp_path / "coverage.xml").write_text(COBERTURA, encoding="utf-8")
    summary = tmp_path / "summary.md"
    args = ["--junit", str(tmp_path / "junit.xml"), "--coverage", str(tmp_path / "coverage.xml"),
            "--out", str(tmp_path / "b"), "--summary", str(summary)]
    assert golden_badges.main(args) == 0
    tests = json.loads((tmp_path / "b" / "tests.json").read_text(encoding="utf-8"))
    assert tests["message"] == "2 failed, 5 passed" and tests["color"] == "red"
    cov = json.loads((tmp_path / "b" / "coverage.json").read_text(encoding="utf-8"))
    assert cov["message"] == "83.1%" and cov["color"] == "brightgreen"
    assert "| 8 | 1 | 1 | 1 | 83.1% |" in summary.read_text(encoding="utf-8")


def test_badges_green_when_nothing_failed(tmp_path: Path) -> None:
    (tmp_path / "junit.xml").write_text('<testsuite tests="3" failures="0" errors="0" skipped="0"/>', encoding="utf-8")
    assert golden_badges.main(["--junit", str(tmp_path / "junit.xml"), "--out", str(tmp_path / "b")]) == 0
    assert json.loads((tmp_path / "b" / "tests.json").read_text(encoding="utf-8"))["color"] == "brightgreen"
    assert not (tmp_path / "b" / "coverage.json").exists()


def test_badges_unreadable_input_exits_two(tmp_path: Path) -> None:
    assert golden_badges.main(["--junit", str(tmp_path / "none.xml"), "--out", str(tmp_path / "b")]) == 2
