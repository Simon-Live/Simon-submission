// The rough wait wording on the job page (docs/specs/app.md "Wait estimate", TICKET-288).
//   node --test tests/part7/queue-eta.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { minutesRange, queueText, leftText, PLAIN_QUEUE, LATE } from "../../web/queue-eta.js";

test("a range of whole minutes from 0.8 to 1.3 times the estimate", () => {
  assert.equal(minutesRange(840), "11 to 18 minutes");
  assert.equal(minutesRange(60), "1 minute"); // both ends round to 1: one figure, no range
  assert.equal(minutesRange(240), "3 to 5 minutes");
  assert.equal(minutesRange(20), "1 minute"); // never "0 minutes"
});

test("a queued job with eta_s shows its place and the range", () => {
  assert.equal(queueText({ status: "queued", queue_position: 3, eta_s: 900 }), "Place in line: 3. About 12 to 20 minutes.");
});

test("without eta_s the queued line is exactly the old one", () => {
  const old = "Place in line: 3. Your turn comes when the ones before finish.";
  assert.equal(queueText({ status: "queued", queue_position: 3 }), old);
  assert.equal(queueText({ status: "queued", queue_position: 3, eta_s: null }), old);
  assert.equal(queueText({ status: "queued", queue_position: 3, eta_s: 0 }), old);
  assert.ok(old.endsWith(PLAIN_QUEUE));
});

test("a running job shows the time left, or that it takes longer than usual", () => {
  assert.equal(leftText({ status: "running", eta_s: 240, eta_basis: { late: false } }), "About 3 to 5 minutes left.");
  assert.equal(leftText({ status: "running", eta_s: 30, eta_basis: { late: true } }), LATE);
  assert.equal(leftText({ status: "running", eta_s: -5 }), LATE);
  assert.equal(leftText({ status: "running" }), "");
  assert.equal(leftText({ status: "queued", eta_s: 240 }), "");
  assert.equal(leftText({ status: "done", eta_s: 240 }), "");
});
