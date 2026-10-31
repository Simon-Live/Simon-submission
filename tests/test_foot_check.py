"""`python -m part2.foot_check` and `make check-feet` (TICKET-043, docs/specs/integration-contract.md AC-C16): coverage,
segment-length consistency and plausibility of the optional foot points, on synthetic pose3d files with known numbers.
Reported, never gated."""
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from part2 import check, coco_set, doctor, foot_check, outputs
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


def without_ankles(doc: dict, *sides) -> dict:
    """doc with the named sides' ankle joints null (a joint the model did not give), in every person-frame."""
    for f in doc["frames"]:
        for p in f["people"]:
            p["joints"].update({f"{side}_ankle": None for side in sides})
    return doc


def test_within_bound_counts_only_points_whose_ankle_is_readable_and_the_rest_are_reported_apart():
    far = feet()
    far["left_heel"] = pt(np.array(ANKLE["left"]) + [0, -0.5, 0])  # a measured point beyond the bound
    r = foot_check.check_doc(without_ankles(doc_of([far, feet()]), "right"))
    # 12 points present; the 6 of the right foot have no ankle to be measured against and are not counted either way
    assert (r["points"], r["points_with_ankle"], r["points_without_ankle"]) == (12, 6, 6)
    assert r["points_within_bound"] == 5 and r["within_bound"] == round(5 / 6, 4)  # not 5 / 12
    assert r["max_ankle_m"] == 0.5
    assert r["with_all_six"] == 2  # coverage is about the six points, not about the ankles


def test_max_ankle_is_null_not_zero_when_no_point_could_be_measured():
    r = foot_check.check_doc(without_ankles(doc_of([feet(), feet()]), "left", "right"))
    got = (r["points"], r["points_with_ankle"], r["points_without_ankle"], r["points_within_bound"])
    assert got == (12, 0, 12, 0) and r["max_ankle_m"] is None and r["within_bound"] == 0.0
    assert r["coverage"] == 1.0


def test_the_summary_measures_within_bound_over_points_with_an_ankle_across_files(tmp_path):
    whole = write(tmp_path, doc_of([feet()]), "whole.json")  # 6 measured points, all within
    half = write(tmp_path, without_ankles(doc_of([feet()]), "right"), "half.json")  # 3 measured
    report, code = foot_check.check_files([whole, half])
    assert code == 0 and [f["points_without_ankle"] for f in report["files"]] == [0, 3]
    assert report["summary"]["points"] == 12 and report["summary"]["points_without_ankle"] == 3
    assert report["summary"]["within_bound"] == 1.0  # 9 of 9 measured, not 9 of 12


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
                                 "points": 12, "points_without_ankle": 0, "within_bound": 1.0}
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


def run_module(*args, scored_env=None):
    """The module as a process; PART2_SCORED_DIR is scored_env, or unset when None (what make check-2 also reads)."""
    env = {k: v for k, v in os.environ.items() if k != check.SCORED_ENV}
    if scored_env is not None:
        env[check.SCORED_ENV] = str(scored_env)
    return subprocess.run([sys.executable, "-m", "part2.foot_check", *map(str, args)], cwd=ROOT, capture_output=True,
                          text=True, env=env)


def put(root: Path, mode: str, doc) -> Path:
    (root / mode).mkdir(parents=True, exist_ok=True)
    return write(root / mode, doc)


def test_check_files_with_no_file_is_an_empty_report_with_exit_0():
    report, code = foot_check.check_files([])
    assert code == 0 and report["files"] == [] and report["gated"] is False and report["bound_m"] == 0.35
    assert report["summary"] == {"files": 0, "unreadable": 0, "person_frames": 0, "with_all_six": 0, "coverage": 0.0,
                                 "points": 0, "points_without_ankle": 0, "within_bound": 0.0}


def expected_scored_files(scored: Path) -> list[Path]:
    """What outputs.MODES and the committed manifest imply for the gpu backend, written out without foot_check."""
    ids = [str(r["image_id"]) for r in json.loads(coco_set.MANIFEST.read_text())["images"]]
    out = []
    for m in outputs.MODES:
        if m.backend == "gpu":
            out += ([scored / m.name / i / "pose3d.json" for i in ids] if m.run is outputs.run_coco
                    else [scored / m.name / "pose3d.json"])
    return out


def test_scored_names_every_expected_file_of_the_gpu_sets_present_or_not(tmp_path):
    paths, problems = foot_check.scored_files(tmp_path)
    assert problems == [] and paths == expected_scored_files(tmp_path)
    assert len(paths) == 23 and paths[0] == tmp_path / "single" / "pose3d.json"  # 3 whole-clip modes + 20 coco images
    assert sum(p.parts[-3] == "coco-single" for p in paths) == 20 and not any("cpu-single" in str(p) for p in paths)
    assert "COCO_MANIFEST" not in vars(foot_check) and "SCORED_MODES" not in vars(foot_check)  # one list, not a copy


def test_a_gpu_mode_added_to_outputs_is_checked_with_no_edit_and_a_cpu_mode_is_not(tmp_path, monkeypatch):
    before = foot_check.scored_files(tmp_path)[0]
    fake_gpu = outputs.Mode("fake-gpu", "gpu", "fixtures/input/single/frames", outputs.run_single)
    fake_cpu = outputs.Mode("fake-cpu", "cpu", "fixtures/input/single/frames", outputs.run_single)
    monkeypatch.setattr(outputs, "MODES", [*outputs.MODES, fake_gpu, fake_cpu])
    after, problems = foot_check.scored_files(tmp_path)
    assert problems == [] and after == [*before, tmp_path / "fake-gpu" / "pose3d.json"]
    assert after == expected_scored_files(tmp_path)
    monkeypatch.setattr(outputs, "MODES", [m for m in outputs.MODES if m.name != "class"])
    assert tmp_path / "class" / "pose3d.json" not in foot_check.scored_files(tmp_path)[0]  # a removed mode is not expected


def test_importing_foot_check_loads_no_model_code():
    code = ("import sys, part2.foot_check; print([m for m in ('torch', 'cv2', 'onnxruntime', 'transformers') "
            "if m in sys.modules])")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "[]"


def test_with_no_file_and_no_flag_the_scored_dir_is_the_one_check_2_reads():
    assert check.scored_dir() == ROOT / "fixtures" / "output" / "scored"
    r = run_module()
    out = json.loads(r.stdout)
    assert r.returncode == 0 and r.stderr == "" and len(out["files"]) == 23 and out["summary"]["unreadable"] == 0
    assert out["files"][0]["file"] == str(check.scored_dir() / "single" / "pose3d.json")


def test_part2_scored_dir_with_no_flag_is_read_like_check_2_and_the_flag_wins(tmp_path):
    env_dir, flag_dir = tmp_path / "from-env", tmp_path / "from-flag"
    paths, _ = foot_check.scored_files(env_dir)
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        write(p.parent, doc_of([feet()]))
    r = run_module(scored_env=env_dir)
    out = json.loads(r.stdout)
    assert r.returncode == 0 and out["summary"]["files"] == 23 and out["summary"]["unreadable"] == 0
    assert [f["file"] for f in out["files"]] == [str(p) for p in paths]
    r = run_module("--scored", flag_dir, scored_env=env_dir)  # the flag first, as in check.scored_dir
    out = json.loads(r.stdout)
    assert r.returncode == 2 and out["summary"]["files"] == 0
    assert out["files"][0]["file"] == str(flag_dir / "single" / "pose3d.json")


def test_explicit_files_alone_are_checked_alone_whatever_the_environment(tmp_path):
    only = write(tmp_path, doc_of([feet()]), "only.json")
    r = run_module(only, scored_env=tmp_path / "elsewhere")
    out = json.loads(r.stdout)
    assert r.returncode == 0 and [f["file"] for f in out["files"]] == [str(only)]


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
    assert sorted(p for p in paths if p.parts[-3] == "coco-single") == on_disk and len(on_disk) == 20


def test_an_unreadable_or_odd_manifest_is_named_and_exits_2(tmp_path, monkeypatch):
    for text, needle in (("{not json", "not JSON"), ('{"images": [{"file": 1}]}', "not a coco image manifest"),
                         ("[]", "not a coco image manifest")):
        manifest = write(tmp_path, text, "images.json")
        monkeypatch.setattr(coco_set, "MANIFEST", manifest)
        paths, problems = foot_check.scored_files(tmp_path)
        whole_clip = len(outputs.modes_for("gpu")) - 1  # every gpu mode but coco-single, which the manifest expands
        assert len(paths) == whole_clip and len(problems) == 1 and problems[0]["file"] == str(manifest)
        assert needle in problems[0]["error"]
        report, code = foot_check.check_files(paths, problems)
        assert code == 2 and report["files"][0] == problems[0] and report["summary"]["unreadable"] == whole_clip + 1
    monkeypatch.setattr(coco_set, "MANIFEST", tmp_path / "gone.json")
    assert "cannot read" in foot_check.scored_files(tmp_path)[1][0]["error"]


def make_n(*args, env=None):
    base = {k: v for k, v in os.environ.items() if k != check.SCORED_ENV}
    r = subprocess.run(["make", "-n", "check-feet", *args], cwd=ROOT, capture_output=True, text=True,
                       env={**base, **(env or {})})
    assert r.returncode == 0, r.stderr
    assert "cpu-single" not in r.stdout and "part2 check" not in r.stdout and "FEET_DIR" not in r.stdout
    return r.stdout.strip()


def test_make_check_feet_passes_the_flag_only_for_scored_and_leaves_the_default_to_the_module():
    assert make_n().endswith("python -m part2.foot_check")  # no --scored: the module reads PART2_SCORED_DIR or the default
    assert make_n("SCORED=out").endswith("python -m part2.foot_check --scored out")
    assert make_n(env={check.SCORED_ENV: "elsewhere"}).endswith("python -m part2.foot_check")  # the env reaches the module
    assert "FEET_DIR" not in (ROOT / "Makefile").read_text()


def test_both_targets_choose_the_same_dir_for_scored_the_env_and_the_default():
    make2 = subprocess.run(["make", "-n", "check-2", "SCORED=out"], cwd=ROOT, capture_output=True, text=True)
    assert make2.returncode == 0 and f"{check.SCORED_ENV}=out" in make2.stdout  # check-2 takes SCORED=out as the env
    for flag, env in (("out", None), (None, "out"), (None, None)):
        r = run_module(*(["--scored", flag] if flag else []), scored_env=env)
        first = json.loads(r.stdout)["files"][0]["file"]
        assert first == str(check.scored_dir(ROOT, flag or env) / "single" / "pose3d.json"), (flag, env)


def test_the_names_follow_part2_joints():
    assert {n for s in foot_check.SEGMENTS for n in s} - {"left_ankle", "right_ankle"} == set(EXTRA)
