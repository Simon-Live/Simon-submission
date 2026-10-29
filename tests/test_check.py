"""`make check-2` on the committed scored outputs (docs/specs/check-2.md AC-K01 to AC-K07, AC-K10, AC-K13, AC-K14).

Temp roots hold a copy of part2/ (test_stamp.make_root), hand-made fixtures and outputs stamped the way
part2.outputs stamps them."""
import ast
import builtins
import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest
from test_eval_3d import _pose3d
from test_eval_reproj import _setup
from test_lifter_fixed_bones import skeleton
from test_stamp import make_root, stamped, touch

from part2 import check, stamp

ROOT = Path(__file__).resolve().parent.parent
MULTI = ("part2.track", "part2.multi3d")
LABEL_SHA256 = {  # upstream 7e11a7f; the gold labels are read-only (ADR-0004, AC-K06)
    "fixtures/input/single/labels_2d.json": "b830ee137c5cfd8d261bd7a00759673ba79e41df3098ccffbd92f92b450e3a7b",
    "fixtures/input/class/gt_tracks.json": "3357eac5a400dfaf4cfd9470d8ad2ca766fe8a7026dc695ee7b0e53a92b38923",
}


def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))


def _single(root, labels_ok=True, mode="single", backend="gpu", lifter=None, profile="gpu-cu128"):
    pose3d, camera, labels = _setup()
    if not labels_ok:
        labels["frames"][0]["joints"]["left_wrist"][1] += 1000
    _write(root / "fixtures/input/single/labels_2d.json", labels)
    out = root / "fixtures/output/scored" / mode
    _write(out / "pose3d.json", pose3d)
    _write(out / "camera.json", camera)
    return stamped(root, mode, backend=backend, lifter=lifter, profile=profile, files=("pose3d.json", "camera.json"))


def _class(root, mode="class", tracker="api-sam31", n_people=5, n_tracked=None):
    """GT with n_people on every keyframe; tracks.json and pose3d.json with the first n_tracked of them."""
    n_tracked = n_people if n_tracked is None else n_tracked
    frames = range(3)
    box = lambda i: [100.0 * i, 0.0, 50.0, 100.0]  # noqa: E731
    gt = {"keyframes_only": True, "frames": [{"frame": f, "people": [{"id": f"g{i}", "bbox": box(i)}
                                                                      for i in range(n_people)]} for f in frames]}
    _write(root / "fixtures/input/class/gt_tracks.json", gt)
    tracks = {"frames": [{"frame": f, "people": [{"id": i, "bbox": box(i), "confidence": 0.9,
                                                  "mask_rle": {"size": [2, 2], "counts": "04"}} for i in range(n_tracked)]}
                         for f in frames]}
    joints = {j: {"x": 0.0, "y": 0.0, "z": 0.0, "conf": 1.0} for j in _setup()[0]["frames"][0]["people"][0]["joints"]}
    pose3d = {"frames": [{"frame": f, "t_ms": f * 1000.0, "people": [{"id": i, "joints": joints} for i in range(n_tracked)]}
                         for f in frames]}
    out = root / "fixtures/output/scored" / mode
    _write(out / "tracks.json", tracks)
    _write(out / "pose3d.json", pose3d)
    return stamped(root, mode, frames="class", tracker=tracker, modules=MULTI, files=("tracks.json", "pose3d.json"))


def _cpu(root, offset=0.0):
    """scored/cpu-single: the GPU reference scored/single shifted by `offset` m (a 6-frame skeleton reference is
    written first when there is none)."""
    ref = root / "fixtures/output/scored/single"
    if not (ref / "pose3d.json").is_file():
        _write(ref / "pose3d.json", _pose3d(skeleton(6)))
        stamped(root, "single")
    doc = json.loads((ref / "pose3d.json").read_text())
    for f in doc["frames"]:
        for j in f["people"][0]["joints"].values():
            j["x"] += offset
    _write(root / "fixtures/output/scored/cpu-single/pose3d.json", doc)
    stamped(root, "cpu-single", backend="cpu", lifter="fixed-bones", profile="cpu")


def _coco(root, monkeypatch, passing=True):
    _write(root / check.COCO_LABELS, {"images": []})
    out = root / "fixtures/output/scored/coco-single"
    _write(out / "img0" / "pose3d.json", {"frames": []})
    stamped(root, "coco-single", files=("img0/pose3d.json",))
    fake = types.ModuleType("part2.eval_coco")
    fake.block = lambda scored_dir, labels_path: {"metric": "reprojection_error_pct_of_body_height", "pass": passing,
                                                      "dir": scored_dir.name}
    monkeypatch.setitem(sys.modules, "part2.eval_coco", fake)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.delenv("PART2_SCORED_DIR", raising=False)
    return make_root(tmp_path)


# ---- AC-K01, AC-K05: committed outputs scored, each naming its producer --------------------------------

def test_scored_outputs_pass_and_name_what_made_them(root, monkeypatch):
    _single(root)
    _class(root)
    _coco(root, monkeypatch)
    r = check.run(root)
    assert r["one_person"]["pass"] is True and r["one_person"]["n_frames"] == 20 and "nose" in r["one_person"]["body_height"]
    assert "per_frame" not in r["one_person"]
    assert r["one_person"]["outputs"] | {"code_sha256": None, "created_utc": None} == {
        "dir": "fixtures/output/scored/single", "backend": "gpu", "tracker": None, "lifter": None, "refine": [],
        "stamp": "fresh", "code_sha256": None, "env_profile": "gpu-cu128", "host_gpu": "Test GPU", "created_utc": None}
    assert r["multi_person"]["pass"] is True and r["multi_person"]["n_gt_people"] == 5
    assert r["multi_person"]["outputs"]["tracker"] == "api-sam31"
    assert r["one_person_coco"]["pass"] is True and "per_frame" not in r["one_person_coco"]
    assert r["one_person_coco"]["dir"] == "coco-single"
    assert list(r) == ["one_person", "one_person_coco", "multi_person", "multi_person_local_open", "cpu_backend_3d", "pass"]
    assert r["pass"] is True


def test_single_fails_on_bad_reprojection(root):
    _single(root, labels_ok=False)
    m = check.check_single(root)
    assert m["pass"] is False and m["n_failed_frames"] == 1


def test_labels_do_not_invalidate_outputs(root):
    _single(root)
    labels = root / "fixtures/input/single/labels_2d.json"
    labels.write_text(labels.read_text() + " ")
    assert check.check_single(root)["pass"] is True


# ---- AC-K02: SCORED override ---------------------------------------------------------------------------

def test_scored_override_reads_another_dir_with_the_same_rules(root, monkeypatch):
    out = _single(root)
    (root / "out").mkdir()
    out.rename(root / "out" / "single")
    monkeypatch.setenv("PART2_SCORED_DIR", "out")
    m = check.check_single(root)
    assert m["pass"] is True and m["outputs"]["dir"] == "out/single" and m["outputs"]["stamp"] == "fresh"
    monkeypatch.delenv("PART2_SCORED_DIR")
    assert check.run(root, "out")["one_person"]["pass"] is True
    assert check.check_single(root)["status"].startswith("missing output fixtures/output/scored/single/pose3d.json")


# ---- AC-K03, AC-K04: stale and v1 stamps fail their mode only -------------------------------------------

def test_a_stale_mode_fails_with_what_changed_and_the_others_still_score(root):
    _single(root)
    _class(root)
    touch(root / "part2" / "trackers" / "api_sam31.py")
    r = check.run(root)
    assert r["one_person"]["pass"] is True
    mp = r["multi_person"]
    assert mp["pass"] is False and mp["outputs"]["stamp"] == "stale"
    assert mp["status"].startswith("fixtures/output/scored/class is stale: code changed since ")
    assert mp["changed_files"] == ["part2/trackers/api_sam31.py"]


def test_a_cpu_lock_change_leaves_the_gpu_modes_fresh(root):
    _single(root)
    _class(root)
    touch(root / "envs" / "cpu" / "requirements.txt")
    r = check.run(root)
    assert r["one_person"]["pass"] is True and r["multi_person"]["pass"] is True


def test_a_v1_stamp_fails_its_mode_with_the_v1_message(root):
    out = _single(root)
    (out / "stamp.json").write_text(json.dumps({"fingerprint": "abc"}))
    m = check.check_single(root)
    assert m["pass"] is False and m["status"] == "stamp v1 from HPC; run make outputs" and m["outputs"]["stamp"] == "v1"


def test_an_edited_output_fails(root):
    out = _single(root)
    pose = json.loads((out / "pose3d.json").read_text())
    pose["frames"] = pose["frames"][:-1]
    (out / "pose3d.json").write_text(json.dumps(pose))
    assert "does not match its stamp" in check.check_single(root)["status"]


# ---- AC-K06: scoring rules and labels unchanged ---------------------------------------------------------

def test_gold_labels_match_the_recorded_upstream_digests():
    for rel, digest in LABEL_SHA256.items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, rel


def _code_only(src: str) -> str:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                node.body = node.body[1:] or [ast.Pass()]
    return ast.dump(tree)


@pytest.mark.parametrize("rel", ["part2/eval_reproj.py", "part2/eval_tracks.py"])
def test_evals_have_no_code_diff_against_upstream(rel):
    old = subprocess.run(["git", "show", f"7e11a7f:{rel}"], cwd=ROOT, capture_output=True, text=True)
    if old.returncode != 0:
        pytest.skip("upstream commit 7e11a7f not in this clone (shallow)")
    assert _code_only(old.stdout) == _code_only((ROOT / rel).read_text())


def test_rule_constants_unchanged():
    from part2 import eval_3d, eval_reproj, eval_tracks

    assert (eval_reproj.THRESHOLD, eval_reproj.MIN_FRAMES) == (0.05, 20)
    assert (eval_tracks.IOU_THRESHOLD, eval_tracks.MIN_COVERAGE, eval_tracks.MAX_SWAPS_PER_MIN, eval_tracks.MIN_PEOPLE) == \
        (0.5, 0.95, 1.0, 5)
    assert (eval_3d.MAX_MEAN_M, eval_3d.MAX_BONE_CV) == (0.10, 0.05)


# ---- AC-K07: the CPU 3D bar ----------------------------------------------------------------------------

def test_cpu_block_is_printed_and_never_changes_the_top_level_pass(root, monkeypatch):
    _single(root)
    _class(root)
    _coco(root, monkeypatch)
    r = check.run(root)
    assert r["cpu_backend_3d"]["status"] == "no cpu outputs; run make outputs BACKEND=cpu" and r["pass"] is True
    _cpu(root, offset=0.5)
    r = check.run(root)
    cpu = r["cpu_backend_3d"]
    assert cpu["pass"] is False and cpu["mean_m"] == pytest.approx(0.5, abs=1e-4) and r["pass"] is True
    assert cpu["mean_joint_distance_m"] == cpu["mean_m"] and cpu["bone_length_cv_mean"] == cpu["bone_cv_mean"]
    assert cpu["bone_length_cv_max"] == cpu["bone_cv_max"] and cpu["lifter"] == "fixed-bones" and cpu["frames"] == 20
    assert cpu["reference"] == "fixtures/output/scored/single" and cpu["outputs"]["backend"] == "cpu"
    _cpu(root, offset=0.0)
    r = check.run(root)
    assert r["cpu_backend_3d"]["pass"] is True and r["pass"] is True and "cpu_backend_3d" not in check.GATED
    _class(root, n_tracked=4)  # the gated blocks alone decide: a red multi_person is red with a green bar
    r = check.run(root)
    assert r["cpu_backend_3d"]["pass"] is True and r["pass"] is False


def test_check_2_cpu_exits_by_the_block(root, capsys):
    assert check.main(["--block", "cpu_backend_3d"], root=root) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "no cpu outputs; run make outputs BACKEND=cpu"
    _cpu(root, offset=0.0)
    assert check.main(["--block", "cpu_backend_3d"], root=root) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["pass"] is True and out["frames"] == 6 and out["lifter"] == "fixed-bones"
    _cpu(root, offset=0.3)
    assert check.main(["--block", "cpu_backend_3d"], root=root) == 1
    capsys.readouterr()
    (root / "fixtures/output/scored/single/pose3d.json").unlink()
    assert check.main(["--block", "cpu_backend_3d"], root=root) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "no gpu reference; run make outputs BACKEND=gpu"


def test_a_stale_cpu_output_fails_the_bar(root, capsys):
    _cpu(root)
    touch(root / "part2" / "lifters" / "fixed_bones.py")
    b = check.check_cpu_3d(root)
    assert b["pass"] is False and "cpu-single is stale" in b["status"] and b["outputs"]["stamp"] == "stale"
    assert check.main(["--block", "cpu_backend_3d"], root=root) == 1


def test_other_blocks_exit_0_or_1(root, capsys):
    _single(root)
    assert check.main(["--block", "one_person"], root=root) == 0
    assert check.main(["--block", "multi_person"], root=root) == 1


# ---- AC-K10: nothing scored -----------------------------------------------------------------------------

def test_no_scored_dir_fails_every_mode_with_missing_output(root, capsys):
    _write(root / "fixtures/input/single/labels_2d.json", _setup()[2])
    _write(root / "fixtures/input/class/gt_tracks.json", {"frames": []})
    _write(root / check.COCO_LABELS, {"images": []})
    assert check.main([], root=root) == 1
    r = json.loads(capsys.readouterr().out)
    assert r["one_person"]["status"] == "missing output fixtures/output/scored/single/pose3d.json; run make outputs"
    assert r["multi_person"]["status"] == "missing output fixtures/output/scored/class/tracks.json; run make outputs"
    assert r["multi_person_local_open"]["status"].startswith("missing output fixtures/output/scored/class-local-open/")
    assert r["one_person_coco"]["status"] == "missing output fixtures/output/scored/coco-single/stamp.json; run make outputs"
    assert r["one_person_coco"]["pass"] is False and r["pass"] is False


def test_missing_fixture_inputs_are_named(tmp_path, monkeypatch):
    monkeypatch.delenv("PART2_SCORED_DIR", raising=False)
    r = check.run(tmp_path)
    assert r["pass"] is False
    assert r["one_person"]["status"].startswith("missing fixture input fixtures/input/single/frames")
    assert r["multi_person"]["status"].startswith("missing fixture input fixtures/input/class/frames")


def test_a_missing_stamp_is_a_missing_output(root):
    out = _single(root)
    (out / "stamp.json").unlink()
    assert check.check_single(root)["status"] == "missing output fixtures/output/scored/single/stamp.json; run make outputs"


# ---- AC-K13: COCO block ---------------------------------------------------------------------------------

def test_the_gate_needs_the_coco_block(root, monkeypatch):
    _single(root)
    _class(root)
    r = check.run(root)
    assert r["one_person_coco"]["pass"] is False and r["pass"] is False
    assert r["one_person_coco"]["status"] == f"missing fixture input {check.COCO_LABELS}"
    _coco(root, monkeypatch, passing=False)
    r = check.run(root)
    assert r["one_person_coco"]["pass"] is False and r["one_person"]["pass"] is True and r["pass"] is False
    assert r["one_person_coco"]["outputs"]["dir"] == "fixtures/output/scored/coco-single"


# ---- AC-K14: local-open reported, never gated -----------------------------------------------------------

def test_local_open_is_reported_beside_and_never_gated(root, monkeypatch):
    _single(root)
    _class(root)
    _coco(root, monkeypatch)
    _class(root, mode="class-local-open", tracker="local-open", n_tracked=4)
    r = check.run(root)
    lo = r["multi_person_local_open"]
    assert lo["gated"] is False and lo["pass"] is False and lo["n_gt_people"] == 5
    assert lo["outputs"]["tracker"] == "local-open" and lo["outputs"]["dir"] == "fixtures/output/scored/class-local-open"
    assert r["pass"] is True and "multi_person_local_open" not in check.GATED


def test_multi_person_is_scored_on_api_sam31_outputs_only(root):
    _class(root, tracker="local-open")
    m = check.check_class(root)
    assert m["pass"] is False
    assert m["status"] == "fixtures/output/scored/class was tracked by local-open, not api-sam31; run make outputs"
    _class(root, mode="class-local-open", tracker="api-sam31")
    assert "not local-open" in check.check_class_local_open(root)["status"]
    assert check.check_class_local_open(root)["gated"] is False


# ---- errors ---------------------------------------------------------------------------------------------

def test_crashing_eval_becomes_failed_json(root, monkeypatch):
    out = _single(root)
    from part2 import eval_reproj

    monkeypatch.setattr(eval_reproj, "evaluate_files", lambda *a, **k: (_ for _ in ()).throw(KeyError("nose")))
    r = check.run(root)
    assert r["one_person"] == {"pass": False, "status": "error: KeyError: 'nose'"}
    assert out.exists()


def test_class_without_eval_tracks_reports_it(root, monkeypatch):
    _class(root)
    real = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", lambda n, g=None, l=None, f=(), lv=0: (_ for _ in ()).throw(ImportError(n))
                        if f and "eval_tracks" in f else real(n, g, l, f, lv))
    assert "#13" in check.check_class(root)["status"]


# ---- the v1 interface of the team's k8s/ and hpc/ scripts -----------------------------------------------

def test_v1_fingerprint_and_stamp_still_work_and_read_as_v1(root, capsys):
    pose3d, camera, labels = _setup()
    _write(root / "fixtures/input/single/labels_2d.json", labels)
    fp = check.fingerprint("single", root)
    assert check.main(["fingerprint", "single"], root=root) == 0 and capsys.readouterr().out.strip() == fp
    _write(root / "out/single/pose3d.json", pose3d)
    _write(root / "out/single/camera.json", camera)
    assert check.main(["stamp", "single", fp], root=root) == 0
    assert json.loads((root / "out/single/stamp.json").read_text()) == {"fingerprint": fp}
    capsys.readouterr()
    assert check.run(root, "out")["one_person"]["status"] == "stamp v1 from HPC; run make outputs"


def test_scored_dir_resolution(tmp_path, monkeypatch):
    monkeypatch.delenv("PART2_SCORED_DIR", raising=False)
    assert check.scored_dir(tmp_path) == tmp_path / "fixtures/output/scored"
    monkeypatch.setenv("PART2_SCORED_DIR", "")
    assert check.scored_dir(tmp_path) == tmp_path / "fixtures/output/scored"
    monkeypatch.setenv("PART2_SCORED_DIR", str(tmp_path / "abs"))
    assert check.scored_dir(tmp_path) == tmp_path / "abs"
