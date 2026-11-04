"""Synthetic 4-take validation set (spec part3-skeleton.md "Synthetic validation set").

Regenerate: python3 -m part3.synth --out fixtures/input/synthetic-4take

Deterministic. The truth is the real Part 2 squat (fixture frame = true body frame: x subject's left,
y up, z anterior, origin hip midpoint, which is also the world frame here). Each take adds a start
offset, tempo, time warp, performance variation, a camera (azimuth, pitch, roll), Part-2-like errors,
injected label swaps, and is put into Part 2's per-frame pelvis frame with the camera's up.

Random draw order inside a take, rng = numpy.random.default_rng([20261027, k]) with k = 1..4 for the
takes and 6 for the arm raise (the mirrored file draws nothing):
  1. phi: rng.uniform(0, 2 pi), the time-warp phase
  2. rng.uniform(size=(8, 2)): row i = (A_i / 1.5, psi_i / 2 pi) for the limb bone i of LIMB_BONES
  3. depth bias b: rng.uniform(-0.10, 0.10)
  4. bone-length factors: rng.normal(1.0, 0.03, size=(n, 18)), n = frames in the file
  5. joint noise: rng.standard_normal((n, 17, 3)), multiplied by sigma_j afterwards
The arm raise makes the same draws and ignores phi and the performance pairs.
"""

import argparse
import math
import pathlib
from dataclasses import dataclass

import numpy as np

from part3 import bones, io
from part3.geometry import body_up, pelvis_axes, pelvis_frame, point, rotation
from part3.joints import BONE_NAMES, GROUPS, INDEX, JOINTS, N_JOINTS, PAIRS, ROOT, swap_index
from part3.temporal import centred_mean

FIXTURE = io.REPO / "fixtures" / "input" / "part2-single" / "pose3d.json"
SEED = 20261027
FPS = 15
WARP_AMPLITUDE = 0.03       # tau(t) = t + 0.03 D sin(2 pi t / D + phi)
VARIATION_MAX_DEG = 1.5     # A ~ U(0, 1.5)
BONE_JITTER = 0.03
DEPTH_BIAS_MAX = 0.10
FAR_SIDE = ("right_elbow", "right_wrist", "right_knee", "right_ankle")
FAR_SIGMA_FACTOR = 2.67
FAR_CONF = 0.3
ARMRAISE_FRAMES = 105
ARMRAISE_PERIOD_S = 3.5
ARMRAISE_AMPLITUDE_DEG = 85.0
ARMRAISE_TAKE = 6
# Limb bones in draw order for the performance pairs, with the chain each belongs to.
LIMB_BONES = ("left_upper_arm", "right_upper_arm", "left_forearm", "right_forearm",
              "left_thigh", "right_thigh", "left_shank", "right_shank")
_CHAINS = (  # (root joint, mid joint, end joint, upper limb-bone index, lower limb-bone index)
    ("left_shoulder", "left_elbow", "left_wrist", 0, 2),
    ("right_shoulder", "right_elbow", "right_wrist", 1, 3),
    ("left_hip", "left_knee", "left_ankle", 4, 6),
    ("right_hip", "right_knee", "right_ankle", 5, 7),
)


@dataclass(frozen=True)
class Spec:
    k: int
    azimuth: float
    pitch: float
    roll: float
    offset_s: float
    tempo: float


TAKES = (Spec(1, 0, 12, -5, 0.4, 1.00), Spec(2, 45, -8, 6, 0.0, 0.88),
         Spec(3, 90, 20, 3, 0.8, 1.12), Spec(4, 180, -15, -8, 0.6, 0.95))
# Injected swaps per take: (group, first frame, last frame) in the take's own file, inclusive.
SWAPS = {4: (("body", 20, 24), ("body", 61, 65)),
         3: (("legs", 30, 35), ("legs", 80, 83), ("face", 86, 88)),
         2: (("arms", 50, 53),)}
FLIPS_INJECTED = sum(last - first + 1 for runs in SWAPS.values() for _, first, last in runs)  # 27
ARMRAISE_SPEC = Spec(ARMRAISE_TAKE, 180, -15, -8, 0.0, 1.00)


@dataclass
class Source:
    """The truth source: smoothed rigid squat frames, their bone lengths, sigma_j and the fixture hash."""
    frames: np.ndarray    # (N, 17, 3)
    lengths: np.ndarray   # (18,)
    sigma: np.ndarray     # (17,)
    sha256: str

    @property
    def duration(self):
        return (len(self.frames) - 1) / FPS


def noise_sigma(J):
    """sigma_j: rms over x, y, z of std(second difference of joint j) / sqrt(6), shape (17,)."""
    per_axis = np.diff(J, n=2, axis=0).std(axis=0) / math.sqrt(6.0)
    return np.sqrt((per_axis ** 2).mean(axis=1))


def load_source(path=FIXTURE):
    doc, sha256 = io.read_json(path)
    J = np.array([[[f["people"][0]["joints"][name][axis] for axis in "xyz"] for name in JOINTS]
                  for f in doc["frames"]])
    lengths = np.median(bones.measure(J), axis=0)
    frames = bones.retarget(centred_mean(J, 5), lengths)
    return Source(frames, lengths, noise_sigma(J), sha256)


# ---- camera ----------------------------------------------------------------------------------

def camera_axes(azimuth, pitch, roll):
    """(optical axis f, right r, up u) in world coordinates.

    The camera sits in direction (sin A, 0, cos A) from the subject and looks at it; pitch rotates
    about the camera right axis, then roll about the pitched optical axis.
    """
    a = math.radians(azimuth)
    f0 = -np.array([math.sin(a), 0.0, math.cos(a)])
    r0 = np.cross(f0, [0.0, 1.0, 0.0])
    u0 = np.cross(r0, f0)
    pitched = rotation(r0, pitch)
    f, u1 = pitched @ f0, pitched @ u0
    rolled = rotation(f, roll)
    return f, rolled @ r0, rolled @ u1


# ---- clean truth for a take --------------------------------------------------------------------

def take_lengths(src, spec):
    """(offset frames, motion frames) of a squat take."""
    n_off = int(round(FPS * spec.offset_s))
    n_motion = int(math.floor((len(src.frames) - 1) / spec.tempo + 1e-9)) + 1
    return n_off, n_motion


def truth_times(src, spec, phi, n_off, n_motion):
    """(n,) truth time in seconds of every file frame: 0 for the offset, then tau(min(tempo u, D))."""
    D = src.duration
    t = np.minimum(spec.tempo * np.arange(n_motion) / FPS, D)
    tau = np.clip(t + WARP_AMPLITUDE * D * np.sin(2 * np.pi * t / D + phi), 0.0, D)
    return np.concatenate([np.zeros(n_off), tau])


def truth_at(src, times):
    """Truth frames at `times` (linear interpolation between truth frames, rebuilt at truth lengths)."""
    pos = np.clip(np.asarray(times) * FPS, 0, len(src.frames) - 1)
    lo = np.floor(pos).astype(int)
    hi = np.minimum(lo + 1, len(src.frames) - 1)
    w = (pos - lo)[:, None, None]
    return bones.retarget(src.frames[lo] * (1 - w) + src.frames[hi] * w, src.lengths)


def _rot_x(deg):
    """(n, 3, 3) rotations about the body x axis."""
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    R = np.zeros(a.shape + (3, 3))
    R[..., 0, 0] = 1.0
    R[..., 1, 1], R[..., 1, 2], R[..., 2, 1], R[..., 2, 2] = c, -s, s, c
    return R


def apply_variation(J, times, duration, amp, psi):
    """Rotate each limb bone about body x by amp sin(2 pi t / D + psi) degrees, down the chain."""
    theta = amp[None, :] * np.sin(2 * np.pi * times[:, None] / duration + psi[None, :])
    out = np.array(J, copy=True)
    for root, mid, end, upper, lower in _CHAINS:
        s, e, w = (INDEX[name] for name in (root, mid, end))
        new_mid = J[:, s] + np.einsum("nij,nj->ni", _rot_x(theta[:, upper]), J[:, e] - J[:, s])
        out[:, e] = new_mid
        out[:, w] = new_mid + np.einsum("nij,nj->ni", _rot_x(theta[:, upper] + theta[:, lower]),
                                        J[:, w] - J[:, e])
    return out


def armraise_frames(src):
    """The first truth frame held 105 frames with both arms abducting in the frontal plane."""
    t = np.arange(ARMRAISE_FRAMES) / FPS
    theta = np.radians(ARMRAISE_AMPLITUDE_DEG * (1 - np.cos(2 * np.pi * t / ARMRAISE_PERIOD_S)))
    out = np.repeat(src.frames[:1], ARMRAISE_FRAMES, axis=0)
    length = {name: src.lengths[BONE_NAMES.index(name)] for name in BONE_NAMES}
    for side, sign in (("left", 1.0), ("right", -1.0)):
        shoulder = src.frames[0, INDEX[f"{side}_shoulder"]]
        direction = np.stack([sign * np.sin(theta), -np.cos(theta), np.zeros_like(theta)], axis=-1)
        upper, fore = length[f"{side}_upper_arm"], length[f"{side}_forearm"]
        out[:, INDEX[f"{side}_elbow"]] = shoulder + upper * direction
        out[:, INDEX[f"{side}_wrist"]] = shoulder + (upper + fore) * direction
    return out, t


# ---- errors, swaps, canonicalisation -----------------------------------------------------------

def draw(k, n):
    """All random draws of a take, in the documented order."""
    rng = np.random.default_rng([SEED, k])
    phi = rng.uniform(0, 2 * np.pi)
    pairs = rng.uniform(size=(8, 2))
    bias = rng.uniform(-DEPTH_BIAS_MAX, DEPTH_BIAS_MAX)
    factors = rng.normal(1.0, BONE_JITTER, size=(n, len(BONE_NAMES)))
    noise = rng.standard_normal((n, N_JOINTS, 3))
    return phi, VARIATION_MAX_DEG * pairs[:, 0], 2 * np.pi * pairs[:, 1], bias, factors, noise


def corrupt(src, clean, f, bias, factors, noise, far_side):
    """Part-2-like errors in world coordinates: bone factors, depth bias along f, joint noise."""
    J = bones.retarget(clean, src.lengths * factors)
    depth = np.einsum("nkj,j->nk", J - point(J, ROOT)[:, None, :], f)
    J = J + bias * depth[..., None] * f
    sigma = np.array(src.sigma)
    conf = np.ones((len(J), N_JOINTS))
    if far_side:
        for name in FAR_SIDE:
            sigma[INDEX[name]] *= FAR_SIGMA_FACTOR
            conf[:, INDEX[name]] = FAR_CONF
    return J + noise * sigma[None, :, None], conf


def inject_swaps(J, conf, schedule):
    """Swap labels (positions and conf together) per the schedule; returns the per-frame group lists."""
    J, conf = np.array(J, copy=True), np.array(conf, copy=True)
    swapped = [[] for _ in range(len(J))]
    for group, first, last in schedule:
        perm = swap_index(GROUPS[group])
        for i in range(first, last + 1):
            J[i], conf[i] = J[i][perm], conf[i][perm]
            swapped[i].append(group)
    return J, conf, swapped


def reflect(J, r):
    """Mirror positions across the plane through each frame's hip midpoint with normal r."""
    o = point(J, ROOT)[:, None, :]
    return J - 2 * np.einsum("nkj,j->nk", J - o, r)[..., None] * r


@dataclass
class Take:
    spec: Spec
    times: np.ndarray       # (n,) truth time of every frame
    clean: np.ndarray       # (n, 17, 3) clean truth in the true body frame
    world: np.ndarray       # (n, 17, 3) after errors, correct labels
    labelled: np.ndarray    # (n, 17, 3) after the injected swaps
    conf: np.ndarray        # (n, 17)
    swapped: list
    f: np.ndarray
    r: np.ndarray
    u: np.ndarray
    canon: np.ndarray       # (n, 17, 3) Part 2 frame of `labelled`
    up_in_input: np.ndarray  # (n, 3)


def finish(src, spec, times, clean, draws, schedule=(), far_side=False):
    """Camera, errors, swaps and canonicalisation for clean take frames."""
    _, _, _, bias, factors, noise = draws
    f, r, u = camera_axes(spec.azimuth, spec.pitch, spec.roll)
    world, conf = corrupt(src, clean, f, bias, factors, noise, far_side)
    labelled, conf, swapped = inject_swaps(world, conf, schedule)
    canon, _ = pelvis_frame(labelled, u)
    axes, _ = pelvis_axes(labelled, u)
    up_in = np.einsum("nij,j->ni", axes, body_up(clean)[0])
    return Take(spec, times, clean, world, labelled, conf, swapped, f, r, u, canon, up_in)


def build_take(src, spec):
    """One squat take (k = 1..4)."""
    n_off, n_motion = take_lengths(src, spec)
    draws = draw(spec.k, n_off + n_motion)
    phi, amp, psi = draws[:3]
    times = truth_times(src, spec, phi, n_off, n_motion)
    clean = apply_variation(truth_at(src, times), times, src.duration, amp, psi)
    return finish(src, spec, times, clean, draws, SWAPS.get(spec.k, ()), far_side=spec.k == 3)


def build_armraise(src):
    """The arm-raise negative control: take 4's camera and error parameters, stream k = 6."""
    clean, times = armraise_frames(src)
    return finish(src, ARMRAISE_SPEC, times, clean, draw(ARMRAISE_TAKE, len(clean)))


def build_mirrored(take):
    """Take 1 reflected across the plane through the hip midpoint with normal r, every pair swapped."""
    mirrored = reflect(take.world, take.r)[:, swap_index(PAIRS)]
    return pelvis_frame(mirrored, take.u)[0], take.conf[:, swap_index(PAIRS)]


# ---- serialisation -----------------------------------------------------------------------------

def _coord(value):
    return io.round_clean(value, io.OUTPUT_DECIMALS)


def pose3d_doc(J, conf, mirrored=False):
    frames = []
    for i in range(len(J)):
        joints = {name: {"x": _coord(J[i, j, 0]), "y": _coord(J[i, j, 1]), "z": _coord(J[i, j, 2]),
                         "conf": float(conf[i, j])} for j, name in enumerate(JOINTS)}
        frames.append({"frame": i, "t_ms": round(1000 * i / FPS, 3), "people": [{"id": 0, "joints": joints}]})
    doc = {"frames": frames}
    if mirrored:
        doc["mirrored"] = True
    return doc


def truth_doc(take):
    spec = take.spec
    frames = [{"frame": i, "truth_time_s": io.round_clean(take.times[i], 6),
               "up_in_input": [io.round_clean(v, 6) for v in take.up_in_input[i]],
               "swapped": take.swapped[i],
               "joints": {name: [_coord(v) for v in take.clean[i, j]] for j, name in enumerate(JOINTS)}}
              for i in range(len(take.clean))]
    return {"take": spec.k,
            "camera": {"azimuth_deg": spec.azimuth, "pitch_deg": spec.pitch, "roll_deg": spec.roll},
            "start_offset_s": spec.offset_s, "tempo": spec.tempo, "frames": frames}


def source_text(src):
    schedule = "; ".join(f"take {k}: " + ", ".join(f"{g} {a}-{b}" for g, a, b in runs)
                         for k, runs in sorted(SWAPS.items(), reverse=True))
    return f"""# Synthetic 4-take set (derived, not recorded)

- **What:** four synthetic single-phone takes of the same squat, a mirrored copy of take 1, and an
  arm-raise negative control. Derived from the real Part 2 squat
  `fixtures/input/part2-single/pose3d.json` (SHA-256 `{src.sha256}`), smoothed (5-frame
  mean) and rebuilt at the fixture's median bone lengths.
- **Regenerate:** `python3 -m part3.synth --out fixtures/input/synthetic-4take` (deterministic; a test
  proves the output is byte-identical). Seed `numpy.random.default_rng([{SEED}, k])`, draw order in
  `part3/synth.py`.
- **Simulated per take:** start offset, tempo and a smooth time warp, performance variation up to 3
  degrees, a camera (azimuth 0, 45, 90, 180; phone pitch and roll), Part-2-like errors (per-frame
  bone-length jitter 3%, per-take depth bias up to 10%, joint noise at the jitter measured on the real
  fixture, far-side joints in take 3 at conf 0.3 with 2.67 times that noise), injected label swaps,
  and Part 2's per-frame pelvis frame with the camera's up.
- **Injected label swaps** (frame indices of the take's own file, inclusive):
  {schedule}.
  `flips_injected` = {FLIPS_INJECTED} frames.
- **Files:** `take-<k>/pose3d.json` and `truth.json` (k = 1 to 4; `truth.json` also carries `truth_time_s`
  per frame), `take-1-mirrored/pose3d.json` (`"mirrored": true`), `negative-armraise/pose3d.json` and
  `truth.json`.
"""


def generate(out_dir):
    """Write the full synthetic set under `out_dir`."""
    out = pathlib.Path(out_dir)
    src = load_source()

    def write(rel, text):
        io.write_text(out / rel, text, mkdir=True)

    takes = [build_take(src, spec) for spec in TAKES]
    for take in takes:
        write(f"take-{take.spec.k}/pose3d.json", io.dumps(pose3d_doc(take.canon, take.conf)))
        write(f"take-{take.spec.k}/truth.json", io.dumps(truth_doc(take)))
    mirrored, mirrored_conf = build_mirrored(takes[0])
    write("take-1-mirrored/pose3d.json", io.dumps(pose3d_doc(mirrored, mirrored_conf, mirrored=True)))
    armraise = build_armraise(src)
    write("negative-armraise/pose3d.json", io.dumps(pose3d_doc(armraise.canon, armraise.conf)))
    write("negative-armraise/truth.json", io.dumps(truth_doc(armraise)))
    write("SOURCE.md", source_text(src))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m part3.synth", description=__doc__.split("\n")[0])
    parser.add_argument("--out", required=True, help="output directory, e.g. fixtures/input/synthetic-4take")
    generate(parser.parse_args(argv).out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
