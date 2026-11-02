// The trainer's video on the coach stage (web/model/coach-trainer.js): follower time to trainer time, pace and the
// step that keeps the video in step. Run: node --test tests/part7/
import test from "node:test";
import assert from "node:assert/strict";
import { DRIFT_S, RATE_MAX, alignmentOf, trainerTime, trainerRate, trainerStep } from "../../web/model/coach-trainer.js";

const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} is not ${b}`);

// 10 fps; the trainer's 21 frames (0..2 s) are matched to follower frames 30..70: the follower starts 3 s late and
// moves at half the trainer's speed
const replay = { fps: 10, exp_to_fol: Array.from({ length: 21 }, (_, e) => 30 + 2 * e),
  expected_t: Array.from({ length: 21 }, (_, e) => e / 10), follower: Array.from({ length: 91 }, () => []) };
const align = alignmentOf(replay);

test("no alignment from a replay without a matched frame list", () => {
  assert.equal(alignmentOf(null), null);
  assert.equal(alignmentOf({ fps: 30 }), null);
  assert.equal(alignmentOf({ fps: 0, exp_to_fol: [0] }), null);
  assert.equal(alignmentOf({ fps: 30, exp_to_fol: [0, NaN] }), null);
});

test("the trainer time is the trainer frame matched to the follower frame, as the 3D compare picks it", () => {
  near(trainerTime(3, align), 0);       // follower frame 30 -> trainer frame 0
  near(trainerTime(4, align), 0.5);     // frame 40 -> trainer frame 5
  near(trainerTime(4.1, align), 0.5);   // frame 41: the largest trainer frame not above it is still 5
  near(trainerTime(5, align), 1);
  near(trainerTime(1, align), 0, 1e-9); // before the trainer starts it holds its first frame
  near(trainerTime(8, align), 2);       // after the matched part it holds its last
});

test("expected_t missing: the trainer frame index over fps", () => {
  const a = alignmentOf({ fps: 10, exp_to_fol: [0, 5, 10] });
  near(trainerTime(1, a), 0.2);
});

test("the trainer time stays inside the trainer's video", () => {
  near(trainerTime(8, align, { trainer: 1.5 }), 1.45);
});

test("without a replay the time is scaled by the two lengths", () => {
  near(trainerTime(6, null, { trainer: 10, you: 20 }), 3);
  near(trainerTime(5, null, { trainer: 10 }), 5);           // the follower's length not known yet: same time
});

test("the pace is the local slope: half speed here, 0 while the trainer holds a frame", () => {
  near(trainerRate(4, align), 0.5);
  assert.equal(trainerRate(1, align), 0);
  assert.equal(trainerRate(8, align), 0);
  near(trainerRate(3, null, { trainer: 10, you: 20 }), 0.5);
  assert.equal(trainerRate(0.5, null, { trainer: 100, you: 1 }), RATE_MAX);
});

test("the step plays, slows and puts the trainer back only when it strays", () => {
  const playing = trainerStep(4, true, { t: 0.5, paused: true, rate: 1 }, align);
  assert.deepEqual(playing, { seek: null, play: true, rate: 0.5 });
  const strayed = trainerStep(4, true, { t: 0.5 + DRIFT_S + 0.1, paused: false, rate: 0.5 }, align);
  assert.equal(strayed.rate, null);
  near(strayed.seek, 0.5);
  const paused = trainerStep(5, false, { t: 0.5, paused: false, rate: 0.5 }, align);
  assert.equal(paused.play, false);
  near(paused.seek, 1);
  const holding = trainerStep(1, true, { t: 0, paused: false, rate: 1 }, align);
  assert.deepEqual(holding, { seek: null, play: false, rate: null });
});
