// TICKET-376: Part 2's unseen mark reaches the 3D model (replay.follower_unseen) and the 2D overlay draws no bone to a null joint.
import test from "node:test";
import assert from "node:assert/strict";
import { normalizeReplay, hidesForPicked, dimsForPicked } from "../../web/compare.js";
import { skeletonAt } from "../../web/model/skeleton-frame.js";

const joints = ["nose", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"];
const bones = [[1, 2], [1, 3], [3, 5], [2, 4], [4, 6], [0, 1]];
const pose = joints.map((_, i) => [i * 0.1, i * 0.1, 0]);
const base = { fps: 10, joints, bones, expected: [pose], follower: [pose, pose, pose], exp_to_fol: [0] };

test("normalizeReplay marks the follower's unseen joints per frame from follower_unseen", () => {
  const m = normalizeReplay({ ...base, follower_unseen: [[5, 6], [3, 5, 6], [5, 6]] });
  assert.deepEqual(m.followerUnseen, [[5, 6], [3, 5, 6], [5, 6]]);
  assert.deepEqual(m.expectedUnseen, [[]]);
});

test("a replay without follower_unseen, or with a wrong length or bad indices, marks nothing extra", () => {
  assert.deepEqual(normalizeReplay(base).followerUnseen, [[], [], []]);
  assert.deepEqual(normalizeReplay({ ...base, follower_unseen: [[5]] }).followerUnseen, [[], [], []]);
  assert.deepEqual(normalizeReplay({ ...base, follower_unseen: [[99, -1, "x"], null, [4]] }).followerUnseen, [[], [], [4]]);
});

test("the 2D overlay keeps hips and draws a bone only when both ends are seen", () => {
  const doc = { joints, bones, frames: [
    { t: 0, pts: [[.5, .1], [.4, .5], [.6, .5], [.4, .7], [.6, .7], null, null] },
    { t: 0.1, pts: [[.5, .1], [.4, .5], [.6, .5], null, [.6, .7], null, null] }] };
  const a = skeletonAt(doc, 0, 100, 100), b = skeletonAt(doc, 0.1, 100, 100);
  assert.deepEqual(a.bones.map(([x, y]) => `${x}-${y}`), ["1-2", "1-3", "2-4", "0-1"]);
  assert.deepEqual(b.bones.map(([x, y]) => `${x}-${y}`), ["1-2", "2-4", "0-1"]);
  assert.equal(a.points[5], null);
  assert.ok(a.points[1] && a.points[2]);
});

test("only Part 2's marks are hidden; a held-in joint and the trainer's marks stay dimmed", () => {
  const withNull = { ...base, follower: base.follower.map((f) => f.slice()) };
  withNull.follower[1][4] = null; // a joint missing from a frame: held in from the last one, dimmed, still drawn
  const m = normalizeReplay({ ...withNull, follower_unseen: [[5], [5], [5]] });
  assert.deepEqual(m.followerHide, [[5], [5], [5]]);
  assert.deepEqual(m.followerUnseen[1], [4, 5]);
  assert.deepEqual(hidesForPicked(m, { follower: 1, expected: 0 }), [[], [5]]);
  assert.deepEqual(dimsForPicked(m, { follower: 1, expected: 0 }), [[], [4, 5]]);
  assert.deepEqual(normalizeReplay(base).followerHide, [[], [], []]);
});
