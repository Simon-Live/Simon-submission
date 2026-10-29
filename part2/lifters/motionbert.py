"""Lifter C `motionbert`: MotionBERT-Lite (DSTformer) on the RTMPose 2D sequence, torch on CPU.

Spec: docs/specs/backends-gpu-cpu.md ("Lifter C"); ADR-0002, ADR-0005 (licence caveat), ASM-012.

Weights and the two model source files come from the Hugging Face repo walterzhu/MotionBERT at a pinned
revision (no login), are checked against pinned SHA-256 digests and live under ~/.cache only
(MOTIONBERT_DIR overrides). The checkpoint is the one MotionBERT's docs/inference.md names for
in-the-wild 3D pose (FT_MB_lite_MB_ft_h36m_global_lite); settings from its config
MB_ft_h36m_global_lite.yaml (flip test-time augmentation on, confidence channel on).

Pipeline per person: COCO-17 -> H36M-17 (H36M_FROM_COCO), x and y mapped to [-1, 1] by MotionBERT's
in-the-wild crop_scale (the clip's 2D extent, scale_range [1, 1]), confidence clipped to [0, 1]; windows of 243
frames overlapping by half, the middle of each kept, a short clip padded with its edge frames; output
H36M-17 -> COCO-17 (h36m_to_coco), made hip-midpoint relative, scaled so the mean of the 12 body bones
equals lifter B's fitted mean, and placed by the root depth search (part2.lifters.place_root).
torch loads only inside MotionBert.network().

Deviation from the spec text ("normalised to [-1, 1] by the image size"), chosen label-free on the single
fixture's 2D: crop_scale gave output x, y within 0.057 of the input 2D (fraction of body span) and a mean
H36M bone CV of 0.163, against 0.127 and 0.178 for centring on the image and dividing by min(w, h) / 2.
"""
import hashlib
import importlib.util
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

import numpy as np

from part2.lifters import J, bone_lengths, hip_mid, place_root, rays
from part2.lifters.fixed_bones import CONF_MIN, fit_lengths

NAME = "motionbert"
REPO = "walterzhu/MotionBERT"
REVISION = "370a9196aa3c89198b134c82476143b01c0fb32c"
CHECKPOINT = "checkpoint/pose3d/FT_MB_lite_MB_ft_h36m_global_lite/best_epoch.bin"
FILES = {  # measured at TICKET-015 on 2026-10-28
    CHECKPOINT: "9811155371db4ca5d20f31a36a232d41012e12e1333882888a564d741861148f",
    "lib/model/DSTformer.py": "0896b29872b10f55be8902ceceacb9febe7876fa2065d5f9dd670fbb902f2f47",
    "lib/model/drop.py": "44b1af7912ae46c62c5b74712dae31697afc697e788c8dd9c5050602a2397173",
    "LICENSE": "045ee95b545fb51f5c6e28e1a50644fe618f6278f3c8720852c6fe96f53b472f",
}
NET = {"dim_in": 3, "dim_out": 3, "dim_feat": 256, "dim_rep": 512, "depth": 5, "num_heads": 8, "mlp_ratio": 4,
       "num_joints": 17, "maxlen": 243}  # MB_ft_h36m_global_lite.yaml; LayerNorm eps 1e-6 (lib/utils/learning.py)
WINDOW = 243
FLIP = True
LICENCE_NOTE = ("MotionBERT (lifter C): Apache-2.0 code; checkpoint FT_MB_lite_MB_ft_h36m_global_lite is trained on "
                "Human3.6M, whose terms are research-only; accepted with this caveat by the operator on #336 "
                "(2026-10-28, ADR-0005).")
SETUP_MESSAGE = "the cpu backend needs make setup-cpu"

# H36M index -> COCO-17 sources averaged (spec table); 7 (spine) is the mean of 0 and 8.
H36M_FROM_COCO = {
    0: ["left_hip", "right_hip"], 1: ["right_hip"], 2: ["right_knee"], 3: ["right_ankle"],
    4: ["left_hip"], 5: ["left_knee"], 6: ["left_ankle"], 8: ["left_shoulder", "right_shoulder"], 9: ["nose"],
    10: ["left_eye", "right_eye", "left_ear", "right_ear"], 11: ["left_shoulder"], 12: ["left_elbow"],
    13: ["left_wrist"], 14: ["right_shoulder"], 15: ["right_elbow"], 16: ["right_wrist"],
}
SPINE, THORAX, NOSE, HEAD = 7, 8, 9, 10
COCO_FROM_H36M = {"right_hip": 1, "right_knee": 2, "right_ankle": 3, "left_hip": 4, "left_knee": 5, "left_ankle": 6,
                  "nose": 9, "left_shoulder": 11, "left_elbow": 12, "left_wrist": 13, "right_shoulder": 14,
                  "right_elbow": 15, "right_wrist": 16}
HEAD_POINTS = ["left_eye", "right_eye", "left_ear", "right_ear"]
FLIP_LEFT, FLIP_RIGHT = [4, 5, 6, 11, 12, 13], [1, 2, 3, 14, 15, 16]  # MotionBERT utils_data.flip_data


def cache_dir() -> Path:
    return Path(os.environ.get("MOTIONBERT_DIR") or Path.home() / ".cache" / "simon-part-2" / "motionbert" / REVISION)


def coco_to_h36m(x) -> np.ndarray:
    """(n, 17, C) COCO-17 -> (n, 17, C) H36M-17; every channel (coordinates and confidence) averaged."""
    x = np.asarray(x, float)
    y = np.zeros_like(x)
    for h, src in H36M_FROM_COCO.items():
        y[:, h] = x[:, [J[s] for s in src]].mean(axis=1)
    y[:, SPINE] = (y[:, 0] + y[:, THORAX]) / 2
    return y


def h36m_to_coco(y3d, head_offsets) -> np.ndarray:
    """(n, 17, 3) H36M-17 -> (n, 17, 3) COCO-17. Eyes and ears: the lifted head point plus each one's 2D
    offset from the 2D head point (head_offsets (n, 4, 2), same units), at the head's depth."""
    y3d = np.asarray(y3d, float)
    out = np.zeros_like(y3d)
    for name, h in COCO_FROM_H36M.items():
        out[:, J[name]] = y3d[:, h]
    for k, name in enumerate(HEAD_POINTS):
        out[:, J[name], :2] = y3d[:, HEAD, :2] + head_offsets[:, k]
        out[:, J[name], 2] = y3d[:, HEAD, 2]
    return out


def head_offsets(x2d) -> np.ndarray:
    """(n, 17, 2) COCO 2D -> (n, 4, 2): each eye and ear minus the mean of the four (the H36M head point)."""
    pts = np.asarray(x2d, float)[:, [J[n] for n in HEAD_POINTS]]
    return pts - pts.mean(axis=1, keepdims=True)


def normalise(kp2d) -> np.ndarray:
    """MotionBERT's crop_scale (lib/utils/utils_data.py, scale_range [1, 1]): the square around the clip's
    2D extent maps to [-1, 1]."""
    kp2d = np.asarray(kp2d, float)
    pts = kp2d.reshape(-1, 2)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    side = max(float((hi - lo).max()), 1e-6)
    return np.clip(((kp2d - (lo + hi - side) / 2) / side - 0.5) * 2, -1, 1)


def windows(n: int, size: int = WINDOW) -> list[tuple[np.ndarray, int, int, int]]:
    """[(frame indices (size,), first kept window position, first kept frame, count)]: overlapping by half,
    each frame kept exactly once from the middle part of a window; a clip shorter than size is padded by
    repeating its edge frames."""
    if n <= size:
        before = (size - n) // 2
        return [(np.clip(np.arange(size) - before, 0, n - 1), before, 0, n)]
    starts = sorted(set(list(range(0, n - size, size // 2)) + [n - size]))
    cuts = [0] + [(a + b + size) // 2 for a, b in zip(starts, starts[1:])] + [n]
    return [(np.arange(s, s + size), lo - s, lo, hi - lo) for s, lo, hi in zip(starts, cuts, cuts[1:])]


def flip(x) -> np.ndarray:
    """Mirror x (first channel) and swap left and right H36M joints (MotionBERT's flip_data)."""
    y = np.array(x, dtype=float, copy=True)
    y[..., 0] *= -1
    y[..., FLIP_LEFT + FLIP_RIGHT, :] = y[..., FLIP_RIGHT + FLIP_LEFT, :]
    return y


class MotionBert:
    name = NAME
    _net = None  # loaded once per process

    def __init__(self, net=None):
        """net: callable (B, T, 17, 3) float array -> (B, T, 17, 3), for tests; None loads MotionBERT."""
        self.net = net

    def available(self) -> tuple[bool, str]:
        if importlib.util.find_spec("torch") is None:
            return False, SETUP_MESSAGE
        return True, f"torch importable; weights {'cached' if self._cached() else 'download on first use'} in {cache_dir()}"

    def models(self) -> list:
        return [{"name": "MotionBERT-Lite 3D pose (FT_MB_lite_MB_ft_h36m_global_lite)", "source": _url(CHECKPOINT),
                 "weights_sha256": FILES[CHECKPOINT],
                 "licence": "Apache-2.0 code; Human3.6M training data under research-only terms"}]

    def licence_notes(self) -> list:
        return [LICENCE_NOTE]

    def lift(self, kp2d, conf, K, image_size, fps=None) -> np.ndarray:
        return self.lift_info(kp2d, conf, K, image_size, fps)[0]

    def lift_info(self, kp2d, conf, K, image_size, fps=None) -> tuple[np.ndarray, dict]:
        kp2d, conf = np.asarray(kp2d, float), np.asarray(conf, float)
        if kp2d.ndim != 3 or kp2d.shape[1:] != (17, 2) or conf.shape != kp2d.shape[:2] or not len(kp2d):
            raise ValueError(f"motionbert: expected kp2d (n, 17, 2) and conf (n, 17), got {kp2d.shape}, {conf.shape}")
        x2d = normalise(kp2d)
        inp = coco_to_h36m(np.concatenate([x2d, np.clip(conf, 0, 1)[..., None]], axis=-1))
        out = np.zeros((len(kp2d), 17, 3))
        for idx, pos, first, count in windows(len(kp2d)):
            out[first:first + count] = self.predict(inp[idx][None])[0, pos:pos + count]
        coco = h36m_to_coco(out, head_offsets(x2d))
        rel = coco - hip_mid(coco)[:, None]
        lengths, _, fit = fit_lengths(rays(kp2d, K)[..., :2], conf >= CONF_MIN)
        scale = float(lengths.mean() / bone_lengths(rel).mean())
        cam = place_root(rel * scale, kp2d, conf, K)
        return cam, {"lifter": NAME, "checkpoint": CHECKPOINT, "revision": REVISION, "flip": FLIP,
                     "windows": len(windows(len(kp2d))), "scale_m_per_unit": round(scale, 4),
                     "target_bone_mean_m": round(float(lengths.mean()), 4), "fallback_bones": fit["fallback_bones"],
                     "root_depth_m": [round(float(v), 3) for v in np.percentile(hip_mid(cam)[:, 2], [0, 50, 100])]}

    def predict(self, x) -> np.ndarray:
        """(B, T, 17, 3) normalised H36M input -> (B, T, 17, 3), averaged with the flipped pass (FLIP)."""
        net = self.net or self.network()
        y = np.asarray(net(x), float)
        if FLIP:
            y = (y + flip(np.asarray(net(flip(x)), float))) / 2
        return y

    def network(self):
        if MotionBert._net is None:
            MotionBert._net = _load_network(ensure_files())
        return MotionBert._net

    @staticmethod
    def _cached() -> bool:
        return all((cache_dir() / f).is_file() for f in FILES)


def _url(rel: str) -> str:
    return f"https://huggingface.co/{REPO}/resolve/{REVISION}/{rel}"


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_files(root: Path | None = None, fetch=None) -> Path:
    """Download any missing pinned file into the cache and check every digest; returns the cache root."""
    root = Path(root or cache_dir())
    fetch = fetch or _fetch
    for rel, digest in FILES.items():
        path = root / rel
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            fetch(_url(rel), path)
        if sha256(path) != digest:
            raise RuntimeError(f"motionbert: {path} does not match its pinned SHA-256; delete it and rerun")
    return root


def _fetch(url: str, path: Path) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".part-")
    try:
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(url, timeout=60) as resp:
            for chunk in iter(lambda: resp.read(1 << 20), b""):
                out.write(chunk)
        os.replace(tmp, path)
    except OSError as e:
        raise RuntimeError(f"could not download MotionBERT weights from {url} ({e})") from None
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _load_network(root: Path):
    """DSTformer from the pinned source with the pinned checkpoint, eval mode, wrapped numpy in, numpy out."""
    from functools import partial

    import torch
    from torch import nn

    sys.path.insert(0, str(root))
    try:
        from lib.model.DSTformer import DSTformer
    finally:
        sys.path.remove(str(root))
    model = DSTformer(**NET, norm_layer=partial(nn.LayerNorm, eps=1e-6))
    state = torch.load(root / CHECKPOINT, map_location="cpu", weights_only=True)["model_pos"]
    model.load_state_dict({k.removeprefix("module."): v for k, v in state.items()}, strict=True)
    model.eval()

    def run(x):
        with torch.no_grad():
            return model(torch.as_tensor(np.asarray(x), dtype=torch.float32)).numpy()

    return run
