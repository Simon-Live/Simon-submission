"""Modes and sections (practice-and-modes.md): section cutting, request fields, Part 5 `--profile` argv."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from part7 import chain, modes, sections
from part7.parts import p5_analyse, probe
from support import Api, ffmpeg_video, make_lock
from test_server import _fake_follower, _upload
from test_trainer_chain_and_harness import _capture_runner, step

JOINT = {"left_hip": [0.1, 0, 0], "right_hip": [-0.1, 0, 0], "nose": [0, 0.8, 0]}
SEC = {"start_ms": 1000, "end_ms": 3000, "index": 2, "count": 4}


def animation(n: int = 100, fps: int = 10, with_t: bool = True) -> bytes:
    frames = [{"index": i, **({"t": i / fps} if with_t else {}), "joints": JOINT} for i in range(n)]
    return json.dumps({"format": "simon.animation.v1", "fps": fps, "frame_count": n, "duration_s": n / fps,
                       "frames": frames}).encode()


# ----- sections.cut -------------------------------------------------------------------------------------
def test_cut_keeps_the_frame_range_and_rebases_times() -> None:
    doc = json.loads(sections.cut(animation(), SEC))
    ts = [f["t"] for f in doc["frames"]]
    assert ts[0] == 0 and ts[-1] == pytest.approx(2.0) and len(ts) == 21  # 1.0 s to 3.0 s inclusive at 10 fps
    assert all(b > a for a, b in zip(ts, ts[1:]))
    assert [f["index"] for f in doc["frames"]] == list(range(21))
    assert doc["frame_count"] == 21 and doc["duration_s"] == pytest.approx(2.0)


def test_cut_reads_time_from_index_over_fps_and_skeleton_keyframes() -> None:
    raw = json.loads(animation(with_t=False))
    raw["format"], raw["keyframes"] = "simon.skeleton.v1", raw.pop("frames")
    doc = json.loads(sections.cut(json.dumps(raw).encode(), SEC))
    assert "frames" not in doc and doc["keyframes"][0]["t"] == 0 and len(doc["keyframes"]) == 21


@pytest.mark.parametrize("sec", [
    {"start_ms": 9500, "end_ms": 12000, "index": 1, "count": 2},   # ends after the clip
    {"start_ms": 20000, "end_ms": 22000, "index": 1, "count": 2},  # starts after the clip
])
def test_cut_outside_the_clip_is_refused(sec: dict[str, int]) -> None:
    with pytest.raises(sections.SectionError):
        sections.cut(animation(), sec)


def test_cut_without_frames_is_refused() -> None:
    with pytest.raises(sections.SectionError):
        sections.cut(b'{"format": "simon.animation.v1"}', SEC)
    with pytest.raises(sections.SectionError):
        sections.cut(b"not json", SEC)


@pytest.mark.parametrize("bad", [
    "x", {"start_ms": 0}, {**SEC, "start_ms": 0.5}, {**SEC, "start_ms": True}, {**SEC, "start_ms": 3000},
    {**SEC, "end_ms": 1500}, {**SEC, "index": 0}, {**SEC, "index": 5}, {**SEC, "count": 9, "index": 1},
])
def test_parse_refuses_bad_sections(bad: Any) -> None:
    with pytest.raises(sections.SectionError):
        sections.parse(bad)


def test_parse_accepts_a_good_section_and_none() -> None:
    assert sections.parse(SEC) == SEC and sections.parse(None) is None
    assert sections.parse({**SEC, "extra": 1}) == SEC


def test_modes_parse() -> None:
    assert modes.parse(None) is None and modes.parse("rehab") == "rehab"
    for bad in ("zen", 3, "", ["dance"]):
        with pytest.raises(modes.ModeError):
            modes.parse(bad)


# ----- the server ---------------------------------------------------------------------------------------
def _follow(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch, **extra: Any) -> tuple[int, dict[str, Any]]:
    seen: dict[str, Any] = {}
    inner = _fake_follower()

    def spy(video: Path, expected: Path, work: Path, report: Any = None, **kw: Any) -> dict[str, Any]:
        seen["expected"], seen["mode"] = json.loads(Path(expected).read_text()), kw.get("mode")
        return inner(video, expected, work, report, **kw)

    monkeypatch.setattr(chain, "follower", spy)
    api.app.child.files["animation.json"] = animation()
    status, doc = api.json("POST", "api/follow", {"upload_id": _upload(api, tiny_mp4), "entry_id": "lateral-raise", **extra})
    if status == 202:
        api.app.queue.wait(doc["job"], 60)
        doc["seen"] = seen
    return status, doc


def test_follow_stores_mode_and_section_and_cuts_the_expected_clip(
    api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    status, doc = _follow(api, tiny_mp4, monkeypatch, mode="rehab", section=SEC)
    assert status == 202 and doc["mode"] == "rehab" and doc["section"] == SEC
    assert len(doc["seen"]["expected"]["frames"]) == 21 and doc["seen"]["expected"]["frames"][0]["t"] == 0
    assert doc["seen"]["mode"] == "rehab"
    status, record = api.json("GET", f"api/jobs/{doc['job']}")
    assert status == 200 and record["mode"] == "rehab" and record["section"] == SEC and record["status"] == "done"


def test_follow_without_mode_or_section_is_unchanged(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    status, doc = _follow(api, tiny_mp4, monkeypatch)
    assert status == 202 and "mode" not in doc and "section" not in doc
    assert len(doc["seen"]["expected"]["frames"]) == 100 and doc["seen"]["mode"] is None
    record = api.json("GET", f"api/jobs/{doc['job']}")[1]
    assert "mode" not in record and "section" not in record


@pytest.mark.parametrize("extra", [
    {"mode": "zen"}, {"mode": 4}, {"section": "x"}, {"section": {**SEC, "end_ms": 1200}},
    {"section": {"start_ms": 9500, "end_ms": 12000, "index": 1, "count": 2}},
])
def test_follow_invalid_mode_or_section_is_400_and_queues_nothing(
    api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch, extra: dict[str, Any]
) -> None:
    status, doc = _follow(api, tiny_mp4, monkeypatch, **extra)
    assert status == 400 and doc["error"]
    assert api.app.queue.counts() == {"running": 0, "waiting": 0}


# ----- Part 5 argv --------------------------------------------------------------------------------------
@pytest.mark.parametrize("help_flags,mode,expect_profile", [
    ("--replay --profile", "rehab", ["--profile", "rehab"]),
    ("--replay", None, None),
    ("--replay --profile", None, None),
])
def test_part5_profile_only_when_the_pin_offers_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, help_flags: str, mode: str | None,
    expect_profile: list[str] | None,
) -> None:
    probe.clear_cache()
    argvs = _capture_runner(monkeypatch, [step(5, 0, help_flags)])
    lk = make_lock()
    lk.path("5").mkdir(parents=True, exist_ok=True)
    _, _, _, notes = p5_analyse.run(tmp_path / "e.json", tmp_path / "f.json", tmp_path / "w", lock=lk,
                                    state=tmp_path / "s", mode=mode)
    argv = argvs[-1]
    if expect_profile:
        assert argv[argv.index("--profile"):][:2] == expect_profile
    else:
        assert "--profile" not in argv
    assert notes == []
    probe.clear_cache()


# ----- optional `first` and `speed` ---------------------------------------------------------------------
def test_speed_stretches_the_cut_clip_and_first_is_kept() -> None:
    sec = {**SEC, "speed": 0.5, "first": 1}
    assert sections.parse(sec) == sec
    doc = json.loads(sections.cut(animation(), sec))
    assert doc["frames"][-1]["t"] == pytest.approx(4.0) and len(doc["frames"]) == 21  # 2 s of trainer over 4 s
    assert doc["duration_s"] == pytest.approx(4.0)


def test_speed_scales_fps_so_part5_reads_the_stretched_rate() -> None:
    doc = json.loads(sections.cut(animation(fps=10), {**SEC, "speed": 0.5}))
    assert doc["fps"] == pytest.approx(5.0)
    full = json.loads(sections.cut(animation(fps=10), SEC))
    assert full["fps"] == 10  # speed 1 leaves the rate alone


@pytest.mark.parametrize("bad", [{"speed": 0.1}, {"speed": 1.5}, {"speed": "x"}, {"speed": True}, {"first": 0}, {"first": 3}, {"first": 1.5}])
def test_parse_refuses_bad_speed_or_first(bad: dict[str, Any]) -> None:
    with pytest.raises(sections.SectionError):
        sections.parse({**SEC, **bad})


def test_an_end_just_past_the_clip_is_cut_at_the_end() -> None:
    doc = json.loads(sections.cut(animation(), {"start_ms": 8000, "end_ms": 10800, "index": 4, "count": 4}))
    assert doc["frames"][-1]["t"] == pytest.approx(1.9)  # the clip ends at 9.9 s


def test_group_stores_the_mode_and_ignores_a_section(monkeypatch: pytest.MonkeyPatch, api: Api) -> None:
    from part7 import people_routes

    seen: dict[str, Any] = {}
    monkeypatch.setattr(people_routes, "_group_request", lambda h, doc: {
        "name": "n", "category": "dance", "work": Path("w"), "trainer": "1", "followers": ["2"], "labels": {},
        "entry_labels": {}, "save_entry": True})
    monkeypatch.setattr(people_routes.group, "group_job", lambda **kw: seen.update(kw) or (lambda ctx: {}))
    status, doc = api.json("POST", "api/group", {"mode": "dance", "section": SEC})
    assert status == 202 and doc["mode"] == "dance" and "section" not in doc and seen["mode"] == "dance"
    assert api.json("POST", "api/group", {"mode": "zen"})[0] == 400
