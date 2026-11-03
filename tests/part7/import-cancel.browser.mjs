// docs/specs/model-picker.md AC-P14 and TICKET-286: the "Import a model" dialog always has a way out. In the real app
// (tests/part7/real_app.py: the real api/models routes, no GPU, so a photo stays queued) on the Me page (#/me), at
// 1728x925 and at 390x844, Cancel is clicked in every state: idle, file chosen, uploading, waiting, error, failed
// conversion. Escape and a backdrop click close it too. Negative assertions: after Cancel the dialog is not in the DOM,
// no model is left on the server (GET api/models) and no poll for the cancelled model follows.
//   PLAYWRIGHT_DIR=<node_modules> scripts/with-browser-slot.sh node tests/part7/import-cancel.browser.mjs [--case waiting]
// Screenshots: SHOTS_DIR (default a temp folder).
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const SHOTS = process.env.SHOTS_DIR || fs.mkdtempSync(path.join(os.tmpdir(), "import-cancel-"));
fs.mkdirSync(SHOTS, { recursive: true });
const only = process.argv.includes("--case") ? process.argv[process.argv.indexOf("--case") + 1] : null;

const PORT = 7700 + Math.floor(Math.random() * 90);
const HELPER = PORT + 100;
const BASE = `http://127.0.0.1:${PORT}/simon-part-7`;
const app = spawn("python3", [path.join(here, "real_app.py"), String(PORT), String(HELPER)], { stdio: "inherit" });
for (let i = 0; i < 100; i++) {
  try { if ((await fetch(`${BASE}/api/models`)).ok) break; } catch { /* starting */ }
  await new Promise((r) => setTimeout(r, 100));
}
const browser = await chromium.launch();
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const VIEWPORTS = [[1728, 925], [390, 844]];

const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");
const photo = { name: "me.png", mimeType: "image/png", buffer: PNG };
const junk = { name: "broken.glb", mimeType: "model/gltf-binary", buffer: Buffer.from("this is not a model at all") };
const rigged = path.join(here, "fixtures/models/riggedfigure.glb");
const ids = async () => ((await (await fetch(`${BASE}/api/models`)).json()).mine || []).map((m) => m.id);

async function open([width, height]) {
  const ctx = await browser.newContext({ viewport: { width, height } });
  const page = await ctx.newPage();
  const log = [];
  page.on("console", (m) => { if (m.type() === "error" && !/status of (400|401|404|415|422)|ERR_ABORTED/.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => { if (/api\/models/.test(r.url())) log.push({ method: r.method(), url: r.url(), at: Date.now() }); });
  await page.goto(`${BASE}/#/me`);
  await page.getByTestId("my-model-upload").click();
  await page.getByTestId("model-import-dialog").waitFor();
  return { page, log, close: () => ctx.close() };
}

/** The dialog and its Cancel are on screen and nothing covers Cancel. */
async function reachable(page, label) {
  const box = await page.evaluate(() => {
    const d = document.querySelector('[data-testid="model-import-dialog"]');
    const c = document.querySelector('[data-testid="model-import-cancel"]');
    const r = c.getBoundingClientRect();
    const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    const dr = d.getBoundingClientRect();
    return { top: top && top.dataset.testid, bottom: r.bottom, h: r.height, dialogBottom: dr.bottom, vh: innerHeight, vw: innerWidth, right: dr.right };
  });
  assert.equal(box.top, "model-import-cancel", `${label}: Cancel is the element under its own centre`);
  assert.ok(box.bottom <= box.vh && box.dialogBottom <= box.vh && box.right <= box.vw, `${label}: the dialog and Cancel fit the screen`);
  assert.ok(box.h >= 44, `${label}: Cancel is at least 44 px tall (${box.h})`);
}

async function gone(page, label) {
  await page.getByTestId("model-import-dialog").waitFor({ state: "detached", timeout: 3000 });
  assert.equal(await page.getByTestId("model-import-dialog").count(), 0, `${label}: the dialog is not in the DOM`);
  // the Me page lists the models again before Upload is usable, so this waits for it
  await page.waitForFunction(() => { const b = document.querySelector('[data-testid="my-model-upload"]'); return b && !b.disabled; }, null, { timeout: 5000 })
    .catch(() => assert.fail(`${label}: Upload is usable again`));
}

const tag = (vp) => `${vp[0]}x${vp[1]}`;
const posts = (log) => log.filter((r) => r.method === "POST");

const cases = {
  async idle(vp) {
    for (const how of ["cancel", "escape", "backdrop"]) {
      const { page, log, close } = await open(vp);
      await reachable(page, `idle ${tag(vp)}`);
      if (how === "cancel") await page.getByTestId("model-import-cancel").click();
      if (how === "escape") await page.keyboard.press("Escape");
      if (how === "backdrop") await page.mouse.click(5, vp[1] - 5);
      await gone(page, `idle ${how}`);
      assert.equal(posts(log).length, 0, "nothing was sent");
      await close();
    }
    ok(`idle ${tag(vp)}: Cancel, Escape and the backdrop close the dialog and send nothing`);
  },

  async chosen(vp) {
    const { page, log, close } = await open(vp);
    await page.getByTestId("model-import-file").setInputFiles(photo);
    await page.getByTestId("model-import-consent").waitFor({ state: "visible" });
    await reachable(page, `chosen ${tag(vp)}`);
    await page.screenshot({ path: path.join(SHOTS, `chosen-${tag(vp)}.png`) });
    await page.getByTestId("model-import-cancel").click();
    await gone(page, "chosen");
    assert.equal(posts(log).length, 0, "a chosen file is not sent after Cancel");
    await close();
    ok(`file chosen ${tag(vp)}: Cancel closes and nothing is sent`);
  },

  async uploading(vp) {
    const before = await ids();
    const { page, log, close } = await open(vp);
    let held = null;
    await page.route(/api\/models\?/, (route) => { held = route; }); // the upload never gets an answer while it is held
    await page.getByTestId("model-import-file").setInputFiles(photo);
    await page.getByTestId("model-import-consent").selectOption("self");
    await page.getByTestId("model-import-submit").click();
    for (let i = 0; i < 50 && !held; i++) await sleep(50);
    assert.ok(held, "the upload started");
    assert.equal(await page.getByTestId("model-import-submit").isDisabled(), true, "Import is off while uploading");
    await reachable(page, `uploading ${tag(vp)}`);
    await page.getByTestId("model-import-cancel").click();
    await gone(page, "uploading");
    // a small upload runs on after Cancel (catalog.js ABORT_MIN_BYTES): the real server makes the model, and the
    // dialog, already closed, deletes it as soon as the answer names it
    await held.continue();
    for (let i = 0; i < 40 && !log.some((r) => r.method === "DELETE"); i++) await sleep(50);
    await sleep(300);
    assert.ok(log.some((r) => r.method === "DELETE"), "the model the late answer named was deleted");
    assert.deepEqual(await ids(), before, "no model is left on the server");
    assert.equal(log.filter((r) => r.method === "GET" && /api\/models\/[0-9a-f]{32}/.test(r.url)).length, 0, "no wait for a model started");
    await close();
    ok(`uploading ${tag(vp)}: Cancel closes at once and the model a late answer names is deleted`);
  },

  async waiting(vp) {
    const before = await ids();
    const { page, log, close } = await open(vp);
    await page.getByTestId("model-import-file").setInputFiles(photo);
    await page.getByTestId("model-import-consent").selectOption("self");
    await page.getByTestId("model-import-submit").dblclick(); // a double click starts one import
    await page.getByTestId("model-progress").waitFor();
    await page.waitForFunction(() => /graphics card/i.test(document.querySelector('[data-testid="model-progress-label"]')?.textContent || ""));
    assert.equal(posts(log).length, 1, "a double click sent one upload");
    const id = (await ids()).find((m) => !before.includes(m));
    assert.ok(id, "the photo is queued on the server");
    await reachable(page, `waiting ${tag(vp)}`);
    await page.screenshot({ path: path.join(SHOTS, `waiting-${tag(vp)}.png`) });
    await page.getByTestId("model-import-cancel").click();
    const cancelledAt = Date.now();
    await gone(page, "waiting");
    await sleep(2500);
    assert.ok(log.some((r) => r.method === "DELETE" && r.url.endsWith(`/api/models/${id}`)), "Cancel deleted the queued model");
    assert.deepEqual(await ids(), before, "the cancelled model is not on the server");
    const polls = log.filter((r) => r.method === "GET" && r.url.endsWith(`/api/models/${id}`) && r.at > cancelledAt + 200);
    assert.equal(polls.length, 0, "no poll for the cancelled model after Cancel");
    await close();
    ok(`waiting ${tag(vp)}: Cancel stops the wait and deletes the queued model; a double click sent one upload`);
  },

  async escapebusy(vp) {
    const before = await ids();
    const { page, close } = await open(vp);
    await page.getByTestId("model-import-file").setInputFiles(photo);
    await page.getByTestId("model-import-consent").selectOption("self");
    await page.getByTestId("model-import-submit").click();
    await page.getByTestId("model-progress").waitFor();
    await page.keyboard.press("Escape");
    await gone(page, "escape while waiting");
    await sleep(800);
    assert.deepEqual(await ids(), before, "the model Escape cancelled is not on the server");
    await close();
    ok(`waiting ${tag(vp)}: Escape closes and deletes the queued model`);
  },

  async error(vp) {
    const before = await ids();
    const { page, log, close } = await open(vp);
    await page.getByTestId("model-import-file").setInputFiles(junk);
    await page.getByTestId("model-import-submit").click();
    const err = page.getByTestId("model-import-error");
    await err.waitFor({ state: "visible" });
    const text = await err.textContent();
    assert.ok(text.length > 10 && text.length < 200 && !/Traceback|undefined|null|\{/.test(text), `a plain sentence: ${text}`);
    assert.equal(await page.getByTestId("model-import-submit").isEnabled(), true, "Import is usable again for a retry");
    assert.equal(await page.getByTestId("model-progress").count(), 0, "no progress bar is left after a refusal");
    await reachable(page, `error ${tag(vp)}`);
    await page.screenshot({ path: path.join(SHOTS, `error-${tag(vp)}.png`) });
    await page.getByTestId("model-import-cancel").click();
    await gone(page, "error");
    assert.equal(posts(log).length, 1, "one upload was sent");
    assert.deepEqual(await ids(), before, "a refused file leaves no model");
    await close();
    ok(`error ${tag(vp)}: a refusal shows a plain sentence, Import works again, Cancel closes`);
  },

  async failed(vp) {
    const before = await ids();
    const { page, log, close } = await open(vp);
    // the real server queues the photo; its status is answered "failed", as when Part 2 finds no person
    await page.route(/api\/models\/[0-9a-f]{32}$/, (route) => (route.request().method() === "GET"
      ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "failed", error: "No person was found in the photo." }) })
      : route.continue()));
    await page.getByTestId("model-import-file").setInputFiles(photo);
    await page.getByTestId("model-import-consent").selectOption("self");
    await page.getByTestId("model-import-submit").click();
    await page.getByTestId("model-import-error").waitFor({ state: "visible" });
    assert.match(await page.getByTestId("model-import-error").textContent(), /No person was found in the photo/);
    assert.equal(await page.getByTestId("model-import-submit").isEnabled(), true, "Import is usable again after a failed conversion");
    await reachable(page, `failed ${tag(vp)}`);
    await page.getByTestId("model-import-cancel").click();
    await gone(page, "failed");
    await sleep(800);
    assert.ok(log.some((r) => r.method === "DELETE"), "Cancel deleted the failed model");
    assert.deepEqual(await ids(), before, "the failed model is not left on the server");
    await close();
    ok(`failed conversion ${tag(vp)}: the reason shows, Import works again, Cancel closes and cleans up`);
  },

  async success(vp) {
    const before = await ids();
    const { page, close } = await open(vp);
    await page.getByTestId("model-import-file").setInputFiles(rigged);
    await page.getByTestId("model-import-submit").click();
    await gone(page, "success");
    const now = await ids();
    assert.equal(now.length, before.length + 1, "the rigged model was imported");
    const id = now.find((m) => !before.includes(m));
    await fetch(`${BASE}/api/models/${id}`, { method: "DELETE", headers: { Origin: `http://127.0.0.1:${PORT}` } });
    await close();
    ok(`success ${tag(vp)}: a rigged GLB imports and the dialog closes by itself`);
  },
};

try {
  for (const vp of VIEWPORTS) {
    for (const [name, fn] of Object.entries(cases)) if (!only || only === name) await fn(vp);
  }
} finally {
  await browser.close();
  app.kill();
}
assert.deepEqual(errors, [], `console errors: ${errors.join(" | ")}`);
console.log(`${passed} passed; shots in ${SHOTS}`);
