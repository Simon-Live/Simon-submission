"""History store (docs/specs/history.md "Store", TICKET-179 AC-1 to AC-7), on the real cleared squat takes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from history_support import ENTRY, FIRST, OTHER, SECOND, USER, World, job_record, record_two, seed_job, video, world  # noqa: F401
from part7 import history_store


def _probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_record_take_copies_analysis_clip_and_meta(tmp_path: Path, world: World) -> None:  # AC-1
    world.opted_in.add(USER)
    folder = seed_job(tmp_path, SECOND)
    world.owners[SECOND] = USER
    assert history_store.record_take(tmp_path, job_record(tmp_path, SECOND), folder) is True
    copy = tmp_path / "history" / USER / ENTRY / "takes" / SECOND
    assert sorted(p.name for p in copy.iterdir()) == ["analysis.json", "clip.mp4", "meta.json"]
    assert (copy / "analysis.json").read_bytes() == (folder / "work" / "follower" / "analysis.json").read_bytes()
    meta = json.loads((copy / "meta.json").read_text())
    assert (meta["score"], meta["grade"], meta["private"], meta["clip"]) == (77, "C", False, True)
    assert meta["at"] == "2026-10-31T18:23:16Z" and meta["duration_s"] == 2.0 and meta["duration_source"] == "ffprobe"  # the fixture video is 2 s
    streams = _probe(copy / "clip.mp4")["streams"]
    assert [s["codec_type"] for s in streams] == ["video"]  # no audio
    assert streams[0]["r_frame_rate"] == "8/1"
    assert not list((tmp_path / "history" / ".tmp").iterdir())  # the staging folder is cleaned


def test_clip_short_side_is_480_and_never_upscaled(tmp_path: Path) -> None:  # AC-1
    big, small = video(tmp_path / "big.mp4", 1, "720x1280"), video(tmp_path / "small.mp4", 1, "320x240")
    for source, expect in ((big, (480, 854)), (small, (320, 240))):
        out = tmp_path / f"out-{source.stem}.mp4"
        assert history_store._make_clip(source, out)
        s = _probe(out)["streams"][0]
        assert (s["width"], s["height"]) == expect
    assert history_store._make_clip(tmp_path / "missing.mp4", tmp_path / "x.mp4") is False


def test_no_consent_no_copy(tmp_path: Path, world: World) -> None:  # AC-2
    folder = seed_job(tmp_path, SECOND)
    record = job_record(tmp_path, SECOND)
    assert history_store.record_take(tmp_path, record, folder) is False  # anonymous: no owner
    world.owners[SECOND] = USER
    assert history_store.record_take(tmp_path, record, folder) is False  # owned, no retention consent
    assert not (tmp_path / "history" / USER).exists()


def test_no_identity_module_keeps_the_feature_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-2
    monkeypatch.setitem(sys.modules, "part7.identity", None)  # an import of it raises ImportError
    folder = seed_job(tmp_path, SECOND, with_video=False)
    assert history_store.record_take(tmp_path, job_record(tmp_path, SECOND), folder) is False
    assert history_store.owner_of(tmp_path, SECOND) is None and history_store.retention_opt_in(tmp_path, USER) is False


def test_private_and_group(tmp_path: Path, world: World) -> None:  # AC-3
    world.opted_in.add(USER)
    for job, extra in ((FIRST, {"private": True}), (SECOND, {"mode": "rehab"})):
        folder = seed_job(tmp_path, job, **extra)
        world.owners[job] = USER
        assert history_store.record_take(tmp_path, job_record(tmp_path, job), folder)
    got = history_store.takes(tmp_path, USER, ENTRY)
    # private true is kept and flagged; a rehab take is a normal take; a job with no field is not private
    assert [(t["job_id"], t["private"]) for t in got] == [(FIRST, True), (SECOND, False)]
    assert all(t["clip"] is not None for t in got)
    history_store.drop_take(tmp_path, FIRST)
    group = {**job_record(tmp_path, FIRST), "kind": "group"}
    assert history_store.record_take(tmp_path, group, tmp_path / "jobs" / FIRST) is False  # a group person never enters
    assert [t["job_id"] for t in history_store.takes(tmp_path, USER, ENTRY)] == [SECOND]


def test_unfinished_or_unscored_take_is_not_copied(tmp_path: Path, world: World) -> None:  # edge
    world.opted_in.add(USER)
    world.owners[FIRST] = USER
    folder = seed_job(tmp_path, FIRST, status="running")
    assert history_store.record_take(tmp_path, job_record(tmp_path, FIRST), folder) is False
    (folder / "work" / "follower" / "analysis.json").write_text("{}")
    assert history_store.record_take(tmp_path, {**job_record(tmp_path, FIRST), "status": "done"}, folder) is False
    assert history_store.record_take(tmp_path, {"id": "../x"}, folder) is False


def test_missing_video_still_copies_without_a_clip(tmp_path: Path, world: World) -> None:  # edge
    world.opted_in.add(USER)
    folder = seed_job(tmp_path, SECOND, with_video=False)
    world.owners[SECOND] = USER
    assert history_store.record_take(tmp_path, job_record(tmp_path, SECOND), folder)
    (take,) = history_store.takes(tmp_path, USER, ENTRY)
    assert take["clip"] is None and take["analysis"].is_file()


def test_order_and_dates(tmp_path: Path, world: World) -> None:  # AC-4
    world.opted_in.add(USER)
    for job in (SECOND, FIRST):  # recorded out of order
        folder = seed_job(tmp_path, job, with_video=False)
        world.owners[job] = USER
        history_store.record_take(tmp_path, job_record(tmp_path, job), folder)
    got = history_store.takes(tmp_path, USER, ENTRY)
    assert [(t["take"], t["job_id"], t["score"]) for t in got] == [(1, FIRST, 100), (2, SECOND, 77)]
    assert [t["at"] for t in got] == ["2026-10-31T18:14:00Z", "2026-10-31T18:23:16Z"]  # the recorded times
    assert history_store.takes(tmp_path, OTHER, ENTRY) == [] and history_store.takes(tmp_path, "bad", ENTRY) == []
    assert history_store.entries(tmp_path, USER) == [ENTRY] and history_store.entries(tmp_path, OTHER) == []


def test_claim(tmp_path: Path, world: World) -> None:  # AC-5
    seed_job(tmp_path, SECOND)
    assert history_store.claim(tmp_path, USER, SECOND) is False  # not owned
    world.owners[SECOND] = USER
    assert history_store.claim(tmp_path, USER, SECOND) is False  # owned, no retention consent
    world.opted_in.add(USER)
    assert history_store.claim(tmp_path, OTHER, SECOND) is False  # someone else's job
    assert history_store.claim(tmp_path, USER, SECOND) is True
    meta = tmp_path / "history" / USER / ENTRY / "takes" / SECOND / "meta.json"
    before = (meta.stat().st_mtime_ns, meta.read_text())
    assert history_store.claim(tmp_path, USER, SECOND) is True  # a second call changes nothing
    assert (meta.stat().st_mtime_ns, meta.read_text()) == before
    assert history_store.claim(tmp_path, USER, "ffffffffffff") is False and history_store.claim(tmp_path, USER, "../x") is False


def test_sweep(tmp_path: Path, world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-6
    record_two(tmp_path, world)
    meta = tmp_path / "history" / USER / ENTRY / "takes" / FIRST / "meta.json"
    doc = json.loads(meta.read_text())
    doc["kept_ts"] -= 91 * 86400
    meta.write_text(json.dumps(doc))
    now = doc["kept_ts"] + 91 * 86400
    assert history_store.sweep(tmp_path, now=now) == 1
    assert [t["job_id"] for t in history_store.takes(tmp_path, USER, ENTRY)] == [SECOND]
    assert history_store.sweep(tmp_path, now=now + 10 * 86400) == 0  # the other copy is 10 days old
    monkeypatch.setenv("SIMON7_HISTORY_DAYS", "5")
    assert history_store.days() == 5
    assert history_store.sweep(tmp_path, now=now + 10 * 86400) == 1
    assert history_store.entries(tmp_path, USER) == []
    monkeypatch.setenv("SIMON7_HISTORY_DAYS", "nope")
    assert history_store.days() == 90


def _report(state: Path, key: str, jobs: list[str]) -> Path:
    path = history_store.reports_dir(state, USER, ENTRY) / f"{key}.json"
    history_store.write_json(path, {"format": "simon.history.v1", "takes": [{"job_id": j} for j in jobs]})
    return path


def test_drop_and_forget(tmp_path: Path, world: World) -> None:  # AC-7
    record_two(tmp_path, world)
    both, only_second = _report(tmp_path, "a" * 8, [FIRST, SECOND]), _report(tmp_path, "b" * 8, [SECOND])
    assert history_store.drop_take(tmp_path, FIRST) == 1
    assert not both.exists() and only_second.exists()  # the report citing the dropped take goes, the other stays
    assert history_store.drop_take(tmp_path, FIRST) == 0 and history_store.drop_take(tmp_path, "../..") == 0
    left = history_store.takes(tmp_path, USER, ENTRY)
    assert [(t["job_id"], t["take"]) for t in left] == [(SECOND, 1)]  # numbering follows what is left
    record_two(tmp_path, world)
    history_store.set_consent(tmp_path, USER, True, "v1")
    assert history_store.forget(tmp_path, USER, ENTRY) == 2
    assert history_store.entries(tmp_path, USER) == []
    record_two(tmp_path, world)
    assert history_store.forget(tmp_path, USER) == 2
    assert not (tmp_path / "history" / USER).exists()
    assert history_store.consent(tmp_path, USER)["video"] is False  # forgetting everything clears the consent too
    assert history_store.forget(tmp_path, USER) == 0 and history_store.forget(tmp_path, "x") == 0


def test_forget_keeps_other_users(tmp_path: Path, world: World) -> None:  # edge
    record_two(tmp_path, world)
    assert history_store.forget(tmp_path, OTHER) == 0
    assert len(history_store.takes(tmp_path, USER, ENTRY)) == 2


def test_video_consent(tmp_path: Path) -> None:
    assert history_store.consent(tmp_path, USER) == {"video": False, "version": None, "at": None}
    got = history_store.set_consent(tmp_path, USER, True, "2026-11")
    assert got["video"] is True and got["version"] == "2026-11" and got["at"].endswith("Z")
    assert history_store.set_consent(tmp_path, USER, False, "2026-11")["video"] is False
    for bad in ((USER, "yes", "v1"), (USER, True, ""), (USER, True, "a b"), ("short", True, "v1"), (USER, True, 5)):
        with pytest.raises(ValueError):
            history_store.set_consent(tmp_path, *bad)  # type: ignore[arg-type]


def test_withdraw_retention_deletes_all_history_now(tmp_path: Path, world: World) -> None:  # consent withdrawal
    record_two(tmp_path, world)
    history_store.set_consent(tmp_path, USER, True, "v1")
    report = _report(tmp_path, "c" * 8, [FIRST, SECOND])
    assert history_store.withdraw_retention(tmp_path, USER) == 2
    assert not report.exists() and not (tmp_path / "history" / USER).exists()
    assert (tmp_path / "jobs" / FIRST).is_dir()  # job folders keep the normal 7-day rule
    assert history_store.withdraw_retention(tmp_path, USER) == 0


def test_withdraw_video_consent_drops_video_reports_keeps_copies(tmp_path: Path, world: World) -> None:  # consent withdrawal
    record_two(tmp_path, world)
    history_store.set_consent(tmp_path, USER, True, "v1")
    folder = history_store.reports_dir(tmp_path, USER, ENTRY)
    history_store.write_json(folder / "v.json", {"video": True, "takes": []})
    history_store.write_json(folder / "j.json", {"video": False, "takes": []})
    history_store.set_consent(tmp_path, USER, False, "v1")
    assert not (folder / "v.json").exists() and (folder / "j.json").exists()
    assert len(history_store.takes(tmp_path, USER, ENTRY)) == 2


def test_sweep_removes_stale_staging(tmp_path: Path) -> None:  # edge
    stale = tmp_path / "history" / ".tmp" / "x-1"
    stale.mkdir(parents=True)
    os.utime(stale, (1, 1))
    history_store.sweep(tmp_path)
    assert not stale.exists()


# ----- Part 5's analysis has no follower duration: ffprobe, then the job record, replay.json, the compared span -----
def _analysis(end: float | None) -> dict:
    return {"score": {"value": 80, "grade": "B", "timeline": [{"t_s": [0.0, 2.0]}, {"t_s": [2.0, end]}] if end else []}}


def test_duration_from_ffprobe_is_exact_and_recorded(tmp_path: Path) -> None:
    folder = tmp_path / "job"
    (folder / "work").mkdir(parents=True)
    video(folder / "work" / "video.mp4", 2, "320x240")
    seconds, source = history_store.duration_of({"duration_ms": 9999}, folder, _analysis(5.0))
    assert source == "ffprobe" and 1.9 < seconds < 2.2


def test_duration_falls_back_to_the_job_record(tmp_path: Path) -> None:
    assert history_store.duration_of({"duration_ms": 9955}, tmp_path, _analysis(5.0)) == (9.955, "job")
    assert history_store.duration_of({"trim": {"start_ms": 1000, "end_ms": 4500}}, tmp_path, None) == (3.5, "job")


def test_duration_falls_back_to_the_replay_follower_times(tmp_path: Path) -> None:
    (tmp_path / "work" / "follower").mkdir(parents=True)
    (tmp_path / "work" / "follower" / "replay.json").write_text(json.dumps({"follower_t": [0.0, 4.5, 9.833333]}))
    assert history_store.duration_of({}, tmp_path, _analysis(5.0)) == (9.833, "replay")


def test_duration_last_resort_is_the_end_of_the_compared_span(tmp_path: Path) -> None:
    assert history_store.duration_of({}, tmp_path, _analysis(9.833)) == (9.833, "timeline")
    assert history_store.duration_of({}, tmp_path, _analysis(None)) == (None, None)
    assert history_store.duration_of({}, tmp_path, "not an analysis") == (None, None)


def test_the_source_is_kept_in_meta_and_a_copy_without_a_duration_still_gets_one_in_the_facts(tmp_path: Path, world: World) -> None:
    from part7 import history_facts
    world.opted_in.add(USER)
    folder = seed_job(tmp_path, SECOND)
    world.owners[SECOND] = USER
    assert history_store.record_take(tmp_path, job_record(tmp_path, SECOND), folder)
    meta = json.loads((tmp_path / "history" / USER / ENTRY / "takes" / SECOND / "meta.json").read_text())
    assert meta["duration_source"] == "ffprobe" and history_store.takes(tmp_path, USER, ENTRY)[0]["duration_source"] == "ffprobe"
    row = {"take": 1, "duration_s": None, "at": "x", "score": 80, "grade": "B"}
    assert history_facts._take_row(row, _analysis(7.5))["duration_s"] == 7.5


def test_anonymous_sweep_creates_nothing(tmp_path: Path) -> None:  # R8
    assert history_store.sweep(tmp_path) == 0
    assert not (tmp_path / "history").exists()
