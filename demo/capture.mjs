// demo/capture.mjs: record the real Part 7 UI as phone-sized WebM segments for the submission video.
// Drives a LOCAL server (demo/local-state.sh start), never staging. Run it through scripts/with-browser-slot.sh.
// Usage: [DEMO_ONLY=mesh,result] node demo/capture.mjs <out-dir> [base-url] [follower-clip.mp4]
// Writes <out-dir>/ui-{catalog,watch,follow,result}.webm and <out-dir>/marks.json (seconds since each
// segment started, for the beats the build cuts on). No fake camera: the follow screen gets an uploaded take.
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { createRequire } from "node:module";
import { spawn } from "node:child_process";

const OUT = path.resolve(process.argv[2] || path.join(os.tmpdir(), "simon-demo-work", "capture"));
const BASE = (process.argv[3] || "http://127.0.0.1:17391/").replace(/\/?$/, "/");
const TAKE = process.argv[4] || path.join(os.homedir(), ".local/state/simon-part-7/staging/jobs/5277380db1e1/work/video.mp4");
const FRESH_JOB = process.env.DEMO_FRESH_JOB || "";
const ENTRY = process.env.DEMO_ENTRY || "body-squat-19b06562";
const JOB = process.env.DEMO_JOB || "5277380db1e1";
const VIEWPORT = { width: 412, height: 915 };
const SIZE = VIEWPORT; // recordVideo does not upscale: a larger size only adds grey padding

const req = createRequire(process.env.PLAYWRIGHT_ROOT || path.join(os.homedir(), "simon-part-7", "package.json"));
const { chromium } = req("playwright");
fs.mkdirSync(OUT, { recursive: true });
const marksFile = path.join(OUT, "marks.json");
const marks = fs.existsSync(marksFile) ? JSON.parse(fs.readFileSync(marksFile, "utf8")) : {}; // partial re-records keep the other segments' marks

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function segment(browser, name, fn) {
  const dir = path.join(OUT, `raw-${name}`);
  fs.rmSync(dir, { recursive: true, force: true });
  const ctx = await browser.newContext({
    viewport: VIEWPORT, deviceScaleFactor: 2, hasTouch: false,
    recordVideo: { dir, size: SIZE },
  });
  // The build line carries a commit id and update time; it is app chrome, not content.
  await ctx.addInitScript(() => {
    document.addEventListener("DOMContentLoaded", () => {
      const s = document.createElement("style");
      s.textContent = '[data-testid="build-line"],[data-testid="build-details"],a[href="#/signin"]{display:none!important}';
      document.head.append(s);
    });
  });
  const page = await ctx.newPage();
  const t0 = Date.now();
  const m = { at: (label) => { (marks[name] ||= {})[label] = (Date.now() - t0) / 1000; } };
  await fn(page, m);
  m.at("end");
  const vid = page.video();
  await ctx.close();
  fs.copyFileSync(await vid.path(), path.join(OUT, `ui-${name}.webm`));
  fs.rmSync(dir, { recursive: true, force: true });
}

// Smooth scroll by `px` over `ms`.
async function glide(page, px, ms = 1400) {
  // window.scrollBy in small steps: a mouse wheel over the 3D canvas zooms the figure instead of scrolling the page
  const steps = Math.max(6, Math.round(ms / 40));
  for (let i = 0; i < steps; i++) { await page.evaluate((d) => window.scrollBy(0, d), px / steps); await sleep(ms / steps); }
}

async function scrollTo(page, testid, ms = 1600, offset = 90) {
  const y = await page.evaluate(([id, off]) => {
    const el = document.querySelector(`[data-testid="${id}"]`);
    return el ? el.getBoundingClientRect().top + window.scrollY - off : null;
  }, [testid, offset]);
  if (y == null) return false;
  const cur = await page.evaluate(() => window.scrollY);
  await glide(page, y - cur, ms);
  return true;
}

async function drag(page, testid, dx, dy = 0, ms = 1800) {
  const box = await page.locator(`[data-testid="${testid}"], #${testid}`).first().boundingBox();
  if (!box) return false;
  const cx = box.x + box.width / 2, cy = box.y + Math.min(box.height / 2, 300);
  await page.mouse.move(cx, cy); await page.mouse.down();
  const steps = 40;
  for (let i = 1; i <= steps; i++) { await page.mouse.move(cx + (dx * i) / steps, cy + (dy * i) / steps); await sleep(ms / steps); }
  await page.mouse.up();
  return true;
}

// The mesh demo page (SAM 3D Body meshes of two stock clips, TICKET-143) is static: serve its web dir read only.
// The page is standalone (release 12 serves it as web/mesh-demo.html), so the video labels it as a demo page.
const MESH_WEB = process.env.DEMO_MESH_WEB || path.resolve(path.dirname(new URL(import.meta.url).pathname), "..", "web");
const MESH_PORT = Number(process.env.DEMO_MESH_PORT || 17392);
const MESH_SIZE = { width: 1536, height: 864 };
const ONLY = (process.env.DEMO_ONLY || "").split(",").filter(Boolean); // e.g. DEMO_ONLY=mesh re-records one segment
const want = (n) => !ONLY.length || ONLY.includes(n);

async function meshSegment(browser) {
  if (!fs.existsSync(path.join(MESH_WEB, "mesh-demo.html"))) { console.error("mesh demo not found at", MESH_WEB); return; }
  const srv = spawn("python3", ["-m", "http.server", String(MESH_PORT), "--bind", "127.0.0.1", "--directory", MESH_WEB], { stdio: "ignore" });
  try {
    await sleep(800);
    const dir = path.join(OUT, "raw-mesh");
    fs.rmSync(dir, { recursive: true, force: true });
    const ctx = await browser.newContext({ viewport: MESH_SIZE, recordVideo: { dir, size: MESH_SIZE } });
    const page = await ctx.newPage();
    const t0 = Date.now();
    await page.goto(`http://127.0.0.1:${MESH_PORT}/mesh-demo.html`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => window.__meshDemo && window.__meshDemo.ready, null, { timeout: 60000 });
    const start = (Date.now() - t0) / 1000;
    (marks.mesh ||= {}).start = start;
    await sleep(1500);
    await drag(page, "stage", 260, 0, 5000).catch(() => {});
    await sleep(1000);
    marks.mesh.end = (Date.now() - t0) / 1000;
    const vid = page.video();
    await ctx.close();
    fs.copyFileSync(await vid.path(), path.join(OUT, "ui-mesh.webm"));
    fs.rmSync(dir, { recursive: true, force: true });
  } finally { srv.kill(); }
}

const browser = await chromium.launch();
try {
  if (want("catalog")) await segment(browser, "catalog", async (page, m) => {
    await page.goto(BASE + "#/", { waitUntil: "domcontentloaded" });
    await page.locator('[data-testid="entries"]').waitFor();
    await sleep(2500); m.at("list");
    await glide(page, 520, 1800); await sleep(900);
    await page.evaluate(() => window.scrollTo(0, 0)); await sleep(700);
    await page.locator('[data-testid="kind-dance"]').click().catch(() => {}); await sleep(1800); m.at("filter");
    await page.locator('[data-testid="kind-exercise"]').click().catch(() => {}); await sleep(1500);
  });

  if (want("watch")) await segment(browser, "watch", async (page, m) => {
    await page.goto(`${BASE}#/watch/${ENTRY}`, { waitUntil: "domcontentloaded" });
    await page.locator('[data-testid="watch-frame"]').waitFor();
    await sleep(1200);
    await page.evaluate(() => { const v = document.querySelector('[data-testid="trainer-video"]'); if (v) { v.muted = true; v.play().catch(() => {}); } });
    await sleep(2500); m.at("video");
    await scrollTo(page, "viewer", 1500, 70); await sleep(600); m.at("figure");
    await page.locator('[data-testid="play"]').click().catch(() => {});
    await drag(page, "viewer", 150, 0, 2000); m.at("rotated");
    await page.locator('[data-testid="view-side"]').click().catch(() => {}); await sleep(1500); m.at("side");
    await page.locator('[data-testid="view-top"]').click().catch(() => {}); await sleep(1500);
    await page.locator('[data-testid="view-front"]').click().catch(() => {}); await sleep(1000);
  });

  if (want("follow")) await segment(browser, "follow", async (page, m) => {
    await page.goto(`${BASE}#/follow/${ENTRY}`, { waitUntil: "domcontentloaded" });
    await page.locator('[data-testid="upload"]').waitFor({ state: "attached" });
    await sleep(1500);
    await page.locator('[data-testid="upload"]').setInputFiles(TAKE);
    await sleep(2500); m.at("take");
    await glide(page, 420, 1800); await sleep(1500); m.at("ready");
  });

  // The redesigned result: score ring, Reference vs You, what to work on next, export, Meta models card, replay,
  // 3D compare, "Hear this line". Beats are marked in seconds from the segment start; the build cuts on them.
  if (want("result")) await segment(browser, "result", async (page, m) => {
    await page.goto(`${BASE}#/result/${JOB}`, { waitUntil: "domcontentloaded" });
    await page.locator('[data-testid="summary-score"]').waitFor({ timeout: 30000 });
    await sleep(200); m.at("score");
    await sleep(4200);
    await scrollTo(page, "summary-worst", 1400, 70); m.at("worst");
    await page.locator('[data-testid="summary-worst-play"]').click().catch(() => {});
    await sleep(3200);
    await scrollTo(page, "summary-note", 1200, 200); await sleep(1800); m.at("next");
    await scrollTo(page, "export-slot", 1200, 260); await sleep(600);
    m.at("export_click");
    await page.locator('[data-testid="export-start"]').click().catch(() => {});
    await Promise.race([
      page.locator('[data-testid="export-video"]').waitFor({ timeout: 240000 }),
      page.locator('[data-testid="export-error"]').waitFor({ timeout: 240000 }),
    ]).catch(() => {});
    await sleep(500); m.at("export_ready"); await sleep(2800);
    await scrollTo(page, "models-used", 1500, 70); await sleep(600); m.at("models");
    await glide(page, 360, 2400); await sleep(1200);
    await scrollTo(page, "breakdown", 1500, 70); await sleep(2200); m.at("breakdown");
    await scrollTo(page, "replay-worst", 1500, 330); await sleep(600); m.at("replay");
    await page.locator('[data-testid="replay-worst"]').click().catch(() => {}); await sleep(3500);
    await scrollTo(page, "compare-canvas", 1800, 70); await sleep(1000); m.at("compare");
    await page.locator('[data-testid="play"]').last().click().catch(() => {});
    await drag(page, "compare-canvas", -140, 0, 2200); m.at("rotated");
    await sleep(1000);
    await scrollTo(page, "fault-0", 1800, 90); await sleep(1200); m.at("fault");
    await page.locator('[data-testid="voice-play"]').first().click().catch(() => {}); m.at("hear");
    await sleep(3500);
  });

  // The fresh jobs (demo/make-jobs.py): in-app SAM 3D Body meshes, the Meta models card, the second opinion.
  if (want("fresh")) await segment(browser, "fresh", async (page, m) => {
    await page.goto(`${BASE}#/result/${FRESH_JOB}`, { waitUntil: "domcontentloaded" });
    await page.locator('[data-testid="summary-score"]').waitFor({ timeout: 30000 });
    await sleep(200); m.at("score");
    await sleep(3000);
    await page.locator('[data-testid="summary-mesh"]:not([hidden])').waitFor({ timeout: 30000 }).catch(() => {});
    await scrollTo(page, "summary-mesh", 1400, 120); await sleep(1200); m.at("mesh");
    await drag(page, "summary-mesh", 160, 0, 3200).catch(() => {}); await sleep(1200); m.at("meshrot");
    await scrollTo(page, "export-slot", 1400, 260); await sleep(600);
    m.at("export_click");
    await page.locator('[data-testid="export-start"]').click().catch(() => {});
    await Promise.race([
      page.locator('[data-testid="export-video"]').waitFor({ timeout: 240000 }),
      page.locator('[data-testid="export-error"]').waitFor({ timeout: 240000 }),
    ]).catch(() => {});
    await sleep(500); m.at("export_ready"); await sleep(2400);
    await scrollTo(page, "models-used", 1600, 70); await sleep(600); m.at("models");
    await glide(page, 300, 2200); await sleep(1400); m.at("modelsend");
    // The verdict badges sit on the "Mistakes you repeated" cards; the "also noticed" list is the second-opinion slot below.
    await scrollTo(page, "fault-0", 1800, 110).catch(() => {}); await sleep(600); m.at("badge");
    await sleep(3200);
    await scrollTo(page, "second-opinion-slot", 1800, 110); await sleep(3000); m.at("second");
    await page.locator('[data-testid="second-opinion-0"]').click().catch(() => {}); await sleep(1500); m.at("tap");
  });

  if (ONLY.includes("mesh")) await meshSegment(browser); // the standalone demo page; the cut now uses the in-app mesh view
} finally {
  await browser.close();
}
fs.writeFileSync(marksFile, JSON.stringify(marks, null, 1));
console.log("captured", Object.keys(marks).join(","), "->", OUT);
