"""Muse Spark's second opinion (docs/specs/second-opinion.md AC-SO-01 to AC-SO-07, AC-SC-01; TICKET-045, contract C1).

The Meta Model API is a fake client (upload, count, respond, delete); no socket is opened. The take is the real stock
pair pexels-5034562 (the example) and pexels-8837221 (the take, five faults); the clip files are stand-ins, since
`prepare` is replaced by the identity here and tested on its own.
"""
import io
import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from part5 import cli, opinion
from part5.io import JOINTS
from part5.opinion import guard, meta_api, prompt
from part5.opinion.meta_api import OpinionError
from part5.output import OutputError, validate_analysis
from part5.pipeline import run
from part5.score_report import score_block

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "fixtures/input/eval/real/pexels-5034562/skeleton.json"
FOLLOWER = ROOT / "fixtures/input/eval/real/pexels-8837221/skeleton.json"
SENTINEL = "s" + "k-meta-SENTINEL-never-printed"   # built at run time: the publish gate refuses key-shaped literals


@pytest.fixture
def take():
    return run(str(EXPECTED), str(FOLLOWER), score=score_block)


@pytest.fixture
def meta(monkeypatch, tmp_path):
    """The gate open: a key file holding the sentinel, META_LIVE=1, a temp ledger, stand-in clips, no ffmpeg run."""
    key = tmp_path / "MODEL_API_KEY"
    key.write_text(f" {SENTINEL}\n")
    monkeypatch.setenv("PART5_META_KEY_FILE", str(key))
    monkeypatch.setenv("PART5_META_USAGE_FILE", str(tmp_path / "simon" / "meta_usage.jsonl"))
    monkeypatch.setenv("META_LIVE", "1")
    monkeypatch.setattr(meta_api, "prepare", lambda path, out_dir: Path(path))
    monkeypatch.setattr(meta_api, "clip_seconds", lambda path: None)
    clips = []
    for name in ("teacher.mp4", "student.mp4"):
        (tmp_path / name).write_bytes(b"\x00\x00\x00 ftypisom")
        clips.append(str(tmp_path / name))
    return SimpleNamespace(clips=clips, ledger=tmp_path / "simon" / "meta_usage.jsonl", key=key)


def answer(verdicts=(), observations=(), tokens=(9000, 400)):
    text = json.dumps({"verdicts": list(verdicts), "observations": list(observations)})
    return {"output": [{"type": "reasoning", "summary": []},
                       {"type": "message", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]}}


class Fake:
    """The Meta Model API stand-in. `respond` returns `payload` or raises it; every call is recorded."""

    def __init__(self, payload=None, count=9000, upload_error=None):
        self.payload, self.count_tokens, self.upload_error = payload, count, upload_error
        self.uploaded, self.deleted, self.bodies, self.last_status = [], [], [], None

    def upload(self, path):
        if self.upload_error:
            raise self.upload_error
        self.uploaded.append(Path(path).name)
        return f"file-{len(self.uploaded)}"

    def delete(self, file_id):
        self.deleted.append(file_id)

    def count(self, body):
        return self.count_tokens

    def respond(self, body):
        self.bodies.append(body)
        if isinstance(self.payload, Exception):
            self.last_status = 500
            raise self.payload
        self.last_status = 200
        return self.payload


def all_verdicts(n, agrees):
    return [{"fault_index": i, "agrees": agrees, "note": f"The take shows it the way the list says, item {'abcde'[i]}."}
            for i in range(n)]


def attach(take, meta, fake, **kw):
    return opinion.attach(take, *meta.clips, live=True, client=fake, **kw)


# ---- AC-SO-01: one request, both clips ---------------------------------------------------------------------------
def test_ac_so_01_one_request_carries_both_clips_teacher_first_and_the_faults(take, meta):
    n = len(take.analysis["faults"])
    fake = Fake(answer(all_verdicts(n, True), [{"at_s": 2.5, "text": "The take keeps a steady tempo between reps."}]))
    doc = attach(take, meta, fake)
    block = doc["second_opinion"]
    assert block["status"] == "ok" and block["reason"] is None and block["model"] == "muse-spark-1.3"
    assert block["backend"] == "meta-model-api" and block["lang"] == "en"
    assert [v["fault_index"] for v in block["verdicts"]] == list(range(n))
    assert block["observations"] == [{"at_s": 2.5, "text": "The take keeps a steady tempo between reps.",
                                      "label": "model_opinion"}]
    assert len(fake.bodies) == 1 and fake.uploaded == ["teacher.mp4", "student.mp4"]
    content = fake.bodies[0]["input"][0]["content"]
    kinds = [c["type"] for c in content]
    assert kinds == ["input_text", "input_text", "input_file", "input_text", "input_file", "input_text"]
    assert content[2]["file_id"] == "file-1" and "teacher" in content[1]["text"]
    assert content[4]["file_id"] == "file-2" and "student" in content[3]["text"]
    listed = json.loads(content[5]["text"].split("(JSON): ", 1)[1])
    assert [f["fault_index"] for f in listed] == list(range(n)) and listed[0]["what"] == take.analysis["faults"][0]["text_timed"]
    assert sorted(fake.deleted) == ["file-1", "file-2"]
    assert block["usage"] == {"input_tokens": 9000, "output_tokens": 400, "cached_tokens": 0, "usd": 0.01295}


# ---- AC-SO-02 and AC-SO-03: what is kept --------------------------------------------------------------------------
def test_ac_so_02_bad_verdicts_are_dropped_with_reasons(take, meta):
    verdicts = [{"fault_index": 0, "agrees": True, "note": "The take shows bent elbows."},
                {"fault_index": 1, "agrees": True, "note": "Clip 2 names a clip by its number."},
                {"fault_index": 0, "agrees": False, "note": "A second verdict."},
                {"fault_index": 99, "agrees": True, "note": "No such fault."},
                {"fault_index": 1, "agrees": "yes", "note": "Not a boolean."},
                {"fault_index": True, "agrees": True, "note": "A bool is not an index."},
                {"fault_index": 2, "agrees": False, "note": "The left arm stays level, as the teacher's does."}]
    block = attach(take, meta, Fake(answer(verdicts)))["second_opinion"]
    assert [(v["fault_index"], v["agrees"]) for v in block["verdicts"]] == [(0, True), (2, False)]
    assert [r["reason"] for r in block["rejected"]] == [
        "adds a number", "second verdict for the same fault", "names no fault of this take", "agrees is not true or false",
        "names no fault of this take"]


def test_ac_so_03_at_most_two_observations_inside_the_clip(take, meta):
    end = float(take.follower.t[-1])
    observations = [{"at_s": end + 1, "text": "Past the end."}, {"at_s": -1, "text": "Before the start."},
                    {"at_s": "2", "text": "Not a number."}, {"at_s": 1.0, "text": "The pace is even."},
                    {"at_s": 2.04, "text": "The stance stays wide."}, {"at_s": 3.0, "text": "A third one."}]
    block = attach(take, meta, Fake(answer([], observations)))["second_opinion"]
    assert [o["at_s"] for o in block["observations"]] == [1.0, 2.0]
    assert [r["reason"] for r in block["rejected"]] == ["time outside the clip"] * 3 + ["more than 2 observations"]


# ---- AC-SO-04: the guardrail --------------------------------------------------------------------------------------
def clip_showing(*joints, frames=10):
    mask = np.zeros((frames, len(JOINTS)), dtype=bool)
    for j in joints:
        mask[:, JOINTS.index(j)] = True
    return SimpleNamespace(mask=mask, t=np.linspace(0, 4.0, frames))


UPPER = ("nose", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
         "left_hip", "right_hip")


@pytest.mark.parametrize("text,reason", [
    ("The left elbow stays bent at 1.5 s.", None),
    ("The trunk leans toward the teacher's side.", None),
    ("The head turns down at 2 s.", None),
    ("The knees stay soft through the rep.", "names a body part the clip does not show (knee)"),
    ("The right foot points out.", "names a body part the clip does not show (foot)"),
    ("The left elbow drops at 5.2 s.", "names a time outside the clip"),
    ("The left elbow drops by 12 degrees.", "adds a number"),
    ("The left elbow drops, nice effort.", "adds praise"),
    ("The left elbow position risks injury.", "uses a word this product does not use"),
    ("Your coach would like the elbow higher.", "uses a word this product does not use"),
    ("A rehab cue for the elbow.", "uses a word this product does not use"),
    ("Medical advice: shoulder down.", "uses a word this product does not use"),
    ("The elbow\nbends.", "more than one line"),
    ("x" * 141, "too long"),
    ("", "empty"),
])
def test_ac_so_04_the_guardrail_rejects_what_the_input_does_not_support(text, reason):
    shows = guard.supported(clip_showing(*UPPER))
    assert guard.text_problem(text, 4.0, shows) == reason


def test_ac_so_04_a_side_the_clip_does_not_show_is_rejected():
    shows = guard.supported(clip_showing("left_elbow", "left_shoulder"))
    assert guard.text_problem("The left elbow bends early.", 4.0, shows) is None
    assert guard.text_problem("The right elbow bends early.", 4.0, shows) == \
        "names a side the clip does not show (right elbow)"
    assert "trunk" not in shows and "head" not in shows


def test_ac_so_04_a_joint_seen_in_under_half_the_frames_does_not_count():
    clip = clip_showing(*UPPER, "left_knee", "right_knee")
    clip.mask[:6, JOINTS.index("left_knee")] = False
    clip.mask[:6, JOINTS.index("right_knee")] = False
    assert "knee" not in guard.supported(clip)
    assert guard.supported(SimpleNamespace(mask=None, t=[])) == {}


def test_ac_so_04_an_observation_naming_a_hidden_body_part_is_rejected_on_a_real_take(take, meta, monkeypatch):
    hidden = take.follower
    mask = hidden.mask.copy()
    mask[:, [JOINTS.index("left_ankle"), JOINTS.index("right_ankle")]] = False
    monkeypatch.setattr(take, "follower", SimpleNamespace(mask=mask, t=hidden.t))
    observations = [{"at_s": 1.0, "text": "The feet roll at the bottom."}, {"at_s": 1.5, "text": "The hips sink low."}]
    block = attach(take, meta, Fake(answer([], observations)))["second_opinion"]
    assert [o["text"] for o in block["observations"]] == ["The hips sink low."]
    assert block["rejected"] == [{"kind": "observation", "index": 0,
                                  "reason": "names a body part the clip does not show (foot)"}]


# ---- AC-SO-05: the score never reads it ----------------------------------------------------------------------------
def test_ac_so_05_disputes_never_change_a_measured_field(take, meta):
    before = json.dumps(take.analysis, sort_keys=True)
    n = len(take.analysis["faults"])
    doc = attach(take, meta, Fake(answer(all_verdicts(n, False))))
    assert all(v["agrees"] is False for v in doc["second_opinion"]["verdicts"])
    after = dict(doc)
    after.pop("second_opinion")
    assert json.dumps(after, sort_keys=True) == before
    assert json.dumps(take.analysis, sort_keys=True) == before   # the result's own analysis is not touched


def test_ac_so_05_no_clip_leaves_the_document_as_it_was(take):
    assert opinion.attach(take, None, None) is take.analysis


# ---- AC-SO-06: skipped and fallback ----------------------------------------------------------------------------------
def test_ac_so_06_one_clip_is_skipped(take, meta):
    block = opinion.attach(take, meta.clips[0], None, live=True, client=Fake())["second_opinion"]
    assert (block["status"], block["reason"]) == ("skipped", "both clips are needed")
    assert block["verdicts"] == [] and block["observations"] == [] and block["model"] is None


def test_ac_so_06_live_off_and_no_key_are_skipped(take, meta, monkeypatch):
    monkeypatch.delenv("META_LIVE")
    block = opinion.attach(take, *meta.clips, live=False, client=Fake())["second_opinion"]
    assert block["status"] == "skipped" and block["reason"].startswith("live calls are off")
    meta.key.unlink()
    block = opinion.attach(take, *meta.clips, live=True, client=Fake())["second_opinion"]
    assert (block["status"], block["reason"]) == ("skipped", "no key")


def test_ac_so_06_a_missing_clip_falls_back(take, meta):
    fake = Fake()
    block = opinion.attach(take, meta.clips[0], "/no/such/take.mp4", live=True, client=fake)["second_opinion"]
    assert (block["status"], block["reason"]) == ("fallback", "follower clip not readable") and fake.uploaded == []


@pytest.mark.parametrize("fake,reason", [
    (Fake(upload_error=OpinionError("HTTP 413 on upload")), "HTTP 413 on upload"),
    (Fake(OpinionError("timeout on responses")), "timeout on responses"),
    (Fake({"output": [{"type": "message", "content": [{"type": "output_text", "text": "I agree with all."}]}]}),
     "unreadable answer"),
    (Fake(answer(), count=500_000), "estimated $0.64 over the per-call limit of $0.50"),
])
def test_ac_so_06_a_failed_call_falls_back_with_a_plain_reason(take, meta, fake, reason):
    doc = attach(take, meta, fake)
    block = doc["second_opinion"]
    assert (block["status"], block["reason"]) == ("fallback", reason)
    assert block["verdicts"] == [] and SENTINEL not in json.dumps(doc)
    assert sorted(fake.deleted) == [f"file-{i + 1}" for i in range(len(fake.uploaded))]


def test_ac_so_06_the_spend_cap_stops_the_call_before_it_is_made(take, meta, monkeypatch):
    meta.ledger.parent.mkdir(parents=True)
    meta.ledger.write_text(json.dumps({"usd": 4.99}) + "\n")
    fake = Fake(answer())
    block = attach(take, meta, fake)["second_opinion"]
    assert (block["status"], block["reason"]) == ("fallback", "spend cap reached") and fake.bodies == []
    monkeypatch.setenv("PART5_META_SPEND_CAP_USD", "10")
    assert attach(take, meta, Fake(answer()))["second_opinion"]["status"] == "ok"


def test_ac_so_06_a_ledger_that_cannot_be_written_stops_the_call(take, meta, monkeypatch, tmp_path):
    (tmp_path / "blocked").write_text("a file where the ledger directory would be")
    monkeypatch.setenv("PART5_META_USAGE_FILE", str(tmp_path / "blocked" / "meta_usage.jsonl"))
    fake = Fake(answer())
    block = attach(take, meta, fake)["second_opinion"]
    assert (block["status"], block["reason"]) == ("fallback", "usage ledger not writable") and fake.bodies == []


# ---- AC-SO-07: the ledger ------------------------------------------------------------------------------------------
def test_ac_so_07_each_call_writes_one_line_without_key_or_text(take, meta):
    n = len(take.analysis["faults"])
    attach(take, meta, Fake(answer(all_verdicts(n, True), tokens=(10_000, 1_000))))
    attach(take, meta, Fake(OpinionError("HTTP 500 on responses")))
    lines = [json.loads(x) for x in meta.ledger.read_text().splitlines()]
    assert [(x["http_status"], x["input_tokens"], x["usd"]) for x in lines] == [(200, 10_000, 0.01675), (500, 0, 0.0)]
    assert all(x["model"] == "muse-spark-1.3" and x["purpose"] == "second_opinion" for x in lines)
    text = meta.ledger.read_text()
    assert SENTINEL not in text and "The take shows" not in text
    assert meta_api.spent() == pytest.approx(0.01675)


# ---- the client and its helpers ------------------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, status, body):
        self.status, self._body = status, body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def open(self, request, timeout):
        self.requests.append(request)
        item = self.answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_the_http_client_sends_the_key_only_in_the_header_and_maps_failures(tmp_path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"video")
    client = meta_api.HttpClient(SENTINEL)
    client._opener = FakeOpener(FakeResponse(200, b'{"id": "file-9"}'), FakeResponse(200, b'{"input_tokens": 77}'),
                                FakeResponse(200, json.dumps(answer()).encode()), FakeResponse(204, b""),
                                urllib.error.HTTPError(meta_api.API, 429, "slow down", {}, io.BytesIO(b"{}")))
    assert client.upload(clip) == "file-9"
    body = prompt.request("file-1", "file-2", [], 4.0)
    assert client.count(body) == 77
    assert client.respond(body)["usage"]["input_tokens"] == 9000
    client.delete("file-9")
    with pytest.raises(OpinionError) as raised:
        client.respond(body)
    assert raised.value.reason == "HTTP 429 on responses" and SENTINEL not in raised.value.reason
    urls = [r.full_url for r in client._opener.requests]
    assert urls == [f"{meta_api.API}/files", f"{meta_api.API}/responses/input_tokens", f"{meta_api.API}/responses",
                    f"{meta_api.API}/files/file-9", f"{meta_api.API}/responses"]
    assert all(r.get_header("Authorization") == f"Bearer {SENTINEL}" for r in client._opener.requests)
    assert SENTINEL.encode() not in client._opener.requests[0].data


def test_a_missing_upload_id_and_an_unreadable_count_are_reasons():
    client = meta_api.HttpClient("k")
    client._opener = FakeOpener(FakeResponse(200, b"{}"), FakeResponse(200, b'{"usage": {}}'))
    with pytest.raises(OpinionError, match="upload returned no file id"):
        client.upload(__file__)
    with pytest.raises(OpinionError, match="token count unreadable"):
        client.count(prompt.request("a", "b", [], 1.0))


def test_without_ffmpeg_a_small_clip_goes_as_it_is_and_a_large_one_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(meta_api.shutil, "which", lambda name: None)
    small = tmp_path / "small.mp4"
    small.write_bytes(b"x" * 10)
    assert meta_api.prepare(small, tmp_path) == small
    monkeypatch.setattr(meta_api, "MAX_UPLOAD_BYTES", 5)
    with pytest.raises(OpinionError, match="clip too large to send"):
        meta_api.prepare(small, tmp_path)
    assert meta_api.clip_seconds(small) is None


def test_output_text_reads_only_message_text():
    payload = {"output": [{"type": "reasoning", "summary": [{"text": "thinking"}]},
                          {"type": "message", "content": [{"type": "output_text", "text": "{}"}]}]}
    assert meta_api.output_text(payload) == "{}"
    assert meta_api.output_text({"output_text": "plain"}) == "plain"


# ---- AC-SC-01: the document ----------------------------------------------------------------------------------------
def with_block(take, **change):
    block = {"status": "ok", "reason": None, "backend": "meta-model-api", "model": "muse-spark-1.3", "lang": "en",
             "verdicts": [{"fault_index": 0, "agrees": True, "note": "Seen."}],
             "observations": [{"at_s": 1.0, "text": "Even pace.", "label": "model_opinion"}]}
    block.update(change)
    return dict(take.analysis, second_opinion=block)


@pytest.mark.parametrize("change", [
    {"status": "maybe"}, {"backend": None}, {"reason": 3},
    {"verdicts": [{"fault_index": 40, "agrees": True, "note": "x"}]},
    {"verdicts": [{"fault_index": 0, "agrees": True, "note": "x"}, {"fault_index": 0, "agrees": False, "note": "y"}]},
    {"observations": [{"at_s": 1.0, "text": "x", "label": "fact"}]},
    {"observations": [{"at_s": 1.0, "text": "x", "label": "model_opinion"}] * 3},
    {"verdicts": "none"},
])
def test_ac_sc_01_a_block_that_breaks_contract_c1_is_rejected(take, change):
    with pytest.raises(OutputError, match="second_opinion"):
        validate_analysis(with_block(take, **change))


def test_ac_sc_01_the_doctor_notes_the_block_and_the_language(take, tmp_path, capsys):
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(with_block(take)))
    assert cli.main(["doctor", str(path), "--for", "part7"]) == 0
    out = capsys.readouterr().out
    assert "second opinion ok: 1 verdict (1 agrees, 0 disputes), 1 observation" in out
    assert "lines in en" in out


def test_ac_sc_01_the_cli_writes_a_skipped_block_when_live_is_off(tmp_path, capsys, meta, monkeypatch):
    monkeypatch.delenv("META_LIVE")
    out = tmp_path / "a.json"
    assert cli.main(["analyse", "--expected", str(EXPECTED), "--follower", str(FOLLOWER), "--out", str(out),
                     "--expected-video", meta.clips[0], "--follower-video", meta.clips[1]]) == 0
    doc = json.loads(out.read_text())
    assert doc["second_opinion"]["status"] == "skipped" and "second opinion: skipped" in capsys.readouterr().out
