"""part5.server: the HTTP layer over api.handle and web/, on a real socket (127.0.0.1, free port)."""
import http.client
import json
import socket
import threading
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
    assert len(json.loads(fetch(port, "GET", path + "api/samples")[2])["followers"]) == len(LABELS["takes"])
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
