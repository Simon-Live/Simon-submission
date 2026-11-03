"""TICKET-211: the staging-only seed of synthetic demo histories (tools/seed_history.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from part7 import history_all, history_facts, history_plan, history_recap, history_routes, history_store, identity

SPEC = importlib.util.spec_from_file_location("seed_history", Path(__file__).resolve().parents[2] / "tools" / "seed_history.py")
seed_history = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seed_history)  # type: ignore[union-attr]


@pytest.fixture()
def seeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, str]]:
    monkeypatch.setenv("SIMON7_STAGING", "1")
    seed_history.seed(tmp_path, clips=False)
    store = identity.IdentityStore(tmp_path, seed_history.auth._pepper(tmp_path))
    return tmp_path, {e: store._user_for(e, 1.0) for e in seed_history.DEMO_EMAILS}


def test_it_refuses_without_the_staging_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-3
    monkeypatch.delenv("SIMON7_STAGING", raising=False)
    with pytest.raises(seed_history.SeedError):
        seed_history.seed(tmp_path, clips=False)
    assert not (tmp_path / "history").exists() and seed_history.main(["--state", str(tmp_path)]) == 2


def test_it_refuses_an_address_outside_the_allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-3
    monkeypatch.setenv("SIMON7_STAGING", "1")
    with pytest.raises(seed_history.SeedError):
        seed_history.seed(tmp_path, clips=False, emails=("real.person@gmail.com",))
    assert not (tmp_path / "history").exists()


def test_every_seeded_copy_is_marked_and_the_volume_is_enough(seeded: tuple[Path, dict[str, str]]) -> None:  # AC-1, AC-2
    state, users = seeded
    ada = users[seed_history.DEMO_EMAILS[0]]
    assert history_store.entries(state, ada) == sorted([seed_history.SQUAT, seed_history.LUNGE, seed_history.PRESS])
    counts = {e: len(history_store.takes(state, ada, e)) for e in history_store.entries(state, ada)}
    assert all(10 <= n <= 30 for n in counts.values()), counts
    every = [t for e in history_store.entries(state, ada) for t in history_store.takes(state, ada, e)]
    assert every and all(t["synthetic"] for t in every)
    ben = history_store.takes(state, users[seed_history.DEMO_EMAILS[1]], seed_history.SQUAT)
    assert len(ben) == 3 and history_store.retention_opt_in(state, ada)


def test_the_public_take_says_seeded(seeded: tuple[Path, dict[str, str]]) -> None:  # AC-2
    state, users = seeded
    found = history_store.takes(state, users[seed_history.DEMO_EMAILS[0]], seed_history.SQUAT)
    facts = history_facts.build(found, seed_history.SQUAT)
    assert all(history_routes._public_take(seed_history.SQUAT, t, r)["synthetic"] for t, r in zip(found, facts["takes"]))


def test_the_planted_cases_show_in_the_fact_table(seeded: tuple[Path, dict[str, str]]) -> None:  # AC-SD-1
    state, users = seeded
    found = history_store.takes(state, users[seed_history.DEMO_EMAILS[0]], seed_history.SQUAT)
    facts = history_facts.build(found, seed_history.SQUAT)
    assert facts["group"] == {"section": "full", "mode": "fitness"}
    assert [t["mode"] for t in found].count("dance") == 2 and any(t["section_key"] == "s2of4" for t in found) and any(t["private"] for t in found)
    by = {(m["measure"], m["side"]): m for m in facts["measures"]}
    knee, lean = by[("knee_valgus", "left")], by[("trunk_lean_forward", "center")]
    assert knee["status"] == "fixed" and knee["still_close"]["take"] == facts["latest"]   # fixed, back, fixed again, still close
    assert lean["status"] == "improved"
    assert not facts["takes"][6]["in_group"] and not facts["takes"][11]["in_group"]


def test_the_latest_press_takes_are_a_section_so_practise_this_section_shows(seeded: tuple[Path, dict[str, str]]) -> None:  # AC-SD-9
    state, users = seeded
    ada = users[seed_history.DEMO_EMAILS[0]]
    found = history_store.takes(state, ada, seed_history.PRESS)
    assert [t["section_key"] for t in found][-3:] == ["s2of4"] * 3 and found[-4]["section_key"] == "full"
    facts = history_facts.build(found, seed_history.PRESS)
    assert facts["group"] == {"section": "s2of4", "mode": "fitness"}
    plan = history_plan.build(facts)
    assert plan is not None and any(i["kind"] == "section" and i["step"] == "s2@full" for i in plan["items"])
    squat = history_facts.build(history_store.takes(state, ada, seed_history.SQUAT), seed_history.SQUAT)  # negative: the squat offers none
    assert not any(i["kind"] == "section" for i in (history_plan.build(squat) or {"items": []})["items"])


def test_a_rehab_take_is_counted_in_the_recap_and_never_read(seeded: tuple[Path, dict[str, str]]) -> None:  # AC-SD-10
    state, users = seeded
    ada = users[seed_history.DEMO_EMAILS[0]]
    rehab = [t for e in history_store.entries(state, ada) for t in history_store.takes(state, ada, e) if t["mode"] == "rehab"]
    assert len(rehab) == 1 and rehab[0]["synthetic"] and rehab[0]["entry_id"] == seed_history.LUNGE
    read = history_all.gather(state, ada, lambda e: e)
    assert sum(e["rehab_takes"] for e in read) == 1
    assert all(t["mode"] != "rehab" for e in read for t in history_all.readable(history_store.takes(state, ada, e["entry_id"])))  # negative
    month = history_recap.month_of(rehab[0]["at"])
    assert history_recap.build(read, month)["rehab_takes"] == 1


def test_the_lunge_and_the_press_show_the_other_states(seeded: tuple[Path, dict[str, str]]) -> None:
    state, users = seeded
    ada = users[seed_history.DEMO_EMAILS[0]]
    lunge = history_facts.build(history_store.takes(state, ada, seed_history.LUNGE), seed_history.LUNGE)
    assert lunge["measures"][0]["status"] == "fixed" and lunge["measures"][0].get("still_close")
    press = history_facts.build(history_store.takes(state, ada, seed_history.PRESS), seed_history.PRESS)
    assert press["measures"][0]["status"] == "persistent" and press["measures"][0]["first"]["unit"] == "m"
    ben = history_facts.build(history_store.takes(state, users[seed_history.DEMO_EMAILS[1]], seed_history.SQUAT), seed_history.SQUAT)
    assert ben["measures"][0]["status"] == "fixed"


def test_seeded_analyses_keep_part_5s_structure(seeded: tuple[Path, dict[str, Any]]) -> None:  # AC-5
    state, users = seeded
    take = history_store.takes(state, users[seed_history.DEMO_EMAILS[0]], seed_history.SQUAT)[0]
    doc = history_store.read_json(take["analysis"])
    template = history_store.read_json(seed_history.TEMPLATE)
    assert doc["format"] == template["format"] and doc["schema_version"] == template["schema_version"]
    assert doc["score"]["params_sha256"] == template["score"]["params_sha256"] and doc["seed_edit"] == seed_history.SEED_EDIT


def test_forget_removes_the_seeded_copies_like_any_copy(seeded: tuple[Path, dict[str, str]]) -> None:  # AC-4
    state, users = seeded
    ada = users[seed_history.DEMO_EMAILS[0]]
    assert history_store.forget(state, ada) > 0
    assert history_store.entries(state, ada) == []
    assert history_store.entries(state, users[seed_history.DEMO_EMAILS[1]])  # another account is untouched


def test_ada_has_one_measure_shared_by_squat_and_lunge_so_the_cross_table_is_not_empty(seeded: tuple[Path, dict[str, str]]) -> None:  # AC-SD-11
    state, users = seeded
    read = history_all.included(history_all.gather(state, users[seed_history.DEMO_EMAILS[0]], str))
    shared = history_all.across(history_all.cross_table(read))
    assert [(r["measure"], r["side"]) for r in shared] == [seed_history.KNEE]
    assert {c["entry_id"] for c in shared[0]["entries"]} == {seed_history.SQUAT, seed_history.LUNGE}
    assert history_all.blocker(read) is None
    ben = history_all.included(history_all.gather(state, users[seed_history.DEMO_EMAILS[1]], str))
    assert len(ben) == 1  # negative: ben has one movement, so nothing is shared


def test_seeded_movements_outside_the_catalog_get_display_names(seeded: tuple[Path, dict[str, str]]) -> None:  # AC-SD-12
    from part7 import labels
    state, _ = seeded
    doc = history_store.read_json(state / labels.SEEDED_NAMES)
    assert doc["synthetic"] is True and doc["names"] == {seed_history.LUNGE: "Lunge", seed_history.PRESS: "Shoulder press"}

    class NoCatalog:
        def get_entry(self, _: str) -> None:
            return None

    assert labels.entry_name(NoCatalog(), seed_history.LUNGE, state) == "Lunge"
    assert labels.entry_name(NoCatalog(), seed_history.LUNGE) == seed_history.LUNGE  # no state: the id
    assert labels.entry_name(NoCatalog(), "other-entry", state) == "other-entry"  # only seeded entries


def test_a_catalog_name_shows_with_a_capital_first_letter(tmp_path: Path) -> None:  # AC-SD-12
    from part7 import labels

    class Catalog:
        def get_entry(self, _: str) -> dict[str, str]:
            return {"name": "body squat"}

    assert labels.entry_name(Catalog(), "body-squat-19b06562", tmp_path) == "Body squat"


def test_one_seeded_squat_take_is_fault_capped_so_the_hollow_dot_data_is_present(seeded: tuple[Path, dict[str, str]]) -> None:  # AC-SD-13
    state, users = seeded
    found = history_store.takes(state, users[seed_history.DEMO_EMAILS[0]], seed_history.SQUAT)
    facts = history_facts.build(found, seed_history.SQUAT)
    capped = [row for row in facts["takes"] if row["uncapped"]]
    assert len(capped) == 1                                                     # only that take; the others stay uncapped (negative)
    assert capped[0]["uncapped"] == {"value": 94, "grade": "A", "fault_cap": 89}
    assert capped[0]["score"] == 89 and capped[0]["in_group"]                   # the dot sits above a point on the line


def test_demo_ada_has_one_seeded_answered_trainer_note_that_the_patterns_receipt_counts(seeded: tuple[Path, dict[str, str]]) -> None:  # AC-SD-14
    from part7 import history_longpack, history_patterns_job, notes

    state, users = seeded
    ada, ben = users[seed_history.DEMO_EMAILS[0]], users[seed_history.DEMO_EMAILS[1]]
    got = notes.notes_for(state, ada, seed_history.SQUAT)
    assert len(got) == 1 and got[0]["matched_fault"] == "trunk_lean_forward center" and got[0]["at_s"] == seed_history.NOTE_AT_S
    assert got[0]["note"].startswith("Seeded demo note") and got[0]["job_id"] == seed_history.job_id_for(seed_history.DEMO_EMAILS[0], seed_history.SQUAT, seed_history.NOTE_TAKE)
    rows = history_patterns_job.PatternRunner(state).plan(ada, seed_history.SQUAT)[0]
    assert len(history_longpack.owner_notes(state, ada, seed_history.SQUAT, rows)) == 1  # "1 trainer note" on the receipt
    assert notes.notes_for(state, ben, seed_history.SQUAT) == []  # negative: the other demo account got none
    seed_history.seed(state)  # run again: the same note, not a second one
    assert len(notes.notes_for(state, ada, seed_history.SQUAT)) == 1


def test_the_seeded_note_sits_on_a_take_the_comparison_report_and_ask_both_send(seeded: tuple[Path, dict[str, str]]) -> None:  # AC-SD-14
    from part7 import history_ask, history_longpack, history_report

    state, users = seeded
    ada, ben = users[seed_history.DEMO_EMAILS[0]], users[seed_history.DEMO_EMAILS[1]]
    runner = history_report.Runner(state)
    usable, _, narration = runner.plan(ada, seed_history.SQUAT)
    notes = history_longpack.owner_notes(state, ada, seed_history.SQUAT, usable)
    assert len(notes) == 1
    packed = runner.packed(seed_history.SQUAT, usable, history_facts.build(usable, seed_history.SQUAT), narration, False, notes)
    texts = [c["text"] for c in packed["content"] if c["type"] == "text"]
    at = next(i for i, text in enumerate(texts) if text.startswith(f"Trainer notes on take {seed_history.NOTE_TAKE} of"))
    assert texts[at - 1].startswith(f"Take {seed_history.NOTE_TAKE} digest") and packed["manifest"]["notes_sent"] == 1  # the note follows a take that is sent
    assert history_ask.pack(history_ask.gather(state, ada, str), "what changed?")["manifest"]["notes_sent"] == 1
    other = history_report.Runner(state).plan(ben, seed_history.SQUAT)[0]
    assert history_longpack.owner_notes(state, ben, seed_history.SQUAT, other) == []  # negative: ben has none
