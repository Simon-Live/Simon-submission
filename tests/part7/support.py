"""Helpers for the server tests: a stub Part 6 over HTTP, tiny real videos, a request client."""

from __future__ import annotations

import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any, Iterator
import tempfile

from part7 import config, modules, server

VIDEO_BYTES = bytes(range(256)) * 400  # 102400 bytes for Range tests


def load_scaled(seconds: float, cap: float = 10.0) -> float:
    """A wait deadline stretched by host load (TICKET-188): `seconds` when idle, up to `cap` times that when the
    1-minute load average is above half the CPU count. Never shorter than `seconds`."""
    try:
        per_cpu = os.getloadavg()[0] / max(1, os.cpu_count() or 1)
    except (OSError, AttributeError):
        return seconds
    return seconds * min(cap, max(1.0, per_cpu * 2))


_DEFAULT_ROOT = Path(tempfile.mkdtemp(prefix="part7-test-modules-"))


def _seed_default_root() -> None:
    """The default stub root ships Part 5's real replay schema, as the part5 module does."""
    src = config.part_dir("5") / "contracts" / "replay.schema.json"
    if not src.is_file():
        return  # no Part 5 checkout (CI without PARTS_READ_TOKEN): tests that need the schema skip (ci_skips.py)
    dst = _DEFAULT_ROOT / "part-5" / "contracts" / "replay.schema.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())


_seed_default_root()


def stub_modules(root: Path | None = None) -> modules.Modules:
    """Modules under `root/part-N` with fixed shas (`1` * 40 ... `6` * 40); no git involved."""
    return modules.Modules(root=root or _DEFAULT_ROOT, shas={str(n): str(n) * 40 for n in range(1, 7)})


def make_lock() -> modules.Modules:
    return stub_modules()


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


def recorder_webm(path: Path, seconds: float = 3.0) -> Path:
    """A WebM like Chrome's MediaRecorder writes (TICKET-064): 1 ms time base, about 30 frames a second at
    irregular times, no duration and no DefaultDuration, so ffprobe reports `r_frame_rate` 1000/1 and no average.
    """
    tmp = path.with_suffix(".tmp.webm")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=30:duration={seconds}",
         "-vf", "settb=1/1000,setpts='(N*0.0338+random(1)*0.014)/TB'", "-fps_mode", "passthrough",
         "-enc_time_base", "1/1000", "-c:v", "libvpx", "-live", "1", "-f", "webm", str(tmp)],
        check=True, timeout=120,
    )
    data = bytearray(tmp.read_bytes())
    at = data.find(b"\x23\xe3\x83")  # DefaultDuration; overwritten by an EBML Void element of the same length
    if at >= 0:
        total = 4 + (data[at + 3] & 0x7F)
        data[at:at + total] = b"\xec" + bytes([0x80 | (total - 2)]) + bytes(total - 2)
    path.write_bytes(bytes(data))
    tmp.unlink()
    return path


def part1_reads(path: Path) -> bool:
    """Part 1's `media_info` probe (keyframe_finder/from_video.py at pin e84e92b1d0b1), regexes verbatim.

    Part 1 is a black box; this pins the contract Part 7 must meet: the ffmpeg banner of a clip handed to Part 1
    shows WxH, a plain number before `fps` (or `tbr`) and a Duration.
    """
    import re

    text = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    size = re.search(r"(\d{2,5})x(\d{2,5})", text)
    fps = re.search(r"(\d+(?:\.\d+)?)\s+fps", text) or re.search(r"(\d+(?:\.\d+)?)\s+tbr", text)
    duration = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", text)
    return bool(size and fps and duration)


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
        hdr = {"Content-Type": "application/json", **({"Origin": f"http://127.0.0.1:{self.port}"} if method == "POST" and path.endswith("/delete") else {}),
               **(headers or {})}  # a same-origin page sends its Origin on a delete (its CSRF guard)
        status, _, data = self.request(method, path, None if doc is None else json.dumps(doc).encode(), hdr)
        return status, json.loads(data or b"null")

    def upload(self, path: Path, ctype: str = "video/mp4", headers: dict[str, str] | None = None
               ) -> tuple[int, Any]:
        status, _, data = self.request("POST", "api/uploads", path.read_bytes(), {"Content-Type": ctype, **(headers or {})})
        return status, json.loads(data)


def lock_with_schema(tmp_path: Path, schema: dict[str, Any]) -> tuple[modules.Modules, Path]:
    """Modules whose Part 5 checkout (under a temp folder) ships `contracts/replay.schema.json`."""
    lk = stub_modules(tmp_path / "mods")
    clone = lk.path("5")
    (clone / "contracts").mkdir(parents=True)
    (clone / "contracts" / "replay.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    return lk, tmp_path / "pstate"


# ---------------------------------------------------------------- model job owners (TICKET-306)
def dead_pid() -> int:
    """The pid of a process that has already exited."""
    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait()
    return proc.pid


@contextlib.contextmanager
def live_process() -> Iterator[int]:
    """Another live process (the old server, in a restart with no gap); stopped by its pid when the block ends."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        yield proc.pid
    finally:
        proc.kill()
        proc.wait()


def stamp_of(pid: int) -> dict[str, Any]:
    """The `run_by` stamp a server with this pid writes into a model's status."""
    from part7.queue_lock import start_time

    return {"pid": pid, "start": start_time(pid)}
