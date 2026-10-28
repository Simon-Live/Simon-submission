"""part6/server.py: static files, the read API, entry files with Range, base path (AC-001, 002,
010) and the Phase 2 routes: contract, jobs, source filter, import (AC-C03, AC-C07, AC-C09)."""
import base64
import functools
import http.client
import json
import socket
import threading
import time
from pathlib import Path

import pytest
from conftest import short_id

from part6 import contract, importer, motion, processor, server, validate

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "output" / "catalog"
MANIFESTS = [json.loads((p / "manifest.json").read_text()) for p in sorted(FIXTURES.iterdir())]
N = len(MANIFESTS)
BY_NAME = sorted(MANIFESTS, key=lambda m: (m["name"].casefold(), m["name"], m["id"]))
HEALTH = {"ok": True, "contract_version": 1}


def raw(port, request):
    """Send raw bytes and return (status, headers, body); no URL normalisation on the way."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.putrequest("GET", request, skip_host=False, skip_accept_encoding=True)
        conn.endheaders()
        resp = conn.getresponse()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
    finally:
        conn.close()


def ids(body):
    return [m["id"] for m in json.loads(body)["entries"]]


def expected_ids(terms="", category=None):
    """Ids of the fixture entries whose name holds every term, in list order."""
    return [m["id"] for m in BY_NAME
            if all(t in m["name"].casefold() for t in terms.casefold().split())
            and category in (None, m["category"])]


# health and list

def test_health_counts_entries(app):
    status, body = app.client.get_json("/api/health")
    assert (status, body) == (200, dict(HEALTH, entries=N))
    assert N == 8


def test_health_reports_zero_for_an_empty_catalog(tmp_path, start_server):
    app = start_server(tmp_path / "empty")
    assert app.client.get_json("/api/health") == (200, dict(HEALTH, entries=0))
    assert app.client.get_json("/api/entries") == (200, {"entries": []})


def test_health_follows_the_folders_on_every_request(app, seeded):
    import shutil
    shutil.rmtree(seeded / "squat")
    assert app.client.get_json("/api/health")[1]["entries"] == N - 1


def test_list_sorted_by_name_with_whole_manifests(app):
    status, headers, body = app.client.get("/api/entries")
    assert status == 200 and headers["content-type"] == "application/json"
    entries = json.loads(body)["entries"]
    assert [m["name"] for m in entries] == [
        "Arm wave", "Forward lunge", "Hip twist", "Jumping jack", "Side step", "Squat",
        "Squat (Part 4)", "Step-touch (Part 4)"]
    assert [m["id"] for m in entries] == [m["id"] for m in BY_NAME]
    assert {m["files_source"] for m in entries} == {"fixture"} and not any(
        m.get("visitor") for m in entries)


@pytest.mark.parametrize("query,terms,category", [
    ("q=lunge", "lunge", None),
    ("q=LUNGE+forward", "lunge forward", None),
    ("q=%20lunge%20", "lunge", None),
    ("q=zzz", "zzz", None),
    ("q=part", "part", None),
    ("category=dance", "", "dance"),
    ("category=exercise", "", "exercise"),
    ("q=step&category=dance", "step", "dance"),
    ("q=step&category=exercise", "step", "exercise"),
    ("category=", "", None),
    ("q=", "", None),
])
def test_list_search_and_filter(app, query, terms, category):
    status, _, body = app.client.get(f"/api/entries?{query}")
    assert status == 200 and ids(body) == expected_ids(terms, category)


def test_the_search_and_filter_cases_find_something_to_tell_apart():
    assert expected_ids("lunge") == ["forward-lunge"] and expected_ids("zzz") == []
    assert len(expected_ids("", "dance")) == 4 and len(expected_ids("", "exercise")) == 4
    assert "part4-step-touch" in expected_ids("step", "dance") and expected_ids("step", "exercise") == []


@pytest.mark.parametrize("category", ["yoga", "Dance", "dances", "exercise%20", "1"])
def test_unknown_category_is_400(app, category):
    status, body = app.client.get_json(f"/api/entries?category={category}")
    assert (status, body) == (400, {"error": "category"})


def test_list_skips_an_invalid_entry(app, seeded):
    (seeded / "squat" / "manifest.json").write_text("{")
    assert "squat" not in ids(app.client.get("/api/entries")[2])
    assert app.client.get("/api/entries/squat")[0] == 404


@pytest.mark.parametrize("number", ["1e400", "-1e400", "1" + "0" * 5000, "-" + "1" * 400],
                         ids=short_id)
def test_list_skips_a_manifest_holding_a_number_no_browser_can_read(app, seeded, capsys, number):
    path = seeded / "squat" / "manifest.json"
    path.write_text(path.read_text().rstrip()[:-1] + f', "extra": {number}}}')
    status, _, body = app.client.get("/api/entries")
    assert status == 200 and ids(body) == [i for i in expected_ids() if i != "squat"]
    assert b"NaN" not in body and b"Infinity" not in body
    assert app.client.get("/api/entries/squat")[0] == 404
    assert app.client.get("/api/entries/squat/animation.json")[0] == 404
    assert app.client.get_json("/api/health")[1]["entries"] == N - 1
    assert "skipping squat: manifest.json: is not valid JSON" in capsys.readouterr().err


def test_a_manifest_with_a_large_finite_number_is_served(app, seeded):
    path = seeded / "squat" / "manifest.json"
    path.write_text(path.read_text().rstrip()[:-1] + ', "extra": 1.7976931348623157e308}')
    status, body = app.client.get_json("/api/entries/squat")
    assert status == 200 and body["extra"] == 1.7976931348623157e308
    assert "squat" in ids(app.client.get("/api/entries")[2])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_response_never_carries_nan_or_infinity(app, monkeypatch, capsys, value):
    monkeypatch.setattr(server.catalog, "list_entries", lambda *args, **kw: [{"x": value}])
    status, _, body = app.client.get("/api/entries")
    assert (status, json.loads(body)) == (500, {"error": "internal error"})
    assert b"NaN" not in body and b"Infinity" not in body
    assert "ValueError" in capsys.readouterr().err


# entry and files

def test_entry_manifest(app):
    status, body = app.client.get_json("/api/entries/squat")
    assert status == 200 and body["id"] == "squat" and body["name"] == "Squat"
    assert body["video_uri"] is None and body["files_source"] == "fixture"


@pytest.mark.parametrize("path", [
    "/api/entries/nope", "/api/entries/Squat", "/api/entries/squat%00", "/api/entries/..",
    "/api/entries/%2e%2e", "/api/entries/%2e%2e%2f%2e%2e", "/api/entries/a%2fb",
    "/api/entries/squat%0a", "/api/entries/.tmp-x", "/api/entries/", "/api/entries/x" + "y" * 80,
    "/api/entries/squat/", "/api/entries/squat/nope.json", "/api/entries/squat/..%2fsquat%2fmanifest.json",
    "/api/entries/squat/%2e%2e", "/api/entries/squat/.hidden", "/api/entries/squat/a%2fb",
    "/api/entries/squat/animation.json%0a", "/api/entries/squat/a/b", "/api/nope", "/api",
    "/api/", "/api/health/x", "/api/entries/nope/animation.json", "/api/jobs", "/api/jobs/",
    "/api/jobs/x/y", "/api/contract/x", "/api/import/x", "/api/jobs/Bad", "/api/jobs/..",
    "/api/jobs/%2e%2e", "/api/jobs/a%2fb", "/api/jobs/.tmp-x", "/api/jobs/x%00",
    "/api/jobs/x" + "y" * 80, "/api/jobs/unknown-00000000"])
def test_unknown_or_malformed_paths_are_json_404(app, path):
    status, headers, body = app.client.get(path)
    assert status == 404 and json.loads(body) == {"error": "not found"}
    assert headers["cache-control"] == "no-store"


def name_video(seeded, filename, data=b"video-bytes"):
    """Make the squat entry's manifest name a video file in its folder."""
    path = seeded / "squat" / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["video_uri"] = filename
    path.write_text(json.dumps(manifest))
    (seeded / "squat" / filename).write_bytes(data)


def test_entry_files_and_content_types(app, seeded):
    name_video(seeded, "clip.mp4", b"mp4-bytes")
    expected = {"animation.json": "application/json", "keyframes.json": "application/json",
                "skeleton.json": "application/json", "thumbnail.svg": "image/svg+xml",
                "clip.mp4": "video/mp4"}
    for name, ctype in expected.items():
        status, headers, body = app.client.get(f"/api/entries/squat/{name}")
        assert status == 200 and headers["content-type"] == ctype, name
        assert body == (seeded / "squat" / name).read_bytes()
        assert int(headers["content-length"]) == len(body)


def test_only_files_the_manifest_names_are_served(app, seeded):
    folder = seeded / "squat"
    for extra in ("manifest.json.bak", "notes.txt", "evil.html", "page.js", "other.json"):
        (folder / extra).write_text("<script>alert(1)</script>")
    for path in ("manifest.json", "manifest.json.bak", "notes.txt", "evil.html", "page.js",
                 "other.json", "video.webm"):
        status, headers, body = app.client.get(f"/api/entries/squat/{path}")
        assert status == 404 and json.loads(body) == {"error": "not found"}, path
    assert app.client.get("/api/entries/squat/animation.json")[0] == 200
    assert app.client.get("/api/entries/squat")[0] == 200     # the manifest has its own route


def test_a_video_uri_that_is_not_a_plain_file_name_serves_nothing(app, seeded):
    path = seeded / "squat" / "manifest.json"
    manifest = json.loads(path.read_text())
    (seeded / "squat" / "v.webm").write_bytes(b"v")
    (seeded / "squat" / "sub").mkdir()
    (seeded / "squat" / "sub" / "v.webm").write_bytes(b"v")
    for uri in ("https://example.com/v.webm", "sub/v.webm", "../squat/v.webm", ".v.webm", ""):
        manifest["video_uri"] = uri
        path.write_text(json.dumps(manifest))
        assert app.client.get("/api/entries/squat/v.webm")[0] == 404, uri
    manifest["video_uri"] = "v.webm"
    path.write_text(json.dumps(manifest))
    assert app.client.get("/api/entries/squat/v.webm")[2] == b"v"
    (seeded / "squat" / "v.webm").unlink()
    assert app.client.get("/api/entries/squat/v.webm")[0] == 404


def test_entry_files_are_never_served_as_a_page_or_script(app, seeded):
    path = seeded / "squat" / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["animation"] = "page.html"
    manifest["skeleton"] = "app.js"
    path.write_text(json.dumps(manifest))
    (seeded / "squat" / "page.html").write_text("<script>alert(1)</script>")
    (seeded / "squat" / "app.js").write_text("alert(1)")
    for name in ("page.html", "app.js"):
        status, headers, _ = app.client.get(f"/api/entries/squat/{name}")
        assert status == 200 and headers["content-type"] == "application/octet-stream"
        assert headers["x-content-type-options"] == "nosniff"


def test_api_responses_are_never_cached(app):
    for path in ("/api/health", "/api/entries", "/api/entries/squat",
                 "/api/entries/squat/animation.json", "/api/entries/squat/thumbnail.svg",
                 "/api/entries/zzz", "/api/entries?category=x"):
        assert app.client.get(path)[1]["cache-control"] == "no-store", path


def test_the_served_animation_is_valid_json_with_17_joints(app):
    status, body = app.client.get_json("/api/entries/squat/animation.json")
    assert status == 200 and len(body["frames"][0]["people"][0]["joints"]) == 17


def test_files_of_an_invalid_entry_are_not_served(app, seeded):
    (seeded / "squat" / "manifest.json").write_text("{")
    assert app.client.get("/api/entries/squat/animation.json")[0] == 404


# Range

@pytest.fixture
def video(seeded):
    data = bytes(range(256)) * 4
    name_video(seeded, "video.webm", data)
    return data


@pytest.mark.parametrize("header,start,end", [
    ("bytes=0-9", 0, 9), ("bytes=10-19", 10, 19), ("bytes=1000-", 1000, 1023),
    ("bytes=-24", 1000, 1023), ("bytes=1020-5000", 1020, 1023), ("bytes=0-0", 0, 0),
    ("bytes=1023-1023", 1023, 1023), ("bytes=-5000", 0, 1023)])
def test_one_range_gets_206(app, video, header, start, end):
    status, headers, body = app.client.get("/api/entries/squat/video.webm", {"Range": header})
    assert status == 206 and body == video[start:end + 1]
    assert headers["content-range"] == f"bytes {start}-{end}/1024"
    assert int(headers["content-length"]) == end - start + 1
    assert headers["accept-ranges"] == "bytes" and headers["content-type"] == "video/webm"


@pytest.mark.parametrize("header", [
    None, "", "bytes=0-9,20-29", "bytes=5-2", "bytes=1024-", "bytes=2000-3000", "bytes=-0",
    "bytes=abc", "bytes=-", "bytes=--5", "items=0-5", "bytes", "bytes=0-9x"])
def test_anything_else_gets_the_whole_file(app, video, header):
    headers = {"Range": header} if header is not None else {}
    status, resp, body = app.client.get("/api/entries/squat/video.webm", headers)
    assert status == 200 and body == video and "content-range" not in resp
    assert resp["accept-ranges"] == "bytes"


def test_parse_range_unit():
    assert server.parse_range("bytes=2-4", 10) == (2, 4)
    assert server.parse_range("bytes=2-", 10) == (2, 9)
    assert server.parse_range("bytes=-3", 10) == (7, 9)
    assert server.parse_range("bytes=9-12", 10) == (9, 9)
    assert server.parse_range("bytes=10-12", 10) is None
    assert server.parse_range("bytes=0-1", 0) is None
    assert server.parse_range(None, 10) is None


def test_head_returns_headers_and_no_body(app, video):
    status, headers, body = app.client.request("HEAD", "/api/entries/squat/video.webm")
    assert status == 200 and body == b"" and headers["content-length"] == "1024"
    status, headers, body = app.client.request("HEAD", "/api/health")
    assert status == 200 and body == b"" and int(headers["content-length"]) > 0


# static files

@pytest.fixture
def site(tmp_path, start_server, seeded):
    web = tmp_path / "site"
    (web / "vendor" / "three").mkdir(parents=True)
    files = {"index.html": "<h1>index</h1>", "app.js": "export {}", "mod.mjs": "export {}",
             "style.css": "a{}", "icon.svg": "<svg/>", "data.json": "{}",
             "clip.webm": "w", "clip.mp4": "m", "blob.bin": "b",
             "vendor/three/three.module.js": "// three"}
    for name, text in files.items():
        (web / name).write_text(text)
    (web / ".secret").write_text("hidden")
    (tmp_path / "outside.txt").write_text("outside")
    (web / "link.txt").symlink_to(tmp_path / "outside.txt")
    return start_server(seeded, web_root=web)


def test_root_serves_index_html(site):
    status, headers, body = site.client.get("/")
    assert status == 200 and body == b"<h1>index</h1>"
    assert headers["content-type"] == "text/html; charset=utf-8"


@pytest.mark.parametrize("path,ctype", [
    ("/index.html", "text/html; charset=utf-8"), ("/app.js", "text/javascript; charset=utf-8"),
    ("/mod.mjs", "text/javascript; charset=utf-8"), ("/style.css", "text/css; charset=utf-8"),
    ("/icon.svg", "image/svg+xml"), ("/data.json", "application/json"),
    ("/clip.webm", "video/webm"), ("/clip.mp4", "video/mp4"), ("/blob.bin", "application/octet-stream"),
    ("/vendor/three/three.module.js", "text/javascript; charset=utf-8")])
def test_explicit_content_types(site, path, ctype):
    status, headers, _ = site.client.get(path)
    assert status == 200 and headers["content-type"] == ctype
    assert headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("path", [
    "/missing.js", "/vendor", "/vendor/", "/vendor/three/", "/.secret", "/vendor/../.secret",
    "/%2e%2e/outside.txt", "/..%2foutside.txt", "/%2e%2e%2foutside.txt", "/vendor/..%2f..%2foutside.txt",
    "/link.txt", "/index.html/", "/app.js%00", "/a%5cb", "/%2e", "/vendor//three/three.module.js"])
def test_static_404s(site, path):
    assert site.client.get(path)[0] == 404


@pytest.mark.parametrize("request_target", [
    "/../outside.txt", "/vendor/../../outside.txt", "/../../../../etc/passwd", "/./index.html",
    "/vendor/./three/../../../outside.txt"])
def test_raw_traversal_never_leaves_the_web_folder(site, request_target):
    status, _, body = raw(site.port, request_target)
    assert body != b"outside" and b"root:" not in body
    assert status in (200, 404)


def test_static_files_are_revalidated_not_stored(site):
    assert site.client.get("/app.js")[1]["cache-control"] == "no-cache"


def test_static_routes_never_fall_through_to_the_api_namespace(site):
    assert site.client.get("/api/index.html")[0] == 404


def test_a_server_over_the_shipped_fixtures_cannot_be_made(tmp_path):
    fixtures = server.REPO_ROOT / "fixtures" / "output" / "catalog"
    for root in (fixtures, fixtures / "squat"):
        with pytest.raises(server.catalog.RootError):
            server.make_server(root, port=0)


def test_repo_root_is_defined_once():
    assert server.REPO_ROOT is server.catalog.REPO_ROOT
    assert "REPO_ROOT =" not in (server.REPO_ROOT / "part6" / "server.py").read_text()


def test_the_default_web_folder_is_the_repo_web_folder(seeded):
    srv = server.make_server(seeded, port=0)
    try:
        assert srv.web_root == (server.REPO_ROOT / "web").resolve()
        assert (server.REPO_ROOT / "part6" / "server.py").is_file()
    finally:
        srv.server_close()


# base path

def test_normalize_base():
    assert [server.normalize_base(v) for v in (None, "", "/", "//", "/simon", "/simon/", "simon",
                                                " /a/b/ ")] == ["", "", "", "", "/simon", "/simon",
                                                               "/simon", "/a/b"]


def test_requests_under_a_base_path(seeded, start_server):
    app = start_server(seeded, base_path="/simon/")
    c = app.client
    assert c.get("/simon/api/health")[0] == 200
    assert c.get_json("/simon/api/health")[1] == dict(HEALTH, entries=N)
    assert c.get("/simon/")[2] == b"<!doctype html><title>t</title>"
    assert c.get("/simon/api/entries/squat/animation.json")[0] == 200
    assert c.get("/simon/api/entries?category=dance")[0] == 200
    status, body = c.post_json({"name": "Under base", "category": "dance", "duration_ms": 2000},
                               path="/simon/api/entries", prefix="")
    assert status == 201
    assert c.get_json(f"/simon/api/jobs/{body['id']}")[1] == {
        "id": body["id"], "status": "done", "entry": body}
    assert c.get_json("/simon/api/contract")[1]["contract_version"] == 1


@pytest.mark.parametrize("path", [
    "/", "/api/health", "/api/entries", "/index.html", "/simonx/api/health", "/simon-x/",
    "/other/simon/api/health", "/SIMON/api/health", "/simon/../api/health"])
def test_requests_outside_the_base_path_are_404(seeded, start_server, path):
    app = start_server(seeded, base_path="/simon")
    assert app.client.get(path)[0] == 404


def test_the_bare_base_path_redirects_to_its_slash(seeded, start_server):
    app = start_server(seeded, base_path="/simon")
    status, headers, _ = app.client.get("/simon")
    assert status == 301 and headers["location"] == "/simon/"


def test_the_environment_sets_the_base_path(seeded, start_server, monkeypatch):
    monkeypatch.setenv("SIMON6_BASE_PATH", "/env-base")
    app = start_server(seeded)
    assert app.srv.base_path == "/env-base"
    assert app.client.get("/env-base/api/health")[0] == 200
    assert app.client.get("/api/health")[0] == 404


def test_default_base_path_is_the_root(seeded, start_server):
    app = start_server(seeded)
    assert app.srv.base_path == "" and app.client.get("/api/health")[0] == 200


# methods

@pytest.mark.parametrize("method,path", [
    ("PUT", "/api/entries"), ("DELETE", "/api/entries/squat"), ("PATCH", "/api/entries"),
    ("POST", "/api/health"), ("POST", "/api/entries/squat"), ("POST", "/api/entries/squat/animation.json"),
    ("POST", "/"), ("PUT", "/index.html"), ("OPTIONS", "/api/entries"), ("DELETE", "/"),
    ("POST", "/api/contract"), ("POST", "/api/jobs/x"), ("DELETE", "/api/jobs/x"),
    ("PUT", "/api/contract"), ("PUT", "/api/import"), ("DELETE", "/api/import"),
    ("GET", "/api/import")])
def test_other_methods_are_405(app, method, path):
    status, headers, body = app.client.request(method, path, body=b"{}" if method == "POST" else None)
    assert status == 405 and json.loads(body) == {"error": "method not allowed"}


def test_an_unread_request_body_is_never_parsed_as_the_next_request(app, capsys):
    conn = http.client.HTTPConnection("127.0.0.1", app.port, timeout=5)
    try:
        conn.request("POST", "/api/health", body=b"GET /api/health HTTP/1.1\r\n\r\n")
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 405 and resp.getheader("Connection") == "close"
    finally:
        conn.close()
    assert "Bad request" not in capsys.readouterr().err


def test_post_to_an_unknown_api_path_is_404(app):
    assert app.client.post({"name": "x"}, path="/api/nope")[0] == 404


# threading and logging

def test_a_stalled_connection_does_not_block_other_requests(app):
    stalled = [socket.create_connection(("127.0.0.1", app.port)) for _ in range(3)]
    try:
        for s in stalled:
            s.sendall(b"GET /api/health HTTP/1.1\r\nHost: x\r\nX-Slow: ")   # never finished
        began = time.monotonic()
        results = []

        def fetch():
            results.append(app.client.get("/api/health")[0])

        threads = [threading.Thread(target=fetch) for _ in range(8)]
        [t.start() for t in threads]
        [t.join(5) for t in threads]
        assert results == [200] * 8 and time.monotonic() - began < 3
    finally:
        for s in stalled:
            s.close()


def test_requests_are_logged_to_stderr_never_stdout(app, capsys):
    app.client.get("/api/health")
    app.client.get("/api/entries/nope")
    out = capsys.readouterr()
    assert out.out == ""
    assert "GET /api/health" in out.err and '"GET /api/entries/nope HTTP/1.1" 404' in out.err


def test_keep_alive_serves_several_requests_on_one_connection(app):
    conn = http.client.HTTPConnection("127.0.0.1", app.port, timeout=5)
    try:
        for _ in range(3):
            conn.request("GET", "/api/health")
            resp = conn.getresponse()
            assert resp.status == 200 and json.loads(resp.read())["ok"] is True
    finally:
        conn.close()


def test_a_crash_after_the_headers_closes_the_connection_without_a_second_response(
        app, monkeypatch, capsys):
    def half_a_response(self, status, obj):
        self._start(200, 5, {"Content-Type": "application/json"})
        raise RuntimeError("died after the headers")

    monkeypatch.setattr(server.Handler, "_json", half_a_response)
    with socket.create_connection(("127.0.0.1", app.port), timeout=5) as s:
        s.sendall(b"GET /api/health HTTP/1.1\r\nHost: x\r\n\r\n")
        data = b""
        while chunk := s.recv(4096):      # returns b"" only when the server closed the socket
            data += chunk
    assert data.count(b"HTTP/1.1") == 1 and b"internal error" not in data
    assert "died after the headers" in capsys.readouterr().err
    monkeypatch.undo()
    assert app.client.get("/api/health")[0] == 200


def test_a_crash_in_a_handler_is_a_json_500_and_the_server_lives(app, monkeypatch, capsys):
    monkeypatch.setattr(server.catalog, "list_entries", lambda *a, **k: 1 / 0)
    status, body = app.client.get_json("/api/entries")
    assert (status, body) == (500, {"error": "internal error"})
    assert "ZeroDivisionError" in capsys.readouterr().err
    monkeypatch.undo()
    assert app.client.get("/api/health")[0] == 200


def test_head_on_a_post_only_route_is_405_without_a_body(app):
    status, headers, body = app.client.request("HEAD", "/api/import")
    assert status == 405 and body == b""


# Phase 2 helpers

VALID = {"name": "Evening flow", "category": "dance", "duration_ms": 2000}
SAMPLE = processor.generate("squat", 2000, motion.MotionParams(2.0, 1))
WEBM = b"\x1a\x45\xdf\xa3" + bytes(range(100))
MP4 = b"\x00\x00\x00\x18ftypmp42" + bytes(range(100))


def text_file(name, data):
    return {"name": name, "text": data if isinstance(data, str) else json.dumps(data)}


def video_file(name="clip.webm", data=WEBM):
    return {"name": name, "base64": base64.b64encode(data).decode()}


def sample_files(*kinds):
    return [text_file(f"{kind}.json", SAMPLE[kind]) for kind in kinds]


def import_body(**changes):
    """A valid import body; a changed field replaces it, `...` drops it."""
    body = {"name": "Imported move", "category": "exercise",
            "files": sample_files("animation", "skeleton", "keyframes")}
    body.update(changes)
    return {k: v for k, v in body.items() if v is not ...}


def post_import(app, body, headers=None):
    payload = body if isinstance(body, bytes) else json.dumps(body).encode()
    status, resp, data = app.client.request(
        "POST", "/api/import", body=payload,
        headers={"Content-Type": "application/json"} if headers is None else headers)
    return status, json.loads(data)


class Slow:
    """A processor that reports a stage, then waits to be released."""

    def __init__(self, stage="keyframes", files=None):
        self.stage, self.files = stage, files
        self.started = threading.Event()
        self.release = threading.Event()
        self.seen = []

    def __call__(self, recording, report):
        self.seen.append(recording)
        report(f"processing:{self.stage}")
        self.started.set()
        assert self.release.wait(15), "the test never released the processor"
        return self.files or processor.process(recording)


@pytest.fixture
def serve_with(seeded, start_server, monkeypatch):
    """serve_with(**make_server options) -> a running server over the seeded catalog."""
    def start(**options):
        monkeypatch.setattr(server, "make_server",
                            functools.partial(server.make_server, **options))
        return start_server(seeded)
    return start


@pytest.fixture
def quick_answer(monkeypatch):
    """POST api/entries gives up waiting after 0.1 s instead of 3 s."""
    monkeypatch.setattr(server, "WAIT_SECONDS", 0.1)


def entry_count(app):
    return app.client.get_json("/api/health")[1]["entries"]


def nothing_new(seeded):
    return sorted(p.name for p in seeded.iterdir()) == sorted(m["id"] for m in MANIFESTS)


# health and contract

def test_health_reports_the_contract_version(app):
    assert app.client.get_json("/api/health")[1]["contract_version"] == contract.CONTRACT_VERSION == 1


def test_the_contract_endpoint_is_the_contract_document(app):
    status, headers, body = app.client.get("/api/contract")
    assert status == 200 and headers["content-type"] == "application/json"
    assert headers["cache-control"] == "no-store"
    assert json.loads(body) == contract.document(None)
    doc = json.loads(body)
    assert doc["contract_version"] == 1 and "manifest" in doc["schemas"]
    assert doc["handoff"]["follow_url"] is None


def test_the_follow_url_reaches_the_contract_document(serve_with):
    url = "https://example.org/follow?id={id}&m={manifest}"
    app = serve_with(follow_url=url)
    doc = app.client.get_json("/api/contract")[1]
    assert doc == contract.document(url) and doc["handoff"]["follow_url"] == url
    assert app.srv.follow_url == url


@pytest.mark.parametrize("url", ["ftp://example.org/{id}", "javascript:alert(1)",
                                 "//example.org/{id}", "/relative/{id}", "https://", "http://a b/"])
def test_a_follow_url_that_is_not_http_or_https_stops_the_server(seeded, url):
    with pytest.raises(ValueError):
        server.make_server(seeded, port=0, follow_url=url)


def test_the_contract_endpoint_is_head_ready(app):
    status, headers, body = app.client.request("HEAD", "/api/contract")
    assert status == 200 and body == b"" and int(headers["content-length"]) > 100


# source filter

@pytest.mark.parametrize("source", validate.FILES_SOURCES)
def test_the_source_filter_keeps_one_files_source(app, source):
    status, body = app.client.get_json(f"/api/entries?source={source}")
    assert status == 200
    expected = [m["id"] for m in BY_NAME if m["files_source"] == source]
    assert [m["id"] for m in body["entries"]] == expected
    assert (len(expected) == N) == (source == "fixture")


@pytest.mark.parametrize("source", ["pipeline", "Fixture", "mocks", "x", "fixture%20", "1"])
def test_an_unknown_source_is_400(app, source):
    assert app.client.get_json(f"/api/entries?source={source}") == (400, {"error": "source"})


def test_a_blank_source_is_no_filter_and_it_combines_with_q_and_category(app):
    assert ids(app.client.get("/api/entries?source=")[2]) == [m["id"] for m in BY_NAME]
    manifest = app.client.post_json(VALID)[1]
    mine = app.client.get_json("/api/entries?source=mock&category=dance&q=evening")[1]
    assert [m["id"] for m in mine["entries"]] == [manifest["id"]]
    assert app.client.get_json("/api/entries?source=mock&category=exercise")[1] == {"entries": []}
    assert app.client.get_json("/api/entries?source=mock&q=zzz")[1] == {"entries": []}
    assert app.client.get_json("/api/entries?source=import")[1] == {"entries": []}


# POST api/entries: the job flow

def test_the_mock_answers_201_with_the_manifest_and_marks_a_visitor(app):
    status, manifest = app.client.post_json(VALID)
    assert status == 201 and manifest["files_source"] == "mock" and manifest["visitor"] is True
    assert app.client.get_json(f"/api/jobs/{manifest['id']}") == (
        200, {"id": manifest["id"], "status": "done", "entry": manifest})
    assert app.client.get_json(f"/api/entries/{manifest['id']}")[1] == manifest


def test_a_slow_processor_answers_202_and_the_job_ends_with_the_entry(serve_with, quick_answer):
    slow = Slow("skeleton")
    app = serve_with(processor=slow)
    status, body = app.client.post_json(VALID)
    assert status == 202
    assert body == {"id": body["id"], "status": "processing:skeleton", "job": f"api/jobs/{body['id']}"}
    assert app.client.get_json(f"/api/jobs/{body['id']}") == (
        200, {"id": body["id"], "status": "processing:skeleton", "entry": None})
    assert app.client.get(f"/api/entries/{body['id']}")[0] == 404
    slow.release.set()
    assert wait_for_status(app, body["id"], "done")
    job = app.client.get_json(f"/api/jobs/{body['id']}")[1]
    entry = app.client.get_json(f"/api/entries/{body['id']}")[1]
    assert job["entry"] == entry and entry["files_source"] == "processor" and entry["visitor"] is True
    assert entry["description"].startswith("Recorded ")
    day = entry["created_at"][:10]
    assert entry["description"] == f"Recorded {day}. Processed by {__name__}:Slow."
    assert validate.check_entry(app.srv.root / body["id"]) == []


def wait_for_status(app, job_id, status, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if app.client.get_json(f"/api/jobs/{job_id}")[1]["status"] == status:
            return True
        time.sleep(0.02)
    return False


def test_the_job_path_in_a_202_is_relative_to_the_base_path(serve_with, quick_answer, monkeypatch):
    monkeypatch.setenv("SIMON6_BASE_PATH", "/simon")
    slow = Slow()
    app = serve_with(processor=slow)
    status, body = app.client.post_json(VALID, path="/simon/api/entries", prefix="")
    assert status == 202 and body["job"] == f"api/jobs/{body['id']}"
    assert app.client.get_json(f"/simon/{body['job']}")[1]["id"] == body["id"]
    slow.release.set()


def test_a_processor_reports_stages_that_the_job_shows_in_order(serve_with, quick_answer):
    stages = ["keyframes", "skeleton", "animation"]
    seen, gates = [], [threading.Event() for _ in stages]

    def staged(recording, report):
        for stage, gate in zip(stages, gates):
            report(f"processing:{stage}")
            assert gate.wait(10)
        return processor.process(recording)

    app = serve_with(processor=staged)
    body = app.client.post_json(VALID)[1]
    for stage, gate in zip(stages, gates):
        assert wait_for_status(app, body["id"], f"processing:{stage}")
        seen.append(stage)
        gate.set()
    assert wait_for_status(app, body["id"], "done") and seen == stages


def test_a_processor_that_finishes_inside_the_wait_is_201(serve_with):
    app = serve_with(processor=lambda recording, report: processor.process(recording, report))
    status, manifest = app.client.post_json(VALID)
    assert status == 201 and manifest["files_source"] == "processor"


def test_a_failed_job_is_202_with_the_status_and_no_entry(serve_with, seeded):
    app = serve_with(processor=lambda recording, report: {"status": "failed:pose: nobody in view"})
    status, body = app.client.post_json(VALID)
    assert status == 202 and body["status"] == "failed:pose: nobody in view"
    assert app.client.get_json(body["job"].replace("api/", "/api/", 1)) == (
        200, {"id": body["id"], "status": body["status"], "entry": None})
    assert nothing_new(seeded) and entry_count(app) == N


def test_a_raising_processor_fails_the_job_with_the_stage_and_message(serve_with, seeded, capsys):
    def broken(recording, report):
        report("processing:animation")
        raise RuntimeError("model crashed\nsecret detail")

    app = serve_with(processor=broken)
    status, body = app.client.post_json(VALID)
    assert status == 202 and body["status"] == "failed:animation: model crashed"
    assert nothing_new(seeded) and "secret detail" in capsys.readouterr().err


def test_files_the_readers_reject_fail_the_job_as_validate(serve_with, seeded):
    app = serve_with(processor=lambda recording, report: {"animation": {"fps": 30}})
    status, body = app.client.post_json(VALID)
    assert status == 202 and body["status"].startswith("failed:validate: animation.json: ")
    assert nothing_new(seeded)


def test_the_processor_gets_the_recording_and_a_report_function(serve_with):
    seen = []

    def spy(recording, report):
        seen.append((recording, callable(report)))
        return processor.process(recording)

    app = serve_with(processor=spy)
    manifest = app.client.post_json(dict(VALID, name="Spied"))[1]
    assert seen == [({"id": manifest["id"], "name": "Spied", "category": "dance",
                      "duration_ms": 2000, "video_path": None}, True)]


def test_a_ninth_waiting_recording_is_503_busy(serve_with, quick_answer, seeded):
    slow = Slow()
    app = serve_with(processor=slow)
    results = [app.client.post_json(dict(VALID, name=f"Move {n}")) for n in range(9)]
    assert [status for status, _ in results] == [202] * 9      # one running, eight waiting
    status, body = app.client.post_json(dict(VALID, name="One too many"))
    assert (status, body) == (503, {"error": "busy, try again"})
    assert not any(p.name.startswith("one-too-many") for p in seeded.iterdir())
    slow.release.set()
    assert wait_for_status(app, results[-1][1]["id"], "done")
    assert app.client.post_json(VALID)[0] == 201                # room again


def test_validation_still_comes_before_the_queue(serve_with):
    app = serve_with(processor=lambda recording, report: pytest.fail("called"))
    assert app.client.post_json(dict(VALID, duration_ms=5)) == (400, {"error": "duration_ms"})


def test_the_cap_applies_to_processed_recordings(serve_with, seeded):
    app = serve_with(max_recordings=1)
    first = app.client.post_json(VALID)[1]
    second = app.client.post_json(VALID)[1]
    assert app.client.get(f"/api/entries/{first['id']}")[0] == 404
    assert app.client.get(f"/api/entries/{second['id']}")[0] == 200


def test_shutdown_closes_the_job_worker(app):
    worker = app.srv.jobs._thread
    assert worker.is_alive()
    app.stop()
    assert not worker.is_alive()


# the fake Part 4 processors, end to end

def test_the_fake_part4_processor_runs_stages_then_the_entry_plays(serve_with, monkeypatch):
    monkeypatch.setenv("SIMON6_FAKE_STAGE_S", "0.25")
    monkeypatch.setattr(server, "WAIT_SECONDS", 0.05)
    app = serve_with(processor=jobs_parse("fixtures.processors.part4_fake:process"))
    status, body = app.client.post_json(VALID)
    assert status == 202
    seen = set()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = app.client.get_json(body["job"].replace("api/", "/api/", 1))[1]
        seen.add(job["status"])
        if job["status"] == "done":
            break
        time.sleep(0.02)
    assert job["status"] == "done"
    assert len(seen - {"queued", "done"}) >= 2 and all(
        s.startswith(("queued", "processing:", "done")) for s in seen)
    entry = job["entry"]
    assert entry["files_source"] == "processor"
    assert "Processed by fixtures.processors.part4_fake:process." in entry["description"]
    assert entry["provenance"]["animation"]["format"] == "simon.animation.v1"
    assert entry["provenance"]["animation"]["part"] == 4
    animation = app.client.get_json(f"/api/entries/{entry['id']}/animation.json")[1]
    assert animation["format"] == "simon.animation.v1"


def test_the_fake_part4_failure_names_the_pose_stage(serve_with):
    app = serve_with(processor=jobs_parse("fixtures.processors.part4_fake:fail"))
    status, body = app.client.post_json(VALID)
    assert status == 202 and body["status"] == "failed:pose: no person found in the video"


def jobs_parse(spec):
    from part6.jobs import parse_processor
    return parse_processor(spec)


# jobs route

def test_an_unknown_job_is_404_and_its_entry_is_not_created(app):
    assert app.client.get_json("/api/jobs/never-submitted-00000000") == (404, {"error": "not found"})


def test_a_job_older_than_the_last_50_is_404_while_the_entry_stays(serve_with):
    app = serve_with(max_recordings=0)        # no cap, so the first entry is not trimmed
    first = app.client.post_json(VALID)[1]
    for _ in range(50):
        assert app.client.post_json(VALID)[0] == 201
    assert app.client.get(f"/api/jobs/{first['id']}")[0] == 404
    assert app.client.get(f"/api/entries/{first['id']}")[0] == 200


def test_a_job_is_head_ready(app):
    manifest = app.client.post_json(VALID)[1]
    status, headers, body = app.client.request("HEAD", f"/api/jobs/{manifest['id']}")
    assert status == 200 and body == b"" and int(headers["content-length"]) > 0


# import: success

def test_an_import_is_201_with_the_manifest_marked_import_and_visitor(app):
    status, manifest = post_import(app, import_body())
    assert status == 201
    assert manifest["files_source"] == "import" and manifest["visitor"] is True
    assert manifest["name"] == "Imported move" and manifest["category"] == "exercise"
    assert manifest["video_uri"] is None and manifest["duration_ms"] > 0
    assert set(manifest["provenance"]) == {"animation", "skeleton", "keyframes"}
    assert validate.check_entry(app.srv.root / manifest["id"]) == []
    assert app.client.get_json(f"/api/entries/{manifest['id']}")[1] == manifest
    assert entry_count(app) == N + 1
    listed = app.client.get_json("/api/entries?source=import")[1]["entries"]
    assert [m["id"] for m in listed] == [manifest["id"]]
    served = app.client.get_json(f"/api/entries/{manifest['id']}/animation.json")[1]
    assert served == SAMPLE["animation"]


def test_an_import_accepts_a_content_type_with_parameters(app):
    status, manifest = post_import(app, import_body(),
                                   {"Content-Type": "Application/JSON; charset=utf-8"})
    assert status == 201 and manifest["files_source"] == "import"


def test_a_skeleton_alone_imports_and_has_no_animation(app):
    status, manifest = post_import(app, import_body(files=sample_files("skeleton")))
    assert status == 201 and manifest["animation"] is None and manifest["skeleton"]
    assert app.client.get(f"/api/entries/{manifest['id']}/animation.json")[0] == 404


@pytest.mark.parametrize("name,data,ext", [("clip.webm", WEBM, "webm"), ("movie.mp4", MP4, "mp4"),
                                           ("whatever.bin", WEBM, "webm")])
def test_a_video_is_stored_by_its_magic_bytes_under_a_fixed_name(app, name, data, ext):
    status, manifest = post_import(app, import_body(files=sample_files("animation") + [
        video_file(name, data)]))
    assert status == 201 and manifest["video_uri"] == f"video.{ext}"
    status, headers, body = app.client.get(f"/api/entries/{manifest['id']}/video.{ext}")
    assert status == 200 and body == data
    assert headers["content-type"] == ("video/webm" if ext == "webm" else "video/mp4")
    assert manifest["provenance"]["video"]["bytes"] == len(data)


def test_dropped_names_never_build_a_path(app, seeded):
    files = [text_file("../../outside/animation.json", SAMPLE["animation"]),
             text_file("/etc/skeleton.json", SAMPLE["skeleton"]),
             text_file("..\\keyframes.json", SAMPLE["keyframes"])]
    status, manifest = post_import(app, import_body(files=files))
    assert status == 201
    folder = seeded / manifest["id"]
    assert sorted(p.name for p in folder.iterdir()) == [
        "animation.json", "keyframes.json", "manifest.json", "skeleton.json", "thumbnail.svg"]
    assert not (seeded.parent / "outside").exists()
    assert sorted(p.name for p in seeded.iterdir()) == sorted([m["id"] for m in MANIFESTS]
                                                              + [manifest["id"]])


def test_the_name_is_trimmed_like_record(app):
    assert post_import(app, import_body(name="  Wide   open  "))[1]["name"] == "Wide open"


def test_two_imports_one_after_the_other_both_succeed(app):
    results = [post_import(app, import_body()) for _ in range(2)]
    assert [status for status, _ in results] == [201, 201]
    assert len({m["id"] for _, m in results}) == 2


def test_the_visitor_cap_applies_after_an_import(serve_with):
    app = serve_with(max_recordings=1)
    first = post_import(app, import_body())[1]
    second = post_import(app, import_body())[1]
    assert app.client.get(f"/api/entries/{first['id']}")[0] == 404
    assert app.client.get(f"/api/entries/{second['id']}")[0] == 200
    assert entry_count(app) == N + 1


def test_a_failed_cap_after_an_import_is_logged_and_the_entry_stays(serve_with, monkeypatch, capsys):
    app = serve_with(max_recordings=1)

    def broken(*args, **kwargs):
        raise OSError("no listing")

    monkeypatch.setattr(server.catalog, "enforce_cap", broken)
    status, manifest = post_import(app, import_body())
    assert status == 201 and app.client.get(f"/api/entries/{manifest['id']}")[0] == 200
    assert "could not apply the cap of 1: no listing" in capsys.readouterr().err


def test_recorded_and_imported_entries_are_visitors_and_fixtures_are_not(app):
    recorded = app.client.post_json(VALID)[1]
    imported = post_import(app, import_body())[1]
    assert recorded["visitor"] is True and imported["visitor"] is True
    assert [m["id"] for m in app.client.get_json("/api/entries")[1]["entries"]
            if m.get("visitor")] == sorted([recorded["id"], imported["id"]],
                                           key=lambda i: i.split("-")[0])


# import: every 400

BAD_SHAPE = [
    (dict(name=...), "name"), (dict(name=""), "name"), (dict(name="   "), "name"),
    (dict(name=None), "name"), (dict(name=7), "name"), (dict(name="x" * 81), "name"),
    (dict(name="a\x00b"), "name"), (dict(name="line\nbreak"), "name"),
    (dict(category=...), "category"), (dict(category="yoga"), "category"),
    (dict(category=None), "category"), (dict(category="Dance"), "category"),
    (dict(category=["dance"]), "category"), (dict(category={"dance": 1}), "category"),
    (dict(files=...), "files"), (dict(files=None), "files"), (dict(files="animation.json"), "files"),
    (dict(files={}), "files"), (dict(files=[]), "files"), (dict(files=[1]), "files"),
    (dict(files=["x"]), "files"), (dict(files=[None]), "files"), (dict(files=[[]]), "files"),
    (dict(files=[{"text": "{}"}]), "files"), (dict(files=[{"name": 7, "text": "{}"}]), "files"),
    (dict(files=[{"name": "", "text": "{}"}]), "files"),
    (dict(files=[{"name": "x" * 256, "text": "{}"}]), "files"),
    (dict(files=[{"name": "a\nb.json", "text": "{}"}]), "files"),
    (dict(files=[{"name": "a\tb.json", "text": "{}"}]), "files"),
    (dict(files=[{"name": "a\x7fb.json", "text": "{}"}]), "files"),
    (dict(files=[{"name": "a\u0085b.json", "text": "{}"}]), "files"),
    (dict(files=[{"name": "some/dir\x00/a.json", "text": "{}"}]), "files"),
    (dict(files=[{"name": "a.json"}]), "files"),
    (dict(files=[{"name": "a.json", "text": "{}", "base64": "e30="}]), "files"),
    (dict(files=[{"name": "a.json", "text": 7}]), "files"),
    (dict(files=[{"name": "a.json", "base64": 7}]), "files"),
    (dict(files=[{"name": "a.json", "text": None, "base64": None}]), "files"),
    (dict(files=[text_file("a.json", {})] * 5), "too many files"),
    (dict(files=[{"name": "clip.webm", "base64": "!!not base64!!"}]), "clip.webm: not valid base64"),
    (dict(files=[{"name": "clip.webm", "base64": "abc"}]), "clip.webm: not valid base64"),
    (dict(files=[{"name": "clip.webm", "base64": "e30=\n"}]), "clip.webm: not valid base64"),
    (dict(files=[{"name": "clip.webm", "base64": "\u00e9\u00e9\u00e9\u00e9"}]),
     "clip.webm: not valid base64"),
    (dict(files=[text_file("broken.json", "{")]), "broken.json: is not valid JSON"),
    (dict(files=[text_file("animation.json", "\ud800")]), "animation.json: is not valid JSON"),
    # every message shows the importer's file label: the last path part, as the browser shows it
    (dict(files=[{"name": "some/where/clip.webm", "base64": "abc"}]), "clip.webm: not valid base64"),
    (dict(files=[{"name": "C:\\fakepath\\clip.webm", "base64": "abc"}]), "clip.webm: not valid base64"),
    (dict(files=[{"name": "  clip.webm  ", "base64": "abc"}]), "clip.webm: not valid base64"),
    (dict(files=[{"name": "x" * 200 + ".webm", "base64": "abc"}]),
     f"{'x' * importer.LABEL_MAX}: not valid base64"),
    (dict(files=[text_file("some/where/animation.json", "\ud800")]),
     "animation.json: is not valid JSON"),
    (dict(files=[text_file("a\ud800b.json", "\ud800")]), "a\ud800b.json: is not valid JSON"),
    (dict(files=[text_file("notes.json", "[1, 2]")]), None),
    (dict(files=sample_files("skeleton", "skeleton")), "two skeleton files"),
    (dict(files=sample_files("animation") + [text_file("again-animation.json", SAMPLE["animation"])]),
     "two animation files"),
    (dict(files=[video_file("clip.webm", b"hello, not a video")]),
     "clip.webm: not a WebM or MP4 video"),
    (dict(files=[video_file("a.webm"), video_file("b.mp4", MP4)] + sample_files("animation")),
     "two video files"),
    (dict(files=sample_files("keyframes")),
     "nothing to play: add an animation.json or a skeleton.json"),
    (dict(files=[video_file()]), "nothing to play: add an animation.json or a skeleton.json"),
    (dict(files=[text_file("animation.json", {"schema": "simon.animation/9", "fps": 30})]), None),
]


@pytest.mark.parametrize("changes,message", BAD_SHAPE)
def test_every_bad_import_is_a_400_with_a_plain_reason_and_writes_nothing(
        app, seeded, changes, message):
    status, body = post_import(app, import_body(**changes))
    assert status == 400, body
    if message is not None:
        assert body == {"error": message}
    else:
        assert body["error"] and body["error"] not in ("body", "files")
    assert nothing_new(seeded)
    assert app.srv.import_slots.acquire(blocking=False)         # the slot came back
    app.srv.import_slots.release()


def test_a_reader_message_is_served_as_the_error(app):
    files = [text_file("animation.json", {"schema": "simon.animation/9", "fps": 30})]
    assert post_import(app, import_body(files=files)) == (400, {"error": (
        'animation.json: schema "simon.animation/9" is not a version Part 6 reads '
        "(it reads simon.animation/1, simon.animation.v1)")})


def test_a_json_file_over_the_limit_is_too_large(app, monkeypatch):
    monkeypatch.setattr(importer, "MAX_JSON_BYTES", 50)
    assert post_import(app, import_body()) == (400, {"error": "animation.json: file too large"})


def test_a_video_over_the_limit_is_too_large(app, monkeypatch):
    monkeypatch.setattr(importer, "MAX_VIDEO_BYTES", 50)
    files = sample_files("animation") + [video_file()]
    assert post_import(app, import_body(files=files)) == (400, {"error": "clip.webm: file too large"})


@pytest.mark.parametrize("payload", [b"", b"not json", b"{", b"[]", b'"text"', b"42", b"null",
                                     b"\xff\xfe\x00", b"{'name': 'a'}"])
def test_a_body_that_is_not_a_json_object_is_400_body(app, seeded, payload):
    assert post_import(app, payload) == (400, {"error": "body"})
    assert nothing_new(seeded)


@pytest.mark.parametrize("headers", [{}, {"Content-Type": "text/plain"},
                                     {"Content-Type": "application/x-www-form-urlencoded"},
                                     {"Content-Type": "multipart/form-data; boundary=x"},
                                     {"Content-Type": "application/jsonp"}])
def test_an_import_needs_a_json_content_type(app, seeded, headers):
    assert post_import(app, import_body(), headers) == (400, {"error": "body"})
    assert nothing_new(seeded)


def post_head(length, path="/api/import"):
    """The request head of a JSON POST that promises `length` body bytes."""
    return (f"POST {path} HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
            f"Content-Length: {length}\r\n\r\n").encode()


def raw_post(port, head, body=b""):
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(head + body)
        s.shutdown(socket.SHUT_WR)          # the client is done sending, whatever it promised
        chunks = []
        while chunk := s.recv(65536):
            chunks.append(chunk)
    return b"".join(chunks)


@pytest.mark.parametrize("length", [None, "abc", "-5"])
def test_an_import_without_a_usable_content_length_is_400_body(app, length):
    extra = b"" if length is None else f"Content-Length: {length}\r\n".encode()
    reply = raw_post(app.port, b"POST /api/import HTTP/1.1\r\nHost: x\r\n"
                     b"Content-Type: application/json\r\n" + extra + b"\r\n")
    assert reply.startswith(b"HTTP/1.1 400") and b'{"error": "body"}' in reply


def test_a_body_that_stops_short_is_400_body(app):
    reply = raw_post(app.port, post_head(500), b'{"name": "cut off"')
    assert reply.startswith(b"HTTP/1.1 400") and b'{"error": "body"}' in reply


# import: 413 and 503

def test_the_import_body_cap_is_24_mib():
    assert server.MAX_IMPORT_BODY == 24 * 1024 * 1024 and server.MAX_BODY == 4096
    assert server.MAX_IMPORTS == 1 and server.BODY_SECONDS == 60


def test_a_body_over_the_cap_is_413_and_a_body_at_the_cap_is_not(app, seeded, monkeypatch):
    monkeypatch.setattr(server, "MAX_IMPORT_BODY", 2000)
    at_cap = b"x" * 2000
    assert post_import(app, at_cap) == (400, {"error": "body"})
    assert post_import(app, at_cap + b"x") == (413, {"error": "body too large"})
    assert post_import(app, b"x" * 50_000) == (413, {"error": "body too large"})
    assert nothing_new(seeded) and entry_count(app) == N
    assert app.client.get("/api/health")[0] == 200


def test_413_answers_before_the_body_is_read_and_closes_the_connection(app, monkeypatch):
    monkeypatch.setattr(server, "MAX_IMPORT_BODY", 2000)
    head = post_head(31457280)        # claims 30 MiB, sends 100 bytes
    began = time.monotonic()
    with socket.create_connection(("127.0.0.1", app.port), timeout=10) as s:
        s.sendall(head + b"x" * 100)
        s.settimeout(5)
        data = b""
        while b'"body too large"' not in data:
            chunk = s.recv(4096)
            assert chunk, "the connection closed without an answer"
            data += chunk
    assert data.startswith(b"HTTP/1.1 413") and b"Connection: close" in data
    assert time.monotonic() - began < 5


def test_the_body_is_read_in_chunks_never_in_one_read(app, monkeypatch):
    sizes = []
    real = server.Handler._read_body

    def spy(self, limit):
        read = self.rfile.read1
        self.rfile.read1 = lambda n=-1: (sizes.append(n), read(n))[1]
        return real(self, limit)

    monkeypatch.setattr(server.Handler, "_read_body", spy)
    body = json.dumps(import_body()).encode()
    assert len(body) > server.CHUNK
    assert post_import(app, body)[0] == 201
    assert sizes and max(sizes) <= server.CHUNK


def test_an_import_while_another_runs_is_503_busy_and_the_slot_returns(app, seeded):
    slots = app.srv.import_slots
    assert slots.acquire(blocking=False)
    assert not slots.acquire(blocking=False)                    # one slot, nothing else to take
    assert post_import(app, import_body()) == (503, {"error": "busy, try again"})
    assert post_import(app, b"x" * 200_000) == (503, {"error": "busy, try again"})
    assert nothing_new(seeded)
    slots.release()
    assert post_import(app, import_body())[0] == 201


def test_a_second_import_while_the_first_runs_is_503_and_the_first_still_succeeds(app, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    real = importer.prepare_import

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return real(*args, **kwargs)

    monkeypatch.setattr(importer, "prepare_import", slow)
    results = []
    first = threading.Thread(target=lambda: results.append(post_import(app, import_body())))
    first.start()
    assert entered.wait(5)
    assert post_import(app, import_body()) == (503, {"error": "busy, try again"})
    release.set()
    first.join(10)
    assert results[0][0] == 201
    assert post_import(app, import_body())[0] == 201            # the slot came back


def test_an_import_does_not_hold_up_reading_entries(app, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    real = importer.prepare_import

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return real(*args, **kwargs)

    monkeypatch.setattr(importer, "prepare_import", slow)
    worker = threading.Thread(target=lambda: post_import(app, import_body()))
    worker.start()
    assert entered.wait(5)
    began = time.monotonic()
    assert app.client.get("/api/health")[0] == 200 and app.client.get("/api/entries")[0] == 200
    assert time.monotonic() - began < 2
    release.set()
    worker.join(10)


def test_recording_and_importing_write_under_the_save_lock(app, monkeypatch):
    held = []
    real = server.importer.store_processed

    def spy(*args, **kwargs):
        held.append(("record", app.srv.save_lock.locked()))
        return real(*args, **kwargs)

    monkeypatch.setattr(server.importer, "store_processed", spy)
    real_commit = server.importer.commit_import

    def spy_commit(*args, **kwargs):
        held.append(("import", app.srv.save_lock.locked()))
        return real_commit(*args, **kwargs)

    monkeypatch.setattr(server.importer, "commit_import", spy_commit)
    assert app.client.post_json(VALID)[0] == 201
    assert post_import(app, import_body())[0] == 201
    assert held == [("record", True), ("import", True)]


def test_an_import_reads_its_files_outside_the_save_lock(app, monkeypatch):
    """Review R5: parsing and the readers run before the lock; only the write and the cap run in it."""
    held = {}
    for name in ("prepare_import", "commit_import"):
        real = getattr(server.importer, name)

        def spy(*args, _real=real, _name=name, **kwargs):
            held[_name] = app.srv.save_lock.locked()
            return _real(*args, **kwargs)

        monkeypatch.setattr(server.importer, name, spy)
    cap = []
    monkeypatch.setattr(server.CatalogServer, "apply_cap",
                        lambda self, keep_id: cap.append(self.save_lock.locked()))
    assert post_import(app, import_body())[0] == 201
    assert held == {"prepare_import": False, "commit_import": True} and cap == [True]


def test_a_bad_import_is_answered_while_the_save_lock_is_held_elsewhere(app, seeded):
    with app.srv.save_lock:
        assert post_import(app, import_body(files=[text_file("broken.json", "{")])) == (
            400, {"error": "broken.json: is not valid JSON"})
        assert post_import(app, import_body(name="  ")) == (400, {"error": "name"})
    assert nothing_new(seeded)


def test_a_good_import_waits_for_the_lock_only_to_write(app, monkeypatch):
    prepared = threading.Event()
    real = server.importer.prepare_import

    def spy(*args, **kwargs):
        result = real(*args, **kwargs)
        prepared.set()
        return result

    monkeypatch.setattr(server.importer, "prepare_import", spy)
    results = []
    with app.srv.save_lock:
        worker = threading.Thread(target=lambda: results.append(post_import(app, import_body())))
        worker.start()
        assert prepared.wait(5)                  # the files were read with the lock held elsewhere
        time.sleep(0.2)
        assert results == [] and entry_count(app) == N
    worker.join(10)
    assert results[0][0] == 201 and entry_count(app) == N + 1


# import: file names (AC-C07, review residual 7)

NAMES_THE_BROWSER_ALLOWS = ["a b.json", "a\u00a0b.json", "a\u200bb.json", "a\u3000b.json",
                            "a\u2028b.json", "caf\u00e9 \U0001f3c3.json", "a\ud800b.json",
                            " a.json", "some dir/my move.json"]


@pytest.mark.parametrize("name", NAMES_THE_BROWSER_ALLOWS)
def test_a_file_name_is_refused_only_for_a_control_character(name):
    items, bad = server.decode_files([{"name": name, "text": "{}"}])
    assert bad is None and items == [{"name": name, "data": b"{}"}]


@pytest.mark.parametrize("name", ["a\x00b", "a\tb", "a\nb", "a\rb", "a\x1fb", "a\x7fb",
                                  "a\x85b", "a\x9fb", "\x00", "dir/\x1b.json"])
def test_a_file_name_with_a_control_character_is_files(name):
    assert server.decode_files([{"name": name, "text": "{}"}]) == (None, "files")


@pytest.mark.parametrize("name", NAMES_THE_BROWSER_ALLOWS[:5] + ["some dir/my move.json"])
def test_a_file_whose_name_holds_a_space_like_character_imports(app, name):
    status, manifest = post_import(app, import_body(files=[text_file(name, SAMPLE["animation"])]))
    assert status == 201, manifest
    assert manifest["provenance"]["animation"]["original_name"] == importer.file_label(name)


@pytest.mark.parametrize("name", ["a\u00a0b.webm", "a\u200bb.webm", "x/y z.webm"])
def test_a_message_names_the_file_by_the_importers_label(app, name):
    status, body = post_import(app, import_body(files=[{"name": name, "base64": "abc"}]))
    assert (status, body) == (400, {"error": f"{importer.file_label(name)}: not valid base64"})


# import: strict JSON, nesting, a slow body (review B1, R3, R4, R6)

@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity", "1e400", "-1e400",
                                      "1" + "0" * 5000, "[1, 2, 1" + "0" * 400 + "]"], ids=short_id)
def test_a_json_constant_a_browser_cannot_parse_in_an_ignored_field_is_400_not_valid_json(
        app, seeded, constant):
    text = json.dumps(SAMPLE["animation"])[:-1] + f', "ignored": {constant}}}'
    status, body = post_import(app, import_body(files=[text_file("animation.json", text)]))
    assert (status, body) == (400, {"error": "animation.json: is not valid JSON"})
    assert nothing_new(seeded)


@pytest.mark.parametrize("number", ["1e400", "-1e400", "1" + "0" * 5000], ids=short_id)
def test_a_number_no_browser_can_read_in_the_request_body_is_400_body(app, seeded, number):
    payload = json.dumps(import_body()).encode()[:-1] + f', "extra": {number}}}'.encode()
    assert post_import(app, payload) == (400, {"error": "body"})
    assert nothing_new(seeded)


@pytest.mark.parametrize("number", ["1e400", "-1e400", "1" * 400], ids=["1e400", "-1e400", "400 digits"])
def test_a_number_no_browser_can_read_in_the_entry_body_is_400_body(app, seeded, number):
    status, _, data = app.client.post(json.dumps(VALID).encode()[:-1] + f', "extra": {number}}}'.encode())
    assert (status, json.loads(data)) == (400, {"error": "body"})
    assert nothing_new(seeded)


def test_nan_in_the_request_body_itself_is_400_body(app, seeded):
    payload = json.dumps(import_body()).encode()[:-1] + b', "extra": NaN}'
    assert post_import(app, payload) == (400, {"error": "body"})
    assert app.client.post_json(VALID)[0] == 201
    assert app.client.post(json.dumps(VALID).encode()[:-1] + b', "extra": Infinity}')[0] == 400
    assert len(list(seeded.iterdir())) == N + 1


@pytest.mark.parametrize("name,data", [("animation.json", SAMPLE["animation"]),
                                       ("skeleton.json", SAMPLE["skeleton"])])
def test_a_file_with_a_byte_order_mark_imports_over_http(app, name, data):
    text = "\ufeff" + json.dumps(data)
    status, manifest = post_import(app, import_body(files=[text_file(name, text)]))
    assert status == 201
    stored = (app.srv.root / manifest["id"] / name).read_bytes()
    assert stored.startswith(b"\xef\xbb\xbf") and validate.check_entry(app.srv.root / manifest["id"]) == []


def test_a_request_body_with_a_byte_order_mark_is_read(app):
    payload = b"\xef\xbb\xbf" + json.dumps(import_body()).encode()
    assert post_import(app, payload)[0] == 201


def test_a_deeply_nested_body_is_400_body_not_a_server_error(app, seeded, capsys):
    deep = b"[" * 200_000 + b"]" * 200_000
    assert post_import(app, deep) == (400, {"error": "body"})
    assert post_import(app, b'{"name": ' + deep + b"}") == (400, {"error": "body"})
    shallow_enough_for_the_entry_cap = b"[" * 2000 + b"]" * 2000       # the entry body is 4096 bytes at most
    status, _, data = app.client.post(shallow_enough_for_the_entry_cap)
    assert status == 400 and json.loads(data) == {"error": "body"}
    assert nothing_new(seeded) and "Traceback" not in capsys.readouterr().err
    assert app.client.get("/api/health")[0] == 200


def test_a_deeply_nested_file_is_400_not_valid_json(app, seeded):
    deep = "[" * 200_000
    assert post_import(app, import_body(files=[text_file("animation.json", deep)])) == (
        400, {"error": "animation.json: is not valid JSON"})
    assert nothing_new(seeded)


def read_until_closed(sock, seconds=10):
    sock.settimeout(seconds)
    data = b""
    while True:
        try:
            chunk = sock.recv(65536)
        except OSError:
            break
        if not chunk:
            break
        data += chunk
    return data


def test_a_body_that_does_not_arrive_in_time_is_408_and_the_connection_closes(
        app, seeded, monkeypatch):
    monkeypatch.setattr(server, "BODY_SECONDS", 0.5)
    head = post_head(5000)
    began = time.monotonic()
    with socket.create_connection(("127.0.0.1", app.port), timeout=10) as s:
        s.sendall(head + b'{"name": "slo')          # then nothing more
        data = read_until_closed(s)
    assert data.startswith(b"HTTP/1.1 408") and b'{"error": "body too slow"}' in data
    assert b"Connection: close" in data
    assert 0.4 < time.monotonic() - began < 5
    assert nothing_new(seeded)


def test_a_sender_that_trickles_bytes_is_cut_off_at_the_total_deadline(app, seeded, monkeypatch):
    monkeypatch.setattr(server, "BODY_SECONDS", 0.6)
    body = json.dumps(import_body()).encode()
    head = post_head(len(body))
    began = time.monotonic()
    with socket.create_connection(("127.0.0.1", app.port), timeout=10) as s:
        s.sendall(head)
        sent = 0
        s.settimeout(0.05)
        reply = b""
        while time.monotonic() - began < 8 and not reply:
            try:
                s.sendall(body[sent:sent + 1])         # one byte every 0.1 s: each read is "in time"
                sent += 1
            except OSError:
                break
            time.sleep(0.1)
            try:
                reply = s.recv(65536)
            except (TimeoutError, BlockingIOError):
                pass
        reply += read_until_closed(s, 2)
    assert reply.startswith(b"HTTP/1.1 408") and b"body too slow" in reply
    assert sent < len(body) and time.monotonic() - began < 5
    assert nothing_new(seeded)


def test_a_slow_body_gives_the_import_slot_back(app, monkeypatch):
    monkeypatch.setattr(server, "BODY_SECONDS", 0.3)
    head = post_head(5000)
    with socket.create_connection(("127.0.0.1", app.port), timeout=10) as s:
        s.sendall(head + b"{")
        assert read_until_closed(s).startswith(b"HTTP/1.1 408")
    monkeypatch.setattr(server, "BODY_SECONDS", 60)
    assert post_import(app, import_body())[0] == 201


def test_a_body_that_arrives_in_pieces_within_the_deadline_is_accepted(app):
    body = json.dumps(import_body()).encode()
    head = post_head(len(body))
    with socket.create_connection(("127.0.0.1", app.port), timeout=10) as s:
        s.sendall(head)
        for start in range(0, len(body), 3000):
            s.sendall(body[start:start + 3000])
            time.sleep(0.02)
        reply = b""
        s.settimeout(10)
        while b'"files_source": "import"' not in reply:
            chunk = s.recv(65536)
            assert chunk
            reply += chunk
    assert reply.startswith(b"HTTP/1.1 201")


def test_the_entry_body_has_the_same_deadline(app, monkeypatch):
    monkeypatch.setattr(server, "BODY_SECONDS", 0.4)
    head = post_head(100, "/api/entries")
    with socket.create_connection(("127.0.0.1", app.port), timeout=10) as s:
        s.sendall(head + b'{"name"')
        assert read_until_closed(s).startswith(b"HTTP/1.1 408")


# recording: the id is made fresh, retried when taken (moved from the removed catalog helper)

def test_a_recording_gets_another_id_when_the_first_is_taken(app, seeded, monkeypatch):
    ids = iter(["squat", "same-00000001", "other-00000002"])
    monkeypatch.setattr(server.catalog, "new_id", lambda name: next(ids))
    status, manifest = app.client.post_json(VALID)
    assert status == 201 and manifest["id"] == "same-00000001"
    status, manifest = app.client.post_json(VALID)
    assert status == 201 and manifest["id"] == "other-00000002"


def test_a_recording_gives_up_after_repeated_id_collisions(app, seeded, monkeypatch, capsys):
    monkeypatch.setattr(server.catalog, "new_id", lambda name: "squat")
    status, body = app.client.post_json(VALID)
    assert (status, body) == (500, {"error": "internal error"})
    assert "could not allocate an entry id" in capsys.readouterr().err and nothing_new(seeded)
