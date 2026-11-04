"""`part2 image3d --out DIR IMG [--height M]`: a picture of a character -> DIR/model.glb (textured, rigged) + DIR/avatar.json.

    1. TRELLIS (MIT, Microsoft) makes a textured mesh from the picture, in a child process of the image3d venv
       (part2/image3d_worker.py), so its torch, spconv and CUDA build never meet the SAM 3D Body venv.
    2. part2 autorig rigs that mesh: SAM 3D Body fits the MHR body to a front drawing of it, the skeleton and the skin
       weights come from MHR, and the 22 canonical bones carry their names.
    3. The baked texture is kept as an image with its UVs (part2.image3d_glb), not sampled into vertex colours.

Exit codes: 0 written, 1 failed, 2 bad input, 3 nothing humanoid could be rigged (the picture is not of a figure the
body model can fit), 4 GPU busy or too little GPU memory. Spec: docs/specs/image3d.md. Licences: ADR-0005. The caller owns
the right to use the picture (a copyrighted character stays that character's owner's).
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from part2 import autorig, autorig_mesh, gpu_guard, image3d_glb, provenance
from part2.autorig_mesh import Mesh, MeshError
from part2.mhr_export import JOINTS, LICENCE

STATE = Path(os.environ.get("PART2_STATE_DIR", Path.home() / ".local/state/simon-part-2"))
PYTHON_ENV = "PART2_IMAGE3D_PYTHON"
GPU_WAIT_ENV, GPU_WAIT_S = "PART2_IMAGE3D_GPU_WAIT_S", 30.0
BACKENDS = ("auto", "sam3do", "trellis")
LABELS = {"sam3do": "SAM 3D Objects", "trellis": "TRELLIS"}
MIN_FREE_ENV = "PART2_IMAGE3D_MIN_FREE_GIB"  # overrides the need below (a caller that knows better, tests)
MIN_FREE_GIB = {"sam3do": 22.0, "trellis": 16.0}  # sam3do: device peak on an empty card, measured (spec "Measured"); trellis: unmeasured estimate
GEN_TIMEOUT_S = 1800.0
ASSUMED_HEIGHT_M = 1.7
SCHEMA, KIND = "simon.avatar.v1", "image3d"
GLB_NAME, JSON_NAME = "model.glb", "avatar.json"
YAWS_DEG = (0, 90, 270)          # generated figures are not always turned to the camera the way autorig expects
# per backend: how the notice names it, what a copy needs of it, and the words added to avatar.json's `licence`
CREDIT = {"sam3do": ("SAM 3D Objects (SAM License, Meta, 2025-11-19)", "a copy of the SAM License", ""),
          "trellis": ("TRELLIS (Microsoft, MIT licence)", "the TRELLIS MIT notice (Copyright (c) Microsoft Corporation)",
                      "; TRELLIS MIT")}


def notice(backend: str) -> str:
    made, needs, _ = CREDIT[backend]
    return (f"Made from a picture with {made}, rigged with SAM 3D Body (SAM License, Meta, 2025-11-19) and the MHR body "
            "model (Apache-2.0, facebookresearch/MHR): the skeleton and the skin weights come from MHR. Passing this "
            f"file on needs a copy of the SAM License, the MHR Apache-2.0 licence text and notice, and {needs}. The look "
            "of the model comes from the picture it was made from; the rights to that picture belong to its owner.")


class Image3dError(Exception):
    """A run that ends with `code`; str() is the one line printed after "part2: "."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Generated:
    glb: bytes
    report: dict = field(default_factory=dict)


def check_image(path) -> Path:
    """The picture as a Path, or Image3dError(2): one non-empty JPEG, PNG or WebP of at most 25 MB (same rules as avatar)."""
    from part2 import avatar

    try:
        return avatar.check_images([path])[0]
    except avatar.AvatarError as e:
        raise Image3dError(2, str(e).replace("avatar takes", "image3d takes")) from None


# ---- step 1: the textured mesh ----------------------------------------------------------------------

class VramSampler:
    """Polls nvidia-smi for the used memory of GPU 0 while a child runs: the device-wide peak, which includes the CUDA
    context and every other process (torch's own peak is in the worker's report)."""

    def __init__(self, period_s: float = 0.5):
        self.period, self.peak_gib, self.start_gib = period_s, None, None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _used(self):
        q = gpu_guard.query()
        return None if q is None else q["total_gib"] - q["free_gib"]

    def _run(self):
        while not self._stop.is_set():
            used = self._used()
            if used is not None:
                self.peak_gib = used if self.peak_gib is None else max(self.peak_gib, used)
            self._stop.wait(self.period)

    def __enter__(self):
        self.start_gib = self._used()
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=5)


def worker_python() -> Path:
    return Path(os.environ.get(PYTHON_ENV) or STATE / "venvs" / "image3d-cu128" / "bin" / "python")


class ObjectGenerator:
    """One image3d-venv backend ("sam3do" or "trellis") run as a child process: generate(image, workdir) -> Generated."""

    def __init__(self, backend: str):
        self.backend = backend

    def generate(self, image: Path, workdir: Path) -> Generated:
        py = worker_python()
        label = LABELS[self.backend]
        if not py.is_file():
            raise Image3dError(1, f"the image3d environment is not installed ({py}); run envs/image3d-cu128/setup.sh")
        script = Path(__file__).with_name("image3d_worker.py")
        glb, report = workdir / "generated.glb", workdir / "generated.json"
        cmd = [str(py), "-I", str(script), "--backend", self.backend, "--image", str(image), "--out", str(glb),
               "--report", str(report)]
        with VramSampler() as vram:
            try:
                done = subprocess.run(cmd, capture_output=True, text=True, timeout=GEN_TIMEOUT_S, check=False)
            except subprocess.TimeoutExpired:
                raise Image3dError(1, f"{label} did not finish within {GEN_TIMEOUT_S:.0f} s") from None
        if done.returncode != 0 or not glb.is_file() or not report.is_file():
            tail = (done.stderr or done.stdout).strip().splitlines()[-1:] or ["no output"]
            oom = "out of memory" in (done.stderr or "").lower()
            raise Image3dError(4 if oom else 1, f"{label} failed (exit {done.returncode}): {tail[0][:300]}")
        rep = json.loads(report.read_text())
        rep["device_used_before_gib"] = None if vram.start_gib is None else round(vram.start_gib, 2)
        rep["device_used_peak_gib"] = None if vram.peak_gib is None else round(vram.peak_gib, 2)
        return Generated(glb.read_bytes(), rep)


class AutoGenerator:
    """SAM 3D Objects first; TRELLIS only when SAM 3D Objects cannot run here (a failure that is not a busy or full GPU).
    The report says which ran and, after a fallback, why SAM 3D Objects did not."""

    def generate(self, image: Path, workdir: Path) -> Generated:
        try:
            return ObjectGenerator("sam3do").generate(image, workdir)
        except Image3dError as e:
            if e.code != 1:
                raise
            gen = ObjectGenerator("trellis").generate(image, workdir)
            gen.report["fallback_from"] = {"backend": "sam3do", "reason": str(e)}
            return gen


def make_generator(backend: str):
    if backend not in BACKENDS:
        raise Image3dError(2, f"--backend must be one of {', '.join(BACKENDS)}")
    return AutoGenerator() if backend == "auto" else ObjectGenerator(backend)


# ---- step 2 and 3: rig it, keep the texture ---------------------------------------------------------

def _yawed(mesh: Mesh, deg: int) -> Mesh:
    """The mesh turned `deg` degrees about Y (vertex order kept, so UVs still line up)."""
    a = np.deg2rad(deg)
    c, s = np.cos(a), np.sin(a)
    v = mesh.vertices @ np.array([[c, 0, -s], [0, 1, 0], [s, 0, c]]).T
    return Mesh(v, mesh.faces, mesh.colors)


def _with_colours(fit_body, colours):
    """autorig draws the mesh with vertex colours; this mesh has none (its look is the texture), so the drawing gets the
    colours sampled from the texture while the GLB built from the same mesh gets none."""
    return lambda m: fit_body(Mesh(m.vertices, m.faces, colours))


def rig_textured(glb: bytes, skin, fit_body, height_m: float, commit: str, backend: str) -> tuple[bytes, dict]:
    """(rigged GLB with the texture, avatar.json base) for a generated GLB. Tries the figure as it is, then turned a
    quarter either way, and keeps the first the body model fits; raises Image3dError(3) when none fits."""
    try:
        coloured = autorig_mesh.check(autorig_mesh.load_glb(glb))
        tex = image3d_glb.read_texture(glb)
        if len(tex.uv) != len(coloured.vertices):
            raise MeshError("the generated GLB has more than one primitive")
        mesh, info = autorig_mesh.normalize(Mesh(coloured.vertices, coloured.faces, None), height_m, "y")
    except MeshError as e:
        raise Image3dError(1, f"the generated model cannot be used: {e}") from None
    colours, why = coloured.colors, "no attempt"
    autorig.TRACE.clear()
    for yaw in YAWS_DEG:
        try:
            rigged = autorig.rig(_yawed(mesh, yaw), skin, _with_colours(fit_body, colours), commit)
        except autorig.NoPersonInPicture as e:
            why = str(e)
        except autorig.BadInput as e:
            why = str(e)
        else:
            avatar = dict(rigged.avatar, turned_before_fit_deg=yaw, up_axis=info["up"])
            return image3d_glb.add_texture(rigged.glb, tex, notice(backend), len(mesh.vertices)), {**avatar, "texture": _texture_doc(tex)}
    why = f"{why} (fits tried, in order: {autorig.TRACE})"
    raise Image3dError(3, f"nothing humanoid could be rigged from this picture: {why}")


def _texture_doc(tex) -> dict:
    w, h = tex.size
    return {"mime": tex.mime, "width": w, "height": h, "uv_set": 0}


def _document(base: dict, gen: dict, wall_s: float, rig_s: float, height_assumed: bool) -> dict:
    return {**base, "schema": SCHEMA, "kind": KIND, "inputs": 1, "joints": JOINTS, "licence": LICENCE + CREDIT[gen["backend"]][2],
            "backend": {k: gen.get(k) for k in ("backend", "version", "weights_repo", "weights_revision", "code_commit",
                                                 "seed", "texture_size")},
            "timings_s": {**gen.get("timings_s", {}), "rig_s": round(rig_s, 2), "total_s": round(wall_s, 2)},
            "peak_vram_gib": {k: gen.get(k) for k in ("peak_vram_allocated_gib", "peak_vram_reserved_gib",
                                                       "device_used_before_gib", "device_used_peak_gib")},
            "height_assumed": height_assumed, "copyright": notice(gen["backend"])}


def _write(out: Path, glb: bytes, doc: dict) -> None:
    for name, data in ((GLB_NAME, glb), (JSON_NAME, (json.dumps(doc, indent=2) + "\n").encode())):
        tmp = out / (name + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, out / name)


def build(out: Path, image: Path, generator, skin_loader, fit_body_factory, height_m, commit: str) -> dict:
    """Generate, rig, write; the avatar.json document. Called with the GPU lock held. `skin_loader()` and
    `fit_body_factory()` are the SAM 3D Body parts, called after the generator's process has ended and freed its memory."""
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="image3d-") as tmp:
        gen = generator.generate(image, Path(tmp))
    t1 = time.monotonic()
    glb, base = rig_textured(gen.glb, skin_loader(), fit_body_factory(), height_m or ASSUMED_HEIGHT_M, commit,
                              gen.report["backend"])
    t2 = time.monotonic()
    doc = _document(base, gen.report, t2 - t0, t2 - t1, height_m is None)
    _write(out, glb, doc)
    return doc


# ---- the command ------------------------------------------------------------------------------------

def _sam_parts():
    """(skin_loader, fit_body_factory) for the gpu backend, or Image3dError(1) when it cannot run here."""
    from part2 import backends

    backend = backends.get("gpu")
    try:
        ok, reason = backend.available()
    except Exception as e:  # noqa: BLE001  (a broken install is the same answer as a missing one)
        ok, reason = False, str(e)
    if not ok:
        raise Image3dError(1, reason)
    return (lambda: autorig.load_skin(backend.paths()["ckpt"])), (lambda: autorig.sam_fit_body(backend))


def command(out, image, height_m=None, backend="auto", generator=None, sam_parts=None) -> int:
    """The `image3d` subcommand. `generator` and `sam_parts` replace the GPU steps in tests."""
    need = float(os.environ.get(MIN_FREE_ENV) or MIN_FREE_GIB.get(backend if backend != "auto" else "sam3do", 0.0))
    from part2.trackers import GpuBusy

    try:
        img = check_image(image)
        if height_m is not None and not 0.3 <= height_m <= 3.0:
            raise Image3dError(2, "--height must be between 0.3 and 3 metres")
        if backend not in BACKENDS:
            raise Image3dError(2, f"--backend must be one of {', '.join(BACKENDS)}")
        out = Path(out)
        if out.exists() and not out.is_dir():
            raise Image3dError(2, f"{out}: --out exists and is not a directory")
        out.mkdir(parents=True, exist_ok=True)
        for name in (GLB_NAME, JSON_NAME):  # a failed run never leaves the last run's files looking current
            (out / name).unlink(missing_ok=True)
        free = gpu_guard.free_gib()
        if generator is None and free is not None and free < need:
            raise Image3dError(4, f"only {free:.1f} GiB of GPU memory is free, {need:.0f} needed; "
                                  "Part 2's warm workers hold the rest and must release first")
        with gpu_guard.gpu_lock(wait_s=float(os.environ.get(GPU_WAIT_ENV, GPU_WAIT_S))):
            doc = build(out, img, generator or make_generator(backend), *(sam_parts if sam_parts is not None else _sam_parts()), height_m,
                        provenance.part2_commit())
    except Image3dError as e:
        print(f"part2: {e}", file=sys.stderr)
        return e.code
    except GpuBusy as e:
        print(f"part2: {e}", file=sys.stderr)
        return 4
    except (OSError, ValueError, RuntimeError) as e:
        print(f"part2: {e}", file=sys.stderr)
        return 4 if "out of memory" in str(e).lower() else 1
    print(f"image3d ({doc['height_m']} m, {len(doc['mapped'])} named bones, texture {doc['texture']['width']}x"
          f"{doc['texture']['height']}) -> {out / GLB_NAME} + {out / JSON_NAME}")
    return 0
