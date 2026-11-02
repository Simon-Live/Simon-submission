"""The API's own error message on an HTTP failure's reason (TICKET-099, part5/opinion/meta_api.py `_api_detail`).

An HTTP error from the Meta Model API keeps its error type and message, scrubbed, after the status line, so a 400 can be
told from its reason instead of the status alone. The key, a Bearer token or Authorization header, a URL and a long
quoted run never reach it. The client is the real `HttpClient` over a fake opener (no socket); the Ask path is checked
end to end, so the document's `fallback_reason` is what a page shows.
"""
import io
import json
import unicodedata
import urllib.error

import pytest
from test_ask_agent import QUESTION
from test_ask_cli_api import valid
from test_ask_tools import golden_take
from test_history_opinion import KEY, ledger_lines, meta  # noqa: F401  (meta is a fixture)
from test_second_opinion import FakeOpener, FakeResponse

from part5.ask import agent
from part5.opinion import guard, meta_api
from part5.opinion.meta_api import OpinionError

TOKEN = "tok" + "en-0123456789abcdef0123456789"   # built at run time: the publish gate refuses key-shaped literals
URL = "https://files.example.invalid/v1/responses?id=1"
FAKE_BODY = {"input": [{"role": "user", "content": "x"}]}


def refused(code, body):
    """The HTTPError the API answers with: status `code`, the body `body` (bytes, or JSON for anything else)."""
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return urllib.error.HTTPError(meta_api.API, code, "refused", {}, io.BytesIO(raw))


def reason_of(error, key=KEY):
    client = meta_api.HttpClient(key)
    client._opener = FakeOpener(error)
    with pytest.raises(OpinionError) as raised:
        client.respond(FAKE_BODY)
    return raised.value.reason


def test_a_400_keeps_the_apis_error_type_and_message():
    error = {"error": {"type": "invalid_request_error", "message": "Unknown parameter: 'previous_response_id'."}}
    assert reason_of(refused(400, error)) == (
        "HTTP 400 on responses: invalid_request_error: Unknown parameter: 'previous_response_id'.")


def test_the_key_a_bearer_token_an_authorization_header_and_a_url_are_taken_out():
    message = f"Bad credentials {KEY}; see {URL} or www.example.invalid/docs/a; Authorization: Bearer {TOKEN}"
    reason = reason_of(refused(400, {"error": {"type": "invalid_request_error", "message": message}}))
    assert reason.startswith("HTTP 400 on responses: invalid_request_error: Bad credentials [removed]")
    for secret in (KEY, TOKEN, "Bearer", URL, "example.invalid", "files."):
        assert secret not in reason
    assert "Authorization" not in reason


def test_a_token_after_bearer_and_a_bare_host_path_are_taken_out_too():
    reason = reason_of(refused(400, {"error": {"type": "auth", "message": f"bearer {TOKEN} for host.example.invalid/x/y"}}))
    assert TOKEN not in reason and "example.invalid" not in reason and reason.startswith("HTTP 400 on responses: auth: ")


def test_a_long_quoted_echo_and_a_long_id_are_taken_out():
    echo = "Your right elbow bends a great deal more than the example at 0.7 s"
    message = f"Invalid input 'previous_response_id': \"{echo}\" in resp_0123456789abcdefghijklmnopq"
    reason = reason_of(refused(400, {"error": {"type": "invalid_request_error", "message": message}}))
    assert echo not in reason and "resp_0123" not in reason and "'previous_response_id'" in reason


def test_the_detail_is_one_line_cut_to_160_characters_so_the_reason_fits_the_ask_document():
    reason = reason_of(refused(400, {"error": {"type": "invalid_request_error", "message": "word\n\t " * 200}}))
    head, detail = reason.split(": ", 1)
    assert head == "HTTP 400 on responses" and len(detail) == 160 and detail.endswith("...") and "\n" not in reason
    assert len(reason) <= 200


@pytest.mark.parametrize("body", [
    {}, [], 5, b"<html>Bad gateway</html>", b"", b"\xff\xfe", {"error": {}}, {"error": {"type": 3, "message": None}},
    {"error": 7}, {"error": {"message": "  "}},
], ids=repr)
def test_a_body_with_no_error_text_leaves_the_status_line_alone(body):
    assert reason_of(refused(502, body)) == "HTTP 502 on responses"


def test_an_error_as_text_or_with_only_a_code_is_kept():
    assert reason_of(refused(400, {"error": "Request is malformed."})) == "HTTP 400 on responses: Request is malformed."
    assert reason_of(refused(404, {"error": {"code": "not_found", "message": "No such response."}})) == (
        "HTTP 404 on responses: not_found: No such response.")


def test_only_an_http_error_has_a_detail_and_the_other_reasons_are_unchanged():
    client = meta_api.HttpClient(KEY)
    client._opener = FakeOpener(TimeoutError(), FakeResponse(200, b"not json"))
    for expected in ("timeout on responses", "unreadable response on responses"):
        with pytest.raises(OpinionError) as raised:
            client.respond(FAKE_BODY)
        assert raised.value.reason == expected


def test_the_count_and_the_upload_steps_carry_the_detail_too(tmp_path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"video")
    client = meta_api.HttpClient(KEY)
    client._opener = FakeOpener(refused(413, {"error": {"type": "too_large", "message": "File is too big."}}),
                                refused(400, {"error": {"type": "bad", "message": "No input."}}))
    with pytest.raises(OpinionError) as upload:
        client.upload(clip)
    with pytest.raises(OpinionError) as count:
        client.count({"model": "m", "input": []})
    assert (upload.value.reason, count.value.reason) == ("HTTP 413 on upload: too_large: File is too big.",
                                                          "HTTP 400 on count: bad: No input.")


def test_an_ask_that_gets_a_400_shows_the_scrubbed_message_as_its_fallback_reason(meta):
    message = f"Invalid turn at {URL} with {KEY}. Authorization: Bearer {TOKEN}"
    client = meta_api.HttpClient(KEY)
    client._opener = FakeOpener(FakeResponse(200, b'{"input_tokens": 120}'),
                                refused(400, {"error": {"type": "invalid_request_error", "message": message}}))
    doc = valid(agent.ask_run(QUESTION, golden_take(), client=client))
    assert doc["source"] == "measured_facts"
    assert doc["fallback_reason"] == "HTTP 400 on responses: invalid_request_error: Invalid turn at [removed] with [removed]. [removed]"
    assert len(doc["fallback_reason"]) <= 200
    shown = json.dumps(doc) + meta.ledger.read_text()
    for secret in (KEY, TOKEN, URL, "example.invalid", "Bearer"):
        assert secret not in shown
    assert ledger_lines(meta)[-1]["http_status"] == 400


# ---- R4 of the 1.14.1 review: `_scrubbed` was a heuristic; the detail is now held to the guards' own check ------------
MASKED = "mk_live_********ghij"   # how an API echoes a key back: no replace of the key finds it


@pytest.mark.parametrize("code", [401, 403])
def test_r4_a_401_and_a_403_give_no_detail_whatever_the_body_says(code):
    body = {"error": {"type": "invalid_api_key", "message": f"Incorrect API key provided: {MASKED}."}}
    assert reason_of(refused(code, body)) == f"HTTP {code} on responses"
    assert reason_of(refused(code, {"error": "Forbidden by the gateway"})) == f"HTTP {code} on responses"


def test_r4_a_masked_key_is_taken_out_of_any_other_status_too():
    body = {"error": {"type": "invalid_request_error", "message": f"Bad key {MASKED} in the header."}}
    reason = reason_of(refused(400, body))
    assert reason == "HTTP 400 on responses: invalid_request_error: Bad key [removed] in the header."
    assert "mk_live" not in reason and "ghij" not in reason and "*" not in reason


def test_r4_control_and_bidi_characters_are_taken_out_of_the_detail():
    message = "Invalid \x1b[31mred\x1b[0m input ‮evil‬ ​zero \x07bell"
    reason = reason_of(refused(400, {"error": {"type": "invalid_request_error", "message": message}}))
    assert reason == "HTTP 400 on responses: invalid_request_error: Invalid [31mred[0m input evil zero bell"
    assert all(unicodedata.category(c) not in ("Cc", "Cf") for c in reason)


@pytest.mark.parametrize("message", [
    "Ask your coach about the input.", "Visit example.com for help.", "Your injury is not a valid parameter.",
    "See mailto:help@example.invalid.",
])
def test_r4_a_detail_that_fails_the_guards_unsafe_check_is_dropped_whole(message):
    """`guard.unsafe_problem` is the check every text shown to a follower passes; a detail failing it is left off."""
    assert guard.unsafe_problem(message) is not None
    assert reason_of(refused(400, {"error": {"type": "invalid_request_error", "message": message}})) == (
        "HTTP 400 on responses")
