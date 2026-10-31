"""`part2 stock` / `make stock-outputs`: the Pexels follower takes for Part 5 (TICKET-028).

Spec: docs/specs/stock-takes.md (AC-T01 to AC-T07, error rows, edge cases). ADR-0005 (licences), ADR-0006.

    part2 stock [--clip pexels-5034562|pexels-5034577|pexels-8837221|pexels-5034562-0to7s] [--backend gpu|cpu]

A take is a whole clip (`pexels-<id>`) or a cut of one listed in CUTS (`pexels-<id>-<start>to<end>s`, seconds).
Per take: download DOWNLOAD_URL into the cache (PART2_STOCK_DIR, else ~/.cache/simon-part-2/stock; a cut reuses
its clip's download), read the title and author from PAGE_URL at run time, read the file facts with ffprobe,
sample frames at 10 fps with `part2 frames` (a cut keeps the frames inside its time range), run the one-person
pipeline (no tracker; the gpu backend under the host GPU lock), check the result as `make check-2-contract` does,
then write fixtures/output/stock/<take>/{pose3d.json, camera.json, SOURCE.md}. The video, the frames and the
scratch run stay in the cache; nothing is written to the output dir before every check passed. Exit 0 when every
take converted, 1 when one failed, 2 for an unknown backend.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import time
import typing
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
EDGE_MS = 0.5  # a frame timed within this many ms of a cut's end is inside the cut (t_ms is rounded)


class StockError(RuntimeError):
    """A clip could not be converted; str() is the whole user-facing line (exit 1)."""


class Take(typing.NamedTuple):
    """A whole clip (`end` None) or the cut `start` to `end` seconds of it; `why` says why Part 5 asked for it."""
    clip: str
    start: float = 0.0
    end: float | None = None
    why: str | None = None


def clip_id(clip: str) -> str:
    return clip.removeprefix("pexels-")


def num(x: float) -> str:
    """A number as SOURCE.md prints it: at most 3 decimals, no trailing zeros."""
    return f"{x:.3f}".rstrip("0").rstrip(".")


def take_name(t: Take) -> str:
    """The take's folder name: `pexels-<id>` for a whole clip, `pexels-<id>-<start>to<end>s` for a cut."""
    return t.clip if t.end is None else f"{t.clip}-{num(t.start)}to{num(t.end)}s"


CUTS = (Take(EXPECTED, 0.0, 7.0, "its alignment cannot skip the bottle reach and the standing that follow the squats"),)
TAKES = {take_name(t): t for t in [*map(Take, CLIPS), *CUTS]}  # what `part2 stock` runs without --clip, in order


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
    from part2.hashing import sha256_file

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
    from part2.hashing import sha256_file

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


def check_range(take: str, duration: float) -> tuple[float, float]:
    """(start, end) in seconds of the take inside a clip of `duration` s; refuses a range the clip does not hold."""
    t = TAKES[take]
    start, end = t.start, duration if t.end is None else t.end
    if start < 0:
        raise StockError(f"stock: {take}: start {num(start)} s is before the clip")
    if end <= start:
        raise StockError(f"stock: {take}: end {num(end)} s is not after start {num(start)} s")
    if end > duration:
        raise StockError(f"stock: {take}: end {num(end)} s is past the clip ({num(duration)} s)")
    return start, end


def cut_frames(frames_dir: Path, take: str, start: float, end: float) -> list[dict]:
    """Keep the frames timed `start` to `end` s (both ends included) and drop the rest. The kept frames are
    renumbered from 0 with `t_ms` counted from the first of them, and `t0_pts_ms` moves to that frame's PTS, so
    `t0_pts_ms + t_ms` is still the file clock. Frame files are named by position, so renaming in order is safe."""
    from part2 import frames
    from part2.schema import write_json

    manifest = Path(frames_dir) / frames.MANIFEST
    doc = json.loads(manifest.read_text())
    keep = [r for r in doc["frames"] if start * 1000 - EDGE_MS <= r["t_ms"] <= end * 1000 + EDGE_MS]
    if not keep:
        raise StockError(f"stock: {take}: no frame between {num(start)} and {num(end)} s")
    kept = {r["file"] for r in keep}
    for r in doc["frames"]:
        if r["file"] not in kept:
            (frames_dir / r["file"]).unlink()
    t0, recs = keep[0]["t_ms"], []
    for i, r in enumerate(keep):
        name = f"{i:06d}{Path(r['file']).suffix}"
        if name != r["file"]:
            (frames_dir / r["file"]).rename(frames_dir / name)
        recs.append({"frame": i, "t_ms": round(r["t_ms"] - t0, 3), "file": name})
    if "t0_pts_ms" in doc:
        doc["t0_pts_ms"] = round(doc["t0_pts_ms"] + t0, 3)
    write_json(manifest, {**doc, "frames": recs}, indent=1)
    return recs


def _pose_extras(frames_dir: Path, backend, take: str, span: tuple[float, float], commit: str | None = None) -> dict:
    """output_steps.pose_extras (one-person mode: no tracker) plus the source clip in the provenance (AC-T04) and, for a
    cut, its time range in seconds (AC-T07). `commit` is the run's one part2_commit measure (see command())."""
    from part2 import frames, output_steps, provenance

    t = TAKES[take]
    extras = output_steps.pose_extras(frames.load_meta(frames_dir), False, backend, commit=commit)
    extras["provenance"].update({"source_clip": t.clip, "source_url": PAGE_URL.format(id=clip_id(t.clip))})
    if t.end is not None:
        extras["provenance"]["source_range_s"] = list(span)
    provenance.validate(extras["provenance"])
    return extras


def run_pipeline(take: str, backend, video: Path, work: Path, span: tuple[float, float],
                 commit: str | None = None) -> dict:
    """Frames at FPS (a cut keeps those inside `span`), the one-person run and the contract checks in `work`;
    {frames, people, provenance}. `commit` is the part2_commit to record (None: measured when the file is written)."""
    from part2 import canonical, contract, frames, output_steps
    from part2.schema import ContractError

    shutil.rmtree(work, ignore_errors=True)
    recs = frames.ingest(video, work / "frames", FPS)
    if TAKES[take].end is not None:
        recs = cut_frames(work / "frames", take, *span)
    with output_steps.gpu_locked(backend):
        doc = backend.estimate(work / "frames", work / "body3d.json")
    if not any(f["people"] for f in doc["frames"]):
        raise StockError(f"stock: no person in {take}")
    try:
        canonical.write(work / "body3d.json", work, smooth=False,
                        extras=_pose_extras(work / "frames", backend, take, span, commit))
    except ContractError as e:
        raise StockError(f"stock: {take} breaks the contract at {e.path}: {e.msg}") from None
    for name, kind in zip(OUTPUT_FILES, ("pose3d", "camera")):
        problem = contract._file_problem(work / name, kind)
        if problem:
            raise StockError(f"stock: {take} breaks the contract at {problem}")
    pose = json.loads((work / "pose3d.json").read_text())
    people = {p["id"] for f in pose["frames"] for p in f["people"]}
    return {"frames": len(recs), "people": len(people), "provenance": pose["provenance"]}


def _range_line(take: str, span: tuple[float, float], duration: float) -> str:
    t = TAKES[take]
    if t.end is None:
        return f"- **Time range used:** 0 to {num(duration)} s (the whole clip)."
    return (f"- **Time range used:** {num(span[0])} to {num(span[1])} s of the {num(duration)} s clip. This take is a "
            f"cut of {t.clip} made for Part 5: {t.why}.")


def source_md(take: str, page: dict, dl: dict, facts: dict, run: dict, span: tuple[float, float]) -> str:
    """SOURCE.md: every value fetched, read from the file or ffprobe, or taken from the run's provenance."""
    clip, cut, prov = TAKES[take].clip, TAKES[take].end is not None, run["provenance"]
    vid, angle = clip_id(clip), CLIPS[clip]
    title = f'"{page["title"]}"' if page["title"] else "title not available"
    status = f"HTTP {page['status']}" if page["note"] is None else page["note"]
    gap = "" if page["note"] is None else "; the title and author were not available"
    role = ("a cut of " if cut else "") + "Part 5's expected take"
    use = f"angle: {angle}" + (f"; {role}" if clip == EXPECTED else "")
    tracker = prov.get("tracker") or "none (one-person mode)"
    return "\n".join([
        f"# Stock take {take}: source", "",
        f"Generated by `part2 stock --clip {take}`. Do not edit by hand.", "",
        f"- **Clip:** {title}, Pexels video {vid}", f"  <{page['url']}>",
        f"- **Author:** {page['author'] or NOT_STATED}",
        f"- **Page:** read {page['read_utc'][:10]} (UTC), {status}{gap}.",
        f"- **Licence:** Pexels free licence, <{LICENCE_URL}>",
        f"- **Original file:** `{dl['name']}`, {dl['size']} bytes, {facts['width']}×{facts['height']}, "
        f"{num(facts['fps'])} fps, {num(facts['duration_s'])} s; downloaded {dl['downloaded_utc'][:10]} (UTC) from",
        f"  <{dl['url']}>; sha256 `{dl['sha256']}`. The video is not in this repo; re-download it from that URL.",
        _range_line(take, span, facts["duration_s"]),
        f"- **Frames:** sampled at {num(FPS)} fps with `part2 frames`: {run['frames']} frames.",
        f"- **Produced by:** `part2 stock`, `part2_commit` `{prov.get('part2_commit')}`, backend {prov.get('backend')}, "
        f"tracker {tracker}, lifter {prov.get('lifter') or 'none'}.",
        f"- **Use:** follower take for Part 5 ({use}), decision D2 on Part 5 #18.", ""])


def convert(take: str, backend, out_root: Path | None = None, cache: Path | None = None,
            commit: str | None = None) -> dict:
    """One take end to end; the output dir is written only after every check passed. `commit` is the part2_commit
    the run measured before it wrote any take (command() passes it); a direct caller gets it measured here, before
    this take writes anything."""
    from part2 import provenance

    t0 = time.perf_counter()
    commit = commit or provenance.part2_commit()
    clip = TAKES[take].clip
    d = (cache or cache_dir()) / clip
    dl = download(clip, d)
    page = read_page(clip)
    facts = probe(d / dl["name"])
    span = check_range(take, facts["duration_s"])
    work = d / ("run" if take == clip else f"run-{take}")
    run = run_pipeline(take, backend, d / dl["name"], work, span, commit)
    out = Path(out_root or OUT_ROOT) / take
    out.mkdir(parents=True, exist_ok=True)
    for name in OUTPUT_FILES:
        shutil.copyfile(work / name, out / name)
    (out / "SOURCE.md").write_text(source_md(take, page, dl, facts, run, span))
    return {"clip": take, "dir": str(out), "title": page["title"], "author": page["author"] or NOT_STATED,
            "page": page["note"] or f"HTTP {page['status']}", "sha256": dl["sha256"], "reused_download": dl["reused"],
            "time_range_s": [span[0], round(span[1], 3)], "frames": run["frames"], "people": run["people"],
            "seconds": round(time.perf_counter() - t0, 1)}


def command(clip: str | None = None, backend_name: str | None = None, out_root: Path | None = None) -> int:
    from part2 import backends, lifters, outputs, provenance

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
    commit = provenance.part2_commit()  # once, before any take rewrites the tracked outputs (R14)
    for c in [clip] if clip else list(TAKES):
        print(f"stock: {c} ({backend.name}) ...", file=sys.stderr, flush=True)
        try:
            summary.append(convert(c, backend, out_root, commit=commit))
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
