"""The texture of a generated GLB, read out and put onto a rigged GLB, for `part2 image3d`. numpy and Pillow only.

    tex = read_texture(glb_bytes)                 # Texture(uv (n, 2), image bytes, mime) of the first triangle primitive
    rigged = add_texture(glb, tex, notice)        # TEXCOORD_0, the image, a sampler and the material's base colour

part2 autorig samples a texture into vertex colours; this keeps the image and the UVs instead. The vertex order of the
rigged GLB is the order of the mesh autorig was given, so the UVs read from the generated GLB line up one to one.
Spec: docs/specs/image3d.md (AC-6, AC-7).
"""
import io
from dataclasses import dataclass

import numpy as np
from PIL import Image

from part2 import autorig_glb, autorig_mesh
from part2.autorig_mesh import MeshError

MIMES = {"image/png", "image/jpeg"}


@dataclass
class Texture:
    uv: np.ndarray    # (n, 2) float32, glTF convention (origin top left)
    image: bytes      # PNG or JPEG bytes, as stored in the source GLB
    mime: str

    @property
    def size(self) -> tuple[int, int]:
        return Image.open(io.BytesIO(self.image)).size


def read_texture(glb: bytes, name: str = "the generated GLB") -> Texture:
    """UVs and base colour image of the first triangle primitive; MeshError when it has none."""
    doc, blob = autorig_mesh._glb_chunks(glb, name)
    try:
        prim = next(p for m in doc["meshes"] for p in m["primitives"] if p.get("mode", 4) == 4)
        tex_index = doc["materials"][prim["material"]]["pbrMetallicRoughness"]["baseColorTexture"]["index"]
        img = doc["images"][doc["textures"][tex_index]["source"]]
        view = doc["bufferViews"][img["bufferView"]]
        start = view.get("byteOffset", 0)
        data = bytes(blob[start:start + view["byteLength"]])
        uv = autorig_mesh._accessor(doc, blob, prim["attributes"]["TEXCOORD_0"]).astype(np.float32)
    except (KeyError, IndexError, StopIteration, TypeError):
        raise MeshError(f"{name} has no base colour texture with UVs") from None
    mime = img.get("mimeType", "image/png")
    if mime not in MIMES:
        raise MeshError(f"{name} has a {mime} texture; PNG or JPEG is needed")
    try:
        Image.open(io.BytesIO(data)).verify()
    except (OSError, ValueError):
        raise MeshError(f"{name} has a texture image that cannot be decoded") from None
    if not np.isfinite(uv).all():
        raise MeshError(f"{name} has UVs that are not finite numbers")
    return Texture(uv, data, mime)


def add_texture(glb: bytes, tex: Texture, notice: str, n_vertices: int) -> bytes:
    """`glb` (autorig's skinned GLB, one primitive) with `tex` as its base colour; the asset copyright becomes `notice`."""
    if len(tex.uv) != n_vertices:
        raise autorig_glb.GlbError(f"{len(tex.uv)} UVs for {n_vertices} vertices")
    doc, blob = autorig_mesh._glb_chunks(glb, "the rigged GLB")
    blob = bytes(blob)
    prim = doc["meshes"][0]["primitives"][0]
    for data, view_extra in ((np.ascontiguousarray(tex.uv, dtype="<f4").tobytes(), {"target": 34962}), (tex.image, {})):
        blob += b"\x00" * (-len(blob) % 4)
        view = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), **view_extra}
        blob += data
        doc["bufferViews"].append(view)
    uv_view, img_view = len(doc["bufferViews"]) - 2, len(doc["bufferViews"]) - 1
    doc["accessors"].append({"bufferView": uv_view, "componentType": 5126, "count": n_vertices, "type": "VEC2",
                             "min": [float(x) for x in tex.uv.min(0)], "max": [float(x) for x in tex.uv.max(0)]})
    prim["attributes"]["TEXCOORD_0"] = len(doc["accessors"]) - 1
    doc["images"] = [{"bufferView": img_view, "mimeType": tex.mime, "name": "baseColor"}]
    doc["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071}]
    doc["textures"] = [{"source": 0, "sampler": 0}]
    pbr = doc["materials"][prim["material"]]["pbrMetallicRoughness"]
    pbr["baseColorFactor"] = [1, 1, 1, 1]
    pbr["baseColorTexture"] = {"index": 0}
    doc["asset"]["copyright"] = notice
    doc["buffers"][0]["byteLength"] = len(blob)
    return autorig_glb._pack(doc, blob)
