"""part2/image3d.py and its CLI block: a picture -> a textured, rigged GLB. Spec: docs/specs/image3d.md.
No GPU, torch or scipy: TRELLIS and SAM 3D Body are fakes."""
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from autorig_helpers import fake_fit_body
from image3d_helpers import FakeGenerator, fake_sam_parts, png_bytes, textured_glb

from part2 import autorig, autorig_glb, cli, gpu_guard, image3d, trackers
from part2.mhr_export import MHR_INDEX

CANONICAL = set(MHR_INDEX)


@pytest.fixture
def picture(tmp_path):
    p = tmp_path / "pic.png"
    p.write_bytes(png_bytes(32))
    return p


def run(tmp_path, picture, generator=None, parts=None, **kw):
    out = tmp_path / "out"
    code = image3d.command(out, picture, kw.pop("height_m", None), "auto", generator or FakeGenerator(), parts or fake_sam_parts(), **kw)
    return code, out


# ---- input (AC-1) -------------------------------------------------------------------------------------

def test_a_picture_is_checked_by_its_bytes(tmp_path, capsys):
    bad = tmp_path / "a.png"
    bad.write_bytes(b"GIF89a....")
    empty = tmp_path / "e.png"
    empty.write_bytes(b"")
    for path, words in ((bad, "not a JPEG, PNG or WebP"), (empty, "empty"), (tmp_path / "none.png", "not a file")):
        gen = FakeGenerator()
        assert image3d.command(tmp_path / "o", path, None, "auto", gen, fake_sam_parts()) == 2
        assert words in capsys.readouterr().err and gen.calls == []


def test_an_out_that_is_a_file_and_a_height_out_of_range_are_exit_2(tmp_path, picture, capsys):
    f = tmp_path / "f"
    f.write_text("x")
    assert image3d.command(f, picture, None, "auto", FakeGenerator(), fake_sam_parts()) == 2
    assert "not a directory" in capsys.readouterr().err
    assert image3d.command(tmp_path / "o", picture, 9.0, "auto", FakeGenerator(), fake_sam_parts()) == 2
    assert "--height" in capsys.readouterr().err


# ---- the result (AC-2 to AC-5) --------------------------------------------------------------------------

def test_writes_a_textured_rigged_glb_and_the_document(tmp_path, picture, capsys):
    code, out = run(tmp_path, picture)
    assert code == 0
    glb = (out / "model.glb").read_bytes()
    doc, read = autorig_glb.read(glb)
    names = {n["name"] for n in doc["nodes"]}
    assert CANONICAL <= names and len(doc["skins"][0]["joints"]) == 127
    assert doc["images"] and doc["textures"] and "COLOR_0" not in doc["meshes"][0]["primitives"][0]["attributes"]
    assert "TEXCOORD_0" in doc["meshes"][0]["primitives"][0]["attributes"]
    v = read(doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"])
    assert v[:, 1].min() == pytest.approx(0, abs=1e-5) and np.ptp(v[:, 1]) == pytest.approx(1.7, abs=1e-3)
    meta = json.loads((out / "avatar.json").read_text())
    assert meta["schema"] == "simon.avatar.v1" and meta["kind"] == "image3d" and meta["inputs"] == 1
    assert meta["backend"]["backend"] == "trellis" and meta["backend"]["weights_revision"] == "r"
    assert set(meta["mapped"]) == CANONICAL and meta["joints"] == 127 and meta["height_assumed"] is True
    assert "SAM License" in meta["licence"] and "MIT" in meta["licence"] and "TRELLIS" in meta["copyright"]
    t = meta["timings_s"]
    assert t["load_s"] == 1.0 and t["generate_s"] == 2.0 and t["rig_s"] >= 0 and t["total_s"] >= t["rig_s"]
    assert meta["peak_vram_gib"]["peak_vram_allocated_gib"] == 10.5 and meta["peak_vram_gib"]["device_used_peak_gib"] == 24.0
    assert meta["texture"] == {"mime": "image/png", "width": 8, "height": 8, "uv_set": 0}
    assert "TRELLIS" in doc["asset"]["copyright"]
    assert "texture 8x8" in capsys.readouterr().out
    assert not list(out.glob("*.part"))


def test_height_given_sets_the_size_and_is_not_assumed(tmp_path, picture):
    code, out = run(tmp_path, picture, height_m=1.9)
    meta = json.loads((out / "avatar.json").read_text())
    assert code == 0 and meta["height_assumed"] is False and meta["height_m"] == pytest.approx(1.9, abs=1e-3)


def test_stale_files_are_removed_when_a_run_fails(tmp_path, picture):
    out = tmp_path / "out"
    out.mkdir()
    (out / "model.glb").write_bytes(b"old")
    (out / "avatar.json").write_text("{}")
    code = image3d.command(out, picture, None, "auto", FakeGenerator(error=image3d.Image3dError(1, "boom")), fake_sam_parts())
    assert code == 1 and not (out / "model.glb").exists() and not (out / "avatar.json").exists()


# ---- turning and refusing (AC-8, AC-9) ----------------------------------------------------------------

class FailFirst:
    """A fit_body that finds no person in its first `n` calls, then fits."""

    def __init__(self, n):
        self.n, self.inner, self.calls = n, fake_fit_body(), 0

    def __call__(self, mesh):
        self.calls += 1
        if self.calls <= self.n:
            raise autorig.NoPersonInPicture("no person found in the picture of the mesh")
        return self.inner(mesh)


def parts_with(fit):
    skin_loader, _ = fake_sam_parts()
    return skin_loader, lambda: fit


def test_a_figure_that_does_not_fit_is_turned_a_quarter_and_tried_again(tmp_path, picture):
    fit = FailFirst(1)
    code, out = run(tmp_path, picture, parts=parts_with(fit))
    assert code == 0 and fit.calls == 2
    assert json.loads((out / "avatar.json").read_text())["turned_before_fit_deg"] == 90


def test_nothing_humanoid_is_exit_3_and_says_so(tmp_path, picture, capsys):
    fit = FailFirst(99)
    code, out = run(tmp_path, picture, parts=parts_with(fit))
    err = capsys.readouterr().err
    assert code == 3 and "nothing humanoid could be rigged" in err and "no person found" in err
    assert fit.calls == len(image3d.YAWS_DEG) and not (out / "model.glb").exists()


def test_a_generated_model_without_a_texture_is_a_failure_not_a_rig(tmp_path, picture, capsys):
    code, _ = run(tmp_path, picture, generator=FakeGenerator(glb=textured_glb(with_uv=False)[0]))
    assert code == 1 and "cannot be used" in capsys.readouterr().err


# ---- the GPU (AC-10, AC-11) -----------------------------------------------------------------------------

def test_too_little_free_gpu_memory_is_exit_4_and_names_the_release(tmp_path, picture, monkeypatch, capsys):
    monkeypatch.setattr(gpu_guard, "free_gib", lambda: 5.0)
    out = tmp_path / "out"
    code = image3d.command(out, picture)  # the real generator is chosen: the check runs before anything loads
    err = capsys.readouterr().err
    assert code == 4 and "5.0 GiB" in err and "warm workers" in err


def test_a_busy_gpu_lock_is_exit_4(tmp_path, picture, monkeypatch, capsys):
    def busy(wait_s):
        raise trackers.GpuBusy()

    monkeypatch.setattr(gpu_guard, "gpu_lock", busy)
    code, _ = run(tmp_path, picture)
    assert code == 4 and "another GPU job" in capsys.readouterr().err


def test_a_generator_that_runs_out_of_memory_is_exit_4(tmp_path, picture):
    code, _ = run(tmp_path, picture, generator=FakeGenerator(error=image3d.Image3dError(4, "out of memory")))
    assert code == 4


def test_the_gpu_lock_is_held_while_the_generator_runs(tmp_path, picture):
    seen = []

    class Gen(FakeGenerator):
        def generate(self, image, workdir):
            seen.append(gpu_guard.try_lock() is None)  # None: the lock is held by this very process
            return super().generate(image, workdir)

    code, _ = run(tmp_path, picture, generator=Gen())
    assert code == 0 and seen == [True]


# ---- the TRELLIS child process (AC-12) -----------------------------------------------------------------

class Done:
    def __init__(self, returncode=0, stderr="", stdout=""):
        self.returncode, self.stderr, self.stdout = returncode, stderr, stdout


def test_trellis_generator_reads_the_childs_files_and_adds_the_device_peak(tmp_path, picture, monkeypatch):
    py = tmp_path / "py"
    py.write_text("")
    monkeypatch.setenv(image3d.PYTHON_ENV, str(py))
    glb = textured_glb()[0]

    def fake_run(cmd, **kw):
        assert cmd[0] == str(py) and cmd[1] == "-I" and cmd[2].endswith("image3d_worker.py")
        (tmp_path / "generated.glb").write_bytes(glb)
        (tmp_path / "generated.json").write_text(json.dumps({"backend": "trellis", "timings_s": {"load_s": 1}}))
        return Done()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(gpu_guard, "query", lambda: {"free_gib": 8.0, "total_gib": 32.0})
    gen = image3d.ObjectGenerator("trellis").generate(picture, tmp_path)
    assert gen.glb == glb and gen.report["backend"] == "trellis"
    assert gen.report["device_used_before_gib"] == 24.0 and gen.report["device_used_peak_gib"] == 24.0


def test_trellis_generator_failures_map_to_exit_codes(tmp_path, picture, monkeypatch):
    py = tmp_path / "py"
    py.write_text("")
    monkeypatch.setenv(image3d.PYTHON_ENV, str(py))
    monkeypatch.setattr(gpu_guard, "query", lambda: None)
    for stderr, code in (("Traceback\ntorch.OutOfMemoryError: CUDA out of memory", 4), ("Traceback\nValueError: x", 1)):
        monkeypatch.setattr(subprocess, "run", lambda cmd, _e=stderr, **kw: Done(1, _e))
        with pytest.raises(image3d.Image3dError) as e:
            image3d.ObjectGenerator("trellis").generate(picture, tmp_path)
        assert e.value.code == code and "TRELLIS failed" in str(e.value)


def test_trellis_generator_without_its_environment_says_how_to_install(tmp_path, picture, monkeypatch):
    monkeypatch.setenv(image3d.PYTHON_ENV, str(tmp_path / "missing"))
    with pytest.raises(image3d.Image3dError, match="setup.sh") as e:
        image3d.ObjectGenerator("trellis").generate(picture, tmp_path)
    assert e.value.code == 1


def test_vram_sampler_keeps_the_highest_reading(monkeypatch):
    readings = iter([{"free_gib": 20.0, "total_gib": 32.0}, {"free_gib": 4.0, "total_gib": 32.0}, {"free_gib": 10.0, "total_gib": 32.0}])
    monkeypatch.setattr(gpu_guard, "query", lambda: next(readings, {"free_gib": 10.0, "total_gib": 32.0}))
    with image3d.VramSampler(period_s=0.001) as s:
        while s.peak_gib is None or s.peak_gib < 28:
            pass
    assert s.start_gib == 12.0 and s.peak_gib == 28.0


# ---- the CLI (AC-13) -----------------------------------------------------------------------------------

def test_cli_passes_the_arguments_through(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(image3d, "command", lambda *a: seen.append(a) or 0)
    assert cli.main(["image3d", "--out", str(tmp_path), "p.png", "--height", "1.8"]) == 0
    assert cli.main(["image3d", "--out", str(tmp_path), "p.png", "--backend", "trellis"]) == 0
    assert seen == [(tmp_path, Path("p.png"), 1.8, "auto"), (tmp_path, Path("p.png"), None, "trellis")]


def test_cli_requires_out_and_an_image(capsys):
    for argv in (["image3d", "p.png"], ["image3d", "--out", "x"]):
        with pytest.raises(SystemExit) as e:
            cli.main(argv)
        assert e.value.code == 2
    capsys.readouterr()


# ---- which model made the mesh (AC-15) -----------------------------------------------------------------

def _run_child(monkeypatch, tmp_path, outcomes):
    """Patch the child process: outcomes maps a backend to None (works) or the stderr of a failure; returns the calls."""
    py = tmp_path / "py"
    py.write_text("")
    monkeypatch.setenv(image3d.PYTHON_ENV, str(py))
    monkeypatch.setattr(gpu_guard, "query", lambda: None)
    glb, calls = textured_glb()[0], []

    def fake_run(cmd, **kw):
        backend = cmd[cmd.index("--backend") + 1]
        calls.append(backend)
        if outcomes[backend] is not None:
            return Done(1, outcomes[backend])
        (tmp_path / "generated.glb").write_bytes(glb)
        (tmp_path / "generated.json").write_text(json.dumps({"backend": backend, "timings_s": {}}))
        return Done()

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_auto_runs_sam_3d_objects_and_stops_there_when_it_works(tmp_path, picture, monkeypatch):
    calls = _run_child(monkeypatch, tmp_path, {"sam3do": None, "trellis": None})
    gen = image3d.make_generator("auto").generate(picture, tmp_path)
    assert calls == ["sam3do"] and gen.report["backend"] == "sam3do" and "fallback_from" not in gen.report


def test_auto_falls_back_to_trellis_and_says_why_sam_3d_objects_did_not_run(tmp_path, picture, monkeypatch):
    calls = _run_child(monkeypatch, tmp_path, {"sam3do": "GatedRepoError: 401", "trellis": None})
    gen = image3d.make_generator("auto").generate(picture, tmp_path)
    assert calls == ["sam3do", "trellis"] and gen.report["backend"] == "trellis"
    assert "GatedRepoError" in gen.report["fallback_from"]["reason"] and gen.report["fallback_from"]["backend"] == "sam3do"


def test_auto_does_not_fall_back_when_the_gpu_is_full(tmp_path, picture, monkeypatch):
    calls = _run_child(monkeypatch, tmp_path, {"sam3do": "torch.OutOfMemoryError: CUDA out of memory", "trellis": None})
    with pytest.raises(image3d.Image3dError) as e:
        image3d.make_generator("auto").generate(picture, tmp_path)
    assert calls == ["sam3do"] and e.value.code == 4


def test_a_named_backend_never_falls_back(tmp_path, picture, monkeypatch):
    calls = _run_child(monkeypatch, tmp_path, {"sam3do": "boom", "trellis": None})
    with pytest.raises(image3d.Image3dError):
        image3d.make_generator("sam3do").generate(picture, tmp_path)
    assert calls == ["sam3do"]


def test_the_notice_and_licence_name_the_backend_that_ran(tmp_path, picture):
    class Sam(FakeGenerator):
        def generate(self, image, workdir):
            gen = super().generate(image, workdir)
            gen.report["backend"] = "sam3do"
            return gen

    code, out = run(tmp_path, picture, generator=Sam())
    meta = json.loads((out / "avatar.json").read_text())
    assert code == 0 and "SAM 3D Objects" in meta["copyright"] and "TRELLIS" not in meta["copyright"]
    assert meta["licence"] == "SAM License; MHR Apache-2.0 notice"
    doc, _ = autorig_glb.read((out / "model.glb").read_bytes())
    assert "SAM 3D Objects" in doc["asset"]["copyright"]


def test_an_unknown_backend_is_exit_2(tmp_path, picture, capsys):
    assert image3d.command(tmp_path / "o", picture, None, "bogus", FakeGenerator(), fake_sam_parts()) == 2
    assert "--backend" in capsys.readouterr().err


def test_a_refusal_for_the_facing_names_every_fit_tried(tmp_path, picture, capsys):
    from autorig_helpers import fake_fit_body

    fit = fake_fit_body(hip_sign=(-1, 1))  # the hips always read the wrong way round
    code, _ = run(tmp_path, picture, parts=parts_with(fit))
    err = capsys.readouterr().err
    assert code == 3 and "cannot tell which way the figure faces" in err and "fits tried" in err
    assert err.count("'faces_forward': False") == 2 * len(image3d.YAWS_DEG) and "fit_error_share" in err
