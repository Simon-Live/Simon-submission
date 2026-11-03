// TICKET-246 (docs/specs/heading-note.md): the camera angle hint on Follow and the rough-score note on the result.
//   node --test tests/part7/heading-note.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { installDom, El } from "./fake-dom.mjs";

installDom();
const { TEXT, ROUGH_DEG, FAR_DEG, headingOffset, headingLevel, mountHeadingNote, angleHint } = await import("../../web/heading-note.js");
const { withQualityCap } = await import("../../web/quality-cap.js");
const { isCapped, isWarningCapped, isLowMatch, withCapWinning } = await import("../../web/model/score-labels.js");

const take = (deg, reasons = []) => ({
  schema_version: "1.14.0",
  score: { value: 84, grade: "B" },
  quality: { version: "simon.quality.v1", level: reasons.length ? "degraded" : "ok", reasons, signals: { heading_offset_deg: deg }, score_cap: null },
});
const reason = (deg) => ({ code: "heading_offset", words: `The body was turned about ${Math.round(deg)} degrees from the way the example faces.`, value: deg, threshold: 5 });
const mounted = (analysis) => { const slot = new El("div"); mountHeadingNote(slot, { analysis }); return slot; };

test("the words are the agreed ones, with no dash", () => {
  assert.equal(TEXT.rough, "Filmed from a different angle than the trainer, so treat this score as rough.");
  for (const s of Object.values(TEXT)) assert.ok(!/[\u2013\u2014]| \x2d /.test(s), s);
  assert.equal(ROUGH_DEG, 5);
  assert.equal(FAR_DEG, 15);
});

test("AC-1: the follow screen line asks for the trainer's side and angle", () => {
  const p = angleHint();
  assert.equal(p.getAttribute("data-testid"), "angle-hint");
  assert.equal(p.textContent, "Film from the same side and angle as the trainer's video.");
});

test("AC-1: capture adds the line on Follow only (a reference is docked), under the framing hint", () => {
  const src = readFileSync(new URL("../../web/capture.js", import.meta.url), "utf8");
  assert.match(src, /if \(reference\) framing\.after\(angleHint\(\)\);/);
});

test("AC-2: over 5 degrees the result says the score is rough", () => {
  const slot = mounted(take(7.4, [reason(7.4)]));
  const note = slot.querySelector('[data-testid="heading-note"]');
  assert.equal(note.textContent, TEXT.rough);
  assert.equal(note.getAttribute("data-level"), "rough");
});

test("AC-2: Part 5's limit is at or above 5, so exactly 5.0 is rough", () => {
  assert.equal(headingLevel(take(5.0, [reason(5.0)])), "rough");
  assert.equal(headingLevel(take(4.9)), null);
});

test("AC-2: at or over 15 degrees the wording is stronger", () => {
  const note = mounted(take(17.1, [reason(17.1)])).querySelector('[data-testid="heading-note"]');
  assert.equal(note.textContent, TEXT.far);
  assert.equal(note.getAttribute("data-level"), "far");
});

test("AC-2: the reason alone (signal null) still gives the note", () => {
  const a = take(null, [reason(8)]);
  assert.equal(headingOffset(a), 8);
  assert.equal(headingLevel(a), "rough");
});

test("AC-3 negative: same angle, no note", () => {
  for (const a of [take(0.0), take(2.9), take(null), { score: { value: 90 } }, null, { quality: { level: "ok" } }]) {
    const slot = mounted(a);
    assert.equal(slot.children.length, 0);
    assert.equal(headingLevel(a), null);
  }
});

test("AC-2: a note, not a cap: the score is the same with or without the heading", () => {
  const far = take(41.5, [reason(41.5)]);
  assert.deepEqual(withQualityCap(far).score, { value: 84, grade: "B" });
  assert.deepEqual(withQualityCap(far).warnings, undefined);
  const shown = withQualityCap(far);
  assert.equal(isCapped(shown.score), false);
  assert.equal(isWarningCapped(shown.score), false);
  assert.equal(isLowMatch(shown), false);
  assert.deepEqual(withCapWinning(shown).score, withCapWinning(withQualityCap(take(0))).score);
});
