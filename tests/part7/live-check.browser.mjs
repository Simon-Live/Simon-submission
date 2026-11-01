// Live check (client 22d09a7 / c76b618, TICKET-187) on the running capture widget with a stand-in for MediaPipe.
// PLAYWRIGHT_DIR=/path/to/node_modules [CHROME_EXECUTABLE=/path/to/chrome] node tests/part7/live-check.browser.mjs
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";
import { serveRoot } from "./serve_static.mjs";

const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve("node_modules"), "x.js"));
const { chromium } = req("playwright");
const { server, port } = await serveRoot();
const browser = await chromium.launch({
  ...(process.env.CHROME_EXECUTABLE ? { executablePath: process.env.CHROME_EXECUTABLE } : {}),
  args: ["--autoplay-policy=no-user-gesture-required"],
});
try {
  const page = await browser.newPage({ viewport: { width: 412, height: 915 } });
  const errors = [];
  const external = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => { if (!r.url().startsWith(`http://127.0.0.1:${port}`) && !r.url().startsWith("blob:") && !r.url().startsWith("data:")) external.push(r.url()); });
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/live-check.html`);
  await page.getByTestId("live-toggle").waitFor();
  await page.waitForFunction(() => document.querySelector('[data-testid="preview"]').videoWidth > 0);

  // off by default: nothing is loaded and nothing is drawn, with the reason stated
  assert.equal(await page.getByTestId("live-toggle").textContent(), "Live check: off");
  assert.equal(await page.evaluate(() => window.__loads), 0);
  assert.match(await page.getByTestId("live-note").textContent(), /loads Google's MediaPipe/);
  assert.equal(await page.getByTestId("live-status").isHidden(), true);
  console.log("ok - the live check starts off: no model load, no chip, the note says what turning it on does");

  await page.getByTestId("live-toggle").click();
  await page.getByTestId("live-status").filter({ hasText: "Step back: your feet is out of view" }).waitFor({ timeout: 8000 });
  assert.equal(await page.getByTestId("live-toggle").textContent(), "Live check: on");
  assert.equal(await page.evaluate(() => window.__loads), 1);
  assert.equal(await page.getByTestId("live-status").getAttribute("data-ok"), "false");
  assert.match(await page.getByTestId("live-note").textContent(), /approximate/);
  const drawn = await page.getByTestId("live-canvas").evaluate((c) => {
    const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    return d.some((v, i) => i % 4 === 3 && v > 0);
  });
  assert.ok(drawn, "joints are drawn on the canvas over the preview");
  const accent = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--live-ok").trim());
  assert.ok(accent, "the joint colours come from the --live-* tokens");
  console.log("ok - turned on: the chip names what is out of view and joints are drawn from the token colours");

  await page.getByTestId("live-toggle").click();
  await page.getByTestId("live-status").waitFor({ state: "hidden" });
  const cleared = await page.getByTestId("live-canvas").evaluate((c) => !c.getContext("2d").getImageData(0, 0, c.width, c.height).data.some((v, i) => i % 4 === 3 && v > 0));
  assert.ok(cleared, "turned off, the canvas is cleared");
  assert.equal(await page.evaluate(() => localStorage.getItem("simon.liveCheck")), "off");
  assert.deepEqual(external, [], "the stand-in loader means no request left the machine");
  assert.deepEqual(errors, []);
  console.log("ok - turned off again: chip hidden, canvas cleared, choice remembered");
  console.log("3 live-check browser checks passed");
} finally {
  await browser.close();
  server.close();
}
