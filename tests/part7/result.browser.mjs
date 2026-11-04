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

async function open(kase, { noWebgl = false, more = true } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true, reducedMotion: "reduce" });
  // the stage's "Rep breakdown" (score over time, form per rep) and the result's "More" open for these checks, as a
  // viewer who left them open
  await ctx.addInitScript(() => { try { localStorage.setItem("simon.stage.breakdown", "open"); } catch { /* blocked */ } });
  if (more) await ctx.addInitScript(() => { try { localStorage.setItem("simon.result.more", "open"); } catch { /* blocked */ } });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error" && !isResultScreen404(m.location().url)) errors.push(`${kase}: ${m.text()} ${m.location().url}`); });
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
  assert.equal((await tid(page, "summary-grade").textContent()).trim(), analysis.score.grade);
  ok("AC-A12/J9 score and grade equal analysis.json");
  await page.screenshot({ path: path.join(SHOTS, "01-score.png"), clip: { x: 0, y: 0, width: 412, height: 300 } });
  // the lean result (team, 2026-11-02): the score bar is the score; no old grade panel, sum line, stats or fault list
  for (const gone of ["score-panel", "band-rule", "score-sum", "score-detail"]) assert.equal(await page.getByTestId(gone).count(), 0, `negative: no ${gone}`);
  assert.equal(await page.locator(".rs-stats").count(), 0, "negative: no stats tiles");
  {
    const fresh = await open("ok", { more: false });
    assert.equal(await tid(fresh, "result-more").getAttribute("data-open"), "false", "More is closed by default");
    assert.equal(await tid(fresh, "download-analysis").isVisible(), false, "the downloads wait in More");
    await tid(fresh, "result-more-toggle").click();
    assert.ok(await tid(fresh, "download-analysis").isVisible(), "a tap opens More");
    assert.equal(await fresh.evaluate(() => localStorage.getItem("simon.result.more")), "open", "the choice is kept");
    await fresh.context().close();
  }
  ok("lean result: the score bar only, everything else under a closed More");

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
    // hidden controls (0 x 0: a stage view this take lacks, a chip with no moment) are not targets, as in a11y.browser.mjs
    small: [...document.querySelectorAll("button, a.sr-btn, input[type=range]")].map((e) => [e.dataset.testid, e.getBoundingClientRect().height, e.getBoundingClientRect().width]).filter(([, h, w]) => h > 0 && w > 0 && (h < 43.5 || w < 43.5)),
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
    assert.equal(await tid(p, "summary-grade").textContent(), "F");
    assert.ok(await tid(p, "compare").isVisible());
    assert.equal(await p.locator('[data-testid^="fault-"]').count(), 0);
    assert.match(await tid(p, "record-again").getAttribute("href"), /^#\//);   // in More (closed): present, not shown
    await p.screenshot({ path: path.join(SHOTS, "08-refusal.png") });
    await p.context().close();
    const n = await open("noreplay");
    assert.equal(await n.getByTestId("compare").count(), 0);
    assert.equal(await tid(n, "summary-grade").textContent(), "F");
    await n.context().close();
    ok("old-pin refusal: warning banner, score 0 and F, compare when a replay exists, Record again");
  }
  // partial view (schema 1.4.0): full result plus warnings and low-confidence faults
  {
    const p = await open("partial");
    assert.deepEqual((await tid(p, "warning").getAttribute("data-codes")).split(","), ["moving_part_out_of_frame", "low_match"]);
    assert.match(await tid(p, "warning-moving_part_out_of_frame").textContent(), /legs were out of frame/);
    assert.equal(await tid(p, "summary-grade").textContent(), "F");
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
  // TICKET-155: one fault, 59 F because of the low_match cap; the warning banner above the score says why (the old
  // score card and its cap line are gone from the lean result)
  {
    const p = await open("capped");
    assert.equal(await tid(p, "score").textContent(), "59");
    assert.equal((await tid(p, "summary-grade").textContent()).trim(), "F");
    assert.ok(await tid(p, "warning").isVisible());
    assert.equal(await p.getByTestId("score-cap").count(), 0, "negative: no old score card");
    await p.screenshot({ path: path.join(SHOTS, "08c-capped.png"), clip: { x: 0, y: 0, width: 412, height: 560 } });
    await p.context().close();
    ok("TICKET-155 capped score: 59 F under the warning banner");
  }
  // the judge hero (staging job 652b525a73ee, QA 2026-11-02): one score on screen, every other figure labelled
  {
    const p = await open("low-match-hero");
    assert.equal(await tid(p, "score").textContent(), "59", "the ring is score.value");
    assert.equal(await tid(p, "summary-score-caption").textContent(), "score out of 100");
    assert.equal(await tid(p, "summary-grade").textContent(), "F");
    assert.equal(await p.getByTestId("score-sum").count(), 0, "negative: the lean result draws no sum line");
    await p.waitForSelector('[data-testid="breakdown-verdict"]', { state: "attached" });
    assert.equal(await tid(p, "breakdown-verdict").textContent(), "This take didn't match the trainer closely enough to judge form.");
    assert.equal(await tid(p, "insights-empty").textContent(), "This take didn't match the trainer closely enough to judge form.");
    assert.doesNotMatch(await p.locator("body").innerText(), /Nothing to work on|average form/i, "negative: no empty-praise line, no 'average form'");
    // negative: in the score and summary area, a figure other than 59 sits only beside its label
    const area = await p.evaluate(() => ["score-top", "result-summary"].map((id) => document.querySelector(`[data-testid="${id}"]`)?.innerText || "").join("\n"));
    const loose = area.replace(/\u00a0/g, " ").split("\n").flatMap((line) => [...line.matchAll(/\d+(?:\.\d+)?/g)]
      .filter((x) => x[0] !== "59" && !/before the (warning |fault )?caps?|started at 100|lost|out of 100|^Parts$|^\d+$/i.test(line))   // innerText follows the CSS case ("SCORE OUT OF 100")
      .map((x) => `${x[0]} in "${line}"`));
    assert.deepEqual(loose, [], "unlabelled figures in the summary");
    await p.screenshot({ path: path.join(SHOTS, "08d-low-match-hero.png"), fullPage: true });
    await p.context().close();
    // with motion on, the ring counts up from 0 (the reveal) and settles on score.value: a read mid-count sees a lower
    // number (QA's 8 and 39 were frames of this count), the settled read is 59
    const ctx = await browser.newContext({ viewport: { width: 412, height: 915 } });
    const m = await ctx.newPage();
    await m.goto(`http://127.0.0.1:${port}/tests/part7/harness/result.html?case=low-match-hero`);
    await m.waitForFunction(() => window.__ready === true);
    await m.waitForFunction(() => document.querySelector('[data-testid="summary-score"]')?.dataset.reveal === "done", null, { timeout: 10000 });
    assert.equal(await tid(m, "score").textContent(), "59", "settled on score.value after the count-up");
    await ctx.close();
    ok("judge hero: one score (59) in the ring, the grade and the sum; 100 only beside 'before the cap'; no 'Nothing to work on'");
  }
  // one-letter.md: the MM-Fit take 42a02415127e (37 F, credit 16,239 of 22,367, C). The headline and the grade panel
  // show one letter; with a warning too, both still show C (nothing is capped).
  {
    const p = await open("one-letter");
    assert.equal(await tid(p, "summary-grade").textContent(), "C");
    assert.equal(await p.getByTestId("grade").count(), 0, "negative: no second grade panel");
    await p.context().close();
    // nothing capped (score-as-designed 31a08e6): a warned take with a credit shows the credit and its letter too
    const c = await open("one-letter-capped");
    assert.equal(await tid(c, "summary-grade").textContent(), "C");
    assert.equal(await c.locator('[data-testid="summary-grade"]').count(), 1, "one letter on the page");
    assert.ok(await tid(c, "warning").isVisible(), "the warning banner stays");
    assert.doesNotMatch(await tid(c, "warning").textContent(), /capped/i, "the banner has no cap wording");
    await c.context().close();
    ok("one letter: the result shows one letter (C, warned or not)");
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
    const showAll = async (page) => { const b = page.getByTestId("insights-all"); if (await b.count()) await b.click(); };   // the top 3 show; the rest after "Show all"
    await showAll(p);
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
    await showAll(g);
    for (const [i, x] of gold.insights.entries()) {
      const fault = gold.faults.find((f) => f.cue === x.cue);
      assert.ok(fault, `insight ${i} has a matching fault`);
      await tid(g, `insight-${i}`).click();
      await near(g, x.at_s);
      assert.equal(await attr(g, "compare", "data-highlighted-joints"), fault.joints.join(","), `insight ${i} lights its fault's joints`);
      assert.equal(await attr(g, `insight-${i}`, "aria-pressed"), "true");
    }
    for (const [i, x] of gold.insights.entries()) assert.equal(await tid(g, `insight-${i}-cue`).textContent(), x.cue);
    assert.equal(await g.getByTestId("fault-list").count(), 0, "negative: no second list of the same mistakes");
    await noSideScroll(g, "insights-golden");
    await g.context().close();
    ok("insights (Part 5 golden): a tap lights the matching fault's joints; insight cues equal the analysis");

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
    assert.match(first, /^Your head was further forward than the trainer's for part of the move, not long enough to count \(held for 50 of the 60 frames needed\)\.$/);
    assert.match(await tid(p, "near-misses").textContent(), /did not cost you any points/);
    // after "Mistakes you repeated", and the explained_by item (shoulder tilt) is not shown
    const order = await p.evaluate(() => {
      const a = document.querySelector(".sr-faults"), b = document.querySelector('[data-testid="near-misses"]');
      return !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    });
    assert.ok(order, "Close calls follow Mistakes you repeated");
    assert.ok(!/shoulder/.test(await tid(p, "near-misses").textContent()));
    const atS = Number(await attr(p, "near-miss-1", "data-at-s")); // trunk lean, follower frame 45
    await tid(p, "near-miss-1").click();
    await p.waitForTimeout(300);
    const t = Number(await attr(p, "clock", "data-t"));
    assert.ok(Math.abs(t - atS) <= 1 / 30, `clock ${t}, close call at ${atS}`);
    assert.ok(atS > 1.4 && atS < 1.6, `frame 45 is about 1.5 s, got ${atS}`);
    await p.context().close();
    ok("close calls: three rows after Mistakes you repeated, wording from Part 5's numbers, a tap moves the clock, explained_by hidden");
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
  // TICKET-331: a fake follow take whose movement the trainer deleted (harness case "orphan"); signed in, so the owner's calls would
  // be made if the page did not skip them. A 404 on any of them would also surface in `errors` (not an ignored URL).
  {
    const gone = await open("orphan");
    const present = await open("orphan-present");
    const read = (page) => page.evaluate(() => ({
      req: window.__req.slice(),
      note: document.querySelector('[data-testid="orphan-note"]')?.textContent || null,
      retry: document.querySelectorAll('[data-testid="summary-retry"], [data-testid="record-again"]').length,
      dead: document.querySelectorAll('a[href^="#/follow/"], a[href^="#/watch/"]').length,
      videosNote: document.querySelector('[data-testid="orphan-videos-note"]')?.textContent || null,
      score: document.querySelector('[data-testid="score"], [data-testid="summary-score"]')?.textContent || null,
      stage: !!document.querySelector('[data-testid="stage"]'),
      compare: !!document.querySelector('[data-testid="compare"]'),
    }));
    const g = await read(gone);
    assert.equal(g.note, "The trainer removed this movement. Your take and its result are still here.");
    assert.equal(g.retry, 0, "no Retry set and no Record again");
    assert.equal(g.dead, 0, "no link to the deleted movement");
    assert.match(g.videosNote, /trainer's video is no longer available/);
    assert.deepEqual(g.req, [], "none of the entry-dependent calls was made");
    assert.ok(g.score && g.stage && g.compare, "the score, the stage and the 3D compare still render");
    await gone.screenshot({ path: path.join(SHOTS, "orphan-take-top.png") });
    await gone.screenshot({ path: path.join(SHOTS, "orphan-take-full.png"), fullPage: true });
    ok("TICKET-331 an orphaned take shows the note, no dead links, the Videos note, and makes no entry-dependent call");
    const p = await read(present);
    assert.equal(p.note, null);
    assert.equal(p.videosNote, null);
    assert.ok(p.retry >= 1, "an existing movement keeps Retry set");
    ok("TICKET-331 negative: a take whose movement exists shows none of it");
    await gone.context().close();
    await present.context().close();
  }
  {
    // TICKET-322 AC-S14: the trainer's clip plays on the result page, so the entry's source and licence show beside the take's
    const openSource = async (kase) => {
      const ctx = await browser.newContext({ viewport: { width: 412, height: 915 } });
      await ctx.addInitScript(() => { try { localStorage.setItem("simon.result.more", "open"); } catch { /* blocked */ } }); // the credit sits in More
      const page = await ctx.newPage();
      page.on("pageerror", (e) => errors.push(`source ${kase}: ${e.message}`));
      await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/result-source.html?case=${kase}`);
      await page.waitForFunction(() => window.__ready === true, null, { timeout: 60000 });
      await page.waitForTimeout(800);
      return page;
    };
    const cc = await openSource("cc");
    const block = cc.getByTestId("result-entry-source");
    assert.equal(await block.count(), 1, "the entry credit shows");
    assert.equal(await block.isVisible(), true);
    assert.equal(await cc.getByTestId("result-entry-source-lead").textContent(), "Trainer's video:");
    const lic = cc.getByTestId("result-entry-source-licence-link");
    assert.equal(await lic.getAttribute("href"), "https://creativecommons.org/licenses/by/4.0/");
    assert.equal(await lic.getAttribute("rel"), "noopener noreferrer");
    assert.equal(await lic.getAttribute("target"), "_blank");
    assert.equal(await cc.getByTestId("result-entry-source-changes").textContent(), "Changes: Simon re-encodes the clip, may cut its length and builds a 3D model from it.");
    assert.equal(await cc.getByTestId("result-entry-source-link").getAttribute("href"), "https://mmfit.github.io/");
    assert.equal(await cc.getByTestId("result-entry-source-edit").count(), 0, "read-only: no edit form here");
    await cc.screenshot({ path: path.join(SHOTS, "result-entry-source.png"), fullPage: true });
    ok("TICKET-322 the CC BY entry credit shows with its licence link, changes line and Trainer's video lead");
    const none = await openSource("none");
    assert.equal(await none.getByTestId("result-entry-source").count(), 0);
    ok("TICKET-322 negative: an entry with no source shows no credit block");
    const alone = await openSource("notrainer");
    assert.equal(await alone.getByTestId("result-entry-source").count(), 0);
    assert.equal(await alone.getByTestId("result-entry-source-slot").count(), 0, "no slot without a trainer video");
    assert.equal((await alone.evaluate(() => window.__req)).some((u) => u.includes("api/source/entry/")), false, "no entry source request");
    ok("TICKET-322 negative: no trainer video, no entry credit slot and no request");
    const mine = await openSource("mine");
    assert.equal(await mine.getByTestId("result-entry-source-edit").count(), 0, "the owner edits on the watch page, not here");
    ok("TICKET-322 the owner sees no entry edit form on the result page");
    for (const pg of [cc, none, alone, mine]) await pg.context().close();
  }
  assert.deepEqual(errors, [], JSON.stringify(errors));
  ok("no console errors");
  console.log(`# pass ${passed}`);
} catch (err) {
  console.error(err);
  process.exitCode = 1;
} finally {
  await browser.close();
  server.close();
}
