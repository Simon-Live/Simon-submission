// Browser checks for the group result "Watch all" view at 412x915 (people.md, TICKET-085): the board at
// #/group/<job> opens the 3D overlay of every scored person on the trainer, with per-person toggles,
// a shared clock and a close. The refused person never appears. A fake API is installed with page.route;
// the harness is tests/part7/harness/watchall.html.
//   PLAYWRIGHT_DIR=/path/to/node_modules node tests/part7/watchall.browser.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const replay = JSON.parse(fs.readFileSync(path.join(here, "../../fixtures/input/replay.json")));

const JOB = {
  id: "w1", kind: "group", status: "done",
  result: {
    trainer_id: 1,
    people: [
      { id: 2, label: "Front row left", status_code: "ok", score: 88, grade: "B", faults: [{}, {}] },
      { id: 3, label: "Front row right", status_code: "ok", score: 73, grade: "C", faults: [{}] },
      { id: 5, label: "Middle", status_code: "ok", score: 61, grade: "D", faults: [] },
      { id: 4, label: "Back row", status_code: "error", status_text: "This person could not be analysed.", score: null, grade: null, faults: [] },
    ],
  },
};
const SCORED = ["2", "3", "5"];
const REFUSED = "4";
const replayHits = [];

async function install(page) {
  await page.route("**/api/**", async (route) => {
    const p = new URL(route.request().url()).pathname.replace(/^.*\/api\//, "api/");
    let m;
    if (p === "api/client-log") return route.fulfill({ status: 204, body: "" });
    if (/^api\/jobs\/w1\/people\/\d+\.jpg$/.test(p)) {
      return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="32"><rect width="24" height="32" fill="#1b2431"/></svg>' });
    }
    if (p === "api/jobs/w1")return route.fulfill({ contentType: "application/json", body: JSON.stringify(JOB) });
    if ((m = /^api\/results\/w1\/(\d+)\/replay\.json$/.exec(p))) {
      replayHits.push(m[1]);
      // the refused person has a readable replay too, so only the board can keep them out of the view
      const r = structuredClone(replay);
      const shift = Number(m[1]) % 3;
      r.follower = r.follower.map((_, i, a) => a[(i + shift * 6) % a.length]);
      return route.fulfill({ contentType: "application/json", body: JSON.stringify(r) });
    }
    return route.fulfill({ status: 404, body: "{}" });
  });
}

const { server, port } = await serveRoot();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const tid = (page, id) => page.getByTestId(id);
const attr = (page, name) => tid(page, "multi-compare").getAttribute(name);
const cols = async (page, name) => (await attr(page, name)).split(",");

try {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, hasTouch: true });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(e.message));
  await install(page);
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/watchall.html#/group/w1`);
  await page.waitForFunction(() => window.__ready === true);
  await tid(page, "group-board").waitFor();
  assert.equal(await tid(page, "multi-compare").count(), 0);
  assert.equal(await tid(page, "watch-all-panel").isHidden(), true);
  assert.equal(await tid(page, `group-row-${REFUSED}`).getAttribute("data-refused"), "true");
  ok("the board lists four rows and Watch all is closed");

  // ---- open: a canvas, a legend and toggles for the scored people only ---------------------------
  await tid(page, "watch-all").click();
  await tid(page, "multi-compare").waitFor();
  await tid(page, "group-toggle-2").waitFor();
  await page.waitForFunction(() => document.querySelector('[data-testid="multi-compare"]').hasAttribute("data-joints-drawn"));
  assert.equal(await tid(page, "watch-all").getAttribute("aria-expanded"), "true");
  assert.equal(await tid(page, "watch-all-panel").isVisible(), true);
  const canvas = await page.evaluate(() => { const c = document.querySelector('[data-testid="multi-compare"] canvas'); return c ? { w: c.width, h: c.height } : null; });
  assert.ok(canvas && canvas.w > 0 && canvas.h > 0, "a canvas with a size is in the view");
  assert.equal(await page.locator('[data-testid="multi-compare"] canvas').count(), 1);
  ok("Watch all renders a sized canvas");

  assert.equal(await attr(page, "data-people"), SCORED.join(","));
  const toggleIds = await page.$$eval('[data-testid^="group-toggle-"]', (b) => b.map((x) => x.getAttribute("data-testid").replace("group-toggle-", "")));
  assert.deepEqual(toggleIds, SCORED);
  const toggleText = await page.$$eval(".pp-toggle", (b) => b.map((x) => x.textContent));
  assert.deepEqual(toggleText, ["Front row left", "Front row right", "Middle"]);
  assert.equal(await tid(page, `group-toggle-${REFUSED}`).count(), 0);
  const legend = await page.$$eval(".sr-legend li", (l) => l.map((x) => x.textContent));
  assert.deepEqual(legend, ["Trainer"]);
  const drawn0 = await cols(page, "data-joints-drawn");
  assert.equal(drawn0.length, 4, "trainer ghost plus three people");
  assert.ok(drawn0.every((n) => Number(n) > 0), `every figure has joints drawn: ${drawn0}`);
  assert.equal(await page.locator('.pp-toggle[aria-pressed="true"]').count(), 3);
  ok("every scored person has a toggle and a drawn figure, the refused one has neither");

  // ---- negative: the refused person is not in the overlay text or the figure count -----------------
  assert.equal(await page.locator('[data-testid="multi-compare"]').getByText("Back row").count(), 0);
  assert.ok(!(await attr(page, "data-people")).split(",").includes(REFUSED));
  assert.equal((await cols(page, "data-bones-drawn")).length, 4);
  assert.ok(!replayHits.includes(REFUSED), `the refused replay was never requested: ${replayHits}`);
  ok("the refused person is not named in the view and has no figure");

  // ---- toggle hides one person -------------------------------------------------------------------
  await tid(page, "group-toggle-3").click();
  assert.equal(await tid(page, "group-toggle-3").getAttribute("aria-pressed"), "false");
  assert.equal(await attr(page, "data-hidden"), "3");
  await page.waitForFunction(() => document.querySelector('[data-testid="multi-compare"]').getAttribute("data-joints-drawn").split(",")[2] === "-");
  const hiddenDrawn = await cols(page, "data-joints-drawn");
  assert.equal(hiddenDrawn[2], "-", "person 3 is not drawn");
  assert.ok(hiddenDrawn[0] !== "-" && hiddenDrawn[1] !== "-" && hiddenDrawn[3] !== "-", `the others still are: ${hiddenDrawn}`);
  assert.equal(await tid(page, "group-toggle-2").getAttribute("aria-pressed"), "true");
  assert.equal((await cols(page, "data-bones-drawn"))[2], "-");
  ok("a toggle hides that person only (aria-pressed, data-hidden, draw stats)");

  await tid(page, "group-toggle-3").click();
  assert.equal(await attr(page, "data-hidden"), "");
  await page.waitForFunction(() => document.querySelector('[data-testid="multi-compare"]').getAttribute("data-joints-drawn").split(",")[2] !== "-");
  assert.equal(await tid(page, "group-toggle-3").getAttribute("aria-pressed"), "true");
  ok("toggling again shows them");

  // ---- play and scrub move the shared clock ------------------------------------------------------
  assert.equal(await tid(page, "clock").getAttribute("data-t"), "0");
  await tid(page, "play").click();
  assert.equal(await tid(page, "play").getAttribute("data-playing"), "true");
  await page.waitForFunction(() => Number(document.querySelector('[data-testid="clock"]').getAttribute("data-t")) > 0.3);
  await tid(page, "play").click();
  assert.equal(await tid(page, "play").getAttribute("data-playing"), "false");
  const paused = Number(await tid(page, "clock").getAttribute("data-t"));
  assert.ok(paused > 0.3);
  assert.ok(Math.abs(Number(await tid(page, "scrub").inputValue()) - paused) < 1e-6, "the scrubber follows the clock");
  await page.waitForTimeout(300);
  assert.equal(Number(await tid(page, "clock").getAttribute("data-t")), paused, "paused means the clock holds");
  ok("play advances the clock and pause holds it");

  const max = Number(await tid(page, "scrub").getAttribute("max"));
  const target = Math.round((max / 2) * 10) / 10;
  await tid(page, "scrub").evaluate((e, v) => { e.value = String(v); e.dispatchEvent(new Event("input", { bubbles: true })); }, target);
  assert.ok(Math.abs(Number(await tid(page, "clock").getAttribute("data-t")) - target) < 0.05);
  assert.equal(await tid(page, "clock").textContent(), `${target.toFixed(1)} s`);
  assert.equal((await cols(page, "data-joints-drawn")).length, 4);
  await tid(page, "scrub").evaluate((e) => { e.value = "0"; e.dispatchEvent(new Event("input", { bubbles: true })); });
  assert.equal(await tid(page, "clock").getAttribute("data-t"), "0");
  assert.equal(await tid(page, "clock").textContent(), "0.0 s");
  ok("scrubbing sets the shared clock and its readout, both ways");

  // ---- close returns to the board ---------------------------------------------------------------
  await tid(page, "watch-all").click();
  assert.equal(await tid(page, "multi-compare").count(), 0);
  assert.equal(await page.locator("canvas").count(), 0);
  assert.equal(await tid(page, "watch-all-panel").isHidden(), true);
  assert.equal(await tid(page, "watch-all").getAttribute("aria-expanded"), "false");
  assert.equal(await tid(page, "watch-all").textContent(), "Watch all");
  assert.equal(await tid(page, "group-board").isVisible(), true);
  assert.equal(await page.locator('[data-testid^="group-row-"]').count(), 4);
  ok("closing removes the view and canvas and keeps the board");

  // ---- reopen works, then leaving the route tears it down --------------------------------------
  await tid(page, "watch-all").click();
  await tid(page, "group-toggle-5").waitFor();
  assert.equal(await attr(page, "data-people"), SCORED.join(","));
  await page.evaluate(() => { location.hash = "#/elsewhere"; });
  await page.waitForFunction(() => document.getElementById("app").textContent.startsWith("elsewhere"));
  assert.equal(await page.locator("canvas").count(), 0);
  ok("reopening works and leaving the route destroys the view");

  assert.deepEqual(errors, [], `console errors: ${errors.join(" | ")}`);
  ok("no console or page errors");
} finally {
  await browser.close();
  server.close();
}
console.log(`${passed} browser checks passed`);
