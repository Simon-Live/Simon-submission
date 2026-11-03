"""TICKET-313: a floor-work entry tells Part 3 (`run --floor-work`), and nothing else changes (docs/specs/floor-work.md)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import json

from auth_support import authenv, get, post, sign_in  # noqa: F401  (authenv: a fixture used by name)
from part7 import auth, chain, group, labels, modules, processor, runner
from part7.parts import p3_skeleton, probe
from support import Api, ffmpeg_video, make_lock
from test_server import _fake_follower, _fake_trainer, _upload
from test_trainer_chain_and_harness import seams, step  # noqa: F401  (seams: a fixture used by name)

# The real `--view part5` file of Part 3 at 73ed073 (`python -m part3 run --in fixtures/input/part2-single/pose3d.json
# --view part5 --fps 30 --floor-work`), cut to its first 3 frames. It has no `frame` block, with the flag or without.
PART5_REAL = Path(__file__).parent / "fixtures" / "part3-73ed073-part5-floor-work.json"


class FakePart3:
    """Stands in for `python -m part3`: `--help` lists `--floor-work` only when `offers` is true; `doctor` rejects it."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, offers: bool) -> None:
        self.argvs: list[list[str]] = []
        self.offers = offers
        probe.clear_cache()
        monkeypatch.setattr(runner, "run", self._run)

    def _run(self, part: Any, argv: list[str], **kw: Any) -> runner.Step:
        if argv[-1] == "--help":
            text = "usage: part3 run [--keyframes-densify X]" + (" [--floor-work]" if self.offers else "")
            return step(3, 0, text)
        self.argvs.append(list(argv))
        if "doctor" in argv and "--floor-work" in argv:
            return step(3, 2, "unrecognized arguments: --floor-work")
        return step(3)

    def runs(self) -> list[list[str]]:
        return [a for a in self.argvs if "run" in a]


def _lock(tmp_path: Path) -> modules.Modules:
    lk = make_lock()
    lk.path("3").mkdir(parents=True, exist_ok=True)
    return lk


def _pose(tmp_path: Path) -> Path:
    pose = tmp_path / "pose3d.json"
    pose.write_text("{}")
    return pose


def _all_calls(tmp_path: Path, lk: modules.Modules, floor: bool) -> list[str]:
    """Every Part 3 `run` call of a trainer take (--view part4 plus the retry) and a follower take (--view part5)."""
    args, _ = p3_skeleton.floor_work_args(floor, lk)
    p3_skeleton.part4(_pose(tmp_path), "every:10", tmp_path / "w4", lock=lk, floor_args=args)
    p3_skeleton.part5(_pose(tmp_path), tmp_path / "w5", lock=lk, floor_args=args)
    return args


def test_marked_entry_passes_the_flag_on_trainer_and_follower_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePart3(monkeypatch, offers=True)
    lk = _lock(tmp_path)
    assert _all_calls(tmp_path, lk, True) == ["--floor-work"]
    views = {a[a.index("--view") + 1]: a for a in fake.runs()}
    assert "--floor-work" in views["part4"] and "--floor-work" in views["part5"]
    p3_skeleton.part4(_pose(tmp_path), "every:10", tmp_path / "w6", lock=lk, person="3", floor_args=["--floor-work"])
    people = fake.runs()[-1]  # the people path: --person with the flag
    assert people[people.index("--person") + 1] == "3" and "--floor-work" in people


def test_the_retry_after_a_180_degree_refusal_keeps_the_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePart3(monkeypatch, offers=True)
    first = fake._run
    calls = {"n": 0}

    def refuse_once(part: Any, argv: list[str], **kw: Any) -> runner.Step:
        if argv[-1] != "--help" and "run" in argv:
            calls["n"] += 1
            if calls["n"] == 1:
                fake.argvs.append(list(argv))
                return step(3, 2, "turns over 180 degrees; smaller every")
        return first(part, argv, **kw)

    monkeypatch.setattr(runner, "run", refuse_once)
    p3_skeleton.part4(_pose(tmp_path), "every:10", tmp_path / "w", lock=_lock(tmp_path), floor_args=["--floor-work"])
    assert len(fake.runs()) == 2 and all("--floor-work" in a for a in fake.runs())


def test_marked_entry_with_a_pin_lacking_the_flag_runs_without_it_and_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePart3(monkeypatch, offers=False)
    args, note = p3_skeleton.floor_work_args(True, _lock(tmp_path))
    assert args == [] and note == "floor work requested, Part 3 pin lacks --floor-work"
    _all_calls(tmp_path, _lock(tmp_path), True)
    assert fake.runs() and all("--floor-work" not in a for a in fake.runs())


def test_an_unmarked_entry_argv_is_byte_identical_and_probes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePart3(monkeypatch, offers=True)
    lk = _lock(tmp_path)
    assert p3_skeleton.floor_work_args(False, lk) == ([], None)
    assert _all_calls(tmp_path, lk, False) == []
    marked_off = [a for a in fake.argvs]
    base = FakePart3(monkeypatch, offers=True)
    p3_skeleton.part4(_pose(tmp_path), "every:10", tmp_path / "w4", lock=lk)
    p3_skeleton.part5(_pose(tmp_path), tmp_path / "w5", lock=lk)
    assert base.argvs == marked_off  # negative: nothing new, not even a help probe for the flag
    assert not any("--floor-work" in a for a in base.argvs)


def test_doctor_argv_never_carries_the_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePart3(monkeypatch, offers=True)
    lk = _lock(tmp_path)
    target = tmp_path / "skeleton.json"
    target.write_text("{}")
    for consumer in ("part3", "part4", "part5"):
        assert p3_skeleton.doctor(target, consumer, tmp_path, lock=lk)["exit"] == 0
    doctors = [a for a in fake.argvs if "doctor" in a]
    assert len(doctors) == 3 and all("--floor-work" not in a for a in doctors)


def test_chain_trainer_and_follower_hand_the_flag_to_part3_and_note_it(tmp_path: Path, seams: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    seen: list[Any] = []
    ok = {"floor_work_args": lambda floor, lk=None: (["--floor-work"], "Part 3 floor work: on") if floor else ([], None)}
    monkeypatch.setattr(p3_skeleton, "floor_work_args", ok["floor_work_args"])
    def fake_part4(pose: Path, kf: Any, work: Path, **kw: Any) -> Any:
        seen.append(kw.get("floor_args"))
        skel, kf1 = Path(work) / "skeleton.json", Path(work) / "keyframes.v1.json"
        skel.write_text("{}")
        kf1.write_text("{}")
        return ([step(3)], skel, kf1, None)

    monkeypatch.setattr(p3_skeleton, "part4", fake_part4)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"mp4")
    res = chain.trainer(video, tmp_path / "w", lock=make_lock(), catalog=tmp_path / "cat", floor_work=True)
    assert seen == [["--floor-work"]] and "Part 3 floor work: on" in res["note"]
    chain.trainer(video, tmp_path / "w2", lock=make_lock(), catalog=tmp_path / "cat")
    assert seen[-1] == []  # negative: unmarked sends no new argument


def test_group_job_passes_floor_work_to_the_trainer_and_every_follower(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    got: list[Any] = []
    monkeypatch.setattr(chain, "follower", lambda *a, **k: got.append(k.get("floor_work")) or {"ok": True, "status": "ok", "files": {}})
    monkeypatch.setattr(group, "_follower_row", lambda *a, **k: {})
    ctx = SimpleNamespace(set_stage=lambda s: None, _queue=SimpleNamespace(update=lambda *a, **k: None), id="a" * 12,
                          dir=tmp_path, add_note=lambda n: None)
    people_work = tmp_path / "pw"
    group._followers(ctx, "anim.json", "skel.json", tmp_path / "v.mp4", people_work, tmp_path / "p.json", ["1", "2"], {},
                     make_lock(), "cpu", None, "live", None, True)
    assert got == [True, True]


@pytest.fixture(scope="module")
def clip_mp4(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return ffmpeg_video(tmp_path_factory.mktemp("floor") / "clip.mp4", 12)


def _post_trainer(api: Api, clip: Path, **extra: Any) -> dict[str, Any]:
    status, doc = api.json("POST", "api/trainer", {"upload_id": _upload(api, clip), "name": "Push-up", "category": "exercise", **extra})
    assert status == 202
    return api.app.queue.wait(doc["job"], 60)


def test_checkbox_saves_at_create_and_reloads_and_is_passed_to_the_chain(api: Api, clip_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kws: list[dict[str, Any]] = []
    inner = _fake_trainer(entry_id="push-up")
    monkeypatch.setattr(chain, "trainer", lambda *a, **k: (kws.append(k), inner(*a, **k))[1])
    assert _post_trainer(api, clip_mp4, floor_work=True)["status"] == "done"
    assert kws[-1]["floor_work"] is True
    assert api.json("GET", "api/labels") == (200, {"push-up": {"tags": [], "notes": "", "floor_work": True}})
    assert labels.floor_work(api.app.state, "push-up") is True  # reload: read back from Part 7's own store
    monkeypatch.setattr(chain, "trainer", lambda *a, **k: (kws.append(k), _fake_trainer(entry_id="squat")(*a, **k))[1])
    assert _post_trainer(api, clip_mp4)["status"] == "done"
    assert kws[-1]["floor_work"] is False and labels.floor_work(api.app.state, "squat") is False
    assert "squat" not in api.json("GET", "api/labels")[1]  # negative: an unmarked entry gains nothing


def test_labels_edit_keeps_the_mark_and_a_follow_take_reads_it(api: Api, clip_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    labels.set_floor_work(api.app.state, "lateral-raise", True)
    labels.save(api.app.state, "lateral-raise", {"tags": ["a"], "notes": ""})
    assert labels.floor_work(api.app.state, "lateral-raise") is True
    kws: list[dict[str, Any]] = []
    inner = _fake_follower()
    monkeypatch.setattr(chain, "follower", lambda *a, **k: (kws.append(k), inner(*a, **k))[1])
    status, doc = api.json("POST", "api/follow", {"upload_id": _upload(api, clip_mp4), "entry_id": "lateral-raise"})
    assert status == 202 and api.app.queue.wait(doc["job"], 60)["status"] == "done"
    assert kws[-1]["floor_work"] is True
    labels.set_floor_work(api.app.state, "lateral-raise", False)
    status, doc = api.json("POST", "api/follow", {"upload_id": _upload(api, clip_mp4), "entry_id": "lateral-raise"})
    assert api.app.queue.wait(doc["job"], 60)["status"] == "done" and kws[-1]["floor_work"] is False


def test_bad_ids_and_unrelated_values_are_not_floor_work(tmp_path: Path) -> None:
    with pytest.raises(labels.LabelsError):
        labels.set_floor_work(tmp_path, "../evil", True)
    assert labels.floor_work(tmp_path, "../evil") is False and labels.floor_work(None, "x") is False


@pytest.mark.usefixtures("authenv")
def test_owner_edits_the_checkbox_and_download_my_data_lists_it(api: Api) -> None:
    ada, grace = sign_in(api), sign_in(api, "grace@example.com")
    owner = get(api, "api/auth/me", cookie=ada)[2]["user_id"]
    auth.identity(api.app).attach_entry("push-up", owner, "")
    assert post(api, "api/me/entries/push-up", {"floor_work": True}, cookie=grace)[0] == 404  # not the owner
    assert post(api, "api/me/entries/push-up", {"floor_work": "yes"}, cookie=ada)[0] == 400
    assert post(api, "api/me/entries/push-up", {}, cookie=ada)[0] == 400
    assert post(api, "api/me/entries/push-up", {"floor_work": True}, cookie=ada)[2] == {"entry_id": "push-up", "only_me": False, "floor_work": True}
    assert [e["floor_work"] for e in get(api, "api/me/entries", cookie=ada)[2]["entries"]] == [True]
    exported = get(api, "api/me/export", ada)[2]
    assert exported["entries"][0]["floor_work"] is True and exported["entries"][0]["entry_id"] == "push-up"
    post(api, "api/me/entries/push-up", {"floor_work": False}, cookie=ada)
    assert get(api, "api/me/export", ada)[2]["entries"][0]["floor_work"] is False


def test_the_job_note_logs_each_outcome_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for offers, expect in ((True, "Part 3 floor work: on"), (False, "floor work requested, Part 3 pin lacks --floor-work")):
        FakePart3(monkeypatch, offers=offers)
        run = chain._Run(tmp_path / "v.mp4", None, {})
        chain._floor_args(run, True, _lock(tmp_path))
        assert run.notes == [expect]
        quiet = chain._Run(tmp_path / "v.mp4", None, {})
        chain._floor_args(quiet, False, _lock(tmp_path))
        assert quiet.notes == []  # negative: an unmarked entry logs nothing


def test_the_real_part5_view_has_no_frame_block_so_the_result_cannot_read_it_there() -> None:
    doc = json.loads(PART5_REAL.read_text())
    assert doc["view"] == "part5" and doc["producer"] == "part3" and "frame" not in doc


@pytest.mark.parametrize("sent,marked,expected", [(True, True, True), (False, True, False), (True, False, False),
                                                  (False, False, False)])
def test_result_says_floor_work_only_when_part3_got_the_flag_for_a_marked_entry(sent: bool, marked: bool, expected: bool) -> None:
    result = {"ok": True, **({"floor_work": True} if sent else {})}
    assert processor.floor_scored(result, marked) is expected


def test_a_floor_work_trainer_take_has_no_person_resumes_as_v1_and_passes_the_flag(api: Api, clip_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from part7 import resume

    kws: list[dict[str, Any]] = []
    inner = _fake_trainer(entry_id="push-up")
    monkeypatch.setattr(chain, "trainer", lambda *a, **k: (kws.append(k), inner(*a, **k))[1])
    done = _post_trainer(api, clip_mp4, floor_work=True)
    assert done["status"] == "done"
    assert kws[-1]["person"] is None and kws[-1]["floor_work"] is True  # a normal take, not one person of a people job
    record = json.loads((api.app.queue.job_dir(done["id"]) / "job.json").read_text())
    assert record["_resume"]["v"] == resume.SPEC_VERSION == 1 and record["_resume"]["floor_work"] is True
    assert "people_job" not in record["_resume"] and "person_id" not in record["_resume"]
    rebuilt: list[dict[str, Any]] = []
    monkeypatch.setattr(resume.processor, "trainer_job", lambda raw, **k: rebuilt.append(k) or (lambda ctx: None))
    assert resume.rebuild(api.app, record) is not None
    assert rebuilt[0]["person"] is None and rebuilt[0]["floor_work"] is True


def _fake_follow_chain(monkeypatch: pytest.MonkeyPatch, offers: bool) -> list[list[str]]:
    """The real chain.follower with Parts 2 and 5 faked; Part 3 `run` writes the real part5 view. Returns the argvs."""
    probe.clear_cache()
    monkeypatch.setattr(probe, "has_flag", lambda *a, **k: offers)
    argvs: list[list[str]] = []

    def fake_run(part: Any, argv: list[str], **kw: Any) -> runner.Step:
        argvs.append(list(argv))
        if "run" in argv and argv[argv.index("--view") + 1] == "part5":
            Path(argv[argv.index("--out") + 1]).write_bytes(PART5_REAL.read_bytes())  # what Part 3 really writes
        return step(int(part))

    def fake_analyse(run: Any, expected: Path, follower: Path, work: Path, *a: Any, **k: Any) -> tuple[Path, str]:
        out = Path(work) / "analysis.json"
        out.write_text(json.dumps({"format": "simon.analysis.v1", "status": {"code": "ok"}, "faults": [],
                                   "score": {"value": 72, "grade": "C"}}))
        return (out, "ok")

    def fake_pose(run: Any, video: Path, work: Path, *a: Any, **k: Any) -> Path:
        pose = Path(work) / "pose3d.json"
        pose.write_text("{}")
        return pose

    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(chain, "_pose", fake_pose)
    monkeypatch.setattr(chain, "_analyse", fake_analyse)
    return argvs


def test_a_mirrored_follow_take_on_a_floor_work_entry_carries_both_flags_and_resumes_with_both(
    api: Api, clip_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TICKET-310 with TICKET-313: `--flip on` and `--floor-work` both reach Part 3 run, neither reaches doctor."""
    from part7 import mirrored, resume

    labels.set_floor_work(api.app.state, "lateral-raise", True)
    argvs = _fake_follow_chain(monkeypatch, offers=True)  # the pin offers --flip and --floor-work
    status, doc = api.json("POST", "api/follow", {"upload_id": _upload(api, clip_mp4), "entry_id": "lateral-raise",
                                                  "mirrored": True})
    assert status == 202, doc
    done = api.app.queue.wait(doc["job"], 60)
    assert done["status"] == "done", done
    runs = [a for a in argvs if "run" in a and "--view" in a]
    assert len(runs) == 1
    tail = runs[0][runs[0].index("--body") + 2:]
    assert tail == ["--flip", "on", "--floor-work"]  # stable order: person, flip, floor work
    doctors = [a for a in argvs if "doctor" in a]
    assert doctors and all("--floor-work" not in a and "--flip" not in a for a in doctors)
    record = api.json("GET", f"api/jobs/{doc['job']}")[1]
    assert record["mirrored"] is True  # web/mirrored-note.js: "Scored as a mirrored video"
    assert record["result"]["floor_work"] is True  # web/floor-work.js: "Scored as floor work"

    saved = json.loads((api.app.queue.job_dir(doc["job"]) / "job.json").read_text())
    assert saved["_resume"]["v"] == resume.SPEC_VERSION and mirrored.of_record(saved)
    rebuilt: list[dict[str, Any]] = []
    monkeypatch.setattr(resume.processor, "follow_job", lambda raw, **k: rebuilt.append(k) or (lambda ctx: None))
    monkeypatch.setattr(resume.processor, "trainer_job", lambda raw, **k: rebuilt.append(k) or (lambda ctx: None))
    assert resume.rebuild(api.app, saved) is not None
    assert rebuilt[-1]["mirrored"] is True and rebuilt[-1]["floor_work"] is True
    trainer = {"id": "b" * 12, "kind": "trainer", "mirrored": True, "_resume": {
        "v": resume.SPEC_VERSION, "upload_id": saved["_resume"]["upload_id"], "name": "Push-up", "category": "exercise",
        "labels": None, "floor_work": True}}
    assert resume.rebuild(api.app, trainer) is not None
    assert rebuilt[-1]["mirrored"] is True and rebuilt[-1]["floor_work"] is True
    labels.set_floor_work(api.app.state, "lateral-raise", False)
    plain = {k: v for k, v in saved.items() if k != "mirrored"}
    assert resume.rebuild(api.app, plain) is not None
    assert rebuilt[-1]["mirrored"] is False and rebuilt[-1]["floor_work"] is False  # negative: neither flag invented
    probe.clear_cache()


def test_a_pin_without_the_flag_or_an_unmarked_entry_gives_no_floor_line(api: Api, clip_mp4: Path,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative for B1: the line follows what Part 3 was sent, not the entry alone."""
    labels.set_floor_work(api.app.state, "lateral-raise", True)
    for offers, marked in ((False, True), (True, False)):
        labels.set_floor_work(api.app.state, "lateral-raise", marked)
        argvs = _fake_follow_chain(monkeypatch, offers=offers)
        status, doc = api.json("POST", "api/follow", {"upload_id": _upload(api, clip_mp4), "entry_id": "lateral-raise"})
        assert status == 202 and api.app.queue.wait(doc["job"], 60)["status"] == "done"
        assert not any("--floor-work" in a for a in argvs)
        assert "floor_work" not in api.json("GET", f"api/jobs/{doc['job']}")[1]["result"]
    probe.clear_cache()


def test_a_mirrored_floor_work_trainer_upload_carries_both_at_the_top_level(api: Api, clip_mp4: Path,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """R3/R4: one request carries mirrored and floor_work; neither is read from a person field."""
    kws: list[dict[str, Any]] = []
    inner = _fake_trainer(entry_id="push-up")
    monkeypatch.setattr(chain, "trainer", lambda *a, **k: (kws.append(k), inner(*a, **k))[1])
    assert _post_trainer(api, clip_mp4, floor_work=True, mirrored=True)["status"] == "done"
    assert kws[-1]["mirrored"] is True and kws[-1]["floor_work"] is True and kws[-1]["person"] is None
    assert labels.floor_work(api.app.state, "push-up") is True


def test_group_job_saves_labels_and_the_mark_through_entry_saver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R9/R10: the group job's new entry gets its labels and its floor-work mark (labels.entry_saver), and an
    unmarked group entry gets no mark."""
    work = tmp_path / "people"
    work.mkdir()
    (work / "tracks.json").write_text("{}")
    monkeypatch.setattr(group, "reused_clip", lambda ctx, sel: tmp_path / "v.mp4")
    monkeypatch.setattr(group, "_pose_once", lambda *a, **k: tmp_path / "pose3d.json")
    monkeypatch.setattr(group, "_followers", lambda *a, **k: [])
    for entry_id, floor in (("plank", True), ("squat", False)):
        monkeypatch.setattr(chain, "trainer", lambda *a, _e=entry_id, **k: {
            "ok": True, "entry_id": _e, "files": {"animation": "a.json", "skeleton": "s.json"}})
        state = tmp_path / "state"
        fn = group.group_job(people_work=work, trainer_id="1", follower_ids=["2"], name="Plank", category="exercise",
                             catalog=tmp_path / "cat", entry_labels={"tags": ["core"], "notes": ""}, labels_state=state,
                             lock=make_lock(), floor_work=floor)
        ctx = SimpleNamespace(set_stage=lambda s: None, work=tmp_path / entry_id, id="c" * 12, add_note=lambda n: None)
        assert fn(ctx)["entry_id"] == entry_id
        assert labels.floor_work(state, entry_id) is floor and labels.get(state, entry_id) == {"tags": ["core"], "notes": ""}


def test_the_probe_asks_again_when_the_pin_sha_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R13: a pin bump (a new HEAD in the clone) is seen without a restart; the same sha is asked once."""
    probe.clear_cache()
    helps: list[str] = []
    sha = {"now": "a" * 40}
    monkeypatch.setattr(modules, "head_sha", lambda path: sha["now"])
    monkeypatch.setattr(probe, "help_text", lambda *a, **k: helps.append(sha["now"]) or ("--floor-work" if sha["now"][0] == "b" else ""))
    clone = tmp_path / "part-3"
    assert probe.has_flag(3, ["python3", "-m", "part3", "run"], clone, "--floor-work") is False
    assert probe.has_flag(3, ["python3", "-m", "part3", "run"], clone, "--floor-work") is False
    sha["now"] = "b" * 40
    assert probe.has_flag(3, ["python3", "-m", "part3", "run"], clone, "--floor-work") is True
    assert helps == ["a" * 40, "b" * 40]
    probe.clear_cache()


@pytest.mark.usefixtures("authenv")
def test_labels_never_list_an_only_me_entry_to_anyone_but_its_owner(api: Api) -> None:
    """R5/R6: GET api/labels and api/labels/<id> follow the "only me" rule, signed out and as a second account."""
    ada, grace = sign_in(api), sign_in(api, "grace@example.com")
    owner = get(api, "api/auth/me", cookie=ada)[2]["user_id"]
    store = auth.identity(api.app)
    store.attach_entry("plank", owner, "")
    store.attach_entry("bridge", owner, "")
    labels.set_floor_work(api.app.state, "plank", True)  # floor work, no tags or notes
    labels.set_floor_work(api.app.state, "bridge", True)
    labels.save(api.app.state, "bridge", {"tags": ["glutes"], "notes": ""})
    assert post(api, "api/me/entries/plank", {"only_me": True}, cookie=ada)[0] == 200
    mark = {"tags": [], "notes": "", "floor_work": True}
    for cookie in (None, grace):
        listed = get(api, "api/labels", cookie=cookie)[2]
        assert "plank" not in listed and listed["bridge"] == {"tags": ["glutes"], "notes": "", "floor_work": True}
        assert get(api, "api/labels/plank", cookie=cookie)[0] == 404
    assert get(api, "api/labels", cookie=ada)[2]["plank"] == mark
    assert get(api, "api/labels/plank", cookie=ada)[2] == mark  # R6: the single entry carries floor_work too
    assert get(api, "api/labels/bridge")[2] == {"tags": ["glutes"], "notes": "", "floor_work": True}
    assert post(api, "api/me/entries/plank", {"only_me": False}, cookie=ada)[0] == 200
    assert get(api, "api/labels/plank")[2] == mark and "plank" in get(api, "api/labels")[2]


@pytest.mark.usefixtures("authenv")
def test_the_edit_route_answers_404_for_an_id_the_floor_store_cannot_hold(api: Api) -> None:
    """R8: an owned entry whose id fails ENTRY_ID_RE gets 404, not 500, and nothing is changed."""
    ada = sign_in(api)
    owner = get(api, "api/auth/me", cookie=ada)[2]["user_id"]
    auth.identity(api.app).attach_entry("Bad_Id", owner, "")
    status, _, body = post(api, "api/me/entries/Bad_Id", {"floor_work": True, "only_me": True}, cookie=ada)
    assert status == 404 and "error" in body
    assert auth.identity(api.app).entry_owner("Bad_Id") == (owner, False)
