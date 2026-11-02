"""Shared fixtures for the image3d tests: a textured box humanoid GLB, a fake generator and fake SAM parts.

No GPU, no torch, no scipy. Spec: docs/specs/image3d.md."""
import io

import numpy as np
from autorig_helpers import fake_fit_body, glb_bytes, humanoid, synthetic_skin
from PIL import Image

from part2 import autorig_mesh, image3d

MATERIAL = {"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}


def png_bytes(size=8, colour=(200, 60, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), colour).save(buf, "PNG")
    return buf.getvalue()


def textured_glb(png=None, with_uv=True) -> tuple[bytes, np.ndarray]:
    """(GLB bytes, UVs): the box humanoid as one primitive with a base colour texture, as TRELLIS writes it."""
    mesh = humanoid()
    rng = np.random.default_rng(3)
    uv = rng.random((len(mesh.vertices), 2)).astype(np.float32)
    glb = glb_bytes(mesh.vertices, mesh.faces, material=MATERIAL, texcoords=uv if with_uv else None,
                    image=png if png is not None else png_bytes())
    return glb, uv


class FakeGenerator:
    def __init__(self, glb=None, error=None):
        self.glb, self.error, self.calls = glb, error, []

    def generate(self, image, workdir):
        self.calls.append(image)
        if self.error:
            raise self.error
        report = {"backend": "trellis", "version": "fake", "weights_repo": "x/y", "weights_revision": "r",
                  "code_commit": "c", "seed": 1, "texture_size": 8, "timings_s": {"load_s": 1.0, "generate_s": 2.0},
                  "peak_vram_allocated_gib": 10.5, "peak_vram_reserved_gib": 12.0,
                  "device_used_before_gib": 11.0, "device_used_peak_gib": 24.0}
        return image3d.Generated(self.glb or textured_glb()[0], report)


def fake_sam_parts(**fake):
    """(skin_loader, fit_body_factory) like image3d._sam_parts, with the box humanoid's synthetic skin."""
    mesh = autorig_mesh.normalize(humanoid())[0]
    return (lambda: synthetic_skin(mesh.vertices)), (lambda: fake_fit_body(**fake))
