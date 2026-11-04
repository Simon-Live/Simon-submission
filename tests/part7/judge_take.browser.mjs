// The judge's take in 60 s (docs/specs/judge-take.md, TICKET-260), driven on Follow against tests/part7/fake_api.py:
// under ?profile=submission the capture defaults to a 6 s Quick take after 3 s, a one-person clip goes from the trim
// straight to the analysis (no picker, no details step), and the result shows the measured stage split. Negatives: a
// two-person clip still shows the picker, the default profile keeps the details step, an old job says "Timing not
// recorded". Signed out and signed in, no console errors. The consent step is on, as in prod and on staging, and answered
// through the screen: the check before a send then answers later, which is the path a judge's take runs.
//   PLAYWRIGHT_DIR=<node_modules> /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/judge_take.browser.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { answerConsentStep } from "../../staging/consent-step.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"))("playwright");
const port = await new Promise((resolve) => {
  const probe = net.createServer().listen(0, "127.0.0.1", () => { const p = probe.address().port; probe.close(() => resolve(p)); });
});
const base = `http://127.0.0.1:${port}/`;
const server = spawn("python3", [path.join(here, "fake_api.py"), String(port)], { stdio: "ignore" });
for (let i = 0; i < 100; i++) {
  if (server.exitCode !== null) throw new Error(`fake_api.py exited ${server.exitCode}`);
  try { if ((await fetch(`${base}api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 100)); }
}
const clip = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "judge-take-")), "take.webm");
fs.writeFileSync(clip, Buffer.from(await (await fetch(`${base}catalog/api/entries/lateral-raise/video.webm`)).arrayBuffer()));
const post = (route, body) => fetch(`${base}${route}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
const state = async () => (await fetch(`${base}__test/state`)).json();
const person = (id, coverage = 0.95) => ({ id, coverage, frames: 40, box_mid: [1, 1, 5, 5] });

const browser = await chromium.launch({ args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] });
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };

async function open(query, signedIn, gated = true) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 } });
  ctx.setDefaultTimeout(20000);
  await ctx.route(/api\/auth\/me$/, (route) => route.fulfill({ contentType: "application/json",
    body: JSON.stringify({ available: true, signed_in: signedIn, ...(signedIn ? { email: "judge@example.com", user_id: "u-judge" } : {}) }) }));
  if (gated) await ctx.route(/api\/policy$/, async (route) => {
    const doc = await (await route.fetch()).json();
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ ...doc, consent: { ...doc.consent, required: true, version: "test" } }) });
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  // a 404 shows in the console as "Failed to load resource": fake_api.py lacks routes the app expects to miss (per-job
  // result files, labels, signed-in history and notes, the people
  // pictures). A failure on a route this flow uses is an error here.
  page.on("console", (m) => { if (m.type() === "error" && !/^Failed to load resource/.test(m.text())) errors.push(m.text()); });
  page.on("response", (r) => { if (r.status() >= 400 && /\/api\/(ghost|jobs|follow|people|uploads|config)\b/.test(r.url()) && !/\.jpg$/.test(r.url())) errors.push(`${r.status()} ${r.url()}`); });
  await page.goto(`${base}${query}#/follow/lateral-raise`);
  if (gated) await answerConsentStep(page);
  await page.getByTestId("upload").waitFor({ state: "attached" });
  return { ctx, page, errors };
}

async function uploadAndTrim(page) {
  await page.getByTestId("upload").setInputFiles(clip);
  await page.locator('[data-testid="trim"][data-thumbs]').waitFor({ state: "attached" });
  await page.getByTestId("trim-continue").click();
}

try {
  for (const signedIn of [false, true]) {
    const who = signedIn ? "signed in" : "signed out";
    await post("__test/reset", {});
    const { ctx, page, errors } = await open("?profile=submission", signedIn);
    assert.equal(await page.getByTestId("quick-take").isVisible(), true);
    assert.equal(await page.getByTestId("quick-take").textContent(), "Quick take: 6 seconds after a 3 second countdown.");
    assert.equal(await page.getByTestId("countdown-select").inputValue(), "3");
    assert.equal(await page.getByTestId("duration-select").inputValue(), "6");
    ok(`${who}: AC-3 the submission profile opens on a 6 s Quick take after 3 s`);

    await uploadAndTrim(page);
    await page.waitForURL(/#\/job\/job1$/);
    const jobs = (await state()).jobs;
    assert.equal(jobs.job1.kind, "follow");
    assert.equal(String(jobs.job1.person_id), "0", "the one person was sent as the choice");
    assert.equal(jobs.job1.entry_id, "lateral-raise");
    ok(`${who}: AC-1 one person in the clip: the analysis starts with no picker and no details tap`);

    const split = page.getByTestId("stage-split");
    await split.waitFor({ state: "attached", timeout: 30000 });
    assert.equal(await split.isVisible(), false, "negative: the split waits in the closed \"i\" panel");
    await page.getByTestId("stage-made").click(); // the stage's "i" pill opens "How this was made" with the split
    await split.waitFor({ timeout: 10000 });
    assert.equal(await split.getAttribute("data-recorded"), "true");
    assert.equal(await page.getByTestId("split-picker").textContent(), "Person picker skipped");
    assert.match(await page.getByTestId("split-stage-pose").textContent(), /Pose\s*33\.1 s/);
    assert.match(await page.getByTestId("split-total").textContent(), /41\.2 s/);
    assert.equal(await page.getByTestId("stage-split").count(), 1, "one strip per job");
    assert.deepEqual(errors, [], `${who}: no console errors`);
    ok(`${who}: AC-4 the result shows the measured split from the job's timing`);
    await ctx.close();
  }

  // AC-1 with no consent step (a server outside prod and staging): the check before a send answers at once and the job still goes
  await post("__test/reset", {});
  {
    const { ctx, page, errors } = await open("?profile=submission", false, false);
    await uploadAndTrim(page);
    await page.waitForURL(/#\/job\/job1$/);
    assert.equal((await state()).jobs.job1.kind, "follow");
    assert.deepEqual(errors, []);
    ok("AC-1 with no consent step: one person, the analysis starts by itself");
    await ctx.close();
  }

  // AC-2 negative: two people still show the picker under the submission profile, and nothing starts by itself
  await post("__test/reset", {});
  await post("__test/people", { people: [person("0"), person("1")], auto_id: null });
  {
    const { ctx, page, errors } = await open("?profile=submission", false);
    await uploadAndTrim(page);
    await page.getByTestId("person-1").waitFor();
    assert.equal(await page.getByTestId("people-continue").isVisible(), true);
    await page.waitForTimeout(800);
    assert.deepEqual((await state()).jobs, {}, "negative: no follow job before a person is chosen");
    assert.deepEqual(errors, []);
    ok("AC-2 two people: the picker shows and no job starts by itself");
    await ctx.close();
  }

  // the default profile keeps the details step for a one-person clip, and the 5 s / 15 s defaults
  await post("__test/reset", {});
  {
    const { ctx, page, errors } = await open("?profile=default", false);
    assert.equal(await page.getByTestId("quick-take").isHidden(), true);
    assert.equal(await page.getByTestId("duration-select").inputValue(), "15");
    await uploadAndTrim(page);
    await page.getByTestId("analyse").waitFor();
    await page.waitForTimeout(800);
    assert.deepEqual((await state()).jobs, {}, "negative: the default profile waits for Analyse my take");
    assert.deepEqual(errors, []);
    ok("default profile: no Quick take, and the details step stays");
    await ctx.close();
  }

  // AC-4 negative: an old job without a summary says so, never zeros
  await post("__test/reset", {});
  await post("__test/timing", { recorded: false });
  {
    const { ctx, page, errors } = await open("?profile=submission", false);
    await uploadAndTrim(page);
    await page.waitForURL(/#\/job\/job1$/);
    const split = page.getByTestId("stage-split");
    await split.waitFor({ state: "attached", timeout: 30000 });
    assert.equal(await split.isVisible(), false, "negative: the split waits in the closed \"i\" panel");
    await page.getByTestId("stage-made").click(); // the stage's "i" pill opens "How this was made" with the split
    await split.waitFor({ timeout: 10000 });
    assert.equal(await split.getAttribute("data-recorded"), "false");
    assert.equal((await page.getByTestId("split-none").textContent()).trim(), "Timing not recorded");
    assert.equal(await page.locator('[data-testid^="split-stage-"]').count(), 0, "negative: no stage rows, no zeros");
    assert.deepEqual(errors, []);
    ok("AC-4 an old job: 'Timing not recorded', no stage rows");
    await ctx.close();
  }
  console.log(`${passed} judge-take browser checks passed`);
} finally {
  await browser.close();
  server.kill();
}
