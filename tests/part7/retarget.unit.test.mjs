// docs/specs/model-retarget.md: quat.js and retarget.js, AC-RT1 to AC-RT7 and AC-NFR-RT1.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as Q from '../../web/skin/quat.js';
import {
  CANON, REQUIRED, SIMON_JOINTS, SIMON_LEG_M, restFromModel, createSolver, sourceFrame,
} from '../../web/skin/retarget.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIX = path.join(HERE, 'fixtures', 'skin');
const load = (n) => JSON.parse(fs.readFileSync(path.join(FIX, n), 'utf8'));
const RESTS = ['rest-tpose.json', 'rest-apose.json', 'rest-ual2f.json', 'rest-riggedfigure.json'];
const restOf = (n) => load(n).bones;
const deg = (r) => (r * 180) / Math.PI;
const angle = (a, b) => deg(Math.acos(Math.max(-1, Math.min(1, Q.vDot(a, b)))));
const near = (a, b, tol, msg) => assert.ok(Q.qAngleDeg(a, b) < tol, `${msg}: ${Q.qAngleDeg(a, b)} deg`);
const fromAxisAngle = (axis, degs) => {
  const a = Q.vNorm(axis);
  const h = (degs * Math.PI) / 360;
  return [a[0] * Math.sin(h), a[1] * Math.sin(h), a[2] * Math.sin(h), Math.cos(h)];
};
const NOSOLVE = new Set();

// ---- quat.js
test('quat: product, inverse, rotate and angle', () => {
  const q90z = fromAxisAngle([0, 0, 1], 90);
  const v = Q.qRotate(q90z, [1, 0, 0]);
  assert.ok(Q.vLen(Q.vSub(v, [0, 1, 0])) < 1e-9);
  near(Q.qMul(q90z, Q.qInv(q90z)), [0, 0, 0, 1], 1e-3, 'q * inverse');
  const twice = Q.qMul(q90z, q90z);
  assert.ok(Q.vLen(Q.vSub(Q.qRotate(twice, [1, 0, 0]), [-1, 0, 0])) < 1e-9);
  assert.ok(Math.abs(Q.qAngleDeg(q90z, [0, 0, 0, 1]) - 90) < 1e-6);
  assert.ok(Q.qAngleDeg(q90z, q90z.map((c) => -c)) < 1e-6, 'q and -q are the same rotation');
});

test('quat: slerp endpoints, midpoint and the shortest path', () => {
  const a = [0, 0, 0, 1];
  const b = fromAxisAngle([0, 1, 0], 80);
  near(Q.qSlerp(a, b, 0), a, 1e-3, 't=0');
  near(Q.qSlerp(a, b, 1), b, 1e-3, 't=1');
  assert.ok(Math.abs(Q.qAngleDeg(a, Q.qSlerp(a, b, 0.5)) - 40) < 1e-6);
  assert.ok(Math.abs(Q.qAngleDeg(a, Q.qSlerp(a, b.map((c) => -c), 0.5)) - 40) < 1e-6);
  assert.ok(Math.abs(Q.qAngleDeg(a, Q.qSlerp(a, fromAxisAngle([0, 1, 0], 0.5), 0.5)) - 0.25) < 1e-6);
});

test('quat: vNorm of zero is null and normalization of a zero quaternion is identity', () => {
  assert.equal(Q.vNorm([0, 0, 0]), null);
  assert.equal(Q.vNorm([NaN, 1, 0]), null);
  assert.deepEqual(Q.qNorm([0, 0, 0, 0]), [0, 0, 0, 1]);
});

test('quat: basisFromPrimaryRef puts the primary on its axis for every axis pair', () => {
  const AX = { x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] };
  for (const pa of 'xyz') {
    for (const ra of 'xyz') {
      if (pa === ra) continue;
      const p = Q.vNorm([0.3, -0.8, 0.5]);
      const ref = [0.9, 0.2, -0.4];
      const q = Q.basisFromPrimaryRef(p, ref, pa, ra);
      assert.ok(Q.vLen(Q.vSub(Q.qRotate(q, AX[pa]), p)) < 1e-9, `primary ${pa}`);
      const r = Q.qRotate(q, AX[ra]);
      assert.ok(Math.abs(Q.vDot(r, p)) < 1e-9, `ref ${ra} is orthogonal`);
      assert.ok(Q.vDot(r, ref) > 0, `ref ${ra} keeps the reference side`);
      const handed = Q.vDot(Q.vCross(Q.qRotate(q, AX.x), Q.qRotate(q, AX.y)), Q.qRotate(q, AX.z));
      assert.ok(handed > 0.999, 'right-handed');
    }
  }
});

test('quat: basisFromPrimaryRef gives null for degenerate input and throws for bad axes', () => {
  assert.equal(Q.basisFromPrimaryRef([0, 0, 0], [1, 0, 0], 'y', 'x'), null);
  assert.equal(Q.basisFromPrimaryRef([0, 1, 0], [0, 2, 0], 'y', 'x'), null);
  assert.equal(Q.basisFromPrimaryRef([0, 1, 0], null, 'y', 'x'), null);
  assert.throws(() => Q.basisFromPrimaryRef([0, 1, 0], [1, 0, 0], 'y', 'y'), /bad axes/);
  assert.throws(() => Q.basisFromPrimaryRef([0, 1, 0], [1, 0, 0], 'w', 'x'), /bad axes/);
});

test('quat: qFromBasis covers all four trace branches', () => {
  const qs = [[0, 0, 0, 1], fromAxisAngle([1, 0, 0], 170), fromAxisAngle([0, 1, 0], 170), fromAxisAngle([0, 0, 1], 170)];
  for (const q of qs) {
    const x = Q.qRotate(q, [1, 0, 0]);
    const y = Q.qRotate(q, [0, 1, 0]);
    const z = Q.qRotate(q, [0, 0, 1]);
    near(Q.qFromBasis(x, y, z), q, 1e-4, 'round trip');
  }
});

// ---- helpers for the retarget tests
const infoOf = (name) => restFromModel(restOf(name));
const poseOf = (info) => info.pose17.map((v) => v.slice());
const idx = Object.fromEntries(SIMON_JOINTS.map((n, i) => [n, i]));
const pivotOf = (pose) => Q.vScale(Q.vAdd(pose[idx.left_hip], pose[idx.right_hip]), 0.5);
const rotateAbout = (pose, q, pivot) => pose.map((p) => (p ? Q.vAdd(Q.qRotate(q, Q.vSub(p, pivot)), pivot) : p));
const UPPER = ['nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear', 'left_shoulder', 'right_shoulder',
  'left_elbow', 'right_elbow', 'left_wrist', 'right_wrist'];
const rotateUpper = (pose, q) => {
  const pelvis = pivotOf(pose);
  const out = pose.map((v) => v.slice());
  for (const n of UPPER) out[idx[n]] = Q.vAdd(Q.qRotate(q, Q.vSub(pose[idx[n]], pelvis)), pelvis);
  return out;
};
const PARENT_JOINT = { left_elbow: 'left_shoulder', right_elbow: 'right_shoulder', left_knee: 'left_hip', right_knee: 'right_hip' };
const bendJoint = (pose, joint, child, axisRef, degs) => {
  // rotate the child about the joint, about an axis orthogonal to the parent segment
  const p = pose.map((v) => v.slice());
  const up = Q.vNorm(Q.vSub(p[idx[joint]], p[idx[PARENT_JOINT[joint]]]));
  const q = fromAxisAngle(Q.vCross(up, axisRef), degs);
  p[idx[child]] = Q.vAdd(p[idx[joint]], Q.qRotate(q, Q.vSub(p[idx[child]], p[idx[joint]])));
  return p;
};
const LIMB_DEFS = [
  { key: 'leftArm', pts: ['left_shoulder', 'left_elbow', 'left_wrist'], bones: ['leftUpperArm', 'leftLowerArm'], flex: ['left_elbow', 'left_wrist', [0, 0, 1]] },
  { key: 'rightArm', pts: ['right_shoulder', 'right_elbow', 'right_wrist'], bones: ['rightUpperArm', 'rightLowerArm'], flex: ['right_elbow', 'right_wrist', [0, 0, 1]] },
  { key: 'leftLeg', pts: ['left_hip', 'left_knee', 'left_ankle'], bones: ['leftUpperLeg', 'leftLowerLeg'], flex: ['left_knee', 'left_ankle', [0, 0, -1]] },
  { key: 'rightLeg', pts: ['right_hip', 'right_knee', 'right_ankle'], bones: ['rightUpperLeg', 'rightLowerLeg'], flex: ['right_knee', 'right_ankle', [0, 0, -1]] },
];
const dirOf = (pose, a, b) => Q.vNorm(Q.vSub(pose[idx[b]], pose[idx[a]]));
const deltaOf = (info, world, bone) => Q.qMul(world[bone], Q.qInv(info.world[bone]));
const restNormals = (info) => {
  const f = sourceFrame(info.pose17);
  return Object.fromEntries(Object.entries(f.limbs).map(([k, v]) => [k, v.normal]));
};

// ---- AC-RT1
for (const name of RESTS) {
  test(`AC-RT1 rest identity: ${name}`, () => {
    const info = infoOf(name);
    const world = createSolver(info).solve(info.pose17, NOSOLVE);
    assert.deepEqual(Object.keys(world).sort(), [...info.present].sort());
    for (const b of info.present) near(world[b], info.world[b], 0.5, `${name} ${b}`);
  });
}

test('AC-RT1 restFromModel fills tails, lists required bones and builds a 17 joint pose', () => {
  const info = infoOf('rest-ual2f.json');
  assert.equal(info.pose17.length, 17);
  assert.deepEqual(info.bones.hips.tail, info.bones.spine.head);
  assert.deepEqual(info.bones.leftUpperArm.tail, info.bones.leftLowerArm.head);
  assert.equal(info.bones.leftHand.tail, null);
  assert.equal(CANON.length, 22);
  assert.equal(REQUIRED.length, 15);
  assert.equal(SIMON_LEG_M, 0.8347);
  const p = info.pose17;
  assert.ok(p[idx.left_hip][0] > 0 && p[idx.right_hip][0] < 0, 'subject left is +x');
  assert.ok(p[idx.nose][1] > p[idx.left_shoulder][1], 'the head is above the shoulders');
  assert.ok(p[idx.nose][2] > p[idx.left_ear][2], 'the nose is in front of the ears');
});

// ---- Errors
test('restFromModel throws with a named reason', () => {
  const rest = structuredClone(restOf('rest-tpose.json'));
  delete rest.leftLowerLeg;
  assert.throws(() => restFromModel(rest), /missing required bone leftLowerLeg/);
  const bad = structuredClone(restOf('rest-tpose.json'));
  bad.head.world = [0, 0, NaN, 1];
  assert.throws(() => restFromModel(bad), /bad rest for head/);
  const bad2 = structuredClone(restOf('rest-tpose.json'));
  bad2.hips.head = [1, 2];
  assert.throws(() => restFromModel(bad2), /bad rest for hips/);
  assert.throws(() => restFromModel(null), /rest must be an object/);
});

// ---- AC-RT2
const ROTATIONS = [
  ['none', [0, 0, 0, 1]],
  ['yaw 75', fromAxisAngle([0, 1, 0], 75)],
  ['yaw 180', fromAxisAngle([0, 1, 0], 180)],
  ['pitch 40', fromAxisAngle([1, 0, 0], 40)],
  ['roll -50', fromAxisAngle([0, 0, 1], -50)],
  ['mixed', Q.qMul(fromAxisAngle([0, 1, 0], -120), Q.qMul(fromAxisAngle([1, 0, 0], 25), fromAxisAngle([0, 0, 1], 35)))],
];

for (const name of RESTS) {
  test(`AC-RT2 rigid rotations move every bone with the pose: ${name}`, () => {
    const info = infoOf(name);
    for (const [label, q] of ROTATIONS) {
      const pose = rotateAbout(poseOf(info), q, pivotOf(info.pose17));
      const world = createSolver(info).solve(pose, NOSOLVE);
      for (const b of info.present) near(world[b], Q.qMul(q, info.world[b]), 0.5, `${name} ${label} ${b}`);
    }
  });

  test(`AC-RT2 elbows and knees bent 0 to 150 degrees under rotation: ${name}`, () => {
    const info = infoOf(name);
    const rn = restNormals(info);
    const restSeg = createSolver(info).restSegments;
    for (const [label, q] of ROTATIONS) {
      for (let bend = 0; bend <= 150; bend += 15) {
        let pose = poseOf(info);
        for (const L of LIMB_DEFS) pose = bendJoint(pose, L.flex[0], L.flex[1], L.flex[2], bend);
        pose = rotateAbout(pose, q, pivotOf(pose));
        const world = createSolver(info).solve(pose, NOSOLVE);
        for (const L of LIMB_DEFS) {
          const dirs = [dirOf(pose, L.pts[0], L.pts[1]), dirOf(pose, L.pts[1], L.pts[2])];
          L.bones.forEach((b, i) => {
            const e = angle(Q.qRotate(deltaOf(info, world, b), restSeg[b]), dirs[i]);
            assert.ok(e < 0.5, `${name} ${label} bend ${bend} ${b}: ${e}`);
          });
          if (sourceFrame(pose).limbs[L.key].bendDeg >= 15) {
            const want = Q.vNorm(Q.vCross(dirs[0], dirs[1]));
            for (const b of L.bones) {
              const e = angle(Q.qRotate(deltaOf(info, world, b), rn[L.key]), want);
              assert.ok(e < 1, `${name} ${label} bend ${bend} ${b} normal: ${e}`);
            }
          }
        }
        const neck = Q.vScale(Q.vAdd(pose[idx.left_shoulder], pose[idx.right_shoulder]), 0.5);
        const up = Q.vNorm(Q.vSub(neck, pivotOf(pose)));
        for (const b of ['spine', 'hips']) {
          assert.ok(angle(Q.qRotate(deltaOf(info, world, b), restSeg[b]), up) < 0.5, `${name} ${label} ${b} direction`);
        }
        const headUp = Q.qRotate(q, restSeg.head);
        assert.ok(angle(Q.qRotate(deltaOf(info, world, 'head'), restSeg.head), headUp) < 0.5, `${name} ${label} head`);
      }
    }
  });
}

test('AC-RT2 a lean with the legs fixed turns the chest chain and keeps the legs where they are', () => {
  const info = infoOf('rest-ual2f.json');
  const lean = fromAxisAngle([1, 0, 0], 35);
  const world = createSolver(info).solve(rotateUpper(poseOf(info), lean), NOSOLVE);
  for (const b of ['leftUpperLeg', 'rightLowerLeg', 'leftFoot']) near(world[b], info.world[b], 0.5, b);
  near(world.chest, Q.qMul(lean, info.world.chest), 0.5, 'chest leans');
  assert.ok(Q.qAngleDeg(world.head, info.world.head) > 20, 'the head leans too');
});

// ---- AC-RT3
function twistChange(prev, cur) {
  // the angle between the previous normal, carried to the new bone direction, and the new normal
  const axis = Q.vCross(prev.dir, cur.dir);
  const swing = Q.vLen(axis) < 1e-9 ? [0, 0, 0, 1] : fromAxisAngle(axis, angle(prev.dir, cur.dir));
  return angle(Q.qRotate(swing, prev.normal), cur.normal);
}
function trackTwist(info, poses, bone) {
  const solver = createSolver(info);
  const seg = solver.restSegments[bone];
  const rn = restNormals(info);
  const key = LIMB_DEFS.find((l) => l.bones.includes(bone)).key;
  return poses.map((pose) => {
    const d = deltaOf(info, solver.solve(pose, NOSOLVE), bone);
    return { dir: Q.qRotate(d, seg), normal: Q.qRotate(d, rn[key]) };
  });
}
const UP_DOWN = [...Array(19).keys()].map((i) => i * 5).concat([...Array(18).keys()].map((i) => 85 - i * 5), [0, 0, 5, 10, 15, 25, 40, 60, 90]);

for (const [label, angles] of [
  ['straight and re-bent in the same plane', UP_DOWN],
  ['through a slightly wrong-way bend near straight', [60, 40, 20, 8, 3, 0, -4, -8, -4, 0, 3, 8, 20, 40, 60]],
]) {
  test(`AC-RT3 straight limb stability: ${label}`, () => {
    const info = infoOf('rest-tpose.json');
    for (const bone of ['leftUpperArm', 'rightUpperArm', 'leftUpperLeg', 'leftLowerArm']) {
      const L = LIMB_DEFS.find((l) => l.bones.includes(bone));
      const poses = angles.map((a) => bendJoint(poseOf(info), L.flex[0], L.flex[1], L.flex[2], a));
      const t = trackTwist(info, poses, bone);
      for (let i = 1; i < t.length; i++) {
        const c = twistChange(t[i - 1], t[i]);
        assert.ok(c < 90, `${bone} frame ${i} (${angles[i]} deg): twist changed ${c}`);
      }
    }
  });
}

test('AC-RT3 a straight arm swinging in the front plane keeps a smooth twist', () => {
  const info = infoOf('rest-tpose.json');
  const poses = [];
  for (let a = 0; a <= 180; a += 5) {
    const q = fromAxisAngle([0, 0, 1], a);
    const p = poseOf(info);
    for (const n of ['left_elbow', 'left_wrist']) p[idx[n]] = Q.vAdd(Q.qRotate(q, Q.vSub(p[idx[n]], p[idx.left_shoulder])), p[idx.left_shoulder]);
    poses.push(p);
  }
  const t = trackTwist(info, poses, 'leftUpperArm');
  for (let i = 1; i < t.length; i++) assert.ok(twistChange(t[i - 1], t[i]) < 30, `frame ${i}`);
});

test('AC-RT3 a straight arm holds the twist of its last bend, and reset() forgets it', () => {
  const info = infoOf('rest-tpose.json');
  const solver = createSolver(info);
  // bend the elbow towards the back (axis flipped), then straighten
  const back = bendJoint(poseOf(info), 'left_elbow', 'left_wrist', [0, 0, -1], 90);
  const rn = restNormals(info).leftArm;
  const normalOf = (world) => Q.qRotate(deltaOf(info, world, 'leftUpperArm'), rn);
  const bentNormal = normalOf(solver.solve(back, NOSOLVE));
  const heldNormal = normalOf(solver.solve(poseOf(info), NOSOLVE));
  assert.ok(angle(bentNormal, heldNormal) < 1, 'the straightened arm keeps the bend plane');
  const freshNormal = normalOf(createSolver(info).solve(poseOf(info), NOSOLVE));
  assert.ok(angle(heldNormal, freshNormal) > 90, 'a new solver falls back to the fixed rest normal');
  solver.reset();
  assert.deepEqual(solver.lastSegments, {});
  near(solver.solve(poseOf(info), NOSOLVE).leftUpperArm, createSolver(info).solve(poseOf(info), NOSOLVE).leftUpperArm, 1e-3, 'after reset');
});

// ---- AC-RT4: the real take
test('AC-RT4 fixture replay: the follower track on the UAL2 mannequin', () => {
  const replay = load('replay-fixture.json');
  assert.equal(replay.follower.length, 96);
  assert.deepEqual(replay.joints, SIMON_JOINTS);
  const info = infoOf('rest-ual2f.json');
  const solver = createSolver(info, { jointNames: replay.joints });
  const rn = restNormals(info);
  const errs = [];
  let flips = 0;
  let checked = 0;
  let prevT = null;
  for (const pose of replay.follower) {
    const world = solver.solve(pose, NOSOLVE);
    const frame = sourceFrame(pose);
    const cur = {};
    for (const b of Object.values(world)) assert.ok(b.every(Number.isFinite), 'no NaN');
    for (const L of LIMB_DEFS) {
      L.bones.forEach((b, i) => {
        const d = deltaOf(info, world, b);
        const dir = Q.qRotate(d, solver.restSegments[b]);
        errs.push(angle(dir, dirOf(pose, L.pts[i], L.pts[i + 1])));
        cur[b] = { dir, normal: Q.qRotate(d, rn[L.key]), bend: frame.limbs[L.key].bendDeg };
      });
    }
    if (prevT) {
      for (const b of Object.keys(cur)) {
        if (cur[b].bend >= 20 && prevT[b].bend >= 20) {
          checked++;
          if (twistChange(prevT[b], cur[b]) > 90) flips++;
        }
      }
    }
    prevT = cur;
  }
  errs.sort((a, b) => a - b);
  const median = errs[errs.length >> 1];
  const max = errs[errs.length - 1];
  console.log(`# fixture replay: median limb direction error ${median.toFixed(4)} deg, max ${max.toFixed(4)} deg, twist pairs checked ${checked}, flips ${flips}`);
  assert.ok(median < 1 && max < 3, `${median} ${max}`);
  assert.ok(checked > 100, 'the take has bent frames to check');
  assert.equal(flips, 0);
});

test('AC-RT4 fixture replay: every rest gives unit quaternions and no NaN on every frame', () => {
  const replay = load('replay-fixture.json');
  for (const name of RESTS) {
    const info = infoOf(name);
    const solver = createSolver(info);
    for (const pose of replay.follower) {
      const world = solver.solve(pose, NOSOLVE);
      for (const b of info.present) {
        assert.ok(world[b].every(Number.isFinite) && Math.abs(Math.hypot(...world[b]) - 1) < 1e-6, `${name} ${b}`);
      }
    }
  }
});

// ---- AC-RT5
const withUpperChest = (rest) => ({ ...rest, upperChest: { head: [0, 1.3, 0], tail: null, world: [0, 0, 0, 1] } });

test('AC-RT5 missing optional bones solve and the spine weights renormalize', () => {
  const full = withUpperChest(restOf('rest-tpose.json'));
  const cases = [
    { drop: [], spine: ['spine', 'chest', 'upperChest'] },
    { drop: ['upperChest'], spine: ['spine', 'chest'] },
    { drop: ['chest', 'upperChest'], spine: ['spine'] },
    { drop: ['chest', 'upperChest', 'neck', 'leftToes', 'rightToes', 'leftShoulder', 'rightShoulder'], spine: ['spine'] },
  ];
  for (const c of cases) {
    const rest = structuredClone(full);
    for (const d of c.drop) delete rest[d];
    const info = restFromModel(rest);
    const world = createSolver(info).solve(rotateUpper(poseOf(info), fromAxisAngle([0, 1, 0], 60)), NOSOLVE);
    assert.deepEqual(Object.keys(world).sort(), [...info.present].sort());
    for (const b of Object.values(world)) assert.ok(b.every(Number.isFinite));
    c.spine.forEach((b, k) => {
      const want = (60 * (k + 1)) / c.spine.length;
      assert.ok(Math.abs(Q.qAngleDeg(world[b], info.world[b]) - want) < 0.5, `${b} turns ${want} with ${c.spine.length} spine bones`);
    });
    assert.ok(Q.qAngleDeg(world.hips, info.world.hips) < 0.5, 'hips stay');
    if (!c.drop.includes('neck')) assert.ok(Math.abs(Q.qAngleDeg(world.neck, info.world.neck) - 60) < 0.5, 'neck');
    assert.ok(Math.abs(Q.qAngleDeg(world.head, info.world.head) - 60) < 0.5, 'head');
  }
});

test('AC-RT5 the spineWeights option renormalizes over the bones present', () => {
  const rest = withUpperChest(restOf('rest-tpose.json'));
  delete rest.chest;
  const info = restFromModel(rest);
  const world = createSolver(info, { spineWeights: [0.25, 0.5, 1] }).solve(rotateUpper(poseOf(info), fromAxisAngle([0, 1, 0], 90)), NOSOLVE);
  assert.ok(Math.abs(Q.qAngleDeg(world.spine, info.world.spine) - 22.5) < 0.5);
  assert.ok(Math.abs(Q.qAngleDeg(world.upperChest, info.world.upperChest) - 90) < 0.5);
});

// ---- AC-RT6
test('AC-RT6 an all-null lower body solves, the legs keep their rest rotation, the arms still follow', () => {
  const info = infoOf('rest-ual2f.json');
  const pose = poseOf(info);
  for (const n of ['left_hip', 'right_hip', 'left_knee', 'right_knee', 'left_ankle', 'right_ankle']) pose[idx[n]] = null;
  pose[idx.left_wrist] = bendJoint(poseOf(info), 'left_elbow', 'left_wrist', [0, 0, 1], 90)[idx.left_wrist];
  const solver = createSolver(info);
  const world = solver.solve(pose, NOSOLVE);
  for (const [b, w] of Object.entries(world)) assert.ok(w.every(Number.isFinite), b);
  for (const b of ['leftUpperLeg', 'leftLowerLeg', 'leftFoot', 'rightUpperLeg', 'rightFoot', 'leftToes']) near(world[b], info.world[b], 0.5, b);
  const got = Q.qRotate(deltaOf(info, world, 'leftLowerArm'), solver.restSegments.leftLowerArm);
  assert.ok(angle(got, dirOf(pose, 'left_elbow', 'left_wrist')) < 0.5, 'the forearm still follows');
});

test('AC-RT6 rigid rotation holds for every combination of missing face joints', () => {
  const info = infoOf('rest-apose.json');
  const q = fromAxisAngle([0, 1, 0], 50);
  const face = ['nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear'];
  for (let mask = 0; mask < 32; mask++) {
    const pose = rotateAbout(poseOf(info), q, pivotOf(info.pose17));
    face.forEach((n, i) => { if (mask & (1 << i)) pose[idx[n]] = null; });
    const world = createSolver(info).solve(pose, NOSOLVE);
    for (const b of info.present) {
      assert.ok(world[b].every(Number.isFinite), `${mask} ${b}`);
      near(world[b], Q.qMul(q, info.world[b]), 0.5, `mask ${mask} ${b}`);
    }
  }
});

test('AC-RT6 the head uses the nose and shoulders without ears, and the chest without a face', () => {
  const info = infoOf('rest-ual2f.json');
  const base = poseOf(info);
  const neck = Q.vScale(Q.vAdd(base[idx.left_shoulder], base[idx.right_shoulder]), 0.5);
  const q = fromAxisAngle([1, 0, 0], 30);
  const nodded = base.map((v) => v.slice());
  for (const n of ['nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear']) nodded[idx[n]] = Q.vAdd(Q.qRotate(q, Q.vSub(base[idx[n]], neck)), neck);
  const full = createSolver(info).solve(nodded, NOSOLVE);
  assert.ok(Math.abs(Q.qAngleDeg(full.head, info.world.head) - 30) < 1, 'full face sees the nod');
  const noEars = nodded.map((v) => v.slice());
  for (const n of ['left_ear', 'right_ear', 'left_eye', 'right_eye']) noEars[idx[n]] = null;
  const nose = createSolver(info).solve(noEars, NOSOLVE);
  assert.ok(Math.abs(Q.qAngleDeg(nose.head, info.world.head) - 30) < 8, `nose only: ${Q.qAngleDeg(nose.head, info.world.head)}`);
  const noFace = nodded.map((v) => v.slice());
  for (const n of ['nose', 'left_ear', 'right_ear', 'left_eye', 'right_eye']) noFace[idx[n]] = null;
  const chest = createSolver(info).solve(noFace, NOSOLVE);
  near(chest.head, Q.qMul(Q.qMul(chest.chest, Q.qInv(info.world.chest)), info.world.head), 1e-3, 'head follows the chest change');
});

test('AC-RT6 bad entries count as absent: null, undefined, NaN, short arrays, a short pose', () => {
  const info = infoOf('rest-tpose.json');
  const pose = poseOf(info);
  pose[idx.left_knee] = [NaN, 0, 0];
  pose[idx.right_knee] = undefined;
  pose[idx.left_wrist] = [1, 2];
  pose[idx.nose] = [Infinity, 0, 0];
  for (const p of [pose, pose.slice(0, 5), null]) {
    const world = createSolver(info).solve(p, NOSOLVE);
    for (const w of Object.values(world)) assert.ok(w.every(Number.isFinite));
  }
  const none = createSolver(info).solve(null, NOSOLVE);
  for (const b of info.present) near(none[b], info.world[b], 0.5, `empty pose ${b}`);
});

test('AC-RT6 jointNames: another order gives the same result, unknown names are ignored, fewer names mean absent', () => {
  const info = infoOf('rest-ual2f.json');
  const pose = load('replay-fixture.json').follower[48];
  const ref = createSolver(info).solve(pose, NOSOLVE);
  const order = [...SIMON_JOINTS.keys()].reverse();
  const shuffled = createSolver(info, { jointNames: order.map((i) => SIMON_JOINTS[i]) }).solve(order.map((i) => pose[i]), NOSOLVE);
  for (const b of info.present) near(shuffled[b], ref[b], 1e-3, b);
  const extra = createSolver(info, { jointNames: [...SIMON_JOINTS, 'tail_tip'] }).solve([...pose, [9, 9, 9]], NOSOLVE);
  for (const b of info.present) near(extra[b], ref[b], 1e-3, b);
  const half = createSolver(info, { jointNames: SIMON_JOINTS.slice(0, 11) }).solve(pose.slice(0, 11), NOSOLVE);
  for (const w of Object.values(half)) assert.ok(w.every(Number.isFinite));
  for (const b of ['leftUpperLeg', 'rightFoot']) near(half[b], info.world[b], 1e-3, `${b} keeps rest`);
});

test('AC-RT6 a zero length segment does not throw', () => {
  const info = infoOf('rest-tpose.json');
  const pose = poseOf(info);
  pose[idx.left_elbow] = pose[idx.left_shoulder].slice();
  pose[idx.left_wrist] = pose[idx.left_shoulder].slice();
  const world = createSolver(info).solve(pose, NOSOLVE);
  for (const w of Object.values(world)) assert.ok(w.every(Number.isFinite));
});

// ---- sourceFrame
test('sourceFrame reports the segments, bends and bases of a pose', () => {
  const info = infoOf('rest-tpose.json');
  const f = sourceFrame(bendJoint(poseOf(info), 'left_knee', 'left_ankle', [0, 0, -1], 90));
  assert.ok(Math.abs(f.limbs.leftLeg.bendDeg - 90) < 1e-6);
  assert.ok(f.limbs.rightLeg.bendDeg < 1);
  assert.equal(f.limbs.leftLeg.dirs.length, 2);
  for (const k of ['pelvis', 'neck', 'hipsBasis', 'chestBasis', 'headBasis']) assert.ok(f[k], k);
  const empty = sourceFrame([]);
  assert.equal(empty.pelvis, null);
  assert.equal(empty.headBasis, null);
  assert.equal(empty.limbs.leftArm.bendDeg, null);
});

// ---- AC-RT7 and AC-NFR-RT1
test('AC-RT7 the modules import nothing but each other and carry no dash characters', () => {
  for (const f of ['quat.js', 'retarget.js', 'skin-math.js']) {
    const text = fs.readFileSync(path.join(HERE, '..', '..', 'web', 'skin', f), 'utf8');
    const code = text.replace(/\/\/.*$/gm, '');
    const imports = [...code.matchAll(/^import[^;]*from\s+'([^']+)'/gms)].map((m) => m[1]);
    for (const i of imports) assert.match(i, /^\.\/(quat|retarget)\.js$/, `${f} imports ${i}`);
    assert.ok(!/\bdocument\b|\bwindow\b|\bfetch\(|\brequire\(/.test(code), `${f} touches no DOM or network`);
    assert.ok(!text.includes(String.fromCharCode(0x2014)) && !text.includes(String.fromCharCode(0x2013)), `${f} has a dash character`);
    assert.ok(text.split('\n').length < 800);
  }
});

test('AC-NFR-RT1 a solve of 17 joints over 22 bones is fast', () => {
  const info = infoOf('rest-ual2f.json');
  const replay = load('replay-fixture.json');
  const solver = createSolver(info);
  for (let i = 0; i < 100; i++) solver.solve(replay.follower[i], NOSOLVE);
  const t0 = process.hrtime.bigint();
  const n = 3000;
  for (let i = 0; i < n; i++) solver.solve(replay.follower[i % replay.follower.length], NOSOLVE);
  const ms = Number(process.hrtime.bigint() - t0) / 1e6 / n;
  console.log(`# solve: ${ms.toFixed(4)} ms per frame`);
  assert.ok(ms < 2, `${ms} ms`);
});
