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
import { isResultScreen404 } from "./lane_modules.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const SHOTS = process.env.SHOTS_DIR || path.join(here, "screens");
fs.mkdirSync(SHOTS, { recursive: true });
const analysis = JSON.parse(fs.readFileSync(path.join(here, "../../fixtures/input/analysis-1.2.0.json")));

const { server, port, logs } = await serveRoot();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };

async function open(kase, { noWebgl = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true, reducedMotion: "reduce" });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error" && !isResultScreen404(m.location().url)) errors.push(`${kase}: ${m.text()}`); });
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
  await page.locator("canvas").scrollIntoViewIfNeeded(); // the canvas sits below the score, insights and timeline
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
  await page.locator("canvas").scrollIntoViewIfNeeded(); // the canvas sits below the score, insights and timeline
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
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
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
    assert.match(await tid(p, "score-cap").textContent(), /^Graded F at most: a moving part of your body was out of frame; /);
    await p.screenshot({ path: path.join(SHOTS, "08b-partial.png"), fullPage: true });
    await p.context().close();
    const okp = await open("ok");
    assert.equal(await okp.getByTestId("warning").count(), 0);
    assert.equal(await okp.getByTestId("fault-0-low").count(), 0);
    assert.equal(await okp.getByTestId("score-cap").count(), 0);
    await okp.context().close();
    ok("partial view: warning banner per code, score and F, faults with low-confidence marking; none on a clean take");
  }
  // TICKET-155: one fault, 59 F because of the low_match cap; the score card itself says why
  {
    const p = await open("capped");
    assert.equal(await tid(p, "score").textContent(), "59");
    assert.equal((await tid(p, "grade").textContent()).trim(), "F");
    const cap = tid(p, "score-cap");
    assert.ok(await cap.isVisible());
    assert.equal(await cap.textContent(), "Graded F at most: this take does not closely match the trainer's movement.");
    assert.ok(await p.evaluate(() => !!document.querySelector('[data-testid="score-panel"] [data-testid="score-cap"]')));
    await p.screenshot({ path: path.join(SHOTS, "08c-capped.png"), clip: { x: 0, y: 0, width: 412, height: 560 } });
    await p.context().close();
    ok("TICKET-155 capped score: the score card says why; a clean take has no cap line");
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
  // TICKET-066 (journey.md step 8b): "What to work on" taps drive the 3D compare and the score timeline
  {
    const fixture = (f) => JSON.parse(fs.readFileSync(path.join(here, "../../fixtures/input", f)));
    const near = async (p, atS) => {
      const t = Number(await attr(p, "clock", "data-t"));
      assert.ok(Math.abs(t - atS) <= 1 / 30, `clock ${t}, insight at ${atS}`);
    };
    const noSideScroll = async (p, name) => {
      const sw = await p.evaluate(() => document.documentElement.scrollWidth);
      assert.ok(sw <= 412, `${name}: scrollWidth ${sw}`);
    };
    // without a matching fault, an insight lights its own joint, both sides for `side: both`, none for tempo
    const ownJoints = (x) => (!x.joint ? "" : x.side === "both" && !/^(left|right)_/.test(x.joint) ? `left_${x.joint},right_${x.joint}` : x.joint);

    const ins = fixture("analysis-insights.json");
    const p = await open("insights");
    assert.ok(await tid(p, "compare").isVisible(), "the insights analysis has a compare to seek");
    assert.equal(await p.locator(".sr-insight").count(), ins.insights.length);
    for (const [i, x] of ins.insights.entries()) {
      assert.equal(await tid(p, `insight-${i}-cue`).textContent(), x.cue);
      await tid(p, `insight-${i}`).click();
      await near(p, x.at_s);
      assert.equal(await attr(p, "compare", "data-highlighted-joints"), ownJoints(x), `insight ${i} joints`);
      assert.equal(await attr(p, `insight-${i}`, "aria-pressed"), "true");
      assert.equal(await p.locator('.sr-insight[aria-pressed="true"]').count(), 1);
      assert.equal(await attr(p, `timeline-${x.window}`, "aria-pressed"), "true", `insight ${i} opens window ${x.window}`);
      assert.equal(await p.locator('.sr-tl-bar[aria-pressed="true"]').count(), 1);
    }
    await tid(p, "insight-0").scrollIntoViewIfNeeded();
    await p.screenshot({ path: path.join(SHOTS, "13-insight-tapped.png"), fullPage: true });
    let missCues = 0;
    for (const [i, w] of ins.score.timeline.entries()) {
      await tid(p, `timeline-${i}`).click();
      const cues = (w.misses || []).map((m) => m.cue).filter(Boolean);
      assert.equal(await p.locator(`[data-testid^="timeline-${i}-miss-"][data-testid$="-cue"]`).count(), cues.length);
      for (const [k, m] of (w.misses || []).entries()) {
        if (!m.cue) continue;
        assert.equal(await tid(p, `timeline-${i}-miss-${k}-cue`).textContent(), m.cue);
        missCues++;
      }
    }
    assert.ok(missCues > 0, "the fixture's windows carry miss cues");
    await noSideScroll(p, "insights");
    await p.context().close();
    ok(`insights: ${ins.insights.length} taps seek the compare to at_s, light the joints, set aria-pressed and open the window; ${missCues} miss cues equal the analysis`);

    const gold = fixture("analysis-1.5.0.json");
    const g = await open("insights-golden");
    for (const [i, x] of gold.insights.entries()) {
      const fault = gold.faults.find((f) => f.cue === x.cue);
      assert.ok(fault, `insight ${i} has a matching fault`);
      await tid(g, `insight-${i}`).click();
      await near(g, x.at_s);
      assert.equal(await attr(g, "compare", "data-highlighted-joints"), fault.joints.join(","), `insight ${i} lights its fault's joints`);
      assert.equal(await attr(g, `insight-${i}`, "aria-pressed"), "true");
    }
    for (const [i, f] of gold.faults.entries()) assert.equal(await tid(g, `fault-${i}-cue`).textContent(), f.cue);
    await noSideScroll(g, "insights-golden");
    await g.context().close();
    ok("insights (Part 5 golden): a tap lights the matching fault's joints; fault cues equal the analysis");

    for (const kase of ["ok", "partial"]) { // 1.2.0, and the same with the 1.4.0 fields: written before insights
      const o = await open(kase);
      assert.equal(await o.getByTestId("insights").count(), 0, `${kase}: no insights section`);
      assert.equal(await o.locator('[data-testid$="-cue"]').count(), 0, `${kase}: no cue elements`);
      assert.ok(await tid(o, "fault-0").isVisible());
      await o.context().close();
    }
    ok("an analysis older than 1.5.0 shows no insights section and no cues");
  }
  // TICKET-100: "Close calls" from Part 5 1.8.0 diagnostics.near_misses
  {
    const p = await open("nearmiss");
    await p.getByTestId("near-misses").waitFor();
    assert.equal(await p.locator('[data-testid^="near-miss-"][data-reason]').count(), 3, "three close calls, no more");
    const first = await tid(p, "near-miss-0-text").textContent();
    assert.match(first, /^Your head was further forward than the trainer's for part of the move, not long enough to count \(50 of 60 frames\)\.$/);
    assert.match(await tid(p, "near-misses").textContent(), /did not cost you any points/);
    // after "What to fix", and the explained_by item (shoulder tilt) is not shown
    const order = await p.evaluate(() => {
      const a = document.querySelector(".sr-faults"), b = document.querySelector('[data-testid="near-misses"]');
      return !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    });
    assert.ok(order, "Close calls follow What to fix");
    assert.ok(!/shoulder/.test(await tid(p, "near-misses").textContent()));
    const atS = Number(await attr(p, "near-miss-1", "data-at-s")); // trunk lean, follower frame 45
    await tid(p, "near-miss-1").click();
    await p.waitForTimeout(300);
    const t = Number(await attr(p, "clock", "data-t"));
    assert.ok(Math.abs(t - atS) <= 1 / 30, `clock ${t}, close call at ${atS}`);
    assert.ok(atS > 1.4 && atS < 1.6, `frame 45 is about 1.5 s, got ${atS}`);
    await p.context().close();
    ok("close calls: three rows after What to fix, wording from Part 5's numbers, a tap moves the clock, explained_by hidden");
    for (const kase of ["ok", "nearmiss-empty"]) { // 1.2.0 without the field, and 1.8.0 listing none
      const o = await open(kase);
      assert.equal(await o.getByTestId("near-misses").count(), 0, `${kase}: no close calls section`);
      assert.equal(await o.getByText("Close calls").count(), 0, `${kase}: no heading`);
      assert.ok(await tid(o, "fault-0").isVisible());
      await o.context().close();
    }
    ok("no near_misses field, or an empty list, shows no Close calls section");
  }
  // TICKET-065 (compare-view.md AC-C9, AC-C10): the same body in every view for the same data
  {
    const stats = async (p, id) => Object.fromEntries(await Promise.all(["data-joints-drawn", "data-joints-dimmed", "data-bones-drawn"]
      .map(async (a) => [a, (await attr(p, id, a)).split(",")])));
    const seekT = async (p, id, t) => {
      await p.locator(`[data-testid="${id}"] [data-testid="scrub"]`).evaluate((s, v) => { s.value = String(v); s.dispatchEvent(new Event("input", { bubbles: true })); }, t);
      await p.waitForTimeout(250);
    };
    const cmp = await open("ok");
    const c = await stats(cmp, "compare");
    const anim = await open("animation");
    const a = await stats(anim, "viewer");
    assert.deepEqual(c["data-joints-drawn"], ["17", "17"]);
    assert.deepEqual(a["data-joints-drawn"], ["17"]);
    assert.deepEqual(a["data-bones-drawn"], c["data-bones-drawn"].slice(0, 1), "Watch animation draws the compare's bones");
    assert.equal(a["data-bones-drawn"][0], "18");
    await anim.screenshot({ path: path.join(SHOTS, "11-viewer-part4-animation.png") });
    await cmp.context().close();
    await anim.context().close();
    ok("AC-C9 the Watch animation (Part 4 bones) draws the compare's 17 joints and 18 bones");

    // TICKET-090: a shipped sample entry (simon.animation/1, people[].joints) draws whole and logs nothing
    const s1 = await open("animation-sim1");
    const ss = await stats(s1, "viewer");
    assert.deepEqual(ss["data-joints-drawn"], ["17"]);
    assert.deepEqual(ss["data-joints-dimmed"], ["0"], "no joint of the sample is dimmed");
    assert.deepEqual(ss["data-bones-drawn"], ["18"]);
    await s1.context().close();
    ok("TICKET-090 a simon.animation/1 sample draws 17 joints and 18 bones with none dimmed");

    const u = await open("unseen");
    const ua = await open("animation-unseen");
    await seekT(u, "compare", 1.0);
    await seekT(ua, "viewer", 1.0);
    const us = await stats(u, "compare");
    const as = await stats(ua, "viewer");
    assert.deepEqual(us["data-joints-drawn"], ["17", "17"], "an unseen joint is still drawn");
    assert.deepEqual(us["data-joints-dimmed"], ["1", "1"]);
    assert.deepEqual(as["data-joints-drawn"], ["17"]);
    assert.deepEqual(as["data-joints-dimmed"], ["1"], "Watch dims the same trainer joint as the compare");
    await u.screenshot({ path: path.join(SHOTS, "12-compare-unseen-dimmed.png") });
    await u.context().close();
    await ua.context().close();
    ok("AC-C10 an unseen joint is dimmed, not dropped, in the compare and on Watch");
    // every earlier page had a full body: the two unseen pages are the only views that logged, once each
    const dimmed = logs.filter((l) => l && l.event === "body_dimmed");
    assert.deepEqual(dimmed.map((l) => l.detail.view).sort(), ["compare", "viewer"]);
    assert.ok(dimmed.every((l) => l.level === "warn" && /dims left_wrist/.test(l.detail.report)), JSON.stringify(dimmed));
    ok("a view that dims joints posts one body_dimmed client log event");
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
