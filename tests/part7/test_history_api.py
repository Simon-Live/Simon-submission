"""TICKET-181 AC-2 to AC-6: history_api.ask with a fake transport; no network, no key (docs/specs/history-meta.md)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from part7 import history_api as api
from part7 import history_guard, history_prompt
from test_history_prompt import make  # the packing test's fixture builder


class FakeTransport:
    def __init__(self, *, count: int = 20_000, answer: str = '{"summary": {}}', fail: str | None = None,
                 usage: dict[str, Any] | None = None, ledger: Path | None = None):
        self.count_value, self.answer, self.fail, self.ledger = count, answer, fail, ledger
        self.usage = usage or {"input_tokens": 20_000, "output_tokens": 500,
                               "input_tokens_details": {"cached_tokens": 10_000}}
        self.calls: list[str] = []
        self.uploaded: list[str] = []
        self.deleted: list[str] = []
        self.bodies: list[dict[str, Any]] = []
        self.ledger_at_call: str | None = None

    def upload(self, path: str) -> str:
        if self.fail == "upload":
            raise api.HistoryError("HTTP 500 on upload")
        self.calls.append("upload")
        self.uploaded.append(path)
        return f"file-{len(self.uploaded)}"

    def delete(self, file_id: str) -> None:
        self.calls.append("delete")
        self.deleted.append(file_id)

    def count(self, body: dict[str, Any]) -> int:
        self.calls.append("count")
        self.bodies.append(body)
        if self.fail == "count":
            raise api.HistoryError("HTTP 400 on count")
        return self.count_value

    def respond(self, body: dict[str, Any]) -> Any:
        self.calls.append("respond")
        if self.ledger is not None:
            self.ledger_at_call = self.ledger.read_text() if self.ledger.exists() else ""
        if self.fail == "respond":
            raise api.HistoryError("HTTP 500 on responses")
        return {"status": "completed", "usage": self.usage,
                "output": [{"type": "message", "content": [{"type": "output_text", "text": self.answer}]}]}


def packed(videos: bool = True, consent: bool = True) -> dict[str, Any]:
    facts, rows = make([60, 70, 80])
    return history_prompt.pack("e1", facts, rows, teacher_clip="/t.mp4", teacher_duration_s=20.0,
                               video_consent=consent and videos)


def ledger_lines(state: Path) -> list[dict[str, Any]]:
    path = state / "history" / "spend.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_ask_returns_text_and_usage_with_cost_and_clips(tmp_path):
    fake = FakeTransport()
    text, usage = api.ask(packed(), transport=fake, state=tmp_path)
    assert text == '{"summary": {}}'
    assert usage == {"input_tokens": 20_000, "cached_tokens": 10_000, "output_tokens": 500, "usd": 0.016125,
                     "clips_sent": 3}  # the three take clips; the teacher clip is not counted
    assert api.price(20_000, 500, 10_000) == usage["usd"]


def test_caps_a_call_over_the_per_call_limit_is_refused_before_the_call(tmp_path, monkeypatch):
    fake = FakeTransport(count=500_000)  # 500k input tokens alone cost $0.625
    with pytest.raises(api.HistoryError) as err:
        api.ask(packed(), transport=fake, state=tmp_path)
    assert "per-call limit" in err.value.reason
    assert "respond" not in fake.calls and ledger_lines(tmp_path) == []
    monkeypatch.setenv(api.CALL_MAX_ENV, "1.00")
    api.ask(packed(), transport=FakeTransport(count=500_000), state=tmp_path)  # the env changes the limit
    monkeypatch.setenv(api.CALL_MAX_ENV, "garbage")
    with pytest.raises(api.HistoryError):
        api.ask(packed(), transport=FakeTransport(count=500_000), state=tmp_path / "other")


def test_caps_the_total_cap_refuses_and_settled_cost_replaces_the_estimate(tmp_path, monkeypatch):
    monkeypatch.setenv(api.CAP_ENV, "0.10")
    api.ask(packed(), transport=FakeTransport(), state=tmp_path)  # estimate 0.0558, real cost 0.016125
    assert api.spent_usd(tmp_path / "history" / "spend.jsonl") == pytest.approx(0.016125)
    for _ in range(2):
        api.ask(packed(), transport=FakeTransport(), state=tmp_path)  # three calls fit: 0.0484 + 0.0558 passes 0.10
    fake = FakeTransport()
    with pytest.raises(api.HistoryError) as err:
        api.ask(packed(), transport=fake, state=tmp_path)
    assert err.value.reason == "spend cap reached" and "respond" not in fake.calls
    assert len(fake.deleted) == 4  # the refused call still removes its uploads
    assert api.spent_usd(tmp_path / "history" / "spend.jsonl") <= 0.10
    assert api.CAP_USD == 10.0 and api.CALL_MAX_USD == 0.50


def test_caps_tokens_are_counted_first_and_uploads_come_before_the_count(tmp_path):
    fake = FakeTransport()
    api.ask(packed(), transport=fake, state=tmp_path)
    assert fake.calls.index("count") < fake.calls.index("respond")
    assert fake.calls[:4] == ["upload"] * 4 and fake.calls.index("count") == 4
    assert "max_output_tokens" in fake.bodies[0]


def test_ledger_before_call_line_is_written_under_flock_with_no_user_or_text(tmp_path):
    ledger = tmp_path / "history" / "spend.jsonl"
    fake = FakeTransport(ledger=ledger)
    api.ask(packed(), transport=fake, state=tmp_path)
    before = [json.loads(line) for line in fake.ledger_at_call.splitlines()]
    assert len(before) == 1 and before[0]["kind"] == "reserve" and before[0]["usd"] > 0  # present at the call
    lines = ledger_lines(tmp_path)
    assert [line["kind"] for line in lines] == ["reserve", "settle"] and lines[0]["call"] == lines[1]["call"]
    allowed = {"call", "kind", "model", "usd", "when", "input_tokens", "cached_tokens", "output_tokens", "clips_sent",
               "seconds"}
    assert all(set(line) <= allowed for line in lines)
    raw = ledger.read_text()
    assert "Take " not in raw and "job0000" not in raw and "/clips" not in raw and "file-" not in raw
    assert (tmp_path / "history" / "spend.jsonl.lock").exists()


def test_ledger_before_call_a_failed_call_still_counts_at_its_estimate(tmp_path):
    with pytest.raises(api.HistoryError):
        api.ask(packed(), transport=FakeTransport(fail="respond"), state=tmp_path)
    lines = ledger_lines(tmp_path)
    assert [line["kind"] for line in lines] == ["reserve"]
    assert api.spent_usd(tmp_path / "history" / "spend.jsonl") == lines[0]["usd"] > 0


def test_ledger_before_call_concurrent_reservations_cannot_both_pass_the_cap(tmp_path, monkeypatch):
    monkeypatch.setenv(api.CAP_ENV, "0.05")  # room for one 0.042 estimate, not two
    results: list[str] = []

    def go() -> None:
        try:
            api.ask(packed(videos=False), transport=FakeTransport(), state=tmp_path)
            results.append("ok")
        except api.HistoryError as exc:
            results.append(exc.reason)

    threads = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1 and results.count("spend cap reached") == 3


def test_ledger_unwritable_stops_before_the_call(tmp_path):
    blocker = tmp_path / "history"
    blocker.write_text("a file where the folder should be")
    fake = FakeTransport()
    with pytest.raises(api.HistoryError) as err:
        api.ask(packed(), transport=fake, state=tmp_path)
    assert err.value.reason == "spend ledger not writable" and "respond" not in fake.calls
    assert fake.deleted == ["file-1", "file-2", "file-3", "file-4"]


def test_files_deleted_every_path_success(tmp_path):
    fake = FakeTransport()
    api.ask(packed(), transport=fake, state=tmp_path)
    assert len(fake.uploaded) == 4 and sorted(fake.deleted) == sorted(f"file-{i}" for i in range(1, 5))


@pytest.mark.parametrize("fail", ["respond", "count"])
def test_files_deleted_every_path_model_and_count_errors(tmp_path, fail):
    fake = FakeTransport(fail=fail)
    with pytest.raises(api.HistoryError):
        api.ask(packed(), transport=fake, state=tmp_path)
    assert len(fake.deleted) == 4


def test_files_deleted_every_path_upload_error_deletes_what_went_up(tmp_path):
    class Flaky(FakeTransport):
        def upload(self, path: str) -> str:
            if len(self.uploaded) == 2:
                raise api.HistoryError("HTTP 500 on upload")
            return super().upload(path)

    fake = Flaky()
    with pytest.raises(api.HistoryError):
        api.ask(packed(), transport=fake, state=tmp_path)
    assert fake.deleted == ["file-1", "file-2"] and "respond" not in fake.calls


def test_files_deleted_every_path_guard_failure_after_ask(tmp_path):
    p = packed()
    fake = FakeTransport(answer="this is not JSON at all")
    text, _ = api.ask(p, transport=fake, state=tmp_path)
    assert len(fake.deleted) == 4  # gone before the guard sees the answer
    kept, rejected = history_guard.check(text, p["facts"], None, None)
    assert kept["summary"]["source"] == "fact_table" and rejected[0]["item"] == "answer"


def test_files_deleted_every_path_a_failed_delete_does_not_hide_the_answer(tmp_path):
    class NoDelete(FakeTransport):
        def delete(self, file_id: str) -> None:
            raise api.HistoryError("HTTP 404 on delete")

    text, _ = api.ask(packed(), transport=NoDelete(), state=tmp_path)
    assert text


def test_request_shape_model_cache_schema_and_expiry(tmp_path):
    fake = FakeTransport()
    api.ask(packed(), transport=fake, state=tmp_path)
    body = fake.bodies[0]
    assert body["model"] == "muse-spark-1.3" and "contributor" not in json.dumps(body)
    assert body["prompt_cache_key"] == "simon-history" and body["prompt_cache_retention"] == "in_memory"
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["schema"] == history_prompt.SCHEMA
    content = body["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": history_prompt.INSTRUCTIONS}
    assert [c["file_id"] for c in content if c["type"] == "input_file"] == ["file-1", "file-2", "file-3", "file-4"]
    assert api.MODEL == "muse-spark-1.3" and api.EXPIRES_AFTER_S == 3600
    assert body["store"] is False and api.STORE_FALSE_ACCEPTED and api.STRICT_SCHEMA


def test_request_shape_store_false_and_strict_are_switchable(tmp_path, monkeypatch):
    p = packed()
    ids = {i: "f" for i, c in enumerate(p["content"]) if c["type"] == "video"}
    assert api.build_body(p, ids)["store"] is False
    monkeypatch.setattr(api, "STORE_FALSE_ACCEPTED", False)
    assert "store" not in api.build_body(p, ids)
    monkeypatch.setattr(api, "STRICT_SCHEMA", False)
    assert "text" not in api.build_body(p, ids)  # the guard's JSON-parse fallback handles the plain answer


def test_request_shape_upload_form_carries_expires_after(monkeypatch):
    seen: dict[str, Any] = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"id": "file-x"}'

    class Opener:
        def open(self, request, timeout):
            seen.update(url=request.full_url, data=request.data, method=request.get_method(),
                        auth=request.get_header("Authorization"))
            return Resp()

    clip = Path(__file__)
    client = api.HttpClient("k" * 12)
    client._opener = Opener()
    assert client.upload(str(clip)) == "file-x"
    assert seen["url"] == "https://api.meta.ai/v1/files" and seen["method"] == "POST"
    assert b'name="expires_after[seconds]"\r\n\r\n3600' in seen["data"] and b"user_data" in seen["data"]
    assert seen["auth"] == "Bearer " + "k" * 12
    client.delete("file-x")
    assert seen["url"].endswith("/files/file-x") and seen["method"] == "DELETE"


def test_http_client_errors_become_history_errors_without_secrets():
    import urllib.error

    class Boom:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(request.full_url, 429, "secret body", {}, None)

    client = api.HttpClient("sk-very-secret")
    client._opener = Boom()
    with pytest.raises(api.HistoryError) as err:
        client.respond({"model": "m"})
    assert err.value.reason == "HTTP 429 on responses" and "secret" not in err.value.reason

    class Weird:
        def open(self, request, timeout):
            class R:
                def __enter__(s): return s
                def __exit__(s, *a): return False
                def read(s): return b"not json"
            return R()

    client._opener = Weird()
    with pytest.raises(api.HistoryError) as err:
        client.count({"model": "m", "input": []})
    assert err.value.reason == "unreadable response on count"


def test_consent_and_private_no_consent_sends_json_only(tmp_path):
    fake = FakeTransport()
    p = packed(consent=False)
    api.ask(p, transport=fake, state=tmp_path)
    assert fake.uploaded == [] and p["clips_sent"] == 0
    assert all(c["type"] == "input_text" for c in fake.bodies[0]["input"][0]["content"])


def test_consent_and_private_ask_refuses_video_without_the_flag(tmp_path):
    p = packed()
    p["video_consent"] = False
    fake = FakeTransport()
    with pytest.raises(api.HistoryError) as err:
        api.ask(p, transport=fake, state=tmp_path)
    assert err.value.reason == "no video consent" and fake.calls == []


def test_consent_and_private_private_clip_is_never_uploaded(tmp_path):
    facts, rows = make([60, 70, 80], private=(3,))
    p = history_prompt.pack("e1", facts, rows, video_consent=True)
    fake = FakeTransport()
    api.ask(p, transport=fake, state=tmp_path)
    assert "/clips/take3.mp4" not in fake.uploaded and len(fake.uploaded) == 2


def test_errors_empty_incomplete_and_missing_key(tmp_path):
    with pytest.raises(api.HistoryError) as err:
        api.ask(packed(), transport=FakeTransport(answer="  "), state=tmp_path)
    assert err.value.reason == "the model answered with no text" and err.value.usage["input_tokens"] == 20_000

    class Incomplete(FakeTransport):
        def respond(self, body):
            out = super().respond(body)
            out["status"] = "incomplete"
            return out

    with pytest.raises(api.HistoryError) as err:
        api.ask(packed(), transport=Incomplete(), state=tmp_path)
    assert "stopped" in err.value.reason
    keys_dir = tmp_path / "keys"
    keys_dir.mkdir()
    with pytest.raises(api.HistoryError) as err:
        api.ask(packed(), state=tmp_path, keys_dir=keys_dir)
    assert err.value.reason == "no Meta Model API key"


def test_output_text_and_usage_reading_are_tolerant():
    assert api.output_text({"output_text": "plain"}) == "plain"
    assert api.output_text({"output": [{"type": "reasoning"}, {"content": [{"text": "a"}, {"text": "b"}]}]}) == "a\nb"
    assert api.output_text(None) == ""
    assert api.read_usage({"usage": {"input_tokens": True, "output_tokens": "x"}}) == {
        "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0}
    assert api.price(0, 0) == 0 and api.price(10, 0, cached_tokens=99) == api.price(10, 0, 10)


def test_ledger_line_survives_a_damaged_ledger(tmp_path):
    path = tmp_path / "history" / "spend.jsonl"
    path.parent.mkdir()
    path.write_text('not json\n{"call": "a", "kind": "reserve", "usd": 0.5}\n[1]\n')
    assert api.spent_usd(path) == 0.5
    assert api.spent_usd(tmp_path / "missing.jsonl") == 0.0


def test_reserve_prices_video_by_seconds_because_the_counter_is_blind(tmp_path):
    facts, rows = make([60, 70, 80, 90, 50], duration=30.0)
    p = history_prompt.pack("e1", facts, rows, teacher_clip="/t.mp4", teacher_duration_s=30.0, video_consent=True)
    assert p["clips_sent"] == 4 and p["video_seconds"] == 150.0  # 4 take clips plus the teacher clip
    q = history_prompt.pack("e1", facts, rows[:4], video_consent=True)  # 4 clips of 30 s
    assert q["video_seconds"] == 120.0
    fake = FakeTransport(count=1000)  # the counter's number: text plus about 180 per clip
    api.ask(q, transport=fake, state=tmp_path)
    reserve = ledger_lines(tmp_path)[0]
    assert reserve["input_tokens"] == 1000 + 4 * 30 * 220 == 27_400  # about 26,400 for video plus the counted text
    assert reserve["usd"] == api.price(27_400, api.MAX_OUTPUT_TOKENS)


def test_reserve_feeds_the_per_call_cap(tmp_path, monkeypatch):
    facts, rows = make([60, 70, 80, 90], duration=60.0)
    q = history_prompt.pack("e1", facts, rows, video_consent=True)
    monkeypatch.setenv(api.CALL_MAX_ENV, "0.04")  # 1000 text + 52,800 video tokens would cost about 0.084
    fake = FakeTransport(count=1000)
    with pytest.raises(api.HistoryError) as err:
        api.ask(q, transport=fake, state=tmp_path)
    assert "per-call limit" in err.value.reason and "respond" not in fake.calls


def test_a_request_never_carries_more_than_five_videos(tmp_path):
    facts, rows = make(list(range(50, 70)), duration=5.0)
    p = history_prompt.pack("e1", facts, rows, teacher_clip="/t.mp4", teacher_duration_s=5.0, video_consent=True)
    fake = FakeTransport()
    api.ask(p, transport=fake, state=tmp_path)
    sent = [c for c in fake.bodies[0]["input"][0]["content"] if c["type"] == "input_file"]
    assert len(sent) <= api.MAX_VIDEOS == 5 and len(fake.uploaded) == len(sent)
    p["content"] += [{"type": "video", "path": "/x.mp4", "label": "Take 99"}]
    p["content"] += [{"type": "video", "path": "/y.mp4", "label": "Take 98"}]
    fake = FakeTransport()
    with pytest.raises(api.HistoryError) as err:
        api.ask(p, transport=fake, state=tmp_path / "s2")
    assert "more than 5 videos" in err.value.reason and fake.calls == []


def test_caps_are_checked_before_any_file_is_uploaded(tmp_path, monkeypatch):  # R6
    monkeypatch.setenv(api.CAP_ENV, "0.01")  # under the cost of any one call
    fake = FakeTransport()
    with pytest.raises(api.HistoryError) as err:
        api.ask(packed(), transport=fake, state=tmp_path)
    assert err.value.reason == "spend cap reached" and fake.calls == [] and ledger_lines(tmp_path) == []
    monkeypatch.delenv(api.CAP_ENV)
    monkeypatch.setenv(api.CALL_MAX_ENV, "0.001")
    fake = FakeTransport()
    with pytest.raises(api.HistoryError) as err:
        api.ask(packed(), transport=fake, state=tmp_path)
    assert "per-call limit" in err.value.reason and fake.calls == []  # nothing left the machine
