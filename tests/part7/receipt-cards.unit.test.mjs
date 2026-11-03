// "What Simon sent" on every model card (docs/specs/history-receipt.md): patterns, ask, reel, across and recap.
// node --test tests/part7/receipt-cards.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { El, installDom, find } from "./fake-dom.mjs";

installDom();
const patterns = await import("../../web/model/patterns.js");
const patternsView = await import("../../web/views/patterns.js");
const ask = await import("../../web/model/ask.js");
const askView = await import("../../web/views/ask.js");
const reel = await import("../../web/model/reel.js");
const reelView = await import("../../web/views/reel.js");
const recap = await import("../../web/model/recap.js");
const recapView = await import("../../web/views/recap.js");

const sent = (feature) => ({
  feature, prompt_version: "x.v1", model: "muse-spark-1.3", store: false, file_expires_s: 3600, digest_takes: [1, 2, 3], clip_takes: [],
  fields: ["score"], teacher_clip: false, video_consent: false, narration_cues: 0, est_input_tokens: 900, settled: true,
  input_tokens: 900, cached_tokens: 0, output_tokens: 50, usd: 0.001,
});
const area = () => new El("div");

test("patterns card draws the receipt when the result carries one, and not for the table-only result", () => {
  const withSent = area();
  patternsView.renderPatternResult(withSent, patterns.patternsView({ status: "ok", patterns: [], sent: sent("pattern") }), { open() {} });
  assert.match(find(withSent, "patterns-sent-summary").textContent, /What Simon sent: 3 takes, no clips/);
  const none = area();
  patternsView.renderPatternResult(none, patterns.patternsView({ status: "fallback", reason: "x", patterns: [], sent: null }), { open() {} });
  assert.equal(find(none, "patterns-sent"), null); // negative: no model call, no receipt
});

test("ask answer draws the receipt; a refusal without a call draws none", () => {
  const host = area();
  const ui = askView.renderAsk(host, { maxChars: 200, suggestions: [], remaining: 5 }, { ask() {} });
  ui.answer(ask.answerView({ status: "ok", text: "t", claims: [], sent: sent("ask"), reach: { takes: 3, movements: 1, left_out: 0 } }));
  assert.ok(find(host, "ask-sent"));
  ui.answer(ask.answerView({ status: "refused", message: "No." }));
  assert.equal(find(host, "ask-sent"), null);
});

test("reel card draws the receipt", () => {
  const card = reelView.renderReelCard(reel.reelPanel({ consent: { video: true }, takes: [{ clip: "a" }, { clip: "b" }] }), { onMake() {} }, { open() {} });
  const doc = { status: "ok", seconds: 5, watched: [1, 2], video_url: "r.mp4", moments: [{ take: 1, at_s: 1, text: "m", role: "first" }], sent: { ...sent("reel"), clip_takes: [1, 2] } };
  card.show(reel.reelView(doc, "e"));
  assert.match(find(card.el, "reel-sent-summary").textContent, /3 takes, 2 clips/);
  card.show(reel.reelView({ ...doc, sent: undefined }, "e"));
  assert.equal(find(card.el, "reel-sent"), null);
});

test("across and recap model parts draw the receipt; a recap with no model call draws none", () => {
  const model = { status: "ok", entries: [{ entry_id: "a", name: "Squat" }], observations: [], next_focus: null, sent: sent("cross") };
  for (const [render, prefix] of [[recapView.renderAcross, "across"], [recapView.renderRecap, "recap"]]) {
    const screen = area();
    screen.classList = { add() {} };
    const append = screen.append.bind(screen);
    screen.append = (...kids) => append(...kids.filter(Boolean)); // the browser's append(null) is a "null" text; the fake DOM throws
    const vm = prefix === "across" ? recap.acrossView({ entries: [], table: [] }) : recap.recapView({ recap: { takes: 5, month: "2026-10", entries: [], movements: [] }, model_state: "none" });
    const handles = render(screen, vm, { onRun() {}, onLeaveOut() {} });
    handles.model(recap.modelView(model));
    assert.ok(find(screen, `${prefix}-sent`), prefix);
    handles.model(recap.modelView({ ...model, sent: undefined }));
    assert.equal(find(screen, `${prefix}-sent`), null, `${prefix} without a call`);
  }
  assert.equal(recap.modelView(null), null);
});

test("an older stored result without a built block shows no receipt", () => {
  assert.equal(patterns.patternsView({ status: "ok", patterns: [], sent: { to: "Meta", keys: [], takes_full: 2 } }).sent, null);
});
