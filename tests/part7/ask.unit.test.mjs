// "Ask my history" model (docs/specs/history-ask.md): question check, status words, the answer view model and the receipt.
//   node --test tests/part7/ask.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { QUESTION_MAX, answerView, citeLabel, droppedLine, questionError, receiptLine, stateForStatus } from "../../web/model/ask.js";

const BODY = {
  status: "ok", text: "Trunk lean forward is new in take 2.", dropped: 2, message: "",
  claims: [{ kind: "trend", text: "Trunk lean forward shows in take 2 at 1 s.", cites: [{ take: 2, at_s: 1, clip: "api/me/history/e/takes/j/clip.mp4" }, { take: 1, at_s: null, clip: null }] }],
  reach: { takes: 2, movements: 1, left_out: 0, video: false },
  usage: { input_tokens: 20000, cached_tokens: 10000, output_tokens: 500, usd: 0.016 },
};

test("the question is checked before it is sent", () => {
  assert.equal(questionError(""), "Type a question first.");
  assert.equal(questionError("   "), "Type a question first.");
  assert.match(questionError("x".repeat(QUESTION_MAX + 1)), /under 200 characters/);
  assert.equal(questionError("is my score up?"), "");
});

test("each status maps to a state, and the server's words win", () => {
  assert.equal(stateForStatus(401).kind, "signedout");
  assert.equal(stateForStatus(409).kind, "consent");
  assert.equal(stateForStatus(409, { message: "Simon is answering another question." }).message, "Simon is answering another question.");
  assert.equal(stateForStatus(422).kind, "few");
  assert.equal(stateForStatus(500).kind, "error");
});

test("a cite names the movement and its own take number, never the number across movements", () => {
  assert.equal(citeLabel({ movement: "Squat", take: 16, at_s: 2 }), "Squat, take 16 · 2 s");
  assert.equal(citeLabel({ movement: "Squat", take: 16, at_s: null }), "Squat, take 16");
  const v = answerView({ status: "ok", claims: [{ kind: "trend", text: "t", cites: [{ ref: 31, movement: "Squat", take: 16, at_s: 2, clip: "c.mp4" }] }] });
  assert.deepEqual(v.claims[0].cites.map((c) => [c.label, c.take]), [["Squat, take 16 · 2 s", 16]]);
  assert.ok(!v.claims[0].cites[0].label.includes("31"));
});

test("cite labels name the take and the second", () => {
  assert.equal(citeLabel({ take: 2, at_s: 1 }), "Take 2 · 1 s");
  assert.equal(citeLabel({ take: 3, at_s: 2.14 }), "Take 3 · 2.1 s");
  assert.equal(citeLabel({ take: 1, at_s: null }), "Take 1");
});

test("an answer view keeps the claims, the cites, the dropped count and the receipt", () => {
  const v = answerView(BODY);
  assert.equal(v.kind, "ok");
  assert.equal(v.lead, BODY.text);
  assert.deepEqual(v.claims[0].cites.map((c) => [c.label, c.clip !== null]), [["Take 2 · 1 s", true], ["Take 1", false]]);
  assert.equal(v.dropped, "Simon could not check this (2 left out).");
  assert.match(v.receipt, /2 takes of 1 movement as text, with no video/);
  assert.match(v.receipt, /20,000 tokens in, 10,000 of them cached, 500 out\./);
});

test("no dropped claims means no dropped line, and nothing is invented for a missing field", () => {
  assert.equal(droppedLine(0), "");
  const v = answerView({ status: "abstain", message: "Your takes do not mention tempo." });
  assert.deepEqual([v.kind, v.message, v.claims, v.dropped, v.receipt], ["abstain", "Your takes do not mention tempo.", [], "", ""]);
  assert.equal(answerView(null).kind, "failed");
  assert.equal(receiptLine({ reach: { takes: 5, movements: 2, left_out: 1 } }), "Simon read 5 takes of 2 movements as text, with no video, and sent them to Meta's model. 1 older take left out to fit the limit.");
});

test("user strings hold no em dash, en dash or spaced hyphen", () => {
  for (const f of ["web/model/ask.js", "web/views/ask.js"]) {
    const text = fs.readFileSync(new URL(`../../${f}`, import.meta.url), "utf8");
    assert.doesNotMatch(text, /[\u2013\u2014]/);
  }
});

test("each server code maps to its own state; busy never shows the consent text", () => {
  const consent = stateForStatus(409, { code: "consent_required" });
  assert.equal(consent.kind, "consent");
  assert.match(consent.message, /keep your takes/);
  const busy = stateForStatus(409, { code: "busy", retry_after: 5 });
  assert.equal(busy.kind, "busy");
  assert.match(busy.message, /still answering/);
  assert.doesNotMatch(busy.message, /keep your takes|keeping takes/); // negative
  assert.doesNotMatch(stateForStatus(409, { code: "busy" }).message, /account/);
  const forbidden = stateForStatus(403, { code: "forbidden_origin" });
  assert.equal(forbidden.kind, "error");
  assert.match(forbidden.message, /another site/);
  assert.notEqual(forbidden.message, stateForStatus(500).message); // not the generic line
  assert.equal(stateForStatus(422, { code: "too_few_takes" }).kind, "few");
  assert.equal(stateForStatus(400, { code: "invalid_question" }).kind, "error");
  assert.equal(stateForStatus(403).kind, "error"); // no body: still not the generic line
  assert.match(stateForStatus(403).message, /another site/);
});
