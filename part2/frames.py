"""Frame ingest: a video or a directory of images -> numbered frames plus frames.json.

frames.json: {"source": str, "frames": [{"frame": int, "t_ms": float, "file": str}]}
`frame` and `t_ms` are the values later written into pose3d.json / tracks.json.
"""
import json
import shutil
import subprocess
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
MANIFEST = "frames.json"


def ingest(src: Path, out_dir: Path, fps: float | None = None) -> list[dict]:
    """Write frames for `src` into `out_dir` and return the frame records.

    Video: every decoded frame with its own timestamp, or resampled to `fps`.
    Directory: images in name order; timestamps from the directory's own frames.json if
    present, otherwise from `fps` (required then).
    """
    src, out_dir = Path(src), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = _from_dir(src, out_dir, fps) if src.is_dir() else _from_video(src, out_dir, fps)
    (out_dir / MANIFEST).write_text(json.dumps({"source": str(src), "frames": frames}, indent=1))
    return frames


def load(frames_dir: Path) -> list[dict]:
    return json.loads((Path(frames_dir) / MANIFEST).read_text())["frames"]


def _from_video(src: Path, out_dir: Path, fps: float | None) -> list[dict]:
    if not src.is_file():
        raise FileNotFoundError(src)
    pts = _probe_timestamps(src)
    if not pts:
        raise ValueError(f"no video frames decoded from {src}")
    for old in out_dir.glob("*.jpg"):
        old.unlink()
    cmd = ["ffmpeg", "-v", "error", "-i", str(src)]
    cmd += ["-vf", f"fps={fps}"] if fps else ["-fps_mode", "passthrough"]
    subprocess.run(cmd + ["-q:v", "2", "-start_number", "0", str(out_dir / "%06d.jpg")], check=True)
    files = sorted(out_dir.glob("*.jpg"))
    if fps:
        times = [pts[0] + i / fps for i in range(len(files))]
    else:
        if len(files) != len(pts):
            raise RuntimeError(f"ffmpeg wrote {len(files)} frames but ffprobe reported {len(pts)}")
        times = pts
    t0 = pts[0]
    return [{"frame": i, "t_ms": round((t - t0) * 1000, 3), "file": f.name} for i, (f, t) in enumerate(zip(files, times))]


def _probe_timestamps(src: Path) -> list[float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=best_effort_timestamp_time",
         "-of", "csv=p=0", str(src)],
        check=True, capture_output=True, text=True,
    ).stdout
    return [float(line.strip().rstrip(",")) for line in out.splitlines() if line.strip().rstrip(",") not in ("", "N/A")]


def _from_dir(src: Path, out_dir: Path, fps: float | None) -> list[dict]:
    images = sorted(p for p in src.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not images:
        raise ValueError(f"no images ({', '.join(sorted(IMAGE_EXTS))}) in {src}")
    given = src / MANIFEST
    if given.exists():
        times = {r["file"]: r["t_ms"] for r in json.loads(given.read_text())["frames"]}
        missing = [p.name for p in images if p.name not in times]
        if missing:
            raise ValueError(f"{given} has no t_ms for {missing[:3]}")
        t_ms = [times[p.name] for p in images]
    elif fps:
        t_ms = [round(i * 1000 / fps, 3) for i in range(len(images))]
    else:
        raise ValueError(f"{src} has no {MANIFEST}; pass --fps to timestamp its images")
    frames = []
    for i, (p, t) in enumerate(zip(images, t_ms)):
        name = f"{i:06d}{p.suffix.lower()}"
        if src.resolve() != out_dir.resolve():
            shutil.copyfile(p, out_dir / name)
        else:
            name = p.name
        frames.append({"frame": i, "t_ms": t, "file": name})
    return frames
