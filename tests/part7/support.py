"""Helpers for the server tests: a stub Part 6 over HTTP, tiny real videos, a request client."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading
from typing import Any

from part7 import pins, server

VIDEO_BYTES = bytes(range(256)) * 400  # 102400 bytes for Range tests


def make_lock() -> pins.Lock:
    parts = {
        str(n): {"repo": f"https://example.com/p{n}.git", "sha": str(n) * 40, "pinned_at": "2026-10-29T14:52:00Z",
                 "status": "STATUS: DONE", "repin_due": False}
        for n in range(1, 7)
    }
    return pins.Lock({"schema": "part7.parts-lock/1", "pinned_at": "2026-10-29T14:52:00Z", "parts": parts})


class _Part6Stub(BaseHTTPRequestHandler):
    """Answers like Part 6 under `/catalog`: entries, one video with Range support."""

    def log_message(self, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        if "/catalog/video.mp4" in self.path:
            return self._video()
        body = json.dumps({"path": self.path, "ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Seen-Host", self.headers.get("Host", ""))
        self.send_header("X-Seen-Custom", self.headers.get("X-Custom", ""))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        data = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(201)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _video(self) -> None:
        rng = self.headers.get("Range")
        data, status, extra = VIDEO_BYTES, 200, {}
        if rng and rng.startswith("bytes="):
            start_s, _, end_s = rng[6:].partition("-")
            start, end = int(start_s), int(end_s) if end_s else len(VIDEO_BYTES) - 1
            data, status = VIDEO_BYTES[start : end + 1], 206
            extra["Content-Range"] = f"bytes {start}-{end}/{len(VIDEO_BYTES)}"
        self.send_response(status)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Accept-Ranges", "bytes")
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)


class FakeChild:
    """Stands in for `p6_catalog.Child`: a stub Part 6 HTTP port plus canned entries."""

    def __init__(self, catalog_dir: Path) -> None:
        self.catalog_dir = catalog_dir
        self._http = ThreadingHTTPServer(("127.0.0.1", 0), _Part6Stub)
        self.port = self._http.server_address[1]
        threading.Thread(target=self._http.serve_forever, daemon=True).start()
        self.up = True
        self.entries: dict[str, dict[str, Any]] = {
            "lateral-raise": {"id": "lateral-raise", "animation": "animation.json", "skeleton": "skeleton.json"},
            "skel-only": {"id": "skel-only", "animation": None, "skeleton": "skeleton.json"},
            "empty": {"id": "empty", "animation": None, "skeleton": None},
        }
        self.files = {"animation.json": b'{"format": "simon.animation.v1"}', "skeleton.json": b'{"format": "x"}'}

    def health(self) -> dict[str, Any] | None:
        return {"ok": True} if self.up else None

    def list_entries(self) -> list[dict[str, Any]]:
        return list(self.entries.values())

    def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        return self.entries.get(entry_id)

    def get_entry_file(self, entry_id: str, filename: str) -> bytes | None:
        return self.files.get(filename)

    def close(self) -> None:
        self._http.shutdown()
        self._http.server_close()


def ffmpeg_video(path: Path, seconds: float, codec: str = "libx264") -> Path:
    """Write a tiny real video (testsrc) of `seconds`; mp4 for libx264, webm for libvpx."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=5:duration={seconds}",
         "-c:v", codec, "-pix_fmt", "yuv420p", str(path)],
        check=True, timeout=120,
    )
    return path


class Api:
    """A running app on a free port with small request helpers."""

    def __init__(self, app: server.App, http: ThreadingHTTPServer) -> None:
        self.app, self.http, self.port = app, http, http.server_address[1]

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None,
                base: str | None = None) -> tuple[int, dict[str, str], bytes]:
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request(method, (base if base is not None else self.app.base) + path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        out = (resp.status, {k.lower(): v for k, v in resp.getheaders()}, data)
        conn.close()
        return out

    def json(self, method: str, path: str, doc: Any = None, headers: dict[str, str] | None = None
             ) -> tuple[int, Any]:
        hdr = {"Content-Type": "application/json", **(headers or {})}
        status, _, data = self.request(method, path, None if doc is None else json.dumps(doc).encode(), hdr)
        return status, json.loads(data or b"null")

    def upload(self, path: Path, ctype: str = "video/mp4", headers: dict[str, str] | None = None
               ) -> tuple[int, Any]:
        status, _, data = self.request("POST", "api/uploads", path.read_bytes(), {"Content-Type": ctype, **(headers or {})})
        return status, json.loads(data)


def lock_with_schema(tmp_path: Path, schema: dict[str, Any]) -> tuple[pins.Lock, Path]:
    """A lock whose Part 5 clone (under a temp state folder) ships `contracts/replay.schema.json`."""
    lk, state = make_lock(), tmp_path / "pstate"
    clone = lk.path("5", state=state)
    (clone / "contracts").mkdir(parents=True)
    (clone / "contracts" / "replay.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    return lk, state
