// Browser checks for the video-quality result screen at 412x915, with Part 5's three display fixtures
// (fixtures/input/quality/analysis-{none,minor,major}.json). Run:
//   PLAYWRIGHT_DIR=/path/to/node_modules node tests/part7/quality-result.browser.mjs
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const { server, port } = await serveRoot();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };

async function open(kase) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, hasTouch: true });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error") errors.push(`${kase}: ${m.text()}`); });
  page.on("pageerror", (e) => errors.push(`${kase}: ${e.message}`));
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/quality-result.html?case=${kase}`);
  await page.waitForFunction(() => window.__ready === true);
  await page.waitForTimeout(300);
  return page;
}
const count = (page, id) => page.getByTestId(id).count();

try {
  const none = await open("none");
  assert.equal(await count(none, "quality-tips"), 0);
  assert.equal(await count(none, "quality-cap"), 0);
  assert.equal(await count(none, "warning"), 0);
  ok("no quality: no tips section, no cap line, no banner");

  const minor = await open("minor");
  assert.ok(await minor.getByTestId("quality-tips").isVisible());
  assert.ok(await minor.getByTestId("quality-tip-dark").isVisible());
  assert.equal(await count(minor, "quality-cap"), 0, "a minor issue never mentions a cap");
  assert.equal(await count(minor, "warning"), 0, "a minor issue adds no warning banner");
  assert.match(await minor.getByTestId("quality-tip-dark").innerText(), /At 1\.2 s/);
  assert.equal(await count(minor, "quality-time-future_camera_issue"), 0, "no at_s, no time chip");
  ok("minor: tips section with a tip per issue, no banner, no cap line");

  await minor.evaluate(() => { window.__events.length = 0; });
  await minor.getByTestId("quality-time-dark").click();
  const events = await minor.evaluate(() => window.__events);
  assert.deepEqual(events.map((e) => e.at_s), [1.2]);
  ok("the time chip dispatches simon:seek with at_s");

  const major = await open("major");
  assert.ok(await major.getByTestId("warning").isVisible());
  assert.ok(await major.getByTestId("warning-quality_dark").isVisible());
  assert.ok(await major.getByTestId("warning-tip-quality_dark").isVisible());
  assert.equal(await major.getByTestId("warning-moving_part_out_of_frame").getAttribute("data-cause"), "body_cut_off");
  assert.equal((await major.getByTestId("quality-cap").innerText()).trim(), "Capped at 59 because of the video quality.");
  assert.ok(await major.getByTestId("record-again").isVisible());
  ok("major: banner with tips, the cause on the existing warning, cap line, Record again");

  assert.deepEqual(errors, []);
  ok("no console errors");
} finally {
  await browser.close();
  server.close();
}
console.log(`${passed} quality-result browser checks passed`);
