"""One take, one letter (docs/specs/one-letter.md AC-1 to AC-5): every server surface shows the result headline's score.

The trigger is the real MM-Fit take 42a02415127e (CC BY 4.0): `score.value` 37, grade F, credit 16,239 of 22,367 points
and C on Part 5's F to S scale, no cap. The result headline shows C; every other surface showed F. The capped variant
carries a `low_match` warning cap: the cap wins, so it is 37 and F everywhere.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from history_support import ENTRY, SECOND, USER, World, job_record, seed_job, world  # noqa: F401
from part7 import (auth_routes, challenge_routes, challenges, export_clip, export_data, group, history_facts, history_report,
                   history_store, judge_view, notes_routes, share_routes, shown_score, teacher_stats)
from support import Api

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "shown-score-vectors.json").read_text(encoding="utf-8"))["cases"]
TRIGGER = VECTORS[0]["analysis"]["score"]
CAPPED = VECTORS[4]["analysis"]["score"]
CREDIT_SHOWN = {"letter": "C", "figures": "16,239", "caption": "of 22,367", "unit": "points", "capped": False, "warning": [],
                "measure": 72.6}
# team, 2 Nov (#61): nothing capped. A warned take with a credit shows the credit; the warning is still named
CAPPED_SHOWN = {"letter": "C", "figures": "16,239", "caption": "of 22,367", "unit": "points", "capped": False, "warning": ["low_match"],
                "measure": 72.6}


def _analysis(score: dict[str, Any]) -> dict[str, Any]:
    return {"status": {"code": "ok"}, "score": copy.deepcopy(score), "faults": [{"text": "knees in", "at_s": 1.0}],
            **({"warnings": [{"code": "low_match", "text": "Low match."}]} if score.get("capped_by") else {})}


def _job(root: Path, job_id: str, score: dict[str, Any], *, entry: str = "squat-real-people", light: Any = None, **extra: Any) -> Path:
    folder = root / job_id
    (folder / "work" / "follower").mkdir(parents=True)
    result = {"score": score["value"], "grade": score["grade"], **({"light": light} if light else {})}
    record = {"id": job_id, "kind": "follow", "status": "done", "entry_id": entry, "finished_at": "2026-11-02T10:00:00Z",
              "created_at": "2026-11-02T10:00:00Z", "result": result, **extra}
    (folder / "job.json").write_text(json.dumps(record), encoding="utf-8")
    (folder / "work" / "follower" / "analysis.json").write_text(json.dumps(_analysis(score)), encoding="utf-8")
    return folder


# ----- AC-1: the decision, held to the browser's by the shared vectors ----------------------------------------------------
@pytest.mark.parametrize("case", VECTORS, ids=[c["name"] for c in VECTORS])
def test_the_shared_vectors(case: dict[str, Any]) -> None:
    assert shown_score.shown(case["analysis"], case.get("light"), case.get("display")) == case["expect"]


def test_the_credit_letter_comes_from_the_analysis_grades_not_a_constant() -> None:
    """Part 5 1.14.3 moved E to 40 and F under 40; a document written before keeps its own marks (E 45, F 30)."""
    new_scale = [[95, "S"], [85, "A"], [75, "B"], [65, "C"], [55, "D"], [40, "E"], [0, "F"]]
    old_scale = [[95, "S"], [85, "A"], [75, "B"], [65, "C"], [55, "D"], [45, "E"], [30, "F"]]

    def letter(grades: Any, percent: float = 42.0) -> str:
        credit = {"percent": percent, "points": percent * 10, "max_points": 1000, "tolerance": "normal", "grade": "F", "grades": grades}
        score = {"value": 20, "grade": "F", "credit": credit}
        return shown_score.shown({"score": score})["letter"]

    assert letter(new_scale) == "E" and letter(old_scale) == "F"
    assert letter(new_scale, 39.9) == "F" and letter(new_scale, 40.0) == "E"


def test_public_is_the_row_block_and_none_stays_none() -> None:
    assert shown_score.public(shown_score.shown({"score": TRIGGER})) == CREDIT_SHOWN
    assert shown_score.public(None) is None and shown_score.of_path(None) is None
    assert shown_score.of_path(Path("/nonexistent/analysis.json")) is None


# ----- AC-2, AC-3: each surface -----------------------------------------------------------------------------------------
def test_teacher_dashboard_takes(tmp_path: Path) -> None:
    _job(tmp_path, "aaaaaaaaaaaa", TRIGGER)
    _job(tmp_path, "bbbbbbbbbbbb", CAPPED, finished_at="2026-11-02T11:00:00Z")
    takes = teacher_stats.collect(tmp_path, "squat-real-people")["takes"]
    assert [(t["score"], t["grade"]) for t in takes] == [(37, "F"), (37, "F")]   # the numeric field and Part 5's grade stay
    assert [t["shown"] for t in takes] == [CREDIT_SHOWN, CAPPED_SHOWN]


def test_history_copy_rows_facts_and_report(tmp_path: Path, world: World) -> None:  # noqa: F811
    world.opted_in.add(USER)
    folder = seed_job(tmp_path, SECOND, with_video=False, result={"score": 37, "grade": "F", "light": {"level": "ok"}})
    (folder / "work" / "follower" / "analysis.json").write_text(json.dumps(_analysis(TRIGGER)), encoding="utf-8")
    world.owners[SECOND] = USER
    assert history_store.record_take(tmp_path, job_record(tmp_path, SECOND), folder)
    meta = json.loads((tmp_path / "history" / USER / ENTRY / "takes" / SECOND / "meta.json").read_text())
    assert meta["light"] == {"level": "ok"}   # kept with a new copy, so the light cap can be applied at read time
    take = history_store.takes(tmp_path, USER, ENTRY)[0]
    assert (take["score"], take["grade"]) == (37, "F")
    assert shown_score.of_take(take) == CREDIT_SHOWN
    row = history_facts.build([take], ENTRY)["takes"][0]
    assert row["shown"] == CREDIT_SHOWN
    assert history_report._row(take)["shown"] == CREDIT_SHOWN
    pending = history_store.pending_take(tmp_path, USER, SECOND)
    assert pending is not None and shown_score.of_take(pending) == CREDIT_SHOWN


def test_an_old_history_copy_without_light_gets_no_light_cap(tmp_path: Path) -> None:  # AC-5
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(_analysis({**TRIGGER, "value": 75, "grade": "C"})), encoding="utf-8")
    assert shown_score.of_take({"analysis": path})["letter"] == "C"
    dark = shown_score.of_take({"analysis": path, "light": {"level": "major"}})   # nothing capped (team, 2 Nov): the credit, the light named
    assert dark["figures"] == "16,239" and dark["capped"] is False and dark["warning"] == ["quality_light_dark"]


def test_me_list_score(tmp_path: Path) -> None:
    _job(tmp_path, "aaaaaaaaaaaa", TRIGGER)
    _job(tmp_path, "bbbbbbbbbbbb", CAPPED)
    h = SimpleNamespace(app=SimpleNamespace(queue=SimpleNamespace(job_dir=lambda j: tmp_path / j)))
    assert auth_routes._score_of(h, "aaaaaaaaaaaa") == (37, "F", CREDIT_SHOWN)
    assert auth_routes._score_of(h, "bbbbbbbbbbbb") == (37, "F", CAPPED_SHOWN)


def test_export_download_score_of_a_take_with_no_copy(tmp_path: Path) -> None:
    _job(tmp_path, "aaaaaaaaaaaa", TRIGGER)
    ctx = SimpleNamespace(jobs=tmp_path)
    assert export_data._job_score(ctx, "aaaaaaaaaaaa") == (37, "F", False, CREDIT_SHOWN)


def _routes_h(root: Path) -> Any:
    jobs = {p.name: json.loads((p / "job.json").read_text()) for p in root.iterdir() if (p / "job.json").is_file()}
    return SimpleNamespace(app=SimpleNamespace(queue=SimpleNamespace(get=jobs.get, job_dir=lambda j: root / j), state=root))


def test_board_entry_stores_the_shown_score_and_ranks_by_the_shown_measure(tmp_path: Path) -> None:  # AC-4
    _job(tmp_path, "aaaaaaaaaaaa", TRIGGER)
    _job(tmp_path, "bbbbbbbbbbbb", CAPPED)
    _job(tmp_path, "cccccccccccc", {"value": 50, "grade": "F"})
    h, board = _routes_h(tmp_path), {"entry_id": "squat-real-people"}
    credit, capped, plain = (challenge_routes._score_entry(h, board, j, None, n) for j, n in
                             (("aaaaaaaaaaaa", "Ana"), ("bbbbbbbbbbbb", "Ben"), ("cccccccccccc", "Cy")))
    assert (credit["score"], credit["grade"], credit["shown"]) == (37, "F", CREDIT_SHOWN)
    assert capped["shown"] == CAPPED_SHOWN
    ranked = challenges.ranked([{**e, "created_at": "2026-11-02T10:00:00Z"} for e in (credit, plain)])
    assert [e["name"] for e in ranked] == ["Ana", "Cy"]   # one-letter.md L3: the shown measure, C at 72.6% above 50 F
    lead = challenges.summary({"id": "x", "entries": [{**credit, "created_at": "2026-11-02T10:00:00Z"}]})["leader"]
    assert lead["shown"] == CREDIT_SHOWN and lead["score"] == 37


def test_group_rows(tmp_path: Path) -> None:
    for pid, score in (("1", TRIGGER), ("2", CAPPED)):
        path = tmp_path / pid / "analysis.json"
        path.parent.mkdir()
        path.write_text(json.dumps(_analysis(score)), encoding="utf-8")
    rows = [group._follower_row("aaaaaaaaaaaa", pid, f"Person {pid}", {"ok": True, "files": {"analysis": str(tmp_path / pid / "analysis.json")}})
            for pid in ("1", "2")]
    assert [(r["score"], r["grade"], r["shown"]) for r in rows] == [(37, "F", CREDIT_SHOWN), (37, "F", CAPPED_SHOWN)]


def test_export_clip_burns_the_shown_score() -> None:
    job = {"result": {"score": 37, "grade": "F"}}
    facts = export_clip.facts_from(job, _analysis(TRIGGER))
    texts = export_clip.texts_for(facts)
    assert (texts["score.txt"], texts["grade.txt"]) == ("16,239", "Grade C")
    assert (facts.score, facts.grade) == (37, "F")   # the job result's fields stay
    capped = export_clip.texts_for(export_clip.facts_from(job, _analysis(CAPPED)))
    assert (capped["score.txt"], capped["grade.txt"]) == ("16,239", "Grade C")   # nothing capped: the credit is burnt in
    old = export_clip.texts_for(export_clip.facts_from(job, {"faults": []}))
    assert (old["score.txt"], old["grade.txt"]) == ("37", "Grade F")   # no analysis score: the job result's, as before


def test_judge_hero_carries_the_shown_score(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(judge_view.HERO_ENV, raising=False)
    monkeypatch.setattr(judge_view.mesh_files, "index", lambda root, job_id: {"follower": True, "trainer": True})
    _job(tmp_path, "aaaaaaaaaaaa", TRIGGER, light={"level": "ok"})
    _job(tmp_path, "bbbbbbbbbbbb", {"value": 50, "grade": "F"}, light={"level": "ok"})
    assert judge_view.hero(tmp_path, tmp_path)["job_id"] is None   # TICKET-373: nothing is picked unless named
    monkeypatch.setenv(judge_view.HERO_ENV, "aaaaaaaaaaaa")
    hero = judge_view.hero(tmp_path, tmp_path)
    assert hero["job_id"] == "aaaaaaaaaaaa" and hero["shown"] == CREDIT_SHOWN
    named = judge_view._candidate(tmp_path, "aaaaaaaaaaaa")
    assert named is not None and named["score"] == 37 and named["shown"] == CREDIT_SHOWN


# the judge hero take f7f06d0bc4f3 (hero.json, 2026-11-02): value 31 F, credit 72.3% C, 17,486 of 24,200 points, uncapped
HERO_TAKE = {**TRIGGER, "value": 31, "grade": "F",
             "credit": {**TRIGGER["credit"], "percent": 72.3, "points": 17486, "max_points": 24200,
                        "levels": {"normal": {"percent": 72.3, "points": 17486, "max_points": 24200}}}}
HERO_SHOWN = {"letter": "C", "figures": "17,486", "caption": "of 24,200", "unit": "points", "capped": False, "warning": [], "measure": 72.3}


def _hero_job(api: Api, score: dict[str, Any]) -> str:
    from test_judge_view import REAL, put_mesh

    def fn(ctx: Any) -> dict[str, Any]:
        put_mesh(ctx.dir / "work" / "follower" / "part2")
        (ctx.dir / "work" / "follower" / "analysis.json").write_text(json.dumps({"status": {"code": "ok"}, "score": score}), encoding="utf-8")
        return {"result": {"entry_id": REAL, "score": score["value"], "grade": score["grade"], "light": {"level": "ok"}}}

    from test_judge_view import finished
    finished(api, "trainer", REAL)
    rec = api.app.queue.submit("follow", fn, entry_id=REAL)
    assert api.app.queue.wait(rec["id"], 10)["status"] == "done"
    return rec["id"]


def test_api_judge_hero_carries_the_headline_score(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # coordinator priority
    monkeypatch.delenv(judge_view.HERO_ENV, raising=False)
    job = _hero_job(api, HERO_TAKE)
    (api.app.state / judge_view.HERO_FILE).write_text(json.dumps({"job_id": job}), encoding="utf-8")
    status, doc = api.json("GET", "api/judge/hero")
    assert status == 200 and (doc["job_id"], doc["source"], doc["score"]) == (job, "configured", 31)   # the ranked field stays
    assert doc["shown"] == HERO_SHOWN   # negative: not 31 and F


def test_notes_score_for_the_trainer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for score, expect in ((TRIGGER, CREDIT_SHOWN), (CAPPED, CAPPED_SHOWN)):
        assert notes_routes._score_doc(_analysis(score)) == {"value": 37, "grade": "F", "shown": expect}
    assert notes_routes._score_doc({"score": {"grade": "F"}}) is None


def test_shared_history_report_rows() -> None:
    rows = share_routes._report_rows({"takes": [{"take": 1, "at": "2026-11-02T10:00:00Z", "score": 37, "grade": "F", "shown": CREDIT_SHOWN},
                                                {"take": 2, "at": "2026-11-02T11:00:00Z", "score": 37, "grade": "F"}]})
    assert rows[0]["shown"] == CREDIT_SHOWN and (rows[0]["score"], rows[0]["grade"]) == (37, "F")
    assert "shown" not in rows[1]   # a report cached before the block: score and grade as before (AC-5)


def test_history_entry_route_sends_the_shown_block(api: Api, world: World) -> None:  # noqa: F811
    world.opted_in.add(USER)
    state = api.app.state
    folder = seed_job(state, SECOND, with_video=False)
    (folder / "work" / "follower" / "analysis.json").write_text(json.dumps(_analysis(CAPPED)), encoding="utf-8")
    world.owners[SECOND] = USER
    assert history_store.record_take(state, job_record(state, SECOND), folder)
    status, doc = api.json("GET", f"api/me/history/{ENTRY}", headers={"X-Test-User": USER})
    assert status == 200
    assert doc["takes"][0]["shown"] == CAPPED_SHOWN and doc["takes"][0]["grade"] == "F"
    status, listing = api.json("GET", "api/me/history", headers={"X-Test-User": USER})
    assert status == 200 and listing["entries"][0]["latest"]["shown"] == CAPPED_SHOWN
