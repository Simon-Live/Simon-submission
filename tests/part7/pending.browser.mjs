// Offline takes in a real browser at 412x915 with Chromium's fake camera and tests/part7/fake_api.py (it honors
// Idempotency-Key like the real server). Run:
//   PLAYWRIGHT_DIR=/path/to/node_modules node tests/part7/pending.browser.mjs
import assert from "node:assert/strict";
import path from "node:path";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const PORT = 8400 + Math.floor(Math.random() * 300);
const BASE = `http://127.0.0.1:${PORT}`;
const server = spawn("python3", [path.join(here, "fake_api.py"), String(PORT)], { stdio: "inherit" });
process.on("exit", () => server.kill());
for (let i = 0; i < 50; i++) {
  try { if ((await fetch(`${BASE}/api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 100)); }
}
const state = async () => (await fetch(`${BASE}/__test/state`)).json();
const post = (p, body = {}) => fetch(`${BASE}/${p}`, { method: "POST", body: JSON.stringify(body) });
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");
const person = (id, coverage = 0.9) => ({ id, coverage, frames: 40, box_mid: [10, 10, 50, 120] });

const browser = await chromium.launch({
  args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
});
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };

async function open({ noIdb = false } = {}) {
  await post("__test/reset");
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, permissions: ["camera"] });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|ERR_FAILED|net::/.test(m.text())) errors.push(m.text()); });
  await page.route("**/api/jobs/pj*/people/*.jpg", (r) => r.fulfill({ body: PNG, contentType: "image/png" }));
  if (noIdb) await page.addInitScript(() => Object.defineProperty(window, "indexedDB", { value: undefined, configurable: true }));
  return { ctx, page, tid: (id) => page.locator(`[data-testid="${id}"]:visible`).first() };
}
const idbCount = (page) => page.evaluate(() => new Promise((resolve) => {
  const o = indexedDB.open("simon-local", 1);
  o.onsuccess = () => {
    const db = o.result;
    if (!db.objectStoreNames.contains("pending-takes")) { resolve(0); return; }
    const q = db.transaction("pending-takes").objectStore("pending-takes").count();
    q.onsuccess = () => resolve(q.result);
  };
  o.onerror = () => resolve(-1);
}));
const idbIds = (page) => page.evaluate(() => new Promise((resolve) => {
  const o = indexedDB.open("simon-local", 1);
  o.onsuccess = () => { const q = o.result.transaction("pending-takes").objectStore("pending-takes").getAllKeys(); q.onsuccess = () => resolve(q.result); };
}));
const waitFor = async (fn, what, ms = 20000) => {
  const end = Date.now() + ms;
  for (;;) {
    if (await fn()) return;
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await new Promise((r) => setTimeout(r, 150));
  }
};
async function record(page, tid) {
  await tid("countdown-select").selectOption("0");
  await tid("duration-select").selectOption("5");
  await tid("framing-hint").waitFor();
  await tid("cam-start").click();
  await tid("trim-continue").waitFor({ timeout: 20000 });
  await tid("trim-continue").click();
}

try {
  // a) uploads blocked: the take is saved, a reload shows the banner, unblocked it is sent and the copy is gone
  {
    const { ctx, page, tid } = await open();
    await page.route("**/api/uploads", (r) => r.abort());
    await page.goto(`${BASE}/#/follow/lateral-raise`);
    await record(page, tid);
    await tid("saved-panel").waitFor();
    assert.match(await tid("saved-message").innerText(), /Couldn't reach the app\. Your take is saved on this device and will be sent when the app is back\./);
    assert.equal(await tid("saved-title").innerText(), "Saved on this device");
    for (const id of ["pending-send", "pending-delete", "record-again"]) assert.ok(await tid(id).isVisible(), id);
    assert.equal(await tid("saved-auto").isChecked(), true, "start automatically is on by default");
    assert.equal(await idbCount(page), 1);
    assert.equal((await state()).uploads.length, 0);
    ok("a) blocked upload: the saved panel with Send now, Delete take and Record again; one copy in IndexedDB");

    await page.reload();
    await tid("pending-banner").waitFor({ state: "visible" });
    assert.match(await tid("pending-banner").innerText(), /1 take waiting to send/);
    ok("a) reload: the banner says 1 take waiting to send");

    await page.goto(`${BASE}/#/pending`);
    await page.locator("li.pending-row").first().waitFor();
    const [id] = await idbIds(page);
    assert.match(await tid(`pending-${id}`).innerText(), /Saved on this device/);
    assert.ok(await tid(`pending-send-${id}`).isVisible() && await tid(`pending-delete-${id}`).isVisible());
    ok("a) #/pending lists the take with Send now and Delete");

    await page.unroute("**/api/uploads");
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await waitFor(async () => (await state()).jobs && Object.keys((await state()).jobs).length === 1, "the job");
    await waitFor(async () => (await idbCount(page)) === 0, "the saved copy to be deleted");
    const s = await state();
    assert.equal(s.uploads.length, 1);
    await tid("pending-sent").waitFor();
    assert.match(await tid("pending-sent").innerText(), /Your take was sent\. The analysis has started\./);
    assert.match(await tid("pending-sent-link").getAttribute("href"), /#\/job\/job1/);
    ok("a) unblocked: uploaded, job created once, IndexedDB empty, notice links to the job");
    await ctx.close();
  }

  // b) 413: the message is shown and the saved copy is deleted
  {
    const { ctx, page, tid } = await open();
    await page.route("**/api/uploads", (r) => r.fulfill({ status: 413, json: { error: "The file is too large (95 MB at most)." } }));
    await page.goto(`${BASE}/#/follow/lateral-raise`);
    await record(page, tid);
    await tid("people-error").waitFor();
    assert.match(await tid("people-error").innerText(), /too large/);
    assert.ok(await tid("record-again").isVisible());
    await waitFor(async () => (await idbCount(page)) === 0, "the copy to be deleted");
    assert.equal(await tid("saved-panel").isVisible(), false);
    ok("b) 413: the message shows, the saved copy is deleted, Record again is offered");
    await ctx.close();
  }

  // c) the answer to the job call is lost after the server accepted it: the retry makes no second job
  {
    const { ctx, page, tid } = await open();
    let lost = 0;
    await page.route("**/api/follow", async (r) => {
      if (lost++ === 0) { await r.fetch(); await r.abort(); } else await r.continue();
    });
    await page.goto(`${BASE}/#/follow/lateral-raise`);
    await record(page, tid);
    await tid("analyse").click();
    await tid("saved-panel").waitFor();
    assert.equal(Object.keys((await state()).jobs).length, 1, "the server accepted the first request");
    await tid("pending-send").click();
    await tid("pending-open-job").waitFor();
    const s = await state();
    assert.equal(Object.keys(s.jobs).length, 1, "exactly one job");
    assert.equal(s.replays, 1, "the retry was answered from the key");
    assert.equal(s.uploads.length, 1);
    await waitFor(async () => (await idbCount(page)) === 0, "the copy to be deleted");
    ok("c) lost 202: Send now replays the same Idempotency-Key, exactly one job, copy deleted");
    await ctx.close();
  }

  // d) a two-person clip: the background send uploads and stops at the picker; Finish reopens it from the saved record
  {
    const { ctx, page, tid } = await open();
    await post("__test/people", { people: [person("0"), person("1", 0.5)], auto_id: null });
    await page.route("**/api/people", (r) => r.abort());
    await page.goto(`${BASE}/#/follow/lateral-raise`);
    await record(page, tid);
    await tid("saved-panel").waitFor();
    assert.equal((await state()).uploads.length, 1, "the upload went through; only the people job was blocked");
    await page.unroute("**/api/people");
    await tid("pending-send").click();
    await tid("pending-finish").waitFor();
    assert.match(await tid("saved-message").innerText(), /Your take is uploaded\. Choose who is in it to finish\./);
    await tid("pending-finish").click();
    await tid("people").waitFor();
    assert.equal((await state()).uploads.length, 1, "no second upload");
    await tid("person-1").click();
    await tid("people-continue").click();
    await tid("analyse").waitFor();
    await tid("analyse").click();
    await page.waitForURL(/#\/job\/job1/);
    const jobs = Object.values((await state()).jobs);
    assert.equal(jobs.length, 1);
    assert.deepEqual([jobs[0].person_id, jobs[0].entry_id], ["1", "lateral-raise"]);
    assert.equal(await idbCount(page), 0);
    ok("d) two people: uploaded in the background, Finish opens the picker from the record, job sent, copy deleted");
    await ctx.close();
  }

  // e) no IndexedDB (private mode): the sentence, then the in-memory Try again works
  {
    const { ctx, page, tid } = await open({ noIdb: true });
    await page.route("**/api/uploads", (r) => r.abort());
    await page.goto(`${BASE}/#/follow/lateral-raise`);
    await record(page, tid);
    await tid("try-again").waitFor();
    assert.equal(await tid("pending-notice").innerText(), "This take is only kept while this page is open.");
    assert.equal(await tid("saved-panel").isVisible(), false);
    assert.ok(await tid("record-again").isVisible());
    await page.unroute("**/api/uploads");
    await tid("try-again").click();
    await tid("analyse").waitFor();
    await tid("analyse").click();
    await page.waitForURL(/#\/job\/job1/);
    assert.equal((await state()).uploads.length, 1);
    ok("e) no IndexedDB: 'only kept while this page is open', Try again resends the in-memory take");
    await ctx.close();
  }

  // f) Delete take removes the copy
  {
    const { ctx, page, tid } = await open();
    await page.route("**/api/uploads", (r) => r.abort());
    await page.goto(`${BASE}/#/follow/lateral-raise`);
    await record(page, tid);
    await tid("pending-delete").click();
    await waitFor(async () => (await idbCount(page)) === 0, "the copy to be deleted");
    await tid("cam-start").waitFor();
    assert.equal(await tid("pending-banner").isVisible(), false);
    ok("f) Delete take removes the saved copy and returns to the camera");
    await ctx.close();
  }

  assert.deepEqual(errors, [], errors.join("\n"));
} finally {
  await browser.close();
  server.kill();
}
console.log(`${passed} offline-takes browser checks passed`);
