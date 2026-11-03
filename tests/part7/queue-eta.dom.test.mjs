// The job page's wait line with and without `eta_s` (docs/specs/app.md "Wait estimate", TICKET-288): mountJob from
// web/job.js on the fake DOM, fed one job answer per test.
//   node --test tests/part7/queue-eta.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El, find } from "./fake-dom.mjs";

installDom();
// what the progress bar touches beyond fake-dom: an inline style and a class list per element
Object.defineProperty(El.prototype, "style", { get() { return (this._style ||= { setProperty() {} }); } });
Object.defineProperty(El.prototype, "classList", { get() { return (this._cl ||= { add() {}, remove() {}, toggle() {}, contains: () => false }); } });
let answer = {};
globalThis.location = { hash: "" };
globalThis.fetch = async (url) => {
  const body = String(url).includes("api/jobs/") ? answer : {};
  return { ok: true, status: 200, json: async () => body, headers: { get: () => null } };
};
const { mountJob } = await import("../../web/job.js");
const settle = () => new Promise((r) => setTimeout(r, 30));

async function show(job) {
  answer = { id: "abcdefabcdef", kind: "follow", stage: null, stages: [], note: null, ...job };
  const root = new El("div");
  const stop = mountJob(root, "abcdefabcdef");
  await settle();
  stop();
  return { queue: find(root, "queue"), left: find(root, "eta-left") };
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
  answer = { id: "abcdefabcdef", kind: "follow", stage: "pose", stages: [], note: null, status: "running", eta_s: 240, eta_basis: { late: false } };
  const root = new El("div");
  const stop = mountJob(root, "abcdefabcdef");
  await settle();
  stop();
  assert.equal(find(root, "eta-left").textContent, "About 3 to 5 minutes left.");
  assert.doesNotMatch(find(root, "stage-detail").textContent, /Usually/);
  assert.equal(find(root, "stages").getAttribute("data-eta"), "shown");
});

test("negative: without eta_s the static hint stays", async () => {
  answer = { id: "abcdefabcdef", kind: "follow", stage: "pose", stages: [], note: null, status: "running" };
  const root = new El("div");
  const stop = mountJob(root, "abcdefabcdef");
  await settle();
  stop();
  assert.equal(find(root, "eta-left").hidden, true);
  assert.match(find(root, "stage-detail").textContent, /Usually about/);
  assert.equal(find(root, "stages").getAttribute("data-eta"), "none");
});
