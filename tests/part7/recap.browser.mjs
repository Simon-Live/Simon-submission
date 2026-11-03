// Browser drive of "Across my movements", the monthly recap and the next-session plan at 412x915 against a fake history
// server. Every document below is SEEDED (written for this test), not a real student's takes; the model answer is a
// hand-written fixture that already passed the guard in tests/part7/test_history_cross.py.
//   PLAYWRIGHT_DIR=/path/to/node_modules node tests/part7/recap.browser.mjs [shots-dir]
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(here, "../..");
const SHOTS = path.resolve(process.argv[2] || process.env.SHOTS_DIR || path.join(ROOT, "demos/rubric/TICKET-224"));
fs.mkdirSync(SHOTS, { recursive: true });
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(ROOT, "node_modules"), "x.js"))("playwright");
const PAGE = JSON.parse(fs.readFileSync(path.join(here, "fixtures/history/page-body-squat.fixture.json"), "utf8"));
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
const json = (res, body, status = 200, headers = {}) => { res.writeHead(status, { "content-type": "application/json", ...headers }); res.end(JSON.stringify(body)); };

const SQUAT = "squat-aaaaaaaa";
const DANCE = "dance-bbbbbbbb";
const ENTRY = PAGE.entry_id;
const UNLISTED = "seed-shoulder-press"; // a seeded movement that is not in the catalog (tools/seed_history.py)
const cell = (id, name, status, takes, a, b) => ({ entry_id: id, name, status, takes, first: { take: takes[0], at_s: 2, magnitude: a }, last: { take: takes[takes.length - 1], at_s: 2.1, magnitude: b } });
const KNEE = { measure: "knee_valgus", side: "left", across: 2, entries: [cell(SQUAT, "Squat", "improved", [1, 2, 4], 20, 14), cell(DANCE, "Dance routine", "persistent", [1, 2], 20, 20)] };
const CHEST = { measure: "trunk_lean_forward", side: "center", across: 1, entries: [cell(SQUAT, "Squat", "fixed", [1], 20, 20)] };
let leftOut = [];
let prefsBodies = [];
let reportPolls = 0;
let reportRuns = 0;
const planFor = {
  [ENTRY]: { format: "simon.history.plan.v1", entry_id: ENTRY, label: "Worked out from your stored takes, without the model.", based_on: { take: 2, at: "2026-10-28T10:00:00Z" },
    spacing: "Come back tomorrow for the next session. Spreading practice over days helps it stick.",
    items: [
      { kind: "cue", text: "Work on the left knee cue: “Push the left knee out” (take 2, 2.1 s)." },
      { kind: "section", step: "s2@slow", section_key: "s2of4@0.75", text: "Practise section 2 of 4, where it showed in take 2." },
      { kind: "speed", speed: 0.75, text: "Start the slow step at 0.75 speed." },
      { kind: "takes", takes: 3, text: "Record 3 takes, then see if the cue came up again." },
    ] },
};
const entries = () => [{ entry_id: SQUAT, name: "Squat", takes: 3, rehab_takes: 1, left_out: leftOut.includes(SQUAT) }, { entry_id: DANCE, name: "Dance routine", takes: 2, rehab_takes: 0, left_out: leftOut.includes(DANCE) }];
let noOverlap = false, emptyReport = false;
const NO_OVERLAP = "Nothing has come up in two movements yet, so there is nothing to read across.";
const allDoc = () => noOverlap ? ({ entries: entries(), table: [{ ...KNEE, across: 1, entries: KNEE.entries.slice(0, 1) }, CHEST], can_read: false, blocked: NO_OVERLAP, report: "none", disclosure: "" })
  : ({ entries: entries(), table: leftOut.length ? [{ ...KNEE, across: 1, entries: KNEE.entries.filter((c) => !leftOut.includes(c.entry_id)) }, CHEST] : [KNEE, CHEST],
  can_read: leftOut.length === 0, report: "none", disclosure: "Sent to Meta's model: the measurements and cues of the takes of the movements listed here. No video is sent. Take a movement out of the list to leave it out." });
const REPORT = { format: "simon.history.all.v1", kind: "all", status: "ok", entries: entries(), observations: [
  { text: "The left knee cue came up in Squat and in Dance routine.", measure: "knee_valgus", side: "left", label: "model_opinion",
    cites: [{ entry: SQUAT, take: 1, at_s: 2 }, { entry: DANCE, take: 1, at_s: 3 }] }], next_focus: null };
const RECAP = (month) => month === "2025-02" ? { recap: { month, label: "February 2025", takes: 0, days: 0, movements: [], records: [], faults_gone: [], next_focus: null, entries: entries() }, model: null, model_state: "hidden", offer: null, disclosure: "" } : ({
  recap: { month: "2026-10", label: "October 2026", days: 4, takes: 4, movements: [{ entry_id: DANCE, name: "Dance routine" }, { entry_id: SQUAT, name: "Squat" }], rehab_takes: 1,
    records: [{ entry_id: SQUAT, name: "Squat", take: 2, score: 75 }], faults_gone: [{ entry_id: SQUAT, name: "Squat", measure: "trunk_lean_forward", side: "center", take: 2 }],
    next_focus: { measure: "knee_valgus", side: "left", movements: 2, source: "fact_table" }, entries: entries() },
  model: null, model_state: "none", offer: { month: "2026-10", label: "October 2026", takes: 4 }, disclosure: "Sent to Meta's model: the measurements and cues of the takes. No video is sent." });

function api(req, res, p, search) {
  if (p === "/api/auth/me") return json(res, { available: true, signed_in: true, user_id: "u-1", email: "a@b.co", retention: { opted_in: true } });
  const body = [];
  req.on("data", (c) => body.push(c));
  req.on("end", () => {
    const text = Buffer.concat(body).toString();
    if (p === "/api/me/history") return json(res, { entries: entries().map((e) => ({ ...e, takes: e.takes })), across: true, recap_offer: { month: "2026-10", label: "October 2026", takes: 4 } });
    if (p === "/api/me/history/all") return json(res, allDoc());
    if (p === "/api/me/history/all/prefs") { prefsBodies.push(text); leftOut = JSON.parse(text).left_out; return json(res, allDoc()); }
    if (p === "/api/me/history/all/report") {
      if (req.method === "POST") { reportRuns++; return json(res, { status: "running" }, 202, { "Retry-After": "1" }); }
      return ++reportPolls < 2 ? json(res, { status: "running" }, 202, { "Retry-After": "1" }) : json(res, emptyReport ? { ...REPORT, observations: [] } : REPORT);
    }
    if (p === "/api/me/history/recap") return json(res, RECAP(new URLSearchParams(search).get("month") || undefined));
    if (p === `/api/me/history/${ENTRY}` || p === `/api/me/history/${UNLISTED}` || p === "/api/me/history/rehab-cccccccc") return json(res, PAGE);
    if (p.endsWith("/report") && p.startsWith("/api/me/history/") && !p.includes("/all/") && !p.includes("/recap/")) return json(res, {}, 404);
    if (p === `/api/me/history/${ENTRY}/plan` || p === `/api/me/history/${UNLISTED}/plan`) return json(res, { plan: planFor[ENTRY] });
    if (p === "/api/me/history/rehab-cccccccc/plan") return json(res, { plan: null });
    return json(res, {}, 404);
  });
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://x");
  const p = decodeURIComponent(url.pathname);
  if (p.startsWith("/api/")) return api(req, res, p, url.search);
  if (p === `/catalog/api/entries/${ENTRY}`) return json(res, { id: ENTRY });   // the catalog has the squat and not the seeded press
  if (p.startsWith("/catalog/api/")) return json(res, {}, 404);
  const file = path.resolve(ROOT, "." + p);
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) return res.writeHead(404).end("not found");
  res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const tid = (id) => `[data-testid="${id}"]`;
async function open(query) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(`${base}/tests/part7/harness/recap.html?${query}`);
  return { page, ctx };
}
const shot = (page, name) => page.screenshot({ path: path.join(SHOTS, name), fullPage: true });
const BAD = /\b(pain|injur\w*|medic\w*|therap\w*|health\w*|weak\w*|tight\w*|you have a)\b/i;

try {
  {  // across my movements: the table, the list of what is read, leave one out, the read
    const { page, ctx } = await open("mode=all");
    await page.waitForSelector(tid("across-row-0"));
    assert.match(await page.textContent(tid("across-row-0")), /Came up in Squat and Dance routine\./);
    assert.equal(await page.locator(tid("across-row-1")).count(), 0, "a measure in one movement only is not an across row");
    assert.match(await page.textContent(tid("across-disclosure")), /Sent to Meta's model/);
    assert.equal(await page.locator("input[data-entry]").count(), 2);
    await shot(page, "across-01-table.png");
    ok("the table lists what came up in two movements and says what is sent");
    await page.tap(tid("across-read-1"));
    await page.waitForSelector(`${tid("across-run")}[disabled]`);
    assert.deepEqual(JSON.parse(prefsBodies.at(-1)), { left_out: [DANCE] });
    assert.equal(await page.isChecked(tid("across-read-1")), false, "the left-out movement is unticked");
    assert.equal(await page.locator(tid("across-row-0")).count(), 0, "with one movement left nothing came up across");
    await shot(page, "across-02-left-out.png");
    ok("a movement can be left out, and the read is off with one left");
    await page.tap(tid("across-read-1"));
    await page.waitForSelector(`${tid("across-run")}:not([disabled])`);
    await page.tap(tid("across-run"));
    await page.waitForSelector(`${tid("across-status")}[data-kind="waiting"]`);
    await page.waitForSelector(tid("across-observation-0"), { timeout: 15000 });
    const text = await page.textContent(tid("across-page"));
    assert.match(text, /came up in Squat and in Dance routine/);
    assert.match(text, /Squat, take 1 at 2 s; Dance routine, take 1 at 3 s/);
    assert.match(text, /model's opinion, not scored/);
    assert.doesNotMatch(text, BAD, "no health or weakness wording on the page");
    assert.equal(reportRuns, 1);
    await shot(page, "across-03-read.png");
    ok("the model read shows cited observations with the opinion label and no banned wording");
    await ctx.close();
  }
  {  // an empty cross table: the read is off with the reason; a read with nothing to cite says so
    noOverlap = true;
    const off = await open("mode=all");
    await off.page.waitForSelector(tid("across-empty"));
    await off.page.waitForSelector(`${tid("across-run")}[disabled]`);
    assert.equal((await off.page.textContent(tid("across-blocked"))).trim(), NO_OVERLAP);
    ok("with no measure in two movements the read is off and says why");
    await off.ctx.close();
    noOverlap = false; emptyReport = true; reportPolls = 0;
    const none = await open("mode=all");
    await none.page.waitForSelector(`${tid("across-run")}:not([disabled])`);
    assert.equal(await none.page.locator(tid("across-blocked")).count(), 0, "an overlap leaves no reason on the page");
    await none.page.tap(tid("across-run"));
    await none.page.waitForSelector(tid("across-nothing"), { timeout: 15000 });
    assert.match(await none.page.textContent(tid("across-nothing")), /found nothing it could cite across these movements/);
    ok("a read with no observations says so in plain words");
    emptyReport = false;
    await none.ctx.close();
  }
  {  // the monthly recap
    const { page, ctx } = await open("mode=recap&month=2026-10");
    await page.waitForSelector(tid("recap-stats"));
    assert.match(await page.textContent(tid("recap-title")), /October 2026/);
    assert.match(await page.textContent(tid("recap-stats")), /Days4Takes4Movements2/);
    assert.match(await page.textContent(tid("recap-record-0")), /Squat: new best 75/);
    assert.match(await page.textContent(tid("recap-gone-item-0")), /trunk lean forward cue was gone in take 2/);
    assert.match(await page.textContent(tid("recap-focus")), /Knee valgus, left/);
    assert.match(await page.textContent(tid("recap-rehab")), /1 more take counted, not read/);
    assert.doesNotMatch(await page.textContent(tid("recap-page")), BAD);
    await shot(page, "recap-01-month.png");
    ok("the recap shows days, takes, bests, cues gone and one focus; rehab is a count only");
    await ctx.close();
    const empty = await open("mode=recap&month=2025-02");
    await empty.page.waitForSelector(tid("recap-empty"));
    assert.equal(await empty.page.locator(tid("recap-stats")).count(), 0, "an empty month has no stats and no run button");
    assert.equal(await empty.page.locator(tid("recap-run")).count(), 0);
    ok("an empty month says so");
    await empty.ctx.close();
  }
  {  // the list: the start-of-month offer and the across link
    const { page, ctx } = await open("mode=list");
    await page.waitForSelector(tid("recap-offer"));
    assert.match(await page.textContent(tid("recap-offer")), /Your October 2026 recap/);
    assert.equal(await page.getAttribute(tid("recap-offer"), "href"), "#/me/recap?month=2026-10");
    assert.equal(await page.getAttribute(tid("across-link"), "href"), "#/me/all");
    await shot(page, "recap-02-list-offer.png");
    ok("the list offers last month's recap and across my movements");
    await ctx.close();
  }
  {  // the plan card on the history page, then Practise this section
    const { page, ctx } = await open(`mode=page&entry=${ENTRY}`);
    await page.waitForSelector(tid("plan-card"));
    const items = await page.locator(`${tid("plan-items")} li`).allTextContents();
    assert.deepEqual(items.map((t) => t.slice(0, 18)), ["Work on the left k", "Practise section 2", "Start the slow ste", "Record 3 takes, th"]);
    assert.match(await page.textContent(tid("plan-spacing")), /Come back tomorrow/);
    assert.doesNotMatch(await page.textContent(tid("plan-card")), /streak|ready|reps|weight|load/i);
    await shot(page, "plan-01-history-page.png");
    ok("the history page shows the plan with the spacing note");
    await page.tap(tid("plan-practise"));
    const stored = await page.evaluate((e) => JSON.parse(localStorage.getItem(`simon.practice.${e}`)), ENTRY);
    assert.equal(stored.on, true);
    assert.equal(stored.focus, "s2@slow");
    assert.equal(await page.evaluate(() => location.hash), `#/follow/${ENTRY}`);
    ok("Practise this section sets the practice step and opens the follow screen");
    await ctx.close();
    const slot = await open(`mode=slot&entry=${ENTRY}`);
    await slot.page.waitForSelector(`${tid("history-slot")} ${tid("plan-card")}`);
    ok("the plan card is on the result slot after a take");
    await slot.ctx.close();
    const none = await open("mode=page&entry=rehab-cccccccc");
    await none.page.waitForTimeout(500);
    assert.equal(await none.page.locator(tid("plan-card")).count(), 0);
    ok("no plan, no card");
    await none.ctx.close();
    const unlisted = await open(`mode=page&entry=${UNLISTED}`);  // the plan names a section, the catalog has no such movement
    await unlisted.page.waitForSelector(tid("plan-card"));
    assert.match(await unlisted.page.textContent(tid("plan-items")), /Practise section 2/);
    assert.equal(await unlisted.page.locator(tid("plan-practise")).count(), 0, "no button to a follow screen that would say the movement is not in the catalog");
    ok("a movement that is not in the catalog keeps its plan and loses the Practise button");
    await unlisted.ctx.close();
  }
  assert.deepEqual(errors, [], "no page errors");
  console.log(`${passed} passed`);
} finally {
  await browser.close();
  server.close();
}
