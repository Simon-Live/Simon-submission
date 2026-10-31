// Playwright drive of the follower reference panel (web/reference.js) at 412x915 with Chromium's fake camera and a
// fake API serving a real short mp4 (made with ffmpeg) as the trainer video.
//   PLAYWRIGHT_DIR=/path/to/node_modules/playwright \
//     node tests/part7/drive_reference.mjs <out-dir>
import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const here = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(here, "../../web");
const out = path.resolve(process.argv[2] || path.join(here, "screens"));
fs.mkdirSync(out, { recursive: true });
const work = fs.mkdtempSync(path.join(os.tmpdir(), "simon-ref-"));
const MP4 = path.join(work, "trainer.mp4");
execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x426:rate=25:duration=6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
  "-g", "5", "-movflags", "+faststart", "-y", MP4]);
const mp4 = fs.readFileSync(MP4);
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT_DIR || "playwright");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };

const server = http.createServer((req, res) => {
  const pathname = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (pathname === "/catalog/api/entries/e1/trainer.mp4") { // a real file with Range support, as the catalog serves it
    const m = /bytes=(\d+)-(\d*)/.exec(req.headers.range || "");
    if (!m) { res.writeHead(200, { "content-type": "video/mp4", "accept-ranges": "bytes", "content-length": mp4.length }).end(mp4); return; }
    const a = Number(m[1]), b = m[2] ? Number(m[2]) : mp4.length - 1;
    res.writeHead(206, { "content-type": "video/mp4", "accept-ranges": "bytes", "content-range": `bytes ${a}-${b}/${mp4.length}`, "content-length": b - a + 1 });
    res.end(mp4.subarray(a, b + 1));
    return;
  }
  const rel = pathname.replace(/^\//, "") || "index.html";
  const file = path.resolve(WEB, rel);
  if (!file.startsWith(WEB) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404).end("no"); return; }
  res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const BASE = `http://127.0.0.1:${server.address().port}/`;

const errors = [];
const browser = await chromium.launch({
  args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
});
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, permissions: ["camera"] });
const page = await ctx.newPage();
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
await page.route("**/api/config", (r) => r.fulfill({ json: { limits: { max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000 } } }));
await page.route("**/catalog/api/entries/e1", (r) => r.fulfill({ json: { id: "e1", name: "Lateral raise", video_uri: "trainer.mp4" } }));
await page.route("**/catalog/api/entries", (r) => r.fulfill({ json: { entries: [] } }));
await page.route("**/api/labels", (r) => r.fulfill({ json: {} }));

const tid = (id) => page.getByTestId(id);
const shot = (name) => page.screenshot({ path: path.join(out, `${name}.png`) });
const log = (m) => console.log(`ok  ${m}`);
const refTime = () => tid("reference-video").evaluate((v) => v.currentTime);
const refPlaying = () => tid("reference-video").evaluate((v) => !v.paused);
const box = async (id) => (await tid(id).boundingBox());

await page.goto(`${BASE}#/follow/e1`);
await tid("reference").waitFor();
await page.waitForFunction(() => document.querySelector('[data-testid="reference-video"]').readyState >= 2);
for (const id of ["reference-video", "reference-mirror", "reference-swap"]) assert.equal(await tid(id).count(), 1, id);
assert.equal(await tid("reference").getAttribute("data-mirror"), "true", "mirrored by default");
assert.equal(await refPlaying(), false, "paused before recording");
const over = await box("preview"), pip = await box("reference");
// TICKET-063: beside the camera, never over it (an overlay hid the follower's legs).
assert.ok(pip.width < over.width && pip.x >= over.x + over.width - 1 && Math.abs(pip.y - over.y) < 2, "panel beside the preview on a phone");
log("panel shows beside the preview, not over it");
await shot("1-follow-beside");

// Swap and mirror on the live screen.
await tid("reference-swap").click();
assert.equal(await tid("reference").getAttribute("data-swap"), "true");
const big = await box("reference"), small = await box("preview");
assert.ok(big.width > small.width * 1.5 && big.x + big.width <= small.x + 1, "swap makes the trainer large and the camera small, side by side");
await shot("2-follow-swapped");
await tid("reference-swap").click();
assert.equal(await tid("reference").getAttribute("data-swap"), "false");
await tid("reference-mirror").click();
assert.equal(await tid("reference").getAttribute("data-mirror"), "false");
assert.equal(await tid("reference-video").evaluate((v) => getComputedStyle(v).transform), "none", "unmirrored");
await tid("reference-mirror").click();
assert.match(await tid("reference-video").evaluate((v) => getComputedStyle(v).transform), /matrix\(-1/, "mirrored by default");
log("swap and mirror work");

// Record with a 3 s countdown: the reference holds until zero, then plays from the start.
await tid("countdown-select").selectOption("3");
await tid("duration-select").selectOption("5");
await tid("cam-start").click();
await tid("countdown").waitFor();
await tid("reference-first").waitFor();
assert.equal(await refPlaying(), false, "holds during the countdown");
await shot("3-countdown-first-frame");
await page.waitForFunction(() => document.querySelector('[data-testid="rec-timer"]') && !document.querySelector('[data-testid="rec-timer"]').hidden);
await page.waitForFunction(() => !document.querySelector('[data-testid="reference-video"]').paused);
const t0 = await refTime();
assert.ok(t0 < 1.5, `starts at the countdown end (t=${t0})`);
assert.equal(await tid("reference-video").evaluate((v) => v.muted && v.loop), true, "muted and looping");
await page.waitForTimeout(1500);
const t1 = await refTime();
assert.ok(t1 > t0 + 0.8, `plays with the recording clock (${t0} -> ${t1})`);
await shot("4-recording");
log("starts at the countdown end, muted, looping");

// Trim: the reference sits beside the take and follows its playhead.
await tid("trim-continue").waitFor({ timeout: 20000 });
assert.equal(await refPlaying(), false, "stopped after recording");
const take = await box("trim-start");
const stage = await page.locator(".trim-stage video").boundingBox(), r = await box("reference");
assert.ok(r.x > stage.x + stage.width - 2 && Math.abs(r.y - stage.y) < 4, "reference sits beside the take");
await tid("trim-play").click();
await page.waitForTimeout(1200);
const playing = await refPlaying();
await tid("trim-play").click();
assert.equal(playing, true, "plays along with Play selection");
await page.waitForTimeout(300);
const near = async (label, offset = 0) => {
  const take = await page.locator(".trim-stage video").evaluate((v) => v.currentTime);
  const ref = await refTime();
  const dur = await tid("reference-video").evaluate((v) => v.duration);
  const want = (((take + offset) % dur) + dur) % dur;
  assert.ok(Math.abs(ref - want) < 0.25, `${label}: reference ${ref} follows take ${take} (+${offset})`);
};
await near("after play");
const tb = await page.locator(".trim-track").boundingBox();
await page.mouse.click(tb.x + tb.width * 0.6, tb.y + tb.height / 2);
await page.waitForTimeout(500);
await near("after scrub");
await tid("reference-offset").fill("1000");
await page.waitForTimeout(500);
await near("with offset", 1);
await shot("5-trim-follow");
log("follows the trim playhead, with the offset slider");
assert.equal(await tid("reference-swap").isVisible(), false, "no swap in the trim editor");

// Back to the preview: the panel returns beside the camera.
await tid("trim-back").click();
await tid("reference").waitFor();
assert.equal(await tid("reference").getAttribute("data-mode"), "live");
log("returns to the preview after Record again");

assert.deepEqual(errors, [], `no console errors: ${errors.join("; ")}`);
await browser.close();
server.close();
fs.rmSync(work, { recursive: true, force: true });
console.log("PASS drive_reference");
