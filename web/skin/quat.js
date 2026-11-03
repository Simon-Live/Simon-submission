// Pure vector and quaternion math on plain arrays. No three, no DOM (docs/specs/model-retarget.md, AC-RT7).
// Quaternions are [x, y, z, w], Hamilton product, active rotation: qMul(a, b) applies b first, then a.

const EPS = 1e-9;

export const vSub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const vAdd = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const vScale = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
export const vDot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const vCross = (a, b) => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
export const vLen = (a) => Math.hypot(a[0], a[1], a[2]);

// Unit vector, or null for a zero or non-finite vector.
export function vNorm(a) {
  const l = vLen(a);
  if (!(l > EPS) || !Number.isFinite(l)) return null;
  return [a[0] / l, a[1] / l, a[2] / l];
}

export function qMul(a, b) {
  const [ax, ay, az, aw] = a;
  const [bx, by, bz, bw] = b;
  return [
    aw * bx + ax * bw + ay * bz - az * by,
    aw * by - ax * bz + ay * bw + az * bx,
    aw * bz + ax * by - ay * bx + az * bw,
    aw * bw - ax * bx - ay * by - az * bz,
  ];
}

// Inverse of a unit quaternion.
export const qInv = (q) => [-q[0], -q[1], -q[2], q[3]];

export function qNorm(q) {
  const l = Math.hypot(q[0], q[1], q[2], q[3]);
  if (!(l > EPS)) return [0, 0, 0, 1];
  return [q[0] / l, q[1] / l, q[2] / l, q[3] / l];
}

// Shortest-path spherical interpolation, t in [0, 1].
export function qSlerp(a, b, t) {
  let d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3];
  let bb = b;
  if (d < 0) { d = -d; bb = [-b[0], -b[1], -b[2], -b[3]]; }
  if (d > 0.9995) {
    return qNorm([
      a[0] + (bb[0] - a[0]) * t, a[1] + (bb[1] - a[1]) * t,
      a[2] + (bb[2] - a[2]) * t, a[3] + (bb[3] - a[3]) * t,
    ]);
  }
  const th = Math.acos(Math.min(1, d));
  const s = Math.sin(th);
  const wa = Math.sin((1 - t) * th) / s;
  const wb = Math.sin(t * th) / s;
  return qNorm([
    a[0] * wa + bb[0] * wb, a[1] * wa + bb[1] * wb,
    a[2] * wa + bb[2] * wb, a[3] * wa + bb[3] * wb,
  ]);
}

// Rotation whose columns are the given orthonormal x, y, z axes.
export function qFromBasis(x, y, z) {
  const m00 = x[0], m10 = x[1], m20 = x[2];
  const m01 = y[0], m11 = y[1], m21 = y[2];
  const m02 = z[0], m12 = z[1], m22 = z[2];
  const tr = m00 + m11 + m22;
  let q;
  if (tr > 0) {
    const s = Math.sqrt(tr + 1) * 2;
    q = [(m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s];
  } else if (m00 > m11 && m00 > m22) {
    const s = Math.sqrt(1 + m00 - m11 - m22) * 2;
    q = [0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s];
  } else if (m11 > m22) {
    const s = Math.sqrt(1 + m11 - m00 - m22) * 2;
    q = [(m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s];
  } else {
    const s = Math.sqrt(1 + m22 - m00 - m11) * 2;
    q = [(m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s];
  }
  return qNorm(q);
}

export function qRotate(q, v) {
  const u = [q[0], q[1], q[2]];
  const t = vScale(vCross(u, v), 2);
  return vAdd(vAdd(v, vScale(t, q[3])), vCross(u, t));
}

// Angle in degrees of the rotation between two unit quaternions (0 to 180).
export function qAngleDeg(a, b) {
  const d = Math.abs(a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]);
  return (2 * Math.acos(Math.min(1, d)) * 180) / Math.PI;
}

const AXIS = { x: 0, y: 1, z: 2 };

// Rotation with `primary` on primaryAxis and the part of `ref` orthogonal to it on refAxis; the third axis
// follows from a right-handed frame. Null when a vector is degenerate or ref is parallel to primary.
export function basisFromPrimaryRef(primary, ref, primaryAxis, refAxis) {
  const pi = AXIS[primaryAxis];
  const ri = AXIS[refAxis];
  if (pi === undefined || ri === undefined || pi === ri) throw new Error('basisFromPrimaryRef: bad axes');
  const p = vNorm(primary);
  if (!p || !ref) return null;
  const r = vNorm(vSub(ref, vScale(p, vDot(ref, p))));
  if (!r) return null;
  const cyclic = (ri - pi + 3) % 3 === 1;
  const t = cyclic ? vCross(p, r) : vCross(r, p);
  const axes = [null, null, null];
  axes[pi] = p;
  axes[ri] = r;
  axes[3 - pi - ri] = t;
  return qFromBasis(axes[0], axes[1], axes[2]);
}
