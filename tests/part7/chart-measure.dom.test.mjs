// Chart heights follow the shown measure (docs/specs/one-letter.md L8): on the history and teacher charts a C at 37
// (the credit's 72.6%, the MM-Fit take 42a02415127e, CC BY 4.0) sits above an F at 50, and the axis says what it counts.
//   node --test tests/part7/chart-measure.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom } from "./fake-dom.mjs";

installDom();
const { chartMeasure } = await import("../../web/model/score-labels.js");
const { scoreLine } = await import("../../web/model/score-line.js");
const history = await import("../../web/model/history.js");
const teacher = await import("../../web/model/teacher.js");

const CREDIT = { letter: "C", figures: "16,239", caption: "of 22,367", unit: "points", capped: false, warning: [], measure: 72.6 };
const PLAIN50 = { letter: "F", figures: "50", caption: "out of 100", unit: "score", capped: false, warning: [], measure: 50 };
const KEY = { section_key: "full", mode: "fitness", score_version: "simon.score.v3" };
const take = (n, score, shown) => ({ take: n, at: `2026-11-0${n}T10:00:00Z`, score, grade: "F", ...KEY, ...(shown ? { shown } : {}) });
const higher = (a, b) => a.y < b.y;   // SVG: a smaller y is higher on the chart

test("history: the C at 37 (72.6%) sits higher than the F at 50", () => {
  const [c, f] = scoreLine([take(1, 37, CREDIT), take(2, 50, PLAIN50)]).points;
  assert.ok(higher(c, f), `C at y=${c.y} should be above F at y=${f.y}`);
  assert.equal(c.score, 37);   // Part 5's value stays on the point
});

test("teacher: the C at 37 (72.6%) sits higher than the F at 50", () => {
  const [c, f] = teacher.chartModel([take(1, 37, CREDIT), take(2, 50, PLAIN50)]).points;
  assert.ok(higher(c, f), `C at y=${c.y} should be above F at y=${f.y}`);
});

test("an old row without a measure falls back to its score", () => {
  const [old, c] = scoreLine([take(1, 80), take(2, 37, CREDIT)]).points;
  const [plain] = scoreLine([take(1, 80, { ...PLAIN50, figures: "80", measure: 80 })]).points;
  assert.equal(old.y, plain.y);   // 80 with no block sits where 80 out of 100 does
  assert.ok(higher(old, c));      // 80 above 72.6
  const [t] = teacher.chartModel([take(1, 80)]).points;
  assert.equal(t.y, teacher.chartModel([take(1, 80, { ...PLAIN50, measure: 80 })]).points[0].y);
});

test("the axis says what the height counts, and how mixed rows read", () => {
  assert.equal(chartMeasure([take(1, 37, CREDIT)]).axis, "% of the trainer's points");
  assert.equal(chartMeasure([take(1, 50, PLAIN50), take(2, 60)]).axis, "Score out of 100");
  assert.equal(chartMeasure([take(1, 37, CREDIT), take(2, 50, PLAIN50)]).axis,
    "% of the trainer's points, or the score out of 100 for a take without points");
  assert.equal(history.takesChart([take(1, 37, CREDIT)]).axis, "% of the trainer's points");
  assert.equal(teacher.teacherView({ takes: [take(1, 37, CREDIT)] }, { name: "Squat" }, "squat").chart.axis, "% of the trainer's points");
  assert.equal(history.takesChart([take(1, 37, CREDIT)]).hint, "Oldest take on the left. The height is the % of the trainer's points, from 0 to 100.");
  assert.equal(history.takesChart([take(1, 50)]).hint, "Oldest take on the left. Scores run from 0 to 100.");   // an old chart reads as before
  const mixed = teacher.chartModel([take(1, 37, CREDIT), take(2, 50, PLAIN50)]);
  assert.equal(mixed.hint, "Oldest take on the left. The height is the % of the trainer's points, or the score out of 100 for a take without points.");
  const DASHES = new RegExp("[\\u2013\\u2014]");   // the writer rules: no en or em dash in axis text
  for (const t of [mixed.axis, mixed.hint]) assert.doesNotMatch(t, DASHES);
});

test("the spoken labels name the shown figures, not the heights", () => {
  const label = history.takesChart([take(1, 50, PLAIN50), take(2, 37, CREDIT)]).label;
  assert.match(label, /from 50 to 16,239 points of 22,367/);
  assert.match(label, /Lowest 50, highest 16,239 points of 22,367/);
  assert.doesNotMatch(label, /72\.6/);
  assert.match(teacher.chartLabel([take(1, 50, PLAIN50), take(2, 37, CREDIT)]), /Lowest 50, highest 16,239 points of 22,367/);
  assert.equal(teacher.chartLabel([take(1, 80)]), "One score: 80.");   // an old row reads as before
});
