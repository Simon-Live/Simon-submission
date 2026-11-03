// The GPU line on the job page (docs/specs/app.md "GPU wait on the job", TICKET-289).
//   node --test tests/part7/gpu-note.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { gpuText, GPU_WAIT, COLD_PATH } from "../../web/queue-eta.js";

const running = { status: "running", stage: "pose" };

test("a running job waiting for the GPU says so, whatever the reason class", () => {
  assert.equal(gpuText({ ...running, wait: { since: "2026-11-02T12:29:00Z", reason: "other GPU work" } }), GPU_WAIT);
  assert.equal(gpuText({ ...running, wait: { since: "2026-11-02T12:29:00Z", reason: "another take" } }), GPU_WAIT);
  assert.equal(GPU_WAIT, "Waiting for the graphics card. Another job is using it.");
});

test("the cold path shows during the 3D step only; a warm worker shows nothing", () => {
  assert.equal(gpuText({ ...running, worker: "cold", worker_reason: "restarting" }), COLD_PATH);
  assert.equal(COLD_PATH, "Running the slower path. This take will need more time.");
  assert.equal(gpuText({ ...running, stage: "skeleton", worker: "cold" }), "");
  assert.equal(gpuText({ ...running, worker: "warm" }), "");
});

test("no fields, a null wait or a finished job: no line (the negative)", () => {
  assert.equal(gpuText(running), "");
  assert.equal(gpuText({ ...running, wait: null, worker: null }), "");
  assert.equal(gpuText({ status: "done", stage: "pose", wait: { reason: "another take" }, worker: "cold" }), "");
  assert.equal(gpuText({ status: "queued", wait: { reason: "another take" } }), "");
  for (const s of [GPU_WAIT, COLD_PATH]) assert.doesNotMatch(s, new RegExp(`[${String.fromCharCode(0x2013, 0x2014)}]| - `));
});
