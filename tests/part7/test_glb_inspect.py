"""GLB reading, checks and bind-pose measures (docs/specs/model-import.md; AC-MI1 to AC-MI6)."""

from __future__ import annotations

import os
from pathlib import Path
import struct
import sys

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "models"))

import glbmaker  # noqa: E402
from part7 import bone_map, glb_inspect  # noqa: E402

REAL = HERE / "fixtures" / "models" / "riggedfigure.glb"
SCRATCH = os.environ.get("MODEL_FIXTURES_DIR")


def measure(blob: bytes) -> dict:
    report = glb_inspect.inspect_bytes(blob)
    res = bone_map.map_result(report.gltf, report.positions())
    assert not res.missing, res.missing
    return glb_inspect.normalization(report, res.bones)


def test_good_model_counts_and_bind_positions() -> None:
    report = glb_inspect.inspect_bytes(glbmaker.humanoid())
    assert report.counts == {"triangles": 1, "joints": 17, "skins": 1, "textures": 0, "max_texture_px": 0}
    assert report.has_skin and report.max_weight_error == 0.0
    hips = report.skin_nodes[0]
    assert report.position(hips) == pytest.approx((0, 1.0, 0))
    assert report.position(report.skin_nodes[-1])[1] == pytest.approx(0.08)  # a foot: local offsets add up through the parents


@pytest.mark.parametrize("blob", [b"", b"glTF", b"NOTG" + b"\0" * 40, glbmaker.humanoid()[:60],
                                  struct.pack("<4sII", b"glTF", 1, 20) + b"\0" * 8])
def test_not_a_glb_is_refused(blob: bytes) -> None:
    with pytest.raises(glb_inspect.GlbError):
        glb_inspect.inspect_bytes(blob)


def test_broken_json_chunk_is_refused() -> None:
    body = b'{"asset": '
    chunk = struct.pack("<II", len(body) + 2, glb_inspect.JSON_CHUNK) + body + b"  "
    blob = struct.pack("<4sII", b"glTF", 2, 12 + len(chunk)) + chunk
    with pytest.raises(glb_inspect.GlbError):
        glb_inspect.inspect_bytes(blob)


def test_external_buffer_uri_is_refused_and_no_file_is_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "evil.glb"
    path.write_bytes(glbmaker.humanoid(buffer_uri="../../../../etc/hostname"))
    opened: list[str] = []
    real_read = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: (opened.append(str(self)), real_read(self))[1])
    with pytest.raises(glb_inspect.GlbError, match="outside itself"):
        glb_inspect.inspect(path)
    assert opened == [str(path)]  # the model file only; nothing the model pointed at


def test_external_image_uri_is_refused() -> None:
    with pytest.raises(glb_inspect.GlbError, match="outside itself"):
        glb_inspect.inspect_bytes(glbmaker.humanoid(image_uri="http://example.com/a.png"))


def test_data_uri_image_is_allowed() -> None:
    glb_inspect.inspect_bytes(glbmaker.humanoid(image_uri="data:image/png;base64,iVBORw0KGgo="))


def test_draco_and_other_decoders_are_named() -> None:
    with pytest.raises(glb_inspect.GlbError, match="Draco"):
        glb_inspect.inspect_bytes(glbmaker.humanoid(extra={"extensionsRequired": ["KHR_draco_mesh_compression"]}))
    with pytest.raises(glb_inspect.GlbError, match="meshopt"):
        glb_inspect.inspect_bytes(glbmaker.humanoid(extra={"extensionsRequired": ["EXT_meshopt_compression"]}))
    with pytest.raises(glb_inspect.GlbError, match="FOO_unknown"):
        glb_inspect.inspect_bytes(glbmaker.humanoid(extra={"extensionsRequired": ["FOO_unknown"]}))
    glb_inspect.inspect_bytes(glbmaker.humanoid(extra={"extensionsRequired": ["KHR_materials_unlit"]}))


def test_model_without_skin_reports_none() -> None:
    report = glb_inspect.inspect_bytes(glbmaker.humanoid(skin=False))
    assert not report.has_skin and report.counts["joints"] == 0


def test_skin_without_inverse_bind_matrices_is_refused() -> None:
    with pytest.raises(glb_inspect.GlbError, match="inverse bind"):
        glb_inspect.inspect_bytes(glbmaker.humanoid(ibm=False))


def test_skinned_primitive_needs_joints_and_weights() -> None:
    with pytest.raises(glb_inspect.GlbError, match="JOINTS_0 and WEIGHTS_0"):
        glb_inspect.inspect_bytes(glbmaker.humanoid(joints_attr=False))


def test_joint_index_out_of_range_and_non_finite_weights_are_refused() -> None:
    with pytest.raises(glb_inspect.GlbError, match="not valid"):
        glb_inspect.inspect_bytes(glbmaker.humanoid(joint_index=200))
    with pytest.raises(glb_inspect.GlbError, match="not valid"):
        glb_inspect.inspect_bytes(glbmaker.humanoid(weights=[float("nan"), 0, 0, 0]))


def test_weight_sum_error_is_recorded_not_rejected() -> None:
    report = glb_inspect.inspect_bytes(glbmaker.humanoid(weights=[0.5, 0.25, 0.0, 0.0]))  # the loader normalizes these
    assert report.max_weight_error == pytest.approx(0.25)


def test_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    blob = glbmaker.humanoid()
    monkeypatch.setattr(glb_inspect, "MAX_TRIANGLES", 0)
    with pytest.raises(glb_inspect.GlbError, match="triangles"):
        glb_inspect.inspect_bytes(blob)
    monkeypatch.setattr(glb_inspect, "MAX_TRIANGLES", 300_000)
    monkeypatch.setattr(glb_inspect, "MAX_JOINTS", 5)
    with pytest.raises(glb_inspect.GlbError, match="joints"):
        glb_inspect.inspect_bytes(blob)
    monkeypatch.setattr(glb_inspect, "MAX_JOINTS", 512)
    monkeypatch.setattr(glb_inspect, "MAX_TEXTURES", 1)
    with pytest.raises(glb_inspect.GlbError, match="textures"):
        glb_inspect.inspect_bytes(glbmaker.humanoid(images=[glbmaker.png_header(8, 8)] * 2))


def test_texture_size_limit_and_measure() -> None:
    report = glb_inspect.inspect_bytes(glbmaker.humanoid(images=[glbmaker.png_header(2048, 512)]))
    assert report.counts["max_texture_px"] == 2048
    with pytest.raises(glb_inspect.GlbError, match="8192 pixels"):
        glb_inspect.inspect_bytes(glbmaker.humanoid(images=[glbmaker.png_header(8192, 8)]))


def test_image_size_png_jpeg_webp() -> None:
    assert glb_inspect.image_size(glbmaker.png_header(640, 480)) == (640, 480)
    jpeg = b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"\0" * 14 + b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 300, 200) + b"\0" * 10
    assert glb_inspect.image_size(jpeg) == (200, 300)
    vp8x = b"RIFF" + b"\0" * 4 + b"WEBP" + b"VP8X" + b"\0" * 8 + (99).to_bytes(3, "little") + (49).to_bytes(3, "little")
    assert glb_inspect.image_size(vp8x) == (100, 50)
    assert glb_inspect.image_size(b"nothing") is None


def test_node_loop_and_bad_children_are_refused() -> None:
    blob = glbmaker.humanoid(extra={"nodes": [{"children": [1]}, {"children": [0]}], "skins": [], "meshes": []})
    with pytest.raises(glb_inspect.GlbError):
        glb_inspect.inspect_bytes(blob)


# ---- normalization from world-space bind positions
def test_y_up_facing_z_metres_is_identity() -> None:
    norm = measure(glbmaker.humanoid())
    assert norm["up_fix"] == [0.0, 0.0, 0.0, 1.0] and norm["scale_to_m"] == 1.0
    assert norm["height_m"] == pytest.approx(1.7 * 1.0 + 0.0, abs=0.2)
    assert norm["leg_length_m"] == pytest.approx(0.87, abs=0.01)
    assert norm["rest_class"] == "T"


def test_z_up_model_gets_a_quarter_turn_about_x() -> None:
    norm = measure(glbmaker.humanoid(up="z"))
    assert norm["up_fix"] == pytest.approx([-0.707107, 0, 0, 0.707107], abs=1e-5)


def test_model_facing_minus_z_gets_a_half_turn_about_y() -> None:
    assert measure(glbmaker.humanoid(face="-z"))["up_fix"] == [0.0, 1.0, 0.0, 0.0]


def test_centimetre_model_scales_to_metres() -> None:
    norm = measure(glbmaker.humanoid(unit=100.0))
    assert norm["scale_to_m"] == 0.01 and norm["leg_length_m"] == pytest.approx(0.87, abs=0.01)


def test_root_matrix_is_applied_before_measuring() -> None:
    # a Z_UP root as in CesiumMan: its matrix turns a Z-up skeleton into Y up, so no further fix is needed
    z_up_to_y = [1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1]
    assert measure(glbmaker.humanoid(up="z", root_matrix=z_up_to_y))["up_fix"] == [0.0, 0.0, 0.0, 1.0]


def test_a_pose_is_classed_a() -> None:
    report = glb_inspect.inspect_bytes(glbmaker.humanoid())  # arms hang 45 degrees down in the first check
    res = bone_map.map_result(report.gltf, report.positions())
    fixed = {n: report.position(i) for n, i in res.bones.items()}
    for side, sign in (("left", 1), ("right", -1)):
        base = fixed[f"{side}UpperArm"]
        fixed[f"{side}LowerArm"] = (base[0] + sign * 0.3, base[1] - 0.3, base[2])
    assert glb_inspect._rest_class(fixed) == "A"
    assert glb_inspect._rest_class({**fixed, "leftLowerArm": (0.2, 0.0, 0.0), "rightLowerArm": (-0.2, 0.0, 0.0),
                                    "leftUpperArm": (0.2, 1.0, 0.0), "rightUpperArm": (-0.2, 1.0, 0.0)}) == "other"


def test_real_rigged_figure_measures() -> None:
    report = glb_inspect.inspect(REAL)
    assert report.counts["joints"] == 19 and report.counts["triangles"] == 256
    norm = measure(REAL.read_bytes())
    assert norm["up_fix"] == [0.0, 0.0, 0.0, 1.0] and norm["height_m"] == pytest.approx(1.45, abs=0.05)


def test_symlink_and_missing_file_are_refused(tmp_path: Path) -> None:
    target = tmp_path / "real.glb"
    target.write_bytes(glbmaker.humanoid())
    link = tmp_path / "link.glb"
    link.symlink_to(target)
    for bad in (link, tmp_path / "missing.glb", tmp_path):
        with pytest.raises(glb_inspect.GlbError):
            glb_inspect.inspect(bad)


@pytest.mark.skipif(not SCRATCH, reason="MODEL_FIXTURES_DIR not set")
def test_cesiumman_gets_identity_up_fix() -> None:
    norm = measure((Path(SCRATCH) / "khronos-cesiumman" / "CesiumMan.glb").read_bytes())  # its root matrix already makes it Y up
    assert norm["up_fix"] == [0.0, 0.0, 0.0, 1.0] and norm["scale_to_m"] == 1.0


@pytest.mark.skipif(not SCRATCH, reason="MODEL_FIXTURES_DIR not set")
def test_robot_expressive_weight_error_is_recorded_not_rejected() -> None:
    report = glb_inspect.inspect(Path(SCRATCH) / "quaternius-robotexpressive" / "RobotExpressive.glb")
    assert report.max_weight_error > 0.5


# ---- TICKET-243: height_m from the legs when the mesh box is not a human stature
def _with_box_top(top: float) -> dict:
    report = glb_inspect.inspect_bytes(glbmaker.humanoid())
    res = bone_map.map_result(report.gltf, report.positions())
    for acc in report.gltf["accessors"]:
        if acc.get("type") == "VEC3" and acc.get("max") and acc["max"][1] > 1.0:
            acc["max"][1] = top
    return glb_inspect.normalization(report, res.bones)


def test_normal_mesh_box_keeps_its_height() -> None:
    norm = _with_box_top(2.0)
    assert norm["height_m"] == pytest.approx(2.0, abs=0.01)


def test_oversized_mesh_box_reads_the_leg_implied_height() -> None:
    norm = _with_box_top(2.68)  # a chibi head: the box passes the skeleton check but is 3.1 times the legs
    assert norm["height_m"] == pytest.approx(norm["leg_length_m"] * glb_inspect.HEIGHT_PER_LEG, abs=0.001)


@pytest.mark.skipif(not SCRATCH, reason="MODEL_FIXTURES_DIR not set")
def test_kenney_height_is_within_ten_percent_of_its_leg_implied_height() -> None:
    glb = Path(SCRATCH or "") / "converted" / "kenney-characterMedium.glb"  # convert.py output, kept local
    if not glb.is_file():
        pytest.skip("no local converted Kenney GLB")
    norm = measure(glb.read_bytes())
    implied = norm["leg_length_m"] * glb_inspect.HEIGHT_PER_LEG
    assert abs(norm["height_m"] - implied) <= 0.10 * implied and norm["height_m"] < 3.0


_MANNEQUIN = "quaternius-ual2/extracted/Universal Animation Library 2 [Standard]/Female Mannequin/Unreal-Godot/Mannequin_F.glb"


@pytest.mark.skipif(not SCRATCH, reason="MODEL_FIXTURES_DIR not set")
@pytest.mark.parametrize("rel,expected", [("threejs-soldier/Soldier.glb", 1.83), (_MANNEQUIN, 1.806)])
def test_full_human_models_keep_their_measured_height(rel: str, expected: float) -> None:
    norm = measure((Path(SCRATCH or "") / rel).read_bytes())
    assert norm["height_m"] == pytest.approx(expected, abs=0.005)
