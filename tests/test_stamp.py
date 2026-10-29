"""Stamp part2.stamp/2 (docs/specs/check-2.md "Scored outputs and stamps": AC-K03, AC-K04, AC-K08). ADR-0006.

Temp roots hold a copy of part2/ and the three profile lock files, so a stamp's code, frames and env lock can be
changed one at a time without touching the repo."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from part2 import backends, lifters, stamp, trackers

ROOT = Path(__file__).resolve().parent.parent
LOCKS = ("envs/gpu-cu128/constraints.txt", "envs/cpu/requirements.txt", "k8s/constraints-gpu.txt")
MULTI = ("part2.track", "part2.multi3d")


def make_root(tmp_path: Path, modes=("single", "class")) -> Path:
    """A temp repo root: part2/ copied, the profile locks copied, two fake frames per fixture mode."""
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "part2", root / "part2", ignore=shutil.ignore_patterns("__pycache__"))
    for lock in LOCKS:
        (root / lock).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / lock, root / lock)
    for mode in modes:
        write_frames(root / "fixtures" / "input" / mode / "frames")
    return root


def write_frames(d: Path, n=2) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (d / f"{i:06d}.jpg").write_bytes(b"\xff\xd8frame%d" % i)
    (d / "frames.json").write_text(json.dumps({"source": "test", "frames": [
        {"frame": i, "t_ms": i * 100.0, "file": f"{i:06d}.jpg"} for i in range(n)]}))
    return d


def stamped(root: Path, mode: str, backend="gpu", frames="single", files=("pose3d.json",), profile="gpu-cu128",
            tracker=None, lifter=None, modules=()) -> Path:
    """A scored dir with fake output files and a v2 stamp, as part2.outputs leaves it."""
    out = root / "fixtures" / "output" / "scored" / mode
    pre = stamp.prepare(root, mode, backend, root / "fixtures" / "input" / frames / "frames", modules,
                        tracker=tracker, lifter=lifter, profile=profile)
    out.mkdir(parents=True, exist_ok=True)
    for f in files:
        if not (out / f).exists():
            (out / f).write_text(json.dumps({"mode": mode, "file": f}))
    stamp.finish(pre, out, files, models=[{"name": "m", "source": "s", "weights_sha256": "ab", "licence": "x"}],
                 host_gpu="Test GPU", run={"frames": 2})
    return out


def touch(path: Path) -> None:
    path.write_text(path.read_text() + "\n# edited\n")


# ---- AC-K03: freshness per mode -------------------------------------------------------------------------

def test_a_fresh_stamp_checks_clean_and_names_its_producer(tmp_path):
    root = make_root(tmp_path)
    out = stamped(root, "single")
    assert stamp.check(out, root) is None
    doc = stamp.load(out)
    assert doc["schema"] == "part2.stamp/2" and doc["mode"] == "single" and doc["backend"] == "gpu"
    assert doc["tracker"] is None and doc["lifter"] is None and doc["refine"] == []
    assert doc["env_profile"] == "gpu-cu128" and doc["env_lock"] == "envs/gpu-cu128/constraints.txt"
    assert doc["models"] == [{"name": "m", "source": "s", "weights_sha256": "ab"}]
    assert set(doc) >= {"schema", "mode", "backend", "tracker", "lifter", "refine", "models", "env_profile",
                        "env_lock_sha256", "code_sha256", "frames_sha256", "created_utc", "host_gpu"}
    assert doc["host_gpu"] == "Test GPU" and doc["files_sha256"]["pose3d.json"] == stamp.sha256_file(out / "pose3d.json")


def test_changing_a_listed_file_stales_only_the_modes_that_list_it(tmp_path):
    root = make_root(tmp_path)
    gpu = stamped(root, "single")
    cpu = stamped(root, "cpu-single", backend="cpu", lifter="fixed-bones", profile="cpu")
    cls = stamped(root, "class", frames="class", tracker="api-sam31", modules=MULTI, files=("tracks.json", "pose3d.json"))
    touch(root / "part2" / "backends" / "cpu_rtm.py")
    assert stamp.check(gpu, root) is None and stamp.check(cls, root) is None
    problem = stamp.check(cpu, root)
    assert problem["stamp"] == "stale" and problem["changed_files"] == ["part2/backends/cpu_rtm.py"]
    assert problem["status"].startswith("fixtures/output/scored/cpu-single is stale: code changed since 20")
    assert problem["status"].endswith("; run make outputs")
    touch(root / "part2" / "trackers" / "api_sam31.py")
    assert stamp.check(gpu, root) is None and stamp.check(cls, root)["changed_files"] == ["part2/trackers/api_sam31.py"]
    touch(root / "part2" / "body3d.py")  # shared by both backends
    assert stamp.check(gpu, root)["changed_files"] == ["part2/body3d.py"]


def test_a_cpu_lock_change_never_stales_a_gpu_made_mode(tmp_path):
    root = make_root(tmp_path)
    gpu = stamped(root, "single")
    cpu = stamped(root, "cpu-single", backend="cpu", lifter="fixed-bones", profile="cpu")
    touch(root / "envs" / "cpu" / "requirements.txt")
    assert stamp.check(gpu, root) is None
    assert stamp.check(cpu, root)["status"].startswith("fixtures/output/scored/cpu-single is stale: env lock changed")
    touch(root / "k8s" / "constraints-gpu.txt")  # the team profile: neither mode used it
    assert stamp.check(gpu, root) is None


def test_validation_only_modules_stale_nothing(tmp_path):
    root = make_root(tmp_path)
    out = stamped(root, "single")
    for name in ("schema.py", "contract.py", "doctor.py", "provenance.py", "keys.py", "check.py", "outputs.py"):
        touch(root / "part2" / name)
    assert stamp.check(out, root) is None


def test_frames_and_code_changes_are_both_named(tmp_path):
    root = make_root(tmp_path)
    out = stamped(root, "single")
    (root / "fixtures" / "input" / "single" / "frames" / "000000.jpg").write_bytes(b"changed")
    assert "is stale: frames changed since" in stamp.check(out, root)["status"]
    touch(root / "part2" / "joints.py")
    assert "is stale: code and frames changed since" in stamp.check(out, root)["status"]


def test_a_deleted_code_file_is_a_change(tmp_path):
    root = make_root(tmp_path)
    out = stamped(root, "single")
    (root / "part2" / "body3d.py").unlink()
    assert stamp.check(out, root)["changed_files"] == ["part2/body3d.py"]


# ---- AC-K04 and the file digests -------------------------------------------------------------------------

def test_a_v1_stamp_reads_as_stale_with_the_v1_message(tmp_path):
    root = make_root(tmp_path)
    out = stamped(root, "single")
    (out / "stamp.json").write_text(json.dumps({"fingerprint": "abc"}))
    assert stamp.check(out, root) == {"status": "stamp v1 from HPC; run make outputs", "stamp": "v1"}
    (out / "stamp.json").write_text(json.dumps({"schema": "part2.stamp/9"}))
    assert stamp.check(out, root)["stamp"] == "v1"


def test_missing_stamp_or_output_file_is_missing_output(tmp_path):
    root = make_root(tmp_path)
    out = stamped(root, "single", files=("pose3d.json", "camera.json"))
    (out / "camera.json").unlink()
    assert stamp.check(out, root)["status"] == "missing output fixtures/output/scored/single/camera.json; run make outputs"
    (out / "stamp.json").unlink()
    assert stamp.check(out, root) == {"status": "missing output fixtures/output/scored/single/stamp.json; run make outputs",
                                      "stamp": "missing"}


def test_an_output_edited_by_hand_is_refused(tmp_path):
    root = make_root(tmp_path)
    out = stamped(root, "single")
    (out / "pose3d.json").write_text("{}")
    assert stamp.check(out, root) == {"status": "fixtures/output/scored/single/pose3d.json does not match its stamp "
                                                "(edited after make outputs); run make outputs", "stamp": "edited"}


def test_finish_refuses_to_stamp_a_file_that_was_not_written(tmp_path):
    root = make_root(tmp_path)
    pre = stamp.prepare(root, "single", "gpu", root / "fixtures/input/single/frames", profile="gpu-cu128")
    (tmp_path / "o").mkdir()
    with pytest.raises(FileNotFoundError, match="pose3d.json not written"):
        stamp.finish(pre, tmp_path / "o", ["pose3d.json"])
    assert not (tmp_path / "o" / "stamp.json").exists()


# ---- AC-K08: same tree, same hashes ---------------------------------------------------------------------

def test_prepare_twice_with_no_change_gives_identical_hashes(tmp_path):
    root = make_root(tmp_path)
    a, b = (stamp.prepare(root, "class", "gpu", root / "fixtures/input/class/frames", MULTI, tracker="local-open",
                          profile="gpu-cu128") for _ in range(2))
    for k in ("code_sha256", "frames_sha256", "env_lock_sha256", "code_files"):
        assert a[k] == b[k]


def test_frames_hash_of_a_missing_dir_is_stable_and_differs(tmp_path):
    assert stamp.frames_sha256(tmp_path / "none") == stamp.frames_sha256(tmp_path / "none2")
    assert stamp.frames_sha256(write_frames(tmp_path / "f")) != stamp.frames_sha256(tmp_path / "none")


# ---- code closure and registry entries ------------------------------------------------------------------

def test_closure_lists_the_backend_tracker_and_lifter_files_and_skips_validation_modules(tmp_path):
    root = make_root(tmp_path)
    files = stamp.code_closure(root, [*stamp.BASE_MODULES, *MULTI, *stamp.entry_modules("gpu", "local-open")])
    assert {"part2/frames.py", "part2/joints.py", "part2/canonical.py", "part2/body3d.py", "part2/multi3d.py",
            "part2/backends/gpu_sam3db.py", "part2/trackers/local_open.py", "part2/trackers/__init__.py"} <= set(files)
    assert "part2/backends/cpu_rtm.py" not in files and "part2/trackers/api_sam31.py" not in files
    assert not set(files) & stamp.NOT_OUTPUT_CODE
    cpu = stamp.code_closure(root, stamp.entry_modules("cpu", lifter="motionbert"))
    assert {"part2/lifters/__init__.py", "part2/lifters/motionbert.py", "part2/lifters/fixed_bones.py"} <= set(cpu)


def test_closure_follows_relative_function_level_and_attribute_imports(tmp_path):
    root = tmp_path
    (root / "part2" / "pkg").mkdir(parents=True)
    (root / "part2" / "__init__.py").write_text("")
    (root / "part2" / "pkg" / "__init__.py").write_text("from .a import thing\n")
    (root / "part2" / "pkg" / "a.py").write_text("from ..b import helper\nthing = 1\n")
    (root / "part2" / "b.py").write_text("def helper():\n    import part2.c\n    from part2 import d\n")
    (root / "part2" / "c.py").write_text("import numpy\n")
    (root / "part2" / "d.py").write_text("")
    (root / "part2" / "unused.py").write_text("")
    assert stamp.code_closure(root, ["part2.pkg"]) == ["part2/b.py", "part2/c.py", "part2/d.py",
                                                     "part2/pkg/__init__.py", "part2/pkg/a.py"]
    with pytest.raises(stamp.StampError, match="no module part2.nothere"):
        stamp.code_closure(root, ["part2.nothere"])


def test_every_registered_entry_resolves_to_a_file():
    names = [("backend", b) for b in backends.names()] + [("tracker", t) for t in trackers.names()] + \
            [("lifter", n) for n in lifters.names()]
    for kind, name in names:
        kw = {"backend": "gpu", kind: name}
        mods = stamp.entry_modules(**kw)
        assert stamp.code_closure(ROOT, mods), (kind, name)


def test_unknown_entries_raise():
    for kw in ({"backend": "tpu"}, {"backend": "gpu", "tracker": "nope"}, {"backend": "cpu", "lifter": "nope"}):
        with pytest.raises(stamp.StampError, match="unknown"):
            stamp.entry_modules(**kw)
    assert stamp.entry_modules("gpu", refine=["kp2d-fit"])[-1] == "part2.refine.kp2d_fit"


def test_closure_covers_every_part2_module_an_entry_imports():
    """ADR-0006 pre-mortem 1: the declared list is checked by importing each entry in a clean interpreter."""
    entries = [m for b in backends.names() for m in stamp.entry_modules(b)]
    entries += [stamp.entry_modules("gpu", tracker=t)[1] for t in trackers.names()]
    entries += [stamp.entry_modules("cpu", lifter=n)[1] for n in lifters.names()]
    for entry in sorted(set(entries)) + list(MULTI) + list(stamp.BASE_MODULES):
        code = (f"import sys, importlib; importlib.import_module({entry!r}); "
                "print('\\n'.join(sorted(m for m in sys.modules if m.split('.')[0] == 'part2')))")
        loaded = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
        files = {stamp.rel(stamp.module_path(ROOT, m), ROOT) for m in loaded if stamp.module_path(ROOT, m)}
        closure = set(stamp.code_closure(ROOT, [entry])) | stamp.NOT_OUTPUT_CODE
        assert files <= closure, (entry, files - closure)


# ---- env profile ----------------------------------------------------------------------------------------

def test_env_profile_follows_the_interpreter_then_the_backend():
    assert stamp.env_profile("cpu", prefix="/x/venvs/gpu-cu128", env={}) == "gpu-cu128"
    assert stamp.env_profile("cpu", prefix="/x/.venv", env={}) == "cpu"
    assert stamp.env_profile("gpu", prefix="/x/.venv", env={}) == "team-gpu"
    assert stamp.env_profile("gpu", prefix="/x", env={"PART2_ENV_PROFILE": "cpu"}) == "cpu"
    with pytest.raises(stamp.StampError, match='unknown env profile "conda"'):
        stamp.env_profile("gpu", env={"PART2_ENV_PROFILE": "conda"})


def test_describe_names_the_producer_and_the_state(tmp_path):
    root = make_root(tmp_path)
    out = stamped(root, "cpu-single", backend="cpu", lifter="motionbert", profile="cpu")
    d = stamp.describe(out, root)
    assert d["dir"] == "fixtures/output/scored/cpu-single" and d["backend"] == "cpu" and d["lifter"] == "motionbert"
    assert d["stamp"] == "fresh" and d["tracker"] is None and d["refine"] == [] and d["code_sha256"]
    (out / "stamp.json").write_text(json.dumps({"fingerprint": "x"}))
    d = stamp.describe(out, root, stamp.check(out, root))
    assert d["stamp"] == "v1" and d["backend"] is None and d["code_sha256"] is None
