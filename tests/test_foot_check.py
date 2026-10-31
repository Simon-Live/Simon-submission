"""`python -m part2.foot_check` and `make check-feet` (TICKET-043, docs/specs/integration-contract.md AC-C16): coverage,
segment-length consistency and plausibility of the optional foot points, on synthetic pose3d files with known numbers.
Reported, never gated."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from part2 import doctor, foot_check
from part2.joints import CANONICAL, EXTRA

ROOT = Path(__file__).resolve().parent.parent
ANKLE = {"left": [0.1, -0.88, -0.03], "right": [-0.1, -0.88, -0.03]}


def pt(xyz, conf=1.0) -> dict:
    x, y, z = (float(v) for v in xyz)
    return {"x": x, "y": y, "z": z, "conf": conf}


def joints() -> dict:
    out = {j: pt([0.0, 0.0, 0.0]) for j in CANONICAL}
    out.update({f"{side}_ankle": pt(a) for side, a in ANKLE.items()})
    return out


def feet(heel=0.08, toe=0.15, gap=0.05, conf=1.0) -> dict:
    """The six points at known distances: heel `heel` m behind each ankle, big toe `toe` m in front of it, small toe
    `gap` m to the outside of the big toe."""
    out = {}
    for side, a in ANKLE.items():
        a, outward = np.array(a), (1 if side == "left" else -1)
        big = a + [0, 0, toe]
        out.update({f"{side}_heel": pt(a + [0, 0, -heel], conf), f"{side}_big_toe": pt(big, conf),
                    f"{side}_small_toe": pt(big + [outward * gap, 0, 0], conf)})
    return out


def doc_of(extra_per_frame, pid=0) -> dict:
    people = lambda e: [{"id": pid, "joints": joints(), **({} if e is None else {"extra_joints": e})}]  # noqa: E731
    return {"frames": [{"frame": i, "t_ms": i * 100.0, "people": people(e)} for i, e in enumerate(extra_per_frame)]}


def write(tmp_path, doc, name="pose3d.json") -> Path:
    path = tmp_path / name
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    return path


def test_segment_means_and_coefficients_of_variation():
    r = foot_check.check_doc(doc_of([feet(toe=t) for t in (0.15, 0.15, 0.20, 0.10)]))
    assert (r["person_frames"], r["with_all_six"], r["coverage"], r["points"]) == (4, 4, 1.0, 24)
    seg = r["people"]["0"]["segments"]
    assert seg["left_ankle-left_heel"] == {"n": 4, "mean_m": 0.08, "cv": 0.0}
    assert seg["right_big_toe-right_small_toe"] == {"n": 4, "mean_m": 0.05, "cv": 0.0}
    toe = seg["left_ankle-left_big_toe"]
    assert toe["n"] == 4 and toe["mean_m"] == pytest.approx(0.15) and toe["cv"] == pytest.approx(0.2357, abs=1e-4)
    assert list(seg) == [f"{a}-{b}" for a, b in foot_check.SEGMENTS] and len(seg) == 6
    assert (r["within_bound"], r["points_within_bound"], r["low_conf"]) == (1.0, 24, 0.0)
    assert r["max_ankle_m"] == pytest.approx(np.hypot(0.20, 0.05), abs=1e-4)  # the small toe in front of the 0.20 m toe


def test_coverage_counts_person_frames_with_all_six_present_and_finite():
    missing, null = feet(), feet()
    del missing["right_heel"]
    null["left_small_toe"] = None
    r = foot_check.check_doc(doc_of([feet(), missing, null, feet()]))
    assert (r["with_all_six"], r["coverage"], r["points"]) == (2, 0.5, 22)
    seg = r["people"]["0"]["segments"]
    assert seg["right_ankle-right_heel"]["n"] == 3 and seg["left_big_toe-left_small_toe"]["n"] == 3


def test_a_point_beyond_the_bound_and_low_confidence_points_are_counted():
    far = feet()
    far["left_heel"] = pt(np.array(ANKLE["left"]) + [0, -0.5, 0])
    r = foot_check.check_doc(doc_of([far, feet(conf=0.3), feet(), feet()]))
    assert foot_check.BOUND_M == 0.35
    assert r["points_within_bound"] == 23 and r["within_bound"] == round(23 / 24, 4) and r["max_ankle_m"] == 0.5
    assert r["low_conf"] == 0.25


def test_a_file_without_foot_points_reports_zero_coverage():
    r = foot_check.check_doc(doc_of([None, None]))
    got = (r["person_frames"], r["coverage"], r["points"], r["within_bound"], r["max_ankle_m"])
    assert got == (2, 0.0, 0, 0.0, None)
    assert all(s == {"n": 0, "mean_m": None, "cv": None} for s in r["people"]["0"]["segments"].values())


def test_one_frame_gives_a_mean_and_no_cv_and_people_are_reported_apart():
    doc = doc_of([feet()])
    doc["frames"][0]["people"].append({"id": "b", "joints": joints(), "extra_joints": feet(heel=0.1)})
    r = foot_check.check_doc(doc)
    assert set(r["people"]) == {"0", '"b"'}  # the id as JSON: the integer 0 and the string "b"
    assert r["people"]['"b"']["segments"]["left_ankle-left_heel"] == {"n": 1, "mean_m": 0.1, "cv": None}


def test_ids_0_and_the_string_0_are_two_people_each_with_its_own_numbers():
    doc = doc_of([feet(heel=0.08), feet(heel=0.08)], pid=0)
    for f in doc["frames"]:
        f["people"].append({"id": "0", "joints": joints(), "extra_joints": feet(heel=0.12)})
        f["people"].append({"id": None, "joints": joints(), "extra_joints": feet(heel=0.2)})  # a person without an id
    r = foot_check.check_doc(doc)
    assert set(r["people"]) == {"0", '"0"', "null"} and r["person_frames"] == 6
    heel = {k: v["segments"]["left_ankle-left_heel"] for k, v in r["people"].items()}
    # grouped by str(id), 0 and "0" would merge into one person of n 4 with a cv above 0
    assert heel == {"0": {"n": 2, "mean_m": 0.08, "cv": 0.0}, '"0"': {"n": 2, "mean_m": 0.12, "cv": 0.0},
                    "null": {"n": 2, "mean_m": 0.2, "cv": 0.0}}


def test_people_are_read_with_the_one_helper_of_doctor():
    assert foot_check.people_in is doctor.people_in and not hasattr(doctor, "_people") and not hasattr(foot_check, "people")
    doc = {"frames": [5, {"people": "x"}, {"frame": 1}, {"people": [1, {"id": 1}, "z", {"id": "a"}]}, {"people": []}]}
    assert list(doctor.people_in(doc)) == [{"id": 1}, {"id": "a"}] and list(doctor.people_in({})) == []
    assert foot_check.check_doc(doc)["person_frames"] == 2


def test_an_empty_file_and_a_frame_without_people():
    r = foot_check.check_doc({"frames": [{"frame": 0, "t_ms": 0.0, "people": []}]})
    assert (r["person_frames"], r["coverage"], r["people"]) == (0, 0.0, {})


def test_files_are_summed_and_an_unreadable_file_is_named_exit_2(tmp_path):
    a = write(tmp_path, doc_of([feet(), feet()]), "a.json")
    b = write(tmp_path, doc_of([None, None]), "b.json")
    bad = write(tmp_path, "{not json", "bad.json")
    shape = write(tmp_path, {"people": []}, "shape.json")
    report, code = foot_check.check_files([a, b])
    assert code == 0 and report["gated"] is False and report["bound_m"] == 0.35
    assert report["summary"] == {"files": 2, "unreadable": 0, "person_frames": 4, "with_all_six": 2, "coverage": 0.5,
                                 "points": 12, "within_bound": 1.0}
    report, code = foot_check.check_files([a, bad, tmp_path / "missing.json", shape])
    assert code == 2 and report["summary"]["files"] == 1 and report["summary"]["unreadable"] == 3
    errors = [f.get("error", "") for f in report["files"]]
    assert errors[0] == "" and "not JSON (line 1)" in errors[1] and "cannot read" in errors[2]
    assert "no frames list" in errors[3]


def test_the_module_runs_prints_json_and_exits_0_whatever_the_numbers(tmp_path):
    far = feet(toe=0.9)  # every big toe implausibly far: still exit 0
    path = write(tmp_path, doc_of([far, None]))
    r = subprocess.run([sys.executable, "-m", "part2.foot_check", str(path)], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["files"][0]["coverage"] == 0.5 and out["files"][0]["within_bound"] < 1.0
    r = subprocess.run([sys.executable, "-m", "part2.foot_check", str(tmp_path / "nope.json")], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 2 and "cannot read" in json.loads(r.stdout)["files"][0]["error"]


def run_module(*args):
    return subprocess.run([sys.executable, "-m", "part2.foot_check", *map(str, args)], cwd=ROOT, capture_output=True,
                          text=True)


def put(root: Path, mode: str, doc) -> Path:
    (root / mode).mkdir(parents=True, exist_ok=True)
    return write(root / mode, doc)


def test_no_file_at_all_is_an_empty_json_report_with_exit_0_not_a_usage_error():
    r = run_module()
    assert r.returncode == 0 and r.stderr == ""
    out = json.loads(r.stdout)
    assert out["files"] == [] and out["gated"] is False and out["bound_m"] == 0.35
    assert out["summary"] == {"files": 0, "unreadable": 0, "person_frames": 0, "with_all_six": 0, "coverage": 0.0,
                              "points": 0, "within_bound": 0.0}
    assert foot_check.check_files([]) == (out, 0)


def test_scored_names_every_expected_file_of_the_gpu_sets_present_or_not(tmp_path):
    paths, problems = foot_check.scored_files(tmp_path)
    ids = [r["image_id"] for r in json.loads(foot_check.COCO_MANIFEST.read_text())["images"]]
    assert problems == [] and len(ids) == 20
    assert paths[:3] == [tmp_path / m / "pose3d.json" for m in ("single", "class", "class-local-open")]
    assert paths[3:] == [tmp_path / "coco-single" / str(i) / "pose3d.json" for i in ids]
    assert not any("cpu-single" in str(p) for p in paths)


def test_a_missing_scored_file_is_reported_as_unreadable_not_dropped(tmp_path):
    put(tmp_path, "single", doc_of([feet(), feet()]))
    put(tmp_path, "class", doc_of([feet()]))
    r = run_module("--scored", tmp_path)
    out = json.loads(r.stdout)
    assert r.returncode == 2 and len(out["files"]) == 23
    assert [f["file"] for f in out["files"][:3]] == [str(tmp_path / m / "pose3d.json")
                                                     for m in ("single", "class", "class-local-open")]
    assert out["files"][0]["person_frames"] == 2 and out["files"][1]["person_frames"] == 1
    bad = [f for f in out["files"] if "error" in f]
    assert len(bad) == 21 and all("cannot read" in f["error"] for f in bad)
    assert bad[0]["file"].endswith("class-local-open/pose3d.json")
    assert bad[1]["file"].endswith("coco-single/785/pose3d.json")  # the manifest's first image
    assert out["summary"]["files"] == 2 and out["summary"]["unreadable"] == 21 and out["summary"]["person_frames"] == 3


def test_a_complete_scored_dir_exits_0_and_explicit_files_are_added_to_it(tmp_path):
    paths, _ = foot_check.scored_files(tmp_path)
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        write(p.parent, doc_of([feet()]))
    extra = write(tmp_path, doc_of([None]), "extra.json")
    r = run_module("--scored", tmp_path, extra)
    out = json.loads(r.stdout)
    assert r.returncode == 0 and len(out["files"]) == 24 and out["files"][-1]["file"] == str(extra)
    assert all("error" not in f for f in out["files"]) and out["summary"]["files"] == 24
    assert out["files"][0]["coverage"] == 1.0 and out["files"][-1]["coverage"] == 0.0


def test_the_committed_scored_layout_is_listed_whole_and_every_listed_file_exists():
    scored = ROOT / "fixtures" / "output" / "scored"
    paths, problems = foot_check.scored_files(scored)
    on_disk = sorted((scored / "coco-single").glob("*/pose3d.json"))
    assert problems == [] and all(p.is_file() for p in paths)
    assert sorted(paths[3:]) == on_disk and len(on_disk) == 20


def test_an_unreadable_or_odd_manifest_is_named_and_exits_2(tmp_path, monkeypatch):
    for text, needle in (("{not json", "not JSON"), ('{"images": [{"file": 1}]}', "not a coco image manifest"),
                         ("[]", "not a coco image manifest")):
        manifest = write(tmp_path, text, "images.json")
        monkeypatch.setattr(foot_check, "COCO_MANIFEST", manifest)
        paths, problems = foot_check.scored_files(tmp_path)
        assert len(paths) == 3 and len(problems) == 1 and problems[0]["file"] == str(manifest)
        assert needle in problems[0]["error"]
        report, code = foot_check.check_files(paths, problems)
        assert code == 2 and report["files"][0] == problems[0] and report["summary"]["unreadable"] == 4
    monkeypatch.setattr(foot_check, "COCO_MANIFEST", tmp_path / "gone.json")
    assert "cannot read" in foot_check.scored_files(tmp_path)[1][0]["error"]


def test_make_check_feet_passes_the_scored_dir_to_the_module_which_names_the_files():
    for args, scored in (([], "fixtures/output/scored"), (["SCORED=out"], "out")):
        r = subprocess.run(["make", "-n", "check-feet", *args], cwd=ROOT, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip().endswith(f"python -m part2.foot_check --scored {scored}")
        assert "cpu-single" not in r.stdout and "part2 check" not in r.stdout


def test_the_names_follow_part2_joints():
    assert {n for s in foot_check.SEGMENTS for n in s} - {"left_ankle", "right_ankle"} == set(EXTRA)
