"""The mesh as it is built: `part2 run --mesh --mesh-stream` writes `mesh3d.stream/` while SAM 3D Body runs (TICKET-284).

The finished pair (`mesh3d.json` + `mesh3d.bin`) is written at the end of the run and is not touched by this module, so
it stays byte-identical with and without streaming. The stream is a second, partial view of the same blocks for a reader
that wants the first frames before the run ends:

  mesh3d.stream/head.bin       faces then vertex_joint labels, each zero-padded to 4 bytes (written once, first frame)
  mesh3d.stream/chunk-NNNN.bin the int16 blocks of the frames finished since the last chunk, in block order
  mesh3d.stream/stream.json    the manifest, replaced atomically after each chunk; `done` is true after the last one

Every file is written under a temporary name and renamed into place, so a reader never sees a half-written file, and the
manifest is renamed last, so every chunk it lists exists. Spec: docs/design/specs/mesh3d.md (AC-M19 to AC-M23).
"""
import json
import os
from pathlib import Path

import numpy as np

DIR_NAME, MANIFEST, HEAD = "mesh3d.stream", "stream.json", "head.bin"
FORMAT = "part2.mesh3d-stream/2026-11-02"


def _atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def clear(out_dir) -> None:
    """Remove a stream an earlier run left in out_dir (its files only, then the folder)."""
    d = Path(out_dir) / DIR_NAME
    if d.is_dir():
        for f in d.iterdir():
            if f.is_file():
                f.unlink()
        d.rmdir()


class MeshStream:
    """Flushes the collector's finished frames to `out_dir/mesh3d.stream/` every `every` frames (default each frame)."""

    def __init__(self, out_dir, every: int = 1):
        if every < 1:
            raise ValueError("a mesh stream flushes at least every frame")
        self.dir, self.every = Path(out_dir) / DIR_NAME, every
        self.sent_blocks, self.frames_done, self.total, self.chunks = 0, 0, None, []
        self.head_meta = None

    def _write_head(self, c) -> None:
        from part2 import mesh3d  # the layout is the collector's: no second copy of it

        self.dir.mkdir(parents=True, exist_ok=True)
        faces = c.plan.faces.astype("<u2" if c.plan.count <= 65535 else "<u4")
        head = mesh3d._pad(faces.tobytes())
        offset = len(head)
        head += mesh3d._pad(c.vertex_joint.astype(np.uint8).tobytes())
        _atomic(self.dir / HEAD, head)
        self.head_meta = {"file": HEAD, "bytes": len(head), "vertex_count": c.plan.count, "face_count": len(faces),
                          "faces": {"offset": 0, "dtype": "uint16" if faces.itemsize == 2 else "uint32"},
                          "vertex_joint": {"offset": offset, "names": list(mesh3d.CANONICAL)}}

    def end_frame(self, c) -> None:
        """Called by the collector when a frame is complete. Flushes when `every` frames are waiting."""
        self.frames_done += 1
        if self.frames_done % self.every == 0 or not self.chunks:  # the first frame with a person goes out at once
            self.flush(c)

    def flush(self, c, done: bool = False) -> None:
        if c.plan is None:  # no person yet: nothing a viewer can draw
            return
        if self.head_meta is None:
            self._write_head(c)
        new = c.blocks[self.sent_blocks:]
        if new:
            name = f"chunk-{len(self.chunks):04d}.bin"
            _atomic(self.dir / name, b"".join(b.tobytes() for b in new))
            self.chunks.append({"file": name, "first_block": self.sent_blocks, "blocks": len(new)})
            self.sent_blocks += len(new)
        elif not done:
            return
        self._manifest(c, done)

    def _manifest(self, c, done: bool) -> None:
        from part2 import mesh3d

        frames = [{"frame": f["frame"], "t_ms": f["t_ms"],
                   "people": [{"id": p["id"], "block": p["block"]} for p in f["people"] if p["block"] < self.sent_blocks]}
                  for f in c.frames]
        doc = {"format": FORMAT, "model": "sam-3d-body-dinov3", "frame_of_reference": mesh3d.FRAME_OF_REFERENCE,
               "vertices": {"dtype": "int16", "unit_m": mesh3d.UNIT_M}, "head": self.head_meta, "chunks": self.chunks,
               "block_bytes": mesh3d.bytes_per_person_frame(c.plan.count), "frames": frames,
               "frames_done": len(frames), "frames_total": self.total, "done": done}
        _atomic(self.dir / MANIFEST, json.dumps(doc).encode())

    def finish(self, c) -> None:
        """After the finished pair is written: flush what is left and mark the stream done.

        The total is known for certain only now (body3d.estimate, a stamped file, does not announce it), so a
        running stream reports frames_total null until this last flush."""
        if self.total is None:
            self.total = len(c.frames)
        self.flush(c, done=True)
