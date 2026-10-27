"""POST api/entries: the mock recording flow behind the processor seam (AC-008, AC-008a)."""
import hashlib
import json
import re
import socket
import threading
from pathlib import Path

import pytest

from part6 import catalog, motion, processor, validate

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "output" / "catalog"
VALID = {"name": "Evening flow", "category": "dance", "duration_ms": 2000}


def body_of(**changes):
    obj = dict(VALID, **changes)
    return {k: v for k, v in obj.items() if v is not ...}


# success

def test_201_with_the_new_manifest(app, seeded):
    status, manifest = app.client.post_json(VALID)
    assert status == 201
    assert re.fullmatch(r"evening-flow-[0-9a-f]{8}", manifest["id"])
    assert manifest["name"] == "Evening flow" and manifest["category"] == "dance"
    assert manifest["duration_ms"] == 2000 and manifest["files_source"] == "mock"
    assert manifest["video_uri"] is None and manifest["schema_version"] == 1
    assert manifest["description"].startswith("Mock recording from ")
    assert manifest["description"].endswith(". Capture and processing are mocked.")
    assert validate.check_entry(seeded / manifest["id"]) == []


def test_the_response_is_json_and_not_cached(app):
    status, headers, body = app.client.post(VALID)
    assert status == 201 and headers["content-type"] == "application/json"
    assert headers["cache-control"] == "no-store"
    assert json.loads(body)["id"]


def test_the_new_entry_is_listed_searchable_and_filterable(app):
    manifest = app.client.post_json(VALID)[1]
    listed = app.client.get_json("/api/entries")[1]["entries"]
    assert manifest in listed and len(listed) == 7
    assert [m["id"] for m in app.client.get_json("/api/entries?q=evening")[1]["entries"]] == [
        manifest["id"]]
    dances = [m["id"] for m in app.client.get_json("/api/entries?category=dance")[1]["entries"]]
    exercises = [m["id"] for m in app.client.get_json("/api/entries?category=exercise")[1]["entries"]]
    assert manifest["id"] in dances and manifest["id"] not in exercises
    assert app.client.get_json("/api/health")[1]["entries"] == 7
    assert app.client.get_json(f"/api/entries/{manifest['id']}")[1] == manifest


def test_the_new_entrys_files_validate_and_play(app):
    manifest = app.client.post_json(VALID)[1]
    base = f"/api/entries/{manifest['id']}"
    animation = app.client.get_json(f"{base}/animation.json")[1]
    assert validate.check_animation(animation) == [] and len(animation["frames"]) == 60
    assert validate.check_skeleton(app.client.get_json(f"{base}/skeleton.json")[1]) == []
    assert validate.check_keyframes(app.client.get_json(f"{base}/keyframes.json")[1]) == []
    status, headers, svg = app.client.get(f"{base}/thumbnail.svg")
    assert status == 200 and headers["content-type"] == "image/svg+xml" and svg.count(b"<circle") == 17


def test_the_entry_persists_across_a_server_restart(tmp_path, seeded, start_server):
    first = start_server(seeded)
    manifest = first.client.post_json(VALID)[1]
    first.stop()
    second = start_server(seeded)
    assert second.client.get_json(f"/api/entries/{manifest['id']}")[1] == manifest
    assert second.client.get_json("/api/health")[1]["entries"] == 7


def test_the_shipped_fixtures_are_not_touched(app):
    def digest():
        return hashlib.sha256(b"".join(
            p.read_bytes() for p in sorted(FIXTURES.rglob("*")) if p.is_file())).hexdigest()

    before = digest()
    app.client.post_json(VALID)
    assert digest() == before


def test_name_is_trimmed_and_collapsed_and_duplicates_are_allowed(app):
    first = app.client.post_json(body_of(name="  Hip   twist   deluxe "))[1]
    second = app.client.post_json(body_of(name="Hip twist deluxe"))[1]
    assert first["name"] == second["name"] == "Hip twist deluxe"
    assert first["id"] != second["id"] and first["id"].startswith("hip-twist-deluxe-")


def test_unknown_fields_are_ignored(app):
    status, manifest = app.client.post_json(body_of(
        id="squat", files_source="fixture", video_uri="x.webm", description="hi", extra=[1]))
    assert status == 201 and manifest["id"] != "squat"
    assert manifest["files_source"] == "mock" and manifest["video_uri"] is None
    assert manifest["description"].startswith("Mock recording")
    assert app.client.get_json("/api/entries/squat")[1]["files_source"] == "fixture"


@pytest.mark.parametrize("duration", [1000, 1001, 60000, 120000])
def test_duration_bounds_are_inclusive(app, duration):
    status, manifest = app.client.post_json(body_of(duration_ms=duration))
    assert status == 201 and manifest["duration_ms"] == duration
    frames = app.client.get_json(f"/api/entries/{manifest['id']}/animation.json")[1]["frames"]
    assert len(frames) == max(30, round(duration * 30 / 1000))


def test_name_of_80_characters_is_accepted(app):
    assert app.client.post_json(body_of(name="x" * 80))[0] == 201
    assert app.client.post_json(body_of(name="é" * 80))[0] == 201


def test_two_recordings_with_the_same_name_make_different_animations(app):
    ids = [app.client.post_json(VALID)[1]["id"] for _ in range(2)]
    files = [app.client.get(f"/api/entries/{i}/animation.json")[2] for i in ids]
    assert files[0] != files[1]


def test_both_categories_make_a_movement_of_that_category(app):
    for category in ("exercise", "dance"):
        manifest = app.client.post_json(body_of(category=category, duration_ms=3000))[1]
        kf = app.client.get_json(f"/api/entries/{manifest['id']}/keyframes.json")[1]
        movement = kf["people"][0]["repetitions"][0]["movement"]
        assert motion.FAMILIES[movement].category == category


def test_concurrent_creates_all_succeed_with_distinct_ids(app):
    results = []

    def create(n):
        results.append(app.client.post_json(body_of(name=f"Parallel {n}", duration_ms=1500)))

    threads = [threading.Thread(target=create, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join(20) for t in threads]
    assert [s for s, _ in results] == [201] * 8
    assert len({m["id"] for _, m in results}) == 8
    assert app.client.get_json("/api/health")[1]["entries"] == 14


# validation: one failing case per rule

@pytest.mark.parametrize("changes,field", [
    ({"name": ""}, "name"), ({"name": "   "}, "name"), ({"name": ...}, "name"),
    ({"name": None}, "name"), ({"name": 7}, "name"), ({"name": ["a"]}, "name"),
    ({"name": "x" * 81}, "name"), ({"name": " " + "x" * 81 + " "}, "name"),
    ({"name": "a\x00b"}, "name"), ({"name": "a\x1bb"}, "name"), ({"name": "line\nbreak"}, "name"),
    ({"category": ...}, "category"), ({"category": None}, "category"),
    ({"category": "yoga"}, "category"), ({"category": "Dance"}, "category"),
    ({"category": ""}, "category"), ({"category": 1}, "category"),
    ({"duration_ms": ...}, "duration_ms"), ({"duration_ms": None}, "duration_ms"),
    ({"duration_ms": 999}, "duration_ms"), ({"duration_ms": 0}, "duration_ms"),
    ({"duration_ms": -1000}, "duration_ms"), ({"duration_ms": 120001}, "duration_ms"),
    ({"duration_ms": 2000.5}, "duration_ms"), ({"duration_ms": 2000.0}, "duration_ms"),
    ({"duration_ms": "2000"}, "duration_ms"), ({"duration_ms": True}, "duration_ms"),
    ({"duration_ms": [2000]}, "duration_ms"), ({"duration_ms": 10 ** 12}, "duration_ms"),
])
def test_400_names_the_bad_field(app, changes, field):
    status, body = app.client.post_json(body_of(**changes))
    assert (status, body) == (400, {"error": field})
    assert app.client.get_json("/api/health")[1]["entries"] == 6


@pytest.mark.parametrize("payload", [
    b"", b"not json", b"{", b"[]", b"[1, 2]", b'"text"', b"42", b"null", b"true",
    b"\xff\xfe\x00", b'{"name": "a", "name": ', b"{'name': 'a'}"])
def test_400_for_a_body_that_is_not_a_json_object(app, payload):
    assert app.client.post_json(payload) == (400, {"error": "body"})


def read_to_close(sock):
    """Read the whole reply: headers and body may arrive in separate segments."""
    chunks = []
    while chunk := sock.recv(4096):
        chunks.append(chunk)
    return b"".join(chunks)


def test_400_for_a_missing_or_bad_content_length(app):
    for head in (b"POST /api/entries HTTP/1.1\r\nHost: x\r\n\r\n",
                 b"POST /api/entries HTTP/1.1\r\nHost: x\r\nContent-Length: abc\r\n\r\n",
                 b"POST /api/entries HTTP/1.1\r\nHost: x\r\nContent-Length: -5\r\n\r\n"):
        with socket.create_connection(("127.0.0.1", app.port), timeout=5) as s:
            s.sendall(head)
            reply = read_to_close(s)
        assert reply.startswith(b"HTTP/1.1 400") and b'{"error": "body"}' in reply


def padded(size):
    base = json.dumps(dict(VALID, pad="")).encode()
    return json.dumps(dict(VALID, pad="x" * (size - len(base) + 0))).encode()


def test_a_body_of_exactly_4096_bytes_is_accepted_and_4097_is_413(app):
    ok, too_big = padded(4096), padded(4097)
    assert (len(ok), len(too_big)) == (4096, 4097)
    assert app.client.post(ok)[0] == 201
    status, body = app.client.post_json(too_big)
    assert (status, body) == (413, {"error": "body too large"})
    assert app.client.get_json("/api/health")[1]["entries"] == 7


def test_a_huge_body_is_413_without_storing_anything(app):
    status, body = app.client.post_json(b"x" * 200_000)
    assert (status, body) == (413, {"error": "body too large"})
    assert app.client.get_json("/api/health")[1]["entries"] == 6


def test_validation_runs_before_any_processing(app, monkeypatch):
    def explode(recording):
        raise AssertionError("processor called")
    monkeypatch.setattr(processor, "process", explode)
    assert app.client.post_json(body_of(duration_ms=5))[0] == 400
    assert app.client.post_json(body_of(name=""))[0] == 400


# the processor seam and atomic writes

def test_the_server_gets_every_shared_file_from_process_only(app, seeded, monkeypatch):
    calls = []
    sample = processor.generate("squat", 1000, motion.MotionParams(1.0, 1))
    stamped = json.loads(json.dumps(sample))
    stamped["animation"]["units"] = {"length": "stub"}

    def stub(recording):
        calls.append(recording)
        return stamped

    monkeypatch.setattr(processor, "process", stub)
    manifest = app.client.post_json(body_of(name="Stubbed", category="exercise", duration_ms=1000))[1]
    assert len(calls) == 1
    assert set(calls[0]) == {"id", "name", "category", "duration_ms", "video_path"}
    assert calls[0] == {"id": manifest["id"], "name": "Stubbed", "category": "exercise",
                        "duration_ms": 1000, "video_path": None}
    served = app.client.get_json(f"/api/entries/{manifest['id']}/animation.json")[1]
    assert served["units"] == {"length": "stub"}
    assert app.client.get_json(f"/api/entries/{manifest['id']}/skeleton.json")[1] == stamped["skeleton"]


def test_a_processor_failure_is_a_500_and_leaves_nothing_behind(app, seeded, monkeypatch):
    def broken(recording):
        raise RuntimeError("model crashed")
    monkeypatch.setattr(processor, "process", broken)
    status, body = app.client.post_json(VALID)
    assert (status, body) == (500, {"error": "internal error"})
    assert sorted(p.name for p in seeded.iterdir()) == sorted(
        ["squat", "forward-lunge", "jumping-jack", "side-step", "arm-wave", "hip-twist"])
    monkeypatch.undo()
    assert app.client.post_json(VALID)[0] == 201


def test_a_failed_write_leaves_no_half_entry(app, seeded, monkeypatch):
    real = catalog.os.rename

    def fail(src, dst):
        raise OSError("disk gone")
    monkeypatch.setattr(catalog.os, "rename", fail)
    assert app.client.post_json(VALID)[0] == 500
    monkeypatch.setattr(catalog.os, "rename", real)
    assert not [p for p in seeded.iterdir() if p.name.startswith(".") or "evening" in p.name]
    assert app.client.get_json("/api/health")[1]["entries"] == 6


def test_a_crash_before_the_rename_never_shows_in_the_listing(app, seeded):
    (seeded / ".tmp-crashed-00000000").mkdir()
    (seeded / ".tmp-crashed-00000000" / "manifest.json").write_text(
        (seeded / "squat" / "manifest.json").read_text())
    assert app.client.get_json("/api/health")[1]["entries"] == 6
    assert app.client.get("/api/entries/.tmp-crashed-00000000")[0] == 404
