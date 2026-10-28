"""The HTTP server of the run app on a real socket (docs/specs/run-app.md AC-R07, AC-R08, AC-NFR-01..03, AC-NFR-05;
docs/specs/compare-mode.md AC-M02, AC-M03, AC-M04, AC-NFR-M1)."""

import base64
import contextlib
import copy
import hashlib
import http.client
import json
import socket
import threading
import time
from types import SimpleNamespace

import pytest

from conftest import ROOT
from part3 import cli, runapi, server

WEB = ROOT / "web"
BASE = "/simon-part-3/"
IMPORT_MAP = '{"imports": {"three": "./vendor/three.js"}}'
INLINE = "window.answer = 42;"
APP_HTML = (f'<!doctype html><html><head><script type="importmap">{IMPORT_MAP}</script></head><body>'
            f'<script type="module" src="app.js"></script><script>{INLINE}</script></body></html>')
SECRET = "SECRET-MARKER-NOT-FOR-VISITORS"


class Reply:
    def __init__(self, response, body):
        self.status, self.body = response.status, body
        self.headers = {name.lower(): value for name, value in response.getheaders()}

    def json(self):
        return json.loads(self.body)

    def error_code(self):
        return self.json()["error"]["code"]


class Client:
    def __init__(self, port, base):
        self.port, self.base = port, base

    def connect(self):
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)

    def raw(self, method, path, body=None, headers=None):
        conn = self.connect()
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return Reply(response, response.read())
        finally:
            conn.close()

    def get(self, rel, **kwargs):
        return self.raw("GET", self.base + rel, **kwargs)

    def post(self, rel, body=b"", headers=None):
        return self.raw("POST", self.base + rel, body=body, headers=headers)

    def run(self, query, body=b""):
        return self.post("api/run?" + query, body)


@contextlib.contextmanager
def serving(base=BASE, web_dir=None):
    app = server.AppServer(("127.0.0.1", 0), base, web_dir)
    thread = threading.Thread(target=app.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield Client(app.server_address[1], app.base)
    finally:
        app.shutdown()
        app.server_close()
        thread.join(5)


@pytest.fixture(scope="module")
def real():
    with serving() as client:
        yield client


@pytest.fixture
def site(tmp_path):
    """A server over a small web folder whose files, and the files that must not be served, are known."""
    web = tmp_path / "web"
    (web / "data").mkdir(parents=True)
    (web / "app.html").write_text(APP_HTML)
    (web / "index.html").write_text("<!doctype html><title>agreement</title>")
    (web / "compare.html").write_text("<!doctype html><title>compare</title>")
    (web / "app.js").write_text("export const ok = true;")
    (web / "app.css").write_text("body { margin: 0; }")
    (web / "data" / "demo.json").write_text('{"p95": 1.5}')
    (web / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (web / "mark.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (web / "notes.txt").write_text(SECRET)
    (web / "tool.py").write_text(SECRET)
    (web / ".hidden.json").write_text(SECRET)
    outside = tmp_path / "outside.json"
    outside.write_text(SECRET)
    (web / "link.json").symlink_to(outside)
    with serving(BASE, web) as client:
        yield client


@pytest.fixture
def clip(real_doc):
    doc = copy.deepcopy(real_doc)
    doc["frames"] = doc["frames"][:40]
    doc["note"] = "UPLOAD-MARKER-123"
    return doc


def hash_of(text):
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"


def csp_of(reply):
    return reply.headers["content-security-policy"]


def script_src(reply):
    return [part for part in csp_of(reply).split("; ") if part.startswith("script-src")][0].split()[1:]


# ---- routes and base path (AC-R07, AC-R08) -----------------------------------------------------

def test_pages_and_files_answer_under_the_base(site):
    page, agreement = site.get(""), site.get("agreement")
    assert (page.status, page.body.decode()) == (200, APP_HTML)
    assert page.headers["content-type"] == "text/html; charset=utf-8"
    assert (agreement.status, b"agreement" in agreement.body) == (200, True)
    assert site.get("app.js").body == b"export const ok = true;"
    assert site.get("data/demo.json").json() == {"p95": 1.5}


def test_the_base_without_a_slash_redirects(site):
    reply = site.raw("GET", BASE.rstrip("/"))
    assert (reply.status, reply.headers["location"]) == (308, BASE)


def test_outside_the_base_is_404_json(site):
    for path in ("/", "/api/health", "/app.js", "/simon-part-3x/", "/other/app.js", "/simon-part-3/../app.js"):
        reply = site.raw("GET", path)
        assert reply.status == 404 and reply.error_code() == "not_found", path
        assert reply.headers["content-type"] == "application/json"
    assert site.raw("POST", BASE.rstrip("/")).status == 404  # only GET is redirected


def test_the_default_base_serves_at_the_root(tmp_path):
    (tmp_path / "app.html").write_text("<p>root</p>")
    with serving("/", tmp_path) as client:
        assert client.get("").body == b"<p>root</p>"
        assert client.raw("GET", "/api/health").json() == {"ok": True, "samples": 7}
        assert client.raw("GET", "/simon-part-3/").status == 404


@pytest.mark.parametrize("given, expected", [("/", "/"), ("", "/"), ("simon-part-3", "/simon-part-3/"),
                                             ("/simon-part-3", "/simon-part-3/"), ("/a/b/", "/a/b/")])
def test_base_is_normalised(given, expected):
    assert server.normalise_base(given) == expected


def test_a_missing_app_page_is_404_and_the_rest_still_works(tmp_path):
    (tmp_path / "index.html").write_text("<p>agreement</p>")
    with serving(BASE, tmp_path) as client:
        assert client.get("").status == 404 and client.get("").error_code() == "not_found"
        assert client.get("agreement").body == b"<p>agreement</p>"
        assert client.get("api/health").json()["ok"] is True


def test_the_real_agreement_view_is_the_existing_index_page(real):
    reply = real.get("agreement")
    assert (reply.status, reply.body) == (200, (WEB / "index.html").read_bytes())
    assert real.get("data/demo.json").body == (WEB / "data" / "demo.json").read_bytes()


@pytest.mark.skipif(not (WEB / "app.html").exists(), reason="web/app.html is written by the page ticket")
def test_the_real_run_page_is_web_app_html(real):
    assert real.get("").body == (WEB / "app.html").read_bytes()


def test_every_allowed_file_of_web_is_served_as_is(real):
    files = [p for p in WEB.rglob("*") if p.is_file() and p.suffix in server.STATIC_TYPES]
    assert files
    for path in files:
        reply = real.get(path.relative_to(WEB).as_posix())
        assert reply.status == 200 and reply.body == path.read_bytes(), path


def test_query_strings_are_ignored_for_lookup(site):
    assert site.get("app.js?v=3&x=%2e%2e").status == 200
    assert site.get("api/health?x=1").json()["ok"] is True


def test_the_compare_page_is_web_compare_html_with_its_own_csp(real):
    reply = real.get("compare")
    assert (reply.status, reply.body) == (200, (WEB / "compare.html").read_bytes())
    assert reply.headers["content-type"] == "text/html; charset=utf-8" and reply.headers["cache-control"] == "no-cache"
    html = (WEB / "compare.html").read_text()
    block = html.split('<script type="importmap">')[1].split("</script>")[0]
    assert script_src(reply) == ["'self'", hash_of(block)]
    for rel in ("compare.js", "compare.css", "scene.js", "app.css", "controls.js"):
        assert real.get(rel).status == 200, rel


def test_the_shared_controls_module_is_served_as_javascript(real):
    # Both pages import it as an ES module; a wrong type would make the browser refuse it.
    reply = real.get("controls.js")
    assert (reply.status, reply.body) == (200, (WEB / "controls.js").read_bytes())
    assert reply.headers["content-type"] == "text/javascript; charset=utf-8"
    assert reply.headers["x-content-type-options"] == "nosniff"


def test_the_compare_page_route_follows_the_base_path(site):
    assert (site.get("compare").status, b"compare" in site.get("compare").body) == (200, True)
    assert site.get("compare.html").body == site.get("compare").body
    assert site.raw("GET", "/compare").status == 404 and site.raw("GET", "/simon-part-3x/compare").status == 404


def test_api_health_and_samples(real):
    assert real.get("api/health").json() == {"ok": True, "samples": 7}
    assert real.get("api/samples").json() == {"samples": runapi.samples()}


def test_head_has_the_headers_and_no_body(site):
    head, full = site.raw("HEAD", BASE + "app.js"), site.get("app.js")
    assert head.status == 200 and head.body == b""
    assert head.headers["content-length"] == full.headers["content-length"]


def test_wrong_method_on_a_known_path_is_405(site):
    for method, rel, allow in [("POST", "", "GET, HEAD"), ("GET", "api/run", "POST"), ("POST", "api/health", "GET, HEAD"),
                               ("PUT", "app.js", "GET, HEAD"), ("DELETE", "api/samples", "GET, HEAD"),
                               ("OPTIONS", "agreement", "GET, HEAD"), ("GET", "api/compare", "POST"),
                               ("PUT", "api/compare", "POST"), ("POST", "compare", "GET, HEAD")]:
        reply = site.raw(method, BASE + rel)
        assert reply.status == 405 and reply.error_code() == "method", (method, rel)
        assert reply.headers["allow"] == allow
    assert site.raw("POST", BASE + "nothing-here").status == 404


def test_an_unknown_method_gets_json_not_html(site):
    reply = site.raw("BREW", BASE)
    assert reply.status == 501 and reply.error_code() == "bad_request"
    assert reply.headers["content-type"] == "application/json"


def test_a_port_in_use_is_reported(capsys):
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        assert server.main(["--port", str(held.getsockname()[1])]) == 1
    assert "cannot listen" in capsys.readouterr().err


# ---- AC-NFR-01: no request path reaches the filesystem -----------------------------------------

@pytest.mark.parametrize("path", [
    BASE + "../part3/cli.py", BASE + "%2e%2e%2fpart3%2fcli.py", BASE + "..%2fpart3%2fcli.py",
    BASE + "%2e%2e/part3/cli.py", BASE + "..\\part3\\cli.py", BASE + "%5c..%5cpart3%5ccli.py",
    BASE + "vendor/../../part3/cli.py", BASE + "..%252fpart3%252fcli.py", BASE + "....//part3/cli.py",
    BASE + "../../../../etc/passwd", BASE + "/etc/passwd", "/etc/passwd", BASE + "part3/cli.py",
    BASE + "fixtures/input/part2-single/pose3d.json", BASE + "app.js%00.png", BASE + "%2e%2e/",
    f"http://127.0.0.1{BASE}../part3/cli.py", BASE + "app%2ejs", BASE + "vendor/three/LICENSE",
    BASE + "vendor/three/VERSION", BASE + "vendor//three/three.module.js",
])
def test_traversal_attempts_are_404(real, path):
    reply = real.raw("GET", path)
    assert reply.status == 404 and reply.error_code() == "not_found"
    assert b"import" not in reply.body and b"root:" not in reply.body


def test_only_allowed_extensions_regular_files_are_served(site):
    for rel in ("notes.txt", "tool.py", ".hidden.json", "link.json", "data/", "data", "missing.js"):
        reply = site.get(rel)
        assert reply.status == 404 and SECRET.encode() not in reply.body, rel


def test_content_types_follow_the_extension(site):
    kinds = {"app.js": "text/javascript; charset=utf-8", "app.css": "text/css; charset=utf-8",
             "data/demo.json": "application/json", "logo.png": "image/png", "mark.svg": "image/svg+xml",
             "index.html": "text/html; charset=utf-8"}
    for rel, kind in kinds.items():
        assert site.get(rel).headers["content-type"] == kind, rel


# ---- AC-NFR-03: headers ------------------------------------------------------------------------

def test_every_response_has_nosniff_and_no_referrer(site):
    replies = [site.get(""), site.get("app.js"), site.get("api/health"), site.get("missing"), site.get("api/run"),
               site.raw("GET", BASE.rstrip("/")), site.raw("GET", "/elsewhere"), site.run("sample=take-1"),
               site.run("flip=bad&sample=take-1"), site.raw("BREW", BASE), site.get("api/compare"),
               site.post("api/compare", b"{}"), site.run("sample=take-1&body=file:/etc/passwd")]
    for reply in replies:
        assert reply.headers["x-content-type-options"] == "nosniff"
        assert reply.headers["referrer-policy"] == "no-referrer"


def test_cache_headers_api_no_store_static_no_cache(site):
    for rel in ("api/health", "api/samples", "missing", "api/run", "api/compare"):
        assert site.get(rel).headers["cache-control"] == "no-store", rel
    assert site.run("sample=take-1").headers["cache-control"] == "no-store"
    assert site.post("api/compare", b"{}").headers["cache-control"] == "no-store"
    for rel in ("", "app.js", "app.css", "data/demo.json", "logo.png"):
        assert site.get(rel).headers["cache-control"] == "no-cache", rel


def test_html_csp_lists_every_inline_script_hash_and_not_the_external_one(site):
    page = site.get("")
    assert script_src(page) == ["'self'", hash_of(IMPORT_MAP), hash_of(INLINE)]
    csp = csp_of(page)
    for directive in ("default-src 'self'", "style-src 'self' 'unsafe-inline'", "img-src 'self' data: blob:",
                      "connect-src 'self'", "object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'",
                      "form-action 'self'"):
        assert directive in csp.split("; ")
    assert script_src(site.get("agreement")) == ["'self'"]
    for rel in ("app.js", "api/health", "data/demo.json"):
        assert "content-security-policy" not in site.get(rel).headers


def test_the_real_index_page_csp_hash_matches_its_import_map(real):
    html = (WEB / "index.html").read_text()
    block = html.split('<script type="importmap">')[1].split("</script>")[0]
    assert script_src(real.get("agreement")) == ["'self'", hash_of(block)]


@pytest.mark.skipif(not (WEB / "app.html").exists(), reason="web/app.html is written by the page ticket")
def test_the_real_run_page_csp_covers_each_inline_script(real):
    html = (WEB / "app.html").read_text()
    inline = [part.split(">", 1)[1] for part in html.split("<script")[1:] if "src=" not in part.split(">")[0]]
    assert script_src(real.get("")) == ["'self'", *[hash_of(block.split("</script>")[0]) for block in inline]]


# ---- AC-NFR-02: limits -------------------------------------------------------------------------

def test_a_post_without_content_length_is_411(real):
    conn = real.connect()
    conn.putrequest("POST", BASE + "api/run?sample=take-1")
    conn.endheaders()
    response = conn.getresponse()
    assert (response.status, json.loads(response.read())["error"]["code"]) == (411, "length_required")
    conn.close()


def post_head(client, *headers, query=""):
    """A POST to api/run whose request line and chosen headers are sent; the caller sends any body."""
    conn = client.connect()
    conn.putrequest("POST", BASE + "api/run" + query)
    for header in headers:
        conn.putheader(*header)
    conn.endheaders()
    return conn


def answer(conn):
    response = conn.getresponse()
    return response.status, json.loads(response.read())["error"]["code"], response


@pytest.mark.parametrize("value", ["abc", "-5", "1e3", "1 2", "0x10", "", "9" * 40])
def test_a_content_length_that_is_not_digits_is_400(real, value):
    conn = post_head(real, ("Content-Length", value), query="?sample=take-1")
    assert answer(conn)[:2] == (400, "bad_request")
    conn.close()


def test_a_chunked_body_is_411(real):
    conn = post_head(real, ("Transfer-Encoding", "chunked"), query="?sample=take-1")
    assert answer(conn)[:2] == (411, "length_required")
    conn.close()


MIB = 1024 * 1024


def test_the_limits_are_the_documented_ones():
    """AC-M03: 16 MiB uploads, a 32 MiB drain, a 60 s body deadline; the other guards keep their values."""
    assert (server.MAX_BODY, server.DRAIN_MAX, server.BODY_TIMEOUT_S) == (16 * MIB, 32 * MIB, 60.0)
    assert (server.SOCKET_TIMEOUT_S, server.HEADER_DEADLINE_S, server.MAX_CONNECTIONS, server.MAX_RUNS) == (
        15.0, 20.0, 16, 2)
    assert server.RESERVED_CONNECTIONS == 1 and server.RESERVE_HEAD_S == 2.0


def test_a_body_over_16_mib_is_read_and_discarded_then_413_with_close(real):
    """AC-M03: 16 MiB + 1 is refused with the plain text, whichever route it is posted to (residual 11: per route)."""
    for rel, text in (("api/run?name=big.json", "This file is over 16 MB. Choose a smaller pose3d.json file."),
                      ("api/compare", "This compare request is over 16 MB.")):
        reply = real.post(rel, b"x" * (server.MAX_BODY + 1))
        assert reply.status == 413 and reply.error_code() == "too_large", rel
        assert reply.headers["connection"] == "close"
        assert reply.json()["error"]["message"] == text
        assert reply.json()["error"]["field"] is None


def test_a_body_of_3_mib_is_no_longer_too_large(real):
    reply = real.post("api/run?name=big.json", b"x" * (3 * MIB))
    assert (reply.status, reply.error_code()) == (400, "not_json")


def test_exactly_32_mib_is_still_discarded_before_the_413(real):
    reply = real.post("api/run", b"x" * server.DRAIN_MAX)
    assert (reply.status, reply.error_code()) == (413, "too_large")


def test_beyond_32_mib_the_413_comes_without_reading_the_body(real):
    conn = post_head(real, ("Content-Length", str(server.DRAIN_MAX + 1)))  # no body is ever sent
    status, code, response = answer(conn)
    assert (status, code, response.getheader("Connection")) == (413, "too_large", "close")
    conn.close()


def test_a_stalled_oversize_body_gets_the_413_after_the_body_timeout(monkeypatch):
    monkeypatch.setattr(server, "BODY_TIMEOUT_S", 0.4)
    with serving() as client:
        conn = post_head(client, ("Content-Length", str(server.MAX_BODY + 1)))
        started = time.perf_counter()
        assert answer(conn)[:2] == (413, "too_large")
        assert 0.3 < time.perf_counter() - started < 3
        conn.close()


def test_exactly_16_mib_is_accepted_for_reading(real):
    """AC-M03: the cap is on Content-Length over 16 MiB, so exactly 16 MiB is read and judged on its content."""
    reply = real.post("api/run", b" " * server.MAX_BODY)
    assert reply.status == 400 and reply.error_code() == "not_json"
    compared = real.post("api/compare", b" " * server.MAX_BODY)
    assert compared.status == 400 and compared.error_code() == "compare_shape"


def test_a_client_that_goes_silent_mid_upload_is_dropped_at_the_socket_timeout_not_the_body_deadline(monkeypatch):
    monkeypatch.setattr(server, "SOCKET_TIMEOUT_S", 0.5)
    monkeypatch.setattr(server, "BODY_TIMEOUT_S", 30.0)
    with serving() as client:
        conn = post_head(client, ("Content-Length", str(8 * MIB)))
        conn.send(b"{" * 1000)  # a start, then silence
        started = time.perf_counter()
        assert answer(conn)[:2] == (400, "bad_request")
        assert 0.4 < time.perf_counter() - started < 5
        conn.close()


def test_a_stalled_upload_is_answered_400_within_the_body_timeout_while_health_keeps_answering(monkeypatch):
    assert server.SOCKET_TIMEOUT_S == 15.0 and server.BODY_TIMEOUT_S == 60.0 and server.MAX_CONNECTIONS == 16
    monkeypatch.setattr(server, "BODY_TIMEOUT_S", 0.6)
    with serving() as client:
        conn = post_head(client, ("Content-Length", "500"))
        conn.send(b"{")
        started = time.perf_counter()
        assert client.get("api/health").status == 200  # a stalled upload does not block other requests
        assert answer(conn)[:2] == (400, "bad_request")
        assert time.perf_counter() - started < 3
        conn.close()
        deadline = time.monotonic() + 3
        while client.run("sample=take-1").status != 200 and time.monotonic() < deadline:
            time.sleep(0.05)  # the stalled upload's run slot comes back
        assert client.run("sample=take-1").status == 200


def test_a_connection_that_sends_nothing_is_dropped_after_the_socket_timeout(monkeypatch):
    monkeypatch.setattr(server, "SOCKET_TIMEOUT_S", 0.5)
    with serving() as client:
        silent = socket.create_connection(("127.0.0.1", client.port))
        silent.settimeout(5)
        started = time.perf_counter()
        assert client.get("api/health").status == 200
        assert silent.recv(100) == b""  # the server closed it
        assert time.perf_counter() - started < 3
        silent.close()


def test_a_connection_over_the_cap_and_the_reserve_gets_busy_quickly_and_the_cap_frees_up(monkeypatch):
    monkeypatch.setattr(server, "MAX_CONNECTIONS", 2)
    with serving() as client:
        held = [socket.create_connection(("127.0.0.1", client.port)) for _ in range(3)]  # 2 general slots + the reserve
        time.sleep(0.2)  # let the server pick all three up
        started = time.perf_counter()
        reply = client.get("api/health")
        assert (reply.status, reply.error_code()) == (503, "busy")
        assert time.perf_counter() - started < 2
        assert reply.headers["x-content-type-options"] == "nosniff"
        for sock in held:
            sock.close()
        deadline = time.monotonic() + 3
        while client.get("api/health").status != 200 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert client.get("api/health").status == 200


def stall(client, count):
    """`count` connections that open and then say nothing, until the test closes them."""
    return [socket.create_connection(("127.0.0.1", client.port)) for _ in range(count)]


def test_health_answers_and_everything_else_is_busy_while_sixteen_clients_stall():
    assert server.MAX_CONNECTIONS == 16 and server.RESERVED_CONNECTIONS == 1
    with serving() as client:
        stalled = stall(client, server.MAX_CONNECTIONS)
        try:
            time.sleep(0.3)  # let the server pick all sixteen up
            for rel in ("api/health", "api/health?x=1"):
                health = client.get(rel)
                assert (health.status, health.json()) == (200, {"ok": True, "samples": 7}), rel
                assert health.headers["x-content-type-options"] == "nosniff"
            for busy in (client.run("sample=take-1"), client.run("name=a.json", b"x" * 30000),
                         client.get("api/samples"), client.get(""), client.raw("HEAD", BASE + "api/health/")):
                assert busy.status == 503
            assert client.run("sample=take-1").error_code() == "busy"
            assert client.run("name=a.json", b"x" * 30000).error_code() == "busy"  # the answer, not a reset
            assert client.get("api/health").status == 200  # the reserve is free again after each answer
        finally:
            for sock in stalled:
                sock.close()
        deadline = time.monotonic() + 3
        while client.run("sample=take-1").status != 200 and time.monotonic() < deadline:
            time.sleep(0.05)  # the general slots come back
        assert client.run("sample=take-1").status == 200


def test_a_silent_client_in_the_reserve_is_dropped_after_the_short_head_deadline(monkeypatch):
    monkeypatch.setattr(server, "MAX_CONNECTIONS", 1)
    monkeypatch.setattr(server, "RESERVE_HEAD_S", 0.5)
    with serving() as client:
        general = stall(client, 1)
        time.sleep(0.2)
        silent = stall(client, 1)[0]  # the next connection lands in the reserve
        silent.settimeout(5)
        started = time.perf_counter()
        time.sleep(0.2)
        assert client.get("api/health").error_code() == "busy"  # the reserve is taken: turned away at once
        assert silent.recv(100) == b""  # the server closed it
        assert 0.4 < time.perf_counter() - started < 3
        deadline = time.monotonic() + 3
        while client.get("api/health").status != 200 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert client.get("api/health").status == 200  # the reserve is free again
        silent.close()
        general[0].close()


def trickle(client, first, rest, gap, limit_s):
    """Send `first` at once, then `rest` one byte every `gap` seconds while listening.
    Returns (what the server sent, seconds taken)."""
    sock = socket.create_connection(("127.0.0.1", client.port))
    heard, started = b"", time.perf_counter()
    try:
        sock.sendall(first)
        sock.settimeout(gap)
        for i in range(len(rest)):
            if time.perf_counter() - started > limit_s:
                break
            try:
                sock.send(rest[i:i + 1])
                chunk = sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            heard += chunk
            sock.settimeout(2)
            while chunk:  # an answer has started: read it to the end
                chunk = sock.recv(65536)
                heard += chunk
            break
    finally:
        sock.close()
    return heard, time.perf_counter() - started


def test_a_header_trickle_is_dropped_at_the_total_deadline(monkeypatch):
    monkeypatch.setattr(server, "HEADER_DEADLINE_S", 0.8)  # SOCKET_TIMEOUT_S stays 15: every byte arrives in time
    with serving() as client:
        head = f"GET {BASE}api/health HTTP/1.0\r\nX-Slow: ".encode()  # the blank line that ends the head never comes
        heard, seconds = trickle(client, b"", head + b"a" * 400, gap=0.15, limit_s=5)
        assert heard == b"" and 0.7 < seconds < 3  # closed without an answer, near the deadline and not at the limit
        assert client.get("api/health").status == 200


def test_a_request_line_trickle_is_dropped_at_the_total_deadline(monkeypatch):
    monkeypatch.setattr(server, "HEADER_DEADLINE_S", 0.8)
    with serving() as client:
        heard, seconds = trickle(client, b"", f"GET {BASE}".encode() + b"a" * 400, gap=0.15, limit_s=5)
        assert heard == b"" and 0.7 < seconds < 3


def test_a_slow_but_complete_head_inside_the_deadline_is_served(monkeypatch):
    monkeypatch.setattr(server, "HEADER_DEADLINE_S", 3.0)
    with serving() as client:
        head = f"GET {BASE}api/health HTTP/1.0\r\n\r\n".encode()
        heard, seconds = trickle(client, b"", head, gap=0.02, limit_s=5)  # about 0.8 s in all
        assert heard.startswith(b"HTTP/1.0 200") and b'"ok": true' in heard


def test_a_body_trickle_is_answered_400_at_the_total_body_deadline(monkeypatch):
    monkeypatch.setattr(server, "BODY_TIMEOUT_S", 0.8)
    with serving() as client:
        head = f"POST {BASE}api/run?name=a.json HTTP/1.0\r\nContent-Length: 500\r\n\r\n".encode()
        heard, seconds = trickle(client, head, b"{" * 400, gap=0.15, limit_s=5)
        assert heard.startswith(b"HTTP/1.0 400") and b'"bad_request"' in heard
        assert 0.7 < seconds < 3  # one byte every 0.15 s never reset the 0.8 s body deadline


def test_the_run_slot_is_taken_before_the_body_is_read(monkeypatch):
    monkeypatch.setattr(server, "MAX_RUNS", 1)
    monkeypatch.setattr(server, "BODY_TIMEOUT_S", 1.5)
    with serving() as client:
        slow = post_head(client, ("Content-Length", "500"))  # holds the only slot while its body is awaited
        slow.send(b"{")
        time.sleep(0.2)
        started = time.perf_counter()
        busy = client.run("sample=take-1")
        assert (busy.status, busy.error_code()) == (503, "busy")
        assert time.perf_counter() - started < 1.0  # answered at once, not after the slow upload gives up
        assert client.get("api/health").status == 200  # health never takes a run slot
        slow.close()


def test_a_cross_site_post_is_403_and_other_fetch_sites_pass(real, clip):
    body = json.dumps(clip).encode()
    refused = real.post("api/run?name=a.json", body, headers={"Sec-Fetch-Site": "cross-site"})
    assert (refused.status, refused.error_code()) == (403, "cross_site")
    assert refused.json()["error"]["message"] == "This request came from another site and was refused."
    assert real.get("api/health", headers={"Sec-Fetch-Site": "cross-site"}).status == 200  # reads are not refused
    for site_value in ("same-origin", "same-site", "none", "Same-Origin"):
        ok = real.post("api/run?sample=take-1", headers={"Sec-Fetch-Site": site_value})
        assert ok.status == 200, site_value
    assert real.post("api/run?sample=take-1", headers={"Sec-Fetch-Site": "CROSS-SITE"}).status == 403


def test_a_non_finite_metric_is_null_in_strict_json(real, monkeypatch):
    monkeypatch.setattr(runapi, "bone_variation", lambda *args: float("nan"))

    def refuse(constant):
        raise AssertionError(f"{constant} in the response")

    metrics = json.loads(real.run("sample=take-1").body, parse_constant=refuse)["metrics"]
    assert metrics["bone_length_variation_output"] is None


def slow_process(monkeypatch, gate):
    """Make the pipeline wait on `gate`; returns a semaphore released once per run that has started."""
    entered, real_process = threading.Semaphore(0), cli.process

    def slow(*args, **kwargs):
        entered.release()
        gate.wait(10)
        return real_process(*args, **kwargs)

    monkeypatch.setattr(cli, "process", slow)
    return entered


def test_a_third_concurrent_run_is_busy_and_the_slots_come_back(real, monkeypatch):
    gate = threading.Event()
    entered = slow_process(monkeypatch, gate)
    results = []
    workers = [threading.Thread(target=lambda: results.append(real.run("sample=take-1"))) for _ in range(2)]
    for worker in workers:
        worker.start()
    assert all(entered.acquire(timeout=5) for _ in range(2))
    busy = real.run("sample=take-2")
    assert (busy.status, busy.error_code()) == (503, "busy")
    assert busy.json()["error"]["message"] == "The server is busy. Try again in a moment."
    assert real.get("api/health").status == 200  # the server still answers while two runs are busy
    gate.set()
    for worker in workers:
        worker.join(10)
    assert [r.status for r in results] == [200, 200]
    assert real.run("sample=take-3").status == 200


def test_a_run_past_the_timeout_is_503_and_keeps_its_slot_until_it_ends(monkeypatch):
    monkeypatch.setattr(server, "RUN_TIMEOUT_S", 0.3)
    monkeypatch.setattr(server, "MAX_RUNS", 1)
    gate = threading.Event()
    entered = slow_process(monkeypatch, gate)
    with serving() as client:
        started = time.perf_counter()
        slow = client.run("sample=take-1")
        assert entered.acquire(timeout=5)
        assert time.perf_counter() - started < 3
        assert (slow.status, slow.error_code()) == (503, "timeout")
        assert slow.json()["error"]["message"] == "The run took too long and was stopped."
        assert client.run("sample=take-2").error_code() == "busy"  # the stuck thread still holds the only slot
        gate.set()
        deadline = time.monotonic() + 5
        while client.run("sample=take-2").status != 200 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert client.run("sample=take-2").status == 200


def test_a_pipeline_exception_is_500_without_a_traceback(real, monkeypatch, capsys):
    def explode(*args, **kwargs):
        raise RuntimeError("secret detail at /home/someone/file.py")
    monkeypatch.setattr(cli, "process", explode)
    reply = real.run("sample=take-1")
    assert (reply.status, reply.error_code()) == (500, "internal")
    for leaked in (b"Traceback", b"RuntimeError", b"secret", b"/home/"):
        assert leaked not in reply.body
    assert "Traceback" in capsys.readouterr().err


# ---- AC-R02, AC-R04, AC-R05 over HTTP ----------------------------------------------------------

def test_a_sample_run_over_http_returns_the_cli_text(real, tmp_path):
    reply = real.run("sample=part2-squat&flip=auto")
    body = reply.json()
    assert reply.status == 200 and body["ok"] is True and body["source"]["id"] == "part2-squat"
    status, direct = runapi.handle("part2-squat", "auto", None, b"")
    assert (status, body["skeleton_text"]) == (200, direct["skeleton_text"])


@pytest.mark.parametrize("sample_id", ["part2-squat", "take-1", "take-2", "take-3", "take-4", "take-1-mirrored",
                                       "armraise-control"])
def test_every_sample_runs_over_http_in_under_two_seconds(real, sample_id):
    started = time.perf_counter()
    reply = real.run(f"sample={sample_id}")
    assert reply.status == 200 and time.perf_counter() - started < 2.0


def test_the_flip_defaults_to_auto(real):
    assert real.run("sample=take-1-mirrored").json()["metrics"]["mirror"]["applied"] is True
    assert real.run("sample=take-1-mirrored&flip=off").json()["metrics"]["mirror"]["applied"] is False


def test_a_good_upload_runs_and_shows_its_name(real, clip):
    raw = json.dumps(clip).encode()
    reply = real.run("flip=auto&name=caf%C3%A9%20clip.json", raw)
    body = reply.json()
    assert reply.status == 200
    assert body["source"] == {"kind": "upload", "id": None, "name": "café clip.json", "bytes": len(raw),
                              "sha256": hashlib.sha256(raw).hexdigest()}
    assert body["metrics"]["frames"] == 40


@pytest.mark.parametrize("query, body, status, code", [
    ("sample=take-1&flip=sideways", b"", 400, "bad_flip"),
    ("sample=take-99", b"", 404, "unknown_sample"),
    ("", b"", 400, "no_input"),
    ("sample=take-1", b"{}", 400, "both_inputs"),
    ("name=a.json", b"not json", 400, "not_json"),
    ("a=1&" * 30 + "sample=take-1", b"", 400, "bad_request"),
])
def test_error_codes_over_http(real, query, body, status, code):
    reply = real.run(query, body)
    assert (reply.status, reply.error_code()) == (status, code)
    assert reply.json()["error"]["field"] is None
    assert b"Traceback" not in reply.body


def test_a_contract_break_over_http_names_the_field(real, clip):
    del clip["frames"][0]["people"][0]["joints"]["nose"]["conf"]
    reply = real.run("name=bad.json", json.dumps(clip).encode())
    error = reply.json()["error"]
    assert (reply.status, error["code"]) == (422, "contract")
    assert error["field"] == "pose3d.frames[0].people[0].joints.nose.conf"
    assert error["message"].startswith("This file is not a valid pose3d.json: pose3d.frames[0].people[0]")


def test_the_first_value_of_a_repeated_query_field_wins(real):
    assert real.run("sample=take-1&sample=take-2").json()["source"]["id"] == "take-1"


# ---- the log line ------------------------------------------------------------------------------

def test_one_log_line_per_request_without_the_query_or_the_upload(real, clip, capsys):
    capsys.readouterr()
    real.get("api/health?token=hidden-query-value")
    real.run("name=private-name.json", json.dumps(clip).encode())
    lines = [line for line in capsys.readouterr().err.splitlines() if line.strip()]
    assert len(lines) == 2
    health, upload = lines
    assert health.split()[1:5] == ["GET", BASE + "api/health", "200", health.split()[4]]
    assert health.split()[4].endswith("ms") and health.endswith("127.0.0.1")
    assert upload.split()[1:4] == ["POST", BASE + "api/run", "200"]
    assert "upload=" in upload and "sha256=" in upload
    for hidden in ("hidden-query-value", "private-name", "UPLOAD-MARKER-123", "frames"):
        assert not any(hidden in line for line in lines)


def test_the_client_is_the_forwarded_address_only_from_a_loopback_peer(real, capsys):
    capsys.readouterr()
    real.get("api/health", headers={"X-Forwarded-For": "203.0.113.9"})
    real.get("api/health", headers={"X-Forwarded-For": "evil\x1b[31m; rm -rf"})
    first, second = capsys.readouterr().err.splitlines()
    assert first.endswith(" 203.0.113.9") and second.endswith(" 127.0.0.1")


@pytest.mark.parametrize("peer, forwarded, expected", [
    ("198.51.100.4", "203.0.113.9", "198.51.100.4"), ("127.0.0.1", "203.0.113.9, 10.0.0.1", "203.0.113.9"),
    ("::1", "2001:db8::7", "2001:db8::7"), ("127.0.0.1", None, "127.0.0.1"), ("127.0.0.1", "nonsense!", "127.0.0.1"),
    ("not-an-address", "203.0.113.9", "not-an-address")])
def test_client_address_rules(peer, forwarded, expected):
    headers = {} if forwarded is None else {"X-Forwarded-For": forwarded}
    handler = SimpleNamespace(client_address=(peer, 5000), headers=headers)
    assert server.Handler._client(handler) == expected
