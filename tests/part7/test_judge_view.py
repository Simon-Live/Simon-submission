"""The curated judge view: test-artefact rule, boards, page default and hero take (docs/specs/judge-view.md, AC-J1 to AC-J6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from part7 import challenges, entry_access, jobs, judge_view
from support import Api, published

REAL = "body-squat-19b06562"
HEADER = b'{"format": "part2.mesh3d/2026-10-31", "bin": "mesh3d.bin"}'


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(judge_view.HERO_ENV, raising=False)
    monkeypatch.delenv(judge_view.PROFILE_ENV, raising=False)


def put_mesh(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "mesh3d.json").write_bytes(HEADER)
    (folder / "mesh3d.bin").write_bytes(bytes(range(16)))


def finished(api: Api, kind: str, entry: str, score: int | None = None, mesh: bool = True,
             analysis: dict[str, Any] | None = None) -> str:
    who = "trainer" if kind == "trainer" else "follower"

    def fn(ctx: jobs.JobContext) -> dict[str, Any]:
        if mesh:
            put_mesh(ctx.dir / "work" / who / "part2")
        if analysis is not None:
            (ctx.dir / "work").mkdir(parents=True, exist_ok=True)
            (ctx.dir / "work" / "analysis.json").write_text(json.dumps(analysis))
        return {"result": {"entry_id": entry} if score is None else {"entry_id": entry, "score": score}}

    rec = api.app.queue.submit(kind, fn, entry_id=entry)
    assert api.app.queue.wait(rec["id"], 10)["status"] == "done"
    if kind == "trainer":
        published(api.app.state, entry)  # the movement it made is public (W-N1)
    return rec["id"]


def board(api: Api, entry: str, title: str) -> str:
    published(api.app.state, entry)  # a published movement (W-N1: one without a row is shown to nobody)
    return challenges.create(api.app.state, entry_id=entry, title=title, creator_name="Sam", kind="friend")["id"]


# ----- AC-J1 the rule --------------------------------------------------------------------------------------
@pytest.mark.parametrize("entry_id", [
    "verify-2026-11-02t00-53-32z-196f3040", "check-7-2026-11-01-ab12", "qa-journey-qamvxvd3y", "QA-190-board", "Verify-x",
])
def test_a_verify_check7_or_qa_movement_is_a_test_artefact(entry_id: str) -> None:
    assert judge_view.is_test_id(entry_id) is True


@pytest.mark.parametrize("entry_id", [REAL, "squat", "arm-wave", "quality-squat", "verified-move", "", None])
def test_a_real_movement_is_not(entry_id: Any) -> None:
    assert judge_view.is_test_id(entry_id) is False


# ----- AC-J2 boards ----------------------------------------------------------------------------------------
def test_the_judge_view_hides_test_boards_and_the_plain_list_keeps_them(api: Api) -> None:
    real = board(api, REAL, "Beat my squat")
    test = board(api, "verify-2026-11-02t00-53-32z-196f3040", "Beat my verify")
    qa = board(api, "qa-journey-qamvxvd3y", "Beat my QA journey")
    _, plain = api.json("GET", "api/challenges")
    assert {c["id"] for c in plain["challenges"]} == {real, test, qa}  # the verify and QA runs still see their own
    _, judge = api.json("GET", "api/challenges?view=judge")
    assert [c["id"] for c in judge["challenges"]] == [real]
    _, judged = api.json("GET", f"api/challenges?view=judge&entry_id={REAL}")
    assert [c["id"] for c in judged["challenges"]] == [real]
    status, _ = api.json("GET", f"api/challenges/{test}")
    assert status == 200  # hidden from the list only; the link still opens, nothing is deleted


# ----- AC-J3 page default ----------------------------------------------------------------------------------
def test_index_carries_the_default_profile_only_on_the_judge_url(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    (api.app.web_dir / "index.html").write_text("<head><title>Simon</title></head><h1>Simon</h1>", encoding="utf-8")
    _, _, plain = api.request("GET", "")
    assert b"simon-default-profile" not in plain
    monkeypatch.setenv(judge_view.PROFILE_ENV, "submission")
    _, _, judge = api.request("GET", "")
    assert b'<meta name="simon-default-profile" content="submission">\n</head>' in judge
    _, _, app_js = api.request("GET", "app.js")
    assert b"simon-default-profile" not in app_js


def test_an_unknown_default_profile_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(judge_view.PROFILE_ENV, "debug")
    assert judge_view.default_profile() == "default"
    assert judge_view.page_with_profile(b"<head></head>") == b"<head></head>"


# ----- AC-J5 hero ------------------------------------------------------------------------------------------
NONE = {"job_id": None, "entry_id": None, "score": None, "source": "none"}


def name_hero(monkeypatch: pytest.MonkeyPatch, job_id: str) -> dict[str, Any]:
    monkeypatch.setenv(judge_view.HERO_ENV, job_id)
    return judge_view.hero(Path("/nonexistent-state"), Path("/nonexistent-jobs"))


def test_with_no_named_hero_no_take_is_offered(api: Api) -> None:
    """TICKET-373: the old best-scoring pick handed visitors a stranger's job id, and the id is the key to the take."""
    finished(api, "trainer", REAL)
    unnamed = finished(api, "follow", REAL, score=88)  # qualifies: a real movement, a score and both meshes
    status, _, raw = api.request("GET", "api/judge/hero")
    assert status == 200 and json.loads(raw) == NONE
    assert unnamed.encode() not in raw  # negative: the id of a take nobody named is never in the answer


def test_a_configured_hero_wins_by_environment_then_by_file(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    finished(api, "trainer", REAL)
    low = finished(api, "follow", REAL, score=50)
    other = finished(api, "follow", REAL, score=60)
    finished(api, "follow", REAL, score=90)
    (api.app.state / judge_view.HERO_FILE).write_text(json.dumps({"job_id": low}), encoding="utf-8")
    assert api.json("GET", "api/judge/hero")[1] == {"job_id": low, "entry_id": REAL, "score": 50, "source": "configured"}
    monkeypatch.setenv(judge_view.HERO_ENV, other)
    _, doc = api.json("GET", "api/judge/hero")
    assert (doc["job_id"], doc["source"]) == (other, "configured")
    assert judge_view.configured_id(api.app.state) == other


def test_residual5_the_hero_never_names_a_movement_the_caller_may_not_see(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    finished(api, "trainer", REAL)
    take = finished(api, "follow", REAL, score=70)
    monkeypatch.setenv(judge_view.HERO_ENV, take)
    assert api.json("GET", "api/judge/hero")[1]["job_id"] == take  # shown while the movement is public
    entry_access.set_published(api.app.state, REAL, False)
    assert api.json("GET", "api/judge/hero") == (200, NONE), "a private movement named as the hero"
    entry_access.drop(api.app.state, REAL)
    assert api.json("GET", "api/judge/hero") == (200, NONE), "a movement with no row named as the hero"


def test_a_configured_hero_that_does_not_qualify_is_ignored_and_nothing_stands_in(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    finished(api, "trainer", REAL)
    finished(api, "follow", REAL, score=80)  # qualifies, but nobody named it
    nomesh = finished(api, "follow", REAL, score=99, mesh=False)
    monkeypatch.setenv(judge_view.HERO_ENV, nomesh)
    assert api.json("GET", "api/judge/hero") == (200, NONE)
    monkeypatch.setenv(judge_view.HERO_ENV, "not-a-job")
    assert api.json("GET", "api/judge/hero") == (200, NONE)


def test_a_named_test_movement_take_answers_null(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    finished(api, "trainer", "verify-2026-11-02t00-53-32z-196f3040")
    test_take = finished(api, "follow", "verify-2026-11-02t00-53-32z-196f3040", score=99)
    monkeypatch.setenv(judge_view.HERO_ENV, test_take)
    assert api.json("GET", "api/judge/hero") == (200, NONE)


def test_a_capped_or_warned_take_is_never_the_hero(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    """QA on staging 2026-11-02: the best take with meshes was a low-match take capped at 59 F; a judge saw it first."""
    finished(api, "trainer", REAL)
    ok = finished(api, "follow", REAL, score=70, analysis={"status": {"code": "ok"}, "score": {"value": 70}})
    capped = finished(api, "follow", REAL, score=95, analysis={"status": {"code": "ok"}, "warnings": [{"code": "low_match"}],
                                                                "score": {"value": 59, "capped_by": ["low_match"]}})
    low = finished(api, "follow", REAL, score=90, analysis={"status": {"code": "ok"}, "match": {"quality": "low"}})
    for warned in (capped, low):
        monkeypatch.setenv(judge_view.HERO_ENV, warned)
        assert api.json("GET", "api/judge/hero") == (200, NONE)  # negative: named, scored higher, still not shown
    monkeypatch.setenv(judge_view.HERO_ENV, ok)
    assert api.json("GET", "api/judge/hero")[1]["job_id"] == ok


def test_no_named_take_and_no_file_means_no_hero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert judge_view.configured_id(tmp_path) is None
    assert judge_view.hero(tmp_path, tmp_path) == NONE
    assert name_hero(monkeypatch, "aaaaaaaaaaaa") == NONE  # named, but this server does not hold it


# ----- TICKET-247: a dim or dark take is never the hero -----------------------------------------------------
@pytest.mark.parametrize("level,warned", [("ok", False), ("degraded", True), ("major", True)])
def test_a_take_with_light_above_ok_is_warned(tmp_path: Path, level: str, warned: bool) -> None:
    result = {"score": 80, "light": {"median_y": 50, "dark_share": 1.0, "level": level}}
    assert judge_view._warned(tmp_path, result) is warned


@pytest.mark.parametrize("level,warned", [("ok", False), ("degraded", True), ("major", True), (None, False)])
def test_a_take_with_quality_above_ok_is_warned(tmp_path: Path, level: str | None, warned: bool) -> None:
    result: dict = {"score": 80}
    if level:
        result["quality"] = {"version": "simon.quality.v1", "level": level, "reasons": [], "signals": {}, "score_cap": 59 if level == "major" else None}
    assert judge_view._warned(tmp_path, result) is warned  # no block: not assessed, not excluded


def test_the_analysis_file_quality_block_also_warns(tmp_path: Path) -> None:
    (tmp_path / "analysis.json").write_text('{"quality": {"level": "major", "score_cap": 59}, "score": {"value": 90}}', encoding="utf-8")
    assert judge_view._warned(tmp_path, {"score": 59, "analysis": "analysis.json"}) is True


def test_a_take_without_light_is_not_warned_by_it(tmp_path: Path) -> None:
    assert judge_view._warned(tmp_path, {"score": 80}) is False


def test_a_named_dark_take_is_not_the_hero(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    finished(api, "trainer", REAL)
    ok = finished(api, "follow", REAL, score=50)

    def dark_take(ctx: jobs.JobContext) -> dict[str, Any]:
        put_mesh(ctx.dir / "work" / "follower" / "part2")
        return {"result": {"entry_id": REAL, "score": 59, "light": {"median_y": 44.0, "dark_share": 1.0, "level": "major"}}}

    rec = api.app.queue.submit("follow", dark_take, entry_id=REAL)
    assert api.app.queue.wait(rec["id"], 10)["status"] == "done"
    monkeypatch.setenv(judge_view.HERO_ENV, rec["id"])
    assert api.json("GET", "api/judge/hero") == (200, NONE)
    monkeypatch.setenv(judge_view.HERO_ENV, ok)
    assert api.json("GET", "api/judge/hero")[1]["job_id"] == ok
