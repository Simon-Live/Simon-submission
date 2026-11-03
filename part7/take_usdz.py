"""A USDZ of the same rigged take, for Quick Look on iPhone and iPad (docs/specs/take-ar.md, TICKET-282).

One `.usda` layer inside an uncompressed, 64-byte aligned USDZ package. Each figure is a UsdSkel `SkelRoot` with a
`Skeleton` of the 17 joints, a `SkelAnimation` (rotations per kept frame, hips translations) and a skinned `Mesh` with a
flat-colour `UsdPreviewSurface`. No image file goes in the package. Units are metres, Y up, as in the GLB.
"""

from __future__ import annotations

import struct
import zlib
from typing import Callable

from part7 import take_glb, take_rig as rig

FPS = 24
LAYER = "take.usda"
ALIGN = 64


def _f(x: float) -> str:
    return f"{x:.6g}"


def _vec(v: tuple[float, ...]) -> str:
    return "(" + ", ".join(_f(c) for c in v) + ")"


def _matrix(t: rig.Vec) -> str:
    return f"((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), ({_f(t[0])}, {_f(t[1])}, {_f(t[2])}, 1))"


def _joint_paths() -> list[str]:
    paths: list[str] = []
    for i, name in enumerate(rig.NAMES):
        paths.append(name if rig.PARENT[i] < 0 else f"{paths[rig.PARENT[i]]}/{name}")
    return paths


def _quat(q: rig.Quat) -> str:
    return f"({_f(q[3])}, {_f(q[0])}, {_f(q[1])}, {_f(q[2])})"  # USD writes the real part first


def _samples(fig: rig.Figure, render: Callable[[int], str]) -> str:
    return "\n".join(f"            {_f(t * FPS)}: {render(k)}," for k, t in enumerate(fig.times))


def _figure(fig: rig.Figure, key: str, rgba: tuple[float, float, float, float]) -> str:
    paths = _joint_paths()
    joints = "[" + ", ".join(f'"{p}"' for p in paths) + "]"
    rest = "[" + ", ".join(_matrix(fig.local_offset(i)) for i in range(len(rig.NAMES))) + "]"
    bind = "[" + ", ".join(_matrix(h) for h in fig.bone_head) + "]"
    rot = _samples(fig, lambda k: "[" + ", ".join(_quat(q) for q in fig.rotations[k]) + "]")
    # the hips take their position from the animation, the other joints keep their bind offset
    trans = _samples(fig, lambda k: "[" + ", ".join(_vec(fig.hips[k] if i == 0 else fig.local_offset(i))
                                                    for i in range(len(rig.NAMES))) + "]")
    scales = "[" + ", ".join("(1, 1, 1)" for _ in rig.NAMES) + "]"
    idx = ", ".join(f"{b0}, {b1}, 0, 0" for b0, b1 in fig.bones)
    wts = ", ".join(f"{_f(w0)}, {_f(w1)}, 0, 0" for w0, w1 in fig.weights)
    points = ", ".join(_vec(p) for p in fig.positions)
    counts = ", ".join("3" for _ in range(len(fig.faces) // 3))
    ids = ", ".join(str(i) for i in fig.faces)
    opacity = rgba[3]
    return f'''    def SkelRoot "{key}"
    {{
        def Skeleton "Skel" (prepend apiSchemas = ["SkelBindingAPI"])
        {{
            uniform token[] joints = {joints}
            uniform matrix4d[] bindTransforms = {bind}
            uniform matrix4d[] restTransforms = {rest}
            rel skel:animationSource = </Take/{key}/Skel/Anim>

            def SkelAnimation "Anim"
            {{
                uniform token[] joints = {joints}
                quatf[] rotations.timeSamples = {{
{rot}
                }}
                half3[] scales = {scales}
                float3[] translations.timeSamples = {{
{trans}
                }}
            }}
        }}

        def Mesh "Body" (prepend apiSchemas = ["MaterialBindingAPI", "SkelBindingAPI"])
        {{
            int[] faceVertexCounts = [{counts}]
            int[] faceVertexIndices = [{ids}]
            point3f[] points = [{points}]
            uniform token subdivisionScheme = "none"
            matrix4d primvars:skel:geomBindTransform = ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))
            int[] primvars:skel:jointIndices = [{idx}] (
                elementSize = 4
                interpolation = "vertex"
            )
            float[] primvars:skel:jointWeights = [{wts}] (
                elementSize = 4
                interpolation = "vertex"
            )
            rel skel:skeleton = </Take/{key}/Skel>
            rel material:binding = </Take/{key}/Material>
            uniform bool doubleSided = 1
        }}

        def Material "Material"
        {{
            token outputs:surface.connect = </Take/{key}/Material/Surface.outputs:surface>
            def Shader "Surface"
            {{
                uniform token info:id = "UsdPreviewSurface"
                color3f inputs:diffuseColor = ({_f(rgba[0])}, {_f(rgba[1])}, {_f(rgba[2])})
                float inputs:opacity = {_f(opacity)}
                float inputs:roughness = 0.85
                float inputs:metallic = 0
                token outputs:surface
            }}
        }}
    }}
'''


def build_usda(figures: list[rig.Figure]) -> str:
    if not figures or len(figures) > 2:
        raise rig.RigError("A take file holds one or two figures.")
    end = max(f.duration_s for f in figures) * FPS
    body = _figure(figures[0], "Person", take_glb.BODY_RGBA)
    if len(figures) == 2:
        body += _figure(figures[1], "Ghost", take_glb.GHOST_RGBA)
    return f'''#usda 1.0
(
    defaultPrim = "Take"
    metersPerUnit = 1
    upAxis = "Y"
    timeCodesPerSecond = {FPS}
    startTimeCode = 0
    endTimeCode = {_f(end)}
    doc = "{take_glb.LICENCE}"
)

def Xform "Take"
{{
{body}}}
'''


def pack_usdz(layer_name: str, layer: bytes) -> bytes:
    """A USDZ (zip, stored, file data at a multiple of 64 bytes) holding one layer."""
    name = layer_name.encode("ascii")
    offset = 30 + len(name)
    pad = (-(offset + 4)) % ALIGN  # extra field: 2 byte id, 2 byte size, then `pad` zero bytes
    extra = struct.pack("<HH", 0x1986, pad) + b"\0" * pad
    crc = zlib.crc32(layer) & 0xFFFFFFFF
    local = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0x21, crc, len(layer), len(layer), len(name), len(extra))
    local += name + extra
    central = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, 0, 0, 0x21, crc, len(layer), len(layer),
                          len(name), 0, 0, 0, 0, 0, 0) + name
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, len(central), len(local) + len(layer), 0)
    return local + layer + central + end


def build_usdz(figures: list[rig.Figure]) -> bytes:
    return pack_usdz(LAYER, build_usda(figures).encode("utf-8"))
