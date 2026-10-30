// Playwright drive for the capture lane (TICKET-052) at 412x915 with Chromium's fake camera.
//   PLAYWRIGHT_DIR=/path/to/node_modules/playwright node tests/part7/drive_recorder.mjs <out-dir>
// The API is mocked in the page. web/trim.js and web/labels.js belong to the EDIT lane; when they are
// absent from web/, the stand-ins in tests/part7/recorder_standins/ are served instead (test only).
import http from "node:http";
import fs from "node:fs";
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const here = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(here, "../../web");
const STAND = path.join(here, "recorder_standins");
const out = path.resolve(process.argv[2] || path.join(here, "../../qa/screenshots/recorder"));
mkdirSync(out, { recursive: true });
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT_DIR || "playwright");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };

const server = http.createServer((req, res) => {
  let rel = decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/^\//, "") || "index.html";
  let file = path.resolve(WEB, rel);
  // This drive checks the REC lane against its trim stand-in (it records the editor arguments); the real
  // trim editor is proven by the staging journey verify.
  if (rel === "trim.js") file = path.resolve(STAND, rel);
  if (!file.startsWith(WEB) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.resolve(STAND, rel);
  if (!file.startsWith(STAND) && !file.startsWith(WEB) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404).end("not found");
    return;
  }
  res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const BASE = `http://127.0.0.1:${server.address().port}/`;

const errors = [];
const posts = [];
const browser = await chromium.launch({
  args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
});
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, permissions: ["camera"] });
const page = await ctx.newPage();
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
await page.route("**/api/config", (r) => r.fulfill({ json: { limits: { max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000 } } }));
await page.route("**/api/uploads", (r) => {
  posts.push({ url: "uploads", bytes: r.request().postDataBuffer()?.length || 0 });
  r.fulfill({ status: 201, json: { upload_id: "u1", duration_ms: 9000, width: 640, height: 480 } });
});
await page.route("**/api/trainer", (r) => { posts.push({ url: "trainer", body: r.request().postDataJSON() }); r.fulfill({ status: 202, json: { job: { id: "j1" } } }); });
await page.route("**/api/follow", (r) => { posts.push({ url: "follow", body: r.request().postDataJSON() }); r.fulfill({ status: 202, json: { job: { id: "j2" } } }); });
await page.route("**/catalog/api/entries/e1", (r) => r.fulfill({ json: { id: "e1", name: "Lateral raise" } }));
await page.route("**/api/jobs/**", (r) => r.fulfill({ json: { id: "j", kind: "trainer", status: "running", stage: "upload" } }));
await page.route("**/api/people", (r) => r.fulfill({ status: 202, json: { job: "pj1" } }));
await page.route("**/api/jobs/pj1", (r) => r.fulfill({ json: { id: "pj1", kind: "people", status: "done", result: { people: [{ id: "0", coverage: 0.95, frames: 40, box_mid: [1, 1, 5, 5] }], auto_id: "0" } } }));
await page.route("**/catalog/api/entries", (r) => r.fulfill({ json: { entries: [] } }));

const tid = (id) => page.getByTestId(id);
const shot = (name) => page.screenshot({ path: path.join(out, `${name}.png`), fullPage: true });
const log = (m) => console.log(`ok  ${m}`);

async function watchCountdown() {
  const seen = [];
  const t0 = Date.now();
  while (Date.now() - t0 < 30000) {
    const n = await tid("countdown").count();
    if (!n) { if (seen.length) break; await page.waitForTimeout(50); continue; }
    const v = (await tid("countdown").textContent()).trim();
    if (seen[seen.length - 1] !== v) { seen.push(v); if (v === "4") await shot("02-countdown"); }
    await page.waitForTimeout(80);
  }
  return seen;
}

await page.goto(`${BASE}#/record`);
await tid("cam-start").waitFor();

// Defaults, framing hint (AC-R7).
assert.equal(await tid("countdown-select").inputValue(), "5");
assert.equal(await tid("duration-select").inputValue(), "15");
assert.match(await tid("framing-hint").textContent(), /^Step back until your whole body fits, or at least everything that moves\.$/);
await shot("01-preview");
log("defaults 5 s / 15 s and framing hint");

// AC-R1: countdown 5 + duration 10, hands-free.
await tid("countdown-select").selectOption("5");
await tid("duration-select").selectOption("10");
await tid("cam-start").click();
const seen = await watchCountdown();
assert.deepEqual(seen, ["5", "4", "3", "2", "1"]);
log(`countdown digits ${seen.join(",")}`);
const recStart = Date.now();
await tid("rec-timer").waitFor({ state: "visible" });
await page.waitForTimeout(3000);
await shot("03-recording");
await tid("trim").waitFor({ timeout: 15000 });
const recMs = Date.now() - recStart;
assert.ok(recMs > 9300 && recMs < 11500, `auto-stop after ${recMs} ms`);
log(`auto-stop ${recMs} ms after recording began (no touch)`);
const call = await page.evaluate(() => window.__trimCall);
assert.equal(call.source, "recording");
assert.equal(call.countdownUsed, true);
assert.equal(call.manual, false);
assert.ok(call.size > 1000);
log(`trim editor opened with ${JSON.stringify(call)}`);

// Continue -> save step -> Save posts raw upload, then trim and labels.
await tid("trim-continue").click();
await tid("save").waitFor();
await tid("name").fill("Dumbbell lateral raise");
await tid("tag-input").fill("arms");
await tid("tag-input").press("Enter");
await tid("notes").fill("n");
await shot("04-save-step");
await tid("save").click();
await page.waitForFunction(() => location.hash.startsWith("#/job/"));
const tr = posts.find((p) => p.url === "trainer");
assert.ok(posts.find((p) => p.url === "uploads").bytes > 1000);
assert.deepEqual(tr.body, { upload_id: "u1", name: "Dumbbell lateral raise", category: "exercise", trim: { start_ms: 0, end_ms: 4000 }, labels: { tags: ["arms"], notes: "n" }, people_job: "pj1", person_id: "0" });
log("trainer POST carries upload_id, name, category, trim, labels");

// Selections persist across a reload.
await page.goto(`${BASE}#/record`);
await page.reload();
await tid("cam-start").waitFor();
assert.equal(await tid("countdown-select").inputValue(), "5");
assert.equal(await tid("duration-select").inputValue(), "10");
await tid("countdown-select").selectOption("3");
await tid("duration-select").selectOption("0");
await page.reload();
await tid("cam-start").waitFor();
assert.equal(await tid("countdown-select").inputValue(), "3");
assert.equal(await tid("duration-select").inputValue(), "0");
log("selections persist across reloads (3 s, Manual)");

// Cancel records nothing.
await tid("cam-start").click();
await tid("countdown").waitFor();
await tid("countdown-cancel").click();
await page.waitForTimeout(3600);
assert.equal(await tid("countdown").count(), 0);
assert.equal(await tid("trim").count(), 0);
assert.equal(await tid("rec-timer").isVisible(), false);
assert.equal(await tid("take-preview").isVisible(), false);
assert.equal(await tid("cam-start").isVisible(), true);
assert.equal(await tid("countdown-select").isDisabled(), false);
log("Cancel returns to the preview, nothing recorded");

// Manual: Stop works and is flagged manual; the trim editor's back path returns to the preview.
await tid("countdown-select").selectOption("0");
await tid("cam-start").click();
await tid("cam-stop").waitFor({ state: "visible" });
assert.equal(await tid("countdown").count(), 0);
assert.equal(await tid("duration-select").isDisabled(), true);
await page.waitForTimeout(2200);
await tid("cam-stop").click();
await tid("trim").waitFor();
const manual = await page.evaluate(() => window.__trimCall);
assert.deepEqual([manual.manual, manual.countdownUsed], [true, false]);
await tid("trim-back").click();
await tid("cam-start").waitFor({ state: "visible" });
assert.equal(await tid("trim").count(), 0);
log("Manual stop flagged, editor back returns to the preview");

// Upload path opens the editor with source "upload".
await page.setInputFiles('[data-testid="upload"]', { name: "clip.webm", mimeType: "video/webm", buffer: Buffer.alloc(4096, 1) });
await tid("trim").waitFor();
const up = await page.evaluate(() => window.__trimCall);
assert.deepEqual([up.source, up.countdownUsed, up.manual], ["upload", false, false]);
log("picked file opens the editor as an upload");

// Follower: countdown Off, 5 s, Analyse posts the trim.
posts.length = 0;
await page.goto(`${BASE}#/follow/e1`);
await tid("framing-hint").waitFor();
await tid("countdown-select").selectOption("0");
await tid("duration-select").selectOption("5");
await tid("cam-start").click();
await tid("trim").waitFor({ timeout: 12000 });
await tid("trim-continue").click();
await shot("05-follow-analyse");
await tid("analyse").click();
await page.waitForFunction(() => location.hash.startsWith("#/job/"));
assert.deepEqual(posts.find((p) => p.url === "follow").body, { upload_id: "u1", entry_id: "e1", trim: { start_ms: 0, end_ms: 4000 }, people_job: "pj1", person_id: "0" });
log("follower POST carries trim");

await browser.close();
server.close();
assert.deepEqual(errors, []);
console.log("DRIVE PASS");
