// The cap wins everywhere (docs/specs/share.md "Score and cap", docs/specs/score-consistency.md S5). Staging take
// f530a6875dfb (333aefca5): the result's headline showed Part 5's uncapped credit, "10,413 of 22,000" and grade E, under
// a warning that the grade is capped at F, and its share link showed "0 F" with no warning. The fixture is the low-match
// hero (capped to 59 F, 100 A before the cap) carrying the credit block of analysis-credit.json (74.7%, C, 9,087 of
// 12,160), the same shape: a warning cap and a credit that ignores it.
//   node --test tests/part7/share-score-cap.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { installDom, El, find } from "./fake-dom.mjs";

installDom();
globalThis.matchMedia = () => ({ matches: true });   // reduced motion: the headline lands at once
const { summaryOf } = await import("../../web/model/score-labels.js");
const { resultWarnings, WARNING_TITLE } = await import("../../web/result.js");   // the result screen's own warnings
const { withQualityCap } = await import("../../web/quality-cap.js");
const { withLight } = await import("../../web/light-result.js");
const asShown = (a, light) => withLight(withQualityCap(a), light);   // web/result.js: quality cap, then light cap
const { renderResultSummary } = await import("../../web/views/result-summary.js");
const { renderSnapshot } = await import("../../web/views/shared.js");
const shareModel = await import("../../web/model/share.js");

const load = (f) => JSON.parse(fs.readFileSync(new URL(`../../fixtures/input/${f}`, import.meta.url)));
const hero = load("analysis-low-match-hero.json");
const credit = load("analysis-credit.json");
const plain = load("analysis-timeline.json");
const capped = { ...hero, score: { ...hero.score, credit: credit.score.credit } };
// the hooks web/share.js injects: the result screen's warnings and heading
const model = { ...shareModel, bylines: () => ({ author: null, trainer: null }), warningsOf: resultWarnings, warningTitle: () => WARNING_TITLE };
const NB = / /g;

/** The `result` block part7/share_routes.py `_result_block` stores: the score with its cap fields and credit (no
 * per-window detail), the warnings, quality, match, light and mode. */
function resultBlock(a, light = null) {
  const { timeline: _t, per_rep: _p, components: _c, tempo: _m, params_sha256: _h, version: _v, ...score } = a.score;
  if (score.credit) { const { levels: _l, per_window: _w, ...c } = score.credit; score.credit = c; }
  return { score, warnings: a.warnings || [], mode: "fitness", ...(a.match ? { match: { quality: a.match.quality } } : {}),
    ...(a.quality ? { quality: a.quality } : {}), ...(light ? { light } : {}) };
}
const snapshot = (a, light) => ({ kind: "take_result", title: "Squat", score: a.score.value, grade: a.score.grade, result: resultBlock(a, light),
  faults: [], on: "2026-11-02", include: { score: true, faults: true }, clip: false });

/** The result screen's headline, drawn by its own view: {score, caption, grade, label, text}. */
function headline(a, light, scoreDisplay = null) {
  const root = new El("div");
  renderResultSummary(root, summaryOf(asShown(a, light), { kind: "exercise", scoreDisplay }), { reveal: false });
  const bar = find(root, "summary-score");
  return { score: find(root, "score").textContent, caption: find(root, "summary-score-caption").textContent,
    grade: find(root, "summary-grade").textContent, label: bar.getAttribute("aria-label"), text: root.textContent.replace(NB, " ") };
}
/** The shared page for the same take, drawn by the viewer's renderer: {score, caption, grade, warnings, text}. */
function viewer(snap) {
  const page = new El("section");
  renderSnapshot(page, snap, model);
  const box = find(page, "shared-warning");
  return { score: find(page, "shared-score"), grade: find(page, "shared-grade"), caption: find(page, "shared-score-caption"),
    warningBox: box, text: page.textContent.replace(NB, " ") };
}

test("a capped take's headline is the capped score and grade, never the credit before the cap", () => {
  const h = headline(capped);
  assert.equal(h.score, "59");
  assert.equal(h.grade, "F");
  assert.equal(h.caption, "score out of 100");
  assert.equal(h.label, "Score 59 out of 100, grade F");
  // negative: neither the credit's figure, its scale nor its letter, nor the score before the cap, is in the headline
  for (const loose of ["9,087", "12,160", "74.7", "75%"]) assert.ok(!h.text.includes(loose), `headline shows ${loose}`);
  assert.notEqual(h.grade, "C");
  assert.notEqual(h.grade, "A");
  assert.ok(!/\b100\b/.test(`${h.score} ${h.label}`.replace("out of 100", "")), "the value before the cap is not the headline");
});

test("a capped take's share shows the same score, grade and warning as its result", () => {
  const h = headline(capped);
  const v = viewer(snapshot(capped));
  assert.equal(v.score.children[0].textContent, h.score);
  assert.equal(v.caption.textContent.trim(), h.caption);
  assert.equal(v.grade.textContent, `, grade ${h.grade}`);
  assert.equal(v.score.getAttribute("aria-label"), h.label);
  assert.equal(v.score.textContent, "59 score out of 100, grade F");
  const warned = resultWarnings(asShown(capped));
  assert.ok(v.warningBox, "the share carries the result's warning");
  assert.equal(v.warningBox.children[0].textContent, WARNING_TITLE);
  assert.equal(find(v.warningBox, "shared-warning-low_match").textContent, warned[0].text);
  assert.match(warned[0].text, /capped at F/);
  // negative: the uncapped credit, its letter and the value before the cap never reach the viewer
  for (const loose of ["9,087", "12,160", "grade C", "grade A", " 100 "]) assert.ok(!v.text.includes(loose), `viewer shows ${loose}`);
});

test("the owner's preview draws the same snapshot the same way (one renderer)", () => {
  const snap = snapshot(capped);
  const preview = viewer({ ...snap, clip: null, clip_included: false });
  assert.equal(preview.text, viewer(snap).text);
});

test("Part 7's caps win in the share too: a too-dark take shows the light cap and its warning", async () => {
  const { LIGHT_CAP, LIGHT_MAJOR_LABEL } = await import("../../web/light-result.js");
  const light = { level: "major" };
  const h = headline(credit, light);
  const v = viewer(snapshot(credit, light));
  assert.equal(h.score, String(LIGHT_CAP));
  assert.equal(h.grade, "F");
  assert.equal(v.score.textContent, `${LIGHT_CAP} score out of 100, grade F`);
  assert.equal(find(v.warningBox, "shared-warning-light_dark").textContent, LIGHT_MAJOR_LABEL);
  assert.ok(!v.text.includes("9,087"));
});

test("an uncapped take is unchanged: the credit headline in points, and the share says the same", () => {
  const h = headline(credit);
  assert.equal(h.score, "9,087");
  assert.equal(h.caption, "of 12,160");
  assert.equal(h.grade, "C");
  const v = viewer(snapshot(credit));
  assert.equal(v.score.textContent, "9,087 of 12,160, grade C");
  assert.equal(v.score.getAttribute("aria-label"), h.label);
  assert.equal(v.warningBox, null, "no warning on an unwarned take");
  const p = viewer(snapshot(plain));
  assert.equal(p.score.textContent, `${plain.score.value} average form, grade ${plain.score.grade}`);
  assert.equal(headline(plain).caption, "average form");
});

test("an old snapshot without the result block still renders as it always did", () => {
  const old = { kind: "take_result", title: "Squat", score: 0, grade: "F", faults: ["knees bent much more than the example"], on: "2026-11-02",
    include: { score: true, faults: true }, clip: false, author: null, expires_utc: "2026-11-09T10:00:00Z" };
  const v = viewer(old);
  assert.equal(v.score.textContent, "0 F");
  assert.equal(v.warningBox, null);
  assert.equal(v.grade, null);
  assert.match(v.text, /knees bent much more than the example/);
  const odd = viewer({ ...old, result: { score: "x" } });
  assert.equal(odd.score.textContent, "0 F", "a malformed block falls back to the old fields");
});

test("the owner's points or % choice: the share shows the unit the result showed, and a capped take ignores it", () => {
  const pct = { mode: "percent" };
  assert.deepEqual(shareModel.createBody({ kind: "take_result", itemRef: "j", scoreDisplay: { mode: "percent", level: "bogus" } }).score_display, pct);
  assert.equal("score_display" in shareModel.createBody({ kind: "history_report", itemRef: "e", scoreDisplay: pct }), false);
  assert.equal(shareModel.displayChoice({ mode: "x" }), null);
  const h = headline(credit, null, pct);
  const snap = snapshot(credit);
  const v = viewer({ ...snap, result: { ...snap.result, display: pct } });
  assert.equal(h.score, "75%");
  assert.equal(v.score.textContent, `75% ${h.caption}, grade ${h.grade}`);
  assert.equal(v.score.getAttribute("aria-label"), h.label);
  const c = snapshot(capped);
  assert.equal(viewer({ ...c, result: { ...c.result, display: pct } }).score.textContent, "59 score out of 100, grade F");
});
