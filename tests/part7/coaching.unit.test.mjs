// Pure helpers of the coaching moments (coaching-moments.md): worst moment and moments to review. Run: node --test tests/part7/coaching.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  momentLabel, leadInSpan, worstMoment, momentsToReview, flaggedWindows,
  LEAD_IN_S, REVIEW_GAP, TOP_MISSES, MAX_MOMENTS,
} from "../../web/coaching.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = (f) => JSON.parse(fs.readFileSync(path.join(here, "../../fixtures/input", f)));
const insights = fixture("analysis-insights.json");

const win = (a, b, value, misses = [], extra = {}) => ({ t_s: [a, b], compared: true, value, grade: "B", components: { similarity: 0 }, misses, ...extra });
const miss = (at_s, points, cue_kind = "range") => ({ at_s, points, cue_kind, cue: `cue ${at_s}`, text: `text ${at_s}` });
const take = (value, timeline, extra = {}) => ({ score: { value, grade: "C", basis: "reps", timeline, ...extra }, faults: [] });

test("moment label and lead-in", () => {
  assert.equal(momentLabel(3.24), "At 3.2 s");
  assert.deepEqual(leadInSpan(5.8), { from: 5.8 - LEAD_IN_S, to: 5.8 });
  assert.equal(leadInSpan(0.4).from, 0);
});

test("worst moment is the lowest compared window of the real fixture", () => {
  const w = worstMoment(insights);
  assert.equal(w.kind, "window");
  assert.equal(w.value, 54);
  assert.deepEqual([w.from, w.to], [7.867, 9.1]);
  assert.equal(w.at, 7.9);
});

test("worst moment skips windows that did not match and ties keep the first", () => {
  const a = take(70, [win(0, 5, 20, [], { compared: false }), win(5, 10, 60, [miss(6, 9)]), win(10, 15, 60, [miss(11, 9)])]);
  const w = worstMoment(a);
  assert.deepEqual([w.index, w.from, w.to, w.at], [1, 5, 10, 6]);
});

test("a flawless take has no worst moment", () => {
  assert.equal(worstMoment(take(98, [win(0, 5, 98), win(5, 10, 97)])), null);
});

test("without a timeline the worst moment is the fault with the most points, from its lead-in", () => {
  const a = { score: { value: 70, grade: "C" }, faults: [{ at_s: 1, points: 2 }, { at_s: 4, points: 6 }, { at_s: 6 }] };
  const w = worstMoment(a);
  assert.equal(w.kind, "fault");
  assert.deepEqual([w.index, w.at, w.from], [1, 4, 3]);
  const noPoints = worstMoment({ score: { value: 70, grade: "C" }, faults: [{ at_s: 2 }, { at_s: 5 }] });
  assert.equal(noPoints.index, 0);
  assert.equal(worstMoment({ score: { value: 70, grade: "C" }, faults: [] }), null);
  assert.equal(worstMoment(null), null);
});

test("moments to review: windows 15 points under the take, plus the biggest misses outside them", () => {
  const ms = momentsToReview(insights);
  const take77 = insights.score.value;
  const flagged = insights.score.timeline.map((w, i) => [w, i]).filter(([w]) => w.value <= take77 - REVIEW_GAP).map(([, i]) => i);
  assert.deepEqual(flaggedWindows(ms), new Set(flagged));
  assert.ok(flagged.includes(6) && flagged.includes(5), "windows scoring 55 and 54 are flagged");
  assert.ok(!flagged.includes(4), "69 is only 8 under 77");
  const times = ms.map((m) => m.at);
  assert.deepEqual(times, [...times].sort((a, b) => a - b));
  assert.ok(ms.length <= MAX_MOMENTS);
  const misses = ms.filter((m) => m.kind === "miss");
  assert.ok(misses.length <= TOP_MISSES);
  for (const m of misses) {
    assert.ok(!ms.some((o) => o.kind === "window" && m.at >= o.from && m.at <= o.to), "a miss inside a flagged window is not repeated");
  }
});

test("moments to review: none for an even take, and none without a score", () => {
  const even = take(80, [win(0, 5, 82), win(5, 10, 78)]);
  assert.deepEqual(momentsToReview(even).filter((m) => m.kind === "window"), []);
  assert.deepEqual(momentsToReview({}), []);
  assert.deepEqual(momentsToReview({ score: { value: 80 } }), []);
});

test("the biggest misses are chosen by points and capped", () => {
  const a = take(90, [win(0, 5, 88, [miss(1, 3), miss(2, 9), miss(3, 7), miss(4, 8), miss(4.5, 1)])]);
  assert.deepEqual(momentsToReview(a).map((m) => m.at), [2, 3, 4]);
});
