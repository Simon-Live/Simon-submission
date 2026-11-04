// The GPU line under the step line on the job page (docs/specs/app.md "GPU wait on the job", TICKET-289): mountJob
// from web/job.js on the fake DOM, fed one job answer per test.
//   node --test tests/part7/gpu-note.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { mountJobPage } from "./job-dom.mjs";

async function show(job) {
  const { stop, find } = await mountJobPage({ kind: "follow", stages: [], note: null, queue_position: null, ...job });
  stop();
  return { gpu: find("gpu-note"), detail: find("stage-detail"), note: find("job-note") };
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
