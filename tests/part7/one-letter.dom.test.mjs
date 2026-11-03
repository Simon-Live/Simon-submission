// One take, one letter (docs/specs/one-letter.md AC-1 to AC-5). The real MM-Fit take 42a02415127e (CC BY 4.0) has
// `score.value` 37, grade F and Part 5's credit 16,239 of 22,367 points, C on the F to S scale, with no cap: its result
// headline shows C, and every other surface showed F. Its capped variant (a low_match warning cap) shows 37 F everywhere.
//   node --test tests/part7/one-letter.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { installDom, El, find } from "./fake-dom.mjs";

installDom();
const { shownScore, shownRow, toneOfLetter, shownText } = await import("../../web/model/score-labels.js");
const me = await import("../../web/model/me.js");
const teacher = await import("../../web/model/teacher.js");
const history = await import("../../web/model/history.js");
const { scoreLine } = await import("../../web/model/score-line.js");
const notes = await import("../../web/model/notes.js");
const share = await import("../../web/model/share.js");
const { heroCard } = await import("../../web/hero.js");
const core = await import("../../web/challenge-core.js");
const actions = await import("../../web/challenge-actions.js");
const { renderScore, refreshScore } = await import("../../web/score.js");
const group = await import("../../web/group-result.js");

const VECTORS = JSON.parse(fs.readFileSync(new URL("./fixtures/shown-score-vectors.json", import.meta.url))).cases;
const TRIGGER = VECTORS[0].analysis.score;
const CAPPED = VECTORS[4].analysis.score;
// what the server sends with a row (part7/shown_score.py `public`)
const CREDIT_SHOWN = { letter: "C", figures: "16,239", caption: "of 22,367", unit: "points", capped: false, warning: [], measure: 72.6 };
const CAPPED_SHOWN = { letter: "F", figures: "37", caption: "score out of 100", unit: "score", capped: true, warning: ["low_match"], measure: 37 };
const row = (shown, extra = {}) => ({ job_id: "42a02415127e", take: 1, at: "2026-11-02T10:00:00Z", score: 37, grade: "F", shown, ...extra });
const CREDIT_ROW = row(CREDIT_SHOWN);
const CAPPED_ROW = row(CAPPED_SHOWN);
const OLD_ROW = row(undefined);

// ----- AC-1: the shared vectors ---------------------------------------------------------------------------------------
for (const c of VECTORS) {
  test(`vector: ${c.name}`, () => {
    const got = shownScore(c.analysis, { light: c.light || null, display: c.display || null });
    if (c.expect === null) return assert.equal(got, null);
    const { frac: _f, grades: _g, ...same } = got;
    assert.deepEqual(same, c.expect);
  });
}

test("a credit take carries its own scale for the grade panel; a plain take the A to F bands", () => {
  const credit = shownScore({ score: TRIGGER });
  assert.equal(credit.grades[0][1], "S");
  assert.ok(Math.abs(credit.frac - 0.726) < 1e-9);
  assert.equal(shownScore({ score: { value: 82, grade: "B" } }).grades[0][1], "A");
  assert.equal(toneOfLetter("S"), "good");
  assert.equal(toneOfLetter("E"), "bad");
  assert.equal(toneOfLetter("?"), "warn");
});

test("shownText words the figures as the ring's label does", () => {
  assert.equal(shownText(CREDIT_SHOWN), "16,239 points of 22,367");
  assert.equal(shownText(CAPPED_SHOWN), "37");
  assert.equal(shownText({ figures: "73%", caption: "credit earned", unit: "percent" }), "73% credit earned");
});

// ----- AC-5: a row stored before the block ----------------------------------------------------------------------------
test("shownRow: the server's block, else the row's own score and grade", () => {
  assert.equal(shownRow(CREDIT_ROW).letter, "C");
  assert.equal(shownRow(CREDIT_ROW).figures, "16,239");
  assert.deepEqual([shownRow(OLD_ROW).letter, shownRow(OLD_ROW).figures], ["F", "37"]);
  assert.equal(shownRow({ score: null }), null);
  assert.equal(shownRow({ ...OLD_ROW, shown: { letter: 3 } }).letter, "F");   // a malformed block is ignored
});

// ----- AC-2, AC-3: each surface ---------------------------------------------------------------------------------------
const pair = (r) => [r.score, r.grade];

test("Me list", () => {
  assert.deepEqual(pair(me.takeRow({ ...CREDIT_ROW, kind: "follow" })), ["16,239", "C"]);
  assert.equal(me.takeRow({ ...CREDIT_ROW, kind: "follow" }).tone, "warn");
  assert.deepEqual(pair(me.takeRow({ ...CAPPED_ROW, kind: "follow" })), ["37", "F"]);
  assert.deepEqual(pair(me.takeRow({ ...OLD_ROW, kind: "follow" })), ["37", "F"]);
});

test("teacher dashboard: takes and chart points", () => {
  const view = teacher.teacherView({ takes: [CREDIT_ROW, CAPPED_ROW] }, { name: "Squat" }, "squat");
  assert.deepEqual(view.takes.map(pair), [["37", "F"], ["16,239", "C"]]);   // newest first
  assert.deepEqual(view.chart.points.map((p) => [p.score, p.grade]), [[37, "C"], [37, "F"]]);   // the height stays the 0 to 100 score
});

test("history: rows, fact table and chart points", () => {
  const view = history.pageView({ takes: [CREDIT_ROW, { ...CAPPED_ROW, take: 2 }] }, "squat", null);
  assert.deepEqual(view.takes.map(pair), [["16,239", "C"], ["37", "F"]]);
  const facts = history.factTable({ takes: [CREDIT_ROW, CAPPED_ROW] });
  assert.deepEqual(facts.takes.map(pair), [["16,239", "C"], ["37", "F"]]);
  const line = scoreLine([CREDIT_ROW, { ...CAPPED_ROW, take: 2 }]);
  assert.deepEqual(line.points.map((p) => [p.score, p.grade, p.tone]), [[37, "C", "warn"], [37, "F", "bad"]]);
});

test("notes: the trainer's score line", () => {
  const view = (shown) => notes.trainerView({ id: "r1", state: "asked", include: ["score"], score: { value: 37, grade: "F", shown } });
  assert.equal(view(CREDIT_SHOWN).score, "Score 16,239 points of 22,367, grade C");
  assert.equal(view(CAPPED_SHOWN).score, "Score 37, grade F");
  assert.equal(view(undefined).score, "Score 37, grade F");
});

test("share: a shared history report's rows", () => {
  const vm = share.viewModel({ kind: "history_report", takes: [{ take: 1, score: 37, grade: "F", shown: CREDIT_SHOWN }, { take: 2, score: 37, grade: "F", shown: CAPPED_SHOWN }] });
  assert.deepEqual(vm.rows.map(pair), [["16,239", "C"], ["37", "F"]]);
});

test("judge hero card: take f7f06d0bc4f3 (31 F, credit 17,486 of 24,200, C) reads as its headline", () => {
  const hero = { job_id: "f7f06d0bc4f3", entry_id: "e", score: 31, source: "configured",
    shown: { letter: "C", figures: "17,486", caption: "of 24,200", unit: "points", capped: false, warning: [] } };
  const text = heroCard(hero).text;
  assert.equal(text, "Scored 17,486 points of 24,200, grade C, with both bodies in 3D.");
  assert.doesNotMatch(text, /\b31\b|\bF\b/, "negative: neither the 0 to 100 score nor its grade");
  const capped = heroCard({ ...hero, shown: { letter: "F", figures: "31", caption: "score out of 100", unit: "score", capped: true, warning: ["low_match"] } });
  assert.equal(capped.text, "Scored 31 out of 100, grade F, with both bodies in 3D.");
});

test("judge hero line", () => {
  assert.equal(heroCard({ job_id: "42a02415127e", score: 37, shown: CREDIT_SHOWN }).text, "Scored 16,239 points of 22,367, grade C, with both bodies in 3D.");
  assert.equal(heroCard({ job_id: "42a02415127e", score: 37 }).text, "Scored 37 out of 100, with both bodies in 3D.");
});

test("boards: the row and the leader show the letter; ranking follows the shown measure (AC-4, one-letter.md L3)", () => {
  const ranked = core.rankEntries([{ name: "Ana", score: 37, grade: "F", shown: CREDIT_SHOWN, created_at: "a" }, { name: "Cy", score: 50, grade: "F", created_at: "b" }]);
  assert.deepEqual(ranked.map((e) => e.name), ["Ana", "Cy"]);   // C at 72.6% above 50 F
  assert.deepEqual(core.boardNums(ranked[0]), { score: "16,239", grade: "C" });
  assert.deepEqual(core.boardNums({ score: 37, grade: "F", shown: CAPPED_SHOWN }), { score: "37", grade: "F" });
  assert.equal(core.leaderText({ score: 37, shown: CREDIT_SHOWN }), ", top score 16,239 points of 22,367");
  assert.equal(core.leaderText({ score: 50 }), ", top score 50");
  assert.equal(core.leaderText(null), "");
});

test("the challenge share card and text", () => {
  const added = { name: "Ana", score: 37, grade: "F", shown: CREDIT_SHOWN };
  const model = actions.cardModel({ id: "c1", title: "T" }, added, "Squat", "https://x/#/challenge/c1");
  assert.deepEqual([model.score, model.grade], ["16,239", "C"]);
  assert.equal(actions.shareText(added, "Squat"), "I scored 16,239 points of 22,367 on Squat. Can you beat it?");
  assert.equal(actions.shareText({ ...added, shown: CAPPED_SHOWN }, "Squat"), "I scored 37 on Squat. Can you beat it?");
});

test("group result rows", () => {
  const rows = group.boardRows({ people: [{ id: "1", score: 37, grade: "F", status_code: "ok", shown: CREDIT_SHOWN },
    { id: "2", score: 37, grade: "F", status_code: "ok", shown: CAPPED_SHOWN }, { id: "3", score: 37, grade: "F", status_code: "ok" }] });
  assert.deepEqual(rows.map(pair), [["16,239", "C"], ["37", "F"], [37, "F"]]);
  assert.deepEqual(rows.map((r) => r.id), ["1", "2", "3"]);   // the server's order
});

test("the result's grade panel shows the headline's letter on the credit scale", () => {
  const root = new El("div");
  const panel = renderScore(root, { score: TRIGGER });
  assert.equal(find(panel, "grade").textContent, "C");
  assert.match(find(panel, "band-rule").textContent, /S95 and above/);
  assert.doesNotMatch(find(panel, "band-rule").textContent, /90 and above/);
  const hard = refreshScore(panel, { score: TRIGGER }, { mode: "points", level: "hard" });
  assert.equal(find(hard, "grade").textContent, "D");
  const warned = renderScore(new El("div"), { score: CAPPED });   // a credit with a warning: shown as Part 5 gave it, no cap line
  assert.equal(find(warned, "grade").textContent, "C");
  assert.equal(find(warned, "score").textContent, "16,239");
  assert.equal(find(warned, "score-cap"), null);
  const capped = renderScore(new El("div"), { score: VECTORS[11].analysis.score });   // no credit block: the A to F fallback, with its cap line
  assert.equal(find(capped, "grade").textContent, "F");
  assert.match(find(capped, "band-rule").textContent, /90 and above/);
  assert.ok(find(capped, "score-cap"));
  const plain = renderScore(new El("div"), { score: { value: 82, grade: "B" } });
  assert.equal(find(plain, "grade").textContent, "B");
});
