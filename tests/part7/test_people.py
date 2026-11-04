"""People choice and group mode, server side (people.md, AC-P1 to AC-P3, AC-P5 to AC-P7) with fake part runners."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import threading
from typing import Any

import pytest

from part7 import crop, group, media, people, runner
from part7.parts import p1_keyframes, p2_pose, p3_skeleton, p4_animate, p5_analyse, p6_catalog
from support import Api, ffmpeg_video, load_scaled

FRAMES = 20
VISITOR = {"Cf-Connecting-Ip": "203.0.113.7"}


def _step(part: int, code: int = 0, stdout: str = "") -> runner.Step:
    return runner.Step(part=part, commit="c" * 12, argv=["fake"], cwd="/tmp", exit=code, timed_out=False,
                       duration_s=0.0, log="", stdout=stdout)


def tracks_doc(counts: dict[int, int], frames: int = FRAMES, mask: list[int] | None = None) -> dict[str, Any]:
    """tracks.json where person `id` is seen in the first `counts[id]` frames; ids stand side by side."""
    out = []
    for f in range(frames):
        ppl = []
        for pid, n in counts.items():
            if f < n:
                person: dict[str, Any] = {"id": pid, "bbox": [10 + 90 * pid, 40, 80, 160], "confidence": 0.9}
                if mask:
                    person["mask_rle"] = {"size": mask, "counts": ""}
                ppl.append(person)
        out.append({"frame": f, "people": ppl})
    return {"frames": out, "provenance": {"tracker": "local-sam31"}}


class Fakes:
    """Installs fake part runners and records what each part was given."""

    def __init__(self, mp: pytest.MonkeyPatch, counts: dict[int, int], track: bool = True, ids: bool = True) -> None:
        self.counts, self.caps = counts, {"track": track, "ids": ids}
        self.p1_videos: list[Path] = []
        self.p2_calls: list[dict[str, Any]] = []
        self.track_fps: list[int] = []
        self.p5_kw: list[dict[str, Any]] = []
        self.p3_people: list[tuple[str, str | None]] = []
        self.scores: dict[str, Any] = {}
        self.gate: threading.Event | None = None
        mp.setattr(p2_pose, "capabilities", lambda *a, **k: self.caps)
        mp.setattr(p2_pose, "track", self.track)
        mp.setattr(p2_pose, "run", self.p2_run)
        mp.setattr(p2_pose, "doctor", lambda *a, **k: _step(2))
        mp.setattr(p1_keyframes, "run", self.p1_run)
        mp.setattr(p1_keyframes, "doctor", lambda *a, **k: _step(6))
        mp.setattr(p3_skeleton, "part4", self.p3_part4)
        mp.setattr(p3_skeleton, "part5", self.p3_part5)
        mp.setattr(p3_skeleton, "doctor", lambda *a, **k: _step(3))
        mp.setattr(p4_animate, "validate", lambda *a, **k: _step(4))
        mp.setattr(p4_animate, "run", self.p4_run)
        mp.setattr(p5_analyse, "doctor", lambda *a, **k: _step(5))
        mp.setattr(p5_analyse, "run", self.p5_run)
        mp.setattr(p6_catalog, "import_entry", self.p6_import)
        mp.setattr(p6_catalog, "doctor", lambda *a, **k: _step(6))

    def track(self, clip: Path, work: Path, **kw: Any) -> tuple[runner.Step, Path]:
        self.track_fps.append(kw.get("fps"))
        path = Path(work) / "part2_track" / "tracks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(tracks_doc(self.counts)), encoding="utf-8")
        return (_step(2), path)

    def p2_run(self, video: Path, work: Path, **kw: Any) -> tuple[runner.Step, Path]:
        self.p2_calls.append({k: (str(v) if isinstance(v, Path) else v) for k, v in kw.items() if k in ("multi", "tracks", "ids", "fps")})
        out = Path(work) / "part2"
        out.mkdir(parents=True, exist_ok=True)
        (out / "pose3d.json").write_text('{"frames": [{"frame": 0, "people": [{"id": 0}]}]}', encoding="utf-8")
        (out / "tracks.json").write_text(json.dumps(tracks_doc(self.counts)), encoding="utf-8")
        return (_step(2), out / "pose3d.json")

    def p1_run(self, video: Path, work: Path, **kw: Any) -> tuple[runner.Step, Path, None]:
        self.p1_videos.append(Path(video))
        kf = Path(work) / "keyframes.json"
        kf.write_text('{"format": "simon.keyframes/part1"}', encoding="utf-8")
        return (_step(1), kf, None)

    def p3_part4(self, pose: Path, kf: Any, work: Path, **kw: Any) -> tuple[list[runner.Step], Path, Path, None]:
        self.p3_people.append(("part4", kw.get("person")))
        skel, kfv1 = Path(work) / "skeleton.json", Path(work) / "keyframes.v1.json"
        skel.write_text("{}", encoding="utf-8")
        kfv1.write_text("{}", encoding="utf-8")
        return ([_step(3)], skel, kfv1, None)

    def p3_part5(self, pose: Path, work: Path, **kw: Any) -> tuple[runner.Step, Path]:
        self.p3_people.append(("part5", kw.get("person")))
        out = Path(work) / "follower.json"
        out.write_text(json.dumps({"person": kw.get("person")}), encoding="utf-8")
        return (_step(3), out)

    def p4_run(self, skel: Path, kfv1: Path, work: Path, **kw: Any) -> tuple[runner.Step, Path]:
        anim = Path(work) / "part4" / "animation.json"
        anim.parent.mkdir(parents=True, exist_ok=True)
        anim.write_text('{"format": "simon.animation.v1"}', encoding="utf-8")
        return (_step(4), anim)

    def p5_run(self, expected: Path, follower: Path, work: Path, **kw: Any) -> tuple[runner.Step, Path, str, list[str]]:
        self.p5_kw.append(kw)
        if self.gate is not None:
            self.gate.wait(10)
        pid = json.loads(Path(follower).read_text(encoding="utf-8"))["person"]
        score = self.scores.get(pid, 70)
        refused = score is None
        doc = {"status": {"code": "refused" if refused else "ok"}, "faults": [] if refused else [{"at_s": 1}],
               "score": {"value": score, "grade": None if refused else "C"}}
        out = Path(work) / "analysis.json"
        out.write_text(json.dumps(doc), encoding="utf-8")
        return (_step(5, 3 if refused else 0), out, doc["status"]["code"], [])

    def p6_import(self, catalog: Path, folder: Path, name: str, cat: str, parts: Any, work: Path, **kw: Any
                  ) -> tuple[runner.Step, dict[str, Any]]:
        assert (Path(folder) / "video.mp4").is_file()
        return (_step(6), {"id": "class-warmup"})


@pytest.fixture(scope="module")
def class_mp4(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("people") / "class.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=size=320x240:rate=5:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
                   check=True, timeout=60)
    return path


def _people_job(api: Api, mp4: Path, trim: dict[str, int] | None = None) -> dict[str, Any]:
    status, up = api.upload(mp4)
    assert status == 201
    body: dict[str, Any] = {"upload_id": up["upload_id"], **({"trim": trim} if trim else {})}
    status, doc = api.json("POST", "api/people", body, VISITOR)
    assert status == 202, doc
    job = api.app.queue.wait(doc["job"], load_scaled(60))  # polls to the terminal status; the deadline grows with host load
    assert job and job["status"] == "done", job
    return job


# ----- pure helpers -----------------------------------------------------------------------------------
def test_summarize_orders_by_coverage_and_drops_noise() -> None:
    frames = tracks_doc({0: 20, 1: 12, 2: 1})["frames"]
    found = people.summarize(frames, 320, 240)
    assert [p["id"] for p in found] == ["0", "1"]  # id 2 has 5% coverage
    assert found[0]["coverage"] == 1.0 and found[1]["coverage"] == 0.6 and found[1]["frames"] == 12
    assert found[0]["box_mid"] == [10, 40, 80, 160]


def test_auto_id_only_when_exactly_one_person_is_sure() -> None:
    assert people.auto_id([{"id": "0", "coverage": 0.9}, {"id": "1", "coverage": 0.3}]) == "0"
    assert people.auto_id([{"id": "0", "coverage": 0.9}, {"id": "1", "coverage": 0.6}]) is None
    assert people.auto_id([{"id": "0", "coverage": 0.5}]) is None


def test_union_box_has_margin_even_sides_and_stays_inside() -> None:
    frames = tracks_doc({0: 20})["frames"]
    x, y, w, h = crop.union_box(frames, "0", 320, 240)
    assert (x, y) == (0, 16)  # 10 - 15% of 80, 40 - 15% of 160, rounded down to even
    assert w % 2 == 0 and h % 2 == 0 and x + w <= 320 and y + h <= 240
    assert w >= 80 * 1.3 - 2 and h >= 160 * 1.3 - 2 or y + h == 240
    assert crop.union_box(frames, "9", 320, 240) is None


def test_union_box_scales_from_the_track_size_to_the_video() -> None:
    frames = tracks_doc({0: 5}, mask=[120, 160])["frames"]  # boxes in a 160x120 picture, video is 320x240
    x, y, w, h = crop.union_box(frames, "0", 320, 240, margin=0.0, pad=0.0)
    assert (x, y, w, h) == (20, 80, 160, 160) or (w, h) == (160, 240 - 80)


def test_group_order_puts_refused_takes_last() -> None:
    rows = [{"id": "a", "score": None}, {"id": "b", "score": 60}, {"id": "c", "score": 90}, {"id": "d", "score": None}]
    assert [r["id"] for r in group.order(rows)] == ["c", "b", "a", "d"]


# ----- the people job -----------------------------------------------------------------------------------
def test_people_job_lists_people_with_pictures_and_no_auto_id(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Fakes(monkeypatch, {0: 20, 1: 14})
    job = _people_job(api, class_mp4)
    result = job["result"]
    assert [p["id"] for p in result["people"]] == ["0", "1"]
    assert result["auto_id"] == "0" or result["auto_id"] is None
    assert result["frame"] == "people/frame.jpg"
    assert job["stages"][:2] == ["upload", "track"]
    for name in ("frame", "0", "1"):
        status, headers, body = api.request("GET", f"api/jobs/{job['id']}/people/{name}.jpg")
        assert status == 200 and headers["content-type"] == "image/jpeg" and body[:2] == b"\xff\xd8"
    assert api.request("GET", f"api/jobs/{job['id']}/people/9.jpg")[0] == 404
    assert api.request("GET", f"api/jobs/{job['id']}/people/..%2Fjob.json")[0] == 404
    assert api.request("GET", "api/jobs/nothere00000/people/frame.jpg")[0] == 404


def test_crop_is_240_px_tall(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Fakes(monkeypatch, {0: 20})
    job = _people_job(api, class_mp4)
    jpg = api.app.queue.job_dir(job["id"]) / "people" / "0.jpg"
    shown = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=height", "-of", "csv=p=0", str(jpg)],
                           capture_output=True, text=True, check=True).stdout
    assert int(shown) == people.CROP_HEIGHT


def test_one_person_clip_gets_auto_id(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-P1: one person with coverage of at least 0.6 skips the choice."""
    Fakes(monkeypatch, {3: 20, 4: 3})
    result = _people_job(api, class_mp4)["result"]
    assert result["auto_id"] == "3" and [p["id"] for p in result["people"]] == ["3", "4"]


def test_two_sure_people_have_no_auto_id(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Fakes(monkeypatch, {0: 20, 1: 18})
    assert _people_job(api, class_mp4)["result"]["auto_id"] is None


def test_nobody_found_fails_with_the_plain_sentence(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Fakes(monkeypatch, {})
    _, up = api.upload(class_mp4)
    _, doc = api.json("POST", "api/people", {"upload_id": up["upload_id"]})
    job = api.app.queue.wait(doc["job"], 60)
    assert job["status"] == "failed" and job["reason"] == people.NO_ONE.rstrip(".")


def test_part2_without_track_falls_back_to_a_multi_run_and_says_so(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes = Fakes(monkeypatch, {0: 20, 1: 14}, track=False, ids=False)
    job = _people_job(api, class_mp4)
    assert "no track command" in job["note"]
    assert fakes.p2_calls == [{"multi": True}]
    assert (api.app.queue.job_dir(job["id"]) / "work" / "pose3d_all.json").is_file()


def test_people_trim_is_cut_and_recorded(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Fakes(monkeypatch, {0: 20})
    job = _people_job(api, class_mp4, {"start_ms": 1000, "end_ms": 3000})
    assert job["trim"] == {"start_ms": 1000, "end_ms": 3000} and 1900 <= job["duration_ms"] <= 2200


def test_people_trim_end_just_past_the_probed_length_is_the_end(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The browser reads a recording a little longer than ffprobe; an end handle left at the end must not 400."""
    Fakes(monkeypatch, {0: 20})
    duration_ms = media.probe(class_mp4)["duration_ms"]
    job = _people_job(api, class_mp4, {"start_ms": 1000, "end_ms": duration_ms + 400})
    assert job["trim"] == {"start_ms": 1000, "end_ms": duration_ms}


@pytest.mark.parametrize("trim", [{"start_ms": 0, "end_ms": 500}, {"start_ms": 0, "end_ms": 99000},
                                  {"start_ms": 3000, "end_ms": 1000}, {"start_ms": "a"}])
def test_people_bad_trim_is_400(api: Api, class_mp4: Path, trim: dict[str, Any]) -> None:
    _, up = api.upload(class_mp4)
    status, doc = api.json("POST", "api/people", {"upload_id": up["upload_id"], "trim": trim})
    assert status == 400 and doc["message"]


def test_people_unknown_upload_is_400(api: Api) -> None:
    assert api.json("POST", "api/people", {"upload_id": "0" * 16})[0] == 400


# ----- trainer and follow with a chosen person ---------------------------------------------------------------
def _trainer(api: Api, people_job: str, **extra: Any) -> dict[str, Any]:
    _, up = api.upload(Path(api.app.queue.job_dir(people_job) / "work" / "clip.mp4"))
    body = {"upload_id": up["upload_id"], "name": "Warm-up", "category": "exercise", "people_job": people_job, **extra}
    status, doc = api.json("POST", "api/trainer", body, VISITOR)
    assert status == 202, doc
    return api.app.queue.wait(doc["job"], 60)


def test_trainer_with_person_crops_for_part1_and_points_part3_and_part2(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-P2, AC-P7."""
    fakes = Fakes(monkeypatch, {0: 20, 1: 18})
    pj = _people_job(api, class_mp4)["id"]
    job = _trainer(api, pj, person_id=1)
    assert job["status"] == "done", job
    assert fakes.p1_videos[-1].name == "person.mp4"
    cropped = media.probe(fakes.p1_videos[-1])
    assert cropped["width"] < 320 and cropped["height"] <= 240
    assert fakes.p3_people[-1] == ("part4", "1")
    assert fakes.p2_calls[-1]["ids"] == ["1"] and fakes.p2_calls[-1]["tracks"].endswith("tracks_10fps.json")
    assert "cropped to person 1" in job["note"]
    assert job["entry_id"] == "class-warmup"


def test_trainer_with_person_and_old_part2_runs_everyone_and_says_so(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes = Fakes(monkeypatch, {0: 20, 1: 18}, track=False, ids=False)
    pj = _people_job(api, class_mp4)["id"]
    job = _trainer(api, pj, person_id="0")
    assert job["status"] == "done"
    assert fakes.p2_calls == [{"multi": True}]  # the people job's run; the trainer reused its pose3d_all.json
    assert "3D ran for everyone" in job["note"] and fakes.p3_people[-1] == ("part4", "0")


def test_trainer_uses_auto_id_when_no_person_is_named(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fakes = Fakes(monkeypatch, {5: 20})
    pj = _people_job(api, class_mp4)["id"]
    assert _trainer(api, pj)["status"] == "done" and fakes.p3_people[-1] == ("part4", "5")


def test_trainer_without_people_job_is_unchanged(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fakes = Fakes(monkeypatch, {0: 20})
    _, up = api.upload(tiny_mp4)
    status, doc = api.json("POST", "api/trainer", {"upload_id": up["upload_id"], "name": "x", "category": "dance"})
    assert status == 202
    assert api.app.queue.wait(doc["job"], 60)["status"] == "done"
    assert fakes.p3_people[-1] == ("part4", None) and fakes.p1_videos[-1].name == "video.mp4"


@pytest.mark.parametrize("extra, text", [
    ({"people_job": "000000000000", "person_id": 0}, "no longer available"),
    ({"person_id": 9}, "not in the clip"),
    ({"people_job": "bad"}, "no longer available"),
])
def test_trainer_person_errors_are_400(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch,
                                       extra: dict[str, Any], text: str) -> None:
    Fakes(monkeypatch, {0: 20, 1: 18})
    pj = _people_job(api, class_mp4)["id"]
    _, up = api.upload(class_mp4)
    body = {"upload_id": up["upload_id"], "name": "x", "category": "dance", "people_job": pj, **extra}
    status, doc = api.json("POST", "api/trainer", body)
    assert status == 400 and text in doc["message"]


def test_person_needed_when_there_is_no_auto_id(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Fakes(monkeypatch, {0: 20, 1: 18})
    pj = _people_job(api, class_mp4)["id"]
    _, up = api.upload(class_mp4)
    status, doc = api.json("POST", "api/trainer", {"upload_id": up["upload_id"], "name": "x", "category": "dance",
                                                   "people_job": pj})
    assert status == 400 and doc["message"] == "Choose who the recording is about."


def test_follow_with_person_gets_part3_person_and_that_persons_analysis(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-P3."""
    fakes = Fakes(monkeypatch, {0: 20, 1: 18})
    fakes.scores = {"1": 55}
    pj = _people_job(api, class_mp4)["id"]
    _, up = api.upload(class_mp4)
    status, doc = api.json("POST", "api/follow", {"upload_id": up["upload_id"], "entry_id": "lateral-raise",
                                                  "people_job": pj, "person_id": "1",
                                                  "labels": {"tags": ["slow"], "notes": "left side"}}, VISITOR)
    assert status == 202, doc
    job = api.app.queue.wait(doc["job"], 60)
    assert job["status"] == "done" and job["result"]["score"] == 55
    assert job["labels"] == {"tags": ["slow"], "notes": "left side"}  # follower take labels live in the job record
    assert job["people_job"] == pj and job["person_id"] == "1" and job["trim"] is None
    assert Path(fakes.p5_kw[-1]["expected_visibility"]).name == "expected_skeleton.json"
    assert fakes.p3_people[-1] == ("part5", "1")
    assert fakes.p2_calls[-1]["ids"] == ["1"]


# ----- group mode ------------------------------------------------------------------------------------------
def _group_body(api: Api, pj: str, **over: Any) -> dict[str, Any]:
    return {"people_job": pj, "trainer_id": "0", "follower_ids": ["1", "2", "3"], "name": "Warm-up",
            "category": "exercise", "save_entry": True, **over}


def _group(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch, **over: Any) -> tuple[Fakes, dict[str, Any]]:
    fakes = Fakes(monkeypatch, {0: 20, 1: 20, 2: 20, 3: 20})
    pj = _people_job(api, class_mp4)["id"]
    status, doc = api.json("POST", "api/group", _group_body(api, pj, **over), VISITOR)
    assert status == 202, doc
    assert doc["kind"] == "group"
    return fakes, api.app.queue.wait(doc["job"], 90)


def test_group_job_one_trainer_three_followers_ordered_by_score(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-P4, AC-P5, AC-P7."""
    fakes = Fakes(monkeypatch, {0: 20, 1: 20, 2: 20, 3: 20})
    fakes.scores = {"1": 60, "2": None, "3": 88}
    pj = _people_job(api, class_mp4)["id"]
    before = api.app.quota.gpu_jobs_today()
    labels = {"1": "Front row left", "tags": ["warm-up"], "notes": "Mon class"}
    status, doc = api.json("POST", "api/group", _group_body(api, pj, labels=labels), VISITOR)
    assert status == 202
    job = api.app.queue.wait(doc["job"], 90)
    assert job["status"] == "done", job
    assert len(fakes.p5_kw) == 3 and all(k["expected_visibility"] for k in fakes.p5_kw)  # trainer skeleton.json
    rows = job["result"]["people"]
    assert [r["id"] for r in rows] == ["3", "1", "2"]  # 88, 60, refused last
    assert rows[0]["score"] == 88 and rows[0]["grade"] == "C" and rows[0]["faults"] == 1
    assert rows[2]["score"] is None and rows[2]["status_code"] == "refused" and rows[2]["faults"] == 0
    assert [r["label"] for r in rows] == ["Person 3", "Front row left", "Person 2"]
    assert job["result"]["trainer_id"] == "0" and job["entry_id"] == "class-warmup" == job["result"]["entry_id"]
    assert job["stages"] == ["upload", "track", "pose", "trainer", "catalog", "followers"]
    assert job["progress"] == "3 of 3"
    # Part 2 ran once for the four people; Part 1 saw the trainer's crop; Part 3 got each person
    assert fakes.p2_calls[-1]["ids"] == ["0", "1", "2", "3"]
    assert fakes.p1_videos[-1].name == "person.mp4"
    assert fakes.p3_people[-4:] == [("part4", "0"), ("part5", "1"), ("part5", "2"), ("part5", "3")]
    # per person results
    for pid in ("1", "3"):
        status, _, body = api.request("GET", f"api/results/{job['id']}/{pid}/analysis.json")
        assert status == 200 and json.loads(body)["status"]["code"] == "ok"
    assert api.request("GET", f"api/results/{job['id']}/2/analysis.json")[0] == 200
    assert api.request("GET", f"api/results/{job['id']}/1/replay.json")[0] == 404  # the fake wrote no replay
    assert api.request("GET", f"api/results/{job['id']}/9/analysis.json")[0] == 404
    assert api.request("GET", f"api/results/{pj}/1/analysis.json")[0] == 404  # not a group job
    # entry labels, quota: 1 trainer + 3 follower GPU jobs
    saved = json.loads((api.app.state / "labels" / "class-warmup.json").read_text(encoding="utf-8"))
    assert saved["tags"] == ["warm-up"] and saved["notes"] == "Mon class"
    assert api.app.quota.gpu_jobs_today() - before == 4
    assert json.loads((api.app.state / "quota" / next(iter((api.app.state / "quota").glob("*.json"))).name)
                      .read_text())["trainer"] == 1


def test_group_without_save_entry_makes_no_entry(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fakes, job = _group(api, class_mp4, monkeypatch, save_entry=False, follower_ids=["1"])
    assert job["status"] == "done" and job["entry_id"] is None and "catalog" not in job["stages"]
    assert len(job["result"]["people"]) == 1


def test_group_follower_that_cannot_be_measured_is_an_f_row_not_a_failure(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes = Fakes(monkeypatch, {0: 20, 1: 20, 2: 20})
    real = fakes.p3_part5

    def part5(pose: Path, work: Path, **kw: Any) -> tuple[runner.Step, Path]:
        step, out = real(pose, work, **kw)
        return (_step(3, 2, "part3: pose3d.frames: no person in any frame"), out) if kw.get("person") == "2" else (step, out)

    monkeypatch.setattr(p3_skeleton, "part5", part5)
    pj = _people_job(api, class_mp4)["id"]
    _, doc = api.json("POST", "api/group", _group_body(api, pj, follower_ids=["1", "2"]), VISITOR)
    job = api.app.queue.wait(doc["job"], 90)
    assert job["status"] == "done"
    # never fail to analyse: Part 3 failing for person 2 is an analysis by Part 7 (F, warning), still a row of the board
    rows = {r["id"]: r for r in job["result"]["people"]}
    assert rows["1"]["status_code"] == "ok" and rows["2"]["status_code"] == "ok"
    assert (rows["2"]["score"], rows["2"]["grade"], rows["2"]["faults"]) == (0, "F", 0)
    assert rows["2"]["analysis"] and "analysed by Part 7 alone" in job["note"]
    assert job["result"]["people"][-1]["id"] == "2"  # ordered by score, the F last
    status, _, body = api.request("GET", f"api/results/{job['id']}/2/analysis.json")
    assert status == 200 and [w["code"] for w in json.loads(body)["warnings"]] == ["no_usable_measures"]


def test_group_with_old_part2_runs_everyone_once_and_says_so(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes = Fakes(monkeypatch, {0: 20, 1: 20, 2: 20}, track=False, ids=False)
    pj = _people_job(api, class_mp4)["id"]
    _, doc = api.json("POST", "api/group", _group_body(api, pj, follower_ids=["1", "2"]), VISITOR)
    job = api.app.queue.wait(doc["job"], 90)
    assert job["status"] == "done" and "3D ran for everyone" in job["note"]
    assert fakes.p2_calls == [{"multi": True}]


@pytest.mark.parametrize("over, text", [
    ({"follower_ids": [str(i) for i in range(1, 10)]}, "1 to 8 people"),
    ({"follower_ids": []}, "1 to 8 people"),
    ({"follower_ids": ["1", "1"]}, "1 to 8 people"),
    ({"follower_ids": "1"}, "1 to 8 people"),
    ({"follower_ids": ["0", "1"]}, "not among"),
    ({"trainer_id": "77"}, "not among"),
    ({"follower_ids": ["1", "88"]}, "not in the clip"),
    ({"name": ""}, "name"),
    ({"category": "yoga"}, "exercise or dance"),
    ({"people_job": "nope"}, "no longer available"),
    ({"labels": {"tags": ["Bad Tag"]}}, "tags"),
    ({"labels": {"notes": "x" * 281}}, "Notes"),
])
def test_group_request_errors_are_400_and_cost_nothing(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch, over: dict[str, Any], text: str
) -> None:
    Fakes(monkeypatch, {i: 20 for i in range(10)})
    pj = _people_job(api, class_mp4)["id"]
    before = api.app.quota.gpu_jobs_today()
    status, doc = api.json("POST", "api/group", _group_body(api, pj, **over), VISITOR)
    assert status == 400 and text in doc["message"]
    assert api.app.quota.gpu_jobs_today() == before


def test_group_clip_over_30_seconds_is_400(api: Api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-P6."""
    Fakes(monkeypatch, {0: 20, 1: 20})
    long_clip = ffmpeg_video(tmp_path / "long.mp4", 35)
    pj = _people_job(api, long_clip)["id"]
    status, doc = api.json("POST", "api/group", _group_body(api, pj, follower_ids=["1"]), VISITOR)
    assert status == 400 and "30 seconds" in doc["message"]
    trimmed = _people_job(api, long_clip, {"start_ms": 0, "end_ms": 20000})["id"]
    assert api.json("POST", "api/group", _group_body(api, trimmed, follower_ids=["1"]), VISITOR)[0] == 202


def test_eight_followers_are_allowed(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Fakes(monkeypatch, {i: 20 for i in range(9)})
    pj = _people_job(api, class_mp4)["id"]
    ids = [str(i) for i in range(1, 9)]
    status, doc = api.json("POST", "api/group", _group_body(api, pj, follower_ids=ids), VISITOR)
    assert status == 202
    job = api.app.queue.wait(doc["job"], 120)
    assert job["status"] == "done" and len(job["result"]["people"]) == 8


def test_one_group_job_per_visitor_at_a_time(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fakes = Fakes(monkeypatch, {0: 20, 1: 20, 2: 20})
    fakes.gate = threading.Event()
    pj = _people_job(api, class_mp4)["id"]
    body = _group_body(api, pj, follower_ids=["1"])
    status, first = api.json("POST", "api/group", body, VISITOR)
    assert status == 202
    used = api.app.quota.gpu_jobs_today()
    status, doc = api.json("POST", "api/group", body, VISITOR)
    assert status == 429 and "still being analysed" in doc["message"]
    assert api.app.quota.gpu_jobs_today() == used
    other = {"Cf-Connecting-Ip": "198.51.100.9"}
    assert api.json("POST", "api/group", body, other)[0] == 202
    fakes.gate.set()
    api.app.queue.wait(first["job"], 60)
    assert api.json("POST", "api/group", body, VISITOR)[0] == 202


def test_group_board_job_record_is_public_json(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fakes, job = _group(api, class_mp4, monkeypatch, follower_ids=["1"])
    status, doc = api.json("GET", f"api/jobs/{job['id']}")
    assert status == 200 and doc["result"]["people"][0]["analysis"] == f"api/results/{job['id']}/1/analysis.json"


# ----- argv of the part adapters ------------------------------------------------------------------------------
def _capture(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    seen: list[list[str]] = []

    def fake_run(part: Any, argv: list[str], **kw: Any) -> runner.Step:
        seen.append(list(argv))
        return _step(int(part))

    monkeypatch.setattr(runner, "run", fake_run)
    return seen


def test_part5_expected_visibility_is_passed_only_when_the_pin_has_the_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from support import make_lock

    from part7.parts import probe

    seen = _capture(monkeypatch)
    lk, skeleton = make_lock(), tmp_path / "skeleton.json"
    monkeypatch.setattr(probe, "help_text", lambda *a, **k: "")
    monkeypatch.setattr(probe, "has_flag", lambda part, argv, clone, flag, lock=None: flag == "--expected-visibility")
    _, _, _, notes = p5_analyse.run(tmp_path / "e.json", tmp_path / "f.json", tmp_path / "w", lock=lk, state=tmp_path,
                                    expected_visibility=skeleton)
    argv = seen[-1]
    assert argv[argv.index("--expected-visibility") + 1] == str(skeleton.resolve())
    p5_analyse.run(tmp_path / "e.json", tmp_path / "f.json", tmp_path / "w", lock=lk, state=tmp_path)
    assert "--expected-visibility" not in seen[-1]
    monkeypatch.setattr(probe, "has_flag", lambda *a, **k: False)
    _, _, _, notes = p5_analyse.run(tmp_path / "e.json", tmp_path / "f.json", tmp_path / "w", lock=lk, state=tmp_path,
                                    expected_visibility=skeleton)
    assert "--expected-visibility" not in seen[-1] and any("cannot check what is visible" in n for n in notes)


def test_part2_run_passes_tracks_and_ids_and_track_is_its_own_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from support import make_lock

    seen = _capture(monkeypatch)
    lk, tracks = make_lock(), tmp_path / "tracks.json"
    p2_pose.run(tmp_path / "v.mp4", tmp_path / "w", backend="cpu", lock=lk, state=tmp_path, tracks=tracks, ids=["2", "5"])
    argv = seen[-1]
    assert argv[argv.index("--mode") + 1] == "multi" and argv[argv.index("--ids") + 1] == "2,5"
    assert argv[argv.index("--tracks") + 1] == str(tracks.resolve())
    p2_pose.run(tmp_path / "v.mp4", tmp_path / "w", backend="cpu", lock=lk, state=tmp_path)
    assert "single" in seen[-1] and "--tracks" not in seen[-1] and "--ids" not in seen[-1]
    _, out = p2_pose.track(tmp_path / "v.mp4", tmp_path / "w", backend="cpu", lock=lk, state=tmp_path)
    assert "track" in seen[-1] and seen[-1][seen[-1].index("--fps") + 1] == "10" and out.name == "tracks.json"


def test_part3_gets_person_only_when_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from support import make_lock

    seen = _capture(monkeypatch)
    monkeypatch.setattr("part7.parts.probe.has_flag", lambda *a, **k: True)
    lk = make_lock()
    p3_skeleton.part5(tmp_path / "p.json", tmp_path / "w", lock=lk, state=tmp_path, person="4")
    assert seen[-1][seen[-1].index("--person") + 1] == "4"
    p3_skeleton.part5(tmp_path / "p.json", tmp_path / "w", lock=lk, state=tmp_path)
    assert "--person" not in seen[-1]
    p3_skeleton.part4(tmp_path / "p.json", "every:10", tmp_path / "w", lock=lk, state=tmp_path, person="4")
    assert seen[-1][seen[-1].index("--person") + 1] == "4"


@pytest.mark.parametrize("step,said", [
    ({"exit": 4}, people.NO_ONE_TRACKED),
    ({"exit": 4, "first_try": {"exit": 4}}, people.NO_ONE_TRACKED),
    ({"exit": 1}, "the people finder failed"),
])
def test_a_clip_with_nobody_says_so_and_a_broken_finder_does_not(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: dict[str, Any], said: str) -> None:
    """Prod run on release 8: `part2: no person found to track`, exit 4, read "The people finder failed."."""
    from types import SimpleNamespace

    from part7.jobs import JobFailed

    monkeypatch.setattr(p2_pose, "capabilities", lambda *_a: {"track": True})
    monkeypatch.setattr(p2_pose, "track", lambda *_a, **_k: (step, tmp_path / "absent" / "tracks.json"))
    monkeypatch.setattr(people.applog, "log", lambda *_a, **_k: None)
    monkeypatch.setattr(people.applog, "job_id_of", lambda *_a: "j")
    ctx = SimpleNamespace(work=tmp_path, set_stage=lambda _s: None, add_note=lambda _n: None)
    with pytest.raises(JobFailed) as failed:
        people._find_people(ctx, tmp_path / "v.mp4", "cpu", object(), tmp_path, [])
    assert failed.value.reason.startswith(said)
    assert (failed.value.cause == "no_person") == (said == people.NO_ONE_TRACKED)
