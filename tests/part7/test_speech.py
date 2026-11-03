"""The spoken-line route and MMS-TTS synthesis (docs/specs/voice.md AC-R1..R9)."""

from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import threading
import time
import urllib.request
import wave
from typing import Any

import pytest

from part7 import jobs, speech
from support import Api

FIXTURES = Path(__file__).parent / "fixtures" / "analysis"
ES = json.loads((FIXTURES / "contract-c1-es.analysis.json").read_text(encoding="utf-8"))
EN = json.loads((FIXTURES / "contract-c1-en-no-opinion.analysis.json").read_text(encoding="utf-8"))
RIFF = b"RIFF\x24\x00\x00\x00WAVEfmt "


def get_wav(api: Api, job: str, index: int = 0, timeout: float = 10.0) -> tuple[int, dict[str, str], bytes]:
    """GET the line, asking again while it is being made (the route answers 202 and generates in the background)."""
    end = time.monotonic() + timeout
    while True:
        got = api.request("GET", f"api/jobs/{job}/speech/{index}.wav")
        if got[0] != 202 or time.monotonic() > end:
            return got
        time.sleep(0.02)


@pytest.fixture(autouse=True)
def _clean_speech_state() -> Any:
    speech._FAILED.clear()
    speech._STARTS.clear()
    yield
    for _ in range(200):  # let a background synthesis end before the next test
        if not speech._ACTIVE:
            break
        time.sleep(0.02)
    speech._FAILED.clear()
    speech._STARTS.clear()


def follow_job(api: Api, analysis: Any, kind: str = "follow", write: bool = True) -> str:
    def fn(ctx: jobs.JobContext) -> dict[str, Any]:
        if write:
            (ctx.work / "follower").mkdir(parents=True)
            (ctx.work / "follower" / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
        return {"result": {}}

    job = api.app.queue.submit(kind, fn)
    assert api.app.queue.wait(job["id"], 10)["status"] == "done"
    return job["id"]


class FakeRun:
    """Stands in for the isolated-env subprocess: records argv, writes `--out`, exits as told."""

    def __init__(self, code: int = 0, write: bool = True, boom: Exception | None = None) -> None:
        self.calls: list[list[str]] = []
        self.texts: list[str] = []
        self.code, self.write, self.boom = code, write, boom

    def __call__(self, argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        self.texts.append(Path(argv[argv.index("--text-file") + 1]).read_text(encoding="utf-8"))
        if self.boom:
            raise self.boom
        if self.write:
            Path(argv[argv.index("--out") + 1]).write_bytes(RIFF)
        return subprocess.CompletedProcess(argv, self.code, "", "model exploded" if self.code else "")


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeRun:
    run = FakeRun()
    monkeypatch.setattr(speech.subprocess, "run", run)
    return run


def test_ac_r1_speaks_the_line_in_its_language_and_caches_it(api: Api, fake: FakeRun) -> None:
    job = follow_job(api, ES)
    status, hdr, body = get_wav(api, job)
    assert (status, body, hdr["content-type"]) == (200, RIFF, "audio/wav")
    assert fake.texts == [ES["phrasing"]["faults"][0]["text"]]
    argv = fake.calls[0]
    assert argv[argv.index("--lang") + 1] == "spa"
    assert argv[:3] == ["uv", "run", "--no-project"] and "-I" in argv
    again = api.request("GET", f"api/jobs/{job}/speech/0.wav")
    assert again[0] == 200 and len(fake.calls) == 1, "second request is served from the job folder"
    assert list((api.app.queue.job_dir(job) / "speech").glob("0-spa-*.wav"))


def test_ac_r2_text_change_makes_a_new_file(api: Api, fake: FakeRun) -> None:
    job = follow_job(api, ES)
    get_wav(api, job)
    path = api.app.queue.job_dir(job) / "work" / "follower" / "analysis.json"
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["phrasing"]["faults"][0]["text"] = "Otra frase."
    path.write_text(json.dumps(changed), encoding="utf-8")
    get_wav(api, job)
    assert len(fake.calls) == 2


def test_ac_r3_falls_back_to_fault_text_and_english_without_phrasing_lang(api: Api, fake: FakeRun) -> None:
    doc = {"faults": [{"text": "Keep your back straight."}]}
    job = follow_job(api, doc)
    assert get_wav(api, job)[0] == 200
    assert fake.calls[0][fake.calls[0].index("--lang") + 1] == "eng"


def test_ac_r4_unknown_language_is_404_and_runs_nothing(api: Api, fake: FakeRun) -> None:
    doc = json.loads(json.dumps(ES))
    doc["phrasing"]["lang"] = "xx"
    job = follow_job(api, doc)
    status, _, body = api.request("GET", f"api/jobs/{job}/speech/0.wav")
    assert status == 404 and json.loads(body)["ok"] is False
    assert fake.calls == []


@pytest.mark.parametrize("path", [
    "api/jobs/{job}/speech/7.wav", "api/jobs/{job}/speech/-1.wav", "api/jobs/{job}/speech/..%2F0.wav",
    "api/jobs/{job}/speech/0001.wav", "api/jobs/{job}/speech/a.wav", "api/jobs/{job}/speech/0.mp3",
    "api/jobs/000000000000/speech/0.wav", "api/jobs/..%2F..%2Fetc/speech/0.wav", "api/jobs/ABCDEF012345/speech/0.wav",
])
def test_ac_r5_bad_job_or_index_is_404(api: Api, fake: FakeRun, path: str) -> None:
    job = follow_job(api, ES)
    assert api.request("GET", path.format(job=job))[0] == 404
    assert fake.calls == []


def test_ac_r6_only_finished_follow_jobs_with_an_analysis_speak(api: Api, fake: FakeRun) -> None:
    assert api.request("GET", f"api/jobs/{follow_job(api, ES, kind='group')}/speech/0.wav")[0] == 404
    assert api.request("GET", f"api/jobs/{follow_job(api, ES, write=False)}/speech/0.wav")[0] == 404
    assert fake.calls == []


@pytest.mark.parametrize("run", [FakeRun(code=1), FakeRun(write=False),
                                 FakeRun(boom=subprocess.TimeoutExpired("uv", 1)), FakeRun(boom=FileNotFoundError("uv"))])
def test_ac_r7_a_failed_synthesis_is_404_and_leaves_no_file(api: Api, monkeypatch: pytest.MonkeyPatch, run: FakeRun) -> None:
    monkeypatch.setattr(speech.subprocess, "run", run)
    job = follow_job(api, ES)
    assert get_wav(api, job)[0] == 404
    folder = api.app.queue.job_dir(job) / "speech"
    assert not list(folder.glob("*.wav")) and not list(folder.glob("*.txt"))
    monkeypatch.setattr(speech.subprocess, "run", FakeRun())
    assert api.request("GET", f"api/jobs/{job}/speech/0.wav")[0] == 404, "a failed line rests for a while"
    monkeypatch.setattr(speech, "FAILED_TTL_S", 0.0)
    assert get_wav(api, job)[0] == 200, "a later request may succeed"


def _wait_idle() -> None:
    """Block until no synthesis thread holds the slot."""
    import time

    for _ in range(500):
        if speech._SLOT.acquire(blocking=False):
            speech._SLOT.release()
            return
        time.sleep(0.01)
    raise AssertionError("a synthesis thread did not finish")


def test_failed_and_start_records_expire(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(speech, "_FAILED", {Path("/x/a.wav"): 0.0})
    monkeypatch.setattr(speech, "_STARTS", {"v": [0.0], "w": [999.0]})
    with speech._LOCK:
        speech._expire(1000.0)
    assert speech._FAILED == {} and list(speech._STARTS) == ["w"]


def test_ac_r8_the_subprocess_is_time_boxed_and_the_server_imports_no_model(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        seen.update(kw)
        return subprocess.CompletedProcess(argv, 1, "", "")

    assert speech.start(tmp_path, 0, "eng", "Hi.", run=run) == "started"
    _wait_idle()
    assert seen["timeout"] == speech.TIMEOUT_S > 0
    source = (Path(speech.__file__)).read_text(encoding="utf-8")
    assert not any(w in source for w in ("import torch", "import transformers", "import scipy"))


def test_ac_r9_every_offered_language_has_a_mms_code_and_other_methods_are_refused(api: Api, fake: FakeRun) -> None:
    assert speech.LANGS == {"en": "eng", "es": "spa", "fr": "fra", "ar": "ara", "hi": "hin", "pt": "por"}
    assert speech.lang_code("pt-BR") == "por" and speech.lang_code("ES_mx") == "spa" and speech.lang_code(None) is None
    job = follow_job(api, EN)
    assert api.request("POST", f"api/jobs/{job}/speech/0.wav", b"{}")[0] == 405


# ----- one real synthesis -----------------------------------------------------------------------------------
def _hub_reachable_or_cached(code: str) -> bool:
    cached = Path.home() / ".cache" / "huggingface" / "hub" / f"models--facebook--mms-tts-{code}"
    try:
        urllib.request.urlopen(f"https://huggingface.co/facebook/mms-tts-{code}/resolve/main/config.json", timeout=15)
        return True
    except OSError:
        return cached.is_dir()


def wav_seconds(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as w:
        return w.getnframes() / w.getframerate()


def test_real_mms_tts_speaks_english_and_spanish_through_the_route(api: Api) -> None:
    """Runs the real isolated-env subprocess (CPU): downloads each voice on first use."""
    if not all(_hub_reachable_or_cached(c) for c in ("eng", "spa")):
        pytest.skip("Hugging Face Hub unreachable and the MMS-TTS voices are not cached; the real synthesis could not run")
    for analysis, lang in ((EN, "eng"), (ES, "spa")):
        job = follow_job(api, analysis)
        status, hdr, body = get_wav(api, job, timeout=speech.TIMEOUT_S + 30)  # first use downloads the voice
        assert status == 200, f"MMS-TTS {lang} did not synthesize; see the job log"
        assert hdr["content-type"] == "audio/wav" and len(body) > 1000
        assert wav_seconds(body) > 0.5


# One real fixture line (fixtures/input/analysis-1.5.0.json, fault 0) spoken in each offered language through the route.
# The translations are hand-written for this proof. Runs only when SIMON_PROOF_DIR names the output folder.
LINE = {
    "en": "Right elbow bent more than the example.",
    "es": "El codo derecho está más doblado que en el ejemplo.",
    "fr": "Le coude droit est plus plié que dans l'exemple.",
    "pt": "O cotovelo direito está mais dobrado do que no exemplo.",
    "hi": "दायां कोहनी उदाहरण से ज्यादा मुड़ी हुई है।",
    "ar": "المرفق الأيمن أكثر انحناءً من المثال.",
}


def test_proof_same_line_in_every_language(api: Api) -> None:
    import os

    out = os.environ.get("SIMON_PROOF_DIR")
    if not out:
        pytest.skip("proof run only: set SIMON_PROOF_DIR to the folder that receives the wavs")
    folder, rows = Path(out), []
    folder.mkdir(parents=True, exist_ok=True)
    for lang, text in LINE.items():
        doc = json.loads(json.dumps(EN))
        doc["phrasing"]["lang"] = lang
        doc["phrasing"]["faults"][0]["text"] = text
        job = follow_job(api, doc)
        status, _, body = get_wav(api, job, timeout=speech.TIMEOUT_S + 30)
        assert status == 200, lang
        (folder / f"line0-{lang}.wav").write_bytes(body)
        rows.append({"lang": lang, "mms_voice": f"facebook/mms-tts-{speech.LANGS[lang]}", "text": text,
                     "seconds": round(wav_seconds(body), 2), "bytes": len(body), "job": job})
    (folder / "durations.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


# ----- per-line language (Part 5 schema 1.9.0: phrasing.faults[i].lang) --------------------------------------
REAL = json.loads((FIXTURES / "real-part5-1.9.0-es-live.analysis.json").read_text(encoding="utf-8"))


def test_ac_r10_each_line_is_spoken_in_its_own_language(api: Api, fake: FakeRun) -> None:
    doc = json.loads(json.dumps(ES))
    doc["phrasing"]["faults"][1]["lang"] = "en"  # a template fallback line in a Spanish take
    doc["phrasing"]["faults"][0]["lang"] = "es"
    job = follow_job(api, doc)
    get_wav(api, job, 1)
    get_wav(api, job, 0)
    langs = [c[c.index("--lang") + 1] for c in fake.calls]
    assert langs == ["eng", "spa"]
    assert speech.line_of(ES, 0)[0] == "es", "no per-line lang: phrasing.lang"


def test_ac_r12_a_line_from_faults_is_english_whatever_phrasing_lang_says() -> None:
    doc = json.loads(json.dumps(ES))
    del doc["phrasing"]["faults"][0]["text"]
    doc["phrasing"]["faults"][0]["lang"] = "es"
    doc["faults"][0]["text"] = "Right elbow bent more than the example."
    assert speech.line_of(doc, 0) == ("en", "Right elbow bent more than the example.")
    assert speech.line_of(doc, 1)[0] == "es"


def test_b4_a_busy_synthesis_answers_503_without_starting_a_process(api: Api, fake: FakeRun) -> None:
    job = follow_job(api, ES)
    assert speech._SLOT.acquire(blocking=False)  # another line is being made
    try:
        status, hdr, _ = api.request("GET", f"api/jobs/{job}/speech/0.wav")
        assert status == 503 and hdr["retry-after"]
        assert fake.calls == []
    finally:
        speech._SLOT.release()
    assert get_wav(api, job)[0] == 200, "free again"
    assert len(fake.calls) == 1


def wait_for_log(caplog: pytest.LogCaptureFixture, wanted: Any, timeout: float = 5.0) -> list[str]:
    """The server thread logs after the response is sent: poll the captured records (50 ms) until one matches."""
    end = time.monotonic() + timeout
    while True:
        text = [r.getMessage() for r in list(caplog.records)]
        if any(wanted(m) for m in text) or time.monotonic() > end:
            return text
        time.sleep(0.05)


def test_the_designed_busy_answer_is_info_not_an_anomaly_and_a_real_5xx_still_is(
        api: Api, fake: FakeRun, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """TICKET-204: 503 "Another spoken line is being made" is by design; any other 5xx stays ANOMALY http_5xx."""
    import logging

    from part7 import server

    job = follow_job(api, ES)
    assert speech._SLOT.acquire(blocking=False)
    try:
        with caplog.at_level(logging.INFO, logger="part7"):
            assert api.request("GET", f"api/jobs/{job}/speech/0.wav")[0] == 503
    finally:
        speech._SLOT.release()
    # The INFO line and the ANOMALY line come from one if/else, so once the INFO line is in, no ANOMALY can follow.
    text = wait_for_log(caplog, lambda m: m.endswith("answered 503 (busy by design)"))
    assert any(m.endswith("answered 503 (busy by design)") for m in text), text
    assert not any("ANOMALY http_5xx" in m for m in text), text
    caplog.clear()

    def boom(self: Any) -> None:
        self._error(503, "The app is busy.")

    monkeypatch.setattr(server._Handler, "_health", boom)
    with caplog.at_level(logging.INFO, logger="part7"):
        assert api.request("GET", "api/health")[0] == 503
    text = wait_for_log(caplog, lambda m: "ANOMALY http_5xx" in m and "api/health" in m)
    assert any("ANOMALY http_5xx" in m and "api/health" in m for m in text), text


def test_r8_the_first_request_answers_202_at_once_and_a_later_one_is_served(
        api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()

    def slow(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        release.wait(5)
        Path(argv[argv.index("--out") + 1]).write_bytes(RIFF)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(speech.subprocess, "run", slow)
    job = follow_job(api, ES)
    first = api.request("GET", f"api/jobs/{job}/speech/0.wav")
    again = api.request("GET", f"api/jobs/{job}/speech/0.wav")
    other = api.request("GET", f"api/jobs/{job}/speech/1.wav")
    assert first[0] == 202 and first[1]["retry-after"] and again[0] == 202, "the model is not waited for"
    assert other[0] == 503, "one generation at a time"
    release.set()
    assert get_wav(api, job)[0] == 200


def test_r8_an_unfinished_or_unknown_job_never_starts_a_synthesis(api: Api, fake: FakeRun) -> None:
    release = threading.Event()
    job = api.app.queue.submit("follow", lambda ctx: (release.wait(5), {"result": {}})[1])
    assert api.request("GET", f"api/jobs/{job['id']}/speech/0.wav")[0] == 404
    release.set()
    assert api.request("GET", "api/jobs/0123456789ab/speech/0.wav")[0] == 404
    assert fake.calls == []


def test_r8_a_visitor_may_start_only_so_many_syntheses(api: Api, fake: FakeRun, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(speech, "START_LIMIT", 2)
    jobs_ = [follow_job(api, {"faults": [{"text": f"Line {n}."}]}) for n in range(3)]
    for job in jobs_[:2]:
        assert get_wav(api, job)[0] == 200
    assert api.request("GET", f"api/jobs/{jobs_[2]}/speech/0.wav")[0] == 429
    assert len(fake.calls) == 2
    assert api.request("GET", f"api/jobs/{jobs_[0]}/speech/0.wav")[0] == 200, "a cached line is never limited"


def test_b4_two_threads_at_once_start_one_process(tmp_path: Path) -> None:
    import threading

    started, release, results = threading.Event(), threading.Event(), []

    def slow(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        started.set()
        release.wait(5)
        Path(argv[argv.index("--out") + 1]).write_bytes(RIFF)
        return subprocess.CompletedProcess(argv, 0, "", "")

    results.append(speech.start(tmp_path, 0, "eng", "One.", run=slow))
    assert started.wait(5)
    assert speech.active_in(tmp_path)
    assert speech.start(tmp_path, 1, "eng", "Two.", run=slow) == "busy"
    release.set()
    _wait_idle()
    assert results[0] == "started" and not speech.active_in(tmp_path)
    assert speech.cache_path(tmp_path, 0, "eng", "One.").is_file()
    assert not hasattr(speech, "_LOCKS")


def test_ac_r11_real_part5_output_is_spoken_in_spanish(api: Api, fake: FakeRun) -> None:
    job = follow_job(api, REAL)
    assert get_wav(api, job, 2)[0] == 200
    assert fake.calls[0][fake.calls[0].index("--lang") + 1] == "spa"
    assert fake.texts[0] == REAL["phrasing"]["faults"][2]["text"] == REAL["faults"][2]["coaching"]
