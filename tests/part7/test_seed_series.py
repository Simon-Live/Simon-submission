"""TICKET-218: the seeded demo history shows the series (it is one score scale, so the 2026-10-30 rescale never splits it)."""

from __future__ import annotations

from pathlib import Path

from part7 import history_facts, history_store
from test_seed_history import seed_history, seeded  # noqa: F401


def test_the_seeded_history_is_one_score_scale_so_the_demo_series_shows(seeded: tuple[Path, dict[str, str]]) -> None:  # noqa: F811
    state, users = seeded
    ada = users[seed_history.DEMO_EMAILS[0]]
    takes = history_store.takes(state, ada, seed_history.SQUAT)
    assert {t["score_version"].split(":")[0] for t in takes} == {seed_history.SEED_SCORE_VERSION}   # not a real v1 score
    series = history_facts.build(takes, seed_history.SQUAT)["series"]
    assert series["hidden"] is False and len(series["takes"]) >= 4                                   # enough comparable takes
    assert {m["measure"] for m in series["measures"]} == {"trunk_lean_forward", "knee_valgus"}      # one chart for each planted difference
