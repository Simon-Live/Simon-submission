"""TICKET-221 AC-6, AC-7 and the routes: the pattern finder job, over the real ledger with a fake transport (no network)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from history_support import ENTRY, OTHER, USER, World, world  # noqa: F401
from part7 import history_patterns_job as job_mod, history_receipt, history_report, history_store
from patterns_support import SCENARIO, seed_store
from support import Api
from test_history_api import FakeTransport, ledger_lines

BASE = "api/me/history"
GOOD = {"kind": "starts_at_rep", "measure": "knee_valgus", "side": "left", "tempo_band": None, "takes_with": 4, "takes_total": 5,
        "from_rep": 3, "text": "The left knee differs more from the example from rep 3, in 4 of 5 takes.",
        "cites": [{"take": 2, "at_s": 2.5}, {"take": 3, "at_s": 3.2}]}
BAD = {**GOOD, "takes_with": 5}


def _as(user: str | None) -> dict[str, str]:
    return {"X-Test-User": user} if user else {}


def _json(api: Api, method: str, path: str, user: str | None = USER) -> tuple[int, Any]:
    return api.json(method, path, {}, headers={**_as(user), "Origin": f"http://127.0.0.1:{api.port}"})


def _transport(patterns: list[dict[str, Any]]) -> FakeTransport:
    return FakeTransport(answer=json.dumps({"patterns": patterns}))


@pytest.fixture()
def runner(tmp_path: Path, world: World) -> job_mod.PatternRunner:  # noqa: F811
    seed_store(tmp_path, world)
    return job_mod.PatternRunner(tmp_path, tmp_path / "catalog")


def _run(runner: job_mod.PatternRunner, transport: FakeTransport, user: str = USER) -> dict[str, Any]:
    runner.transport = transport
    kind, value = runner.request(user, ENTRY)
    assert runner.wait_idle(20)
    key = runner.plan(user, ENTRY)[2]
    return job_mod.cached(runner.state, user, ENTRY, key) or value


def test_ok_result_is_checked_stored_and_served_from_cache(runner: job_mod.PatternRunner) -> None:
    fake = _transport([GOOD, BAD])
    doc = _run(runner, fake)
    assert doc["status"] == "ok" and doc["format"] == job_mod.FORMAT and [p["from_rep"] for p in doc["patterns"]] == [3]
    assert doc["rejected"][0]["rule"] == 4
    assert doc["meter"]["cached_tokens"] == 10_000 and doc["meter"]["hit_rate"] == 0.5  # the response's own numbers
    assert doc["reach"]["video"] is False and "faults.measure" in doc["reach"]["keys"] and doc["reach"]["takes_full"] == 5
    assert not any("text" == k.split(".")[1] for k in doc["reach"]["keys"])
    sent = doc["sent"]  # the shared receipt (TICKET-212)
    assert sent["feature"] == "pattern" and sent["settled"] and sent["digest_takes"] == [1, 2, 3, 4, 5] and "faults.measure" in sent["fields"]
    assert history_receipt.leaks(sent, str(runner.state), USER, "@", "0000000000") == []  # negative: no path, id or email
    body = fake.bodies[0]
    assert body["prompt_cache_key"].startswith("simon-long-") and USER not in body["prompt_cache_key"]
    assert body["text"]["format"]["name"] == "simon_patterns_v1" and body["store"] is False
    assert fake.uploaded == []  # text only: no clip leaves the machine (AC-6)
    kind, hit = runner.request(USER, ENTRY)
    assert kind == "cached" and hit["key"] == doc["key"] and fake.calls.count("respond") == 1  # no second call


def test_ledger_line_has_its_own_feature_and_prompt_version_and_cached_tokens(runner: job_mod.PatternRunner) -> None:
    _run(runner, _transport([GOOD]))
    reserve, settle = ledger_lines(runner.state)
    assert (reserve["feature"], settle["feature"]) == ("pattern", "pattern") and settle["prompt_version"] == "pattern.v1"
    assert settle["cached_tokens"] == 10_000 and settle["input_tokens"] == 20_000
    assert USER not in json.dumps([reserve, settle])


def test_model_failure_and_bad_json_end_in_the_table(runner: job_mod.PatternRunner) -> None:
    doc = _run(runner, FakeTransport(fail="respond"))
    assert doc["status"] == "fallback" and doc["reason"] and doc["patterns"][0]["source"] == "fact_table"
    bad = _run(runner, FakeTransport(answer="not json"))
    assert bad["status"] == "ok" and bad["patterns"][0]["source"] == "fact_table" and bad["rejected"] == []  # nothing kept: the table stays


def test_every_pattern_rejected_shows_the_table_not_nothing(runner: job_mod.PatternRunner) -> None:
    doc = _run(runner, _transport([BAD]))
    assert doc["patterns"][0]["source"] == "fact_table" and len(doc["rejected"]) == 1


def test_daily_limit_counts_against_the_report_cap_and_few_takes_are_refused(runner: job_mod.PatternRunner, monkeypatch: pytest.MonkeyPatch,
                                                                              tmp_path: Path) -> None:
    monkeypatch.setenv("SIMON7_HISTORY_DAILY", "1")
    _run(runner, _transport([GOOD]))
    assert history_report.runs_today(runner.state, USER) == 1
    runner.transport = _transport([GOOD])
    history_store.drop_take(tmp_path, f"{1:012x}")  # a changed history is a new key: it needs a new call, which the cap refuses
    with pytest.raises(history_report.Refused) as caught:
        runner.request(USER, ENTRY)
    assert caught.value.status == 429


def test_consent_and_minimum_takes(tmp_path: Path, world: World) -> None:  # noqa: F811
    seed_store(tmp_path, world, SCENARIO[:2])
    runner = job_mod.PatternRunner(tmp_path)
    with pytest.raises(history_report.Refused) as few:
        runner.request(USER, ENTRY)
    assert few.value.status == 422
    world.opted_in.discard(USER)
    with pytest.raises(history_report.Refused) as no:
        runner.request(USER, ENTRY)
    assert no.value.status == 409


def test_private_takes_and_other_sections_are_not_read(tmp_path: Path, world: World) -> None:  # noqa: F811
    ids = seed_store(tmp_path, world)
    meta = history_store.take_dir(tmp_path, USER, ENTRY, ids[2]) / history_store.META_NAME
    doc = json.loads(meta.read_text())
    meta.write_text(json.dumps({**doc, "private": True}))
    runner = job_mod.PatternRunner(tmp_path)
    rows, facts, _, _ = runner.plan(USER, ENTRY)
    assert [r["take"] for r in rows] == [1, 2, 4, 5] and facts["takes"]
    fake = _transport([GOOD])
    runner.transport = fake
    runner.request(USER, ENTRY)
    assert runner.wait_idle(20)
    sent = json.dumps(fake.bodies[0]["input"])
    assert ids[2] not in sent and sent.count("analysis (JSON data)") == 4


# ----- routes ---------------------------------------------------------------------------------------------
@pytest.fixture()
def seeded(api: Api, world: World) -> Api:  # noqa: F811
    seed_store(api.app.state, world)
    return api


def _patterns_runner(api: Api) -> job_mod.PatternRunner:
    return job_mod.runner_for(api.app.state, api.app.child.catalog_dir)


def test_routes_owner_only(seeded: Api) -> None:
    assert _json(seeded, "POST", f"{BASE}/{ENTRY}/patterns", None)[0] == 401
    assert seeded.request("GET", f"{BASE}/{ENTRY}/patterns")[0] == 401
    assert _json(seeded, "POST", f"{BASE}/{ENTRY}/patterns", OTHER)[0] == 404
    assert seeded.request("GET", f"{BASE}/{ENTRY}/patterns", headers=_as(OTHER))[0] == 404
    assert _json(seeded, "DELETE", f"{BASE}/{ENTRY}/patterns")[0] == 405
    assert seeded.request("GET", f"{BASE}/{ENTRY}/patterns", headers=_as(USER))[0] == 404  # nothing made yet


def test_routes_run_poll_and_delete_my_data(seeded: Api) -> None:
    runner = _patterns_runner(seeded)
    runner.transport = _transport([GOOD])
    status, doc = _json(seeded, "POST", f"{BASE}/{ENTRY}/patterns")
    assert status == 202 and doc["status"] in ("queued", "running")
    assert runner.wait_idle(20)
    code, _, body = seeded.request("GET", f"{BASE}/{ENTRY}/patterns", headers=_as(USER))
    result = json.loads(body)
    assert code == 200 and result["status"] == "ok" and result["patterns"][0]["cites"][0]["take"] == 2
    assert seeded.request("GET", f"{BASE}/{ENTRY}/patterns", headers=_as(OTHER))[0] == 404  # another user cannot read it
    assert _json(seeded, "POST", f"{BASE}/{ENTRY}/patterns")[0] == 200  # stored: no second call
    folder = job_mod.store_dir(seeded.app.state, USER, ENTRY)
    assert list(folder.glob("*.json"))
    _json(seeded, "DELETE", BASE)                                     # Delete my data
    assert not list(folder.glob("*.json")) and not folder.exists()


def test_a_deleted_take_removes_the_result_that_cites_it(seeded: Api) -> None:
    runner = _patterns_runner(seeded)
    runner.transport = _transport([GOOD])
    _json(seeded, "POST", f"{BASE}/{ENTRY}/patterns")
    assert runner.wait_idle(20)
    folder = job_mod.store_dir(seeded.app.state, USER, ENTRY)
    assert list(folder.glob("*.json"))
    history_store.drop_take(seeded.app.state, f"{3:012x}")
    assert not list(folder.glob("*.json"))


def _regroup(state: Path, ids: list[str], keep: int) -> None:
    """Leave the last `keep` takes in the latest take's mode; the earlier ones move to another mode (total unchanged)."""
    for job in ids[:-keep]:
        meta = history_store.take_dir(state, USER, ENTRY, job) / history_store.META_NAME
        history_store.write_json(meta, {**json.loads(meta.read_text()), "mode": "practice"})


def test_page_payload_carries_the_servers_own_group_verdict(seeded: Api) -> None:
    code, doc = seeded.json("GET", f"{BASE}/{ENTRY}", headers=_as(USER))
    assert code == 200 and doc["patterns"] == {"eligible": True, "group_takes": 5, "min_takes": 3, "reason": None}


def test_page_payload_says_not_eligible_when_the_group_is_short_though_the_total_is_not(tmp_path: Path, world: World) -> None:  # noqa: F811
    ids = seed_store(tmp_path, world)
    _regroup(tmp_path, ids, 2)  # 5 takes in total, 2 in the latest take's section and mode
    runner = job_mod.PatternRunner(tmp_path)
    verdict = runner.eligibility(USER, ENTRY)
    assert verdict == {"eligible": False, "group_takes": 2, "min_takes": 3, "reason": job_mod.MSG_FEW}
    with pytest.raises(history_report.Refused) as no:  # the same function backs the 422
        runner.request(USER, ENTRY)
    assert no.value.status == 422 and no.value.code == "too_few_takes"


def test_route_page_and_post_agree_for_a_short_group(api: Api, world: World) -> None:  # noqa: F811
    ids = seed_store(api.app.state, world)
    _regroup(api.app.state, ids, 2)
    code, doc = api.json("GET", f"{BASE}/{ENTRY}", headers=_as(USER))
    assert code == 200 and len(doc["takes"]) == 5 and doc["patterns"]["eligible"] is False and doc["patterns"]["group_takes"] == 2
    assert _json(api, "POST", f"{BASE}/{ENTRY}/patterns")[0] == 422


# ----- TICKET-237 AC-8: the owner's answered notes reach the pack and the receipt count -----------------------
def _add_requests(state: Path, rows: list[tuple[str, str, str, str, str | None]]) -> None:
    """`(job, follower, state, note, matched_fault)` rows in the notes table (the table the notes feature writes)."""
    import sqlite3

    from part7 import identity, notes

    identity.db_path(state).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(identity.db_path(state)))
    db.executescript(notes._SCHEMA)
    for i, (job, follower, st, note, matched) in enumerate(rows):
        db.execute("INSERT INTO note_requests (id, job_id, entry_id, follower_id, trainer_id, state, asked_utc, answered_utc, note, note_at_s, matched_fault) "
                   "VALUES (?, ?, ?, ?, 't-1', ?, '2026-10-20T10:00:00Z', '2026-10-20T11:00:00Z', ?, 3.2, ?)", (f"r{i}-{job}", job, ENTRY, follower, st, note, matched))
    db.commit()
    db.close()


def test_an_answered_note_reaches_the_pack_and_the_receipt_counts_it_without_the_text(tmp_path: Path, world: World) -> None:  # noqa: F811
    ids = seed_store(tmp_path, world)
    runner = job_mod.PatternRunner(tmp_path, tmp_path / "catalog")
    key_before = runner.plan(USER, ENTRY)[2]
    _add_requests(tmp_path, [(ids[2], USER, "answered", "Knee caves at the bottom.", "knee_valgus left"), (ids[3], USER, "answered", "Eyes up.", None)])
    doc = _run(runner, _transport([GOOD]))
    body = json.dumps(runner.transport.bodies[0]["input"])
    assert "Knee caves at the bottom." in body and "Eyes up." in body and body.count("Trainer notes on take") == 2
    assert doc["sent"]["notes_sent"] == 2 and "Knee caves" not in json.dumps(doc["sent"]) and ids[2] not in json.dumps(doc["sent"])
    assert history_receipt.leaks(doc["sent"], "Knee caves", "Eyes up") == []
    assert key_before != runner.plan(USER, ENTRY)[2]  # the notes are part of the result's key: a new note is a new result


def test_declined_open_withdrawn_and_other_users_notes_never_reach_the_pack(tmp_path: Path, world: World) -> None:  # noqa: F811
    ids = seed_store(tmp_path, world)
    _add_requests(tmp_path, [(ids[0], USER, "declined", "Declined text.", None), (ids[1], USER, "asked", "Open text.", None),
                             (ids[2], USER, "withdrawn", "Withdrawn text.", None), (ids[3], OTHER, "answered", "Other persons note.", None)])
    runner = job_mod.PatternRunner(tmp_path, tmp_path / "catalog")
    doc = _run(runner, _transport([GOOD]))
    body = json.dumps(runner.transport.bodies[0]["input"])
    assert "Trainer notes" not in body and not any(w in body for w in ("Declined text", "Open text", "Withdrawn text", "Other persons"))
    assert doc["sent"]["notes_sent"] == 0


def test_a_note_on_a_private_take_never_reaches_the_pack(tmp_path: Path, world: World) -> None:  # noqa: F811
    ids = seed_store(tmp_path, world)
    meta = history_store.take_dir(tmp_path, USER, ENTRY, ids[2]) / history_store.META_NAME
    meta.write_text(json.dumps({**json.loads(meta.read_text()), "private": True}))
    _add_requests(tmp_path, [(ids[2], USER, "answered", "Private take note.", None)])
    runner = job_mod.PatternRunner(tmp_path, tmp_path / "catalog")
    doc = _run(runner, _transport([GOOD]))
    assert "Private take note" not in json.dumps(runner.transport.bodies[0]["input"]) and doc["sent"]["notes_sent"] == 0
