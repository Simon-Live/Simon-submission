"""SAM 3D Body mesh sequence: mesh3d.json (header) + mesh3d.bin (payload), written by `part2 run --mesh`.

The MHR mesh is decimated once per run by vertex clustering on the first person-frame (clusters split into the
mesh's connected pieces inside each voxel, so touching limbs never merge), then every person-frame is the mean of
each cluster, moved into the pose3d canonical frame of that person and frame (part2.canonical.frame_axes on the
model's own 17 joints) and stored as little-endian int16 at 0.1 mm. The faces are written once.

mesh3d.bin: faces (face_count x 3, uint16 or uint32) at offset 0, then vertex_joint (vertex_count uint8: the index
into vertex_joint.names of each vertex's nearest joint on the first person-frame, so a viewer can tint a limb), each
zero-padded to 4 bytes, then one vertex_count x 3 int16 block per person-frame at the offset the header gives.
Spec: docs/specs/mesh3d.md (TICKET-048, requested by simon-part-7 TICKET-143). Licences: ADR-0005 (SAM License for
the SAM 3D Body weights and the mirror's copy of the MHR model; MHR upstream Apache-2.0).
"""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from part2 import canonical
from part2.joints import CANONICAL
from part2.schema import ContractError, check_finite, write_json

FORMAT = "part2.mesh3d/2026-10-31"
SCHEMA = Path(__file__).resolve().parent.parent / "contracts" / "mesh3d.schema.json"
JSON_NAME, BIN_NAME = "mesh3d.json", "mesh3d.bin"
UNIT_M = 1e-4
DEFAULT_TARGET = 2500
MIN_TARGET = 100
BACKENDS = ("gpu", "cpu-sam3db")  # the backends that run SAM 3D Body and so have a mesh
FRAME_OF_REFERENCE = "pose3d canonical: origin hip midpoint, x subject's left, y up, z forward, metres"
LICENCE = "SAM 3D Body: SAM License (Meta, 2025-11-19); MHR body model: Apache-2.0 (facebookresearch/MHR)"
REFUSAL = "--mesh needs SAM 3D Body (--backend gpu or cpu-sam3db)"


@dataclass
class Plan:
    labels: np.ndarray  # source vertex -> decimated vertex
    count: int
    faces: np.ndarray  # decimated faces (k x 3)


def _edges(faces: np.ndarray) -> np.ndarray:
    e = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    return np.unique(np.sort(e, axis=1), axis=0)


def _clusters(v: np.ndarray, edges: np.ndarray, size: float) -> tuple[np.ndarray, int]:
    """Labels 0..n-1: vertices in one voxel of `size` metres and connected by mesh edges inside it."""
    _, voxel = np.unique(np.floor((v - v.min(0)) / size).astype(np.int64), axis=0, return_inverse=True)
    voxel = voxel.reshape(-1)
    a, b = edges[voxel[edges[:, 0]] == voxel[edges[:, 1]]].T
    labels = np.arange(len(v))
    while True:  # min-label propagation over the in-voxel edges
        before = labels.copy()
        m = np.minimum(labels[a], labels[b])
        np.minimum.at(labels, a, m)
        np.minimum.at(labels, b, m)
        labels = labels[labels]
        if np.array_equal(labels, before):
            break
    _, compact = np.unique(labels, return_inverse=True)
    return compact.reshape(-1), int(compact.max()) + 1


def plan(vertices, faces, target: int = DEFAULT_TARGET) -> Plan:
    """The decimation for a whole run: at most `target` vertices (the source mesh kept whole when smaller)."""
    v, f = np.asarray(vertices, dtype=float), np.asarray(faces, dtype=np.int64)
    if len(v) <= target:
        return Plan(np.arange(len(v)), len(v), _clean_faces(f))
    edges = _edges(f)
    lo, hi = 1e-5, float(np.ptp(v, axis=0).max()) + 1e-3
    best = _clusters(v, edges, hi)
    for _ in range(40):  # geometric bisection on the voxel size; the cluster count falls as it grows
        mid = (lo * hi) ** 0.5
        labels, n = _clusters(v, edges, mid)
        if n > target:
            lo = mid
        else:
            hi, best = mid, (labels, n)
        if best[1] >= 0.97 * target:
            break
    labels, n = best
    return Plan(labels, n, _clean_faces(labels[f]))


def _clean_faces(f: np.ndarray) -> np.ndarray:
    """Drop faces that repeat a vertex and faces that repeat another face (first winding kept)."""
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
    _, first = np.unique(np.sort(f, axis=1), axis=0, return_index=True)
    return f[np.sort(first)]


def apply(p: Plan, vertices) -> np.ndarray:
    """Decimated positions: the mean of each cluster's source vertices."""
    v = np.asarray(vertices, dtype=float)
    counts = np.bincount(p.labels, minlength=p.count)
    return np.stack([np.bincount(p.labels, weights=v[:, k], minlength=p.count) for k in range(3)], axis=1) / counts[:, None]


class Collector:
    """Gathers person-frames during body3d.estimate; `write` produces the pair."""

    def __init__(self, target: int = DEFAULT_TARGET, stream=None):
        if target < MIN_TARGET:
            raise ValueError(f"--mesh-vertices must be at least {MIN_TARGET}")
        self.target, self.plan, self.source_vertex_count = target, None, 0
        self.frames: list[dict] = []
        self.blocks: list[np.ndarray] = []
        self.clipped = 0
        self.vertex_joint = None
        self.stream = stream  # a part2.mesh_stream.MeshStream, or None (TICKET-284)
        self._open = False  # a frame was started and not yet ended for the stream

    def expect(self, total: int) -> None:
        """The number of frames the run will go through, for a stream's counter."""
        if self.stream is not None:
            self.stream.total = total

    def end_frame(self) -> None:
        """The current frame is complete (its people are all added): a stream flushes it.

        Called by `frame` for the previous frame and by `write` for the last one, so body3d.estimate (a stamped
        file) needs no change; an explicit call is harmless (a frame is ended at most once)."""
        if self.stream is not None and self._open:
            self._open = False
            self.stream.end_frame(self)

    def frame(self, frame: int, t_ms: float) -> None:
        self.end_frame()
        self.frames.append({"frame": frame, "t_ms": t_ms, "people": []})
        self._open = True

    def add(self, pid, verts_cam, faces, joints_cam) -> bool:
        """One person of the current frame. False (and nothing kept) when the hips give no canonical frame."""
        try:
            R, t = canonical.frame_axes(np.asarray(joints_cam, dtype=float))
        except ValueError:
            return False
        if self.plan is None:
            self.plan = plan(verts_cam, faces, self.target)
            self.source_vertex_count = len(verts_cam)
        can = canonical.to_canonical(apply(self.plan, verts_cam), R, t)
        if self.vertex_joint is None:
            self.vertex_joint = nearest_joint(can, canonical.to_canonical(np.asarray(joints_cam, dtype=float), R, t))
        q = np.round(can / UNIT_M)
        lim = np.iinfo(np.int16).max
        self.clipped += int((np.abs(q) > lim).sum())
        self.blocks.append(np.clip(q, -lim, lim).astype("<i2"))
        self.frames[-1]["people"].append({"id": pid, "block": len(self.blocks) - 1})
        return True

    def write(self, out_dir, model: str = "sam-3d-body-dinov3") -> tuple[Path, Path] | None:
        """Write mesh3d.bin then mesh3d.json into out_dir; None when no person-frame was collected. The bin is hashed
        and then written block by block, never joined into one bytes object (a long class clip is hundreds of MB)."""
        if self.plan is None:
            return None
        faces = self.plan.faces.astype("<u2" if self.plan.count <= 65535 else "<u4")
        head = _pad(faces.tobytes())
        joint_offset = len(head)
        head += _pad(self.vertex_joint.astype(np.uint8).tobytes())
        block = bytes_per_person_frame(self.plan.count)
        offsets = [len(head) + i * block for i in range(len(self.blocks))]
        size = len(head) + len(self.blocks) * block
        digest = hashlib.sha256(head)
        for b in self.blocks:
            digest.update(b.tobytes())
        frames = [{"frame": f["frame"], "t_ms": f["t_ms"],
                   "people": [{"id": p["id"], "offset": offsets[p["block"]]} for p in f["people"]]} for f in self.frames]
        header = {"format": FORMAT, "frame_of_reference": FRAME_OF_REFERENCE, "model": model, "licence": LICENCE,
                  "bin": BIN_NAME, "bin_bytes": size, "bin_sha256": digest.hexdigest(),
                  "source_vertex_count": self.source_vertex_count, "vertex_count": self.plan.count,
                  "face_count": len(faces), "faces": {"offset": 0, "dtype": "uint16" if faces.itemsize == 2 else "uint32"},
                  "vertices": {"dtype": "int16", "unit_m": UNIT_M},
                  "vertex_joint": {"offset": joint_offset, "names": list(CANONICAL)}, "clipped": self.clipped, "frames": frames}
        check_header(header)
        _check_layout(header, head, size)  # the faces and labels are in `head`; the blocks are whole by construction
        out_dir = Path(out_dir)
        with open(out_dir / BIN_NAME, "wb") as bin_file:
            bin_file.write(head)
            for b in self.blocks:
                bin_file.write(b.tobytes())
        written = write_json(out_dir / JSON_NAME, header), out_dir / BIN_NAME
        self.end_frame()
        if self.stream is not None:
            self.stream.finish(self)
        return written


def nearest_joint(verts: np.ndarray, joints: np.ndarray) -> np.ndarray:
    """Index of the nearest of the 17 joints for every vertex (both in the same frame)."""
    d = np.linalg.norm(verts[:, None, :] - joints[None, :, :], axis=2)
    return np.argmin(d, axis=1)


def _pad(b: bytes) -> bytes:
    return b + b"\0" * (-len(b) % 4)


def bytes_per_person_frame(vertex_count: int) -> int:
    return vertex_count * 3 * 2


# --- reading and checking -----------------------------------------------------------------------

def check_header(header) -> None:
    """Raise ContractError unless header keeps contracts/mesh3d.schema.json and its frames are in order. The bin is
    not looked at, so a header with `frames` or `people` of the wrong type is refused here before anything iterates it."""
    from part2 import contract

    check_finite(header, "mesh3d")
    contract.check_schema(header, contract.load_schema(SCHEMA), at="mesh3d")
    contract.check_sequence(header, "mesh3d")


def validate(header, payload: bytes) -> None:
    """Raise ContractError unless header keeps the schema and payload is the bin it describes."""
    check_header(header)
    check_payload(header, payload)


def check_payload(header: dict, payload: bytes) -> None:
    """Raise ContractError unless payload (the bin) has the size and sha256 the checked header gives and the layout in it."""
    if len(payload) != header["bin_bytes"]:
        raise ContractError("mesh3d.bin", f"{len(payload)} bytes, header says {header['bin_bytes']}")
    if hashlib.sha256(payload).hexdigest() != header["bin_sha256"]:
        raise ContractError("mesh3d.bin", "sha256 differs from the header")
    _check_layout(header, payload, len(payload))


def _check_layout(header: dict, head: bytes, size: int) -> None:
    """Faces, labels and block offsets of a bin of `size` bytes. `head` holds at least its faces and labels."""
    n, k = header["vertex_count"], header["face_count"]
    dtype = "<u2" if header["faces"]["dtype"] == "uint16" else "<u4"
    end = k * 3 * np.dtype(dtype).itemsize
    if end > size:
        raise ContractError("mesh3d.faces", "faces run past the end of the bin")
    if k and int(np.frombuffer(head, dtype=dtype, count=k * 3).max()) >= n:
        raise ContractError("mesh3d.faces", f"a face index is not below vertex_count {n}")
    vj = header["vertex_joint"]
    if vj["offset"] < end or vj["offset"] + n > size:
        raise ContractError("mesh3d.vertex_joint.offset", "the labels are not inside the bin after the faces")
    if n and int(np.frombuffer(head, dtype=np.uint8, count=n, offset=vj["offset"]).max()) >= len(vj["names"]):
        raise ContractError("mesh3d.vertex_joint", "a label is not an index into names")
    end = vj["offset"] + n
    block = bytes_per_person_frame(n)
    for i, f in enumerate(header["frames"]):
        for j, p in enumerate(f["people"]):
            o = p["offset"]
            if o < end or o % 2 or o + block > size:
                raise ContractError(f"mesh3d.frames[{i}].people[{j}].offset", f"{o} is not a whole block inside the bin")


def _bin_of(path: Path, header) -> bytes:
    """The bytes of the bin a mesh3d.json names: a file name beside it, never a path."""
    name = header.get("bin") if isinstance(header, dict) else None
    if not isinstance(name, str) or Path(name).name != name:
        raise ContractError("mesh3d.bin", f"must be a file name beside {path.name}, not {name!r}")
    try:
        return (path.parent / name).read_bytes()
    except OSError as e:
        raise ContractError("mesh3d.bin", f"cannot be read ({e.strerror or e})") from None


def read(path) -> tuple[dict, bytes]:
    """(header, payload) for a mesh3d.json path; the bin is read from the same directory and checked."""
    path = Path(path)
    header = json.loads(path.read_text())
    payload = _bin_of(path, header)
    validate(header, payload)
    return header, payload


def is_mesh3d(doc) -> bool:
    return isinstance(doc, dict) and str(doc.get("format", "")).startswith("part2.mesh3d/")


def _listed(doc: dict) -> tuple[int, int]:
    """(people, frames) a header lists, counting only what has the right type: `frames` that is not an array or a
    `people` that is not one counts as none, and check_header says why."""
    frames = doc.get("frames") if isinstance(doc.get("frames"), list) else []
    ids = {str(p.get("id")) for f in frames if isinstance(f, dict) and isinstance(f.get("people"), list)
           for p in f["people"] if isinstance(p, dict)}
    return len(ids), len(frames)


def diagnose(path, doc, consumer=None) -> dict:
    """part2 doctor on a mesh3d.json: the header against its schema, then the bin; Parts 3, 5 and 6 do not read it.
    exit 0 when both are valid, 1 when not (or when a consumer is named), with the same report as for pose3d."""
    path, error = Path(path), None
    try:
        check_header(doc)
        check_payload(doc, _bin_of(path, doc))
    except (ContractError, OSError, ValueError) as e:
        error = str(e)
    people, frames = _listed(doc)
    findings = [{"consumer": consumer, "verdict": "would reject", "reason": "it does not read mesh3d.json",
                 "fix": "give it pose3d.json; mesh3d.json is for the 3D mesh view"}] if consumer else []
    return {"file": str(path), "kind": "mesh3d", "version": str(doc.get("format")), "detected_by": "by its format field",
            "people": people, "frames": frames, "findings": findings,
            "schema_error": error, "extra_joints": None, "warnings": [],
            "exit": 1 if (error or consumer) else 0}
