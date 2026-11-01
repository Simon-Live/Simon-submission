// Browser checks for the Shape or timing breakdown at 412x915 (docs/specs/breakdown.md). Run:
//   node tests/part7/breakdown.browser.mjs
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
const load = (f) => JSON.parse(fs.readFileSync(path.join(here, "fixtures/input", `${f}.json`)));

const { server, port } = await serveRoot();
const browser = await chromium.launch();
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok: ${name}`); };

async function open(kase) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error" && !isResultScreen404(m.location().url)) errors.push(`${kase}: ${m.text()}`); });
  page.on("pageerror", (e) => errors.push(`${kase}: ${e.message}`));
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/breakdown.html?case=${kase}`);
  await page.waitForFunction(() => window.__ready === true);
  await page.waitForSelector("[data-testid=breakdown]");
  return page;
}
const text = (page, id) => page.getByTestId(id).first().textContent();

try {
  // rushing: shape also lost, tempo insight present
  const rush = await open("breakdown-rushing");
  const a = load("breakdown-rushing");
  assert.match(await text(rush, "tempo-line"), /^Rushing: your moves took 37% of the trainer's time$/);
  assert.equal(await rush.getByTestId("tempo-line").getAttribute("data-tempo"), "rushing");
  assert.match(await text(rush, "breakdown-verdict"), /^Most of your lost points are shape: /);
  assert.match(await text(rush, "timing-note"), /does not lower your score/);
  const tempoRow = rush.locator("[data-cue-kind=tempo]");
  assert.equal(await tempoRow.count(), 1);
  assert.equal((await tempoRow.getByTestId("kind-tag").allTextContents()).join(), "Timing");
  const shapeRows = rush.locator("[data-cue-kind=range], [data-cue-kind=position]");
  const n = await shapeRows.count();
  assert.ok(n >= 4);
  assert.equal(await rush.locator("[data-cue-kind=range] [data-testid=kind-tag], [data-cue-kind=position] [data-testid=kind-tag]").count(), n);
  for (const t of await rush.locator("[data-cue-kind=range] [data-testid=kind-tag]").allTextContents()) assert.equal(t, "Shape");
  assert.equal(await rush.getByTestId("kind-tag").count(), n + 1);
  assert.equal(a.score.tempo.ratio, 0.37);
  ok("rushing fixture: Rushing line, shape verdict, Timing tag on the tempo row and Shape tags on the others");

  // witness 2: the split in the DOM equals the sum of Part 5's miss points
  const misses = a.score.timeline.flatMap((w) => w.misses);
  const sumOf = (k) => Math.round(misses.filter((m) => m.cue_kind === k).reduce((s, m) => s + m.points, 0) * 10) / 10;
  assert.equal(await text(rush, "shape-position"), `Where a body part is${sumOf("position")} points lost`);
  assert.equal(await text(rush, "shape-range"), `How far you move${sumOf("range")} points lost`);
  ok("shape split equals the sum of the timeline miss points by cue_kind");

  // idempotent re-mount
  await rush.evaluate(() => window.__remount());
  await rush.evaluate(() => window.__remount());
  assert.equal(await rush.getByTestId("kind-tag").count(), n + 1);
  assert.equal(await rush.getByTestId("breakdown").count(), 1);
  ok("re-mounting twice leaves one panel and one tag per row");

  // seek event
  const moments = rush.getByTestId("tempo-moment");
  assert.equal(await moments.count(), 8);
  await moments.nth(3).click();
  const seeks = await rush.evaluate(() => window.__seeks);
  assert.deepEqual(seeks, [{ at_s: a.score.timeline[3].t_s[0] }]);
  ok("tapping a tempo moment fires simon:seek with its at_s");

  // body note
  const note = rush.getByTestId("body-note");
  assert.match(await note.locator("summary").textContent(), /^Scored on a standard body$/);
  assert.equal(await note.locator("p").first().isHidden(), true);
  await note.locator("summary").click();
  assert.match(await note.locator("p").first().textContent(), /1\.70 m/);
  assert.equal(await note.locator("p").first().isVisible(), true);
  await rush.screenshot({ path: path.join(SHOTS, "breakdown-rushing.png"), fullPage: true });
  ok("body note is closed by default and opens to the plain-words explanation");

  // negative: on the beat
  const on = await open("breakdown-onbeat");
  assert.equal(await text(on, "tempo-line"), "On the beat");
  assert.doesNotMatch(await text(on, "breakdown-verdict"), /timing is off/);
  assert.doesNotMatch(await text(on, "breakdown"), /Rushing|Dragging/);
  assert.equal(await on.locator("[data-cue-kind=tempo]").count(), 0);
  assert.equal(await on.locator("[data-testid=kind-tag]", { hasText: "Timing" }).count(), 0);
  assert.equal(await on.getByTestId("tempo-moment").count(), 0);
  ok("on-the-beat fixture: no Timing verdict, no Rushing or Dragging, no Timing tags, no moments");

  // dragging with close shape
  const drag = await open("breakdown-dragging");
  assert.equal(await text(drag, "breakdown-verdict"), "Your shape is close; the timing is off: dragging");
  assert.match(await text(drag, "tempo-line"), /^Dragging: your moves took 1\.4 times the trainer's time$/);
  assert.equal(await drag.locator("[data-cue-kind=tempo] [data-testid=kind-tag]").textContent(), "Timing");
  ok("dragging fixture with a close shape: timing verdict and Dragging line");

  // rehab: Part 5 says slower is fine, so the panel reassures and lists no timing problem
  const rs = await open("breakdown-rehab-slow");
  assert.equal(await text(rs, "tempo-line"), "Slower than the trainer, and that is fine in rehab");
  assert.equal(await rs.getByTestId("tempo-line").getAttribute("data-tempo"), "slow-ok");
  assert.doesNotMatch(await text(rs, "breakdown-verdict"), /timing is off|dragging/i);
  assert.equal(await rs.getByTestId("breakdown").getAttribute("data-verdict"), "both-good");
  assert.equal(await rs.getByTestId("tempo-moment").count(), 0);
  assert.equal(await rs.locator("[data-cue-kind=tempo]").count(), 0);
  assert.doesNotMatch(await rs.getByTestId("breakdown").textContent(), /Dragging/);
  ok("rehab slow fixture: reassurance line, no Timing verdict, no Dragging, no moments, no Timing tag");

  // rehab fast still rushes
  const rf = await open("breakdown-rehab-fast");
  assert.match(await text(rf, "tempo-line"), /^Rushing: /);
  assert.equal(await rf.getByTestId("tempo-line").getAttribute("data-tempo"), "rushing");
  assert.equal(await rf.locator("[data-cue-kind=tempo] [data-testid=kind-tag]").textContent(), "Timing");
  ok("rehab fast fixture: still Rushing with a Timing tag");

  // old Part 5: no timeline, no tempo
  const old = await open("breakdown-old");
  assert.match(await text(old, "breakdown-verdict"), /^Most of your lost points are shape: how far you move$/);
  assert.equal(await text(old, "tempo-line"), "No timing detail in this analysis.");
  assert.equal(await text(old, "shape-range"), "How far you move2 found");
  assert.equal(await old.getByTestId("body-note").count(), 1);
  ok("old analysis without timeline or tempo shows what exists");

  assert.deepEqual(errors, []);
  ok("no console errors");
  console.log(`${passed} checks passed`);
} finally {
  await browser.close();
  server.close();
}
