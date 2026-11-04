// Browser drive of the class table and the class handout at 412x915 and 360x780 (TICKET-273 AC-3, AC-4;
// docs/specs/class-table.md, docs/specs/handout.md). The page is the real app; the API is a small fake served by this
// file. The class answer is SEEDED (written for this test in the shape of part7/class_table.py, `seeded: true`), not a
// real class, and is the owner's view (per-follower rows); the second movement answers the public view (no rows,
// `seeded: false`) for the negative checks.
//   PLAYWRIGHT_DIR=/path/to/node_modules node tests/part7/teacher_class.browser.mjs [shots-dir]
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { decodeMatrix, matrixFromPath } from "./qr-decode.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(here, "../..");
const WEB = path.join(ROOT, "web");
const SHOTS = path.resolve(process.argv[2] || process.env.SHOTS_DIR || path.join(ROOT, "demos/rubric/TICKET-273"));
fs.mkdirSync(SHOTS, { recursive: true });
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(ROOT, "node_modules"), "x.js"))("playwright");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
const json = (res, body, status = 200) => { res.writeHead(status, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };

const SEEDED = "body-squat-19b06562";
const REAL = "lateral-raise";
const HIDDEN = "only-me-move";
const ENTRIES = { [SEEDED]: { id: SEEDED, name: "Body squat", category: "exercise" }, [REAL]: { id: REAL, name: "Lateral raise", category: "exercise" }, [HIDDEN]: { id: HIDDEN, name: "Hidden", category: "exercise" } };
const TAKES = [58, 61, 69, 72, 70, 81].map((score, i) => ({ n: i + 1, at: `2026-11-0${1 + (i % 2)}T1${i}:00:00Z`, score, grade: score >= 80 ? "B" : score >= 65 ? "C" : "D", top_cues: ["Seeded cue for knee valgus"] }));
const TABLE = { follower_count: 3, takes_7d: 6, window_days: 7, top_cue: { text: "Seeded cue for knee valgus", followers: 3 },
  followers: [{ n: 1, takes: 3, first: 58, latest: 81, delta: 23 }, { n: 2, takes: 2, first: 61, latest: 70, delta: 9 }] };
// the seeded movement answers as its owner sees it (rows, mine); the other answers the public shape (no followers key)
const teacherDoc = (entry, owner) => {
  const { followers, ...publicTable } = TABLE;
  return { entry, takes: TAKES, cue_counts: [{ text: "Seeded cue for knee valgus", count: 5 }],
    class_table: owner ? { ...TABLE, seeded: true } : { ...publicTable, seeded: false }, attribution: { kind: "entry", author: null, mine: owner && followers.length > 0 } };
};

function api(req, res, p) {
  if (p === "/api/auth/me") return json(res, { available: true, signed_in: false });
  if (p === "/api/config") return json(res, { limits: { max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000 }, part5: {} });
  if (p === "/api/client-log") { res.writeHead(204); return res.end(); }
  if (p === "/api/labels" || p === "/api/health") return json(res, {});
  const teacher = /^\/api\/teacher\/([^/]+)(\/author)?$/.exec(p);
  if (teacher) {
    if (!ENTRIES[teacher[1]] || teacher[1] === HIDDEN) return json(res, { message: "This movement is not in the catalog." }, 404);
    return teacher[2] ? json(res, { attribution: { kind: "entry", author: null } }) : json(res, teacherDoc(teacher[1], teacher[1] === SEEDED));
  }
  const entry = /^\/catalog\/api\/entries\/([^/]+)$/.exec(p);
  if (entry) return ENTRIES[entry[1]] ? json(res, ENTRIES[entry[1]]) : json(res, { error: "no" }, 404);
  return json(res, {}, 404);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://x");
  const p = decodeURIComponent(url.pathname);
  if (p.startsWith("/api/") || p.startsWith("/catalog/api/")) return api(req, res, p);
  const file = path.resolve(WEB, p === "/" ? "index.html" : "." + p);
  if (!file.startsWith(WEB) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) return res.writeHead(404).end("no");
  res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const APP = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch();
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const tid = (id) => `[data-testid="${id}"]`;

async function open(route, width, height) {
  const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 2, hasTouch: true });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error" && !(route.includes(HIDDEN) && /404/.test(m.text())) && !/\/api\/(policy|version|programmes)/.test(m.location().url)) errors.push(`${route}: ${m.text()}`); });
  await page.goto(`${APP}${route}`);
  await page.waitForSelector(tid("splash"), { state: "detached", timeout: 5000 }).catch(() => {}); // the first-visit splash leaves on its own
  return { page, ctx };
}

/** Fails when anything on the page is wider than the viewport (a sideways scroll on a phone). */
async function fits(page, width) {
  const wide = await page.evaluate(() => document.documentElement.scrollWidth);
  assert.ok(wide <= width, `the page is ${wide}px wide at ${width}px`);
  const over = await page.evaluate((w) => [...document.querySelectorAll(".th *, .ho *")].filter((el) => el.getBoundingClientRect().right > w + 0.5).map((el) => el.className || el.tagName), width);
  assert.deepEqual(over, [], `elements past the right edge at ${width}px`);
}

try {
  for (const [width, height] of [[412, 915], [360, 780]]) {
    const { page, ctx } = await open(`/#/teacher/${SEEDED}`, width, height);
    await page.waitForSelector(tid("class-table"));
    assert.equal(await page.textContent(tid("class-followers")), "3followers");
    assert.equal(await page.textContent(tid("class-recent")), "6takes in the last 7 days");
    assert.equal(await page.textContent(tid("class-top-cue")), "Seeded cue for knee valgusfor 3 of 3 followers");
    assert.deepEqual(await page.locator(`${tid("class-changes")} li`).allTextContents(), ["Follower 1+2358 to 81 over 3 takes", "Follower 2+961 to 70 over 2 takes"]);
    assert.equal(await page.textContent(tid("class-owner-note")), "Only you see each follower's scores.");
    assert.match(await page.textContent(tid("teacher-seeded")), /^Seeded demo data These takes were made for the demo, not by real followers\.$/);
    assert.ok(await page.isVisible(tid("class-seeded")));
    assert.ok(await page.isVisible(tid("teacher-handout")));
    assert.doesNotMatch(await page.textContent(tid("class-table")), /@|user|job/i, "negative: no email, account or job in the table");
    await fits(page, width);
    await page.screenshot({ path: path.join(SHOTS, `class-table-${width}.png`), fullPage: true });
    await ctx.close();
    ok(`class table at ${width}px: facts, top cue, changes and the seeded label, no sideways scroll`);
  }
  // negative: the same numbers with seeded false carry no seeded label
  {
    const { page, ctx } = await open(`/#/teacher/${REAL}`, 412, 915);
    await page.waitForSelector(tid("class-table"));
    assert.equal(await page.locator(tid("teacher-seeded")).count(), 0);
    assert.equal(await page.locator(tid("class-seeded")).count(), 0);
    assert.equal(await page.textContent(tid("class-followers")), "3followers");
    for (const id of ["class-follower-block", "class-changes", "class-owner-note"]) assert.equal(await page.locator(tid(id)).count(), 0, id);
    assert.doesNotMatch(await page.textContent(tid("class-table")), /From first take to latest|Follower 1/);
    await fits(page, 412);
    await page.screenshot({ path: path.join(SHOTS, "class-table-public-412.png"), fullPage: true });
    await ctx.close();
    ok("class table, public view: class facts only, no per-follower block, no seeded label on data that is not seeded");
  }
  // AC-4: the handout from the teacher page; the QR reads back to the link shown, which is the live follow link
  for (const [width, height] of [[412, 915], [360, 780]]) {
    const { page, ctx } = await open(`/#/teacher/${SEEDED}`, width, height);
    await page.click(tid("teacher-handout"));
    await page.waitForSelector(tid("handout-qr"));
    assert.equal(page.url(), `${APP}/#/teacher/${SEEDED}/handout`);
    const link = `${APP}/#/follow/${SEEDED}`;
    assert.equal(await page.textContent(tid("handout-link")), link);
    assert.equal(await page.textContent(tid("handout-title")), "Follow Body squat with Simon");
    const d = await page.getAttribute(tid("handout-qr-path"), "d");
    const side = Number((await page.getAttribute(tid("handout-qr"), "viewBox")).split(" ")[2]);
    assert.equal(decodeMatrix(matrixFromPath(d, side), 4).text, link);
    const paper = await page.evaluate(() => [getComputedStyle(document.querySelector(".ho-qr-paper")).fill, getComputedStyle(document.querySelector(".ho-qr-ink")).fill]);
    assert.deepEqual(paper, ["rgb(255, 255, 255)", "rgb(0, 0, 0)"], "dark modules on white");
    await fits(page, width);
    await page.screenshot({ path: path.join(SHOTS, `handout-${width}.png`), fullPage: true });
    if (width === 412) {
      await page.locator(tid("handout-qr")).screenshot({ path: path.join(SHOTS, "handout-qr.png") });
      await page.emulateMedia({ media: "print" });
      assert.equal(await page.isVisible("header.bar"), false, "print: the app bar is hidden");
      assert.equal(await page.isVisible(tid("handout-print")), false, "print: the print button is hidden");
      assert.ok(await page.isVisible(tid("handout-qr")));
      const ground = await page.evaluate(() => [getComputedStyle(document.body).backgroundImage, getComputedStyle(document.body, "::before").display]);
      assert.deepEqual(ground, ["none", "none"], "print: no page texture behind the sheet");
      await page.screenshot({ path: path.join(SHOTS, "handout-print.png"), fullPage: true });
      await page.emulateMedia({ media: "screen" });
      await page.evaluate(() => { window.__printed = 0; window.print = () => { window.__printed += 1; }; });
      await page.click(tid("handout-print"));
      assert.equal(await page.evaluate(() => window.__printed), 1);
    }
    await page.click(tid("handout-back"));
    await page.waitForSelector(tid("class-table"));
    await ctx.close();
    ok(`handout at ${width}px: QR reads back to ${link}, prints without the app chrome`);
  }
  // negative: an entry its owner keeps to "only me" (the author route answers 404) gets no handout
  {
    const { page, ctx } = await open(`/#/teacher/${HIDDEN}/handout`, 412, 915);
    await page.waitForSelector(tid("handout-error"));
    assert.equal(await page.locator(tid("handout-qr")).count(), 0);
    assert.match(await page.textContent(tid("handout-error")), /not found/);
    await ctx.close();
    ok("handout: a hidden movement shows not found and no QR code");
  }
  assert.deepEqual(errors, [], `console or page errors: ${errors.join(" | ")}`);
  console.log(`${passed} passed`);
} finally {
  await browser.close();
  server.close();
}
