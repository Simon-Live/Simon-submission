"""The key file, the ledger and the cap of the Meta Model API call (docs/specs/second-opinion.md AC-SO-06, AC-SO-07;
review findings B5, R1, R2, R8, R12, R17).

Every key is a temp file; the real key file is never read. The API is a fake opener or a fake client; no socket is
opened.
"""
import json
import logging
import os
import threading
import time
import urllib.error

import pytest

from part5 import opinion
from part5.opinion import meta_api
from part5.opinion.meta_api import OpinionError
from part5.phrasing import muse_spark
from part5.phrasing.local_llm import BackendError
from test_second_opinion import (  # noqa: F401  (the fixtures are used by name)
    SENTINEL, Fake, FakeOpener, FakeResponse, all_verdicts, answer, attach, meta, take)

CAP_ENV, CALL_ENV = "PART5_META_SPEND_CAP_USD", "PART5_META_CALL_MAX_USD"


@pytest.fixture
def keyfile(tmp_path, monkeypatch):
    """One temp path both backends read their key from."""
    path = tmp_path / "key"
    monkeypatch.setenv("PART5_META_KEY_FILE", str(path))
    monkeypatch.setenv("PART5_BASETEN_KEY_FILE", str(path))
    return path


# ---- B5: one set of helpers for both backends ------------------------------------------------------------------------
def test_review_b5_the_two_backends_share_one_set_of_key_and_ledger_helpers():
    for name in ("path_of", "unavailable_for", "read_key_from", "open_ledger_at"):
        assert getattr(meta_api, name) is getattr(muse_spark, name)
    source = open(meta_api.__file__).read()
    assert "O_APPEND" not in source and "key_path().read_text" not in source   # no copy of the helpers is left


READERS = [(meta_api.read_key, OpinionError), (muse_spark._read_key, BackendError)]


@pytest.mark.parametrize("read,error", READERS)
@pytest.mark.parametrize("content,reason", [
    (None, "key file unreadable"), (b"", "key file is empty"), (b" \n\t \n", "key file is empty"),
    (b"\xff\xfe\x00 not utf-8", "key file unreadable"),
])
def test_review_r8_a_missing_empty_or_unreadable_key_file_is_a_reason_not_a_crash(keyfile, read, error, content, reason):
    if content is not None:
        keyfile.write_bytes(content)
    with pytest.raises(error) as raised:
        read()
    assert raised.value.reason == reason


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
@pytest.mark.parametrize("read,error", READERS)
def test_review_r8_a_key_file_without_read_permission_is_unreadable(keyfile, read, error):
    keyfile.write_text("a-temp-key\n")
    keyfile.chmod(0)
    with pytest.raises(error) as raised:
        read()
    assert raised.value.reason == "key file unreadable"


@pytest.mark.parametrize("read", [meta_api.read_key, muse_spark._read_key])
def test_review_b5_the_key_is_stripped_and_both_read_the_same_text(keyfile, read):
    keyfile.write_text("  a-temp-key \n")
    assert read() == "a-temp-key"


def test_review_b5_both_backends_say_the_same_when_a_live_call_is_not_allowed(keyfile):
    assert meta_api.unavailable(live=True) == muse_spark.unavailable(live=True) == "no key"
    keyfile.mkdir()   # a directory is no key file
    assert meta_api.unavailable(live=True) == muse_spark.unavailable(live=True) == "no key"
    keyfile.rmdir()
    keyfile.write_text("a-temp-key")
    off = meta_api.unavailable(live=False)
    assert off == muse_spark.unavailable(live=False) and off.startswith("live calls are off")
    assert meta_api.unavailable(live=True) is None and muse_spark.unavailable(live=True) is None


@pytest.mark.parametrize("open_ledger,error", [(meta_api.open_ledger, OpinionError),
                                               (muse_spark._open_ledger, BackendError)])
def test_review_b5_a_ledger_that_cannot_be_opened_is_a_reason(tmp_path, monkeypatch, open_ledger, error):
    (tmp_path / "blocked").write_text("a file where the ledger directory would be")
    monkeypatch.setenv("PART5_META_USAGE_FILE", str(tmp_path / "blocked" / "u.jsonl"))
    monkeypatch.setenv("PART5_BASETEN_USAGE_FILE", str(tmp_path / "blocked" / "u.jsonl"))
    with pytest.raises(error) as raised:
        open_ledger()
    assert raised.value.reason == "usage ledger not writable"


# ---- R8: the real key path through the run ---------------------------------------------------------------------------
@pytest.mark.parametrize("content,reason", [(b"", "key file is empty"), (b"\n \n", "key file is empty"),
                                            (b"\xff\xfe\x00", "key file unreadable")])
def test_review_r8_without_a_client_a_bad_key_file_ends_in_a_fallback_block(take, meta, content, reason):
    meta.key.write_bytes(content)
    doc = opinion.attach(take, *meta.clips, live=True)   # client=None: the real key path
    assert (doc["second_opinion"]["status"], doc["second_opinion"]["reason"]) == ("fallback", reason)
    assert doc["faults"] == take.analysis["faults"] and not meta.ledger.exists()


def test_review_r8_without_a_client_the_http_client_makes_the_whole_call_with_the_key_in_the_header_only(
        take, meta, monkeypatch):
    n = len(take.analysis["faults"])
    opener = FakeOpener(FakeResponse(200, b'{"id": "file-1"}'), FakeResponse(200, b'{"id": "file-2"}'),
                        FakeResponse(200, b'{"input_tokens": 1000}'),
                        FakeResponse(200, json.dumps(answer(all_verdicts(n, True), tokens=(1000, 200))).encode()),
                        FakeResponse(204, b""), FakeResponse(204, b""))
    monkeypatch.setattr(meta_api, "no_redirect_opener", lambda: opener)
    doc = opinion.attach(take, *meta.clips, live=True)
    block = doc["second_opinion"]
    assert block["status"] == "ok" and len(block["verdicts"]) == n
    assert [r.full_url.removeprefix(meta_api.API) for r in opener.requests] == [
        "/files", "/files", "/responses/input_tokens", "/responses", "/files/file-1", "/files/file-2"]
    assert all(r.get_header("Authorization") == f"Bearer {SENTINEL}" for r in opener.requests)
    assert SENTINEL not in json.dumps(doc) and SENTINEL not in meta.ledger.read_text()
    [line] = [json.loads(x) for x in meta.ledger.read_text().splitlines()]
    assert (line["http_status"], line["input_tokens"], line["output_tokens"]) == (200, 1000, 200)


@pytest.mark.parametrize("failure,estimated", [
    (TimeoutError("timed out"), True),
    (urllib.error.URLError(ConnectionRefusedError("refused")), True),
    (urllib.error.HTTPError(meta_api.API, 429, "slow down", {}, None), False),
])
def test_review_r1_through_the_http_client_only_a_call_with_no_answer_is_recorded_at_its_estimate(
        take, meta, monkeypatch, failure, estimated):
    opener = FakeOpener(FakeResponse(200, b'{"id": "file-1"}'), FakeResponse(200, b'{"id": "file-2"}'),
                        FakeResponse(200, b'{"input_tokens": 1000}'), failure, FakeResponse(204, b""),
                        FakeResponse(204, b""))
    monkeypatch.setattr(meta_api, "no_redirect_opener", lambda: opener)
    block = opinion.attach(take, *meta.clips, live=True)["second_opinion"]
    assert block["status"] == "fallback" and SENTINEL not in json.dumps(block)
    [line] = [json.loads(x) for x in meta.ledger.read_text().splitlines()]
    if estimated:
        assert line["http_status"] is None and line["estimated"] is True
        assert (line["input_tokens"], line["output_tokens"], line["usd"]) == (1000, 3000, 0.014)
    else:
        assert line["http_status"] == 429 and line["usd"] == 0.0 and "estimated" not in line


# ---- R2: the amounts from the environment ----------------------------------------------------------------------------
@pytest.mark.parametrize("name,default", [(CAP_ENV, 5.0), (CALL_ENV, 0.5)])
@pytest.mark.parametrize("raw", ["nan", "NaN", "inf", "-inf", "-1", "-0.01", "abc", "1e999"])
def test_review_r2_a_bad_amount_keeps_the_default_and_logs_a_warning(monkeypatch, caplog, name, default, raw):
    monkeypatch.setenv(name, raw)
    with caplog.at_level(logging.WARNING, logger=meta_api.__name__):
        assert meta_api._env_usd(name, default) == default
    assert name in caplog.text and repr(raw) in caplog.text and "using the default" in caplog.text


@pytest.mark.parametrize("raw,value", [("0", 0.0), ("2.5", 2.5), (" 7 ", 7.0)])
def test_review_r2_a_good_amount_is_used_and_an_unset_or_blank_one_is_the_default_without_a_warning(
        monkeypatch, caplog, raw, value):
    with caplog.at_level(logging.WARNING, logger=meta_api.__name__):
        monkeypatch.setenv(CAP_ENV, raw)
        assert meta_api._env_usd(CAP_ENV, 5.0) == value
        monkeypatch.setenv(CAP_ENV, "  ")
        assert meta_api._env_usd(CAP_ENV, 5.0) == 5.0
        monkeypatch.delenv(CAP_ENV)
        assert meta_api._env_usd(CAP_ENV, 5.0) == 5.0
    assert caplog.text == ""


@pytest.mark.parametrize("raw", ["nan", "inf", "-1"])
def test_review_r2_a_bad_cap_still_stops_a_call_and_a_bad_ceiling_still_allows_one(meta, monkeypatch, raw):
    meta.ledger.parent.mkdir(parents=True)
    meta.ledger.write_text(json.dumps({"usd": 4.99}) + "\n")
    monkeypatch.setenv(CAP_ENV, raw)
    with pytest.raises(OpinionError, match="spend cap reached"):
        meta_api.check_budget(0.024)
    meta.ledger.write_text("")
    monkeypatch.setenv(CALL_ENV, raw)
    meta_api.check_budget(0.024)   # the default ceiling of $0.50 applies: nothing raised
    with pytest.raises(OpinionError, match="over the per-call limit of \\$0.50"):
        meta_api.check_budget(0.60)


def test_review_r2_a_zero_cap_or_ceiling_refuses_every_call(meta, monkeypatch):
    monkeypatch.setenv(CAP_ENV, "0")
    with pytest.raises(OpinionError, match="spend cap reached"):
        meta_api.check_cap()
    monkeypatch.delenv(CAP_ENV)
    monkeypatch.setenv(CALL_ENV, "0")
    with pytest.raises(OpinionError, match="per-call limit"):
        meta_api.check_budget(0.001)


# ---- R12: what is sent ------------------------------------------------------------------------------------------------
def test_review_r12_ffmpeg_drops_the_recordings_metadata(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(meta_api.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(meta_api.subprocess, "run", lambda command, **kwargs: seen.append(command))
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"video")
    out = meta_api.prepare(clip, tmp_path)
    [command] = seen
    at = command.index("-map_metadata")
    assert command[at + 1] == "-1" and at > command.index("-i") and command[-1] == str(out)


def test_review_r12_the_upload_header_names_a_fixed_file_whatever_the_path_holds(tmp_path):
    clip = tmp_path / 'a"b\r\nX-Evil: 1.mp4'
    clip.write_bytes(b"video")
    client = meta_api.HttpClient("k")
    client._opener = FakeOpener(FakeResponse(200, b'{"id": "file-1"}'))
    assert client.upload(clip) == "file-1"
    data = client._opener.requests[0].data
    assert b'Content-Disposition: form-data; name="file"; filename="clip.mp4"\r\n' in data
    assert b"X-Evil" not in data and b'a"b' not in data and clip.name.encode() not in data
    assert data.count(b"filename=") == 1


# ---- R17: the lock on the ledger -------------------------------------------------------------------------------------
def test_review_r17_a_held_ledger_blocks_a_second_open_until_it_is_closed(meta, monkeypatch):
    monkeypatch.setattr(meta_api, "LOCK_WAIT_S", 0.3)
    held = meta_api.open_ledger()
    with pytest.raises(OpinionError) as raised:
        meta_api.open_ledger()
    assert raised.value.reason == "usage ledger busy"
    held.close()
    meta_api.open_ledger().close()   # free again


def test_review_r17_a_waiting_open_gets_the_ledger_when_its_holder_closes_it(meta):
    held, got = meta_api.open_ledger(), []
    waiter = threading.Thread(target=lambda: got.append(meta_api.open_ledger()))
    waiter.start()
    time.sleep(0.3)
    assert got == []   # still waiting
    held.close()
    waiter.join(20)
    assert len(got) == 1
    got[0].close()


def test_review_r17_the_baseten_ledger_is_not_locked(meta, monkeypatch, tmp_path):
    monkeypatch.setenv("PART5_BASETEN_USAGE_FILE", str(tmp_path / "baseten.jsonl"))
    first, second = muse_spark._open_ledger(), muse_spark._open_ledger()
    first.close()
    second.close()


class Blocking(Fake):
    """A call that stays in flight until `release` is set."""

    def __init__(self, payload):
        super().__init__(payload)
        self.in_call, self.release = threading.Event(), threading.Event()

    def respond(self, body):
        self.in_call.set()
        assert self.release.wait(20)
        return super().respond(body)


class Counting(Fake):
    def __init__(self, payload):
        super().__init__(payload)
        self.counted = threading.Event()

    def count(self, body):
        self.counted.set()
        return super().count(body)


def test_review_r17_two_runs_cannot_both_pass_the_cap(take, meta, monkeypatch):
    """Each call is estimated at $0.024 and costs $0.01295; the cap of $0.03 holds the first only."""
    monkeypatch.setenv(CAP_ENV, "0.03")
    first, second, done = Blocking(answer()), Counting(answer()), {}

    def run(name, fake):
        done[name] = attach(take, meta, fake)["second_opinion"]

    a = threading.Thread(target=run, args=("first", first))
    a.start()
    assert first.in_call.wait(20)
    b = threading.Thread(target=run, args=("second", second))
    b.start()
    assert second.counted.wait(20)
    time.sleep(0.3)   # the second run has counted and is waiting for the ledger
    assert b.is_alive() and second.bodies == []
    first.release.set()
    a.join(20)
    b.join(20)
    assert done["first"]["status"] == "ok"
    assert (done["second"]["status"], done["second"]["reason"]) == ("fallback", "spend cap reached")
    assert second.bodies == [] and sorted(second.deleted) == ["file-1", "file-2"]
    assert len(meta.ledger.read_text().splitlines()) == 1 and meta_api.spent() == pytest.approx(0.01295)
