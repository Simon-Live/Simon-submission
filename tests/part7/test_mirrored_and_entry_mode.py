"""TICKET-310 (a mirrored upload flips on request) and TICKET-311 (the entry decides the scoring profile).

recorder.md "Mirrored uploads", practice-and-modes.md "The entry decides", processor.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from part7 import chain, labels, mirrored, modes, modules
from part7.parts import p3_skeleton, p5_analyse, probe
from support import Api, make_lock
from test_server import _fake_follower, _fake_trainer, _upload
from test_trainer_chain_and_harness import _capture_runner, step


# ----- A: Part 3 argv for a mirrored take ---------------------------------------------------------------
def _pose(tmp_path: Path) -> Path:
    pose = tmp_path / "pose3d.json"
    pose.write_text(json.dumps({"format": "simon.pose3d.v1", "frames": []}), encoding="utf-8")
    return pose


def _lock() -> modules.Modules:
    lk = make_lock()
    lk.path("3").mkdir(parents=True, exist_ok=True)
    return lk


@pytest.mark.parametrize("view", ["part4", "part5"])
def test_mirrored_take_passes_flip_on_when_the_pin_offers_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, view: str
) -> None:
    probe.clear_cache()
    monkeypatch.setattr(probe, "has_flag", lambda *a, **k: True)
    argvs = _capture_runner(monkeypatch, [step(3)])
    pose = _pose(tmp_path)
    if view == "part4":
        p3_skeleton.part4(pose, "every:10", tmp_path / "w", lock=_lock(), mirrored=True)
    else:
        p3_skeleton.part5(pose, tmp_path / "w", lock=_lock(), mirrored=True)
    argv = argvs[-1]
    assert argv[argv.index("--flip"):][:2] == ["--flip", "on"]
    assert argv[argv.index("--in") + 1] == str(pose.resolve()), "the pose itself, unchanged"
    probe.clear_cache()


def test_mirrored_take_on_a_pin_without_flip_gets_the_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probe.clear_cache()
    monkeypatch.setattr(probe, "has_flag", lambda *a, **k: False)
    argvs = _capture_runner(monkeypatch, [step(3)])
    p3_skeleton.part5(_pose(tmp_path), tmp_path / "w", lock=_lock(), mirrored=True)
    argv = argvs[-1]
    assert "--flip" not in argv
    hinted = Path(argv[argv.index("--in") + 1])
    assert hinted.name == "pose3d.mirrored.json"
    assert json.loads(hinted.read_text())["mirrored"] is True, "Part 3's --flip auto reads the top-level hint"
    probe.clear_cache()


@pytest.mark.parametrize("view", ["part4", "part5"])
def test_unmirrored_take_sends_nothing_new(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, view: str) -> None:
    probe.clear_cache()
    asked: list[str] = []
    monkeypatch.setattr(probe, "has_flag", lambda *a, **k: asked.append(a[3]) or True)
    argvs = _capture_runner(monkeypatch, [step(3)])
    pose = _pose(tmp_path)
    if view == "part4":
        p3_skeleton.part4(pose, "every:10", tmp_path / "w", lock=_lock())
    else:
        p3_skeleton.part5(pose, tmp_path / "w", lock=_lock())
    argv = argvs[-1]
    assert "--flip" not in argv and "--flip" not in asked
    assert argv[argv.index("--in") + 1] == str(pose.resolve())
    assert not (tmp_path / "w" / "pose3d.mirrored.json").exists()
    probe.clear_cache()


def test_the_pinned_part3_offers_flip() -> None:
    lk = modules.load()
    clone = lk.path("3")
    if not (clone / "part3" / "cli.py").is_file():
        pytest.skip("Part 3 is not checked out")
    text = (clone / "part3" / "cli.py").read_text(encoding="utf-8")
    assert '"--flip"' in text and "mirror.FLIP_VALUES" in text, "the pin's run command has --flip auto|on|off"


def test_mirrored_parse_takes_only_true() -> None:
    for doc in ({}, {"mirrored": False}, {"mirrored": "true"}, {"mirrored": 1}):
        record: dict[str, Any] = {}
        assert mirrored.take(doc, record) is False and record == {}
    record = {}
    assert mirrored.take({"mirrored": True}, record) is True and record == {"mirrored": True}
    assert mirrored.of_record(record) and not mirrored.of_record({}) and not mirrored.of_record(None)


# ----- A: the server keeps the choice and passes it on --------------------------------------------------
def _spy_follow(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    inner = _fake_follower()

    def spy(video: Path, expected: Path, work: Path, report: Any = None, **kw: Any) -> dict[str, Any]:
        seen.update(mode=kw.get("mode"), mirrored=kw.get("mirrored"))
        return inner(video, expected, work, report, **kw)

    monkeypatch.setattr(chain, "follower", spy)
    return seen


def _follow(api: Api, mp4: Path, entry: str = "lateral-raise", **extra: Any) -> dict[str, Any]:
    status, doc = api.json("POST", "api/follow", {"upload_id": _upload(api, mp4), "entry_id": entry, **extra})
    assert status == 202, doc
    api.app.queue.wait(doc["job"], 60)
    return api.json("GET", f"api/jobs/{doc['job']}")[1]


def test_follow_mirrored_is_kept_and_reaches_the_chain(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _spy_follow(monkeypatch)
    record = _follow(api, tiny_mp4, mirrored=True)
    assert record["status"] == "done" and record["mirrored"] is True and seen["mirrored"] is True


def test_follow_unmirrored_adds_nothing(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _spy_follow(monkeypatch)
    for extra in ({}, {"mirrored": False}, {"mirrored": "yes"}):
        record = _follow(api, tiny_mp4, **extra)
        assert "mirrored" not in record and seen["mirrored"] is False


def test_trainer_mirrored_is_kept_and_reaches_the_chain(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []
    inner = _fake_trainer()

    def spy(video: Path, work: Path, report: Any = None, **kw: Any) -> dict[str, Any]:
        seen.append(kw.get("mirrored"))
        return inner(video, work, report, **kw)

    monkeypatch.setattr(chain, "trainer", spy)
    for extra, kept in (({"mirrored": True}, True), ({}, False)):
        body = {"upload_id": _upload(api, tiny_mp4), "name": "Squat", "category": "exercise", **extra}
        status, doc = api.json("POST", "api/trainer", body)
        assert status == 202
        record = api.app.queue.wait(doc["job"], 60)
        assert record["status"] == "done" and (record.get("mirrored") is True) is kept
    assert seen == [True, False]


def test_chain_passes_mirrored_to_part3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    got: list[Any] = []

    def part5(pose3d: Any, work: Any, **kw: Any) -> Any:
        got.append(kw.get("mirrored"))
        return (step(3, 1), Path(work) / "follower.json")

    monkeypatch.setattr(chain, "_pose", lambda *a, **k: tmp_path / "pose3d.json")
    monkeypatch.setattr(p3_skeleton, "part5", part5)
    for flag in (True, False):
        chain._follower_chain(tmp_path / "v.mp4", tmp_path / "e.json", tmp_path / "w", lock=make_lock(), mirrored=flag)
    assert got == [True, False]


# ----- B: the entry decides the mode --------------------------------------------------------------------
@pytest.mark.parametrize("manifest,tags,expect", [
    ({"category": "exercise"}, ["rehab"], "rehab"),
    ({}, ["rehab", "knee"], "rehab"),
    ({"category": "dance"}, ["rehab"], "rehab"),
    ({"category": "exercise"}, [], "fitness"),
    ({"category": "dance"}, None, "dance"),
    ({}, [], None),
    (None, None, None),
    ({"category": "other"}, ["fitness"], None),
])
def test_of_entry(manifest: Any, tags: Any, expect: str | None) -> None:
    assert modes.of_entry(manifest, tags) == expect


def test_decide_follows_the_entry_and_keeps_none() -> None:
    assert modes.decide("fitness", "rehab") == "rehab"
    assert modes.decide("rehab", "fitness") == "fitness"
    assert modes.decide("dance", None) == "dance", "an entry without a kind keeps the posted mode"
    assert modes.decide(None, "rehab") is None, "no posted mode stays the standard rules"


def _with_entry(api: Api, category: str | None, tags: list[str] | None) -> None:
    entry = {"id": "lateral-raise", "animation": "animation.json", "skeleton": "skeleton.json"}
    if category:
        entry["category"] = category
    api.app.child.entries["lateral-raise"] = entry
    if tags is not None:
        labels.save(api.app.state, "lateral-raise", {"tags": tags, "notes": ""})


def test_rehab_entry_with_the_bar_on_exercise_scores_with_profile_rehab(
    api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _with_entry(api, "exercise", ["rehab"])
    seen = _spy_follow(monkeypatch)
    with caplog.at_level("WARNING"):
        record = _follow(api, tiny_mp4, mode="fitness")
    assert record["mode"] == "rehab" and seen["mode"] == "rehab"
    assert any("mode fitness posted for entry lateral-raise" in r.getMessage() for r in caplog.records)
    # the mode the chain got is what Part 5 is called with
    probe.clear_cache()
    argvs = _capture_runner(monkeypatch, [step(5, 0, "--replay --profile")])
    lk = make_lock()
    lk.path("5").mkdir(parents=True, exist_ok=True)
    p5_analyse.run(tmp_path / "e.json", tmp_path / "f.json", tmp_path / "w", lock=lk, state=tmp_path / "s",
                   mode=seen["mode"])
    argv = argvs[-1]
    assert argv[argv.index("--profile"):][:2] == ["--profile", "rehab"]
    probe.clear_cache()


def test_fitness_entry_with_the_bar_on_rehab_follows_the_entry(
    api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_entry(api, "exercise", None)
    seen = _spy_follow(monkeypatch)
    record = _follow(api, tiny_mp4, mode="rehab")
    assert record["mode"] == "fitness" and seen["mode"] == "fitness"


def test_entry_without_a_kind_uses_the_posted_mode(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _with_entry(api, None, ["knee"])
    seen = _spy_follow(monkeypatch)
    record = _follow(api, tiny_mp4, mode="rehab")
    assert record["mode"] == "rehab" and seen["mode"] == "rehab"
    record = _follow(api, tiny_mp4)
    assert "mode" not in record and seen["mode"] is None


def test_resume_keeps_mirrored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from part7 import processor, resume

    got: dict[str, Any] = {}
    monkeypatch.setattr(processor, "follow_job", lambda raw, **kw: got.update(kw) or (lambda ctx: {}))

    class App:
        phrasing = "template"
        lock = None
        backend = "cpu"
        state = tmp_path
        queue = uploads = None

        class child:  # noqa: N801
            @staticmethod
            def get_entry(_e: str) -> dict[str, Any]:
                return {"animation": None, "skeleton": "skeleton.json"}

            @staticmethod
            def get_entry_file(_e: str, _n: str) -> bytes:
                return b"{}"

        @staticmethod
        def upload_file(_u: str) -> Path:
            return tmp_path / "raw.mp4"

    record = {"id": "j1", "kind": "follow", "entry_id": "e", "mirrored": True,
              "_resume": {"v": resume.SPEC_VERSION, "upload_id": "u"}}
    assert resume.rebuild(App(), record) is not None and got["mirrored"] is True
