"""Read and check a rigged GLB or VRM with the standard library only (docs/specs/model-import.md).

`inspect(path)` parses the container, refuses anything the browser loader should not be handed (external files, decoders
it does not ship, no skeleton, over the limits) and measures the bind pose. "Bind" means the node pose of the file after
every node transform, which is what three.js shows after `updateMatrixWorld`.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import struct
from typing import Any

MAGIC = b"glTF"
JSON_CHUNK, BIN_CHUNK = 0x4E4F534A, 0x004E4942
MAX_TRIANGLES, MAX_JOINTS, MAX_TEXTURES, MAX_TEXTURE_PX = 300_000, 512, 32, 4096
# HARDENING 3 (TICKET-341): the document is read before any count is trusted, so nodes, meshes, vertices and the
# depth of the node tree are capped before anything is built from them.
MAX_NODES, MAX_MESHES, MAX_VERTICES, MAX_NODE_DEPTH = 10_000, 2_000, 600_000, 512
# The extensions GLTFLoader r170 reads without a decoder. Draco, meshopt and KTX2 need decoders the app does not ship.
SUPPORTED_REQUIRED = frozenset({
    "KHR_materials_unlit", "KHR_materials_emissive_strength", "KHR_materials_clearcoat", "KHR_materials_ior",
    "KHR_materials_specular", "KHR_materials_sheen", "KHR_materials_transmission", "KHR_materials_volume",
    "KHR_materials_iridescence", "KHR_materials_anisotropy", "KHR_materials_dispersion", "KHR_materials_variants",
    "KHR_materials_pbrSpecularGlossiness", "KHR_texture_transform", "KHR_mesh_quantization", "KHR_lights_punctual",
    "EXT_texture_webp", "EXT_texture_avif",
})
DECODERS = {"KHR_draco_mesh_compression": "Draco", "EXT_meshopt_compression": "meshopt", "KHR_texture_basisu": "KTX2"}
COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
NORM_MAX = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

MSG_NOT_GLB = "This file is not a valid GLB or VRM model. Export it again from your 3D tool, then choose the new file."
MSG_EXTERNAL = "This model points at files outside itself. Export it with everything embedded."


class GlbError(ValueError):
    """The file is refused; the message is plain words for the person who uploaded it."""


@dataclass
class Report:
    gltf: dict[str, Any]
    blob: bytes
    counts: dict[str, int]
    max_weight_error: float
    skin_nodes: list[int]
    parent: list[int | None]
    world: list[list[float]]  # column-major 4x4 per node, bind pose after every node transform
    names: list[str] = field(default_factory=list)

    @property
    def has_skin(self) -> bool:
        return bool(self.skin_nodes)

    def position(self, node: int) -> tuple[float, float, float]:
        m = self.world[node]
        return (m[12], m[13], m[14])

    def positions(self) -> dict[int, tuple[float, float, float]]:
        return {n: self.position(n) for n in range(len(self.world))}


# ---------------------------------------------------------------- matrices (column-major, as glTF)
IDENTITY = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def mat_mul(a: list[float], b: list[float]) -> list[float]:
    return [sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4)) for c in range(4) for r in range(4)]


def mat_from_trs(t: list[float], q: list[float], s: list[float]) -> list[float]:
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    r = [
        1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w),
        2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w),
        2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y),
    ]
    out = [r[0] * s[0], r[1] * s[0], r[2] * s[0], 0, r[3] * s[1], r[4] * s[1], r[5] * s[1], 0,
           r[6] * s[2], r[7] * s[2], r[8] * s[2], 0, t[0], t[1], t[2], 1.0]
    return out


def node_local(node: dict[str, Any]) -> list[float]:
    if "matrix" in node:
        m = node["matrix"]
        if len(m) != 16:
            raise GlbError(MSG_NOT_GLB)
        return [float(v) for v in m]
    return mat_from_trs(node.get("translation", [0, 0, 0]), node.get("rotation", [0, 0, 0, 1]), node.get("scale", [1, 1, 1]))


# ---------------------------------------------------------------- container
def read_container(data: bytes) -> tuple[dict[str, Any], bytes]:
    """The JSON document and the embedded binary chunk of a GLB."""
    if len(data) < 20 or data[:4] != MAGIC:
        raise GlbError(MSG_NOT_GLB)
    version, total = struct.unpack_from("<II", data, 4)
    if version != 2 or total > len(data):
        raise GlbError(MSG_NOT_GLB)
    doc, blob, pos = None, b"", 12
    while pos + 8 <= total:
        size, kind = struct.unpack_from("<II", data, pos)
        body = data[pos + 8:pos + 8 + size]
        if len(body) != size:
            raise GlbError(MSG_NOT_GLB)
        if kind == JSON_CHUNK and doc is None:
            try:
                doc = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise GlbError(MSG_NOT_GLB) from exc
        elif kind == BIN_CHUNK and not blob:
            blob = bytes(body)
        pos += 8 + size + (-size % 4)
    if not isinstance(doc, dict):
        raise GlbError(MSG_NOT_GLB)
    return doc, blob


def _check_uris(doc: dict[str, Any]) -> list[bytes | None]:
    """Buffers by index (None for the embedded chunk); any URI that is not an inline data URI is refused."""
    buffers: list[bytes | None] = []
    for item in doc.get("buffers") or []:
        uri = item.get("uri") if isinstance(item, dict) else None
        if uri is None:
            buffers.append(None)
        elif isinstance(uri, str) and uri.startswith("data:") and ";base64," in uri:
            try:
                buffers.append(base64.b64decode(uri.split(";base64,", 1)[1], validate=True))
            except ValueError as exc:
                raise GlbError(MSG_NOT_GLB) from exc
        else:
            raise GlbError(MSG_EXTERNAL)
    for item in doc.get("images") or []:
        uri = item.get("uri") if isinstance(item, dict) else None
        if uri is not None and not (isinstance(uri, str) and uri.startswith("data:")):
            raise GlbError(MSG_EXTERNAL)
    return buffers


def _check_extensions(doc: dict[str, Any]) -> None:
    for ext in doc.get("extensionsRequired") or []:
        if ext in DECODERS:
            raise GlbError(f"This model is compressed with {DECODERS[ext]}, which Simon cannot open. Export it without compression, then choose the new file.")
        if ext not in SUPPORTED_REQUIRED:
            raise GlbError(f"This model needs the extension {ext}, which Simon does not support. Export it without that extension, then choose the new file.")


# ---------------------------------------------------------------- accessors
def _view_bytes(doc: dict[str, Any], blob: bytes, buffers: list[bytes | None], view_i: int) -> tuple[bytes, int]:
    views = doc.get("bufferViews") or []
    if not isinstance(view_i, int) or not 0 <= view_i < len(views):
        raise GlbError(MSG_NOT_GLB)
    view = views[view_i]
    bi = view.get("buffer", 0)
    if not isinstance(bi, int) or not 0 <= bi < len(buffers):
        raise GlbError(MSG_NOT_GLB)
    data = blob if buffers[bi] is None else buffers[bi]
    start = view.get("byteOffset", 0)
    length = view.get("byteLength", 0)
    if start < 0 or length < 0 or start + length > len(data):
        raise GlbError(MSG_NOT_GLB)
    return data[start:start + length], view.get("byteStride", 0)


def read_accessor(doc: dict[str, Any], blob: bytes, buffers: list[bytes | None], index: int) -> list[tuple[float, ...]]:
    """The elements of accessor `index` as tuples (normalized integers are scaled to 0..1 or -1..1)."""
    accessors = doc.get("accessors") or []
    if not isinstance(index, int) or not 0 <= index < len(accessors):
        raise GlbError(MSG_NOT_GLB)
    acc = accessors[index]
    fmt = COMPONENT.get(acc.get("componentType"))
    width = WIDTH.get(acc.get("type"))
    if fmt is None or width is None or "sparse" in acc:
        raise GlbError(MSG_NOT_GLB)
    count = acc.get("count", 0)
    if "bufferView" not in acc:
        return [(0.0,) * width] * count
    data, stride = _view_bytes(doc, blob, buffers, acc["bufferView"])
    code, size = fmt
    item = size * width
    stride = stride or item
    base = acc.get("byteOffset", 0)
    if count < 0 or (count and base + (count - 1) * stride + item > len(data)):
        raise GlbError(MSG_NOT_GLB)
    scale = NORM_MAX.get(acc.get("componentType")) if acc.get("normalized") else None
    out: list[tuple[float, ...]] = []
    unpack = struct.Struct("<" + code * width).unpack_from
    for i in range(count):
        row = unpack(data, base + i * stride)
        out.append(tuple(max(v / scale, -1.0) for v in row) if scale else row)
    return out


# ---------------------------------------------------------------- images
def image_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) of a PNG, JPEG or WebP, or None when the header is not understood."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        pos = 2
        while pos + 9 < len(data):
            if data[pos] != 0xFF:
                pos += 1
                continue
            marker = data[pos + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                pos += 2
                continue
            seg = struct.unpack(">H", data[pos + 2:pos + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[pos + 5:pos + 9])
                return (w, h)
            pos += 2 + seg
        return None
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        kind = data[12:16]
        if kind == b"VP8X":
            return (1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little"))
        if kind == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        if kind == b"VP8 ":
            w, h = struct.unpack("<HH", data[26:30])
            return (w & 0x3FFF, h & 0x3FFF)
    return None


def _max_texture_px(doc: dict[str, Any], blob: bytes, buffers: list[bytes | None]) -> int:
    biggest = 0
    for img in doc.get("images") or []:
        data = None
        if "bufferView" in img:
            data = _view_bytes(doc, blob, buffers, img["bufferView"])[0]
        elif str(img.get("uri", "")).startswith("data:"):
            try:
                data = base64.b64decode(img["uri"].split(",", 1)[1])
            except ValueError:
                data = None
        size = image_size(data) if data else None
        biggest = max(biggest, max(size) if size else 0)
    return biggest


# ---------------------------------------------------------------- skin and weights
def _primitive_stats(doc: dict[str, Any], blob: bytes, buffers: list[bytes | None], skinned: set[int]) -> tuple[int, float]:
    """(triangles, worst weight-sum error) over the meshes; structural checks on joints and weights raise GlbError."""
    triangles, worst, vertices = 0, 0.0, 0
    accessors = doc.get("accessors") or []
    for mi, mesh in enumerate(doc.get("meshes") or []):
        for prim in mesh.get("primitives") or []:
            attrs = prim.get("attributes") or {}
            if isinstance(attrs.get("POSITION"), int) and 0 <= attrs["POSITION"] < len(accessors):
                vertices += accessors[attrs["POSITION"]].get("count", 0)
                if vertices > MAX_VERTICES:
                    raise GlbError(f"This model has more than {MAX_VERTICES} vertices. The limit is {MAX_VERTICES}. Reduce it in your 3D tool, then choose the new file.")
            if prim.get("mode", 4) == 4:
                if "indices" in prim and 0 <= prim["indices"] < len(accessors):
                    triangles += accessors[prim["indices"]].get("count", 0) // 3
                elif "POSITION" in attrs and 0 <= attrs["POSITION"] < len(accessors):
                    triangles += accessors[attrs["POSITION"]].get("count", 0) // 3
            if mi not in skinned:
                continue
            if "JOINTS_0" not in attrs or "WEIGHTS_0" not in attrs:
                raise GlbError("A skinned part of this model has no joint weights (JOINTS_0 and WEIGHTS_0). Export it with its skin weights, then choose the new file.")
            joints = read_accessor(doc, blob, buffers, attrs["JOINTS_0"])
            weights = read_accessor(doc, blob, buffers, attrs["WEIGHTS_0"])
            if len(joints) != len(weights):
                raise GlbError(MSG_NOT_GLB)
            skin_size = max((len(doc["skins"][s].get("joints") or []) for s in skinned_skins(doc, mi)), default=0)
            for jrow, wrow in zip(joints, weights):
                if not all(math.isfinite(v) for v in wrow) or max(jrow) >= max(skin_size, 1):
                    raise GlbError("The joint weights of this model are not valid. Export it again with its skin weights, then choose the new file.")
                worst = max(worst, abs(sum(wrow) - 1.0))
    return triangles, worst


def skinned_skins(doc: dict[str, Any], mesh_index: int) -> list[int]:
    return sorted({n["skin"] for n in doc.get("nodes") or [] if n.get("mesh") == mesh_index and isinstance(n.get("skin"), int)
                   and 0 <= n["skin"] < len(doc.get("skins") or [])})


def _world_poses(doc: dict[str, Any]) -> tuple[list[int | None], list[list[float]]]:
    nodes = doc.get("nodes") or []
    parent: list[int | None] = [None] * len(nodes)
    for i, node in enumerate(nodes):
        for child in node.get("children") or []:
            if not isinstance(child, int) or not 0 <= child < len(nodes) or parent[child] is not None or child == i:
                raise GlbError(MSG_NOT_GLB)
            parent[child] = i
    world: list[list[float] | None] = [None] * len(nodes)

    def solve(i: int, depth: int = 0) -> list[float]:
        if depth > min(len(nodes), MAX_NODE_DEPTH):
            raise GlbError(MSG_NOT_GLB)  # a loop in the node tree
        if world[i] is None:
            local = node_local(nodes[i])
            world[i] = local if parent[i] is None else mat_mul(solve(parent[i], depth + 1), local)
        return world[i]

    return parent, [solve(i) for i in range(len(nodes))]


def inspect_bytes(data: bytes) -> Report:
    doc, blob = read_container(data)
    buffers = _check_uris(doc)
    _check_extensions(doc)
    nodes, skins = doc.get("nodes") or [], doc.get("skins") or []
    if len(nodes) > MAX_NODES:
        raise GlbError(f"This model has {len(nodes)} nodes. The limit is {MAX_NODES}. Reduce it in your 3D tool, then choose the new file.")
    if len(doc.get("meshes") or []) > MAX_MESHES:
        raise GlbError(f"This model has {len(doc['meshes'])} meshes. The limit is {MAX_MESHES}. Reduce it in your 3D tool, then choose the new file.")
    parent, world = _world_poses(doc)
    skin_nodes: list[int] = []
    for skin in skins:
        joints = skin.get("joints") or []
        if len(joints) > MAX_JOINTS:
            raise GlbError(f"This model has {len(joints)} joints in one skeleton. The limit is {MAX_JOINTS}. Reduce it in your 3D tool, then choose the new file.")
        if not all(isinstance(j, int) and 0 <= j < len(nodes) for j in joints):
            raise GlbError(MSG_NOT_GLB)
        if joints and skin.get("inverseBindMatrices") is None:
            raise GlbError("This model has no inverse bind matrices, so it cannot be posed. Export it with its skin, then choose the new file.")
        skin_nodes.extend(j for j in joints if j not in skin_nodes)
    skinned_meshes = {n["mesh"] for n in nodes if isinstance(n.get("mesh"), int) and isinstance(n.get("skin"), int)}
    triangles, worst = _primitive_stats(doc, blob, buffers, skinned_meshes)
    textures = len(doc.get("images") or [])
    biggest = _max_texture_px(doc, blob, buffers)
    if triangles > MAX_TRIANGLES:
        raise GlbError(f"This model has {triangles} triangles. The limit is {MAX_TRIANGLES}. Reduce it in your 3D tool, then choose the new file.")
    if textures > MAX_TEXTURES:
        raise GlbError(f"This model has {textures} textures. The limit is {MAX_TEXTURES}.")
    if biggest > MAX_TEXTURE_PX:
        raise GlbError(f"A texture in this model is {biggest} pixels wide. The limit is {MAX_TEXTURE_PX}.")
    counts = {"triangles": triangles, "joints": len(skin_nodes), "skins": len(skins), "textures": textures,
              "max_texture_px": biggest}
    names = [str(n.get("name", "")) for n in nodes]
    return Report(doc, blob, counts, worst, skin_nodes, parent, world, names)


def inspect(path: str | Path) -> Report:
    """Parse and check the GLB at `path`; raises GlbError with a plain message when it is refused."""
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        raise GlbError(MSG_NOT_GLB)
    return inspect_bytes(p.read_bytes())


# ---------------------------------------------------------------- normalization from the bind pose
def _sub(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _len(v: tuple[float, ...]) -> float:
    return math.sqrt(sum(c * c for c in v))


def _quat_between(a: tuple[float, ...], b: tuple[float, ...]) -> list[float]:
    """Shortest rotation taking unit vector a onto unit vector b, as [x, y, z, w]."""
    dot = sum(x * y for x, y in zip(a, b))
    if dot < -0.999999:
        axis = (0.0, 0.0, 1.0) if abs(a[0]) > 0.9 else (1.0, 0.0, 0.0)
        cross = (a[1] * axis[2] - a[2] * axis[1], a[2] * axis[0] - a[0] * axis[2], a[0] * axis[1] - a[1] * axis[0])
        n = _len(cross)
        return [cross[0] / n, cross[1] / n, cross[2] / n, 0.0]
    cross = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    q = [cross[0], cross[1], cross[2], 1.0 + dot]
    n = math.sqrt(sum(c * c for c in q))
    return [c / n for c in q]


def _q_mul(a: list[float], b: list[float]) -> list[float]:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz]


def _q_rot(q: list[float], v: tuple[float, ...]) -> tuple[float, float, float]:
    x, y, z, w = q
    t = (2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0]))
    return (v[0] + w * t[0] + y * t[2] - z * t[1], v[1] + w * t[1] + z * t[0] - x * t[2], v[2] + w * t[2] + x * t[1] - y * t[0])


def _cardinal(v: tuple[float, ...]) -> tuple[float, float, float]:
    """The signed axis unit vector closest to v."""
    i = max(range(3), key=lambda k: abs(v[k]))
    out = [0.0, 0.0, 0.0]
    out[i] = 1.0 if v[i] >= 0 else -1.0
    return (out[0], out[1], out[2])


HEIGHT_PER_BONE_SPAN = 1.18  # stature over head-joint-to-sole, measured on the real models (spec "Normalization")
HEIGHT_PER_LEG = 2.15  # stature over thigh plus shank: Mannequin_F 2.18, Seed-san 2.16, Soldier 2.08, Xbot 2.04
HUMAN_HEIGHT_PER_LEG = (1.8, 3.0)  # measured stature over leg a person can have (real models run 2.0 to 2.8)


def normalization(report: Report, bones: dict[str, int]) -> dict[str, Any]:
    """scale_to_m, up_fix, height_m, leg_length_m and rest_class, all from world-space bind positions.

    `up_fix` is a whole number of quarter turns: it takes the cardinal axis nearest the hips-to-head direction onto +Y,
    then turns about +Y so the left leg is at +X (a model facing +Z, as Simon's pose frame expects). A model that is
    already Y up and facing +Z, CesiumMan included, gets the identity. A VRM 0.x model faces -Z and gets the half turn
    from the same rule. `scale_to_m` is a power of ten that brings the skeleton to human size (1.0 for every model that
    is already in metres). `height_m` is the skinned mesh box, cross-checked against the skeleton; when that box is
    not in a human ratio to the legs (a chibi head, a prop), it is the stature the legs imply.
    """
    pos = {name: report.position(node) for name, node in bones.items()}
    q_up = _quat_between(_cardinal(_sub(pos["head"], pos["hips"])), (0.0, 1.0, 0.0))
    side = _q_rot(q_up, _sub(pos["leftUpperLeg"], pos["rightUpperLeg"]))
    flat = _cardinal((side[0], 0.0, side[2]))
    yaw = {(1.0, 0.0): 0.0, (-1.0, 0.0): math.pi, (0.0, 1.0): math.pi / 2, (0.0, -1.0): -math.pi / 2}[(flat[0], flat[2])]
    up_fix = _q_mul([0.0, math.sin(yaw / 2), 0.0, math.cos(yaw / 2)], q_up)
    up_fix = [0.0 if abs(c) < 1e-9 else round(c, 6) for c in up_fix]
    if up_fix[3] < 0 or (up_fix[3] == 0 and next(c for c in up_fix if c) < 0):
        up_fix = [-c for c in up_fix]
    fixed = {n: _q_rot(up_fix, p) for n, p in pos.items()}
    span = fixed["head"][1] - min(fixed[f"{s}{p}"][1] for s in ("left", "right") for p in ("Foot",))
    estimate = span * HEIGHT_PER_BONE_SPAN
    scale = 1.0
    while estimate * scale < 0.3 and scale < 1e4:
        scale *= 10
    while estimate * scale >= 3.5 and scale > 1e-4:
        scale /= 10
    height = estimate
    for corners in (mesh_corners(report), mesh_corners(report, raw=True)):  # the box as three.js places it, then the raw box
        ys = [_q_rot(up_fix, c)[1] for c in corners]
        if ys and 1.0 <= (max(ys) - min(ys)) / (estimate or 1.0) <= 1.45:
            height = max(ys) - min(ys)
            break
    leg = max(_len(_sub(fixed[f"{s}UpperLeg"], fixed[f"{s}LowerLeg"])) + _len(_sub(fixed[f"{s}LowerLeg"], fixed[f"{s}Foot"]))
              for s in ("left", "right"))
    if leg and not HUMAN_HEIGHT_PER_LEG[0] <= height / leg <= HUMAN_HEIGHT_PER_LEG[1]:
        height = leg * HEIGHT_PER_LEG
    return {"scale_to_m": scale, "up_fix": up_fix, "height_m": round(height * scale, 4),
            "leg_length_m": round(leg * scale, 4),
            "rest_class": _rest_class(fixed)}


def mesh_corners(report: Report, raw: bool = False) -> list[tuple[float, float, float]]:
    """The eight bounding-box corners of every skinned mesh (POSITION min and max), in world space or `raw`."""
    doc, out = report.gltf, []
    accessors = doc.get("accessors") or []
    for i, node in enumerate(doc.get("nodes") or []):
        if not (isinstance(node.get("mesh"), int) and isinstance(node.get("skin"), int)):
            continue
        for prim in doc["meshes"][node["mesh"]].get("primitives") or []:
            acc = accessors[prim["attributes"]["POSITION"]] if "POSITION" in (prim.get("attributes") or {}) else {}
            lo, hi = acc.get("min"), acc.get("max")
            if not (isinstance(lo, list) and isinstance(hi, list) and len(lo) == len(hi) == 3):
                continue
            m = IDENTITY if raw else report.world[i]
            for cx in (lo[0], hi[0]):
                for cy in (lo[1], hi[1]):
                    for cz in (lo[2], hi[2]):
                        out.append((m[0] * cx + m[4] * cy + m[8] * cz + m[12], m[1] * cx + m[5] * cy + m[9] * cz + m[13],
                                    m[2] * cx + m[6] * cy + m[10] * cz + m[14]))
    return out


def _rest_class(fixed: dict[str, tuple[float, float, float]]) -> str:
    """T when the upper arms lie within 25 degrees of horizontal, A when 25 to 70 degrees below it, else other."""
    angles = []
    for side in ("left", "right"):
        arm = _sub(fixed[f"{side}LowerArm"], fixed[f"{side}UpperArm"])
        n = _len(arm) or 1.0
        angles.append(math.degrees(math.asin(max(-1.0, min(1.0, -arm[1] / n)))))  # degrees below horizontal
    mean = sum(angles) / 2
    if abs(mean) <= 25:
        return "T"
    return "A" if 25 < mean <= 70 else "other"
