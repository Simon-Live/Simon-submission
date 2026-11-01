"""TICKET-196: an upload refused as "not a video" is logged with its reason and kept for diagnosis."""
from __future__ import annotations

import logging
from pathlib import Path
import socket

import pytest

from part7 import refused_uploads
from support import Api


def _refused(api: Api) -> list[Path]:
    root = api.app.state / refused_uploads.DIR_NAME
    return sorted(root.iterdir()) if root.is_dir() else []


def _lines(caplog: pytest.LogCaptureFixture, text: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if text in r.getMessage() and r.levelno == logging.WARNING]


def _short_post(api: Api, body: bytes, announced: int) -> bytes:
    with socket.create_connection(("127.0.0.1", api.port), timeout=10) as sock:
        sock.sendall((f"POST {api.app.base}api/uploads HTTP/1.1\r\nHost: x\r\nContent-Type: video/webm\r\n"
                      f"Content-Length: {announced}\r\n\r\n").encode() + body)
        sock.shutdown(socket.SHUT_WR)
        out = b""
        while chunk := sock.recv(4096):
            out += chunk
        return out


def test_a_short_body_is_400_logged_and_kept(api: Api, tiny_mp4: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    data = tiny_mp4.read_bytes()
    reply = _short_post(api, data[: len(data) // 2], len(data))
    assert b" 400 " in reply.split(b"\r\n")[0]
    assert b"not a video" in reply.lower()
    (line,) = _lines(caplog, "upload refused (short_read)")
    assert f"announced {len(data)} bytes" in line and f"received {len(data) // 2} bytes" in line and "video/webm" in line
    assert len(_lines(caplog, "ANOMALY upload_refused")) == 1
    (kept,) = _refused(api)
    assert next(kept.glob("upload.*")).stat().st_size == len(data) // 2
    assert not any(api.app.uploads.iterdir())


def test_a_file_that_does_not_probe_is_400_logged_with_the_probe_error_and_kept(
    api: Api, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    junk = tmp_path / "junk.webm"
    junk.write_bytes(b"not a video at all" * 20)
    status, _ = api.upload(junk, "video/webm")
    assert status == 400
    (line,) = _lines(caplog, "upload refused (probe_failed)")
    assert "announced 360 bytes" in line and "received 360 bytes" in line and "probe error:" in line
    assert "reason=probe_failed" in _lines(caplog, "ANOMALY upload_refused")[0]
    assert len(_refused(api)) == 1


def test_a_wrong_content_type_is_400_and_logged(api: Api, tiny_mp4: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    assert api.upload(tiny_mp4, "text/plain")[0] == 400
    (line,) = _lines(caplog, "upload refused (content_type)")
    assert "text/plain" in line
    assert _refused(api) == []  # nothing was saved


def test_a_good_upload_logs_no_refusal(api: Api, tiny_mp4: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    assert api.upload(tiny_mp4)[0] == 201
    assert _lines(caplog, "upload refused") == [] and _refused(api) == []


def test_the_refused_store_keeps_the_last_twenty(tmp_path: Path) -> None:
    for i in range(25):
        folder = tmp_path / "uploads" / f"f{i:02d}"
        folder.mkdir(parents=True)
        (folder / "upload.webm").write_bytes(b"x")
        assert refused_uploads.keep(folder, tmp_path) is not None
    names = sorted(p.name for p in (tmp_path / refused_uploads.DIR_NAME).iterdir())
    assert len(names) == 20 and "f24" in names and "f00" not in names


def test_the_refused_store_stays_under_its_size_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(refused_uploads, "KEEP_BYTES", 2500)
    for i in range(5):
        folder = tmp_path / "uploads" / f"f{i}"
        folder.mkdir(parents=True)
        (folder / "upload.webm").write_bytes(b"x" * 1000)
        refused_uploads.keep(folder, tmp_path)
    names = sorted(p.name for p in (tmp_path / refused_uploads.DIR_NAME).iterdir())
    assert names == ["f3", "f4"]


def _age(folder: Path, days: float) -> None:
    import os
    import time
    stamp = time.time() - days * 86400
    os.utime(folder, (stamp, stamp))


def test_the_sweep_removes_refused_uploads_past_retention_and_keeps_newer_ones(tmp_path: Path) -> None:
    root = tmp_path / refused_uploads.DIR_NAME
    for name, days in (("old", 8), ("fresh", 1)):
        (root / name).mkdir(parents=True)
        (root / name / "upload.webm").write_bytes(b"x")
        _age(root / name, days)
    assert refused_uploads.sweep(tmp_path) == 1
    assert [p.name for p in root.iterdir()] == ["fresh"]


def test_the_sweep_with_no_refused_folder_is_a_no_op(tmp_path: Path) -> None:
    assert refused_uploads.sweep(tmp_path) == 0


def test_the_server_sweep_and_start_apply_retention(api: Api) -> None:
    from part7 import server
    root = api.app.state / refused_uploads.DIR_NAME
    (root / "old").mkdir(parents=True)
    _age(root / "old", 9)
    server._sweep(api.app)
    assert not (root / "old").exists()


def test_prune_tolerates_a_folder_that_vanishes_during_the_stat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / refused_uploads.DIR_NAME
    for name in ("a", "b"):
        (root / name).mkdir(parents=True)
    real = Path.stat
    seen = {"a": 0}

    def flaky(self: Path, *args: object, **kw: object):  # type: ignore[no-untyped-def]
        if self.name == "a" and self.parent == root:
            seen["a"] += 1
            if seen["a"] > 1:  # the listing's is_dir saw it; the mtime read after it did not
                raise FileNotFoundError(2, "gone", str(self))
        return real(self, *args, **kw)

    monkeypatch.setattr(Path, "stat", flaky)
    refused_uploads._prune(root)  # does not raise
    monkeypatch.undo()
    assert (root / "b").is_dir()


def test_keep_logs_the_failure_and_removes_the_folder_when_it_cannot_move(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    (tmp_path / "uploads-refused").write_text("a file where the folder should be")
    folder = tmp_path / "u1"
    folder.mkdir()
    assert refused_uploads.keep(folder, tmp_path) is None
    assert not folder.exists()
    assert any("refused upload not kept" in r.getMessage() for r in caplog.records)
