// Unit tests for "Close calls" (TICKET-100): Part 5 1.8.0 diagnostics.near_misses picked, ordered and worded. Run: node --test tests/part7/
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { nearMissesOf, closeCalls, sentenceOf, secondsOfFrame, WORDS, MAX_CLOSE_CALLS } from "../../web/near-misses.js";

const load = (f) => JSON.parse(fs.readFileSync(new URL(`../../fixtures/input/${f}`, import.meta.url)));
const nm = load("analysis-near-misses.json");
const replay = load("replay.json");
const DASH = /[\u2013\u2014]| - /;

test("absent, empty and malformed near_misses show nothing", () => {
  assert.equal(nearMissesOf(load("analysis-1.2.0.json")), null);
  assert.equal(nearMissesOf(null), null);
  assert.equal(nearMissesOf({ diagnostics: { near_misses: { total: 0, omitted: 0, items: [] } } }), null);
  assert.equal(nearMissesOf({ diagnostics: { near_misses: { items: "x" } } }), null);
  assert.deepEqual(closeCalls(load("analysis-1.2.0.json"), replay), []);
  assert.deepEqual(closeCalls({ diagnostics: { near_misses: { total: 0, omitted: 0, items: [] } } }, replay), []);
});

test("at most three, persistence ones first, closest first (frames over against frames needed)", () => {
  const calls = closeCalls(nm, replay);
  assert.equal(calls.length, MAX_CLOSE_CALLS);
  assert.deepEqual(calls.map((c) => c.item.measure), ["head_forward", "trunk_lean_forward", "knee_flexion"]);
});

test("explained_by and fitness items are left out; reps items follow the persistence ones", () => {
  const base = { side: "left", direction: "more", measure: "elbow_flexion", follower_frames: [3, 9] };
  const a = { diagnostics: { near_misses: { items: [
    { ...base, reason: "explained_by", frames_over: 99, needed_frames: 100 },
    { ...base, reason: "fitness", found_in_reps: 4, needed_reps: 4 },
    { ...base, reason: "reps", found_in_reps: 2, needed_reps: 3 },
    { ...base, reason: "persistence", frames_over: 1, needed_frames: 100 },
  ] } } };
  const calls = closeCalls(a, replay);
  assert.deepEqual(calls.map((c) => c.item.reason), ["persistence", "reps"]);
  assert.match(calls[1].text, /only 2 of the 3 reps it needed/);
});

test("the wording names the trainer, the part and the frames, and says it did not count", () => {
  const trunk = closeCalls(nm, replay).find((c) => c.item.measure === "trunk_lean_forward");
  assert.equal(trunk.text, "Your back leaned forward less than the trainer's for part of the move, not long enough to count (held for 68 of the 114 frames needed).");
  const knee = closeCalls(nm, replay).find((c) => c.item.measure === "knee_flexion");
  assert.match(knee.text, /^Your left knee bent more than the trainer's/);
  assert.equal(sentenceOf({ measure: "foot_out", side: "right", direction: "less", reason: "persistence", counted_frames: 5, frames_over: 12, needed_frames: 9 }),
    "Your right foot stayed further in than the trainer's for part of the move, not long enough to count (held for 5 of the 9 frames needed).");
  assert.equal(sentenceOf({ measure: "unknown_measure", side: "left", direction: "more", reason: "persistence" }), null);
  for (const pair of Object.values(WORDS)) for (const s of pair) assert.ok(!DASH.test(s), s);
});

test("the moment is the first follower frame in seconds: the replay clock, else frame over fps", () => {
  const calls = closeCalls(nm, replay);
  const trunk = calls.find((c) => c.item.measure === "trunk_lean_forward");
  assert.equal(trunk.at_s, replay.follower_t[45]);
  assert.equal(secondsOfFrame(45, { fps: 30 }), 1.5);
  assert.equal(secondsOfFrame(45, { fps: 30, follower_t: [] }), 1.5);
  assert.equal(secondsOfFrame(45, null), null);
  assert.equal(secondsOfFrame(null, replay), null);
  assert.equal(secondsOfFrame(5, { fps: 0 }), null);
  assert.equal(closeCalls(nm, null)[0].at_s, null);
});

test("a real staging record reads counted_frames against needed_frames, never frames_over (TICKET-200)", () => {
  // Part 5 near_misses item from a staging analysis.json: 54 frames past the threshold, but only 21 in runs long enough, 30 needed.
  const real = load("near-miss-staging-persistence.json");
  assert.equal(sentenceOf(real), "Your left knee bent less than the trainer's for part of the move, not long enough to count (held for 21 of the 30 frames needed).");
  assert.ok(!/54/.test(sentenceOf(real)));
  // closeness ranks by counted frames: 21 of 30 beats 10 of 100 even though 90 frames were over
  const other = { ...real, measure: "elbow_flexion", frames_over: 90, counted_frames: 10, needed_frames: 100 };
  const calls = closeCalls({ diagnostics: { near_misses: { items: [other, real] } } }, null);
  assert.equal(calls[0].item.measure, "knee_flexion");
});

test("a persistence item with no counted_frames reads without the count (TICKET-202)", () => {
  const text = sentenceOf({ measure: "foot_out", side: "right", direction: "less", reason: "persistence", frames_over: 12, needed_frames: 9 });
  assert.match(text, /not long enough to count\.$/);
  assert.doesNotMatch(text, /undefined|NaN|held for/);
});
