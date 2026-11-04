// A finished trainer job on the job page never heads for the result route (docs/specs/orphaned-take-result.md AC-O6): only a
// follow take does, and a trainer job's button opens its movement.
//   node --test tests/part7/job-trainer-route.dom.test.mjs
import test, { after } from "node:test";
import assert from "node:assert/strict";
import { mountJobPage } from "./job-dom.mjs";

const page = (job) => { location.hash = "#/job/abcdefabcdef"; return mountJobPage({ stage: null, stages: [], note: null, status: "done", ...job }); };

test("a done trainer job stays off the result route and its button opens the movement", async () => {
  const { find, stop } = await page({ kind: "trainer", entry_id: "squat-f7374065", result: { entry_id: "squat-f7374065" } });
  stop();
  assert.equal(location.hash, "#/job/abcdefabcdef");
  assert.equal(find("open").href ?? find("open").attrs?.href, "#/watch/squat-f7374065");
});

test("a done trainer job with its movement only in result still opens the movement", async () => {
  const { find, stop } = await page({ kind: "trainer", entry_id: null, result: { entry_id: "squat-f7374065" } });
  stop();
  assert.equal(location.hash, "#/job/abcdefabcdef");
  assert.equal(find("open").href ?? find("open").attrs?.href, "#/watch/squat-f7374065");
});

test("negative: a done follow take still goes to its result", async () => {
  const { stop } = await page({ kind: "follow", entry_id: "squat" });
  stop();
  assert.equal(location.hash, "#/result/abcdefabcdef");
});

after(() => { setTimeout(() => process.exit(process.exitCode || 0), 100); });
