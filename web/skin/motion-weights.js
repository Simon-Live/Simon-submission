// Skin weights from the person's own motion (docs/specs/person-skin.md AC-PS17): which bones each vertex of the SAM 3D
// Body mesh follows, judged over many of the mesh's own frames and their pose3d keypoints instead of one rest pose.
//
// In one pose a vertex can sit nearer the wrong bone: with the arms down, the side of the waist is a few centimetres
// from the forearm and far from the spine, so a rest-pose nearest-bone (or nearest-joint label) rule binds it to the arm,
// and once the arm rises the waist is pulled out into a slab. Over the take a vertex stays close to the bone it moves
// with and drifts away from the others, so the cost of a bone is the power mean (p = 8) of the vertex's distance to it
// over the frames: a few frames with the arm away from the waist rule the arm out, and one noisy frame does not decide
// alone. The second bone is joined to the first (parent or child) unless one of them is a torso bone, so a foot never
// shares the other shin, while a waist the take never parted from a resting hand may still share it. Plain arithmetic
// on typed arrays, no three; about 2500 vertices x 17 segments x 65 frames.
//
// The server computes the same weights once (part7.skin_weights) and ships them in rest.json; this file is the fallback
// for a rest file without them. It is part7.take_rig.motion_weights operation for operation (powers by multiplication,
// roots by Math.sqrt, doubles throughout), so the two give equal bits on tests/part7/skin-weights-vector.json (AC-PS18).

const EPS = 0.005; // metres; keeps 1/c^2 finite

/** A bone segment from head `a` to tail `b`: [ax, ay, az, dx, dy, dz, squared length], the form segD2 reads. */
export function segment(a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const dz = b[2] - a[2];
  return [a[0], a[1], a[2], dx, dy, dz, dx * dx + dy * dy + dz * dz];
}

/** Squared point-to-segment distance: the one such helper of the skin code (person-skin.js and the tests use it too). */
export function segD2(px, py, pz, s) {
  const qx = px - s[0];
  const qy = py - s[1];
  const qz = pz - s[2];
  let t = s[6] ? (qx * s[3] + qy * s[4] + qz * s[5]) / s[6] : 0;
  t = t < 0 ? 0 : t > 1 ? 1 : t;
  const ex = qx - s[3] * t;
  const ey = qy - s[4] * t;
  const ez = qz - s[5] * t;
  return ex * ex + ey * ey + ez * ez;
}

/**
 * Two-bone weights from motion. `frames` is a list of {positions: Float64Array(3n) in metres, joints: {name: [x,y,z]}}
 * (the rest frame first), `segments` a list of [boneIndex, fromJoint, toJoint] (a bone may own several; its nearest
 * counts in each frame), `parents` the parent index of each bone (-1 for the root; its length is the bone count),
 * `torso` a Set of the torso bones. Returns {bone: Uint8Array(2n), weight: Float64Array(2n)}: each vertex's lowest-cost
 * bone and the lowest-cost bone it may share, weighted by inverse squared cost, summing to 1.
 */
export function motionWeights(frames, segments, parents, torso, n) {
  const boneCount = parents.length;
  const joined = (a, b) => parents[a] === b || parents[b] === a || torso.has(a) || torso.has(b);
  const acc = new Float64Array(n * boneCount);
  const near = new Float64Array(boneCount);
  for (const { positions, joints } of frames) {
    const segs = segments.map(([b, f, t]) => [b, segment(joints[f], joints[t])]);
    for (let i = 0; i < n; i++) {
      const px = positions[3 * i];
      const py = positions[3 * i + 1];
      const pz = positions[3 * i + 2];
      near.fill(Infinity);
      for (const [b, s] of segs) {
        const d2 = segD2(px, py, pz, s);
        if (d2 < near[b]) near[b] = d2;
      }
      for (let b = 0; b < boneCount; b++) {
        if (near[b] === Infinity) continue;
        const d4 = near[b] * near[b];
        acc[i * boneCount + b] += d4 * d4;
      }
    }
  }
  const owned = new Set(segments.map((s) => s[0]));
  const cost = new Float64Array(boneCount);
  const bone = new Uint8Array(2 * n);
  const weight = new Float64Array(2 * n);
  for (let i = 0; i < n; i++) {
    cost.fill(Infinity);
    let b0 = -1;
    for (let b = 0; b < boneCount; b++) {
      if (owned.has(b)) cost[b] = Math.sqrt(Math.sqrt(Math.sqrt(acc[i * boneCount + b] / frames.length)));
      if (cost[b] !== Infinity && (b0 < 0 || cost[b] < cost[b0])) b0 = b;
    }
    let b1 = -1;
    for (let b = 0; b < boneCount; b++) {
      if (b !== b0 && joined(b, b0) && cost[b] !== Infinity && (b1 < 0 || cost[b] < cost[b1])) b1 = b;
    }
    const c0 = cost[b0] + EPS;
    const w0 = 1 / (c0 * c0);
    const c1 = b1 >= 0 ? cost[b1] + EPS : 0;
    const w1 = b1 >= 0 ? 1 / (c1 * c1) : 0;
    bone[2 * i] = b0;
    bone[2 * i + 1] = b1 >= 0 ? b1 : b0;
    weight[2 * i] = w0 / (w0 + w1);
    weight[2 * i + 1] = w1 / (w0 + w1);
  }
  return { bone, weight };
}
