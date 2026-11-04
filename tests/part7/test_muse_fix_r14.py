"""Release 14: the target follows the cue, the check looks at the whole person, the switch (docs/specs/muse-fix.md). Fakes only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from part7 import muse_fix, muse_fix_geom as geom, muse_fix_sanity as sane
from test_muse_fix import Fake, body, build_job, drawing_on, fake_compositor, ledger_rows, measurer_at  # noqa: F401  (the two autouse fixtures)


def set_fault(job: Path, **fields: Any) -> None:
    path = job / "work" / "follower" / "analysis.json"
    doc = json.loads(path.read_text())
    doc["faults"][0].update(fields)
    path.write_text(json.dumps(doc))


def broken(name: str, **at: float) -> dict[str, Any]:
    joints = body(150.0)
    joints[name].update(at)
    return joints


def test_the_cue_says_which_way_the_angle_goes() -> None:
    # job 4d2477ec7656: upper_arm_out, direction more ("Keep your left arm closer in"): the shoulder angle must close
    assert geom.wanted_move("upper_arm_out", "more") == -1 and geom.wanted_move("upper_arm_out", "less") == 1
    assert geom.wanted_move("knee_flexion", "more") == 1 and geom.wanted_move("elbow_flexion", "more") == 1  # "straighten": open
    assert geom.wanted_move("forearm_out", "less") is None and geom.wanted_move("knee_flexion", "x") is None
    follower, target = 60.1, 125.2  # that run: the target asked for a wider angle than the follower's
    assert (target - follower) * geom.wanted_move("upper_arm_out", "more") < 0  # the old target went the other way


def test_a_target_on_the_wrong_side_of_the_cue_is_no_moment_and_nothing_is_paid(tmp_path: Path) -> None:
    job, state, fake = build_job(tmp_path / "jobs"), tmp_path / "state", Fake()  # follower 60, trainer 150: opening the knee
    set_fault(job, measure="knee_flexion", direction="less")  # "less" asks for a closing knee: 150 is the wrong way
    out = muse_fix.run(job, consent=True, transport=fake, measurer=measurer_at(150.0), state=state)
    assert out["status"] == "not_available" and fake.edits == [] and not ledger_rows(state)
    set_fault(job, direction="more")  # "more" asks for an opening knee: 150 is the right way
    assert muse_fix.run(job, consent=True, transport=Fake(), measurer=measurer_at(150.0), state=state)["status"] == "shown"


def test_a_picture_that_is_not_one_whole_person_is_a_miss_even_with_the_angle_on_target(tmp_path: Path) -> None:
    cases = {
        "three-joints-only": {n: body(150.0)[n] for n in ("right_hip", "right_knee", "right_ankle")},
        "one-shin-half-the-other": broken("left_ankle", y=-0.5),
        "a-chair-leg": broken("left_ankle", y=-1.9),
        "head-far-from-shoulders": broken("nose", y=1.8),
        "joint-far-from-body": broken("left_wrist", x=-3.0),
    }
    for label, joints in cases.items():
        job, fake = build_job(tmp_path / "jobs", name=label), Fake()
        out = muse_fix.run(job, consent=True, transport=fake, measurer=lambda path, j=joints: j, state=tmp_path / "s")
        assert out["status"] == "missed" and out["reason"] == sane.NOT_A_PERSON, label
        assert out["attempts"][0]["error_deg"] == 0.0 and len(fake.edits) == 2, label  # on target, still a miss; one retry as for any miss
        assert not list(muse_fix.folder(job).glob("corrected*")), label
    unseen = body(150.0)
    for n in ("left_ankle", "right_wrist", "left_wrist", "left_ear", "right_ear"):
        unseen[n]["conf"] = 0.05
    assert sane.whole_person(unseen) == sane.NOT_A_PERSON  # five hidden joints leave 12 of 17
    assert sane.whole_person(body(150.0)) is None


def test_a_joint_that_did_not_move_the_way_the_cue_asks_is_a_miss() -> None:
    assert sane.moved_toward_cue(60.0, 150.0, 150.0, 1) and not sane.moved_toward_cue(160.0, 150.0, 150.0, 1)
    assert not sane.moved_toward_cue(60.0, 61.0, 150.0, 1)  # barely moved
    assert sane.moved_toward_cue(160.0, 150.0, 150.0, None)  # no cue direction: the target's side decides
    assert not sane.moved_toward_cue(None, 150.0, 150.0, 1)
    assert sane.verdict(body(150.0), "right_knee", original=body(160.0), target_deg=150.0, want=1) == sane.WRONG_WAY
    assert sane.verdict(body(150.0), "right_knee", original=body(60.0), target_deg=150.0, want=1) is None


def test_with_the_switch_off_nothing_is_read_sent_or_paid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(muse_fix, "DRAW_ENABLED", False)
    job, state, fake = build_job(tmp_path / "jobs"), tmp_path / "state", Fake()
    out = muse_fix.run(job, consent=True, transport=fake, measurer=measurer_at(150.0), state=state)
    assert out == {"status": "no_check", "reason": muse_fix.SWITCHED_OFF} and fake.edits == [] and not ledger_rows(state)
    assert muse_fix.blocker() == muse_fix.SWITCHED_OFF and not muse_fix.folder(job).exists()


def test_with_the_switch_off_the_referee_pays_and_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # R14b B4
    monkeypatch.setattr(muse_fix, "DRAW_ENABLED", False)
    job = tmp_path / "jobs" / "aaaaaaaaaaaa"
    job.mkdir(parents=True)
    out = muse_fix.referee(job, b"r", b"o", b"c", consent=True, state=tmp_path / "state")
    assert out == {"status": "no_check", "reason": muse_fix.SWITCHED_OFF} and not muse_fix.folder(job).exists()


def test_the_shipped_switch_is_off() -> None:
    source = Path(muse_fix.__file__).read_text(encoding="utf-8")
    assert "\nDRAW_ENABLED = False\n" in source  # to turn it on: change that line to DRAW_ENABLED = True
