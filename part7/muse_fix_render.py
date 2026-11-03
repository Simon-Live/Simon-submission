"""The grey control render for "You, doing it right" (docs/specs/muse-fix.md, TICKET-280).

Reads a person's SAM 3D Body mesh (`mesh3d.json` + `mesh3d.bin`, Part 2 CONTRACT), turns the faulted limb to the
trainer's angle (`muse_fix_geom.bend_limb`), projects it with the frame's own camera and draws it flat grey as a PNG
the size of the video frame. No dependency: a z-sorted triangle fill into one grey byte per pixel and a zlib PNG.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from typing import Any
import zlib

from part7 import muse_fix_geom as geom

BACKGROUND, LIGHT = 40, (0.3, 0.5, 0.8)
MAX_SIDE = 4096


class RenderError(ValueError):
    """The mesh or camera cannot be used; the message is short and has no path."""


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_frame(folder: Path, frame: int, person: Any = 0) -> dict[str, Any]:
    """`{vertices, labels, faces}` of one mesh frame and person of a Part 2 output folder; RenderError when absent."""
    head = read_json(folder / "mesh3d.json")
    if not isinstance(head, dict):
        raise RenderError("no mesh for this take")
    try:
        blob = (folder / str(head["bin"])).read_bytes()
        n, nf = int(head["vertex_count"]), int(head["face_count"])
        face_t = {"uint16": ("H", 2), "uint32": ("I", 4)}[head["faces"]["dtype"]]
        unit = float(head["vertices"]["unit_m"])
        names = head["vertex_joint"]["names"]
        label_at = int(head["vertex_joint"]["offset"])
        row = next(f for f in head["frames"] if f["frame"] == frame)
        at = int(next(p for p in row["people"] if str(p["id"]) == str(person))["offset"])
        faces = struct.unpack(f"<{nf * 3}{face_t[0]}", blob[: nf * 3 * face_t[1]])
        raw = struct.unpack(f"<{n * 3}h", blob[at: at + n * 6])
        label_ids = blob[label_at: label_at + n]
        if len(label_ids) != n:
            raise ValueError("short")
        labels = [names[i] for i in label_ids]
    except (OSError, KeyError, StopIteration, ValueError, TypeError, struct.error, IndexError):
        raise RenderError("the mesh for this moment is unreadable") from None
    verts = [(raw[i] * unit, raw[i + 1] * unit, raw[i + 2] * unit) for i in range(0, n * 3, 3)]
    return {"vertices": verts, "labels": labels, "faces": [faces[i: i + 3] for i in range(0, nf * 3, 3)]}


def camera_for(folder: Path, frame: int, person: Any = 0) -> dict[str, Any]:
    """`{R, t, K, size}` of one frame and person from `camera.json`; RenderError when absent."""
    doc = read_json(folder / "camera.json")
    try:
        entry = next(p for f in doc["frames"] if f["frame"] == frame for p in f["people"] if str(p["id"]) == str(person))
        w, h = (int(x) for x in doc["image_size"])
        cam = {"R": entry["R"], "t": entry["t"], "K": doc["K"], "size": (w, h)}
        geom.project((0.0, 0.0, 0.0), cam["R"], cam["t"], cam["K"])
    except (KeyError, StopIteration, TypeError, ValueError, IndexError):
        raise RenderError("no camera for this moment") from None
    if not (0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE):
        raise RenderError("no camera for this moment")
    return cam


def png_gray(width: int, height: int, pixels: bytearray) -> bytes:
    """An 8-bit grey PNG of `pixels` (row-major, width*height bytes)."""
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + bytes(pixels[y * width: (y + 1) * width]) for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


def _shade(a: tuple[float, ...], b: tuple[float, ...], c: tuple[float, ...]) -> float:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    ln = math.sqrt(nx * nx + ny * ny + nz * nz)
    if ln < 1e-12:
        return 0.0
    return abs(nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2]) / ln


def rasterise(points: list[tuple[float, float, float] | None], faces: list[tuple[int, int, int]], width: int, height: int) -> bytearray:
    """Flat-shaded grey triangles, far to near. Pixels no triangle covers keep BACKGROUND."""
    img = bytearray([BACKGROUND]) * (width * height)
    order = []
    for f in faces:
        a, b, c = (points[i] for i in f)
        if a is None or b is None or c is None:
            continue
        order.append(((a[2] + b[2] + c[2]) / 3.0, a, b, c))
    order.sort(key=lambda t: -t[0])
    for _, a, b, c in order:
        area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(area) < 1e-9:
            continue
        grey = int(90 + 140 * min(1.0, _shade(a, b, c)))
        x0, x1 = max(0, math.floor(min(a[0], b[0], c[0]))), min(width - 1, math.ceil(max(a[0], b[0], c[0])))
        y0, y1 = max(0, math.floor(min(a[1], b[1], c[1]))), min(height - 1, math.ceil(max(a[1], b[1], c[1])))
        for y in range(y0, y1 + 1):
            py = y + 0.5
            for x in range(x0, x1 + 1):
                px = x + 0.5
                w0 = ((b[0] - px) * (c[1] - py) - (b[1] - py) * (c[0] - px)) / area
                w1 = ((c[0] - px) * (a[1] - py) - (c[1] - py) * (a[0] - px)) / area
                if w0 >= 0 and w1 >= 0 and w0 + w1 <= 1:
                    img[y * width + x] = grey
    return img


def control_render(folder: Path, frame: int, joint: str, target_deg: float, joints: dict[str, Any], person: Any = 0) -> bytes:
    """The control PNG: the mesh of `frame` with `joint` turned to `target_deg`, drawn with that frame's camera."""
    mesh, cam = load_frame(folder, frame, person), camera_for(folder, frame, person)
    bent = geom.bend_limb(mesh["vertices"], mesh["labels"], joints, joint, target_deg)
    if bent is None:
        raise RenderError("this joint cannot be turned")
    width, height = cam["size"]
    pts = [geom.project(v, cam["R"], cam["t"], cam["K"]) for v in bent]
    return png_gray(width, height, rasterise(pts, mesh["faces"], width, height))


GUIDE_LINE, GUIDE_DOT = (255, 0, 0), (255, 255, 0)


def png_rgba(width: int, height: int, pixels: bytearray) -> bytes:
    """An 8-bit RGBA PNG of `pixels` (row-major, 4 bytes a pixel)."""
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + bytes(pixels[y * width * 4: (y + 1) * width * 4]) for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


def _paint(img: bytearray, width: int, height: int, box: tuple[float, float, float, float], rgb: tuple[int, int, int], hit) -> None:
    for y in range(max(0, math.floor(box[1])), min(height - 1, math.ceil(box[3])) + 1):
        for x in range(max(0, math.floor(box[0])), min(width - 1, math.ceil(box[2])) + 1):
            if hit(x + 0.5, y + 0.5):
                img[(y * width + x) * 4: (y * width + x) * 4 + 4] = bytes((*rgb, 255))


def guide_overlay(width: int, height: int, points: list[tuple[float, float]]) -> bytes:
    """A transparent PNG with a red line through `points` and a yellow dot on each, thick enough to see at any size."""
    r = max(4.0, width / 140.0)
    img = bytearray(width * height * 4)
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        dx, dy = bx - ax, by - ay
        den = dx * dx + dy * dy or 1.0

        def near(px: float, py: float, ax=ax, ay=ay, dx=dx, dy=dy, den=den) -> bool:
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / den))
            return math.hypot(px - ax - t * dx, py - ay - t * dy) <= r / 2
        _paint(img, width, height, (min(ax, bx) - r, min(ay, by) - r, max(ax, bx) + r, max(ay, by) + r), GUIDE_LINE, near)
    for cx, cy in points:
        _paint(img, width, height, (cx - r, cy - r, cx + r, cy + r), GUIDE_DOT, lambda px, py, cx=cx, cy=cy: math.hypot(px - cx, py - cy) <= r)
    return png_rgba(width, height, img)


def composite(frame: bytes, overlay: bytes) -> bytes:
    """The frame with the overlay laid over it, as a PNG, made by ffmpeg (already a Part 7 requirement); RenderError if it fails."""
    work = Path(tempfile.mkdtemp(prefix="muse-fix-guide-"))
    try:
        (work / "frame").write_bytes(frame)
        (work / "overlay.png").write_bytes(overlay)
        try:
            done = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(work / "frame"), "-i", str(work / "overlay.png"),
                                   "-filter_complex", "overlay=0:0", "-frames:v", "1", str(work / "out.png")],
                                  capture_output=True, timeout=60, check=False)
            out = (work / "out.png").read_bytes() if done.returncode == 0 else b""
        except (OSError, subprocess.TimeoutExpired):
            out = b""
        if not out:
            raise RenderError("the frame could not be drawn on")
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def image_size(blob: bytes) -> tuple[int, int] | None:
    """`(width, height)` of a PNG or JPEG from its header, else None."""
    if blob.startswith(b"\x89PNG\r\n\x1a\n") and len(blob) >= 24:
        return struct.unpack(">II", blob[16:24])
    if not blob.startswith(b"\xff\xd8"):
        return None
    i = 2
    while i + 9 < len(blob):
        if blob[i] != 0xFF:
            return None
        marker = blob[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", blob[i + 5: i + 9])
            return (w, h)
        i += 2 + struct.unpack(">H", blob[i + 2: i + 4])[0]
    return None


def guide_points(folder: Path, frame: int, joint: str, target_deg: float, joints: dict[str, Any], person: Any = 0,
                 jpg: bytes | None = None) -> tuple[list[tuple[float, float]], tuple[int, int]]:
    """Pixel points of the parent, joint and child with the child turned about the joint to `target_deg` (the same turn as
    the control render), and the size they are in; RenderError when the joint cannot be placed. When `jpg` is given and its
    size differs from the camera's, the points are scaled to the picture, so the guide lands on the limb in the picture sent."""
    cam = camera_for(folder, frame, person)
    names = geom.chain(joint)
    pts = [geom._xyz(joints.get(n)) for n in names] if names else []
    if names is None or any(p is None for p in pts):
        raise RenderError("this joint cannot be drawn")
    bent = geom.bend_limb(pts, ["other", "other", geom.moving_labels(joint)[0]], joints, joint, target_deg)  # type: ignore[arg-type]
    flat = [geom.project(p, cam["R"], cam["t"], cam["K"]) for p in bent] if bent else [None]
    if any(p is None for p in flat):
        raise RenderError("this joint cannot be drawn")
    size, pixels = cam["size"], [(p[0], p[1]) for p in flat]  # type: ignore[index]
    real = image_size(jpg) if jpg else None
    if real and real != size:
        pixels = [(x * real[0] / size[0], y * real[1] / size[1]) for x, y in pixels]
        size = real
    return pixels, size


def guide_frame(folder: Path, frame: int, jpg: bytes, joint: str, target_deg: float, joints: dict[str, Any], person: Any = 0,
                points: tuple[list[tuple[float, float]], tuple[int, int]] | None = None) -> bytes:
    """The student's own frame as a PNG with the limb's guide drawn where `joint` at `target_deg` puts it."""
    flat, (width, height) = points or guide_points(folder, frame, joint, target_deg, joints, person, jpg)
    return composite(jpg, guide_overlay(width, height, flat))
