"""TICKET-206 (a): a history take records its section, mode and score version; old records read as unknown."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from history_support import ENTRY, SECOND, USER, World, job_record, seed_job, world  # noqa: F401
from part7 import history_store

SECTION = {"start_ms": 2000, "end_ms": 5000, "index": 2, "count": 4}


@pytest.mark.parametrize("section, key", [
    (None, "full"), (SECTION, "s2of4"), ({**SECTION, "first": 1}, "s1-2of4"), ({**SECTION, "first": 2}, "s2of4"),
    ({**SECTION, "speed": 0.5}, "s2of4@0.5"), ({**SECTION, "speed": 1}, "s2of4"), ("junk", None), ({"index": 2}, None),
])
def test_section_key(section, key) -> None:
    assert history_store.section_key(section) == key


def test_mode_of_prefers_the_choice_then_the_profile_then_fitness() -> None:
    assert history_store.mode_of({"mode": "dance"}, {"profile": "rehab"}) == "dance"
    assert history_store.mode_of({}, {"profile": "rehab"}) == "rehab"
    assert history_store.mode_of({"mode": "bogus"}, {"profile": "bogus"}) == "fitness"
    assert history_store.mode_of({}, None) == "fitness"


def test_score_version() -> None:
    assert history_store.score_version({"score": {"version": "simon.score.v1", "params_sha256": "abcdef0123456789"}}) == "simon.score.v1:abcdef01"
    assert history_store.score_version({"score": {"version": "simon.score.v1"}}) == "simon.score.v1"
    assert history_store.score_version({"score": {}}) is None and history_store.score_version(None) is None


def test_a_recorded_take_keeps_section_mode_and_version(tmp_path: Path, world: World) -> None:  # noqa: F811
    world.opted_in.add(USER)
    folder = seed_job(tmp_path, SECOND, section=SECTION, mode="dance")
    world.owners[SECOND] = USER
    assert history_store.record_take(tmp_path, job_record(tmp_path, SECOND), folder)
    meta = json.loads((tmp_path / "history" / USER / ENTRY / "takes" / SECOND / "meta.json").read_text())
    assert (meta["section_key"], meta["mode"]) == ("s2of4", "dance") and meta["score_version"].startswith("simon.score.v1:")
    (take,) = history_store.takes(tmp_path, USER, ENTRY)
    assert (take["section_key"], take["mode"], take["score_version"]) == ("s2of4", "dance", meta["score_version"])


def test_a_record_made_before_the_fields_existed_is_unknown(tmp_path: Path, world: World) -> None:  # noqa: F811
    world.opted_in.add(USER)
    folder = seed_job(tmp_path, SECOND)
    world.owners[SECOND] = USER
    assert history_store.record_take(tmp_path, job_record(tmp_path, SECOND), folder)
    path = tmp_path / "history" / USER / ENTRY / "takes" / SECOND / "meta.json"
    meta = json.loads(path.read_text())
    for field in ("section_key", "mode", "score_version"):
        del meta[field]
    path.write_text(json.dumps(meta))
    (take,) = history_store.takes(tmp_path, USER, ENTRY)
    assert (take["section_key"], take["mode"], take["score_version"]) == (None, None, None)
    path.write_text(json.dumps({**meta, "mode": "bogus", "section_key": 7}))
    (take,) = history_store.takes(tmp_path, USER, ENTRY)
    assert (take["section_key"], take["mode"]) == (None, None)
