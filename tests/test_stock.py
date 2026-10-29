"""`part2 stock` (docs/specs/stock-takes.md: AC-T01 to AC-T05, the error rows, the edge cases).

No network: a local HTTP server on 127.0.0.1 serves a tiny generated clip (behind a redirect, as Pexels does) and
a fake Pexels page. The 3D backend is test_outputs.FakeBackend; everything after it (frames, canonical frame,
contract checks, doctor, SOURCE.md) is the real code."""
import hashlib
import http.server
import json
import shutil
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_frames import needs_ffmpeg
from test_outputs import FakeBackend

from part2 import cli, doctor, outputs, provenance, stock

CLIP = "pexels-5034562"
VIDEO_NAME = "5034562-tiny_64x48_10fps.mp4"
PAGE = """<!DOCTYPE html><html><head><title>
  Woman Doing Squats &amp; Lunges </title>
<meta property="og:title" content="og title, not used">
<script type="application/ld+json">{"@type": "VideoObject", "creator": {"@type": "Person", "name": "Test Author"}}</script>
</head><body>page</body></html>"""
CHALLENGE_PAGE = '<html><head><title>Just a moment...</title><script src="https://challenges.cloudflare.com/x.js"></script>'


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.hits.append(self.path)
        status, ctype, body, extra = self.server.routes.get(self.path, (404, "text/plain", b"missing", {}))
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def make_clip(path: Path, seconds=2, size="64x48", rate=10) -> bytes:
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size={size}:rate={rate}",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path.read_bytes()


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A fake Pexels on 127.0.0.1 for every clip id: the page, the download redirect and the video file."""
    video = make_clip(tmp_path / "clip.mp4")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.hits, server.routes = [], {}
    base = f"http://127.0.0.1:{server.server_address[1]}"
    for c in stock.CLIPS:
        vid = stock.clip_id(c)
        server.routes[f"/video/{vid}/"] = (200, "text/html; charset=utf-8", PAGE.encode(), {})
        server.routes[f"/download/video/{vid}/"] = (302, "text/html", b"", {"Location": f"/files/{vid}-tiny_64x48_10fps.mp4"})
        server.routes[f"/files/{vid}-tiny_64x48_10fps.mp4"] = (200, "video/mp4", video, {})
    monkeypatch.setattr(stock, "PAGE_URL", base + "/video/{id}/")
    monkeypatch.setattr(stock, "DOWNLOAD_URL", base + "/download/video/{id}/")
    monkeypatch.setenv(stock.CACHE_ENV, str(tmp_path / "cache"))
    lock = tmp_path / "gpu.lock"
    monkeypatch.setenv("PART2_GPU_LOCK", str(lock))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield SimpleNamespace(server=server, routes=server.routes, hits=server.hits, video=video, out=tmp_path / "out",
                          cache=tmp_path / "cache", lock=lock, tmp=tmp_path)
    server.shutdown()
    server.server_close()


def files_under(d: Path) -> list[Path]:
    return sorted(p for p in d.rglob("*") if p.is_file()) if d.exists() else []


def run_cli(site, monkeypatch, capsys, argv, backend=None):
    backend = backend or FakeBackend("gpu", lock=str(site.lock))
    monkeypatch.setattr(stock, "OUT_ROOT", site.out)
    monkeypatch.setattr(outputs, "backend_for", lambda name, lifter: (backend, None))
    code = cli.main(["stock", *argv])
    return code, capsys.readouterr()


# AC-T01, AC-T02, AC-T03, AC-T04
@needs_ffmpeg
def test_a_clip_becomes_the_three_files_with_fetched_facts(site):
    backend = FakeBackend("gpu", lock=str(site.lock))
    res = stock.convert(CLIP, backend, site.out)
    out = site.out / CLIP
    assert sorted(p.name for p in out.iterdir()) == ["SOURCE.md", "camera.json", "pose3d.json"]  # AC-T01, AC-T03
    assert doctor.command(out / "pose3d.json", "part3") == 0
    assert backend.locked == [True]  # the gpu backend ran under the host GPU lock
    prov = json.loads((out / "pose3d.json").read_text())["provenance"]
    assert prov["backend"] == "gpu" and "tracker" in prov and prov["tracker"] is None  # AC-T04: one-person, no tracker
    assert prov["source_clip"] == CLIP
    provenance.validate(prov)
    md = (out / "SOURCE.md").read_text()
    sha = hashlib.sha256(site.video).hexdigest()
    for fact in ['"Woman Doing Squats & Lunges", Pexels video 5034562', "- **Author:** Test Author",
                 f"`{VIDEO_NAME}`, {len(site.video)} bytes, 64×48, 10 fps, 2 s", f"sha256 `{sha}`",
                 "- **Time range used:** 0 to 2 s (the whole clip).", "sampled at 10 fps with `part2 frames`: 20 frames.",
                 f"`part2_commit` `{prov['part2_commit']}`, backend gpu, tracker none (one-person mode), lifter none.",
                 "(angle: side; Part 5's expected take), decision D2 on Part 5 #18", "HTTP 200.",
                 "<https://www.pexels.com/license/>"]:
        assert fact in md, fact
    assert not any(ch in md for ch in ("\u2014", "\u2013")) and " " + "-" + " " not in md
    assert res == {**res, "clip": CLIP, "title": "Woman Doing Squats & Lunges", "author": "Test Author", "sha256": sha,
                   "time_range_s": [0, 2.0], "frames": 20, "people": 1, "reused_download": False}
    # AC-T03: the video and the frames stay in the cache
    assert (site.cache / CLIP / VIDEO_NAME).read_bytes() == site.video
    assert list((site.cache / CLIP / "run" / "frames").glob("*.jpg"))
    assert not [p for p in files_under(site.out) if p.suffix.lower() in (".mp4", ".jpg", ".jpeg", ".png", ".webm")]


@needs_ffmpeg
def test_a_page_without_title_tag_or_author_falls_back_and_says_so(site):
    site.routes["/video/5034577/"] = (200, "text/html", b'<html><head><meta property="og:title" content="OG Title"></head>', {})
    stock.convert("pexels-5034577", FakeBackend("cpu"), site.out)
    md = (site.out / "pexels-5034577" / "SOURCE.md").read_text()
    assert '- **Clip:** "OG Title", Pexels video 5034577' in md
    assert "- **Author:** not stated on the page\n" in md
    assert "(angle: front), decision D2" in md and "expected take" not in md
    assert "backend cpu" in md


@needs_ffmpeg
def test_a_refused_page_leaves_title_and_author_unavailable(site):
    site.routes["/video/8837221/"] = (403, "text/html", CHALLENGE_PAGE.encode(), {})
    res = stock.convert("pexels-8837221", FakeBackend("cpu"), site.out)
    md = (site.out / "pexels-8837221" / "SOURCE.md").read_text()
    assert "- **Clip:** title not available, Pexels video 8837221" in md
    assert "- **Author:** not stated on the page\n" in md
    assert "HTTP 403 (Cloudflare challenge page); the title and author were not available." in md
    assert "Just a moment" not in md and res["title"] is None and "(angle: three-quarter)" in md


def test_parse_page_reads_only_what_the_page_shows():
    assert stock.parse_page(PAGE) == ("Woman Doing Squats & Lunges", "Test Author")
    ld_list = '<script type="application/ld+json">[{"@graph": [{"author": [{"name": " A  B "}]}]}]</script>'
    assert stock.parse_page("<title></title>" + ld_list) == (None, "A B")
    assert stock.parse_page('<meta name="author" content="Meta Name"><title>T</title>') == ("T", "Meta Name")
    assert stock.parse_page('<script type="application/ld+json">{broken</script><title>T</title>') == ("T", None)
    assert stock.parse_page("<html></html>") == (None, None)


# AC-T05 and the first error row
@needs_ffmpeg
@pytest.mark.parametrize("code", [403, 404, 500])
def test_an_http_error_exits_1_and_writes_nothing(site, monkeypatch, capsys, code):
    site.routes["/download/video/5034577/"] = (code, "text/plain", b"no", {})
    rc, io = run_cli(site, monkeypatch, capsys, ["--clip", "pexels-5034577", "--backend", "gpu"])
    assert rc == 1
    assert f"stock: download of pexels-5034577 failed: HTTP {code}\n" in io.err
    assert not site.out.exists() and files_under(site.cache) == []


@needs_ffmpeg
def test_html_instead_of_a_video_is_not_a_video(site, monkeypatch, capsys):
    site.routes["/files/5034577-tiny_64x48_10fps.mp4"] = (200, "text/html", b"<html>login</html>", {})
    rc, io = run_cli(site, monkeypatch, capsys, ["--clip", "pexels-5034577"])
    assert rc == 1 and "stock: download of pexels-5034577 failed: not a video\n" in io.err
    assert not site.out.exists() and files_under(site.cache) == []


class NobodyBackend(FakeBackend):
    def estimate(self, frames_dir, out_path, boxes=None):
        doc = super().estimate(frames_dir, out_path, boxes)
        for f in doc["frames"]:
            f["people"] = []
        out_path.write_text(json.dumps(doc))
        return doc


class NaNBackend(FakeBackend):
    def estimate(self, frames_dir, out_path, boxes=None):
        doc = super().estimate(frames_dir, out_path, boxes)
        doc["frames"][0]["people"][0]["kp3d_cam"]["nose"] = [float("nan")] * 3
        out_path.write_text(json.dumps(doc))
        return doc


@needs_ffmpeg
def test_no_person_exits_1(site, monkeypatch, capsys):
    rc, io = run_cli(site, monkeypatch, capsys, ["--clip", CLIP], backend=NobodyBackend("cpu"))
    assert rc == 1 and f"stock: no person in {CLIP}\n" in io.err and not site.out.exists()


@needs_ffmpeg
def test_an_output_that_breaks_the_contract_exits_1(site, monkeypatch, capsys):
    rc, io = run_cli(site, monkeypatch, capsys, ["--clip", CLIP], backend=NaNBackend("cpu"))
    assert rc == 1 and f"stock: {CLIP} breaks the contract at pose3d" in io.err and "nose" in io.err
    assert not site.out.exists()


@needs_ffmpeg
def test_a_contract_problem_found_after_writing_is_reported_with_its_path(site, monkeypatch, capsys):
    from part2 import contract

    monkeypatch.setattr(contract, "_file_problem", lambda path, kind: "camera.json: K: fake" if kind == "camera" else None)
    rc, io = run_cli(site, monkeypatch, capsys, ["--clip", CLIP], backend=FakeBackend("cpu"))
    assert rc == 1 and f"stock: {CLIP} breaks the contract at camera.json: K: fake\n" in io.err
    assert not site.out.exists()


# Edge: a cached download is reused only after its size and sha256 match
@needs_ffmpeg
def test_a_matching_cached_download_is_reused_and_a_corrupt_one_replaced(site):
    dl_path = "/download/video/5034562/"
    stock.convert(CLIP, FakeBackend("cpu"), site.out)
    assert site.hits.count(dl_path) == 1
    res = stock.convert(CLIP, FakeBackend("cpu"), site.out)
    assert site.hits.count(dl_path) == 1 and res["reused_download"] is True
    cached = site.cache / CLIP / VIDEO_NAME
    cached.write_bytes(site.video[:-10] + b"x" * 10)  # same size, other sha256
    res = stock.convert(CLIP, FakeBackend("cpu"), site.out)
    assert site.hits.count(dl_path) == 2 and res["reused_download"] is False
    assert cached.read_bytes() == site.video


# Edge: a clip longer than 60 s is kept whole
@needs_ffmpeg
def test_a_clip_longer_than_60_s_is_kept_whole(site):
    long = make_clip(site.tmp / "long.mp4", seconds=61, size="16x16", rate=1)
    site.routes["/files/5034562-tiny_64x48_10fps.mp4"] = (200, "video/mp4", long, {})
    res = stock.convert(CLIP, FakeBackend("cpu"), site.out)
    md = (site.out / CLIP / "SOURCE.md").read_text()
    assert "- **Time range used:** 0 to 61 s (the whole clip)." in md and ": 61 frames." in md
    assert res["frames"] == 61 and res["time_range_s"] == [0, 61.0]


def test_a_backend_that_cannot_run_exits_1_before_any_download(monkeypatch, capsys, tmp_path):
    hits = []
    monkeypatch.setattr(stock, "download", lambda *a: hits.append(a))
    monkeypatch.setattr(outputs, "backend_for", lambda name, lifter: (None, f"{outputs.NO_CUDA}\noutputs: no torch"))
    assert stock.command(CLIP, "gpu", tmp_path) == 1
    err = capsys.readouterr().err
    assert "stock: backend gpu needs CUDA (make setup-gpu)\nstock: no torch" in err and "outputs:" not in err
    assert hits == []


def test_no_clip_runs_all_three_in_order_and_one_failure_fails_the_run(monkeypatch, capsys):
    seen = []

    def fake_convert(clip, backend, out_root=None, cache=None):
        seen.append(clip)
        if clip == "pexels-5034577":
            raise stock.StockError("stock: download of pexels-5034577 failed: HTTP 429")
        return {"clip": clip}

    monkeypatch.setattr(stock, "convert", fake_convert)
    monkeypatch.setattr(outputs, "backend_for", lambda name, lifter: (FakeBackend("cpu"), None))
    assert cli.main(["stock", "--backend", "cpu"]) == 1
    io = capsys.readouterr()
    assert seen == list(stock.CLIPS) == ["pexels-5034562", "pexels-5034577", "pexels-8837221"]
    summary = json.loads(io.out)
    assert summary[1] == {"clip": "pexels-5034577", "error": "stock: download of pexels-5034577 failed: HTTP 429"}
    assert summary[2] == {"clip": "pexels-8837221"}


def test_unknown_clip_or_backend_is_a_usage_error(capsys):
    for argv in (["stock", "--clip", "pexels-1"], ["stock", "--backend", "tpu"]):
        with pytest.raises(SystemExit) as e:
            cli.main(argv)
        assert e.value.code == 2
    capsys.readouterr()


def test_the_cache_defaults_to_the_user_cache(monkeypatch):
    monkeypatch.delenv(stock.CACHE_ENV, raising=False)
    assert stock.cache_dir() == Path.home() / ".cache" / "simon-part-2" / "stock"
    assert stock.OUT_ROOT == Path(stock.__file__).resolve().parent.parent / "fixtures" / "output" / "stock"


@pytest.mark.skipif(not shutil.which("make"), reason="make not installed")
def test_make_stock_outputs_runs_the_stock_command():
    root = Path(stock.__file__).resolve().parent.parent
    out = subprocess.run(["make", "-n", "-C", str(root), "stock-outputs", "CLIP=pexels-8837221"], capture_output=True,
                         text=True, check=True).stdout
    assert "-m part2 stock --backend gpu --clip pexels-8837221" in out
    assert "--clip" not in subprocess.run(["make", "-n", "-C", str(root), "stock-outputs"], capture_output=True,
                                          text=True, check=True).stdout
