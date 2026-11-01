// The trainer's unseen joints (web/model/trainer-visibility.js, compare.js normalizeReplay, result-summary.js posesAt; TICKET-116).
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { trainerUnseenByFrame, validVisibility, unionIndices } from "../../web/model/trainer-visibility.js";
import { normalizeReplay, bodyReport } from "../../web/compare.js";
import { posesAt } from "../../web/model/result-summary.js";

const load = (f) => JSON.parse(fs.readFileSync(new URL(`../../fixtures/input/${f}`, import.meta.url)));
const replay = load("replay.json");
const seated = load("trainer-visibility-seated.json"); // part7/trainer_visibility.py over expected_skeleton_seated.json
const standing = load("trainer-visibility-standing.json");
const LEGS = ["left_knee", "right_knee", "left_ankle", "right_ankle"].map((n) => replay.joints.indexOf(n)).sort((a, b) => a - b);

test("a real expected_skeleton sample: the seated trainer's knees and ankles are unseen in every frame", () => {
  assert.ok(validVisibility(seated) && validVisibility(standing));
  const by = trainerUnseenByFrame(seated, replay.joints, replay.expected_t);
  assert.equal(by.length, replay.expected.length);
  assert.ok(by.every((u) => JSON.stringify([...u].sort((a, b) => a - b)) === JSON.stringify(LEGS)));
});

test("a standing trainer with full visibility marks nothing", () => {
  assert.ok(trainerUnseenByFrame(standing, replay.joints, replay.expected_t).every((u) => u.length === 0));
  const m = normalizeReplay(replay, standing);
  assert.ok(m.expectedUnseen.every((u) => u.length === 0));
  assert.equal(bodyReport(m), null);
});

test("frames take the nearest skeleton time; joints map by name; bad documents mark nothing", () => {
  const doc = { joints: ["a", "b", "c"], t: [0, 1], unseen: [[0], [2, 1]] };
  assert.deepEqual(trainerUnseenByFrame(doc, ["c", "a"], [0, 0.4, 0.6, 5]), [[1], [1], [0], [0]]);
  for (const bad of [null, {}, { joints: ["a"], t: [0], unseen: [[3]] }, { joints: ["a"], t: [0, 1], unseen: [[]] }, { joints: [], t: [], unseen: [] }]) {
    assert.deepEqual(trainerUnseenByFrame(bad, ["a"], [0, 1]), [[], []]);
  }
  assert.deepEqual(unionIndices([3, 1], [1, 2]), [1, 2, 3]);
});

test("normalizeReplay dims the trainer's unseen joints and leaves the follower alone", () => {
  const plain = normalizeReplay(replay);
  assert.ok(plain.expectedUnseen.every((u) => u.length === 0));
  const m = normalizeReplay(replay, seated);
  assert.ok(m.expectedUnseen.every((u) => JSON.stringify(u) === JSON.stringify(LEGS)));
  assert.deepEqual(m.followerUnseen, plain.followerUnseen);
  assert.deepEqual(m.expected, plain.expected, "positions are unchanged: the joints are dimmed, not moved or dropped");
  assert.match(bodyReport(m), /trainer: dims left_knee,right_knee,left_ankle,right_ankle/);
});

test("independent of the follower: a follower that lacks a joint the trainer was seen with does not dim the trainer's", () => {
  const r = structuredClone(replay);
  const wrist = r.joints.indexOf("left_wrist");
  r.follower.forEach((f) => { f[wrist] = null; });
  const m = normalizeReplay(r, standing);
  assert.ok(m.expectedUnseen.every((u) => u.length === 0), "the trainer's wrist was seen");
  assert.ok(m.followerNever.includes(wrist));
  assert.ok(m.expected.every((f) => f[wrist]), "and is still drawn");
});

test("posesAt hands the summary figures the trainer's dimmed joints only", () => {
  const p = posesAt(normalizeReplay(replay, seated), 1.0);
  assert.deepEqual([...p.referenceDim].sort((a, b) => a - b), LEGS);
  assert.ok(p.reference.every(Boolean) && p.you.every(Boolean), "every joint is still placed");
  assert.deepEqual(posesAt(normalizeReplay(replay, standing), 1.0).referenceDim, []);
  assert.deepEqual(posesAt(normalizeReplay(replay), 1.0).referenceDim, []);
});
