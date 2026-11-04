// The job page's wait line with and without `eta_s` (docs/specs/app.md "Wait estimate", TICKET-288): mountJob from
// web/job.js on the fake DOM, fed one job answer per test.
//   node --test tests/part7/queue-eta.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { mountJobPage } from "./job-dom.mjs";

const BASE = { kind: "follow", stage: null, stages: [], note: null };

async function show(job) {
  const { stop, find } = await mountJobPage({ ...BASE, ...job });
  stop();
  return { queue: find("queue"), left: find("eta-left") };
}

test("queued without eta_s: exactly the old line and no time left", async () => {
  const { queue, left } = await show({ status: "queued", queue_position: 3 });
  assert.equal(queue.textContent, "Place in line: 3. Your turn comes when the ones before finish.");
  assert.doesNotMatch(queue.textContent, /About|minute/);
  assert.equal(left.hidden, true);
  assert.equal(left.textContent, "");
});

test("queued with eta_s: the place and a range of minutes", async () => {
  const { queue, left } = await show({ status: "queued", queue_position: 3, eta_s: 900, eta_basis: { late: false } });
  assert.equal(queue.textContent, "Place in line: 3. About 12 to 20 minutes.");
  assert.equal(left.hidden, true);
});

test("running with eta_s: the time left; past the estimate: longer than usual", async () => {
  let { queue, left } = await show({ status: "running", stage: "pose", queue_position: null, eta_s: 240, eta_basis: { late: false } });
  assert.equal(left.textContent, "About 3 to 5 minutes left.");
  assert.equal(left.hidden, false);
  assert.equal(queue.textContent, "");
  ({ left } = await show({ status: "running", stage: "pose", queue_position: null, eta_s: 30, eta_basis: { late: true } }));
  assert.equal(left.textContent, "Taking longer than usual.");
  assert.doesNotMatch(left.textContent, /-|\b0 minutes/);
});

// TICKET-316: the page never shows two different times
test("a measured time on screen removes the static 'Usually about' hint", async () => {
  const { stop, find } = await mountJobPage({ ...BASE, stage: "pose", status: "running", eta_s: 240, eta_basis: { late: false } });
  stop();
  assert.equal(find("eta-left").textContent, "About 3 to 5 minutes left.");
  assert.doesNotMatch(find("stage-detail").textContent, /Usually/);
  assert.equal(find("stages").getAttribute("data-eta"), "shown");
});

test("negative: without eta_s the static hint stays", async () => {
  const { stop, find } = await mountJobPage({ ...BASE, stage: "pose", status: "running" });
  stop();
  assert.equal(find("eta-left").hidden, true);
  assert.match(find("stage-detail").textContent, /Usually about/);
  assert.equal(find("stages").getAttribute("data-eta"), "none");
});
