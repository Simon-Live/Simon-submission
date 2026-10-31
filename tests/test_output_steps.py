"""part2.output_steps (docs/specs/check-2.md "Files" and AC-K15): the steps `part2 run`, `part2 stock` and
`make outputs` share. `part2 run` and `make outputs` reach them end to end in test_cli.py, test_outputs.py and
test_refine_outputs.py; these tests call each step directly, with fakes for the backend and the refine ladder."""
import contextlib
import json

from part2 import gpu_guard, output_steps, provenance, refine


class Backend:
    def __init__(self, name="gpu", **prov):
        self.name = name
        self._prov = {"backend": name, "detector": "fake", "models": [{"name": "m3d", "source": "t", "weights_sha256": None}],
                      **prov}

    def provenance(self):
        return dict(self._prov)


# ---- gpu_locked -----------------------------------------------------------------------------------------

def test_gpu_locked_holds_the_host_lock_for_the_gpu_backend_only(monkeypatch):
    held = []

    @contextlib.contextmanager
    def lock():
        held.append("in")
        yield
        held.append("out")

    monkeypatch.setattr(gpu_guard, "gpu_lock", lock)
    with output_steps.gpu_locked(Backend("cpu")):
        assert held == []
    with output_steps.gpu_locked(Backend("gpu")):
        assert held == ["in"]
    assert held == ["in", "out"]


# ---- pose_extras ----------------------------------------------------------------------------------------

def test_pose_extras_names_the_origin_the_mirror_flag_and_what_ran():
    extras = output_steps.pose_extras({"t0_pts_ms": 40.0}, True, Backend())
    prov = extras["provenance"]
    assert (extras["t0_pts_ms"], extras["mirrored"]) == (40.0, True)
    assert (prov["backend"], prov["tracker"], prov["refine"], prov["detector"]) == ("gpu", None, [], "fake")
    assert [m["name"] for m in prov["models"]] == ["m3d"] and prov["contract_version"]
    assert output_steps.pose_extras({}, False, Backend())["mirrored"] is None


def test_pose_extras_adds_the_tracker_its_models_and_a_fallback():
    tracks = {"tracker": "local-open", "models": [{"name": "sam", "source": "t", "weights_sha256": None}],
              "fallback_from": "api-sam31", "fallback_reason": "no key", "spend_usd": 1}
    prov = output_steps.pose_extras({}, False, Backend(), tracks)["provenance"]
    assert prov["tracker"] == "local-open" and [m["name"] for m in prov["models"]] == ["m3d", "sam"]
    assert (prov["fallback_from"], prov["fallback_reason"]) == ("api-sam31", "no key") and "spend_usd" not in prov


def test_pose_extras_names_the_refine_rungs_and_their_models():
    prov = output_steps.pose_extras({}, False, Backend(), refine=["kp2d-fit"])["provenance"]
    assert prov["refine"] == ["kp2d-fit"]
    assert [m["name"] for m in prov["models"]] == ["m3d", *[m["name"] for m in refine.models(["kp2d-fit"])]]
    assert prov["licence_notes"] == refine.licence_notes(["kp2d-fit"])


def _no_measure(*args):
    raise AssertionError("the commit was measured again")


def test_pose_extras_records_the_commit_it_is_given_over_the_backends_own(monkeypatch):
    """R14: a run that measured the tree once passes the value in; nothing measures the tree again, and the backend's
    own part2_commit (the cpu one) does not win."""
    monkeypatch.setattr(provenance, "_git", _no_measure)
    prov = output_steps.pose_extras({}, False, Backend(part2_commit="b" * 40), commit="c" * 40 + "+dirty")["provenance"]
    assert prov["part2_commit"] == "c" * 40 + "+dirty"


def test_pose_extras_without_a_commit_measures_it_as_part2_run_always_did(monkeypatch):
    monkeypatch.setattr(provenance, "_git", lambda *args: "d" * 40 if args[0] == "rev-parse" else "")
    assert output_steps.pose_extras({}, False, Backend())["provenance"]["part2_commit"] == "d" * 40
    assert output_steps.pose_extras({}, False, Backend(part2_commit="b" * 40))["provenance"]["part2_commit"] == "b" * 40


# ---- refine ---------------------------------------------------------------------------------------------

def test_refine_without_rungs_returns_the_doc_and_writes_nothing(tmp_path):
    doc = {"frames": []}
    assert output_steps.refine([], doc, tmp_path, tmp_path, Backend()) is doc
    assert list(tmp_path.iterdir()) == []


def test_refine_keeps_the_unrefined_doc_and_writes_the_refined_one_under_the_lock(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(refine, "apply", lambda names, doc, frames_dir, **kw: calls.append((names, kw)) or {"refined": 1})
    backend, locks = Backend("cpu"), []
    out = output_steps.refine(["kp2d-fit"], {"frames": []}, tmp_path / "f", tmp_path, backend, model2d="m2",
                              lock=lambda: locks.append(1))
    names, kw = calls[0]
    assert out == {"refined": 1} and names == ["kp2d-fit"]
    assert (kw["model2d"], kw["backend"], kw["work_dir"]) == ("m2", backend, tmp_path)
    assert kw["lock"]() is None and locks == [1]  # the given lock factory is the one the rungs use
    assert json.loads((tmp_path / "body3d-unrefined.json").read_text()) == {"frames": []}
    assert json.loads((tmp_path / "body3d.json").read_text()) == {"refined": 1}


def test_refine_defaults_to_the_host_gpu_lock(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(refine, "apply", lambda names, doc, frames_dir, **kw: seen.update(kw) or doc)
    monkeypatch.setattr(output_steps, "gpu_locked", lambda backend: ("locked", backend.name))
    output_steps.refine(["kp2d-fit"], {}, tmp_path, tmp_path, Backend("gpu"))
    assert seen["lock"]() == ("locked", "gpu")


# ---- tracks_extras and stamp_tracks ---------------------------------------------------------------------

def test_tracks_extras_keeps_the_trackers_block_and_adds_the_version_and_backend():
    doc = {"provenance": {"tracker": "local-open", "fallback_from": "api-sam31"}}
    extras = output_steps.tracks_extras({"t0_pts_ms": 5.0}, doc, "gpu")
    assert extras["t0_pts_ms"] == 5.0
    assert extras["provenance"] == {"tracker": "local-open", "fallback_from": "api-sam31", "backend": "gpu",
                                    "contract_version": extras["provenance"]["contract_version"]}
    assert extras["provenance"]["contract_version"]
    assert "backend" not in output_steps.tracks_extras({}, doc, None)["provenance"]  # `part2 track` names no backend
    assert output_steps.tracks_extras({}, {}, None)["provenance"].keys() == {"contract_version"}


def test_tracks_extras_records_the_run_commit_over_the_one_the_tracker_measured(monkeypatch):
    """N3: a run that measured the tree once passes the value in; the tracker's own (write-time) commit does not
    win, and nothing measures the tree again. Without it the tracker's commit stands (`part2 run`, `part2 track`)."""
    monkeypatch.setattr(provenance, "_git", _no_measure)
    doc = {"provenance": {"tracker": "local-open", "part2_commit": "b" * 40 + "+dirty"}}
    run = "c" * 40
    assert output_steps.tracks_extras({}, doc, "gpu", commit=run)["provenance"]["part2_commit"] == run
    assert output_steps.tracks_extras({}, doc, "gpu")["provenance"]["part2_commit"] == "b" * 40 + "+dirty"
    assert doc["provenance"]["part2_commit"] == "b" * 40 + "+dirty"  # the tracker's own block is not edited


def test_a_dirty_run_commit_passes_the_tracks_contract(tmp_path):
    path, doc = tmp_path / "tracks.json", {"frames": [{"frame": 0, "people": []}], "provenance": {"tracker": "t"}}
    extras = output_steps.tracks_extras({}, doc, "gpu", commit="c" * 40 + "+dirty")
    output_steps.stamp_tracks(path, doc, extras)
    assert json.loads(path.read_text())["provenance"]["part2_commit"] == "c" * 40 + "+dirty"


def test_stamp_tracks_adds_only_the_keys_that_have_a_value(tmp_path):
    path, doc = tmp_path / "tracks.json", {"frames": [{"frame": 0, "people": []}]}
    output_steps.stamp_tracks(path, doc, {"t0_pts_ms": None, "provenance": {"backend": "gpu"}})
    assert json.loads(path.read_text()) == {"frames": [{"frame": 0, "people": []}], "provenance": {"backend": "gpu"}}

