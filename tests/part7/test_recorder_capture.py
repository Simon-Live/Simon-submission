"""Static checks for the recorder capture lane (TICKET-052): countdown, duration, wiring."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

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
    assert "DURATIONS = [0, 5, 6, 10, 15, 20, 30, 45, 60]" in c  # 6 s: the Quick take (TICKET-260)
    assert "QUICK_TAKE = { countdown: 3, duration: 6 }" in c
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
        assert "mountTakeFlow" in s and "mountCapture" not in s and "editTake" not in s and len(s.splitlines()) < (50 if s is r else 90)  # follow also hosts the mode picker and the practice ladder
    assert 'role: "trainer"' in r and 'role: "follower"' in f
    assert "editTake" in t and "capture.reset()" in t and "pending.front(rec" in t  # the upload and people job run in web/pending.js (offline takes)
    assert "openPeoplePicker" in t and "mountModeSwitch" in t and "mountLabels" in t and "labels.value()" in t
    assert "pending.submit(rec)" in t and "createTrainerJob" in (WEB / "api.js").read_text(encoding="utf-8")  # the job call goes through submitJob (offline takes)
    assert "trim ? { trim }" in a and "labels ? { labels }" in a and "api/people" in a and "api/group" in a


def test_capture_hands_edit_info_to_trim_editor():
    c = src("capture")
    assert "openTrimEditor" in c
    for frag in ["source:", "countdownUsed:", "manual:"]:
        assert frag in c


def test_mirrored_by_css_only():
    assert not re.search(r"scaleX", src("capture") + src("countdown"))


# TICKET-063: live preview on open, whole body on every follower surface, client logs.


def css(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def test_camera_opens_on_mount_only_when_allowed_with_the_fallback_kept():
    c = src("capture")
    # TICKET-187, client a5e5503: no permission prompt on load. Only "granted" opens on mount; "denied" shows the
    # blocked state; "prompt" and "unknown" show Open camera as the first focus (drive_capture.mjs proves it live).
    assert "export async function cameraAllowed" in c and "permissions.query" in c
    assert 'if (state === "granted") { openPreview(); return; }' in c
    assert 'state === "denied") { camStatus("blocked"); return; }' in c
    assert "camOpen.focus(" in c
    for key in ["blocked", "dark", "asking"]:
        assert f"{key}:" in c
    assert '"data-testid": "cam-open"' in c and '"Try again"' in c


def test_no_person_picture_uses_cover():
    ref = css("reference.css")
    styles = css("styles.css")
    assert "object-fit: cover" not in ref
    cam_rules = [line for line in styles.splitlines() if line.startswith((".cam", ".trim-video"))]
    assert not [line for line in cam_rules if "object-fit: cover" in line], cam_rules
    assert ".cam video {" in styles and "object-fit: contain" in styles
    assert ".ref-media {" in ref and ".ref-first {" in ref


def test_reference_sits_beside_the_camera_never_over_it():
    ref = css("reference.css")
    assert ".ref-row { display: grid;" in ref
    assert "position: absolute; right:" not in ref and "inset: 8px" not in ref


def test_capture_and_take_flow_log_the_contract_events():
    c, t, a = src("capture"), src("take-flow"), src("api")
    assert 'fetch("api/client-log"' in a and "keepalive: true" in a
    for ev in ["camera_opened", "camera_refused", "camera_dark", "camera_unsupported", "recorder_started",
               "take_recorded", "take_dimensions"]:
        assert f'"{ev}"' in c, ev
    for ev in ["trim_chosen", "upload_done", "upload_failed"]:
        assert f'"{ev}"' in t, ev
    assert c.count("console.info(") >= 3 and c.count("console.warn(") >= 3
    opened = next(line for line in c.splitlines() if 'clientLog("info", "camera_opened"' in line)
    assert "label" not in opened and "width: set.width" in opened  # the device label never reaches the server


def test_clientlog_unit():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, "--test", str(WEB.parent / "tests/part7/clientlog.unit.test.mjs")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
