"""part2/server.py: health, pages, headers, methods, paths, base path, outputs and the contract (docs/specs/run-app.md:
AC-A01, AC-A02, AC-A10, AC-A11).

Most tests serve a small synthetic repo from tmp_path so every edge case is exact; the AC-A01 tests also serve the
committed outputs under fixtures/output/. Shared fixtures and helpers: tests/server_helpers.py. The run API over HTTP
is in test_server_run.py; the pages, the process and scripts/dev.sh are in test_server_pages.py.
"""
import json
import re
import sys
from pathlib import Path

import pytest

import part2.contract
from part2 import server
from server_helpers import (JPEG, ROOT, fake_smi, fetch, get_json, isolated_jobs, port, raw_exchange,  # noqa: F401
                            real_port, repo, running, write_output)

CSP = "default-src 'self'; img-src 'self' data: blob:"
CONTRACT_DATA = {"schemas": [{"name": "pose3d", "version": "part2.pose3d/2026-10-28", "direction": "produces",
                              "file": "contracts/pose3d.schema.json"}],
                 "compatibility": [{"producer_file": "pose3d.json", "consumer": "Part 3", "result": "works"}]}


# ---- health, pages, headers ---------------------------------------------------------------------------

def test_health_answers_ok_with_version_gpu_and_worker(port):
    status, doc = get_json(port, "/api/health")
    assert status == 200
    assert doc["ok"] is True and isinstance(doc["version"], str) and doc["version"]
    assert doc["gpu"] is None and doc["worker"] == "idle"


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
