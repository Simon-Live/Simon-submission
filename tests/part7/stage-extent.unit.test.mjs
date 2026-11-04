// docs/specs/model-skin.md AC16c: the take's extent the stage frames from its first frame. No three, no DOM:
// node --test tests/part7/stage-extent.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { hipCentre, frameStickBox, extremeFrames, projectBoxes } from "../../web/stage-extent.js";

const HL = 1, HR = 2; // joint 0 a hand, 1 and 2 the hips
const pose = (hand, hipY = 0) => [hand, [-0.1, hipY, 0], [0.1, hipY, 0]];

test("the hip centre is the middle of both hips, the origin without one", () => {
  assert.deepEqual(hipCentre(pose([0, 1, 0], 0.5), HL, HR), [0, 0.5, 0]);
  assert.deepEqual(hipCentre([[1, 1, 1], null, [0.1, 0, 0]], HL, HR), [0, 0, 0]);
  assert.deepEqual(hipCentre(null, HL, HR), [0, 0, 0]);
});

test("a frame's box is relative to its hips and grown by the pad; unseen joints are left out", () => {
  const b = frameStickBox([[0.5, 1.5, -0.2], [-0.1, 1, 0], [0.1, 1, 0], null], HL, HR, 0.03);
  assert.deepEqual(b.min.map((v) => +v.toFixed(3)), [-0.13, -0.03, -0.23]);
  assert.deepEqual(b.max.map((v) => +v.toFixed(3)), [0.53, 0.53, 0.03]);
});

test("a frame with no joint, or no frame, has no box", () => {
  assert.equal(frameStickBox(null, HL, HR), null);
  assert.equal(frameStickBox([null, null, null], HL, HR), null);
});

test("the extreme frames include each axis' furthest reach both ways, wherever it falls", () => {
  const frames = Array.from({ length: 200 }, () => pose([0, 0.3, 0]));
  frames[37] = pose([0, 0.9, 0]);   // up
  frames[71] = pose([0, -0.8, 0]);  // down
  frames[113] = pose([0.7, 0, 0]);  // out to the left
  frames[151] = pose([-0.7, 0, 0]); // out to the right
  frames[163] = pose([0, 0, 0.6]);  // forward
  frames[199] = pose([0, 0, -0.6]); // back
  const picked = extremeFrames(frames, HL, HR, 0);
  for (const i of [37, 71, 113, 151, 163, 199]) assert.ok(picked.includes(i), `frame ${i} picked`);
  assert.ok(picked.length <= 7);
});

test("the furthest reach on the floor counts as well as each axis", () => {
  const frames = Array.from({ length: 50 }, () => pose([0.5, 0, 0]));
  frames[20] = pose([0.45, 0, 0.45]); // not the furthest on x or z, the furthest from the hips on the floor
  assert.ok(extremeFrames(frames, HL, HR, 0).includes(20));
});

test("frames spread evenly over the take are added, sorted, without repeats or empty frames", () => {
  const frames = Array.from({ length: 100 }, (_, i) => (i === 50 ? null : pose([0, 0.3 + i / 1000, 0])));
  const picked = extremeFrames(frames, HL, HR, 10);
  assert.deepEqual(picked, [...new Set(picked)].sort((a, b) => a - b));
  assert.ok(!picked.includes(50));
  for (const i of [0, 10, 20, 30, 40, 60, 70, 80, 90]) assert.ok(picked.includes(i), `even frame ${i}`);
  assert.ok(picked.includes(99), "the tallest frame");
});

test("a take of one frame picks it; an empty take picks none", () => {
  assert.deepEqual(extremeFrames([pose([0, 1, 0])], HL, HR), [0]);
  assert.deepEqual(extremeFrames([], HL, HR), []);
  assert.deepEqual(extremeFrames([null, null], HL, HR), []);
});

test("the projected box spans every corner of every box at the slot", () => {
  const ortho = (x, y) => [x, y];
  const r = projectBoxes([{ min: [-0.1, -0.5, 0], max: [0.1, 0.5, 0] }, { min: [0, 0, -1], max: [0.6, 0.2, 1] }], [0.4, 0, 0], ortho);
  assert.deepEqual(r, { x0: 0.30000000000000004, x1: 1, y0: -0.5, y1: 0.5 });
});

test("the projected box grows a box given to it and goes through the projection", () => {
  const into = { x0: -2, x1: 0, y0: 0, y1: 0.1 };
  const persp = (x, y, z) => [x / (3 - z), y / (3 - z)];
  const r = projectBoxes([{ min: [0, 0, 1], max: [1, 1, 1] }], [0, 0, 0], persp, into);
  assert.equal(r, into);
  assert.deepEqual(r, { x0: -2, x1: 0.5, y0: 0, y1: 0.5 });
});

test("no boxes leave the box given unchanged", () => {
  assert.deepEqual(projectBoxes([], [0, 0, 0], (x, y) => [x, y]), { x0: Infinity, x1: -Infinity, y0: Infinity, y1: -Infinity });
});
