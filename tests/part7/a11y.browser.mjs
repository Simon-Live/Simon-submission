// Accessibility pass over the 2026-10-31 screens at 412x915 and 1280x800 (docs/specs/ui-polish.md):
// axe-core finds zero serious or critical violations; tap targets are >= 44 px; nothing overflows sideways;
// the moments, share feedback and toggles carry their roles and states. Pages: the existing harnesses on tests/part7/fake_api.py.
//   /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/a11y.browser.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const AXE = fs.readFileSync(req.resolve("axe-core/axe.min.js"), "utf8");

process.on("uncaughtException", (e) => { console.error(e); process.exit(1); });
process.on("exit", () => server?.kill());
const PORT = 8000 + Math.floor(Math.random() * 300);
const BASE = `http://127.0.0.1:${PORT}`;
const server = spawn("python3", [path.join(here, "fake_api.py"), String(PORT)], { stdio: "inherit" });
for (let i = 0; i < 50; i++) {
  try { if ((await fetch(`${BASE}/api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 100)); }
}
const { server: staticServer, port: staticPort } = await serveRoot();
const STATIC = `http://127.0.0.1:${staticPort}/tests/part7/harness`;
const day = 86400000;
const iso = (offset) => new Date(Date.now() + offset).toISOString().replace(/\.\d+Z$/, "Z");
const entry = (name, score, grade, strongest) => ({ name, score, grade, job_id: "x", pid: null, created_at: "2026-10-30T10:00:00Z", strongest_section: strongest });
const seed = (doc) => fetch(`${BASE}/__test/challenges`, { method: "POST", body: JSON.stringify(doc) });
const base = { entry_id: "lateral-raise", kind: "friend", created_at: iso(-day), ends_at: null, sponsor: null };
await seed({ ...base, id: "board1", title: "Beat my Dumbbell lateral raise", creator_name: "Sam",
  entries: [entry("High", 91, "A", { label: "Rep 2", value: 95, t_s: [3, 6] }), entry("Low", 55, "D", null)] });
await seed({ ...base, id: "crew1", title: "Crew night", creator_name: "Kim", kind: "crew", entries: [entry("Ana", 77, "C", null)] });
await seed({ ...base, id: "spons1", title: "Raise the roof", kind: "sponsored", creator_name: "Example Sportswear", ends_at: iso(3 * day + 3600000),
  sponsor: { name: "Example Sportswear", tagline: "Move more, every day", url: "https://example.com/shop", prize: "A pair of running shoes" },
  entries: [entry("Ana", 77, "C", null)] });
await seed({ ...base, id: "ended1", title: "Old news", ends_at: iso(-day), entries: [entry("Zed", 66, "C", null)] });

const H = "/__harness";
const PAGES = [
  ["result-coach", `${STATIC}/coach.html?case=ok`, "[data-testid=moments]"],
  ["result-insights", `${STATIC}/result.html?case=insights`, ".simon-result"],
  ["breakdown", `${STATIC}/breakdown.html?case=breakdown-rushing`, "[data-testid=score-panel]"],
  ["challenge-actions", `${H}/challenge.html?screen=actions&job=job1&entry=lateral-raise&score=61`, "[data-testid=challenge-create]"],
  ["challenge-crew-button", `${H}/challenge.html?screen=crew&job=grp1&entry=salsa-basic`, "[data-testid]"],
  ["leaderboard-friend", "/#/challenge/board1", "[data-testid=leaderboard]"],
  ["leaderboard-crew", "/#/challenge/crew1", "[data-testid=leaderboard]"],
  ["leaderboard-sponsored", "/#/challenge/spons1", "[data-testid=sponsor-banner]"],
  ["leaderboard-ended", "/#/challenge/ended1", "[data-testid=leaderboard]"],
  ["catalog", "/#/", "[data-testid]"],
  ["follow", "/#/follow/lateral-raise", ".mode-picker"],
];
const SIZES = [["phone", 412, 915], ["desktop", 1280, 800]];
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--autoplay-policy=no-user-gesture-required"] });
const failures = [];
let passed = 0;

async function audit(size, name, page, scope = "body") {
  await page.evaluate(AXE);
  const res = await page.evaluate(() => axe.run(document, { resultTypes: ["violations"], rules: { "html-has-lang": { enabled: !/^\/(tests|__harness)\//.test(location.pathname) }, "page-has-heading-one": { enabled: false }, region: { enabled: false } } }));
  for (const v of res.violations.filter((x) => ["serious", "critical"].includes(x.impact))) {
    failures.push(`${size} ${name}: axe ${v.id} (${v.impact}) ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
  }
  const geo = await page.evaluate((scope) => {
    const label = (e) => `${e.tagName.toLowerCase()}[${e.dataset.testid || e.className || e.textContent.trim().slice(0, 20)}]`;
    const small = [...document.querySelectorAll(`${scope} button, ${scope} a[href], ${scope} summary, ${scope} input:not([type=hidden]):not([type=file]), ${scope} select`)].filter((e) => {
      if (e.matches("input") && e.closest("label")?.getBoundingClientRect().height >= 43.5) return false; // the label is the target
      const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
      return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && (r.height < 43.5 || r.width < 43.5);
    }).map((e) => `${label(e)} ${Math.round(e.getBoundingClientRect().width)}x${Math.round(e.getBoundingClientRect().height)}`);
    return { small, overflow: document.documentElement.scrollWidth - innerWidth };
  }, scope);
  for (const s of geo.small) failures.push(`${size} ${name}: small target ${s}`);
  if (geo.overflow > 0) failures.push(`${size} ${name}: sideways overflow ${geo.overflow}px`);
}

for (const [size, width, height] of SIZES) {
  for (const [name, url, ready] of PAGES) {
    const ctx = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce" });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(url.startsWith("http") ? url : `${BASE}${url}`);
    try { await page.locator(ready).first().waitFor({ timeout: 6000 }); } catch { failures.push(`${size} ${name}: never rendered ${ready}`); }
    await page.waitForTimeout(500);
    await audit(size, name, page, name === "breakdown" ? "[data-testid=breakdown-slot]" : "body"); // the harness rows beside the slot are unstyled stand-ins
    if (errors.length) failures.push(`${size} ${name}: page errors ${errors.join("; ")}`);
    await ctx.close();
    passed++;
    console.log(`checked - ${size} ${name}`);
  }
}

// ---- states: what a person reaches by tapping, on both sizes ---------------------------------------------------
const tid = (page, id) => page.getByTestId(id);
const intersects = (a, b) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
const rep = (n, ...ms) => ({ rep: n, movement: "raise", keyframes: ms.map((t_ms, i) => ({ name: `k${i}`, frame: t_ms / 40, t_ms })) });
const KEYFRAMES = { fps: 25, people: [{ id: 0, repetitions: [rep(1, 0, 1500), rep(2, 4000, 5500), rep(3, 8000, 9500)] }] };
async function visit(size, width, height, url, ready, { keyframes = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce", hasTouch: width < 600 });
  const page = await ctx.newPage();
  if (keyframes) { // the fake API has no keyframes file; the ladder needs three reps to draw
    await page.route("**/catalog/api/entries/lateral-raise/keyframes.json", (r) => r.fulfill({ json: KEYFRAMES }));
    await page.route("**/catalog/api/entries/lateral-raise", async (r) => r.fulfill({ json: { ...(await (await r.fetch()).json()), keyframes: "keyframes.json", duration_ms: 12000 } }));
  }
  await page.goto(url.startsWith("http") ? url : `${BASE}${url}`);
  await page.locator(ready).first().waitFor({ timeout: 6000 });
  return { ctx, page };
}
for (const [size, width, height] of SIZES) {
  // the result screen: moments are toggles, the video never sits under a control, the worst-moment button pairs with its note
  let { ctx, page } = await visit(size, width, height, `${STATIC}/coach.html?case=ok`, "[data-testid=moments]");
  const rows = page.locator('[data-testid^="moment-"][data-at]:not([data-testid^="moment-marker"])');
  assert.ok((await rows.count()) > 1, `${size}: several moments to review`);
  assert.equal(await page.locator('[data-testid^="moment-"][aria-pressed="true"]').count(), 0, `${size}: negative: nothing pressed before a tap`);
  await tid(page, "moment-0").click();
  assert.equal(await tid(page, "moment-0").getAttribute("aria-pressed"), "true");
  assert.equal(await tid(page, "moment-marker-0").getAttribute("aria-pressed"), "true", `${size}: the marker and the row share one state`);
  assert.equal(await tid(page, "moment-1").getAttribute("aria-pressed"), "false");
  await tid(page, "replay-worst").click();
  assert.equal(await tid(page, "replay-worst").getAttribute("aria-pressed"), "true");
  const boxes = await page.evaluate(() => {
    const r = (q) => { const e = document.querySelector(q); if (!e) return null; const b = e.getBoundingClientRect(); return { x: b.x, y: b.y, width: b.width, height: b.height }; };
    return { video: r('[data-testid="result-video"]'), bar: r(".sr-coach-bar"), marks: r(".sr-marks"), canvas: r(".sr-stage canvas") };
  });
  for (const k of ["bar", "marks"]) assert.ok(!boxes.video || !intersects(boxes.video, boxes[k]), `${size}: the video does not overlap ${k}`);
  await audit(size, "result-coach-pressed", page);
  await ctx.close();

  // the share step: feedback is announced, the picture has a name, the fields are labelled
  ({ ctx, page } = await visit(size, width, height, `${H}/challenge.html?screen=actions&job=job1&entry=lateral-raise&score=61`, "[data-testid=challenge-create]"));
  await tid(page, "challenge-create").click();
  await tid(page, "challenge-error").waitFor();
  assert.equal(await tid(page, "challenge-error").getAttribute("role"), "alert");
  assert.equal(await page.getByLabel("Your name on the board").count(), 1, `${size}: the name field has its label`);
  await tid(page, "challenge-name").fill("Sam");
  await tid(page, "challenge-create").click();
  await tid(page, "share-card-preview").waitFor();
  assert.equal(await tid(page, "share-status").getAttribute("role"), "status");
  assert.match(await tid(page, "share-card-preview").getAttribute("alt"), /Sam scored 61/);
  await audit(size, "share-step", page);
  await ctx.close();

  // the follow screen: mode buttons are toggles, the Learn in sections switch is a labelled checkbox
  ({ ctx, page } = await visit(size, width, height, "/#/follow/lateral-raise", ".mode-picker", { keyframes: true }));
  const picker = page.locator(".mode-picker .mode-btn");
  assert.ok((await picker.count()) >= 2);
  await picker.nth(1).click();
  assert.equal(await picker.nth(1).getAttribute("aria-pressed"), "true");
  assert.equal(await picker.nth(0).getAttribute("aria-pressed"), "false");
  assert.equal(await page.getByLabel(/sections/i).count() >= 1, true, `${size}: the practice switch is labelled`);
  await tid(page, "practice-toggle").check();
  await tid(page, "ladder").waitFor();
  await audit(size, "follow-ladder", page);
  await ctx.close();

  // the catalog mode filter
  ({ ctx, page } = await visit(size, width, height, "/#/", "[data-testid=mode-filter]"));
  const filter = page.locator('[data-testid^="mode-filter-"]');
  await filter.nth(1).click();
  assert.equal(await filter.nth(1).getAttribute("aria-pressed"), "true");
  assert.equal(await page.locator('[data-testid^="mode-filter-"][aria-pressed="true"]').count(), 1, `${size}: one filter pressed at a time`);
  await audit(size, "catalog-filtered", page);
  await ctx.close();
  console.log(`checked - ${size} states`);
}
await browser.close();
server.kill();
staticServer.close();
if (failures.length) { console.error(failures.join("\n")); process.exit(1); }
console.log(`ok - ${passed} page/size combinations: zero serious or critical axe violations, 44 px targets, no overflow`);
