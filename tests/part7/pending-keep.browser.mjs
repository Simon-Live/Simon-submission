// A recording is never lost silently (TICKET-290, offline-takes.md "Kept until the analysis is done"): the kept store
// in a real browser at 412x915 with Chromium's fake camera and tests/part7/fake_api.py. The outbox drive
// (pending.browser.mjs) stays as written; this one covers what TICKET-290 adds. Run:
//   PLAYWRIGHT_DIR=/path/to/node_modules node tests/part7/pending-keep.browser.mjs
import assert from "node:assert/strict";
import path from "node:path";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const PORT = 8700 + Math.floor(Math.random() * 300);
const BASE = `http://127.0.0.1:${PORT}`;
const server = spawn("python3", [path.join(here, "fake_api.py"), String(PORT)], { stdio: "inherit" });
process.on("exit", () => server.kill());
for (let i = 0; i < 50; i++) {
  try { if ((await fetch(`${BASE}/api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 100)); }
}
const state = async () => (await fetch(`${BASE}/__test/state`)).json();
const post = (p, body = {}) => fetch(`${BASE}/${p}`, { method: "POST", body: JSON.stringify(body) });
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");
const RESTARTED = { id: "job1", kind: "follow", status: "failed", stage: "pose", entry_id: "lateral-raise", result: null,
  note: "", reason: "the app restarted before this take finished; record it again", queue_position: null };

const browser = await chromium.launch({
  args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
});
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };

async function open() {
  await post("__test/reset");
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, permissions: ["camera"] });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|ERR_FAILED|net::/.test(m.text())) errors.push(m.text()); });
  await page.route("**/api/jobs/pj*/people/*.jpg", (r) => r.fulfill({ body: PNG, contentType: "image/png" }));
  return { ctx, page, tid: (id) => page.locator(`[data-testid="${id}"]:visible`).first() };
}
/** The records of one IndexedDB store, read without creating anything the app would then miss. */
const records = (page, db, store) => page.evaluate(([db, store]) => new Promise((resolve) => {
  indexedDB.databases().then((list) => {
    if (!list.some((d) => d.name === db)) { resolve([]); return; }
    const o = indexedDB.open(db);
    o.onsuccess = () => {
      if (!o.result.objectStoreNames.contains(store)) { resolve([]); return; }
      const q = o.result.transaction(store).objectStore(store).getAll();
      q.onsuccess = () => resolve(q.result.map(({ blob, ...r }) => ({ ...r, blobSize: blob ? blob.size : 0 })));
    };
    o.onerror = () => resolve(null);
  });
}), [db, store]);
const outbox = (page) => records(page, "simon-local", "pending-takes");
const kept = (page) => records(page, "simon-kept", "kept-takes");
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
async function sendFollow(page, tid) {
  await page.goto(`${BASE}/#/follow/lateral-raise`);
  await record(page, tid);
  await tid("analyse").click();
  await page.waitForURL(/#\/job\/job1/);
}

try {
  // k1) after the 202 the recording leaves the outbox into the kept store and is deleted when the job is done
  {
    const { ctx, page, tid } = await open();
    await sendFollow(page, tid);
    assert.deepEqual(await outbox(page), [], "the outbox is empty after the 202");
    const [k] = await kept(page);
    assert.equal(k.stage, "sent");
    assert.equal(k.job, "job1");
    assert.ok(k.blobSize > 0, "the recording itself is kept");
    await waitFor(async () => (await kept(page)).length === 0, "the kept copy to clear once the job is done", 45000);
    ok("k1) sent: kept at 'sent' with its job and recording, cleared when the job is done; outbox empty at the 202");
    await ctx.close();
  }

  // k2) the job is cut by a restart: the job page offers Send it again from the kept recording, with fresh keys
  {
    const { ctx, page, tid } = await open();
    await page.route("**/api/jobs/job1", (r) => r.fulfill({ status: 200, json: RESTARTED }));
    await sendFollow(page, tid);
    await tid("send-again").waitFor();
    assert.equal(await tid("send-again-note").innerText(), "Your recording is still on this device.");
    assert.equal(await tid("retry").innerText(), "Try again", "the old action stays beside it");
    await tid("send-again").click();
    await page.waitForURL(/#\/job\/job2/);
    const s = await state();
    assert.deepEqual(Object.keys(s.jobs).sort(), ["job1", "job2"], "a second job, not a replay of the failed one");
    assert.equal(s.replays, 0, "fresh Idempotency-Key");
    assert.equal(s.uploads.length, 1, "the upload the server holds is reused");
    const ks = await kept(page);
    assert.deepEqual(ks.map((r) => [r.stage, r.job, r.again_of]), [["sent", "job2", "job1"]]);
    ok("k2) restart cut: Send it again on the job page sends the kept take as job2, one upload, no replay");
    await ctx.close();
  }

  // k3) a stopped take is listed on #/pending with Send it again and Delete, and the banner says it needs the person
  {
    const { ctx, page, tid } = await open();
    await page.route("**/api/jobs/job1", (r) => r.fulfill({ status: 200, json: RESTARTED }));
    await sendFollow(page, tid);
    await page.goto(`${BASE}/#/`);
    await waitFor(async () => (await kept(page)).some((r) => r.stage === "job_failed"), "the watch to mark the job stopped", 45000);
    await tid("pending-stuck").waitFor();
    assert.equal(await tid("pending-stuck").innerText(), "1 take could not be sent");
    await page.goto(`${BASE}/#/pending`);
    const [k] = await kept(page);
    await tid(`pending-${k.id}`).waitFor();
    assert.equal(await tid(`pending-status-${k.id}`).innerText(), "The analysis stopped before it finished. Your recording is still on this device.");
    assert.ok(await tid(`pending-again-${k.id}`).isVisible());
    await tid(`pending-delete-${k.id}`).click();
    await waitFor(async () => (await kept(page)).length === 0, "Delete to remove the kept take");
    ok("k3) #/pending: a stopped take with Send it again and Delete; the banner counts it; Delete removes it");
    await ctx.close();
  }

  // k4) a failed upload: the banner on another screen says why with Retry; Retry sends it
  {
    const { ctx, page, tid } = await open();
    await page.route("**/api/uploads", (r) => r.abort());
    await page.goto(`${BASE}/#/follow/lateral-raise`);
    await record(page, tid);
    await tid("saved-panel").waitFor();
    await page.goto(`${BASE}/#/`);
    await tid("pending-failed").waitFor();
    assert.equal(await tid("pending-failed").innerText(), "Couldn't reach the app. Your take is saved on this device and will be sent when the app is back.");
    assert.equal(await tid("pending-retry").innerText(), "Retry");
    assert.equal((await outbox(page)).length, 1, "kept in the outbox while it fails");
    await page.unroute("**/api/uploads");
    await tid("pending-retry").click();
    await waitFor(async () => Object.keys((await state()).jobs).length === 1, "Retry to send the take");
    ok("k4) failed upload: the reason and Retry in the banner on the home screen; Retry sends it");
    await ctx.close();
  }

  // k5) a 413 with the flag off (until #61): the plain reason and how to fit, and the take is not kept anywhere
  {
    const { ctx, page, tid } = await open();
    await page.route("**/api/uploads", (r) => r.fulfill({ status: 413, json: { error: "The file is too large (95 MB at most)." } }));
    await page.goto(`${BASE}/#/follow/lateral-raise`);
    await record(page, tid);
    await tid("people-error").waitFor();
    assert.equal(await tid("people-error").innerText(),
      "This take is too large to send (95 MB at most), so it was not kept. Record a shorter take to stay under the limit.");
    await waitFor(async () => (await outbox(page)).length === 0, "the outbox copy to go");
    assert.deepEqual(await kept(page), []);
    ok("k5) 413 with keepRefused off: the plain reason and the limit, deleted from both stores");
    await ctx.close();
  }

  assert.deepEqual(errors, [], errors.join("\n"));
} finally {
  await browser.close();
  server.kill();
}
console.log(`${passed} kept-takes browser checks passed`);
