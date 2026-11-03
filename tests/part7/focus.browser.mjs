// Browser drive of "Last time you worked on" (follow screen) and the cue's result line (result slot) at 412x915,
// TICKET-223 AC-1, AC-2. The page is the real app; the API is a small fake served by this file. Every answer below is
// SEEDED (written for this test, shaped like the answers of part7/history_focus.py), not a real student's takes.
//   PLAYWRIGHT_DIR=/path/to/node_modules node tests/part7/focus.browser.mjs [shots-dir]
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(here, "../..");
const WEB = path.join(ROOT, "web");
const SHOTS = path.resolve(process.argv[2] || process.env.SHOTS_DIR || path.join(ROOT, "demos/rubric/TICKET-223"));
fs.mkdirSync(SHOTS, { recursive: true });
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(ROOT, "node_modules"), "x.js"))("playwright");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
const json = (res, body, status = 200) => { res.writeHead(status, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };

const ENTRY = "body-squat-19b06562";
const JOB = "5277380db1e1"; // the job the history harness mounts its result slot for
const ENTRIES = [
  { id: "sq", name: "Lateral raise", category: "exercise", files_source: "import", video_uri: null, animation: "animation.json", duration_ms: 12000 },
  { id: "salsa", name: "Salsa basic", category: "dance", files_source: "import", video_uri: null, animation: "animation.json", duration_ms: 12000 },
];
const FOCUS = { format: "simon.history.focus.v1", entry_id: "sq", source: "fact_table", label: "Worked out from your stored takes.", measure: "knee_valgus", side: "left",
  cue: "Push the left knee out", cites: [{ take: 4, at_s: 12.3 }], take: 4, at_s: 12.3, at: "2026-11-01T10:00:00Z", date: "1 Nov" };
const AFTER = (change) => ({ job_id: JOB, take: 5, came_up: true, at_s: 2.4, change, band: { unit: "deg", value: 3 } });
const PAGE = JSON.parse(fs.readFileSync(path.join(here, "fixtures/history/page-body-squat.fixture.json"), "utf8"));

let scenario = "ok"; // ok | within | gone | signedout
const meRequests = []; // every api/me request the page made
const statuses = []; // every response status the browser saw from the fake API

function api(req, res, p, search) {
  if (req.url.startsWith("/__scenario/")) { scenario = req.url.split("/").pop(); meRequests.length = 0; statuses.length = 0; return json(res, {}); }
  if (p === "/api/auth/me") return json(res, scenario === "signedout" ? { available: true, signed_in: false } : { available: true, signed_in: true, user_id: "u-1", email: "a@b.co", retention: { opted_in: true } });
  if (p === "/api/config") return json(res, { limits: { max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000 }, part5: { lang: true, video: true, private: true } });
  if (p === "/api/client-log") { res.writeHead(200, { "Content-Type": "application/json" }); return res.end('{"ok": true}'); }
  if (p === "/api/labels") return json(res, {});
  if (p === "/api/me/profile") return json(res, { profile: null });
  if (p === "/api/health") return json(res, { ok: true });
  if (/^\/api\/teacher\/[^/]+\/author$/.test(p)) return json(res, {});
  const entry = /^\/catalog\/api\/entries\/([^/]+)(?:\/(.+))?$/.exec(p);
  if (entry) {
    const found = ENTRIES.find((e) => e.id === entry[1]);
    if (!found) return json(res, { error: "no" }, 404);
    return entry[2] ? json(res, { fps: 30, frames: [] }) : json(res, found);
  }
  if (p.startsWith("/api/me/")) meRequests.push(p + search);
  if (scenario === "signedout" && p.startsWith("/api/me/")) return json(res, { error: "sign in" }, 401);
  if (p === "/api/me/history/sq/focus") return json(res, { focus: FOCUS, after: null });
  if (p === "/api/me/history/salsa/focus") return json(res, { focus: null, after: null }); // no takes of it yet: an empty answer
  if (p === `/api/me/history/${ENTRY}/focus`) return json(res, { focus: { ...FOCUS, entry_id: ENTRY }, after: scenario === "gone" ? { ...AFTER(null), came_up: false, at_s: null } : AFTER(scenario === "within" ? "not_enough" : "larger") });
  if (p === "/api/me/history") return json(res, { entries: [{ entry_id: ENTRY, name: PAGE.name, takes: 2 }] });
  if (p === `/api/me/history/${ENTRY}`) return json(res, PAGE);
  if (p === `/api/me/history/${ENTRY}/plan`) return json(res, { plan: null });
  if (p === `/api/me/since-last-time/${JOB}`) return json(res, { since: null });
  return json(res, {}, 404);
}

function serve(root) {
  return http.createServer((req, res) => {
    const url = new URL(req.url, "http://x");
    const p = decodeURIComponent(url.pathname);
    if (p.startsWith("/api/") || p.startsWith("/catalog/api/") || p.startsWith("/__scenario/")) return api(req, res, p, url.search);
    const file = path.resolve(root, p === "/" ? "index.html" : "." + p);
    if (!file.startsWith(root) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) return res.writeHead(404).end("no");
    res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
}
const appServer = serve(WEB); // the real app, for the follow screen
const rootServer = serve(ROOT); // the repository root, for the history harness (result slot)
await new Promise((r) => appServer.listen(0, "127.0.0.1", r));
await new Promise((r) => rootServer.listen(0, "127.0.0.1", r));
const APP = `http://127.0.0.1:${appServer.address().port}`;
const HARNESS = `http://127.0.0.1:${rootServer.address().port}`;

const browser = await chromium.launch();
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const tid = (id) => `[data-testid="${id}"]`;
const shot = (page, name) => page.screenshot({ path: path.join(SHOTS, name), fullPage: true });

async function open(base, route, kase) {
  await fetch(`${APP}/__scenario/${kase}`);
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error" && !(route.includes("not-mine") && /404/.test(m.text()))) errors.push(`${kase} ${route}: ${m.text()}`); }); // strict: "Failed to load resource" counts, so a 401 or 404 fails
  page.on("response", (r) => { if (/\/api\/me\//.test(r.url())) statuses.push(r.status()); });
  await page.goto(`${base}${route}`);
  return { page, ctx };
}

try {
  // AC-1: the follow screen shows the cue word for word with the take, the second, the date and the label
  {
    const { page, ctx } = await open(APP, "/#/follow/sq", "ok");
    await page.waitForSelector(tid("focus-last-line"));
    assert.equal(await page.textContent(tid("focus-last-line")), "Last time you worked on: Push the left knee out (Take 4, 12.3 s)");
    assert.equal(await page.textContent(tid("focus-last-note")), "From 1 Nov. Worked out from your stored takes.");
    assert.deepEqual(meRequests.filter((r) => r.includes("/focus")), ["/api/me/history/sq/focus"], "one focus request, no job");
    await shot(page, "focus-01-follow-line.png");
    await ctx.close();
    ok("follow screen: the line shows the cue verbatim with take, second, date and label");
  }
  // negative: a movement with no kept takes shows no line and no error
  {
    const { page, ctx } = await open(APP, "/#/follow/salsa", "ok");
    await page.waitForSelector(tid("follow-mode"));
    await page.waitForTimeout(500);
    assert.equal(await page.locator(tid("focus-last")).count(), 0);
    assert.ok(meRequests.some((r) => r.endsWith("/salsa/focus")), "the signed-in screen did ask");
    await ctx.close();
    ok("follow screen: an empty answer draws nothing");
  }
  // negative: a movement the catalog does not show the viewer is a dead end, and no owner data is asked for
  {
    const { page, ctx } = await open(APP, "/#/follow/not-mine-12345678", "ok");
    await page.waitForSelector(tid("not-found"));
    await page.waitForTimeout(500);
    assert.deepEqual(meRequests.filter((r) => r.includes("/focus")), [], "no focus request for an entry the viewer cannot open");
    await ctx.close();
    ok("follow screen: no owner request for an entry the viewer does not have");
  }
  // negative: signed out, no owner-only request is sent and the console stays clean (no 401)
  {
    const { page, ctx } = await open(APP, "/#/follow/sq", "signedout");
    await page.waitForSelector(tid("follow-mode"));
    await page.waitForTimeout(700);
    assert.equal(await page.locator(tid("focus-last")).count(), 0, "signed out shows no focus line");
    assert.deepEqual(meRequests, [], "signed out makes no api/me request");
    assert.equal(statuses.includes(401), false, "no 401 reached the browser");
    await shot(page, "focus-02-follow-signed-out.png");
    await ctx.close();
    ok("follow screen: signed out sends no owner-only request and logs no 401");
  }
  // AC-2: the result line after a take, with the noise band
  for (const [kase, change, pattern] of [["ok", "larger", /came up again at 2\.4 s\. The fault looks larger\.$/], ["within", "not_enough", /came up again at 2\.4 s\. Not enough to tell if it is larger or smaller\.$/], ["gone", "", /did not come up this time\.$/]]) {
    const { page, ctx } = await open(HARNESS, "/tests/part7/harness/history.html?mode=slot", kase);
    await page.waitForSelector(tid("focus-result"));
    const text = await page.textContent(tid("focus-result"));
    assert.match(text, /^Last time's cue “Push the left knee out” /);
    assert.match(text, pattern);
    assert.equal(await page.getAttribute(tid("focus-result"), "data-change"), change);
    if (kase === "within") assert.doesNotMatch(text, /looks (larger|smaller)/, "negative: inside the noise band it never says larger or smaller");
    assert.ok(meRequests.includes(`/api/me/history/${ENTRY}/focus?job=${JOB}`), "the focus request names the job");
    await shot(page, `focus-03-result-${kase}.png`);
    await ctx.close();
    ok(`result slot (${kase}): ${text.slice(-48)}`);
  }
  // negative: signed out, the result slot makes no owner request
  {
    const { page, ctx } = await open(HARNESS, "/tests/part7/harness/history.html?mode=slot", "signedout");
    await page.waitForSelector(tid("stand-in"));
    await page.waitForTimeout(600);
    assert.equal(await page.locator(tid("focus-result")).count(), 0);
    assert.deepEqual(meRequests, [], "signed out: no api/me request from the result slot");
    assert.equal(statuses.includes(401), false);
    await ctx.close();
    ok("result slot: signed out sends no owner-only request");
  }
  assert.deepEqual(errors, [], `console or page errors: ${errors.join(" | ")}`);
  console.log(`${passed} passed`);
} finally {
  await browser.close();
  appServer.close();
  rootServer.close();
}
