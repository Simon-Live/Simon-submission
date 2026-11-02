"""`part2 autorig`: an unrigged humanoid mesh (OBJ, or GLB without a skin) -> DIR/model.glb and DIR/avatar.json.

    part2 autorig --out DIR MESH [--height M] [--up y|z]       (python -m part2 autorig ...)

Method: the mesh is normalised (metres, Y up, soles on y = 0), drawn from the front, and SAM 3D Body fits the MHR body
to that picture. The fitted body is moved onto the mesh (a scale and shift, then trimmed nearest-point steps). The
mesh then takes the MHR skeleton, in the pose it is in, and the MHR skin weights of its nearest body vertices. The 22
mapped bones carry their canonical names (hips, spine, ..., rightToes), so Part 7's bone_map reads the GLB with its
`simon-avatar` preset. Every joint has an identity rotation at bind, as `part2 avatar` writes.

Exit codes: 0 written, 1 failed (the model cannot run here), 2 bad input (one line on stderr), 3 no person found in
the picture of the mesh, 4 GPU busy or too little GPU memory. Spec: docs/specs/autorig.md. Licences: ADR-0005 (the SAM
License covers the weights and the mirror's MHR file; MHR upstream is Apache-2.0); a rigged mesh passes both on.
"""
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from part2 import autorig_glb, autorig_mesh
from part2.autorig_mesh import Mesh, MeshError
from part2.mhr_export import (  # one MHR table, shared with avatar
    JOINTS,
    LICENCE,
    MHR_INDEX,
    UNDER,
    is_under,
    joint_names,
)

NOTICE = ("Rigged with SAM 3D Body (SAM License, Meta, 2025-11-19) and the MHR body model (Apache-2.0, "
          "facebookresearch/MHR): the skeleton and the skin weights come from MHR, the surface is the uploader's mesh. "
          "Passing this file on needs a copy of the SAM License and the MHR Apache-2.0 licence text and notice.")
GPU_WAIT_ENV, GPU_WAIT_S = "PART2_AUTORIG_GPU_WAIT_S", 30.0
MAX_FIT_ERROR = 0.06            # median gap between the fitted body and the mesh, either way, as a share of the mesh height
ICP_STEPS, ICP_KEEP, ICP_STOP_M = 30, 0.7, 1e-4
SCALE_BAND = (0.8, 1.25)
KNN_K = 4
DETECT_THRESHOLDS = (0.5, 0.25)  # the detector's own floor is 0.25
MAX_INFLUENCES = 4
OUT_NAMES = ("model.glb", "avatar.json")
LEFT_HIP, RIGHT_HIP = 9, 10      # MHR70 keypoints, the subject's left and right


class AutorigError(Exception):
    """A run that ends with `code`; str() is the one line printed after "part2: "."""
    code = 1


class BadInput(AutorigError):
    code = 2


class NoPersonInPicture(AutorigError):
    code = 3


class GpuUnavailable(AutorigError):
    code = 4


@dataclass
class Skin:
    """The MHR skinning: joint parents (-1 at the root) and, per body vertex, up to four joints and weights."""
    parents: np.ndarray   # (127,)
    idx: np.ndarray       # (V, 4)
    w: np.ndarray         # (V, 4) rows sum to 1


@dataclass
class Fit:
    """A fitted MHR body in camera space (metres): vertices (V,3), joints (127,3), MHR70 keypoints (70,3)."""
    vertices: np.ndarray
    joints: np.ndarray
    keypoints: np.ndarray

    def moved(self, scale: float, shift) -> "Fit":
        return Fit(*(a * scale + shift for a in (self.vertices, self.joints, self.keypoints)))


@dataclass
class Rigged:
    glb: bytes
    avatar: dict


# ---- skin from the MHR file -------------------------------------------------------------------------

def skin_from_flat(parents, vert, joint, weight, n_vertices: int) -> Skin:
    """Flat (vertex, joint, weight) triples -> the four heaviest joints per vertex, renormalised to sum 1."""
    vert, joint, weight = (np.asarray(a) for a in (vert, joint, weight))
    if len(vert) == 0 or not np.isfinite(weight).all() or (weight < 0).any():
        raise AutorigError("the MHR skin weights are not usable")
    if (np.bincount(vert, weights=weight, minlength=n_vertices) <= 0).any():
        raise AutorigError("the MHR skin weights are not usable (a vertex has no positive weight)")
    order = np.lexsort((-weight, vert))
    vert, joint, weight = vert[order], joint[order], weight[order]
    start = np.concatenate([[0], np.cumsum(np.bincount(vert, minlength=n_vertices))[:-1]])
    rank = np.arange(len(vert)) - start[vert]
    keep = rank < MAX_INFLUENCES
    idx = np.zeros((n_vertices, MAX_INFLUENCES), dtype=np.int64)
    w = np.zeros((n_vertices, MAX_INFLUENCES))
    idx[vert[keep], rank[keep]] = joint[keep]
    w[vert[keep], rank[keep]] = weight[keep]
    return Skin(np.asarray(parents, dtype=np.int64), idx, w / w.sum(1, keepdims=True))


def load_skin(ckpt_dir) -> Skin:
    """The skinning of `<ckpt_dir>/assets/mhr_model.pt` (needs torch; the TorchScript file is read on the CPU)."""
    import torch

    path = Path(ckpt_dir) / "assets" / "mhr_model.pt"
    ch = torch.jit.load(str(path), map_location="cpu").character_torch
    lbs = ch.linear_blend_skinning
    n = lambda t: t.detach().cpu().numpy()
    return skin_from_flat(n(ch.skeleton.joint_parents), n(lbs.vert_indices_flattened), n(lbs.skin_indices_flattened),
                          n(lbs.skin_weights_flattened), len(n(ch.mesh.rest_vertices)))


# ---- nearest points ---------------------------------------------------------------------------------

def knn(points: np.ndarray, targets: np.ndarray, k: int = 1):
    """(distances, indices), each (len(points), k): the k nearest rows of `targets` to each point. Uses scipy's tree
    when it is installed (the GPU venv), else blocks of brute force."""
    k = min(k, len(targets))
    try:
        from scipy.spatial import cKDTree
    except ImportError:
        cKDTree = None
    if cKDTree is not None:
        d, i = cKDTree(targets).query(points, k=k)
        return d.reshape(len(points), k), i.reshape(len(points), k)
    block = max(1, 4_000_000 // max(len(targets), 1))
    ds, ix = [], []
    t2 = (targets ** 2).sum(1)
    for s in range(0, len(points), block):
        p = points[s:s + block]
        d2 = np.maximum((p ** 2).sum(1)[:, None] + t2[None, :] - 2 * p @ targets.T, 0.0)
        part = np.argpartition(d2, k - 1, axis=1)[:, :k] if k < len(targets) else np.tile(np.arange(k), (len(d2), 1))
        pd = np.take_along_axis(d2, part, 1)
        o = np.argsort(pd, axis=1)
        ix.append(np.take_along_axis(part, o, 1))
        ds.append(np.sqrt(np.take_along_axis(pd, o, 1)))
    return np.concatenate(ds), np.concatenate(ix)


def _sample(points: np.ndarray, limit: int = 10000) -> np.ndarray:
    return points if len(points) <= limit else points[:: -(-len(points) // limit)]


# ---- placing the fitted body on the mesh ------------------------------------------------------------

def align(fit: Fit, target: np.ndarray):
    """(fit moved onto `target` (n,3), median gap in metres). The fit starts as a scale about the camera (the picture
    does not change with it) that matches the heights, then up to ICP_STEPS rounds of a scale and shift fitted to the nearest
    target points of the ICP_KEEP closest fit vertices."""
    target = _sample(np.asarray(target, dtype=float))
    h_fit = np.ptp(fit.vertices[:, 1])
    if h_fit <= 1e-6:
        raise AutorigError("the fitted body has no height")
    cur = fit.moved(float(np.ptp(target[:, 1]) / h_fit), 0.0)
    total = 1.0  # the scale the steps added to the height match; kept inside SCALE_BAND so a bad fit cannot shrink away
    for _ in range(ICP_STEPS):
        d, j = knn(cur.vertices, target)
        keep = d[:, 0] <= np.quantile(d[:, 0], ICP_KEEP)
        a, b = cur.vertices[keep], target[j[keep, 0]]
        am, bm = a.mean(0), b.mean(0)
        denom = float(((a - am) ** 2).sum())
        s = float(((a - am) * (b - bm)).sum() / denom) if denom > 0 else 1.0
        s = float(np.clip(total * s, *SCALE_BAND) / total)
        total *= s
        shift = bm - s * am
        cur = cur.moved(s, shift)
        if abs(s - 1) * 1.7 < ICP_STOP_M and np.abs(shift).max() < ICP_STOP_M:
            break
    forward, _ = knn(cur.vertices, target)
    backward, _ = knn(target, cur.vertices)
    return cur, float(max(np.median(forward), np.median(backward)))


# ---- skin transfer and bones ------------------------------------------------------------------------

def transfer_weights(vertices: np.ndarray, body: np.ndarray, skin: Skin, k: int = KNN_K, block: int = 20000):
    """(idx (n,4), w (n,4)): each mesh vertex takes the skin of its k nearest body vertices, nearer ones counting more,
    cut to the four heaviest joints and renormalised. Every row sums to 1."""
    d, nn = knn(vertices, body, k)
    inv = 1.0 / (d + 1e-3)
    out_i = np.zeros((len(vertices), MAX_INFLUENCES), dtype=np.int64)
    out_w = np.zeros((len(vertices), MAX_INFLUENCES))
    for s in range(0, len(vertices), block):
        sl = slice(s, s + block)
        dense = np.zeros((len(d[sl]), len(skin.parents)))
        rows = np.arange(len(dense))[:, None, None]
        np.add.at(dense, (np.broadcast_to(rows, skin.idx[nn[sl]].shape), skin.idx[nn[sl]]),
                  skin.w[nn[sl]] * inv[sl][:, :, None])
        top = np.argsort(-dense, axis=1)[:, :MAX_INFLUENCES]
        tw = np.take_along_axis(dense, top, 1)
        out_i[sl], out_w[sl] = top, tw / tw.sum(1, keepdims=True)
    return out_i, out_w


def canonical_map(parents) -> dict:
    """{canonical bone: MHR joint index} after checking that the asset has the layout MHR_INDEX assumes: 127 joints and
    each bone under the one the chain rule names (Foot under LowerLeg under UpperLeg, Hand under LowerArm, ...)."""
    parents = np.asarray(parents)
    if len(parents) != JOINTS:
        raise AutorigError(f"the MHR model has {len(parents)} joints, not {JOINTS}")
    for bone, above in UNDER.items():
        if not is_under(parents, MHR_INDEX[bone], MHR_INDEX[above]):
            raise AutorigError(f"the MHR model does not have the joint layout autorig expects: {bone} is not under {above}")
    return dict(MHR_INDEX)


# ---- the rig ----------------------------------------------------------------------------------------

def faces_forward(keypoints_mesh: np.ndarray) -> bool:
    """True when the fitted body's left hip is on +x of its right hip: the subject faces +Z, as the front view assumes."""
    return bool(keypoints_mesh[LEFT_HIP, 0] > keypoints_mesh[RIGHT_HIP, 0])


def rig(mesh: Mesh, skin: Skin, fit_body, part2_commit: str = "unknown") -> Rigged:
    """Rig a normalised mesh. `fit_body(mesh) -> (Fit in camera space, Camera)` is the picture-and-model step; when the
    fit reads the figure facing -Z the mesh is turned half a turn and fitted once more, and the turn stays in the GLB."""
    turned = False
    for attempt in range(2):
        fit, cam = fit_body(mesh)
        placed, err = align(fit, cam.to_cam(mesh.vertices))
        body = Fit(*(cam.to_mesh(a) for a in (placed.vertices, placed.joints, placed.keypoints)))
        if faces_forward(body.keypoints):
            break
        if attempt == 1:
            raise BadInput("cannot tell which way the figure faces; turn it to face +Z (or -Z) and Y up")
        mesh, turned = autorig_mesh.face_back(mesh), True
    height = float(np.ptp(mesh.vertices[:, 1]))
    if err > MAX_FIT_ERROR * height:
        raise BadInput("the mesh does not look like one standing person; the fitted body is "
                       f"{err / height:.0%} of its height away")
    mapping = canonical_map(skin.parents)
    idx, w = transfer_weights(mesh.vertices, body.vertices, skin)
    glb = autorig_glb.build(mesh, body.joints, skin.parents, joint_names(mapping), idx, w,
                            {"copyright": NOTICE, "licence": LICENCE})
    avatar = {"schema": "simon.avatar.v1", "kind": "autorig", "inputs": 1,
              "height_m": round(float(np.ptp(mesh.vertices[:, 1])), 3), "joints": JOINTS, "mapped": mapping,
              "licence": LICENCE, "part2_commit": part2_commit, "skinning": "nearest-body-vertices",
              "fit_error_m": round(err, 4), "turned_to_face_forward": turned}
    return Rigged(glb, avatar)


# ---- SAM 3D Body ------------------------------------------------------------------------------------

def sam_fit_body(backend):
    """A `fit_body` that draws the mesh from the front and fits it with the SAM 3D Body estimator of `backend`."""
    import cv2
    import torch

    def fit_body(mesh: Mesh):
        est = backend.load()
        image, cam = autorig_mesh.render_front(mesh)
        with tempfile.TemporaryDirectory(prefix="autorig-") as tmp:
            path = Path(tmp) / "front.png"
            image.save(path)
            bgr = cv2.imread(str(path))
            box = _person_box(est, bgr, cam, mesh)
            outs = est.process_one_image(str(path), bboxes=box, cam_int=torch.tensor(cam.K[None], dtype=torch.float32))
        if not outs:
            raise NoPersonInPicture("no person found in the picture of the mesh")
        o = outs[0]
        t = np.asarray(o["pred_cam_t"], dtype=float)
        parts = [np.asarray(o[k], dtype=float) + t for k in ("pred_vertices", "pred_joint_coords", "pred_keypoints_3d")]
        if parts[1].shape != (JOINTS, 3):
            raise AutorigError(f"SAM 3D Body gave {parts[1].shape[0]} joints, not {JOINTS}")
        return Fit(*parts), cam

    return fit_body


def _person_box(est, bgr, cam, mesh: Mesh) -> np.ndarray:
    """The (1, 4) xyxy box SAM 3D Body fits: the person detector's pick at its usual score, then at its lowest score; a
    drawing of a mesh is often not what the detector was trained on, so the mesh's own outline is the last answer."""
    from part2 import body3d

    for thr in DETECT_THRESHOLDS:
        dets = est.detector.run_human_detection(bgr, det_cat_id=0, bbox_thr=thr, nms_thr=0.3, default_to_full_image=False)
        if len(dets):
            return dets[[body3d.choose_subject(dets, None)]].astype(np.float32)
    q = cam.to_cam(mesh.vertices)
    uv = q[:, :2] * cam.K[0, 0] / q[:, 2:3] + cam.size / 2
    lo, hi = uv.min(0), uv.max(0)
    pad = 0.04 * (hi - lo)
    return np.concatenate([lo - pad, hi + pad])[None].astype(np.float32)


# ---- the command ------------------------------------------------------------------------------------

def _clear(out: Path) -> None:
    for name in OUT_NAMES:
        (out / name).unlink(missing_ok=True)  # a failed run never leaves an older run's files looking current


def _write(out: Path, rigged: Rigged) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, data in (("model.glb", rigged.glb), ("avatar.json", json.dumps(rigged.avatar, indent=2).encode())):
        tmp = out / (name + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, out / name)


def run(mesh_path, out, height_m=None, up=None, backend=None, skin=None, fit_body=None) -> dict:
    """Rig `mesh_path` into `out` and return avatar.json. Input problems are BadInput before the GPU is touched.
    `backend`, `skin` and `fit_body` are for tests; by default the gpu backend and its MHR file are used."""
    out = Path(out)
    _clear(out)
    try:
        mesh, info = autorig_mesh.normalize(autorig_mesh.load(mesh_path), height_m, up)
    except MeshError as e:
        raise BadInput(str(e)) from None
    from part2 import provenance

    commit = provenance.part2_commit()
    if fit_body is not None:
        rigged = rig(mesh, skin, fit_body, commit)
    else:
        rigged = _rig_on_gpu(mesh, backend, commit)
    rigged.avatar.update({"up_axis": info["up"], "unit_guess": info["unit"]})
    _write(out, rigged)
    return rigged.avatar


def _rig_on_gpu(mesh: Mesh, backend, commit: str) -> Rigged:
    from part2 import backends, gpu_guard, trackers

    backend = backend or backends.get("gpu")
    try:
        ok, reason = backend.available()
    except Exception as e:  # noqa: BLE001  (a broken install is the same answer as a missing one)
        ok, reason = False, str(e)
    if not ok:
        raise AutorigError(reason)
    free = gpu_guard.free_gib()
    if free is not None and free < gpu_guard.MIN_FREE_GIB:
        raise GpuUnavailable(f"only {free:.1f} GiB of GPU memory is free; need {gpu_guard.MIN_FREE_GIB:.0f}")
    wait = float(os.environ.get(GPU_WAIT_ENV, GPU_WAIT_S))
    try:
        with gpu_guard.gpu_lock(wait_s=wait):
            skin = load_skin(backend.paths()["ckpt"])
            return rig(mesh, skin, sam_fit_body(backend), commit)
    except trackers.GpuBusy:
        raise GpuUnavailable("another GPU job is running") from None
    except RuntimeError as e:
        if "out of memory" in str(e).lower():
            raise GpuUnavailable("the GPU ran out of memory") from None
        raise


def command(mesh_path, out, height_m=None, up=None) -> int:
    """The `autorig` subcommand: exit code per the module doc; one line on stderr for a failure."""
    try:
        avatar = run(mesh_path, out, height_m, up)
    except AutorigError as e:
        print(f"part2: {e}", file=sys.stderr)
        return e.code
    print(f"{Path(out) / 'model.glb'} ({avatar['height_m']} m, {len(avatar['mapped'])} named bones)")
    return 0
