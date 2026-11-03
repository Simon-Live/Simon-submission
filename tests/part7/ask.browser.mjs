// Browser drive of "Ask my history" at 412x915 against a fake server (docs/specs/history-ask.md, TICKET-222).
// The history and every answer are SEEDED fixtures written in this file, not a real student's takes or a model's output.
//   PLAYWRIGHT_DIR=/path/to/node_modules node tests/part7/ask.browser.mjs [shots-dir]
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(here, "../..");
const SHOTS = path.resolve(process.argv[2] || process.env.SHOTS_DIR || path.join(ROOT, "demos/rubric/TICKET-222"));
fs.mkdirSync(SHOTS, { recursive: true });
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(ROOT, "node_modules"), "x.js"))("playwright");
const CLIP = path.join(ROOT, "web/media/landing-loop.mp4"); // stands in for a kept 480 px take clip
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
const ENTRY = "body-squat-19b06562";
const CLIP_URL = `api/me/history/${ENTRY}/takes/5277380db1e1/clip.mp4`;
const json = (res, body, status = 200, headers = {}) => { res.writeHead(status, { "content-type": "application/json", ...headers }); res.end(JSON.stringify(body)); };

// SEEDED answers. `ok` has a kept claim and a dropped one; the dropped text is not in any response.
const SENT = { takes: 2, movements: 1, left_out: 0, video: false };
const USAGE = { input_tokens: 9200, cached_tokens: 0, output_tokens: 310, usd: 0.0125 };
const ANSWERS = {
  ok: { status: "ok", text: null, dropped: 1, remaining: 19, message: "", reach: SENT, usage: USAGE,
    claims: [{ kind: "trend", text: "Trunk lean forward shows in take 2 at 1 s, not before.", measure: "trunk_lean_forward", side: "center", relation: "new",
      cites: [{ ref: 2, entry_id: ENTRY, take: 2, job_id: "5277380db1e1", at_s: 1, clip: CLIP_URL }, { ref: 1, entry_id: ENTRY, take: 1, job_id: "cc7cd5469055", at_s: null, clip: null }] }] },
  clean: { status: "ok", text: "Trunk lean forward is new in take 2.", dropped: 0, remaining: 18, message: "", reach: SENT, usage: { ...USAGE, cached_tokens: 7400 },
    claims: [{ kind: "count", text: "Trunk lean forward shows in 1 take.", cites: [{ ref: 2, entry_id: ENTRY, take: 2, job_id: "5277380db1e1", at_s: null, clip: CLIP_URL }] }] },
  abstain: { status: "abstain", text: null, claims: [], dropped: 0, remaining: 17, message: "Your takes do not mention tempo.", reach: SENT, usage: USAGE },
  refused: { status: "refused", text: null, claims: [], dropped: 0, remaining: 17, message: "Simon answers questions about your takes only. Ask about a movement, a score or how a move changed.", usage: null },
};
const SUGGESTIONS = ["Is my trunk lean forward getting better in Body squat?", "When did my trunk lean forward first show up in Body squat?", "Which take of Body squat scored best?"];

let scenario = "ok"; // ok | signedout | few | limit
const asked = []; // the questions the server received
function api(req, res, p) {
  if (req.url.startsWith("/__scenario/")) { scenario = req.url.split("/").pop(); asked.length = 0; return json(res, {}); }
  if (p === "/api/auth/me") return json(res, scenario === "signedout" ? { available: true, signed_in: false } : { available: true, signed_in: true, user_id: "u-1", email: "a@b.co", retention: { opted_in: true } });
  if (scenario === "signedout") return json(res, { error: "sign in" }, 401);
  if (p === "/api/me/history") return json(res, { entries: [{ entry_id: ENTRY, name: "Body squat", takes: 2 }] });
  if (p === "/api/me/history/ask" && req.method === "GET") {
    return json(res, { retention: true, takes: scenario === "few" ? 1 : 2, can_ask: scenario !== "few", suggestions: SUGGESTIONS, limit: 20, remaining: 20, max_chars: 200 });
  }
  if (p === "/api/me/history/ask" && req.method === "POST") {
    let raw = "";
    req.on("data", (c) => { raw += c; });
    req.on("end", () => {
      const q = JSON.parse(raw).question;
      asked.push(q);
      if (scenario === "limit") return json(res, { message: "You have asked 20 questions today. Try again tomorrow." }, 429);
      const key = /pain/i.test(q) ? "refused" : /tempo/i.test(q) ? "abstain" : /best/i.test(q) ? "clean" : "ok";
      json(res, ANSWERS[key]);
    });
    return;
  }
  if (/^\/api\/me\/history\/[^/]+\/takes\/[0-9a-f]+\/clip\.mp4$/.test(p)) return sendFile(req, res, CLIP, "video/mp4");
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
const shot = (page, name) => page.screenshot({ path: path.join(SHOTS, name), fullPage: true });
async function open(kase) {
  await fetch(`${base}/__scenario/${kase}`);
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(`${base}/tests/part7/harness/history.html?mode=list`);
  return { page, ctx };
}

try {
  {
    const { page, ctx } = await open("ok");
    await page.waitForSelector(tid("ask"));
    assert.equal(await page.locator(`${tid("ask-suggestions")} button`).count(), 3, "three suggested questions");
    assert.match(await page.textContent(tid("ask-suggestion-0")), /^Is my trunk lean forward getting better in Body squat\?$/);
    assert.equal(await page.locator(tid("ask-claim-0")).count(), 0, "no answer before a question");
    await shot(page, "ask-01-box-seeded.png");
    await page.tap(tid("ask-suggestion-0"));
    await page.waitForSelector(tid("ask-claim-0"));
    assert.deepEqual(asked, [SUGGESTIONS[0]]);
    assert.match(await page.textContent(tid("ask-claim-0")), /Trunk lean forward shows in take 2 at 1 s/);
    assert.match(await page.textContent(tid("ask-dropped")), /^Simon could not check this \(1 left out\)\.$/);
    assert.match(await page.textContent(tid("ask-receipt")), /2 takes of 1 movement as text, with no video/);
    assert.match(await page.textContent(tid("ask-receipt")), /9,200 tokens in, 0 of them cached/);
    assert.equal(await page.locator(tid("ask-lead")).count(), 0, "no lead sentence when a claim was dropped");
    assert.match(await page.textContent(tid("ask-remaining")), /19 questions left today/);
    assert.equal(await page.isDisabled(tid("ask-cite-0-1")), true, "a clip that is not kept is disabled");
    await shot(page, "ask-02-answer-with-dropped-seeded.png");
    ok("seeded: a suggested question gets a claim, a dropped count and a receipt");
    await page.tap(tid("ask-cite-0-0"));
    await page.waitForFunction(() => { const v = document.querySelector('.ask [data-testid="history-video"]'); return v && v.readyState >= 1 && v.currentTime >= 0.9 && v.currentTime < 3; }, null, { timeout: 15000 });
    assert.match(await page.getAttribute(`.ask ${tid("history-video")}`, "src"), /takes\/5277380db1e1\/clip\.mp4$/);
    ok("a cited moment opens that take's clip at that second");
    await page.fill(tid("ask-input"), "Which take scored best?");
    await page.press(tid("ask-input"), "Enter");
    await page.waitForSelector(tid("ask-lead"));
    assert.equal(await page.locator(tid("ask-dropped")).count(), 0, "nothing dropped, no dropped line");
    assert.match(await page.textContent(tid("ask-receipt")), /7,400 of them cached/);
    ok("a typed follow-up shows the lead and the cached tokens");
    await page.fill(tid("ask-input"), "is my tempo getting better?");
    await page.press(tid("ask-input"), "Enter");
    await page.waitForFunction(() => /do not mention tempo/.test(document.querySelector('[data-testid="ask-lead"]')?.textContent || ""));
    assert.equal(await page.locator(tid("ask-claim-0")).count(), 0);
    ok("an abstention says so and shows no claims");
    await page.fill(tid("ask-input"), "why is there pain?");
    await page.press(tid("ask-input"), "Enter");
    await page.waitForFunction(() => /answers questions about your takes only/.test(document.querySelector('[data-testid="ask-lead"]')?.textContent || ""));
    assert.equal(await page.locator(tid("ask-receipt")).count(), 0, "a refusal has no receipt");
    await shot(page, "ask-03-refused-seeded.png");
    ok("a refused question shows the fixed words");
    const before = asked.length;
    await page.fill(tid("ask-input"), "");
    await page.press(tid("ask-input"), "Enter");
    assert.match(await page.textContent(tid("ask-status")), /Type a question first/);
    assert.equal(asked.length, before, "an empty question is never sent");
    await ctx.close();
    ok("an empty question is stopped before it is sent");
  }
  {
    const { page, ctx } = await open("limit");
    await page.waitForSelector(tid("ask"));
    await page.tap(tid("ask-suggestion-1"));
    await page.waitForSelector(`${tid("ask-status")}[data-kind="limit"]`);
    assert.match(await page.textContent(tid("ask-status")), /Try again tomorrow/);
    assert.equal(await page.isDisabled(tid("ask-send")), false);
    await ctx.close();
    ok("a 429 shows its words and frees the button");
  }
  for (const kase of ["signedout", "few"]) {
    const { page, ctx } = await open(kase);
    await page.waitForTimeout(800);
    assert.equal(await page.locator(tid("ask")).count(), 0, `${kase}: no ask box`);
    assert.equal(await page.locator(tid("ask-input")).count(), 0);
    await ctx.close();
  }
  ok("negative: no box when signed out or with fewer than 2 takes");
  assert.deepEqual(errors, [], `page errors: ${errors.join(" | ")}`);
  console.log(`${passed} passed`);
} finally {
  await browser.close();
  server.close();
}
