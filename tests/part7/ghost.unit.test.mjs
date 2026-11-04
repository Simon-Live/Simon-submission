// Follow the ghost (docs/specs/follow-ghost.md, TICKET-264): the clock, the frame index and the placement on the preview.
//   node --test tests/part7/ghost.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { usableGhost, ghostDuration, ghostClock, frameIndexAt, placeGhost, stepScale, scaleRange, SCALE, IMAGE_SCALE, FOOT_LINE } from "../../web/model/ghost.js";

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

// the trainer's own Part 2 picture (box "image", AC-5): a 640 x 480 trainer frame
const image = {
  format: "simon.skeleton2d.v1", box: "image", available: true, image_size: [640, 480], joints: ["nose", "left_wrist", "left_knee"],
  bones: [[0, 1], [1, 2]], frames: [{ t: 0, pts: [[0.5, 0.25], [0.75, 0.5], null] }],
};

test("AC-5 an image ghost is the trainer's frame fitted inside the preview, about its centre", () => {
  assert.equal(usableGhost(image), true);
  assert.equal(usableGhost({ ...image, image_size: [0, 480] }), false, "an image ghost needs a positive image_size");
  assert.equal(usableGhost({ ...image, image_size: undefined }), false);
  assert.deepEqual(scaleRange(image), IMAGE_SCALE);
  assert.deepEqual(scaleRange(doc), SCALE, "a body ghost keeps the first build's range");
  // 640 x 480 into a 1280 x 720 landscape preview: height-bound, fit 1.5, so 960 x 720 centred
  const wide = placeGhost(image, 0, 1280, 720, { mirrored: false });
  assert.deepEqual(wide.points[0], [640, 180]);
  assert.deepEqual(wide.points[1], [640 + 0.25 * 960, 360]);
  assert.equal(wide.points[2], null, "an unseen joint stays unseen");
  assert.deepEqual(wide.bones, [[0, 1]], "no bone to the unseen knee");
  // into a 412 x 732 portrait preview: width-bound, fit 412 / 640, a band across the middle
  const tall = placeGhost(image, 0, 412, 732, { mirrored: false });
  const fh = 480 * (412 / 640);
  assert.ok(Math.abs(tall.points[0][1] - (366 - 0.25 * fh)) < 1e-9);
  assert.ok(Math.abs(tall.points[1][0] - (206 + 0.25 * 412)) < 1e-9);
  // the default scale is the trainer's own framing (1); scale 0.5 halves the distances from the centre
  const half = placeGhost(image, 0, 1280, 720, { mirrored: false, scale: 0.5 });
  assert.deepEqual(half.points[1], [640 + 0.25 * 480, 360]);
  // mirrored by default, like the reference: the wrist on the image's right is drawn on the left
  assert.deepEqual(placeGhost(image, 0, 1280, 720).points[1], [640 - 0.25 * 960, 360]);
});

test("AC-5 the image ghost's size steps between 0.5 and 2", () => {
  assert.equal(stepScale(IMAGE_SCALE.start, 1, IMAGE_SCALE), 1.1);
  assert.equal(stepScale(IMAGE_SCALE.max, 1, IMAGE_SCALE), 2);
  assert.equal(stepScale(IMAGE_SCALE.min, -1, IMAGE_SCALE), 0.5);
  assert.equal(stepScale(SCALE.max, 1), SCALE.max, "the body range is the default");
});
