"""Moderation and prize-board rules (docs/specs/challenges.md "Integrity"): the report control, the operator's
remove-entry and remove-board, and a prize board that needs rules, an end date, one result per account and no own-compute take."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from auth_support import authenv, post, sign_in  # noqa: F401  authenv is a fixture
from part7 import challenge_routes, challenges, cli, ops_notice
from support import Api
from test_challenges import SPONSOR, _create, _job, _sponsored

ENTRY = "lateral-raise"


def _run(capsys: pytest.CaptureFixture[str], state: Path, *args: str) -> tuple[int, str, str]:
    code = cli.main(["challenge", "--state", str(state), *args])
    out = capsys.readouterr()
    return code, out.out, out.err


_SEQ = iter(range(1, 10**6))


def _board(state: Path, names: list[str]) -> str:
    entries = [{"name": n, "score": 50 + i, "grade": "C", "job_id": f"{next(_SEQ):012x}", "pid": None, "created_at": "2026-11-01T00:00:00Z"} for i, n in enumerate(names)]
    return challenges.create(state, entry_id=ENTRY, title="T", creator_name="Maker", kind="friend", entries=entries)["id"]


# ----- the operator's CLI ---------------------------------------------------------------------------------
def test_cli_remove_entry_takes_one_name_off_and_leaves_the_rest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cid = _board(tmp_path, ["Sam", "Kim", "sam"])
    code, out, _ = _run(capsys, tmp_path, "remove-entry", cid, "--name", "SAM")
    assert code == 0 and json.loads(out)["removed"] == 2
    assert [e["name"] for e in challenges.get(tmp_path, cid)["entries"]] == ["Kim"]
    assert _run(capsys, tmp_path, "remove-entry", "nosuchid1", "--name", "x")[0] == 2


def test_cli_remove_board_deletes_it_and_a_missing_one_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    keep, gone = _board(tmp_path, ["Sam"]), _board(tmp_path, ["Kim"])
    code, out, _ = _run(capsys, tmp_path, "remove-board", gone)
    assert code == 0 and challenges.get(tmp_path, gone) is None and challenges.get(tmp_path, keep) is not None
    assert _run(capsys, tmp_path, "remove-board", gone)[0] == 2


def test_cli_show_prints_every_name_and_the_reports_without_visitor_keys(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cid = _board(tmp_path, ["Sam"])
    challenges.report(tmp_path, cid, "name", "visitorkey1")
    code, out, _ = _run(capsys, tmp_path, "show", cid)
    shown = json.loads(out)
    assert code == 0 and shown["entries"][0]["name"] == "Sam" and shown["reports"][0]["reason"] == "name"
    assert "visitorkey1" not in out and "job_id" not in out


# ----- prize boards ----------------------------------------------------------------------------------------
def test_a_prize_board_needs_rules_and_an_end_date(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = ["create", "--entry", ENTRY, "--title", "T", "--sponsor-name", "Brand", "--sponsor-url", "https://example.com", "--prize", "Shoes"]
    for extra in ([], ["--ends", "2999-12-01"], ["--rules-url", "https://example.com/rules"]):
        with pytest.raises(SystemExit):  # a required flag is missing: the parser refuses
            cli.main(["challenge", "--state", str(tmp_path), *base, *extra])
    assert _run(capsys, tmp_path, *base, "--rules-url", "http://example.com/rules", "--ends", "2999-12-01")[0] == 2
    capsys.readouterr()
    assert challenges.list_all(tmp_path) == []


def test_the_library_refuses_a_prize_board_without_rules_or_end(tmp_path: Path) -> None:
    with pytest.raises(challenges.ChallengeError):
        challenges.create(tmp_path, entry_id=ENTRY, title="T", creator_name="B", kind="sponsored", sponsor={k: v for k, v in SPONSOR.items() if k != "rules_url"},
                          allow_sponsored=True, ends_at="2999-12-01T00:00:00Z")
    with pytest.raises(challenges.ChallengeError, match="end date"):
        challenges.create(tmp_path, entry_id=ENTRY, title="T", creator_name="B", kind="sponsored", sponsor=SPONSOR, allow_sponsored=True)
    assert challenges.list_all(tmp_path) == []
    made = challenges.create(tmp_path, entry_id=ENTRY, title="T", creator_name="Simon Official", kind="sponsored", sponsor=SPONSOR, allow_sponsored=True, ends_at="2999-12-01T00:00:00Z")
    assert made["sponsor"]["rules_url"] == "https://example.com/rules"  # the operator may use a reserved name; the page shows the rules link


def _join(api: Api, cid: str, job: str, sid: str | None) -> tuple[int, Any]:
    status, _, body = post(api, f"api/challenges/{cid}/entries", {"job_id": job, "name": "Ada"}, cookie=sid)
    return status, body


def test_a_prize_board_takes_one_result_per_account_and_needs_sign_in(api: Api, authenv: Any) -> None:
    cid = _sponsored(api)["id"]
    sid = sign_in(api)
    assert _join(api, cid, _job(api, "a1a1a1a1a1a1"), None)[0] == 403  # signed out: no account to count
    assert _join(api, cid, _job(api, "a1a1a1a1a1a2"), sid)[0] == 201
    status, body = _join(api, cid, _job(api, "a1a1a1a1a1a3"), sid)
    assert (status, body["error"]) == (409, challenges.MSG_SPONSOR_ONE)
    assert len(challenges.get(api.app.state, cid)["entries"]) == 1
    friend = _create(api)["id"]  # control: a friend board takes the same account's first result
    assert _join(api, friend, _job(api, "a1a1a1a1a1a4"), sid)[0] == 201


def test_a_prize_board_refuses_an_own_compute_take_even_when_byok_ranked_is_on(api: Api, authenv: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(challenges, "ranks_owner_compute", lambda: True)
    cid, friend = _sponsored(api)["id"], _create(api)["id"]
    sid = sign_in(api)
    own = _job(api, "b2b2b2b2b2b1", compute_owner=True)
    status, body = _join(api, cid, own, sid)
    assert (status, body["error"]) == (409, challenges.MSG_SPONSOR_OWN_COMPUTE)
    assert _join(api, friend, own, sid)[0] == 201  # control: the ranked friend board still takes it while the switch is on


# ----- report ----------------------------------------------------------------------------------------------
@pytest.fixture()
def notices(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(ops_notice, "send", lambda subject, body, state: sent.append((subject, body)) or True)
    monkeypatch.setattr(challenge_routes, "_background", lambda fn, *args: fn(*args))  # the mail goes off the request thread; the test waits for it
    return sent


def _report(api: Api, cid: str, reason: Any, ip: str = "198.51.100.7") -> tuple[int, Any]:
    status, _, body = post(api, f"api/challenges/{cid}/report", {"reason": reason}, headers={"Cf-Connecting-Ip": ip})
    return status, body


def test_a_report_is_recorded_and_raises_one_notice_with_no_free_text(api: Api, notices: list[tuple[str, str]]) -> None:
    cid = _create(api, title="Beat my raises")["id"]
    assert _report(api, cid, "name") == (200, {"reported": True})
    assert _report(api, cid, "name") == (200, {"reported": True})  # the same visitor and reason counts once
    assert len(challenges.get(api.app.state, cid)["reports"]) == 1 and len(notices) == 1
    subject, body = notices[0]
    assert cid in body and "name" in body and "Beat my raises" not in body and "Sam" not in body
    assert "reports" not in api.json("GET", f"api/challenges/{cid}")[1] and "visitor" not in str(api.json("GET", f"api/challenges/{cid}")[1])
    assert _report(api, cid, "score", ip="198.51.100.9")[0] == 200 and len(notices) == 1  # the second is counted, not mailed


@pytest.mark.parametrize("reason", [None, "", "I hate this", {"x": 1}, "NAME"])
def test_a_report_takes_only_a_listed_reason(api: Api, notices: list[tuple[str, str]], reason: Any) -> None:
    cid = _create(api)["id"]
    assert _report(api, cid, reason)[0] == 400
    assert "reports" not in challenges.get(api.app.state, cid) and notices == []


def test_a_report_on_a_missing_board_is_404(api: Api, notices: list[tuple[str, str]]) -> None:
    assert _report(api, "nosuchboard", "name")[0] == 404 and notices == []
