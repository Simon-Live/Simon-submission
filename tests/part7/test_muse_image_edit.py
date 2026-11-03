"""TICKET-330: the live muse-image-1.0 edit shape and Meta's error message kept, masked, in a failure reason.

The fixtures are recorded from the live calls of 2026-11-02 (masked: the returned picture is replaced by a 4x4 PNG)."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any
import urllib.error

import pytest

from part7 import history_api, muse_fix_api

FIXTURES = Path(__file__).parent / "fixtures" / "muse_image"
KEY = "mk-live-0123456789abcdefSECRET"
PNG = base64.b64decode(json.loads((FIXTURES / "edit-200.json").read_text())["data"][0]["b64_json"])
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class Resp:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self) -> "Resp":
        return self

    def __exit__(self, *a: Any) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


class Opener:
    """Records the request and answers with a recorded body, or raises the recorded HTTP error."""

    def __init__(self, body: bytes, status: int = 200):
        self.body, self.status = body, status
        self.seen: dict[str, Any] = {}

    def open(self, request: Any, timeout: float) -> Resp:
        self.seen = {"url": request.full_url, "method": request.get_method(), "data": request.data,
                     "type": request.get_header("Content-type"), "auth": request.get_header("Authorization")}
        if self.status != 200:
            raise urllib.error.HTTPError(request.full_url, self.status, "Bad Request", {}, io.BytesIO(self.body))
        return Resp(self.body)


PROMPT = muse_fix_api.edit_prompt("right_elbow", 77.9, 131.2)


def transport(body: bytes, status: int = 200) -> tuple[muse_fix_api.Transport, Opener]:
    tr, op = muse_fix_api.Transport(KEY), Opener(body, status)
    tr._opener = op
    return tr, op


def test_edit_sends_the_documented_json_body_and_reads_the_recorded_answer(tmp_path: Path) -> None:
    tr, op = transport(fixture("edit-200.json"))
    out = muse_fix_api.edit_image(JPG, PROMPT, transport=tr, state=tmp_path)
    assert op.seen["url"] == "https://api.meta.ai/v1/images/edits" and op.seen["method"] == "POST"
    assert op.seen["type"] == "application/json" and op.seen["auth"] == "Bearer " + KEY
    body = json.loads(op.seen["data"])
    assert body["model"] == "muse-image-1.0" and body["n"] == 1 and body["prompt"] == PROMPT
    assert body["response_format"] == "b64_json" and body["output_format"] == "png"
    (frame,) = (item["image_url"] for item in body["images"])
    assert body["reasoning_strength"] == "high"
    assert frame == "data:image/jpeg;base64," + base64.b64encode(JPG).decode()
    assert "image[]" not in op.seen["data"].decode() and "multipart" not in op.seen["type"]
    assert out["image"] == PNG and out["kind"] == "png" and out["model"] == "muse-image-1.0"


def test_edit_body_refuses_a_picture_that_is_not_png_or_jpeg() -> None:
    with pytest.raises(history_api.HistoryError):
        muse_fix_api.edit_body("p", b"RIFF....WEBP")


def test_a_400_keeps_metas_message_in_the_reason(tmp_path: Path) -> None:
    tr, _ = transport(fixture("edit-400-image-array.json"), 400)
    with pytest.raises(history_api.HistoryError) as err:
        muse_fix_api.edit_image(JPG, PROMPT, transport=tr, state=tmp_path)
    reason = err.value.reason
    assert reason.startswith("HTTP 400 on image edit: `image[]` is not a valid image key")
    assert len(reason) <= len("HTTP 400 on image edit: ") + history_api.ERROR_CHARS and KEY not in reason


def test_an_error_body_loses_keys_tokens_and_payloads_and_is_cut_short() -> None:
    b64 = base64.b64encode(b"\x89PNG" + bytes(range(256)) * 4).decode()
    message = (f"bad key {KEY} with Bearer abc.def and data:image/png;base64,{b64} plus raw {b64[:120]} "
               "sk-proj_ABCDEFGH1234 " + "and more words " * 20)
    tr, _ = transport(json.dumps({"error": {"message": message}}).encode(), 401)
    with pytest.raises(history_api.HistoryError) as err:
        tr.respond({"model": "m"})
    reason = err.value.reason
    assert reason.startswith("HTTP 401 on responses: bad key <redacted> with <masked>")
    for leak in (KEY, "abc.def", b64[:40], "sk-proj", "base64,"):
        assert leak not in reason
    assert reason.endswith("...") and len(reason) <= len("HTTP 401 on responses: ") + history_api.ERROR_CHARS


def test_a_plain_text_body_is_kept_and_an_empty_one_leaves_the_status_alone() -> None:
    tr, _ = transport(b"upstream timed out\n", 504)
    with pytest.raises(history_api.HistoryError) as err:
        tr.respond({"model": "m"})
    assert err.value.reason == "HTTP 504 on responses: upstream timed out"
    tr, _ = transport(b"", 429)
    with pytest.raises(history_api.HistoryError) as err:
        tr.respond({"model": "m"})
    assert err.value.reason == "HTTP 429 on responses"


class CountingTransport:
    """A transport that must never be reached: a picture that cannot be sent fails before the call and the reserve."""

    def __init__(self) -> None:
        self.edits = 0

    def edit(self, prompt: str, frame: bytes) -> dict[str, Any]:
        self.edits += 1
        return json.loads(fixture("edit-200.json"))


def ledger_lines(state: Path) -> list[str]:
    path = history_api.ledger_path(state)
    return path.read_text().splitlines() if path.is_file() else []


@pytest.mark.parametrize("frame", [JPG[:4] + b"\x00" * muse_fix_api.MAX_IMAGE_BYTES, b"RIFF....WEBPVP8 "],
                         ids=["over_the_size_limit", "not_png_or_jpeg"])
def test_a_picture_that_cannot_be_sent_reserves_nothing(tmp_path: Path, frame: bytes) -> None:  # R2, R3
    tr = CountingTransport()
    with pytest.raises(history_api.HistoryError) as err:
        muse_fix_api.edit_image(frame, PROMPT, transport=tr, state=tmp_path)
    assert err.value.reason == "an image could not be used" and tr.edits == 0 and ledger_lines(tmp_path) == []


def test_a_picture_at_the_size_limit_is_sent(tmp_path: Path) -> None:  # R3: the limit is inclusive
    tr = CountingTransport()
    frame = JPG[:4] + b"\x00" * (muse_fix_api.MAX_IMAGE_BYTES - 4)
    assert len(frame) == muse_fix_api.MAX_IMAGE_BYTES
    assert muse_fix_api.edit_image(frame, PROMPT, transport=tr, state=tmp_path)["kind"] == "png"
    assert tr.edits == 1 and len(ledger_lines(tmp_path)) == 2  # one reserve, one settle


def test_the_screen_gets_plain_words_and_the_record_keeps_metas_message() -> None:  # R1
    from part7 import history_report

    raw = history_api.HistoryError("HTTP 400 on image edit: `image[]` is not a valid image key")
    assert history_report._reason(raw) == history_report.MSG_MODEL_FAILED
    assert history_report.reason_detail(raw) == "HTTP 400 on image edit: `image[]` is not a valid image key"
    for reason in ("timeout on responses", "request failed on upload (OSError)", "unreadable response on count"):
        assert history_report.screen_reason(reason) == history_report.MSG_MODEL_FAILED
    capped = "estimated $0.20 is over the per-call limit of $0.10"
    assert history_report.screen_reason(capped) == capped  # already plain words
