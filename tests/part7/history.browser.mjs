// Browser drive of "Your takes over time" at 412x915 against a fake history server built from C-HTTP
// (docs/specs/history-web.md AC-3, AC-4). The model answer is a hand-written FIXTURE (tests/part7/fixtures/history).
//   PLAYWRIGHT_DIR=/path/to/node_modules node tests/part7/history.browser.mjs [shots-dir]
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(here, "../..");
const SHOTS = path.resolve(process.argv[2] || process.env.SHOTS_DIR || path.join(ROOT, "demos/rubric/TICKET-182"));
fs.mkdirSync(SHOTS, { recursive: true });
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(ROOT, "node_modules"), "x.js"))("playwright");
const fx = (f) => JSON.parse(fs.readFileSync(path.join(here, "fixtures/history", f), "utf8"));
const PAGE = fx("page-body-squat.fixture.json");
const REPORT = fx("report-body-squat.fixture.json");
// TICKET-218: a hand-written series (FIXTURE, not a measurement) so the page draws the fault lines; one gap, two sides
const pt = (take, value) => ({ take, at: `2026-11-0${take}T10:00:00Z`, day: `2026-11-0${take}`, present: !!value, value });
PAGE.facts = { ...(PAGE.facts || {}), series: { hidden: false, takes: [1, 2, 3, 4], plateaus: [], early_signs: [],
  measures: [{ measure: "knee_valgus", side_note: null, lines: [
    { side: "left", unit: "deg", plateau: false, present_in: [1, 2, 4], points: [pt(1, 20), pt(2, 15), pt(3, null), pt(4, 6)] },
    { side: "right", unit: "deg", plateau: false, present_in: [], points: [pt(1, 0), pt(2, 0), pt(3, 0), pt(4, 0)] }] }] } };
// one-letter.md L8: a plain 50 F take, then a 37 take shown as C at 72.6% (the MM-Fit take 42a02415127e's credit, CC BY 4.0)
const SHOWN = (letter, figures, caption, unit, measure) => ({ letter, figures, caption, unit, capped: false, warning: [], measure });
const CREDIT_PAGE = { ...PAGE, takes: [
  { ...PAGE.takes[0], score: 50, grade: "F", shown: SHOWN("F", "50", "out of 100", "score", 50) },
  { ...PAGE.takes[1], score: 37, grade: "F", shown: SHOWN("C", "16,239", "of 22,367", "points", 72.6) }] };
const CLIP = path.join(ROOT, "web/media/landing-loop.mp4"); // stands in for a kept 480 px take clip
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
const ENTRY = PAGE.entry_id;
const json = (res, body, status = 200, headers = {}) => { res.writeHead(status, { "content-type": "application/json", ...headers }); res.end(JSON.stringify(body)); };

let scenario = "ok"; // ok | fallback | signedout | consent
let polls = 0;
const meRequests = []; // every api/me request the page made
let runs = 0;

function api(req, res, p) {
  if (req.url.startsWith("/__scenario/")) { scenario = req.url.split("/").pop(); polls = 0; runs = 0; return json(res, {}); }
  if (p === "/api/auth/me") return json(res, scenario === "signedout" ? { available: true, signed_in: false } : { available: true, signed_in: true, user_id: "u-1", email: "a@b.co", retention: { opted_in: true } });
  if (p.startsWith("/api/me/")) meRequests.push(p);
  if (scenario === "signedout") return json(res, { error: "sign in" }, 401);
  if (p === "/api/me/history") return json(res, { entries: [{ entry_id: ENTRY, name: PAGE.name, takes: 2 }] });
  if (p === `/api/me/history/${ENTRY}`) return json(res, scenario === "credit" ? CREDIT_PAGE : PAGE);
  if (p === `/api/me/history/${ENTRY}/report`) {
    if (req.method === "POST") {
      runs++;
      if (scenario === "consent") return json(res, { error: "no consent" }, 409);
      return json(res, { status: "running" }, 202, { "Retry-After": "1" });
    }
    if (!runs) return json(res, {}, 404);
    if (scenario === "fallback") return json(res, { ...REPORT, status: "fallback", reason: "over_budget", usage: null, trends: [], focus: null, observations: [], summary: null, facts: PAGE.facts });
    return ++polls < 3 ? json(res, { status: "running" }, 202, { "Retry-After": "1" }) : json(res, { ...REPORT, facts: PAGE.facts });
  }
  if (p === "/api/me/since-last-time/5277380db1e1") return json(res, { since: SEEDED_SINCE });
  const clip = /^\/api\/me\/history\/[^/]+\/takes\/([0-9a-f]+)\/clip\.mp4$/.exec(p);
  if (clip) { clips.push(clip[1]); return sendFile(req, res, CLIP, "video/mp4"); }
  return json(res, {}, 404);
}
const clips = [];
// SEEDED history, not a real student's: two made takes of the squat, the line a server would build from them (history_since).
const SEEDED_SINCE = {
  format: "simon.history.since.v1", job_id: "5277380db1e1", take: 2, entry_id: ENTRY, previous: { take: 1, job_id: "cc7cd5469055", at: "2026-10-28T10:00:00Z" },
  line: "Since last time (28 Oct): score 77 to 84; the left knee cue is gone; the elbow cue is new",
  facts: [
    { kind: "score", text: "score 77 to 84", link: { take: 1, job_id: "cc7cd5469055", at_s: null, clip: `api/me/history/${ENTRY}/takes/cc7cd5469055/clip.mp4` } },
    { kind: "gone", text: "the left knee cue is gone", link: { take: 1, job_id: "cc7cd5469055", at_s: 1.5, clip: `api/me/history/${ENTRY}/takes/cc7cd5469055/clip.mp4` } },
    { kind: "new", text: "the elbow cue is new", link: { take: 1, job_id: "cc7cd5469055", at_s: 2, clip: null } },
  ],
  bests: [{ kind: "best", text: "New best: 84", link: { take: 1, job_id: "cc7cd5469055", at_s: null, clip: `api/me/history/${ENTRY}/takes/cc7cd5469055/clip.mp4` } }],
};

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
async function open(mode, kase) {
  await fetch(`${base}/__scenario/${kase}`);
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(`${base}/tests/part7/harness/history.html?mode=${mode}`);
  return { page, ctx };
}
const shot = (page, name) => page.screenshot({ path: path.join(SHOTS, name), fullPage: true });
const tid = (id) => `[data-testid="${id}"]`;

try {
  // AC-3: the whole path through the real UI, with the waiting state caught on the way
  {
    const { page, ctx } = await open("page", "ok");
    await page.waitForSelector(tid("history-chart"));
    await page.waitForSelector(tid("history-series-chart-knee_valgus"));
    assert.equal(await page.locator(`${tid("history-series-chart-knee_valgus")} circle`).count(), 7, "3 dots on the left line (take 3 is a gap), 4 zeros on the right");
    assert.equal(await page.locator(tid("history-series-seeded")).count(), 0, "real takes carry no seeded label");
    ok("the fault lines draw from the series, a gap is not a dot");
    assert.equal(await page.locator(tid("history-trend-0")).count(), 0, "no report before the run");
    await shot(page, "history-01-before-run.png");
    await page.tap(tid("history-run"));
    await page.waitForSelector(`${tid("history-status")}[data-kind="waiting"]`);
    assert.match(await page.textContent(tid("history-status")), /Simon is reading your takes/);
    assert.equal(await page.isDisabled(tid("history-run")), true);
    await shot(page, "history-02-waiting-202.png");
    ok("run shows the 202 waiting state");
    await page.waitForSelector(tid("history-trend-0"), { timeout: 15000 });
    assert.equal(await page.isVisible(tid("history-status")), false, "the status line clears");
    assert.match(await page.textContent(tid("history-observation-0")), /model's opinion, not scored/);
    assert.match(await page.textContent(tid("history-context-used")), /41,872 of 1,048,576 tokens used/);
    assert.match(await page.textContent(tid("history-context-cached")), /30,208 cached tokens/);
    await shot(page, "history-03-full-report.png");
    ok("the report shows trend, focus, observation and context meter");
    await page.tap(tid("history-cite-0-0"));
    await page.waitForFunction(() => { const v = document.querySelector('[data-testid="history-video"]'); return v && v.readyState >= 1 && v.currentTime >= 0.85 && v.currentTime < 3; }, null, { timeout: 15000 });
    assert.match(await page.getAttribute(tid("history-video"), "src"), /takes\/5277380db1e1\/clip\.mp4$/);
    assert.equal(await page.isVisible(tid("history-player")), true);
    assert.ok(clips.includes("5277380db1e1"), "the server saw that take's clip request");
    await shot(page, "history-04-cite-opened.png");
    ok("a cite chip opens that take's clip at that second");
    await page.tap(tid("history-cite-0-1"));
    await page.waitForFunction(() => /cc7cd5469055/.test(document.querySelector('[data-testid="history-video"]').getAttribute("src")));
    ok("a second chip switches to the other take");
    await ctx.close();
  }
  // fallback: the fact table with its reason
  {
    const { page, ctx } = await open("page", "fallback");
    await page.tap(tid("history-run"));
    await page.waitForSelector(tid("history-fallback"), { timeout: 15000 });
    assert.match(await page.textContent(tid("history-fallback")), /Measured across your takes/);
    assert.match(await page.textContent(tid("history-fallback-reason")), /Over budget\./);
    assert.equal(await page.locator(tid("history-trend-0")).count(), 0);
    assert.equal(await page.locator(tid("history-context")).count(), 0, "no meter without a call");
    await shot(page, "history-05-fallback.png");
    ok("fallback shows the fact table and its reason");
    await ctx.close();
  }
  // 409: the status line names the way out
  {
    const { page, ctx } = await open("page", "consent");
    await page.tap(tid("history-run"));
    await page.waitForSelector(`${tid("history-status")}[data-kind="consent"]`);
    assert.equal(await page.isDisabled(tid("history-run")), false);
    await ctx.close();
    ok("a 409 shows its status line and frees the button");
  }
  // AC-4: the slot, signed in and signed out (negative), and the signed-out page
  {
    const { page, ctx } = await open("slot", "ok");
    await page.waitForSelector(tid("history-slot-link"));
    assert.match(await page.textContent(tid("history-slot-link")), /Your takes over time \(2\)/);
    await shot(page, "history-06-slot-signed-in.png");
    // TICKET-213: the seeded "Since last time" line above the link, each fact opens the earlier take's clip
    await page.waitForSelector(tid("since-line"));
    assert.match(await page.textContent(tid("since-line")), /^Since last time \(28 Oct\): score 77 to 84; the left knee cue is gone; the elbow cue is new$/);
    assert.match(await page.textContent(tid("since-best-0")), /New best: 84/);
    assert.equal(await page.isDisabled(tid("since-fact-2")), true, "a clip that is not kept is disabled");
    await page.tap(tid("since-fact-1"));
    await page.waitForFunction(() => { const v = document.querySelector('[data-testid="since-last-time"] [data-testid="history-video"]'); return v && v.readyState >= 1 && v.currentTime >= 1.4; }, null, { timeout: 15000 });
    assert.match(await page.getAttribute(`${tid("since-last-time")} ${tid("history-video")}`, "src"), /takes\/cc7cd5469055\/clip\.mp4$/);
    await shot(page, "since-01-line-seeded.png");
    ok("seeded: the since line shows and a fact opens the earlier take at that second");
    await ctx.close();
    meRequests.length = 0;
    const anon = await open("slot", "signedout");
    await anon.page.waitForSelector(tid("stand-in"));
    await anon.page.waitForTimeout(600);
    assert.equal(await anon.page.locator(`${tid("history-slot")} > *`).count(), 0, "the slot stays empty when signed out");
    assert.equal(await anon.page.locator(tid("history-slot-link")).count(), 0);
    assert.equal(await anon.page.locator(tid("since-last-time")).count(), 0, "an anonymous result shows no since line");
    assert.deepEqual(meRequests.filter((r) => r.includes("since-last-time")), []);
    assert.deepEqual(meRequests, [], "an anonymous result page makes no api/me request");
    await shot(anon.page, "history-07-slot-signed-out-empty.png");
    await anon.ctx.close();
    const page401 = await open("page", "signedout");
    await page401.page.waitForSelector(tid("history-error"));
    assert.match(await page401.page.textContent("body"), /Sign in to see your takes/);
    assert.equal(await page401.page.locator(tid("history-run")).count(), 0);
    await shot(page401.page, "history-08-page-signed-out.png");
    await page401.ctx.close();
    ok("the slot shows only for a signed-in student; signed out it stays empty");
  }
  // one-letter.md L8: the chart's heights follow the shown measure, so the C at 37 sits above the F at 50
  {
    const { page, ctx } = await open("page", "credit");
    await page.waitForSelector(tid("history-chart"));
    const cy = async (n) => Number(await page.getAttribute(tid(`history-dot-${n}`), "cy"));
    const [f, c] = [await cy(1), await cy(2)];
    assert.ok(c < f, `the C dot (cy ${c}) sits above the F dot (cy ${f})`);
    assert.equal(await page.getAttribute(tid("history-dot-2"), "data-tone"), "warn", "coloured by its letter, C");
    assert.equal(await page.textContent(tid("history-chart-axis")),
      "Oldest take on the left. The height is the % of the trainer's points, or the score out of 100 for a take without points.");
    const label = await page.getAttribute(tid("history-chart"), "aria-label");
    assert.match(label, /highest 16,239 points of 22,367/);
    assert.doesNotMatch(label, /72\.6/, "negative: the spoken label names the figures, not the height");
    await shot(page, "history-10-credit-height.png");
    await ctx.close();
    ok("the chart draws the C at 37 (72.6%) above the F at 50 and says what the height counts");
  }
  const list = await open("list", "ok");
  await list.page.waitForSelector(tid("history-mytakes-0"));
  await shot(list.page, "history-09-my-takes.png");
  await list.ctx.close();
  ok("the my takes list");
  assert.deepEqual(errors, [], `page errors: ${errors.join(" | ")}`);
  console.log(`${passed} passed`);
} finally {
  await browser.close();
  server.close();
}
