"""Frames never reach Meta in prod or in serverless mode (docs/specs/licence-gates.md LIC-H2, serverless-compute.md AC-SC5)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from part7 import licence_gates, runner
from part7.parts import p2_pose


@pytest.fixture(params=["prod", "serverless"])
def gated(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.delenv("FIRM_ENV", raising=False)
    monkeypatch.delenv("SIMON7_COMPUTE", raising=False)
    if request.param == "prod":
        monkeypatch.setenv("FIRM_ENV", "prod")
    else:
        monkeypatch.setenv("SIMON7_COMPUTE", "serverless")
    return request.param


@pytest.mark.parametrize("asked", [None, "auto", "local-sam31", "api-sam31", "bytetrack", "local-open"])
def test_every_request_becomes_local_open(gated: str, asked: str | None) -> None:
    assert licence_gates.tracker(asked) == "local-open"


def test_the_meta_tracker_is_not_allowed(gated: str) -> None:
    assert licence_gates.tracker_allowed("api-sam31") is False
    assert licence_gates.tracker_allowed(None) is False
    assert licence_gates.tracker_allowed("local-open") is True


def test_outside_the_gate_the_request_stands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIRM_ENV", raising=False)
    monkeypatch.delenv("SIMON7_COMPUTE", raising=False)
    assert licence_gates.tracker("api-sam31") == "api-sam31" and licence_gates.tracker(None) is None


def _step(code: int) -> runner.Step:
    return runner.Step(part=2, commit="c", argv=[], cwd=".", exit=code, timed_out=False, duration_s=0.0, log="l")


def test_a_failed_local_open_is_not_retried_with_the_default_order(gated: str, tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """Part 2's default order holds api-sam31: no call without --tracker may start."""
    calls: list[list[str]] = []

    def execute(sub: list[str], *args: object, **kwargs: object) -> runner.Step:
        calls.append(sub)
        return _step(1)

    monkeypatch.setattr(p2_pose, "_execute", execute)
    monkeypatch.setattr(p2_pose, "api_tracker_allowed", lambda *a, **k: False)
    lock = SimpleNamespace(path=lambda part: tmp_path, sha=lambda part: "a" * 40, sha12=lambda part: "a" * 12)
    step, _ = p2_pose.track(tmp_path / "clip.mp4", tmp_path / "work", lock=lock, tracker="auto")
    assert step["exit"] == 1
    assert len(calls) == 1 and calls[0][calls[0].index("--tracker") + 1] == "local-open"
