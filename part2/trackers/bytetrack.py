"""bytetrack: rtmlib YOLOX person boxes on every frame, ByteTrack association; the mask is the filled box.

Spec: docs/specs/tracker-registry.md (Trackers, locked defaults). ADR-0003, ADR-0005.

The association follows ByteTrack (Zhang et al., ECCV 2022), github.com/ifzhang/ByteTrack,
Copyright (c) 2021 Yifu Zhang, MIT License (LICENSE file fetched 2026-10-28, sha256
e9d83751678cbaba6dfba902ea39215c423d93425e58f8450d6001f7261696f9). It is re-implemented here with numpy
only: a constant-velocity Kalman filter on (cx, cy, aspect, h), a first association of high-score boxes
with score-fused IoU, a second association of low-score boxes, unconfirmed tracks and a lost buffer.

`PersonDetector` is shared with local-open (rtmlib and onnxruntime are imported lazily, at first use).
"""
import hashlib
from pathlib import Path

import numpy as np

from part2.trackers import NoPerson, Tracker

DETECTOR_URL = ("https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/"
                "yolox_x_8xb8-300e_humanart-a39d44ed.zip")
DETECTOR_NAME = "rtmlib-yolox-x-humanart"
# Starting values from the spec, committed before any scoring; never tuned on the class labels.
PARAMS = {
    "track_high_thresh": 0.6,   # first association and track confirmation
    "track_low_thresh": 0.1,    # second association floor
    "new_track_thresh": 0.7,    # ByteTrack's default: high + 0.1
    "match_thresh": 0.8,        # first association: max cost (1 - score * IoU)
    "second_match_thresh": 0.5,  # second association: max cost (1 - IoU)
    "unconfirmed_match_thresh": 0.7,
    "track_buffer_frames": 30,  # frames a lost track is kept for re-identification
    "duplicate_iou": 0.85,      # tracked and lost tracks overlapping above this are duplicates
}


class PersonDetector:
    """rtmlib YOLOX (Human-Art, the CPU backend's detector); returns [[x1, y1, x2, y2, score]] per image."""

    def __init__(self, url: str = DETECTOR_URL, device: str = "cpu"):
        from rtmlib import YOLOX

        self.model = YOLOX(url, model_input_size=(640, 640), backend="onnxruntime", device=device)
        self.path = Path(self.model.onnx_model)
        self._sha = None

    def __call__(self, image) -> np.ndarray:
        padded, ratio = self.model.preprocess(image)
        out = self.model.inference(padded)
        if out[0].ndim != 3 or out[0].shape[-1] != 5:
            raise RuntimeError(f"detector output shape {out[0].shape} not understood (expected (1, N, 5))")
        dets = np.asarray(out[0][0], dtype=np.float64).copy()
        if len(out) > 1:  # labels: keep class 0 (person)
            dets = dets[np.asarray(out[1][0]) == 0]
        dets[:, :4] /= ratio
        return dets

    def weights_sha256(self) -> str:
        if self._sha is None:
            h = hashlib.sha256()
            with self.path.open("rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            self._sha = h.hexdigest()
        return self._sha

    def model_record(self) -> dict:
        return {"name": DETECTOR_NAME, "source": DETECTOR_URL, "weights_sha256": self.weights_sha256(),
                "licence": "Apache-2.0 (MMPose/MMDetection)"}


def read_image(path):
    import cv2

    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"cannot read frame {path}")
    return img


# --- ByteTrack association -------------------------------------------------------------------------

class _Kalman:
    """Constant-velocity filter on (cx, cy, a, h) and their velocities (ByteTrack's KalmanFilter)."""
    pos_w, vel_w = 1.0 / 20, 1.0 / 160

    def __init__(self):
        self.F = np.eye(8)
        self.F[:4, 4:] = np.eye(4)
        self.H = np.eye(4, 8)

    def initiate(self, z):
        h = z[3]
        std = [2 * self.pos_w * h, 2 * self.pos_w * h, 1e-2, 2 * self.pos_w * h,
               10 * self.vel_w * h, 10 * self.vel_w * h, 1e-5, 10 * self.vel_w * h]
        return np.r_[z, np.zeros(4)], np.diag(np.square(std))

    def predict(self, mean, cov):
        h = mean[3]
        q = np.diag(np.square([self.pos_w * h, self.pos_w * h, 1e-2, self.pos_w * h,
                               self.vel_w * h, self.vel_w * h, 1e-5, self.vel_w * h]))
        return self.F @ mean, self.F @ cov @ self.F.T + q

    def update(self, mean, cov, z):
        h = mean[3]
        r = np.diag(np.square([self.pos_w * h, self.pos_w * h, 1e-1, self.pos_w * h]))
        s = self.H @ cov @ self.H.T + r
        gain = np.linalg.solve(s, (cov @ self.H.T).T).T
        return mean + gain @ (z - self.H @ mean), cov - gain @ s @ gain.T


def _xyah(tlwh):
    x, y, w, h = tlwh
    return np.array([x + w / 2, y + h / 2, w / max(h, 1e-6), h], dtype=np.float64)


class _Track:
    def __init__(self, tlwh, score):
        self.det_tlwh = np.asarray(tlwh, dtype=np.float64)
        self.score = float(score)
        self.mean = self.cov = None
        self.id = None
        self.state = "new"
        self.activated = False
        self.frame = self.start = 0

    @property
    def tlwh(self):
        if self.mean is None:
            return self.det_tlwh.copy()
        cx, cy, a, h = self.mean[:4]
        w = a * h
        return np.array([cx - w / 2, cy - h / 2, w, h])

    @property
    def tlbr(self):
        x, y, w, h = self.tlwh
        return np.array([x, y, x + w, y + h])


def _iou_matrix(a, b) -> np.ndarray:
    """IoU between two lists of [x1, y1, x2, y2] boxes."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    ix = np.clip(np.minimum(a[:, None, 2], b[None, :, 2]) - np.maximum(a[:, None, 0], b[None, :, 0]), 0, None)
    iy = np.clip(np.minimum(a[:, None, 3], b[None, :, 3]) - np.maximum(a[:, None, 1], b[None, :, 1]), 0, None)
    inter = ix * iy
    area = lambda m: (m[:, 2] - m[:, 0]) * (m[:, 3] - m[:, 1])  # noqa: E731
    union = area(a)[:, None] + area(b)[None, :] - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-12), 0.0)


def _hungarian(cost: np.ndarray) -> list[int]:
    """Minimum-cost assignment for a square matrix: row i -> column result[i] (shortest augmenting paths)."""
    n = cost.shape[0]
    u, v = np.zeros(n + 1), np.zeros(n + 1)
    p, way = np.zeros(n + 1, dtype=int), np.zeros(n + 1, dtype=int)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, used = np.full(n + 1, np.inf), np.zeros(n + 1, dtype=bool)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], np.inf, 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0 - 1, j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    result = [0] * n
    for j in range(1, n + 1):
        result[p[j] - 1] = j - 1
    return result


def linear_assignment(cost: np.ndarray, thresh: float):
    """Matches with cost <= thresh, minimising total cost (lap.lapjv with extend_cost and cost_limit)."""
    n, m = cost.shape
    if n == 0 or m == 0:
        return [], list(range(n)), list(range(m))
    big = 1e6
    size = n + m
    ext = np.full((size, size), big)
    ext[:n, :m] = np.where(cost <= thresh, cost, big)
    ext[:n, m:] = np.where(np.eye(n), thresh / 2, big)
    ext[n:, :m] = np.where(np.eye(m), thresh / 2, big)
    ext[n:, m:] = 0.0
    assign = _hungarian(ext)
    matches = [(i, j) for i, j in enumerate(assign[:n]) if j < m and cost[i, j] <= thresh]
    mi, mj = {i for i, _ in matches}, {j for _, j in matches}
    return matches, [i for i in range(n) if i not in mi], [j for j in range(m) if j not in mj]


class ByteTracker:
    """Online association over per-frame detections [[x1, y1, x2, y2, score]]."""

    def __init__(self, params: dict | None = None):
        self.p = {**PARAMS, **(params or {})}
        self.kf = _Kalman()
        self.tracked, self.lost = [], []
        self.frame = 0
        self.next_id = 0

    def _activate(self, t: _Track):
        t.id, self.next_id = self.next_id, self.next_id + 1
        t.mean, t.cov = self.kf.initiate(_xyah(t.det_tlwh))
        t.state, t.activated = "tracked", self.frame == 1
        t.frame = t.start = self.frame

    def _update(self, t: _Track, det: _Track):
        t.mean, t.cov = self.kf.update(t.mean, t.cov, _xyah(det.det_tlwh))
        t.state, t.activated, t.frame, t.score = "tracked", True, self.frame, det.score

    @staticmethod
    def _cost(tracks, dets, fuse: bool):
        iou = _iou_matrix([t.tlbr for t in tracks], [d.tlbr for d in dets])
        if fuse and len(dets):
            iou = iou * np.array([d.score for d in dets])[None, :]
        return 1.0 - iou

    def update(self, dets) -> list[_Track]:
        self.frame += 1
        p = self.p
        dets = np.asarray(dets, dtype=np.float64).reshape(-1, 5)
        to_track = lambda rows: [_Track([x1, y1, x2 - x1, y2 - y1], s) for x1, y1, x2, y2, s in rows]  # noqa: E731
        high = to_track(dets[dets[:, 4] > p["track_high_thresh"]])
        low = to_track(dets[(dets[:, 4] > p["track_low_thresh"]) & (dets[:, 4] <= p["track_high_thresh"])])

        unconfirmed = [t for t in self.tracked if not t.activated]
        confirmed = [t for t in self.tracked if t.activated]
        pool = confirmed + [t for t in self.lost if t not in confirmed]
        for t in pool:
            mean = t.mean.copy()
            if t.state != "tracked":
                mean[7] = 0
            t.mean, t.cov = self.kf.predict(mean, t.cov)

        active, refound, newly_lost, removed = [], [], [], []
        matches, u_track, u_det = linear_assignment(self._cost(pool, high, True), p["match_thresh"])
        for i, j in matches:
            (active if pool[i].state == "tracked" else refound).append(pool[i])
            self._update(pool[i], high[j])

        remaining = [pool[i] for i in u_track if pool[i].state == "tracked"]
        matches, u_rem, _ = linear_assignment(self._cost(remaining, low, False), p["second_match_thresh"])
        for i, j in matches:
            active.append(remaining[i])
            self._update(remaining[i], low[j])
        for i in u_rem:
            remaining[i].state = "lost"
            newly_lost.append(remaining[i])

        left = [high[j] for j in u_det]
        matches, u_unc, u_new = linear_assignment(self._cost(unconfirmed, left, True), p["unconfirmed_match_thresh"])
        for i, j in matches:
            self._update(unconfirmed[i], left[j])
            active.append(unconfirmed[i])
        for i in u_unc:
            unconfirmed[i].state = "removed"
            removed.append(unconfirmed[i])

        for j in u_new:
            if left[j].score >= p["new_track_thresh"]:
                self._activate(left[j])
                active.append(left[j])

        for t in self.lost:
            if t.state == "lost" and self.frame - t.frame > p["track_buffer_frames"]:
                t.state = "removed"
                removed.append(t)

        keep = [t for t in self.tracked if t.state == "tracked" and t not in removed]
        self.tracked = keep + [t for t in active + refound if t not in keep]
        self.lost = [t for t in self.lost + newly_lost if t.state == "lost" and t not in self.tracked]
        self._drop_duplicates()
        return [t for t in self.tracked if t.activated]

    def _drop_duplicates(self):
        iou = _iou_matrix([t.tlbr for t in self.tracked], [t.tlbr for t in self.lost])
        drop_a, drop_b = set(), set()
        for i, j in zip(*np.where(iou > self.p["duplicate_iou"])):
            a, b = self.tracked[i], self.lost[j]
            if a.frame - a.start > b.frame - b.start:
                drop_b.add(j)  # keep the longer-lived track
            else:
                drop_a.add(i)
        self.tracked = [t for i, t in enumerate(self.tracked) if i not in drop_a]
        self.lost = [t for j, t in enumerate(self.lost) if j not in drop_b]


# --- the tracker adapter ---------------------------------------------------------------------------

def box_detection(track_id: int, tlwh, score: float, height: int, width: int):
    """A detection record with the box clipped to the image and its filled box as the mask, or None."""
    x, y, w, h = (float(v) for v in tlwh)
    x0, y0 = max(0.0, x), max(0.0, y)
    x1, y1 = min(float(width), x + w), min(float(height), y + h)
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[int(np.floor(y0)):int(np.ceil(y1)), int(np.floor(x0)):int(np.ceil(x1))] = 1
    return {"id": int(track_id), "bbox": [x0, y0, x1 - x0, y1 - y0], "mask": mask,
            "confidence": float(min(max(score, 0.0), 1.0))}


class ByteTrack(Tracker):
    name = "bytetrack"
    mask_source = "box"
    detector = DETECTOR_NAME
    modules = ("rtmlib", "onnxruntime", "cv2")

    def __init__(self, detector=None, reader=None, params=None, **_):
        self._detector = detector  # callable(image) -> [[x1, y1, x2, y2, score]]; default PersonDetector
        self._read = reader or read_image
        self._params = {**PARAMS, **(params or {})}

    def available(self, n_frames=None):
        if self._detector is not None:
            return True, ""
        return super().available(n_frames)

    def params(self):
        return dict(self._params)

    def models(self):
        rec = getattr(self._detector, "model_record", None)
        return [rec()] if rec else [{"name": DETECTOR_NAME, "source": DETECTOR_URL, "weights_sha256": None,
                                     "licence": "Apache-2.0 (MMPose/MMDetection)"}]

    def detect(self, frames_dir, frame_records):
        from part2 import track as track_mod

        if self._detector is None:
            self._detector = PersonDetector()
        tracker = ByteTracker(self._params)
        out = {}
        for r in frame_records:
            img = self._read(Path(frames_dir) / r["file"])
            height, width = img.shape[:2]
            people = []
            for t in tracker.update(self._detector(img)):
                d = box_detection(t.id, t.tlwh, t.score, height, width)
                if d is not None:
                    people.append({**{k: v for k, v in d.items() if k != "mask"},
                                   "mask_rle": track_mod.mask_to_rle(d["mask"])})
            if people:
                out[r["frame"]] = people
        if not out:
            raise NoPerson()
        return out
