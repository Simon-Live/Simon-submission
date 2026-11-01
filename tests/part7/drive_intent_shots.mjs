// Before and after screenshots at 412x915 for docs/specs/result-intent.md (the intent carried forward from the parked
// lane/rubric-result-parked-visual 2f8dd0d). It only uses harness pages that exist on main before the change, so the
// same script takes both sets:
//   PLAYWRIGHT_DIR=<node_modules> node tests/part7/drive_intent_shots.mjs <out dir> <before|after>
// Shots: the first screen, the moment marks of a real take with two misses at 0.9 s (job 5277380db1e1, routed in
// place of the coach harness's analysis), the stage after the reveal, and the whole screen.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const [out = path.join(here, "screens"), prefix = "after"] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const JOB = "abcdef123456";
const REAL = path.join(here, "fixtures/history/5277380db1e1/analysis.json");

const { server, port } = await serveRoot();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--autoplay-policy=no-user-gesture-required"] });
const shot = (name) => path.join(out, `${prefix}-${name}.png`);
const json = (route, body) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

async function page(url, routes = async () => {}) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, hasTouch: true });
  const p = await ctx.newPage();
  await routes(p);
  await p.goto(`http://127.0.0.1:${port}${url}`);
  await p.waitForFunction(() => window.__ready === true);
  return p;
}

try {
  // the real job's screen (result-additions harness, the job's files answered as in result_additions.browser.mjs)
  const full = await page("/tests/part7/harness/result-additions.html?case=ok", async (p) => {
    await p.route(`**/api/results/${JOB}/video.mp4`, (r) => r.continue({ url: `http://127.0.0.1:${port}/tests/part7/fixtures/coach.webm` }));
    await p.route("**/api/auth/me", (r) => json(r, { available: false }));
    await p.route(`**/api/results/${JOB}/models.json`, (r) => r.fulfill({ status: 404, body: "" }));
    await p.route(`**/api/results/${JOB}/skeleton2d.json`, (r) => r.fulfill({ status: 404, body: "" }));
    await p.route(`**/api/results/${JOB}/mesh.json`, (r) => json(r, { trainer: null, you: null }));
    await p.route("**/catalog/api/entries/*", (r) => json(r, { id: "lateral-raise-0f13199f", name: "Lateral raise" }));
  });
  await full.waitForTimeout(2500);
  await full.screenshot({ path: shot("first-screen") });
  await full.locator('[data-testid="compare"]').evaluate((n) => n.scrollIntoView({ block: "center" }));
  await full.waitForTimeout(400);
  await full.screenshot({ path: shot("stage-mid") });
  await full.waitForTimeout(2000);
  await full.screenshot({ path: shot("stage") });
  await full.screenshot({ path: shot("full"), fullPage: true });
  console.log(`${prefix}: compare mode ${await full.locator('[data-testid="compare"]').getAttribute("data-mode")}`);
  await full.context().close();

  // a real take with two misses at 0.9 s: the marks on the strip under the video
  const real = fs.readFileSync(REAL, "utf8");
  const marks = await page("/tests/part7/harness/coach.html?case=ok", (p) => p.route("**/fixtures/input/analysis-insights.json",
    (r) => r.fulfill({ status: 200, contentType: "application/json", body: real })));
  await marks.locator('[data-testid="moments-strip"]').evaluate((n) => n.scrollIntoView({ block: "center" }));
  await marks.waitForTimeout(800);
  await marks.screenshot({ path: shot("coincident-marks") });
  const boxes = await marks.locator('[data-testid^="moment-marker-"]').evaluateAll((els) => els.map((e) => {
    const r = e.getBoundingClientRect();
    return `${e.dataset.testid} x=${r.left.toFixed(0)} w=${r.width.toFixed(0)} label="${e.getAttribute("aria-label")}"`;
  }));
  console.log(`${prefix}: ${boxes.length} marks\n  ${boxes.join("\n  ")}`);
  await marks.context().close();
} finally {
  await browser.close();
  server.close();
}
