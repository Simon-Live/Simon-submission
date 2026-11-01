"""Lifter B2 `bones-prior`: the fixed-bones lift with a depth-sign and joint-limit prior (TICKET-044, approach B2).

Spec: docs/specs/backends-gpu-cpu.md ("Lifter B2, bones-prior"); ADR-0002. numpy only, deterministic.
Registered in part2.lifters (_REGISTRY), where it is also the default lifter (AC-B10).

Steps 1 to 4 are fixed-bones' own functions (part2.lifters.fixed_bones, unchanged): rays, bone lengths over the
clip scaled to a standing chain, per-frame root depth, and the tree placement whose ten sign bits (hip line, left
torso side, eight limb bones) give 1024 candidate poses per frame, every joint on its ray at its bone length.
5. Prior, per frame and candidate, in the trunk frame (x the hip line, u the trunk axis, f = x cross u, the front):
   for each joint limit, the angle in degrees by which the candidate leaves the published range, weighted by how
   well the angle is defined, summed and divided by DEG_UNIT, plus W_WIDTH times the relative shoulder width error.
   Limits (AAOS average ranges, cited in the spec): hip extension HIP_EXT, hip adduction HIP_ADD, knee and elbow
   extension 0 (no backward bend; a bend sideways, as a rotated hip gives in cross-legged sitting, is free), the
   upper arm behind the frontal plane at most SH_HEXT at shoulder height (falling to 0 straight up), the shoulder
   line twisted against the hip line at most SPINE_ROT. Plus fixed-bones' posture limits in degrees: the trunk
   leaning back past fixed_bones.LEAN_BACK_DEG and the face turned past FACE_TURN from the body's front.
6. Temporal: Viterbi over the clip; a bit that flips between two frames costs W_JUMP times the distance its joint
   jumps (the gap between its two roots, in bone lengths, mean of both frames), so a bone crossing the image plane
   flips for free and a foreshortened bone flips only when the prior insists.
7. Output: face joints in front of the shoulder midpoint by FACE_FWD along the trunk's front, then every joint
   scaled along its ray by H_CHAIN / fixed_bones.H_REF. Every joint stays on its ray, so the output reprojects onto
   kp2d as fixed-bones' does, and the tree's bone lengths stay fixed.
"""
import numpy as np

from part2.lifters import BODY_BONES, J, bone_cv, rays
from part2.lifters import fixed_bones as fb

NAME = "bones-prior"
# ADR-0002: limits in degrees, AAOS average ranges of motion (Greene and Heckman 1994); see the spec's B2 table.
HIP_EXT = 30.0      # hip extension
HIP_ADD = 30.0      # hip adduction
# Knee and elbow extension 0 (no hyperextension): hinge_excess counts any backward bend.
SH_HEXT = 45.0      # shoulder horizontal extension (horizontal abduction)
SPINE_ROT = 45.0    # thoracolumbar rotation
FACE_TURN = 90.0    # the face never points behind the body's front (fixed-bones' facing term, in degrees)
# Tuned on the tuning clips only (spec B2 tuning table); never on the bar fixture.
DEG_UNIT = 30.0     # degrees of limit excess that cost as much as one unit
W_JUMP = 3.0        # cost of a sign flip per bone length its joint jumps
W_WIDTH = fb.W_WIDTH
# Measured on the GPU outputs of the tuning clips (spec B2), medians over their 15 people: the standing chain
# (fixed-bones' scale reference, 1.60 m there) and each face joint's offset in front of the shoulder midpoint
# along the trunk's front.
H_CHAIN = 1.50
FACE_FWD = {"nose": 0.15, "left_eye": 0.13, "right_eye": 0.13, "left_ear": 0.03, "right_ear": 0.03}
EPS = 1e-9
CONFIGS = fb.CONFIGS  # (1024, 10): bit 0 the hip line, then fixed_bones.CHAINS


class BonesPrior:
    name = NAME

    def available(self) -> tuple[bool, str]:
        return True, "numpy only"

    def models(self) -> list:
        return []

    def licence_notes(self) -> list:
        return []

    def lift(self, kp2d, conf, K, image_size=None, fps=None) -> np.ndarray:
        return self.lift_info(kp2d, conf, K, image_size, fps)[0]

    def lift_info(self, kp2d, conf, K, image_size=None, fps=None) -> tuple[np.ndarray, dict]:
        kp2d, conf = np.asarray(kp2d, float), np.asarray(conf, float)
        if kp2d.ndim != 3 or kp2d.shape[1:] != (17, 2) or conf.shape != kp2d.shape[:2] or not len(kp2d):
            raise ValueError(f"{NAME}: expected kp2d (n, 17, 2) and conf (n, 17), got {kp2d.shape}, {conf.shape}")
        r = rays(kp2d, K)
        valid = conf >= fb.CONF_MIN
        lengths, Z, fit = fb.fit_lengths(r[..., :2], valid)
        path, prior = solve(r, lengths, Z, valid)
        final, clipped = fb.place(r, lengths, Z, CONFIGS[path][:, None])
        k = H_CHAIN / fb.H_REF  # every joint scales along its ray: reprojection unchanged
        pos, lengths, Z = place_face(final[:, 0], r) * k, lengths * k, Z * k
        cv = bone_cv(pos)
        flips = int((CONFIGS[path[1:]] != CONFIGS[path[:-1]]).sum())
        return pos, {"lifter": NAME, "H_ref_m": H_CHAIN, "clipped": int(clipped.sum()), **fit,
                     "bone_lengths_m": {"-".join(b): round(float(lengths[i]), 4) for i, b in enumerate(BODY_BONES)},
                     "root_depth_m": [round(float(Z.min()), 3), round(float(np.median(Z)), 3), round(float(Z.max()), 3)],
                     "sign_flips": flips, "prior_cost_mean": round(float(prior.mean()), 4),
                     "bone_cv_mean": round(float(cv.mean()), 5), "bone_cv_max": round(float(cv.max()), 5)}


def _unit(v):
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, EPS), n[..., 0]


def _dot(a, b):
    return (a * b).sum(-1)


def arc_excess(theta, lo, hi) -> np.ndarray:
    """Degrees from theta to the allowed arc from lo up to hi (degrees, an arc shorter than 360) the short way round."""
    t = np.mod(np.asarray(theta, float) - lo, 360.0)  # 0 at lo; inside the arc while t is at most its length
    return np.where(t <= hi - lo, 0.0, np.minimum(t - (hi - lo), 360.0 - t))


def trunk_frame(pos) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Subject's left x (hip line), trunk axis u (hip-mid to shoulder-mid, made normal to x), front f = x cross u."""
    P = lambda name: pos[..., J[name], :]
    x, _ = _unit(P("left_hip") - P("right_hip"))
    t = (P("left_shoulder") + P("right_shoulder") - P("left_hip") - P("right_hip")) / 2
    u, _ = _unit(t - _dot(t, x)[..., None] * x)
    return x, u, np.cross(x, u)


def sagittal_excess(d, u, f, lo, hi) -> np.ndarray:
    """Excess of a limb direction's angle in the trunk's sagittal plane (0 down, 90 forward, 180 up) outside [lo, hi],
    weighted by the length of its sagittal part (a limb pointing sideways has no sagittal angle)."""
    a, b = _dot(d, f), -_dot(d, u)
    return arc_excess(np.degrees(np.arctan2(a, b)), lo, hi) * np.hypot(a, b)


def hinge_excess(d, s, axis) -> np.ndarray:
    """Knee or elbow (extension limit 0, so any backward bend is excess): the bend angle k between the proximal unit
    segment d and the distal s, times the share of the bend direction pointing against the neutral one (axis cross
    d, the way the joint flexes with no rotation above it). A straight limb or one bent sideways (a rotated hip,
    as in cross-legged sitting) costs nothing; the weight fades as the axis loses its definition."""
    a, w_axis = _unit(axis)
    k = np.degrees(np.arccos(np.clip(_dot(d, s), -1.0, 1.0)))
    bend, _ = _unit(s - _dot(s, d)[..., None] * d)
    return k * np.maximum(0.0, -_dot(bend, np.cross(a, d))) * np.minimum(w_axis, 1.0)


def _seg(pos, a, b):
    return _unit(pos[..., J[b], :] - pos[..., J[a], :])[0]


def _ok(valid, *names):
    return np.all([valid[:, J[n]] for n in names], axis=0)[:, None].astype(float)


def limit_excess(pos, valid) -> np.ndarray:
    """(n, C) summed degrees of joint-limit excess (step 5)."""
    return sum(limit_terms(pos, valid).values())


def limit_terms(pos, valid) -> dict:
    """{term: (n, C) degrees of excess}, each term counted where its joints are confident."""
    x, u, f = trunk_frame(pos)
    terms = {}
    for side, sx in (("left", 1.0), ("right", -1.0)):
        hip, knee, ankle = f"{side}_hip", f"{side}_knee", f"{side}_ankle"
        sh, el, wr = f"{side}_shoulder", f"{side}_elbow", f"{side}_wrist"
        thigh, shank = _seg(pos, hip, knee), _seg(pos, knee, ankle)
        upper, fore = _seg(pos, sh, el), _seg(pos, el, wr)
        ok_thigh, ok_leg, ok_upper, ok_arm = (_ok(valid, hip, knee), _ok(valid, hip, knee, ankle),
                                              _ok(valid, sh, el), _ok(valid, sh, el, wr))
        terms[f"{side}_hip_extension"] = ok_thigh * sagittal_excess(thigh, u, f, -HIP_EXT, 180.0)
        adduction = -np.degrees(np.arcsin(np.clip(sx * _dot(thigh, x), -1, 1)))
        terms[f"{side}_hip_adduction"] = ok_thigh * np.maximum(0.0, adduction - HIP_ADD)
        terms[f"{side}_knee"] = ok_leg * hinge_excess(thigh, shank, x - _dot(x, thigh)[..., None] * thigh)
        terms[f"{side}_elbow"] = ok_arm * hinge_excess(upper, fore, _dot(x, upper)[..., None] * upper - x)
        behind = np.degrees(np.arcsin(np.clip(-_dot(upper, f), -1, 1)))
        terms[f"{side}_shoulder_behind"] = ok_upper * np.maximum(0.0, behind - SH_HEXT * (1.0 - _dot(upper, u)))
    xs = pos[..., J["left_shoulder"], :] - pos[..., J["right_shoulder"], :]
    xs = xs - _dot(xs, u)[..., None] * u
    twist = np.degrees(np.arctan2(_dot(np.cross(x, xs), u), _dot(x, xs)))
    ok_trunk = _ok(valid, "left_shoulder", "right_shoulder", "left_hip", "right_hip")
    terms["trunk_twist"] = ok_trunk * np.maximum(0.0, np.abs(twist) - SPINE_ROT)
    return {**terms, **posture_terms(pos, valid)}


def posture_terms(pos, valid) -> dict:
    """fixed-bones' posture terms in degrees: trunk leaning back past LEAN_BACK_DEG against camera up, and the face
    (nose minus ears) turned past FACE_TURN from the body's front."""
    _, front = fb.body_axes(pos)
    torso, _ = _unit((pos[..., J["left_shoulder"], :] + pos[..., J["right_shoulder"], :]
                      - pos[..., J["left_hip"], :] - pos[..., J["right_hip"], :]) / 2)
    lean = np.degrees(np.arcsin(np.clip(-_dot(torso, front), -1, 1)))
    face = np.degrees(np.arccos(np.clip(-fb.facing(pos, front, valid), -1, 0))) - FACE_TURN
    return {"lean_back": np.maximum(0.0, lean - fb.LEAN_BACK_DEG), "face_turn": np.maximum(0.0, face)}


def place_face(pos, r) -> np.ndarray:
    """Each face joint on its ray at the shoulder midpoint's depth plus the depth part of FACE_FWD along the
    trunk's front (in profile the offset lies in the image and the depth stays the shoulders')."""
    out = pos.copy()
    _, _, f = trunk_frame(pos)
    z = (pos[:, J["left_shoulder"], 2] + pos[:, J["right_shoulder"], 2]) / 2
    for name, ahead in FACE_FWD.items():
        out[:, J[name]] = (z + ahead * f[:, 2])[:, None] * r[:, J[name]]
    return out


def width_error(pos, lengths) -> np.ndarray:
    width = lengths[fb.SEG[("left_shoulder", "right_shoulder")]]
    return np.abs(np.linalg.norm(pos[..., J["left_shoulder"], :] - pos[..., J["right_shoulder"], :], axis=-1) - width) / width


def _length(lengths, a, b) -> float:
    return lengths[BODY_BONES.index((a, b) if (a, b) in BODY_BONES else (b, a))]


def _tree(pos, r, lengths, Z):
    """(parent point, child ray, length) per sign bit of CONFIGS: the hip line (from the hip midpoint), then
    fixed_bones.CHAINS."""
    root = np.broadcast_to((Z[:, None] * (r[:, J["left_hip"]] + r[:, J["right_hip"]]) / 2)[:, None], pos[..., 0, :].shape)
    out = [(root, r[:, None, J["left_hip"]], _length(lengths, "left_hip", "right_hip") / 2)]
    for parent, child in fb.CHAINS:
        out.append((pos[..., J[parent], :], r[:, None, J[child]], _length(lengths, parent, child)))
    return out


def jumps(pos, r, lengths, Z) -> np.ndarray:
    """(n, C, 10): per sign bit, |far root - near root| / L of its joint, 2 sqrt(b^2 - a c) |ray| / (a L) for
    |s ray - P| = L (0 when clipped: the ray misses the sphere and both roots are its closest point)."""
    out = []
    for P, ray, L in _tree(pos, r, lengths, Z):
        a, b, c = _dot(ray, ray), _dot(ray, P), _dot(P, P) - L * L
        out.append(2.0 * np.sqrt(np.maximum(b * b - a * c, 0.0)) / a * np.sqrt(a) / L)
    return np.stack(out, axis=-1)


def solve(r, lengths, Z, valid) -> tuple[np.ndarray, np.ndarray]:
    """Steps 5 and 6: the configuration index per frame and the prior cost of the chosen path. The Viterbi forward
    pass runs chunk by chunk as each chunk's costs are made, so the jump costs (C x B floats per frame) never
    outlive their chunk; what stays per frame is the unary cost row and the back pointers, C each."""
    n = len(r)
    unary, back, carry = np.empty((n, len(CONFIGS))), np.empty((n, len(CONFIGS)), dtype=np.int32), None
    for i in range(0, n, fb.CHUNK):
        c = slice(i, i + fb.CHUNK)
        pos, _ = fb.place(r[c], lengths, Z[c], CONFIGS[None])
        unary[c] = limit_excess(pos, valid[c]) / DEG_UNIT + W_WIDTH * width_error(pos, lengths)
        carry, back[c] = viterbi_forward(unary[c], W_JUMP * jumps(pos, r[c], lengths, Z[c]), carry)
    path = backtrack(carry[0], back)
    return path, unary[np.arange(n), path]


def viterbi(unary, gap) -> np.ndarray:
    """Configuration per frame minimising unary plus, per bit flipped between frames t-1 and t, the mean of its
    gap in both frames. unary (n, C), gap (n, C, B) for CONFIGS (C, B)."""
    carry, back = viterbi_forward(unary, gap)
    return backtrack(carry[0], back)


def viterbi_forward(unary, gap, carry=None):
    """The forward pass over a run of frames: (carry, back), back (n, C) the best previous configuration of each
    configuration at each frame. `carry` (the running cost v and the last frame's flip costs) is what the run
    before it left, None for the first run of a clip, so a clip can be fed in chunks: the back pointers and the
    final carry are those of one pass over all of it, bit for bit."""
    bits = CONFIGS.astype(np.float32)
    back = np.zeros(unary.shape, dtype=np.int32)
    if carry is None:
        v, prev, start = unary[0].astype(np.float32), _flip_cost(bits, gap[0]), 1
    else:
        (v, prev), start = carry, 0
    for t in range(start, len(unary)):
        cur = _flip_cost(bits, gap[t])
        tot = v[:, None] + 0.5 * (prev + cur.T)
        back[t] = tot.argmin(axis=0)
        v = tot[back[t], np.arange(len(v))] + unary[t].astype(np.float32)
        prev = cur
    return (v, prev), back


def backtrack(v, back) -> np.ndarray:
    """The path ending at the cheapest final cost v, followed back through the pointers."""
    path = np.zeros(len(back), dtype=np.int32)
    path[-1] = int(v.argmin())
    for t in range(len(back) - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    return path


def _flip_cost(bits, w) -> np.ndarray:
    """M[i, j] = sum over bits k where configurations i and j differ of w[i, k] (bits, w: (C, B)):
    [i_k != j_k] = i_k + j_k - 2 i_k j_k, so M = rowsum(bits w) + (w (1 - 2 bits)) bits^T."""
    w = w.astype(np.float32)
    return (bits * w).sum(1)[:, None] + (w * (1.0 - 2.0 * bits)) @ bits.T
