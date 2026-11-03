// Part 5's credit score on the result screen (web/model/score-credit.js, its use in model/result-summary.js and
// the saved choice in web/score-display.js). analysis-credit.json is analysis-timeline.json (8 reps, 77 / C) with a
// simon.credit.v1 block standing in for Part 5's score-credit branch.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { creditOf, creditDisplay, creditRing, creditSwitch, creditExplanation, levelsOf, pickDisplay, windowCredit, groupDigits, gradesOf, letterFor, SCORE_GRADES }
  from "../../web/model/score-credit.js";
import { summaryOf } from "../../web/model/result-summary.js";
import { loadScoreDisplay, saveScoreDisplay } from "../../web/score-display.js";

const load = (f) => JSON.parse(fs.readFileSync(new URL(`../../fixtures/input/${f}`, import.meta.url)));
const withCredit = load("analysis-credit.json");
const plain = load("analysis-timeline.json");
const credit = withCredit.score.credit;
// the block as Part 5's design names it (per_window shortened)
const spec = {
  version: "simon.credit.v1", percent: 74.3, grade: "C", points: 20562, max_points: 23687, tolerance: "normal",
  levels: { easy: { percent: 93.4, points: 15420, max_points: 17765 }, normal: { percent: 74.3, points: 20562, max_points: 23687 },
    hard: { percent: 78.2, points: 27786, max_points: 35530 } },
  bands: [[0.5, 1.0], [1.0, 0.6], [2.0, 0.2]], points_per_measure_second: 100,
  per_window: [{ t_s: [0.0, 5.2], percent: 81.0, points: 4012, max_points: 4953 }, { t_s: [5.2, 10.4], percent: 67.6, points: 3350, max_points: 4953 }],
};

test("no credit block (null or absent): nothing to show, the summary is today's score", () => {
  assert.equal(creditOf(plain), null);
  assert.equal(creditDisplay({ score: { ...plain.score, credit: null } }), null);
  assert.equal(creditDisplay({ score: { value: 50, grade: "F", credit: { version: "simon.credit.v1" } } }), null, "malformed: no numbers");
  assert.equal(creditDisplay(null), null);
  for (const a of [plain, { ...withCredit, score: { ...withCredit.score, credit: null } }]) {
    const m = summaryOf(a, { scoreDisplay: { mode: "points" } });
    assert.equal(m.scoreSwitch, null);
    assert.equal(m.ring.text, String(plain.score.value));
    assert.equal(m.ring.caption, "average form");
    assert.equal(m.ring.grade, plain.score.grade);
    assert.match(m.sum.text, /started at 100 and lost/);
    assert.deepEqual(m.bars.map((b) => b.value), plain.score.timeline.map((w) => w.value));
  }
});

test("percent mode: the rounded percentage, Part 5's grade, the switch on %", () => {
  const r = creditRing(spec, { mode: "percent" });
  assert.equal(r.text, "74");
  assert.equal(r.grade, "C");
  assert.equal(r.caption, "credit earned");
  assert.ok(Math.abs(r.frac - 0.743) < 1e-9);
  const m = summaryOf(withCredit, { scoreDisplay: { mode: "percent" } });
  assert.equal(m.ring.unit, "percent");
  assert.equal(m.ring.text, String(Math.round(credit.percent)));
  assert.equal(summaryOf(withCredit, {}).ring.unit, "points", "points by default");
  assert.equal(m.ring.grade, credit.grade);
  assert.deepEqual(m.scoreSwitch.modes.map((x) => [x.text, x.active]), [["%", true], ["Points", false]]);
});

test("points mode: the points with 'of' the most, the same grade", () => {
  const r = creditRing(spec, { mode: "points" });
  assert.equal(r.text, "20,562");
  assert.equal(r.value, 20562);
  assert.equal(r.caption, "of 23,687");
  assert.equal(r.grade, "C");
  assert.match(r.label, /20,562 points of 23,687, grade C/);
  const m = summaryOf(withCredit, { scoreDisplay: { mode: "points" } });
  assert.equal(m.ring.unit, "points");
  assert.equal(m.ring.caption, `of ${groupDigits(credit.max_points)}`);
});

test("levels: Easy / Normal / Hard switch the numbers; the grade stays Part 5's", () => {
  assert.deepEqual(levelsOf(spec), ["easy", "normal", "hard"]);
  assert.equal(creditRing(spec, { mode: "percent", level: "easy" }).text, "93");
  assert.equal(creditRing(spec, { mode: "points", level: "hard" }).text, "27,786");
  assert.equal(creditRing(spec, { mode: "points", level: "hard" }).caption, "of 35,530");
  assert.equal(creditRing(spec, { level: "hard" }).grade, "C");
  const sw = creditSwitch(spec, { level: "easy" });
  assert.deepEqual(sw.levels.map((x) => [x.text, x.active]), [["Easy", true], ["Normal", false], ["Hard", false]]);
  // a credit with only its own tolerance: no level picker
  assert.deepEqual(creditSwitch({ ...spec, levels: undefined }, {}).levels, []);
});

test("a saved choice is checked: unknown values fall back to points at the scored tolerance", () => {
  assert.deepEqual(pickDisplay(spec, {}), { mode: "points", level: "normal" });
  assert.deepEqual(pickDisplay(spec, { mode: "stars", level: "insane" }), { mode: "points", level: "normal" });
  assert.deepEqual(pickDisplay({ ...spec, levels: undefined }, { level: "easy" }), { mode: "points", level: "normal" });
  assert.deepEqual(pickDisplay(spec, null), { mode: "points", level: "normal" });
});

test("the explanation is the bands in plain words, and the points rate", () => {
  assert.equal(creditExplanation(spec),
    "Every body part earns credit on every frame: full credit within half its tolerance, 60% within it, 20% within twice it."
    + " Points: 100 per body part per second at Normal.");
  assert.equal(creditExplanation({ ...spec, bands: undefined, points_per_measure_second: undefined }), "Every body part earns credit on every frame.");
  const m = summaryOf(withCredit, {});
  assert.equal(m.sum.credit, true);
  assert.doesNotMatch(m.sum.text, /started at 100/);
});

test("per window: the same unit as the switch, matched on the window's span", () => {
  const windows = [{ t_s: [0.0, 5.2] }, { t_s: [5.2, 10.4] }];
  assert.deepEqual(windowCredit(spec, windows, { mode: "percent" }).values.map((v) => v.text), ["81%", "68%"]);
  assert.deepEqual(windowCredit(spec, windows, { mode: "points" }).values.map((v) => v.text), ["4,012 of 4,953 points", "3,350 of 4,953 points"]);
  assert.equal(windowCredit(spec, [{ t_s: [20, 25] }, { t_s: [25, 30] }, { t_s: [30, 35] }], {}).values.every((v) => v === null), true, "no match, no value");
  // another level without its own per_window: the scored level's windows, and the note says so
  const easy = windowCredit(spec, windows, { mode: "percent", level: "easy" });
  assert.equal(easy.values[0].text, "81%");
  assert.match(easy.note, /at Normal/);
  assert.doesNotMatch(windowCredit(spec, windows, {}).note, /at Normal/);
  // a level with its own per_window uses it
  const own = { ...spec, levels: { ...spec.levels, easy: { ...spec.levels.easy, per_window: [{ t_s: [0, 5.2], percent: 95, points: 3529, max_points: 3715 }] } } };
  assert.equal(windowCredit(own, windows, { mode: "percent", level: "easy" }).values[0].text, "95%");
});

test("the summary's bars follow the switch; skipped windows stay skipped", () => {
  const pct = summaryOf(withCredit, { scoreDisplay: { mode: "percent" } });
  assert.deepEqual(pct.bars.map((b) => b.value), credit.per_window.map((r) => Math.round(r.percent)));
  assert.equal(pct.bars[0].text, `${Math.round(credit.per_window[0].percent)}%`);
  const pts = summaryOf(withCredit, { scoreDisplay: { mode: "points" } });
  assert.match(pts.bars[0].text, /^[\d,]+ of [\d,]+ points$/);
  const skipped = structuredClone(withCredit);
  skipped.score.timeline[2].compared = false;
  const b = summaryOf(skipped, {}).bars[2];
  assert.equal(b.state, "skipped");
  assert.equal(b.value, null);
});

test("the choice is saved in storage, and works without it", () => {
  const mem = new Map();
  const storage = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) };
  assert.deepEqual(loadScoreDisplay(storage), { mode: undefined, level: undefined });
  saveScoreDisplay({ mode: "points", level: "hard" }, storage);
  assert.deepEqual(loadScoreDisplay(storage), { mode: "points", level: "hard" });
  const blocked = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.deepEqual(loadScoreDisplay(blocked), {});
  assert.doesNotThrow(() => saveScoreDisplay({ mode: "points" }, blocked));
  mem.set("simon.scoreDisplay", "not json");
  assert.deepEqual(loadScoreDisplay(storage), {});
});

test("the credit's F to S grades: Part 5's scale when written, the letter follows the level on screen, else the old A to F", () => {
  const scale = [[95, "S"], [85, "A"], [75, "B"], [65, "C"], [55, "D"], [45, "E"], [30, "F"]];
  assert.deepEqual([100, 95, 90, 75, 65, 55, 48.8, 30, 12].map((p) => letterFor(p, scale)), ["S", "S", "A", "B", "C", "D", "E", "F", "F"]);
  const graded = { ...spec, grades: scale };
  assert.deepEqual(gradesOf(graded), scale);
  assert.equal(gradesOf(spec), SCORE_GRADES, "an analysis without credit.grades keeps the old bands");
  const normal = creditRing(graded, { mode: "percent", level: "normal" });
  assert.equal(normal.grade, letterFor(spec.percent, scale));
  assert.deepEqual(normal.grades, scale);
  const easy = creditRing(graded, { mode: "percent", level: "easy" });
  assert.equal(easy.grade, letterFor(spec.levels.easy.percent, scale), "the grade follows the level shown");
  assert.equal(creditRing(spec, { mode: "percent" }).grade, spec.grade, "an older analysis keeps the grade it wrote");
});
