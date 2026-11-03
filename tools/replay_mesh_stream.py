"""Replay a finished Part 2 mesh pair as a growing `mesh3d.stream/` folder (TICKET-284 test fixture, not a model run).

    python3 tools/replay_mesh_stream.py MESH3D_JSON OUT_DIR [--delay S] [--upto N]

Writes OUT_DIR/mesh3d.stream/ in the format `part2 run --mesh --mesh-stream` writes (Part 2 spec mesh3d.md, AC-M19 to
AC-M23): head.bin, one chunk per frame, stream.json replaced atomically after each chunk, `done` true after the last.
It exists so the pending page can be driven without the GPU. Anything it writes is a replay of real SAM 3D Body output
and is labelled so in the manifest (`replay: true`), which a real run never sets. Standard library only.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

FORMAT = "part2.mesh3d-stream/2026-11-02"


def _atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def replay(header_path: Path, out_dir: Path, delay: float = 0.0, upto: int | None = None) -> int:
    header = json.loads(header_path.read_text())
    payload = (header_path.parent / header["bin"]).read_bytes()
    n = header["vertex_count"]
    head_len = header["vertex_joint"]["offset"] + n + (-n % 4)
    block = n * 6
    d = out_dir / "mesh3d.stream"
    d.mkdir(parents=True, exist_ok=True)
    _atomic(d / "head.bin", payload[:head_len])
    head = {"file": "head.bin", "bytes": head_len, "vertex_count": n, "face_count": header["face_count"],
            "faces": header["faces"], "vertex_joint": header["vertex_joint"]}
    chunks, frames, blocks = [], [], 0
    listed = header["frames"] if upto is None else header["frames"][:upto]
    for i, f in enumerate(listed):
        mine, data = [], b""
        for p in f["people"]:
            mine.append({"id": p["id"], "block": blocks + len(mine)})
            data += payload[p["offset"]:p["offset"] + block]
        if mine:  # one chunk per frame that has a person, like `--mesh-stream` with the default flush
            name = f"chunk-{len(chunks):04d}.bin"
            _atomic(d / name, data)
            chunks.append({"file": name, "first_block": blocks, "blocks": len(mine)})
            blocks += len(mine)
        frames.append({"frame": f["frame"], "t_ms": f["t_ms"], "people": mine})
        done = i + 1 == len(header["frames"])
        doc = {"format": FORMAT, "replay": True, "model": header["model"], "frame_of_reference": header["frame_of_reference"],
               "vertices": header["vertices"], "head": head, "chunks": chunks,
               "block_bytes": block, "frames": frames, "frames_done": len(frames), "frames_total": len(header["frames"]),
               "done": done}
        _atomic(d / "stream.json", json.dumps(doc).encode())
        if delay and i + 1 < len(listed):
            time.sleep(delay)
    return len(frames)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mesh3d_json", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--delay", type=float, default=0.0)
    ap.add_argument("--upto", type=int)
    a = ap.parse_args(argv)
    print(f"replayed {replay(a.mesh3d_json, a.out_dir, a.delay, a.upto)} frames into {a.out_dir / 'mesh3d.stream'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
