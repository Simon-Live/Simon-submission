"""One picture -> one textured, unrigged GLB. Runs INSIDE the image3d venv, as a child of `part2 image3d`.

    <image3d venv>/bin/python -I part2/image3d_worker.py --image IMG --out GLB --report JSON
        [--backend sam3do|trellis] [--seed N] [--texture-size N]

Backends: `sam3do` is SAM 3D Objects (Meta, SAM License; the primary), `trellis` is TRELLIS (Microsoft, MIT; the fallback
for a host without the SAM 3D Objects weights).

Imports torch, TRELLIS and nothing of part2 (the venv has no part2). The parent reads the report: stage timings in
seconds, peak GPU memory (torch's allocator, GiB), and the pinned code and weight revisions.

Both give a mesh (modified FlexiCubes, Apache-2.0) and 3D Gaussians for the look. Their own `to_glb` bakes the texture
with nvdiffrast, and TRELLIS also with a Gaussian rasteriser, under non-commercial licences, so this file does that
step itself: the
mesh is decimated (pyvista), unwrapped (xatlas), every texel is mapped back to its point on the surface, and its colour is
the opacity-weighted colour of the Gaussians around that point. The bake functions are numpy and scipy only, so tests run
them without a GPU. Spec: docs/specs/image3d.md. Environment: envs/image3d-cu128/setup.sh.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

STATE = Path(os.environ.get("PART2_STATE_DIR", Path.home() / ".local/state/simon-part-2"))
# per backend: weights repo and revision, code commit, the display name written to avatar.json
BACKENDS = {
    "sam3do": {"name": "sam3do", "label": "SAM 3D Objects", "weights_repo": "jetjodh/sam-3d-objects",
               "weights_revision": "f29e43c151f2d1a390ce560fa4e439ede44ee801",
               "code_commit": "f91db411c50efee93d8db7aeb323885650f6f722"},
    "trellis": {"name": "trellis", "label": "TRELLIS-image-large", "weights_repo": "microsoft/TRELLIS-image-large",
                "weights_revision": "25e0d31ffbebe4b5a97464dd851910efc3002d96",
                "code_commit": "193e0502b5cb3eb5997ec457d5340e95d09b158e"},
}
ALLOWED_TARGETS = ("sam3d_objects", "torch", "torchvision", "moge")  # what a SAM 3D Objects config may instantiate
SIMPLIFY, TEXTURE_SIZE, SEED = 0.95, 1024, 1
KEEP_COMPONENT = 0.02            # a loose piece smaller than this share of the faces is dropped
NEIGHBOURS = 16                  # Gaussians that colour a texel
SH_C0 = 0.28209479177387814      # the degree-0 spherical harmonic, TRELLIS stores colour as DC coefficients


# ---- the texture bake (numpy, scipy; no GPU) ---------------------------------------------------------

def drop_loose_pieces(faces: np.ndarray, keep: float = KEEP_COMPONENT) -> np.ndarray:
    """The faces of the connected pieces that hold at least `keep` of all faces (the figure; not floating specks)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    n = int(faces.max()) + 1
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]]])
    _, label = connected_components(coo_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(n, n)), directed=False)
    per_face = label[faces[:, 0]]
    size = np.bincount(per_face)
    return faces[size[per_face] >= keep * len(faces)]


def rasterize_uv(uv: np.ndarray, faces: np.ndarray, size: int):
    """(face (size, size) int, -1 where no face, bary (size, size, 3)): the triangle under each texel centre and the
    barycentric weights there. Row r is v = (r + 0.5) / size, so v grows with the row (xatlas's convention)."""
    face = np.full((size, size), -1, dtype=np.int64)
    bary = np.zeros((size, size, 3))
    p = uv * size
    for f in range(len(faces)):
        a, b, c = p[faces[f]]
        x0, x1 = int(max(np.floor(min(a[0], b[0], c[0])), 0)), int(min(np.ceil(max(a[0], b[0], c[0])), size))
        y0, y1 = int(max(np.floor(min(a[1], b[1], c[1])), 0)), int(min(np.ceil(max(a[1], b[1], c[1])), size))
        den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if x1 <= x0 or y1 <= y0 or abs(den) < 1e-12:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        l0 = ((b[1] - c[1]) * (gx - c[0]) + (c[0] - b[0]) * (gy - c[1])) / den
        l1 = ((c[1] - a[1]) * (gx - c[0]) + (a[0] - c[0]) * (gy - c[1])) / den
        inside = (l0 >= 0) & (l1 >= 0) & (1 - l0 - l1 >= 0)
        if inside.any():
            ys, xs = np.nonzero(inside)
            face[y0 + ys, x0 + xs] = f
            bary[y0 + ys, x0 + xs] = np.stack([l0[inside], l1[inside], 1 - l0[inside] - l1[inside]], axis=1)
    return face, bary


def gaussian_colours(points, xyz, scales, quats, opacity, rgb, k: int = NEIGHBOURS, block: int = 100_000) -> np.ndarray:
    """(n, 3) float colour at each point: the Gaussians' colours weighted by opacity times the Gaussian's density at the
    point (its own scales and rotation), over the k nearest Gaussians. A point none of them reaches takes the nearest."""
    from scipy.spatial import cKDTree

    tree = cKDTree(xyz)
    k = min(k, len(xyz))
    out = np.zeros((len(points), 3))
    for s in range(0, len(points), block):
        pts = points[s:s + block]
        _, nn = tree.query(pts, k=k, workers=-1)
        nn = nn.reshape(len(pts), k)
        d = pts[:, None, :] - xyz[nn]                                  # (b, k, 3)
        w, x, y, z = (quats[nn][..., i] for i in range(4))
        rot = np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
                        2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
                        2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], axis=-1).reshape(*nn.shape, 3, 3)
        local = np.einsum("bkji,bkj->bki", rot, d) / scales[nn]         # R^T d / s
        weight = opacity[nn] * np.exp(-0.5 * (local ** 2).sum(-1))      # (b, k)
        total = weight.sum(1, keepdims=True)
        colour = (weight[..., None] * rgb[nn]).sum(1) / np.maximum(total, 1e-12)
        out[s:s + block] = np.where(total > 1e-6, colour, rgb[nn[:, 0]])
    return out


def fill_gutter(image: np.ndarray, covered: np.ndarray) -> np.ndarray:
    """Texels no triangle covers take the colour of the nearest covered texel, so filtering at a seam does not bleed."""
    from scipy.ndimage import distance_transform_edt

    _, (iy, ix) = distance_transform_edt(~covered, return_indices=True)
    return image[iy, ix]


def bake_texture(vertices, faces, uv, gaussians: dict, size: int = TEXTURE_SIZE) -> np.ndarray:
    """(size, size, 3) uint8, image row 0 at the top (glTF), for a mesh unwrapped to `uv` and Gaussians given as a dict
    of numpy arrays: xyz (n,3), scales (n,3), quats (n,4 wxyz), opacity (n,), rgb (n,3) in 0..1."""
    face, bary = rasterize_uv(uv, faces, size)
    covered = face >= 0
    tri = vertices[faces[face[covered]]]                                 # (m, 3, 3)
    points = (tri * bary[covered][..., None]).sum(1)
    colour = np.zeros((size, size, 3))
    colour[covered] = gaussian_colours(points, gaussians["xyz"], gaussians["scales"], gaussians["quats"],
                                       gaussians["opacity"], gaussians["rgb"])
    colour = fill_gutter(colour, covered)
    return np.clip(colour[::-1] * 255 + 0.5, 0, 255).astype(np.uint8)   # v up -> image row 0 on top


def textured_mesh(vertices, faces, gaussians: dict, simplify: float = SIMPLIFY, size: int = TEXTURE_SIZE):
    """(vertices, faces, uv, texture) for a Z-up mesh: loose pieces dropped, decimated, unwrapped, baked."""
    import pyvista
    import xatlas

    faces = drop_loose_pieces(np.asarray(faces))
    if simplify > 0:
        poly = pyvista.PolyData(vertices, np.concatenate([np.full((len(faces), 1), 3), faces], axis=1))
        poly = poly.decimate(simplify)
        vertices, faces = poly.points, poly.faces.reshape(-1, 4)[:, 1:]
    mapping, indices, uv = xatlas.parametrize(np.asarray(vertices, dtype=np.float32), np.asarray(faces, dtype=np.uint32))
    vertices, faces = np.asarray(vertices)[mapping], indices.astype(np.int64)
    return vertices, faces, uv, bake_texture(vertices, faces, uv, gaussians, size)


# ---- the TRELLIS run ---------------------------------------------------------------------------------

def _env(backend: str) -> None:
    """Set before torch/TRELLIS import: dense attention through SDPA, sparse attention through xformers (flash_attn has
    no build for sm_120), spconv's own kernels, and the weight caches under the state directory."""
    os.environ.setdefault("ATTN_BACKEND", "sdpa")
    os.environ.setdefault("SPARSE_ATTN_BACKEND", "xformers")
    os.environ.setdefault("SPCONV_ALGO", "native")
    os.environ.setdefault("HF_HOME", str(STATE / "image3d-cache" / "hf"))
    os.environ.setdefault("TORCH_HOME", str(STATE / "image3d-cache" / "torch"))
    os.environ.setdefault("U2NET_HOME", str(STATE / "image3d-cache" / "u2net"))
    os.environ["LIDRA_SKIP_INIT"] = "true"  # SAM 3D Objects: skip its package-level init
    sys.path.insert(0, str(STATE / "src" / {"sam3do": "sam-3d-objects", "trellis": "TRELLIS"}[backend]))
    _shim_kaolin()
    _pin_xformers_cutlass()


def _pin_xformers_cutlass() -> None:
    """xformers 0.0.32 picks its Hopper flash-attention kernel on this card (sm_120) and fails with "invalid argument";
    its cutlass kernel runs, so every TRELLIS sparse-attention call is given that op."""
    import xformers.ops as xops

    plain = xops.memory_efficient_attention
    xops.memory_efficient_attention = lambda *a, **k: plain(*a, **{"op": xops.MemoryEfficientAttentionCutlassOp, **k})


def _shim_kaolin() -> None:
    """FlexiCubes imports kaolin only for `check_tensor`, a shape assertion helper called inside `assert` with
    throw=False; kaolin has no wheel for this torch/CUDA, so a one-function module stands in."""
    import types

    testing = types.ModuleType("kaolin.utils.testing")
    testing.check_tensor = lambda *a, **k: True
    for name, mod in (("kaolin", types.ModuleType("kaolin")), ("kaolin.utils", types.ModuleType("kaolin.utils")),
                      ("kaolin.utils.testing", testing)):
        sys.modules.setdefault(name, mod)


def _gaussians(g) -> dict:
    n = lambda t: t.detach().float().cpu().numpy().astype(np.float64)
    return {"xyz": n(g.get_xyz), "scales": n(g.get_scaling), "quats": n(g.get_rotation), "opacity": n(g.get_opacity)[:, 0],
            "rgb": np.clip(0.5 + SH_C0 * n(g.get_features)[:, 0, :], 0, 1)}


def _export(vertices, faces, uv, texture: np.ndarray, path: str) -> None:
    import trimesh
    from PIL import Image

    vertices = vertices @ np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]])      # both models are Z up, glTF is Y up
    material = trimesh.visual.material.PBRMaterial(roughnessFactor=1.0, baseColorTexture=Image.fromarray(texture),
                                                   baseColorFactor=np.array([255, 255, 255, 255], dtype=np.uint8))
    mesh = trimesh.Trimesh(vertices, faces, visual=trimesh.visual.TextureVisuals(uv=uv, material=material), process=False)
    mesh.export(path)


def check_targets(node, where: str = "config") -> None:
    """Refuse a hydra config that would instantiate anything outside ALLOWED_TARGETS (a config is code to hydra)."""
    if isinstance(node, dict):
        target = node.get("_target_")
        if target is not None and target.split(".", 1)[0] not in ALLOWED_TARGETS:
            raise ValueError(f"{where}: refusing _target_ {target}")
        for key, value in node.items():
            check_targets(value, f"{where}.{key}")
    elif isinstance(node, (list, tuple)):
        for i, value in enumerate(node):
            check_targets(value, f"{where}[{i}]")


def load_trellis(root: str):
    """A function PIL image, seed -> (mesh, gaussian) for TRELLIS-image-large at `root`."""
    from trellis.pipelines import TrellisImageTo3DPipeline

    pipeline = TrellisImageTo3DPipeline.from_pretrained(root)
    pipeline.cuda()

    def generate(image, seed):
        out = pipeline.run(image, seed=seed, formats=["gaussian", "mesh"])
        return out["mesh"][0], out["gaussian"][0]

    return generate


def load_sam3do(root: str):
    """A function PIL image, seed -> (mesh, gaussian) for the SAM 3D Objects pipeline at `root/checkpoints`. The
    subject mask comes from rembg; the mesh and Gaussians are the decoders' own output, before any postprocess."""
    import torch
    from hydra.utils import instantiate
    from omegaconf import OmegaConf

    ckpt = Path(root) / "checkpoints"
    for yaml in sorted(ckpt.glob("*.yaml")):
        check_targets(OmegaConf.to_container(OmegaConf.load(yaml)), yaml.name)
    config = OmegaConf.load(ckpt / "pipeline.yaml")
    config.rendering_engine, config.compile_model, config.workspace_dir = "pytorch3d", False, str(ckpt)
    pipeline = instantiate(config)

    def generate(image, seed):
        import rembg

        rgb = image.convert("RGB")
        mask = (np.asarray(rembg.remove(rgb, only_mask=True)) > 127).astype(np.uint8) * 255
        out = pipeline.run(np.asarray(rgb), mask, seed, stage1_only=False, with_mesh_postprocess=False,
                           with_texture_baking=False, with_layout_postprocess=False, use_vertex_color=True)
        torch.cuda.synchronize()
        return out["mesh"][0], out["gaussian"][0]

    return generate


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--backend", choices=sorted(BACKENDS), default="sam3do")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--texture-size", type=int, default=TEXTURE_SIZE)
    args = ap.parse_args()
    spec = BACKENDS[args.backend]
    _env(args.backend)
    import torch
    from huggingface_hub import snapshot_download
    from PIL import Image

    marks = {}
    t0 = time.monotonic()
    torch.cuda.reset_peak_memory_stats()
    root = snapshot_download(spec["weights_repo"], revision=spec["weights_revision"])
    generate = (load_sam3do if args.backend == "sam3do" else load_trellis)(root)
    marks["load_s"] = time.monotonic() - t0
    t1 = time.monotonic()
    image = Image.open(args.image)
    image.load()
    mesh, gaussian = generate(image, args.seed)
    marks["generate_s"] = time.monotonic() - t1
    t2 = time.monotonic()
    vertices, faces, uv, texture = textured_mesh(mesh.vertices.detach().cpu().numpy(), mesh.faces.detach().cpu().numpy(),
                                                 _gaussians(gaussian), SIMPLIFY, args.texture_size)
    _export(vertices, faces, uv, texture, args.out)
    marks["bake_s"] = time.monotonic() - t2
    gib = 1024 ** 3
    report = {"backend": spec["name"], "version": f"{spec['label']}@{spec['weights_revision'][:7]}, code {spec['code_commit'][:7]}",
              "weights_repo": spec["weights_repo"], "weights_revision": spec["weights_revision"],
              "code_commit": spec["code_commit"], "seed": args.seed, "texture_size": args.texture_size, "faces": len(faces),
              "timings_s": {k: round(v, 2) for k, v in marks.items()},
              "peak_vram_allocated_gib": round(torch.cuda.max_memory_allocated() / gib, 2),
              "peak_vram_reserved_gib": round(torch.cuda.max_memory_reserved() / gib, 2)}
    Path(args.report).write_text(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
