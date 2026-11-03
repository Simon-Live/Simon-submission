// docs/specs/model-retarget.md: skin-math.js, AC-RT8 and the world to local helpers.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { qMul, qInv, qAngleDeg } from '../../web/skin/quat.js';
import { SIMON_JOINTS, SIMON_LEG_M } from '../../web/skin/retarget.js';
import {
  median, legLengthsFromPose, legLengthFromTrack, fitScaleFromTrack, localFromWorld, worldToLocalChain,
} from '../../web/skin/skin-math.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const replay = JSON.parse(fs.readFileSync(path.join(HERE, 'fixtures', 'skin', 'replay-fixture.json'), 'utf8'));
const I = SIMON_JOINTS.indexOf.bind(SIMON_JOINTS);

function legPose(thigh, shank, sides = ['left', 'right']) {
  const p = SIMON_JOINTS.map(() => null);
  for (const [s, x] of [['left', 0.1], ['right', -0.1]]) {
    if (!sides.includes(s)) continue;
    p[I(`${s}_hip`)] = [x, 0, 0];
    p[I(`${s}_knee`)] = [x, -thigh, 0];
    p[I(`${s}_ankle`)] = [x, -thigh - shank, 0];
  }
  return p;
}

test('median: odd, even, empty and non-finite values', () => {
  assert.equal(median([3, 1, 2]), 2);
  assert.equal(median([4, 1, 2, 3]), 2.5);
  assert.equal(median([]), null);
  assert.equal(median([NaN, 5, Infinity]), 5);
});

test('AC-RT8 leg lengths of one pose: one entry per leg seen', () => {
  assert.deepEqual(legLengthsFromPose(legPose(0.4, 0.5)).map((v) => +v.toFixed(6)), [0.9, 0.9]);
  assert.equal(legLengthsFromPose(legPose(0.4, 0.5, ['left'])).length, 1);
  assert.deepEqual(legLengthsFromPose(null), []);
  const p = legPose(0.4, 0.5);
  p[I('left_knee')] = [NaN, 0, 0];
  assert.equal(legLengthsFromPose(p).length, 1);
});

test('AC-RT8 the track leg length is the median, so one bad frame does not move it', () => {
  const poses = [legPose(0.4, 0.4), legPose(0.4, 0.4), legPose(0.4, 0.4), legPose(1.5, 1.5)];
  const r = legLengthFromTrack(poses);
  assert.equal(r.measured, true);
  assert.ok(Math.abs(r.legM - 0.8) < 1e-9);
});

test('AC-RT8 fit scale makes the character leg as long as the person leg, any profile', () => {
  const tall = fitScaleFromTrack([legPose(0.5, 0.5)], SIMON_JOINTS, 0.8);
  assert.ok(Math.abs(tall.scale - 1.25) < 1e-9);
  const short = fitScaleFromTrack([legPose(0.3, 0.3)], SIMON_JOINTS, 0.8);
  assert.ok(Math.abs(short.scale - 0.75) < 1e-9);
});

test('AC-RT8 with no leg ever seen the fallback leg length is used and flagged', () => {
  const r = fitScaleFromTrack([legPose(0.5, 0.5, [])], SIMON_JOINTS, 0.8347);
  assert.equal(r.measured, false);
  assert.equal(r.legM, SIMON_LEG_M);
  assert.equal(r.scale, 1);
  assert.equal(fitScaleFromTrack([], SIMON_JOINTS, 1).measured, false);
  assert.throws(() => fitScaleFromTrack([], SIMON_JOINTS, 0), /characterLegM must be positive/);
  assert.throws(() => fitScaleFromTrack([], SIMON_JOINTS, NaN), /characterLegM/);
});

test('AC-RT8 jointNames order is honoured', () => {
  const names = [...SIMON_JOINTS].reverse();
  const reversed = legPose(0.4, 0.5).reverse();
  assert.ok(Math.abs(legLengthFromTrack([reversed], names).legM - 0.9) < 1e-9);
});

test('AC-RT8 fixture replay: the measured leg length is near the default profile leg', () => {
  const r = legLengthFromTrack(replay.follower, replay.joints);
  console.log(`# fixture replay leg length ${r.legM.toFixed(4)} m`);
  assert.equal(r.measured, true);
  assert.ok(Math.abs(r.legM - SIMON_LEG_M) < 0.1, String(r.legM)); // the fixture person is a little taller than the default
});

test('localFromWorld and worldToLocalChain round trip a chain, and skip bones without a rotation', () => {
  const s = Math.SQRT1_2;
  const world = { a: [0, 0, s, s], b: [0, s, 0, s], c: [s, 0, 0, s] };
  const parentOf = { a: null, b: 'a', c: 'b' };
  const local = worldToLocalChain(['a', 'b', 'c'], parentOf, world);
  let acc = local.a;
  assert.ok(qAngleDeg(acc, world.a) < 1e-3);
  acc = qMul(acc, local.b);
  assert.ok(qAngleDeg(acc, world.b) < 1e-3);
  acc = qMul(acc, local.c);
  assert.ok(qAngleDeg(acc, world.c) < 1e-3);
  assert.deepEqual(localFromWorld(null, world.a).map((v) => +v.toFixed(6)), world.a.map((v) => +v.toFixed(6)));
  assert.ok(qAngleDeg(localFromWorld(world.a, world.b), qMul(qInv(world.a), world.b)) < 1e-3);
  assert.deepEqual(Object.keys(worldToLocalChain(['a', 'z', 'b'], parentOf, { a: world.a, b: world.b })), ['a', 'b']);
});
