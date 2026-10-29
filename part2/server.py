"""Part 2 web app server (docs/specs/run-app.md). Standard library only.

    python -m part2.server [--host 127.0.0.1] [--port 8722] [--base /]

Serves the pages in web/, the committed outputs under fixtures/output/ and the contract data, all
under a base path: `/` for scripts/dev.sh, `/simon-part-2/` behind the staging gateway. No path from
a request reaches the filesystem (AC-A11): a request picks an entry of a table built from directory
listings, and a name that is not in the table is a 404.

S0 routes (GET and HEAD only): the pages, api/health, api/outputs, api/outputs/<id>,
api/outputs/<id>/frames/<n>.jpg, api/contract, contracts/<file>.json and CONTRACT.md.
"""
from __future__ import annotations

import argparse
import json
import re
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent

CSP = "default-src 'self'; img-src 'self' data: blob:"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".json": "application/json",
         ".md": "text/markdown; charset=utf-8", ".jpg": "image/jpeg"}
# The fixed table of static files in web/. run.html, run.js and overlay.js arrive with M4; until
# the file exists the name answers 404.
STATIC = {"": "index.html", **{n: n for n in (
    "index.html", "contract.html", "run.html", "browse.js", "viewer.js", "run.js", "overlay.js",
    "style.css", "icon.svg")}}

MESSAGES = {
    "not_found": "Not found.",
    "method_not_allowed": "This address accepts GET and HEAD only.",
    "contract_unavailable": "The contract data is not available right now.",
    "bad_request": "The request could not be read.",
    "unreadable": "This output could not be read.",
    "internal": "The server could not answer this request.",
}
STATUS_CODES = {400: "bad_request", 404: "not_found", 405: "method_not_allowed", 503: "contract_unavailable"}

# ---- the committed outputs ---------------------------------------------------------------------------

CORE_OUTPUTS = ("single", "class", "dance")
OUTPUT_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
FRAME_FILE = re.compile(r"[A-Za-z0-9_.-]+\.jpe?g", re.IGNORECASE)
TITLES = {"single": "One person", "class": "Class of several people", "dance": "Dance group"}
# How the committed outputs were made (fixtures/output/README.md); used when pose3d.json has no
# `provenance` block. Descriptive text, not registry names.
MADE_BY = {"single": ("SAM 3D Body (HPC V100)", None),
           "class": ("SAM 3D Body (HPC V100)", "SAM 3.1 through the Meta API"),
           "dance": ("SAM 3D Body (HPC V100)", "SAM 3.1 through the Meta API")}
CLIPS = {
    "squat": {"title": "Squat - exercise demonstration video", "author": "FitnessScape", "licence": "CC BY 3.0",
              "url": "https://commons.wikimedia.org/wiki/File:Squat_-_exercise_demonstration_video.webm"},
    "stretch": {"title": "Side View of a Woman Stretching in a Health Club", "author": None,
                "licence": "Pexels licence",
                "url": "https://www.pexels.com/video/side-view-of-a-woman-stretching-in-a-health-club-6019962/"},
    "yoga": {"title": "People Doing the Cat Cow Pose in a Yoga Class", "author": "Yan Krukau",
             "licence": "Pexels licence",
             "url": "https://www.pexels.com/video/people-doing-the-cat-cow-pose-in-a-yoga-class-8480627/"},
    "dance": {"title": "Women Dancing All Together", "author": None, "licence": "Pexels licence", "url": None},
}
OUTPUT_CLIP = {"single": "squat", "class": "yoga", "dance": "dance"}   # clip each committed output came from
INPUT_CLIP = {"single": "stretch", "class": "yoga"}                    # clip behind fixtures/input/<name>/frames


@dataclass(frozen=True)
class Output:
    id: str
    dir: Path
    summary: dict
    frame_files: dict      # frame number -> JPEG path; empty when no matching pictures are stored


class Response(NamedTuple):
    status: int
    ctype: str
    body: bytes
    headers: tuple = ()


def json_response(status: int, obj) -> Response:
    return Response(status, "application/json", json.dumps(obj).encode())


def error(status: int, code: str | None = None, message: str | None = None, headers: tuple = ()) -> Response:
    code = code or STATUS_CODES.get(status, "internal")
    return Response(status, "application/json",
                    json.dumps({"error": message or MESSAGES[code], "code": code}).encode(), headers)


def _reject_constant(name):
    raise ValueError(name)


def load_json(path: Path):
    """Parse a JSON file; NaN and infinity are errors (browsers cannot read them)."""
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)


def stat_key(*paths: Path) -> tuple:
    """Changes whenever one of the files appears, disappears or is rewritten."""
    key = []
    for p in paths:
        try:
            st = p.stat()
            key.append((str(p), st.st_mtime_ns, st.st_size))
        except OSError:
            key.append((str(p), None, None))
    return tuple(key)


def output_dirs(root: Path) -> dict:
    """{id: dir} for every committed output that has pose3d.json and camera.json."""
    base = root / "fixtures" / "output"
    found = {name: base / name for name in CORE_OUTPUTS}
    scored = base / "scored"
    if scored.is_dir():
        for d in sorted(scored.iterdir()):
            if d.is_dir() and not d.is_symlink() and OUTPUT_ID.fullmatch("scored-" + d.name):
                found["scored-" + d.name] = d
    return {oid: d for oid, d in found.items() if (d / "pose3d.json").is_file() and (d / "camera.json").is_file()}


def frame_dirs(root: Path, oid: str, out_dir: Path) -> list:
    """Directories that may hold this output's pictures: its own, then the input clip it is named after."""
    names = [oid] if oid in CORE_OUTPUTS else oid.split("-")
    inputs = root / "fixtures" / "input"
    return [out_dir / "frames"] + [inputs / n / "frames" for n in names if (inputs / n).is_dir()]


def match_frames(pose_frames: list, frames_dir: Path) -> dict | None:
    """Frame number -> JPEG path when frames.json lists exactly the frames pose3d.json has, with the
    same times; None otherwise (a clip that only looks similar must not be shown beside the wrong skeleton)."""
    try:
        records = load_json(frames_dir / "frames.json")["frames"]
        by_frame = {r["frame"]: r for r in records}
        if len(records) != len(pose_frames) or len(by_frame) != len(records):
            return None
        out = {}
        for f in pose_frames:
            rec = by_frame.get(f["frame"])
            path = frames_dir / rec["file"]
            if abs(rec["t_ms"] - f["t_ms"]) > 1.0 or not FRAME_FILE.fullmatch(rec["file"]):
                return None
            if not path.is_file() or path.resolve().parent != frames_dir.resolve():
                return None
            out[f["frame"]] = path
        return out
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def read_output(root: Path, oid: str, out_dir: Path) -> Output | None:
    """Summarise one output dir, or None when its files are not usable JSON."""
    try:
        pose3d = load_json(out_dir / "pose3d.json")
        frames = pose3d["frames"]
        ids = {p["id"] for f in frames for p in f["people"]}
        if not all(type(f["frame"]) is int and isinstance(f["t_ms"], (int, float)) for f in frames):
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    files, clip = {}, None
    for d in frame_dirs(root, oid, out_dir):
        files = match_frames(frames, d)
        if files:
            clip = None if d == out_dir / "frames" else INPUT_CLIP.get(d.parent.name)   # the input clip's source
            break
    prov = pose3d.get("provenance") if isinstance(pose3d.get("provenance"), dict) else {}
    made = MADE_BY.get(oid, (None, None))
    summary = {
        "id": oid,
        "title": TITLES.get(oid, "Scored " + oid.removeprefix("scored-")),
        "mode": "class" if (out_dir / "tracks.json").is_file() or len(ids) > 1 else "single",
        "people": len(ids), "frames": len(frames),
        "backend": prov.get("backend") or made[0], "tracker": prov.get("tracker") or made[1],
        "source": CLIPS.get(clip or OUTPUT_CLIP.get(oid, "")),
        "has_pictures": bool(files),
    }
    return Output(oid, out_dir, summary, files or {})


def git_version(root: Path) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True,
                             text=True, timeout=5, check=True).stdout.strip()
        return out or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def normalize_base(base: str) -> str:
    inner = base.strip("/")
    return "/" + inner + "/" if inner else "/"


# ---- the app: routes without any socket ----------------------------------------------------------------

class App:
    def __init__(self, root: Path = ROOT, base: str = "/"):
        self.root = Path(root)
        self.base = normalize_base(base)
        self.version = git_version(self.root)
        self._outputs: dict = {}

    def handle(self, method: str, target: str) -> Response:
        path = target.split("?", 1)[0].split("#", 1)[0]
        is_api = path.startswith(self.base + "api/")
        if method not in ("GET", "HEAD"):
            resp = error(405, headers=(("Allow", "GET, HEAD"),))
        elif path == self.base.rstrip("/") and self.base != "/":
            resp = Response(301, "text/plain", b"", (("Location", self.base),))
        elif not path.startswith(self.base):
            resp = error(404)
        else:
            try:
                resp = self._route([unquote(p) for p in path[len(self.base):].split("/")])
            except Exception as exc:  # never a stack trace to the client; the class name only in the log
                print(f"error: {type(exc).__name__} while answering a request", file=sys.stderr)
                resp = error(500, "internal")
        return self._secured(resp, is_api)

    @staticmethod
    def _secured(resp: Response, is_api: bool) -> Response:
        extra = (("X-Content-Type-Options", "nosniff"), ("Content-Security-Policy", CSP),
                 ("Cache-Control", "no-store" if is_api else "no-cache"))
        return resp._replace(headers=resp.headers + extra)

    def _route(self, parts: list) -> Response:
        if len(parts) == 1 and parts[0] in STATIC:
            return self._file(self.root / "web" / STATIC[parts[0]])
        if parts == ["CONTRACT.md"]:
            return self._file(self.root / "CONTRACT.md")
        if parts[0] == "contracts" and len(parts) >= 2:
            return self._contract_file("/".join(parts[1:]))
        if parts[0] == "api" and len(parts) >= 2:
            return self._api(parts[1:])
        return error(404)

    def _api(self, rest: list) -> Response:
        if rest == ["health"]:
            return json_response(200, {"ok": True, "version": self.version, "gpu": None, "worker": "idle"})
        if rest == ["contract"]:
            return self._contract()
        if rest == ["outputs"]:
            return json_response(200, [o.summary for o in self._all_outputs().values()])
        if rest[0] == "outputs" and len(rest) == 2:
            return self._output_detail(rest[1])
        if rest[0] == "outputs" and len(rest) == 4 and rest[2] == "frames":
            return self._output_frame(rest[1], rest[3])
        return error(404)

    # -- static and contract files

    @staticmethod
    def _file(path: Path, ctype: str | None = None) -> Response:
        if not path.is_file():
            return error(404)
        return Response(200, ctype or TYPES[path.suffix], path.read_bytes())

    def _contract_file(self, rel: str) -> Response:
        table = {p.relative_to(self.root / "contracts").as_posix(): p
                 for p in (self.root / "contracts").rglob("*.json") if p.is_file() and not p.is_symlink()}
        return self._file(table[rel]) if rel in table else error(404)

    @staticmethod
    def _contract() -> Response:
        try:
            from part2 import contract  # lazy: the contract module is written beside this one
            return json_response(200, contract.contract_json())
        except Exception:
            return error(503, "contract_unavailable")

    # -- outputs

    def _all_outputs(self) -> dict:
        found = {}
        for oid, d in output_dirs(self.root).items():
            key = stat_key(d / "pose3d.json", d / "camera.json", d / "tracks.json",
                           *(fd / "frames.json" for fd in frame_dirs(self.root, oid, d)))
            cached = self._outputs.get(oid)
            if not cached or cached[0] != key:
                cached = (key, read_output(self.root, oid, d))   # parsed again only when a file changed
                self._outputs[oid] = cached
            if cached[1]:
                found[oid] = cached[1]
        return found

    def _output_detail(self, oid: str) -> Response:
        out = self._all_outputs().get(oid)
        if out is None:
            return error(404)
        try:
            pose3d, camera = load_json(out.dir / "pose3d.json"), load_json(out.dir / "camera.json")
            tracks = load_json(out.dir / "tracks.json") if (out.dir / "tracks.json").is_file() else None
        except (OSError, ValueError):
            return error(500, "unreadable")
        frames = [{"frame": f["frame"], "t_ms": f["t_ms"],
                   "url": f"api/outputs/{oid}/frames/{f['frame']}.jpg" if f["frame"] in out.frame_files else None}
                  for f in pose3d["frames"]]
        return json_response(200, {"output": out.summary, "pose3d": pose3d, "camera": camera,
                                   "tracks": tracks, "frames": frames})

    def _output_frame(self, oid: str, name: str) -> Response:
        out = self._all_outputs().get(oid)
        match = re.fullmatch(r"(0|[1-9][0-9]{0,8})\.jpg", name, re.ASCII)
        path = out.frame_files.get(int(match.group(1))) if out and match else None
        return self._file(path, TYPES[".jpg"]) if path else error(404)   # path comes from the table, not the URL


# ---- the HTTP layer ----------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "part2"
    timeout = 30                      # a slow client holds a thread for 30 s at most

    def version_string(self) -> str:
        return self.server_version

    def _answer(self) -> None:
        resp = self.server.app.handle(self.command, self.path)
        self._write(resp)

    def _write(self, resp: Response) -> None:
        if self.request_version == "HTTP/0.9":      # a bare "GET /path" or a bad request line: still send headers
            self.request_version = "HTTP/1.0"
        try:
            self.send_response(resp.status)
            self.send_header("Content-Type", resp.ctype)
            self.send_header("Content-Length", str(len(resp.body)))
            for key, value in resp.headers:
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(resp.body)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass

    def send_error(self, code, message=None, explain=None):
        code_name = STATUS_CODES.get(code, "bad_request" if 400 <= code < 500 else "internal")
        self._write(App._secured(error(code, code_name), False))

    do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _answer

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    app: App


def make_server(host: str = "127.0.0.1", port: int = 8722, base: str = "/", root: Path = ROOT) -> AppServer:
    server = AppServer((host, port), Handler)
    server.app = App(root, base)
    return server


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m part2.server", description="Part 2 web app (browse and contract pages).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8722)
    parser.add_argument("--base", default="/", help="URL prefix the app is served under, such as /simon-part-2/")
    args = parser.parse_args(argv)
    try:
        server = make_server(args.host, args.port, args.base)
    except OSError:
        print(f"server: port {args.port} on {args.host} is in use by another program", file=sys.stderr)
        return 1
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
    print(f"serving http://{args.host}:{args.port}{server.app.base}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
