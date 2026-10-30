// Browser checks for the result experience at 412x915 (compare-view.md AC-C2..C8, journey.md AC-J7..J9,
// app.md AC-A5, A12). Run:
//   node tests/part7/result.browser.mjs
// Playwright comes from `npm i` in this repo, or from PLAYWRIGHT_DIR (a node_modules folder).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const SHOTS = process.env.SHOTS_DIR || path.join(here, "screens");
fs.mkdirSync(SHOTS, { recursive: true });
const analysis = JSON.parse(fs.readFileSync(path.join(here, "../../fixtures/input/analysis-1.2.0.json")));

const { server, port } = await serveRoot();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };

async function open(kase, { noWebgl = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error") errors.push(`${kase}: ${m.text()}`); });
  page.on("pageerror", (e) => errors.push(`${kase}: ${e.message}`));
  if (noWebgl) {
    await page.addInitScript(() => {
      const orig = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (type, ...rest) {
        return /webgl/.test(type) ? null : orig.call(this, type, ...rest);
      };
    });
  }
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/result.html?case=${kase}`);
  await page.waitForFunction(() => window.__ready === true);
  await page.waitForTimeout(400);
  return page;
}
const tid = (page, id) => page.getByTestId(id);
const attr = (page, id, a) => tid(page, id).getAttribute(a);
const pel = async (page, which) => (await attr(page, "compare", `data-pelvis-${which}`)).split(",").map(Number);
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
async function drag(page, dx, dy) {
  const box = await page.locator("canvas").boundingBox();
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx + dx / 2, cy + dy / 2, { steps: 4 });
  await page.mouse.move(cx + dx, cy + dy, { steps: 4 });
  await page.mouse.up();
  await page.waitForTimeout(250);
}

try {
  // ---- main result -------------------------------------------------------------------------
  const page = await open("ok");
  assert.equal(await tid(page, "score").textContent(), String(analysis.score.value));
  assert.equal((await tid(page, "grade").textContent()).trim(), analysis.score.grade);
  ok("AC-A12/J9 score and grade equal analysis.json");
  assert.equal(await tid(page, "band-rule").isHidden(), true);
  await page.screenshot({ path: path.join(SHOTS, "01-score.png"), clip: { x: 0, y: 0, width: 412, height: 300 } });
  await tid(page, "grade").click();
  assert.equal(await tid(page, "band-rule").isVisible(), true);
  assert.match(await tid(page, "band-rule").textContent(), /60 to 69/);
  await page.screenshot({ path: path.join(SHOTS, "01b-score-band-rule.png"), clip: { x: 0, y: 0, width: 412, height: 560 } });
  await tid(page, "grade").click();
  assert.equal(await tid(page, "band-rule").isHidden(), true);
  ok("tap on the grade shows and hides the band rule");

  assert.equal(await attr(page, "compare", "data-mode"), "side");
  await page.screenshot({ path: path.join(SHOTS, "02-side-by-side.png"), fullPage: true });
  const t0 = await attr(page, "compare", "data-camera-azimuth");
  const sideBefore = [await pel(page, "trainer"), await pel(page, "you")];
  await drag(page, 120, 20);
  const t1 = await attr(page, "compare", "data-camera-azimuth");
  assert.ok(Math.abs(Number(t1) - Number(t0)) > 10, `azimuth ${t0} -> ${t1}`);
  const sideAfter = [await pel(page, "trainer"), await pel(page, "you")];
  assert.ok(dist(sideBefore[0], sideAfter[0]) > 1 && dist(sideBefore[1], sideAfter[1]) > 1, "both figures move on screen");
  await page.screenshot({ path: path.join(SHOTS, "03-rotated.png"), clip: { x: 0, y: 0, width: 412, height: 640 } });
  ok("AC-C2/J7 drag rotates the shared camera and moves both figures");

  await tid(page, "mode-toggle").click();
  assert.equal(await attr(page, "compare", "data-mode"), "overlay");
  assert.equal(await attr(page, "mode-toggle", "aria-pressed"), "true");
  await page.waitForTimeout(250);
  assert.ok(dist(await pel(page, "trainer"), await pel(page, "you")) <= 2);
  await tid(page, "view-front").click();
  await page.waitForTimeout(250);
  await page.screenshot({ path: path.join(SHOTS, "04-overlay.png"), clip: { x: 0, y: 0, width: 412, height: 640 } });
  await tid(page, "mode-toggle").click();
  assert.equal(await attr(page, "compare", "data-mode"), "side");
  assert.equal(await attr(page, "mode-toggle", "aria-pressed"), "false");
  ok("AC-C3 mode toggle and overlay pelvises coincide within 2 px");

  await tid(page, "view-top").click();
  assert.ok(Math.abs(Number(await attr(page, "compare", "data-camera-elevation")) - 90) <= 1);
  await tid(page, "view-front").click();
  assert.equal(Number(await attr(page, "compare", "data-camera-azimuth")), 0);
  await tid(page, "view-side").click();
  assert.equal(Number(await attr(page, "compare", "data-camera-azimuth")), 90);
  await tid(page, "view-top").click();
  await page.waitForTimeout(250);
  await page.screenshot({ path: path.join(SHOTS, "05-top-view.png"), clip: { x: 0, y: 0, width: 412, height: 640 } });
  ok("AC-C5 view buttons set the camera");

  // wheel zoom changes the render
  const before = await page.locator("canvas").screenshot();
  const box = await page.locator("canvas").boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.wheel(0, -400);
  await page.waitForTimeout(300);
  assert.notDeepEqual(before, await page.locator("canvas").screenshot());
  ok("wheel zoom changes the view");

  // clock
  await tid(page, "view-front").click();
  await page.evaluate(() => window.__r.seek(1.9));
  assert.equal(await attr(page, "clock", "data-t"), "1.9");
  assert.equal(await tid(page, "clock").textContent(), "1.9 s");
  assert.equal(await attr(page, "play", "data-playing"), "false");
  const frozen = await tid(page, "clock").textContent();
  await page.waitForTimeout(2000);
  assert.equal(await tid(page, "clock").textContent(), frozen);
  ok("AC-C4 seek(1.9) and AC-C6 paused clock is still after 2 s");
  await page.evaluate(() => window.__r.seek(0));
  await tid(page, "play").click();
  assert.equal(await attr(page, "play", "data-playing"), "true");
  await page.waitForTimeout(900);
  await tid(page, "play").click();
  const played = Number(await attr(page, "clock", "data-t"));
  assert.ok(played > 0.5 && played < 1.6, `played ${played}`);
  await page.waitForTimeout(500);
  assert.equal(Number(await attr(page, "clock", "data-t")), played);
  ok("play advances in real time, pause stops it");
  await tid(page, "scrub").fill("2.4");
  assert.equal(Number(await attr(page, "clock", "data-t")), 2.4);
  ok("scrub sets the clock and pauses");

  // faults
  const f0 = await tid(page, "fault-0").innerText();
  assert.ok(f0.includes(analysis.faults[0].text_timed));
  assert.ok(f0.includes(`at ${analysis.faults[0].at_s.toFixed(1)} s`));
  assert.equal(await page.locator('[data-testid^="fault-"][aria-pressed]').count(), analysis.faults.length);
  await tid(page, "fault-1").click();
  assert.equal(Number(await attr(page, "clock", "data-t")), analysis.faults[1].at_s);
  assert.equal(await attr(page, "compare", "data-highlighted-joints"), analysis.faults[1].joints.join(","));
  assert.equal(await attr(page, "fault-1", "aria-pressed"), "true");
  assert.equal(await attr(page, "fault-0", "aria-pressed"), "false");
  await tid(page, "fault-1").scrollIntoViewIfNeeded();
  await page.waitForTimeout(250);
  await page.screenshot({ path: path.join(SHOTS, "06-fault-tapped.png"), fullPage: true });
  await tid(page, "fault-0").click();
  assert.equal(await attr(page, "compare", "data-highlighted-joints"), analysis.faults[0].joints.join(","));
  assert.equal(await attr(page, "fault-1", "aria-pressed"), "false");
  await tid(page, "fault-0").click();
  assert.equal(await attr(page, "compare", "data-highlighted-joints"), "");
  ok("AC-A5/J8 fault tap seeks, highlights exactly its joints, sets aria-pressed, second tap clears");

  // layout
  const layout = await page.evaluate(() => ({
    sw: document.documentElement.scrollWidth,
    canvasW: document.querySelector("canvas").getBoundingClientRect().width,
    small: [...document.querySelectorAll("button, a.sr-btn, input[type=range]")].map((e) => [e.dataset.testid, e.getBoundingClientRect().height, e.getBoundingClientRect().width]).filter(([, h, w]) => h < 43.5 || w < 43.5),
  }));
  assert.ok(layout.sw <= 412, `scrollWidth ${layout.sw}`);
  assert.ok(layout.canvasW >= 380, `canvas ${layout.canvasW}`);
  assert.deepEqual(layout.small, []);
  ok("AC-C8 canvas fills the width, 44 px targets, no sideways scroll");

  // downloads
  const dl = await Promise.all([page.waitForEvent("download"), tid(page, "download-analysis").click()]);
  assert.equal(dl[0].suggestedFilename(), "analysis.json");
  const body = JSON.parse(fs.readFileSync(await dl[0].path(), "utf8"));
  assert.equal(body.score.value, analysis.score.value);
  assert.equal(await attr(page, "download-replay", "download"), "replay.json");
  ok("downloads");
  await page.context().close();

  // desktop cap
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const p = await ctx.newPage();
    await p.goto(`http://127.0.0.1:${port}/tests/part7/harness/result.html`);
    await p.waitForFunction(() => window.__ready === true);
    const w = await p.evaluate(() => document.querySelector("canvas").getBoundingClientRect().width);
    assert.ok(w <= 960, `desktop canvas ${w}`);
    await p.screenshot({ path: path.join(SHOTS, "07-desktop.png") });
    await ctx.close();
    ok("AC-C8 desktop canvas at most 960 px");
  }

  // old-pin refusal: a warning, an F, no refusal-only screen
  {
    const p = await open("refused");
    assert.match(await tid(p, "warning-different_movement").textContent(), /different movement/);
    assert.ok(await tid(p, "warning").isVisible());
    assert.equal(await tid(p, "score").textContent(), "0");
    assert.equal(await tid(p, "grade").textContent(), "F");
    assert.ok(await tid(p, "compare").isVisible());
    assert.equal(await p.locator('[data-testid^="fault-"]').count(), 0);
    assert.match(await tid(p, "record-again").getAttribute("href"), /^#\//);
    await p.screenshot({ path: path.join(SHOTS, "08-refusal.png") });
    await p.context().close();
    const n = await open("noreplay");
    assert.equal(await n.getByTestId("compare").count(), 0);
    assert.equal(await tid(n, "grade").textContent(), "F");
    await n.context().close();
    ok("old-pin refusal: warning banner, score 0 and F, compare when a replay exists, Record again");
  }
  // partial view (schema 1.4.0): full result plus warnings and low-confidence faults
  {
    const p = await open("partial");
    assert.deepEqual((await tid(p, "warning").getAttribute("data-codes")).split(","), ["moving_part_out_of_frame", "low_match"]);
    assert.match(await tid(p, "warning-moving_part_out_of_frame").textContent(), /legs were out of frame/);
    assert.equal(await tid(p, "grade").textContent(), "F");
    assert.equal(await tid(p, "score").textContent(), "41");
    assert.ok(await tid(p, "compare").isVisible());
    assert.ok(await tid(p, "fault-0").isVisible());
    assert.ok(await tid(p, "fault-0-low").isVisible());
    await p.screenshot({ path: path.join(SHOTS, "08b-partial.png"), fullPage: true });
    await p.context().close();
    const okp = await open("ok");
    assert.equal(await okp.getByTestId("warning").count(), 0);
    assert.equal(await okp.getByTestId("fault-0-low").count(), 0);
    await okp.context().close();
    ok("partial view: warning banner per code, score and F, faults with low-confidence marking; none on a clean take");
  }
  // no faults, fallback, bad replay
  {
    const p = await open("nofaults");
    assert.equal((await tid(p, "no-faults").textContent()), "No faults found in this take.");
    assert.ok(await p.getByTestId("score").isVisible());
    await p.context().close();
    const f = await open("fallback");
    assert.match(await tid(f, "fallback-note").textContent(), /1 of 2 lines use the backup wording \(live phrasing timed out\)/);
    await f.context().close();
    const b = await open("badreplay");
    assert.equal(await tid(b, "compare-note").textContent(), "The replay file could not be read.");
    assert.equal(await b.getByTestId("compare").count(), 0);
    assert.ok(await tid(b, "fault-0").isVisible());
    assert.ok(await tid(b, "score").isVisible());
    await b.getByTestId("fault-0").click();
    assert.equal(await attr(b, "fault-0", "aria-pressed"), "true");
    await b.context().close();
    ok("no faults, fallback note, bad replay keeps score and fault list");
  }
  // WebGL missing
  {
    const p = await open("ok", { noWebgl: true });
    assert.equal(await tid(p, "compare-note").textContent(), "3D view is not available in this browser.");
    assert.ok(await tid(p, "fault-0").isVisible());
    await p.getByTestId("fault-0").click();
    assert.equal(await attr(p, "fault-0", "aria-pressed"), "true");
    await p.screenshot({ path: path.join(SHOTS, "09-no-webgl.png"), fullPage: true });
    await p.context().close();
    ok("WebGL missing: note, score and faults still work");
  }
  // single viewer
  {
    const p = await open("viewer");
    assert.ok(await p.getByTestId("viewer").isVisible());
    assert.equal(await p.getByTestId("mode-toggle").count(), 0);
    for (const id of ["play", "scrub", "clock", "view-front", "view-side", "view-top"]) assert.equal(await p.getByTestId(id).count(), 1);
    await p.getByTestId("view-side").click();
    assert.equal(Number(await p.getByTestId("viewer").getAttribute("data-camera-azimuth")), 90);
    await p.screenshot({ path: path.join(SHOTS, "10-viewer-single.png") });
    await p.context().close();
    ok("single-figure viewer for Watch");
  }
  assert.deepEqual(errors, []);
  ok("no console errors");
  console.log(`# pass ${passed}`);
} catch (err) {
  console.error(err);
  process.exitCode = 1;
} finally {
  await browser.close();
  server.close();
}
