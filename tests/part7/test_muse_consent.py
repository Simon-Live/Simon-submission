"""B2 and B3 of the restore-muse review: the Meta tick is one account's and carries the statement that everyone filmed is 18 or over
(docs/specs/muse-prod.md AC-MP5, Meta Model API Terms 10.1)."""

from __future__ import annotations

from typing import Any

import pytest

from part7 import consent_record, jobs

ITEMS = {k: True for k in consent_record.ITEMS}


def _doc(account: str | None = "", **extra: Any) -> dict:
    consent = {"version": consent_record.VERSION, "items": {**ITEMS, **extra}, "at": None}
    if account is not None:
        consent["account"] = account
    return {"age_band": "adult", "consent": consent}


@pytest.fixture(autouse=True)
def gated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consent_record.GATE_ENV, "on")


def _meta(doc: dict, user: str | None) -> bool:
    return consent_record.meta_allowed(consent_record.job_fields(doc, user))


def test_b2_account_a_tick_does_not_let_account_b_send() -> None:
    a_tick = _doc("user-a", meta=True, meta_adults=True)
    assert _meta(a_tick, "user-a") is True
    assert _meta(a_tick, "user-b") is False  # the next account on the same browser
    assert _meta(a_tick, None) is False  # signed out
    assert consent_record.refusal(a_tick) is None  # the job itself still runs, without Meta


def test_b2_a_signed_out_tick_does_not_pass_for_a_signed_in_account() -> None:
    assert _meta(_doc("", meta=True, meta_adults=True), None) is True
    assert _meta(_doc("", meta=True, meta_adults=True), "user-b") is False
    assert _meta(_doc(None, meta=True, meta_adults=True), "user-b") is False  # an old client sends no account


def test_b2_the_job_record_never_holds_a_foreign_answer() -> None:
    assert consent_record.job_fields(_doc("user-a", meta=True, meta_adults=True), "user-b") == {}
    kept = consent_record.job_fields(_doc("user-a", meta=True), "user-a")["consent"]["items"]  # no 18 statement: the tick is dropped
    assert "meta" not in kept and all(kept[k] for k in consent_record.ITEMS)


def test_b3_no_tick_to_meta_without_the_18_statement() -> None:
    assert _meta(_doc("u", meta=True), "u") is False
    assert _meta(_doc("u", meta=True, meta_adults=False), "u") is False
    assert _meta(_doc("u", meta_adults=True), "u") is False  # the statement alone is no Meta tick
    assert _meta(_doc("u", meta=True, meta_adults=True), "u") is True


def test_b3_the_trainer_answer_is_the_verified_one() -> None:
    def answer(user: str, **extra: bool) -> bool | None:
        kept = consent_record.job_fields(_doc("user-a", **extra), user)
        job = {"kind": "trainer", "entry_id": "e1", "consent": kept.get("consent", {})}
        queue = type("Q", (), {"_cond": __import__("threading").Condition(), "_owner": True, "_jobs": {"j": job}})()
        return jobs.JobQueue.trainer_meta_answer(queue, "e1")

    assert answer("user-a", meta=True, meta_adults=True) is True
    assert answer("user-a", meta=True) is False


def test_the_version_was_bumped_and_matches_the_web_text() -> None:
    assert consent_record.VERSION == "2026-11-04.2"


def test_b2_account_b_cannot_replay_a_points() -> None:
    a_body = _doc("user-a", meta=True, meta_adults=True)
    assert consent_record.refusal(a_body) is None  # a plain read of the answers
    assert consent_record.parse(a_body, "user-a")[1] is None
    assert consent_record.parse(a_body, "user-b") == (None, consent_record.MSG_CONSENT)  # every point is A's
    assert consent_record.parse(a_body, None) == (None, consent_record.MSG_CONSENT)
    assert consent_record.parse(_doc(""), "user-b") == (None, consent_record.MSG_CONSENT)  # a signed-out answer, until confirmed
    assert consent_record.parse(_doc("user-b"), "user-b")[1] is None
    assert consent_record.job_fields(a_body, "user-b") == {}
