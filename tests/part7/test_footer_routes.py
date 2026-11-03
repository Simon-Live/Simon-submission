"""TICKET-326 version footer, server side: the environment in the build stamp and GET api/notices (version-footer.md)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from part7 import buildinfo, notices_routes


def test_environment_is_staging_only_on_the_staging_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(buildinfo.config, "is_staging_server", lambda: True)
    assert buildinfo.environment() == "staging"
    monkeypatch.setattr(buildinfo.config, "is_staging_server", lambda: False)
    assert buildinfo.environment() == "local"


def test_environment_never_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom() -> bool:
        raise OSError("no state")

    monkeypatch.setattr(buildinfo.config, "is_staging_server", boom)
    assert buildinfo.environment() == "local"
    assert buildinfo.collect(tmp_path, parts={})["environment"] == "local"


def test_version_route_carries_the_environment(api) -> None:  # type: ignore[no-untyped-def]
    status, _, data = api.request("GET", "api/version")
    assert status == 200 and json.loads(data)["environment"] in ("staging", "local")


def test_notices_route_serves_the_notices_file_as_text(api) -> None:  # type: ignore[no-untyped-def]
    if not notices_routes.NOTICES.is_file():  # the client repo has no notices file until the licence is decided (MoAlborati/claude-template#382)
        pytest.skip("THIRD_PARTY_NOTICES.md is not in this tree (licence decision pending, MoAlborati/claude-template#382)")
    status, headers, data = api.request("GET", "api/notices")
    assert status == 200
    assert data == notices_routes.NOTICES.read_bytes() and data.startswith(b"# Third-party notices")
    assert "text/plain" in str(headers)


def test_notices_route_missing_file_is_404_and_post_is_405(api, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    assert api.request("POST", "api/notices", b"{}")[0] == 405
    monkeypatch.setattr(notices_routes, "NOTICES", tmp_path / "absent.md")
    status, _, data = api.request("GET", "api/notices")
    assert status == 404 and json.loads(data)["error"] == notices_routes.MSG_NO_NOTICES


def test_other_routes_are_not_taken() -> None:
    assert notices_routes.handle(object(), "GET", "version") is False
