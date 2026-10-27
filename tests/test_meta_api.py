import json

import pytest

from part2 import meta_api


def test_sam_video_cost_has_50_frame_minimum():
    assert meta_api.sam_video_cost(10) == pytest.approx(0.01)
    assert meta_api.sam_video_cost(1000) == pytest.approx(0.20)


def test_budget_refuses_call_over_limit(tmp_path):
    ledger = tmp_path / "spend.jsonl"
    b = meta_api.Budget(limit_usd=1.0, remind_every_usd=0.5, ledger=ledger)
    b.reserve(0.9, "first")
    assert b.record(0.9, "first", "sam-3.1") == pytest.approx(0.9)
    with pytest.raises(meta_api.BudgetExceeded, match="over META_BUDGET_USD"):
        b.reserve(0.2, "second")
    assert b.spent() == pytest.approx(0.9)


def test_budget_zero_limit_refuses_paid_calls(tmp_path):
    b = meta_api.Budget(limit_usd=0, ledger=tmp_path / "s.jsonl")
    with pytest.raises(meta_api.BudgetExceeded):
        b.reserve(0.01, "x")
    b.reserve(0.0, "free")  # free calls (uploads, list) are fine


def test_sse_text_deltas_parses_stream():
    lines = [
        b"event: response.output_text.delta\n",
        b'data: {"type": "response.output_text.delta", "delta": "<0f>abc"}\n',
        b'data: {"type": "response.output_text.delta", "delta": "<1f>def"}\n',
        b"data: [DONE]\n",
    ]
    assert list(meta_api.sse_text_deltas(lines)) == ["<0f>abc", "<1f>def"]


def test_sse_raises_on_error_event():
    lines = [b'data: {"type": "error", "message": "boom"}\n']
    with pytest.raises(RuntimeError, match="stream error"):
        list(meta_api.sse_text_deltas(lines))


def test_multipart_contains_purpose_and_file(tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"fake-mp4")
    body, ctype = meta_api.multipart({"purpose": "user_data"}, "file", f)
    assert b"user_data" in body and b"fake-mp4" in body and b"clip.mp4" in body
    assert ctype.startswith("multipart/form-data; boundary=")


def test_content_helpers():
    assert meta_api.text("person") == {"type": "input_text", "text": "person"}
    assert meta_api.video("file_1") == {"type": "input_video", "file_id": "file_1"}
