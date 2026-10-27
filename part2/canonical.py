"""body3d.json (camera space) -> pose3d.json (shared canonical frame) + camera.json (sidecar).

Canonical frame, per frame and person (README): origin at the hip midpoint; y = world up;
x = subject's left (left-hip minus right-hip, made horizontal); z = x × y (anterior). Metres.

World up is the camera's up (-y in OpenCV camera space), i.e. a level camera is assumed.

camera.json keeps what the canonical frame drops, so joints can be projected back to pixels:
  {camera_frame: "opencv", K, image_size,
   frames: [{frame, people: [{id, R, t}]}]}   with  p_cam = R @ p_canonical + t

conf: SAM 3D Body gives no per-joint confidence. A joint gets 1.0 when its 2D keypoint lies
inside the image and OUTSIDE_CONF when the model placed it outside (extrapolated).
"""
import json
from pathlib import Path

import numpy as np

from part2.joints import CANONICAL
from part2.schema import validate_pose3d

CAMERA_UP = np.array([0.0, -1.0, 0.0])
OUTSIDE_CONF = 0.3
LH, RH = CANONICAL.index("left_hip"), CANONICAL.index("right_hip")


def frame_axes(kp3d_cam: np.ndarray, up=CAMERA_UP) -> tuple[np.ndarray, np.ndarray]:
    """Rotation R (canonical -> camera, columns = canonical x, y, z in camera coords) and origin t."""
    t = (kp3d_cam[LH] + kp3d_cam[RH]) / 2
    y = up / np.linalg.norm(up)
    x = kp3d_cam[LH] - kp3d_cam[RH]
    x = x - x.dot(y) * y
    n = np.linalg.norm(x)
    if n < 1e-6:
        raise ValueError("hip line is vertical; subject's left is undefined")
    x /= n
    z = np.cross(x, y)
    return np.stack([x, y, z], axis=1), t


def to_canonical(kp3d_cam: np.ndarray, R: np.ndarray, t: np.ndarray) -> np.ndarray:
    return (kp3d_cam - t) @ R  # R is orthonormal: p_can = R.T @ (p_cam - t)


def to_camera(kp_can: np.ndarray, R: np.ndarray, t: np.ndarray) -> np.ndarray:
    return kp_can @ R.T + t


def convert(body3d: dict, smooth: bool = False) -> tuple[dict, dict]:
    """Return (pose3d, camera) documents for a body3d.json document."""
    w, h = body3d["image_size"]
    frames = body3d["frames"]
    if smooth:
        frames = smooth_tracks(frames)
    pose_frames, cam_frames = [], []
    for f in frames:
        people, cams = [], []
        for p in f["people"]:
            kp = np.array([p["kp3d_cam"][j] for j in CANONICAL], dtype=float)
            uv = np.array([p["kp2d"][j] for j in CANONICAL], dtype=float)
            R, t = frame_axes(kp)
            can = to_canonical(kp, R, t)
            inside = (uv[:, 0] >= 0) & (uv[:, 0] < w) & (uv[:, 1] >= 0) & (uv[:, 1] < h)
            people.append({"id": p["id"], "joints": {
                j: {"x": round(float(c[0]), 4), "y": round(float(c[1]), 4), "z": round(float(c[2]), 4),
                    "conf": 1.0 if ok else OUTSIDE_CONF}
                for j, c, ok in zip(CANONICAL, can, inside)}})
            cams.append({"id": p["id"], "R": np.round(R, 6).tolist(), "t": np.round(t, 5).tolist()})
        pose_frames.append({"frame": f["frame"], "t_ms": f["t_ms"], "people": people})
        cam_frames.append({"frame": f["frame"], "people": cams})
    pose3d = {"frames": pose_frames}
    validate_pose3d(pose3d)
    camera = {"camera_frame": body3d["camera_frame"], "K": body3d["K"], "image_size": body3d["image_size"],
              "frames": cam_frames}
    return pose3d, camera


def write(body3d_path, out_dir, smooth: bool = False) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    pose3d, camera = convert(json.loads(Path(body3d_path).read_text()), smooth=smooth)
    paths = out_dir / "pose3d.json", out_dir / "camera.json"
    paths[0].write_text(json.dumps(pose3d))
    paths[1].write_text(json.dumps(camera))
    return paths


def project_pose3d(pose3d: dict, camera: dict) -> dict:
    """{(frame, id): {joint: [u, v]}}: canonical joints back to pixels via camera.json."""
    K = np.array(camera["K"], dtype=float)
    cams = {(f["frame"], c["id"]): c for f in camera["frames"] for c in f["people"]}
    out = {}
    for f in pose3d["frames"]:
        for p in f["people"]:
            c = cams[(f["frame"], p["id"])]
            can = np.array([[p["joints"][j][k] for k in "xyz"] for j in CANONICAL])
            cam = to_camera(can, np.array(c["R"]), np.array(c["t"]))
            uv = cam[:, :2] / cam[:, 2:3] * [K[0, 0], K[1, 1]] + [K[0, 2], K[1, 2]]
            out[(f["frame"], p["id"])] = {j: q.tolist() for j, q in zip(CANONICAL, uv)}
    return out


def smooth_tracks(frames: list[dict], min_cutoff: float = 1.0, beta: float = 0.5) -> list[dict]:
    """One-Euro filter on camera-space joints per person id (before canonicalisation, so the
    per-frame axes are computed from smoothed hips). 2D keypoints are left as measured."""
    filters: dict = {}
    out = []
    for f in frames:
        people = []
        for p in f["people"]:
            kp = np.array([p["kp3d_cam"][j] for j in CANONICAL], dtype=float)
            filt = filters.setdefault(p["id"], OneEuro(min_cutoff, beta))
            sm = filt(kp, f["t_ms"] / 1000)
            people.append({**p, "kp3d_cam": {j: v.tolist() for j, v in zip(CANONICAL, sm)}})
        out.append({**f, "people": people})
    return out


class OneEuro:
    """One-Euro filter (Casiez et al. 2012) on arrays; timestamps in seconds."""

    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float = 1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x = self.dx = self.t = None

    @staticmethod
    def _alpha(cutoff, dt):
        r = 2 * np.pi * cutoff * dt
        return r / (r + 1)

    def __call__(self, x, t):
        if self.x is None or t <= self.t:
            self.x, self.dx, self.t = x, np.zeros_like(x), t
            return x
        dt = t - self.t
        dx = (x - self.x) / dt
        self.dx = self.dx + self._alpha(self.d_cutoff, dt) * (dx - self.dx)
        cutoff = self.min_cutoff + self.beta * np.abs(self.dx)
        self.x = self.x + self._alpha(cutoff, dt) * (x - self.x)
        self.t = t
        return self.x
