"""TICKET-064: Part 7's own log (one line per part call and per chain stage), Part 1's retry, the client log."""

from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path
import sys
from typing import Any, Iterator

import pytest

from part7 import applog, client_log, runner, stagelog
from part7.parts import p1_keyframes
from support import Api

VISITOR = {"Cf-Connecting-Ip": "203.0.113.9"}


def _job_log(job_dir: Path) -> str:
    return (job_dir / "steps" / "part7.log").read_text(encoding="utf-8")


# ----- applog ----------------------------------------------------------------------------------------------
def test_any_folder_of_a_job_logs_to_that_jobs_one_part7_log(tmp_path: Path) -> None:
    job = tmp_path / "jobs" / "abcdef012345"
    applog.log("from the job", "abcdef012345", job)
    applog.log("from the trainer chain", "abcdef012345", job / "work" / "trainer")
    text = _job_log(job)
    assert "INFO job abcdef012345: from the job" in text and "from the trainer chain" in text
    assert not (job / "work" / "trainer" / "steps").exists()
    assert applog.job_root(job / "work" / "trainer") == job and applog.job_id_of(job / "work") == "abcdef012345"
    assert text.split(" ", 1)[0].endswith("Z")  # UTC time on every line


def test_setup_appends_to_part7_log_and_rotates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(applog.LOGGER, "handlers", [])  # a fresh process; restored after the test
    (tmp_path / "part7.log").write_text("earlier run\n", encoding="utf-8")
    path = applog.setup(tmp_path)
    try:
        assert applog.setup(tmp_path) == path and len(applog.LOGGER.handlers) == 2  # once per process
        applog.log("serve start: test")
        text = path.read_text(encoding="utf-8")
        assert text.startswith("earlier run\n") and "INFO serve start: test" in text
        assert any(getattr(h, "maxBytes", 0) == applog.MAX_BYTES for h in applog.LOGGER.handlers)
    finally:
        for handler in applog.LOGGER.handlers:
            handler.close()


# ----- runner and stagelog ---------------------------------------------------------------------------------
def test_every_part_call_logs_start_and_exit_and_a_failure_quotes_the_last_lines(tmp_path: Path) -> None:
    job = tmp_path / "jobs" / "0123456789ab"
    steps = job / "work" / "trainer" / "steps"
    ok = runner.run(3, [sys.executable, "-c", "print('fine')"], cwd=tmp_path, log_path=steps / "part3.log")
    bad = runner.run(1, [sys.executable, "-c", "import sys; print('line one', flush=True); sys.exit('could not read video metadata')"],
                     cwd=tmp_path, log_path=steps / "part1.log")
    assert ok["exit"] == 0 and bad["exit"] == 1
    text = _job_log(job)
    assert "part 3 start: " in text and "part3.log" in text and "part 3 exit 0 in " in text
    failed = [line for line in text.splitlines() if "part 1 failed" in line][0]
    assert "WARNING" in failed and "exit 1" in failed and str(steps / "part1.log") in failed
    assert "line one | could not read video metadata" in failed


def test_a_part_call_without_a_step_log_writes_no_job_log(tmp_path: Path) -> None:
    runner.run(4, [sys.executable, "-c", "pass"], cwd=tmp_path)
    runner.run(4, [sys.executable, "-c", "pass"], cwd=tmp_path, log_path=tmp_path / "setup" / "part4-setup-0.log")
    assert not list(tmp_path.rglob("part7.log"))


def test_a_stage_logs_its_inputs_and_its_end(tmp_path: Path, tiny_mp4: Path) -> None:
    work = tmp_path / "jobs" / "aaaaaaaaaaaa" / "work"
    steps: list[Any] = []
    with stagelog.stage(work, "pose", steps, video=stagelog.video_facts(tiny_mp4), person="1", ids="1,2") as end:
        steps.append(runner.Step(part=2, exit=0, timed_out=False, duration_s=1.0, log="x.log", stdout=""))
        end["out"] = "pose3d.json"
    text = _job_log(work.parent)
    assert "stage pose start: video=tiny.mp4 160x120 5 fps 2000 ms person=1 ids=1,2" in text
    assert "stage pose end in " in text and "exits 2:0 out=pose3d.json" in text


def test_a_failed_stage_names_the_reason_the_step_log_and_its_last_lines(tmp_path: Path) -> None:
    work = tmp_path / "jobs" / "bbbbbbbbbbbb" / "work" / "trainer"
    steps: list[Any] = []

    class Stop(Exception):
        result = {"error": "failed:skeleton: the skeleton step failed"}

    with pytest.raises(Stop):
        with stagelog.stage(work, "skeleton", steps, person="0"):
            steps.append(runner.Step(part=3, exit=2, timed_out=False, duration_s=0.5, log="/s/part3.log",
                                     stdout="a\nb\nKeyError: 'people'\n"))
            raise Stop()
    line = [x for x in _job_log(work.parents[1]).splitlines() if "stage skeleton failed" in x][0]
    assert "WARNING" in line and "the skeleton step failed" in line
    assert "part 3 exit 2, log /s/part3.log: a | b | KeyError: 'people'" in line


def test_video_facts_say_unreadable(tmp_path: Path) -> None:
    (tmp_path / "x.mp4").write_bytes(b"not a video")
    assert stagelog.video_facts(tmp_path / "x.mp4") == "x.mp4 unreadable"


# ----- Part 1 retry on a cut network stream ----------------------------------------------------------------
class _Lock:
    def __init__(self, clone: Path) -> None:
        self.clone = clone

    def path(self, part: str) -> Path:
        return self.clone

    def sha12(self, part: Any) -> str:
        return "e84e92b1d0b1"


def _p1(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, outcomes: list[dict[str, Any]],
        spend: list[float] | None = None) -> list[dict[str, Any]]:
    """Run Part 1's adapter with `runner.run` answering `outcomes` in order and the ledger reading `spend` in
    order (the last value repeats); return the calls made."""
    calls: list[dict[str, Any]] = []
    ledger = list(spend or [0.0])

    def total_spend(*a: Any, **k: Any) -> float:
        return ledger.pop(0) if len(ledger) > 1 else ledger[0]

    @contextlib.contextmanager
    def dotenv(*a: Any, **k: Any) -> Iterator[bool]:
        yield True

    def fake_run(part: Any, argv: list[str], cwd: Path, timeout_s: float, log_path: Path, lock: Any) -> runner.Step:
        out = outcomes[len(calls)]
        calls.append({"timeout_s": timeout_s, "log": Path(log_path)})
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(out["stdout"], encoding="utf-8")
        if out["exit"] == 0:
            stem = Path(argv[-1]).stem
            (cwd / "out" / stem).mkdir(parents=True, exist_ok=True)
            (cwd / "out" / stem / "keyframes.json").write_text("{}", encoding="utf-8")
        return runner.Step(part=1, exit=out["exit"], timed_out=out.get("timed_out", False),
                           duration_s=out.get("duration_s", 10.0), log=str(log_path), stdout=out["stdout"])

    monkeypatch.setattr(p1_keyframes, "total_spend_usd", total_spend)
    monkeypatch.setattr(p1_keyframes.keys, "has_key", lambda *a, **k: True)
    monkeypatch.setattr(p1_keyframes.keys, "part1_dotenv", dotenv)
    monkeypatch.setattr(p1_keyframes.runner, "run", fake_run)
    video = tmp_path / "person.mp4"
    video.write_bytes(b"video bytes")
    work = tmp_path / "jobs" / "cccccccccccc" / "work" / "trainer"
    res = p1_keyframes.run(video, work, lock=_Lock(tmp_path / "clone"), timeout_s=90.0)  # type: ignore[arg-type]
    calls.append({"result": res})
    return calls


CUT = "Traceback ...\nhttp.client.IncompleteRead: IncompleteRead(51928 bytes read)\n"


def test_part1_cut_stream_is_retried_once_with_the_time_left(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _p1(monkeypatch, tmp_path, [{"exit": 1, "stdout": CUT, "duration_s": 30.0}, {"exit": 0, "stdout": "ok"}])
    step, kf, note = calls[-1]["result"]
    assert [c["timeout_s"] for c in calls[:-1]] == [90.0, 60.0]
    assert step["exit"] == 0 and kf is not None and note is None
    first = calls[0]["log"].with_name("part1.try1.log")
    assert "IncompleteRead" in first.read_text(encoding="utf-8")
    assert "lost its network stream after 30.0 s, retrying once" in _job_log(tmp_path / "jobs" / "cccccccccccc")
    # the job record keeps both tries: the second is the step, the first rides along under `first_try`
    assert step["first_try"]["exit"] == 1 and step["first_try"]["duration_s"] == 30.0
    assert step["first_try"]["log"] == str(first)
    assert json.loads(json.dumps(step))["first_try"]["log"].endswith("part1.try1.log")


def test_part1_retry_stops_at_the_spend_cap_reached_by_the_first_try(monkeypatch: pytest.MonkeyPatch,
                                                                     tmp_path: Path) -> None:
    monkeypatch.setenv("SIMON7_PART1_SPEND_CAP_USD", "5")
    cap = 5.0
    calls = _p1(monkeypatch, tmp_path, [{"exit": 1, "stdout": CUT, "duration_s": 30.0}, {"exit": 0, "stdout": "ok"}],
                spend=[cap - 0.01, cap])
    step, kf, note = calls[-1]["result"]
    assert len(calls) == 2 and [c["timeout_s"] for c in calls[:-1]] == [90.0]  # one paid call only
    assert step["exit"] == 1 and kf is None and note == "spend cap"
    assert "first_try" not in step
    assert "spend cap is reached, no second try" in _job_log(tmp_path / "jobs" / "cccccccccccc")


@pytest.mark.parametrize("first", [
    {"exit": 1, "stdout": "RuntimeError: could not read video metadata for inbox/x.mp4\n"},  # not a network cut
    {"exit": None, "stdout": CUT, "timed_out": True},  # out of time already
    {"exit": 1, "stdout": CUT, "duration_s": 80.0},  # under RETRY_MIN_S left
])
def test_part1_other_failures_are_not_retried(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, first: dict[str, Any]) -> None:
    calls = _p1(monkeypatch, tmp_path, [first])
    step, kf, note = calls[-1]["result"]
    assert len(calls) == 2 and kf is None and note is not None and note.startswith("key frames from Part 3")


def test_part1_cut_stream_with_too_little_time_logs_why_no_second_try(monkeypatch: pytest.MonkeyPatch,
                                                                     tmp_path: Path) -> None:
    calls = _p1(monkeypatch, tmp_path, [{"exit": 1, "stdout": CUT, "duration_s": 82.4}])
    step, kf, note = calls[-1]["result"]
    assert len(calls) == 2 and [c["timeout_s"] for c in calls[:-1]] == [90.0]  # no second run
    assert kf is None and note is not None and "first_try" not in step
    assert ("Part 1 lost its network stream after 82.4 s, no second try: 7.6 s of its 90 s budget left "
            "(a retry needs 40 s)") in _job_log(tmp_path / "jobs" / "cccccccccccc")


def test_part1_retry_needs_40_s_left_and_the_budget_is_logged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """TICKET-113: 39 s left is not enough for a second try, 40 s is; the lines name the budget used."""
    assert p1_keyframes.RETRY_MIN_S == 40.0
    calls = _p1(monkeypatch, tmp_path, [{"exit": 1, "stdout": CUT, "duration_s": 51.0}])
    assert len(calls) == 2 and "no second try: 39.0 s of its 90 s budget left (a retry needs 40 s)" in _job_log(
        tmp_path / "jobs" / "cccccccccccc")
    (tmp_path / "b").mkdir()
    calls = _p1(monkeypatch, tmp_path / "b", [{"exit": 1, "stdout": CUT, "duration_s": 50.0}, {"exit": 0, "stdout": "ok"}])
    assert [c["timeout_s"] for c in calls[:-1]] == [90.0, 40.0]
    text = _job_log(tmp_path / "b" / "jobs" / "cccccccccccc")
    assert "Part 1 starts with a 90 s budget" in text and "retrying once with 40 s left of its 90 s budget" in text


# ----- POST api/client-log ---------------------------------------------------------------------------------
def _post(api: Api, body: Any, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    status, _, data = api.request("POST", "api/client-log", raw, {"Content-Type": "application/json", **(headers or VISITOR)})
    return status, data


GOOD = {"level": "warn", "event": "upload.retry", "detail": {"status": 502, "try": 2}, "page": "#/record"}


def test_client_log_writes_one_redacted_line_and_answers_200_with_a_body(api: Api, caplog: pytest.LogCaptureFixture,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(applog.keys, "redact", lambda text, *a, **k: text.replace("sk-secret", "<redacted>"))
    with caplog.at_level(logging.INFO, logger="part7"):
        status, data = _post(api, {**GOOD, "detail": {"status": 502, "key": "sk-secret"}})
    assert status == 200 and data == b'{"ok": true}'  # 200 with a body: a 204 fetch shows as net::ERR_ABORTED in Chromium
    lines = [r for r in caplog.records if r.getMessage().startswith("client ")]
    assert len(lines) == 1 and lines[0].levelno == logging.WARNING
    assert lines[0].getMessage() == 'client warn upload.retry page=#/record {"key":"<redacted>","status":502}'


@pytest.mark.parametrize("body", [
    b"not json", b"[]", {**GOOD, "level": "debug"}, {**GOOD, "event": ""}, {**GOOD, "event": "x" * 65},
    {**GOOD, "event": "two\nlines"}, {**GOOD, "detail": [1]}, {k: v for k, v in GOOD.items() if k != "page"},
    {**GOOD, "page": 3},
])
def test_client_log_bad_bodies_are_400(api: Api, body: Any, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="part7"):
        status, data = _post(api, body)
    assert status == 400 and json.loads(data)["message"] == client_log.MSG_BAD
    assert not [r for r in caplog.records if r.getMessage().startswith("client ")]


def test_client_log_over_4_kb_is_413(api: Api) -> None:
    assert _post(api, {**GOOD, "detail": {"text": "x" * 4100}})[0] == 413
    assert _post(api, b"{" + b" " * (client_log.BODY_MAX + 10) + b"}")[0] == 413
    assert _post(api, {**GOOD, "detail": {"text": "x" * 4000}})[0] == 200


def test_the_browsers_cut_bodies_are_accepted_by_the_server(api: Api) -> None:
    """web/api.js clientLogBody cuts by UTF-8 bytes: 3000 quotes or 3000 `é` are never a 413 here."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    web_api = Path(__file__).resolve().parents[2] / "web" / "api.js"
    script = (f"import {{ clientLogBody }} from {json.dumps(web_api.as_uri())};\n"
              "for (const blob of ['\"'.repeat(3000), 'é'.repeat(3000), '\\u2028'.repeat(3000)])\n"
              "  console.log(JSON.stringify(clientLogBody('warn', 'big', { blob }, '#/' + 'é'.repeat(500))));\n")
    out = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60, check=True)
    bodies = out.stdout.rstrip("\n").split("\n")  # not splitlines: a raw U+2028 is not a line end here
    assert len(bodies) == 3
    for raw in bodies:
        assert _post(api, raw.encode("utf-8"))[0] == 200, raw[:80]


def test_client_log_page_is_one_line_and_short(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="part7"):
        assert _post(api, {**GOOD, "level": "info", "page": "#/a\nINFO forged" + "p" * 300})[0] == 200
    msg = [r.getMessage() for r in caplog.records if r.getMessage().startswith("client ")][0]
    assert "\n" not in msg and "page=#/a INFO forged" in msg and len(msg.split(" page=")[1].split(" {")[0]) == 200


@pytest.mark.parametrize("brk", ["\x85", "\u2028", "\u2029", "\ud800"])
def test_client_log_unicode_line_breaks_cannot_forge_a_line(api: Api, caplog: pytest.LogCaptureFixture, brk: str) -> None:
    assert _post(api, {**GOOD, "event": f"a{brk}b"})[0] == 400
    with caplog.at_level(logging.INFO, logger="part7"):
        assert _post(api, {**GOOD, "page": f"#/a{brk}INFO forged", "detail": {"t": f"x{brk}INFO forged"}})[0] == 200
    msg = [r.getMessage() for r in caplog.records if r.getMessage().startswith("client ")][0]
    assert len(msg.splitlines()) == 1 and brk not in msg
    assert "page=#/a INFO forged" in msg
    assert json.loads(msg[msg.index(" {") + 1:]) == {"t": f"x{brk}INFO forged"}  # escaped, the same JSON


def test_client_log_is_rate_limited_per_client(api: Api) -> None:
    api.app.client_rate = client_log.RateLimit(limit=3)
    assert [_post(api, GOOD)[0] for _ in range(4)] == [200, 200, 200, 429]
    assert _post(api, GOOD, {"Cf-Connecting-Ip": "198.51.100.1"})[0] == 200  # another client has its own budget


def test_rate_limit_window_slides() -> None:
    limiter = client_log.RateLimit(limit=2, window_s=60.0)
    assert [limiter.allow("a", t) for t in (0.0, 1.0, 2.0)] == [True, True, False]
    assert limiter.allow("a", 60.5) is True  # the first event left the window


def test_rate_limit_keeps_at_most_max_keys_and_forgets_the_least_recently_seen() -> None:
    limiter = client_log.RateLimit(limit=1, window_s=60.0, max_keys=3)
    assert [limiter.allow(k, 1.0) for k in "abc"] == [True, True, True]
    assert limiter.allow("a", 2.0) is False  # a is now the most recently seen
    assert limiter.allow("d", 3.0) is True and len(limiter._seen) == 3
    assert list(limiter._seen) == ["c", "a", "d"]  # b, the least recently seen, was forgotten
    assert limiter.allow("a", 4.0) is False  # a kept its count
    for i in range(1000):
        limiter.allow(f"k{i}", 5.0)
    assert len(limiter._seen) == 3


def test_a_crashing_route_is_a_plain_500_and_a_log_line(api: Api, caplog: pytest.LogCaptureFixture,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self: Any) -> None:
        raise KeyError("people")

    from part7 import server

    monkeypatch.setattr(server._Handler, "_health", boom)
    with caplog.at_level(logging.INFO, logger="part7"):
        status, _, data = api.request("GET", "api/health")
    assert status == 500 and "went wrong" in json.loads(data)["message"]
    assert any("GET /simon-part-7/api/health crashed: KeyError" in r.getMessage() for r in caplog.records)


def test_a_route_crashing_after_its_headers_sends_no_second_response(api: Api, caplog: pytest.LogCaptureFixture,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    from part7 import server

    def half(self: Any) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "10")
        self.end_headers()
        self.wfile.write(b"part")
        raise RuntimeError("mid body")

    monkeypatch.setattr(server._Handler, "_health", half)
    with caplog.at_level(logging.INFO, logger="part7"), socket.create_connection(("127.0.0.1", api.port), timeout=10) as sock:
        sock.sendall(f"GET {api.app.base}api/health HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        raw = b""
        while chunk := sock.recv(65536):
            raw += chunk
    assert raw.count(b"HTTP/1.") == 1 and raw.startswith(b"HTTP/1.0 200") and raw.endswith(b"\r\n\r\npart")
    assert any("api/health crashed: RuntimeError" in r.getMessage() for r in caplog.records)
    assert api.request("GET", "api/version")[0] == 200  # the server still answers the next request


@pytest.mark.parametrize("exc", [BrokenPipeError, ConnectionResetError, ConnectionAbortedError])
def test_a_client_closing_mid_answer_is_info_not_a_crash(api: Api, caplog: pytest.LogCaptureFixture,
                                                         monkeypatch: pytest.MonkeyPatch, exc: type) -> None:
    """TICKET-204: a write to a closed connection is the client leaving: INFO, no ERROR, no traceback."""
    from part7 import server

    class Gone:
        def write(self, data: bytes) -> None:
            raise exc(32, "Broken pipe")

        def flush(self) -> None:
            pass

    def write_to_gone(self: Any) -> None:
        self.wfile = Gone()
        self.wfile.write(b"x")

    monkeypatch.setattr(server._Handler, "_health", write_to_gone)
    with caplog.at_level(logging.INFO, logger="part7"):
        try:
            api.request("GET", "api/health")
        except OSError:
            pass  # the test client sees the connection end
    messages = [(r.levelno, r.getMessage()) for r in caplog.records]
    assert any(lvl == logging.INFO and m == "client closed the connection during GET /simon-part-7/api/health"
               for lvl, m in messages), messages
    assert not any("crashed" in m or lvl >= logging.ERROR for lvl, m in messages)


# ----- TICKET-174: route arguments never reach the log -----------------------------------------------------
TOKEN = "Zm9vYmFyLXRva2VuLXZhbHVlLTEyMzQ1Njc4OQabcdef0123456789"


@pytest.mark.parametrize("page, shown", [
    (f"#/signin/{TOKEN}", "page=#/signin "), ("#/result/0123456789ab", "page=#/result "),
    ("#/result/0123456789ab/p2", "page=#/result "), ("#/record", "page=#/record "),
])
def test_client_log_scrubs_route_arguments_from_page(api: Api, caplog: pytest.LogCaptureFixture, page: str, shown: str) -> None:
    with caplog.at_level(logging.INFO, logger="part7"):
        assert _post(api, {**GOOD, "page": page})[0] == 200
    msg = [r.getMessage() for r in caplog.records if r.getMessage().startswith("client ")][0]
    assert shown in msg and TOKEN not in msg and "0123456789ab" not in msg


def test_client_log_scrubs_signin_and_result_links_inside_detail(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    detail = {"href": f"https://x.test/#/signin/{TOKEN}", "from": "#/result/0123456789ab"}
    with caplog.at_level(logging.INFO, logger="part7"):
        assert _post(api, {**GOOD, "detail": detail})[0] == 200
    msg = [r.getMessage() for r in caplog.records if r.getMessage().startswith("client ")][0]
    assert "#/signin" in msg and "#/result" in msg and TOKEN not in msg and "0123456789ab" not in msg
