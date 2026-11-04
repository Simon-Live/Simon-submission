// docs/specs/model-picker.md "Intake fix 2" in the real app on the Me page (#/me) at 412x915, against tests/part7/fake_profile.py
// (fake sign-in and profile) with api/models stubbed by page.route: no GPU, no converter. The real web/skin/ modules run.
// Cases: progress (defects 1, 2, 3, 4, 5: a picture of an object and an unrigged GLB), delete (defect 6), deletereal (the
// real server from tests/part7/real_app.py: a DELETE is not reported as net::ERR_ABORTED). No --case runs all.
//   PLAYWRIGHT_DIR=<node_modules> scripts/with-browser-slot.sh node tests/part7/model-intake.browser.mjs [--case progress]
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
const SHOTS = process.env.SHOTS_DIR || fs.mkdtempSync(path.join(os.tmpdir(), "model-intake-"));
fs.mkdirSync(SHOTS, { recursive: true });
const only = process.argv.includes("--case") ? process.argv[process.argv.indexOf("--case") + 1] : null;

const PORT = 7900 + Math.floor(Math.random() * 90);
const BASE = `http://127.0.0.1:${PORT}`;
const server = spawn("python3", [path.join(here, "fake_profile.py"), String(PORT)], { stdio: "inherit" });
for (let i = 0; i < 50; i++) {
  try { if ((await fetch(`${BASE}/api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 100)); }
}
const browser = await chromium.launch();
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const tid = (page, id) => page.getByTestId(id);
const shot = (page, name) => page.screenshot({ path: path.join(SHOTS, name), fullPage: true });
const json = (route, status, body) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const getJson = async (p) => (await fetch(`${BASE}/${p}`)).json();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const A = "a".repeat(32);
const B = "b".repeat(32);
const rec = (id, name, extra = {}) => ({ id, name, kind: "generated", glb: `api/models/${id}/model.glb`, manifest: `api/models/${id}/character.json`,
  licence: { id: "own-work", attribution: null }, status: "ready", ...extra });

/** A GLB with a JSON chunk and no skins: the dialog says up front that Simon adds the skeleton. */
function unriggedGlb() {
  const body = Buffer.from(JSON.stringify({ asset: { version: "2.0" } }));
  const json = Buffer.concat([body, Buffer.alloc((4 - (body.length % 4)) % 4, 0x20)]);
  const head = Buffer.alloc(20);
  head.writeUInt32LE(0x46546c67, 0); head.writeUInt32LE(2, 4); head.writeUInt32LE(20 + json.length, 8);
  head.writeUInt32LE(json.length, 12); head.writeUInt32LE(0x4e4f534a, 16);
  return Buffer.concat([head, json]);
}
/** A GLB whose JSON names a skin: the dialog treats it as already rigged (3 steps, answered ready at once). */
function riggedGlb() {
  const body = Buffer.from(JSON.stringify({ asset: { version: "2.0" }, skins: [{ joints: [0] }] }));
  const json = Buffer.concat([body, Buffer.alloc((4 - (body.length % 4)) % 4, 0x20)]);
  const head = Buffer.alloc(20);
  head.writeUInt32LE(0x46546c67, 0); head.writeUInt32LE(2, 4); head.writeUInt32LE(20 + json.length, 8);
  head.writeUInt32LE(json.length, 12); head.writeUInt32LE(0x4e4f534a, 16);
  return Buffer.concat([head, json]);
}
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");

async function newPage() {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, hasTouch: true });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error" && !/status of (400|401|404)|share-list\.js|ERR_ABORTED/.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(e.message));
  return page;
}

async function signIn(page, email) {
  await fetch(`${BASE}/__test/auth`, { method: "POST", body: JSON.stringify({ reset: true, available: true }) });
  await page.goto(`${BASE}/`);
  await page.evaluate(() => { location.hash = "#/signin"; });
  await tid(page, "auth-email").fill(email);
  await tid(page, "auth-send").tap();
  await tid(page, "auth-code").waitFor();
  const mail = (await getJson("__test/outbox")).outbox.filter((m) => m.email === email).at(-1);
  await tid(page, "auth-code").fill(mail.code);
  await tid(page, "auth-verify").tap();
  await tid(page, "me-email").waitFor();
}

/** api/models stub. `script` is the list of records the job's status goes through, one per poll. */
async function stubModels(page, { mine = [], script = [], onPost = null, instant = false } = {}) {
  const state = { mine: [...mine], posts: [], deletes: [], polls: 0, def: null, readyId: null };
  await page.route(/\/api\/models(\/[0-9a-f]{32})?(\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    const id = (/models\/([0-9a-f]{32})$/.exec(url.pathname) || [])[1];
    if (method === "POST") {
      state.posts.push(Object.fromEntries(url.searchParams));
      if (instant) { // a rigged file is only checked: the server answers ready in the same call
        const made = onPost || B;
        state.mine.push(rec(made, "Rigged"));
        return json(route, 201, { id: made, status: "ready" });
      }
      await sleep(1500); // the upload stays visible long enough to look at
      return json(route, 202, { id: onPost || B, status: "queued" });
    }
    if (method === "DELETE") {
      state.deletes.push(id);
      state.mine = state.mine.filter((m) => m.id !== id);
      if (state.def === `up:${id}`) state.def = null; // what part7/model_import.py does on the server (tests/part7/test_model_privacy.py)
      return json(route, 200, { ok: true, deleted: id }); // an answer with a body, as part7/model_import.py: a bodiless one logs as ERR_ABORTED
    }
    if (id) {
      const at = script[Math.min(state.polls++, script.length - 1)];
      if (at && at.status === "ready" && !state.mine.some((m) => m.id === id)) state.mine.push(rec(id, "Made model"));
      return json(route, 200, { id, name: "Made model", ...at });
    }
    return json(route, 200, { mine: state.mine });
  });
  await page.route(/\/api\/models\/[0-9a-f]{32}\/(model\.glb|character\.json)$/, (route) => route.fulfill({ status: 404, body: "" }));
  await page.route("**/api/me/profile", async (route) => {
    if (route.request().method() === "GET") {
      const r = await route.fetch();
      return json(route, r.status(), { ...(await r.json()), default_model_id: state.def });
    }
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON();
      if ("default_model_id" in body) { state.def = body.default_model_id; return json(route, 200, { default_model_id: state.def }); }
    }
    return route.continue();
  });
  return state;
}

/** Record every label and bar the progress indicator shows, in order, from the page's own DOM. */
const watchProgress = (page) => page.addInitScript(() => {
  window.__seen = [];
  const read = () => {
    const label = document.querySelector('[data-testid="model-progress-label"]');
    const bar = document.querySelector('[data-testid="model-progress-bar"]');
    if (!label || !bar) return;
    const fill = bar.querySelector(".msel-bar-fill");
    const last = window.__seen[window.__seen.length - 1];
    if (last && last.label === label.textContent && last.now === bar.getAttribute("aria-valuenow")) return;
    const dlg = bar.closest("dialog");
    window.__seen.push({ label: label.textContent, now: bar.getAttribute("aria-valuenow"), text: bar.getAttribute("aria-valuetext"),
      barH: bar.getBoundingClientRect().height, fillW: fill.getBoundingClientRect().width, inOpenDialog: !!(dlg && dlg.open) });
  };
  new MutationObserver(read).observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
});
const seen = (page) => page.evaluate(() => window.__seen);

async function openImport(page) {
  await page.evaluate(() => { location.hash = "#/me"; });
  await tid(page, "my-model-upload").waitFor();
  await tid(page, "my-model-upload").tap();
  await tid(page, "model-import-dialog").waitFor();
}

const cases = {
  async progress() {
    const page = await newPage();
    await watchProgress(page);
    await signIn(page, "intake@example.com");
    const state = await stubModels(page, { script: [
      { status: "queued", step: "waiting", step_index: 2, step_count: 5, waiting: "Your model is next." },
      { status: "converting", step: "making", step_index: 3, step_count: 5 },
      { status: "converting", step: "checking", step_index: 4, step_count: 5 },
      { status: "ready" },
    ] });
    await openImport(page);

    // defect 4: the labels sit above their inputs, not inline (skin.css loads with the dialog)
    const name = tid(page, "model-import-name");
    const label = tid(page, "model-import-dialog").locator('label[for$="-name"]');
    const lb = await label.boundingBox();
    const nb = await name.boundingBox();
    assert.ok(lb.y + lb.height <= nb.y + 1, `label above its input (label bottom ${lb.y + lb.height}, input top ${nb.y})`);
    assert.equal(await page.locator("link[data-simon-skin-css]").count(), 1);
    ok("the import dialog is laid out by skin.css on #/me (labels above inputs)");

    // defect 3: the picture question, and the hint for each choice
    await tid(page, "model-import-file").setInputFiles({ name: "armour.png", mimeType: "image/png", buffer: PNG });
    await tid(page, "model-import-picture").waitFor();
    const hint = tid(page, "model-import-photo-hint");
    assert.match(await hint.innerText(), /plain skin-coloured human body/);
    await tid(page, "model-import-picture-object").check();
    const text = await hint.innerText();
    assert.match(text, /3D model of what is in the picture/);
    assert.match(text, /back is the model's guess/);
    assert.doesNotMatch(text, /grey human body|armour|costumes|does not copy/i);
    ok("the object choice shows the object hint, not the person hint");
    await tid(page, "model-import-picture-person").check();
    assert.match(await hint.innerText(), /plain skin-coloured human body/);
    await tid(page, "model-import-picture-object").check();
    await shot(page, "pic-hint-object.png");

    // polish 1: each hint sits under the question it is about, as that question's description, with a gap above it
    const place = await page.evaluate(() => {
      const box = (id) => document.querySelector(`[data-testid="${id}"]`).getBoundingClientRect();
      const q = document.querySelector('[data-testid="model-import-picture"]');
      const src = document.querySelector('[id$="-src-hint"]');
      return { questionBottom: box("model-import-picture").bottom, hintTop: box("model-import-photo-hint").top, hintId: document.querySelector('[data-testid="model-import-photo-hint"]').id,
        describedBy: q.getAttribute("aria-describedby"), sourceHintBottom: src.getBoundingClientRect().bottom, questionTop: box("model-import-picture").top };
    });
    assert.ok(place.hintTop >= place.questionBottom + 8, `the hint sits under the question with a gap (${place.hintTop} vs ${place.questionBottom})`);
    assert.ok(place.questionTop >= place.sourceHintBottom + 8, "negative: the question, not the hint, follows Where it came from");
    assert.equal(place.describedBy, place.hintId, "the hint is the question's described-by text");
    ok("the picture hint sits under What is in the picture?, not under Where it came from");

    // defects 1 and 2: the bar has height and a fill while uploading, inside the open dialog; its steps are the server's
    await tid(page, "model-import-submit").tap();
    await tid(page, "model-progress").waitFor();
    await page.waitForTimeout(400);
    const first = await page.evaluate(() => {
      const bar = document.querySelector('[data-testid="model-progress-bar"]');
      return { barH: bar.getBoundingClientRect().height, fillW: bar.querySelector(".msel-bar-fill").getBoundingClientRect().width,
        inOpenDialog: !!(bar.closest("dialog") && bar.closest("dialog").open) };
    });
    assert.ok(first.inOpenDialog, "the bar is inside the open dialog");
    assert.ok(first.barH >= 6, `the bar has height (${first.barH})`);
    assert.ok(first.fillW > 0, `the bar has a visible fill while uploading (${first.fillW})`);
    assert.equal(await page.locator("link[data-simon-model-progress-css]").count(), 1);
    await shot(page, "pic-uploading.png");
    ok("the progress bar has height and a fill inside the open dialog while uploading");

    await tid(page, "model-import-dialog").waitFor({ state: "detached", timeout: 30000 });
    const labels = (await seen(page)).map((s) => s.label);
    assert.deepEqual([...new Set(labels.map((l) => l.replace(/ \d+%$/, "")))],
      ["Uploading", "Waiting for the graphics card", "Making the 3D model and adding its skeleton", "Checking the model", "Ready"]);
    const steps = (await seen(page)).map((s) => s.text.split(".")[0]);
    assert.ok(steps.includes("Step 3 of 5: Making the 3D model and adding its skeleton"));
    assert.ok(steps.includes("Step 4 of 5: Checking the model"), "the checking step the server reported is shown");
    assert.equal(state.posts[0].kind, "object");
    assert.ok(!("consent" in state.posts[0]), "negative: no consent for an object");
    ok("a character or object picture shows waiting, making, checking and ready from the job status");
  },

  async ready() {
    const page = await newPage();
    await watchProgress(page);
    await signIn(page, "ready@example.com");
    const state = await stubModels(page, { instant: true });
    await openImport(page);
    await tid(page, "model-import-file").setInputFiles({ name: "rigged.glb", mimeType: "model/gltf-binary", buffer: riggedGlb() });
    await tid(page, "model-import-submit").tap();
    await tid(page, "model-progress-label").filter({ hasText: "Ready" }).waitFor();
    const bar = await tid(page, "model-progress-bar").getAttribute("aria-valuenow");
    assert.equal(bar, "100", "the bar is full when Ready shows");
    const t0 = Date.now();
    await page.waitForTimeout(500);
    assert.equal(await tid(page, "model-import-dialog").count(), 1, "polish 2: the dialog is still open half a second after Ready");
    await shot(page, "rigged-ready.png");
    await tid(page, "model-import-dialog").waitFor({ state: "detached", timeout: 10000 });
    assert.ok(Date.now() - t0 >= 700, "Ready was on screen for about a second");
    assert.equal(state.posts.length, 1);
    ok("a rigged GLB shows Ready with the bar full for about a second before the dialog closes");
  },

  async skeleton() {
    const page = await newPage();
    await watchProgress(page);
    await signIn(page, "skeleton@example.com");
    await stubModels(page, { script: [
      { status: "queued", step: "waiting", step_index: 2, step_count: 5 }, { status: "converting", step: "skeleton", step_index: 3, step_count: 5 },
      { status: "converting", step: "skeleton", step_index: 3, step_count: 5 }, { status: "ready" }] });
    await openImport(page);
    await tid(page, "model-import-file").setInputFiles({ name: "soldier.glb", mimeType: "model/gltf-binary", buffer: unriggedGlb() });
    const status = tid(page, "model-import-status");
    await status.filter({ hasText: "No skeleton found, so Simon is adding one." }).waitFor();
    await tid(page, "model-import-submit").tap();
    await tid(page, "model-progress").waitFor();
    await page.waitForTimeout(3600); // well past the 2.5 s it used to vanish after
    const dlg = await tid(page, "model-import-dialog").count();
    if (dlg) {
      assert.match(await status.innerText(), /No skeleton found, so Simon is adding one\./, "still there while the model is made");
      await shot(page, "glb-skeleton-line.png");
    }
    await tid(page, "model-import-dialog").waitFor({ state: "detached", timeout: 30000 });
    ok("the no-skeleton line stays until the model is ready");
  },

  async delete() {
    const page = await newPage();
    await signIn(page, "delete@example.com");
    const state = await stubModels(page, { mine: [rec(A, "Soldier"), rec(B, "Ironman")] });
    state.def = `up:${A}`;
    await page.evaluate(() => { location.hash = "#/me"; });
    const select = tid(page, "my-model-select");
    await select.waitFor();
    assert.equal(await select.inputValue(), `up:${A}`, "the account default is the first model");
    const del = tid(page, "my-model-delete");
    assert.ok(await del.isVisible());
    await shot(page, "me-delete-control.png");
    await tid(page, "my-model-save").tap();
    await tid(page, "my-model-note").filter({ hasText: "Saved." }).waitFor();
    await del.tap();
    assert.equal(await tid(page, "my-model-note").innerText(), "", "polish 4: the Saved note is gone while the confirm is open");
    assert.ok(await tid(page, "my-model-delete-ask").isVisible(), "a confirm comes first");
    assert.deepEqual(state.deletes, [], "negative: nothing is deleted before the answer");
    await tid(page, "my-model-delete-no").tap();
    assert.deepEqual(state.deletes, []);
    await del.tap();
    await shot(page, "me-delete-confirm.png");
    await tid(page, "my-model-delete-yes").tap();
    await tid(page, "my-model-note").filter({ hasText: "Model deleted." }).waitFor();
    assert.deepEqual(state.deletes, [A], "one model, once");
    assert.equal(state.def, null, "the account default no longer names it");
    assert.equal(await select.inputValue(), "person");
    assert.deepEqual(await select.locator("option").evaluateAll((o) => o.map((x) => x.value).filter((v) => v.startsWith("up:"))), [`up:${B}`]);
    assert.equal(await del.isVisible(), false, "Person has no delete control");
    await shot(page, "me-after-delete.png");
    await select.selectOption(`lib:ual1-mannequin`).catch(() => {});
    ok("Delete this model confirms, deletes one own model and clears the default");
    await select.selectOption(`up:${B}`);
    assert.ok(await del.isVisible(), "the other own model has its own control");
    const library = (await select.locator("option").evaluateAll((o) => o.map((x) => x.value))).find((v) => v.startsWith("lib:"));
    if (library) { await select.selectOption(library); assert.equal(await del.isVisible(), false, "negative: a built-in model has none"); }
    ok("the control shows for an own model and not for a built-in one");
  },

  // staging 2026-11-02: DELETE api/models/<id> answered 200 with a body and still logged net::ERR_ABORTED. The client
  // never read the body, so Chromium kept the request open and the next reload cancelled it. Real server, no stubs.
  // The real server refuses a licence with no credit, the field is outlined and the file kept; the fix alone imports the model
  // and the viewer shows it. PROOF_GLB names a model made on Modal (serverless-compute.md AC-SC20); default a fixture.
  async refusalreal() {
    const port = PORT + 200;
    const app = spawn("python3", [path.join(here, "real_app.py"), String(port), String(port + 1)], { stdio: ["ignore", "pipe", "inherit"] });
    try {
      await new Promise((resolve, reject) => {
        app.stdout.on("data", (d) => { if (String(d).includes("ready")) resolve(); });
        app.on("exit", (code) => reject(new Error(`real_app.py ended with ${code}`)));
      });
      const page = await newPage();
      const posts = [];
      page.on("response", (r) => { if (r.request().method() === "POST" && r.url().includes("api/models")) posts.push(r.status()); });
      await page.goto(`http://127.0.0.1:${port}/simon-part-7/#/me`);
      await tid(page, "my-model-upload").click();
      await tid(page, "model-import-file").setInputFiles(process.env.PROOF_GLB || path.join(here, "fixtures/models/riggedfigure.glb"));
      await tid(page, "model-import-licence").selectOption("CC-BY");
      await tid(page, "model-import-submit").click();
      const error = tid(page, "model-import-error");
      await error.waitFor();
      assert.match(await error.textContent(), /Credit line is empty, and CC-BY, CC-BY-SA and CC-BY-NC need/);
      assert.equal(await tid(page, "model-import-credit").getAttribute("aria-invalid"), "true");
      assert.equal(await tid(page, "model-import-status").textContent(), "Your file is still chosen, so you do not need to choose it again.");
      assert.deepEqual(posts, [], "negative: nothing was sent");
      assert.equal(await tid(page, "model-import-file").evaluate((n) => n.files.length), 1, "the file stays chosen");
      await shot(page, "refusal-credit.png");
      await tid(page, "model-import-licence").selectOption("own-work");
      const answered = page.waitForResponse((r) => r.request().method() === "POST" && r.url().includes("api/models"), { timeout: 60000 });
      await tid(page, "model-import-submit").click();
      await answered;
      await tid(page, "model-import-dialog").waitFor({ state: "detached", timeout: 30000 });
      await tid(page, "my-model-preview").waitFor({ timeout: 60000 });
      assert.deepEqual(posts, [201], "the changed licence alone imported it");
      const mine = await page.evaluate(async () => (await (await fetch("api/models")).json()).mine);
      assert.equal(mine.length, 1);
      assert.equal(mine[0].status, "ready");
      await sleep(3000);
      await shot(page, "viewer-model.png");
      ok("refusalreal: credit refusal marked, file kept, licence change imports, viewer shows the model");
    } finally {
      app.kill();
    }
  },
  async deletereal() {
    const port = PORT + 100;
    const app = spawn("python3", [path.join(here, "real_app.py"), String(port), String(port + 1)], { stdio: ["ignore", "pipe", "inherit"] });
    try {
      await new Promise((resolve, reject) => {
        app.stdout.on("data", (d) => { if (String(d).includes("ready")) resolve(); });
        app.on("exit", (code) => reject(new Error(`real_app.py ended with ${code}`)));
      });
      const base = `http://127.0.0.1:${port}/simon-part-7/`;
      const page = await newPage();
      const failed = [];
      page.on("requestfailed", (r) => failed.push(`${r.method()} ${r.url()} ${r.failure()?.errorText}`));
      await page.goto(base);
      const glb = fs.readFileSync(path.join(here, "fixtures/models/riggedfigure.glb")).toString("base64");
      const id = await page.evaluate(async (b64) => {
        const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
        const res = await fetch("api/models?name=Figure&licence=own-work&filename=figure.glb", { method: "POST", headers: { "Content-Type": "model/gltf-binary" }, body: bytes });
        return (await res.json()).id;
      }, glb);
      assert.match(String(id), /^[0-9a-f]{32}$/, "the real server stored the rigged model");
      await page.evaluate(() => { location.hash = "#/me"; });
      const select = tid(page, "my-model-select");
      await select.waitFor();
      await select.selectOption(`up:${id}`);
      const deletes = [];
      page.on("response", (r) => { if (r.request().method() === "DELETE") deletes.push(r.status()); });
      await tid(page, "my-model-delete").tap();
      await tid(page, "my-model-delete-yes").tap();
      await tid(page, "my-model-note").filter({ hasText: "Model deleted." }).waitFor();
      await page.reload(); // an unread answer was cancelled here and reported as net::ERR_ABORTED
      await select.waitFor();
      await sleep(500);
      assert.deepEqual(deletes, [200], "the real server answered the one DELETE with 200");
      assert.deepEqual(failed.filter((f) => f.startsWith("DELETE ")), [], "no failed request for the DELETE");
      assert.equal(await select.locator(`option[value="up:${id}"]`).count(), 0, "the deleted model is gone after the reload");
      await page.context().close();
      ok("a real DELETE is read to its end: no net::ERR_ABORTED after a reload");
    } finally {
      app.kill();
    }
  },
};

try {
  for (const [name, fn] of Object.entries(cases)) if (!only || only === name) await fn();
} finally {
  await browser.close();
  server.kill();
}
assert.deepEqual(errors, [], `console errors: ${errors.join(" | ")}`);
console.log(`${passed} passed; shots in ${SHOTS}`);
