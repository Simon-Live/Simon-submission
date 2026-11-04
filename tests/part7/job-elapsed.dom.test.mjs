// The job page's elapsed time stops at the job's real duration (docs/specs/app.md "Job page elapsed time", AC-JOB-ELAPSED).
//   node --test tests/part7/job-elapsed.dom.test.mjs
import test, { after } from "node:test";
import assert from "node:assert/strict";
import { mountJobPage, settle } from "./job-dom.mjs";

const iso = (msAgo) => new Date(Date.now() - msAgo).toISOString();

async function open(job) {
  const { stop, find } = await mountJobPage({ kind: "follow", stage: null, stages: [], note: null, ...job });
  return { stop, text: () => find("progress-elapsed").textContent };
}

for (const status of ["done", "failed"]) {
  test(`AC-JOB-ELAPSED: ${status} shows finished_at minus started_at, not the time since`, async () => {
    const { text, stop } = await open({ status, started_at: iso(600_000), finished_at: iso(300_000) });
    stop();
    assert.equal(text(), "Elapsed 5:00");
  });
}

test("AC-JOB-ELAPSED: the counter does not move after the terminal status", async () => {
  const { text, stop } = await open({ status: "done", started_at: iso(60_000), finished_at: iso(30_000) });
  const first = text();
  await settle(1300);
  stop();
  assert.equal(text(), first);
  assert.equal(first, "Elapsed 0:30");
});

test("AC-JOB-ELAPSED: a running job still counts from its start", async () => {
  const { text, stop } = await open({ status: "running", started_at: iso(65_000), finished_at: null });
  stop();
  assert.match(text(), /^Elapsed 1:0[5-9]$/);
});

// the failed page mounts "Send it again", whose pending engine keeps a handle open; end the process once the tests are done
after(() => { setTimeout(() => process.exit(process.exitCode || 0), 100); });
