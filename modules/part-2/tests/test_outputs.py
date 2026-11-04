"""`make outputs` driver (docs/specs/check-2.md "Scored outputs and stamps", AC-K08, the backend-gpu error row).

The 3D backend and the tracker are fakes; everything after them (canonical frame, contract checks, multi3d
streams, the stamp) is the real code, run in a temp root that holds a copy of part2/."""
import dataclasses
import fcntl
import json
import types

import pytest
from test_canonical import _body3d
from test_stamp import make_root

from part2 import backends, contract, frames, gpu_guard, outputs, provenance, stamp, trackers


def _fake_estimate(frames_dir, out_path, boxes=None):
    recs = frames.load(frames_dir)
    doc = _body3d([0] * len(recs))
    for f, r in zip(doc["frames"], recs):
        f["frame"], f["t_ms"] = r["frame"], r["t_ms"]
        template = f["people"][0]
        f["people"] = [{**template, "id": pid} for pid in ([0] if boxes is None else list(boxes.get(r["frame"], {})))]
    out_path.write_text(json.dumps(doc))
    return doc


class FakeBackend:
    def __init__(self, name="gpu", fail=False, lock=None):
        self.name, self.fail, self.lock, self.lifter, self.locked = name, fail, lock, None, []

    def available(self, lifter=None):
        return True, ""

    def provenance(self):
        return {"backend": self.name, "models": [{"name": "fake-3d", "source": "test", "weights_sha256": "0" * 64}]}

    def estimate(self, frames_dir, out_path, boxes=None):
        if self.lock:
            with open(self.lock, "a") as f:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(f, fcntl.LOCK_UN)
                    self.locked.append(False)
                except BlockingIOError:
                    self.locked.append(True)
        if self.fail:
            raise RuntimeError("the GPU ran out of memory; free memory or use --backend cpu")
        return _fake_estimate(frames_dir, out_path, boxes)


class FakeTracker(trackers.Tracker):
    mask_source = "fake"

    def __init__(self, name="api-sam31"):
        self.name = name

    def detect(self, frames_dir, recs):
        return {r["frame"]: [{"id": i, "bbox": [0, 0, 2, 2], "mask": [[0, 1], [1, 1]], "confidence": 0.9}
                             for i in (4, 5)] for r in recs}

    def models(self):
        return [{"name": f"{self.name}-model", "source": "test", "weights_sha256": None}]


COCO_IDS = (785, 22705)


def _fake_coco(root, monkeypatch):
    """Two COCO photos staged from fake bytes (no download): the manifest and stage_photo are replaced."""
    from part2 import coco_set
    from part2.schema import write_json

    manifest = root / "fixtures" / "input" / "coco" / "images" / "images.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"images": [{"image_id": i} for i in COCO_IDS]}))
    monkeypatch.setattr(coco_set, "load_manifest", lambda path=None: json.loads(manifest.read_text()))

    def stage(record, dest, root=None, fetch=None):
        out = dest / str(record["image_id"])
        out.mkdir(parents=True, exist_ok=True)
        (out / "photo.jpg").write_bytes(b"\xff\xd8photo")
        write_json(out / "frames.json", {"source": "test", "frames": [{"frame": record["image_id"], "t_ms": 0.0,
                                                                      "file": "photo.jpg"}]})
        return out

    monkeypatch.setattr(coco_set, "stage_photo", stage)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A temp root, the GPU lock in tmp, fake trackers by name, and no real GPU name lookup."""
    root = make_root(tmp_path)
    lock = tmp_path / "gpu.lock"
    monkeypatch.setenv("PART2_GPU_LOCK", str(lock))
    monkeypatch.delenv("PART2_SCORED_DIR", raising=False)
    monkeypatch.setattr(outputs, "host_gpu", lambda name: "Fake GPU" if name == "gpu" else None)
    calls = []
    monkeypatch.setattr(trackers, "resolve", lambda purpose, n_frames=None: calls.append(("resolve", purpose)) or
                        (FakeTracker("api-sam31"), []))
    monkeypatch.setattr(trackers, "select", lambda flag, purpose="bulk", n_frames=None: calls.append(("select", flag)) or
                        (FakeTracker(flag), []))
    _fake_coco(root, monkeypatch)
    # Mode defaults off: these tests run the one-person modes without the chosen rungs unless a test sets them.
    monkeypatch.setattr(outputs, "MODES", [dataclasses.replace(m, refine=()) for m in outputs.MODES])
    return types.SimpleNamespace(root=root, lock=lock, calls=calls, scored=root / "fixtures" / "output" / "scored")


def _use(monkeypatch, backend):
    monkeypatch.setattr(backends, "get", lambda name: backend)
    return backend


def test_modes_by_backend_and_subset():
    assert [m.name for m in outputs.modes_for("gpu")] == ["single", "class", "class-local-open", "coco-single"]
    assert [m.name for m in outputs.modes_for("cpu")] == ["cpu-single"]
    assert [m.name for m in outputs.modes_for("gpu", ["class", "single"])] == ["class", "single"]
    with pytest.raises(ValueError, match='backend cpu does not make mode "single"; choose cpu-single'):
        outputs.modes_for("cpu", ["single"])


def test_scored_dir_flag_env_default(tmp_path, monkeypatch):
    monkeypatch.delenv("PART2_SCORED_DIR", raising=False)
    assert outputs.scored_dir(tmp_path) == tmp_path / "fixtures" / "output" / "scored"
    monkeypatch.setenv("PART2_SCORED_DIR", "out")
    assert outputs.scored_dir(tmp_path) == tmp_path / "out"
    assert outputs.scored_dir(tmp_path, "/abs/x") == outputs.Path("/abs/x")
    from part2 import check

    assert outputs.scored_dir is check.scored_dir  # make outputs writes where make check-2 reads


def test_gpu_run_writes_every_mode_with_a_fresh_stamp(env, monkeypatch, capsys):
    backend = _use(monkeypatch, FakeBackend(lock=env.lock))
    (env.scored / "class").mkdir(parents=True)
    (env.scored / "class" / "pose3d_person_9.json").write_text("{}")  # left from an older run
    assert outputs.main([], root=env.root) == 0
    summary = json.loads(capsys.readouterr().out)
    assert list(summary) == ["single", "class", "class-local-open", "coco-single"]
    assert sorted(p.name for p in (env.scored / "coco-single").iterdir()) == ["22705", "785", "stamp.json"]
    assert sorted(p.name for p in (env.scored / "coco-single" / "785").iterdir()) == ["camera.json", "pose3d.json"]
    assert summary["coco-single"]["frames"] == 2 and summary["coco-single"]["tracker"] is None
    assert summary["class"]["tracker"] == "api-sam31" and summary["class-local-open"]["tracker"] == "local-open"
    assert summary["single"] | {"seconds": 0} == {"dir": "fixtures/output/scored/single", "backend": "gpu", "tracker": None,
                                                  "lifter": None, "frames": 2, "people": 1, "seconds": 0,
                                                  "params": {"smooth": False, "mirrored": False}}
    assert summary["class"]["people"] == 2
    assert sorted(p.name for p in (env.scored / "single").iterdir()) == ["camera.json", "pose3d.json", "stamp.json"]
    assert sorted(p.name for p in (env.scored / "class").iterdir()) == ["camera.json", "pose3d.json", "stamp.json",
                                                                       "tracks.json"]
    for mode in summary:
        assert stamp.check(env.scored / mode, env.root) is None
    doc = stamp.load(env.scored / "class")
    assert doc["host_gpu"] == "Fake GPU" and doc["tracker"] == "api-sam31" and doc["mode"] == "class"
    assert [m["name"] for m in doc["models"]] == ["fake-3d", "api-sam31-model"]
    assert "part2/trackers/__init__.py" in doc["code_files"] and doc["run"]["params"] == outputs.PARAMS
    tracks = json.loads((env.scored / "class" / "tracks.json").read_text())
    assert tracks["provenance"]["backend"] == "gpu" and tracks["provenance"]["tracker"] == "api-sam31"
    assert backend.locked == [True] * 5  # single, class, class-local-open, two COCO photos  # every GPU inference ran under the host lock
    assert ("resolve", "scored") in env.calls and ("select", "local-open") in env.calls


def test_a_named_tracker_replaces_the_scored_order_for_class_only(env, monkeypatch, capsys):
    _use(monkeypatch, FakeBackend())
    assert outputs.main(["--tracker", "bytetrack", "--modes", "class,class-local-open"], root=env.root) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["class"]["tracker"] == "bytetrack" and summary["class-local-open"]["tracker"] == "local-open"
    assert ("resolve", "scored") not in env.calls


def test_cpu_backend_writes_cpu_single_with_its_lifter_and_no_lock(env, monkeypatch, capsys):
    backend = _use(monkeypatch, FakeBackend(name="cpu", lock=env.lock))
    assert outputs.main(["--backend", "cpu", "--lifter", "motionbert"], root=env.root) == 0
    summary = json.loads(capsys.readouterr().out)
    assert list(summary) == ["cpu-single"] and summary["cpu-single"]["lifter"] == "motionbert"
    doc = stamp.load(env.scored / "cpu-single")
    assert doc["lifter"] == "motionbert" and doc["host_gpu"] is None and "part2/lifters/motionbert.py" in doc["code_files"]
    assert backend.lifter == "motionbert" and backend.locked == [False]


def test_scored_flag_writes_elsewhere(env, monkeypatch, capsys):
    _use(monkeypatch, FakeBackend())
    assert outputs.main(["--modes", "single", "--scored", "out"], root=env.root) == 0
    assert stamp.check(env.root / "out" / "single", env.root) is None and not env.scored.exists()


def test_a_failing_mode_keeps_its_old_outputs_and_the_others_still_run(env, monkeypatch, capsys):
    backend = _use(monkeypatch, FakeBackend())
    assert outputs.main(["--modes", "single"], root=env.root) == 0
    before = (env.scored / "single" / "stamp.json").read_text()
    backend.fail = True
    assert outputs.main(["--modes", "single,class"], root=env.root) == 1
    captured = capsys.readouterr()
    summary = json.loads(captured.out.split("\n}\n", 1)[1])
    assert summary["single"]["error"].startswith("RuntimeError: the GPU ran out of memory")
    assert "outputs: single: the GPU ran out of memory" in captured.err
    assert (env.scored / "single" / "stamp.json").read_text() == before


def test_gpu_without_cuda_is_a_plain_refusal(env, monkeypatch, capsys):
    class NoCuda(FakeBackend):
        def available(self, lifter=None):
            return False, "torch sees no CUDA device"

    _use(monkeypatch, NoCuda())
    assert outputs.main([], root=env.root) == 1
    err = capsys.readouterr().err
    assert err.startswith("outputs: backend gpu needs CUDA (make setup-gpu)\n") and "torch sees no CUDA device" in err
    assert not env.scored.exists()


def test_cpu_without_extras_is_a_plain_refusal(env, monkeypatch, capsys):
    class NoExtras(FakeBackend):
        def available(self, lifter=None):
            return False, "missing rtmlib"

    _use(monkeypatch, NoExtras(name="cpu"))
    assert outputs.main(["--backend", "cpu"], root=env.root) == 1
    assert capsys.readouterr().err.startswith("outputs: the cpu backend needs make setup-cpu (missing rtmlib)")


@pytest.mark.parametrize("argv,needle", [
    (["--backend", "tpu"], 'unknown backend "tpu"'),
    (["--backend", "cpu", "--lifter", "nope"], 'unknown lifter "nope"'),
    (["--tracker", "nope"], 'unknown tracker "nope"'),
    (["--modes", "cpu-single"], 'backend gpu does not make mode "cpu-single"'),
])
def test_unknown_names_exit_2(env, argv, needle, capsys):
    assert outputs.main(argv, root=env.root) == 2
    assert needle in capsys.readouterr().err


def test_a_busy_gpu_fails_the_mode_with_the_lock_message(env, monkeypatch, capsys):
    """Every mode takes the host lock through output_steps.gpu_locked (B2: one copy of that rule)."""
    _use(monkeypatch, FakeBackend())
    monkeypatch.setattr(gpu_guard, "gpu_lock", lambda wait_s=None: trackers.gpu_lock(wait_s=0.1, poll_s=0.02))
    with trackers.gpu_lock():
        assert outputs.main(["--modes", "single"], root=env.root) == 1
    assert "outputs: single: another GPU job is running" in capsys.readouterr().err


def test_the_stamp_hashes_are_taken_before_inference(env, monkeypatch, capsys):
    """An edit made while the model runs leaves the outputs stale, never falsely fresh."""
    backend = _use(monkeypatch, FakeBackend())
    real = backend.estimate

    def edit_then_estimate(frames_dir, out_path, boxes=None):
        (env.root / "part2" / "body3d.py").write_text("# edited during the run\n")
        return real(frames_dir, out_path, boxes)

    backend.estimate = edit_then_estimate
    assert outputs.main(["--modes", "single"], root=env.root) == 0
    assert stamp.check(env.scored / "single", env.root)["changed_files"] == ["part2/body3d.py"]


# ---- R14: the commit is measured once, before the run writes anything ----------------------------------------------------

SHA = "a" * 40
GPU_FILES = ("single/pose3d.json", "class/pose3d.json", "class-local-open/pose3d.json", "coco-single/785/pose3d.json",
             "coco-single/22705/pose3d.json")


def _tree(env, monkeypatch, dirty_before=False):
    """A stand-in for provenance's git call: HEAD is SHA; the tree reads dirty from the start (dirty_before) or
    once the run has written a scored file, as the tracked fixtures/output tree does on a real checkout."""
    def fake(*args):
        if args[0] == "rev-parse":
            return SHA
        return " M fixtures/output/scored/single/pose3d.json" if dirty_before or any(env.scored.rglob("*.json")) else ""

    monkeypatch.setattr(provenance, "_git", fake)


def _commits(env, files):
    return {f: json.loads((env.scored / f).read_text())["provenance"]["part2_commit"] for f in files}


def test_every_mode_records_the_commit_measured_before_the_run_wrote_anything(env, monkeypatch):
    _use(monkeypatch, FakeBackend())
    _tree(env, monkeypatch)
    assert outputs.main([], root=env.root) == 0
    assert provenance.part2_commit() == SHA + "+dirty"  # the control: the run's own files now make the tree read dirty
    assert _commits(env, GPU_FILES) == {f: SHA for f in GPU_FILES}


def test_a_tree_dirty_before_the_run_is_recorded_as_dirty_in_every_mode(env, monkeypatch):
    _use(monkeypatch, FakeBackend())
    _tree(env, monkeypatch, dirty_before=True)
    assert outputs.main([], root=env.root) == 0
    assert _commits(env, GPU_FILES) == {f: SHA + "+dirty" for f in GPU_FILES}


TRACKS_FILES = ("class/tracks.json", "class-local-open/tracks.json")


def test_tracks_json_records_the_same_clean_commit_as_pose3d_json(env, monkeypatch):
    """N3: the tracker measures at write time, when the run's earlier modes already made the tree read dirty; the
    run's one measure replaces that, so a clean run says the same clean commit in tracks.json and pose3d.json."""
    _use(monkeypatch, FakeBackend())
    _tree(env, monkeypatch)
    assert outputs.main(["--modes", "single,class,class-local-open"], root=env.root) == 0
    both = [f"{m}/{k}.json" for m in ("class", "class-local-open") for k in ("tracks", "pose3d")]
    assert _commits(env, both) == {f: SHA for f in both}


def test_tracks_json_records_the_same_dirty_commit_as_pose3d_json(env, monkeypatch):
    """A tree dirty before the run reads +dirty in tracks.json too, and the tracks contract accepts that value."""
    _use(monkeypatch, FakeBackend())
    _tree(env, monkeypatch, dirty_before=True)
    assert outputs.main(["--modes", "class,class-local-open"], root=env.root) == 0
    both = [f"{m}/{k}.json" for m in ("class", "class-local-open") for k in ("tracks", "pose3d")]
    assert _commits(env, both) == {f: SHA + "+dirty" for f in both}
    for f in TRACKS_FILES:
        contract.validate(json.loads((env.scored / f).read_text()), "tracks")


def test_a_direct_class_run_mode_records_one_commit_in_tracks_and_pose3d(env, monkeypatch):
    backend = _use(monkeypatch, FakeBackend())
    _tree(env, monkeypatch)
    outputs.run_mode(outputs.modes_for("gpu", ["class"])[0], backend, env.root, env.scored)
    assert _commits(env, ("class/tracks.json", "class/pose3d.json")) == {"class/tracks.json": SHA,
                                                                          "class/pose3d.json": SHA}


def test_the_run_commit_replaces_the_backends_own_commit(env, monkeypatch):
    """The cpu backend names its own part2_commit (HEAD, never +dirty); under `make outputs` the run's one measure wins."""
    class CpuWithCommit(FakeBackend):
        def provenance(self):
            return {**super().provenance(), "part2_commit": "b" * 40}

    _use(monkeypatch, CpuWithCommit(name="cpu"))
    _tree(env, monkeypatch, dirty_before=True)
    assert outputs.main(["--backend", "cpu"], root=env.root) == 0
    assert _commits(env, ("cpu-single/pose3d.json",)) == {"cpu-single/pose3d.json": SHA + "+dirty"}


def test_a_direct_run_mode_measures_the_commit_before_it_writes(env, monkeypatch):
    backend = _use(monkeypatch, FakeBackend())
    _tree(env, monkeypatch)
    mode = outputs.modes_for("gpu", ["single"])[0]
    outputs.run_mode(mode, backend, env.root, env.scored)
    assert _commits(env, ("single/pose3d.json",)) == {"single/pose3d.json": SHA}
