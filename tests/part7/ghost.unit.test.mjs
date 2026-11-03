// Follow the ghost (docs/specs/follow-ghost.md, TICKET-264): the clock, the frame index and the placement on the preview.
//   node --test tests/part7/ghost.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { usableGhost, ghostDuration, ghostClock, frameIndexAt, placeGhost, stepScale, SCALE, FOOT_LINE } from "../../web/model/ghost.js";

const doc = {
  format: "simon.skeleton2d.v1", box: "body", available: true, joints: ["nose", "left_ankle", "right_ankle"], bones: [[0, 1], [0, 2]],
  frames: [0, 1, 2, 3].map((i) => ({ t: i / 10, pts: [[0.5, 0], [0.7, 1], i === 3 ? null : [0.3, 1]] })),
};

test("a ghost is usable only when the route says so and the frames are valid", () => {
  assert.equal(usableGhost(doc), true);
  assert.equal(usableGhost({ ...doc, available: false }), false);
  assert.equal(usableGhost({ available: false, reason: "none" }), false);
  assert.equal(usableGhost(null), false);
  assert.equal(ghostDuration(doc), 0.3);
});

test("AC-1 the clock is the reference video's own when there is one; else the recording clock loops; before, 0", () => {
  assert.equal(ghostClock(2.25, 999, 0.3), 2.25);
  assert.ok(Math.abs(ghostClock(NaN, 450, 0.3) - 0.15) < 1e-9);
  assert.equal(ghostClock(NaN, NaN, 0.3), 0);
  assert.equal(ghostClock(NaN, 1000, 0), 1);
});

test("AC-1 the frame index is the nearest frame (the earlier on a tie)", () => {
  assert.equal(frameIndexAt(doc, 0), 0);
  assert.equal(frameIndexAt(doc, 0.149), 1);
  assert.equal(frameIndexAt(doc, 0.15), 1);
  assert.equal(frameIndexAt(doc, 0.26), 3);
  assert.equal(frameIndexAt(doc, 99), 3);
});

test("placement: feet on the foot line, the body box `scale` of the height, centred, mirrored by default", () => {
  const s = placeGhost(doc, 0, 400, 300);
  const box = SCALE.start * 300;
  assert.deepEqual(s.points[0], [200, FOOT_LINE * 300 - box]);
  assert.equal(s.points[1][1], FOOT_LINE * 300);
  assert.ok(s.points[1][0] < 200, "mirrored: the subject's left ankle (image right) is drawn on the left");
  const raw = placeGhost(doc, 0, 400, 300, { mirrored: false });
  assert.ok(raw.points[1][0] > 200, "not mirrored: the camera's own view");
  assert.equal(s.bones.length, 2);
  const missing = placeGhost(doc, 3, 400, 300);
  assert.equal(missing.points[2], null);
  assert.deepEqual(missing.bones, [[0, 1]], "a bone with an unseen end is not drawn");
  assert.equal(placeGhost(doc, 99, 400, 300).index, 3);
});

test("the size steps stay inside the allowed range", () => {
  assert.equal(stepScale(SCALE.start, 1), 0.9);
  assert.equal(stepScale(SCALE.max, 1), SCALE.max);
  assert.equal(stepScale(SCALE.min, -1), SCALE.min);
});
