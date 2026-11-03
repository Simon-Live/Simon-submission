"""Trainer chain (Parts 1, 2, 3, 4) and follower chain (Parts 2, 3, 5) with hand-off doctors (TICKET-014, 021)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import threading
from typing import Any, Callable

from part7 import applog, config, crop, failcause, modules, people, quality, runner, stagelog
from part7.quality_constants import OWN_ANALYSIS_SCHEMA_VERSION
from part7.parts import (
    p1_keyframes,
    p2_pose,
    p3_skeleton,
    p4_animate,
    p5_analyse,
    p6_catalog,
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class _Stop(Exception):
    """A chain step failed; carries the result dict to return."""

    def __init__(self, result: dict[str, Any]) -> None:
        super().__init__(result.get("error"))
        self.result = result




class _Run:
    """Shared state of one chain run: steps, notes, the stage callback and the failure result."""

    def __init__(self, video: Path, report: Callable[[str], None] | None, extra: dict[str, Any]) -> None:
        self.video = video
        self.report = report
        self.steps: list[runner.Step] = []
        self.notes: list[str] = []
        self.extra = extra

    def stage(self, name: str) -> None:
        if self.report is not None:
            self.report(name)

    def fail_step(self, stage: str, label: str, step: runner.Step) -> _Stop:
        """A part step that failed: the reason is built from its log, the cause class rides along."""
        cause, text = failcause.classify(label, step)
        return self.fail(stage, text, cause=cause)

    def fail(self, stage: str, reason: str, take: str | None = None, cause: str | None = None) -> _Stop:
        """The failure result. `take` is `no_person` or `no_usable_measures` only when a part ran and reported
        that fact; the follower then answers with Part 7's own analysis. Anything else stays a failed job."""
        return _Stop(
            {
                "ok": False, "status": "failed", "stage": stage, "error": f"failed:{stage}: {reason}",
                "clip": str(self.video), "steps": self.steps, "files": {},
                "note": "; ".join(self.notes) if self.notes else None, "take": take, "cause": take or cause or "failed", **self.extra,
            }
        )

    def check(self, stage: str, step: runner.Step, what: str, part: int) -> runner.Step:
        """Record a doctor or validate step; raise when it rejects `what`."""
        self.steps.append(step)
        if step["exit"] != 0:
            raise self.fail(stage, f"{what} was rejected by part {part}")
        return step


def _pose(
    run: _Run, video: Path, work: Path, backend: str, lk: modules.Modules, state: Any, person: people.PersonSel | None = None
) -> Path:
    """Part 2 on `video` holding the GPU lock, then Part 2's doctor; return `pose3d.json`.

    With `person` the 3D is the people job's choice (`people.pose_for`), or already done (`person.pose3d`).
    """
    if person is not None and person.pose3d is not None:
        applog.log(f"stage pose: person {person.id} reuses {person.pose3d.name} of the group's one Part 2 run",
                   applog.job_id_of(work), work)
        return person.pose3d
    run.stage("pose")
    ids = (person.ids or [person.id]) if person is not None else None
    facts = {"video": stagelog.video_facts(video), "person": person and person.id,
             "ids": ",".join(ids) if ids else None, "backend": backend}
    with stagelog.stage(work, "pose", run.steps, **facts) as end:
        pose3d = _pose_run(run, video, work, backend, lk, state, person, ids)
        end["out"] = pose3d.name
    return pose3d


def _pose_run(
    run: _Run, video: Path, work: Path, backend: str, lk: modules.Modules, state: Any,
    person: people.PersonSel | None, ids: list[str] | None,
) -> Path:
    """The body of `_pose`: Part 2 (shared people path when `person`), then its doctor."""
    try:
        if person is not None:
            step, pose3d, note = people.pose_for(person, ids or [person.id], video, work, backend, lk, state)
            if note:
                run.notes.append(note)
        else:
            step, pose3d = p2_pose.run(video, work, backend=backend, lock=lk, state=state)
    except TimeoutError:
        raise run.fail("pose", failcause.busy_text("3D"), cause="busy") from None
    except RuntimeError:
        raise run.fail("pose", failcause.unavailable_text("3D"), cause="missing_tool") from None
    if failcause.mesh_soft_miss(step, pose3d):  # TICKET-143: the take is analysed normally, without a mesh
        step = {**step, "exit": 0, "mesh_miss": True}
        run.notes.append(failcause.MESH_MISS_NOTE)
    run.steps.append(step)
    if failcause.part2_found_nobody(step):
        raise run.fail("pose", "No person was found in this video", take="no_person")
    if step["exit"] != 0 or not pose3d.is_file():
        raise run.fail_step("pose", "3D", step)
    if failcause.take_has_no_person(pose3d):
        raise run.fail("pose", "No person was found in this video", take="no_person")
    doc = p2_pose.doctor(pose3d, work, lock=lk, state=state)
    # a malformed mesh is no mesh, not a failed job; any other doctor failure fails the job without a retry
    if failcause.doctor_blames_mesh(doc) and p2_pose.drop_mesh(pose3d.parent):
        run.steps.append(doc)
        run.notes.append(failcause.MESH_MISS_NOTE)
        doc = p2_pose.doctor(pose3d, work, lock=lk, state=state)
    run.check("pose", doc, "pose3d.json", 2)
    return pose3d


def _has_people(path: Path) -> bool:
    """False when Part 1's file says `people: []` (processor.md fallback row)."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True  # the doctor already read it; an odd file is not this check's business
    return not (isinstance(doc, dict) and doc.get("people") == [])


def _load_1m() -> str:
    """The host 1-minute load average as `42.4`, or `unknown`."""
    try:
        return f"{os.getloadavg()[0]:.1f}"
    except OSError:
        return "unknown"


def _keyframes(
    run: _Run, video: Path, work: Path, lk: modules.Modules, state: Any, keys_dir: Any
) -> tuple[Path | None, int]:
    """Part 1 with the fallback of `processor.md`; return `(keyframes.json or None, provenance part)`.

    Part 1 gets `SIMON7_PART1_TIMEOUT_S` (default 150); a timeout is a fallback to Part 3 `every:10`, never a failure.
    """
    timeout_s = config.part1_timeout_s()
    step, kf_path, note = p1_keyframes.run(
        video, work, lock=lk, state=state, keys_dir=keys_dir, timeout_s=timeout_s
    )
    if step is not None and step.get("timed_out"):
        note = f"key frames from Part 3, Part 1 took longer than {applog.secs(timeout_s)} s"
        applog.log(f"Part 1 timed out after {applog.secs(timeout_s)} s (load {_load_1m()})", applog.job_id_of(work), work,
                   logging.WARNING)  # TICKET-089: a busy host is the usual cause
    if step is not None:
        run.steps.append(step)
    job = applog.job_id_of(work)
    if note:
        run.notes.append(note)
    if kf_path is None or not Path(kf_path).is_file():
        applog.log(f"Part 1 gave no keyframes ({note or 'no note'}, exit {step and step.get('exit')}); "
                   "Part 3 picks the key frames. See steps/part1.log", job, work, logging.WARNING)
        return (None, 3)
    doc = p1_keyframes.doctor(kf_path, work, lock=lk, state=state)
    run.steps.append(doc)
    if doc["exit"] != 0:
        applog.log("Part 1 keyframes rejected by the Part 6 doctor; Part 3 picks the key frames", job, work, logging.WARNING)
        run.notes.append("key frames from Part 3, Part 1 keyframes rejected by Part 6 doctor")
        return (None, 3)
    if not _has_people(Path(kf_path)):
        applog.log("Part 1 found no person; Part 3 picks the key frames", job, work, logging.WARNING)
        run.notes.append("key frames from Part 3, Part 1 found no person")
        return (None, 3)
    applog.log("key frames from Part 1", job, work)
    return (Path(kf_path), 1)


class _Part1:
    """Part 1 on its own thread beside Part 2; `join` merges its steps and notes into the run (they are independent)."""

    def __init__(self, run: _Run, video: Path, work: Path, lk: modules.Modules, state: Any, keys_dir: Any) -> None:
        self._run = run
        self._side = _Run(run.video, None, {})
        self._out: tuple[Path | None, int] = (None, 3)
        self._thread = threading.Thread(
            target=self._work, args=(video, work, lk, state, keys_dir), name="part7-part1", daemon=True
        )
        self._thread.start()

    def _work(self, video: Path, work: Path, lk: modules.Modules, state: Any, keys_dir: Any) -> None:
        try:
            with stagelog.stage(work, "keyframes", self._side.steps, video=stagelog.video_facts(video)) as end:
                self._out = _keyframes(self._side, video, work, lk, state, keys_dir)
                end["from_part"] = self._out[1]
        except Exception as exc:  # Part 1 never fails the job; Part 3 chooses the key frames
            applog.log(f"Part 1 crashed, Part 3 picks the key frames: {applog.cause(exc)}",
                       applog.job_id_of(work), work, logging.ERROR)
            self._side.notes.append("key frames from Part 3, Part 1 failed unexpectedly")
            self._out = (None, 3)

    def join(self) -> tuple[Path | None, int]:
        self._thread.join()
        self._run.steps.extend(self._side.steps)
        self._run.notes.extend(self._side.notes)
        return self._out


def _skeleton(
    run: _Run, pose3d: Path, kf_arg: Path | str, work: Path, lk: modules.Modules, state: Any, person: str | None = None,
    mirrored: bool = False,
    floor_args: list[str] | None = None,
) -> tuple[Path, Path]:
    """Part 3 `--view part4`; return `(skeleton.json, keyframes.v1.json)`. `mirrored`: flip left and right (TICKET-310)."""
    run.stage("skeleton")
    keyframes = Path(kf_arg).name if isinstance(kf_arg, Path) else kf_arg
    with stagelog.stage(work, "skeleton", run.steps, view="part4", person=person, keyframes=keyframes):
        steps, skel, kf_v1, note = p3_skeleton.part4(pose3d, kf_arg, work, lock=lk, state=state, person=person,
                                                     mirrored=mirrored, floor_args=floor_args)
        run.steps.extend(steps)
        if note:
            run.notes.append(note)
        if steps[-1]["exit"] != 0 or not skel.is_file() or not kf_v1.is_file():
            raise run.fail_step("skeleton", "skeleton", steps[-1])
        run.check("skeleton", p3_skeleton.doctor(skel, "part4", work, lock=lk, state=state), "skeleton.json", 3)
    return (skel, kf_v1)


def _animation(run: _Run, skel: Path, kf_v1: Path, work: Path, lk: modules.Modules, state: Any) -> Path:
    """Part 4 validate, animate, validate, then Part 5's loader check; return `animation.json`."""
    run.stage("animation")
    with stagelog.stage(work, "animation", run.steps, skeleton=skel.name, keyframes=kf_v1.name):
        return _animation_steps(run, skel, kf_v1, work, lk, state)


def _animation_steps(run: _Run, skel: Path, kf_v1: Path, work: Path, lk: modules.Modules, state: Any) -> Path:
    run.check("animation", p4_animate.validate("skeleton", skel, work, lock=lk, state=state), "skeleton.json", 4)
    run.check("animation", p4_animate.validate("keyframes", kf_v1, work, lock=lk, state=state), "keyframes.json", 4)
    step, out = p4_animate.run(skel, kf_v1, work, lock=lk, state=state)
    run.steps.append(step)
    if step["exit"] != 0 or not out.is_file():
        raise run.fail("animation", "the animation step failed")  # Part 4 exit 1, AC-R7
    final = work / "animation.json"
    if out.resolve() != final.resolve():
        shutil.copyfile(out, final)
    run.check("animation", p4_animate.validate("animation", final, work, lock=lk, state=state), "animation.json", 4)
    run.check(
        "animation", p5_analyse.doctor(final, work, consumer="part5", lock=lk, state=state), "animation.json", 5
    )
    return final


def _catalog(
    run: _Run, folder: Path, catalog: Path, name: str, category: str, kf_part: int, work: Path,
    lk: modules.Modules, state: Any,
) -> str:
    """Part 6 `import` with provenance, then Part 6 doctor on the entry; return the entry id."""
    run.stage("catalog")
    parts = {"keyframes": kf_part, "skeleton": 3, "animation": 4}
    with stagelog.stage(work, "catalog", run.steps, category=category, keyframes_part=kf_part,
                        video=stagelog.video_facts(folder / "video.mp4")) as end:
        step, manifest = p6_catalog.import_entry(catalog, folder, name, category, parts, work, lock=lk, state=state)
        run.steps.append(step)
        if step["exit"] != 0 or not manifest or not manifest.get("id"):
            raise run.fail("catalog", "the catalog did not accept the entry")
        doc = p6_catalog.doctor(Path(catalog) / str(manifest["id"]), work, lock=lk, state=state)
        run.steps.append(doc)
        if doc["exit"] != 0:
            raise run.fail("catalog", "the catalog did not accept the entry")
        end["entry"] = manifest["id"]
    return str(manifest["id"])


def _part1_video(run: _Run, video: Path, work: Path, person: people.PersonSel | None) -> Path:
    """The video Part 1 sees: a copy cropped to `person` (people.md), else `video` itself."""
    if person is None or person.people_work is None:
        return video
    job = applog.job_id_of(work)
    try:
        box = crop.person_box(video, person.people_work / "tracks.json", person.id)
        cropped = crop.crop_video(video, work / "person.mp4", box)
    except (ValueError, RuntimeError, OSError) as exc:
        applog.log(f"crop to person {person.id} failed, Part 1 gets the whole picture: {applog.cause(exc)}",
                   job, work, logging.WARNING)
        run.notes.append(f"Part 1 saw the whole picture, the crop to person {person.id} failed")
        return video
    applog.log(f"Part 1 input cropped to person {person.id}: box x={box[0]} y={box[1]} w={box[2]} h={box[3]}; "
               f"{stagelog.video_facts(video)} -> {stagelog.video_facts(cropped)}", job, work)
    run.notes.append(f"Part 1 ran on a copy cropped to person {person.id}")
    return cropped


def _floor_args(run: _Run, floor_work: bool, lk: modules.Modules) -> list[str]:
    """Part 3 `run` options for a floor-work entry; the job note says whether the pin offered the flag."""
    args, note = p3_skeleton.floor_work_args(floor_work, lk)
    if note:
        run.notes.append(note)
        applog.log(note)
    return args


def trainer(
    video: Path | str,
    work: Path | str,
    report: Callable[[str], None] | None = None,
    lock: modules.Modules | None = None,
    backend: str = "gpu",
    state: Path | str | None = None,
    keys_dir: Path | str | None = None,
    catalog: Path | str | None = None,
    name: str = "Chain trainer",
    category: str = "exercise",
    person: people.PersonSel | None = None,
    mirrored: bool = False,
    floor_work: bool = False,
) -> dict[str, Any]:
    """Run the trainer chain of `processor.md` (Parts 1, 2, 3, 4, then Part 6 `import` into `catalog`).

    `video` is the normalized H.264 MP4. Stages reported: keyframes, pose, skeleton, animation, catalog.
    Without `catalog` the chain ends after Part 4 (no entry is made). With `person` the chain is about that
    one person of a people job: Part 1 sees a copy cropped to them and Part 3 gets `--person`.
    `floor_work` (the entry is done on the floor) adds Part 3 `--floor-work` when the pin offers it (floor-work.md).
    """
    lk = lock or modules.load()
    video_p, work_p = Path(video), Path(work)
    work_p.mkdir(parents=True, exist_ok=True)
    run = _Run(video_p, report, {"parts": {"keyframes": 3, "skeleton": 3, "animation": 4}})
    floor_args = _floor_args(run, floor_work, lk)
    try:
        run.stage("keyframes")
        part1 = _Part1(run, _part1_video(run, video_p, work_p, person), work_p, lk, state, keys_dir)
        try:
            pose3d = _pose(run, video_p, work_p, backend, lk, state, person)
        finally:
            kf_path, kf_part = part1.join()  # Part 1 and Part 2 run together; Part 3 needs both
        run.extra["parts"] = {"keyframes": kf_part, "skeleton": 3, "animation": 4}
        skel, kf_v1 = _skeleton(
            run, pose3d, kf_path if kf_path is not None else "every:10", work_p, lk, state, person and person.id, mirrored,
            floor_args,
        )
        final_anim = _animation(run, skel, kf_v1, work_p, lk, state)
        final_kf = work_p / "keyframes.json"
        if kf_part == 3 or not final_kf.is_file():
            shutil.copyfile(kf_v1, final_kf)
        entry_id = None
        if catalog is not None:
            folder = work_p / "import"
            folder.mkdir(parents=True, exist_ok=True)
            for src, dst in (
                (final_kf, "keyframes.json"), (skel, "skeleton.json"),
                (final_anim, "animation.json"), (video_p, "video.mp4"),
            ):
                shutil.copyfile(src, folder / dst)
            entry_id = _catalog(run, folder, Path(catalog), name, category, kf_part, work_p, lk, state)
    except _Stop as stop:
        return stop.result
    return {
        "ok": True, "status": "done", "stage": "done", "clip": str(video_p), "steps": run.steps,
        "files": {
            "keyframes": str(final_kf), "skeleton": str(skel), "animation": str(final_anim),
            "pose3d": str(pose3d), "keyframes_v1": str(kf_v1),
        },
        "parts": run.extra["parts"], "entry_id": entry_id,
        "note": "; ".join(run.notes) if run.notes else None, "error": None,
    }


# processor.md "Always analysed": a take is never refused. Part 7 writes the analysis itself (status ok, one
# warning, score 0, grade F) only for two facts: Part 2 ran and found nobody, or Part 3 ran and found nothing to
# measure. Every other failure (a crash, a missing CUDA backend, a missing tool, memory, a timeout, a busy GPU) is
# the machine's and stays a failed job with a specific reason (TICKET-103).
_OWN_WARNING = {
    "no_person": ("no_person", "No person was found in this take."),
    "no_usable_measures": ("no_usable_measures", "Nothing in this take could be measured against the trainer."),
}


def _is_analysis_case(result: dict[str, Any]) -> bool:
    """True when a failed follower chain result carries a fact about the take (`take`), not a failed machine."""
    return result.get("take") in _OWN_WARNING


def write_own_analysis(path: Path, take: str, reason: str, *, expected: Path | str, follower: Path | str,
                       quality_paths: list[Path] | None = None, person_id: str | None = None) -> Path:
    """Write Part 7's own analysis for `take` = no_person or no_usable_measures: ok, one warning, score 0, grade F.

    `expected` (the trainer clip) and `follower` (the take's video or pose file) are the clip references Part 5's
    schema requires (`path`, non-empty); `faults` is empty.
    """
    code, text = _OWN_WARNING[take]
    doc = {
        "format": "simon.analysis.v1", "schema_version": OWN_ANALYSIS_SCHEMA_VERSION, "source": "part7",
        "expected": {"path": str(expected)}, "follower": {"path": str(follower)},
        "status": {"code": "ok", "text": text},
        "warnings": [{"code": code, "text": text, "reason": reason}],
        "match": {"quality": "low", "residual": None, "timing_corr": None, "limits": {}},
        "faults": [],
        "score": {"version": "simon.score.v1", "value": 0, "grade": "F", "components": {}, "capped_by": [code]},
    }
    signal = quality.fallback_quality(quality_paths or [], person_id)
    if signal is not None:
        doc["quality"] = signal
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return path


def follower(
    video: Path | str,
    expected: Path | str,
    work: Path | str,
    report: Callable[[str], None] | None = None,
    lock: modules.Modules | None = None,
    backend: str = "gpu",
    state: Path | str | None = None,
    phrasing: str = "template",
    person: people.PersonSel | None = None,
    expected_visibility: Path | str | None = None,
    mode: str | None = None,
    lang: str | None = None,
    expected_video: Path | str | None = None,
    private: bool | None = None,
    mirrored: bool = False,
    floor_work: bool = False,
) -> dict[str, Any]:
    """`_follower_chain`, except that a failure about the take itself still ends in an analysis (an F with a warning)."""
    res = _follower_chain(
        video, expected, work, report, lock, backend, state, phrasing, person, expected_visibility, mode,
        lang, expected_video, private, mirrored, floor_work,
    )
    if res.get("ok") or not _is_analysis_case(res):
        return res
    reason = str(res.get("error") or "").split(": ", 1)[-1]
    work_path = Path(work)
    quality_paths = []
    if person is not None and person.pose3d is not None:
        quality_paths.append(person.pose3d)
    quality_paths += [work_path / "part2" / "pose3d.json", work_path / "part2" / "tracks.json",
                      work_path / "part2_track" / "tracks.json", work_path / "tracks.json"]
    if person is not None and person.people_work is not None:
        quality_paths += [person.people_work / "pose3d_all.json", person.people_work / "tracks.json"]
    analysis = write_own_analysis(work_path / "analysis.json", str(res["take"]), reason,
                                  expected=expected, follower=video, quality_paths=quality_paths,
                                  person_id=person.id if person else None)
    note = "; ".join(x for x in (res.get("note"), f"analysed by Part 7 alone: {reason}") if x)
    return {
        "ok": True, "status": "ok", "stage": "done", "clip": res.get("clip"), "steps": res.get("steps", []),
        "files": {"analysis": str(analysis)}, "note": note, "error": None,
    }


def _follower_chain(
    video: Path | str,
    expected: Path | str,
    work: Path | str,
    report: Callable[[str], None] | None = None,
    lock: modules.Modules | None = None,
    backend: str = "gpu",
    state: Path | str | None = None,
    phrasing: str = "template",
    person: people.PersonSel | None = None,
    expected_visibility: Path | str | None = None,
    mode: str | None = None,
    lang: str | None = None,
    expected_video: Path | str | None = None,
    private: bool | None = None,
    mirrored: bool = False,
    floor_work: bool = False,
) -> dict[str, Any]:
    """Run the follower chain of `journey.md` (Parts 2, 3 `--view part5 --fps 30`, 5) with every doctor.

    With `person` the analysis is that person's (Part 3 `--person`) in a clip of several. With
    `expected_visibility` (the trainer's `skeleton.json`) Part 5 gets `--expected-visibility`.
    """
    lk = lock or modules.load()
    video_p, expected_p, work_p = Path(video), Path(expected), Path(work)
    work_p.mkdir(parents=True, exist_ok=True)
    run = _Run(video_p, report, {})
    floor_args = _floor_args(run, floor_work, lk)
    try:
        pose3d = _pose(run, video_p, work_p, backend, lk, state, person)
        run.stage("skeleton")
        with stagelog.stage(work_p, "skeleton", run.steps, view="part5", person=person and person.id):
            step, follower_path = p3_skeleton.part5(pose3d, work_p, lock=lk, state=state, person=person and person.id,
                                                    mirrored=mirrored,  # TICKET-310: the person said the video is mirrored
                                                    floor_args=floor_args)
            run.steps.append(step)
            if step["exit"] != 0 or not follower_path.is_file():
                if failcause.part3_found_nothing(step):
                    raise run.fail("skeleton", "Part 3 found nothing to measure", take="no_usable_measures")
                raise run.fail_step("skeleton", "skeleton", step)
            run.check(
                "skeleton", p3_skeleton.doctor(follower_path, "part5", work_p, lock=lk, state=state), "follower.json", 3
            )
        run.stage("analyse")
        with stagelog.stage(work_p, "analyse", run.steps, expected=expected_p.name, phrasing=phrasing,
                            visibility=bool(expected_visibility)) as end:
            analysis, status_code = _analyse(run, expected_p, follower_path, work_p, lk, state, phrasing,
                                             expected_visibility, mode, lang, expected_video, video_p, private)
            end["status"] = status_code
    except _Stop as stop:
        return stop.result
    replay = work_p / "replay.json"
    return {
        "ok": True, "status": status_code, "stage": "done", "clip": str(video_p), "steps": run.steps,
        "files": {
            "pose3d": str(pose3d), "follower": str(follower_path), "analysis": str(analysis),
            **({"replay": str(replay)} if replay.is_file() else {}),
        },
        "note": "; ".join(run.notes) if run.notes else None, "error": None,
        **({"floor_work": True} if p3_skeleton.FLOOR_WORK in floor_args else {}),  # Part 3 got the flag (floor-work.md)
    }


def _analyse(
    run: _Run, expected: Path, follower_path: Path, work: Path, lk: modules.Modules, state: Any, phrasing: str,
    expected_visibility: Path | str | None, mode: str | None = None, lang: str | None = None,
    expected_video: Path | str | None = None, follower_video: Path | str | None = None, private: bool | None = None,
) -> tuple[Path, str]:
    """Part 5's loader check, `analyse` and its Part 7 doctor; return `(analysis.json, status code)`."""
    run.check(
        "analyse", p5_analyse.doctor(follower_path, work, consumer="part5", lock=lk, state=state), "follower.json", 5,
    )
    step, analysis, status_code, notes = p5_analyse.run(
        expected, follower_path, work, lock=lk, state=state, phrasing=phrasing, expected_visibility=expected_visibility,
        mode=mode, lang=lang, expected_video=expected_video, follower_video=follower_video, private=private,
    )
    run.steps.append(step)
    run.notes.extend(notes)
    if step["exit"] not in (0, 3) or not analysis.is_file():
        raise run.fail_step("analyse", "analysis", step)
    run.check(
        "analyse", p5_analyse.doctor(analysis, work, consumer="part7", lock=lk, state=state), "analysis.json", 5,
    )
    return (analysis, status_code)


def _resolve_clip_path(clip_id_or_path: str, state: Path | str | None = None) -> Path:
    direct = Path(clip_id_or_path)
    if direct.is_file():
        return direct.resolve()
    vdir = config.videos_dir(state)
    candidates = [
        vdir / clip_id_or_path / "clip.mp4",
        vdir / f"{clip_id_or_path}.mp4",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand.resolve()
    return candidates[0]


def _default_clips_from_manifest() -> tuple[str | None, list[str]]:
    mpath = config.manifest_path()
    if not mpath.is_file():
        return (None, [])
    try:
        doc = json.loads(mpath.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return (None, [])
    clips = doc.get("clips") or []
    t_id: str | None = None
    f_ids: list[str] = []
    for item in clips:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "")
        role = str(item.get("role") or "")
        if not cid:
            continue
        if role == "trainer" and t_id is None:
            t_id = cid
        elif role in ("follower", "mismatch"):
            f_ids.append(cid)
    return (t_id, f_ids)


def cli_chain(
    trainer_id: str | None = None,
    follower_ids: list[str] | None = None,
    state: Path | str | None = None,
    lock: modules.Modules | None = None,
    backend: str = "gpu",
) -> int:
    """CLI entry point for `part7 chain` (`make chain`)."""
    lk = lock or modules.load()
    def_trainer, def_followers = _default_clips_from_manifest()
    chosen_trainer = trainer_id or def_trainer
    chosen_followers = follower_ids if follower_ids is not None else def_followers

    if not chosen_trainer:
        print("chain: no trainer clip specified and videos/manifest.json not found", file=sys.stderr)
        return 2

    stamp = _utc_stamp()
    cdir = config.check_dir(state)
    cdir.mkdir(parents=True, exist_ok=True)
    run_work = cdir / f"chain-work-{stamp}"
    out_json_path = cdir / f"chain-{stamp}.json"

    trainer_video = _resolve_clip_path(chosen_trainer, state=state)
    trainer_res = trainer(
        trainer_video,
        run_work / "trainer",
        lock=lk,
        backend=backend,
        state=state,
        catalog=run_work / "catalog",
        name="Chain trainer",
    )

    followers_res: list[dict[str, Any]] = []
    overall_ok = bool(trainer_res.get("ok"))

    if not overall_ok:
        if trainer_res.get("error"):
            print(trainer_res["error"], file=sys.stderr)
    else:
        expected_anim = Path(trainer_res["files"]["animation"])
        for idx, fid in enumerate(chosen_followers):
            f_video = _resolve_clip_path(fid, state=state)
            f_res = follower(
                f_video,
                expected_anim,
                run_work / f"follower-{idx}-{Path(fid).stem}",
                lock=lk,
                backend=backend,
                state=state,
                phrasing="template",
            )
            followers_res.append(
                {
                    "clip": fid,
                    "steps": f_res["steps"],
                    "status": f_res["status"],
                    "ok": f_res["ok"],
                    "error": f_res.get("error"),
                }
            )
            if not f_res["ok"]:
                overall_ok = False
                if f_res.get("error"):
                    print(f_res["error"], file=sys.stderr)
                break

    summary = {
        "pins": lk.shas_short(),
        "trainer": {
            "clip": chosen_trainer,
            "steps": trainer_res["steps"],
            "ok": trainer_res["ok"],
            "note": trainer_res.get("note"),
            "parts": trainer_res.get("parts"),
            "error": trainer_res.get("error"),
        },
        "followers": followers_res,
        "ok": overall_ok,
    }
    text = json.dumps(summary, indent=2)
    out_json_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if overall_ok else 1
