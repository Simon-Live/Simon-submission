"""Unrigged mesh in, flat-shaded front view out, for `part2 autorig`. numpy and Pillow only (no GL, no torch).

    mesh = load(path)                          # .obj, or a .glb without a skin (Mesh: vertices, faces, colours)
    mesh, info = normalize(mesh, height_m=None, up=None)   # Y up, metres, soles on y = 0, centred on x and z
    turned = face_back(mesh)                   # the same mesh turned half a turn about Y
    image, cam = render_front(mesh)            # PIL image, Camera (K, to_cam, to_mesh)

Spec: docs/specs/autorig.md (AC-1 to AC-8). A GLB that already has a skin is refused, not rigged twice. Textures of a
GLB are sampled at the vertices into vertex colours; OBJ keeps `v x y z r g b` colours when present.
"""
import json
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

MAX_BYTES = 200 * 1024 * 1024
MAX_TRIANGLES = 300_000
MIN_TRIANGLES = 50
ASSUMED_HEIGHT_M = 1.7
RENDER_SIZE = 768
FOCAL_PX = 1200.0
FILL = 0.78                      # the figure's height as a share of the picture
BACKGROUND = (236, 236, 236)
DEFAULT_COLOUR = (196, 196, 204)
_COMPONENT = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2", 5125: "u4", 5126: "f4"}
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
_SUPPORTED_EXTENSIONS = {"KHR_materials_unlit", "KHR_texture_transform", "KHR_materials_emissive_strength"}


class MeshError(ValueError):
    """The input is not a usable unrigged mesh; the message is one line for the user."""


@dataclass
class Mesh:
    vertices: np.ndarray            # (n, 3) float64
    faces: np.ndarray               # (m, 3) int64
    colors: np.ndarray | None = None  # (n, 3) float in 0..1


@dataclass
class Camera:
    """A pinhole camera in front of a mesh, looking down -Z with +Y up. Camera space is OpenCV's (x right, y down,
    z forward), the space SAM 3D Body reports in."""
    K: np.ndarray
    size: int
    cx: float
    cy: float
    zcam: float

    def to_cam(self, p: np.ndarray) -> np.ndarray:
        p = np.asarray(p, dtype=float)
        return np.stack([p[..., 0] - self.cx, self.cy - p[..., 1], self.zcam - p[..., 2]], axis=-1)

    def to_mesh(self, q: np.ndarray) -> np.ndarray:
        q = np.asarray(q, dtype=float)
        return np.stack([q[..., 0] + self.cx, self.cy - q[..., 1], self.zcam - q[..., 2]], axis=-1)


# ---- loading ----------------------------------------------------------------------------------------

def load(path) -> Mesh:
    """The mesh in `path`: OBJ text or a GLB without a skin. MeshError for anything else."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError:
        raise MeshError(f"cannot read {path.name}") from None
    if not path.is_file():
        raise MeshError(f"{path.name} is not a file")
    if size == 0:
        raise MeshError(f"{path.name} is empty")
    if size > MAX_BYTES:
        raise MeshError(f"{path.name} is over {MAX_BYTES // 2**20} MB")
    data = path.read_bytes()
    if data[:4] == b"glTF":
        mesh = load_glb(data, path.name)
    elif path.suffix.lower() == ".obj":
        mesh = load_obj(data.decode("utf-8", "replace"), path.name)
    else:
        raise MeshError(f"{path.name} is neither a GLB nor an OBJ")
    return check(mesh, path.name)


def check(mesh: Mesh, name: str = "the mesh") -> Mesh:
    v = mesh.vertices
    if len(v) == 0 or len(mesh.faces) == 0:
        raise MeshError(f"{name} has no triangles")
    if not np.isfinite(v).all():
        raise MeshError(f"{name} has a vertex that is not a finite number")
    if len(mesh.faces) > MAX_TRIANGLES:
        raise MeshError(f"{name} has {len(mesh.faces)} triangles, over the {MAX_TRIANGLES} limit")
    if len(mesh.faces) < MIN_TRIANGLES:
        raise MeshError(f"{name} has {len(mesh.faces)} triangles, too few to be a body")
    if mesh.faces.min() < 0 or mesh.faces.max() >= len(v):
        raise MeshError(f"{name} has a face that points at a missing vertex")
    return mesh


def load_obj(text: str, name: str = "the OBJ") -> Mesh:
    verts, cols, faces = [], [], []
    for ln, line in enumerate(text.splitlines(), 1):
        parts = line.split()
        if not parts:
            continue
        try:
            if parts[0] == "v" and len(parts) >= 4:
                verts.append([float(x) for x in parts[1:4]])
                if len(parts) >= 7:
                    cols.append([float(x) for x in parts[4:7]])
            elif parts[0] == "f" and len(parts) >= 4:
                idx = [_obj_index(p, len(verts)) for p in parts[1:]]
                faces.extend([idx[0], idx[i], idx[i + 1]] for i in range(1, len(idx) - 1))
        except ValueError:
            raise MeshError(f"{name} line {ln} cannot be read") from None
    colors = np.clip(np.array(cols), 0, 1) if len(cols) == len(verts) and cols else None
    return Mesh(np.array(verts, dtype=float).reshape(-1, 3), np.array(faces, dtype=np.int64).reshape(-1, 3), colors)


def _obj_index(token: str, count: int) -> int:
    i = int(token.split("/")[0])
    if i == 0:
        raise ValueError("zero index")
    return i - 1 if i > 0 else count + i


def load_glb(data: bytes, name: str = "the GLB") -> Mesh:
    doc, blob = _glb_chunks(data, name)
    if doc.get("skins") or any("skin" in n for n in doc.get("nodes", [])):
        raise MeshError(f"{name} is already rigged (it has a skin); use it as it is")
    bad = set(doc.get("extensionsRequired", [])) - _SUPPORTED_EXTENSIONS
    if bad:
        raise MeshError(f"{name} needs {min(bad)}, which autorig cannot read")
    parts = []
    for node, matrix in _walk(doc):
        if "mesh" in node:
            for prim in doc["meshes"][node["mesh"]].get("primitives", []):
                if prim.get("mode", 4) == 4 and "POSITION" in prim.get("attributes", {}):
                    parts.append(_primitive(doc, blob, prim, matrix, name))
    if not parts:
        raise MeshError(f"{name} has no triangle mesh")
    base = np.cumsum([0] + [len(p.vertices) for p in parts])
    colors = None
    if any(p.colors is not None for p in parts):
        colors = np.concatenate([p.colors if p.colors is not None else np.full((len(p.vertices), 3), 0.77) for p in parts])
    return Mesh(np.concatenate([p.vertices for p in parts]),
                np.concatenate([p.faces + b for p, b in zip(parts, base)]), colors)


def _glb_chunks(data: bytes, name: str):
    if len(data) < 20 or struct.unpack_from("<I", data, 4)[0] != 2:
        raise MeshError(f"{name} is not a glTF 2.0 binary")
    pos, doc, blob = 12, None, b""
    while pos + 8 <= len(data):
        length, kind = struct.unpack_from("<I4s", data, pos)
        body = data[pos + 8:pos + 8 + length]
        if len(body) < length:
            raise MeshError(f"{name} is cut short")
        if kind == b"JSON":
            try:
                doc = json.loads(body)
            except ValueError:
                raise MeshError(f"{name} has unreadable JSON") from None
        elif kind == b"BIN\x00":
            blob = body
        pos += 8 + length + (-length % 4)
    if not isinstance(doc, dict):
        raise MeshError(f"{name} has no JSON chunk")
    return doc, blob


def _matrix(node: dict) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], dtype=float).reshape(4, 4).T
    t, r, s = node.get("translation", [0, 0, 0]), node.get("rotation", [0, 0, 0, 1]), node.get("scale", [1, 1, 1])
    x, y, z, w = r
    rot = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4)
    m[:3, :3] = rot * np.array(s)
    m[:3, 3] = t
    return m


def _walk(doc: dict):
    nodes = doc.get("nodes", [])
    scene = (doc.get("scenes") or [{}])[doc.get("scene", 0)] if doc.get("scenes") else {}
    roots = scene.get("nodes", range(len(nodes)) if not doc.get("scenes") else [])
    seen = set()
    stack = [(i, np.eye(4)) for i in reversed(list(roots))]
    while stack:
        i, parent = stack.pop()
        if i in seen or not 0 <= i < len(nodes):
            raise MeshError("the GLB node tree loops or points at a missing node")
        seen.add(i)
        world = parent @ _matrix(nodes[i])
        yield nodes[i], world
        stack.extend((c, world) for c in reversed(nodes[i].get("children", [])))


def _accessor(doc: dict, blob: bytes, index: int) -> np.ndarray:
    try:
        acc = doc["accessors"][index]
        if "sparse" in acc:
            raise MeshError("the GLB uses sparse accessors, which autorig cannot read")
        dtype, width, count = np.dtype("<" + _COMPONENT[acc["componentType"]]), _WIDTH[acc["type"]], acc["count"]
        view = doc["bufferViews"][acc["bufferView"]]
        start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        stride = view.get("byteStride") or dtype.itemsize * width
        raw = np.frombuffer(blob, dtype=np.uint8, count=stride * (count - 1) + dtype.itemsize * width, offset=start)
        rows = np.lib.stride_tricks.as_strided(raw, shape=(count, dtype.itemsize * width), strides=(stride, 1))
        out = np.ascontiguousarray(rows).view(dtype).reshape(count, width)
    except (KeyError, IndexError, ValueError, TypeError):
        raise MeshError("the GLB has an accessor that cannot be read") from None
    if acc.get("normalized"):
        out = out / float(np.iinfo(dtype).max)
    return out


def _primitive(doc: dict, blob: bytes, prim: dict, world: np.ndarray, name: str) -> Mesh:
    attrs = prim["attributes"]
    pos = _accessor(doc, blob, attrs["POSITION"]).astype(float)
    pos = pos @ world[:3, :3].T + world[:3, 3]
    if "indices" in prim:
        idx = _accessor(doc, blob, prim["indices"]).reshape(-1).astype(np.int64)
    else:
        idx = np.arange(len(pos), dtype=np.int64)
    if len(idx) % 3:
        raise MeshError(f"{name} has an index list that is not whole triangles")
    colors = _colors(doc, blob, prim, pos.shape[0])
    return Mesh(pos, idx.reshape(-1, 3), colors)


def _colors(doc: dict, blob: bytes, prim: dict, n: int):
    """Vertex colours: COLOR_0 times the material colour and the base colour texture sampled at TEXCOORD_0."""
    mat = (doc.get("materials") or [{}])[prim["material"]] if "material" in prim else {}
    pbr = mat.get("pbrMetallicRoughness", {})
    out = np.tile(np.array(pbr.get("baseColorFactor", [1, 1, 1, 1])[:3], dtype=float), (n, 1))
    known = False
    if "COLOR_0" in prim["attributes"]:
        out = out * np.clip(_accessor(doc, blob, prim["attributes"]["COLOR_0"])[:, :3].astype(float), 0, 1)
        known = True
    tex = pbr.get("baseColorTexture")
    if tex is not None and "TEXCOORD_0" in prim["attributes"]:
        img = _texture(doc, blob, tex.get("index", 0))
        if img is not None:
            uv = _accessor(doc, blob, prim["attributes"]["TEXCOORD_0"]).astype(float)
            h, w = img.shape[:2]
            px = np.clip((uv[:, 0] % 1.0) * (w - 1), 0, w - 1).round().astype(int)
            py = np.clip((uv[:, 1] % 1.0) * (h - 1), 0, h - 1).round().astype(int)
            out = out * (img[py, px, :3] / 255.0)
            known = True
    if not known and "baseColorFactor" not in pbr:
        return None
    return np.clip(out, 0, 1)


def _texture(doc: dict, blob: bytes, index: int):
    try:
        src = doc["images"][doc["textures"][index]["source"]]
        view = doc["bufferViews"][src["bufferView"]]
        raw = blob[view.get("byteOffset", 0):view.get("byteOffset", 0) + view["byteLength"]]
        import io

        return np.asarray(Image.open(io.BytesIO(raw)).convert("RGBA"))
    except (KeyError, IndexError, OSError, ValueError):
        return None  # an external or unreadable image: the vertex keeps its material colour


# ---- normalising ------------------------------------------------------------------------------------

def normalize(mesh: Mesh, height_m: float | None = None, up: str | None = None):
    """(mesh in metres, Y up, soles on y = 0, centred on x and z, info). `up` is "y" or "z" (None guesses: Z when the
    mesh is much longer in Z than in Y). The size comes from height_m when given, else from a unit guess."""
    v = np.array(mesh.vertices, dtype=float)
    ext = v.max(0) - v.min(0)
    axis = up.lower() if up else ("z" if ext[1] < 0.6 * ext[2] else "y")
    if axis not in ("y", "z"):
        raise MeshError('--up must be "y" or "z"')
    if axis == "z":
        v = np.stack([v[:, 0], v[:, 2], -v[:, 1]], axis=1)  # a half turn of the up axis from Z to Y, handedness kept
    h = float(v[:, 1].max() - v[:, 1].min())
    if h <= 0:
        raise MeshError("the mesh has no height")
    scale, unit = _scale(h, height_m)
    v *= scale
    lo, hi = v.min(0), v.max(0)
    v -= np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    info = {"up": axis, "unit": unit, "scale": scale, "height_m": round(float(v[:, 1].max()), 4)}
    return Mesh(v, mesh.faces, mesh.colors), info


def _scale(h: float, height_m: float | None):
    if height_m is not None:
        if not 0.3 <= height_m <= 3.0:
            raise MeshError("--height must be between 0.3 and 3 metres")
        return height_m / h, "given"
    for lo, hi, factor, unit in ((0.5, 2.6, 1.0, "m"), (50, 260, 0.01, "cm"), (500, 2600, 0.001, "mm")):
        if lo <= h <= hi:
            return factor, unit
    return ASSUMED_HEIGHT_M / h, "assumed"


def face_back(mesh: Mesh) -> Mesh:
    """The mesh turned half a turn about Y (x and z negated), for a figure that faces -Z."""
    v = mesh.vertices * np.array([-1.0, 1.0, -1.0])
    return Mesh(v, mesh.faces, mesh.colors)


# ---- rendering --------------------------------------------------------------------------------------

def render_front(mesh: Mesh, size: int = RENDER_SIZE):
    """(PIL RGB image, Camera): the figure seen from +Z, flat shaded, far faces painted first."""
    v = mesh.vertices
    lo, hi = v.min(0), v.max(0)
    centre = (lo + hi) / 2
    dist = (hi[1] - lo[1]) * FOCAL_PX / (FILL * size)
    cam = Camera(np.array([[FOCAL_PX, 0, size / 2], [0, FOCAL_PX, size / 2], [0, 0, 1.0]]), size,
                 float(centre[0]), float(centre[1]), float(hi[2] + dist))
    q = cam.to_cam(v)
    uv = q[:, :2] * FOCAL_PX / q[:, 2:3] + size / 2
    tri = mesh.faces
    a, b, c = q[tri[:, 0]], q[tri[:, 1]], q[tri[:, 2]]
    n = np.cross(b - a, c - a)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    light = np.array([0.25, -0.35, -1.0])
    light /= np.linalg.norm(light)
    shade = 0.42 + 0.58 * np.abs(n @ light)
    base = np.array(DEFAULT_COLOUR, dtype=float) if mesh.colors is None else None
    face_col = (np.tile(base, (len(tri), 1)) if base is not None else mesh.colors[tri].mean(axis=1) * 255)
    rgb = np.clip(face_col * shade[:, None], 0, 255).astype(np.uint8)
    order = np.argsort(-(a[:, 2] + b[:, 2] + c[:, 2]))
    img = Image.new("RGB", (size, size), BACKGROUND)
    draw = ImageDraw.Draw(img)
    for f in order:
        draw.polygon([tuple(uv[i]) for i in tri[f]], fill=tuple(int(x) for x in rgb[f]))
    return img, cam
