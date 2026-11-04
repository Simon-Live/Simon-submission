// One score on the result (web/model/score-labels.js, Part 5 CONTRACT: score.value is THE score). The fixture is
// staging job 652b525a73ee's analysis shape (Part 5 1.12.0): one part at 100 A, capped to 59 F by low_match, no
// faults, no insights; paths, diagnostics and the second opinion left out.
//   node --test tests/part7/score_consistency.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { summaryOf, labelSummary, isLowMatch, isCapped, insightsEmptyText, LOW_MATCH_TEXT, SCORE_CAPTION } from "../../web/model/score-labels.js";
import { summaryOf as baseSummaryOf } from "../../web/model/result-summary.js";

const load = (f) => JSON.parse(fs.readFileSync(new URL(`../../fixtures/input/${f}`, import.meta.url)));
const hero = load("analysis-low-match-hero.json");
const plain = load("analysis-timeline.json");   // 8 reps, 77 C, no cap
const credit = load("analysis-credit.json");
const NB = / /g;

/** Every figure in the summary's visible text, each with the words just before it. */
function figures(m) {
  const lines = [
    `${m.ring.caption} ${m.ring.text}`,
    m.sum && m.sum.text,
    ...m.stats.map((x) => `${x.label} ${x.value}`),
    ...m.bars.map((b) => `${m.barsTitle} ${b.label} ${b.text}`),
  ].filter(Boolean).map((t) => t.replace(NB, " "));
  return lines.flatMap((t) => [...t.matchAll(/(\d+(?:\.\d+)?)/g)].map((x) => ({ n: Number(x[1]), before: t.slice(0, x.index), line: t })));
}

test("the hero take: the ring, the grade and the sum all name score.value (59) as the score", () => {
  const m = summaryOf(hero, { kind: "exercise" });
  assert.equal(m.ring.value, 59);
  assert.equal(m.ring.text, "59");
  assert.equal(m.ring.grade, "F");
  assert.equal(m.ring.caption, SCORE_CAPTION, "a capped score is not called average form");
  assert.notEqual(m.ring.caption, "average form");
  assert.match(m.ring.label, /^Score 59 out of 100, grade F$/);
  const sum = m.sum.text.replace(NB, " ");
  assert.match(sum, /≈ 100 before the warning cap\. A warning then limited the score to 59: /);
  assert.equal(m.sum.capped, true);
});

test("the hero take: every other figure is labelled as from before the cap", () => {
  const m = summaryOf(hero, { kind: "exercise" });
  assert.deepEqual(m.stats.map((x) => [x.label, x.value]), [["Parts", "1"], ["Best part before the cap", "100"]]);
  assert.equal(m.barsTitle, "Form over the take before the cap");
  for (const b of m.bars) assert.equal(b.value, 100);
});

test("negative: no unlabelled number other than score.value in the summary area", () => {
  const m = summaryOf(hero, { kind: "exercise" });
  const value = hero.score.value;
  const allowed = (f) => f.n === value
    || / out of $/.test(f.before)                                   // the scale, "score out of 100"
    || /before the (warning |fault )?caps?/.test(f.line)          // labelled as from before the cap
    || /^Parts $/.test(f.before) || /^Form over the take before the cap \d*$/.test(f.before.trim()) // a count or a bar's index
    || /started at $/.test(f.before) || /lost /.test(f.before);  // the sum's own terms (100 start, the deductions)
  const loose = figures(m).filter((f) => !allowed(f));
  assert.deepEqual(loose, [], `unlabelled figures: ${JSON.stringify(loose)}`);
  // and the client's model alone shows why the label is needed: the same 100 under "Best part", the ring "average form"
  const raw = baseSummaryOf(hero, { kind: "exercise" });
  assert.equal(raw.ring.caption, "average form");
  assert.equal(raw.stats.find((x) => x.key === "best").label, "Best part");
});

test("a low-match take never says it has nothing to work on", () => {
  assert.equal(isLowMatch(hero), true);
  assert.equal(insightsEmptyText(hero), LOW_MATCH_TEXT);
  assert.equal(LOW_MATCH_TEXT, "This take didn't match the trainer closely enough to judge form.");
  assert.doesNotMatch(insightsEmptyText(hero), /Nothing to work on/);
  assert.equal(isLowMatch({ score: { capped_by: ["low_match"] } }), true);
  assert.equal(isLowMatch({ match: { quality: "low" } }), true);
  assert.equal(isLowMatch(plain), false);
  assert.equal(insightsEmptyText(plain), "Nothing to work on in this take.");
  assert.equal(isLowMatch(null), false);
});

test("an uncapped take and a credit score keep the client's model as it is", () => {
  assert.equal(isCapped(plain.score), false);
  assert.deepEqual(summaryOf(plain, { kind: "exercise" }), baseSummaryOf(plain, { kind: "exercise" }));
  assert.equal(summaryOf(plain, { kind: "exercise" }).ring.caption, "average form");
  const cappedCredit = { ...credit, score: { ...credit.score, value: 59, grade: "F", uncapped: { value: 80, grade: "B" }, capped_by: ["low_match"] } };
  assert.deepEqual(summaryOf(credit, { kind: "exercise" }), baseSummaryOf(credit, { kind: "exercise" }), "an uncapped credit ring is the client's");
  // team, 2 Nov (#61): nothing capped. A warned take with a credit shows the credit, exactly as the client's model draws it
  const m = summaryOf(cappedCredit, { kind: "exercise" });
  assert.deepEqual(m, baseSummaryOf(cappedCredit, { kind: "exercise" }), "the credit ring, its switch and its F to S letter stay");
  assert.notEqual(m.ring.unit, "score");
  assert.ok(m.scoreSwitch, "the points or % switch stays");
  assert.equal(labelSummary(null, hero), null);
});

test("dance: a capped take's ring is captioned as the score too", () => {
  const m = summaryOf(hero, { kind: "dance" });
  assert.equal(m.ring.caption, SCORE_CAPTION);
  assert.equal(m.ring.text, "59");
});

test("a too-dark take (TICKET-247): withLight runs first, so the light cap is the one score the summary shows", async () => {
  const { withLight, LIGHT_CAP } = await import("../../web/light-result.js");
  assert.ok(plain.score.value > LIGHT_CAP, "the fixture scores above the cap");
  const dark = withLight(plain, { median_y: 30, dark_share: 0.9, level: "major" });
  assert.equal(isCapped(dark.score), true);
  assert.equal(dark.score.uncapped.value, plain.score.value);
  const m = summaryOf(dark, { kind: "exercise" });
  assert.equal(m.ring.value, LIGHT_CAP);
  assert.equal(m.ring.text, String(LIGHT_CAP));
  assert.equal(m.ring.caption, SCORE_CAPTION);
  // negative: the same take without the light reading keeps its own score and the client's caption
  assert.equal(summaryOf(withLight(plain, { level: "ok" }), { kind: "exercise" }).ring.caption, "average form");
});
