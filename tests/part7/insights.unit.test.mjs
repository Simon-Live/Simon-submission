// Unit tests for "What to work on" and the cues (Part 5 schema 1.5.0, ADR-0014; TICKET-066). Run: node --test tests/part7/
// analysis-insights.json is the new Part 5 on the real lateral raise (trainer Pexels 5319084, follower 40297504);
// analysis-1.5.0.json is Part 5's golden example (two faults, no score); the older fixtures have no cues.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { insightsOf, insightChip } from "../../web/result.js";
import { jointsFor, tempoLine, tempoShare, timelineOf } from "../../web/timeline.js";

const load = (f) => JSON.parse(fs.readFileSync(new URL(`../../fixtures/input/${f}`, import.meta.url)));
const reps = load("analysis-insights.json");
const golden = load("analysis-1.5.0.json");
const DASH = /[\u2013\u2014]| - /;

test("older analyses have no insights, so nothing new shows", () => {
  assert.equal(insightsOf(load("analysis-1.2.0.json")), null);
  assert.equal(insightsOf(load("analysis-timeline.json")), null);
  assert.equal(insightsOf(null), null);
  for (const w of timelineOf(load("analysis-timeline.json"))) assert.equal(tempoLine(w), null);
});

test("insights come as Part 5 ranked them, at most 5, the tempo item last", () => {
  const items = insightsOf(reps);
  assert.equal(items.length, 5);
  assert.deepEqual(items.map((x) => x.cue), reps.insights.map((x) => x.cue));
  assert.equal(items.at(-1).kind, "tempo");
  const scored = items.filter((x) => x.kind !== "tempo");
  assert.deepEqual(scored.map((x) => x.points), [...scored.map((x) => x.points)].sort((a, b) => b - a));
  for (const x of items) assert.ok(x.cue.split(/\s+/).length <= 6 && !DASH.test(x.cue) && !DASH.test(x.why), x.cue);
});

test("an empty list is kept apart from no list, and items without a cue are dropped", () => {
  assert.deepEqual(insightsOf({ insights: [] }), []);
  assert.deepEqual(insightsOf({ insights: [{ why: "x" }, null, { cue: "Lean forward more", why: "y" }] }).map((x) => x.cue), ["Lean forward more"]);
});

test("the chip says what an insight cost, or Tempo, or nothing without points", () => {
  assert.deepEqual(insightChip({ kind: "range", points: 5.33 }), { text: "−5.3", label: "Costs 5.3 points of your score" });
  assert.deepEqual(insightChip({ kind: "tempo", points: null }), { text: "Tempo", label: "Tempo, not scored" });
  assert.equal(insightChip({ kind: "position", points: null }), null);
});

test("joints to highlight: the fault's own joints, else both sides or the centre joints", () => {
  const f = golden.faults[1];
  assert.deepEqual(jointsFor({ cue: f.cue, joint: "shoulder", side: "both" }, golden), f.joints);
  assert.deepEqual(jointsFor({ cue: "Move your hands out wider", joint: "elbow", side: "both" }, reps), ["left_elbow", "right_elbow"]);
  assert.deepEqual(jointsFor({ joint: "left_shoulder", side: "left" }, reps), ["left_shoulder"]);
  assert.deepEqual(jointsFor({ joint: "spine", side: "center" }, reps), ["left_shoulder", "right_shoulder", "left_hip", "right_hip"]);
  assert.deepEqual(jointsFor({ joint: null, side: null }, reps), []);
});

test("each rep of the fast follower has a tempo line; every miss carries its cue", () => {
  const windows = timelineOf(reps).filter((w) => w.compared !== false);
  assert.equal(windows.length, 8);
  for (const w of windows) {
    assert.match(tempoLine(w), /^Slow down to match the trainer: this took \d+% of the trainer's time\.$/);
    for (const m of w.misses) assert.ok(m.cue && m.text, JSON.stringify(m));
  }
  assert.equal(tempoLine({ tempo: { ratio: 1.02, cue: null } }), null);
  assert.equal(tempoShare(2.4), "2.4 times the trainer's time");
  assert.equal(tempoShare(0.37), "37% of the trainer's time");
});

test("the golden 1.5.0 example: each fault has a cue and an insight in fault order, without points", () => {
  assert.deepEqual(insightsOf(golden).map((x) => x.cue), golden.faults.map((f) => f.cue));
  assert.ok(insightsOf(golden).every((x) => x.points === null && insightChip(x) === null));
});
