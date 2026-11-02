"""part2/autorig_mesh.py: reading, normalising and drawing an unrigged mesh. Spec: docs/specs/autorig.md (AC-1 to AC-6)."""
import io
import struct

import numpy as np
import pytest
from autorig_helpers import glb_bytes, humanoid, obj_text, pack
from PIL import Image

from part2 import autorig_mesh as am


def write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data if isinstance(data, bytes) else data.encode())
    return p


def test_ac1_obj_reads_vertices_faces_colours_and_polygons(tmp_path):
    base = humanoid()
    text = obj_text(base)
    text += "# comment\nvn 0 0 1\nvt 0 0\n"
    mesh = am.load(write(tmp_path, "a.obj", text))
    assert mesh.vertices.shape == base.vertices.shape and np.allclose(mesh.vertices, base.vertices)
    assert np.array_equal(mesh.faces, base.faces) and mesh.colors is None
    quad = "".join(f"v {x} {y} 0 0.5 0.25 1\n" for x, y in [(0, 0), (1, 0), (1, 1), (0, 1)])
    many = am.load_obj(quad + "f 1/1/1 2/2/2 3/3/3 4/4/4\n" * 30)
    assert len(many.faces) == 60 and many.faces[0].tolist() == [0, 1, 2] and many.faces[1].tolist() == [0, 2, 3]
    assert np.allclose(many.colors[0], [0.5, 0.25, 1])


def test_ac1_obj_negative_indices_and_unreadable_line():
    text = "v 0 0 0\nv 1 0 0\nv 0 1 0\n" + "f -3 -2 -1\n" * 60
    assert am.load_obj(text).faces[0].tolist() == [0, 1, 2]
    with pytest.raises(am.MeshError, match="line 2 cannot be read"):
        am.load_obj("v 0 0 0\nv 1 x 0\n")
    with pytest.raises(am.MeshError, match="cannot be read"):
        am.load_obj("v 0 0 0\nf 0 1 2\n")


def test_ac2_glb_applies_node_transforms_and_default_indices(tmp_path):
    mesh = humanoid()
    nodes = [{"children": [1], "translation": [1, 0, 0], "scale": [2, 2, 2]}, {"mesh": 0, "translation": [0, 1, 0]}]
    data = glb_bytes(mesh.vertices, mesh.faces, nodes=nodes, scene_nodes=[0])
    out = am.load(write(tmp_path, "a.glb", data))
    assert np.allclose(out.vertices, mesh.vertices * 2 + [1, 2, 0], atol=1e-5)
    flat = glb_bytes(np.tile(mesh.vertices, (2, 1))[:150], None, nodes=[{"mesh": 0, "matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 5, 0, 0, 1]}])
    got = am.load(write(tmp_path, "b.glb", flat))
    assert got.faces.shape == (50, 3) and np.allclose(got.vertices[:, 0], np.tile(mesh.vertices, (2, 1))[:150, 0] + 5, atol=1e-5)


def test_ac2_glb_colours_from_vertex_material_and_texture(tmp_path):
    mesh = humanoid()
    n = len(mesh.vertices)
    vc = am.load(write(tmp_path, "c.glb", glb_bytes(mesh.vertices, mesh.faces, colors=np.full((n, 3), 0.5),
                                                    material={"pbrMetallicRoughness": {"baseColorFactor": [1, 0.5, 1, 1]}})))
    assert np.allclose(vc.colors[0], [0.5, 0.25, 0.5])
    png = io.BytesIO()
    Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(png, "PNG")
    uv = np.zeros((n, 2))
    tex = am.load(write(tmp_path, "t.glb", glb_bytes(
        mesh.vertices, mesh.faces, texcoords=uv, image=png.getvalue(),
        material={"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}})))
    assert np.allclose(tex.colors[0], [1, 0, 0])
    broken = am.load(write(tmp_path, "u.glb", glb_bytes(
        mesh.vertices, mesh.faces, texcoords=uv, image=b"not an image",
        material={"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "baseColorFactor": [0.2, 0.4, 0.6, 1]}})))
    assert np.allclose(broken.colors[0], [0.2, 0.4, 0.6])
    plain = am.load(write(tmp_path, "p.glb", glb_bytes(mesh.vertices, mesh.faces)))
    assert plain.colors is None


def test_ac3_refusals_for_rigged_and_unreadable_glb(tmp_path):
    mesh = humanoid()
    with pytest.raises(am.MeshError, match="already rigged"):
        am.load(write(tmp_path, "s.glb", glb_bytes(mesh.vertices, mesh.faces, skin=True)))
    with pytest.raises(am.MeshError, match="KHR_draco_mesh_compression"):
        am.load(write(tmp_path, "d.glb", glb_bytes(mesh.vertices, mesh.faces, extensions_required=["KHR_draco_mesh_compression"])))
    good = glb_bytes(mesh.vertices, mesh.faces)
    with pytest.raises(am.MeshError, match="cut short"):
        am.load(write(tmp_path, "c.glb", good[:-40]))
    with pytest.raises(am.MeshError, match="not a glTF 2.0"):
        am.load(write(tmp_path, "v.glb", b"glTF" + struct.pack("<II", 1, 20) + b"\0" * 20))
    with pytest.raises(am.MeshError, match="unreadable JSON"):
        am.load(write(tmp_path, "j.glb", b"glTF" + struct.pack("<II", 2, 32) + struct.pack("<I4s", 4, b"JSON") + b"{{{{"))
    with pytest.raises(am.MeshError, match="no triangle mesh"):
        am.load(write(tmp_path, "n.glb", pack({"asset": {"version": "2.0"}, "scenes": [{"nodes": []}], "scene": 0}, b"")))


def test_ac3_glb_with_a_broken_accessor_or_loop_is_refused(tmp_path):
    mesh = humanoid()
    loop = [{"mesh": 0, "children": [0]}]
    with pytest.raises(am.MeshError, match="loops"):
        am.load(write(tmp_path, "l.glb", glb_bytes(mesh.vertices, mesh.faces, nodes=loop)))
    data = bytearray(glb_bytes(mesh.vertices, mesh.faces))
    i = data.index(b'"count"')
    data[i:i + 7] = b'"cxunt"'  # an accessor without its count
    with pytest.raises(am.MeshError, match="accessor"):
        am.load(write(tmp_path, "a.glb", bytes(data)))


def test_ac4_refusals_for_bad_files(tmp_path):
    with pytest.raises(am.MeshError, match="cannot read nope.obj"):
        am.load(tmp_path / "nope.obj")
    with pytest.raises(am.MeshError, match="is not a file"):
        am.load(tmp_path)
    with pytest.raises(am.MeshError, match="is empty"):
        am.load(write(tmp_path, "e.obj", b""))
    with pytest.raises(am.MeshError, match="neither a GLB nor an OBJ"):
        am.load(write(tmp_path, "a.fbx", b"Kaydara FBX Binary  \0"))
    with pytest.raises(am.MeshError, match="no triangles"):
        am.load(write(tmp_path, "z.obj", "v 0 0 0\n"))
    with pytest.raises(am.MeshError, match="too few"):
        am.load(write(tmp_path, "f.obj", "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"))
    with pytest.raises(am.MeshError, match="not a finite number"):
        am.load(write(tmp_path, "n.obj", "v nan 0 0\nv 1 0 0\nv 0 1 0\n" + "f 1 2 3\n" * 60))
    with pytest.raises(am.MeshError, match="missing vertex"):
        am.load(write(tmp_path, "m.obj", "v 0 0 0\nv 1 0 0\nv 0 1 0\n" + "f 1 2 9\n" * 60))


def test_ac4_size_and_triangle_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(am, "MAX_BYTES", 100)
    with pytest.raises(am.MeshError, match="over 0 MB"):
        am.load(write(tmp_path, "big.obj", "v 0 0 0\n" * 40))
    monkeypatch.setattr(am, "MAX_BYTES", 10**9)
    monkeypatch.setattr(am, "MAX_TRIANGLES", 100)
    with pytest.raises(am.MeshError, match="over the 100 limit"):
        am.load(write(tmp_path, "t.obj", "v 0 0 0\nv 1 0 0\nv 0 1 0\n" + "f 1 2 3\n" * 101))


def test_ac5_unit_guess_and_height_flag():
    base = humanoid()
    for factor, unit in ((1, "m"), (100, "cm"), (1000, "mm")):
        mesh, info = am.normalize(am.Mesh(base.vertices * factor + [3, 2, 1], base.faces))
        assert info["unit"] == unit and info["height_m"] == pytest.approx(1.7, abs=0.01)
        assert mesh.vertices[:, 1].min() == pytest.approx(0) and abs(mesh.vertices[:, 0].mean()) < 0.1
    _, info = am.normalize(am.Mesh(base.vertices * 0.001, base.faces))
    assert info["unit"] == "assumed" and info["height_m"] == pytest.approx(1.7, abs=0.01)
    given, info = am.normalize(am.Mesh(base.vertices * 50, base.faces), height_m=1.5)
    assert info["unit"] == "given" and given.vertices[:, 1].max() == pytest.approx(1.5)
    with pytest.raises(am.MeshError, match="--height must be"):
        am.normalize(base, height_m=9)


def test_ac5_z_up_is_turned_to_y_up_facing_kept():
    base = humanoid()
    zup = np.stack([base.vertices[:, 0], -base.vertices[:, 2], base.vertices[:, 1]], axis=1)  # Y up -> Z up, front stays +Y
    mesh, info = am.normalize(am.Mesh(zup, base.faces))
    assert info["up"] == "z" and mesh.vertices[:, 1].max() == pytest.approx(1.7, abs=0.01)
    ref, _ = am.normalize(base, up="y")
    assert np.allclose(np.sort(mesh.vertices, axis=0), np.sort(ref.vertices, axis=0), atol=1e-6)
    with pytest.raises(am.MeshError, match='"y" or "z"'):
        am.normalize(base, up="x")


def test_ac5_a_mesh_with_no_height_is_refused():
    flat = am.Mesh(np.array([[0, 0, 0], [1, 0, 0], [0, 0, 1.0]]), np.array([[0, 1, 2]]))
    with pytest.raises(am.MeshError, match="no height"):
        am.normalize(flat, up="y")
    ints = am.Mesh(np.array([[0, 0, 0], [1, 0, 0], [0, 170, 0]]), np.array([[0, 1, 2]]))  # integer vertices are fine
    assert am.normalize(ints, up="y")[1]["unit"] == "cm"


def test_ac6_front_view_is_deterministic_whole_and_invertible():
    mesh, _ = am.normalize(humanoid(colors=True))
    a, cam = am.render_front(mesh, size=256)
    b, _ = am.render_front(mesh, size=256)
    assert a.size == (256, 256) and a.tobytes() == b.tobytes()
    px = np.asarray(a).astype(int)
    figure = (np.abs(px - np.array(am.BACKGROUND)).sum(axis=2) > 6)
    rows, cols = np.where(figure)
    assert rows.min() > 5 and rows.max() < 250 and cols.min() > 5 and cols.max() < 250  # the whole figure is inside
    assert (rows.max() - rows.min()) / 256 == pytest.approx(am.FILL, abs=0.04)
    q = cam.to_cam(mesh.vertices)
    assert np.allclose(cam.to_mesh(q), mesh.vertices) and (q[:, 2] > 0).all()
    uv = q[:, :2] * cam.K[0, 0] / q[:, 2:3] + 128
    assert uv.min() > 0 and uv.max() < 256


def test_ac6_left_of_the_subject_is_on_the_right_of_the_picture():
    mesh, _ = am.normalize(humanoid())
    image, _ = am.render_front(mesh, size=256)
    figure = (np.abs(np.asarray(image).astype(int) - np.array(am.BACKGROUND)).sum(axis=2) > 6)
    ys = np.where(figure[:, :].any(axis=1))[0]
    arm_row = figure[int(ys.min() + (ys.max() - ys.min()) * 0.25)]
    assert arm_row.any()
    # the subject's left (+x) arm is drawn on the right half: its outline reaches the right edge region
    cols = np.where(arm_row)[0]
    assert cols.max() - 128 == pytest.approx(128 - cols.min(), abs=3)


def test_face_back_is_a_half_turn_about_y():
    mesh = humanoid()
    t = am.face_back(mesh)
    assert np.allclose(t.vertices, mesh.vertices * [-1, 1, -1]) and np.array_equal(t.faces, mesh.faces)
