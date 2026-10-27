// Drives the served demo viewer in headless Chromium and writes the demo package media.
//
//   scripts/with-browser-slot.sh node demo/capture.mjs [--url http://127.0.0.1:8733/] [--out demo]
//
// Start the page first with `make demo` (and `make demo-data` for web/data/demo.json).
// Writes front.png, side.png, top.png, toggle-off.png (1440x900), phone.png (390x844) and
// viewer.webm (1280x720, about 20 s) into --out. Prints a JSON summary; exits 0 only when
// the console is clean, the page's agreement figure equals demo.json, nothing scrolls sideways at
// 390 px, the take toggle hides the take in the 3D rig, Space and the arrow keys work, a mouse wheel
// redraws the paused overlap panel, and every file was written.
// Offline: the only requests go to the page being served.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "/home/gingy/.npm/_npx/9833c18b2d85bc59/node_modules/playwright/index.mjs";

const args = parseArgs(process.argv.slice(2));
const baseUrl = (args.url || "http://127.0.0.1:8733/").replace(/\/?$/, "/");
const outDir = path.resolve(args.out || "demo");
const SETTLE_MS = 700; // camera fly-to is 450 ms, plus a render
const VIDEO_MIN_MS = 18000;
const VIDEO_RANGE_S = [15, 25];
const consoleErrors = [];
const files = {};

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 2) {
    if (!argv[i].startsWith("--") || argv[i + 1] === undefined) throw new Error(`usage: capture.mjs [--url U] [--out DIR] (got ${argv[i]})`);
    out[argv[i].slice(2)] = argv[i + 1];
  }
  return out;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function watch(page, label) {
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(`${label} console: ${msg.text()}`);
  });
  page.on("pageerror", (error) => consoleErrors.push(`${label} pageerror: ${error.message}`));
  page.on("requestfailed", (request) => consoleErrors.push(`${label} requestfailed: ${request.url()}`));
}

async function openPage(context, label) {
  const page = await context.newPage();
  watch(page, label);
  await page.goto(baseUrl, { waitUntil: "load" });
  await page.waitForFunction(() => window.viewerReady === true, null, { timeout: 30000 });
  return page;
}

// Frame of the deepest squat: the take-1 output frame whose hips are closest to the ankles.
function deepestFrame(demo) {
  let best = 0;
  let bestHeight = Infinity;
  demo.takes[0].output.forEach((joints, i) => {
    if (!joints) return;
    const hips = (joints[11][1] + joints[12][1]) / 2;
    const ankles = Math.min(joints[15][1], joints[16][1]);
    if (hips - ankles < bestHeight) {
      bestHeight = hips - ankles;
      best = i;
    }
  });
  return best;
}

async function shot(page, name, options = {}) {
  const file = path.join(outDir, name);
  await page.screenshot({ path: file, ...options });
  files[name] = fs.statSync(file).size;
}

async function pauseAt(page, frame) {
  if (await page.evaluate(() => window.viewer.playing)) await page.click("#btn-play");
  await page.fill("#scrub", String(frame));
  await sleep(250);
}

const sameTakes = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const nextFrames = (page, count = 2) => page.evaluate(
  (n) => new Promise((resolve) => { const tick = (left) => (left ? requestAnimationFrame(() => tick(left - 1)) : resolve()); tick(n); }),
  count,
);

// AC-V2 in the 3D rig: the takes drawn in the overlap panel (rig visibility), not the legend class.
const takesDrawn = (page) => page.evaluate(() => window.viewer.visibleTakes());

// AC-V3 by keyboard: Space toggles playing (state and button text), arrow keys step one frame while paused.
// The focus is moved off the slider so the document key handler is the one under test.
async function keyboardChecks(page) {
  await page.evaluate(() => { if (window.viewer.playing) window.viewer.pause(); document.activeElement.blur(); });
  const state = () => page.evaluate(() => ({ playing: window.viewer.playing, text: document.getElementById("btn-play").textContent, frame: window.viewer.frame, count: window.viewer.frameCount }));
  const idle = await state();
  await page.keyboard.press("Space");
  const started = await state();
  await page.keyboard.press("Space");
  const stopped = await state();
  const spaceOk = !idle.playing && idle.text === "Play" && started.playing && started.text === "Pause" && !stopped.playing && stopped.text === "Play";
  await page.keyboard.press("ArrowRight");
  const right = await state();
  await page.keyboard.press("ArrowLeft");
  const left = await state();
  const arrowOk = !right.playing && right.frame === (stopped.frame + 1) % stopped.count && left.frame === stopped.frame;
  return { spaceOk, arrowOk };
}

// B1 (AC-V3): with playback paused, a mouse wheel over the overlap panel must redraw it. Two screenshots with
// no input prove the paused panel is otherwise stable, so a difference after the wheel is the zoom.
async function pausedWheelRedraws(page) {
  await page.evaluate(() => { if (window.viewer.playing) window.viewer.pause(); });
  const stage = page.locator("#overlap-stage");
  await nextFrames(page);
  const before = await stage.screenshot();
  await nextFrames(page);
  const idle = await stage.screenshot();
  const box = await page.locator("#overlap-stage canvas").boundingBox();
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
  await page.mouse.wheel(0, -500);
  await nextFrames(page);
  const zoomed = await stage.screenshot();
  return { idleStable: before.equals(idle), redraws: !idle.equals(zoomed) };
}

async function desktopShots(browser, frame) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await openPage(context, "desktop");
  await pauseAt(page, frame);
  for (const view of ["front", "side", "top"]) {
    await page.click(`#btn-${view}`);
    await sleep(SETTLE_MS);
    await shot(page, `${view}.png`);
  }
  await page.click("#btn-front");
  const drawnBefore = await takesDrawn(page);
  await page.uncheck("#take-4");
  await sleep(SETTLE_MS);
  await shot(page, "toggle-off.png");
  const legendOff = await page.evaluate(() => document.querySelector('#legend li[data-take="4"]').classList.contains("off"));
  const drawnOff = await takesDrawn(page);
  await page.check("#take-4");
  const drawnBack = await takesDrawn(page);
  const hidesIn3d = sameTakes(drawnBefore, [1, 2, 3, 4]) && sameTakes(drawnOff, [1, 2, 3]) && sameTakes(drawnBack, [1, 2, 3, 4]);
  const agreementText = (await page.textContent("#agreement-p95")).trim();
  const keyboard = await keyboardChecks(page);
  const wheel = await pausedWheelRedraws(page);
  await context.close();
  return { agreementText, takeFourHidden: legendOff, hidesIn3d, keyboard, wheel };
}

async function phoneShot(browser, frame) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  const page = await openPage(context, "phone");
  await pauseAt(page, frame);
  await sleep(SETTLE_MS);
  const metrics = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth }));
  await shot(page, "phone.png", { fullPage: true });
  await context.close();
  return { ...metrics, ok: metrics.scroll <= metrics.inner };
}

// Real mouse drags on the overlap canvas orbit the camera.
async function orbitDrag(page, box, dx, steps, stepMs) {
  const y = box.y + box.height * 0.5;
  const x0 = box.x + box.width * 0.5 - dx / 2;
  await page.mouse.move(x0, y);
  await page.mouse.down();
  for (let s = 1; s <= steps; s++) {
    await page.mouse.move(x0 + (dx * s) / steps, y);
    await sleep(stepMs);
  }
  await page.mouse.up();
}

async function recordVideo(browser) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "simon-video-"));
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
    recordVideo: { dir: tmp, size: { width: 1280, height: 720 } },
  });
  const started = Date.now();
  const page = await openPage(context, "video");
  const box = await page.locator("#overlap-stage canvas").boundingBox();
  if ((await page.evaluate(() => window.viewer.playing)) === false) await page.click("#btn-play");
  await sleep(2000); // the squat plays in the three-quarter view
  await orbitDrag(page, box, 340, 60, 30); // real mouse drags orbit the overlap camera
  await orbitDrag(page, box, -480, 80, 30);
  await page.click("#btn-side");
  await sleep(1800);
  await page.click("#btn-top");
  await sleep(1800);
  await page.click("#btn-front");
  await sleep(1200);
  await page.uncheck("#take-4"); // a take disappears from the overlap
  await sleep(1300);
  await page.check("#take-4");
  await page.click("#btn-reset");
  await sleep(700);
  await orbitDrag(page, box, 520, 90, 30);
  await sleep(Math.max(1000, VIDEO_MIN_MS - (Date.now() - started))); // the clip must run 15 to 25 s
  const seconds = (Date.now() - started) / 1000;
  const video = page.video();
  await context.close(); // flushes the recording
  const target = path.join(outDir, "viewer.webm");
  await video.saveAs(target);
  await video.delete();
  fs.rmSync(tmp, { recursive: true, force: true });
  files["viewer.webm"] = fs.statSync(target).size;
  return seconds;
}

async function main() {
  fs.mkdirSync(outDir, { recursive: true });
  const demo = await (await fetch(`${baseUrl}data/demo.json`)).json();
  const agreementJson = demo.metrics.thresholds.joint_angle_agreement_p95_deg.value;
  const frame = deepestFrame(demo);
  const browser = await chromium.launch({ headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
  let desktop = { keyboard: {}, wheel: {} };
  let phone = { ok: false };
  let videoSeconds = 0;
  try {
    desktop = await desktopShots(browser, frame);
    phone = await phoneShot(browser, frame);
    videoSeconds = await recordVideo(browser);
  } finally {
    await browser.close();
  }
  const expected = Number(agreementJson).toFixed(3);
  const agreementOk = desktop.agreementText === expected && Number(desktop.agreementText) === Number(agreementJson);
  const summary = {
    console_errors: consoleErrors,
    agreement_page: desktop.agreementText,
    agreement_json: expected,
    phone_scroll_ok: phone.ok,
    phone_scroll_width: phone.scroll,
    phone_inner_width: phone.inner,
    toggle_off_marks_take_4: desktop.takeFourHidden === true,
    toggle_hides_take_in_3d: desktop.hidesIn3d === true,
    keyboard_space_ok: desktop.keyboard.spaceOk === true,
    keyboard_arrow_ok: desktop.keyboard.arrowOk === true,
    paused_idle_stable: desktop.wheel.idleStable === true,
    paused_wheel_redraws: desktop.wheel.redraws === true,
    squat_frame: frame,
    video_seconds: Math.round(videoSeconds * 10) / 10,
    files,
  };
  const expectedFiles = ["front.png", "side.png", "top.png", "toggle-off.png", "phone.png", "viewer.webm"];
  const videoOk = videoSeconds >= VIDEO_RANGE_S[0] && videoSeconds <= VIDEO_RANGE_S[1];
  const interactionOk = desktop.hidesIn3d === true && desktop.keyboard.spaceOk === true && desktop.keyboard.arrowOk === true
    && desktop.wheel.idleStable === true && desktop.wheel.redraws === true;
  const ok = consoleErrors.length === 0 && agreementOk && phone.ok && desktop.takeFourHidden === true && interactionOk && videoOk
    && expectedFiles.every((name) => files[name] > 0);
  console.log(JSON.stringify(summary, null, 2));
  process.exit(ok ? 0 : 1);
}

main().catch((error) => {
  console.log(JSON.stringify({ console_errors: consoleErrors, error: String(error && error.stack ? error.stack : error), files }, null, 2));
  process.exit(1);
});
