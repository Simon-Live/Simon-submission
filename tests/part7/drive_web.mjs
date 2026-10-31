// One Playwright drive of the web screens against tests/part7/fake_api.py at 412x915.
// Run:
//   node tests/part7/drive_web.mjs <out-dir>
// PLAYWRIGHT_DIR may point at a node_modules/playwright install when `playwright` does not resolve.
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.resolve(process.argv[2] || path.join(here, "../../qa/screenshots/web"));
mkdirSync(out, { recursive: true });
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_DIR || "playwright");

const PORT = 18000 + Math.floor(Math.random() * 1000);
const BASE = `http://127.0.0.1:${PORT}/`;
const server = spawn("python3", [path.join(here, "fake_api.py"), String(PORT)], { stdio: "inherit" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
for (let i = 0; i < 50; i++) {
  try { if ((await fetch(`${BASE}api/health`)).ok) break; } catch { await sleep(100); }
}

const errors = [];
const shot = (page, name) => page.screenshot({ path: path.join(out, `${name}.png`), fullPage: true });
const state = async () => (await fetch(`${BASE}__test/state`)).json();
const tid = (page, id) => page.getByTestId(id);

const browser = await chromium.launch({
  args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
});
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, permissions: ["camera"] });
const page = await ctx.newPage();
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });

// The trim step ends every take; its Continue button hands the range to the people check.
const continueFromTrim = async () => {
  await tid(page, "trim-continue").waitFor({ timeout: 20000 });
  await tid(page, "trim-continue").click();
};

let step = "start";
try {
  // 1. Home
  step = "home";
  await page.goto(BASE);
  await tid(page, "entry-lateral-raise").waitFor();
  assert.equal(await page.locator("[data-testid^=entry-]").count(), 3);
  assert.match(await tid(page, "entry-lateral-raise").innerText(), /VIDEO/i);
  assert.doesNotMatch(await tid(page, "entry-reverse-lunge").innerText(), /VIDEO/i);
  await shot(page, "01-home");
  await tid(page, "search").fill("salsa");
  assert.equal(await page.locator("[data-testid^=entry-]").count(), 1);
  await tid(page, "search").fill("zzzz");
  assert.equal(await page.locator("[data-testid^=entry-]").count(), 0);
  await tid(page, "empty").waitFor();
  await shot(page, "02-home-no-match");
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);

  // 3. Watch
  step = "watch";
  await tid(page, "search").fill("");
  await tid(page, "entry-lateral-raise").click();
  await page.waitForURL(/#\/watch\/lateral-raise/);
  const video = tid(page, "trainer-video");
  await video.waitFor();
  assert.match(await video.getAttribute("src"), /^catalog\/api\/entries\/lateral-raise\/video\.webm$/);
  await video.evaluate((v) => v.play());
  await page.waitForFunction(() => document.querySelector("[data-testid=trainer-video]").currentTime > 0.3);
  assert.ok((await state()).range_requests >= 1, "video fetched with Range");
  await tid(page, "viewer").locator("canvas").waitFor();
  await tid(page, "watch-frame").waitFor();
  await tid(page, "follow").waitFor();
  await video.evaluate((v) => v.pause());
  await shot(page, "03-watch");
  // hand-off: foreign origin ignored, same origin navigates
  const sendMsg = (origin) => page.evaluate((o) => window.dispatchEvent(new MessageEvent("message", { data: { type: "simon:follow", id: "salsa-basic" }, origin: o })), origin);
  await sendMsg("https://evil.example");
  await sleep(300);
  assert.match(page.url(), /#\/watch\/lateral-raise/);
  await sendMsg(new URL(BASE).origin);
  await page.waitForURL(/#\/follow\/salsa-basic/);

  // watch: no animation, no video, missing
  step = "watch-variants";
  await page.goto(`${BASE}#/watch/reverse-lunge`);
  await tid(page, "viewer-empty").waitFor();
  assert.equal(await tid(page, "viewer-empty").innerText(), "This movement has no 3D animation yet.");
  assert.equal(await page.locator("[data-testid=trainer-video]").count(), 0);
  await page.goto(`${BASE}#/watch/nope`);
  await tid(page, "not-found").waitFor();
  assert.equal(await page.locator("[data-testid=trainer-video]").count(), 0);
  await shot(page, "04-watch-not-found");

  // 2. Record: camera. The take flow is record, trim, people check, details, save (take-flow.js).
  step = "record-camera";
  await page.goto(`${BASE}#/record`);
  await tid(page, "cam-start").waitFor();
  await shot(page, "05-record");
  assert.equal(await tid(page, "preview").evaluate((v) => getComputedStyle(v).transform), "matrix(-1, 0, 0, 1, 0, 0)");
  await tid(page, "countdown-select").selectOption("0");
  await tid(page, "duration-select").selectOption("5");
  await tid(page, "cam-start").click();
  await continueFromTrim();
  await tid(page, "name").waitFor();
  assert.equal(await page.locator("[data-testid=people]").count(), 0, "one person skips the picker");
  await tid(page, "save").click();
  await tid(page, "name-error").waitFor();
  assert.equal(Object.keys((await state()).jobs).length, 0);
  assert.match(page.url(), /#\/record/);
  await shot(page, "06-record-name-error");
  await tid(page, "name").fill("Dumbbell lateral raise");
  await shot(page, "08-record-take");
  await tid(page, "save").click();
  await page.waitForURL(/#\/job\/job1/);
  const st = await state();
  assert.ok(st.uploads[0].size > 1000 && st.uploads[0].type.startsWith("video/webm"), JSON.stringify(st.uploads));
  assert.equal(st.people_jobs, 1, "the people check ran once, after the trim");

  // 5. Job stages
  step = "job";
  await tid(page, "stage").first().waitFor();
  assert.equal(await tid(page, "stage").count(), 6);
  await shot(page, "09-job-queued");
  await page.waitForSelector("[data-stage=pose][data-state=current]", { timeout: 10000 });
  await shot(page, "10-job-running");
  await tid(page, "open").waitFor({ timeout: 15000 });
  assert.match(await tid(page, "open").getAttribute("href"), /#\/watch\/lateral-raise/);
  await shot(page, "11-job-done");
  // reload resumes
  await page.reload();
  await tid(page, "stage").first().waitFor();

  // upload fallback + failure with Try again
  step = "record-upload";
  const videoBytes = Buffer.from(await (await fetch(`${BASE}catalog/api/entries/lateral-raise/video.webm`)).arrayBuffer());
  const file = path.join(tmpdir(), "simon-drive-take.webm");
  writeFileSync(file, videoBytes);
  await page.goto(`${BASE}#/record`);
  await tid(page, "upload").setInputFiles(file);
  await continueFromTrim();
  await tid(page, "name").fill("Fails");
  await tid(page, "save").click();
  await page.waitForURL(/#\/job\/bad/);
  await tid(page, "retry").waitFor();
  await shot(page, "12-job-failed");
  assert.match(await tid(page, "retry").getAttribute("href"), /#\/record/);

  // camera refused in a fresh context
  step = "camera-refused";
  const denied = await browser.newContext({ viewport: { width: 412, height: 915 } });
  await denied.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("denied", "NotAllowedError"));
  });
  const dp = await denied.newPage();
  await dp.goto(`${BASE}#/record`);
  await tid(dp, "cam-start").click();
  assert.equal(await tid(dp, "capture-error").innerText(), "Camera access is off. Allow it in the browser, or upload a video.");
  await shot(dp, "13-camera-refused");
  await denied.close();

  // 4. Follow
  step = "follow";
  await page.goto(`${BASE}#/follow/lateral-raise`);
  await tid(page, "upload").waitFor();
  assert.equal(await tid(page, "analyse").isVisible(), false, "Analyse waits for a take");
  await tid(page, "upload").setInputFiles(file);
  await continueFromTrim();
  await tid(page, "analyse").waitFor();
  await shot(page, "14-follow");
  await tid(page, "analyse").click();
  await page.waitForURL(/#\/job\/job\d+/);
  const s2 = await state();
  const follow = Object.values(s2.jobs).find((j) => j.kind === "follow");
  assert.equal(follow.entry_id, "lateral-raise");
  await page.waitForURL(/#\/result\/job\d+/, { timeout: 15000 });
  await shot(page, "15-follow-to-result");
  await page.goto(`${BASE}#/follow/nope`);
  await tid(page, "not-found").waitFor();

  // fixture result route
  step = "result";
  await page.goto(`${BASE}#/result/fixture`);
  await tid(page, "score").waitFor();
  await shot(page, "16-result-fixture");

  // desktop: no horizontal scroll
  step = "desktop";
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(BASE);
  await tid(page, "entry-lateral-raise").waitFor();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await shot(page, "17-home-desktop");

  assert.deepEqual(errors, [], "no console errors");
  console.log("DRIVE OK");
} catch (e) {
  console.error(`DRIVE FAILED at ${step}:`, e.message);
  await shot(page, "failure").catch(() => {});
  process.exitCode = 1;
} finally {
  await browser.close();
  server.kill();
}
