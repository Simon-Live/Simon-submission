"""The class table on GET api/teacher/<entry> (docs/specs/class-table.md AC-C1 to AC-C11; TICKET-273 AC-2)."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import time
from typing import Any

import pytest

from part7 import auth, class_table, identity, teacher_stats
from auth_support import authenv, get, sign_in  # noqa: F401
from support import Api
from test_teacher import ENTRY, _job, _score, _window

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
SEED = importlib.util.spec_from_file_location("seed_class", Path(__file__).resolve().parents[2] / "tools" / "seed_class.py")
seed_class = importlib.util.module_from_spec(SEED)
SEED.loader.exec_module(seed_class)


def _class_fixture(root: Path) -> dict[str, str]:
    """Three followers: ada (3 takes, one older than 7 days), ben (2 takes), and one take made signed out."""
    _job(root, "a00000000001", at="2026-10-24T10:00:00Z", score=_score(50, "D", [_window("Lean less", "Knees out"), _window("Lean less")]))
    _job(root, "b00000000001", at="2026-10-28T10:00:00Z", score=_score(60, "D", [_window("Knees out")]))
    _job(root, "a00000000002", at="2026-10-29T10:00:00Z", score=_score(64, "C", [_window("Lean less")]))
    _job(root, "c00000000001", at="2026-10-30T10:00:00Z", score=_score(71, "C", [_window("Knees out", "Slow down")]))
    _job(root, "b00000000002", at="2026-11-01T10:00:00Z", score=_score(57.5, "D", [_window("Knees out")]))
    _job(root, "a00000000003", at="2026-11-02T09:00:00Z", score=_score(82, "B", [_window("Lean less")]))
    return {"a00000000001": "user-ada", "a00000000002": "user-ada", "a00000000003": "user-ada",
            "b00000000001": "user-ben", "b00000000002": "user-ben"}


def test_three_followers_table(tmp_path: Path) -> None:  # AC-C1, AC-C2, AC-C3, AC-C4
    owners = _class_fixture(tmp_path)
    table = teacher_stats.page(tmp_path, ENTRY, owners, NOW, with_followers=True)["class_table"]
    assert table["follower_count"] == 3
    # "Lean less" is in 3 takes but from one follower; "Knees out" reaches all three followers
    assert table["top_cue"] == {"text": "Knees out", "followers": 3}
    assert table["takes_7d"] == 5 and table["window_days"] == 7  # ada's first take is 9 days old
    assert table["followers"] == [
        {"n": 1, "takes": 3, "first": 50, "latest": 82, "delta": 32},
        {"n": 2, "takes": 2, "first": 60, "latest": 57.5, "delta": -2.5},
    ]  # the signed-out take is a follower of its own with no change to show
    assert table["seeded"] is False


def test_the_table_names_no_account_and_no_job(tmp_path: Path) -> None:  # AC-C5
    owners = _class_fixture(tmp_path)
    text = json.dumps(teacher_stats.page(tmp_path, ENTRY, owners, NOW, with_followers=True))
    for secret in [*owners, *owners.values(), "c00000000001", "\"_folder\"", "\"_cues\"", "\"_synthetic\"", "\"_seed_follower\"", "\"_at\""]:
        assert secret not in text


def test_without_owners_every_take_is_its_own_follower(tmp_path: Path) -> None:
    _class_fixture(tmp_path)
    table = teacher_stats.page(tmp_path, ENTRY, None, NOW, with_followers=True)["class_table"]
    assert table["follower_count"] == 6 and table["followers"] == []
    assert table["top_cue"] == {"text": "Knees out", "followers": 4}


def test_an_entry_with_no_takes(tmp_path: Path) -> None:  # AC-C6
    assert teacher_stats.page(tmp_path, ENTRY, {}, NOW, with_followers=True)["class_table"] == {
        "follower_count": 0, "takes_7d": 0, "window_days": 7, "top_cue": None, "seeded": False, "followers": []}
    assert teacher_stats.page(tmp_path, ENTRY, {}, NOW)["class_table"] is None  # anyone but the owner (private-default D3)


def test_an_entry_with_a_single_take(tmp_path: Path) -> None:  # AC-C6
    _job(tmp_path, "a00000000001", at="2026-11-01T10:00:00Z", score=_score(66, "C", [_window("Knees out", "Knees out")]))
    table = teacher_stats.page(tmp_path, ENTRY, {"a00000000001": "user-ada"}, NOW, with_followers=True)["class_table"]
    assert table == {"follower_count": 1, "takes_7d": 1, "window_days": 7, "top_cue": {"text": "Knees out", "followers": 1},
                     "seeded": False, "followers": []}


def test_a_take_with_no_cues_gives_no_top_cue(tmp_path: Path) -> None:
    _job(tmp_path, "a00000000001", at="2026-11-01T10:00:00Z", score=_score(90, "A"))
    assert teacher_stats.page(tmp_path, ENTRY, {}, NOW, with_followers=True)["class_table"]["top_cue"] is None


def test_a_tie_goes_to_the_first_cue_in_text_order(tmp_path: Path) -> None:
    _job(tmp_path, "a00000000001", at="2026-11-01T10:00:00Z", score=_score(70, "C", [_window("Zed cue")]))
    _job(tmp_path, "b00000000001", at="2026-11-01T11:00:00Z", score=_score(70, "C", [_window("Alpha cue")]))
    assert teacher_stats.page(tmp_path, ENTRY, {}, NOW, with_followers=True)["class_table"]["top_cue"] == {"text": "Alpha cue", "followers": 1}


def test_the_seven_day_window_edges_and_bad_times() -> None:  # AC-C3
    take = {"_folder": "x", "score": 1, "_cues": []}
    found = [{**take, "at": "2026-10-26T12:00:00Z"}, {**take, "at": "2026-10-26T11:59:59Z"}, {**take, "at": "2026-11-02T12:00:01Z"},
             {**take, "at": "not a time"}, {**take, "at": ""}, {**take, "at": "2026-11-01T10:00:00"}]
    assert class_table.build(found, {}, NOW)["takes_7d"] == 2  # the edge itself and a naive time read as UTC; not the future


def test_private_takes_never_reach_the_table(api: Api) -> None:  # AC-C7
    root = api.app.queue.root
    _job(root, "a00000000001", score=_score(64, "C", [_window("Keep your chest up")]))
    _job(root, "b00000000001", score=_score(91, "A", [_window("Secret cue")]), private=True)
    table = teacher_stats.page(root, ENTRY, {}, NOW, with_followers=True)["class_table"]
    assert table["follower_count"] == 1
    status, doc = api.json("GET", f"api/teacher/{ENTRY}")
    assert status == 200 and doc["take_count"] == 1
    assert "Secret cue" not in json.dumps(doc) and "Secret cue" not in json.dumps(table)


def test_the_table_reads_only_the_kept_takes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-C7
    owners = _class_fixture(tmp_path)
    monkeypatch.setattr(teacher_stats, "TAKES_MAX", 2)
    table = teacher_stats.page(tmp_path, ENTRY, owners, NOW, with_followers=True)["class_table"]
    assert table["follower_count"] == 2 and table["followers"] == []  # ben's newest take and ada's newest, one each


def test_follower_rows_are_capped_to_the_most_recent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(class_table, "FOLLOWERS_MAX", 2)
    found = [{"_folder": f"j{i}{k}", "at": f"2026-10-2{i}T1{k}:00:00Z", "score": 50 + k, "_cues": []} for i in range(3) for k in range(2)]
    owners = {f"j{i}{k}": f"u{i}" for i in range(3) for k in range(2)}
    assert [r["n"] for r in class_table.build(found, owners, NOW, with_followers=True)["followers"]] == [2, 3]


def test_seeded_takes_are_labelled_and_grouped_by_seed_follower(tmp_path: Path) -> None:  # AC-C8
    _job(tmp_path, "a00000000001", at="2026-11-01T10:00:00Z", score=_score(60, "D"), synthetic=True, seed_follower="1")
    _job(tmp_path, "a00000000002", at="2026-11-01T11:00:00Z", score=_score(70, "C"), synthetic=True, seed_follower="1")
    _job(tmp_path, "b00000000001", at="2026-11-01T12:00:00Z", score=_score(70, "C"), seed_follower="1")  # not synthetic: ignored
    table = teacher_stats.page(tmp_path, ENTRY, {}, NOW, with_followers=True)["class_table"]
    assert table["seeded"] is True and table["follower_count"] == 2
    assert table["followers"] == [{"n": 1, "takes": 2, "first": 60, "latest": 70, "delta": 10}]


def test_a_synthetic_analysis_alone_marks_the_table_seeded(tmp_path: Path) -> None:  # AC-C8
    _job(tmp_path, "a00000000001", analysis={"status": {"code": "ok"}, "score": _score(60, "D"), "synthetic": True})
    assert teacher_stats.page(tmp_path, ENTRY, {}, NOW, with_followers=True)["class_table"]["seeded"] is True


def _class_world(api: Api) -> dict[str, Any]:
    """The 3-follower fixture on the route: ada and ben own their takes; trainer owns the entry; a third account looks on."""
    owners = _class_fixture(api.app.queue.root)
    sids = {who: sign_in(api, f"{who}@example.com") for who in ("ada", "ben", "trainer", "other")}
    store = auth.identity(api.app)
    users = {who: store.session_user(sid) for who, sid in sids.items()}
    for job, who in owners.items():
        store.attach(job, users[who.removeprefix("user-")], "follow", ENTRY, None, "submit")
    store.attach_entry(ENTRY, users["trainer"])
    return {"owners": owners, "sids": sids, "users": users}


def _secrets(world: dict[str, Any]) -> list[str]:
    return [*world["users"].values(), *world["owners"], "@example.com", "c00000000001"]


PER_FOLLOWER = ('"delta"', '"first"', '"latest"', '"takes":', '"n":')  # the fields of a per-follower row


@pytest.mark.usefixtures("authenv")
def test_owner_gets_the_per_follower_rows(api: Api) -> None:  # AC-C1, AC-C4, AC-C11
    world = _class_world(api)
    status, _, doc = get(api, f"api/teacher/{ENTRY}", cookie=world["sids"]["trainer"])
    table = doc["class_table"]
    assert status == 200 and doc["attribution"]["mine"] is True
    assert table["follower_count"] == 3 and table["top_cue"] == {"text": "Knees out", "followers": 3}
    assert [(r["n"], r["takes"]) for r in table["followers"]] == [(1, 3), (2, 2)]
    text = json.dumps(doc)
    for secret in _secrets(world):
        assert secret not in text  # AC-C5: even the owner gets numbers, never who


@pytest.mark.usefixtures("authenv")
def test_another_account_and_a_follower_get_aggregates_only(api: Api) -> None:  # AC-C11
    world = _class_world(api)
    for who in ("other", "ada"):  # a stranger, and a follower who is in the table
        status, _, doc = get(api, f"api/teacher/{ENTRY}", cookie=world["sids"][who])
        assert status == 200 and doc["attribution"]["mine"] is False
        # private-default D3 (operator ruling 2026-11-03): no class table, no cue, no row; the count of shared takes only
        assert doc["class_table"] is None and doc["takes"] == [] and doc["cue_counts"] == [] and doc["take_count"] == 6
        text = json.dumps(doc["class_table"])
        for field in PER_FOLLOWER:
            assert field not in text, (who, field)  # negative: no per-follower field reaches anyone but the owner
        for secret in _secrets(world):
            assert secret not in json.dumps(doc)


@pytest.mark.usefixtures("authenv")
def test_signed_out_gets_aggregates_only_and_no_401(api: Api) -> None:  # AC-C11
    _class_world(api)
    status, _, doc = get(api, f"api/teacher/{ENTRY}")
    assert status == 200 and doc["class_table"] is None and doc["take_count"] == 6  # private-default D3: no time at all
    for field in PER_FOLLOWER:
        assert field not in json.dumps(doc["class_table"])


def test_the_owner_flag_fails_closed(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-C11
    _class_fixture(api.app.queue.root)
    from part7 import attribution
    monkeypatch.setattr(attribution, "payload", lambda *_: (_ for _ in ()).throw(RuntimeError("store down")))
    status, doc = api.json("GET", f"api/teacher/{ENTRY}")
    assert status == 200 and doc["class_table"] is None and doc["takes"] == []


def test_follow_owners_reads_only_follow_takes_of_the_entry(api: Api) -> None:
    store = auth.identity(api.app)
    user = store._user_for("ada@example.com", time.time())
    store.attach("a00000000001", user, "follow", ENTRY, None, "submit")
    store.attach("a00000000002", user, "follow", "other-move", None, "submit")
    store.attach("a00000000003", user, "trainer", ENTRY, None, "submit")
    assert identity.follow_owners(api.app.state, ENTRY) == {"a00000000001": user}
    assert identity.follow_owners(api.app.state / "nowhere", ENTRY) == {}


def test_seed_tool_refuses_off_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-C9
    monkeypatch.delenv("SIMON7_STAGING", raising=False)
    assert seed_class.main(["--state", str(tmp_path)]) == 2
    assert not (tmp_path / "jobs").exists()


def test_seed_tool_writes_a_labelled_three_follower_class(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-C9
    monkeypatch.setenv("SIMON7_STAGING", "1")
    jobs = seed_class.seed(tmp_path, ENTRY, now=NOW)
    assert len(jobs) == 6 and seed_class.seed(tmp_path, ENTRY, now=NOW) == jobs  # same ids again
    table = teacher_stats.page(tmp_path / "jobs", ENTRY, {}, NOW, with_followers=True)["class_table"]
    assert table["seeded"] is True and table["follower_count"] == 3 and table["takes_7d"] == 6
    assert table["top_cue"] == {"text": "Seeded cue for knee valgus", "followers": 3}
    assert [(r["n"], r["first"], r["latest"]) for r in table["followers"]] == [(1, 58, 81), (2, 61, 70)]
