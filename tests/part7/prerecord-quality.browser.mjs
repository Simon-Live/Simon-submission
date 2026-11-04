// PLAYWRIGHT_DIR=/path/to/node_modules [CHROME_EXECUTABLE=/path/to/chrome] node tests/part7/prerecord-quality.browser.mjs
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";
import { serveRoot } from "./serve_static.mjs";

const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve("node_modules"), "x.js"));
const { chromium } = req("playwright");
const { server, port, logs } = await serveRoot();
const browser = await chromium.launch({
  ...(process.env.CHROME_EXECUTABLE ? { executablePath: process.env.CHROME_EXECUTABLE } : {}),
  args: ["--autoplay-policy=no-user-gesture-required"],
});
try {
  const page = await browser.newPage({ viewport: { width: 412, height: 915 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/prerecord-quality.html`);
  const tips = page.getByTestId("prerecord-tips");
  await page.getByTestId("prerecord-tip-dark").waitFor();
  assert.equal(await tips.getAttribute("aria-live"), "polite");
  assert.ok(await page.getByTestId("framing-hint").isVisible());
  assert.ok(await page.getByTestId("cam-start").isEnabled());
  assert.ok(await tips.locator("p").count() <= 2);
  console.log("ok - dark preview has a polite tip, framing hint and an enabled Record button");

  await page.evaluate(() => { window.__scene = "good"; });
  await page.waitForTimeout(900);
  assert.ok(await page.getByTestId("prerecord-tip-dark").isVisible());
  await tips.waitFor({ state: "hidden", timeout: 4000 });
  console.log("ok - a tip stays during recovery and clears after good readings");

  await page.evaluate(() => { window.__scene = "dark"; });
  await page.getByTestId("prerecord-tip-dark").waitFor();
  const overlay = page.getByTestId("cam-rec");
  assert.ok(await overlay.isVisible() && await overlay.getAttribute("aria-label") === "Record" && await overlay.isEnabled());
  await overlay.click(); // the record button on the preview presses Record below
  await page.getByTestId("cam-stop").waitFor();
  assert.equal(await overlay.getAttribute("aria-label"), "Stop");
  assert.ok(await tips.isHidden());
  const samples = await page.evaluate(() => window.__samples);
  await page.waitForTimeout(1200);
  assert.equal(await page.evaluate(() => window.__samples), samples);
  const qualityLogs = logs.filter((entry) => entry.event === "prerecord_quality");
  assert.equal(qualityLogs.length, 1);
  assert.ok(qualityLogs[0].detail.sample_count > 0);
  assert.ok(Object.values(qualityLogs[0].detail).every((value) => typeof value === "number" && Number.isFinite(value)));
  assert.equal(qualityLogs[0].detail.threshold_sample_ms, 500);
  console.log("ok - recording stops sampling and logs one numeric-only reading summary with thresholds");

  await overlay.click(); // and the same button stops
  await page.getByTestId("take-preview").waitFor();
  assert.ok(await overlay.isHidden(), "no record button on a take");
  assert.ok(await tips.isHidden());
  await page.evaluate(() => window.capture.reset());
  await page.getByTestId("prerecord-tip-dark").waitFor();
  await page.evaluate(() => window.__destroy());
  const lastSamples = await page.evaluate(() => window.__samples);
  await page.waitForTimeout(700);
  assert.equal(await page.evaluate(() => window.__samples), lastSamples);
  assert.deepEqual(errors, []);
  console.log("ok - recording again restarts checks and destroying capture stops them");
  console.log("4 pre-record browser checks passed");
} finally {
  await browser.close();
  server.close();
}
