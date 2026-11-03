// Browser drive of the streamed frames on the job page and the corrected-pose card at 390x844 against a fake server
// (docs/specs/mesh-stream.md, docs/specs/muse-image-corrected.md). Frames and images are hand-made FIXTURES.
//   PLAYWRIGHT_DIR=/path/to/node_modules node tests/part7/mesh_stream.browser.mjs [shots-dir]
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(here, "../..");
const SHOTS = path.resolve(process.argv[2] || process.env.SHOTS_DIR || path.join(ROOT, "demos/rubric/TICKET-284"));
fs.mkdirSync(SHOTS, { recursive: true });
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(ROOT, "node_modules"), "x.js"))("playwright");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAHnOcQAAAAABJRU5ErkJggg==", "base64");
const json = (res, body, status = 200) => { res.writeHead(status, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };

let scenario = "stream"; // stream | plain | card | card-miss | card-noconsent
let snapCalls = 0;
let chunkAsks = [];
let posts = [];
let cardState = {};
const READY = { eligible: true, consent: true, running: false, card: null, image: null, referee: null };
const SHOWN = { status: "shown", label: "AI-generated illustration", image: "corrected-1.png", joint: "left_elbow", error_deg: 3.4,
  error_text: "Measured error: 3.4 degrees from the target pose." };
// 12 vertices per block, int16 at 0.1 mm: a short vertical line that moves right with the frame number
const chunk = (n) => { const a = new Int16Array(36); for (let i = 0; i < 12; i += 1) a.set([1000 * n + i * 10, i * 1500, 0], i * 3); return Buffer.from(a.buffer); };

function api(req, res, p) {
  if (p.startsWith("/__scenario/")) {
    scenario = p.split("/").pop(); snapCalls = 0; chunkAsks = []; posts = [];
    cardState = scenario === "card-noconsent" ? { ...READY, consent: false } : READY;
    return json(res, {});
  }
  if (p === "/api/config") return json(res, {});
  if (p === "/api/jobs/j1") {
    const base = { id: "j1", kind: "follow", status: "running", stage: "pose", stages: ["upload", "pose"], created_at: new Date().toISOString() };
    return json(res, scenario === "stream" ? { ...base, mesh_stream: { url: "api/jobs/j1/mesh-stream", model: "SAM 3D Body" } } : { ...base, mesh_stream: null });
  }
  if (p === "/api/jobs/j1/mesh-stream") {
    snapCalls++;
    const n = Math.min(snapCalls * 2, 8);
    return json(res, { closed: false, model: "SAM 3D Body", stream: { frames_done: n, frames_total: 8, vertex_count: 12, block_bytes: 72,
      chunks: Array.from({ length: n }, (_, i) => `api/results/j1/mesh-stream/chunk-${String(i).padStart(4, "0")}.bin`) } });
  }
  const file = /^\/api\/results\/j1\/mesh-stream\/chunk-(\d{4})\.bin$/.exec(p);
  if (file) { chunkAsks.push(Number(file[1])); res.writeHead(200, { "content-type": "application/octet-stream" }); return res.end(chunk(Number(file[1]))); }
  if (p === "/api/jobs/j1/muse-fix" && req.method === "GET") return json(res, cardState);
  if (p === "/api/jobs/j1/muse-fix" && req.method === "POST") {
    posts.push(scenario);
    cardState = scenario === "card-miss" ? { ...READY, card: { status: "missed", message: "The image model missed the pose." } }
      : { ...READY, card: SHOWN, image: "api/jobs/j1/muse-fix/image" };
    return json(res, { running: true }, 202);
  }
  if (p === "/api/jobs/j1/muse-fix/image") { res.writeHead(200, { "content-type": "image/png" }); return res.end(PNG); }
  return json(res, { error: "no" }, 404);
}

const server = http.createServer((req, res) => {
  const p = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (p.startsWith("/api/") || p.startsWith("/__scenario/")) return api(req, res, p);
  const file = path.resolve(ROOT, "." + p);
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) return res.writeHead(404).end("not found");
  res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();
const problems = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const tid = (id) => `[data-testid="${id}"]`;
async function open(kase, mode) {
  await fetch(`${base}/__scenario/${kase}`);
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, hasTouch: true });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => problems.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") problems.push(`${kase}: ${m.text()}`); });
  await page.goto(`${base}/tests/part7/harness/stream.html?mode=${mode}&id=j1`);
  return { page, ctx };
}
const shot = (page, name) => page.screenshot({ path: path.join(SHOTS, name), fullPage: true });

try {
  {
    const { page, ctx } = await open("stream", "job");
    await page.waitForSelector(tid("mesh-stream"));
    assert.match(await page.textContent(tid("mesh-stream-model")), /SAM 3D Body is rebuilding your body/);
    await page.waitForFunction(() => /^Frame 2 of 8$/.test(document.querySelector('[data-testid="mesh-stream-count"]').textContent));
    const first = await page.getAttribute(tid("mesh-stream"), "data-frames");
    await page.waitForFunction(() => Number(document.querySelector('[data-testid="mesh-stream"]').getAttribute("data-frames")) >= 6, null, { timeout: 15000 });
    const later = await page.getAttribute(tid("mesh-stream"), "data-frames");
    assert.ok(Number(later) > Number(first), "the frame count rises while the job runs");
    const drawn = await page.evaluate(() => { const c = document.querySelector('[data-testid="mesh-stream-canvas"]'); return c.getContext("2d").getImageData(0, 0, c.width, c.height).data.some((v, i) => i % 4 === 3 && v > 0); });
    assert.equal(drawn, true, "the canvas has drawn points");
    assert.deepEqual(chunkAsks.slice(0, 4), [0, 1, 2, 3], `each chunk is fetched once, in order: ${chunkAsks}`);
    await shot(page, "stream-01-frames.png");
    ok("the pending page draws frames and the count rises (two witnesses: count text and the chunk requests)");
    await ctx.close();
  }
  {
    const { page, ctx } = await open("plain", "job");
    await page.waitForSelector(tid("stages"));
    await page.waitForTimeout(2500);
    assert.equal(await page.locator(tid("mesh-stream")).count(), 0, "no stream panel without the hint");
    assert.equal(snapCalls + chunkAsks.length, 0, "negative: a job without a stream never asks for frames");
    await shot(page, "stream-02-plain.png");
    ok("a job without a mesh stage shows the old progress view and asks for no frames");
    await ctx.close();
  }
  {
    const { page, ctx } = await open("card", "card");
    await page.waitForSelector(tid("corrected-ask"));
    assert.deepEqual(posts, [], "nothing is sent before the tap");
    await page.tap(tid("corrected-ask"));
    await page.waitForSelector(tid("corrected-image"), { timeout: 15000 });
    assert.equal(await page.textContent(tid("corrected-label")), "AI-generated illustration");
    assert.equal(await page.textContent(tid("corrected-error")), "Measured error: 3.4 degrees from the target pose.");
    assert.equal(await page.locator(tid("referee-ask")).count(), 1);
    assert.equal(posts.length, 1);
    await shot(page, "corrected-01-image.png");
    ok("the card draws the image only after a tap, labelled with its measured error");
    await ctx.close();
  }
  {
    const { page, ctx } = await open("card-miss", "card");
    await page.waitForSelector(tid("corrected-ask"));
    await page.tap(tid("corrected-ask"));
    await page.waitForSelector(tid("corrected-missed"));
    assert.match(await page.textContent(tid("corrected-missed")), /^The image model missed the pose/);
    assert.equal(await page.locator(tid("corrected-image")).count(), 0);
    ok("a miss shows the plain sentence and no image");
    await ctx.close();
  }
  {
    const { page, ctx } = await open("card-noconsent", "card");
    await page.waitForSelector(tid("stand-in"));
    await page.waitForTimeout(600);
    assert.equal(await page.isVisible(tid("corrected-slot")), false, "no card with consent off");
    assert.equal(await page.locator(tid("corrected-ask")).count(), 0);
    assert.deepEqual(posts, []);
    ok("negative: with consent off no card appears and nothing is posted");
    await ctx.close();
  }
  assert.deepEqual(problems, [], `console problems: ${problems.join(" | ")}`);
  console.log(`${passed} passed`);
} finally {
  await browser.close();
  server.close();
}
