"""The Impact page's persona takes and the architecture page's diagrams (docs/specs/impact-page.md, AC-I1 to AC-I4, AC-A1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from part7 import architecture, config, impact
from support import Api

SHAPE = {  # the contract of docs/impact/persona-takes.json, from the session that makes the takes
    "persona": "seated", "job_id": "", "entry_id": "seated-stretch-1a2b3c4d", "take_url": "https://example.test/#/result/x",
    "trainer_entry_url": "https://example.test/#/watch/x", "score": 71, "mode": "rehab",
    "clip_source": {"url": "https://www.pexels.com/video/1/", "licence": "Pexels License", "file": "videos/x/take.mp4"},
    "why_this_clip": "A seated take with the legs out of frame.", "recorded_utc": "2026-11-02T01:00:00Z", "staging_sha": "abc1234",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(impact.ENV, raising=False)


def put_job(api: Api, job_id: str, entry: str, score: Any = 71, **extra: Any) -> str:
    folder = api.app.queue.job_dir(job_id)
    folder.mkdir(parents=True, exist_ok=True)
    record = {"id": job_id, "kind": "follow", "status": "done", "entry_id": entry, "result": {"entry_id": entry, "score": score}, **extra}
    (folder / "job.json").write_text(json.dumps(record), encoding="utf-8")
    return job_id


def finished(api: Api, entry: str, score: Any, **extra: Any) -> str:
    """A real finished follow take through the queue, as a judge's click would find it."""
    rec = api.app.queue.submit("follow", lambda ctx: {"result": {"entry_id": entry, "score": score}}, entry_id=entry, **extra)
    assert api.app.queue.wait(rec["id"], 10)["status"] == "done"
    return rec["id"]


def row(persona: str, job_id: str, entry: str, **extra: Any) -> dict[str, Any]:
    return {**SHAPE, "persona": persona, "job_id": job_id, "entry_id": entry, **extra}


def write_takes(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(rows), encoding="utf-8")


def by_persona(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["persona"]: p for p in doc["personas"]}


# ----- AC-I1 a card's take is a real finished take on this server, or nothing ----------------------------------------
def test_each_named_take_is_fetched_and_answers_with_its_score(api: Api) -> None:
    a = finished(api, "seated-stretch-1a2b3c4d", 71, mode="rehab")
    b = finished(api, "salsa-basic-9f8e7d6c", 64.6, mode="dance")
    write_takes(api.app.state / impact.STATE_FILE, [row("seated", a, "seated-stretch-1a2b3c4d"), row("remote-class", b, "salsa-basic-9f8e7d6c")])
    status, doc = api.json("GET", "api/impact")
    assert status == 200 and doc["source"] == "state"
    assert [p["persona"] for p in doc["personas"]] == list(impact.PERSONAS)
    got = by_persona(doc)
    assert got["seated"]["take"]["score"] == 71 and got["seated"]["take"]["mode"] == "rehab"
    assert got["seated"]["take"]["clip_source"] == {"url": "https://www.pexels.com/video/1/", "licence": "Pexels License"}
    assert got["remote-class"]["take"]["job_id"] == b and got["remote-class"]["take"]["mode"] == "dance"
    assert got["bodies"] == {"persona": "bodies", "take": None, "missing": "not_listed"}
    for persona in ("seated", "remote-class"):  # every card's job id opens: the job answers 200 with a score
        job = got[persona]["take"]["job_id"]
        code, record = api.json("GET", f"api/jobs/{job}")
        assert code == 200 and isinstance(record["result"]["score"], (int, float)), persona


@pytest.mark.parametrize("why, job_id, entry, extra", [
    ("not on this server", "c3c3c3c3c3c3", "lunge-1", {}),
    ("the committed example", "fixture", "lunge-1", {}),
    ("a QA take", "d4d4d4d4d4d4", "qa-journey-x1", {}),
    ("a verify take", "e5e5e5e5e5e5", "verify-2026-11-02t00-00-00z-1", {}),
    ("private", "f6f6f6f6f6f6", "lunge-1", {"private": True}),
    ("no score", "a7a7a7a7a7a7", "lunge-1", {"score": None}),
    ("another movement than the file names", "b8b8b8b8b8b8", "lunge-2", {"file_entry": "lunge-1"}),
])
def test_a_named_take_that_does_not_qualify_is_missing_not_trusted(api: Api, why: str, job_id: str, entry: str, extra: dict[str, Any]) -> None:
    if why != "not on this server" and job_id != "fixture":
        put_job(api, job_id, entry, extra.get("score", 70), **({"private": True} if extra.get("private") else {}))
    write_takes(api.app.state / impact.STATE_FILE, [row("bodies", job_id, extra.get("file_entry", entry))])
    _, doc = api.json("GET", "api/impact")
    assert by_persona(doc)["bodies"] == {"persona": "bodies", "take": None, "missing": "not_found"}, why


def test_the_environment_wins_then_the_state_file_then_the_repo_file(api: Api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    a = put_job(api, "a1a1a1a1a1a1", "lunge-1")
    b = put_job(api, "b2b2b2b2b2b2", "lunge-2")
    repo = tmp_path / "repo"
    (repo / impact.REPO_FILE).parent.mkdir(parents=True)
    write_takes(repo / impact.REPO_FILE, [row("bodies", a, "lunge-1")])
    jobs_root = api.app.queue.job_dir("0" * 12).parent
    assert impact.personas(api.app.state, jobs_root, repo)["source"] == "repo"
    write_takes(api.app.state / impact.STATE_FILE, [row("bodies", b, "lunge-2")])
    doc = impact.personas(api.app.state, jobs_root, repo)
    assert doc["source"] == "state" and by_persona(doc)["bodies"]["take"]["job_id"] == b
    named = tmp_path / "named.json"
    write_takes(named, [row("home-rehab", a, "lunge-1")])
    monkeypatch.setenv(impact.ENV, str(named))
    doc = impact.personas(api.app.state, jobs_root, repo)
    assert doc["source"] == "env" and by_persona(doc)["home-rehab"]["take"]["job_id"] == a
    assert by_persona(doc)["bodies"]["take"] is None


def test_no_file_anywhere_gives_four_empty_personas(api: Api, tmp_path: Path) -> None:
    doc = impact.personas(api.app.state, api.app.queue.job_dir("0" * 12).parent, tmp_path)
    assert doc["source"] == "none"
    assert [p["missing"] for p in doc["personas"]] == ["not_listed"] * 4


@pytest.mark.parametrize("bad", ["not json", json.dumps({"persona": "seated"}), json.dumps([1, "x", None])])
def test_a_broken_file_gives_empty_personas_not_an_error(api: Api, bad: str) -> None:
    (api.app.state / impact.STATE_FILE).write_text(bad, encoding="utf-8")
    status, doc = api.json("GET", "api/impact")
    assert status == 200 and all(p["take"] is None for p in doc["personas"])


def test_an_unknown_persona_and_a_clip_url_that_is_not_https_are_dropped(api: Api) -> None:
    a = put_job(api, "a1a1a1a1a1a1", "lunge-1")
    rows = [row("astronaut", a, "lunge-1"), row("bodies", a, "lunge-1", clip_source={"url": "javascript:alert(1)", "licence": "CC0"})]
    write_takes(api.app.state / impact.STATE_FILE, rows)
    _, doc = api.json("GET", "api/impact")
    assert {p["persona"] for p in doc["personas"]} == set(impact.PERSONAS)
    assert by_persona(doc)["bodies"]["take"]["clip_source"] == {"url": None, "licence": "CC0"}


def test_the_committed_takes_file_when_present_has_the_contract_shape() -> None:
    path = config.REPO_ROOT / impact.REPO_FILE
    if not path.is_file():
        return  # not written yet: the page then shows every persona empty, which the tests above cover
    rows = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    for r in rows:
        assert set(SHAPE) <= set(r), r
        assert r["persona"] in impact.PERSONAS
        assert not str(r["entry_id"]).lower().startswith(("qa-", "verify-", "check-7-")) and r["job_id"] != "fixture"


# ----- AC-A1 the architecture route hands out the doc's diagrams --------------------------------------------------------
def test_the_architecture_route_returns_the_three_diagrams_of_the_doc(api: Api) -> None:
    status, doc = api.json("GET", "api/architecture")
    assert status == 200 and doc["doc"] == "docs/ARCHITECTURE.md"
    assert len(doc["diagrams"]) == 3
    assert all(d["title"] and d["source"].strip() for d in doc["diagrams"])


def test_the_architecture_route_is_404_when_the_doc_is_not_in_the_tree(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(architecture, "DOC", Path("docs") / "NO-SUCH-DOC.md")
    status, doc = api.json("GET", "api/architecture")
    assert status == 404 and "not in this copy" in doc["error"]


def test_diagrams_take_the_heading_above_each_block() -> None:
    text = "# T\n\n## One\n\n```mermaid\nflowchart LR\n  a --> b\n```\n\nprose\n\n## Two\n```mermaid\nsequenceDiagram\n  A->>B: hi\n```\n"
    assert architecture.diagrams(text) == [
        {"title": "One", "source": "flowchart LR\n  a --> b"}, {"title": "Two", "source": "sequenceDiagram\n  A->>B: hi"}]
