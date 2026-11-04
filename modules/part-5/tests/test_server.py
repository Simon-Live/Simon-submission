"""part5.server: the HTTP layer over api.handle and web/, on a real socket (127.0.0.1, free port)."""
import gzip
import http.client
import json
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from part5 import api, server

ROOT = Path(__file__).resolve().parent.parent
LABELS = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
FOOT_OUT = next(t["take_id"] for t in LABELS["takes"] if t["set"] == "exercise" and t["angle"] == "front"
                and t["lighting"] == "good" and [f["type"] for f in t["faults"]] == ["foot_out"])
PAIR = {"expected": {"sample": "exercise"}, "follower": {"sample": FOOT_OUT}}


@pytest.fixture(scope="module", params=["/simon-part-5/", "/"])
def base(request):
    httpd = server.make_server("127.0.0.1", 0, request.param)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.base_path, httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def fetch(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, response, data


def test_the_page_loads_at_the_base_path(base):
    path, port = base
    status, response, data = fetch(port, "GET", path)
    assert status == 200 and response.getheader("Content-Type").startswith("text/html")
    assert b"<title>Compare your take with the example</title>" in data


def test_static_files_get_their_content_types(base):
    path, port = base
    types = {name: fetch(port, "GET", path + name)[1].getheader("Content-Type")
             for name in ("app.js", "api.js", "style.css", "icon.svg")}
    assert types["app.js"].startswith("text/javascript") and types["api.js"].startswith("text/javascript")
    assert types["style.css"].startswith("text/css") and types["icon.svg"] == "image/svg+xml"


def test_the_base_path_without_its_slash_redirects_to_it(base):
    path, port = base
    if path == "/":
        pytest.skip("the root has no slash-less form")
    status, response, _ = fetch(port, "GET", path.rstrip("/"))
    assert status == 301 and response.getheader("Location") == path


def test_health_and_samples_answer_under_the_base_path_only(base):
    path, port = base
    status, _, data = fetch(port, "GET", path + "api/health")
    assert status == 200 and json.loads(data)["ok"] is True
    listing = json.loads(fetch(port, "GET", path + "api/samples")[2])
    assert len(listing["followers"]) == len(LABELS["takes"]) + 15 + 4  # seed 5, Part 3's kit, Part 2's clips
    assert [e["id"] for e in listing["expected"]] == ["exercise", "dance", "part3-squat"]
    if path != "/":
        assert fetch(port, "GET", "/api/health")[0] == 404


def test_AC_S09_paths_that_climb_out_of_web_are_404(base):
    path, port = base
    for evil in ("../../etc/passwd", "..%2f..%2fetc%2fpasswd", "%2e%2e/%2e%2e/etc/passwd", "app.js/../../part5/api.py",
                 "vendor/", "nothing.txt", ".hidden"):
        status, _, data = fetch(port, "GET", path + evil)
        assert status == 404 and b"root:" not in data and b"def handle" not in data, evil


def test_analyse_over_http_runs_the_pipeline_and_returns_the_replay(base):
    path, port = base
    body = json.dumps(PAIR).encode()
    status, response, data = fetch(port, "POST", path + "api/analyse", body, {"Content-Type": "application/json"})
    payload = json.loads(data)
    assert status == 200 and response.getheader("Content-Type").startswith("application/json")
    assert "foot_out" in [f["measure"] for f in payload["analysis"]["faults"]]
    assert len(payload["replay"]["exp_to_fol"]) == len(payload["replay"]["expected"]) > 0


def test_a_plain_error_comes_back_as_json_with_its_status(base):
    path, port = base
    bad = json.dumps({"expected": {"sample": "../../etc/passwd"}, "follower": {"sample": FOOT_OUT}}).encode()
    status, _, data = fetch(port, "POST", path + "api/analyse", bad)
    assert status == 404 and json.loads(data)["error"]["field"] == "expected.sample"


def test_a_declared_body_over_the_cap_is_413_before_it_is_read(base):
    path, port = base
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall((f"POST {path}api/analyse HTTP/1.1\r\nHost: x\r\n"
                      f"Content-Length: {api.MAX_BODY_BYTES + 1}\r\n\r\n").encode())
        reply = b""
        while chunk := sock.recv(65536):  # the server closes after answering
            reply += chunk
    assert reply.startswith(b"HTTP/1.1 413") and b"larger than 16 MiB" in reply and b"Connection: close" in reply


def test_a_post_without_content_length_is_411(base):
    path, port = base
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(f"POST {path}api/analyse HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        assert sock.recv(65536).startswith(b"HTTP/1.1 411")


@pytest.mark.parametrize("length", [b"\xb2", b"\xd9\xa1", b"12abc", b"-5", b"1.5", b""])
def test_a_content_length_that_is_not_a_plain_number_is_a_400_not_a_crash(base, length):
    """"\xb2" is the superscript two: str.isdigit() says yes and int() raises."""
    path, port = base
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(f"POST {path}api/analyse HTTP/1.1\r\nHost: x\r\nContent-Length: ".encode() + length + b"\r\n\r\n")
        reply = b""
        while chunk := sock.recv(65536):  # the server closes after answering
            reply += chunk
    assert reply.startswith(b"HTTP/1.1 400") and b"whole number" in reply and b"Traceback" not in reply
    assert b"Connection: close" in reply


def test_head_returns_the_headers_and_no_body(base):
    path, port = base
    status, response, data = fetch(port, "HEAD", path)
    assert status == 200 and data == b"" and int(response.getheader("Content-Length")) > 0


def test_posting_to_a_page_is_405_and_to_nowhere_is_404(base):
    path, port = base
    status, response, _ = fetch(port, "POST", path, b"{}")
    assert status == 405 and response.getheader("Allow") == "GET"
    if path != "/":
        assert fetch(port, "POST", "/elsewhere", b"{}")[0] == 404


def test_a_server_error_never_leaks_a_trace_over_http(base, monkeypatch):
    path, port = base
    monkeypatch.setattr(api, "run", lambda *a, **k: 1 / 0)
    status, _, data = fetch(port, "POST", path + "api/analyse", json.dumps(PAIR).encode())
    assert status == 500 and b"Traceback" not in data and b"division" not in data


def test_AC_V11_the_vendored_three_js_is_served_with_the_right_types(base):
    """The page loads three.js from its own address under the base path (no CDN)."""
    path, port = base
    for name in ("vendor/three/three.module.js", "vendor/three/OrbitControls.js", "viewer.js", "joints.js", "preview.js"):
        status, response, data = fetch(port, "GET", path + name)
        assert status == 200 and response.getheader("Content-Type").startswith("text/javascript"), name
        assert len(data) > 100
    status, response, data = fetch(port, "GET", path + "vendor/three/LICENSE")
    assert status == 200 and response.getheader("Content-Type").startswith("text/plain") and b"MIT License" in data


def test_a_large_static_file_is_gzipped_on_request_and_plain_otherwise(base):
    path, port = base
    url = path + "vendor/three/three.module.js"
    _, plain_response, plain = fetch(port, "GET", url)
    _, zipped_response, zipped = fetch(port, "GET", url, headers={"Accept-Encoding": "gzip"})
    assert plain_response.getheader("Content-Encoding") is None and len(plain) > 1_000_000
    assert zipped_response.getheader("Content-Encoding") == "gzip" and len(zipped) < len(plain) // 2
    assert gzip.decompress(zipped) == plain
    assert zipped_response.getheader("Vary") == "Accept-Encoding"


def test_a_static_file_carries_an_etag_and_answers_304_when_the_browser_has_it(base):
    path, port = base
    _, response, _ = fetch(port, "GET", path + "app.js")
    etag = response.getheader("ETag")
    assert etag and response.getheader("Cache-Control") == "no-cache"
    status, _, data = fetch(port, "GET", path + "app.js", headers={"If-None-Match": etag})
    assert status == 304 and data == b""
    assert fetch(port, "GET", path + "app.js", headers={"If-None-Match": '"other"'})[0] == 200


def test_AC_V09_real_takes_over_http_is_503_with_the_plain_message_when_the_report_is_missing(base, monkeypatch):
    path, port = base
    monkeypatch.setattr(api, "_REAL_REPORT", {})
    monkeypatch.setattr(api, "_build_real_report", lambda: (_ for _ in ()).throw(ImportError("part5.real")))
    status, _, data = fetch(port, "GET", path + "api/real-takes")
    assert status == 503 and json.loads(data) == {"error": {
        "field": "real-takes", "message": "The real-take report is not available on this server."}}


def test_AC_V09_real_takes_over_http_serves_the_report(base, monkeypatch):
    path, port = base
    report = {"format": "simon.part5.real_report.v1", "gated": False, "takes": [], "summary": {}, "notes": []}
    monkeypatch.setattr(api, "_REAL_REPORT", {})
    monkeypatch.setattr(api, "_build_real_report", lambda: report)
    status, _, data = fetch(port, "GET", path + "api/real-takes")
    assert status == 200 and json.loads(data) == report


def test_the_rate_limit_counts_the_visitor_named_by_the_gateway_not_the_gateway(base, monkeypatch, tmp_path):
    """Behind the gateway every connection is from 127.0.0.1; X-Forwarded-For tells visitors apart."""
    path, port = base
    (tmp_path / "BASETEN_API_KEY").write_text("k\n")
    monkeypatch.setenv("PART5_BASETEN_KEY_FILE", str(tmp_path / "BASETEN_API_KEY"))
    monkeypatch.setenv("META_LIVE", "1")
    monkeypatch.setattr(api, "_MUSE_LIMIT", api.ClientLimit(per_minute=1))
    monkeypatch.setattr(api, "_in_worker", lambda fn, *a: {"analysis": {}, "replay": {}})
    body = json.dumps({**PAIR, "phrasing": "muse-spark"}).encode()

    def post(visitor):
        return fetch(port, "POST", path + "api/analyse", body, {"X-Forwarded-For": visitor})[0]

    assert [post("203.0.113.1"), post("203.0.113.1"), post("203.0.113.2")] == [200, 429, 200]


def test_static_table_skips_hidden_files_and_lists_the_web_files(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.js").write_text("1")
    (tmp_path / "sub" / "b.css").write_text("2")
    (tmp_path / ".secret").write_text("3")
    assert set(server.static_table(tmp_path)) == {"a.js", "sub/b.css"}
    assert {"index.html", "app.js", "api.js", "style.css"} <= set(server.static_table())


def test_serve_reports_a_busy_port_and_returns_1(capsys):
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        assert server.serve("127.0.0.1", taken.getsockname()[1], "/") == 1
    assert "cannot start" in capsys.readouterr().err


def test_the_serve_subcommand_defaults_to_the_local_dev_port_and_the_root():
    from part5.cli import build_parser

    args = build_parser().parse_args(["serve"])
    assert (args.host, args.port, args.base_path) == ("127.0.0.1", 8725, "/")
    args = build_parser().parse_args(["serve", "--port", "7123", "--base-path", "/simon-part-5/"])
    assert (args.port, args.base_path) == (7123, "/simon-part-5/")


def test_AC_V11_make_demo_serves_the_page_on_its_own_port_8735():
    """`make demo` runs the same server as `scripts/dev.sh` (8725) on another port, so both can run."""
    makefile = (ROOT / "Makefile").read_text()
    assert re.search(r"^\.PHONY:.*\bdemo\b", makefile, re.M)
    assert re.search(r"^demo:\n\t.*python -m part5 serve --port 8735$", makefile, re.M)
    from part5.cli import build_parser

    args = build_parser().parse_args(["serve", "--port", "8735"])
    assert (args.host, args.port, args.base_path) == ("127.0.0.1", 8735, "/")


def _start_serve_subprocess():
    """`python -m part5 serve` on a free 127.0.0.1 port, started once api/health answers: (process, port)."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    proc = subprocess.Popen([sys.executable, "-m", "part5", "serve", "--port", str(port)], cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 30
    while proc.poll() is None and time.monotonic() < deadline:
        try:
            if fetch(port, "GET", "/api/health")[0] == 200:
                return proc, port
        except OSError:
            time.sleep(0.1)
    proc.kill()
    _, err = proc.communicate()
    pytest.fail("part5 serve never answered api/health: " + err)


@pytest.mark.parametrize("terms, gap", [(2, 0.05), (400, 0.002)],
                         ids=["two_terms_50ms_apart", "a_term_every_2ms_until_exit"])
def test_serve_stops_with_exit_0_and_a_clean_log_on_repeated_sigterm(terms, gap):
    """A stop through `make demo` can deliver a second SIGTERM while the interpreter shuts down; the handler is
    one-shot (SIG_IGN after the first), so the second neither raises "Exception ignored ... SystemExit: 0" nor kills the
    process with -15. The 2 ms burst covers the whole shutdown window; the 50 ms pair is the plain double stop."""
    proc, _ = _start_serve_subprocess()
    try:
        proc.send_signal(signal.SIGTERM)
        for _ in range(terms - 1):
            time.sleep(gap)
            if proc.poll() is not None:
                break
            proc.send_signal(signal.SIGTERM)
        _, err = proc.communicate(timeout=20)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    assert proc.returncode == 0, err
    assert "Traceback" not in err and "Exception ignored" not in err, err
