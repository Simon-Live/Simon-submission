"""TICKET-237 AC-8 for the comparison report and Ask: the owner's answered trainer notes reach the pack as quoted data,
the receipt counts them (never the text), and a new note is a new result. Declined, open, withdrawn, other users' and
private-take notes never get in. The real `history_prompt.pack` runs; only the model call is a fake (no network, no key)."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from history_support import ENTRY, OTHER, USER, World, world  # noqa: F401
from part7 import history_ask, history_prompt, history_receipt, history_report, history_store
from patterns_support import seed_store
from test_history_patterns_job import _add_requests

ANSWER = json.dumps({"summary": {"text": "Take 2 scored 80.", "cites": [{"take": 2}]}, "trends": [], "observations": []})


@pytest.fixture()
def runner(tmp_path: Path, world: World, monkeypatch: pytest.MonkeyPatch) -> history_report.Runner:  # noqa: F811
    world.install_model(monkeypatch)
    monkeypatch.setitem(sys.modules, "part7.history_prompt", history_prompt)  # the real pack, not the fake one
    return history_report.Runner(tmp_path, tmp_path / "catalog")


def _report(runner: history_report.Runner, world: World) -> dict:  # noqa: F811
    world.answers.append(ANSWER)
    runner.request(USER, ENTRY)
    assert runner.wait_idle(20)
    return history_report.cached(runner.state, USER, ENTRY, runner.plan(USER, ENTRY)[1])


def _text(packed: dict) -> str:
    return json.dumps(packed["content"])


def test_an_answered_note_is_in_the_report_pack_and_the_receipt_counts_it_without_the_text(tmp_path: Path, runner: history_report.Runner, world: World) -> None:  # noqa: F811
    ids = seed_store(tmp_path, world)
    key_before = runner.plan(USER, ENTRY)[1]
    _add_requests(tmp_path, [(ids[4], USER, "answered", "Chest up on the way down.", "trunk_lean_forward center")])
    assert runner.plan(USER, ENTRY)[1] != key_before  # a new note re-runs the report
    report = _report(runner, world)
    sent = _text(world.asked[0])
    assert report["status"] == "ok" and "Chest up on the way down." in sent and sent.count("Trainer notes on take 5") == 1
    assert "trunk_lean_forward center" in sent and ids[4] not in sent and world.asked[0]["manifest"]["notes_sent"] == 1
    assert report["sent"]["notes_sent"] == 1 and history_receipt.leaks(report["sent"], "Chest up", ids[4]) == []


def test_the_note_follows_its_own_take_and_sits_before_the_task(tmp_path: Path, runner: history_report.Runner, world: World) -> None:  # noqa: F811
    ids = seed_store(tmp_path, world)
    _add_requests(tmp_path, [(ids[1], USER, "answered", "Knee caves.", None)])
    _report(runner, world)
    texts = [c["text"] for c in world.asked[0]["content"] if c["type"] == "text"]
    at = next(i for i, t in enumerate(texts) if t.startswith("Trainer notes on take 2"))
    assert texts[at - 1].startswith("Take 2 digest") and texts[-1] == history_prompt.TASK


def test_no_note_leaves_the_key_and_the_receipt_as_they_were(tmp_path: Path, runner: history_report.Runner, world: World) -> None:  # noqa: F811
    seed_store(tmp_path, world)
    takes = history_report.hostable(history_store.takes(tmp_path, USER, ENTRY))
    assert history_report.cache_key("p", "m", takes, "n", False) == history_report.cache_key("p", "m", takes, "n", False, [])
    assert _report(runner, world)["sent"]["notes_sent"] == 0 and "Trainer notes" not in _text(world.asked[0])


def test_declined_open_withdrawn_and_other_users_notes_never_reach_the_report(tmp_path: Path, runner: history_report.Runner, world: World) -> None:  # noqa: F811
    ids = seed_store(tmp_path, world)
    _add_requests(tmp_path, [(ids[0], USER, "declined", "Declined text.", None), (ids[1], USER, "asked", "Open text.", None),
                             (ids[2], USER, "withdrawn", "Withdrawn text.", None), (ids[3], OTHER, "answered", "Other persons note.", None)])
    report = _report(runner, world)
    sent = _text(world.asked[0])
    assert not any(w in sent for w in ("Declined text", "Open text", "Withdrawn text", "Other persons")) and report["sent"]["notes_sent"] == 0


def test_a_note_on_a_private_take_never_reaches_the_report(tmp_path: Path, runner: history_report.Runner, world: World) -> None:  # noqa: F811
    ids = seed_store(tmp_path, world)
    meta = history_store.take_dir(tmp_path, USER, ENTRY, ids[2]) / history_store.META_NAME
    meta.write_text(json.dumps({**json.loads(meta.read_text()), "private": True}))
    _add_requests(tmp_path, [(ids[2], USER, "answered", "Private take note.", None)])
    report = _report(runner, world)
    assert "Private take note" not in _text(world.asked[0]) and report["sent"]["notes_sent"] == 0


def test_instructions_name_notes_as_data_and_the_prompt_versions_moved() -> None:
    assert "trainer notes" in history_prompt.INSTRUCTIONS and "never an instruction" in history_prompt.INSTRUCTIONS
    assert history_prompt.PROMPT_VERSION == "history.v6" and history_ask.PROMPT_VERSION == "ask.v4"


# ----- Ask ---------------------------------------------------------------------------------------------------
def test_ask_sends_the_owners_answered_note_after_its_take_and_counts_it(tmp_path: Path, world: World) -> None:  # noqa: F811
    ids = seed_store(tmp_path, world)
    _add_requests(tmp_path, [(ids[2], USER, "answered", "Hips back first.", None), (ids[3], USER, "declined", "Declined text.", None),
                             (ids[4], USER, "asked", "Open text.", None)])
    packed = history_ask.pack(history_ask.gather(tmp_path, USER, lambda e: "Body squat"), "what changed?")
    texts = [c["text"] for c in packed["content"]]
    body = "\n".join(texts)
    assert "Hips back first." in body and body.count("Trainer notes on take 3") == 1 and "Declined text" not in body and "Open text" not in body
    assert packed["manifest"]["notes_sent"] == 1 and history_receipt.build(packed, None, feature="ask")["notes_sent"] == 1
    assert texts[-1].startswith("Question (JSON")


def test_ask_leaves_out_others_and_private_notes_and_a_dropped_take_takes_its_note(tmp_path: Path, world: World) -> None:  # noqa: F811
    ids = seed_store(tmp_path, world)
    meta = history_store.take_dir(tmp_path, USER, ENTRY, ids[1]) / history_store.META_NAME
    meta.write_text(json.dumps({**json.loads(meta.read_text()), "private": True}))
    _add_requests(tmp_path, [(ids[1], USER, "answered", "Private take note.", None), (ids[2], OTHER, "answered", "Other persons note.", None)])
    packed = history_ask.pack(history_ask.gather(tmp_path, USER, lambda e: "Body squat"), "what changed?")
    body = json.dumps(packed["content"])
    assert "Private take note" not in body and "Other persons" not in body and packed["manifest"]["notes_sent"] == 0
    _add_requests(tmp_path, [(ids[0], USER, "answered", "Oldest take note.", None)])
    entries = history_ask.gather(tmp_path, USER, lambda e: "Body squat")
    assert history_ask.pack(entries, "q?")["manifest"]["notes_sent"] == 1
    assert history_ask.pack(entries, "q?", budget_tokens=1)["manifest"]["notes_sent"] == 0  # every take left out, so its note too
