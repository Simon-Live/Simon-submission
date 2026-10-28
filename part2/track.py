"""Multi-person tracking -> tracks.json (#10).

CPU-only core: turn per-frame person detections (bbox + binary mask + score, with a
stable track id) into the shared tracks.json shape and validate it:

    {frames: [{frame, people: [{id, bbox, mask_rle, confidence}]}]}

bbox is [x, y, w, h] in pixels; mask_rle is COCO RLE ({size: [h, w], counts});
ids are stable integers across frames. Detections come from SAM 3.1 through
the Meta Model API (api_tracker, via part2.meta_api); everything else in this
module imports and tests without torch or pycocotools.
"""
import json
from pathlib import Path

from part2 import frames as frames_mod
from part2.schema import validate_tracks


def mask_to_rle(mask) -> dict:
    """COCO RLE for a 2D binary mask (any nested sequence / numpy array of 0/1).

    Always writes COCO's compressed counts string, computed here in pure
    python/numpy (byte-identical to pycocotools.mask.encode).
    """
    import numpy as np

    try:
        a = np.asarray(mask)
    except ValueError as e:  # ragged rows
        raise ValueError("mask rows must all have the same width") from e
    if a.ndim != 2 or 0 in a.shape:
        raise ValueError("mask must be a non-empty 2D array")
    h, w = (int(v) for v in a.shape)
    # Column-major (Fortran order) run lengths, starting with the 0-run,
    # then COCO's compressed counts string (verified byte-identical to
    # pycocotools.mask.encode, so no pycocotools dependency is needed).
    flat = a.astype(bool).ravel(order="F")
    bounds = np.flatnonzero(np.diff(flat)) + 1
    starts = np.concatenate(([0], bounds))
    ends = np.concatenate((bounds, [flat.size]))
    counts = (ends - starts).astype(int).tolist()
    if flat[0]:
        counts.insert(0, 0)
    return {"size": [h, w], "counts": _compress_counts(counts)}


def _compress_counts(counts) -> str:
    out = []
    for i, c in enumerate(counts):
        x = c if i <= 2 else c - counts[i - 2]
        while True:
            ch = x & 0x1F
            x >>= 5
            more = (x != -1) if (ch & 0x10) else (x != 0)
            if more:
                ch |= 0x20
            out.append(chr(ch + 48))
            if not more:
                break
    return "".join(out)


def rle_counts(rle: dict) -> list[int]:
    """Uncompressed run-length counts for an RLE dict (str or list counts)."""
    counts = rle["counts"]
    if isinstance(counts, list):
        return [int(c) for c in counts]
    out, i = [], 0
    while i < len(counts):
        x, k = 0, 0
        while True:
            c = ord(counts[i]) - 48
            i += 1
            x |= (c & 0x1F) << (5 * k)
            k += 1
            if not (c & 0x20):
                if c & 0x10:
                    x |= -1 << (5 * k)
                break
        if len(out) > 2:
            x += out[-2]
        out.append(x)
    return out


def build_tracks(frame_records, detections) -> dict:
    """Assemble a tracks document.

    frame_records: records from part2.frames.load ({frame, t_ms, file}).
    detections: {frame: [{id, bbox, mask, confidence}]} — mask is a 2D binary
    array; ids must already be stable across frames (that's the tracker's job).
    Frames with no detections are kept with an empty people list.
    """
    known = {int(r["frame"]) for r in frame_records}
    unknown = sorted({int(k) for k in detections} - known)
    if unknown:
        raise ValueError(f"detections for frames not in frames.json: {unknown[:5]}")
    out_frames = []
    for r in frame_records:
        people = []
        for d in detections.get(r["frame"], detections.get(str(r["frame"]), [])):
            people.append({
                "id": int(d["id"]),
                "bbox": [float(v) for v in d["bbox"]],
                # a pre-encoded mask_rle is used as-is, so callers parsing a
                # stream never hold more than one full-frame raster at a time
                "mask_rle": d["mask_rle"] if "mask_rle" in d else mask_to_rle(d["mask"]),
                "confidence": float(d["confidence"]),
            })
        people.sort(key=lambda p: p["id"])
        out_frames.append({"frame": int(r["frame"]), "people": people})
    doc = {"frames": out_frames}
    validate_tracks(doc)
    return doc


def track(frames_dir, out_path, tracker=None) -> dict:
    """Run tracking on a frames dir and write tracks.json.

    tracker defaults to the SAM 3.1 GPU tracker; tests inject a fake with the
    same call: tracker(frames_dir, frame_records) -> detections dict.
    """
    frames_dir = Path(frames_dir)
    recs = frames_mod.load(frames_dir)
    tracker = tracker or load_sam31_tracker()
    detections = tracker(frames_dir, recs)
    doc = build_tracks(recs, detections)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc))
    return doc


def derive_fps(frame_records) -> float:
    """Median frame rate from t_ms gaps (the SAM API needs a constant-fps video)."""
    ts = sorted(r["t_ms"] for r in frame_records)
    gaps = [b - a for a, b in zip(ts, ts[1:]) if b > a]
    if not gaps:
        return 30.0
    gaps.sort()
    return 1000.0 / gaps[len(gaps) // 2]


def _ffmpeg_exe() -> str:
    """System ffmpeg if present, else the imageio-ffmpeg bundled binary.

    the cluster's compute nodes have no ffmpeg module, so the API tracker must not
    assume one on PATH.
    """
    import shutil

    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as e:
        raise RuntimeError("ffmpeg not found on PATH and imageio-ffmpeg is not "
                           "installed; cannot encode the SAM API video") from e


def _count_frames(video_path, ffmpeg: str) -> int:
    """Exact frame count: ffprobe when available, else an ffmpeg null decode."""
    import re
    import shutil
    import subprocess

    if shutil.which("ffprobe"):
        return int(subprocess.run(
            ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
             "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(video_path)],
            check=True, capture_output=True, text=True).stdout.strip())
    try:
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        n = 0
        while True:
            ok, _ = cap.read()
            if not ok:
                break
            n += 1
        cap.release()
        if n:
            return n
    except ImportError:
        pass
    r = subprocess.run([ffmpeg, "-v", "info", "-i", str(video_path),
                        "-map", "0:v:0", "-c", "copy", "-f", "null", "-"],
                       capture_output=True, text=True)
    counts = re.findall(r"frame=\s*(\d+)", r.stderr)
    if not counts:
        raise RuntimeError(f"could not count frames in encoded video {video_path}")
    return int(counts[-1])


def encode_video(frames_dir, frame_records, out_path) -> float:
    """Re-encode a frames dir as a constant-fps MP4 (H.264) for the SAM API.

    Video frame i is frame_records[i], so API frame indices map back through
    the records to the real `frame` numbers. Returns the fps used.
    """
    import subprocess
    import tempfile

    ffmpeg = _ffmpeg_exe()
    frames_dir = Path(frames_dir)
    fps = derive_fps(frame_records)
    with tempfile.TemporaryDirectory() as tmp:
        list_path = Path(tmp) / "files.txt"
        list_path.write_text("".join(
            f"file '{(frames_dir / r['file']).resolve()}'\n" for r in frame_records))
        subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0",
                        "-r", f"{fps:.3f}", "-i", str(list_path),
                        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_path)],
                       check=True, capture_output=True)
    count = _count_frames(out_path, ffmpeg)
    if count != len(frame_records):
        raise RuntimeError(f"encoded video has {count} frames for {len(frame_records)} "
                           "frame records; API frame indices would not line up")
    return fps


_OBJ_RE = None  # compiled on first use (keeps module import light)


def _decode_mask(payload: str, width: int, height: int):
    """SAM mask payload -> row-major raster bytes (official parser library)."""
    from meta_sam_parser import SegmentationMask, decode_mask_to_raster

    enc = "lossless" if payload.startswith("~") else "one_bit"
    return decode_mask_to_raster(SegmentationMask(encoding=enc, payload=payload,
                                                  width=width, height=height))


def parse_sam31_text(text: str, frame_records, mask_decoder=None) -> dict:
    """Parse SAM 3.1's text grammar into detections for build_tracks.

    Grammar per frame: `<Nf>id<|box;x1;y1;x2;y2;w=W;h=H[;c=score]|><|mask;…|>,…`
    API frame index N maps to frame_records[N] (the video is re-encoded from
    the frames dir in record order). Masks are box-sized crops; each is placed
    at its box corner into a full-frame mask. Ids are SAM's stable track ids.
    """
    import re

    import numpy as np

    global _OBJ_RE
    if _OBJ_RE is None:
        _OBJ_RE = re.compile(
            r",?(\d+)<\|box;x1=([\d.]+);y1=([\d.]+);x2=([\d.]+);y2=([\d.]+);w=(\d+);h=(\d+)"
            r"(?:;c=([\d.]+))?\|><\|mask;x=(\d+);y=(\d+);(?:c=[\d.]+;)?data=(\d+),(\d+),([^|]+)\|>")
    decode = mask_decoder or _decode_mask
    detections = {}
    parts = re.split(r"<(\d+)f>", text)
    for i in range(1, len(parts) - 1, 2):
        api_frame, segment = int(parts[i]), parts[i + 1]
        if api_frame >= len(frame_records):
            continue  # API returned a frame we did not send; nothing to map it to
        frame = int(frame_records[api_frame]["frame"])
        people = []
        for m in _OBJ_RE.finditer(segment):
            pid, x1, y1, x2, y2 = (int(float(m.group(g))) for g in (1, 2, 3, 4, 5))
            img_w, img_h = int(m.group(6)), int(m.group(7))
            if m.group(8) is None:
                raise ValueError(f"frame {frame} id {pid}: SAM returned no confidence "
                                 "(include_confidence was requested)")
            mx, my = int(m.group(9)), int(m.group(10))
            if (mx, my) != (0, 0):
                raise ValueError(f"frame {frame} id {pid}: mask offset x={mx} y={my} "
                                 "is not understood (expected 0,0 crop at the box corner)")
            mh, mw, payload = int(m.group(11)), int(m.group(12)), m.group(13)
            raster = np.frombuffer(decode(payload, mw, mh), dtype=np.uint8).reshape(mh, mw)
            full = np.zeros((img_h, img_w), dtype=np.uint8)
            sub = full[y1:y1 + mh, x1:x1 + mw]
            sel = raster.astype(bool)[:sub.shape[0], :sub.shape[1]]
            sub[sel] = 1
            # encode now: holding a full-frame raster per person per frame
            # would take ~2 MB x people x frames (25 GB for a 1-minute clip)
            people.append({"id": pid, "bbox": [x1, y1, x2 - x1, y2 - y1],
                           "mask_rle": mask_to_rle(full), "confidence": float(m.group(8))})
        if people:
            detections[frame] = people
    return detections


MAX_API_FRAMES = 15000  # per-request limit; chunking would break id continuity
MAX_API_OBJECTS = 16  # tracked objects per frame; more people than this are lost


def api_tracker(frames_dir, frame_records, prompt: str = "person", budget=None):
    """SAM 3.1 via the Meta Model API (through part2.meta_api, budget-guarded).

    Limits: at most 15,000 frames per request and 16 tracked objects per
    frame. Longer clips need chunking, which is not implemented (it would
    break track-id continuity across chunks).
    """
    import tempfile

    from part2 import meta_api

    if len(frame_records) > MAX_API_FRAMES:
        raise ValueError(f"{len(frame_records)} frames exceeds the SAM API limit of "
                         f"{MAX_API_FRAMES} per request; chunking is not implemented")
    frames_dir = Path(frames_dir)
    with tempfile.TemporaryDirectory() as tmp:
        video_path = Path(tmp) / "clip.mp4"
        encode_video(frames_dir, frame_records, video_path)
        file_id = meta_api.upload(video_path)
        deltas = meta_api.respond(
            "sam-3.1", [meta_api.text(prompt), meta_api.video(file_id)],
            est_cost_usd=meta_api.sam_video_cost(len(frame_records)),
            metadata={"include_confidence": "true"}, budget=budget,
            what=f"sam31-track-{frames_dir.name}")
        text = "".join(deltas)
    return parse_sam31_text(text, frame_records)


def load_sam31_tracker():
    """The default tracker: SAM 3.1 through the Meta Model API (#4/#10)."""
    return api_tracker
