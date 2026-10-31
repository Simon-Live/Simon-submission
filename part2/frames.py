"""Frame ingest: a video or a directory of images -> numbered frames plus frames.json.

frames.json: {"source": str, "t0_pts_ms": float (video only), "frames": [{"frame": int, "t_ms": float, "file": str}]}
`frame` and `t_ms` are the values later written into pose3d.json / tracks.json. `frame` is
strictly increasing but not necessarily contiguous (an image dir's own frames.json numbering
is kept); `t_ms` is relative to the first decoded source frame (`pts[k] - pts[0]`) and is the
real timestamp of the pictured frame. `t0_pts_ms` is that first frame's own PTS in ms, copied
into pose3d.json and tracks.json so a reader can rebase onto the file clock.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from part2.schema import is_number, write_json

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
MANIFEST = "frames.json"
# The ffprobe pass that reads every frame's timestamp is killed after this many seconds (fail closed). It decodes the
# video: 60 s of 1080p at 30 fps takes about 2 s, 60 s of 4K at 60 fps about 13 s, so 120 s clears the largest upload
# the app admits many times over and still stops a stalled decoder. docs/specs/journey-followup.md (R17).
PROBE_TIMEOUT_S = 120.0


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
    frames, t0_pts_ms = _from_dir(src, out_dir, fps) if src.is_dir() else _from_video(src, out_dir, fps)
    manifest = {"source": str(src), **({} if t0_pts_ms is None else {"t0_pts_ms": t0_pts_ms}), "frames": frames}
    write_json(out_dir / MANIFEST, manifest, indent=1)
    return frames


def load(frames_dir: Path) -> list[dict]:
    return json.loads((Path(frames_dir) / MANIFEST).read_text())["frames"]


def load_meta(frames_dir: Path) -> dict:
    """The optional top-level keys of frames.json that pose3d.json and tracks.json copy: `t0_pts_ms`."""
    doc = json.loads((Path(frames_dir) / MANIFEST).read_text())
    return {k: doc[k] for k in ("t0_pts_ms",) if k in doc}


def _clear(out_dir: Path) -> None:
    for old in out_dir.iterdir():
        if old.suffix.lower() in IMAGE_EXTS or old.name == MANIFEST:
            old.unlink()


def _run(cmd: list[str], timeout: float | None = None) -> str:
    """The command's stdout. With `timeout` (seconds) a command that has not finished by then is killed and
    RuntimeError("<cmd> timed out after <timeout> s") is raised; without it the command may run as long as it likes."""
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout).stdout
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"{cmd[0]} failed: {e.stderr.strip() or e}") from None
    except FileNotFoundError:
        raise RuntimeError(f"{cmd[0]} not found; install ffmpeg") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{cmd[0]} timed out after {timeout:g} s") from None


def _from_video(src: Path, out_dir: Path, fps: float | None) -> tuple[list[dict], float]:
    """(frame records, the first decoded frame's PTS in ms)"""
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
    return frames, round(pts[0] * 1000, 3)


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
    """The decoded frame timestamps of `src` in seconds, in the order ffprobe reports them. RuntimeError when ffprobe
    fails or does not finish within PROBE_TIMEOUT_S."""
    out = _run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=best_effort_timestamp_time",
                "-of", "csv=p=0", str(src)], timeout=PROBE_TIMEOUT_S)
    return [float(line.strip().rstrip(",")) for line in out.splitlines() if line.strip().rstrip(",") not in ("", "N/A")]


def _from_dir(src: Path, out_dir: Path, fps: float | None) -> tuple[list[dict], float | None]:
    """(frame records, `t0_pts_ms` from the directory's own frames.json, else None)"""
    images = sorted(p for p in src.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not images:
        raise ValueError(f"no images ({', '.join(sorted(IMAGE_EXTS))}) in {src}")
    given, t0_pts_ms = src / MANIFEST, None
    if given.exists():
        manifest = json.loads(given.read_text())
        t0_pts_ms = manifest.get("t0_pts_ms") if is_number(manifest.get("t0_pts_ms")) else None
        recs = {r["file"]: r for r in manifest["frames"]}
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
    return frames, t0_pts_ms
