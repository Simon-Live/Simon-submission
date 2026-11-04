// Browser drive of the private-by-default controls at 390x844 (docs/prod-verify/private-default.md D2, D3, D5, W1 to
// W4; trainer-publish.md AC-TP4, AC-TP6). The page is the real app; the API is a small fake served by this file that
// answers `api/policy` as prod does (trainer_public on, MMS-TTS off, consent required) and records every POST it gets.
//   PLAYWRIGHT_DIR=/path/to/node_modules node tests/part7/private_default.browser.mjs [shots-dir]
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(here, "../..");
const WEB = path.join(ROOT, "web");
const SHOTS = path.resolve(process.argv[2] || process.env.SHOTS_DIR || path.join(ROOT, "qa/runs/private-default"));
fs.mkdirSync(SHOTS, { recursive: true });
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(ROOT, "node_modules"), "x.js"))("playwright");
const { CONSENT_VERSION } = await import("../../web/model/consent-text.js");
const { PUBLISH_TEXT } = await import("../../web/trainer-publish.js");
const { VISIBILITY_TEXT } = await import("../../web/visibility.js");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
const json = (res, body, status = 200) => { res.writeHead(status, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };
const W = 390, H = 844;
const MINE = "my-raise-1a2b", THEIRS = "their-raise-3c4d";
const ENTRIES = { [MINE]: { id: MINE, name: "My raise", category: "exercise" }, [THEIRS]: { id: THEIRS, name: "Their raise", category: "exercise" } };
const POLICY = { prod: true, switches: { face_copy: true, rehab: true, trainer_public: true, prize_boards: true, byok_ranked: true, mms_tts: false },
  phrasing_live: false, consent: { required: true, version: CONSENT_VERSION, items: ["analysis", "biometric", "processors", "people_in_frame"], header: "X-Simon-Consent" },
  age: { minimum: 13, adult: 18 }, pages: {} };
const posts = [];
let published = false;
const shares = [{ job_id: "aaaaaaaaaaaa", at: "2026-11-03T10:00:00Z", shared: false }];

async function body(req) { let raw = ""; for await (const c of req) raw += c; try { return JSON.parse(raw || "null"); } catch { return null; } }

async function api(req, res, p) {
  if (req.method === "POST") {
    const doc = await body(req);
    posts.push([p, doc]);
    if (p === `/api/me/entries/${MINE}`) { published = doc.published === true; return json(res, { entry_id: MINE, published }); }
    if (p === `/api/teacher/${MINE}/shares`) { shares[0].shared = doc.shared === true; return json(res, doc); }
    if (p === "/api/client-log") { res.writeHead(204); return res.end(); }
    return json(res, { error: "no" }, 404);
  }
  if (p === "/api/policy") return json(res, POLICY);
  if (p === "/api/auth/me") return json(res, { available: true, signed_in: true, user_id: "u1", email: "owner@example.com" });
  if (p === "/api/config") return json(res, { limits: { max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000 }, part5: {} });
  if (p === "/api/me/entries") return json(res, { entries: [{ entry_id: MINE, name: "My raise", published, may_publish: true, only_me: false }] });
  if (p === "/api/labels" || p === "/api/health") return json(res, {});
  if (p === `/api/teacher/${MINE}/shares`) return json(res, { takes: shares });
  if (p === `/api/teacher/${THEIRS}/shares`) return json(res, { takes: [] });
  const author = /^\/api\/teacher\/([^/]+)\/author$/.exec(p);
  if (author) return json(res, { attribution: { kind: "entry", author: null, mine: author[1] === MINE } });
  const entry = /^\/catalog\/api\/entries\/([^/]+)$/.exec(p);
  if (entry) return ENTRIES[entry[1]] ? json(res, ENTRIES[entry[1]]) : json(res, { error: "no" }, 404);
  if (p === "/catalog/api/entries") return json(res, { entries: Object.values(ENTRIES) });
  return json(res, { error: "no" }, 404);
}

const server = http.createServer((req, res) => {
  const p = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (p.startsWith("/api/") || p.startsWith("/catalog/")) return api(req, res, p);
  const file = path.resolve(WEB, p === "/" ? "index.html" : "." + p);
  if (!file.startsWith(WEB) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) return res.writeHead(404).end("no");
  res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const APP = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();
const errors = [];
const results = [];
const ok = (name) => { results.push(name); console.log(`ok - ${name}`); };
const tid = (id) => `[data-testid="${id}"]`;

async function open(route) {
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 2, hasTouch: true });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  await page.goto(`${APP}${route}`);
  await page.waitForSelector(tid("splash"), { state: "detached", timeout: 5000 }).catch(() => {});
  return { page, ctx };
}

/** A fresh browser on Record; answers the age question with `year` (January) and, unless blocked, agrees to every point. */
async function recordAs(year, shot) {
  const { page, ctx } = await open("/#/record");
  await page.waitForSelector(tid("age-step"));
  assert.equal(await page.locator(tid("publish-public")).count(), 0, "no box before the age answer (D2)");
  await page.selectOption(tid("age-month"), "1");
  await page.selectOption(tid("age-year"), String(year));
  await page.click(tid("age-next"));
  if (year >= 2014) {
    await page.waitForSelector(tid("age-blocked"));
  } else {
    await page.waitForSelector(tid("consent-step"));
    assert.equal(await page.locator(tid("publish-public")).count(), 0, "no box during the consent step");
    for (const key of POLICY.consent.items) await page.check(tid(`consent-item-${key}`));
    await page.click(tid("consent-agree"));
    await page.waitForSelector(tid("consent-done"));
  }
  await page.screenshot({ path: path.join(SHOTS, shot), fullPage: true });
  return { page, ctx };
}

try {
  {
    const { page, ctx } = await recordAs(2011, "record-390-minor.png");
    assert.equal(await page.textContent(tid("publish-minor")), PUBLISH_TEXT.minor);
    assert.equal(await page.locator(tid("publish-public")).count(), 0);
    await ctx.close();
    ok("13 to 17 at first visit: no box before or after the age answer, the private line instead");
  }
  {
    const { page, ctx } = await recordAs(2016, "record-390-under13.png");
    assert.equal(await page.locator(tid("publish-public")).count(), 0);
    assert.equal(await page.locator(tid("publish-minor")).count(), 0);
    await ctx.close();
    ok("under 13: blocked, no box and no line");
  }
  {
    const { page, ctx } = await recordAs(1990, "record-390-adult.png");
    const box = page.getByRole("checkbox", { name: PUBLISH_TEXT.label, exact: true });
    assert.equal(await box.count(), 1, "the accessible name is the label alone (W4)");
    assert.equal(await box.isChecked(), true, "public by default in prod: the person sees it ticked");
    const statement = page.getByRole("checkbox", { name: PUBLISH_TEXT.statementLabel, exact: true });
    assert.equal(await statement.isChecked(), false, "negative: the second tick is never made for them (PM-B3)");
    const described = await box.evaluate((el) => document.getElementById(el.getAttribute("aria-describedby"))?.textContent);
    assert.equal(described, PUBLISH_TEXT.hint, "the hint is the box's description (W4)");
    await box.focus();
    await page.keyboard.press("Space");
    assert.equal(await box.isChecked(), false);
    await page.keyboard.press("Space");
    assert.equal(await box.isChecked(), true);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth) <= W, "no sideways scroll at 390 px");
    await page.screenshot({ path: path.join(SHOTS, "record-390-adult-box.png") });
    await ctx.close();
    ok("adult: a ticked box with a short name, the second tick left unticked, the hint as its description, Space toggles it, fits 390 px");
  }
  {
    const { page, ctx } = await open(`/#/watch/${MINE}`);
    await page.waitForSelector(tid("visibility-line"));
    assert.equal(await page.textContent(tid("visibility-line")), VISIBILITY_TEXT.private);
    const sw = page.getByRole("checkbox", { name: PUBLISH_TEXT.label, exact: true });
    assert.equal(await sw.isChecked(), false);
    await sw.click();
    assert.equal(await page.textContent(tid("visibility-status")), PUBLISH_TEXT.statementNeeded, "negative: not public without the second tick");
    assert.equal(await sw.isChecked(), false);
    assert.equal(posts.filter(([p]) => p.startsWith("/api/me/entries")).length, 0, "negative: nothing was sent");
    await page.check(tid("visibility-statement"));
    await sw.check();
    await page.waitForFunction((t) => document.querySelector('[data-testid="visibility-line"]').textContent === t, VISIBILITY_TEXT.public);
    assert.deepEqual(posts.filter(([p]) => p.startsWith("/api/me/entries")).at(-1), [`/api/me/entries/${MINE}`, { published: true, nobody_under_18: true }]);
    await page.screenshot({ path: path.join(SHOTS, "watch-390-owner-public.png"), fullPage: true });
    await sw.uncheck();
    await page.waitForFunction((t) => document.querySelector('[data-testid="visibility-line"]').textContent === t, VISIBILITY_TEXT.private);
    assert.deepEqual(posts.filter(([p]) => p.startsWith("/api/me/entries")).at(-1), [`/api/me/entries/${MINE}`, { published: false }]);
    const share = page.locator(tid("share-take"));
    await share.waitFor();
    assert.equal(await share.isChecked(), false, "a take is not shared until its owner ticks it (D3)");
    await share.check();
    await page.waitForFunction(() => document.querySelector('[data-testid="share-take-status"]').textContent === "Saved.");
    assert.deepEqual(posts.at(-1), [`/api/teacher/${MINE}/shares`, { job_id: "aaaaaaaaaaaa", shared: true }]);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth) <= W, "no sideways scroll at 390 px");
    await page.screenshot({ path: path.join(SHOTS, "watch-390-owner-private.png"), fullPage: true });
    await ctx.close();
    ok("owner's Watch: the private line, the switch both ways (two POSTs), the per-take share box");
  }
  {
    const { page, ctx } = await open(`/#/watch/${THEIRS}`);
    await page.waitForSelector("h1");
    await page.waitForTimeout(500);
    assert.equal(await page.locator(tid("visibility-line")).count(), 0, "negative: no line on someone else's movement");
    assert.equal(await page.getByRole("checkbox", { name: PUBLISH_TEXT.label }).count(), 0);
    assert.equal(await page.locator(tid("share-take")).count(), 0);
    await ctx.close();
    ok("someone else's movement: no visibility line, no switch, no share box");
  }
  {
    const { page, ctx } = await open("/#/");
    await page.waitForSelector(tid("nav-record"));
    assert.equal(await page.locator(tid("kind-rehab")).count(), 0, "negative: the header has no Rehab switch");
    await page.waitForSelector('[data-testid="result-count"]');
    await ctx.close();
    ok("the prod rehab switch on: the header has no kind switch and the library loads");
  }
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ passed: results.length, shots: SHOTS }));
} finally {
  await browser.close();
  server.close();
}
