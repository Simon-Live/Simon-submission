// TICKET-392: the words under the grade agree with the grade, at every grade (operator: an S said "Keep working on it.").
// The headline wording is chosen from the grade the ring shows (ring.grade), on the same scale as that grade, so a credit
// take on Part 5's S to F scale never falls through to the F line. The shared page draws no feedback words, only the ring's
// grade, so the same ring grade is what it shows (checked at the end).
//   node --test tests/part7/score-feedback.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { summaryOf } from "../../web/model/score-labels.js";
import { headlineFor } from "../../web/model/score-feedback.js";

const load = (f) => JSON.parse(fs.readFileSync(new URL(`../../fixtures/input/${f}`, import.meta.url)));
const base = load("analysis-credit.json");
const plain = load("analysis-timeline.json");
const SCALE = [[95, "S"], [85, "A"], [75, "B"], [65, "C"], [55, "D"], [40, "E"], [0, "F"]];
const withPercent = (percent, extra = {}) => ({ ...base, score: { ...base.score, credit: { ...base.score.credit, percent, levels: undefined,
  points: Math.round(percent * 100), max_points: 10000, grade: undefined, grades: SCALE, ...extra } } });
const DISCOURAGING = /keep working|go gently|keep practising|try again/i;
const ENCOURAGING = /strong|top|nailed|outstanding|steady and controlled/i;

// every grade, at its lower mark and at the highest percent still under the next mark
const CASES = [["S", 100], ["S", 95], ["A", 94.9], ["A", 85], ["B", 84.9], ["B", 75], ["C", 74.9], ["C", 65], ["D", 64.9], ["D", 55],
  ["E", 54.9], ["E", 40], ["F", 39.9], ["F", 0]];

for (const kind of ["exercise", "dance", "rehab"]) {
  for (const [grade, percent] of CASES) {
    test(`${kind}: ${percent}% is ${grade} and the headline fits it`, () => {
      const m = summaryOf(withPercent(percent), { kind });
      assert.equal(m.ring.grade, grade);
      assert.equal(m.headline, headlineFor(kind, grade, SCALE));
      if (grade === "S" || grade === "A") assert.ok(!DISCOURAGING.test(m.headline), `${grade} reads as discouragement: ${m.headline}`);
      if (grade === "S") assert.match(m.headline, ENCOURAGING);
      if (grade === "E" || grade === "F") assert.ok(!ENCOURAGING.test(m.headline), `${grade} reads as praise: ${m.headline}`);
    });
  }
}

test("the operator's take: S never reads 'Keep working on it.' (exercise, dance, rehab)", () => {
  for (const kind of ["exercise", "dance", "rehab"]) assert.doesNotMatch(summaryOf(withPercent(97), { kind }).headline, DISCOURAGING);
});

test("exact wording per grade, exercise", () => {
  const said = Object.fromEntries(["S", "A", "B", "C", "D", "E", "F"].map((g) => [g, headlineFor("exercise", g, SCALE)]));
  assert.deepEqual(said, { S: "Top form today.", A: "Strong form today.", B: "Solid form today.", C: "Good work. A few fixes.",
    D: "Keep working on it.", E: "Keep working on it.", F: "Keep working on it." });
});

test("words and grade read from one scale: prod job 7d73d7cd1c42 (credit C, older score 61 D) says the C line", () => {
  const a = withPercent(71.8);
  a.score = { ...a.score, value: 61, grade: "D" };
  const m = summaryOf(a, { kind: "exercise" });
  assert.equal(m.ring.grade, "C");
  assert.equal(m.headline, "Good work. A few fixes.");
});

test("the headline follows the level on screen, as the ring's grade does", () => {
  const a = withPercent(74.7, { levels: { easy: { percent: 96, points: 9600, max_points: 10000 }, hard: { percent: 50, points: 5000, max_points: 10000 } } });
  for (const [level, grade] of [["easy", "S"], ["hard", "E"]]) {
    const m = summaryOf(a, { kind: "exercise", scoreDisplay: { mode: "percent", level } });
    assert.equal(m.ring.grade, grade);
    assert.equal(m.headline, headlineFor("exercise", grade, SCALE));
  }
});

test("a take without a credit uses the score's A to F grade and its words", () => {
  const m = summaryOf(plain, { kind: "exercise" });
  assert.equal(m.ring.grade, plain.score.grade);
  assert.equal(m.headline, headlineFor("exercise", plain.score.grade, null));
  assert.equal(headlineFor("exercise", "A", null), "Strong form today.");
});

test("a letter on no known scale falls back by its place on the scale, else says nothing about the grade", () => {
  const scale = [[90, "X"], [60, "Y"], [0, "Z"]];
  assert.equal(headlineFor("exercise", "X", scale), "Top form today.");
  assert.equal(headlineFor("exercise", "Z", scale), "Keep working on it.");
  assert.equal(headlineFor("exercise", "Q", null), "Here is how it went.");
  assert.equal(headlineFor("exercise", undefined, null), "Here is how it went.");
});

test("no headline uses an em or en dash", () => {
  for (const kind of ["exercise", "dance", "rehab"]) for (const g of ["S", "A", "B", "C", "D", "E", "F"]) assert.doesNotMatch(headlineFor(kind, g, SCALE), /[\u2013\u2014]/);
});

test("the shared page shows the ring's grade, with no feedback line of its own", async () => {
  const src = fs.readFileSync(new URL("../../web/views/shared.js", import.meta.url), "utf8");
  assert.doesNotMatch(src, /Keep working|Strong form|Solid form/);
  const { shownScore } = await import("../../web/model/score-labels.js");
  assert.equal(shownScore(withPercent(97).score).letter, summaryOf(withPercent(97), { kind: "exercise" }).ring.grade);
});
