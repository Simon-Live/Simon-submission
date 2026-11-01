"""Idempotency-Key binding, expiry and index (TICKET-106 R5, R6): a key is tied to its request body, expired records
vanish at runtime, a delete finds records through an index, and a malformed Content-Length is a 400."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import time

import pytest

from part7 import chain, idempotency
from support import Api
from test_server import _fake_trainer, _upload

KEY = "3f2b8c1e-9d4a-4e7b-8a61-0c5d2e9f7a10"
OTHER = "aa2b8c1e-9d4a-4e7b-8a61-0c5d2e9f7a11"


def _hdr(key: str = KEY) -> dict[str, str]:
    return {"Idempotency-Key": key}


def test_edited_details_under_the_same_key_replay_the_original_job(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "trainer", _fake_trainer())
    upload_id = _upload(api, tiny_mp4)
    first = api.json("POST", "api/trainer", {"upload_id": upload_id, "name": "A", "category": "dance",
                                             "labels": {"tags": ["x"], "notes": ""}}, _hdr())
    assert first[0] == 202
    same = api.json("POST", "api/trainer", {"upload_id": upload_id, "name": "B", "category": "exercise",
                                            "labels": {"tags": ["y"], "notes": "n"}}, _hdr())
    assert same[0] == 202 and same[1]["job"] == first[1]["job"], "an edit after a lost answer must not delete the take"


def test_another_upload_under_the_same_key_is_422(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "trainer", _fake_trainer())
    upload_id = _upload(api, tiny_mp4)
    assert api.json("POST", "api/trainer", {"upload_id": upload_id, "name": "A", "category": "dance"}, _hdr())[0] == 202
    status, body = api.json("POST", "api/trainer", {"upload_id": "ffffffffffffffff", "name": "A", "category": "dance"}, _hdr())
    assert status == 422 and "different request" in body["error"]


def test_the_index_holds_only_id_shaped_strings_and_forgets_pruned_records(tmp_path: Path) -> None:
    store = idempotency.Store(tmp_path)
    store.put("follow", KEY, 202, {"job": "0123456789ab", "message": "The analysis has started.", "upload_id": "0123456789abcdef"})
    store.forget_ids(["nothing"])  # builds the index
    index = store._built_index()
    assert set(index) == {"0123456789ab", "0123456789abcdef"}
    old = time.time() - 30 * 86400
    path = store._path("follow", KEY)
    os.utime(path, (old, old))
    assert store.prune(7) == 1
    assert all(path not in paths for paths in store._built_index().values())


def test_an_upload_replay_of_another_size_is_422(api: Api, tiny_mp4: Path) -> None:
    assert api.upload(tiny_mp4, headers=_hdr())[0] == 201
    status, _, _ = api.request("POST", "api/uploads", tiny_mp4.read_bytes() + b"x", {"Content-Type": "video/mp4", **_hdr()})
    assert status == 422


def test_the_same_key_while_the_first_request_runs_is_503(api: Api, tiny_mp4: Path) -> None:
    assert api.app.idempotency.begin("uploads", KEY)
    assert api.upload(tiny_mp4, headers=_hdr())[0] == 503
    assert api.app.idempotency.begin("follow", KEY)
    assert api.json("POST", "api/follow", {"upload_id": "x", "entry_id": "lateral-raise"}, _hdr())[0] == 503
    api.app.idempotency.end("uploads", KEY)
    api.app.idempotency.end("follow", KEY)
    assert api.upload(tiny_mp4, headers=_hdr())[0] == 201


def test_a_malformed_content_length_is_a_400_not_a_crash(api: Api) -> None:
    api.app.idempotency.begin("follow", KEY)  # the busy path would have parsed the header itself
    with socket.create_connection(("127.0.0.1", api.port), timeout=10) as sock:
        sock.sendall((f"POST {api.app.base}api/follow HTTP/1.1\r\nHost: x\r\nIdempotency-Key: {KEY}\r\n"
                      "Content-Type: application/json\r\nContent-Length: abc\r\nConnection: close\r\n\r\n{}").encode())
        reply = sock.recv(4096)
    assert reply.startswith(b"HTTP/1.") and b" 400 " in reply.split(b"\r\n")[0]


def test_an_expired_record_reads_as_absent_and_put_prunes_old_ones(tmp_path: Path) -> None:
    store = idempotency.Store(tmp_path, retention_days=1)
    store.put("uploads", KEY, 201, {"upload_id": "a"})
    path = store.dir / f"uploads-{KEY}.json"
    doc = json.loads(path.read_text())
    doc["created"] = time.time() - 2 * 86400
    path.write_text(json.dumps(doc))
    assert store.get("uploads", KEY) is None and not path.exists()
    store.put("follow", OTHER, 202, {"job": "j"})
    old = time.time() - 3 * 86400
    os.utime(store.dir / f"follow-{OTHER}.json", (old, old))
    store._pruned_at = 0.0  # the hourly prune is due
    store.put("uploads", KEY, 201, {"upload_id": "b"})
    assert not (store.dir / f"follow-{OTHER}.json").exists() and store.get("uploads", KEY) is not None


def test_forget_ids_uses_an_index_kept_current_by_put(tmp_path: Path) -> None:
    store = idempotency.Store(tmp_path)
    store.put("follow", KEY, 202, {"id": "aaaaaaaaaaaa"})
    assert store.forget_ids(["zzzzzzzzzzzz"]) == 0  # builds the index
    store.put("follow", OTHER, 202, {"id": "bbbbbbbbbbbb", "nested": {"u": "0123456789abcdef"}})
    assert store.forget_ids(["0123456789abcdef"]) == 1
    assert store.get("follow", OTHER) is None and store.get("follow", KEY) is not None
    assert store.forget_ids(["aaaaaaaaaaaa"]) == 1 and store.forget_ids(["aaaaaaaaaaaa"]) == 0


def test_a_record_saved_under_the_old_whole_body_hash_still_replays_and_says_so(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TICKET-109: records saved before the identity binding were hashed over the whole body."""
    monkeypatch.setattr(chain, "trainer", _fake_trainer())
    upload_id = _upload(api, tiny_mp4)
    body = {"upload_id": upload_id, "name": "A", "category": "dance"}
    first = api.json("POST", "api/trainer", body, _hdr())
    assert first[0] == 202
    old = idempotency.fingerprint(json.dumps(body).encode())  # what the old code stored
    api.app.idempotency.put("trainer", KEY, first[0], first[1], old)
    same = api.json("POST", "api/trainer", body, _hdr())
    assert same[0] == 202 and same[1]["job"] == first[1]["job"]
    doc = json.loads(api.app.idempotency._path("trainer", KEY).read_text())
    assert doc["fingerprint"] == old and doc["fingerprint_form"] == "whole-body"


def test_a_422_names_the_job_the_server_holds(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "trainer", _fake_trainer())
    upload_id = _upload(api, tiny_mp4)
    first = api.json("POST", "api/trainer", {"upload_id": upload_id, "name": "A", "category": "dance"}, _hdr())
    status, body = api.json("POST", "api/trainer", {"upload_id": "ffffffffffffffff", "name": "A", "category": "dance"}, _hdr())
    assert status == 422 and body["job"] == first[1]["job"]


def test_forgetting_ids_and_dropping_keep_the_reverse_map_in_step(tmp_path: Path) -> None:
    store = idempotency.Store(tmp_path)
    store.put("follow", KEY, 202, {"job": "0123456789ab", "upload_id": "0123456789abcdef"})
    store.put("follow", OTHER, 202, {"job": "ba9876543210"})
    store.forget_ids(["nothing"])
    store.drop("follow", KEY)
    assert store._by_path.get(store._path("follow", KEY)) is None
    index = store._built_index()
    assert index["0123456789ab"] == set() and index["ba9876543210"] == {store._path("follow", OTHER)}
    assert store.forget_ids(["ba9876543210"]) == 1 and store._by_path == {}
