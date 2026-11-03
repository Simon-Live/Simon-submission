// Browser drive of "Your progress reel" at 412x915 against a fake history server (docs/specs/history-reel.md, TICKET-228).
// The reel doc and the film are SEEDED fixtures (the landing loop stands in for a cut reel), not a model answer.
//   PLAYWRIGHT_DIR=/path/to/node_modules node tests/part7/reel.browser.mjs [shots-dir]
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(here, "../..");
const SHOTS = path.resolve(process.argv[2] || process.env.SHOTS_DIR || path.join(ROOT, "demos/rubric/TICKET-228"));
fs.mkdirSync(SHOTS, { recursive: true });
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(ROOT, "node_modules"), "x.js"))("playwright");
const PAGE0 = JSON.parse(fs.readFileSync(path.join(here, "fixtures/history/page-body-squat.fixture.json"), "utf8"));
const ENTRY = PAGE0.entry_id;
const CLIP = path.join(ROOT, "web/media/landing-loop.mp4");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
const clipUrl = (j) => `api/me/history/${ENTRY}/takes/${j}/clip.mp4`;
const page = (video) => ({ ...PAGE0, consent: { ...PAGE0.consent, video }, takes: PAGE0.takes.map((t) => ({ ...t, clip: clipUrl(t.job_id) })) });
const REEL = (seeded) => ({
  format: "simon.history.reel.v1", status: "ok", entry_id: ENTRY, seeded, watched: [1, 2], seconds: 6, video_url: `api/me/history/${ENTRY}/reel.mp4`,
  moments: [
    { take: 2, at_s: 0.9, role: "early", label: "model_opinion", text: "The trunk leans forward at 0.9 s in Take 2.", job_id: PAGE0.takes[1].job_id, clip: clipUrl(PAGE0.takes[1].job_id) },
    { take: 1, at_s: 1.0, role: "best", label: "model_opinion", text: "Take 1 stays upright at 1.0 s.", job_id: PAGE0.takes[0].job_id, clip: clipUrl(PAGE0.takes[0].job_id) }],
});
const json = (res, body, status = 200, headers = {}) => { res.writeHead(status, { "content-type": "application/json", ...headers }); res.end(JSON.stringify(body)); };

let scenario = "ok"; // ok | plain | failed | lost | novideo | signedout
let made = 0;
let polls = 0;
const posts = [];
const seen = [];

function api(req, res, p) {
  if (req.url.startsWith("/__scenario/")) { scenario = req.url.split("/").pop(); made = 0; polls = 0; return json(res, {}); }
  if (p === "/api/auth/me") return json(res, scenario === "signedout" ? { available: true, signed_in: false } : { available: true, signed_in: true, user_id: "u-1", email: "a@b.co", retention: { opted_in: true } });
  if (scenario === "signedout") return json(res, { error: "sign in" }, 401);
  if (p === `/api/me/history/${ENTRY}`) return json(res, page(scenario !== "novideo"));
  if (p === `/api/me/history/${ENTRY}/report`) return json(res, {}, 404);
  if (p === `/api/me/history/${ENTRY}/reel`) {
    if (req.method === "POST") { posts.push(scenario); made++; return json(res, { status: "running" }, 202, { "Retry-After": "1" }); }
    if (!made) return json(res, {}, 404);
    if (++polls < 2) return json(res, { status: "running" }, 202, { "Retry-After": "1" });
    if (scenario === "lost") return json(res, { error: "No reel has been made yet." }, 404); // the job died: staging 2026-11-02
    if (scenario === "failed") return json(res, { format: "simon.history.reel.v1", status: "failed", reason: "Simon could not get an answer from Muse Spark this time. Try again later.", entry_id: ENTRY });
    return json(res, REEL(scenario === "ok"));
  }
  if (p === `/api/me/history/${ENTRY}/reel.mp4`) { seen.push("reel.mp4"); return sendFile(req, res, CLIP, "video/mp4"); }
  const clip = /^\/api\/me\/history\/[^/]+\/takes\/([0-9a-f]+)\/clip\.mp4$/.exec(p);
  if (clip) { seen.push(clip[1]); return sendFile(req, res, CLIP, "video/mp4"); }
  return json(res, {}, 404);
}

function sendFile(req, res, file, type) {
  const size = fs.statSync(file).size;
  const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || "");
  if (m && (m[1] || m[2])) {
    const start = m[1] ? Number(m[1]) : Math.max(0, size - Number(m[2]));
    const end = m[1] && m[2] ? Math.min(Number(m[2]), size - 1) : size - 1;
    res.writeHead(206, { "content-type": type, "accept-ranges": "bytes", "content-range": `bytes ${start}-${end}/${size}`, "content-length": end - start + 1 });
    return fs.createReadStream(file, { start, end }).pipe(res);
  }
  res.writeHead(200, { "content-type": type, "accept-ranges": "bytes", "content-length": size });
  fs.createReadStream(file).pipe(res);
}

const server = http.createServer((req, res) => {
  const p = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (p.startsWith("/api/") || p.startsWith("/__scenario/")) return api(req, res, p);
  const file = path.resolve(ROOT, "." + p);
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) return res.writeHead(404).end("not found");
  sendFile(req, res, file, TYPES[path.extname(file)] || "application/octet-stream");
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const tid = (id) => `[data-testid="${id}"]`;
const shot = (pg, name) => pg.screenshot({ path: path.join(SHOTS, name), fullPage: true });
async function open(kase) {
  await fetch(`${base}/__scenario/${kase}`);
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
  const pg = await ctx.newPage();
  pg.on("pageerror", (e) => errors.push(String(e)));
  await pg.goto(`${base}/tests/part7/harness/history.html?mode=page`);
  return { pg, ctx };
}

try {
  {
    const { pg, ctx } = await open("ok");
    await pg.waitForSelector(tid("reel-card"));
    assert.match(await pg.textContent(tid("reel-disclosure")), /sent the measurements of every take and up to 5 of your kept clips to Meta's muse-spark-1\.3/);
    assert.equal(await pg.locator(tid("reel-video")).count(), 0, "no reel before it is made");
    await shot(pg, "reel-01-before.png");
    await pg.tap(tid("reel-make"));
    await pg.waitForSelector(`${tid("reel-status")}[data-kind="waiting"]`);
    assert.equal(await pg.isDisabled(tid("reel-make")), true);
    ok("making the reel shows the waiting state");
    await pg.waitForSelector(tid("reel-video"), { timeout: 15000 });
    assert.equal(await pg.isVisible(tid("reel-status")), false);
    assert.equal(await pg.locator(tid("reel-moment-0")).count(), 1);
    assert.match(await pg.textContent(tid("reel-moment-0")), /The trunk leans forward at 0\.9 s in Take 2\./);
    assert.match(await pg.textContent(tid("reel-moment-0")), /model's opinion, not scored/);
    assert.match(await pg.textContent(tid("reel-seeded")), /Seeded demo history/);
    assert.match(await pg.textContent(tid("reel-length")), /6 seconds, from 2 of your takes/);
    assert.match(await pg.getAttribute(tid("reel-download"), "href"), /reel\.mp4$/);
    assert.ok(await pg.getAttribute(tid("reel-download"), "download"));
    await pg.waitForFunction(() => document.querySelector('[data-testid="reel-video"]').readyState >= 1, null, { timeout: 15000 });
    assert.ok(seen.includes("reel.mp4"), "the film was fetched");
    await shot(pg, "reel-02-seeded-reel.png");
    ok("the reel plays, is labelled seeded, cites each moment and offers a download");
    await pg.tap(tid("reel-cite-0"));
    await pg.waitForFunction(() => { const v = document.querySelector('[data-testid="history-video"]'); return v && v.readyState >= 1 && v.currentTime >= 0.85; }, null, { timeout: 15000 });
    assert.match(await pg.getAttribute(tid("history-video"), "src"), /takes\/5277380db1e1\/clip\.mp4$/);
    ok("a moment opens that take's clip at that second");
    await ctx.close();
  }
  {
    const { pg, ctx } = await open("plain");
    await pg.tap(tid("reel-make"));
    await pg.waitForSelector(tid("reel-video"), { timeout: 15000 });
    assert.equal(await pg.locator(tid("reel-seeded")).count(), 0, "a history that is not seeded carries no seeded label");
    await ctx.close();
    ok("negative: no seeded label on a real history");
  }
  {
    const { pg, ctx } = await open("failed");
    await pg.tap(tid("reel-make"));
    await pg.waitForSelector(tid("reel-failed"), { timeout: 15000 });
    assert.match(await pg.textContent(tid("reel-failed")), /Simon could not get an answer from Muse Spark this time/);
    assert.equal(await pg.locator(tid("reel-video")).count(), 0);
    assert.equal(await pg.isDisabled(tid("reel-make")), false, "the button is free to try again");
    await ctx.close();
    ok("a failed reel says why and shows no film");
  }
  {
    const { pg, ctx } = await open("lost");
    await pg.tap(tid("reel-make"));
    await pg.waitForSelector(tid("reel-failed"), { timeout: 15000 });
    assert.match(await pg.textContent(tid("reel-failed")), /The reel stopped before it finished\. Try again\./);
    assert.doesNotMatch(await pg.textContent(tid("reel-card")), /No takes of this movement were found/, "a died job never reads as no takes");
    assert.equal(await pg.getAttribute(tid("reel-make"), "aria-busy"), "false");
    assert.equal(await pg.isDisabled(tid("reel-make")), false, "the button is free to try again");
    await ctx.close();
    ok("a reel whose job died while polling is a failed reel with a reason");
  }
  {
    posts.length = 0;
    const { pg, ctx } = await open("novideo");
    await pg.waitForSelector(tid("reel-card"));
    assert.equal(await pg.isDisabled(tid("reel-make")), true);
    assert.match(await pg.textContent(tid("reel-hint")), /Turn on "Let Muse Spark watch my takes"/);
    await pg.click(tid("reel-make"), { force: true, trial: false }).catch(() => {});
    await pg.waitForTimeout(400);
    assert.deepEqual(posts, [], "without the video choice no reel request is made");
    await shot(pg, "reel-03-no-video-choice.png");
    await ctx.close();
    ok("negative: without the video choice the button is off and nothing is requested");
  }
  assert.deepEqual(errors, [], `page errors: ${errors.join(" | ")}`);
  console.log(`${passed} passed`);
} finally {
  await browser.close();
  server.close();
}
