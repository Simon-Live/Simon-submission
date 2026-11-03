// Pure helpers for placing a character: fit scale from the incoming pose and world to local rotations.
// No three, no DOM (docs/specs/model-retarget.md, AC-RT7, AC-RT8).
import { qMul, qInv, qNorm, vLen, vSub } from './quat.js';
import { SIMON_JOINTS, SIMON_LEG_M } from './retarget.js';

const isVec = (v) => Array.isArray(v) && v.length >= 3 && Number.isFinite(v[0]) && Number.isFinite(v[1]) && Number.isFinite(v[2]);

export function median(values) {
  const v = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = v.length >> 1;
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

// Hip to knee plus knee to ankle, per leg seen in this pose: an array of 0, 1 or 2 lengths in metres.
export function legLengthsFromPose(pose, jointNames = SIMON_JOINTS) {
  const at = (n) => {
    const i = jointNames.indexOf(n);
    const v = i < 0 || !pose ? null : pose[i];
    return isVec(v) ? v : null;
  };
  const out = [];
  for (const side of ['left', 'right']) {
    const h = at(`${side}_hip`);
    const k = at(`${side}_knee`);
    const a = at(`${side}_ankle`);
    if (h && k && a) out.push(vLen(vSub(h, k)) + vLen(vSub(k, a)));
  }
  return out;
}

// Median leg length over a whole track (correction 3: measured per figure, never a fixed constant).
// Returns {legM, measured}; with no leg ever seen, SIMON_LEG_M and measured false.
export function legLengthFromTrack(poses, jointNames = SIMON_JOINTS) {
  const all = [];
  for (const p of poses || []) all.push(...legLengthsFromPose(p, jointNames));
  const m = median(all);
  return m && m > 0 ? { legM: m, measured: true } : { legM: SIMON_LEG_M, measured: false };
}

// Uniform scale that makes a character whose own leg is characterLegM as long as the person's leg.
export function fitScaleFromTrack(poses, jointNames, characterLegM) {
  if (!(characterLegM > 0)) throw new Error('skin-math: characterLegM must be positive');
  const { legM, measured } = legLengthFromTrack(poses, jointNames);
  return { scale: legM / characterLegM, legM, measured };
}

// Local rotation of a bone from its world rotation and its parent's world rotation (null parent = the world).
export function localFromWorld(parentWorld, world) {
  return parentWorld ? qNorm(qMul(qInv(parentWorld), world)) : qNorm(world);
}

// Local rotations for bones listed parents first. world: {name: quat}; parentOf: {name: name|null}.
// A parent without a world rotation counts as the world, so partial maps stay usable.
export function worldToLocalChain(order, parentOf, world) {
  const out = {};
  for (const name of order) {
    if (!world[name]) continue;
    const parent = parentOf[name];
    out[name] = localFromWorld(parent ? world[parent] : null, world[name]);
  }
  return out;
}

// Angle in degrees (0 to 90, the axis has no sign) between the main axis of a cloud of points and a direction.
// `points` is a flat [x, y, z, ...] array; the axis is the strongest eigenvector of the covariance by power iteration,
// started from `dir` so a limb's own axis wins over any other. Null for fewer than 3 points or a zero direction.
export function axisAngleDeg(points, dir) {
  const n = points.length / 3;
  const dl = Math.hypot(dir[0], dir[1], dir[2]);
  if (n < 3 || !dl) return null;
  const m = [0, 0, 0];
  for (let i = 0; i < points.length; i++) m[i % 3] += points[i] / n;
  const c = [0, 0, 0, 0, 0, 0]; // xx xy xz yy yz zz
  for (let i = 0; i < points.length; i += 3) {
    const x = points[i] - m[0];
    const y = points[i + 1] - m[1];
    const z = points[i + 2] - m[2];
    c[0] += x * x; c[1] += x * y; c[2] += x * z; c[3] += y * y; c[4] += y * z; c[5] += z * z;
  }
  let v = [dir[0] / dl, dir[1] / dl, dir[2] / dl];
  for (let it = 0; it < 24; it++) {
    const w = [c[0] * v[0] + c[1] * v[1] + c[2] * v[2], c[1] * v[0] + c[3] * v[1] + c[4] * v[2], c[2] * v[0] + c[4] * v[1] + c[5] * v[2]];
    const l = Math.hypot(w[0], w[1], w[2]);
    if (!l) return null;
    v = [w[0] / l, w[1] / l, w[2] / l];
  }
  const cos = Math.abs(v[0] * dir[0] + v[1] * dir[1] + v[2] * dir[2]) / dl;
  return (Math.acos(Math.min(1, cos)) * 180) / Math.PI;
}
