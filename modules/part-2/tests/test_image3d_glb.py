"""part2/image3d_glb.py: the texture of a generated GLB, kept on the rigged GLB. Spec: docs/specs/image3d.md (AC-6, AC-7)."""
import numpy as np
import pytest
from autorig_helpers import fake_fit_body, glb_bytes, humanoid, synthetic_skin
from image3d_helpers import png_bytes, textured_glb

from part2 import autorig, autorig_glb, autorig_mesh, image3d_glb
from part2.autorig_mesh import MeshError


def test_read_texture_gives_uvs_and_the_stored_image():
    png = png_bytes(16)
    glb, uv = textured_glb(png)
    tex = image3d_glb.read_texture(glb)
    assert tex.image == png and tex.mime == "image/png" and tex.size == (16, 16)
    assert np.array_equal(tex.uv, uv)


@pytest.mark.parametrize("make,words", [
    (lambda: textured_glb(with_uv=False)[0], "no base colour texture"),
    (lambda: glb_bytes(humanoid().vertices, humanoid().faces), "no base colour texture"),
    (lambda: textured_glb(png=b"not an image")[0], "cannot be decoded"),
])
def test_read_texture_refuses_a_glb_without_a_usable_texture(make, words):
    with pytest.raises(MeshError, match=words):
        image3d_glb.read_texture(make())


def test_read_texture_refuses_a_texture_that_is_not_png_or_jpeg():
    glb, _ = textured_glb()
    doc, blob = autorig_mesh._glb_chunks(glb, "x")
    doc["images"][0]["mimeType"] = "image/webp"
    with pytest.raises(MeshError, match="image/webp"):
        image3d_glb.read_texture(autorig_glb._pack(doc, bytes(blob)))


def rigged_glb():
    mesh = autorig_mesh.normalize(humanoid())[0]
    skin = synthetic_skin(mesh.vertices)
    return mesh, autorig.rig(mesh, skin, fake_fit_body(), "abc").glb


def test_add_texture_keeps_image_uvs_and_skin_and_has_no_vertex_colours():
    mesh, glb = rigged_glb()
    glb2, uv = textured_glb()
    tex = image3d_glb.read_texture(glb2)
    out = image3d_glb.add_texture(glb, tex, "my notice", len(mesh.vertices))
    doc, read = autorig_glb.read(out)
    prim = doc["meshes"][0]["primitives"][0]
    assert "COLOR_0" not in prim["attributes"] and "JOINTS_0" in prim["attributes"]
    _, blob0 = autorig_mesh._glb_chunks(out, "x")
    assert np.array_equal(autorig_mesh._accessor(doc, blob0, prim["attributes"]["TEXCOORD_0"]), uv)
    assert prim["material"] == 0 and doc["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"] == {"index": 0}
    assert doc["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"] == [1, 1, 1, 1]
    view = doc["bufferViews"][doc["images"][0]["bufferView"]]
    _, blob = autorig_mesh._glb_chunks(out, "x")
    assert bytes(blob[view["byteOffset"]:view["byteOffset"] + view["byteLength"]]) == tex.image
    assert doc["asset"]["copyright"] == "my notice" and doc["buffers"][0]["byteLength"] == len(blob)
    assert doc["skins"] and len(doc["skins"][0]["joints"]) == 127
    assert np.array_equal(read(prim["attributes"]["POSITION"]), mesh.vertices.astype("<f4"))  # positions untouched


def test_add_texture_refuses_uvs_that_do_not_match_the_vertices():
    _, glb = rigged_glb()
    tex = image3d_glb.read_texture(textured_glb()[0])
    with pytest.raises(autorig_glb.GlbError, match="UVs for"):
        image3d_glb.add_texture(glb, tex, "n", len(tex.uv) + 1)
