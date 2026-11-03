// The GPU line under the step line on the job page (docs/specs/app.md "GPU wait on the job", TICKET-289): mountJob
// from web/job.js on the fake DOM, fed one job answer per test.
//   node --test tests/part7/gpu-note.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El, find } from "./fake-dom.mjs";

installDom();
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
  answer = { id: "abcdefabcdef", kind: "follow", stages: [], note: null, queue_position: null, ...job };
  const root = new El("div");
  const stop = mountJob(root, "abcdefabcdef");
  await settle();
  stop();
  return { gpu: find(root, "gpu-note"), detail: find(root, "stage-detail"), note: find(root, "job-note") };
}

test("waiting for the GPU: the line shows under the step line", async () => {
  const { gpu } = await show({ status: "running", stage: "pose", wait: { since: "2026-11-02T12:29:00Z", reason: "other GPU work" } });
  assert.equal(gpu.hidden, false);
  assert.equal(gpu.textContent, "Waiting for the graphics card. Another job is using it.");
});

test("the cold path: the slower path line", async () => {
  const { gpu } = await show({ status: "running", stage: "pose", worker: "cold", worker_reason: "restarting" });
  assert.equal(gpu.hidden, false);
  assert.equal(gpu.textContent, "Running the slower path. This take will need more time.");
});

test("fields absent: no GPU line and the old wording exactly (the negative)", async () => {
  const plain = await show({ status: "running", stage: "pose" });
  assert.equal(plain.gpu.hidden, true);
  assert.equal(plain.gpu.textContent, "");
  assert.equal(plain.note.textContent, "This takes a few minutes. You can leave this page open or come back to it.");
  assert.match(plain.detail.textContent, /^Reading where the joints are in every frame\. This is the longest step\./);
  const warm = await show({ status: "running", stage: "pose", worker: "warm", wait: null });
  assert.equal(warm.gpu.hidden, true);
  assert.equal(warm.detail.textContent, plain.detail.textContent);
  assert.equal(warm.note.textContent, plain.note.textContent);
});
