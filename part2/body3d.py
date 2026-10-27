"""SAM 3D Body per frame -> camera-space 17-joint poses (body3d.json). Runs on the GPU pod.

body3d.json:
  {model, camera_frame: "opencv" (x right, y down, z forward, metres),
   K: 3x3 intrinsics (fixed for the clip), image_size: [w, h],
   frames: [{frame, t_ms, people: [{id, bbox: [x, y, w, h],
             kp3d_cam: {<joint>: [x, y, z]}, kp2d: {<joint>: [u, v]}, reproj_self_px}]}]}

kp3d_cam projects through K onto kp2d (reproj_self_px is the median gap, a sanity check).
#9 turns this into pose3d.json + camera.json.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np

from part2 import frames as frames_mod
from part2.joints import CANONICAL, MHR70_INDEX

SAM3D_REPO = os.environ.get("SAM3D_REPO", "/workspace/sam-3d-body")
CKPT_DIR = os.environ.get("SAM3D_CKPT", "/workspace/checkpoints/sam-3d-body-dinov3")
INTRINSICS_SAMPLES = 5


def load_estimator():
    """SAM 3D Body with the ViTDet person detector and MoGe-2 field-of-view estimator."""
    import torch

    sys.path.insert(0, SAM3D_REPO)
    cwd = os.getcwd()
    os.chdir(SAM3D_REPO)  # upstream tools/ resolve config paths relative to the repo root
    try:
        from sam_3d_body import SAM3DBodyEstimator, load_sam_3d_body
        from tools.build_detector import HumanDetector
        from tools.build_fov_estimator import FOVEstimator

        device = torch.device("cuda")
        model, cfg = load_sam_3d_body(f"{CKPT_DIR}/model.ckpt", device=device, mhr_path=f"{CKPT_DIR}/assets/mhr_model.pt")
        return SAM3DBodyEstimator(
            sam_3d_body_model=model, model_cfg=cfg,
            human_detector=HumanDetector(name="vitdet", device=device, path=""),
            human_segmentor=None,
            fov_estimator=FOVEstimator(name="moge2", device=device, path=""),
        )
    finally:
        os.chdir(cwd)


def estimate(frames_dir, out_path, boxes=None, estimator=None) -> dict:
    """Run SAM 3D Body on every frame and write body3d.json.

    boxes: {frame: {id: [x, y, w, h]}} to run on given people (multi-person, from tracks.json).
    Without it, one person per frame becomes id 0 (one-person mode, see choose_subject).
    Assumes fixed intrinsics (no zoom/crop) for the whole frames_dir.
    """
    import cv2
    import torch

    frames_dir = Path(frames_dir)
    recs = frames_mod.load(frames_dir)
    est = estimator or load_estimator()
    images = {r["frame"]: frames_dir / r["file"] for r in recs}

    h, w = _read(images[recs[0]["frame"]]).shape[:2]
    K = clip_intrinsics(est, [images[r["frame"]] for r in recs])
    cam_int = torch.tensor(K[None], dtype=torch.float32)

    out_frames, prev = [], None
    for r in recs:
        bgr = _read(images[r["frame"]])
        if boxes is not None:
            given = boxes.get(r["frame"], boxes.get(str(r["frame"]), {}))
            ids = list(given)
            xyxy = np.array([[x, y, x + bw, y + bh] for x, y, bw, bh in given.values()], dtype=np.float32)
        else:
            dets = est.detector.run_human_detection(bgr, det_cat_id=0, bbox_thr=0.5, nms_thr=0.3,
                                                    default_to_full_image=False)
            if len(dets):
                pick = choose_subject(dets, prev)
                xyxy, ids, prev = dets[[pick]].astype(np.float32), [0], dets[pick]
            else:
                xyxy, ids = np.zeros((0, 4), np.float32), []
        people = []
        if len(ids):
            outs = est.process_one_image(str(images[r["frame"]]), bboxes=xyxy, cam_int=cam_int)
            if len(outs) != len(ids):
                raise RuntimeError(f"frame {r['frame']}: {len(ids)} boxes in, {len(outs)} people out")
            people = [_person(pid, o, K) for pid, o in zip(ids, outs)]
        out_frames.append({"frame": r["frame"], "t_ms": r["t_ms"], "people": people})

    result = {"model": "sam-3d-body-dinov3", "camera_frame": "opencv", "K": np.round(K, 3).tolist(),
              "image_size": [w, h], "frames": out_frames}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(result))
    return result


def _read(path):
    import cv2

    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"cannot read image {path}")
    return img


def choose_subject(dets: np.ndarray, prev) -> int:
    """One-person mode: the detection that best continues last frame's subject (IoU > 0.3),
    else the largest, so a passer-by closer to the camera doesn't take over."""
    if prev is not None:
        ious = [iou_xyxy(d, prev) for d in dets]
        if max(ious) > 0.3:
            return int(np.argmax(ious))
    return int(np.argmax((dets[:, 2] - dets[:, 0]) * (dets[:, 3] - dets[:, 1])))


def iou_xyxy(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return float(inter / union) if union > 0 else 0.0


def clip_intrinsics(est, image_paths) -> np.ndarray:
    """One K for the whole clip (fixed camera): median of MoGe-2 estimates on evenly spaced frames,
    so focal length doesn't jitter frame to frame."""
    import cv2

    picks = [image_paths[int(i)] for i in np.linspace(0, len(image_paths) - 1, min(INTRINSICS_SAMPLES, len(image_paths)))]
    Ks = []
    for p in picks:
        rgb = cv2.cvtColor(_read(p), cv2.COLOR_BGR2RGB)
        Ks.append(np.asarray(est.fov_estimator.get_cam_intrinsics(rgb)).reshape(3, 3))
    return np.median(np.stack(Ks), axis=0)


def _person(pid, o, K) -> dict:
    kp3d = np.asarray(o["pred_keypoints_3d"])[MHR70_INDEX] + np.asarray(o["pred_cam_t"])
    kp2d = np.asarray(o["pred_keypoints_2d"])[MHR70_INDEX, :2]
    uv = project(kp3d, K)
    x0, y0, x1, y1 = (float(v) for v in np.asarray(o["bbox"]).reshape(-1)[:4])
    return {
        "id": int(pid) if str(pid).isdigit() else pid,  # tracks.json ids arrive as JSON-object keys
        "bbox": [round(x0, 1), round(y0, 1), round(x1 - x0, 1), round(y1 - y0, 1)],
        "kp3d_cam": {j: np.round(p, 4).tolist() for j, p in zip(CANONICAL, kp3d)},
        "kp2d": {j: np.round(p, 2).tolist() for j, p in zip(CANONICAL, kp2d)},
        "reproj_self_px": round(float(np.median(np.linalg.norm(uv - kp2d, axis=1))), 3),
    }


def project(points_cam, K) -> np.ndarray:
    """Pinhole projection of Nx3 OpenCV-camera points to Nx2 pixels."""
    p = np.asarray(points_cam, dtype=float)
    K = np.asarray(K, dtype=float)
    return (p[:, :2] / p[:, 2:3]) * np.array([K[0, 0], K[1, 1]]) + np.array([K[0, 2], K[1, 2]])


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="SAM 3D Body on a frames dir (see part2 frames)")
    ap.add_argument("frames_dir")
    ap.add_argument("out_path")
    a = ap.parse_args()
    res = estimate(a.frames_dir, a.out_path)
    n = sum(len(f["people"]) for f in res["frames"])
    print(f"{len(res['frames'])} frames, {n} person-detections, K f={res['K'][0][0]} -> {a.out_path}")
