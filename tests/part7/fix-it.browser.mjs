// docs/specs/fix-it-for-me.md (AC-1 to AC-6) in Chromium on the result harness (tests/part7/harness/result.html: the real
// replay fixture, the real analysis fixture, the real compare.js, picker.js, viewer3d.js and corrected-replay.js) at 412x915
// and 1440x900. The harness result is the example result (no job files), so the bodies are the stick figures; the Person
// skin goes through the same stage.setPoses and has its own proof (person-skin.browser.mjs).
// Witnesses: the numbers the panel writes from the poses it gave the stage, and the canvas pixels (a frame diff).
// Negative: Before shows the take's own pose, a take with no fault shows no button, and the score does not move.
// Run: PLAYWRIGHT_DIR=<node_modules> FIXIT_SHOTS=<dir> scripts/with-browser-slot.sh node tests/part7/fix-it.browser.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const SHOTS = process.env.FIXIT_SHOTS || fs.mkdtempSync(path.join(process.env.TMPDIR || "/tmp", "fix-it-shots-"));
fs.mkdirSync(SHOTS, { recursive: true });
const STATED_DEG = 5;   // the stated angle: the limb turns at least this far toward the trainer, and ends within it of the trainer's
const { port } = await serveRoot();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const log = [];

async function open(kase, viewport, { video = false, reducedMotion = "reduce" } = {}) {
  const context = await browser.newContext({ viewport, reducedMotion, ...(video ? { recordVideo: { dir: path.join(SHOTS, "video"), size: viewport } } : {}) });
  const page = await context.newPage();
  const bad = [];
  page.on("pageerror", (e) => bad.push(`pageerror ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") bad.push(`console ${m.text()}`); });
  page.on("response", (r) => { if (r.status() >= 400 && !r.url().endsWith("favicon.ico") && !/\/api\/(client-log|labels)/.test(r.url())) bad.push(`${r.status()} ${r.url()}`); });
  await page.route("**/api/auth/me", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ available: true, signed_in: false }) }));
  await page.route("**/models/library/library.json", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ schema: "simon.model-library.v1", models: [] }) }));
  await page.route(/\/api\/models(\?.*)?$/, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ mine: [] }) }));
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/result.html?case=${kase}`);
  await page.waitForFunction(() => window.__ready === true);
  return { page, bad, context };
}

const root = (page) => page.getByTestId("fix-it");
const attr = async (page, name) => root(page).getAttribute(`data-${name}`);
const num = async (page, name) => Number(await attr(page, name));
const nextFrames = (page) => page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(r)))));
/** Move the clip to follower time `t` (seconds) by the scrub bar, as a person would, and wait for the draw. */
async function goTo(page, t) {
  const [c0] = (await attr(page, "clip")).split(",").map(Number);
  await page.getByTestId("fix-it-scrub").evaluate((el, v) => { el.value = String(v); el.dispatchEvent(new Event("input", { bubbles: true })); }, t - c0);
  await page.waitForFunction((want) => Math.abs(Number(document.querySelector("[data-testid=fix-it]").dataset.t) - want) < 0.01, t);
  await nextFrames(page);
}
/** A fingerprint and a count of lit pixels of one stage's canvas. */
const canvasPixels = (page, which) => page.evaluate((w) => {
  const src = document.querySelector(`[data-testid=fix-it-stage-${w}] canvas`);
  if (!src) return null;
  const c = document.createElement("canvas");
  c.width = src.width; c.height = src.height;
  const g = c.getContext("2d");
  g.drawImage(src, 0, 0);
  return { w: c.width, h: c.height, data: Array.from(g.getImageData(0, 0, c.width, c.height).data) };
}, which);
const diff = (a, b) => { let n = 0; for (let i = 0; i < a.data.length; i += 4) if (a.data[i] !== b.data[i] || a.data[i + 1] !== b.data[i + 1] || a.data[i + 2] !== b.data[i + 2] || a.data[i + 3] !== b.data[i + 3]) n++; return n; };

/** The panel at the top of the viewport (an element screenshot of two WebGL canvases times out on a loaded host). */
async function shot(page, file) {
  await page.evaluate(() => document.querySelector("[data-testid=fix-it-panel]").scrollIntoView({ block: "start" }));
  await nextFrames(page);
  await page.screenshot({ path: file, timeout: 90000 });
}
const VIEWS = [{ name: "phone-412", width: 412, height: 915 }, { name: "desktop-1440", width: 1440, height: 900 }];
try {
  for (const vp of VIEWS) {
    const { page, bad, context } = await open("ok", { width: vp.width, height: vp.height }, { video: false });
    await root(page).waitFor();
    assert.equal(await page.getByTestId("fix-it-button").textContent(), "Fix it for me");
    const scoreBefore = await page.getByTestId("score-detail").textContent();
    await page.getByTestId("fix-it-button").scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(SHOTS, `${vp.name}-0-button.png`) });
    const options = await page.getByTestId("fix-it-pick").locator("option").evaluateAll((os) => os.map((o) => o.textContent));
    assert.equal(options.length, 2, `two fixable moments: ${options}`);
    ok(`${vp.name}: the button is on a take with arm and leg faults, one choice per moment`);

    for (const [k, limbs] of [[0, "left arm"], [1, "right leg"]]) {
      await page.getByTestId("fix-it-pick").selectOption(String(k));
      await page.getByTestId("fix-it-button").click();
      await page.waitForFunction((n) => document.querySelector("[data-testid=fix-it]").dataset.limbs === n, limbs);
      await page.waitForFunction(() => document.querySelector("[data-testid=fix-it]").dataset.ready === "true");
      assert.equal(await page.getByTestId("fix-it-label").textContent(), `Your take, with the ${limbs} moved toward the trainer's pose`);
      assert.match(await page.getByTestId("fix-it-note").textContent(), /preview of the trainer's pose on your body, not a measurement\. Your score is unchanged\./);
      const [ws, we] = (await attr(page, "window")).split(",").map(Number);
      const at = await num(page, "fault-at");
      const peakAt = await num(page, "peak-at");

      // AC-1/2 inside the window: the chain turns toward the trainer by the stated angle and ends within it of the trainer's
      for (const [when, name] of [[at, "the fault's moment"], [peakAt, "the peak"]]) {
        await goTo(page, when);
        assert.equal(await num(page, "weight"), 1, `${name}: full blend`);
        const moved = await num(page, "moved-deg"), toward = await num(page, "toward-deg");
        assert.ok(moved >= STATED_DEG, `${limbs} at ${name}: moved ${moved} degrees, wanted at least ${STATED_DEG}`);
        assert.ok(toward <= STATED_DEG, `${limbs} at ${name}: ${toward} degrees left to the trainer, wanted at most ${STATED_DEG}`);
        assert.equal(await num(page, "outside-m"), 0, `${name}: joints outside the chain did not move`);
        log.push(`${vp.name} ${limbs} ${name} t=${when}: moved ${moved} deg, ${toward} deg left to the trainer, outside 0 m, was ${await attr(page, "before-toward-deg")} deg off`);
      }

      // identical outside the window: before the ease starts, the corrected pose is the take's own, in numbers and in pixels
      await goTo(page, Math.max(0, ws - 0.31));
      assert.equal(await num(page, "weight"), 0);
      assert.equal(await num(page, "moved-deg"), 0);
      assert.equal(await num(page, "outside-m"), 0);
      await page.getByTestId("fix-it-before").click();
      const beforeOut = await canvasPixels(page, "a");
      await page.getByTestId("fix-it-after").click();
      await nextFrames(page);
      const afterOut = await canvasPixels(page, "a");
      assert.equal(diff(beforeOut, afterOut), 0, "outside the window After is pixel for pixel Before");
      ok(`${vp.name}: ${limbs} turns toward the trainer by at least ${STATED_DEG} deg inside the window and is identical outside it`);

      // the ease: part of the way in between
      await goTo(page, ws - 0.15);
      const w = await num(page, "weight");
      assert.ok(w > 0.2 && w < 0.8, `eased weight ${w}`);
      const mid = await num(page, "moved-deg");
      assert.ok(mid > 0 && mid < await num(page, "peak-deg") + 1e-9, `mid-ease turn ${mid}`);

      // AC-2 Before / After at the peak: Before is the original pose (numbers and pixels), After differs from it
      await goTo(page, peakAt);
      await page.getByTestId("fix-it-before").click();
      await nextFrames(page);
      assert.equal(await attr(page, "shown-a"), "before");
      assert.equal(await num(page, "a-moved-deg"), 0, "negative: Before shows the original pose");
      assert.equal(await page.getByTestId("fix-it-caption-a").textContent(), "You");
      const before = await canvasPixels(page, "a");
      await shot(page, path.join(SHOTS, `${vp.name}-${k}-before.png`));
      await page.getByTestId("fix-it-after").click();
      await nextFrames(page);
      assert.equal(await attr(page, "shown-a"), "after");
      assert.ok(await num(page, "a-moved-deg") >= STATED_DEG);
      assert.equal(await page.getByTestId("fix-it-caption-a").textContent(), "You, corrected");
      const after = await canvasPixels(page, "a");
      await shot(page, path.join(SHOTS, `${vp.name}-${k}-after.png`));
      const changed = diff(before, after);
      assert.ok(changed > 20, `frame diff Before to After at the peak: ${changed} pixels`);
      log.push(`${vp.name} ${limbs}: frame diff Before to After at the peak ${changed} px; at ${Math.max(0, ws - 0.31)} s 0 px`);
      ok(`${vp.name}: ${limbs} Before shows the original pose, After differs by ${changed} px`);
    }

    // split: you and you, corrected side by side with the trainer ghost in both
    await page.getByTestId("fix-it-pick").selectOption("0");
    await page.getByTestId("fix-it-button").click();
    await page.waitForFunction(() => document.querySelector("[data-testid=fix-it]").dataset.limbs === "left arm");
    await page.waitForFunction(() => document.querySelector("[data-testid=fix-it]").dataset.ready === "true");
    await goTo(page, await num(page, "peak-at"));
    await page.getByTestId("fix-it-split").click();
    await page.waitForSelector("[data-testid=fix-it-stage-b] canvas");
    await page.waitForFunction(() => document.querySelector("[data-testid=fix-it]").dataset.shownB === "after");
    await nextFrames(page);
    assert.equal(await attr(page, "shown-a"), "before");
    assert.equal(await page.getByTestId("fix-it-caption-a").textContent(), "You");
    assert.equal(await page.getByTestId("fix-it-caption-b").textContent(), "You, corrected");
    assert.equal(await num(page, "a-moved-deg"), 0);
    assert.ok(await num(page, "b-moved-deg") >= STATED_DEG);
    const [pa, pb] = [await canvasPixels(page, "a"), await canvasPixels(page, "b")];
    assert.ok(pa.w === pb.w && diff(pa, pb) > 20, "the two views differ at the peak");
    await shot(page, path.join(SHOTS, `${vp.name}-2-split.png`));
    await goTo(page, 0);
    await nextFrames(page);
    assert.equal(diff(await canvasPixels(page, "a"), await canvasPixels(page, "b")), 0, "outside the window the two views are the same picture");
    await goTo(page, await num(page, "peak-at"));
    ok(`${vp.name}: split shows you and you, corrected; they differ only inside the window`);

    // the score and the claim: nothing the panel does moves the score or says the student did it
    assert.equal(await page.getByTestId("score-detail").textContent(), scoreBefore);
    const panelText = await root(page).innerText();
    assert.ok(!/[\u2013\u2014]/.test(panelText), "no em or en dash on the panel");
    assert.ok(!/you (did|moved|improved|fixed)|new score|score (rose|went up|improved)/i.test(panelText), `no claim in: ${panelText}`);
    ok(`${vp.name}: the score is unchanged and the panel makes no claim the student did it`);

    // close: panel hidden, canvases freed, focus back on the button
    await page.getByTestId("fix-it-close").click();
    assert.equal(await page.locator("[data-testid=fix-it-panel]").isHidden(), true);
    assert.equal(await page.locator("[data-testid^=fix-it-stage-] canvas").count(), 0);
    assert.equal(await page.evaluate(() => document.activeElement && document.activeElement.dataset.testid), "fix-it-button");
    ok(`${vp.name}: Close frees the views and returns focus`);
    assert.deepEqual(bad, [], `no console errors or failed requests: ${bad}`);
    await context.close();
  }

  // with motion allowed the clip plays by itself and a pause holds it; this run is also the demo capture (a short video per size)
  for (const vp of VIEWS) {
    const { page, bad, context } = await open("ok", { width: vp.width, height: vp.height }, { reducedMotion: "no-preference", video: true });
    await page.getByTestId("fix-it-pick").selectOption("0");
    await page.getByTestId("fix-it-button").click();
    await root(page).scrollIntoViewIfNeeded();
    await page.evaluate(() => document.querySelector("[data-testid=fix-it-panel]").scrollIntoView({ block: "center" }));
    await page.waitForFunction(() => document.querySelector("[data-testid=fix-it]").dataset.ready === "true");
    const t0 = await num(page, "t");
    await page.waitForFunction((a) => Number(document.querySelector("[data-testid=fix-it]").dataset.t) > a + 0.4, t0);
    assert.equal(await page.getByTestId("fix-it-play").getAttribute("data-playing"), "true");
    await page.waitForTimeout(1500);
    await page.getByTestId("fix-it-play").click();
    const held = await num(page, "t");
    await page.waitForTimeout(300);
    assert.equal(await num(page, "t"), held, "paused holds the clock");
    await goTo(page, await num(page, "peak-at"));
    for (const [id, ms] of [["fix-it-before", 1400], ["fix-it-after", 1400], ["fix-it-split", 2200], ["fix-it-split", 600]]) {
      await page.getByTestId(id).click();
      await page.waitForTimeout(ms);
    }
    await page.getByTestId("fix-it-play").click();
    await page.waitForTimeout(2500);
    assert.deepEqual(bad, []);
    ok(`${vp.name}: the replay plays by itself with motion allowed and a pause holds it`);
    await context.close();
  }

  // negative: a take with no fault, no replay or a refusal shows no button and no slot content
  for (const kase of ["nofaults", "noreplay", "refused"]) {
    const { page, bad, context } = await open(kase, { width: 412, height: 915 });
    await page.waitForTimeout(400);
    assert.equal(await page.locator("[data-testid=fix-it]").count(), 0, `${kase}: no panel`);
    assert.equal(await page.locator("[data-testid=fix-it-button]").count(), 0, `${kase}: no button`);
    assert.equal(await page.getByTestId("fix-it-slot").evaluate((el) => el.children.length).catch(() => 0), 0);
    assert.deepEqual(bad, [], `${kase}: ${bad}`);
    await context.close();
  }
  ok("a take with no fault, no replay or a refusal shows no Fix it button");
} finally {
  await browser.close();
  fs.writeFileSync(path.join(SHOTS, "fix-it-measurements.txt"), `${log.join("\n")}\n`);
}
console.log(`\n${passed} checks passed; shots and measurements in ${SHOTS}`);
console.log(log.join("\n"));
process.exit(0);   // the static server keeps the loop alive; a failed assertion above already threw (exit 1)
