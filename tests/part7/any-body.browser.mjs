// docs/specs/any-body.md (AC-AB1 to AC-AB7) on the real app (web/index.html, the real router, compare.js, viewer3d.js,
// character.js and the committed built-in library) with the committed example result. Only the server calls are answered
// by the test. Run: PLAYWRIGHT_DIR=<node_modules> scripts/with-browser-slot.sh node tests/part7/any-body.browser.mjs
// Screenshots go to SIMON_ANYBODY_SHOTS (default: a temp folder).
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.join(root, "node_modules"), "x.js"));
const { chromium } = req("playwright");
const SHOTS = process.env.SIMON_ANYBODY_SHOTS || fs.mkdtempSync(path.join(os.tmpdir(), "any-body-shots-"));
fs.mkdirSync(SHOTS, { recursive: true });

const fixture = (f) => JSON.parse(fs.readFileSync(path.join(root, "fixtures/input", f), "utf8"));
const RESULT = { analysis: fixture("analysis-1.2.0.json"), replay: fixture("replay.json") };
const json = (route, status, body) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const ID = "a".repeat(32);
const MINE = { mine: [{ id: ID, name: "My model", kind: "upload", status: "ready", glb: "models/library/ual1-mannequin/model.glb",
  manifest: "models/library/ual1-mannequin/character.json", licence: { id: "own-work", attribution: null } }] };

const { port } = await serveRoot();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };

async function open(hash, { width, height, mine = { mine: [] }, breakModel = null } = {}) {
  const context = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce" });
  const page = await context.newPage();
  const bad = [];
  page.on("pageerror", (e) => bad.push(`pageerror ${e.message}`));
  await page.route("**/api/auth/me", (r) => json(r, 200, { available: true, signed_in: false }));
  await page.route("**/api/fixture-result", (r) => json(r, 200, RESULT));
  await page.route(/\/api\/models(\?.*)?$/, (r) => json(r, 200, mine));
  if (breakModel) await page.route(`**/models/library/${breakModel}/model.glb`, (r) => r.fulfill({ status: 404, body: "gone" }));
  await page.goto(`http://127.0.0.1:${port}/web/index.html${hash}`);
  return { page, bad, context };
}
const ready = async (page) => {
  await page.waitForFunction(() => document.querySelector("[data-testid=any-body]")?.dataset.ready === "true", null, { timeout: 60000 });
  await page.waitForSelector("[data-testid=splash]", { state: "detached", timeout: 15000 }); // the brand splash covers the first screenshot
};
const attr = (page, name) => page.locator("[data-testid^=any-body-fig-]").evaluateAll((els, n) => els.map((e) => e.getAttribute(n)), name);

try {
  // AC-AB1, AC-AB2, AC-AB4, AC-AB7: desktop, the committed example, signed out
  {
    const { page, bad, context } = await open("#/any-body/fixture", { width: 1280, height: 800 });
    await ready(page);
    assert.equal(await page.locator("[data-testid^=any-body-fig-]").count(), 4);
    assert.deepEqual(await page.locator("[data-testid^=any-body-name-]").allTextContents(), ["Person", "Mannequin (female)", "Mannequin", "Rigged Figure"]);
    ok("AC-AB1 four figures with their names");
    await page.waitForFunction(() => [...document.querySelectorAll("[data-testid^=any-body-fig-]")].every((e) => e.dataset.state === "ready"));
    const ids = await attr(page, "data-skin-id");
    assert.equal(new Set(ids).size, 4, `data-skin-id is distinct per figure: ${ids}`);
    assert.deepEqual(await attr(page, "data-skin-kind"), ["skeleton", "character", "character", "character"]);
    const boxes = await page.locator("[data-testid^=any-body-fig-]").evaluateAll((els) => els.map((e) => e.getBoundingClientRect()));
    assert.ok(boxes.every((b) => b.width > 150 && Math.abs(b.top - boxes[0].top) < 2), "four figures in one row");
    assert.ok(boxes.every((b) => b.right <= 1280), "none runs off the screen");
    ok("AC-AB1 distinct data-skin-id per figure, one row, all on screen");

    const line = await page.getByTestId("any-body-note").textContent();
    assert.match(line, /normalized skeleton/);
    assert.doesNotMatch(await page.getByTestId("any-body").innerText(), /weight|health|calorie|diet|fitness/i);
    ok("AC-AB4 the honest line is shown; no health or weight claim");

    const credit = await page.getByTestId("any-body-credit").textContent();
    assert.match(credit, /Rigged Figure: .*CC BY 4\.0/);
    ok("AC-AB7 the credit line for the CC-BY model");

    // AC-AB2: scrub, then every figure has the same frame, and a different one after a second scrub
    const scrubTo = async (frac) => page.getByTestId("any-body-scrub").evaluate((el, f) => {
      el.value = String(Number(el.max) * f); el.dispatchEvent(new Event("input", { bubbles: true }));
    }, frac);
    await scrubTo(0.5);
    await page.waitForTimeout(300);
    const set1 = await attr(page, "data-frame");
    const drawn1 = await attr(page, "data-drawn-frame");
    assert.equal(new Set(set1).size, 1);
    assert.equal(new Set(drawn1).size, 1);
    assert.equal(set1[0], drawn1[0]);
    await scrubTo(0.9);
    await page.waitForTimeout(300);
    const set2 = await attr(page, "data-frame");
    assert.equal(new Set(set2).size, 1);
    assert.notEqual(set2[0], set1[0], "the frame moved with the scrub");
    assert.equal(new Set(await attr(page, "data-drawn-frame")).size, 1);
    ok(`AC-AB2 identical frame index across figures after scrubbing (${set1[0]}, then ${set2[0]})`);

    // one play button runs all of them
    await scrubTo(0);
    await page.getByTestId("any-body-play").click();
    await page.waitForFunction(() => Number(document.querySelector("[data-testid=any-body-clock]").dataset.t) > 0.3, null, { timeout: 8000 });
    const during = await attr(page, "data-frame");
    assert.equal(new Set(during).size, 1);
    assert.ok(Number(during[0]) > 0);
    await page.getByTestId("any-body-play").click();
    await page.screenshot({ path: path.join(SHOTS, "any-body-desktop.png") });
    assert.deepEqual(bad, []);
    ok("AC-AB2 one play button moves every figure together");
    await context.close();
  }

  // AC-AB6: the button in a result's 3D view opens the view
  {
    const { page, bad, context } = await open("#/result/fixture", { width: 1280, height: 800 });
    const btn = page.getByTestId("any-body-open");
    await btn.waitFor({ timeout: 30000 });
    assert.equal(await btn.getAttribute("href"), "#/any-body/fixture");
    await btn.click();
    await ready(page);
    assert.equal(await page.locator("[data-testid^=any-body-fig-]").count(), 4);
    assert.equal(await page.locator("a.ab-back").getAttribute("href"), "#/result/fixture");
    assert.deepEqual(bad, []);
    ok("AC-AB6 the Any body button opens the view; the view links back");
    await context.close();
  }

  // AC-AB3: phone, two at a time, a switch moves on, all still play
  {
    const { page, bad, context } = await open("#/any-body/fixture", { width: 412, height: 915 });
    await ready(page);
    assert.equal(await page.getByTestId("any-body").getAttribute("data-per"), "2");
    const inView = () => page.locator("[data-testid^=any-body-fig-]").evaluateAll((els) => {
      const g = document.querySelector("[data-testid=any-body-grid]").getBoundingClientRect();
      return els.map((e) => { const r = e.getBoundingClientRect(); return r.left >= g.left - 1 && r.right <= g.right + 1; });
    });
    assert.deepEqual(await inView(), [true, true, false, false]);
    await page.screenshot({ path: path.join(SHOTS, "any-body-phone.png"), fullPage: true });
    await page.getByTestId("any-body-page-1").click();
    await page.waitForFunction(() => document.querySelector("[data-testid=any-body-page-1]").getAttribute("aria-pressed") === "true");
    assert.deepEqual(await inView(), [false, false, true, true]);
    await page.screenshot({ path: path.join(SHOTS, "any-body-phone-2.png"), fullPage: true });
    await page.getByTestId("any-body-scrub").evaluate((el) => { el.value = String(Number(el.max) * 0.4); el.dispatchEvent(new Event("input", { bubbles: true })); });
    await page.waitForTimeout(300);
    assert.equal(new Set(await attr(page, "data-frame")).size, 1, "the figures out of sight keep the same frame");
    assert.deepEqual(bad, []);
    ok("AC-AB3 two figures at 412 px, the switch shows the next two, frames stay in step");
    await context.close();
  }

  // AC-AB1: the caller's own model takes a place after the first built-in; four at most
  {
    const { page, context } = await open("#/any-body/fixture", { width: 1280, height: 800, mine: MINE });
    await ready(page);
    assert.deepEqual(await page.locator("[data-testid^=any-body-name-]").allTextContents(), ["Person", "Mannequin (female)", "Mannequin", "My model"]);
    await context.close();
    ok("AC-AB1 an own model joins the row, never past four");
  }

  // AC-AB5 (negative): one model file is gone; its slot names it, the others still play
  {
    const { page, bad, context } = await open("#/any-body/fixture", { width: 1280, height: 800, breakModel: "rigged-figure" });
    await ready(page);
    await page.waitForFunction(() => document.querySelector("[data-testid=any-body-fig-3]").dataset.state === "error");
    const err = await page.getByTestId("any-body-error-3").textContent();
    assert.match(err, /^Rigged Figure could not be shown/);
    assert.deepEqual(await attr(page, "data-state"), ["ready", "ready", "ready", "error"]);
    assert.equal(await page.getByTestId("any-body-error-1").isVisible(), false);
    await page.getByTestId("any-body-scrub").evaluate((el) => { el.value = String(Number(el.max) * 0.7); el.dispatchEvent(new Event("input", { bubbles: true })); });
    await page.waitForTimeout(300);
    assert.equal(new Set(await attr(page, "data-frame")).size, 1, "the broken slot and the others share the frame");
    assert.deepEqual((await attr(page, "data-skin-kind")).slice(0, 3), ["skeleton", "character", "character"]);
    assert.equal((await attr(page, "data-skin-kind"))[3], "skeleton");
    await page.screenshot({ path: path.join(SHOTS, "any-body-one-broken.png") });
    assert.ok(bad.every((b) => !b.startsWith("pageerror")), `no page error: ${bad}`);
    ok("AC-AB5 a broken model shows a named error in its slot; the others still play");
    await context.close();
  }

  // AC-AB6 (negative): a take with no replay says so and links back
  {
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const page = await context.newPage();
    await page.route("**/api/auth/me", (r) => json(r, 200, { available: true, signed_in: false }));
    await page.route(/\/api\/results\/[0-9a-f]+\/replay\.json$/, (r) => json(r, 404, { error: "none" }));
    await page.goto(`http://127.0.0.1:${port}/web/index.html#/any-body/${ID}`);
    await page.getByTestId("any-body-message").waitFor();
    assert.match(await page.getByTestId("any-body-message").textContent(), /no 3D replay/);
    assert.equal(await page.locator("[data-testid=any-body-fig-0]").count(), 0);
    ok("AC-AB6 a take with no replay shows a plain message and a way back");
    await context.close();
  }
  console.log(`${passed} checks passed; screenshots in ${SHOTS}`);
} catch (err) {
  console.error(err);
  process.exitCode = 1;
} finally {
  await browser.close();
  process.exit(process.exitCode || 0);
}
