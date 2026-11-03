// Follow capture: the trainer and the camera side by side (docs/specs/follow-side-by-side.md, TICKET-291), on the real
// app over tests/part7/fake_api.py with Chrome's fake camera. At each viewport it measures the trainer box (.ref-stage)
// and the camera box (.cam) before Record and while recording: side by side means the same top and height, no overlap
// and both inside the viewport under the sticky header; the negative is that neither is ever hidden, covered or off screen.
//   PLAYWRIGHT_DIR=<node_modules> /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/follow-side.browser.mjs [shots-dir]
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"))("playwright");
const shots = process.argv[2] ? path.resolve(process.argv[2]) : null;
if (shots) fs.mkdirSync(shots, { recursive: true });

const PORT = 8000 + Math.floor(Math.random() * 900);
const BASE = `http://127.0.0.1:${PORT}`;
const server = spawn("python3", [path.join(here, "fake_api.py"), String(PORT)], { stdio: "ignore" });
process.on("exit", () => server.kill());
process.on("uncaughtException", (e) => { console.error(e); process.exit(1); });
for (let i = 0; i < 80; i++) {
  try { if ((await fetch(`${BASE}/api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 100)); }
}

const VIEWPORTS = [
  { name: "desktop", width: 1728, height: 925, layout: "side" },
  { name: "laptop", width: 1280, height: 720, layout: "side" },
  { name: "tablet", width: 1024, height: 768, layout: "side" },
  { name: "phone-portrait", width: 390, height: 844, layout: "side" },
  { name: "phone-landscape", width: 844, height: 390, layout: "side" },
  { name: "small-phone", width: 320, height: 568, layout: "side" },
  // under 200 px no column keeps 40%: the boxes stack. The routine's title block alone is taller than such a screen,
  // so here the check is the order and that neither box is hidden; the box sizing is in follow-layout.unit.test.mjs.
  { name: "narrow-portrait", width: 180, height: 640, layout: "stack" },
];
const TOL = 2;
const browser = await chromium.launch({ args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"] });
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };

/** The two boxes, the header's bottom and whether each box's centre is really that box (not covered). */
const measure = (page) => page.evaluate(() => {
  const rect = (el) => { const b = el.getBoundingClientRect(); return { left: b.left, top: b.top, right: b.right, bottom: b.bottom, width: b.width, height: b.height }; };
  const row = document.querySelector(".ref-row");
  const ref = document.querySelector(".ref-row .ref-stage");
  const cam = document.querySelector(".ref-row .cam");
  const header = document.querySelector("header.bar");
  const mine = (el) => { const b = el.getBoundingClientRect(); const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2); return Boolean(hit && el.contains(hit)); };
  const shown = (el) => { const s = getComputedStyle(el); return s.display !== "none" && s.visibility !== "hidden" && Number(s.opacity) > 0; };
  return {
    layout: row.dataset.layout, ref: rect(ref), cam: rect(cam), headerBottom: header ? header.getBoundingClientRect().bottom : 0,
    vw: window.innerWidth, vh: window.innerHeight, rowRight: row.getBoundingClientRect().right,
    refShown: shown(ref) && mine(ref), camShown: shown(cam) && mine(cam),
  };
});

function assertStack(m, vp, when) {
  const at = `${vp.width}x${vp.height} ${when}`;
  assert.equal(m.layout, "stack", `${at}: layout`);
  for (const b of [m.ref, m.cam]) assert.ok(b.width > 40 && b.height >= 80, `${at}: negative: no box is zero sized`);
  assert.ok(m.ref.bottom <= m.cam.top + TOL, `${at}: stacked, the trainer above the camera with no overlap`);
  assert.ok(Math.abs(m.ref.height - m.cam.height) <= TOL, `${at}: same height`);
}

function assertBoxes(m, vp, when) {
  if (vp.layout === "stack") return assertStack(m, vp, when);
  const at = `${vp.width}x${vp.height} ${when}`;
  assert.equal(m.layout, vp.layout, `${at}: layout`);
  for (const [k, b] of [["trainer", m.ref], ["camera", m.cam]]) {
    assert.ok(b.width > 40 && b.height > 40, `${at}: the ${k} box has a size (${b.width}x${b.height})`);
    assert.ok(b.top >= m.headerBottom - TOL, `${at}: the ${k} box starts under the header (${b.top} < ${m.headerBottom})`);
    assert.ok(b.bottom <= m.vh + TOL, `${at}: the ${k} box ends on screen (${b.bottom} > ${m.vh})`);
    assert.ok(b.left >= -TOL && b.right <= m.vw + TOL, `${at}: the ${k} box is inside the width`);
  }
  assert.ok(m.refShown, `${at}: negative: the trainer box is not hidden or covered`);
  assert.ok(m.camShown, `${at}: negative: the camera box is not hidden or covered`);
  assert.ok(Math.abs(m.ref.height - m.cam.height) <= TOL, `${at}: same height (${m.ref.height} vs ${m.cam.height})`);
  assert.ok(Math.abs(m.ref.top - m.cam.top) <= TOL, `${at}: same top (${m.ref.top} vs ${m.cam.top})`);
  assert.ok(m.ref.right <= m.cam.left + TOL || m.cam.right <= m.ref.left + TOL, `${at}: no overlap side by side`);
  if (vp.width < vp.height) assert.ok(m.ref.width / vp.width >= 0.4 && m.cam.width / vp.width >= 0.4, `${at}: each column keeps 40% of the width`);
}

const big = (page, testid) => page.getByTestId(testid).evaluate((el) => { const b = el.getBoundingClientRect(); return Math.min(b.width, b.height); });

async function run(vp, reducedMotion = "no-preference") {
  const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, permissions: ["camera", "microphone"], reducedMotion });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${BASE}/?profile=submission#/follow/lateral-raise`);
  await page.locator(`.ref-row[data-layout="${vp.layout}"]`).waitFor();
  await page.locator('.cam[data-state="preview"]').waitFor();
  await page.locator('[data-testid="ghost-canvas"]').waitFor({ state: "attached" });
  await page.locator(".splash").waitFor({ state: "hidden" }); // the opening splash covers the page until it fades
  const at = `${vp.width}x${vp.height}`;
  if (vp.layout === "side") {
    for (const id of ["cam-start", "reference-mirror", "reference-swap", "countdown-select"]) {
      assert.ok(await big(page, id) >= 44 - 0.5, `${at}: ${id} is at least 44 px`);
    }
  }

  // before Record: bring the row in view the way a person does (just under the header), then measure
  await page.evaluate(() => {
    const head = document.querySelector("header.bar").getBoundingClientRect().height;
    window.scrollTo(0, window.scrollY + document.querySelector(".ref-row").getBoundingClientRect().top - head - 8);
  });
  const before = await measure(page);
  assertBoxes(before, vp, "before Record");
  // the ghost canvas stays over the camera picture
  const ghost = await page.evaluate(() => {
    const g = document.querySelector('[data-testid="ghost-canvas"]').getBoundingClientRect();
    const c = document.querySelector(".ref-row .cam").getBoundingClientRect();
    return g.width > 0 && g.left >= c.left - 1 && g.right <= c.right + 1 && g.top >= c.top - 1 && g.bottom <= c.bottom + 1;
  });
  assert.ok(ghost, `${at}: the ghost canvas lies over the camera box`);
  if (shots) await page.screenshot({ path: path.join(shots, `${vp.name}-${at}-preview.png`) });

  // Record from the bottom of the page: the countdown brings the row back in view (AC-3)
  await page.getByTestId("countdown-select").selectOption("3");
  await page.getByTestId("cam-start").scrollIntoViewIfNeeded();
  if (vp.layout === "side") await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await page.getByTestId("cam-start").click();
  await page.locator('.cam[data-state="counting"]').waitFor();
  await page.waitForTimeout(reducedMotion === "reduce" ? 50 : 900);
  const counting = await measure(page);
  assertBoxes(counting, vp, "in the countdown");
  await page.locator('.cam[data-state="recording"]').waitFor({ timeout: 8000 });
  await page.waitForTimeout(400);
  const recording = await measure(page);
  assertBoxes(recording, vp, "while recording");
  if (shots) await page.screenshot({ path: path.join(shots, `${vp.name}-${at}-recording${reducedMotion === "reduce" ? "-reduced" : ""}.png`) });
  assert.ok(await big(page, "cam-stop") >= 44 - 0.5, `${at}: Stop is at least 44 px`);
  await page.getByTestId("cam-stop").scrollIntoViewIfNeeded();
  await page.getByTestId("cam-stop").click();
  assert.ok(recording.rowRight <= vp.width + 1, `${at}: the row stays inside the screen's width`); // the page's own scrollWidth at 1024 px is wider at base too
  assert.deepEqual(errors, [], `${at}: no page errors`);
  await ctx.close();
  return recording;
}

try {
  for (const vp of VIEWPORTS) {
    await run(vp);
    ok(`${vp.width}x${vp.height}: ${vp.layout === "side" ? "side by side, both boxes whole on screen" : "stacked, trainer above camera, neither hidden"} before Record, in the countdown and while recording`);
  }
  await run(VIEWPORTS.find((v) => v.width === 390), "reduce");
  ok("390x844 reduced motion: the row is in view at once when the countdown starts");

  // swap still swaps the two columns, and they stay side by side
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 }, permissions: ["camera", "microphone"] });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/#/follow/lateral-raise`);
  await page.locator('.ref-row[data-layout="side"]').waitFor();
  const leftOf = () => page.evaluate(() => document.querySelector(".ref-row .ref-stage").getBoundingClientRect().left < document.querySelector(".ref-row .cam").getBoundingClientRect().left);
  assert.equal(await leftOf(), true, "the trainer is on the left");
  await page.getByTestId("reference-swap").click();
  assert.equal(await leftOf(), false, "swapped, the camera is on the left");
  await ctx.close();
  ok("1280x720: Swap views swaps the two columns");
} finally {
  await browser.close();
  server.kill();
}
console.log(`${passed} passed`);
process.exit(0);
