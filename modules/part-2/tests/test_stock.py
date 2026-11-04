"""`part2 stock` (docs/specs/stock-takes.md: AC-T01 to AC-T05, AC-T07, the error rows, the edge cases).

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
CUT = "pexels-5034562-0to7s"  # Part 5's cut of the expected take (AC-T07)
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


def test_no_clip_runs_every_take_in_order_and_one_failure_fails_the_run(monkeypatch, capsys):
    seen = []

    def fake_convert(clip, backend, out_root=None, cache=None, commit=None):
        seen.append(clip)
        if clip == "pexels-5034577":
            raise stock.StockError("stock: download of pexels-5034577 failed: HTTP 429")
        return {"clip": clip}

    monkeypatch.setattr(stock, "convert", fake_convert)
    monkeypatch.setattr(outputs, "backend_for", lambda name, lifter: (FakeBackend("cpu"), None))
    assert cli.main(["stock", "--backend", "cpu"]) == 1
    io = capsys.readouterr()
    assert seen == list(stock.TAKES) == ["pexels-5034562", "pexels-5034577", "pexels-8837221", CUT]
    summary = json.loads(io.out)
    assert summary[1] == {"clip": "pexels-5034577", "error": "stock: download of pexels-5034577 failed: HTTP 429"}
    assert summary[2:] == [{"clip": "pexels-8837221"}, {"clip": CUT}]


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
    cut = subprocess.run(["make", "-n", "-C", str(root), "stock-outputs", f"CLIP={CUT}"], capture_output=True,
                         text=True, check=True).stdout
    assert f"-m part2 stock --backend gpu --clip {CUT}" in cut
    assert "--clip" not in subprocess.run(["make", "-n", "-C", str(root), "stock-outputs"], capture_output=True,
                                          text=True, check=True).stdout


# AC-T07: cuts of a clip are takes of their own
def test_the_cut_for_part5_is_a_named_take_after_the_whole_clips():
    t = stock.TAKES[CUT]
    assert (t.clip, t.start, t.end) == (CLIP, 0.0, 7.0) and t.why
    assert stock.take_name(t) == CUT and stock.take_name(stock.Take(CLIP)) == CLIP
    assert stock.take_name(stock.Take(CLIP, 0.5, 6.25)) == "pexels-5034562-0.5to6.25s"
    assert list(stock.TAKES) == [*stock.CLIPS, CUT]
    assert [stock.TAKES[c] for c in stock.CLIPS] == [stock.Take(c) for c in stock.CLIPS]


def add_cut(monkeypatch, start, end, why="a test reason") -> str:
    t = stock.Take(CLIP, start, end, why)
    monkeypatch.setitem(stock.TAKES, stock.take_name(t), t)
    return stock.take_name(t)


@needs_ffmpeg
def test_a_cut_keeps_only_its_time_range_and_says_so(site, monkeypatch):
    whole = stock.convert(CLIP, FakeBackend("gpu", lock=str(site.lock)), site.out)
    t0_whole = json.loads((site.out / CLIP / "pose3d.json").read_text())["t0_pts_ms"]
    take = add_cut(monkeypatch, 0.5, 1.5)
    assert take == "pexels-5034562-0.5to1.5s"
    backend = FakeBackend("gpu", lock=str(site.lock))
    res = stock.convert(take, backend, site.out)
    out = site.out / take
    assert sorted(p.name for p in out.iterdir()) == ["SOURCE.md", "camera.json", "pose3d.json"]
    assert doctor.command(out / "pose3d.json", "part3") == 0 and backend.locked == [True]
    pose = json.loads((out / "pose3d.json").read_text())
    assert [f["frame"] for f in pose["frames"]] == list(range(11))  # 0.5 to 1.5 s at 10 fps, both ends
    assert [f["t_ms"] for f in pose["frames"]] == [i * 100.0 for i in range(11)]
    assert pose["t0_pts_ms"] == t0_whole + 500
    prov = pose["provenance"]
    assert prov["source_clip"] == CLIP and prov["source_range_s"] == [0.5, 1.5]
    provenance.validate(prov)
    md = (out / "SOURCE.md").read_text()
    sha = hashlib.sha256(site.video).hexdigest()
    for fact in [f"# Stock take {take}: source", f"Generated by `part2 stock --clip {take}`.",
                 "- **Time range used:** 0.5 to 1.5 s of the 2 s clip. This take is a cut of pexels-5034562 made "
                 "for Part 5: a test reason.", "sampled at 10 fps with `part2 frames`: 11 frames.",
                 f"`{VIDEO_NAME}`, {len(site.video)} bytes, 64×48, 10 fps, 2 s", f"sha256 `{sha}`",
                 "- **Licence:** Pexels free licence, <https://www.pexels.com/license/>",
                 f"`part2_commit` `{prov['part2_commit']}`, backend gpu, tracker none (one-person mode), lifter none.",
                 "(angle: side; a cut of Part 5's expected take), decision D2 on Part 5 #18"]:
        assert fact in md, fact
    assert not any(ch in md for ch in ("\u2014", "\u2013")) and " " + "-" + " " not in md
    assert res == {**res, "clip": take, "time_range_s": [0.5, 1.5], "frames": 11, "people": 1, "reused_download": True}
    assert site.hits.count("/download/video/5034562/") == 1  # the cut reused the clip's download
    # the whole take is untouched and its scratch run is its own
    assert whole["frames"] == 20 and len(json.loads((site.out / CLIP / "pose3d.json").read_text())["frames"]) == 20
    assert len(list((site.cache / CLIP / "run" / "frames").glob("*.jpg"))) == 20
    assert sorted(p.name for p in (site.cache / CLIP / f"run-{take}" / "frames").glob("*.jpg")) == \
        [f"{i:06d}.jpg" for i in range(11)]


@needs_ffmpeg
def test_a_cut_from_the_start_keeps_the_clip_clock(site, monkeypatch):
    take = add_cut(monkeypatch, 0.0, 0.95)
    res = stock.convert(take, FakeBackend("cpu"), site.out)
    pose = json.loads((site.out / take / "pose3d.json").read_text())
    assert res["frames"] == 10 and [f["t_ms"] for f in pose["frames"]] == [i * 100.0 for i in range(10)]
    assert "- **Time range used:** 0 to 0.95 s of the 2 s clip." in (site.out / take / "SOURCE.md").read_text()


@needs_ffmpeg
def test_a_cut_may_end_where_the_clip_ends(site, monkeypatch):
    take = add_cut(monkeypatch, 1.0, 2.0)
    assert stock.convert(take, FakeBackend("cpu"), site.out)["time_range_s"] == [1.0, 2.0]


@needs_ffmpeg
def test_the_part5_cut_past_a_short_clip_is_refused(site, monkeypatch, capsys):
    rc, io = run_cli(site, monkeypatch, capsys, ["--clip", CUT, "--backend", "gpu"])
    assert rc == 1 and f"stock: {CUT}: end 7 s is past the clip (2 s)\n" in io.err
    assert not site.out.exists()


@needs_ffmpeg
@pytest.mark.parametrize("start, end, message", [
    (1.5, 0.5, "end 0.5 s is not after start 1.5 s"),
    (1.0, 1.0, "end 1 s is not after start 1 s"),
    (-0.5, 1.0, "start -0.5 s is before the clip"),
    (0.0, 2.5, "end 2.5 s is past the clip (2 s)"),
    (0.01, 0.05, "no frame between 0.01 and 0.05 s"),
])
def test_a_range_the_clip_does_not_hold_exits_1_and_writes_nothing(site, monkeypatch, capsys, start, end, message):
    take = add_cut(monkeypatch, start, end)
    rc, io = run_cli(site, monkeypatch, capsys, ["--clip", take])
    assert rc == 1 and f"stock: {take}: {message}\n" in io.err
    assert not site.out.exists()


# ---- R14: the commit is measured once, before the run writes any take ----------------------------------------------------

SHA = "a" * 40
TWO_TAKES = ("pexels-5034562", "pexels-5034577")


def only_two_takes(monkeypatch):
    monkeypatch.setattr(stock, "TAKES", {t: stock.TAKES[t] for t in TWO_TAKES})


def stand_in_git(site, monkeypatch, dirty_before=False):
    """provenance's git call: HEAD is SHA; the tree reads dirty from the start (dirty_before) or once a take is
    written under the output dir, as the tracked fixtures/output/stock tree does on a real checkout."""
    def fake(*args):
        if args[0] == "rev-parse":
            return SHA
        return " M fixtures/output/stock/x/pose3d.json" if dirty_before or files_under(site.out) else ""

    monkeypatch.setattr(provenance, "_git", fake)


def commits_recorded(site):
    out = {}
    for take in TWO_TAKES:
        prov = json.loads((site.out / take / "pose3d.json").read_text())["provenance"]
        md = (site.out / take / "SOURCE.md").read_text()
        assert f"`part2_commit` `{prov['part2_commit']}`" in md  # SOURCE.md says what the file says
        out[take] = prov["part2_commit"]
    return out


@needs_ffmpeg
def test_every_take_records_the_commit_measured_before_the_first_take_was_written(site, monkeypatch, capsys):
    only_two_takes(monkeypatch)
    stand_in_git(site, monkeypatch)
    code, _ = run_cli(site, monkeypatch, capsys, [])
    assert code == 0
    assert provenance.part2_commit() == SHA + "+dirty"  # the control: the first take's files now make the tree read dirty
    assert commits_recorded(site) == {t: SHA for t in TWO_TAKES}


@needs_ffmpeg
def test_a_tree_dirty_before_the_run_is_recorded_as_dirty_in_every_take(site, monkeypatch, capsys):
    only_two_takes(monkeypatch)
    stand_in_git(site, monkeypatch, dirty_before=True)
    code, _ = run_cli(site, monkeypatch, capsys, [])
    assert code == 0
    assert commits_recorded(site) == {t: SHA + "+dirty" for t in TWO_TAKES}


def test_the_command_measures_the_commit_once_and_hands_it_to_every_take(monkeypatch, capsys):
    only_two_takes(monkeypatch)
    measured, seen = [], []
    monkeypatch.setattr(provenance, "part2_commit", lambda: measured.append(1) or SHA)
    monkeypatch.setattr(stock, "convert", lambda clip, backend, out_root=None, cache=None, commit=None:
                        seen.append((clip, commit)) or {"clip": clip})
    monkeypatch.setattr(outputs, "backend_for", lambda name, lifter: (FakeBackend("cpu"), None))
    assert cli.main(["stock", "--backend", "cpu"]) == 0
    assert measured == [1] and seen == [(t, SHA) for t in TWO_TAKES]
