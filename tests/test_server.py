"""part2/server.py and the pages (docs/specs/run-app.md: AC-A01, AC-A02, AC-A04 to AC-A12).

Most tests serve a small synthetic repo from tmp_path so every edge case is exact; the AC-A01 tests also
serve the committed outputs under fixtures/output/. Jobs run the fake runner of tests/test_jobs.py; job dirs,
the GPU lock and nvidia-smi are temp files or fakes, and the capability probe is a fake.
"""
import contextlib
import http.client
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import pytest

import part2.contract
from part2 import jobs, runapi, server
from part2.joints import CANONICAL
from test_jobs import FAKE_RUN, fake_command
from test_runapi import ALL_UP, form, jpeg

ROOT = Path(__file__).resolve().parent.parent
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"
CSP = "default-src 'self'; img-src 'self' data: blob:"
CONTRACT_DATA = {"schemas": [{"name": "pose3d", "version": "part2.pose3d/2026-10-28", "direction": "produces",
                              "file": "contracts/pose3d.schema.json"}],
                 "compatibility": [{"producer_file": "pose3d.json", "consumer": "Part 3", "result": "works"}]}


# ---- helpers -----------------------------------------------------------------------------------------

def write_output(d: Path, ids=(0,), n=3, step=200.0, provenance=None, tracks=False):
    d.mkdir(parents=True)
    joints = {name: {"x": 0.01 * k, "y": 0.1 * k, "z": 0.0, "conf": 1.0} for k, name in enumerate(CANONICAL)}
    frames = [{"frame": f, "t_ms": f * step, "people": [{"id": i, "joints": joints} for i in ids]} for f in range(n)]
    (d / "pose3d.json").write_text(json.dumps({"frames": frames, **({"provenance": provenance} if provenance else {})}))
    eye = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    (d / "camera.json").write_text(json.dumps({"K": eye, "image_size": [1280, 720], "frames": [
        {"frame": f, "people": [{"id": i, "R": eye, "t": [0, 0, 3]} for i in ids]} for f in range(n)]}))
    if tracks:
        (d / "tracks.json").write_text(json.dumps({"frames": [
            {"frame": f, "people": [{"id": i, "bbox": [0, 0, 1, 1], "confidence": 1.0} for i in ids]} for f in range(n)]}))


def write_frames(d: Path, n=3, step=200.0, name=lambda f: f"{f:06d}.jpg"):
    d.mkdir(parents=True)
    for f in range(n):
        (d / name(f)).write_bytes(JPEG + str(f).encode())
    (d / "frames.json").write_text(json.dumps({"source": "/somewhere/clip.mp4", "frames": [
        {"frame": f, "t_ms": f * step, "file": name(f)} for f in range(n)]}))


@pytest.fixture
def repo(tmp_path):
    """A small repo root: pages, three outputs (class with matching pictures), a scored output, contracts."""
    root = tmp_path / "repo"
    web = root / "web"
    web.mkdir(parents=True)
    for name in ("index.html", "contract.html"):
        (web / name).write_text(f"<!doctype html><title>{name}</title>")
    (web / "browse.js").write_text("// browse")
    (web / "viewer.js").write_text("// viewer")
    (web / "style.css").write_text("body{}")
    (web / "icon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (web / "unlisted.html").write_text("NOT-IN-THE-TABLE")
    out = root / "fixtures" / "output"
    write_output(out / "single", n=4, step=100.0)
    write_output(out / "class", ids=(0, 1, 2), tracks=True)
    write_output(out / "scored" / "cpu-single", n=4, step=100.0, provenance={"backend": "cpu", "tracker": None})
    write_frames(root / "fixtures" / "input" / "class" / "frames")
    write_frames(root / "fixtures" / "input" / "single" / "frames", n=4, step=100.0)
    (root / "contracts" / "consumers").mkdir(parents=True)
    (root / "contracts" / "pose3d.schema.json").write_text('{"title": "pose3d"}')
    (root / "contracts" / "consumers" / "part3.json").write_text('{"title": "part3"}')
    (root / "contracts" / "notes.txt").write_text("not json")
    (root / "CONTRACT.md").write_text("# Contract\n\nText.\n")
    (root / "private.txt").write_text("PRIVATE-DATA")
    (tmp_path / "secret.txt").write_text("TOP-SECRET")
    return root


@pytest.fixture(autouse=True)
def isolated_jobs(tmp_path_factory, monkeypatch):
    """Job dirs and the GPU lock in temp dirs; no nvidia-smi (health says gpu null) unless a test fakes one."""
    monkeypatch.setenv("PART2_JOBS_DIR", str(tmp_path_factory.mktemp("jobs")))
    monkeypatch.setenv("PART2_GPU_LOCK", str(tmp_path_factory.mktemp("lock") / "gpu.lock"))
    monkeypatch.setenv("PART2_NVIDIA_SMI", str(tmp_path_factory.mktemp("nosmi") / "nvidia-smi"))
    monkeypatch.setenv("PYTHONPATH", str(ROOT))


FAST = jobs.Settings(gpu_poll_s=0.05, poll_s=0.05, kill_grace_s=2.0, gpu_wait_s=0.5)


@contextlib.contextmanager
def running(root: Path, base: str = "/", probe=None, **kw):
    """A server on a free port with its own temp job dir and a fake capability probe (all available)."""
    with tempfile.TemporaryDirectory() as jobs_dir:
        caps = runapi.Capabilities(probe=probe or (lambda: ALL_UP))
        srv = server.make_server("127.0.0.1", 0, base, root, jobs_dir=kw.pop("jobs_dir", Path(jobs_dir)),
                                 caps=caps, settings=kw.pop("settings", FAST), **kw)
        thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        try:
            yield srv.server_address[1]
        finally:
            srv.shutdown()
            srv.server_close()
            thread.join(5)


@pytest.fixture
def port(repo):
    with running(repo) as p:
        yield p


def fetch(port, path, method="GET", body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        r = conn.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
    finally:
        conn.close()


def get_json(port, path):
    status, headers, body = fetch(port, path)
    return status, json.loads(body)


# ---- health, pages, headers ---------------------------------------------------------------------------

def test_health_answers_ok_with_version_gpu_and_worker(port):
    status, doc = get_json(port, "/api/health")
    assert status == 200
    assert doc["ok"] is True and isinstance(doc["version"], str) and doc["version"]
    assert doc["gpu"] is None and doc["worker"] == "idle"


def fake_smi(tmp_path: Path, monkeypatch, line: str = "20480, 32768") -> None:
    script = tmp_path / "nvidia-smi"
    script.write_text(f"#!/bin/sh\necho '{line}'\n")
    script.chmod(0o755)
    monkeypatch.setenv("PART2_NVIDIA_SMI", str(script))


def test_health_names_free_gpu_memory_when_nvidia_smi_answers(repo, tmp_path, monkeypatch):
    fake_smi(tmp_path, monkeypatch)
    with running(repo) as p:
        assert get_json(p, "/api/health")[1]["gpu"] == {"free_gib": 20.0, "total_gib": 32.0}


def test_pages_and_assets_come_from_the_fixed_table(port):
    expect = {"/": "text/html", "/index.html": "text/html", "/contract.html": "text/html",
              "/browse.js": "text/javascript", "/viewer.js": "text/javascript", "/style.css": "text/css",
              "/icon.svg": "image/svg+xml", "/CONTRACT.md": "text/markdown"}
    for path, ctype in expect.items():
        status, headers, body = fetch(port, path)
        assert status == 200 and headers["content-type"].startswith(ctype), path
        assert body
    assert fetch(port, "/")[2] == fetch(port, "/index.html")[2]


def test_files_not_in_the_table_are_404_even_when_they_exist(port):
    for path in ("/unlisted.html", "/run.html", "/run.js", "/overlay.js", "/web/index.html", "/index.html/"):
        assert fetch(port, path)[0] == 404, path


def test_run_page_files_are_served_once_they_exist(repo):
    (repo / "web" / "run.html").write_text("<title>run</title>")
    with running(repo) as p:
        assert fetch(p, "/run.html")[0] == 200


def test_every_response_carries_nosniff_and_a_csp_and_api_is_no_store(port):
    paths = ["/", "/index.html", "/api/health", "/api/outputs", "/api/outputs/class", "/api/outputs/nope",
             "/api/outputs/class/frames/0.jpg", "/api/contract", "/nope", "/api/nope", "/contracts/pose3d.schema.json",
             "/CONTRACT.md", "/icon.svg"]
    for path in paths:
        status, headers, _ = fetch(port, path)
        assert headers["x-content-type-options"] == "nosniff", path
        assert headers["content-security-policy"] == CSP, path
        if path.startswith("/api/"):
            assert headers["cache-control"] == "no-store", path
    for method in ("POST", "DELETE", "HEAD"):
        _, headers, _ = fetch(port, "/api/health", method)
        assert headers["x-content-type-options"] == "nosniff" and headers["cache-control"] == "no-store"


def test_query_string_and_fragment_are_ignored(port):
    assert fetch(port, "/api/health?x=1")[0] == 200
    assert fetch(port, "/index.html?v=3#top")[0] == 200


def test_head_has_the_headers_and_length_of_get_but_no_body(port):
    for path in ("/api/health", "/api/outputs/class", "/index.html", "/api/outputs/class/frames/1.jpg"):
        _, h_get, body = fetch(port, path)
        status, h_head, head_body = fetch(port, path, "HEAD")
        assert status == 200 and head_body == b""
        assert h_head["content-length"] == h_get["content-length"] == str(len(body))
        assert h_head["content-type"] == h_get["content-type"]


# ---- methods ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def test_other_methods_are_405_with_a_plain_json_error(port, method):
    for path in ("/api/health", "/", "/api/capabilities", "/api/jobs/0123456789ab", "/nope"):
        status, headers, body = fetch(port, path, method, body=b"abc" if method in ("POST", "PUT") else None)
        assert status == 405, (method, path)
        assert headers["allow"] == "GET, HEAD" and headers["x-content-type-options"] == "nosniff"
        assert json.loads(body) == {"error": "This address accepts GET and HEAD only.", "code": "method_not_allowed"}


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
def test_the_job_routes_name_their_own_methods(port, method):
    status, headers, body = fetch(port, "/api/jobs", method, body=b"x" if method != "DELETE" else None)
    assert status == 405 and headers["allow"] == "GET, HEAD, POST"
    assert json.loads(body) == {"error": "This address accepts GET, HEAD and POST only.", "code": "method_not_allowed"}
    for m in ("GET", "HEAD", method):
        status, headers, _ = fetch(port, "/api/jobs/0123456789ab/cancel", m)
        assert status == 405 and headers["allow"] == "POST" and headers["x-content-type-options"] == "nosniff"


def test_an_unknown_method_is_a_json_error_not_an_html_page(port):
    status, headers, body = fetch(port, "/api/health", "TRACE")
    assert status == 501 and headers["content-type"] == "application/json"
    assert set(json.loads(body)) == {"error", "code"} and headers["x-content-type-options"] == "nosniff"


def raw_exchange(port, request: bytes) -> tuple:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(request)
        data = b""
        try:
            while chunk := s.recv(4096):
                data += chunk
        except ConnectionResetError:  # the server closes with part of an oversize request unread: TCP resets after the reply
            pass
    head, _, body = data.partition(b"\r\n\r\n")
    return head.decode(), body


def test_protocol_errors_are_json_with_the_security_headers(port):
    head, body = raw_exchange(port, b"GET /index.html HTTP/9.9\r\n\r\n")
    assert " 505 " in head.split("\r\n")[0] and "X-Content-Type-Options: nosniff" in head
    assert set(json.loads(body)) == {"error", "code"}
    head, body = raw_exchange(port, b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\n\r\n")
    assert " 414 " in head.split("\r\n")[0] and json.loads(body)["code"] == "bad_request"
    head, body = raw_exchange(port, b"GET\r\n\r\n")
    assert " 400 " in head.split("\r\n")[0] and "X-Content-Type-Options: nosniff" in head
    head, body = raw_exchange(port, b"GET /api/health\r\n\r\n")             # a bare HTTP/0.9 request
    assert " 200 " in head.split("\r\n")[0] and "Cache-Control: no-store" in head and json.loads(body)["ok"] is True


# ---- traversal and unknown paths (AC-A11) -------------------------------------------------------------

TRAVERSAL = [
    "/..%2f..%2fsecret.txt", "/%2e%2e/%2e%2e/secret.txt", "/%2e%2e%2fprivate.txt", "/..%2fprivate.txt",
    "/%252e%252e%252fprivate.txt", "/../private.txt", "/web/../private.txt", "/..\\private.txt", "/%5c..%5cprivate.txt",
    "/private.txt", "/fixtures/output/single/pose3d.json", "/part2/server.py", "/.git/config", "//private.txt",
    "/contracts/..%2fprivate.txt", "/contracts/../private.txt", "/contracts/consumers/..%2f..%2fprivate.txt",
    "/contracts/%2e%2e/private.txt", "/contracts/notes.txt", "/contracts/", "/contracts",
    "/api/outputs/..%2fsingle", "/api/outputs/%2e%2e", "/api/outputs/..%2f..%2fprivate.txt",
    "/api/outputs/single/frames/..%2f..%2f..%2fprivate.txt", "/api/outputs/class/frames/..%2f000000.jpg",
    "/api/outputs/class%2fframes/0.jpg", "/api/outputs/class/frames/%2e%2e%2f0.jpg", "/api/outputs/class/frames/0.jpg%00.png",
    "/api/outputs/class/frames/000000.jpg", "/api/outputs/class/frames/00.jpg", "/api/outputs/class/frames/0.JPG",
    "/api/outputs/class/frames/", "/api/outputs/class/frames", "/api/outputs/class/pose3d.json",
    "/api/outputs/class/extra/0/1", "/api/outputs/", "/api/", "/api", "/api/health/extra", "/api/secret",
    "/%00", "/index.html%00", "/CONTRACT.md/", "/%C0%AE%C0%AE/private.txt",
    "http://127.0.0.1/../private.txt", "/simon-part-2/api/health",
]


@pytest.mark.parametrize("path", TRAVERSAL)
def test_traversal_and_unknown_paths_are_404_and_never_return_file_content(port, path):
    status, _, body = fetch(port, path)
    assert status == 404, path
    assert json.loads(body) == {"error": "Not found.", "code": "not_found"}
    for secret in (b"TOP-SECRET", b"PRIVATE-DATA", b"root:", b"NOT-IN-THE-TABLE", b"def ", JPEG):
        assert secret not in body


def test_error_bodies_name_no_traceback_class_or_path(port, repo):
    cases = [("GET", "/nope"), ("GET", "/api/outputs/nope"), ("POST", "/api/health"), ("GET", "/api/outputs/class/frames/99.jpg"),
             ("TRACE", "/"), ("GET", "/api/jobs/0123456789ab"), ("POST", "/api/jobs/0123456789ab/cancel"),
             ("GET", "/api/jobs/cancel"), ("POST", "/api/jobs")] + [("GET", p) for p in TRAVERSAL[:12]]
    for method, path in cases:
        _, _, body = fetch(port, path, method)
        text = body.decode()
        assert set(json.loads(text)) == {"error", "code"}
        assert not re.search(r"Traceback|Error\b|Exception|\.py\b", text), text
        assert str(repo) not in text and "/home" not in text and "/tmp" not in text


def test_a_failing_handler_is_a_plain_500_without_details(repo, monkeypatch, capsys):
    def boom(self, rest):
        raise RuntimeError(f"disk exploded at {repo}")
    monkeypatch.setattr(server.App, "_api", boom)
    with running(repo) as p:
        status, _, body = fetch(p, "/api/health")
    assert status == 500
    assert json.loads(body) == {"error": "The server could not answer this request.", "code": "internal"}
    err = capsys.readouterr().err
    assert "RuntimeError" in err and str(repo) not in err


# ---- base path ----------------------------------------------------------------------------------------

def test_normalize_base():
    assert [server.normalize_base(b) for b in ("", "/", "//", "simon-part-2", "/simon-part-2/", "/a/b")] == [
        "/", "/", "/", "/simon-part-2/", "/simon-part-2/", "/a/b/"]


def test_the_app_runs_under_a_prefix(repo):
    with running(repo, "/simon-part-2/") as p:
        assert fetch(p, "/simon-part-2/")[0] == 200
        assert fetch(p, "/simon-part-2/index.html")[0] == 200
        assert get_json(p, "/simon-part-2/api/health")[1]["ok"] is True
        assert get_json(p, "/simon-part-2/api/outputs")[0] == 200
        for path in ("/", "/index.html", "/api/health", "/other/api/health", "/simon-part-2/../api/health",
                     "/simon-part-2x/", "/simon-part-2/%2e%2e/private.txt"):
            assert fetch(p, path)[0] == 404, path
        status, headers, _ = fetch(p, "/simon-part-2")
        assert status == 301 and headers["location"] == "/simon-part-2/"
        assert fetch(p, "/simon-part-2/api/health", "POST")[0] == 405
        status, headers, _ = fetch(p, "/simon-part-2/api/nope")
        assert status == 404 and headers["cache-control"] == "no-store"


# ---- outputs (AC-A01) ---------------------------------------------------------------------------------

def test_outputs_list_the_committed_outputs_and_scored_ones(port):
    status, rows = get_json(port, "/api/outputs")
    assert status == 200
    assert [r["id"] for r in rows] == ["single", "class", "scored-cpu-single"]
    by_id = {r["id"]: r for r in rows}
    assert by_id["class"]["mode"] == "class" and by_id["class"]["people"] == 3 and by_id["class"]["frames"] == 3
    assert by_id["single"]["mode"] == "single" and by_id["single"]["people"] == 1 and by_id["single"]["frames"] == 4
    assert all({"id", "title", "mode", "people", "frames", "backend", "tracker", "source"} <= set(r) for r in rows)


def test_provenance_names_backend_and_tracker_when_present(port):
    _, rows = get_json(port, "/api/outputs")
    scored = next(r for r in rows if r["id"] == "scored-cpu-single")
    assert scored["backend"] == "cpu" and scored["tracker"] is None and scored["title"] == "Scored cpu-single"
    single = next(r for r in rows if r["id"] == "single")
    assert single["backend"] and single["tracker"] is None
    # its frames match fixtures/input/single, so the clip is that input's clip
    assert single["source"]["title"] == "Side View of a Woman Stretching in a Health Club"


def test_output_detail_has_pose3d_camera_tracks_and_frames(port):
    status, doc = get_json(port, "/api/outputs/class")
    assert status == 200
    assert set(doc) == {"output", "pose3d", "camera", "tracks", "frames"}
    assert len(doc["pose3d"]["frames"]) == 3 and doc["camera"]["image_size"] == [1280, 720]
    assert doc["tracks"]["frames"][0]["people"][0]["id"] == 0
    assert doc["frames"] == [{"frame": f, "t_ms": f * 200.0, "url": f"api/outputs/class/frames/{f}.jpg"} for f in range(3)]
    assert doc["output"]["has_pictures"] is True
    assert get_json(port, "/api/outputs/single")[1]["tracks"] is None


def test_an_unknown_output_is_404(port):
    status, doc = get_json(port, "/api/outputs/nope")
    assert status == 404 and doc["code"] == "not_found"
    assert get_json(port, "/api/outputs/dance")[0] == 404          # absent from this repo


def test_frames_are_served_as_jpeg_from_the_matching_input_clip(port):
    status, headers, body = fetch(port, "/api/outputs/class/frames/1.jpg")
    assert status == 200 and headers["content-type"] == "image/jpeg" and body == JPEG + b"1"
    assert fetch(port, "/api/outputs/class/frames/3.jpg")[0] == 404
    assert fetch(port, "/api/outputs/class/frames/x.jpg")[0] == 404
    _, scored = get_json(port, "/api/outputs/scored-cpu-single")
    assert scored["output"]["has_pictures"] is True and scored["frames"][3]["url"].endswith("/frames/3.jpg")


def test_an_output_without_matching_pictures_has_null_urls_and_404_frames(repo):
    (repo / "fixtures" / "input" / "single" / "frames" / "frames.json").write_text(json.dumps({"frames": [
        {"frame": f, "t_ms": f * 99.0, "file": f"{f:06d}.jpg"} for f in range(4)]}))     # times differ
    with running(repo) as p:
        _, doc = get_json(p, "/api/outputs/single")
        assert doc["output"]["has_pictures"] is False and [f["url"] for f in doc["frames"]] == [None] * 4
        assert fetch(p, "/api/outputs/single/frames/0.jpg")[0] == 404


def test_pictures_must_match_frame_count_numbers_and_file_names(repo):
    frames_json = repo / "fixtures" / "input" / "class" / "frames" / "frames.json"
    good = json.loads(frames_json.read_text())

    def has_pictures(doc):
        frames_json.write_text(json.dumps(doc))
        with running(repo) as p:
            return get_json(p, "/api/outputs/class")[1]["output"]["has_pictures"]

    assert has_pictures(good) is True
    assert has_pictures({"frames": good["frames"][:2]}) is False                                   # too few
    assert has_pictures({"frames": good["frames"] + [{"frame": 3, "t_ms": 600.0, "file": "000000.jpg"}]}) is False
    assert has_pictures({"frames": [{**r, "frame": r["frame"] + 1} for r in good["frames"]]}) is False
    assert has_pictures({"frames": [{**r, "file": "../../../private.txt"} for r in good["frames"]]}) is False
    assert has_pictures({"frames": [{**r, "file": "missing.jpg"} for r in good["frames"]]}) is False
    assert has_pictures({"frames": [{**r, "file": "000000.png"} for r in good["frames"]]}) is False
    assert has_pictures({"frames": [{"frame": 0}]}) is False
    frames_json.write_text("not json")
    with running(repo) as p:
        assert get_json(p, "/api/outputs/class")[1]["output"]["has_pictures"] is False


def test_a_picture_that_resolves_outside_the_frames_dir_is_never_served(repo):
    link = repo / "fixtures" / "input" / "class" / "frames" / "000001.jpg"
    link.unlink()
    link.symlink_to(repo / "private.txt")
    with running(repo) as p:
        assert get_json(p, "/api/outputs/class")[1]["output"]["has_pictures"] is False
        status, _, body = fetch(p, "/api/outputs/class/frames/1.jpg")
        assert status == 404 and b"PRIVATE-DATA" not in body


def test_unusable_outputs_are_left_out(repo):
    out = repo / "fixtures" / "output"
    (out / "single" / "pose3d.json").write_text("{ not json")
    (out / "class" / "camera.json").unlink()
    write_output(out / "dance", n=2)
    (out / "dance" / "pose3d.json").write_text('{"frames": [{"frame": 0, "t_ms": NaN, "people": []}]}')
    write_output(out / "scored" / "Bad Name", n=2)
    write_output(out / "scored" / "ok_name", n=2)
    with running(repo) as p:
        assert [r["id"] for r in get_json(p, "/api/outputs")[1]] == ["scored-cpu-single", "scored-ok_name"]
        assert get_json(p, "/api/outputs/single")[0] == 404


def test_an_output_with_odd_frame_records_is_left_out(repo):
    out = repo / "fixtures" / "output"
    (out / "single" / "pose3d.json").write_text(json.dumps({"frames": [{"frame": "0", "t_ms": 0, "people": []}]}))
    (out / "class" / "pose3d.json").write_text(json.dumps({"frames": [{"frame": 0, "people": []}]}))
    (out / "scored" / "cpu-single" / "pose3d.json").write_text(json.dumps([1, 2]))
    with running(repo) as p:
        assert get_json(p, "/api/outputs")[1] == []


def test_a_frame_where_nobody_was_found_is_listed(repo):
    (repo / "fixtures" / "output" / "single" / "pose3d.json").write_text(json.dumps(
        {"frames": [{"frame": 0, "t_ms": 0.0, "people": []}, {"frame": 1, "t_ms": 5.0, "people": []}]}))
    with running(repo) as p:
        row = next(r for r in get_json(p, "/api/outputs")[1] if r["id"] == "single")
        assert row["people"] == 0 and row["frames"] == 2 and row["mode"] == "single"


def test_the_index_follows_the_files(repo):
    with running(repo) as p:
        assert get_json(p, "/api/outputs")[1][0]["frames"] == 4
        write_more = repo / "fixtures" / "output" / "single"
        for f in write_more.iterdir():
            f.unlink()
        write_more.rmdir()
        write_output(write_more, n=6, step=100.0)
        assert get_json(p, "/api/outputs")[1][0]["frames"] == 6
        assert len(get_json(p, "/api/outputs/single")[1]["pose3d"]["frames"]) == 6


# ---- the committed outputs ------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real_port():
    with running(ROOT) as p:
        yield p


def test_committed_outputs_are_listed_with_their_real_counts(real_port):
    _, rows = get_json(real_port, "/api/outputs")
    by_id = {r["id"]: r for r in rows}
    assert {"single", "class", "dance"} <= set(by_id)
    for oid in ("single", "class", "dance"):
        pose3d = json.loads((ROOT / "fixtures" / "output" / oid / "pose3d.json").read_text())
        ids = {p["id"] for f in pose3d["frames"] for p in f["people"]}
        assert by_id[oid]["frames"] == len(pose3d["frames"]) and by_id[oid]["people"] == len(ids)
    assert by_id["class"]["people"] == 7 and by_id["class"]["frames"] == 89 and by_id["class"]["mode"] == "class"
    assert by_id["dance"]["mode"] == "class" and by_id["single"]["mode"] == "single"
    assert by_id["class"]["source"]["licence"] == "Pexels licence"
    if not by_id["single"]["has_pictures"]:       # the committed squat output has no stored clip frames
        assert by_id["single"]["source"]["licence"] == "CC BY 3.0"


def test_committed_class_output_serves_pose3d_tracks_and_every_picture(real_port):
    status, doc = get_json(real_port, "/api/outputs/class")
    assert status == 200 and len(doc["frames"]) == 89 and doc["tracks"] is not None
    assert {p["id"] for p in doc["pose3d"]["frames"][0]["people"]} == set(range(7))
    for f in (doc["frames"][0], doc["frames"][44], doc["frames"][88]):
        status, headers, body = fetch(real_port, "/" + f["url"])
        assert status == 200 and headers["content-type"] == "image/jpeg" and body[:2] == b"\xff\xd8"


def test_committed_outputs_without_stored_pictures_say_so(real_port):
    for oid in ("single", "dance"):
        _, doc = get_json(real_port, f"/api/outputs/{oid}")
        if not doc["output"]["has_pictures"]:
            assert all(f["url"] is None for f in doc["frames"])
    assert get_json(real_port, "/api/outputs/dance")[1]["tracks"] is not None


# ---- contract (AC-A02) ----------------------------------------------------------------------------------

def test_api_contract_returns_what_contract_json_returns(port, monkeypatch):
    monkeypatch.setattr(part2.contract, "contract_json", lambda: CONTRACT_DATA, raising=False)
    status, doc = get_json(port, "/api/contract")
    assert status == 200 and doc == CONTRACT_DATA


def test_api_contract_is_503_with_a_plain_error_when_the_data_is_not_available(port, monkeypatch):
    def broken():
        raise ValueError("cannot read /home/someone/contracts: Traceback")
    monkeypatch.setattr(part2.contract, "contract_json", broken, raising=False)
    status, headers, body = fetch(port, "/api/contract")
    assert status == 503 and headers["cache-control"] == "no-store"
    assert json.loads(body) == {"error": "The contract data is not available right now.", "code": "contract_unavailable"}


def test_api_contract_is_503_when_the_module_cannot_be_imported(port, monkeypatch):
    monkeypatch.delattr(sys.modules["part2"], "contract")
    monkeypatch.setitem(sys.modules, "part2.contract", None)
    assert fetch(port, "/api/contract")[0] == 503


def test_api_contract_is_503_when_the_data_is_not_json(port, monkeypatch):
    monkeypatch.setattr(part2.contract, "contract_json", lambda: {"x": object()}, raising=False)
    assert fetch(port, "/api/contract")[0] == 503


def test_schema_files_under_contracts_are_served_read_only(port):
    status, headers, body = fetch(port, "/contracts/pose3d.schema.json")
    assert status == 200 and headers["content-type"] == "application/json" and json.loads(body) == {"title": "pose3d"}
    assert json.loads(fetch(port, "/contracts/consumers/part3.json")[2]) == {"title": "part3"}
    assert fetch(port, "/contracts/pose3d.schema.json", "PUT", body=b"{}")[0] == 405
    assert fetch(port, "/contracts/nope.json")[0] == 404


def test_contract_md_is_served_for_the_contract_page(port):
    status, headers, body = fetch(port, "/CONTRACT.md")
    assert status == 200 and headers["content-type"] == "text/markdown; charset=utf-8" and body.startswith(b"# Contract")


@pytest.mark.skipif(not hasattr(part2.contract, "contract_json"), reason="part2.contract.contract_json is not merged yet")
def test_contract_page_data_equals_the_contract_command_and_every_schema_downloads(real_port):
    status, doc = get_json(real_port, "/api/contract")
    assert status == 200 and doc == json.loads(json.dumps(part2.contract.contract_json()))
    assert doc["schemas"] and doc["compatibility"]
    for schema in doc["schemas"]:
        status, headers, body = fetch(real_port, "/" + schema["file"])
        assert status == 200 and isinstance(json.loads(body), dict), schema["file"]
    listed = {Path(s["file"]).name for s in doc["schemas"]}
    on_disk = {p.name for p in (ROOT / "contracts").glob("*.schema.json")}
    assert on_disk <= listed


# ---- nothing is written, pages are CSP safe ----------------------------------------------------------------

def snapshot(root: Path):
    return {p.relative_to(root).as_posix(): (p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*") if p.is_file()}


def test_serving_writes_nothing_in_the_tree(repo):
    before = snapshot(repo)
    with running(repo) as p:
        for path in ("/", "/api/health", "/api/outputs", "/api/outputs/class", "/api/outputs/class/frames/0.jpg",
                     "/contracts/pose3d.schema.json", "/CONTRACT.md", "/nope"):
            fetch(p, path)
        fetch(p, "/api/outputs", "POST", body=b"abc")
    assert snapshot(repo) == before


def web_text(name: str) -> str:
    return (ROOT / "web" / name).read_text()


def page_ids(html: str) -> set:
    return set(re.findall(r'\bid="([^"]+)"', html))


def test_pages_use_no_inline_script_style_or_handler_so_the_csp_holds():
    for name in ("index.html", "contract.html", "run.html"):
        html = web_text(name)
        assert not re.search(r"<script(?![^>]*\ssrc=)", html), name
        assert not re.search(r"<style|\sstyle=|\son[a-z]+=", html), name
        assert 'rel="icon" href="icon.svg"' in html and 'href="style.css"' in html
        assert not re.search(r'(?:src|href)="/', html), f"{name} must use relative URLs"
    js = web_text("browse.js") + web_text("viewer.js") + web_text("run.js") + web_text("overlay.js")
    assert not re.search(r"""(?:fetch|href\s*=|src\s*=)\s*\(?\s*['"]/""", js), "scripts must use relative URLs"
    assert "setAttribute('style'" not in js and "innerHTML" not in js


def test_every_element_the_scripts_look_up_exists_on_its_page():
    index, contract = page_ids(web_text("index.html")), page_ids(web_text("contract.html"))
    looked_up = set(re.findall(r"\$\('([a-z-]+)'\)", web_text("browse.js")))
    assert looked_up <= index | contract
    browse_ids = {"output-select", "source-line", "frame-img", "frame-empty", "viewer", "legend", "view-front", "view-side",
                  "view-top", "view-reset", "play-toggle", "frame-slider", "frame-info", "status", "alert", "overlay",
                  "person-picker", "person-select"}
    contract_ids = {"status", "alert", "schemas", "schemas-empty", "compat", "compat-empty", "contract-doc"}
    assert browse_ids <= index and contract_ids <= contract
    assert {"viewer"} & contract == set()          # browse.js tells the pages apart by the canvas


def test_controls_have_the_accessible_names_the_verify_suite_uses():
    html = web_text("index.html")
    for ident, name in (("view-front", "Front"), ("view-side", "Side"), ("view-top", "Top"),
                        ("view-reset", "Reset"), ("play-toggle", "Play")):
        assert f'<button type="button" id="{ident}">{name}</button>' in html
    assert '<label for="frame-slider">Frame</label>' in html and 'id="frame-slider" min="0"' in html
    assert '<label for="output-select">Output</label>' in html
    assert 'role="status"' in html and 'role="alert"' in html
    assert 'aria-label="3D skeleton view"' in html


def test_nothing_we_wrote_uses_an_em_or_en_dash():
    files = [*(ROOT / "web").glob("*"), *(ROOT / "part2" / n for n in ("server.py", "runapi.py", "jobs.py", "gpu_guard.py")),
             ROOT / "scripts" / "dev.sh", Path(__file__), *(ROOT / "tests" / n for n in (
                 "test_viewer_js.py", "test_jobs.py", "test_runapi.py", "test_gpu_guard.py"))]
    banned = (chr(0x2014), chr(0x2013))
    for path in (f for f in files if f.exists()):  # scripts/dev.sh is firm-only and absent upstream
        assert not any(ch in path.read_text() for ch in banned), path


# ---- the process: python -m part2.server and scripts/dev.sh ---------------------------------------------------

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_main_exits_1_with_a_plain_message_when_the_port_is_taken(capsys):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        assert server.main(["--port", str(busy.getsockname()[1])]) == 1
    assert "in use by another program" in capsys.readouterr().err


DEV_SH = ROOT / "scripts" / "dev.sh"
# scripts/dev.sh is a firm-only file (never published), so a clean clone of upstream skips its tests.
needs_dev_sh = pytest.mark.skipif(not DEV_SH.exists(), reason="scripts/dev.sh is firm-only; absent in this checkout")


def dev(args, port, state, timeout=40):
    env = {**os.environ, "PART2_DEV_PORT": str(port), "PART2_DEV_STATE": str(state)}
    return subprocess.run(["bash", str(ROOT / "scripts" / "dev.sh"), *args], env=env, capture_output=True, text=True, timeout=timeout)


def alive(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return False


@needs_dev_sh
def test_dev_script_starts_serves_and_stops(tmp_path):
    port, state = free_port(), tmp_path / "state"
    try:
        started = dev(["start"], port, state)
        assert started.returncode == 0, started.stderr
        pid = int((state / "dev.pid").read_text())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as r:
            assert json.load(r)["ok"] is True
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            assert b"Browse outputs" in r.read()
        again = dev([], port, state)                                  # no argument means start; already running
        assert again.returncode == 0 and "already running" in again.stdout
        assert int((state / "dev.pid").read_text()) == pid
        stopped = dev(["stop"], port, state)
        assert stopped.returncode == 0 and not (state / "dev.pid").exists()
        for _ in range(50):
            if not alive(pid):
                break
            time.sleep(0.1)
        assert not alive(pid)
        assert dev(["stop"], port, state).returncode == 0              # idempotent
    finally:
        dev(["stop"], port, state)


@needs_dev_sh
def test_dev_stop_leaves_a_foreign_process_alone(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    other = subprocess.Popen(["sleep", "30"])
    try:
        (state / "dev.pid").write_text(str(other.pid))
        done = dev(["stop"], free_port(), state)
        assert done.returncode == 0 and other.poll() is None
        assert not (state / "dev.pid").exists()
    finally:
        other.send_signal(signal.SIGKILL)
        other.wait()


@needs_dev_sh
def test_dev_script_refuses_a_port_held_by_another_program_and_unknown_arguments(tmp_path):
    with running(ROOT) as held:
        busy = dev(["start"], held, tmp_path / "state")
        assert busy.returncode == 1 and "in use by another program" in busy.stderr
    assert dev(["bogus"], free_port(), tmp_path / "state").returncode == 2


# ---- the run API over HTTP (AC-A04 to AC-A12) ----------------------------------------------------------------------

@pytest.fixture
def runner(tmp_path):
    """A fake `part2 run` whose behaviour the test sets: runner["behaviour"] = "ok" | "class-fallback" | "sleep" ..."""
    script = tmp_path / "fake_run.py"
    script.write_text(FAKE_RUN)
    state = {"behaviour": "ok"}
    state["command"] = fake_command(script, lambda job: state["behaviour"])
    return state


@pytest.fixture
def run_port(repo, runner, tmp_path, monkeypatch):
    fake_smi(tmp_path, monkeypatch)                        # 20 GiB free
    with running(repo, command=runner["command"]) as p:
        yield p


def post_job(port, fields, file=None, extra=None, filename="clip.mp4"):
    body, ctype = form(fields, file, filename=filename)
    status, headers, raw = fetch(port, "/api/jobs", "POST", body, {"Content-Type": ctype, **(extra or {})})
    return status, headers, json.loads(raw)


def wait_job(port, jid, states=("done", "failed", "cancelled"), timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, doc = get_json(port, f"/api/jobs/{jid}")
        assert status == 200
        if doc["state"] in states:
            return doc
        time.sleep(0.05)
    raise AssertionError(f"job stayed {doc['state']}")


def test_capabilities_list_backends_trackers_samples_and_limits(run_port):
    status, headers, body = fetch(run_port, "/api/capabilities")
    doc = json.loads(body)
    assert status == 200 and headers["cache-control"] == "no-store"
    assert [b["name"] for b in doc["backends"]] == ["gpu", "cpu"]
    assert [t["name"] for t in doc["trackers"]] == ["automatic", "local-open", "bytetrack"]
    assert [s["id"] for s in doc["samples"]] == ["single", "class"]
    assert doc["limits"]["video_s"] == 60 and doc["limits"]["queue"] == 5
    assert "/" not in json.dumps({k: doc[k] for k in ("backends", "trackers", "samples")}).replace("/s", "")


def test_capabilities_say_why_something_cannot_run(repo):
    with running(repo, probe=lambda: {}) as p:
        doc = get_json(p, "/api/capabilities")[1]
        assert not any(b["available"] for b in doc["backends"])
        status, _, body = post_job(p, {"mode": "single", "sample": "single"})
        assert status == 503 and body == {"error": "No backend is available here right now.", "code": "no_backend"}


def test_a_sample_job_runs_and_its_files_download(run_port):
    status, headers, created = post_job(run_port, {"mode": "single", "sample": "single", "backend": "gpu"})
    assert status == 202 and set(created) == {"id", "state"} and headers["cache-control"] == "no-store"
    doc = wait_job(run_port, created["id"])
    assert doc["state"] == "done" and doc["backend"] == "gpu" and doc["tracker"] is None and doc["error"] is None
    assert doc["progress"] == {"stage": "write", "done": 1, "total": 1} and doc["files"] == ["pose3d.json", "camera.json"]
    base = f"/api/jobs/{created['id']}/files/"
    status, headers, body = fetch(run_port, base + "pose3d.json")
    assert status == 200 and headers["content-type"] == "application/json"
    assert headers["content-disposition"] == 'attachment; filename="pose3d.json"'
    assert json.loads(body)["provenance"]["backend"] == "gpu"
    assert fetch(run_port, base + "camera.json")[0] == 200
    assert fetch(run_port, base + "tracks.json")[0] == 404                       # a one-person run has none
    status, headers, body = fetch(run_port, base + "frames/2.jpg")
    assert status == 200 and headers["content-type"] == "image/jpeg" and body.startswith(b"\xff\xd8")
    for bad in ("frames/3.jpg", "frames/02.jpg", "frames/x.jpg", "frames/..%2fjob.json", "job.json", "run.err",
                "run.out", "body3d.json", "..%2fjob.json", "%2e%2e/job.json", "frames", "frames/1.jpg/x"):
        status, _, body = fetch(run_port, base + bad)
        assert status == 404 and json.loads(body) == {"error": "Not found.", "code": "not_found"}, bad
    assert fetch(run_port, base + "pose3d.json", "HEAD")[0] == 200


def test_a_class_job_names_its_fallback_tracker_and_offers_tracks(run_port, runner):
    runner["behaviour"] = "class-fallback"
    status, _, created = post_job(run_port, {"mode": "class", "sample": "class"})
    assert status == 202
    queued = get_json(run_port, f"/api/jobs/{created['id']}")[1]
    assert queued["tracker"] in ("automatic", "local-open") and queued["mode"] == "class"
    doc = wait_job(run_port, created["id"])
    assert doc["tracker"] == "local-open" and doc["fallback"] == {"from": "api-sam31", "reason": "budget"}
    assert doc["notice"] == "SAM 3.1 spend cap reached; tracked with local-open"
    status, headers, _ = fetch(run_port, f"/api/jobs/{created['id']}/files/tracks.json")
    assert status == 200 and headers["content-disposition"] == 'attachment; filename="tracks.json"'


def test_a_photo_job_runs_from_one_upright_frame(run_port):
    status, _, created = post_job(run_port, {"mode": "single"}, jpeg(), filename="photo.jpg")
    assert status == 202
    doc = wait_job(run_port, created["id"])
    assert doc["state"] == "done" and doc["kind"] == "photo"


def test_upload_errors_are_plain_and_leave_no_job(run_port):
    status, _, body = post_job(run_port, {"mode": "single"}, b"just text, renamed\n" * 30, filename="clip.mp4")
    assert status == 415 and body == {"error": "This file is not a video or photo the app can read.", "code": "unsupported"}
    status, _, body = post_job(run_port, {"mode": "single", "tracker": "api-sam31", "sample": "single"})
    assert status == 400 and "chosen by the app" in body["error"]
    status, _, body = post_job(run_port, {"mode": "class", "tracker": "local-sam31", "sample": "class"})
    assert status == 400 and body["code"] == "tracker_by_order"
    status, _, body = post_job(run_port, {"sample": "single"})
    assert status == 400 and body["code"] == "bad_mode"
    assert get_json(run_port, "/api/jobs")[1] == []


def test_the_test_header_lowers_the_body_cap(run_port):
    status, _, body = post_job(run_port, {"mode": "single"}, jpeg(), extra={"X-Part2-Test-Max-Body": "100"})
    assert status == 413 and body["error"] == "The file is too large. Videos can be up to 200 MB and photos up to 20 MB."


def test_a_body_over_the_cap_is_413_without_being_read(repo):
    with running(repo, limits=runapi.Limits(video_bytes=1000, form_slack=0)) as p:
        head, body = raw_exchange(p, b"POST /api/jobs HTTP/1.1\r\nHost: x\r\nContent-Type: multipart/form-data; boundary=b\r\n"
                                     b"Content-Length: 201000000\r\n\r\n")
        assert " 413 " in head.split("\r\n")[0] and json.loads(body)["code"] == "too_large"
        assert "X-Content-Type-Options: nosniff" in head


def test_content_length_missing_or_not_digits(run_port):
    head, body = raw_exchange(run_port, b"POST /api/jobs HTTP/1.1\r\nHost: x\r\nContent-Type: multipart/form-data; boundary=b\r\n\r\n")
    assert " 411 " in head.split("\r\n")[0] and json.loads(body)["code"] == "length_required"
    head, body = raw_exchange(run_port, b"POST /api/jobs HTTP/1.1\r\nHost: x\r\nContent-Length: lots\r\n\r\n")
    assert " 400 " in head.split("\r\n")[0] and json.loads(body)["code"] == "bad_length"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_a_61_second_video_is_422(run_port, tmp_path):
    clip = tmp_path / "long.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=32x32:r=1", "-t", "61",
                    "-c:v", "mpeg4", str(clip)], check=True, timeout=120)
    status, _, body = post_job(run_port, {"mode": "single"}, clip.read_bytes())
    assert status == 422 and body == {"error": "Videos can be at most 60 seconds long.", "code": "too_long"}


def test_the_sixth_job_is_429_and_cancel_answers_409_and_404(run_port, runner):
    runner["behaviour"] = "sleep"
    ids = [post_job(run_port, {"mode": "single", "sample": "single"})[2]["id"] for _ in range(5)]
    status, _, body = post_job(run_port, {"mode": "single", "sample": "single"})
    assert status == 429 and body == {"error": "The queue is full. Try again in a few minutes.", "code": "queue_full"}
    listing = get_json(run_port, "/api/jobs")[1]
    assert [r["position"] for r in listing][1:] == [1, 2, 3, 4] and all(i not in json.dumps(listing) for i in ids)
    for jid in reversed(ids):
        status, _, body = fetch(run_port, f"/api/jobs/{jid}/cancel", "POST")
        assert status == 200 and json.loads(body) == {"state": "cancelled"}
    status, _, body = fetch(run_port, f"/api/jobs/{ids[0]}/cancel", "POST")
    assert status == 409 and json.loads(body) == {"error": "This job has already finished.", "code": "finished"}
    assert fetch(run_port, "/api/jobs/0123456789ab/cancel", "POST")[0] == 404
    assert fetch(run_port, "/api/jobs/..%2f..%2fcancel/cancel", "POST")[0] == 404
    assert get_json(run_port, f"/api/jobs/{ids[0]}")[1]["state"] == "cancelled"
    assert fetch(run_port, f"/api/jobs/{ids[0]}/files/pose3d.json")[0] == 404     # nothing to download


def test_a_failed_job_reports_a_plain_message(run_port, runner):
    runner["behaviour"] = "noperson"
    doc = wait_job(run_port, post_job(run_port, {"mode": "single", "sample": "single"})[2]["id"])
    assert doc["state"] == "failed" and doc["error"] == "No person was found in this file."
    runner["behaviour"] = "crash"
    doc = wait_job(run_port, post_job(run_port, {"mode": "single", "sample": "single"})[2]["id"])
    text = json.dumps(doc)
    assert "Traceback" not in text and "KeyError" not in text and "/home" not in text and ".py" not in text


def test_a_gpu_job_waits_while_memory_is_short(repo, runner, tmp_path, monkeypatch):
    fake_smi(tmp_path, monkeypatch, "4096, 32768")
    with running(repo, command=runner["command"]) as p:
        jid = post_job(p, {"mode": "single", "sample": "single", "backend": "gpu"})[2]["id"]
        assert wait_job(p, jid, ("waiting-gpu",))["position"] == 0
        assert get_json(p, "/api/health")[1]["worker"] == "busy"
        doc = wait_job(p, jid)
        assert doc["error"] == "The GPU is busy with other work; try again later."


def test_unknown_jobs_are_404(run_port):
    for path in ("/api/jobs/0123456789ab", "/api/jobs/xyz", "/api/jobs/..%2f..%2fsecret.txt", "/api/jobs/%2e%2e",
                 "/api/jobs/0123456789ab/files/pose3d.json", "/api/jobs/0123456789AB", "/api/jobs/"):
        status, _, body = fetch(run_port, path)
        assert status == 404 and json.loads(body)["code"] == "not_found", path


def test_running_jobs_write_nothing_in_the_tree(repo, runner, tmp_path, monkeypatch):
    fake_smi(tmp_path, monkeypatch)
    before = snapshot(repo)
    jobs_dir = tmp_path / "server-jobs"
    with running(repo, command=runner["command"], jobs_dir=jobs_dir) as p:
        for fields, file in (({"mode": "single", "sample": "single"}, None), ({"mode": "single"}, jpeg()),
                             ({"mode": "single"}, b"text"), ({"mode": "class", "sample": "class"}, None)):
            status, _, body = post_job(p, fields, file)
            if status == 202:
                wait_job(p, body["id"])
    assert snapshot(repo) == before
    assert len([d for d in jobs_dir.iterdir() if jobs.JOB_ID.fullmatch(d.name)]) == 3


def test_a_restart_reports_unfinished_jobs_as_failed(repo, runner, tmp_path, monkeypatch):
    fake_smi(tmp_path, monkeypatch)
    runner["behaviour"] = "sleep"
    jobs_dir = tmp_path / "server-jobs"
    with running(repo, command=runner["command"], jobs_dir=jobs_dir) as p:
        jid = post_job(p, {"mode": "single", "sample": "single"})[2]["id"]
        wait_job(p, jid, ("running",))
    with running(repo, command=runner["command"], jobs_dir=jobs_dir) as p:
        doc = get_json(p, f"/api/jobs/{jid}")[1]
        assert doc["state"] == "failed" and doc["error"] == "The server restarted."


# ---- the run page (TICKET-025) and the page contract ---------------------------------------------------------------

def test_the_run_page_has_every_element_its_script_looks_up():
    run_ids = page_ids(web_text("run.html"))
    looked_up = set(re.findall(r"\$\('([a-z0-9-]+)'\)", web_text("run.js")))
    assert looked_up and looked_up <= run_ids
    viewer_ids = set(re.findall(r"\$\('([a-z-]+)'\)", web_text("viewer.js")))
    assert viewer_ids <= run_ids and viewer_ids <= page_ids(web_text("index.html"))


def test_run_page_controls_have_the_accessible_names_the_verify_suite_uses():
    html = web_text("run.html")
    assert "<legend>Input</legend>" in html and "<legend>Mode</legend>" in html
    assert '<label for="file-input">Video or photo</label>' in html
    assert 'id="mode-single" value="single" checked> One person</label>' in html
    assert 'id="mode-class" value="class"> Class</label>' in html and 'id="input-file" value="file"> Your own file</label>' in html
    for ident, name in (("backend-select", "Backend"), ("tracker-select", "Tracker"), ("person-select", "Person"),
                        ("frame-slider", "Frame")):
        assert f'<label for="{ident}">{name}</label>' in html
    for ident, name in (("run-button", "Run"), ("cancel-button", "Cancel"), ("view-front", "Front"), ("view-side", "Side"),
                        ("view-top", "Top"), ("view-reset", "Reset"), ("play-toggle", "Play"),
                        ("download-pose3d", "Download pose3d.json"), ("download-tracks", "Download tracks.json")):
        assert re.search(rf'<button type="(button|submit)" id="{ident}"[^>]*>{re.escape(name)}</button>', html), ident
    assert 'id="status" role="status"' in html and 'id="alert" role="alert"' in html
    assert 'aria-label="3D skeleton view"' in html and 'aria-label="People"' in html
    assert "input-sample-" in web_text("run.js")                     # sample radios: input-sample-<id>, label = title


def test_every_page_links_the_others_and_marks_itself():
    for name, current in (("index.html", "Browse"), ("contract.html", "Contract"), ("run.html", "Run")):
        nav = re.search(r'<nav id="site-nav" aria-label="Pages">(.*?)</nav>', web_text(name), re.S).group(1)
        links = re.findall(r'<a href="([a-z.]+)"( aria-current="page")?>([A-Za-z]+)</a>', nav)
        assert [(h, n) for h, _, n in links] == [("index.html", "Browse"), ("contract.html", "Contract"), ("run.html", "Run")]
        assert [n for _, cur, n in links if cur] == [current], name


def test_the_page_hooks_are_declared_on_window_app():
    run, browse = web_text("run.js"), web_text("browse.js")
    for key in ("ready", "output", "job", "runs", "frame", "frameCount", "playing", "people", "colors", "person",
                "viewerPeople", "camera", "target"):
        assert re.search(rf"\b{key}\b", run), key
    for key in ("ready", "output", "job", "runs", "frame", "frameCount", "playing", "people", "colors", "person",
                "camera", "target"):
        assert re.search(rf"\b{key}\b", browse), key


def test_the_run_page_is_served_with_its_scripts(real_port):
    for path, ctype in (("/run.html", "text/html"), ("/run.js", "text/javascript"), ("/overlay.js", "text/javascript")):
        status, headers, body = fetch(real_port, path)
        assert status == 200 and headers["content-type"].startswith(ctype) and body
    assert b'src="overlay.js"' in fetch(real_port, "/index.html")[2]
