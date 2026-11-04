"""`part2 avatar` (part2.avatar), docs/specs/avatar.md AC-1 to AC-4, AC-10 to AC-16, AC-NFR-2 and AC-NFR-3; no GPU."""
import fcntl
import json
import os
import subprocess
import sys

import numpy as np
import pytest
from avatar_rig import body

from part2 import avatar, cli, gpu_guard
from part2 import mhr_export as mx
from part2.backends import BackendUnavailable

JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 20
WEBP = b"RIFF\0\0\0\0WEBPVP8 " + b"\0" * 20


def photo(tmp_path, name="a.jpg", data=JPEG):
    p = tmp_path / name
    p.write_bytes(data)
    return p


class FakeFitter:
    def __init__(self, params=None, error=None):
        self.params = params or [{"shape": np.ones(45), "scale": np.ones(28)}]
        self.error, self.seen = error, None

    def shapes(self, paths):
        self.seen = list(paths)
        if self.error:
            raise self.error
        return self.params[: len(paths)] if len(self.params) >= len(paths) else self.params * len(paths)

    def rest(self, shape, scale):
        self.rest_args = (shape, scale)
        return body()


def run(tmp_path, images, fitter=None, out=None):
    return avatar.command(out or tmp_path / "out", images, fitter or FakeFitter())


# ---- input ----
def test_ac1_photo_count(tmp_path, capsys):
    p = photo(tmp_path)
    assert run(tmp_path, [p]) == 0
    assert run(tmp_path, [p] * 4, out=tmp_path / "o4") == 0
    assert run(tmp_path, [p] * 5, out=tmp_path / "o5") == 2
    assert "1 to 4 photos, got 5" in capsys.readouterr().err
    assert not (tmp_path / "o5").exists()
    assert run(tmp_path, [], out=tmp_path / "o0") == 2


@pytest.mark.parametrize("name,data,reason", [
    ("e.jpg", b"", "empty"), ("t.jpg", b"GIF89a" + b"\0" * 20, "not a JPEG, PNG or WebP"),
    ("p.png", b"%PDF-1.4" + b"\0" * 20, "not a JPEG, PNG or WebP")])
def test_ac2_bad_files(tmp_path, capsys, name, data, reason):
    assert run(tmp_path, [photo(tmp_path, name, data)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("part2: ") and name in err and reason in err and err.count("\n") == 1
    assert not (tmp_path / "out").exists()


def test_ac2_missing_directory_and_size(tmp_path, capsys, monkeypatch):
    assert run(tmp_path, [tmp_path / "nope.jpg"]) == 2 and "not a file" in capsys.readouterr().err
    assert run(tmp_path, [tmp_path]) == 2 and "not a file" in capsys.readouterr().err
    monkeypatch.setattr(avatar, "MAX_IMAGE_BYTES", 10)
    assert run(tmp_path, [photo(tmp_path)]) == 2 and "over 0 MB" in capsys.readouterr().err


def test_ac2_type_is_read_from_bytes_not_extension(tmp_path):
    assert run(tmp_path, [photo(tmp_path, "x.txt", PNG), photo(tmp_path, "y.dat", WEBP), photo(tmp_path, "z.png", JPEG)]) == 0


def test_ac2_symlink_to_image_is_read_through(tmp_path):
    real = photo(tmp_path)
    link = tmp_path / "link.jpg"
    link.symlink_to(real)
    assert run(tmp_path, [link]) == 0 and real.read_bytes() == JPEG


def test_ac3_out_is_a_file(tmp_path, capsys):
    f = tmp_path / "file"
    f.write_text("x")
    assert run(tmp_path, [photo(tmp_path)], out=f) == 2 and "not a directory" in capsys.readouterr().err
    assert f.read_text() == "x"


def test_ac3_missing_out_is_argparse_exit_2(tmp_path):
    with pytest.raises(SystemExit) as e:
        cli.main(["avatar", str(photo(tmp_path))])
    assert e.value.code == 2


def test_cli_dispatch(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(avatar, "command", lambda out, imgs: seen.update(out=out, imgs=imgs) or 0)
    p = photo(tmp_path)
    assert cli.main(["avatar", "--out", str(tmp_path / "o"), str(p), str(p)]) == 0
    assert seen["out"] == tmp_path / "o" and seen["imgs"] == [p, p]


# ---- result ----
def test_ac10_avatar_json_and_files(tmp_path):
    p = photo(tmp_path)
    assert run(tmp_path, [p, p]) == 0
    out = tmp_path / "out"
    assert sorted(x.name for x in out.iterdir()) == ["avatar.json", "model.glb"]
    doc = json.loads((out / "avatar.json").read_text())
    glb, _ = mx.read_glb((out / "model.glb").read_bytes())
    assert doc["schema"] == "simon.avatar.v1" and doc["kind"] == "image" and doc["inputs"] == 2
    assert doc["joints"] == 127 and doc["licence"] == "SAM License; MHR Apache-2.0 notice" and doc["skinning"] == "linear"
    assert doc["height_m"] == round(doc["height_m"], 3) and 1.0 < doc["height_m"] < 2.0
    assert len(doc["mapped"]) == 22 and all(glb["nodes"][i]["name"] == b for b, i in doc["mapped"].items())
    assert doc["part2_commit"] and glb["asset"]["extras"]["licence"] == doc["licence"]


def test_ac11_combine_is_the_median_and_order_free():
    a = {"shape": np.array([1.0, 0]), "scale": np.array([0.0])}
    b = {"shape": np.array([3.0, 0]), "scale": np.array([2.0])}
    c = {"shape": np.array([9.0, 3]), "scale": np.array([4.0])}
    assert list(avatar.combine([a, b, c])["shape"]) == [3.0, 0] and list(avatar.combine([c, a, b])["shape"]) == [3.0, 0]
    assert list(avatar.combine([a])["shape"]) == [1.0, 0]
    assert list(avatar.combine([a, b])["scale"]) == [1.0]


def test_ac4_ac11_command_passes_the_median(tmp_path):
    ps = [{"shape": np.array([float(k)] * 45), "scale": np.array([float(k)] * 28)} for k in (1, 5, 2)]
    f = FakeFitter(ps)
    p = photo(tmp_path)
    assert run(tmp_path, [p, p, p], f) == 0
    assert f.rest_args[0][0] == 2.0 and f.rest_args[1][0] == 2.0


def test_ac12_same_input_same_bytes(tmp_path):
    p = photo(tmp_path)
    run(tmp_path, [p], out=tmp_path / "a")
    run(tmp_path, [p], out=tmp_path / "b")
    for n in ("model.glb", "avatar.json"):
        assert (tmp_path / "a" / n).read_bytes() == (tmp_path / "b" / n).read_bytes()


def test_ac13_stale_outputs_are_removed_on_failure(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "model.glb").write_bytes(b"old")
    (out / "avatar.json").write_text("old")
    assert run(tmp_path, [photo(tmp_path)], FakeFitter(error=avatar.AvatarError(3, "no person found in a.jpg"))) == 3
    assert list(out.iterdir()) == []


def test_ac_nfr3_photos_are_untouched(tmp_path):
    p = photo(tmp_path)
    before = (p.read_bytes(), p.stat().st_mtime_ns)
    run(tmp_path, [p])
    assert (p.read_bytes(), p.stat().st_mtime_ns) == before and sorted(x.name for x in tmp_path.iterdir()) == ["a.jpg", "out"]


# ---- errors ----
def test_ac14_no_person_is_exit_3(tmp_path, capsys):
    assert run(tmp_path, [photo(tmp_path)], FakeFitter(error=avatar.AvatarError(3, "no person found in a.jpg"))) == 3
    assert capsys.readouterr().err == "part2: no person found in a.jpg\n"
    assert not (tmp_path / "out" / "model.glb").exists()


def test_ac15_gpu_lock_held_is_exit_4(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(avatar.GPU_WAIT_ENV, "0.1")
    with gpu_guard.lock_path().open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        assert run(tmp_path, [photo(tmp_path)]) == 4
    assert "another GPU job is running" in capsys.readouterr().err


def test_ac15_lock_is_released_after_a_run(tmp_path):
    run(tmp_path, [photo(tmp_path)])
    f = gpu_guard.try_lock()
    assert f is not None
    gpu_guard.release(f)


def test_ac15_low_gpu_memory_is_exit_4(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(gpu_guard, "free_gib", lambda: 3.0)
    fitter = avatar.SamFitter(backend=object())
    assert run(tmp_path, [photo(tmp_path)], fitter) == 4
    assert "only 3.0 GiB of GPU memory is free" in capsys.readouterr().err


def test_ac15_out_of_memory_is_exit_4(tmp_path, capsys):
    assert run(tmp_path, [photo(tmp_path)], FakeFitter(error=RuntimeError("the GPU ran out of memory; free memory"))) == 4


def test_ac16_model_not_installed_is_exit_1(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(gpu_guard, "free_gib", lambda: None)

    class Missing:
        def load(self):
            raise BackendUnavailable("the gpu backend is unavailable") from RuntimeError("no gpu-cu128 profile at /x")

    assert run(tmp_path, [photo(tmp_path)], avatar.SamFitter(backend=Missing())) == 1
    assert "the gpu backend is unavailable: no gpu-cu128 profile at /x" in capsys.readouterr().err


def test_ac17_wrong_layout_is_exit_1_and_writes_nothing(tmp_path, capsys):
    class Wrong(FakeFitter):
        def rest(self, shape, scale):
            static, v, j = body()
            static.parents[4] = 1
            return static, v, j

    assert run(tmp_path, [photo(tmp_path)], Wrong()) == 1
    assert "does not have the joint layout avatar expects" in capsys.readouterr().err
    assert list((tmp_path / "out").iterdir()) == []


def test_ac18_implausible_body_is_exit_1(tmp_path, capsys):
    class Nan(FakeFitter):
        def rest(self, shape, scale):
            static, v, j = body()
            v[0, 0] = np.nan
            return static, v, j

    assert run(tmp_path, [photo(tmp_path)], Nan()) == 1
    assert "not plausible" in capsys.readouterr().err and list((tmp_path / "out").iterdir()) == []


# ---- the SAM 3D Body step with a fake estimator ----
class FakeEstimator:
    def __init__(self, people):
        self.people, self.calls = people, []

    def process_one_image(self, path):
        self.calls.append(path)
        return self.people.get(os.path.basename(path), [])


def person(box, shape, scale):
    return {"bbox": np.array(box, float), "shape_params": np.full(45, shape), "scale_params": np.full(28, scale)}


def fitter_with(est):
    f = avatar.SamFitter(backend=object())
    f.estimator = est
    return f


def test_ac11_largest_box_is_chosen(monkeypatch):
    monkeypatch.setattr(gpu_guard, "free_gib", lambda: 20.0)
    est = FakeEstimator({"a.jpg": [person([0, 0, 10, 10], 1, 1), person([0, 0, 100, 200], 7, 8), person([0, 0, 50, 50], 3, 3)]})
    out = fitter_with(est).shapes([avatar.Path("/x/a.jpg")])
    assert out[0]["shape"][0] == 7 and out[0]["scale"][0] == 8 and est.calls == ["/x/a.jpg"]


def test_ac14_no_person_in_a_later_photo_names_it(monkeypatch):
    monkeypatch.setattr(gpu_guard, "free_gib", lambda: 20.0)
    est = FakeEstimator({"a.jpg": [person([0, 0, 10, 10], 1, 1)]})
    with pytest.raises(avatar.AvatarError) as e:
        fitter_with(est).shapes([avatar.Path("a.jpg"), avatar.Path("b.jpg")])
    assert e.value.code == 3 and str(e.value) == "no person found in b.jpg"


# ---- rules ----
def test_ac_nfr1_no_torch_at_import():
    code = "import sys, part2.avatar, part2.mhr_export; print([m for m in ('torch',) if m in sys.modules])"
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip() == "[]"


def test_ac_nfr2_stamped_files_unchanged():
    out = subprocess.run(["git", "diff", "--name-only", "main", "--", "part2/trackers", "part2/track.py", "part2/frames.py",
                          "part2/backends"], capture_output=True, text=True, check=False, cwd=os.path.dirname(os.path.dirname(__file__)))
    assert out.stdout.strip() == ""


def test_memory_is_checked_before_the_load_only(monkeypatch):
    free = iter([20.0, 5.0])  # the second reading (model resident) must not be asked for
    monkeypatch.setattr(gpu_guard, "free_gib", lambda: next(free))

    class Backend:
        def load(self):
            return FakeEstimator({"a.jpg": [person([0, 0, 1, 1], 1, 1)]})

    f = avatar.SamFitter(backend=Backend())
    f.shapes([avatar.Path("a.jpg")])
    f.shapes([avatar.Path("a.jpg")])
