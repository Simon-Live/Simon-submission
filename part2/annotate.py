"""Local labelling tool (#6): a small web page served on localhost.

  part2 annotate joints --frames DIR --out labels_2d.json [--prefill body3d.json] [--count 20]
  part2 annotate ids    --frames DIR --out gt_tracks.json [--prefill tracks.json] [--every-s 1.0]

joints -> labels_2d.json: {frames: [{frame, view, joints: {<joint>: [u, v] | null}}]}
          (the format part2/eval_reproj.py scores; null = not visible)
ids    -> gt_tracks.json: {keyframes_only: true, frames: [{frame, people: [{id, bbox: [x, y, w, h]}]}]}
          (ground truth for the tracking eval, #13; ids are the labeller's stable person numbers)

Existing output is loaded, so labelling can stop and resume. Every save rewrites the file.
"""
import json
import math
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from part2 import frames as frames_mod
from part2.joints import CANONICAL

VIEWS = ["front", "side", "back", "other"]
PAGE = Path(__file__).with_name("annotate.html")
MAX_POST_BYTES = 10 * 1024 * 1024


def pick_frames(recs: list[dict], count: int) -> list[int]:
    """`count` frame numbers spread evenly over the clip."""
    if count >= len(recs):
        return [r["frame"] for r in recs]
    step = (len(recs) - 1) / (count - 1) if count > 1 else 0
    return [recs[round(i * step)]["frame"] for i in range(count)]


def keyframes(recs: list[dict], every_s: float) -> list[int]:
    """First frame at or after each `every_s` seconds."""
    out, next_t = [], 0.0
    for r in recs:
        if r["t_ms"] >= next_t * 1000 - 1e-6:
            out.append(r["frame"])
            next_t = r["t_ms"] / 1000 + every_s
    return out


def build_state(mode: str, frames_dir, out_path, prefill=None, count=20, every_s=1.0) -> dict:
    recs = frames_mod.load(frames_dir)
    targets = pick_frames(recs, count) if mode == "joints" else keyframes(recs, every_s)
    out_path = Path(out_path)
    saved = json.loads(out_path.read_text())["frames"] if out_path.exists() else []
    hints = {}
    if prefill:
        doc = json.loads(Path(prefill).read_text())
        for f in doc["frames"]:
            people = f.get("people", [])
            if mode == "joints" and people:
                p = max(people, key=lambda p: p["bbox"][2] * p["bbox"][3])
                hints[f["frame"]] = {j: p["kp2d"][j] for j in CANONICAL if j in p.get("kp2d", {})}
            elif mode == "ids":
                hints[f["frame"]] = [{"id": p["id"], "bbox": p["bbox"]} for p in people]
    if mode == "joints":
        # labelled frames stay in the list even if the pick would now skip them
        targets = sorted(set(targets) | {f["frame"] for f in saved})
    files = {r["frame"]: r["file"] for r in recs}
    return {"mode": mode, "joints": CANONICAL, "views": VIEWS,
            "frames": [{"frame": n, "file": files[n]} for n in targets],
            "saved": saved, "hints": {str(k): v for k, v in hints.items()}}


def _finite(values, what) -> list[float]:
    out = [float(v) for v in values]
    if not all(math.isfinite(v) for v in out):
        raise ValueError(f"{what}: numbers must be finite, got {values!r}")
    return out


def _int_id(v) -> int:
    if isinstance(v, bool) or not (isinstance(v, int) or (isinstance(v, float) and v.is_integer())
                                   or (isinstance(v, str) and v.isdigit())):
        raise ValueError(f"id must be a whole number, got {v!r}")
    return int(v)


def validate(mode: str, doc: dict, allowed_frames=None) -> dict:
    """Check a document posted by the page and return it in canonical form.
    allowed_frames: frame numbers being labelled; anything else is rejected."""
    out = []
    seen = set()
    for f in doc.get("frames", []):
        n = f["frame"]
        if not isinstance(n, int) or isinstance(n, bool) or n in seen:
            raise ValueError(f"bad or duplicate frame {n!r}")
        if allowed_frames is not None and n not in allowed_frames:
            raise ValueError(f"frame {n} is not one of the frames being labelled")
        seen.add(n)
        if mode == "joints":
            joints = f.get("joints", {})
            if set(joints) - set(CANONICAL):
                raise ValueError(f"frame {n}: unknown joints {sorted(set(joints) - set(CANONICAL))}")
            if f.get("view") not in VIEWS:
                raise ValueError(f"frame {n}: view must be one of {VIEWS}")
            clean = {}
            for j in CANONICAL:
                uv = joints.get(j)
                if uv is not None and not (isinstance(uv, list) and len(uv) == 2):
                    raise ValueError(f"frame {n}: {j} must be [u, v] or null")
                clean[j] = None if uv is None else [round(v, 1) for v in _finite(uv, f"frame {n} {j}")]
            if any(v is not None for v in clean.values()):
                out.append({"frame": n, "view": f["view"], "joints": clean})
        else:
            people, ids = [], set()
            for p in f.get("people", []):
                pid = _int_id(p["id"])
                if pid in ids:
                    raise ValueError(f"frame {n}: id {pid} used twice")
                ids.add(pid)
                if not (isinstance(p["bbox"], list) and len(p["bbox"]) == 4):
                    raise ValueError(f"frame {n}: bbox must be [x, y, w, h]")
                x, y, w, h = _finite(p["bbox"], f"frame {n} id {pid} bbox")
                if w <= 0 or h <= 0:
                    raise ValueError(f"frame {n}: empty box for id {pid}")
                people.append({"id": pid, "bbox": [round(x, 1), round(y, 1), round(w, 1), round(h, 1)]})
            out.append({"frame": n, "people": people})
    out.sort(key=lambda f: f["frame"])
    return {"frames": out} if mode == "joints" else {"keyframes_only": True, "frames": out}


def make_server(state: dict, frames_dir, out_path, port=0) -> ThreadingHTTPServer:
    """Localhost server. /api/* needs the per-run token (?t= on the page URL, sent back as
    X-Token) and a localhost Host header, so other sites open in the browser can't read or
    overwrite labels (CSRF / DNS rebinding)."""
    frames_dir, out_path = Path(frames_dir), Path(out_path)
    files = {fr["file"] for fr in state["frames"]}
    allowed = {fr["frame"] for fr in state["frames"]}
    lock = threading.Lock()
    token = secrets.token_urlsafe(16)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body: bytes, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _trusted(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            return host in ("127.0.0.1", "localhost") and secrets.compare_digest(self.headers.get("X-Token", ""), token)

        def do_GET(self):
            if self.path.startswith("/api/") and not self._trusted():
                return self._send(403, b'{"error": "forbidden"}')
            if self.path == "/" or self.path.startswith("/?"):
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/state":
                self._send(200, json.dumps(state).encode())
            elif self.path.startswith("/img/") and self.path[5:] in files:
                name = self.path[5:]
                ctype = "image/png" if name.endswith(".png") else "image/jpeg"
                self._send(200, (frames_dir / name).read_bytes(), ctype)
            else:
                self._send(404, b'{"error": "not found"}')

        def do_POST(self):
            if self.path != "/api/save":
                return self._send(404, b'{"error": "not found"}')
            if not self._trusted():
                return self._send(403, b'{"error": "forbidden"}')
            size = int(self.headers.get("Content-Length") or 0)
            if size > MAX_POST_BYTES:
                return self._send(413, b'{"error": "too large"}')
            try:
                doc = validate(state["mode"], json.loads(self.rfile.read(size)), allowed)
            except (ValueError, KeyError, TypeError, IndexError, AttributeError) as e:
                return self._send(400, json.dumps({"error": str(e)}).encode())
            with lock:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = out_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(doc, indent=1, allow_nan=False))
                tmp.replace(out_path)
                state["saved"] = doc["frames"]
            self._send(200, json.dumps({"saved": len(doc["frames"]), "path": str(out_path)}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.token = token
    return server


def serve(mode, frames_dir, out_path, prefill=None, count=20, every_s=1.0, port=8765, open_browser=True):
    state = build_state(mode, frames_dir, out_path, prefill, count, every_s)
    try:
        server = make_server(state, frames_dir, out_path, port)
    except OSError:  # port taken: let the OS pick a free one
        server = make_server(state, frames_dir, out_path, 0)
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={server.token}"
    print(f"labelling {len(state['frames'])} frames ({mode}) -> {out_path}\nopen {url}  (Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
