// Unit tests for the score timeline's pure parts (Part 5 ADR-0013). Run: node --test tests/part7/
// analysis-timeline.json is Part 5 05312b7 on the real lateral raise: trainer Pexels 5319084, follower 40297504.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { timelineOf, windowLabel, scoreSentence } from "../../web/timeline.js";

const load = (f) => JSON.parse(fs.readFileSync(new URL(`../../fixtures/input/${f}`, import.meta.url)));
const withTimeline = load("analysis-timeline.json");
const old = load("analysis-1.2.0.json");

test("an analysis without a timeline (older Part 5 pin) shows none", () => {
  assert.deepEqual(timelineOf(old), []);
  assert.deepEqual(timelineOf(null), []);
});

test("the timeline is one window per rep and the score is their mean", () => {
  const tl = timelineOf(withTimeline);
  const sc = withTimeline.score;
  assert.equal(sc.basis, "reps");
  assert.equal(tl.length, 8);
  const compared = tl.filter((w) => w.compared !== false);
  const mean = compared.reduce((a, w) => a + w.value, 0) / compared.length;
  assert.ok(Math.abs(sc.value - mean) <= 1);
});

test("each window's misses and similarity add up to its value", () => {
  for (const w of timelineOf(withTimeline).filter((x) => x.compared !== false)) {
    const lost = w.misses.reduce((a, m) => a + m.points, 0) + w.components.similarity;
    assert.ok(Math.abs(100 - lost - w.value) <= 1, JSON.stringify(w));
    for (const m of w.misses) assert.ok(m.text && m.points > 0 && m.at_s >= w.t_s[0] - 1);
  }
});

test("labels and the sentence explain the score", () => {
  const w = { t_s: [4.94, 9.87] };
  assert.equal(windowLabel(w, 2, "reps"), "Rep 3");
  assert.equal(windowLabel(w, 0, "windows"), "4.9 s to 9.9 s");
  assert.match(scoreSentence(withTimeline.score, timelineOf(withTimeline)), /average of 8 reps/);
  assert.match(scoreSentence({ basis: "windows" }, [{ t_s: [0, 3] }]), /100 minus/);
});
