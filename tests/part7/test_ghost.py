"""The trainer's 2D ghost route (docs/specs/follow-ghost.md, TICKET-264)."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from part7 import ghost, jobs
from part7.skeleton2d import JOINTS

# ----- Part 2 fixtures: pose3d.json and camera.json of a trainer clip (Part 2 CONTRACT.md) ----------------------------
K = [[434.0, 0.0, 320.0], [0.0, 434.0, 240.0], [0.0, 0.0, 1.0]]
SIZE = (640, 480)
FRONT = [[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]]  # facing the camera: the subject's left on image right
SIDE = [[0.0, 0.0, -1.0], [0.0, -1.0, 0.0], [-1.0, 0.0, 0.0]]  # side-on: the body's front points to the image's left
LEGS = ("left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle")
UPPER = {"nose": (0.0, 0.62, 0.08), "left_eye": (0.03, 0.66, 0.05), "right_eye": (-0.03, 0.66, 0.05),
         "left_ear": (0.07, 0.64, -0.04), "right_ear": (-0.07, 0.64, -0.04), "left_shoulder": (0.18, 0.46, -0.06),
         "right_shoulder": (-0.19, 0.46, -0.08), "left_elbow": (0.21, 0.24, 0.12), "right_elbow": (-0.24, 0.23, 0.09),
         "left_wrist": (0.01, 0.39, 0.15), "right_wrist": (-0.05, 0.39, 0.14)}
SEATED_LEGS = {"left_hip": (0.09, 0.0, 0.0), "right_hip": (-0.09, 0.0, 0.0), "left_knee": (0.1, -0.02, 0.45),
               "right_knee": (-0.1, -0.02, 0.45), "left_ankle": (0.1, -0.45, 0.45), "right_ankle": (-0.1, -0.45, 0.45)}
STANDING = {**{n: (x, y + 0.28, z) for n, (x, y, z) in UPPER.items()},
            "left_hip": (0.09, 0.0, 0.0), "right_hip": (-0.09, 0.0, 0.0), "left_knee": (0.1, -0.45, 0.02),
            "right_knee": (-0.1, -0.45, 0.02), "left_ankle": (0.12, -0.9, 0.0), "right_ankle": (-0.12, -0.9, 0.0)}


def _joints(body: dict[str, tuple[float, float, float]], unseen: tuple[str, ...] = ()) -> dict[str, Any]:
    return {n: {"x": body[n][0], "y": body[n][1], "z": body[n][2], "conf": 0.3 if n in unseen else 1.0} for n in JOINTS}


def put_part2(folder: Path, body: dict[str, tuple[float, float, float]], rot: list[list[float]], trans: list[float],
              frames: int = 3, unseen: tuple[str, ...] = (), people: tuple[int, ...] = (0,)) -> Path:
    """A trainer's Part 2 folder at 10 frames a second; every person has the same pose and camera."""
    folder.mkdir(parents=True, exist_ok=True)
    pose = {"frames": [{"frame": i, "t_ms": i * 100.0, "people": [{"id": p, "joints": _joints(body, unseen)}
                                                                  for p in people]} for i in range(frames)]}
    cam = {"camera_frame": "opencv", "K": K, "image_size": list(SIZE),
           "frames": [{"frame": i, "people": [{"id": p, "R": rot, "t": [trans[0] + 0.5 * p, trans[1], trans[2]]}
                                              for p in people]} for i in range(frames)]}
    (folder / "pose3d.json").write_text(json.dumps(pose), encoding="utf-8")
    (folder / "camera.json").write_text(json.dumps(cam), encoding="utf-8")
    return folder


def expected_uv(p: tuple[float, float, float], rot: list[list[float]], trans: list[float]) -> tuple[float, float]:
    """The pinhole projection written out here, independent of part7.skeleton2d."""
    cam = [sum(rot[i][j] * p[j] for j in range(3)) + trans[i] for i in range(3)]
    return (K[0][0] * cam[0] / cam[2] + K[0][2]) / SIZE[0], (K[1][1] * cam[1] / cam[2] + K[1][2]) / SIZE[1]


SEATED = {**UPPER, **SEATED_LEGS}
CHEST_UP_T = [0.0, 0.7, 1.0]  # hips 0.7 m below the lens axis at 1 m: below the image, as on square-arms-bc406296


# ----- Part 4 and Part 3 fixtures (the fallback) ----------------------------------------------------------------------
def _anim(frames: int = 3, fps: int = 30) -> dict[str, Any]:
    out = []
    for i in range(frames):
        joints = {n: [0.0, 0.0, 0.0] for n in JOINTS}
        joints["nose"] = [0.1, 0.8 + 0.01 * i, 0.0]
        joints["left_ankle"] = [0.2, -0.8, 0.0]
        joints["right_ankle"] = [-0.2, -0.8, 0.0]
        out.append({"index": i, "t": i / fps, "joints": joints})
    return {"format": "simon.animation.v1", "fps": fps, "joints": list(JOINTS), "frames": out}


def _skeleton() -> dict[str, Any]:
    joints = {n: {"x": 0.0, "y": 0.0, "z": 0.0, "conf": 1.0} for n in JOINTS}
    joints["nose"] = {"x": 0.0, "y": 1.0, "z": 0.0, "conf": 1.0}
    joints["left_wrist"] = {"x": 0.3, "y": 0.5, "z": 0.0, "conf": 0.0}  # unseen: not drawn
    joints["left_knee"] = {"x": 0.1, "y": -0.5, "z": 0.0, "conf": 0.3}  # Part 3's unseen mark: not drawn
    return {"format": "simon.skeleton.v1", "frames": [{"frame": 0, "t_ms": 500.0, "people": [{"id": 0, "joints": joints}]}]}


# what part7/ghost.py build() answered at 2514c4d8, before this fix, for `_anim(5)` and STANDING (frozen output)
FIRST_BUILD = json.loads((Path(__file__).parent / "fixtures" / "ghost-first-build.json").read_text(encoding="utf-8"))


class Child:
    def __init__(self, manifest: dict[str, Any] | None, files: dict[str, Any]) -> None:
        self.manifest, self.files = manifest, files

    def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        return self.manifest

    def get_entry_file(self, entry_id: str, name: str) -> bytes | None:
        doc = self.files.get(name)
        return None if doc is None else (doc if isinstance(doc, bytes) else json.dumps(doc).encode())


class H:
    def __init__(self, child: Child, jobs_root: Path | None = None, state: Path | None = None) -> None:
        self.app = SimpleNamespace(child=child, queue=SimpleNamespace(root=jobs_root), state=state)
        self.sent: list[tuple[int, Any]] = []

    def _json(self, status: int, body: Any) -> None:
        self.sent.append((status, body))

    def _error(self, status: int, msg: str) -> None:
        self.sent.append((status, {"error": msg}))


def trainer_job(root: Path, entry: str, job_id: str = "aaaaaaaaaaa1", person: str | None = None, **part2: Any) -> Path:
    """A done trainer job folder of `entry` under jobs root `root`, with Part 2 files when `part2` says how."""
    job = root / job_id
    job.mkdir(parents=True)
    rec = {"id": job_id, "kind": "trainer", "status": "done", "entry_id": entry, "finished_at": "2026-11-03T02:43:37Z"}
    (job / "job.json").write_text(json.dumps({**rec, **({"person_id": person} if person else {})}), encoding="utf-8")
    if part2:
        put_part2(job / "work" / "trainer" / "part2", **part2)
    return job


ENTRY = {"id": "square-arms", "animation": "animation.json", "skeleton": "skeleton.json"}


# ----- AC-4: the trainer's own Part 2 picture -------------------------------------------------------------------------
def test_seated_chest_up_trainer_projects_through_its_camera_and_drops_the_guessed_legs(tmp_path: Path) -> None:
    folder = put_part2(tmp_path / "part2", SEATED, FRONT, CHEST_UP_T, unseen=LEGS)
    doc = ghost.from_part2(folder)
    assert doc is not None and doc["box"] == "image" and doc["image_size"] == [640.0, 480.0] and doc["mirrored"] is False
    assert [f["t"] for f in doc["frames"]] == [0.0, 0.1, 0.2]
    for frame in doc["frames"]:
        pts = dict(zip(JOINTS, frame["pts"]))
        assert all(pts[n] is None for n in LEGS), "no guessed hips, knees or ankles"
        for name, p in UPPER.items():
            u, v = expected_uv(p, FRONT, CHEST_UP_T)
            assert pts[name] == [round(u, 4), round(v, 4)], name
            assert 0 <= pts[name][0] <= 1 and 0 <= pts[name][1] <= 1, f"{name} is inside the trainer's image"
    pts = dict(zip(JOINTS, doc["frames"][0]["pts"]))
    assert pts["left_shoulder"][0] > 0.5 > pts["right_shoulder"][0], "the subject's left is on the image's right"


def test_side_on_seated_trainer_keeps_the_thigh_the_first_build_collapsed(tmp_path: Path) -> None:
    trans = [0.0, 0.3, 2.5]
    doc = ghost.from_part2(put_part2(tmp_path / "part2", SEATED, SIDE, trans))
    pts = dict(zip(JOINTS, doc["frames"][0]["pts"]))
    assert all(p is not None for p in pts.values()), "the whole seated body is in frame, so every joint is drawn"
    thigh_px = abs(pts["left_knee"][0] - pts["left_hip"][0]) * SIZE[0]
    assert thigh_px > 60, f"the knee lands beside the hip on the image ({thigh_px:.0f} px)"
    assert pts["left_knee"][0] < pts["left_hip"][0], "toward the body's front, the image's left"
    # the first build (depth dropped) drew the same thigh as a point on the hip
    flat = {"frames": [{"t": 0, "joints": {n: list(SEATED[n]) for n in JOINTS}}]}
    old = dict(zip(JOINTS, ghost.build(flat)["frames"][0]["pts"]))
    assert abs(old["left_knee"][0] - old["left_hip"][0]) < 0.01 and abs(old["left_knee"][1] - old["left_hip"][1]) < 0.05


def test_standing_trainer_still_shows_every_joint_head_above_feet(tmp_path: Path) -> None:
    trans = [0.0, -0.1, 3.0]
    doc = ghost.from_part2(put_part2(tmp_path / "part2", STANDING, FRONT, trans))
    pts = dict(zip(JOINTS, doc["frames"][0]["pts"]))
    assert all(p is not None for p in pts.values())
    assert pts["nose"][1] < pts["left_hip"][1] < pts["left_knee"][1] < pts["left_ankle"][1], "head at the top"
    assert pts["left_ankle"][0] > 0.5 > pts["right_ankle"][0]
    assert pts["left_ankle"] == [round(c, 4) for c in expected_uv(STANDING["left_ankle"], FRONT, trans)]


def test_from_part2_picks_the_trainer_person_and_refuses_unusable_folders(tmp_path: Path) -> None:
    folder = put_part2(tmp_path / "two", STANDING, FRONT, [0.0, -0.1, 3.0], people=(0, 1))
    one = ghost.from_part2(folder, "1")
    zero = ghost.from_part2(folder, "0")
    assert one["frames"][0]["pts"][0][0] > zero["frames"][0]["pts"][0][0], "person 1 stands 0.5 m to the right"
    assert ghost.from_part2(tmp_path / "missing") is None
    blind = put_part2(tmp_path / "blind", STANDING, FRONT, [0.0, -0.1, 3.0], unseen=JOINTS)
    assert ghost.from_part2(blind) is None, "a folder with no seen joint is no ghost"


def test_from_part2_never_draws_another_person_as_the_trainer(tmp_path: Path) -> None:
    folder = put_part2(tmp_path / "p", STANDING, FRONT, [0.0, -0.1, 3.0], frames=3, people=(0, 1))
    pose = json.loads((folder / "pose3d.json").read_text())
    pose["frames"][1]["people"] = [p for p in pose["frames"][1]["people"] if p["id"] != 1]  # the trainer is not found
    (folder / "pose3d.json").write_text(json.dumps(pose))
    cam = json.loads((folder / "camera.json").read_text())
    cam["frames"][2]["people"] = [p for p in cam["frames"][2]["people"] if p["id"] != 1]  # no place for them
    (folder / "camera.json").write_text(json.dumps(cam))
    doc = ghost.from_part2(folder, "1")
    assert [all(p is None for p in f["pts"]) for f in doc["frames"]] == [False, True, True], "empty, never person 0"
    follower = ghost.skeleton2d.build(folder, "1")  # the follower's overlay keeps its first-person fallback
    assert all(p is not None for p in follower["frames"][1]["pts"])


def test_malformed_part2_files_fall_back_instead_of_failing(tmp_path: Path) -> None:
    folder = put_part2(tmp_path / "p", STANDING, FRONT, [0.0, -0.1, 3.0])
    cam = json.loads((folder / "camera.json").read_text())
    (folder / "camera.json").write_text(json.dumps({**cam, "frames": 5}))
    assert ghost.from_part2(folder) is None
    put_part2(folder, STANDING, FRONT, [0.0, -0.1, 3.0])
    pose = json.loads((folder / "pose3d.json").read_text())
    pose["frames"][0]["people"][0]["joints"] = ["not", "a", "dict"]
    (folder / "pose3d.json").write_text(json.dumps(pose))
    assert ghost.from_part2(folder) is None


def test_the_follower_overlay_still_draws_joints_part2_placed_outside_the_image(tmp_path: Path) -> None:
    folder = put_part2(tmp_path / "p", SEATED, FRONT, CHEST_UP_T, unseen=LEGS)
    follower = dict(zip(JOINTS, ghost.skeleton2d.build(folder)["frames"][0]["pts"]))  # default min_conf 0.0
    assert follower["left_knee"] is not None and follower["left_knee"][1] > 1, "drawn, below the image"
    assert dict(zip(JOINTS, ghost.from_part2(folder)["frames"][0]["pts"]))["left_knee"] is None


# ----- AC-7: the kept copy outlives the trainer job folder ------------------------------------------------------------
def test_keep_kept_and_forget(tmp_path: Path) -> None:
    state, folder = tmp_path / "state", put_part2(tmp_path / "p", SEATED, FRONT, CHEST_UP_T, unseen=LEGS)
    doc = ghost.keep(state, "square-arms", "aaaaaaaaaaa1", folder, None)
    assert doc is not None and ghost.kept(state, "square-arms") == ("aaaaaaaaaaa1", doc)
    assert ghost.kept(state, "other") is None and ghost.kept(None, "square-arms") is None
    assert ghost.kept(state, "../etc") is None and ghost.forget(state, "../etc", "aaaaaaaaaaa1") is False
    ghost.kept_path(state, "bad").write_text(json.dumps({"format": "x", "entry_id": "bad", "ghost": {}}))
    assert ghost.kept(state, "bad") is None, "only our own format"
    assert ghost.forget(state, "square-arms", "aaaaaaaaaaa2") is False, "a copy of another take stays"
    assert ghost.kept(state, "square-arms") is not None
    assert ghost.forget(state, "square-arms", "aaaaaaaaaaa1") is True and ghost.kept(state, "square-arms") is None
    assert ghost.forget(state, "square-arms", "aaaaaaaaaaa1") is False
    assert ghost.keep(state, "blind", "aaaaaaaaaaa1", tmp_path / "missing", None) is None
    assert not ghost.kept_path(state, "blind").exists(), "nothing kept without a ghost"


def test_kept_accepts_only_an_image_ghost_with_frames(tmp_path: Path) -> None:
    state = tmp_path / "state"
    for i, bad in enumerate(({"box": "body", "frames": [{"t": 0}]}, {"box": "image", "frames": []},
                             {"box": "image", "frames": "x"}, {"box": "image"}, {})):
        entry = f"e{i}"
        history_write(state, entry, bad)
        assert ghost.kept(state, entry) is None, bad
    history_write(state, "ok", {"box": "image", "frames": [{"t": 0, "pts": []}]})
    assert ghost.kept(state, "ok") == ("aaaaaaaaaaa1", {"box": "image", "frames": [{"t": 0, "pts": []}]})


def history_write(state: Path, entry: str, doc: dict[str, Any]) -> None:
    path = ghost.kept_path(state, entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"format": ghost.KEEP_FORMAT, "entry_id": entry, "trainer_job": "aaaaaaaaaaa1", "ghost": doc}))


def test_a_rebuild_that_gives_nothing_answers_the_saved_copy_not_the_body_ghost(tmp_path: Path) -> None:
    jobs_root, state = tmp_path / "jobs", tmp_path / "state"
    old = trainer_job(jobs_root, "square-arms", "aaaaaaaaaaa1", body=SEATED, rot=FRONT, trans=CHEST_UP_T, unseen=LEGS)
    files = {"animation.json": _anim(), "skeleton.json": _skeleton()}
    first = ghost.for_entry(Child(ENTRY, files), "square-arms", jobs_root, state)[1]
    assert first["source"] == "part2"
    time.sleep(0.01)
    trainer_job(jobs_root, "square-arms", "aaaaaaaaaaa2")  # a newer trainer job whose Part 2 files are gone
    (jobs_root / "aaaaaaaaaaa2" / "job.json").write_text(json.dumps(
        {"id": "aaaaaaaaaaa2", "kind": "trainer", "status": "done", "entry_id": "square-arms",
         "finished_at": "2026-11-04T02:43:37Z"}))
    again = ghost.for_entry(Child(ENTRY, files), "square-arms", jobs_root, state)[1]
    assert again["source"] == "part2" and again["frames"] == first["frames"], old.name


def test_a_failed_write_logs_a_warning_and_the_route_still_answers(tmp_path: Path, monkeypatch: Any, caplog: Any) -> None:
    jobs_root, state = tmp_path / "jobs", tmp_path / "state"
    trainer_job(jobs_root, "square-arms", body=SEATED, rot=FRONT, trans=CHEST_UP_T, unseen=LEGS)

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(ghost.history_store, "write_json", boom)
    with caplog.at_level("WARNING"):
        status, body = ghost.for_entry(Child(ENTRY, {"animation.json": _anim()}), "square-arms", jobs_root, state)
    assert status == 200 and body["source"] == "part2" and body["available"] is True
    assert ghost.kept(state, "square-arms") is None
    assert any("could not keep square-arms" in r.getMessage() for r in caplog.records)


class Queue:
    def __init__(self, root: Path, made: list[tuple[str, str]]) -> None:
        self.root, self.made = root, made

    def recent_trainer_entries(self, limit: int) -> list[tuple[str, str]]:
        return self.made[:limit]

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id


def test_sweep_keeps_the_newest_trainer_job_of_each_entry_and_drops_entries_gone(tmp_path: Path) -> None:
    jobs_root, state, catalog = tmp_path / "jobs", tmp_path / "state", tmp_path / "catalog"
    for entry in ("square-arms", "squat"):
        (catalog / entry).mkdir(parents=True)
    trainer_job(jobs_root, "square-arms", "aaaaaaaaaaa2", person="1", body=SEATED, rot=FRONT, trans=CHEST_UP_T,
                unseen=LEGS, people=(0, 1))
    trainer_job(jobs_root, "square-arms", "aaaaaaaaaaa1", body=STANDING, rot=FRONT, trans=[0.0, -0.1, 3.0])
    trainer_job(jobs_root, "squat", "aaaaaaaaaaa3")  # no Part 2 files: nothing to keep
    queue = Queue(jobs_root, [("aaaaaaaaaaa2", "square-arms"), ("aaaaaaaaaaa1", "square-arms"), ("aaaaaaaaaaa3", "squat")])
    assert ghost.sweep(state, catalog, queue) == 1
    job_id, doc = ghost.kept(state, "square-arms")
    assert job_id == "aaaaaaaaaaa2" and doc["frames"][0]["pts"][JOINTS.index("left_knee")] is None, "the newest job"
    assert ghost.sweep(state, catalog, queue) == 0, "already kept: nothing written again"
    ghost.kept_path(state, "gone").write_text("{}")
    ghost.sweep(state, tmp_path / "no-catalog", queue)
    assert ghost.kept_path(state, "gone").exists(), "never prune against a missing catalog"
    ghost.sweep(state, catalog, queue)
    assert not ghost.kept_path(state, "gone").exists() and ghost.kept(state, "square-arms") is not None


def test_sweep_skips_entries_off_the_catalog_and_does_not_reparse_a_job_without_a_ghost(tmp_path: Path,
                                                                                     monkeypatch: Any) -> None:
    jobs_root, state, catalog = tmp_path / "jobs", tmp_path / "state", tmp_path / "catalog"
    for entry in ("square-arms", "squat"):
        (catalog / entry).mkdir(parents=True)
    trainer_job(jobs_root, "square-arms", "bbbbbbbbbbb1", body=STANDING, rot=FRONT, trans=[0.0, -0.1, 3.0])
    trainer_job(jobs_root, "squat", "bbbbbbbbbbb2")  # no Part 2 files
    trainer_job(jobs_root, "removed", "bbbbbbbbbbb3", body=STANDING, rot=FRONT, trans=[0.0, -0.1, 3.0])
    queue = Queue(jobs_root, [("bbbbbbbbbbb3", "removed"), ("bbbbbbbbbbb2", "squat"), ("bbbbbbbbbbb1", "square-arms")])
    built: list[str] = []
    real = ghost.from_part2
    monkeypatch.setattr(ghost, "from_part2", lambda d, p=None: (built.append(d.parent.parent.parent.name), real(d, p))[1])
    assert ghost.sweep(state, catalog, queue) == 1
    assert sorted(built) == ["bbbbbbbbbbb1", "bbbbbbbbbbb2"], "the removed movement was never parsed"
    assert ghost.kept(state, "removed") is None
    built.clear()
    ghost.sweep(state, catalog, queue)
    assert built == [], "the job without a ghost is remembered; the kept one is not rebuilt"


def test_route_answers_the_kept_copy_once_the_trainer_job_is_gone(tmp_path: Path) -> None:
    jobs_root, state = tmp_path / "jobs", tmp_path / "state"
    job = trainer_job(jobs_root, "square-arms", body=SEATED, rot=FRONT, trans=CHEST_UP_T, unseen=LEGS)
    files = {"animation.json": _anim(), "skeleton.json": _skeleton()}
    first = ghost.for_entry(Child(ENTRY, files), "square-arms", jobs_root, state)[1]
    assert first["source"] == "part2" and ghost.kept(state, "square-arms")[0] == job.name, "kept on the first build"
    (job / "job.json").unlink()  # the 7-day sweep removed the job folder
    again = ghost.for_entry(Child(ENTRY, files), "square-arms", jobs_root, state)[1]
    assert again == first
    ghost.forget(state, "square-arms", job.name)
    assert ghost.for_entry(Child(ENTRY, files), "square-arms", jobs_root, state)[1]["source"] == "animation"


# ----- AC-6: the fallback (box "body") --------------------------------------------------------------------------------
def test_build_scales_the_body_height_to_one_in_the_camera_view() -> None:
    doc = ghost.build(_anim())
    assert doc is not None and doc["format"] == "simon.skeleton2d.v1" and doc["box"] == "body" and doc["mirrored"] is False
    assert doc["joints"] == list(JOINTS) and len(doc["frames"]) == 3
    assert [f["t"] for f in doc["frames"]] == [0.0, 0.033, 0.067]
    first = doc["frames"][0]["pts"]
    nose, left_ankle, right_ankle = first[0], first[JOINTS.index("left_ankle")], first[JOINTS.index("right_ankle")]
    # the subject's left is on the image's right (a trainer facing the camera); feet at the bottom
    assert left_ankle[0] > 0.5 > right_ankle[0]
    assert left_ankle[1] == 1.0 and nose[1] < 0.1


def test_a_standing_trainer_without_unseen_joints_answers_exactly_the_first_build() -> None:
    assert ghost.build(_anim(5)) == FIRST_BUILD["anim5"]
    standing = {"frames": [{"t": 0, "joints": {n: list(STANDING[n]) for n in JOINTS}}]}
    assert ghost.build(standing) == FIRST_BUILD["standing"]


def test_build_drops_part4_unseen_joints_and_frame_conf_but_keeps_the_first_build_box() -> None:
    anim = _anim(3)
    before = ghost.build(anim)
    anim["unseen_joints"] = ["left_ankle"]
    for f in anim["frames"]:
        f["conf"] = {n: 1.0 for n in JOINTS}
    anim["frames"][1]["conf"]["right_ankle"] = 0.3  # unseen in this frame only
    doc = ghost.build(anim)
    la, ra = JOINTS.index("left_ankle"), JOINTS.index("right_ankle")
    assert all(f["pts"][la] is None for f in doc["frames"]), "never seen in the clip"
    assert [f["pts"][ra] is None for f in doc["frames"]] == [False, True, False], "unseen in frame 1 only"
    assert doc["frames"][0]["pts"][0] == before["frames"][0]["pts"][0], "the seen joints keep their place"


def test_build_reads_a_part3_skeleton_and_drops_unseen_joints() -> None:
    doc = ghost.build(_skeleton())
    assert doc is not None and doc["frames"][0]["t"] == 0.5
    assert doc["frames"][0]["pts"][JOINTS.index("left_wrist")] is None
    assert doc["frames"][0]["pts"][JOINTS.index("left_knee")] is None


def test_build_refuses_documents_with_no_height_or_no_seen_joint() -> None:
    assert ghost.build(None) is None
    assert ghost.build({"frames": []}) is None
    flat = {"frames": [{"t": 0, "joints": {n: [0, 0, 0] for n in JOINTS}}]}
    assert ghost.build(flat) is None
    blind = {**_anim(), "unseen_joints": list(JOINTS)}
    assert ghost.build(blind) is None


# ----- the route ------------------------------------------------------------------------------------------------------
def test_route_answers_the_trainer_part2_picture_first(tmp_path: Path) -> None:
    jobs_root, state = tmp_path / "jobs", tmp_path / "state"
    trainer_job(jobs_root, "square-arms", person="1", body=SEATED, rot=FRONT, trans=CHEST_UP_T, unseen=LEGS, people=(0, 1))
    h = H(Child(ENTRY, {"animation.json": _anim(), "skeleton.json": _skeleton()}), jobs_root, state)
    assert ghost.handle(h, "GET", "ghost/square-arms.json") is True
    assert ghost.kept(state, "square-arms") is not None, "the route keeps what it built"
    status, body = h.sent[0]
    assert status == 200 and body["source"] == "part2" and body["box"] == "image" and body["available"] is True
    assert body["entry_id"] == "square-arms" and body["image_size"] == [640.0, 480.0] and len(body["frames"]) == 3
    nose = expected_uv(SEATED["nose"], FRONT, [CHEST_UP_T[0] + 0.5, *CHEST_UP_T[1:]])  # person 1 of the job
    assert body["frames"][0]["pts"][0] == [round(c, 4) for c in nose]
    assert all(body["frames"][0]["pts"][JOINTS.index(n)] is None for n in LEGS)


def test_route_falls_back_to_the_entry_files_without_trainer_part2(tmp_path: Path) -> None:
    files = {"animation.json": _anim(), "skeleton.json": _skeleton()}
    for case, root in (("no jobs root", None), ("no trainer job", tmp_path / "empty")):
        h = H(Child(ENTRY, files), root)
        ghost.handle(h, "GET", "ghost/square-arms.json")
        assert h.sent[0][1]["source"] == "animation" and h.sent[0][1]["box"] == "body", case
    trainer_job(tmp_path / "nofiles", "square-arms")  # a trainer job whose Part 2 files are gone
    blind = tmp_path / "blind"
    trainer_job(blind, "square-arms", body=SEATED, rot=FRONT, trans=CHEST_UP_T, unseen=JOINTS)
    for root in (tmp_path / "nofiles", blind):
        status, body = ghost.for_entry(Child(ENTRY, files), "square-arms", root)
        assert status == 200 and body["source"] == "animation", root.name
    (blind / "aaaaaaaaaaa1" / "work" / "trainer" / "part2" / "camera.json").write_text("not json", encoding="utf-8")
    assert ghost.for_entry(Child(ENTRY, files), "square-arms", blind)[1]["source"] == "animation"


def test_route_falls_back_to_the_skeleton_when_the_animation_is_unreadable() -> None:
    h = H(Child({"id": "squat", "animation": "animation.json", "skeleton": "skeleton.json"},
                {"animation.json": b"not json", "skeleton.json": _skeleton()}))
    ghost.handle(h, "GET", "ghost/squat.json")
    assert h.sent[0][0] == 200 and h.sent[0][1]["source"] == "skeleton"


def test_route_404s_and_ignores_other_routes() -> None:
    h = H(Child(None, {}))
    assert ghost.handle(h, "GET", "ghost/squat.json") is True
    assert h.sent == [(404, {"error": ghost.MSG_ENTRY})]
    h2 = H(Child({"id": "squat"}, {}))
    ghost.handle(h2, "GET", "ghost/squat.json")
    assert h2.sent == [(200, {"available": False, "entry_id": "squat", "reason": ghost.MSG_NONE})]  # no console 404
    h3 = H(Child({"id": "squat"}, {}))
    assert ghost.handle(h3, "GET", "ghost/../etc.json") is False
    assert ghost.handle(h3, "POST", "ghost/squat.json") is False
    assert ghost.handle(h3, "GET", "ghosts/squat.json") is False
    assert h3.sent == []


# ----- through the running app (part7/server.py) -----------------------------------------------------------------
def test_app_route_answers_the_ghost_and_the_no_ghost_case(api: Any) -> None:
    from test_ghost import _anim as anim  # same module: the fixture animation

    api.app.child.files = {**api.app.child.files, "animation.json": json.dumps(anim()).encode()}
    status, doc = api.json("GET", "api/ghost/lateral-raise.json")
    assert status == 200 and doc["available"] is True and doc["format"] == "simon.skeleton2d.v1" and len(doc["frames"]) == 3
    assert doc["source"] == "animation", "no trainer job yet: the body ghost"
    status, doc = api.json("GET", "api/ghost/empty.json")
    assert status == 200 and doc == {"available": False, "entry_id": "empty", "reason": ghost.MSG_NONE}
    status, doc = api.json("GET", "api/ghost/not-there.json")
    assert status == 404


def test_app_route_answers_the_trainer_jobs_own_picture(api: Any) -> None:
    def fn(ctx: jobs.JobContext) -> dict[str, Any]:
        put_part2(ctx.dir / "work" / "trainer" / "part2", SEATED, FRONT, CHEST_UP_T, unseen=LEGS)
        return {"result": {"entry_id": "lateral-raise"}}

    rec = api.app.queue.submit("trainer", fn, entry_id="lateral-raise")
    assert api.app.queue.wait(rec["id"], 10)["status"] == "done"
    status, doc = api.json("GET", "api/ghost/lateral-raise.json")
    assert status == 200 and doc["source"] == "part2" and doc["box"] == "image" and doc["image_size"] == [640, 480]
    assert all(f["pts"][JOINTS.index("left_knee")] is None for f in doc["frames"])
    # AC-7: the 7-day job sweep (with its ghost sweep) removes the trainer job folder; the entry keeps its picture
    entry_dir = api.app.child.catalog_dir / "lateral-raise"
    entry_dir.mkdir(parents=True, exist_ok=True)
    assert api.app.queue.cleanup(now=time.time() + 8 * 86400) >= 1 and not api.app.queue.job_dir(rec["id"]).exists()
    assert api.json("GET", "api/ghost/lateral-raise.json") == (200, doc)
    shutil.rmtree(entry_dir)  # the movement left the catalog: the next sweep drops its copy
    api.app.queue.cleanup()
    assert ghost.kept(api.app.state, "lateral-raise") is None
