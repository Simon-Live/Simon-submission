"""CPU backend: RTMPose-x 2D through rtmlib on ONNX Runtime CPU, then a 3D lifter (part2.lifters).

Spec: docs/specs/backends-gpu-cpu.md ("CPU backend"); ADR-0002 (backends), ADR-0005 (licence caveat).

Writes body3d.json in the shape documented in part2/body3d.py, plus a top-level `provenance` object.
- Person boxes: rtmlib's YOLOX-x person detector; in one-person mode the detection that best continues
  the previous frame's box is kept (body3d.choose_subject) and becomes id 0. With `boxes=` (multi mode)
  the detector is skipped and RTMPose-x runs on each given box.
- K: focal = image long side in px, principal point at the image centre (focal_source "long-side").
- kp2d is written as RTMPose gives it (COCO-17 order equals part2.joints.CANONICAL); kp3d_cam comes
  from the lifter in the camera frame; reproj_self_px as in body3d.py.

Nothing heavy is imported at module import: rtmlib, onnxruntime and cv2 load inside Rtm2D.
"""
import importlib.util
import json
import os
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from part2 import frames as frames_mod
from part2 import lifters
from part2.backends import REFUSAL, BackendUnavailable
from part2.body3d import choose_subject, project
from part2.hashing import sha256_file
from part2.joints import CANONICAL

NAME = "cpu"
NEEDS = ("rtmlib", "onnxruntime", "cv2")
FOCAL_SOURCE = "long-side"
ENV_PROFILE = "envs/cpu/requirements.txt"
DETECTOR = "rtmlib-yolox-x"
GIVEN_BOXES = "given boxes"
_ONNX_SDK = "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/"
# rtmlib Body(mode="performance"), pinned here so an rtmlib upgrade cannot swap the models silently.
DET = {"name": "yolox-x person detector (humanart, rtmlib performance mode)",
       "url": _ONNX_SDK + "yolox_x_8xb8-300e_humanart-a39d44ed.zip", "input_size": (640, 640),
       "licence": "Apache-2.0 (rtmlib, mmdetection)"}
POSE = {"name": "rtmpose-x body7 384x288 (rtmlib performance mode)",
        "url": _ONNX_SDK + "rtmpose-x_simcc-body7_pt-body7_700e-384x288-71d7b7e9_20230629.zip",
        "input_size": (288, 384),
        "licence": "Apache-2.0 code and weights; body7 training data includes research-only datasets"}
LICENCE_NOTE = ("RTMPose-x (rtmlib): Apache-2.0 code and weights, trained on body7, which includes datasets with "
                "research-only terms; accepted with this caveat by the operator on #336 (2026-10-28, ADR-0005).")


class Rtm2D:
    """rtmlib YOLOX-x detector plus RTMPose-x on ONNX Runtime CPUExecutionProvider."""

    def __init__(self):
        from rtmlib import YOLOX, RTMPose

        self.det = _load(YOLOX, DET)
        self.pose = _load(RTMPose, POSE)

    @staticmethod
    def read(path) -> np.ndarray:
        import cv2

        img = cv2.imread(str(path))
        if img is None:
            raise ValueError(f"cannot read image {path}")
        return img

    def detect(self, bgr) -> np.ndarray:
        """Person boxes (m, 4) xyxy."""
        return np.asarray(self.det(bgr), dtype=float).reshape(-1, 4)

    def keypoints(self, bgr, xyxy) -> tuple[np.ndarray, np.ndarray]:
        """(m, 17, 2) px and (m, 17) RTMPose scores, one row per box."""
        kp, sc = self.pose(bgr, bboxes=[list(map(float, b)) for b in xyxy])
        return np.asarray(kp, dtype=float), np.asarray(sc, dtype=float)


def lift_available(name: str) -> tuple[bool, str]:
    return lifters.get(name).available()


def _load(cls, spec):
    try:
        return cls(spec["url"], model_input_size=spec["input_size"], backend="onnxruntime", device="cpu")
    except (OSError, zipfile.BadZipFile) as e:
        raise RuntimeError(f"could not download {spec['name']} weights from {spec['url']} ({e})") from None


class Backend:
    """Registry entry `cpu` (part2.backends). `lifter`: a name from part2.lifters, else PART2_LIFTER, else
    lifters.DEFAULT; the CLI sets it from --lifter."""

    name = NAME

    def __init__(self, lifter: str | None = None):
        self.lifter = lifter

    def available(self, lifter: str | None = None) -> tuple[bool, str]:
        """Imports checked without loading them; the lifter's own needs (torch for motionbert) too."""
        missing = [m for m in NEEDS if importlib.util.find_spec(m) is None]
        if missing:
            return False, f"{REFUSAL[NAME]} (missing {', '.join(missing)})"
        ok, why = lift_available(lifters.resolve(lifter or self.lifter))
        if not ok:
            return False, why
        return True, "rtmlib, onnxruntime and opencv importable (ONNX Runtime CPUExecutionProvider)"

    def provenance(self, lifter: str | None = None, detector: str = DETECTOR, extra: dict | None = None) -> dict:
        lift = lifters.get(lifters.resolve(lifter or self.lifter))
        return {
            "backend": NAME, "tracker": None, "lifter": lift.name, "refine": [], "detector": detector,
            "focal_source": FOCAL_SOURCE, "models": [model_entry(DET), model_entry(POSE)] + lift.models(),
            "env_profile": ENV_PROFILE, "part2_commit": _commit(),
            "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "licence_notes": [LICENCE_NOTE] + lift.licence_notes(), **(extra or {}),
        }

    def estimate(self, frames_dir, out_path, boxes=None, lifter: str | None = None, model2d=None) -> dict:
        """Run 2D and the lifter on every frame and write body3d.json (returned).

        boxes: {frame: {id: [x, y, w, h]}} to run on given people (multi mode); without it one person
        per frame becomes id 0. model2d: an object with read/detect/keypoints (Rtm2D by default).
        """
        name = lifters.resolve(lifter or self.lifter)
        ok, why = self.available(name) if model2d is None else lift_available(name)
        if not ok:
            raise BackendUnavailable(REFUSAL[NAME]) from RuntimeError(why)
        model2d = model2d or Rtm2D()
        recs = frames_mod.load(frames_dir)
        t0 = time.perf_counter()
        det = detect_2d(frames_dir, recs, model2d, boxes)
        seconds_2d = time.perf_counter() - t0
        doc, info = lift_2d(det, lifters.get(name))
        n_pf = sum(len(f["people"]) for f in det["frames"])
        doc["provenance"] = self.provenance(name, GIVEN_BOXES if boxes is not None else DETECTOR, {
            "lifter_info": info, "timing": {"seconds_2d": round(seconds_2d, 2), "person_frames": n_pf,
                                            "seconds_per_person_frame_2d": round(seconds_2d / max(n_pf, 1), 3)}})
        write_json(out_path, doc)
        return doc


def detect_2d(frames_dir, recs, model2d, boxes=None) -> dict:
    """{image_size, K, frames: [{frame, t_ms, people: [{id, bbox: [x, y, w, h], kp2d (17, 2), conf (17,)}]}]}"""
    frames_dir = Path(frames_dir)
    out, prev, size = [], None, None
    for r in recs:
        img = model2d.read(frames_dir / r["file"])
        size = size or [int(img.shape[1]), int(img.shape[0])]
        if boxes is not None:
            given = boxes.get(r["frame"], boxes.get(str(r["frame"]), {}))
            ids = list(given)
            xyxy = np.array([[x, y, x + w, y + h] for x, y, w, h in given.values()], dtype=float).reshape(-1, 4)
        else:
            dets = model2d.detect(img)
            if len(dets):
                pick = choose_subject(dets, prev)
                xyxy, ids, prev = dets[[pick]], [0], dets[pick]
            else:
                xyxy, ids = np.zeros((0, 4)), []
        people = []
        if len(ids):
            kp, sc = model2d.keypoints(img, xyxy)
            for pid, b, k, s in zip(ids, xyxy, kp, sc):
                people.append({"id": int(pid) if str(pid).isdigit() else pid,
                               "bbox": [round(float(b[0]), 1), round(float(b[1]), 1),
                                        round(float(b[2] - b[0]), 1), round(float(b[3] - b[1]), 1)],
                               "kp2d": np.asarray(k, float).reshape(17, 2), "conf": np.asarray(s, float).reshape(17)})
        out.append({"frame": r["frame"], "t_ms": r["t_ms"], "people": people})
    if size is None or not any(f["people"] for f in out):
        raise RuntimeError(f"no person found in {len(recs)} frames")
    return {"image_size": size, "K": long_side_K(*size), "frames": out}


def long_side_K(w: int, h: int) -> np.ndarray:
    f = float(max(w, h))
    return np.array([[f, 0.0, w / 2.0], [0.0, f, h / 2.0], [0.0, 0.0, 1.0]])


def clip_fps(t_ms: list) -> float | None:
    dt = np.diff(np.asarray(t_ms, dtype=float))
    dt = dt[dt > 0]
    return float(1000.0 / np.median(dt)) if len(dt) else None


def lift_2d(det: dict, lift) -> tuple[dict, dict]:
    """Lift each person's 2D sequence; return (body3d document, per-person lifter info)."""
    K, size = det["K"], det["image_size"]
    seqs: dict = {}
    for i, f in enumerate(det["frames"]):
        for k, p in enumerate(f["people"]):
            seqs.setdefault(p["id"], []).append((i, k))
    placed, info = {}, {}
    for pid, where in seqs.items():
        kp = np.stack([det["frames"][i]["people"][k]["kp2d"] for i, k in where])
        conf = np.stack([det["frames"][i]["people"][k]["conf"] for i, k in where])
        fps = clip_fps([det["frames"][i]["t_ms"] for i, _ in where])
        kp3d, info[str(pid)] = lift.lift_info(kp, conf, K, size, fps)
        placed.update({w: p3 for w, p3 in zip(where, kp3d)})
    frames = []
    for i, f in enumerate(det["frames"]):
        frames.append({"frame": f["frame"], "t_ms": f["t_ms"],
                       "people": [_person(p, placed[(i, k)], K) for k, p in enumerate(f["people"])]})
    doc = {"model": f"rtmpose-x+{lift.name}", "camera_frame": "opencv", "K": np.round(K, 3).tolist(),
           "image_size": list(size), "frames": frames}
    return doc, info


def _person(p: dict, kp3d: np.ndarray, K) -> dict:
    uv = project(kp3d, K)
    return {"id": p["id"], "bbox": p["bbox"],
            "kp3d_cam": {j: np.round(x, 4).tolist() for j, x in zip(CANONICAL, kp3d)},
            "kp2d": {j: np.round(x, 2).tolist() for j, x in zip(CANONICAL, p["kp2d"])},
            "reproj_self_px": round(float(np.median(np.linalg.norm(uv - p["kp2d"], axis=1))), 3)}


def model_entry(spec: dict) -> dict:
    return {"name": spec["name"], "source": spec["url"], "weights_sha256": _sha256(_onnx_path(spec["url"])),
            "licence": spec["licence"]}


def _onnx_path(url: str) -> Path:
    """Where rtmlib unpacks a model zip (rtmlib.tools.file: TORCH_HOME or XDG_CACHE_HOME/rtmlib, then hub/checkpoints)."""
    home = os.environ.get("TORCH_HOME") or os.path.join(os.environ.get("XDG_CACHE_HOME", "~/.cache"), "rtmlib")
    return Path(home).expanduser() / "hub" / "checkpoints" / (os.path.basename(url).split(".")[0] + ".onnx")


_SHA_CACHE: dict = {}


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime)
    if key not in _SHA_CACHE:
        _SHA_CACHE[key] = sha256_file(path)
    return _SHA_CACHE[key]


def _commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent, capture_output=True,
                             text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def write_json(path, doc) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))
    return path

def save_2d(det: dict, path) -> Path:
    people = lambda f: [{**p, "kp2d": np.round(p["kp2d"], 3).tolist(), "conf": np.round(p["conf"], 4).tolist()}  # noqa: E731
                        for p in f["people"]]
    return write_json(path, {"image_size": det["image_size"], "K": det["K"].tolist(),
                             "frames": [{**f, "people": people(f)} for f in det["frames"]]})


def load_2d(path) -> dict:
    det = json.loads(Path(path).read_text())
    for f in det["frames"]:
        for p in f["people"]:
            p["kp2d"], p["conf"] = np.asarray(p["kp2d"], float), np.asarray(p["conf"], float)
    return {**det, "K": np.asarray(det["K"], float)}


def write_outputs(doc: dict, out_dir) -> list[Path]:
    """body3d.json, then pose3d.json and camera.json through part2.canonical, each carrying `provenance`."""
    from part2 import canonical

    out_dir = Path(out_dir)
    paths = [write_json(out_dir / "body3d.json", doc), *canonical.write(out_dir / "body3d.json", out_dir)]
    for p in paths[1:]:
        write_json(p, {**json.loads(p.read_text()), "provenance": doc["provenance"]})
    return paths


def main(argv=None) -> int:
    """python -m part2.backends.cpu_rtm FRAMES OUT [--lifters a,b] [--reuse-2d]: the 2D runs once (or is read
    back from OUT/rtmpose2d.json), then each lifter writes OUT/<lifter>/{body3d,pose3d,camera}.json."""
    import argparse

    ap = argparse.ArgumentParser(prog="python -m part2.backends.cpu_rtm")
    ap.add_argument("frames_dir", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--lifters", default=",".join(lifters.names()))
    ap.add_argument("--reuse-2d", action="store_true", help="read OUT/rtmpose2d.json instead of running RTMPose")
    a = ap.parse_args(argv)
    names = [lifters.resolve(n) for n in a.lifters.split(",")]
    cached = a.out_dir / "rtmpose2d.json"
    t0 = time.perf_counter()
    if a.reuse_2d:
        det, seconds_2d = load_2d(cached), None
    else:
        ok, why = Backend().available(names[0])
        if not ok:
            raise BackendUnavailable(REFUSAL[NAME]) from RuntimeError(why)
        det = detect_2d(a.frames_dir, frames_mod.load(a.frames_dir), Rtm2D())
        seconds_2d = time.perf_counter() - t0
        save_2d(det, cached)
    n_pf = sum(len(f["people"]) for f in det["frames"])
    timing = {"seconds_2d": None if seconds_2d is None else round(seconds_2d, 2), "person_frames": n_pf,
              "seconds_per_person_frame_2d": None if seconds_2d is None else round(seconds_2d / n_pf, 3)}
    summary = {"frames": len(det["frames"]), **timing, "lifters": {}}
    for name in names:
        t1 = time.perf_counter()
        doc, info = lift_2d(det, lifters.get(name))
        seconds = round(time.perf_counter() - t1, 2)
        doc["provenance"] = Backend(name).provenance(name, DETECTOR, {"lifter_info": info, "timing": timing})
        write_outputs(doc, a.out_dir / name)
        summary["lifters"][name] = {"seconds": seconds, **{k: v for p in info.values() for k, v in p.items()
                                                           if k in ("bone_cv_mean", "bone_cv_max", "clipped",
                                                                    "fallback_bones", "root_depth_m")}}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
