// The 3D compare on the result screen still turns under a drag (compare-view.md AC-C2b, model-skin.md AC16), at Pixel 7
// 412x915 on the client stage with the model picker and Any body under the canvas. Run (through scripts/with-browser-slot.sh):
//   node tests/part7/orbit_drag.browser.mjs
// Playwright comes from `npm i` in this repo, or from PLAYWRIGHT_DIR (a node_modules folder).
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";
import { isResultScreen404 } from "./lane_modules.mjs";
import { dragCanvas } from "../../staging/drive.mjs";   // the staging j6 drag itself

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium, devices } = req("playwright");

const { server, port } = await serveRoot();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };

try {
  const ctx = await browser.newContext({ ...devices["Pixel 7"], viewport: { width: 412, height: 915 } });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text()) && !isResultScreen404(m.location().url)) errors.push(m.text()); });
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/result-additions.html?case=fixture`);
  await page.waitForFunction(() => window.__ready === true);
  const v3 = page.getByTestId("stage-view-3d");   // the 3D view of the client stage (the switch is hidden when 3D is the only view)
  if (await v3.isVisible()) await v3.click();
  assert.equal(await v3.getAttribute("aria-pressed"), "true");
  const compare = page.getByTestId("compare");
  const canvas = compare.locator("canvas");
  await compare.waitFor({ state: "visible" });
  await canvas.scrollIntoViewIfNeeded();
  await page.waitForTimeout(400);

  const az = async () => Number(await compare.getAttribute("data-camera-azimuth"));
  const drag = () => dragCanvas(page, compare);
  // the follower's nose to ankle in px: it shrinks when the back-off moves the camera away
  const span = () => page.evaluate(async () => {
    const s = window.__r.compare.stage;
    for (let i = 0; i < 3; i++) { s.render(); await new Promise(requestAnimationFrame); }
    const a = s.jointScreen(1, 0), b = s.jointScreen(1, 15);
    return Math.hypot(a.x - b.x, a.y - b.y);
  });
  // a skin 3 m tall at the follower's pelvis: far into the Trainer and You chips, so the back-off has work to do
  const setTallSkin = () => page.evaluate(async () => {
    const THREE = await import("/web/vendor/three/three.module.min.js");
    const object3d = new THREE.Mesh(new THREE.BoxGeometry(0.3, 3, 0.3), new THREE.MeshBasicMaterial({ color: 0x88ff00 }));
    window.__r.compare.stage.setSkin(1, { object3d, setPose() {}, setGhost() {}, dispose() {},
      stats: () => ({ kind: "test", id: "tall-box", segErrDeg: 0, footY: 0 }) });
  });

  // nothing covers the canvas: its centre and quarter points hit the canvas itself
  const hits = await canvas.evaluate((c) => {
    const r = c.getBoundingClientRect();
    return [[0.5, 0.5], [0.25, 0.5], [0.75, 0.5], [0.5, 0.25], [0.5, 0.75]].map(([fx, fy]) => document.elementFromPoint(r.left + r.width * fx, r.top + r.height * fy) === c);
  });
  assert.deepEqual(hits, [true, true, true, true, true], "an element covers the 3D canvas");
  // why the old j6 drag missed: the middle of the compare section is the play bar once the tools row wraps under the canvas
  const mid = await compare.evaluate((n) => { const r = n.getBoundingClientRect(); const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return e ? e.className || e.tagName : ""; });
  console.log(`# the compare section's middle hits "${mid}"`);
  ok("no overlay covers the 3D canvas (centre and quarter points)");

  const a0 = await az();
  await drag();
  const a1 = await az();
  assert.ok(Math.abs(a1 - a0) > 10, `first drag moved the azimuth ${a0} -> ${a1}`);
  ok(`a drag across the canvas rotates the compare (${a0} -> ${a1})`);

  const before = await span();
  await setTallSkin();
  await page.waitForFunction(() => document.querySelector('[data-testid="compare"]').dataset.skinKind === "-,test");
  const after = await span();
  assert.equal(await az(), a1, "the skin load left the azimuth alone");
  assert.ok(Math.abs(after - before) < 0.5, `after a hand drag the back-off moved the camera: span ${before.toFixed(1)} -> ${after.toFixed(1)} px`);
  ok("after the viewer has dragged, a skin load does not move the camera (no back-off, same azimuth)");

  await drag();
  const a2 = await az();
  assert.ok(Math.abs(a2 - a1) > 10, `second drag after the skin moved the azimuth ${a1} -> ${a2}`);
  ok(`a second drag after the skin loads still rotates (${a1} -> ${a2})`);

  // a view button hands the camera back to the framing: it backs off for the tall skin by distance only
  await page.getByTestId("view-front").click();
  await page.waitForTimeout(300);
  const framed = await span();
  assert.equal(await az(), 0, "the back-off left the Front view's azimuth at 0");
  assert.equal(Number(await compare.getAttribute("data-camera-elevation")), 8, "the back-off left the Front view's elevation at 8");
  const unframed = await page.evaluate(async () => {
    const s = window.__r.compare.stage;
    s.setSkin(1, null);
    for (let i = 0; i < 3; i++) { s.render(); await new Promise(requestAnimationFrame); }
    const a = s.jointScreen(1, 0), b = s.jointScreen(1, 15);
    return Math.hypot(a.x - b.x, a.y - b.y);
  });
  assert.ok(framed < unframed * 0.9, `negative: after setView the back-off does move the camera back (span ${unframed.toFixed(1)} -> ${framed.toFixed(1)} px)`);
  ok(`after setView the back-off frames the skin by distance only (span ${unframed.toFixed(0)} -> ${framed.toFixed(0)} px, azimuth 0)`);

  await drag();
  assert.ok(Math.abs((await az()) - 0) > 10, "a drag after the framing still rotates");
  ok("a drag after the framing still rotates");

  assert.deepEqual(errors, []);
  ok("no page errors");
} finally {
  await browser.close();
  server.close();
}
console.log(`# pass ${passed}`);
