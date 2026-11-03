"""The progress sheet's store and build (docs/specs/progress-sheet.md, TICKET-283 AC-1, AC-2)."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from auth_support import authenv, sign_in  # noqa: F401
from part7 import auth, history_store, programme, progress_routes, progress_sheet, share_routes
from progress_support import DAYS, ENTRY, job_id, seed, seed_five
from support import Api

pytestmark = pytest.mark.usefixtures("authenv")


def _user(api: Api) -> tuple[str, str]:
    sid = sign_in(api)
    db = auth.identity(api.app)
    user = db.session_user(sid)
    db.set_consent(user, "v1", True)
    return sid, user


def _meta(state: Path, user: str, job: str) -> dict:
    return json.loads((history_store.take_dir(state, user, ENTRY, job) / "meta.json").read_text())


def test_a_rehab_take_keeps_reps_peak_angle_tempo_and_a_skeleton(api: Api) -> None:
    _, user = _user(api)
    state, db = api.app.state, auth.identity(api.app)
    assert seed(state, db, user, job_id(1), DAYS[0])
    facts = _meta(state, user, job_id(1))["rehab"]
    assert (facts["reps"], facts["tempo_ratio"], facts["measure"], facts["source"]) == (5, 2.51, "left_upper_arm_forward", "part7-adapter")
    assert facts["peak_deg"] == facts["peaks"]["left_upper_arm_forward"] == 52.3
    folder = history_store.take_dir(state, user, ENTRY, job_id(1))
    skel = json.loads((folder / progress_sheet.SKELETON_NAME).read_text())
    assert set(skel) == {"joints", "bones", "t", "frames"}
    assert history_store.drop_take(state, job_id(1)) == 1 and not folder.exists()  # the facts and skeleton go with the take


def test_a_fitness_take_is_not_tracked_unless_its_entry_is_a_programme(api: Api) -> None:
    _, user = _user(api)
    state, db = api.app.state, auth.identity(api.app)
    assert seed(state, db, user, job_id(2), DAYS[0], mode="fitness")
    assert "rehab" not in _meta(state, user, job_id(2))
    assert not (history_store.take_dir(state, user, ENTRY, job_id(2)) / progress_sheet.SKELETON_NAME).exists()
    programme.save(state, ENTRY, "right_knee_flexion")
    assert seed(state, db, user, job_id(3), DAYS[1], mode="fitness")
    assert _meta(state, user, job_id(3))["rehab"]["measure"] == "right_knee_flexion"


def test_an_odd_replay_never_costs_the_copy(api: Api) -> None:
    _, user = _user(api)
    state, db = api.app.state, auth.identity(api.app)
    assert seed(state, db, user, job_id(4), DAYS[0], replay=False)
    (state / "jobs" / job_id(5) / "work" / "follower").mkdir(parents=True)
    (state / "jobs" / job_id(5) / "work" / "follower" / "replay.json").write_text('{"joints": ["a"], "follower": [[["x", 1, 2]]]}')
    assert seed(state, db, user, job_id(5), DAYS[1], replay=False)
    assert _meta(state, user, job_id(4))["rehab"]["peak_deg"] is None and _meta(state, user, job_id(4))["rehab"]["reps"] == 5


def test_the_sheet_has_a_calendar_a_trend_every_take_and_a_skeleton_and_no_video(api: Api) -> None:
    _, user = _user(api)
    state = api.app.state
    jobs = seed_five(state, auth.identity(api.app), user)
    sheet = progress_sheet.build(state, user, ENTRY, "Body squat")
    assert sheet is not None and sheet["sessions"] == 5 and [r["job_id"] for r in sheet["takes"]] == jobs
    assert [d["day"] for d in sheet["days"]] == sorted(set(DAYS)) and [d["sessions"] for d in sheet["days"]] == [1, 2, 1, 1]
    assert all(d["peak_deg"] == 52.3 for d in sheet["days"]) and sheet["measure_label"] == "left arm raised forward"
    assert sheet["error"] == {"deg": None, "source": "not yet validated"} and sheet["skeleton_on"].startswith(DAYS[-1])
    skel = sheet["skeleton"]
    assert skel["view"] == "side" and len(skel["frames"]) > 10 and isinstance(skel["peak_frame"], int)
    assert all(0 <= v <= 1 for f in skel["frames"] for p in f if p for v in p)
    text = json.dumps(sheet).lower()
    assert ".mp4" not in text and "clip" not in text and "video" not in text  # AC-2: no video, not even a path


def test_a_declared_measure_reads_the_peaks_already_kept(api: Api) -> None:
    _, user = _user(api)
    state = api.app.state
    seed_five(state, auth.identity(api.app), user)
    programme.save(state, ENTRY, "right_knee_flexion")
    sheet = progress_sheet.build(state, user, ENTRY)
    assert sheet["measure"] == "right_knee_flexion" and sheet["declared"] and {d["peak_deg"] for d in sheet["days"]} == {112.7}


def test_private_takes_and_other_people_are_left_out(api: Api) -> None:
    _, user = _user(api)
    state = api.app.state
    assert progress_sheet.build(state, user, ENTRY) is None
    seed_five(state, auth.identity(api.app), user)
    assert progress_sheet.build(state, "u-someone-else-0000", ENTRY) is None
    meta_path = history_store.take_dir(state, user, ENTRY, job_id(0xA00)) / "meta.json"
    meta_path.write_text(json.dumps({**json.loads(meta_path.read_text()), "private": True}))
    assert progress_sheet.build(state, user, ENTRY)["sessions"] == 4


def test_public_drops_every_id(api: Api) -> None:
    _, user = _user(api)
    state = api.app.state
    jobs = seed_five(state, auth.identity(api.app), user)
    snap = progress_sheet.public(progress_sheet.build(state, user, ENTRY, "Body squat"))
    text = json.dumps(snap)
    assert all(j not in text for j in jobs) and ENTRY not in text and user not in text and snap["title"] == "Body squat"


def test_backfill_fills_old_copies_once(api: Api) -> None:
    _, user = _user(api)
    state = api.app.state
    seed_five(state, auth.identity(api.app), user)
    folder = history_store.take_dir(state, user, ENTRY, job_id(0xA00))
    meta = json.loads((folder / "meta.json").read_text())
    meta.pop("rehab")
    (folder / "meta.json").write_text(json.dumps(meta))
    (folder / progress_sheet.SKELETON_NAME).unlink()
    assert progress_sheet.backfill(state) == {"filled": 1, "already": 4, "untracked": 0, "job_gone": 0}
    assert _meta(state, user, job_id(0xA00))["rehab"]["reps"] == 5 and (folder / progress_sheet.SKELETON_NAME).is_file()
    assert progress_sheet.backfill(state) == {"filled": 0, "already": 5, "untracked": 0, "job_gone": 0}
    assert progress_sheet.main(["backfill", str(state)]) == 0 and progress_sheet.main([]) == 2


def test_server_words_of_the_sheet_carry_no_advice_or_medical_term() -> None:
    """AC-3 on the Python side, with the one banned list of web/model/progress-sheet.js."""
    model = (Path(__file__).resolve().parents[2] / "web" / "model" / "progress-sheet.js").read_text()
    banned = re.findall(r'"([^"]+)"', re.search(r"export const BANNED = \[(.*?)\];", model, re.S).group(1))
    assert {"should", "safe", "recommend", "increase", "decrease", "medical", "injur", "coach"} <= set(banned)
    words = [*programme.LABELS.values(), programme.MSG_MEASURE, share_routes.MSG_NO_SHEET, progress_routes.MSG_NONE]
    for line in words:
        assert not [w for w in banned if w in line.lower()], line
        assert not re.search(r"[\u2013\u2014]| - ", line), line
