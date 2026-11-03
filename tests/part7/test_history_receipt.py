"""TICKET-212: the "What Simon sent" block (docs/specs/history-receipt.md), no network."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from history_support import ENTRY, USER, World, record_two, world  # noqa: F401
from part7 import history_prompt as hp, history_receipt as hr, history_report, history_store
from test_history_prompt import NARRATION, make


def test_pack_manifest_lists_digests_clips_teacher_and_cues():  # AC-1
    facts, rows = make([60, 70, 80])
    packed = hp.pack("e1", facts, rows, teacher_clip="/t.mp4", teacher_duration_s=20.0, narration=NARRATION, video_consent=True)
    m = packed["manifest"]
    assert m["digest_takes"] == [1, 2, 3] and m["clip_takes"] == packed["clip_takes"] and m["teacher_clip"] is True
    assert m["narration_cues"] == 1 and m["prompt_version"] == hp.PROMPT_VERSION and m["video_consent"] is True
    assert m["est_input_tokens"] == packed["est_input_tokens"] and "score" in m["fields"]


def test_no_video_consent_lists_digests_but_no_clips():  # AC-5
    facts, rows = make([60, 70])
    sent = hr.build(hp.pack("e1", facts, rows, video_consent=False))
    assert sent["digest_takes"] == [1, 2] and sent["clip_takes"] == [] and sent["video_consent"] is False
    assert sent["store"] is False and sent["model"] == "muse-spark-1.3" and sent["settled"] is False


def test_private_takes_are_not_in_the_receipt():
    facts, rows = make([60, 70, 80], private=(2,))
    assert hr.build(hp.pack("e1", facts, rows))["digest_takes"] == [1, 3]


def test_usage_fills_tokens_and_cost_and_with_actual_updates_a_block():
    facts, rows = make([60, 70])
    packed = hp.pack("e1", facts, rows)
    usage = {"input_tokens": 900, "cached_tokens": 100, "output_tokens": 50, "usd": 0.0012}
    sent = hr.build(packed, usage, feature="since_last_time")
    assert sent["feature"] == "since_last_time" and sent["settled"] and sent["input_tokens"] == 900 and sent["usd"] == 0.0012
    later = hr.with_actual(hr.build(packed), usage)
    assert later["cached_tokens"] == 100 and later["settled"]
    assert hr.with_actual(later, None) == later


def test_extra_fields_and_junk_are_filtered():
    sent = hr.build({"manifest": {"digest_takes": [2, "x", True, -1, 3], "fields": ["score", "/home/u/file", "a b"],
                                  "prompt_version": "../../etc"}, "feature": "bad feature"}, extra_fields=["pattern_text"])
    assert sent["digest_takes"] == [2, 3] and sent["fields"] == ["score", "pattern_text"]
    assert sent["feature"] == "compare" and sent["prompt_version"] == "unknown"


def test_the_block_holds_no_path_user_job_or_email():  # AC-4
    facts, rows = make([60, 70])
    packed = hp.pack("e1", facts, rows, teacher_clip="/srv/teacher/video.mp4", teacher_duration_s=5.0, narration=NARRATION, video_consent=True)
    sent = hr.build(packed, {"input_tokens": 5, "usd": 0.1})
    assert hr.leaks(sent, "/clips", "/srv", "job0000", USER, "@", "Chest up") == []
    assert hr.leaks({"x": "/clips/a.mp4"}, "/clips") == ["/clips"]


@pytest.fixture()
def runner(tmp_path: Path, world: World, monkeypatch: pytest.MonkeyPatch) -> history_report.Runner:
    world.install_model(monkeypatch)
    record_two(tmp_path, world)
    return history_report.Runner(tmp_path, tmp_path / "catalog")


def test_compose_stores_sent_with_actual_usage(runner, world):  # AC-2
    world.answers.append(json.dumps({"summary": {"text": "Take 2 scored 77.", "cites": [{"take": 2}]}, "trends": [], "observations": []}))
    runner.request(USER, ENTRY)
    assert runner.wait_idle(20)
    report = history_report.cached(runner.state, USER, ENTRY, runner.plan(USER, ENTRY)[1])
    assert report["sent"]["settled"] and report["sent"]["input_tokens"] == 1234 and report["sent"]["usd"] == 0.002
    assert hr.leaks(report["sent"], str(runner.state), USER) == []


def test_a_failed_call_still_records_what_was_sent(runner, world):  # AC-5
    world.answers.append(sys.modules["part7.history_api"].HistoryError("timeout on responses", {"input_tokens": 10, "usd": 0.001}))
    runner.request(USER, ENTRY)
    assert runner.wait_idle(20)
    report = history_report.cached(runner.state, USER, ENTRY, runner.plan(USER, ENTRY)[1])
    assert report["status"] == "fallback" and report["sent"]["input_tokens"] == 10


def test_the_receipt_lives_inside_the_report_file_so_every_delete_path_takes_it(runner, world):  # AC-7
    world.answers.append(json.dumps({"summary": {"text": "Take 2.", "cites": [{"take": 2}]}, "trends": [], "observations": []}))
    runner.request(USER, ENTRY)
    assert runner.wait_idle(20)
    folder = history_store.reports_dir(runner.state, USER, ENTRY)
    files = list(folder.glob("*.json"))
    assert len(files) == 1 and "sent" in json.loads(files[0].read_text(encoding="utf-8"))
    assert not list(runner.state.rglob("*receipt*"))  # no file of its own to leave behind
