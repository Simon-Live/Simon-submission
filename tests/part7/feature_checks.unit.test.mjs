// Feature check discovery (tests/part7/feature_checks.mjs, re-exported by staging/feature-checks.mjs): sorted discovery, a broken module is a FAIL
// check, a throwing runChecks is a FAIL check, no files means nothing runs. Run:
//   node --test tests/part7/feature_checks.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { discoverFeatureChecks, runFeatureChecks } from "./feature_checks.mjs";

function tmpDir(files) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "feature-checks-"));
  for (const [name, body] of Object.entries(files)) fs.writeFileSync(path.join(dir, name), body);
  return dir;
}

function recorder() {
  const rec = { results: [], calls: [] };
  rec.runCheck = async (name, fn) => {
    try {
      rec.results.push({ name, pass: true, detail: await fn() });
      return true;
    } catch (err) {
      rec.results.push({ name, pass: false, detail: err.message });
      return false;
    }
  };
  return rec;
}

const ids = { entryId: "e1", followJobId: "j1" };

test("no checks files: nothing runs and no check is recorded", async () => {
  const dir = tmpDir({ "verify.mjs": "", "checks-notes.txt": "" });
  const rec = recorder();
  assert.deepEqual(await runFeatureChecks(dir, { runCheck: rec.runCheck, ...ids }), []);
  assert.deepEqual(rec.results, []);
});

test("modules run in sorted order with the context", async () => {
  const body = (lane) => `export async function runChecks(ctx) {
    await ctx.runCheck("${lane}-one", async () => ctx.entryId + ":" + ctx.followJobId + ":" + ctx.baseUrl);
  }`;
  const dir = tmpDir({ "checks-modes.mjs": body("modes"), "checks-coach.mjs": body("coach") });
  assert.deepEqual(discoverFeatureChecks(dir).map((d) => d.lane), ["coach", "modes"]);
  const rec = recorder();
  await runFeatureChecks(dir, { runCheck: rec.runCheck, baseUrl: "http://x/", ...ids });
  assert.deepEqual(rec.results.map((r) => r.name), ["checks-coach-import", "coach-one", "checks-modes-import", "modes-one"]);
  assert.equal(rec.results[1].detail, "e1:j1:http://x/");
});

test("a module that fails to import is a FAIL check and the others still run", async () => {
  const dir = tmpDir({
    "checks-breakdown.mjs": "export const x = ;",
    "checks-coach.mjs": "export async function runChecks(c) { await c.runCheck('coach-ok', async () => 'ok'); }",
    "checks-practice.mjs": "export const notRunChecks = 1;",
  });
  const rec = recorder();
  await runFeatureChecks(dir, { runCheck: rec.runCheck, ...ids });
  const by = Object.fromEntries(rec.results.map((r) => [r.name, r.pass]));
  assert.equal(by["checks-breakdown-import"], false);
  assert.equal(by["checks-practice-import"], false);
  assert.equal(by["checks-coach-import"], true);
  assert.equal(by["coach-ok"], true);
});

test("a runChecks that throws is recorded as a FAIL check", async () => {
  const dir = tmpDir({ "checks-challenge.mjs": "export async function runChecks() { throw new Error('boom'); }" });
  const rec = recorder();
  await runFeatureChecks(dir, { runCheck: rec.runCheck, ...ids });
  const run = rec.results.find((r) => r.name === "checks-challenge-run");
  assert.equal(run.pass, false);
  assert.equal(run.detail, "boom");
});

test("checks files with no follow job from the journey fail loudly instead of running", async () => {
  const dir = tmpDir({ "checks-coach.mjs": "export async function runChecks() { throw new Error('must not run'); }" });
  const rec = recorder();
  await runFeatureChecks(dir, { runCheck: rec.runCheck, entryId: null, followJobId: null });
  assert.deepEqual(rec.results.map((r) => [r.name, r.pass]), [["feature-checks-journey", false]]);
});
