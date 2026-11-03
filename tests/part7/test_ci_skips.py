"""TICKET-244: the stated CI skips (tests/part7/ci_skips.py) name their reason and are counted, never silent."""

from __future__ import annotations

from pathlib import Path

import pytest

import ci_skips as cs

PARTS_TEST = "tests/part7/test_part5_history_contract.py::test_x"
HOST_TEST = "tests/part7/test_animation_format.py::test_every_staging_library_animation_is_handled"


def test_a_test_that_needs_a_missing_part_skips_naming_the_secret() -> None:
    kind, reason = cs.skip_reason(PARTS_TEST, {"5"}, github=False)
    assert kind == "parts" and "modules/part-5" in reason and "PARTS_READ_TOKEN" in reason


def test_a_part_that_is_present_runs_the_test() -> None:  # the negative
    assert cs.skip_reason(PARTS_TEST, {"1", "2"}, github=False) is None
    assert cs.skip_reason("tests/test_cli.py::test_anything", {"1", "2", "3", "4", "5", "6"}, github=False) is None


def test_parametrized_ids_match_their_function() -> None:
    nodeid = "tests/part7/test_mode_scoring.py::test_real_part5_native_profiles[dance-a]"
    assert cs.skip_reason(nodeid, {"5"}, github=False)[0] == "parts"
    assert cs.skip_reason("tests/part7/test_mode_scoring.py::test_real_part5_native_profiles_x", {"5"}, False) is None


def test_host_tests_skip_on_a_github_runner_only() -> None:
    kind, reason = cs.skip_reason(HOST_TEST, set(), github=True)
    assert kind == "host" and "no GPU and no staging host" in reason
    assert cs.skip_reason(HOST_TEST, set(), github=False) is None


def test_an_unpublished_file_skips_only_when_absent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    nodeid = "tests/part7/test_camera_paths.py::test_the_samples_validate[orbit]"
    monkeypatch.setattr(cs.config, "REPO_ROOT", tmp_path)
    kind, reason = cs.skip_reason(nodeid, set(), github=True)
    assert kind == "unpublished" and "docs/specs/camera-path-samples/orbit.json" in reason
    (tmp_path / "docs/specs/camera-path-samples").mkdir(parents=True)
    (tmp_path / "docs/specs/camera-path-samples/orbit.json").write_text("{}", encoding="utf-8")
    assert cs.skip_reason(nodeid, set(), github=True) is None


def test_empty_part_folders_count_as_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for n in range(1, 7):
        (tmp_path / f"part-{n}").mkdir()
    (tmp_path / "part-3" / "README.md").write_text("x", encoding="utf-8")
    monkeypatch.setenv("SIMON7_MODULES_DIR", str(tmp_path))
    assert cs.missing_parts() == {"1", "2", "4", "5", "6"}


def test_the_summary_line_names_the_secret_and_the_count() -> None:
    lines = cs.summary_lines({"parts": 7, "unpublished": 0, "host": 2}, {"5"})
    assert lines[0] == "Part repos not checked out (PARTS_READ_TOKEN not set): 7 tests skipped that need them"
    assert lines[1] == "GPU and staging host tests skipped on the GitHub runner: 2"
    assert cs.summary_lines({"parts": 0, "unpublished": 0, "host": 0}, set()) == []  # all parts present: no line
