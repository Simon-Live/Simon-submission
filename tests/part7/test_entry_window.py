"""Re-verification W-N1 (docs/specs/prod-data.md): no movement is shown to anyone else between Part 6 saving it and
its access row being decided. The chain writes the held-back row before Part 6 is asked to save (`Link.reserve`,
Part 6 `import --id`), and a movement without a row is shown only when it is a sample Part 6 ships. Review S-R5: a
`ready` that comes before the row is complete still publishes it, by `release`'s rules.

The chain runs for real on the trainer harness's fake parts (test_trainer_chain_and_harness.seams); the fake import
asks the visibility rule at the moment Part 6 would list the movement."""

from __future__ import annotations

import json
from pathlib import Path
import types
from typing import Any

import pytest

from part7 import auth, chain, entry_access, processor, resume
from part7.parts import p6_catalog
from support import make_lock
from test_trainer_chain_and_harness import seams, step  # noqa: F401  seams is a fixture

OWNER = "u-0123456789abcdef01234567"
JOB = "abcdef012345"


def _saving(seen: dict[str, Any], state: Path, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace the fake import with one that saves under the asked id, as Part 6 `import --id` does, and records
    what a stranger could see at that moment."""
    window: list[dict[str, Any]] = []

    def import_entry(catalog: Path, folder: Path, name: str, *a: Any, entry_id: str | None = None, **k: Any):
        made = entry_id or "made-by-part6-0a1b2c3d"
        (Path(catalog) / made).mkdir(parents=True, exist_ok=True)
        (Path(catalog) / made / "manifest.json").write_text(json.dumps({"id": made, "files_source": "import"}))
        window.append({"id": made, "asked": entry_id, "row": entry_access.get(state, made),
                       "stranger": entry_access.visible(state, made, None, None, catalog)})
        return (step(6), {"id": made, "files_source": "import"})

    monkeypatch.setattr(p6_catalog, "import_entry", import_entry)
    return window


def _take(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, published: bool, band: str = "") -> tuple[
        dict[str, Any], list[dict[str, Any]], list[bool], Path]:
    """One trainer job through `processor.trainer_job` with the submit's deferred link; returns its result, the save
    window, what a stranger saw during the captions step, and the state folder."""
    state, catalog = tmp_path / "state", tmp_path / "catalog"
    if band:
        (state / "jobs" / JOB).mkdir(parents=True)
        (state / "jobs" / JOB / "job.json").write_text(json.dumps({"consent": {"age_band": band}}))
    window = _saving({}, state, monkeypatch)
    during: list[bool] = []
    link = entry_access.Link(state, OWNER, published, deferred=True)
    link.job(JOB)
    on_entry = auth.owned_entry(types.SimpleNamespace(state=state), None, None, link=link)
    monkeypatch.setattr(processor.people, "prepare_clip", lambda ctx, raw, trim, name: raw)
    monkeypatch.setattr(processor.narration, "attach", lambda raw, entry_dir, **k: during.append(
        entry_access.visible(state, Path(entry_dir).name, None, None, catalog)))
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"mp4")
    ctx = types.SimpleNamespace(work=tmp_path / "work", id=JOB, set_stage=lambda s: None, add_note=lambda n: None,
                                set_fields=lambda **f: None)
    fn = processor.trainer_job(raw, name="My move", category="exercise", catalog=catalog, on_entry=on_entry,
                               lock=make_lock())
    return fn(ctx), window, during, state


@pytest.mark.parametrize(("case", "published", "band", "shown"), [
    ("private", False, "", False), ("opted public", True, "adult", True), ("13 to 17, public asked", True, "minor", False),
])
def test_no_stranger_sees_a_movement_while_it_is_saved(
    tmp_path: Path, seams: dict[str, Any], monkeypatch: pytest.MonkeyPatch, case: str, published: bool, band: str,
    shown: bool,
) -> None:
    result, window, during, state = _take(tmp_path, monkeypatch, published, band)
    entry = result["entry_id"]
    assert [w["asked"] for w in window] == [entry] and entry.startswith("my-move-"), "Part 6 saves under the reserved id"
    assert window[0]["row"] is not None and window[0]["row"]["published"] is False, case
    assert window[0]["stranger"] is False and during == [False], f"{case}: seen while it was saved or captioned"
    assert entry_access.visible(state, entry, None, None, tmp_path / "catalog") is shown, case
    assert entry_access.visible(state, entry, OWNER, None, tmp_path / "catalog") is True, "its owner always sees it"


def test_without_a_row_only_a_shipped_sample_is_shown(tmp_path: Path) -> None:
    state, catalog = tmp_path / "state", tmp_path / "catalog"
    for entry, source in (("squat", "fixture"), ("made-before-0a1b2c3d", "import")):
        (catalog / entry).mkdir(parents=True)
        (catalog / entry / "manifest.json").write_text(json.dumps({"id": entry, "files_source": source}))
    assert entry_access.visible(state, "squat", None, None, catalog) is True  # Part 6's seeded samples stay visible
    assert entry_access.visible(state, "made-before-0a1b2c3d", None, None, catalog) is False
    assert entry_access.visible(state, "squat", None, None) is False, "without the catalog nothing proves it a sample"
    assert entry_access.visible(state, "../squat", None, None, catalog) is False


def test_a_row_that_cannot_be_written_stops_the_save(tmp_path: Path, seams: dict[str, Any]) -> None:
    def reserve(entry_id: str) -> Any:
        raise OSError("disk full")

    video = tmp_path / "video.mp4"
    video.write_bytes(b"mp4")
    res = chain.trainer(video, tmp_path / "w", lock=make_lock(), catalog=tmp_path / "cat", name="Lateral raise",
                        reserve=reserve)
    assert res["ok"] is False and res["stage"] == "catalog" and seams["import"] == [], "saved with no row"


def test_a_failed_save_drops_its_reserved_row(tmp_path: Path, seams: dict[str, Any]) -> None:
    seams["import_exit"] = 1
    link = entry_access.Link(tmp_path / "state", OWNER, True, deferred=True)
    video = tmp_path / "video.mp4"
    video.write_bytes(b"mp4")
    res = chain.trainer(video, tmp_path / "w", lock=make_lock(), catalog=tmp_path / "cat", name="Lateral raise",
                        reserve=link.reserve)
    assert res["ok"] is False and entry_access.rows(tmp_path / "state") == []


def test_the_reserved_id_has_part6s_form(tmp_path: Path) -> None:
    found = p6_catalog.new_id(tmp_path, "Côté Squat!")
    assert found.startswith("c-t-squat-") and len(found.rsplit("-", 1)[1]) == 8
    assert p6_catalog.new_id(tmp_path, "???").startswith("movement-")


def test_sr5_ready_before_the_job_id_still_publishes(tmp_path: Path) -> None:
    link = entry_access.Link(tmp_path, OWNER, True, deferred=True)
    link.reserve("early-move-0a1b2c3d")
    link.saved("early-move-0a1b2c3d")
    link.ready()
    link.job(JOB)  # the queue's id comes last
    assert entry_access.get(tmp_path, "early-move-0a1b2c3d")["published"] is True
    assert entry_access.get(tmp_path, "early-move-0a1b2c3d")["trainer_job"] == JOB


def test_sr5_ready_before_the_row_exists_publishes_when_it_is_written(tmp_path: Path) -> None:
    link = entry_access.Link(tmp_path, OWNER, True, deferred=True)
    link.ready()  # nothing to publish yet
    link.saved("late-row-0a1b2c3d")
    assert entry_access.get(tmp_path, "late-row-0a1b2c3d")["published"] is False, "no job id yet: its age answer is unknown"
    link.job(JOB)
    assert entry_access.get(tmp_path, "late-row-0a1b2c3d")["published"] is True


def test_sr5_an_early_ready_never_publishes_a_13_to_17_movement(tmp_path: Path) -> None:
    (tmp_path / "jobs" / JOB).mkdir(parents=True)
    (tmp_path / "jobs" / JOB / "job.json").write_text(json.dumps({"consent": {"age_band": "minor"}}))
    link = entry_access.Link(tmp_path, OWNER, True, deferred=True)
    link.saved("young-move-0a1b2c3d")
    link.ready()
    assert entry_access.visible(tmp_path, "young-move-0a1b2c3d", None, None) is False, "published before its band was read"
    link.job(JOB)  # the band arrives with the job id
    assert entry_access.get(tmp_path, "young-move-0a1b2c3d")["published"] is False
    assert entry_access.visible(tmp_path, "young-move-0a1b2c3d", None, None) is False
    off = entry_access.Link(tmp_path, OWNER, False, deferred=True)
    off.ready()
    off.saved("no-opt-in-0a1b2c3d")
    assert entry_access.get(tmp_path, "no-opt-in-0a1b2c3d")["published"] is False


def test_a_resumed_trainer_job_reserves_its_row_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    got: dict[str, Any] = {}
    monkeypatch.setattr(resume.processor, "trainer_job", lambda raw, **kw: got.update(kw) or (lambda ctx: None))
    monkeypatch.setattr(resume.run_on, "resume_bind", lambda fn, *a: fn)
    app = types.SimpleNamespace(state=tmp_path, child=types.SimpleNamespace(catalog_dir=tmp_path / "catalog"),
                                lock=make_lock(), backend="cpu")
    resume._trainer(app, {"id": JOB}, {"name": "Again", "category": "exercise", "public": True}, tmp_path / "raw.mp4", None)
    got["on_entry"].reserve("again-0a1b2c3d")
    assert entry_access.get(tmp_path, "again-0a1b2c3d")["published"] is False  # held back until its captions step
    got["on_entry"].ready()
    assert entry_access.get(tmp_path, "again-0a1b2c3d")["published"] is True


def test_residual2_undo_drops_only_this_takes_own_row(tmp_path: Path) -> None:
    mine = entry_access.Link(tmp_path, OWNER, True, deferred=True)
    mine.job(JOB)
    undo = mine.reserve("shared-id-0a1b2c3d")
    entry_access.drop(tmp_path, "shared-id-0a1b2c3d")  # meanwhile another take's row came to hold the id
    entry_access.record(tmp_path, "shared-id-0a1b2c3d", trainer_job="999999999999", owner="u-someone", published=True,
                        age_band="adult")
    undo()
    assert entry_access.get(tmp_path, "shared-id-0a1b2c3d")["owner"] == "u-someone", "another take's row was dropped"
    entry_access.drop(tmp_path, "shared-id-0a1b2c3d")
    mine.reserve("shared-id-0a1b2c3d")()
    assert entry_access.get(tmp_path, "shared-id-0a1b2c3d") is None, "its own reserved row stays after a failed save"


def test_residual3_the_sweep_leaves_a_row_reserved_while_part6_saves(tmp_path: Path) -> None:
    from part7 import config, delete_routes

    app = types.SimpleNamespace(state=tmp_path / "state", child=types.SimpleNamespace(catalog_dir=tmp_path / "catalog"))
    link = entry_access.Link(app.state, OWNER, False, deferred=True)
    link.job(JOB)
    link.reserve("saving-now-0a1b2c3d")  # no catalog folder yet: Part 6 is still saving
    made = entry_access.get(app.state, "saving-now-0a1b2c3d")["created_at"]
    assert delete_routes.sweep_entries(app, now=made + 1) == 0
    assert entry_access.get(app.state, "saving-now-0a1b2c3d") is not None, "a reserved row swept during the save"
    delete_routes.sweep_entries(app, now=made + config.TIMEOUTS["6"] + 1)
    assert entry_access.get(app.state, "saving-now-0a1b2c3d") is None, "an old row whose folder never came stays"
