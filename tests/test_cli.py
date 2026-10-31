"""Tests for `part7.cli` and `part7.config` (TICKET-004)."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import pytest

from part7 import cli, config


def test_config_state_root_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = tmp_path / "custom-state"
    monkeypatch.setenv("SIMON7_STATE_DIR", str(custom))
    assert config.state_root() == custom.resolve()
    assert config.videos_dir() == (custom / "videos").resolve()
    assert config.dev_dir() == (custom / "dev").resolve()
    assert config.staging_dir() == (custom / "staging").resolve()
    assert config.check_dir() == (custom / "check").resolve()


def test_normalize_base_path() -> None:
    assert config.normalize_base_path(None) == "/"
    assert config.normalize_base_path("") == "/"
    assert config.normalize_base_path("/") == "/"
    assert config.normalize_base_path("/simon-part-7") == "/simon-part-7/"
    assert config.normalize_base_path("simon-part-7") == "/simon-part-7/"
    assert config.normalize_base_path("/simon-part-7/") == "/simon-part-7/"


def test_cli_parser_subcommands() -> None:
    parser = cli.build_parser()

    args_status = parser.parse_args(["parts-status", "--check-remote"])
    assert args_status.command == "parts-status" and args_status.check_remote is True
    assert parser.parse_args(["parts-status"]).check_remote is False

    args_setup = parser.parse_args(["setup-parts"])
    assert args_setup.command == "setup-parts"

    args_doc = parser.parse_args(["doctor-parts"])
    assert args_doc.command == "doctor-parts"

    args_vid = parser.parse_args(["videos", "verify"])
    assert args_vid.command == "videos"
    assert args_vid.action == "verify"

    args_chain = parser.parse_args(["chain", "--trainer", "t1", "--follower", "f1", "--follower", "f2"])
    assert args_chain.command == "chain"
    assert args_chain.trainer == "t1"
    assert args_chain.follower == ["f1", "f2"]

    args_serve = parser.parse_args(["serve", "--port", "7124", "--base-path", "/simon-part-7/"])
    assert args_serve.command == "serve"
    assert args_serve.port == 7124
    assert args_serve.base_path == "/simon-part-7/"

    args_check = parser.parse_args(["check"])
    assert args_check.command == "check"


def test_python_m_part7_help() -> None:
    res = subprocess.run(
        [sys.executable, "-m", "part7", "--help"],
        cwd=config.REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    for cmd in ("parts-status", "setup-parts", "doctor-parts", "videos", "chain", "serve", "check"):
        assert cmd in res.stdout


def test_modules_dir_resolves_to_repo_modules_and_env_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIMON7_MODULES_DIR", raising=False)
    assert config.modules_dir() == config.REPO_ROOT / "modules"
    assert config.part_dir(3) == config.REPO_ROOT / "modules" / "part-3"
    monkeypatch.setenv("SIMON7_MODULES_DIR", str(tmp_path))
    assert config.part_dir("6") == tmp_path.resolve() / "part-6"
