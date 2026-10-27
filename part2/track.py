"""Multi-person tracking -> tracks.json (#10).

CPU-only core: turn per-frame person detections (bbox + binary mask + score, with a
stable track id) into the shared tracks.json shape and validate it:

    {frames: [{frame, people: [{id, bbox, mask_rle, confidence}]}]}

bbox is [x, y, w, h] in pixels; mask_rle is COCO RLE ({size: [h, w], counts});
ids are stable integers across frames. The SAM 3.1 runner that produces the
detections runs only on the GPU pod (see load_sam31_tracker); everything else in
this module imports and tests without torch or pycocotools.
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
                "mask_rle": mask_to_rle(d["mask"]),
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


def load_sam31_tracker():
    """SAM 3.1 video tracker (GPU pod only). Deferred until the GPU env has SAM 3.

    Kept as a factory so importing part2.track never imports torch/sam3 locally.
    """
    try:
        import sam3  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "SAM 3.1 is not installed here; run tracking in the GPU environment "
            "(k8s/setup_env.sh on user-part2-gpu) or inject a tracker"
        ) from e
    raise RuntimeError("SAM 3.1 tracker wiring is not implemented yet (GPU is down)")
