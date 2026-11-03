"""The focus route and what a new take says about it (TICKET-223 AC-1, AC-2). SEEDED data (history_all_support), no model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from history_all_support import CHEST, KNEE, REHAB, SQUAT, fault, put_take, seed
from history_support import OTHER, USER, World, world  # noqa: F401
from part7 import history_facts, history_focus, history_report, history_store
from support import Api

BASE = "api/me/history"
NEXT = "aaaaaaaaaa01"


def _json(api: Api, path: str, user: str | None = USER) -> tuple[int, Any]:
    headers = {"X-Test-User": user} if user else {}
    return api.json("GET", path, None, headers={**headers, "Origin": f"http://127.0.0.1:{api.port}"})


@pytest.fixture()
def served(api: Api, world: World) -> Api:  # noqa: F811
    world.opted_in.add(USER)
    seed(api.app.state, USER)  # squat takes 1, 2, 4 readable; 3 private
    return api


def _after_take(api: Api, faults: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    put_take(api.app.state, USER, SQUAT, "2026-11-02T10:00:00Z", 82, faults, job=NEXT, **kw)
    status, doc = _json(api, f"{BASE}/{SQUAT}/focus?job={NEXT}")
    assert status == 200
    return doc


def test_focus_is_the_owners_only(served: Api) -> None:  # AC-1
    assert _json(served, f"{BASE}/{SQUAT}/focus", user=None)[0] == 401
    assert _json(served, f"{BASE}/{SQUAT}/focus", user=OTHER)[0] == 404  # nothing of theirs, and not a catalog movement
    assert _json(served, f"{BASE}/{SQUAT}/focus?job={NEXT}", user=OTHER)[0] == 404
    status, doc = _json(served, f"{BASE}/lateral-raise/focus", user=OTHER)  # a catalog movement they have no takes of: an empty answer
    assert (status, doc) == (200, {"focus": None, "after": None})
    assert _json(served, f"{BASE}/Bad_Entry/focus")[0] == 404
    assert "Push the left knee out" not in str(_json(served, f"{BASE}/lateral-raise/focus", user=OTHER))


def test_focus_from_the_fact_table_names_take_second_and_date(served: Api) -> None:  # AC-1
    status, doc = _json(served, f"{BASE}/{SQUAT}/focus")
    focus = doc["focus"]
    assert status == 200 and doc["after"] is None
    assert (focus["source"], focus["cue"], focus["take"], focus["at_s"], focus["date"]) == ("fact_table", KNEE["cue"], 4, 2.1, "1 Nov")
    assert focus["cites"] == [{"take": 4, "at_s": 2.1}] and focus["label"] == "Worked out from your stored takes."
    assert (focus["measure"], focus["side"]) == ("knee_valgus", "left")


def test_focus_prefers_a_cached_report_that_stands(served: Api) -> None:  # AC-1
    state = served.app.state
    _, key, _ = history_report.runner_for(state, served.app.child.catalog_dir).plan(USER, SQUAT)
    item = {"text": "x", "measure": "trunk_lean_forward", "side": "center", "cue": CHEST["cue"], "cites": [{"take": 1, "at_s": 5.0}]}
    history_store.write_json(history_report.report_path(state, USER, SQUAT, key), {"format": history_report.FORMAT, "focus": item})
    focus = _json(served, f"{BASE}/{SQUAT}/focus")[1]["focus"]
    assert (focus["source"], focus["cue"], focus["take"], focus["date"], focus["label"]) == ("report", CHEST["cue"], 1, "5 Oct", "")
    for bad in ({**item, "cites": [{"take": 3, "at_s": 4.0}]},                      # take 3 is private: not read
                {**item, "cue": "Lift your toes"},                                   # not one of that take's cues
                {**item, "cites": [{"take": 9, "at_s": 5.0}]}, {**item, "cites": []}, {**item, "measure": "knee_valgus"}):
        history_store.write_json(history_report.report_path(state, USER, SQUAT, key), {"format": history_report.FORMAT, "focus": bad})
        assert _json(served, f"{BASE}/{SQUAT}/focus")[1]["focus"]["source"] == "fact_table", bad


def test_focus_needs_the_keeping_consent(served: Api, world: World) -> None:  # noqa: F811  # AC-1
    world.opted_in.discard(USER)
    assert _json(served, f"{BASE}/{SQUAT}/focus")[1] == {"focus": None, "after": None}
    assert _json(served, f"{BASE}/{SQUAT}/focus?job={NEXT}")[1] == {"focus": None, "after": None}


def test_focus_never_reads_private_or_rehab_takes(served: Api) -> None:  # AC-1
    state = served.app.state
    put_take(state, USER, SQUAT, "2026-11-03T10:00:00Z", 5, [fault(CHEST, 4.0)], private=True)
    put_take(state, USER, SQUAT, "2026-11-04T10:00:00Z", 5, [fault(CHEST, 4.5)], mode="rehab")
    focus = _json(served, f"{BASE}/{SQUAT}/focus")[1]["focus"]
    assert (focus["cue"], focus["take"]) == (KNEE["cue"], 4)  # the private and rehab takes after it are not the latest to read
    assert _json(served, f"{BASE}/{REHAB}/focus")[1] == {"focus": None, "after": None}  # a rehab-only movement carries nothing
    rehab_job = history_store.takes(state, USER, SQUAT)[-1]["job_id"]
    doc = _json(served, f"{BASE}/{SQUAT}/focus?job={rehab_job}")[1]
    assert doc["after"] is None and doc["focus"]["take"] == 4
    assert history_focus.focus({"takes": [], "latest": None}) is None


@pytest.mark.parametrize("size,change", [(14.0, "not_enough"), (16.9, "not_enough"), (11.0, "not_enough"), (10.9, "smaller"), (8.0, "smaller"), (17.1, "larger"), (25.0, "larger")])
def test_after_uses_the_noise_band(served: Api, size: float, change: str) -> None:  # AC-2
    doc = _after_take(served, [fault(KNEE, 2.4, size)])
    assert doc["focus"]["take"] == 4  # the focus is what the earlier takes carried, not the new take
    after = doc["after"]
    assert (after["came_up"], after["at_s"], after["change"], after["take"]) == (True, 2.4, change, 5)
    assert after["band"] == {"unit": "deg", "value": history_facts.NOISE_BAND["deg"]}


def test_after_says_gone_only_where_the_take_compared_the_moment(served: Api) -> None:  # AC-2
    after = _after_take(served, [])["after"]
    assert (after["came_up"], after["at_s"], after["change"]) == (False, None, None)


def test_after_cannot_tell_when_the_moment_was_not_compared(served: Api) -> None:  # AC-2
    state = served.app.state
    folder = history_store.take_dir(state, USER, SQUAT, NEXT)
    put_take(state, USER, SQUAT, "2026-11-02T10:00:00Z", 82, [], job=NEXT)
    analysis = history_store.read_json(folder / history_store.ANALYSIS_NAME)
    analysis["score"]["timeline"] = [{"t_s": [6.0, 9.0], "compared": True, "misses": []}]  # not around 2.1 s
    history_store.write_json(folder / history_store.ANALYSIS_NAME, analysis)
    after = _json(served, f"{BASE}/{SQUAT}/focus?job={NEXT}")[1]["after"]
    assert (after["came_up"], after["change"]) == (None, None)


def test_after_is_empty_for_another_section_or_mode(served: Api) -> None:  # AC-2
    assert _after_take(served, [fault(KNEE, 2.4, 14.0)], section_key="s1of3")["after"] is None


def test_after_ignores_a_job_that_is_not_the_owners(served: Api) -> None:  # AC-2
    put_take(served.app.state, OTHER, SQUAT, "2026-11-02T10:00:00Z", 82, [fault(KNEE, 2.4, 8.0)], job=NEXT)
    doc = _json(served, f"{BASE}/{SQUAT}/focus?job={NEXT}")[1]
    assert doc["after"] is None and doc["focus"]["take"] == 4
    assert _json(served, f"{BASE}/{SQUAT}/focus?job=not-a-job")[1]["after"] is None


def test_the_focus_doc_has_no_banned_shape(served: Api) -> None:  # AC-1
    text = str(_json(served, f"{BASE}/{SQUAT}/focus")[1]).lower()
    assert "streak" not in text and "ready" not in text and "private" not in text
    assert Path(history_focus.__file__).read_text(encoding="utf-8").count("—") == 0
