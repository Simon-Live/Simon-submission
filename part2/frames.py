"""Frame ingest: a video or a directory of images -> numbered frames plus frames.json.

frames.json: {"source": str, "frames": [{"frame": int, "t_ms": float, "file": str}]}
`frame` and `t_ms` are the values later written into pose3d.json / tracks.json. `frame` is
strictly increasing but not necessarily contiguous (an image dir's own frames.json numbering
is kept); `t_ms` is relative to the first source frame and is the real timestamp of the
pictured frame.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
MANIFEST = "frames.json"


def ingest(src: Path, out_dir: Path, fps: float | None = None) -> list[dict]:
    """Write frames for `src` into `out_dir` (replacing any frames already there) and return
    the frame records.

    Video: every decoded frame, or with `fps` the source frame nearest each 1/fps step (works
    for variable frame rate; never duplicates frames).
    Directory: images in name order; frame numbers and timestamps from the directory's own
    frames.json if present, otherwise numbered 0.. and timestamped from `fps` (required then).
    """
    if fps is not None and fps <= 0:
        raise ValueError(f"fps must be > 0, got {fps}")
    src, out_dir = Path(src), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = _from_dir(src, out_dir, fps) if src.is_dir() else _from_video(src, out_dir, fps)
    (out_dir / MANIFEST).write_text(json.dumps({"source": str(src), "frames": frames}, indent=1))
    return frames


def load(frames_dir: Path) -> list[dict]:
    return json.loads((Path(frames_dir) / MANIFEST).read_text())["frames"]


def _clear(out_dir: Path) -> None:
    for old in out_dir.iterdir():
        if old.suffix.lower() in IMAGE_EXTS or old.name == MANIFEST:
            old.unlink()


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"{cmd[0]} failed: {e.stderr.strip() or e}") from None
    except FileNotFoundError:
        raise RuntimeError(f"{cmd[0]} not found; install ffmpeg") from None


def _from_video(src: Path, out_dir: Path, fps: float | None) -> list[dict]:
    if not src.is_file():
        raise FileNotFoundError(src)
    pts = _probe_timestamps(src)
    if not pts:
        raise ValueError(f"no video frames decoded from {src}")
    _clear(out_dir)
    with tempfile.TemporaryDirectory(dir=out_dir) as tmp:
        _run(["ffmpeg", "-v", "error", "-i", str(src), "-fps_mode", "passthrough", "-q:v", "2",
              "-start_number", "0", str(Path(tmp) / "%06d.jpg")])
        files = sorted(Path(tmp).glob("*.jpg"))
        if len(files) != len(pts):
            raise RuntimeError(f"ffmpeg wrote {len(files)} frames but ffprobe reported {len(pts)}")
        keep = _nearest_per_step(pts, fps) if fps is not None else range(len(pts))
        frames = []
        for i, k in enumerate(keep):
            name = f"{i:06d}.jpg"
            files[k].rename(out_dir / name)
            frames.append({"frame": i, "t_ms": round((pts[k] - pts[0]) * 1000, 3), "file": name})
    return frames


def _nearest_per_step(pts: list[float], fps: float) -> list[int]:
    """Indices of the source frames nearest t0, t0 + 1/fps, ... (deduplicated, in order)."""
    keep, j, step, n = [], 0, 1 / fps, 0
    while True:
        target = pts[0] + n * step
        if target - pts[-1] >= step / 2 - 1e-9:
            return keep
        while j + 1 < len(pts) and abs(pts[j + 1] - target) <= abs(pts[j] - target):
            j += 1
        if not keep or keep[-1] != j:
            keep.append(j)
        n += 1


def _probe_timestamps(src: Path) -> list[float]:
    out = _run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=best_effort_timestamp_time",
                "-of", "csv=p=0", str(src)])
    return [float(line.strip().rstrip(",")) for line in out.splitlines() if line.strip().rstrip(",") not in ("", "N/A")]


def _from_dir(src: Path, out_dir: Path, fps: float | None) -> list[dict]:
    images = sorted(p for p in src.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not images:
        raise ValueError(f"no images ({', '.join(sorted(IMAGE_EXTS))}) in {src}")
    given = src / MANIFEST
    if given.exists():
        recs = {r["file"]: r for r in json.loads(given.read_text())["frames"]}
        missing = [p.name for p in images if p.name not in recs]
        if missing:
            raise ValueError(f"{given} has no entry for {missing[:3]}")
        numbers = [recs[p.name].get("frame", i) for i, p in enumerate(images)]
        t_ms = [recs[p.name]["t_ms"] for p in images]
        if any(b <= a for a, b in zip(numbers, numbers[1:])):
            raise ValueError(f"{given}: frame numbers must increase in file-name order")
    elif fps is not None:
        numbers = list(range(len(images)))
        t_ms = [round(i * 1000 / fps, 3) for i in numbers]
    else:
        raise ValueError(f"{src} has no {MANIFEST}; pass --fps to timestamp its images")
    in_place = src.resolve() == out_dir.resolve()
    if not in_place:
        _clear(out_dir)
    frames = []
    for n, p, t in zip(numbers, images, t_ms):
        name = p.name if in_place else f"{n:06d}{p.suffix.lower()}"
        if not in_place:
            shutil.copyfile(p, out_dir / name)
        frames.append({"frame": n, "t_ms": t, "file": name})
    return frames
