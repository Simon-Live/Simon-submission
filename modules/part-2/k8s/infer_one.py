"""Smoke inference: SAM 3D Body on one image inside the GPU pod.

Downloads the gated checkpoint (needs HF_TOKEN with approved access), runs the upstream
estimator with the vitdet detector + moge2 FOV estimator, and checks that the 3D keypoints
reproject onto the model's own 2D keypoints (the camera model the Part 2 eval will rely on).

    python /workspace/part2/k8s/infer_one.py [image]   (in user-part2-gpu; `make gpu-smoke`)
"""
import hashlib
import json
import os
import sys
import time

import numpy as np
import torch
from huggingface_hub import snapshot_download

REPO = "/workspace/sam-3d-body"
sys.path.insert(0, REPO)
os.chdir(REPO)  # upstream tools/ resolve paths relative to the repo root

from sam_3d_body import SAM3DBodyEstimator, load_sam_3d_body  # noqa: E402

image = sys.argv[1] if len(sys.argv) > 1 else f"{REPO}/notebook/images/dancing.jpg"
# The official repo is gated; WEIGHTS_REPO may point at a mirror, accepted only if every file
# matches the official SHA-256s (LFS hashes are public even for gated repos).
OFFICIAL_SHA256 = {
    "model.ckpt": "b5a2f9d305dd02626b967aa2e86021fba07065df66ce7a7e00ffb9664f150abf",
    "assets/mhr_model.pt": "352e271a6c42729c68554ceaea0c955e866970160c31e35506d782dc0f7377bc",
}
weights_repo = os.environ.get("WEIGHTS_REPO", "facebook/sam-3d-body-dinov3")
ckpt_dir = "/workspace/checkpoints/sam-3d-body-dinov3"
if not all(os.path.exists(f"{ckpt_dir}/{name}") for name in OFFICIAL_SHA256):
    snapshot_download(weights_repo, local_dir=ckpt_dir)
for name, want in OFFICIAL_SHA256.items():
    h = hashlib.sha256()
    with open(f"{ckpt_dir}/{name}", "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 24), b""):
            h.update(chunk)
    assert h.hexdigest() == want, f"{name} from {weights_repo} does not match the official checksum"
print(f"weights from {weights_repo}: checksums match official", flush=True)

device = torch.device("cuda")
t0 = time.time()
model, model_cfg = load_sam_3d_body(
    f"{ckpt_dir}/model.ckpt", device=device, mhr_path=f"{ckpt_dir}/assets/mhr_model.pt"
)
from tools.build_detector import HumanDetector  # noqa: E402
from tools.build_fov_estimator import FOVEstimator  # noqa: E402

estimator = SAM3DBodyEstimator(
    sam_3d_body_model=model,
    model_cfg=model_cfg,
    human_detector=HumanDetector(name="vitdet", device=device, path=""),
    human_segmentor=None,
    fov_estimator=FOVEstimator(name="moge2", device=device, path=""),
)
t_load = time.time() - t0

t0 = time.time()
people = estimator.process_one_image(image, bbox_thr=0.5, use_mask=False)
torch.cuda.synchronize()
t_infer = time.time() - t0

import cv2  # noqa: E402

h, w = cv2.imread(image).shape[:2]
report = {"image": image, "size": [w, h], "people": len(people), "load_s": round(t_load, 1),
          "infer_s": round(t_infer, 2), "gpu_mem_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2), "per_person": []}
for p in people:
    k3d = np.asarray(p["pred_keypoints_3d"]) + np.asarray(p["pred_cam_t"])  # camera space, metres
    f = float(np.asarray(p["focal_length"]).reshape(-1)[0])
    uv = f * k3d[:, :2] / k3d[:, 2:3] + np.array([w / 2, h / 2])  # pinhole, principal point at centre
    err = np.linalg.norm(uv - np.asarray(p["pred_keypoints_2d"])[:, :2], axis=1)
    report["per_person"].append({
        "n_keypoints": int(k3d.shape[0]), "focal_px": round(f, 1), "cam_t": np.round(p["pred_cam_t"], 3).tolist(),
        "height_3d_m": round(float(np.ptp(np.asarray(p["pred_keypoints_3d"])[:, 1])), 2),
        "self_reproj_px_median": round(float(np.median(err)), 2),
    })
print(json.dumps(report, indent=2))
