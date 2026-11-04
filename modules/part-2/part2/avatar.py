"""`part2 avatar --out DIR IMG [IMG...]`: one to four photos of one person -> DIR/model.glb + DIR/avatar.json.

SAM 3D Body reads the body shape of each photo; the shapes are combined (median), MHR is evaluated once at its zero pose
with that shape, and part2.mhr_export writes the skinned glTF. Exit codes: 0 written, 1 failed, 2 bad input, 3 no person
found, 4 GPU busy or out of memory. Spec: docs/specs/avatar.md. Licences: ADR-0005 (SAM License; MHR Apache-2.0 notice).
torch loads inside SamFitter only. The caller owns consent and age checks (Part 7 requires consent=self|consented).
"""
import json
import os
import sys
from pathlib import Path

import numpy as np

from part2 import gpu_guard, mhr_export, provenance

MAX_IMAGES = 4
MAX_IMAGE_BYTES = 25 * 1024 * 1024
GPU_WAIT_ENV, GPU_WAIT_DEFAULT_S = "PART2_AVATAR_GPU_WAIT_S", 30.0
GLB_NAME, JSON_NAME, SCHEMA = "model.glb", "avatar.json", "simon.avatar.v1"
EXIT_FAILED, EXIT_BAD_INPUT, EXIT_NO_PERSON, EXIT_GPU_BUSY = 1, 2, 3, 4


class AvatarError(Exception):
    """A failure with its exit code; str() is the one line printed after "part2: "."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _kind(head: bytes) -> str | None:
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def check_images(paths) -> list[Path]:
    """The photos as Paths, or AvatarError(2): 1 to 4 files, each a non-empty JPEG, PNG or WebP of at most 25 MB (AC-1, AC-2)."""
    paths = [Path(p) for p in paths]
    if not 1 <= len(paths) <= MAX_IMAGES:
        raise AvatarError(EXIT_BAD_INPUT, f"avatar takes 1 to {MAX_IMAGES} photos, got {len(paths)}")
    for p in paths:
        if not p.is_file():
            raise AvatarError(EXIT_BAD_INPUT, f"{p}: not a file")
        size = p.stat().st_size
        if size == 0:
            raise AvatarError(EXIT_BAD_INPUT, f"{p}: the file is empty")
        if size > MAX_IMAGE_BYTES:
            raise AvatarError(EXIT_BAD_INPUT, f"{p}: over {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
        with p.open("rb") as f:
            if _kind(f.read(12)) is None:
                raise AvatarError(EXIT_BAD_INPUT, f"{p}: not a JPEG, PNG or WebP image")
    return paths


def combine(params: list[dict]) -> dict:
    """The median shape and scale over the photos (AC-4, AC-11); one photo gives its own."""
    return {k: np.median(np.stack([np.asarray(p[k], dtype=np.float64).reshape(-1) for p in params]), axis=0)
            for k in ("shape", "scale")}


class SamFitter:
    """SAM 3D Body on the GPU: shapes(paths) per photo, rest(shape, scale) the zero-pose body (torch loads here)."""

    def __init__(self, backend=None):
        from part2.backends import gpu_sam3db

        self.backend = backend or gpu_sam3db.Backend()
        self.estimator = None

    def load(self):
        from part2.backends import BackendUnavailable

        if self.estimator is None:
            free = gpu_guard.free_gib()  # before the model is loaded: afterwards its own memory is gone from the free count
            if free is not None and free < gpu_guard.MIN_FREE_GIB:
                raise AvatarError(EXIT_GPU_BUSY, f"only {free:.1f} GiB of GPU memory is free, {gpu_guard.MIN_FREE_GIB:.0f} needed")
            try:
                self.estimator = self.backend.load()
            except BackendUnavailable as e:
                raise AvatarError(EXIT_FAILED, f"{e}: {e.__cause__}" if e.__cause__ else str(e)) from None
        return self.estimator

    def shapes(self, paths: list[Path]) -> list[dict]:
        est = self.load()
        out = []
        for p in paths:
            people = est.process_one_image(str(p))
            if not len(people):
                raise AvatarError(EXIT_NO_PERSON, f"no person found in {p.name}")
            box = lambda o: float((o["bbox"][2] - o["bbox"][0]) * (o["bbox"][3] - o["bbox"][1]))
            best = max(people, key=box)
            out.append({"shape": mhr_export._np(best["shape_params"]), "scale": mhr_export._np(best["scale_params"])})
        return out

    def rest(self, shape, scale):
        """(MhrStatic, vertices (V, 3) m, joints (127, 3) m) at MHR's zero pose with this body shape."""
        import torch

        head = self.load().model.head_pose
        dev = next(head.parameters()).device
        z = lambda *s: torch.zeros(*s, device=dev)
        t = lambda a: torch.as_tensor(np.asarray(a), dtype=torch.float32, device=dev)[None]
        with torch.no_grad():
            verts, joints = head.mhr_forward(global_trans=z(1, 3), global_rot=z(1, 3), body_pose_params=z(1, 133),
                                             hand_pose_params=None, scale_params=t(scale), shape_params=t(shape),
                                             expr_params=z(1, 72), return_joint_coords=True)
        try:
            static = mhr_export.static_from_mhr(head.mhr)
        except AttributeError:
            raise mhr_export.ExportError("this MHR build does not expose its skinning weights") from None
        return static, mhr_export._np(verts)[0], mhr_export._np(joints)[0]


def _document(res, n_images: int) -> dict:
    return {"schema": SCHEMA, "kind": "image", "inputs": n_images, "height_m": res.height_m,
            "joints": mhr_export.JOINTS, "mapped": res.mapped, "licence": mhr_export.LICENCE,
            "part2_commit": provenance.part2_commit(), "skinning": "linear",
            "max_weight_error": round(res.max_weight_error, 6)}


def _write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def build(out: Path, images: list[Path], fitter) -> dict:
    """Fit, export and write; the avatar.json document. Called with the GPU lock held."""
    shape = combine(fitter.shapes(images))
    static, vertices, joints = fitter.rest(shape["shape"], shape["scale"])
    res = mhr_export.build_glb(static, vertices, joints)
    doc = _document(res, len(images))
    _write(out / GLB_NAME, res.glb)
    _write(out / JSON_NAME, (json.dumps(doc, indent=2) + "\n").encode())
    return doc


def command(out, images, fitter=None) -> int:
    """The `avatar` subcommand. `fitter` replaces the GPU step in tests."""
    from part2.backends import NoPersonFound
    from part2.trackers import GpuBusy

    try:
        photos = check_images(images)
        out = Path(out)
        if out.exists() and not out.is_dir():
            raise AvatarError(EXIT_BAD_INPUT, f"{out}: --out exists and is not a directory")
        out.mkdir(parents=True, exist_ok=True)
        for name in (GLB_NAME, JSON_NAME):  # a failed run never leaves the last run's files looking current
            (out / name).unlink(missing_ok=True)
        wait = float(os.environ.get(GPU_WAIT_ENV, GPU_WAIT_DEFAULT_S))
        with gpu_guard.gpu_lock(wait_s=wait):
            doc = build(out, photos, fitter or SamFitter())
    except AvatarError as e:
        print(f"part2: {e}", file=sys.stderr)
        return e.code
    except GpuBusy as e:
        print(f"part2: {e}", file=sys.stderr)
        return EXIT_GPU_BUSY
    except NoPersonFound as e:
        print(f"part2: {e}", file=sys.stderr)
        return EXIT_NO_PERSON
    except (OSError, ValueError, RuntimeError) as e:
        oom = "out of memory" in str(e).lower()
        print(f"part2: {e}", file=sys.stderr)
        return EXIT_GPU_BUSY if oom else EXIT_FAILED
    print(f"avatar ({doc['inputs']} photo(s), {doc['height_m']} m) -> {out / GLB_NAME} + {out / JSON_NAME}")
    return 0
