"""Static checks for the recorder capture lane (TICKET-052): countdown, duration, wiring."""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"


def src(name: str) -> str:
    return (WEB / f"{name}.js").read_text(encoding="utf-8")


def test_new_testids_present():
    cap, cd = src("capture"), src("countdown")
    for tid in ["countdown-select", "duration-select", "framing-hint"]:
        assert f'"{tid}"' in cap or f'"data-testid": "{tid}"' in cap, tid
    for tid in ["countdown", "countdown-cancel", "rec-timer"]:
        assert f'"data-testid": "{tid}"' in cd, tid


def test_existing_testids_kept():
    c = src("capture")
    for tid in ["cam-start", "cam-stop", "upload", "preview", "take-preview", "timer", "capture-error", "take-info"]:
        assert f'"data-testid": "{tid}"' in c, tid


def test_option_lists_follow_spec():
    c = src("countdown")
    assert "COUNTDOWNS = [0, 3, 5, 10]" in c
    assert "DURATIONS = [0, 5, 10, 15, 20, 30, 45, 60]" in c
    assert "countdown: 5, duration: 15" in c
    assert "RAW_LIMIT_S = 90" in c


def test_framing_hint_text_exact():
    assert "Step back until your whole body fits, or at least everything that moves." in src("capture")


def test_prefs_storage_wrapped_in_try_catch():
    c = src("countdown")
    assert c.count("try {") >= 3 and "localStorage" in c


def test_record_and_follow_are_thin_wrappers_over_one_take_flow():
    r, f, t, a = src("record"), src("follow"), src("take-flow"), src("api")
    for s in (r, f):
        assert "mountTakeFlow" in s and "mountCapture" not in s and "editTake" not in s and len(s.splitlines()) < 50
    assert 'role: "trainer"' in r and 'role: "follower"' in f
    assert "editTake" in t and "capture.reset()" in t and "createPeopleJob(upload, trim)" in t
    assert "openPeoplePicker" in t and "mountModeSwitch" in t and "mountLabels" in t and "labels.value()" in t
    assert "createTrainerJob" in t and "createFollowJob" in t and "createGroupJob" in t
    assert "trim ? { trim }" in a and "labels ? { labels }" in a and "api/people" in a and "api/group" in a


def test_capture_hands_edit_info_to_trim_editor():
    c = src("capture")
    assert "openTrimEditor" in c
    for frag in ["source:", "countdownUsed:", "manual:"]:
        assert frag in c


def test_mirrored_by_css_only():
    assert not re.search(r"scaleX", src("capture") + src("countdown"))
