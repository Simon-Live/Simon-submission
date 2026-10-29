"""`part2 stock` / `make stock-outputs`: the three Pexels follower takes for Part 5 (TICKET-028).

Spec: docs/specs/stock-takes.md (AC-T01 to AC-T05, error rows, edge cases). ADR-0005 (licences), ADR-0006.

    part2 stock [--clip pexels-5034562|pexels-5034577|pexels-8837221] [--backend gpu|cpu]

Per clip: download DOWNLOAD_URL into the cache (PART2_STOCK_DIR, else ~/.cache/simon-part-2/stock), read the
title and author from PAGE_URL at run time, read the file facts with ffprobe, sample frames at 10 fps with
`part2 frames`, run the one-person pipeline (no tracker; the gpu backend under the host GPU lock), check the
result as `make check-2-contract` does, then write fixtures/output/stock/pexels-<id>/{pose3d.json, camera.json,
SOURCE.md}. The video, the frames and the scratch run stay in the cache; nothing is written to the output dir
before every check passed. Exit 0 when every clip converted, 1 when one failed, 2 for an unknown backend.
"""
import contextlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = ROOT / "fixtures" / "output" / "stock"
CACHE_ENV = "PART2_STOCK_DIR"
PAGE_URL = "https://www.pexels.com/video/{id}/"
DOWNLOAD_URL = "https://www.pexels.com/download/video/{id}/"
LICENCE_URL = "https://www.pexels.com/license/"
USER_AGENT = "part2-stock/1.0"  # Pexels refuses urllib's default agent with HTTP 403
FPS = 10.0
CLIPS = {"pexels-5034562": "side", "pexels-5034577": "front", "pexels-8837221": "three-quarter"}
EXPECTED = "pexels-5034562"  # Part 5's expected take
NOT_STATED = "not stated on the page"
CHALLENGE = "challenges.cloudflare.com"  # a bot check page, not the video page
SIDECAR = "download.json"
OUTPUT_FILES = ("pose3d.json", "camera.json")


class StockError(RuntimeError):
    """A clip could not be converted; str() is the whole user-facing line (exit 1)."""


def clip_id(clip: str) -> str:
    return clip.removeprefix("pexels-")


def cache_dir() -> Path:
    return Path(os.environ.get(CACHE_ENV) or Path.home() / ".cache" / "simon-part-2" / "stock")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _open(url: str, timeout: float = 120):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout)


def _safe_name(url: str, clip: str) -> str:
    name = Path(urllib.parse.urlparse(url).path).name
    return name if re.fullmatch(r"[A-Za-z0-9._-]+", name or "") and not name.startswith(".") else f"{clip}.mp4"


def _cached(d: Path) -> dict | None:
    """The recorded download in `d` when its file is there with the recorded size and sha256, else None."""
    from part2.coco_set import sha256_file

    try:
        rec = json.loads((d / SIDECAR).read_text())
        video = d / rec["name"]
        ok = video.is_file() and video.stat().st_size == rec["size"] and sha256_file(video) == rec["sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return rec if ok else None


def download(clip: str, d: Path) -> dict:
    """The clip's video in `d` with its record {name, size, sha256, url, downloaded_utc}: the cached file when
    its size and sha256 match the record, else a fresh download. A failed download leaves no file behind."""
    from part2.coco_set import sha256_file

    rec = _cached(d)
    if rec:
        return {**rec, "reused": True}
    url = DOWNLOAD_URL.format(id=clip_id(clip))
    fail = f"stock: download of {clip} failed"
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".part-")
    try:
        with os.fdopen(fd, "wb") as out, _open(url) as resp:
            if not resp.headers.get_content_type().startswith("video/"):
                raise StockError(f"{fail}: not a video")
            name = _safe_name(resp.geturl(), clip)
            shutil.copyfileobj(resp, out, 1 << 20)
        os.replace(tmp, d / name)
    except urllib.error.HTTPError as e:
        raise StockError(f"{fail}: HTTP {e.code}") from None
    except (urllib.error.URLError, OSError) as e:
        raise StockError(f"{fail}: {getattr(e, 'reason', e)}") from None
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    video = d / name
    rec = {"name": name, "size": video.stat().st_size, "sha256": sha256_file(video), "url": url,
           "downloaded_utc": _utc_now()}
    (d / SIDECAR).write_text(json.dumps(rec, indent=1) + "\n")
    return {**rec, "reused": False}


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.meta, self.ld, self._in = None, {}, [], None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): v for k, v in attrs if v is not None}
        if tag == "title" and self.title is None:
            self._in, self.title = "title", ""
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in = "ld"
            self.ld.append("")
        elif tag == "meta" and "content" in a:
            key = (a.get("property") or a.get("name") or "").lower()
            if key:
                self.meta.setdefault(key, a["content"])

    def handle_endtag(self, tag):
        if tag in ("title", "script"):
            self._in = None

    def handle_data(self, data):
        if self._in == "title":
            self.title += data
        elif self._in == "ld":
            self.ld[-1] += data


def _clean(text) -> str | None:
    text = " ".join(str(text).split()) if isinstance(text, str) else ""
    return text or None


def _ld_author(node) -> str | None:
    """The first author or creator name in a JSON-LD tree (an object with a name, a list of them, or a string)."""
    if isinstance(node, list):
        return next((n for n in map(_ld_author, node) if n), None)
    if not isinstance(node, dict):
        return None
    for key in ("author", "creator"):
        who = node.get(key)
        for w in who if isinstance(who, list) else [who]:
            name = _clean(w.get("name")) if isinstance(w, dict) else _clean(w)
            if name:
                return name
    return next((n for n in map(_ld_author, node.values()) if n), None)


def parse_page(html: str) -> tuple[str | None, str | None]:
    """(title, author) as the page shows them: `<title>`, else og:title; the JSON-LD author or creator, else the
    author meta tag. None for what the page does not show."""
    p = _PageParser()
    p.feed(html)
    title = _clean(p.title) or _clean(p.meta.get("og:title"))
    author = None
    for block in p.ld:
        try:
            author = author or _ld_author(json.loads(block))
        except ValueError:
            continue
    return title, author or _clean(p.meta.get("author"))


def read_page(clip: str) -> dict:
    """{url, status, title, author, read_utc, note}: the page read now. A refusal or a bot check page leaves the
    title and author None and says why in `note`."""
    url = PAGE_URL.format(id=clip_id(clip))
    page = {"url": url, "status": None, "title": None, "author": None, "read_utc": _utc_now(), "note": None}
    try:
        with _open(url, timeout=60) as resp:
            page["status"], body = resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        page["status"], body = e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        page["note"] = f"not read ({getattr(e, 'reason', e)})"
        return page
    if page["status"] != 200 or CHALLENGE in body:
        page["note"] = f"HTTP {page['status']}" + (" (Cloudflare challenge page)" if CHALLENGE in body else "")
        return page
    page["title"], page["author"] = parse_page(body)
    return page


def _fps(rate: str) -> float:
    num, _, den = str(rate).partition("/")
    return float(num) / float(den or 1)


def probe(video: Path) -> dict:
    """{width, height, fps, duration_s} of the first video stream, as ffprobe reads them."""
    from part2.frames import _run

    doc = json.loads(_run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height,avg_frame_rate:format=duration", "-of", "json", str(video)]))
    streams = doc.get("streams") or []
    if not streams:
        raise StockError(f"stock: {video.name} has no video stream")
    s = streams[0]
    return {"width": int(s["width"]), "height": int(s["height"]), "fps": _fps(s["avg_frame_rate"]),
            "duration_s": float(doc["format"]["duration"])}


def num(x: float) -> str:
    """A number as SOURCE.md prints it: at most 3 decimals, no trailing zeros."""
    return f"{x:.3f}".rstrip("0").rstrip(".")


def _locked(backend):
    from part2 import outputs

    return outputs.gpu_guard() if backend.name == "gpu" else contextlib.nullcontext()


def _pose_extras(frames_dir: Path, backend, clip: str) -> dict:
    """cli._pose_extras (one-person mode: no tracker) plus the source clip in the provenance (AC-T04)."""
    from part2 import cli, frames, provenance

    extras = cli._pose_extras(frames.load_meta(frames_dir), False, backend)
    extras["provenance"].update({"source_clip": clip, "source_url": PAGE_URL.format(id=clip_id(clip))})
    provenance.validate(extras["provenance"])
    return extras


def run_pipeline(clip: str, backend, video: Path, work: Path) -> dict:
    """Frames at FPS, the one-person run and the contract checks in `work`; {frames, people, provenance}."""
    from part2 import canonical, contract, frames
    from part2.schema import ContractError

    shutil.rmtree(work, ignore_errors=True)
    recs = frames.ingest(video, work / "frames", FPS)
    with _locked(backend):
        doc = backend.estimate(work / "frames", work / "body3d.json")
    if not any(f["people"] for f in doc["frames"]):
        raise StockError(f"stock: no person in {clip}")
    try:
        canonical.write(work / "body3d.json", work, smooth=False, extras=_pose_extras(work / "frames", backend, clip))
    except ContractError as e:
        raise StockError(f"stock: {clip} breaks the contract at {e.path}: {e.msg}") from None
    for name, kind in zip(OUTPUT_FILES, ("pose3d", "camera")):
        problem = contract._file_problem(work / name, kind)
        if problem:
            raise StockError(f"stock: {clip} breaks the contract at {problem}")
    pose = json.loads((work / "pose3d.json").read_text())
    people = {p["id"] for f in pose["frames"] for p in f["people"]}
    return {"frames": len(recs), "people": len(people), "provenance": pose["provenance"]}


def source_md(clip: str, page: dict, dl: dict, facts: dict, run: dict) -> str:
    """SOURCE.md: every value fetched, read from the file or ffprobe, or taken from the run's provenance."""
    vid, angle, prov = clip_id(clip), CLIPS[clip], run["provenance"]
    title = f'"{page["title"]}"' if page["title"] else "title not available"
    status = f"HTTP {page['status']}" if page["note"] is None else page["note"]
    gap = "" if page["note"] is None else "; the title and author were not available"
    use = f"angle: {angle}" + ("; Part 5's expected take" if clip == EXPECTED else "")
    tracker = prov.get("tracker") or "none (one-person mode)"
    return "\n".join([
        f"# Stock take {clip}: source", "",
        f"Generated by `part2 stock --clip {clip}`. Do not edit by hand.", "",
        f"- **Clip:** {title}, Pexels video {vid}", f"  <{page['url']}>",
        f"- **Author:** {page['author'] or NOT_STATED}",
        f"- **Page:** read {page['read_utc'][:10]} (UTC), {status}{gap}.",
        f"- **Licence:** Pexels free licence, <{LICENCE_URL}>",
        f"- **Original file:** `{dl['name']}`, {dl['size']} bytes, {facts['width']}×{facts['height']}, "
        f"{num(facts['fps'])} fps, {num(facts['duration_s'])} s; downloaded {dl['downloaded_utc'][:10]} (UTC) from",
        f"  <{dl['url']}>; sha256 `{dl['sha256']}`. The video is not in this repo; re-download it from that URL.",
        f"- **Time range used:** 0 to {num(facts['duration_s'])} s (the whole clip).",
        f"- **Frames:** sampled at {num(FPS)} fps with `part2 frames`: {run['frames']} frames.",
        f"- **Produced by:** `part2 stock`, `part2_commit` `{prov.get('part2_commit')}`, backend {prov.get('backend')}, "
        f"tracker {tracker}, lifter {prov.get('lifter') or 'none'}.",
        f"- **Use:** follower take for Part 5 ({use}), decision D2 on Part 5 #18.", ""])


def convert(clip: str, backend, out_root: Path | None = None, cache: Path | None = None) -> dict:
    """One clip end to end; the output dir is written only after every check passed."""
    t0 = time.perf_counter()
    d = (cache or cache_dir()) / clip
    dl = download(clip, d)
    page = read_page(clip)
    facts = probe(d / dl["name"])
    run = run_pipeline(clip, backend, d / dl["name"], d / "run")
    out = Path(out_root or OUT_ROOT) / clip
    out.mkdir(parents=True, exist_ok=True)
    for name in OUTPUT_FILES:
        shutil.copyfile(d / "run" / name, out / name)
    (out / "SOURCE.md").write_text(source_md(clip, page, dl, facts, run))
    return {"clip": clip, "dir": str(out), "title": page["title"], "author": page["author"] or NOT_STATED,
            "page": page["note"] or f"HTTP {page['status']}", "sha256": dl["sha256"], "reused_download": dl["reused"],
            "time_range_s": [0, round(facts["duration_s"], 3)], "frames": run["frames"], "people": run["people"],
            "seconds": round(time.perf_counter() - t0, 1)}


def command(clip: str | None = None, backend_name: str | None = None, out_root: Path | None = None) -> int:
    from part2 import backends, lifters, outputs

    try:
        name = backends.resolve(backend_name)
        lifter = lifters.resolve() if name == "cpu" else None
    except (backends.UnknownBackend, lifters.UnknownLifter) as e:
        print(f"stock: {e}", file=sys.stderr)
        return 2
    backend, refusal = outputs.backend_for(name, lifter)
    if backend is None:
        print(refusal.replace("outputs: ", "stock: "), file=sys.stderr)
        return 1
    summary, failed = [], False
    for c in [clip] if clip else list(CLIPS):
        print(f"stock: {c} ({backend.name}) ...", file=sys.stderr, flush=True)
        try:
            summary.append(convert(c, backend, out_root))
        except StockError as e:
            failed = True
            summary.append({"clip": c, "error": str(e)})
            print(e, file=sys.stderr)
        except (RuntimeError, ValueError, OSError) as e:
            failed = True
            summary.append({"clip": c, "error": f"{type(e).__name__}: {e}"})
            print(f"stock: {c}: {e}", file=sys.stderr)
    print(json.dumps(summary, indent=2))
    return 1 if failed else 0
