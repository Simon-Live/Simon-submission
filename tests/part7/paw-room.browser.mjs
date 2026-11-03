// The job waiting page's paw trail never covers text (TICKET-308): a running job with the slower-path note and the time
// left is shown at 412x915, 390x844 and 1728x925; the paw walk's box and each print's box must not intersect the box of
// any text line (step text, elapsed, step hint, slower-path note, time left). Also under reduced motion.
//   PLAYWRIGHT_DIR=<node_modules> /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/paw-room.browser.mjs [shots-dir [name]]
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(here, "../..");
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.join(ROOT, "node_modules"), "x.js"))("playwright");
const shots = process.argv[2] ? path.resolve(process.argv[2]) : null;
const name = process.argv[3] || "paw-room";
if (shots) fs.mkdirSync(shots, { recursive: true });
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml" };
const JOB = { id: "pr1", kind: "follow", status: "running", stage: "pose", worker: "cold", eta_s: 210, eta_basis: { late: false }, note: "" };

const server = http.createServer((req, res) => {
  const p = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (p === "/api/jobs/pr1") { res.writeHead(200, { "content-type": "application/json" }); return res.end(JSON.stringify(JOB)); }
  if (p.startsWith("/api/")) { res.writeHead(200, { "content-type": "application/json" }); return res.end("{}"); }
  const base = /^\/(tests|web)\//.test(p) ? ROOT : path.join(ROOT, "web");
  const file = path.resolve(base, "." + (p === "/" ? "/index.html" : p));
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404).end("no"); return; }
  res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const BASE = `http://127.0.0.1:${server.address().port}/`;
const browser = await chromium.launch();

const measure = (page) => page.evaluate(() => {
  const box = (el) => { const b = el.getBoundingClientRect(); return { l: b.left, t: b.top, r: b.right, b: b.bottom }; };
  const q = (id) => document.querySelector(`[data-testid="${id}"]`);
  const texts = { "step-text": q("progress-text"), elapsed: q("progress-elapsed"), hint: q("stage-detail"), "gpu-note": q("gpu-note"), eta: q("eta-left") };
  const walk = document.querySelector(".paw-walk");
  const paws = walk ? [walk, ...walk.querySelectorAll("i")].map(box) : [];
  const lines = [];
  for (const [label, el] of Object.entries(texts)) {
    if (!el || el.hidden || !el.textContent.trim()) { lines.push({ label, missing: true }); continue; }
    const range = document.createRange(); range.selectNodeContents(el);
    for (const r of range.getClientRects()) lines.push({ label, l: r.left, t: r.top, r: r.right, b: r.bottom });
  }
  return { paws, lines };
});
const hit = (a, b) => a.l < b.r && a.r > b.l && a.t < b.b && a.b > b.t;

let failures = 0;
for (const [width, height, reduced] of [[412, 915, false], [390, 844, false], [1728, 925, false], [412, 915, true]]) {
  const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 2, reducedMotion: reduced ? "reduce" : "no-preference" });
  await ctx.addInitScript(() => sessionStorage.setItem("simon.splashSeen", "1")); // no brand splash over the page
  const page = await ctx.newPage();
  await page.goto(`${BASE}#/job/pr1`);
  await page.getByTestId("gpu-note").waitFor({ state: "visible", timeout: 8000 });
  await page.getByTestId("eta-left").waitFor({ state: "visible" });
  await page.waitForSelector(".paw-walk i");
  const m = await measure(page);
  const shown = m.lines.filter((l) => !l.missing);
  for (const need of ["gpu-note", "eta", "hint", "elapsed"]) assert.ok(shown.some((l) => l.label === need), `${need} line is shown`);
  let overlaps = 0;
  for (const p of m.paws) for (const l of shown) if (hit(p, l)) overlaps++;
  const walk = m.paws[0];
  console.log(`${width}x${height}${reduced ? " reduced-motion" : ""}: paw box top ${walk?.t.toFixed(0)} bottom ${walk?.b.toFixed(0)}, ${shown.length} text lines, overlaps ${overlaps}`);
  if (shots && width === 412 && !reduced) await page.screenshot({ path: path.join(shots, `${name}.png`), fullPage: true });
  if (overlaps) failures++;
  await ctx.close();
}
await browser.close();
server.close();
if (failures) { console.error(`FAIL: the paw trail overlaps text at ${failures} viewport(s)`); process.exit(1); }
console.log("ok - the paw trail never intersects a text line at 412x915, 390x844, 1728x925 and with reduced motion");
