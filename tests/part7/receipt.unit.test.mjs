// "What Simon sent" (docs/specs/history-receipt.md): model and view. node --test tests/part7/receipt.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, find } from "./fake-dom.mjs";

installDom();
const M = await import("../../web/model/receipt.js");
const V = await import("../../web/views/receipt.js");

const SENT = {
  feature: "compare", prompt_version: "history.v2", model: "muse-spark-1.3", store: false, file_expires_s: 3600,
  digest_takes: [1, 2, 3], clip_takes: [3, 1], fields: ["take", "score", "duration_s"], teacher_clip: true, video_consent: true,
  narration_cues: 4, est_input_tokens: 5000, settled: true, input_tokens: 5200, cached_tokens: 1000, output_tokens: 300, usd: 0.0123,
};
const rowOf = (vm, key) => (vm.rows.find((r) => r.key === key) || {}).value;

test("the rows name the takes, clips, tokens and cost", () => {
  const vm = M.receiptView(SENT);
  assert.equal(vm.summary, "What Simon sent: 3 takes, 2 clips");
  assert.equal(rowOf(vm, "takes"), "Take 1, Take 2, Take 3");
  assert.equal(rowOf(vm, "clips"), "Take 1, Take 3");
  assert.match(rowOf(vm, "model"), /Meta's Muse Spark/);
  assert.equal(rowOf(vm, "tokens"), "5,200");
  assert.equal(rowOf(vm, "cost"), "$0.0123");
  assert.equal(rowOf(vm, "fields"), "take, score, duration");
  assert.equal(rowOf(vm, "narration"), "4 lines of text");
});

test("an Ask receipt names each take by movement and the number its take page uses", () => {
  const vm = M.receiptView({ ...SENT, digest_takes: [1, 2, 3], digest_cites: [["Lunge", 1], ["Squat", 1], ["Squat", 2]], clip_takes: [], teacher_clip: false });
  assert.equal(rowOf(vm, "takes"), "Lunge, take 1; Squat, take 1; Squat, take 2");
  assert.ok(!/Take 3/.test(rowOf(vm, "takes")));  // the number across movements never shows
});

test("no clips and video off still lists the digests", () => {
  const vm = M.receiptView({ ...SENT, clip_takes: [], teacher_clip: false, video_consent: false, narration_cues: 0 });
  assert.equal(rowOf(vm, "clips"), "no clips (video is off)");
  assert.equal(rowOf(vm, "takes"), "Take 1, Take 2, Take 3");
  assert.equal(rowOf(vm, "expires"), undefined);
});

test("an unsettled block shows an estimate and an unknown cost", () => {
  const vm = M.receiptView({ ...SENT, settled: false, input_tokens: undefined, usd: undefined });
  assert.equal(rowOf(vm, "tokens"), "5,000");
  assert.equal(rowOf(vm, "cost"), "not known");
});

test("cost text and missing blocks", () => {
  assert.equal(M.costText(0.00001), "less than $0.0001");
  assert.equal(M.costText(0), "$0");
  assert.equal(M.costText(null), "");
  assert.equal(M.receiptView(null), null);
  assert.equal(M.receiptView("x"), null);
});

test("the run note names Meta", () => {
  assert.match(M.RUN_NOTE, /Meta/);
});

test("the view is a closed fold-out with one row per line, and null without a block", () => {
  assert.equal(V.renderReceipt(null), null);
  const el = V.renderReceipt(M.receiptView(SENT), { testid: "r1" });
  assert.equal(el.tag, "details");
  assert.ok(find(el, "r1-summary"));
  assert.equal(find(el, "r1-cost").textContent, "$0.0123");
  assert.ok(!("open" in (el.attrs || {})));
});

test("the receipt counts trainer notes and never shows their text", () => {
  const vm = M.receiptView({ ...SENT, notes_sent: 2, notes: [{ note: "secret words" }] });
  assert.equal(rowOf(vm, "notes"), "2 trainer notes");
  assert.equal(JSON.stringify(vm).includes("secret words"), false);
  assert.equal(rowOf(M.receiptView({ ...SENT, notes_sent: 1 }), "notes"), "1 trainer note");
  assert.equal(rowOf(M.receiptView({ ...SENT, notes_sent: 0 }), "notes"), undefined);
});
