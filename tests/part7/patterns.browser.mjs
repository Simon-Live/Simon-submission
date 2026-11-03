// Browser drive of "Patterns across your takes" at 412x915 against a fake server (docs/specs/history-patterns.md).
// SEEDED, not a real student's history: four made takes of the squat and a hand-written result (it is NOT a Muse Spark answer).
//   PLAYWRIGHT_DIR=/path/to/node_modules node tests/part7/patterns.browser.mjs [shots-dir]
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(here, "../..");
const SHOTS = path.resolve(process.argv[2] || process.env.SHOTS_DIR || path.join(ROOT, "demos/rubric/TICKET-221"));
fs.mkdirSync(SHOTS, { recursive: true });
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(ROOT, "node_modules"), "x.js"))("playwright");
const CLIP = path.join(ROOT, "web/media/landing-loop.mp4");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
const ENTRY = "body-squat-19b06562";
const JOBS = ["aaaaaaaaaaa1", "aaaaaaaaaaa2", "aaaaaaaaaaa3", "aaaaaaaaaaa4"];
const takes = (n) => JOBS.slice(0, n).map((job_id, i) => ({ take: i + 1, job_id, at: `2026-10-0${i + 1}T10:00:00Z`, duration_s: 9, score: 90 - i * 5, grade: "B", private: false, clip: i === 3 ? false : undefined }));
const pageDoc = (n) => ({ entry_id: ENTRY, name: "Body squat (seeded)", consent: { keep: true, video: false, version: 1 }, takes: takes(n), facts: { takes: [], measures: [] } });
const RESULT = {
  format: "simon.history.patterns.v1", status: "ok", reason: "", entry_id: ENTRY,
  patterns: [
    { kind: "starts_at_rep", measure: "knee_valgus", side: "left", takes_with: 3, takes_total: 4, from_rep: 3, source: "model",
      text: "The left knee differs more from the example from rep 3, in 3 of 4 takes.", cites: [{ take: 2, at_s: 2.5 }, { take: 3, at_s: 3.2 }] },
    { kind: "tempo", measure: null, side: null, tempo_band: "slow_down", takes_with: 2, takes_total: 4, from_rep: null, source: "model",
      text: "Takes 3 and 4 differ more from the example in tempo.", cites: [{ take: 3, at_s: 1 }, { take: 4, at_s: 4 }] },
  ],
  rejected: [], usage: { input_tokens: 12840, cached_tokens: 9000, output_tokens: 400, usd: 0.01 }, meter: { input_tokens: 12840, cached_tokens: 9000 },
  sent: { to: "Meta's model (muse-spark-1.3)", keys: ["faults.measure", "faults.side", "score.value"], takes_full: 4, takes_digest: 0, video: false },
};
const json = (res, body, status = 200, headers = {}) => { res.writeHead(status, { "content-type": "application/json", ...headers }); res.end(JSON.stringify(body)); };

let scenario = "ok"; // ok | few | consent | table
let posts = 0;
let polls = 0;
const clips = [];

function api(req, res, p) {
  if (req.url.startsWith("/__scenario/")) { scenario = req.url.split("/").pop(); posts = 0; polls = 0; return json(res, {}); }
  if (p === "/api/auth/me") return json(res, { available: true, signed_in: true, user_id: "u-1", email: "a@b.co", retention: { opted_in: true } });
  if (p === `/api/me/history/${ENTRY}`) return json(res, pageDoc(scenario === "few" ? 2 : 4));
  if (p === `/api/me/history/${ENTRY}/report`) return json(res, {}, 404);
  if (p === `/api/me/history/${ENTRY}/patterns`) {
    if (req.method === "POST") {
      posts++;
      return scenario === "consent" ? json(res, { message: "no" }, 409) : json(res, { status: "running" }, 202, { "Retry-After": "1" });
    }
    if (!posts) return json(res, {}, 404);
    if (++polls < 2) return json(res, { status: "running" }, 202, { "Retry-After": "1" });
    return json(res, scenario === "table"
      ? { ...RESULT, status: "fallback", reason: "HTTP 500 on responses", meter: null, usage: null, patterns: [{ ...RESULT.patterns[0], source: "fact_table" }] } : RESULT);
  }
  const clip = /^\/api\/me\/history\/[^/]+\/takes\/([0-9a-z]+)\/clip\.mp4$/.exec(p);
  if (clip) { clips.push(clip[1]); return sendFile(req, res, CLIP, "video/mp4"); }
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
const ok = (name) => console.log(`ok - ${name}`);
const tid = (id) => `[data-testid="${id}"]`;
async function open(kase) {
  await fetch(`${base}/__scenario/${kase}`);
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(`${base}/tests/part7/harness/history.html?mode=page`);
  await page.waitForSelector(tid("patterns"));
  return { page, ctx };
}

try {
  {
    const { page, ctx } = await open("ok");
    assert.match(await page.textContent(tid("patterns")), /Patterns across your takes/);
    assert.equal(await page.locator(tid("patterns-list")).count(), 0, "no pattern before the button is pressed");
    await page.tap(tid("patterns-run"));
    await page.waitForSelector(`${tid("patterns-status")}[data-kind="waiting"]`);
    assert.equal(await page.isDisabled(tid("patterns-run")), true);
    await page.waitForSelector(tid("patterns-item-0"), { timeout: 15000 });
    assert.match(await page.textContent(tid("patterns-item-0")), /left knee differs more from the example from rep 3/);
    assert.match(await page.textContent(tid("patterns-item-0")), /Knee valgus, left/);
    assert.match(await page.textContent(tid("patterns-meter")), /12,840 tokens read.*9,000 from cache/);
    assert.match(await page.textContent(tid("patterns-receipt")), /Sent to Meta's model.*4 takes.*No video/);
    assert.equal(await page.isVisible(tid("patterns-status")), false);
    await page.screenshot({ path: path.join(SHOTS, "patterns-01-result.png"), fullPage: true });
    ok("the section lists each pattern with its cited moments, the token line and the receipt");
    await page.tap(tid("patterns-cite-0-0"));
    await page.waitForFunction(() => { const v = document.querySelector('[data-testid="history-video"]'); return v && v.readyState >= 1 && v.currentTime >= 2.4 && v.currentTime < 4; }, null, { timeout: 15000 });
    assert.match(await page.getAttribute(tid("history-video"), "src"), /takes\/aaaaaaaaaaa2\/clip\.mp4$/);
    assert.ok(clips.includes("aaaaaaaaaaa2"));
    ok("a cited moment opens that take's clip at that second");
    // NEGATIVE: take 4's clip is not kept, so its cite is a disabled button and no request for that clip is made
    assert.equal(await page.isDisabled(tid("patterns-cite-1-1")), true);
    assert.equal(clips.includes("aaaaaaaaaaa4"), false);
    ok("negative: a cite to a take with no kept clip is disabled and requests nothing");
    const text = (await page.textContent(tid("patterns"))).toLowerCase();
    for (const word of ["fatigue", "tired", "stop", "rehab", "injur"]) assert.equal(text.includes(word), false, word);
    await ctx.close();
  }
  {
    const { page, ctx } = await open("few");
    assert.equal(await page.isDisabled(tid("patterns-run")), true);
    assert.match(await page.textContent(tid("patterns")), /at least 3 takes/);
    await page.tap(tid("patterns-run"), { force: true, timeout: 1000 }).catch(() => {});
    await page.waitForTimeout(300);
    assert.equal(posts, 0, "negative: with 2 takes no request is made");
    ok("negative: with 2 takes the button is off and nothing is sent");
    await ctx.close();
  }
  {
    const { page, ctx } = await open("consent");
    await page.tap(tid("patterns-run"));
    await page.waitForSelector(`${tid("patterns-status")}[data-kind="consent"]`);
    assert.equal(await page.isDisabled(tid("patterns-run")), false);
    assert.equal(await page.locator(tid("patterns-list")).count(), 0);
    ok("a refusal says why and shows no pattern");
    await ctx.close();
  }
  {
    const { page, ctx } = await open("table");
    await page.tap(tid("patterns-run"));
    await page.waitForSelector(tid("patterns-note"), { timeout: 15000 });
    assert.match(await page.textContent(tid("patterns-note")), /model was not used/i);
    assert.equal(await page.getAttribute(tid("patterns-item-0"), "data-source"), "fact_table");
    assert.equal(await page.locator(tid("patterns-meter")).count(), 0, "no token line when the model did not run");
    ok("when the model was not used the table is shown and labelled");
    await ctx.close();
  }
  assert.deepEqual(errors, []);
} finally {
  await browser.close();
  server.close();
}
