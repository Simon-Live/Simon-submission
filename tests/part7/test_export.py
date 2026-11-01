"""The split-screen export (docs/specs/export-clip.md): facts, command, render, routes."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any

import pytest

from part7 import export_clip, export_routes, jobs
from support import Api, ffmpeg_video

ENTRY = "body-squat-19b06562"
FAULTS = [
    {"cue": "Keep your chest up", "text": "leaning forward more than the example", "text_timed": "leaning forward more than the example at 0.9 s", "at_s": 0.9},
    {"cue": "Knees out", "text": "knees caving in", "at_s": 1.5},
    {"text": "hips low", "follower_t_s": [6.0, 7.0]},
    {"cue": "No time", "text": "x"},
]
RESULT = {"score": 77, "grade": "C", "faults": 4}


@pytest.fixture(autouse=True)
def _clean_state() -> Any:
    export_routes._STATE.clear()
    yield
    export_routes._STATE.clear()


def finish(api: Api, clip: Path, *, kind: str = "follow", result: dict[str, Any] | None = None, faults: list | None = None,
           trainer: bool = True, follower: bool = True, analysis: bool = True, **fields: Any) -> str:
    if trainer:
        d = Path(api.app.child.catalog_dir) / ENTRY
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy(clip, d / "video.mp4")

    def fn(ctx: jobs.JobContext) -> dict[str, Any]:
        if follower:
            shutil.copy(clip, ctx.work / "video.mp4")
        if analysis:
            (ctx.work / "follower").mkdir()
            (ctx.work / "follower" / "analysis.json").write_text(json.dumps({"faults": FAULTS if faults is None else faults}))
        return {"result": RESULT if result is None else result}

    job = api.app.queue.submit(kind, fn, entry_id=ENTRY, **fields)
    assert api.app.queue.wait(job["id"], 10)["status"] == "done"
    return job["id"]


class FakeFfmpeg:
    """Stands in for `export_clip.run_ffmpeg`: writes the output, records the command, can fail or hold."""

    def __init__(self) -> None:
        self.cmds: list[list[str]] = []
        self.code = 0
        self.gate: threading.Event | None = None
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def __call__(self, cmd: list[str], cwd: Path, timeout: float = 0) -> tuple[int, str]:
        with self.lock:
            self.cmds.append(cmd)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.gate:
                self.gate.wait(10)
            if self.code == 0:
                Path(cmd[-1]).write_bytes(b"x" * 4000)
            return (self.code, "boom /secret/path")
        finally:
            with self.lock:
                self.active -= 1


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeFfmpeg:
    f = FakeFfmpeg()
    monkeypatch.setattr(export_clip, "run_ffmpeg", f)
    monkeypatch.setattr(export_clip, "probe_duration", lambda p, runner=None: 4.0)
    return f


def wait_state(api: Api, job: str, states: tuple[str, ...], timeout: float = 20) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        status, doc = api.json("GET", f"api/jobs/{job}/export")
        assert status == 200
        if doc["state"] in states:
            return doc
        time.sleep(0.05)
    raise AssertionError(f"state never reached {states}: {doc}")


# ----- AC-1, AC-2 ----------------------------------------------------------------------------------
def test_facts_come_from_the_job_and_analysis() -> None:
    facts = export_clip.facts_from({"result": RESULT}, {"faults": FAULTS})
    assert (facts.score, facts.grade, facts.faults) == (77, "C", 4)
    assert [c.cue for c in facts.captions] == ["Keep your chest up", "Knees out", "Hips low"]  # the untimed one is skipped
    first = facts.captions[0]
    assert first.detail == "Leaning forward more than the example at 0.9 s"
    assert facts.captions[2].start == 6.0  # follower_t_s when at_s is absent
    assert facts.as_dict()["captions"][0]["at_s"] == 0.9


def test_captions_last_two_to_three_and_a_half_seconds_and_do_not_overlap() -> None:
    facts = export_clip.facts_from({"result": RESULT}, {"faults": FAULTS})
    a, b, c = facts.captions
    assert a.end == b.start == 1.5  # the next fault cuts it short
    assert b.end - b.start == export_clip.CAPTION_MAX_S and c.end - c.start == export_clip.CAPTION_MAX_S
    lone = export_clip.facts_from({"result": RESULT}, {"faults": [{"cue": "a", "at_s": 1}, {"cue": "b", "at_s": 1.2}]})
    assert lone.captions[0].end <= lone.captions[1].start


@pytest.mark.parametrize("result", [None, {}, {"score": 80}, {"grade": "B"}, {"score": True, "grade": "B"}, {"score": 5, "grade": ""}])
def test_a_job_without_score_and_grade_is_refused(result: Any) -> None:
    with pytest.raises(export_clip.ExportError):
        export_clip.facts_from({"result": result}, {"faults": []})


def test_no_faults_reads_as_such() -> None:
    facts = export_clip.facts_from({"result": {"score": 98, "grade": "A"}}, {})
    assert (facts.faults, facts.captions) == (0, ())
    assert export_clip.faults_label(0) == "No faults found" and export_clip.faults_label(1) == "1 fault"
    assert export_clip.texts_for(facts)["faults.txt"] == "No faults found"


def test_long_caption_is_wrapped_and_cut() -> None:
    facts = export_clip.facts_from({"result": RESULT}, {"faults": [{"cue": "word " * 60, "at_s": 1}]})
    text = export_clip.texts_for(facts)["cue0.txt"]
    assert text.count("\n") == export_clip.CUE_LINES - 1 and text.endswith("...")


# ----- AC-3 ----------------------------------------------------------------------------------------
def test_command_shape() -> None:
    facts = export_clip.facts_from({"result": RESULT}, {"faults": FAULTS})
    cmd = export_clip.build_command(Path("/t.mp4"), Path("/f.mp4"), Path("/o.mp4"), 10.0, facts, font="/f.ttf")
    joined = " ".join(cmd)
    assert cmd[0] == "ffmpeg" and cmd[-1] == "/o.mp4" and "-an" in cmd
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p" and cmd[cmd.index("-movflags") + 1] == "+faststart"
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert "s=1080x1920" in joined and "textfile=score.txt" in joined and "textfile=cue2.txt" in joined
    assert "between(t,0.90,1.50)" in joined and "fontfile=/f.ttf" in joined
    assert "-ss" not in cmd


def test_section_cuts_and_slows_the_trainer() -> None:
    facts = export_clip.facts_from({"result": RESULT}, {"faults": []})
    section = {"start_ms": 2000, "end_ms": 6000, "index": 2, "count": 4, "speed": 0.5}
    cmd = export_clip.build_command(Path("/t.mp4"), Path("/f.mp4"), Path("/o.mp4"), 8.0, facts, section)
    assert cmd[cmd.index("-ss") + 1] == "2.000" and cmd[cmd.index("-t") + 1] == "4.000"
    assert cmd.index("-ss") < cmd.index("-i")  # an input option of the trainer clip
    assert "setpts=PTS/0.5000" in " ".join(cmd)


# ----- AC-4 ----------------------------------------------------------------------------------------
def test_render_writes_texts_and_replaces_atomically(tmp_path: Path, fake: FakeFfmpeg) -> None:
    facts = export_clip.facts_from({"result": RESULT}, {"faults": FAULTS})
    out = tmp_path / "x" / "export.mp4"
    seconds = export_clip.render(Path("/t"), Path("/f"), out, facts, run=fake)
    assert seconds == 4.0 and out.read_bytes() == b"x" * 4000
    assert (out.parent / "score.txt").read_text() == "77" and (out.parent / "grade.txt").read_text() == "Grade C"
    assert not (out.parent / "export.partial.mp4").exists()


@pytest.mark.parametrize("code", [1, -9])
def test_render_failure_leaves_no_file(tmp_path: Path, fake: FakeFfmpeg, code: int) -> None:
    fake.code = code
    out = tmp_path / "export.mp4"
    with pytest.raises(export_clip.ExportError):
        export_clip.render(Path("/t"), Path("/f"), out, export_clip.facts_from({"result": RESULT}, {}), run=fake)
    assert not out.exists() and not (tmp_path / "export.partial.mp4").exists()


def test_render_with_no_output_file_is_a_failure(tmp_path: Path) -> None:
    out = tmp_path / "export.mp4"
    with pytest.raises(export_clip.ExportError):
        export_clip.render(Path("/t"), Path("/f"), out, export_clip.facts_from({"result": RESULT}, {}),
                           run=lambda cmd, cwd: (0, ""), runner=lambda *a, **k: subprocess.CompletedProcess(a, 0, "3.0\n", ""))


def test_run_ffmpeg_timeout_and_missing_binary(tmp_path: Path) -> None:
    assert export_clip.run_ffmpeg(["sleep", "5"], tmp_path, timeout=0.2)[0] == -9
    assert export_clip.run_ffmpeg(["no-such-binary-xyz"], tmp_path)[0] == -1
    assert export_clip.run_ffmpeg(["true"], tmp_path)[0] == 0


def test_probe_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp4"
    bad.write_text("not a video")
    with pytest.raises(export_clip.ExportError):
        export_clip.probe_duration(bad)
    with pytest.raises(export_clip.ExportError):
        export_clip.probe_duration(bad, runner=lambda *a, **k: subprocess.CompletedProcess(a, 0, "0\n", ""))


def test_duration_is_the_longer_clip_capped_and_section_aware() -> None:
    def runner(cmd: list[str], **k: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(cmd, 0, {"/t": "30\n", "/f": "5\n", "/big": "500\n"}[cmd[-1]], "")

    assert export_clip.clip_duration(Path("/t"), Path("/f"), None, runner) == 30.0
    assert export_clip.clip_duration(Path("/big"), Path("/f"), None, runner) == export_clip.MAX_DURATION_S
    sec = {"start_ms": 0, "end_ms": 4000, "speed": 0.5}
    assert export_clip.clip_duration(Path("/t"), Path("/f"), sec, runner) == 8.0


# ----- AC-5: one real render -------------------------------------------------------------------------
def test_real_ffmpeg_render(tmp_path: Path, tiny_mp4: Path) -> None:
    facts = export_clip.facts_from({"result": RESULT}, {"faults": FAULTS[:2]})
    out = tmp_path / "export" / "export.mp4"
    export_clip.render(tiny_mp4, tiny_mp4, out, facts)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,width,height,pix_fmt",
         "-of", "json", str(out)], capture_output=True, text=True, check=True)
    stream = json.loads(probe.stdout)["streams"][0]
    assert (stream["codec_name"], stream["width"], stream["height"], stream["pix_fmt"]) == ("h264", 1080, 1920, "yuv420p")
    head = out.read_bytes()[:4096]
    assert head.find(b"moov") != -1 and head.find(b"moov") < (out.read_bytes().find(b"mdat"))  # faststart


# ----- AC-6, AC-7, AC-8 --------------------------------------------------------------------------------
def test_post_then_ready_then_serve(api: Api, tiny_mp4: Path, fake: FakeFfmpeg) -> None:
    job = finish(api, tiny_mp4)
    assert api.json("GET", f"api/jobs/{job}/export")[1]["state"] == "none"
    assert api.request("GET", f"api/jobs/{job}/export.mp4")[0] == 404  # not ready
    fake.gate = threading.Event()
    status, doc = api.json("POST", f"api/jobs/{job}/export")
    assert (status, doc["state"]) == (202, "queued")
    wait_state(api, job, ("rendering",))
    assert api.json("POST", f"api/jobs/{job}/export")[0] == 202  # already running: no second render
    assert api.request("GET", f"api/jobs/{job}/export.mp4")[0] == 404
    fake.gate.set()
    doc = wait_state(api, job, ("ready", "failed"))
    assert doc["state"] == "ready" and doc["url"] == f"api/jobs/{job}/export.mp4" and doc["bytes"] == 4000
    assert (doc["burned"]["score"], doc["burned"]["grade"], doc["burned"]["faults"]) == (77, "C", 4)
    assert len(fake.cmds) == 1
    status, doc2 = api.json("POST", f"api/jobs/{job}/export")
    assert (status, doc2["state"]) == (200, "ready") and len(fake.cmds) == 1
    status, hdr, body = api.request("GET", f"api/jobs/{job}/export.mp4")
    assert (status, hdr["content-type"], hdr["accept-ranges"], body) == (200, "video/mp4", "bytes", b"x" * 4000)
    status, hdr, body = api.request("GET", f"api/jobs/{job}/export.mp4", headers={"Range": "bytes=10-19"})
    assert (status, body, hdr["content-range"]) == (206, b"x" * 10, "bytes 10-19/4000")
    assert api.request("HEAD", f"api/jobs/{job}/export.mp4")[0] == 200
    saved = json.loads((api.app.queue.job_dir(job) / "export" / "status.json").read_text())
    assert saved["state"] == "ready"


@pytest.mark.parametrize("case", ["unfinished", "trainer_job", "no_follower", "no_trainer", "no_analysis", "no_result"])
def test_refusals_are_409(api: Api, tiny_mp4: Path, fake: FakeFfmpeg, case: str) -> None:
    hold = threading.Event()
    if case == "unfinished":
        job = api.app.queue.submit("follow", lambda ctx: (hold.wait(10), {"result": RESULT})[1], entry_id=ENTRY)["id"]
    else:
        opts = {"trainer_job": {"kind": "trainer"}, "no_follower": {"follower": False}, "no_trainer": {"trainer": False},
                "no_analysis": {"analysis": False}, "no_result": {"result": {}}}[case]
        job = finish(api, tiny_mp4, **opts)
    status, doc = api.json("POST", f"api/jobs/{job}/export")
    assert status == 409 and doc["message"] and "/" not in doc["message"]
    assert fake.cmds == []
    hold.set()


def test_unknown_and_malformed_jobs_are_404(api: Api, fake: FakeFfmpeg) -> None:
    for path in ("aaaaaaaaaaaa/export", "not-a-job/export", "..%2f..%2fetc/export", "aaaaaaaaaaaa/export.mp4"):
        assert api.request("GET", f"api/jobs/{path}")[0] == 404
    assert api.request("POST", "api/jobs/aaaaaaaaaaaa/export")[0] == 404


def test_other_methods_and_other_routes(api: Api, tiny_mp4: Path, fake: FakeFfmpeg) -> None:
    job = finish(api, tiny_mp4)
    assert api.request("DELETE", f"api/jobs/{job}/export")[0] == 405
    assert api.request("POST", f"api/jobs/{job}/export.mp4")[0] == 405
    assert api.json("GET", f"api/jobs/{job}")[0] == 200  # the plain job route is not taken over
    assert api.request("GET", f"api/jobs/{job}/other")[0] != 200


def test_failed_render_says_so_plainly_and_can_be_retried(api: Api, tiny_mp4: Path, fake: FakeFfmpeg) -> None:
    job = finish(api, tiny_mp4)
    fake.code = 1
    api.json("POST", f"api/jobs/{job}/export")
    doc = wait_state(api, job, ("failed", "ready"))
    assert doc["state"] == "failed" and doc["message"] == export_routes.MSG_FAILED and "secret" not in json.dumps(doc)
    assert api.request("GET", f"api/jobs/{job}/export.mp4")[0] == 404
    fake.code = 0
    assert api.json("POST", f"api/jobs/{job}/export")[0] == 202
    assert wait_state(api, job, ("ready", "failed"))["state"] == "ready"


def test_an_unexpected_error_in_the_thread_is_a_failed_state(api: Api, tiny_mp4: Path, fake: FakeFfmpeg,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> float:
        raise RuntimeError("secret detail")

    monkeypatch.setattr(export_clip, "render", boom)
    job = finish(api, tiny_mp4)
    api.json("POST", f"api/jobs/{job}/export")
    doc = wait_state(api, job, ("failed",))
    assert "secret" not in json.dumps(doc)


# ----- AC-9 ----------------------------------------------------------------------------------------
def test_stale_disk_states(api: Api, tiny_mp4: Path, fake: FakeFfmpeg) -> None:
    job = finish(api, tiny_mp4)
    directory = api.app.queue.job_dir(job) / "export"
    directory.mkdir()
    for state in ("queued", "rendering"):
        (directory / "status.json").write_text(json.dumps({"state": state}))
        doc = api.json("GET", f"api/jobs/{job}/export")[1]
        assert (doc["state"], doc["message"]) == ("failed", export_routes.MSG_INTERRUPTED)
    (directory / "status.json").write_text(json.dumps({"state": "ready", "url": "x"}))
    assert api.json("GET", f"api/jobs/{job}/export")[1]["state"] == "none"  # the clip file is gone
    (directory / "export.mp4").write_bytes(b"y" * 10)
    assert api.json("GET", f"api/jobs/{job}/export")[1]["state"] == "ready"
    assert api.request("GET", f"api/jobs/{job}/export.mp4")[2] == b"y" * 10
    (directory / "status.json").write_text("not json")
    assert api.json("GET", f"api/jobs/{job}/export")[1]["state"] == "none"


# ----- AC-10 ---------------------------------------------------------------------------------------
def test_one_render_at_a_time(api: Api, tiny_mp4: Path, fake: FakeFfmpeg) -> None:
    a, b = finish(api, tiny_mp4), finish(api, tiny_mp4)
    fake.gate = threading.Event()
    c = finish(api, tiny_mp4)
    assert api.json("POST", f"api/jobs/{a}/export")[0] == 202
    wait_state(api, a, ("rendering",))
    assert api.json("POST", f"api/jobs/{b}/export")[0] == 202
    status, doc = api.json("POST", f"api/jobs/{c}/export")  # one render runs and one waits; a third is turned away
    assert (status, doc["message"]) == (429, export_routes.MSG_BUSY)
    assert api.json("GET", f"api/jobs/{c}/export")[1]["state"] == "none"
    assert api.json("POST", f"api/jobs/{b}/export")[0] == 202  # the waiting one may ask again
    assert api.json("GET", f"api/jobs/{b}/export")[1]["state"] == "queued"
    fake.gate.set()
    assert wait_state(api, a, ("ready",))["state"] == "ready" and wait_state(api, b, ("ready",))["state"] == "ready"
    assert fake.max_active == 1


def test_section_job_passes_its_section(api: Api, tiny_mp4: Path, fake: FakeFfmpeg) -> None:
    section = {"start_ms": 1000, "end_ms": 3000, "index": 1, "count": 2}
    job = finish(api, tiny_mp4, section=section)
    api.json("POST", f"api/jobs/{job}/export")
    wait_state(api, job, ("ready",))
    assert "-ss" in fake.cmds[0]


@pytest.mark.parametrize("cue", ["Lift 20% higher", "Back\\straight %{pts} %%"])
def test_caption_with_percent_or_backslash_is_drawn(tmp_path: Path, tiny_mp4: Path, cue: str) -> None:
    """drawtext expansion is off: `%` and a backslash must not blank or eat the caption (review R1)."""
    facts = export_clip.facts_from({"result": RESULT}, {"faults": [{"cue": cue, "text": cue, "at_s": 0.1}]})
    out = tmp_path / "export" / "export.mp4"
    export_clip.render(tiny_mp4, tiny_mp4, out, facts)
    cap_y = export_clip.HEADER_H + 2 * export_clip.PANEL_H + 28
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-ss", "1", "-i", str(out), "-frames:v", "1", "-vf",
         f"crop=1080:70:0:{cap_y},format=gray", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    assert len(raw) == 1080 * 70 and sum(1 for b in raw if b > 150) > 500  # the caption pixels are lit


def test_command_turns_expansion_off() -> None:
    facts = export_clip.facts_from({"result": RESULT}, {"faults": FAULTS})
    assert " ".join(export_clip.build_command(Path("/t"), Path("/f"), Path("/o"), 5.0, facts)).count("expansion=none") == \
        len(export_clip.texts_for(facts))


def test_landing_media_is_small() -> None:
    web = Path(__file__).resolve().parents[2] / "web" / "media"
    assert 0 < (web / "landing-loop.mp4").stat().st_size < 2 * 1024 * 1024
    assert 0 < (web / "landing-poster.jpg").stat().st_size < 100 * 1024


def test_real_clip_through_the_route(api: Api, tmp_path: Path) -> None:
    """Route, thread and the real ffmpeg together on a tiny synthetic job."""
    job = finish(api, ffmpeg_video(tmp_path / "s.mp4", 2))
    assert api.json("POST", f"api/jobs/{job}/export")[0] == 202
    doc = wait_state(api, job, ("ready", "failed"), timeout=120)
    assert doc["state"] == "ready", doc
    status, hdr, body = api.request("GET", f"api/jobs/{job}/export.mp4")
    assert status == 200 and len(body) == doc["bytes"] and body[4:8] == b"ftyp"
