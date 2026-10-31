// Progress indicators at 412x915 (operator 2026-10-30): byte progress on upload, the people job, the job
// screen and the loading placeholders, against a real local server whose steps are slow on purpose.
//   PLAYWRIGHT_DIR=/path/to/node_modules/playwright node tests/part7/progress.browser.mjs [shots-dir]
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(here, "../..");
const out = path.resolve(process.argv[2] || path.join(here, "screens"));
fs.mkdirSync(out, { recursive: true });
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT_DIR || "playwright");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");
const json = (res, body, status = 200) => { res.writeHead(status, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let peopleStart = 0;
let jobStart = 0;
let slowUpload = true;
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  const p = decodeURIComponent(url.pathname);
  if (p === "/api/uploads") {
    // read the body slowly so the browser reports intermediate progress
    req.on("data", () => { if (slowUpload) { req.pause(); setTimeout(() => req.resume(), 60); } });
    req.on("end", async () => { if (slowUpload) await sleep(1500); json(res, { upload_id: "u1", duration_ms: 5000, width: 640, height: 480 }, 201); });
    return;
  }
  if (p === "/api/config") return json(res, { limits: { max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000 } });
  if (p === "/api/people") { peopleStart = Date.now(); return json(res, { job: "pj1" }, 202); }
  if (/^\/api\/jobs\/pj1\/people\/.*\.jpg$/.test(p)) { res.writeHead(200, { "content-type": "image/png" }); return res.end(PNG); }
  if (p === "/api/jobs/pj1") {
    const t = (Date.now() - peopleStart) / 1000;
    if (t < 1.5) return json(res, { id: "pj1", kind: "people", status: "running", stage: "normalizing" });
    if (t < 3) return json(res, { id: "pj1", kind: "people", status: "running", stage: "trimming" });
    if (t < 5) return json(res, { id: "pj1", kind: "people", status: "running", stage: "tracking" });
    const person = (id) => ({ id, coverage: 0.9, frames: 40, box_mid: [10, 10, 50, 120] });
    return json(res, { id: "pj1", kind: "people", status: "done", result: { people: [person("0"), person("1")], frame: "people/frame.jpg", auto_id: null } });
  }
  if (p === "/api/trainer") { jobStart = Date.now(); return json(res, { job: "tj1" }, 202); }
  if (p === "/api/jobs/tj1") {
    const t = (Date.now() - jobStart) / 1000;
    const base = { id: "tj1", kind: "trainer" };
    if (t < 1.5) return json(res, { ...base, status: "queued", queue_position: 2 });
    if (t < 3.5) return json(res, { ...base, status: "running", stage: "pose" });
    if (t < 6) return json(res, { ...base, status: "running", stage: "skeleton" });
    return json(res, { ...base, status: "done", entry_id: "e9" });
  }
  if (p === "/api/jobs/gj1") return json(res, { id: "gj1", kind: "group", status: "running", stage: "followers", progress: "2 of 3" });
  if (p === "/catalog/api/entries/e1") { await sleep(1500); return json(res, { id: "e1", name: "Lateral raise" }); }
  if (p === "/catalog/api/entries") return json(res, { entries: [] });
  if (p === "/api/labels") return json(res, {});
  const base = /^\/(tests|web)\//.test(p) ? ROOT : path.join(ROOT, "web");
  const file = path.resolve(base, "." + (p === "/" ? "/index.html" : p));
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404).end("no"); return; }
  res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const port = server.address().port;
const BASE = `http://127.0.0.1:${port}/`;

const browser = await chromium.launch({ args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"] });
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, permissions: ["camera"] });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
const tid = (id) => page.getByTestId(id);
const shot = (n) => page.screenshot({ path: path.join(out, `progress-${n}.png`), fullPage: true });
const ok = (m) => console.log(`ok  ${m}`);
const text = async (id) => (await tid(id).first().textContent()).trim();

try {
  // 1. byte progress through uploadVideo (a 6 MB blob; the server reads it slowly)
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/progress.html`);
  await page.waitForFunction(() => window.__seen && window.__seen.length > 0);
  const bar = tid("upload-progress").getByTestId("progress-bar");
  assert.equal(await bar.getAttribute("role"), "progressbar");
  await shot("1-upload-bytes");
  await page.waitForFunction(() => window.__done);
  const seen = await page.evaluate(() => window.__seen);
  assert.ok(seen.length >= 3, `several progress events, saw ${seen}`);
  assert.ok(seen.some((v) => v > 0 && v < 100), "an intermediate percent was reported");
  assert.equal(seen.at(-1), 100);
  assert.match(await text("progress-text"), /^Uploading your take, 100%$/);
  assert.equal(await bar.getAttribute("aria-valuenow"), "100");
  ok(`upload reports bytes: ${seen.slice(0, 6)}... then 100%`);

  // 2. the whole take flow: record, upload, people job (5 s), picker; no disabled button without a reason
  await page.goto("about:blank");
  await page.goto(`${BASE}#/record`);
  await tid("countdown-select").selectOption("0");
  await tid("duration-select").selectOption("5");
  await tid("cam-start").click();
  await tid("trim-continue").waitFor({ timeout: 20000 });
  await page.evaluate(() => {
    window.__bad = [];
    setInterval(() => {
      for (const b of document.querySelectorAll("button:disabled")) {
        if (!b.offsetParent) continue; // hidden
        const scope = b.closest("section, .screen, .picker") || document.body;
        const why = [...scope.querySelectorAll('[data-testid$="reason"], [data-testid$="error"]')].some((e) => !e.hidden && e.textContent.trim());
        if (!why) window.__bad.push(b.getAttribute("data-testid") || b.textContent);
      }
    }, 100);
  });
  await tid("trim-continue").click();
  await tid("upload-progress").waitFor();
  assert.match(await text("progress-text"), /Uploading your take/);
  ok("upload panel appears with 'Uploading your take'");
  await shot("2-uploading");
  await tid("people-progress").waitFor({ timeout: 15000 });
  assert.match(await text("progress-text"), /^Finding the people in your clip, about \d+ (to \d+ )?s$/);
  assert.equal(await tid("people-continue").isVisible(), false, "no Continue button while looking");
  await page.waitForFunction(() => /Step \d of 3/.test(document.querySelector('[data-testid="people-stage"]')?.textContent || ""));
  assert.match(await text("people-stage"), /Step \d of 3: /);
  assert.match(await text("progress-elapsed"), /^Elapsed \d+:\d\d$/);
  await shot("3-finding-people");
  await tid("people-frame").waitFor({ timeout: 12000 });
  assert.match(await text("people"), /Tap the person this recording is about/);
  assert.equal(await tid("people-continue").isDisabled(), true);
  assert.match(await text("people-continue-reason"), /Tap the person/);
  await shot("4-picker");
  await tid("person-1").click();
  assert.equal(await tid("people-continue").isDisabled(), false);
  await tid("people-continue").click();
  await tid("name").fill("Lateral raise");
  await tid("save").click();
  await page.waitForURL(/#\/job\/tj1/);
  ok("people job shows progress, stage and estimate, then the picker with its reason");

  // 3. job screen: queue, stages, overall bar, estimate
  await tid("progress").waitFor();
  await page.waitForFunction(() => /Place in line: 2/.test(document.querySelector('[data-testid="queue"]')?.textContent || ""), null, { timeout: 8000 }); // the first poll fills it
  assert.match(await text("queue"), /Place in line: 2/);
  await shot("5-job-queued");
  await page.waitForFunction(() => document.querySelector('[data-testid="stage-detail"]')?.textContent.includes("longest step"));
  assert.match(await text("stage-detail"), /Usually about 1 to 3 min\./);
  const now1 = Number(await tid("progress-bar").first().getAttribute("aria-valuenow"));
  assert.match(await text("progress-text"), /^Step 3 of 6: Reading the pose$/);
  await shot("6-job-pose");
  await page.waitForFunction(() => /Step 4 of 6/.test(document.querySelector('[data-testid="progress-text"]').textContent));
  const now2 = Number(await tid("progress-bar").first().getAttribute("aria-valuenow"));
  assert.ok(now2 > now1, `overall bar advances ${now1} -> ${now2}`);
  assert.match(await text("progress-elapsed"), /^Elapsed \d+:\d\d$/);
  ok("job screen: queue place, stage k of n, determinate bar advances, estimate, elapsed");

  // 4. group progress for followers
  await page.goto("about:blank");
  await page.goto(`${BASE}#/job/gj1`);
  await tid("group-progress").waitFor({ state: "visible" });
  assert.equal(await text("group-progress"), "Person 2 of 3");
  ok("group job shows 'Person 2 of 3'");

  // 5. watch loading placeholder while the entry loads
  await page.goto("about:blank");
  await page.goto(`${BASE}#/watch/e1`);
  await tid("loading").waitFor();
  assert.equal(await text("loading"), "Loading movement");
  await shot("7-watch-loading");
  ok("watch shows a spinner and skeleton while loading");

  assert.deepEqual(await page.evaluate(() => window.__bad || []), [], "no disabled button shown without a reason");
  assert.deepEqual(errors, []);
  ok("no disabled button without a reason; no console errors");
} finally {
  await browser.close();
  server.close();
}
