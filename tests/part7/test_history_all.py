"""Across my movements, the recap and the plan, without a model (TICKET-224 AC-1, AC-2, AC-5, AC-6; TICKET-223). SEEDED data."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from history_all_support import CHEST, DANCE, KNEE, SQUAT, fault, put_take, seed
from history_support import OTHER, USER
from part7 import history_all, history_facts, history_plan, history_recap, history_store


@pytest.fixture()
def state(tmp_path: Path) -> Path:
    seed(tmp_path, USER)
    return tmp_path


def _gather(state: Path, **kw):
    return history_all.gather(state, USER, lambda e: e.split("-")[0].title(), **kw)


def test_gather_never_reads_private_or_rehab_takes(state: Path) -> None:  # AC-2, AC-6
    found = {e["entry_id"]: e for e in _gather(state)}
    assert set(found) == {SQUAT, DANCE}  # the rehab-only movement has no readable take
    assert [t["take"] for t in found[SQUAT]["takes"]] == [1, 2, 4]  # take 3 is private: not read, number kept
    assert [t["take"] for t in found[SQUAT]["facts"]["takes"]] == [1, 2, 4]
    assert all("rehab" not in str(e["facts"]) for e in found.values())


def test_cross_table_joins_by_measure_and_side_within_each_movement(state: Path) -> None:  # AC-1
    table = history_all.cross_table(_gather(state))
    knee = next(r for r in table if r["measure"] == "knee_valgus")
    assert (knee["side"], knee["across"]) == ("left", 2)
    cells = {c["entry_id"]: c for c in knee["entries"]}
    assert cells[SQUAT]["status"] == "improved" and cells[SQUAT]["takes"] == [1, 2, 4]
    assert (cells[SQUAT]["first"]["magnitude"], cells[SQUAT]["last"]["magnitude"]) == (20.0, 14.0)
    assert cells[DANCE]["takes"] == [1, 2]
    assert [r["measure"] for r in history_all.across(table)] == ["knee_valgus"]  # chest is in one movement only
    assert table == history_all.cross_table(_gather(state))  # deterministic


def test_other_users_takes_are_not_merged(state: Path) -> None:  # AC-1
    put_take(state, OTHER, SQUAT, "2026-10-06T10:00:00Z", 55, [fault(CHEST, 1.0)])
    assert {e["entry_id"] for e in history_all.gather(state, OTHER, str)} == {SQUAT}
    assert "trunk_lean_forward" not in str(history_all.cross_table(_gather(state))[0]["entries"][0]).replace("measure", "")  # mine only
    assert len(history_all.cross_table(history_all.gather(state, OTHER, str))) == 1


def test_leave_one_out_is_saved_and_voids_cross_reports(state: Path) -> None:  # AC-2, AC-4
    folder = history_store.cross_dir(state, USER)
    history_store.write_json(folder / "all-x.json", {"takes": []})
    assert history_all.set_left_out(state, USER, [DANCE, DANCE]) == [DANCE]
    assert not (folder / "all-x.json").exists()
    shown = _gather(state)
    assert [e["left_out"] for e in shown] == [False, True] or {e["entry_id"]: e["left_out"] for e in shown} == {SQUAT: False, DANCE: True}
    assert [e["entry_id"] for e in history_all.included(shown)] == [SQUAT]
    assert history_all.cross_table(history_all.included(shown)) and not history_all.across(history_all.cross_table(history_all.included(shown)))
    for bad in ("x", [1], ["Bad Id"], None):
        with pytest.raises(ValueError):
            history_all.set_left_out(state, USER, bad)


def test_deleting_an_included_take_deletes_the_cross_report_and_forget_removes_all(state: Path) -> None:  # AC-4
    job = history_store.takes(state, USER, DANCE)[0]["job_id"]
    other = history_store.takes(state, USER, SQUAT)[0]["job_id"]
    folder = history_store.cross_dir(state, USER)
    history_store.write_json(folder / "all-k.json", {"takes": [{"job_id": job}, {"job_id": other}]})
    history_store.write_json(folder / "recap-2026-10.json", {"takes": [{"job_id": other}]})
    history_store.write_json(folder / "all-z.json", {"takes": []})
    assert history_store.drop_take(state, job) == 1
    assert sorted(p.name for p in folder.glob("*.json")) == ["all-z.json", "recap-2026-10.json"]
    history_store.forget(state, USER, SQUAT)  # forgetting a movement voids what read it
    assert [p.name for p in folder.glob("*.json")] == ["all-z.json"]
    history_all.set_left_out(state, USER, [DANCE])
    history_store.forget(state, USER)
    assert not history_store.user_dir(state, USER).exists()


def test_recap_counts_one_utc_month(state: Path) -> None:  # AC-5
    recap = history_recap.build(_gather(state), "2026-10")
    assert (recap["takes"], recap["days"]) == (4, 4)  # squats 5th and 20th, dance 10th and 25th; the private take is not here
    assert [m["entry_id"] for m in recap["movements"]] == [DANCE, SQUAT]
    assert recap["rehab_takes"] == 0 and recap["label"] == "October 2026"  # the rehab-only movement is not read
    assert [(r["entry_id"], r["take"], r["score"]) for r in recap["records"]] == [(SQUAT, 2, 75), (DANCE, 2, 70)]
    assert [(g["entry_id"], g["measure"], g["take"]) for g in recap["faults_gone"]] == [(SQUAT, "trunk_lean_forward", 2)]
    focus = recap["next_focus"]
    assert (focus["measure"], focus["side"], focus["movements"], focus["source"]) == ("knee_valgus", "left", 2, "fact_table")
    nov = history_recap.build(_gather(state), "2026-11")
    assert (nov["takes"], nov["days"], nov["records"][0]["score"]) == (1, 1, 80)  # 1 Nov 10:00 UTC is November


def test_recap_month_boundary_and_empty_month(state: Path) -> None:  # AC-5
    put_take(state, USER, SQUAT, "2026-10-31T23:59:59Z", 61, [])
    put_take(state, USER, SQUAT, "2026-11-01T00:00:00Z", 62, [])
    entries = _gather(state)
    assert history_recap.build(entries, "2026-10")["takes"] == 5 and history_recap.build(entries, "2026-11")["takes"] == 2
    empty = history_recap.build(entries, "2025-01")
    assert (empty["takes"], empty["days"], empty["records"], empty["faults_gone"], empty["next_focus"], empty["movements"]) == (0, 0, [], [], None, [])
    assert history_recap.previous_month("2026-01") == "2025-12" and history_recap.valid_month("2026-10") and not history_recap.valid_month("2026-13")


def test_recap_offer_at_the_start_of_a_month(state: Path) -> None:  # AC-5
    entries = _gather(state)
    day = lambda d: datetime(2026, 11, d, 9, 0, tzinfo=timezone.utc)  # noqa: E731
    offer = history_recap.offer(entries, day(3))
    assert offer == {"month": "2026-10", "label": "October 2026", "takes": 5 - 1}
    assert history_recap.offer(entries, day(8)) is None
    assert history_recap.default_month(entries, day(3)) == "2026-10" and history_recap.default_month(entries, day(20)) == "2026-11"
    assert history_recap.offer(entries, datetime(2027, 3, 2, tzinfo=timezone.utc)) is None  # last month has no takes


def test_rehab_shows_only_as_a_count(state: Path) -> None:  # AC-6
    put_take(state, USER, SQUAT, "2026-10-15T10:00:00Z", 70, [fault(KNEE, 2.0)], mode="rehab")
    squat = next(e for e in _gather(state) if e["entry_id"] == SQUAT)
    assert squat["rehab_takes"] == 1 and all(t["mode"] != "rehab" for t in squat["takes"])
    recap = history_recap.build(_gather(state), "2026-10")
    assert recap["rehab_takes"] == 1 and (recap["takes"], len(recap["records"])) == (4, 2)  # counted, and nothing else changed


def _facts(state: Path, entry: str = SQUAT) -> dict:
    return history_facts.build(history_all.readable(history_store.takes(state, USER, entry)), entry)


def test_plan_items_come_from_what_simon_has_and_cite_evidence(state: Path) -> None:  # TICKET-223 AC-3
    plan = history_plan.build(_facts(state))
    assert plan and [i["kind"] for i in plan["items"]] == ["cue", "takes"]  # a whole-movement group: no section, no speed
    cue, takes = plan["items"]
    assert cue["cue"] == KNEE["cue"] and cue["cites"] == [{"take": 4, "at_s": 2.1}]
    assert takes["takes"] == 2 and takes["cites"] == cue["cites"]
    assert "come back tomorrow" in plan["spacing"].lower() and plan["based_on"]["take"] == 4
    assert "streak" not in str(plan).lower() and "ready" not in str(plan).lower()


def test_plan_with_a_section_names_the_ladder_step_and_speed(state: Path) -> None:  # TICKET-223 AC-3
    put_take(state, USER, "move-dddddddd", "2026-10-01T10:00:00Z", 60, [fault(KNEE, 2.0)], mode="dance", section_key="s2of4@0.75")
    put_take(state, USER, "move-dddddddd", "2026-10-02T10:00:00Z", 62, [fault(KNEE, 2.0)], mode="dance", section_key="s2of4@0.75")
    plan = history_plan.build(_facts(state, "move-dddddddd"))
    assert [i["kind"] for i in plan["items"]] == ["cue", "section", "speed", "takes"]
    section, speed = plan["items"][1], plan["items"][2]
    assert (section["section_key"], section["step"], speed["speed"]) == ("s2of4@0.75", "s2@slow", 0.75)
    assert history_plan.step_of("s1-3of4") == "j1-3" and history_plan.step_of("s3of4") == "s3@full" and history_plan.step_of("full") is None


def test_plan_guard_drops_what_the_data_does_not_back(state: Path) -> None:  # TICKET-223 AC-3
    facts = _facts(state)
    base = history_plan._candidate(facts)
    cue = base["items"][0]
    bad = [
        {**cue, "cue": "Squeeze your glutes"},                                   # not one of the student's cues
        {**cue, "cites": [{"take": 3, "at_s": 2.1}]},                            # a private take, not in the input
        {**cue, "cites": [{"take": 4, "at_s": 99}]},                             # outside the take
        {**cue, "cites": [{"take": 4, "at_s": 8.0}]},                            # not where the fault was measured
        {**cue, "text": "Work on the right knee cue: “Push the left knee out”."},  # side word of another fault
        {**cue, "text": "Your knee pain is back."},                              # health word
        {**cue, "text": "Work on the cue 12 times."},                            # an invented number
        {"kind": "section", "section_key": "s9of9", "step": "s9@full", "cites": cue["cites"], "text": "Practise section 9 of 9."},
        {"kind": "speed", "speed": 0.3, "cites": cue["cites"], "text": "Go at 0.3 speed."},
        {"kind": "speed", "speed": 1.0, "cites": cue["cites"], "text": "Go at 1 speed."},
        {"kind": "takes", "takes": 9, "cites": cue["cites"], "text": "Record 9 takes."},
        {"kind": "load", "cites": cue["cites"], "text": "Add weight."},
    ]
    for item in bad:
        plan, rejected = history_plan.check({**base, "items": [cue, item]}, facts)
        assert [i["kind"] for i in plan["items"]] == ["cue"] and len(rejected) == 1, item
    none, rejected = history_plan.check({**base, "items": [bad[0]]}, facts)
    assert none is None and rejected  # without a valid cue there is no plan
    streak, _ = history_plan.check({**base, "spacing": "Keep your streak going, you are ready."}, facts)
    assert streak["spacing"] == history_plan.SPACING


def test_plan_has_nothing_for_rehab_private_or_a_clean_take(state: Path) -> None:  # TICKET-223 AC-5
    put_take(state, USER, "rehab-eeeeeeee", "2026-10-01T10:00:00Z", 60, [fault(KNEE, 2.0)], mode="rehab")
    facts = history_facts.build(history_store.takes(state, USER, "rehab-eeeeeeee"), "rehab-eeeeeeee")
    assert history_plan.build(facts) is None
    put_take(state, USER, "clean-ffffffff", "2026-10-01T10:00:00Z", 99, [])
    assert history_plan.build(history_facts.build(history_store.takes(state, USER, "clean-ffffffff"), "clean-ffffffff")) is None
    put_take(state, USER, "priv-99999999", "2026-10-01T10:00:00Z", 60, [fault(KNEE, 2.0)], private=True)
    assert history_plan.build(history_facts.build(history_store.takes(state, USER, "priv-99999999"), "priv-99999999")) is None


def test_plan_never_uses_a_chest_cue_for_a_knee_fault(state: Path) -> None:
    put_take(state, USER, "mix-77777777", "2026-10-01T10:00:00Z", 60, [fault(CHEST, 2.0, 30.0)])
    plan = history_plan.build(history_facts.build(history_store.takes(state, USER, "mix-77777777"), "mix-77777777"))
    assert plan["items"][0]["measure"] == "trunk_lean_forward" and "Keep your chest up" in plan["items"][0]["text"]
