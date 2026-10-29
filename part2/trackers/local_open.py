"""local-open: SAM 2.1 hiera-large video masks prompted with rtmlib YOLOX person boxes, re-prompted every 2 s.

Spec: docs/specs/tracker-registry.md (Trackers, Edge cases, AC-R07). ADR-0003. ASM-004.

`reprompt_track` is pure: it runs on any propagator with
    add_box(index, obj_id, [x1, y1, x2, y2])  and  propagate(start, stop) -> {index: {obj_id: (mask, score)}}
(`stop` inclusive). `Sam2Propagator` is the real one (gpu-cu128 venv: torch, sam2); tests use a fake.
At each re-prompt frame a detector box with IoU under 0.3 to every live track starts a track, or reuses a
track lost within 3 s whose last box it overlaps by IoU over 0.3. Masks of two tracks overlapping above
IoU 0.8 keep the older id on the larger mask. A one-frame input is detection only, ids by box area.
"""
import contextlib
import os
import tempfile
from pathlib import Path

import numpy as np

from part2.hashing import sha256_file
from part2.trackers import NoPerson, Tracker, gpu_lock
from part2.trackers.bytetrack import DETECTOR_NAME, PersonDetector, read_image

MODEL_ID = "facebook/sam2.1-hiera-large"
CHECKPOINT = "sam2.1_hiera_large.pt"
PARAMS = {
    "reprompt_every_s": 2.0,
    "new_track_iou": 0.3,
    "reuse_iou": 0.3,
    "reuse_within_s": 3.0,
    "duplicate_mask_iou": 0.8,
    "det_score": 0.5,
}


def box_iou(a, b) -> float:
    """IoU of two [x1, y1, x2, y2] boxes."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def mask_box(mask) -> list[float]:
    """[x1, y1, x2, y2] (exclusive right and bottom) of a non-empty mask."""
    ys, xs = np.nonzero(mask)
    return [float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)]


def mask_iou(a, b) -> float:
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0


def reprompt_frames(frame_records, every_s: float) -> list[int]:
    """Indices where the detector runs: the first frame, then the first frame at least every_s later."""
    out, last = [], None
    for i, r in enumerate(frame_records):
        t = r["t_ms"] / 1000.0
        if last is None or t - last >= every_s - 1e-9:
            out.append(i)
            last = t
    return out


def dedupe(objs: dict, thresh: float) -> dict:
    """Two masks overlapping above `thresh`: the older (smaller) id keeps the larger mask."""
    objs, drop = dict(objs), set()
    ids = sorted(objs)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if a in drop or b in drop or mask_iou(objs[a][0], objs[b][0]) <= thresh:
                continue
            (ma, sa), (mb, sb) = objs[a], objs[b]
            objs[a] = (ma if ma.sum() >= mb.sum() else mb, max(sa, sb))
            drop.add(b)
    return {k: v for k, v in objs.items() if k not in drop}


def _encode(objs: dict) -> list[dict]:
    from part2.track import mask_to_rle

    out = []
    for oid, (mask, score) in sorted(objs.items()):
        x1, y1, x2, y2 = mask_box(mask)
        out.append({"id": int(oid), "bbox": [x1, y1, x2 - x1, y2 - y1], "mask_rle": mask_to_rle(mask),
                    "confidence": float(min(max(score, 0.0), 1.0))})
    return out


def _new_ids(boxes, live, last_seen, t_now, times, p, next_id):
    """Assign an id to each detector box that overlaps no live track: reuse a recently lost one, else new."""
    taken, assigned = set(live), []
    for b in sorted(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True):
        if any(box_iou(b, lb) >= p["new_track_iou"] for lb in live.values()):
            continue
        reuse = [(box_iou(b, box), oid) for oid, (idx, box) in last_seen.items()
                 if oid not in taken and t_now - times[idx] <= p["reuse_within_s"]
                 and box_iou(b, box) > p["reuse_iou"]]
        if reuse:
            oid = max(reuse)[1]
        else:
            oid, next_id = next_id, next_id + 1
        taken.add(oid)
        live = {**live, oid: list(b[:4])}
        assigned.append((oid, list(b[:4])))
    return assigned, next_id


def reprompt_track(frame_records, detect_at, propagator, params=None) -> dict:
    """detections {frame: [{id, bbox, mask_rle, confidence}]} from re-prompted mask propagation."""
    p = {**PARAMS, **(params or {})}
    n = len(frame_records)
    times = [r["t_ms"] / 1000.0 for r in frame_records]
    prompts = reprompt_frames(frame_records, p["reprompt_every_s"])
    out, live, last_seen, next_id = {}, {}, {}, 0
    for k, start in enumerate(prompts):
        last_segment = k + 1 == len(prompts)
        stop = n - 1 if last_segment else prompts[k + 1]
        boxes = [list(b) for b in detect_at(start) if b[4] >= p["det_score"]]
        assigned, next_id = _new_ids(boxes, live, last_seen, times[start], times, p, next_id)
        for oid, box in assigned:
            propagator.add_box(start, oid, box)
        if next_id == 0:
            continue  # nobody to track yet
        seg = propagator.propagate(start, stop)
        for idx in sorted(seg):
            objs = {int(o): (np.asarray(m, dtype=bool), float(s)) for o, (m, s) in seg[idx].items()
                    if np.asarray(m).any()}
            for o, (m, _) in objs.items():
                last_seen[o] = (idx, mask_box(m))
            if idx < stop or last_segment:
                people = _encode(dedupe(objs, p["duplicate_mask_iou"]))
                if people:
                    out[frame_records[idx]["frame"]] = people
        live = {int(o): mask_box(np.asarray(m, dtype=bool)) for o, (m, _) in seg.get(stop, {}).items()
                if np.asarray(m).any()}
    if next_id == 0:
        raise NoPerson()
    return out


class Sam2Propagator:
    """SAM 2.1 video predictor over the frames dir (record order), masks offloaded to CPU."""

    def __init__(self, frames_dir, frame_records, model_id: str = MODEL_ID):
        import torch
        from huggingface_hub import hf_hub_download
        from sam2.sam2_video_predictor import SAM2VideoPredictor

        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.weights_sha256 = sha256_file(hf_hub_download(model_id, CHECKPOINT))
        self._tmp = tempfile.TemporaryDirectory()
        for i, r in enumerate(frame_records):
            os.symlink((Path(frames_dir) / r["file"]).resolve(), Path(self._tmp.name) / f"{i}.jpg")
        self.predictor = SAM2VideoPredictor.from_pretrained(model_id, device=self.device)
        with self._ctx():
            self.state = self.predictor.init_state(video_path=self._tmp.name, offload_video_to_cpu=True)

    def _ctx(self):
        stack = contextlib.ExitStack()
        stack.enter_context(self.torch.inference_mode())
        if self.device == "cuda":
            stack.enter_context(self.torch.autocast("cuda", dtype=self.torch.bfloat16))
        return stack

    def add_box(self, index: int, obj_id: int, box) -> None:
        with self._ctx():
            self.predictor.add_new_points_or_box(self.state, frame_idx=int(index), obj_id=int(obj_id),
                                                 box=np.asarray(box, dtype=np.float32))

    def propagate(self, start: int, stop: int) -> dict:
        out = {}
        with self._ctx():
            for idx, obj_ids, logits in self.predictor.propagate_in_video(
                    self.state, start_frame_idx=int(start), max_frame_num_to_track=int(stop - start)):
                logits = logits[:, 0].float()
                masks = (logits > 0).cpu().numpy()
                probs = self.torch.sigmoid(logits).cpu().numpy()
                out[int(idx)] = {int(o): (masks[i], float(probs[i][masks[i]].mean()) if masks[i].any() else 0.0)
                                 for i, o in enumerate(obj_ids)}
        return out

    def close(self) -> None:
        self._tmp.cleanup()


class LocalOpen(Tracker):
    name = "local-open"
    mask_source = "sam"
    detector = DETECTOR_NAME
    reprompt_every_s = PARAMS["reprompt_every_s"]
    modules = ("torch", "sam2", "huggingface_hub", "rtmlib", "onnxruntime", "cv2")

    def __init__(self, detector=None, propagator_factory=None, reader=None, params=None, **_):
        self._detector = detector
        self._factory = propagator_factory
        self._read = reader or read_image
        self._params = {**PARAMS, **(params or {})}
        self._sam_sha = None

    def available(self, n_frames=None):
        if self._detector is not None and self._factory is not None:
            return True, ""
        return super().available(n_frames)

    def params(self):
        return dict(self._params)

    def models(self):
        det = getattr(self._detector, "model_record", None)
        return [{"name": "sam2.1-hiera-large", "source": f"https://huggingface.co/{MODEL_ID}",
                 "weights_sha256": self._sam_sha, "licence": "Apache-2.0"}] + ([det()] if det else [])

    def detect(self, frames_dir, frame_records):
        frames_dir = Path(frames_dir)
        det = self._detector = self._detector or PersonDetector()

        def detect_at(i):
            return det(self._read(frames_dir / frame_records[i]["file"]))

        lock = gpu_lock() if self._factory is None else contextlib.nullcontext()
        with lock:
            prop = (self._factory or Sam2Propagator)(frames_dir, frame_records)
            self._sam_sha = getattr(prop, "weights_sha256", None)
            try:
                return reprompt_track(frame_records, detect_at, prop, self._params)
            finally:
                getattr(prop, "close", lambda: None)()
