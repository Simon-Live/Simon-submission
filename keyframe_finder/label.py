"""Local page for correcting keyframes by hand.

Serves the original video and the predicted keyframes. Saving writes
fixtures/labels/<name>.json and does not call the API.
"""

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from keyframe_finder.schema import FORMAT, dump_json, validate

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "inbox"
LABELS = ROOT / "fixtures" / "labels"
PAGE = ROOT / "label" / "index.html"
STEM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
PORT = 8767


def videos():
    found = []
    if not INBOX.is_dir():
        return found
    for path in sorted(INBOX.glob("*.mp4")):
        draft = ROOT / "out" / path.stem / "keyframes.json"
        if draft.is_file() and STEM.match(path.stem):
            found.append(path.stem)
    return found


def media_path(stem):
    if not STEM.match(stem):
        raise FileNotFoundError(stem)
    link = INBOX / f"{stem}.mp4"
    if not link.is_file():
        raise FileNotFoundError(stem)
    return link.resolve()


def draft_path(stem):
    if not STEM.match(stem):
        raise FileNotFoundError(stem)
    path = ROOT / "out" / stem / "keyframes.json"
    if not path.is_file():
        raise FileNotFoundError(stem)
    return path


def label_document(stem, payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("people"), list):
        raise ValueError("a label needs a people list")
    document = {
        "format": FORMAT,
        "video": f"inbox/{stem}.mp4",
        "fps": payload.get("fps"),
        "people": payload["people"],
    }
    if payload.get("analysis_fps") is not None:
        document["analysis_fps"] = payload["analysis_fps"]
    errors = validate(document)
    if errors:
        raise ValueError("; ".join(errors[:5]))
    return document


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/label", "/label/"}:
            self._send_bytes(PAGE.read_bytes(), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/videos":
            self._send_json({"videos": videos()})
            return
        if parsed.path == "/api/draft":
            stem = (parse_qs(parsed.query).get("video") or [""])[0]
            try:
                draft = json.loads(draft_path(stem).read_text(encoding="utf-8"))
            except FileNotFoundError:
                self._send_json({"error": "no keyframes for that video"}, status=404)
                return
            label_path = LABELS / f"{stem}.json"
            label = json.loads(label_path.read_text(encoding="utf-8")) if label_path.is_file() else None
            self._send_json(
                {
                    "stem": stem,
                    "media": f"/media/{stem}.mp4",
                    "draft": draft,
                    "label": label,
                }
            )
            return
        if parsed.path.startswith("/media/"):
            stem = Path(parsed.path).name.removesuffix(".mp4")
            try:
                self._send_media(media_path(stem))
            except FileNotFoundError:
                self._send_json({"error": "video not in inbox"}, status=404)
            return
        self._send_json({"error": "not found"}, status=404)

    def do_HEAD(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/media/"):
            stem = Path(parsed.path).name.removesuffix(".mp4")
            try:
                path = media_path(stem)
            except FileNotFoundError:
                self.send_error(404)
                return
            size = path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            return
        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        prefix = "/api/labels/"
        if not parsed.path.startswith(prefix):
            self._send_json({"error": "not found"}, status=404)
            return
        stem = parsed.path[len(prefix):]
        if not STEM.match(stem):
            self._send_json({"error": "unknown video"}, status=404)
            return
        try:
            draft_path(stem)
        except FileNotFoundError:
            self._send_json({"error": "no keyframes for that video"}, status=404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            document = label_document(stem, json.loads(raw.decode("utf-8")))
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        dest = LABELS / f"{stem}.json"
        dump_json(dest, document)
        self._send_json({"saved": dest.relative_to(ROOT).as_posix()})

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self._send_bytes(body, "application/json", status)

    def _send_bytes(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_media(self, path):
        size = path.stat().st_size
        start, end = 0, size - 1
        status = 200
        requested = self.headers.get("Range")
        if requested:
            match = re.match(r"bytes=(\d*)-(\d*)$", requested.strip())
            if not match or (match.group(1) == "" and match.group(2) == ""):
                self.send_error(416)
                return
            if match.group(1) == "":
                start = max(0, size - int(match.group(2)))
            else:
                start = int(match.group(1))
                if match.group(2):
                    end = int(match.group(2))
            end = min(end, size - 1)
            if start > end or start >= size:
                self.send_error(416)
                return
            status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        remaining = length
        with path.open("rb") as handle:
            handle.seek(start)
            while remaining > 0:
                chunk = handle.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= len(chunk)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    stems = videos() or [path.stem for path in sorted(INBOX.glob("*.mp4"))]
    if stems:
        print(f"Label: http://127.0.0.1:{PORT}/?video={stems[0]}", flush=True)
    else:
        print(f"Label: http://127.0.0.1:{PORT}/?video=<name>", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
