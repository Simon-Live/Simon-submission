"""part6/server.py: static files, the read API, entry files with Range, base path (AC-001, 002, 010)."""
import http.client
import json
import socket
import threading
import time

import pytest

from part6 import server


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


# health and list

def test_health_counts_entries(app):
    status, body = app.client.get_json("/api/health")
    assert (status, body) == (200, {"ok": True, "entries": 6})


def test_health_reports_zero_for_an_empty_catalog(tmp_path, start_server):
    app = start_server(tmp_path / "empty")
    assert app.client.get_json("/api/health") == (200, {"ok": True, "entries": 0})
    assert app.client.get_json("/api/entries") == (200, {"entries": []})


def test_health_follows_the_folders_on_every_request(app, seeded):
    import shutil
    shutil.rmtree(seeded / "squat")
    assert app.client.get_json("/api/health")[1]["entries"] == 5


def test_list_sorted_by_name_with_whole_manifests(app):
    status, headers, body = app.client.get("/api/entries")
    assert status == 200 and headers["content-type"] == "application/json"
    entries = json.loads(body)["entries"]
    assert [m["name"] for m in entries] == ["Arm wave", "Forward lunge", "Hip twist",
                                            "Jumping jack", "Side step", "Squat"]
    assert entries[-1]["files_source"] == "fixture" and entries[-1]["category"] == "exercise"


@pytest.mark.parametrize("query,expected", [
    ("q=lunge", ["forward-lunge"]),
    ("q=LUNGE+forward", ["forward-lunge"]),
    ("q=%20lunge%20", ["forward-lunge"]),
    ("q=zzz", []),
    ("category=dance", ["arm-wave", "hip-twist", "side-step"]),
    ("category=exercise", ["forward-lunge", "jumping-jack", "squat"]),
    ("q=step&category=dance", ["side-step"]),
    ("q=step&category=exercise", []),
    ("category=", ["arm-wave", "forward-lunge", "hip-twist", "jumping-jack", "side-step", "squat"]),
    ("q=", ["arm-wave", "forward-lunge", "hip-twist", "jumping-jack", "side-step", "squat"]),
])
def test_list_search_and_filter(app, query, expected):
    status, _, body = app.client.get(f"/api/entries?{query}")
    assert status == 200 and ids(body) == expected


@pytest.mark.parametrize("category", ["yoga", "Dance", "dances", "exercise%20", "1"])
def test_unknown_category_is_400(app, category):
    status, body = app.client.get_json(f"/api/entries?category={category}")
    assert (status, body) == (400, {"error": "category"})


def test_list_skips_an_invalid_entry(app, seeded):
    (seeded / "squat" / "manifest.json").write_text("{")
    assert "squat" not in ids(app.client.get("/api/entries")[2])
    assert app.client.get("/api/entries/squat")[0] == 404


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
    "/api/", "/api/health/x", "/api/entries/nope/animation.json"])
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
    assert c.get_json("/simon/api/health")[1] == {"ok": True, "entries": 6}
    assert c.get("/simon/")[2] == b"<!doctype html><title>t</title>"
    assert c.get("/simon/api/entries/squat/animation.json")[0] == 200
    assert c.get("/simon/api/entries?category=dance")[0] == 200
    status, body = c.post_json({"name": "Under base", "category": "dance", "duration_ms": 2000},
                               path="/simon/api/entries", prefix="")
    assert status == 201


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
    ("POST", "/"), ("PUT", "/index.html"), ("OPTIONS", "/api/entries"), ("DELETE", "/")])
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
