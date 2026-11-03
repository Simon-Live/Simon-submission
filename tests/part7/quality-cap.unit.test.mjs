// Part 5 1.13.0 (pin 03137b9): the quality cap Part 7 applies, and the credit block read by its real field names.
// Inputs are Part 5's own example documents from the pinned checkout, not hand-made shapes.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { withQualityCap, qualityLevel, qualityWords, QUALITY_CAP_CODE, QUALITY_FALLBACK_LABEL } from "../../web/quality-cap.js";
import { withLight } from "../../web/light-result.js";
import { resultWarnings } from "../../web/result.js";
import { qualityCapText } from "../../web/quality-result.js";
import { isCapped, summaryOf } from "../../web/model/score-labels.js";
import { creditOf, creditRing, creditSwitch, levelsOf } from "../../web/model/score-credit.js";
import { partTest } from "./needs-part.mjs";

const load = (name) => JSON.parse(readFileSync(new URL(`../../modules/part-5/fixtures/output/${name}`, import.meta.url), "utf8"));
const major = () => load("analysis.quality-major.example.json");
const ok = () => load("analysis.example.json");
const p5test = partTest(5);  // every test below but one reads the Part 5 examples

p5test("the real major example reports a cap and keeps its own score.value", () => {
  const a = major();
  assert.equal(qualityLevel(a), "major");
  assert.equal(a.quality.score_cap, 59);
  assert.ok(qualityWords(a).length > 10);
});

p5test("a major block shows min(score.value, score_cap), grade F, the reason in Part 5's words and the pre-cap figure", () => {
  const a = major();
  a.score = { ...a.score, value: 88, grade: "B", uncapped: undefined };
  delete a.score.uncapped;
  const out = withQualityCap(a);
  assert.equal(out.score.value, 59);
  assert.equal(out.score.grade, "F");
  assert.deepEqual(out.score.uncapped, { value: 88, grade: "B" });
  assert.ok(out.score.capped_by.includes(QUALITY_CAP_CODE));
  const warning = resultWarnings(out).find((w) => w.code === QUALITY_CAP_CODE);
  assert.equal(warning.text, qualityWords(a));
  assert.match(qualityCapText(out), /Capped at 59/);
  assert.equal(a.score.value, 88, "the input is never mutated");
});

p5test("one score everywhere: the summary names the capped score and labels the figures from before the cap", () => {
  const a = major();
  a.score = { ...a.score, value: 88, grade: "B" };
  delete a.score.uncapped;
  delete a.score.credit;
  const out = withQualityCap(a);
  assert.equal(isCapped(out.score), true);
  const model = summaryOf(out, {});
  assert.equal(model.ring.value, 59);
});

p5test("a score already under the cap keeps its value and its grade; the reason still shows", () => {
  const a = major();
  a.score = { ...a.score, value: 40, grade: "F" };
  const out = withQualityCap(a);
  assert.equal(out.score.value, 40);
  assert.equal(out.score.capped_by, a.score.capped_by);
  assert.ok(resultWarnings(out).some((w) => w.code === QUALITY_CAP_CODE));
});

p5test("ok, degraded and an absent block never cap; absent is not assessed, never ok", () => {
  const a = ok();
  assert.equal(withQualityCap(a), a);
  const degraded = { ...a, quality: { ...a.quality, level: "degraded", score_cap: null } };
  assert.equal(withQualityCap(degraded), degraded);
  const bare = { score: { value: 88, grade: "B" } };
  assert.equal(withQualityCap(bare), bare);
  assert.equal(qualityLevel(bare), "not_assessed");
  assert.equal(qualityLevel({ quality: { level: "fine" } }), "not_assessed");
  assert.equal(withQualityCap(null), null);
});

test("a major block without a usable cap number or without words falls back, and never throws", () => {
  const noCap = { score: { value: 88, grade: "B" }, quality: { level: "major", score_cap: null, reasons: [] } };
  assert.equal(withQualityCap(noCap), noCap);
  const noWords = withQualityCap({ score: { value: 88, grade: "B" }, quality: { level: "major", score_cap: 59, reasons: [{ code: "joints_unseen", words: "  " }] } });
  assert.equal(resultWarnings(noWords).find((w) => w.code === QUALITY_CAP_CODE).text, QUALITY_FALLBACK_LABEL);
});

p5test("a major quality and a major light cap once: the uncapped figure is the first one", () => {
  const a = major();
  a.score = { ...a.score, value: 88, grade: "B" };
  delete a.score.uncapped;
  const out = withLight(withQualityCap(a), { level: "major" });
  assert.equal(out.score.value, 59);
  assert.deepEqual(out.score.uncapped, { value: 88, grade: "B" });
});

// ---- score.credit with the real 1.13.0 names: percent, points, max_points, grades, levels, tolerance ----
p5test("the real credit block drives the Points and % switch", () => {
  const a = ok();
  const credit = creditOf(a);
  assert.ok(credit, "creditOf reads Part 5's block");
  assert.deepEqual(levelsOf(credit), ["easy", "normal", "hard"]);
  const points = creditRing(credit, { mode: "points", level: null });
  assert.equal(points.value, Math.round(credit.points));
  assert.equal(points.caption, `of ${String(credit.max_points).replace(/\B(?=(\d{3})+(?!\d))/g, ",")}`);
  const percent = creditRing(credit, { mode: "percent", level: null });
  assert.equal(percent.value, Math.round(credit.percent));
  const letter = credit.grades.find(([lo]) => credit.percent >= lo)?.[1] ?? "F";
  assert.equal(percent.grade, letter, "the grade follows Part 5's own grades scale (S to F)");
  const easy = creditRing(credit, { mode: "points", level: "easy" });
  assert.equal(easy.value, Math.round(credit.levels.easy.points));
  const sw = creditSwitch(credit, { mode: "points", level: null });
  assert.ok(sw, "the switch model exists");
});

p5test("a credit on a capped take is informational: the ring is the score, the credit grade does not follow the cap", () => {
  const a = major();
  const credit = creditOf(a);
  assert.ok(credit);
  const ring = creditRing(credit, { mode: "percent", level: null });
  assert.equal(ring.grade, credit.grades.find(([lo]) => credit.percent >= lo)?.[1] ?? "F");
});
