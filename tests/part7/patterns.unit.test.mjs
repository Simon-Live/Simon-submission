// "Patterns across your takes": model (web/model/patterns.js). node --test tests/part7/patterns.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";

const M = await import("../../web/model/patterns.js");

test("the button needs 3 takes and the url is the entry's", () => {
  assert.equal(M.canFind(2), false);
  assert.equal(M.canFind(3), true);
  assert.equal(M.canFind(undefined), false);
  assert.equal(M.patternsUrl("body squat"), "api/me/history/body%20squat/patterns");
});

test("each status has a plain state", () => {
  for (const [s, k] of [[202, "waiting"], [401, "signedout"], [404, "missing"], [409, "consent"], [422, "few"], [429, "limit"], [500, "error"]]) {
    assert.equal(M.patternsState(s).kind, k);
    assert.ok(M.patternsState(s).message.length > 10);
  }
});

test("meter and receipt come from the stored numbers and never invent one", () => {
  assert.equal(M.meterText({ input_tokens: 12840, cached_tokens: 9000 }), "12,840 tokens read (1.2% of the window), 9,000 from cache.");
  assert.equal(M.meterText(null), "");
  assert.equal(M.meterText({ input_tokens: 0 }), "");
  assert.match(M.receiptText({ to: "Meta's model", keys: ["a", "b"], takes_full: 3, takes_digest: 2 }), /3 takes in full and 2 older takes as a short list \(2 fields\)\. No video/);
  assert.equal(M.receiptText(null), "");
});

test("the view keeps only cites with a take and a second, and links a clip only where one is kept", () => {
  const doc = { status: "ok", reach: { keys: [], takes_full: 2, takes_digest: 0 }, meter: { input_tokens: 10, cached_tokens: 0 }, patterns: [
    { kind: "recurs", measure: "knee_valgus", side: "left", text: "t", cites: [{ take: 1, at_s: 2 }, { take: 2 }, { at_s: 1 }, { take: 3, at_s: 1.5 }] }] };
  const vm = M.patternsView(doc, (n) => (n === 1 ? "clip1" : ""));
  assert.deepEqual(vm.patterns[0].cites.map((c) => [c.take, c.clip]), [[1, "clip1"], [3, ""]]);
  assert.equal(vm.patterns[0].label, "Knee valgus, left");
  assert.equal(vm.note, "");
  assert.equal(M.patternsView(null).hasResult, false);
});

test("a result without the model says so and keeps the reason short", () => {
  const vm = M.patternsView({ status: "fallback", reason: "HTTP 500 on responses", patterns: [{ kind: "recurs", source: "fact_table", cites: [] }] });
  assert.match(vm.note, /The model was not used \(HTTP 500 on responses\)/);
  assert.equal(vm.patterns[0].source, "fact_table");
  assert.equal(M.patternsView({ status: "ok", patterns: [] }).none, true);
});

test("a plain sentence from the server is shown whole, never wrapped in brackets (TICKET-330)", () => {
  const plain = "Simon could not get an answer from Muse Spark this time. Try again later.";
  const vm = M.patternsView({ status: "fallback", reason: plain, patterns: [] });
  assert.equal(vm.note, `${plain} This is the measured table in plain words.`);
  assert.doesNotMatch(vm.note, /HTTP|\(/);
});

test("the gate follows the server's group verdict, not the total take count", () => {
  const short = { takes: [1, 2, 3], patterns: { eligible: false, group_takes: 2, min_takes: 3, reason: "Patterns need at least 3 takes of the same section and mode of this movement." } };
  assert.equal(M.patternsGate(short).ok, false); // negative: 3 in total, 2 in the group
  assert.match(M.patternsGate(short).reason, /same section and mode/);
  assert.deepEqual(M.patternsGate({ takes: [1, 2, 3], patterns: { eligible: true, group_takes: 3 } }), { ok: true, reason: "" });
  assert.equal(M.patternsGate({ takes: [1, 2, 3] }).ok, true); // an older payload falls back to the total
  assert.equal(M.patternsGate({ takes: [1, 2] }).ok, false);
  assert.equal(M.patternsGate(null).ok, false);
});
