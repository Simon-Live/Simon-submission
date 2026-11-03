// Retarget core: 17 Simon joints to a world rotation per bone of any humanoid rig (docs/specs/model-retarget.md).
// Pure math, no three. Quaternions are [x, y, z, w], Hamilton product, active rotation, the convention of
// modules/part-3/part3/rig.py. Pose frame: x subject left, y up, z anterior, metres (part7/animation_format.py).
import {
  vSub, vAdd, vScale, vDot, vCross, vLen, vNorm,
  qMul, qInv, qNorm, qSlerp, qRotate, basisFromPrimaryRef,
} from './quat.js';

export const SIMON_JOINTS = [
  'nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear', 'left_shoulder', 'right_shoulder', 'left_elbow',
  'right_elbow', 'left_wrist', 'right_wrist', 'left_hip', 'right_hip', 'left_knee', 'right_knee', 'left_ankle',
  'right_ankle',
];
// Leg length of the default Part 3 profile (thigh 0.4165 + shank 0.4182); only a fallback (correction 3).
export const SIMON_LEG_M = 0.8347;

const SIDES = ['left', 'right'];
const sided = (parts) => SIDES.flatMap((s) => parts.map((p) => s + p));
export const CANON = [
  'hips', 'spine', 'chest', 'upperChest', 'neck', 'head',
  ...sided(['Shoulder', 'UpperArm', 'LowerArm', 'Hand']),
  ...sided(['UpperLeg', 'LowerLeg', 'Foot', 'Toes']),
];
export const REQUIRED = [
  'hips', 'spine', 'head', ...sided(['UpperArm', 'LowerArm', 'Hand', 'UpperLeg', 'LowerLeg', 'Foot']),
];

// The bone whose head is a bone's tail, first present wins.
const TAIL_CHILD = {
  hips: ['spine'], spine: ['chest', 'upperChest', 'neck'], chest: ['upperChest', 'neck'], upperChest: ['neck'],
  neck: ['head'], head: [], leftShoulder: ['leftUpperArm'], rightShoulder: ['rightUpperArm'],
  leftUpperArm: ['leftLowerArm'], rightUpperArm: ['rightLowerArm'], leftLowerArm: ['leftHand'],
  rightLowerArm: ['rightHand'], leftHand: [], rightHand: [], leftUpperLeg: ['leftLowerLeg'],
  rightUpperLeg: ['rightLowerLeg'], leftLowerLeg: ['leftFoot'], rightLowerLeg: ['rightFoot'],
  leftFoot: ['leftToes'], rightFoot: ['rightToes'], leftToes: [], rightToes: [],
};

const LIMBS = [
  { key: 'leftArm', kind: 'arm', pts: ['left_shoulder', 'left_elbow', 'left_wrist'], bones: ['leftUpperArm', 'leftLowerArm'] },
  { key: 'rightArm', kind: 'arm', pts: ['right_shoulder', 'right_elbow', 'right_wrist'], bones: ['rightUpperArm', 'rightLowerArm'] },
  { key: 'leftLeg', kind: 'leg', pts: ['left_hip', 'left_knee', 'left_ankle'], bones: ['leftUpperLeg', 'leftLowerLeg'] },
  { key: 'rightLeg', kind: 'leg', pts: ['right_hip', 'right_knee', 'right_ankle'], bones: ['rightUpperLeg', 'rightLowerLeg'] },
];

// A change of sign of the bend normal below this bend (the end of the blend from the held normal) is read as hyperextension or noise, not a new bend plane. Held higher, a plane that was locked in by a noisy near-straight frame stayed reversed until 40 degrees and then flipped by 180.
const SIGN_HOLD_DEG = 20;
const RAD = Math.PI / 180;

// Average head proportions from one real take (metres): ears, eyes and nose relative to the ear midpoint.
const HEAD = { earHalf: 0.064, eyeHalf: 0.031, eyeUp: 0.01, eyeFwd: 0.068, noseUp: -0.034, noseFwd: 0.097, pivotUp: 0.07 };

const isVec = (v) => Array.isArray(v) && v.length >= 3 && Number.isFinite(v[0]) && Number.isFinite(v[1]) && Number.isFinite(v[2]);
const mid = (a, b) => (a && b ? vScale(vAdd(a, b), 0.5) : null);
const sub = (a, b) => (a && b ? vSub(a, b) : null);
const angleDeg = (a, b) => Math.acos(Math.max(-1, Math.min(1, vDot(a, b)))) / RAD;
const IDENT = [0, 0, 0, 1];

// The body frame a limb's twist is measured in: the chest for arms, the hips for legs, the world when unknown.
// `fwd` and `up` are unit vectors, `rot` the basis rotation (null = world axes).
function bodyFrame(basis) {
  if (!basis) return { rot: null, fwd: [0, 0, 1], up: [0, 1, 0] };
  return { rot: basis, fwd: qRotate(basis, [0, 0, 1]), up: qRotate(basis, [0, 1, 0]) };
}
const toBody = (body, v) => (body.rot ? qRotate(qInv(body.rot), v) : v);
const fromBody = (body, v) => (body.rot ? qRotate(body.rot, v) : v);

// Normal of a straight limb with no history: the limb direction crossed with the body's forward (arms) or
// backward (legs), so it turns with the body. Along the forward axis it uses the body's up axis instead.
function fallbackNormal(kind, dir, body) {
  const ref = kind === 'arm' ? body.fwd : vScale(body.fwd, -1);
  let n = vCross(dir, ref);
  if (vLen(n) < 0.2) n = vCross(dir, body.up);
  return vNorm(n);
}

// One limb: segment directions, the bend normal to use, and the bases of its two bones.
function limbFrame(limb, j, prev, minBend, body) {
  const [a, b, c] = limb.pts.map((n) => j[n]);
  const u = a && b ? vNorm(vSub(b, a)) : null;
  const l = b && c ? vNorm(vSub(c, b)) : null;
  const pv = prev && prev[limb.key] ? fromBody(body, prev[limb.key]) : null;
  let bend = null;
  let raw = null;
  if (u && l) {
    bend = angleDeg(u, l);
    raw = vNorm(vCross(u, l));
  }
  let n = pv;
  if (raw && bend >= minBend) {
    if (pv && vDot(raw, pv) < 0 && bend < SIGN_HOLD_DEG) raw = vScale(raw, -1);
    if (pv && bend < 2 * minBend) {
      const t = (bend - minBend) / minBend;
      n = vNorm(vAdd(vScale(pv, 1 - t), vScale(raw, t))) || raw;
    } else n = raw;
  }
  const basisOf = (dir) => {
    if (!dir) return null;
    return (n && basisFromPrimaryRef(dir, n, 'y', 'x'))
      || basisFromPrimaryRef(dir, fallbackNormal(limb.kind, dir, body), 'y', 'x');
  };
  const anchor = u || l;
  const used = anchor ? n || fallbackNormal(limb.kind, anchor, body) : null;
  // Only a measured bend is remembered. The fallback normal of a limb never seen bent is a guess, and holding its sign
  // would keep a real bend plane reversed until the bend passed SIGN_HOLD_DEG and then flip it by 180 degrees.
  const flat = n && anchor ? vNorm(vSub(n, vScale(anchor, vDot(n, anchor)))) : null;
  return {
    dirs: [u, l], normal: used, bendDeg: bend, bases: [basisOf(u), basisOf(l)],
    next: flat ? toBody(body, flat) : prev && prev[limb.key] || null,
  };
}

function headFrame(j, neck, shLat) {
  const ears = j.left_ear && j.right_ear;
  const eyes = j.left_eye && j.right_eye;
  const lat = ears ? vSub(j.left_ear, j.right_ear) : eyes ? vSub(j.left_eye, j.right_eye) : shLat;
  const base = ears ? mid(j.left_ear, j.right_ear) : eyes ? mid(j.left_eye, j.right_eye) : null;
  if (lat && base && j.nose) return basisFromPrimaryRef(lat, vSub(j.nose, base), 'x', 'z');
  if (j.nose && neck && shLat) return basisFromPrimaryRef(vSub(j.nose, neck), shLat, 'y', 'x');
  if (base && neck && lat) return basisFromPrimaryRef(vSub(base, neck), lat, 'y', 'x');
  return null;
}

// Source frame from named joints (null = absent). `prev` is the solver's previous bend normals, or null.
function frameFromNamed(j, prev, minBend) {
  const pelvis = mid(j.left_hip, j.right_hip);
  const neck = mid(j.left_shoulder, j.right_shoulder);
  const up = pelvis && neck ? vSub(neck, pelvis) : null;
  const hipsLat = sub(j.left_hip, j.right_hip);
  const shLat = sub(j.left_shoulder, j.right_shoulder);
  const frame = {
    pelvis, neck, up: up ? vNorm(up) : null,
    hipsBasis: up && hipsLat ? basisFromPrimaryRef(up, hipsLat, 'y', 'x') : null,
    chestBasis: up && shLat ? basisFromPrimaryRef(up, shLat, 'y', 'x') : null,
    headBasis: headFrame(j, neck, shLat),
    limbs: {},
  };
  const bodies = { arm: bodyFrame(frame.chestBasis || frame.hipsBasis), leg: bodyFrame(frame.hipsBasis || frame.chestBasis) };
  for (const limb of LIMBS) frame.limbs[limb.key] = limbFrame(limb, j, prev, minBend, bodies[limb.kind]);
  return frame;
}

function namedFromPose(pose, nameIdx) {
  const j = {};
  for (const n of SIMON_JOINTS) {
    const i = nameIdx[n];
    const v = i === undefined || !pose ? null : pose[i];
    j[n] = isVec(v) ? [v[0], v[1], v[2]] : null;
  }
  return j;
}

const SIMON_IDX = Object.fromEntries(SIMON_JOINTS.map((n, i) => [n, i]));

// Source frame of one 17-joint pose, stateless (a straight limb uses the fixed rest normal). For tests.
export function sourceFrame(pose17, minBendDeg = 10) {
  return frameFromNamed(namedFromPose(pose17, SIMON_IDX), null, minBendDeg);
}

function checkRest(rest) {
  if (!rest || typeof rest !== 'object') throw new Error('retarget: rest must be an object');
  const bones = {};
  for (const name of CANON) {
    const r = rest[name];
    if (!r) {
      if (REQUIRED.includes(name)) throw new Error(`retarget: missing required bone ${name}`);
      continue;
    }
    const world = r.world;
    if (!isVec(r.head) || !Array.isArray(world) || world.length !== 4 || !world.every(Number.isFinite)
      || (r.tail != null && !isVec(r.tail))) throw new Error(`retarget: bad rest for ${name}`);
    bones[name] = { head: r.head.slice(0, 3), tail: r.tail ? r.tail.slice(0, 3) : null, world: qNorm(world) };
  }
  return bones;
}

// A full 17-joint pose for the rest character, with the head features placed by average proportions.
function restPose17(bones) {
  const H = (n) => bones[n].head;
  const pelvis = mid(H('leftUpperLeg'), H('rightUpperLeg'));
  const neck = mid(H('leftUpperArm'), H('rightUpperArm'));
  const lat = vNorm(vSub(H('leftUpperArm'), H('rightUpperArm'))) || [1, 0, 0];
  const up = vNorm(vSub(neck, pelvis)) || [0, 1, 0];
  const fwd = vNorm(vCross(lat, up)) || [0, 0, 1];
  const at = (base, l, u, f) => vAdd(base, vAdd(vScale(lat, l), vAdd(vScale(up, u), vScale(fwd, f))));
  const c = vAdd(H('head'), vScale(up, HEAD.pivotUp));
  const pose = {
    nose: at(c, 0, HEAD.noseUp, HEAD.noseFwd),
    left_eye: at(c, HEAD.eyeHalf, HEAD.eyeUp, HEAD.eyeFwd), right_eye: at(c, -HEAD.eyeHalf, HEAD.eyeUp, HEAD.eyeFwd),
    left_ear: at(c, HEAD.earHalf, 0, 0), right_ear: at(c, -HEAD.earHalf, 0, 0),
    left_shoulder: H('leftUpperArm'), right_shoulder: H('rightUpperArm'),
    left_elbow: H('leftLowerArm'), right_elbow: H('rightLowerArm'),
    left_wrist: H('leftHand'), right_wrist: H('rightHand'),
    left_hip: H('leftUpperLeg'), right_hip: H('rightUpperLeg'),
    left_knee: H('leftLowerLeg'), right_knee: H('rightLowerLeg'),
    left_ankle: H('leftFoot'), right_ankle: H('rightFoot'),
  };
  return SIMON_JOINTS.map((n) => pose[n].slice());
}

// rest: {<canonical>: {head:[x,y,z], tail:[x,y,z]|null, world:[x,y,z,w]}} in the character's normalized frame
// (+Y up, facing +Z, left at +X). Throws when a required bone is missing or a value is not finite.
export function restFromModel(rest) {
  const bones = checkRest(rest);
  for (const name of CANON) {
    const b = bones[name];
    if (!b || b.tail) continue;
    const kid = TAIL_CHILD[name].find((k) => bones[k]);
    if (kid) b.tail = bones[kid].head.slice();
  }
  const present = CANON.filter((n) => bones[n]);
  const world = Object.fromEntries(present.map((n) => [n, bones[n].world]));
  return { bones, present, world, pose17: restPose17(bones) };
}

function maskKey(j) {
  let k = '';
  for (const n of SIMON_JOINTS) k += j[n] ? '1' : '0';
  return k;
}

function segmentsOf(frame) {
  const s = {};
  for (const limb of LIMBS) {
    limb.bones.forEach((b, i) => { if (frame.limbs[limb.key].dirs[i]) s[b] = frame.limbs[limb.key].dirs[i]; });
  }
  if (frame.up) { s.spine = frame.up; s.chest = frame.up; s.hips = frame.up; }
  if (frame.headBasis) s.head = qRotate(frame.headBasis, [0, 1, 0]);
  return s;
}

const delta = (cur, rest) => (cur && rest ? qNorm(qMul(cur, qInv(rest))) : null);

// restInfo from restFromModel; opts.jointNames names the entries of each pose passed to solve (default SIMON_JOINTS).
export function createSolver(restInfo, opts = {}) {
  const { jointNames = SIMON_JOINTS, spineWeights = null, neckShare = 0.5, minBendDeg = 10 } = opts;
  const nameIdx = {};
  jointNames.forEach((n, i) => { if (SIMON_IDX[n] !== undefined) nameIdx[n] = i; });
  const has = (n) => !!restInfo.world[n];
  const spineBones = ['spine', 'chest', 'upperChest'].filter(has);
  const sw = {};
  spineBones.forEach((b, k) => { sw[b] = (k + 1) / spineBones.length; });
  if (spineWeights) {
    const given = { spine: spineWeights[0], chest: spineWeights[1], upperChest: spineWeights[2] };
    const top = given[spineBones[spineBones.length - 1]];
    if (top > 0) for (const b of spineBones) if (Number.isFinite(given[b])) sw[b] = given[b] / top;
  }
  const restFrames = new Map();
  const restFor = (j) => {
    const key = maskKey(j);
    let f = restFrames.get(key);
    if (!f) {
      const masked = {};
      restInfo.pose17.forEach((v, i) => { masked[SIMON_JOINTS[i]] = j[SIMON_JOINTS[i]] ? v : null; });
      f = frameFromNamed(masked, null, minBendDeg);
      restFrames.set(key, f);
    }
    return f;
  };
  let prev = {};
  const full = {};
  SIMON_JOINTS.forEach((n, i) => { full[n] = restInfo.pose17[i]; });
  const restSegments = segmentsOf(frameFromNamed(full, null, minBendDeg));
  const solver = { lastSegments: {}, restSegments, reset() { prev = {}; solver.lastSegments = {}; } };

  // dim is accepted for interface parity: dimmed joints are filled upstream and skins are not dimmed per bone.
  solver.solve = function solve(pose, dim) { // eslint-disable-line no-unused-vars
    const j = namedFromPose(pose, nameIdx);
    const cur = frameFromNamed(j, prev, minBendDeg);
    const rest = restFor(j);
    const hipsRaw = delta(cur.hipsBasis, rest.hipsBasis);
    const chestRaw = delta(cur.chestBasis, rest.chestBasis);
    const chestD = chestRaw || hipsRaw || IDENT;
    const hipsD = hipsRaw || chestRaw || IDENT;
    const headD = delta(cur.headBasis, rest.headBasis) || chestD;
    const D = { hips: hipsD, neck: qSlerp(chestD, headD, neckShare), head: headD };
    for (const b of spineBones) D[b] = qSlerp(hipsD, chestD, sw[b]);
    D.leftShoulder = chestD;
    D.rightShoulder = chestD;
    for (const limb of LIMBS) {
      const [up, lo] = limb.bones;
      const root = limb.kind === 'arm' ? chestD : hipsD;
      const lf = cur.limbs[limb.key];
      const rf = rest.limbs[limb.key];
      D[up] = delta(lf.bases[0], rf.bases[0]) || root;
      D[lo] = delta(lf.bases[1], rf.bases[1]) || D[up];
      const tail = limb.kind === 'arm' ? limb.key.replace('Arm', 'Hand') : limb.key.replace('Leg', 'Foot');
      D[tail] = D[lo];
      if (limb.kind === 'leg') D[limb.key.replace('Leg', 'Toes')] = D[lo];
    }
    const out = {};
    for (const n of restInfo.present) out[n] = qNorm(qMul(D[n] || IDENT, restInfo.world[n]));
    for (const limb of LIMBS) if (cur.limbs[limb.key].next) prev[limb.key] = cur.limbs[limb.key].next;
    solver.lastSegments = segmentsOf(cur);
    return out;
  };
  return solver;
}
