"""The muse-spark backend through an injected client (ADR-0005; AC-010, AC-NFR-002 to AC-NFR-004).

No test here opens a socket: the client is a scripted fake, and the guard in `test_phrasing` turns
any real connection into a failure.
"""
import email
import io
import json
import re
import urllib.error
import urllib.request
import urllib.response

import pytest

from part5 import phrasing
from part5.phrasing import local_llm, muse_spark
from part5.phrasing.local_llm import HttpResult
from test_phrasing import (FAULTS, bare, FOOT, KNEE, NetworkUsed, clean_env, make_fault,  # noqa: F401
                           no_network)

SENTINEL = "sentinel-baseten-key-4f9a1c7e-do-not-leak"
GOOD = ["left foot sticking out too far", "right knee not bent enough", "leaning forward more than the example"]
UTC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


def reply(text, prompt=80, completion=40, reasoning=37):
    body = {"choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                      "completion_tokens_details": {"reasoning_tokens": reasoning}}}
    return HttpResult(200, body)


def http_error(code):
    return urllib.error.HTTPError(muse_spark.URL, code, "server said no", {}, io.BytesIO(b"{}"))


class Client:
    """Scripted client: each call takes the next item and returns it, or raises it if it is an exception."""

    def __init__(self, *script):
        self.script, self.requests = list(script), []

    def __call__(self, request):
        self.requests.append(request)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture
def live(monkeypatch, tmp_path):
    """The gate open: a key file holding the sentinel, META_LIVE=1, a temporary ledger."""
    key = tmp_path / "BASETEN_API_KEY"
    key.write_text(f"  {SENTINEL} \n")
    ledger = tmp_path / "home" / "baseten_usage.jsonl"
    monkeypatch.setenv("PART5_BASETEN_KEY_FILE", str(key))
    monkeypatch.setenv("PART5_BASETEN_USAGE_FILE", str(ledger))
    monkeypatch.setenv("META_LIVE", "1")
    return {"key": key, "ledger": ledger}


def ledger_lines(live):
    return [json.loads(x) for x in live["ledger"].read_text().splitlines()] if live["ledger"].exists() else []


def middle_fails(bad):
    """A client where fault 1 gets `bad` and faults 0 and 2 get good lines."""
    return Client(reply(GOOD[0]), bad, reply(GOOD[2]))


# ---- gate: key file and META_LIVE ---------------------------------------------------------------
def test_ac010_no_key_file_falls_back_to_template_and_names_the_missing_key(monkeypatch, tmp_path):
    missing = tmp_path / "secret-dir" / "BASETEN_API_KEY"
    monkeypatch.setenv("PART5_BASETEN_KEY_FILE", str(missing))
    monkeypatch.setenv("META_LIVE", "1")
    client = Client()
    lines, record = phrasing.phrase(FAULTS, "muse-spark", client=client)
    assert lines == [f["text"] for f in FAULTS]
    assert record["requested"] == "muse-spark" and record["backend"] == "template"
    assert record["fallback_reason"] == "no key" and record["model"] is None
    assert bare(record["faults"]) == [{"backend": "template", "model": None, "fallback_reason": "no key"}] * 3
    assert "secret-dir" not in json.dumps(record)
    assert client.requests == []


def test_ac010_scored_fields_equal_a_template_run_when_the_backend_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("PART5_BASETEN_KEY_FILE", str(tmp_path / "nope"))
    assert phrasing.phrase(FAULTS, "muse-spark")[0] == phrasing.phrase(FAULTS, "template")[0]


def test_without_meta_live_there_is_no_call_and_the_reason_says_live_calls_are_off(live, monkeypatch):
    monkeypatch.delenv("META_LIVE")
    client = Client()
    lines, record = phrasing.phrase(FAULTS, "muse-spark", client=client)
    assert record["backend"] == "template" and "live calls are off" in record["fallback_reason"]
    assert "META_LIVE" in record["fallback_reason"]
    assert lines == [f["text"] for f in FAULTS] and client.requests == []
    assert not live["ledger"].exists()


@pytest.mark.parametrize("value", ["0", "", "true", "yes"])
def test_only_meta_live_1_opens_the_gate(live, monkeypatch, value):
    monkeypatch.setenv("META_LIVE", value)
    assert muse_spark.unavailable() is not None
    monkeypatch.setenv("META_LIVE", "1")
    assert muse_spark.unavailable() is None


def test_no_key_is_reported_before_live_calls_are_off(monkeypatch, tmp_path):
    monkeypatch.setenv("PART5_BASETEN_KEY_FILE", str(tmp_path / "nope"))
    assert muse_spark.unavailable() == "no key"


def test_the_default_key_file_is_the_firm_operator_key(monkeypatch):
    monkeypatch.delenv("PART5_BASETEN_KEY_FILE", raising=False)
    assert str(muse_spark.key_path()).endswith("/.config/firm/operator-keys/BASETEN_API_KEY")
    monkeypatch.delenv("PART5_BASETEN_USAGE_FILE", raising=False)
    assert str(muse_spark.usage_path()).endswith("/.simon/baseten_usage.jsonl")


# ---- the request ----------------------------------------------------------------------------------
def test_the_request_is_the_documented_baseten_call(live):
    client = Client(reply(GOOD[0]))
    phrasing.phrase([FOOT], "muse-spark", timeout_s=10, client=client)
    (request,) = client.requests
    assert request["url"] == "https://inference.baseten.co/v1/chat/completions"
    assert request["body"]["model"] == "meta-models/muse-spark-open-1026"
    assert request["body"]["max_tokens"] >= 512
    assert request["timeout_s"] == 10
    assert request["headers"]["Authorization"] == f"Bearer {SENTINEL}", "whitespace stripped"
    assert request["headers"]["Content-Type"] == "application/json"


def test_the_request_carries_only_the_measured_fault_record(live):
    client = Client(reply(GOOD[0]))
    fault = make_fault(text="MARKER template text", body_part="legs", peak_deg=99.0)
    phrasing.phrase([fault], "muse-spark", client=client)
    system, user = client.requests[0]["body"]["messages"]
    assert system["role"] == "system" and user["role"] == "user"
    assert json.loads(user["content"]) == {
        "measure": "foot_out", "joint": "left_ankle", "side": "left", "direction": "more",
        "magnitude_deg": 14.2, "threshold_deg": 6.0, "frames": [20, 52]}
    everything = json.dumps(client.requests[0]["body"])
    for absent in ("MARKER", "peak_deg", "follower_frames", "body_part", SENTINEL):
        assert absent not in everything


def test_the_system_prompt_forbids_numbers_and_extra_faults_and_explains_the_measure(live):
    client = Client(reply(GOOD[0]))
    phrasing.phrase([FOOT], "muse-spark", client=client)
    system = client.requests[0]["body"]["messages"][0]["content"]
    assert "No second fault, no numbers" in system and "foot out from under the hip" in system


def test_the_timeout_asked_for_is_passed_to_the_client(live):
    client = Client(reply(GOOD[0]))
    phrasing.phrase([FOOT], "muse-spark", timeout_s=3, client=client)
    assert client.requests[0]["timeout_s"] == 3


# ---- the happy path and the record -------------------------------------------------------------
def test_good_lines_replace_the_text_and_the_record_names_the_backend(live):
    client = Client(*(reply(line) for line in GOOD))
    lines, record = phrasing.phrase(FAULTS, "muse-spark", client=client)
    assert lines == GOOD
    assert record == {"requested": "muse-spark", "backend": "muse-spark",
                      "model": "meta-models/muse-spark-open-1026", "fallback_reason": None, "lang": "en",
                      "faults": [{"backend": "muse-spark", "model": muse_spark.MODEL, "fallback_reason": None,
                                  "lang": "en", "text": line} for line in GOOD]}
    assert len(client.requests) == 3


def test_a_quoted_reply_is_trimmed(live):
    lines, _ = phrasing.phrase([FOOT], "muse-spark", client=Client(reply('  "left foot too far out"\n')))
    assert lines == ["left foot too far out"]


# ---- AC-010: one fault fails, the others keep the backend's line -------------------------------
FAILURES = [
    ("empty content", reply(""), "muse-spark: empty content"),
    ("whitespace content", reply("  \n "), "muse-spark: empty content"),
    ("null content", HttpResult(200, {"choices": [{"message": {"content": None}}], "usage": {}}),
     "muse-spark: empty content"),
    ("no choices", HttpResult(200, {"usage": {}}), "muse-spark: unexpected response shape"),
    ("http error", http_error(500), "muse-spark: HTTP 500"),
    ("rate limit", http_error(429), "muse-spark: HTTP 429"),
    ("non-2xx result", HttpResult(503, {"error": "busy"}), "muse-spark: HTTP 503"),
    ("timeout", TimeoutError("read timed out"), "muse-spark: timeout after 10 s"),
    ("url timeout", urllib.error.URLError(TimeoutError("timed out")), "muse-spark: timeout after 10 s"),
    ("connection error", urllib.error.URLError(ConnectionRefusedError("refused")),
     "muse-spark: request failed (URLError)"),
    ("bad json", json.JSONDecodeError("bad", "x", 0), "muse-spark: unreadable response"),
    ("garbage result", "not a result", "muse-spark: unreadable response"),
    ("wrong side", reply("left knee not bent enough"), "muse-spark: wrong side"),
    ("added number", reply("right knee not bent enough by 12 degrees"), "muse-spark: adds a number"),
    ("wrong body part", reply("right foot too far out"), "muse-spark: does not name the body part"),
    ("wrong direction", reply("right knee bent more than the example"), "muse-spark: wrong direction"),
    ("extra fault", reply("right knee not bent enough and head forward"),
     "muse-spark: adds another body part (head)"),
    ("praise", reply("right knee not bent enough, nice effort"), "muse-spark: adds praise"),   # AC-P09: untimed too
    ("hyphenated praise", reply("right knee not bent enough, nice-effort"), "muse-spark: adds praise"),
    ("zero-width praise", reply("right knee not bent enough, nice\N{ZERO WIDTH SPACE}effort"),
     "muse-spark: adds praise"),
    ("you are doing great", reply("right knee not bent enough. You're doing great!"), "muse-spark: adds praise"),
]


@pytest.mark.parametrize("label,bad,reason", FAILURES, ids=[f[0] for f in FAILURES])
def test_ac010_one_failing_fault_alone_falls_back_to_its_text(live, label, bad, reason):
    lines, record = phrasing.phrase(FAULTS, "muse-spark", client=middle_fails(bad))
    assert lines == [GOOD[0], KNEE["text"], GOOD[2]]
    assert bare(record["faults"]) == [{"backend": "muse-spark", "model": muse_spark.MODEL, "fallback_reason": None},
                                {"backend": "template", "model": None, "fallback_reason": reason},
                                {"backend": "muse-spark", "model": muse_spark.MODEL, "fallback_reason": None}]
    assert record["backend"] == "muse-spark" and record["fallback_reason"] == reason
    assert record["model"] == "meta-models/muse-spark-open-1026"


def test_when_every_fault_fails_the_backend_is_template(live):
    client = Client(*(TimeoutError() for _ in FAULTS))
    lines, record = phrasing.phrase(FAULTS, "muse-spark", client=client)
    assert lines == [f["text"] for f in FAULTS]
    assert record["backend"] == "template" and record["requested"] == "muse-spark"
    assert record["model"] is None and record["fallback_reason"] == "muse-spark: timeout after 10 s"
    assert all(e["backend"] == "template" for e in record["faults"])


def test_fallback_never_changes_the_scored_fields(live):
    faults = [dict(f) for f in FAULTS]
    phrasing.phrase(faults, "muse-spark", client=middle_fails(reply("")))
    assert faults == FAULTS


# ---- AC-NFR-003: the key never leaves the header ------------------------------------------------
def leak_free(sentinel, *things):
    return all(sentinel not in repr(t) for t in things)


def test_ac_nfr_003_the_sentinel_key_appears_nowhere_but_the_header(live, capsys, caplog):
    caplog.set_level(0)
    leaky = RuntimeError(f"boom with {SENTINEL} inside")
    errors = [http_error(500), TimeoutError(SENTINEL), leaky, urllib.error.URLError(SENTINEL)]
    client = Client(*errors, reply(f"left foot {SENTINEL} too far out"))
    faults = [make_fault() for _ in range(5)]
    lines, record = phrasing.phrase(faults, "muse-spark", client=client)
    assert SENTINEL in client.requests[0]["headers"]["Authorization"], "it is sent, in the header"
    capture = capsys.readouterr()
    assert leak_free(SENTINEL, lines, record, capture.out, capture.err, caplog.text,
                     live["ledger"].read_text())
    assert [r.get("fallback_reason") for r in record["faults"][:3]] == [
        "muse-spark: HTTP 500", "muse-spark: timeout after 10 s", "muse-spark: request failed (RuntimeError)"]


def test_ac_nfr_003_the_key_is_not_in_other_places_either(live):
    client = Client(reply(GOOD[0]))
    phrasing.phrase([FOOT], "muse-spark", client=client)
    body = client.requests[0]["body"]
    assert SENTINEL not in json.dumps(body)
    assert [h for h, v in client.requests[0]["headers"].items() if SENTINEL in v] == ["Authorization"]
    with pytest.raises(ValueError) as unknown:
        phrasing.phrase([FOOT], "other", client=client)
    assert SENTINEL not in str(unknown.value)


def test_ac_nfr_003_a_failed_key_read_does_not_quote_the_path_or_contents(live):
    live["key"].write_text("   \n")
    lines, record = phrasing.phrase([FOOT], "muse-spark", client=Client())
    assert record["faults"][0]["fallback_reason"] == "muse-spark: key file is empty"
    assert str(live["key"]) not in json.dumps(record)


def test_an_unreadable_key_file_is_a_reason_not_a_crash(live):
    live["key"].write_bytes(b"\xff\xfe\x00bad")
    _, record = phrasing.phrase([FOOT], "muse-spark", client=Client())
    assert record["faults"][0]["fallback_reason"] == "muse-spark: key file unreadable"


def test_the_key_is_read_at_the_call_not_at_import(live):
    client = Client(reply(GOOD[0]), reply(GOOD[0]))
    phrasing.phrase([FOOT], "muse-spark", client=client)
    live["key"].write_text("second-key\n")
    phrasing.phrase([FOOT], "muse-spark", client=client)
    assert client.requests[0]["headers"]["Authorization"] == f"Bearer {SENTINEL}"
    assert client.requests[1]["headers"]["Authorization"] == "Bearer second-key"


# ---- AC-NFR-004: one usage line per call --------------------------------------------------------
def test_ac_nfr_004_each_call_appends_one_usage_line_with_the_response_token_counts(live):
    client = Client(reply(GOOD[0], 81, 41, 38), reply(GOOD[1], 82, 42, 39), reply(GOOD[2], 83, 43, 0))
    phrasing.phrase(FAULTS, "muse-spark", client=client)
    entries = ledger_lines(live)
    assert [(e["prompt_tokens"], e["completion_tokens"], e["reasoning_tokens"]) for e in entries] == [
        (81, 41, 38), (82, 42, 39), (83, 43, 0)]
    for entry in entries:
        assert entry["model"] == "meta-models/muse-spark-open-1026" and entry["http_status"] == 200
        assert UTC.match(entry["time"])
        assert set(entry) == {"time", "model", "http_status", "prompt_tokens", "completion_tokens",
                              "reasoning_tokens"}


def test_ac_nfr_004_the_ledger_never_holds_the_text_or_the_key(live):
    phrasing.phrase([FOOT], "muse-spark", client=Client(reply("left foot sticking out too far")))
    raw = live["ledger"].read_text()
    assert "sticking" not in raw and SENTINEL not in raw and "foot" not in raw


def test_ac_nfr_004_a_failed_call_is_counted_too(live):
    client = Client(http_error(500), TimeoutError(), reply("", 80, 512, 512))
    phrasing.phrase(FAULTS, "muse-spark", client=client)
    counts = [(e["http_status"], e["prompt_tokens"], e["completion_tokens"], e["reasoning_tokens"])
              for e in ledger_lines(live)]
    assert counts == [(500, None, None, None), (None, None, None, None), (200, 80, 512, 512)]


def test_ac_nfr_004_the_ledger_appends_across_runs_and_is_private(live):
    for _ in range(2):
        phrasing.phrase([FOOT], "muse-spark", client=Client(reply(GOOD[0])))
    assert len(ledger_lines(live)) == 2
    assert (live["ledger"].stat().st_mode & 0o777) == 0o600


def test_ac_nfr_004_missing_usage_fields_are_null_not_invented(live):
    body = {"choices": [{"message": {"content": GOOD[0]}}], "usage": {"prompt_tokens": 7, "completion_tokens": True}}
    phrasing.phrase([FOOT], "muse-spark", client=Client(HttpResult(200, body)))
    (entry,) = ledger_lines(live)
    assert (entry["prompt_tokens"], entry["completion_tokens"], entry["reasoning_tokens"]) == (7, None, None)


def test_ac_nfr_004_a_flat_reasoning_count_is_read_too(live):
    body = {"choices": [{"message": {"content": GOOD[0]}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 9, "reasoning_tokens": 5}}
    phrasing.phrase([FOOT], "muse-spark", client=Client(HttpResult(200, body)))
    assert ledger_lines(live)[0]["reasoning_tokens"] == 5


def test_no_gate_no_call_no_ledger_line(monkeypatch, tmp_path):
    monkeypatch.setenv("PART5_BASETEN_KEY_FILE", str(tmp_path / "nope"))
    monkeypatch.setenv("PART5_BASETEN_USAGE_FILE", str(tmp_path / "usage.jsonl"))
    phrasing.phrase(FAULTS, "muse-spark", client=Client())
    assert not (tmp_path / "usage.jsonl").exists()


def test_a_spend_that_cannot_be_recorded_is_not_made(live, monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("PART5_BASETEN_USAGE_FILE", str(blocker / "usage.jsonl"))
    client = Client()
    lines, record = phrasing.phrase([FOOT], "muse-spark", client=client)
    assert client.requests == [] and lines == [FOOT["text"]]
    assert record["faults"][0]["fallback_reason"] == "muse-spark: usage ledger not writable"


# ---- AC-NFR-002: the production client is urllib, and it is the only way out ---------------------
def test_ac_nfr_002_without_an_injected_client_the_call_goes_through_urllib(live):
    with pytest.raises(NetworkUsed):
        phrasing.phrase([FOOT], "muse-spark")


def test_the_urllib_client_posts_json_with_the_headers_and_timeout(monkeypatch):
    seen = {}

    class Opener:
        @staticmethod
        def open(http, timeout):
            return fake_urlopen(http, timeout)

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"choices": []}).encode()

    def fake_urlopen(http, timeout):
        seen.update(url=http.full_url, method=http.get_method(), data=http.data, timeout=timeout,
                    headers={k.lower(): v for k, v in http.header_items()})
        return Response()

    monkeypatch.setattr(local_llm, "_OPENER", Opener)
    request = local_llm.chat_request("https://example.invalid/x", "m", FOOT, headers={"Authorization": "Bearer k"},
                                     max_tokens=600, timeout_s=7)
    result = local_llm.urllib_client(request)
    assert result == HttpResult(200, {"choices": []})
    assert seen["method"] == "POST" and seen["timeout"] == 7 and seen["url"] == "https://example.invalid/x"
    assert json.loads(seen["data"])["max_tokens"] == 600
    assert seen["headers"]["authorization"] == "Bearer k" and seen["headers"]["content-type"] == "application/json"


class FakeServer(urllib.request.BaseHandler):
    """Stands in for the network: the first address answers with a redirect to a second one, which
    answers 200. Every request that reaches it is recorded."""
    handler_order = 100

    def __init__(self, status=302):
        self.status, self.opened = status, []

    def http_open(self, req):
        self.opened.append(req)
        start = req.full_url == "http://start.invalid/chat"
        headers = email.message_from_string("Location: http://elsewhere.invalid/steal\r\n\r\n" if start else "\r\n")
        reply = urllib.response.addinfourl(io.BytesIO(b"" if start else b"{}"), headers, req.full_url,
                                           self.status if start else 200)
        reply.msg = "Found" if start else "OK"
        return reply


REDIRECTED = local_llm.chat_request("http://start.invalid/chat", "m", FOOT, headers={"Authorization": "Bearer k"},
                                    max_tokens=600, timeout_s=7)


def test_a_default_opener_would_forward_the_authorization_header_to_the_redirect_target():
    """The control: why the production client refuses redirects."""
    server = FakeServer()
    opener = urllib.request.build_opener(server)
    http = urllib.request.Request(REDIRECTED["url"], data=b"{}", method="POST", headers=REDIRECTED["headers"])
    assert opener.open(http, timeout=7).status == 200
    assert [r.full_url for r in server.opened] == ["http://start.invalid/chat", "http://elsewhere.invalid/steal"]
    assert server.opened[1].get_header("Authorization") == "Bearer k"


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_the_urllib_client_never_follows_a_redirect_so_the_key_goes_nowhere_else(monkeypatch, status):
    server = FakeServer(status)
    monkeypatch.setattr(local_llm, "_OPENER", local_llm.no_redirect_opener(server))
    with pytest.raises(urllib.error.HTTPError) as caught:
        local_llm.urllib_client(REDIRECTED)
    assert caught.value.code == status
    assert [r.full_url for r in server.opened] == ["http://start.invalid/chat"]  # the Location was never asked


def test_a_redirect_is_reported_as_a_plain_http_failure_through_send(monkeypatch):
    server = FakeServer(307)
    monkeypatch.setattr(local_llm, "_OPENER", local_llm.no_redirect_opener(server))
    outcome = local_llm.send(local_llm.urllib_client, REDIRECTED)
    assert outcome.status == 307 and outcome.body is None and outcome.error.reason == "HTTP 307"
    assert len(server.opened) == 1


def test_last_usage_reads_the_newest_line(live):
    assert muse_spark.last_usage() is None
    phrasing.phrase([FOOT], "muse-spark", client=Client(reply(GOOD[0], 5, 6, 7)))
    assert muse_spark.last_usage()["completion_tokens"] == 6
